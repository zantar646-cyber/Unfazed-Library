"""api/index.py — Vercel Serverless Entrypoint for Digital Library Telegram Bot."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update
from loguru import logger

from bot.config.settings import settings
from bot.database.service import db
from bot.services.api import api
from bot.services.cache import cache
from main import create_dispatcher

# Singleton instances across warm serverless lambda invocations
_bot: Optional[Bot] = None
_dp: Optional[Dispatcher] = None
_initialized: bool = False
_init_lock = asyncio.Lock()


async def get_bot_and_dispatcher() -> tuple[Bot, Dispatcher]:
    global _bot, _dp, _initialized
    if _initialized and _bot and _dp:
        return _bot, _dp

    async with _init_lock:
        if _initialized and _bot and _dp:
            return _bot, _dp

        logger.info("Initializing Vercel serverless bot services...")
        await cache.initialize()
        await api.initialize()
        await db.create_tables()
        # SQLite in /tmp starts empty on every cold serverless instance.
        # Seed the default categories so the Categories menu is never empty.
        await db.seed_categories()

        _bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        _dp = create_dispatcher()
        _initialized = True
        logger.info("Vercel serverless bot initialized successfully")
        return _bot, _dp


async def handle_webhook_update(body_bytes: bytes, secret_token_header: Optional[str] = None) -> tuple[int, Dict[str, Any]]:
    """Process incoming Telegram update."""
    if settings.webhook_secret and secret_token_header != settings.webhook_secret:
        logger.warning("Webhook rejected: secret token mismatch")
        return 403, {"error": "Unauthorized: invalid secret token"}

    try:
        data = json.loads(body_bytes.decode("utf-8"))
    except Exception as e:
        logger.error(f"Malformed JSON payload: {e}")
        return 400, {"error": "Invalid JSON"}

    bot, dp = await get_bot_and_dispatcher()

    try:
        update = Update.model_validate(data, context={"bot": bot})
        # Process update through Aiogram middleware & routers
        await dp.feed_update(bot, update)
        return 200, {"ok": True}
    except Exception as e:
        logger.exception(f"Error handling Telegram update: {e}")
        return 200, {"ok": False, "error": str(e)}


async def handle_get_request(path: str, query_params: Dict[str, list[str]], host: str) -> tuple[int, Dict[str, Any]]:
    """Handle administrative and monitoring GET endpoints."""
    parsed_path = path.rstrip("/").lower()
    if parsed_path.startswith("/api"):
        parsed_path = parsed_path[4:]  # Normalize /api/x -> /x

    # 0. Source reachability diagnostics (no bot init; protected by token)
    if parsed_path in ("/sources_check", "/api/sources_check"):
        expected = settings.diag_token or settings.webhook_secret
        supplied = (query_params.get("token") or [""])[0]
        if not expected:
            return 403, {
                "error": "Diagnostics disabled. Set DIAG_TOKEN or WEBHOOK_SECRET, then call with ?token=..."
            }
        if supplied != expected:
            return 403, {"error": "Unauthorized"}

        from bot.services.diagnostics import check_sources

        try:
            return 200, await asyncio.wait_for(check_sources(), timeout=25)
        except asyncio.TimeoutError:
            return 504, {"error": "Source check timed out"}
        except Exception as e:
            logger.exception(f"Source check failed: {e}")
            return 500, {"error": str(e)}

    bot, _ = await get_bot_and_dispatcher()

    # 1. Health & status
    if parsed_path in ("", "/health", "/index", "/index.py"):
        bot_info = {}
        try:
            me = await bot.get_me()
            bot_info = {"id": me.id, "username": me.username, "first_name": me.first_name}
        except Exception as e:
            bot_info = {"error": str(e)}

        db_name = "postgresql (supabase)" if (not settings.use_sqlite and ("supabase" in settings.database_url or settings.supabase_url)) else ("postgresql" if not settings.use_sqlite else ("sqlite (tmp)" if settings.is_vercel else "sqlite"))

        from bot.utils.storage import storage_chat_id

        bridge: Dict[str, Any] = {
            "storage_channel_set": storage_chat_id() is not None,
            "deeplink_secret_set": bool(settings.deeplink_secret),
            "converter_bot_username": settings.converter_bot_username or None,
        }
        try:
            bridge["books_with_storage_message"] = (
                await db.count_books_with_storage_message()
            )
        except Exception as e:
            bridge["books_with_storage_message"] = f"error: {type(e).__name__}"

        return 200, {
            "status": "online",
            "platform": "Vercel Serverless",
            "commit": (os.getenv("VERCEL_GIT_COMMIT_SHA") or "local")[:7],
            "bot": bot_info,
            "database": db_name,
            "bridge": bridge,
            "active_engine": "bot (full architecture)",
            "endpoints": {
                "webhook": "/api/webhook",
                "set_webhook": "/api/set_webhook",
                "webhook_info": "/api/webhook_info",
                "stats": "/api/stats",
                "sources_check": "/api/sources_check?token=...",
                "cron_alerts": "/api/cron/alerts",
            },
        }

    # 2. Webhook status inspector
    if parsed_path in ("/webhook_info", "/api/webhook_info"):
        try:
            info = await bot.get_webhook_info()
            # aiogram exposes dates as ``datetime`` objects, which json.dumps
            # cannot serialize; dump them to JSON-native values first.
            data = info.model_dump(mode="json")
            return 200, {
                "url": data.get("url"),
                "has_custom_certificate": data.get("has_custom_certificate"),
                "pending_update_count": data.get("pending_update_count"),
                "last_error_date": data.get("last_error_date"),
                "last_error_message": data.get("last_error_message"),
                "last_synchronization_error_date": data.get("last_synchronization_error_date"),
                "max_connections": data.get("max_connections"),
                "ip_address": data.get("ip_address"),
            }
        except Exception as e:
            logger.exception(f"Failed to read webhook info: {e}")
            return 500, {"error": str(e)}

    # 3. Webhook auto-setup
    if parsed_path in ("/set_webhook", "/api/set_webhook"):
        # Auto-compute webhook URL from host header if not provided
        target_url = query_params.get("url", [None])[0] or settings.webhook_url
        if not target_url and host:
            protocol = "https"
            target_url = f"{protocol}://{host}/api/webhook"

        if not target_url:
            return 400, {
                "error": "Missing webhook URL. Pass ?url=https://your-domain.vercel.app/api/webhook or set WEBHOOK_URL environment variable."
            }

        try:
            await bot.set_webhook(
                url=target_url,
                secret_token=settings.webhook_secret or None,
                drop_pending_updates=True,
            )
            info = await bot.get_webhook_info()
            return 200, {
                "success": True,
                "message": f"Webhook set to {target_url}",
                "webhook_info": {
                    "url": info.url,
                    "pending_update_count": info.pending_update_count,
                },
            }
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")
            return 500, {"error": str(e)}

    # 4. Telemetry stats
    if parsed_path in ("/stats", "/api/stats"):
        try:
            stats = await db.get_dashboard_stats()
            new_today = await db.get_new_users_today()
            return 200, {"stats": stats, "new_users_today": new_today}
        except Exception as e:
            return 500, {"error": str(e)}

    # 5. Vercel Cron: Check book alerts
    if parsed_path in ("/cron/alerts", "/api/cron/alerts"):
        try:
            from bot.handlers.alerts import _check_alerts_once
            notified_count = await _check_alerts_once(bot)
            return 200, {"status": "ok", "alerts_checked": True, "notified": notified_count}
        except Exception as e:
            return 500, {"error": str(e)}

    return 404, {"error": f"Endpoint '{path}' not found"}


# ─── Dual Interface: ASGI for modern runtimes, BaseHTTPRequestHandler for legacy ───

async def app(scope: Dict[str, Any], receive: Any, send: Any) -> None:
    """ASGI application interface for Vercel Python runtime."""
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await get_bot_and_dispatcher()
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    if scope["type"] != "http":
        return

    method = scope.get("method", "GET").upper()
    path = scope.get("path", "/")
    headers = dict(scope.get("headers", []))
    host = headers.get(b"host", b"").decode("utf-8")
    secret_token = headers.get(b"x-telegram-bot-api-secret-token", b"").decode("utf-8") or None

    query_string = scope.get("query_string", b"").decode("utf-8")
    query_params = parse_qs(query_string)

    if method == "POST":
        body_parts = []
        more_body = True
        while more_body:
            message = await receive()
            body_parts.append(message.get("body", b""))
            more_body = message.get("more_body", False)
        body = b"".join(body_parts)

        status_code, response_data = await handle_webhook_update(body, secret_token)
    else:
        status_code, response_data = await handle_get_request(path, query_params, host)

    response_bytes = json.dumps(response_data, indent=2, default=str).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status_code,
        "headers": [
            [b"content-type", b"application/json"],
            [b"content-length", str(len(response_bytes)).encode("utf-8")],
            [b"cache-control", b"no-cache"],
        ],
    })
    await send({
        "type": "http.response.body",
        "body": response_bytes,
    })


class handler(BaseHTTPRequestHandler):
    """Standard BaseHTTPRequestHandler fallback for Vercel."""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query_params = parse_qs(parsed.query)
        host = self.headers.get("Host", "")

        status_code, data = asyncio.run(handle_get_request(parsed.path, query_params, host))
        response_bytes = json.dumps(data, indent=2, default=str).encode("utf-8")

        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""
        secret_token = self.headers.get("X-Telegram-Bot-Api-Secret-Token")

        status_code, data = asyncio.run(handle_webhook_update(body, secret_token))
        response_bytes = json.dumps(data, indent=2, default=str).encode("utf-8")

        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)
