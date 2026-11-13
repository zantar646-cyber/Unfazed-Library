from __future__ import annotations

import asyncio
import os
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from loguru import logger

from bot.config.settings import settings
from bot.database.service import db
from bot.handlers import admin, ai_features, alerts, book, bookclub, inline_query, reader, shelf, user
from bot.middlewares.auth import RegistrationMiddleware
from bot.middlewares.logging import LoggingMiddleware
from bot.middlewares.rate_limit import RateLimitMiddleware
from bot.services.ai import ai
from bot.services.api import api
from bot.services.cache import cache
from bot.sources.annas_archive import annas_archive
from bot.utils.convert_storage import cleanup_expired_convert_keys, resolve_convert_key
from bot.utils.converter import cleanup_old_converter_files, get_converter_file_path


def setup_logging() -> None:
    logger.remove()
    # Windows consoles often default to cp1252, which cannot encode the emoji and
    # box-drawing characters used in our log messages. Force UTF-8 on stdout.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )
    logger.add(
        sys.stdout,
        format=log_format,
        level=settings.log_level,
        colorize=True,
    )
    logger.add(
        "logs/bot_{time:YYYY-MM-DD}.log",
        format=log_format,
        level="DEBUG",
        rotation="1 day",
        retention="30 days",
        compression="gz",
    )
    logger.info(f"Logging configured, level={settings.log_level}")


async def health_handler(request):
    return web.Response(text="OK", status=200)


async def converter_file_handler(request):
    token = request.match_info.get("token", "")
    filename = request.match_info.get("filename", "")
    file_path = get_converter_file_path(token, filename)
    if file_path:
        return web.FileResponse(file_path)
    return web.Response(text="File not found", status=404)


async def resolve_convert_handler(request):
    key = request.match_info.get("key", "")
    data = resolve_convert_key(key)
    if data:
        return web.json_response(data)
    return web.json_response({"error": "Key not found or expired"}, status=404)


async def start_health_server():
    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/converter/{token}/{filename}", converter_file_handler)
    app.router.add_get("/resolve-convert/{key}", resolve_convert_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health check server running on port {port}")


async def periodic_mirror_check():
    while True:
        await asyncio.sleep(settings.mirror_recheck_interval)
        logger.info("Running periodic mirror health check...")
        try:
            await api.mirror_manager.check_all_mirrors()
        except Exception as e:
            logger.warning(f"Periodic mirror check failed: {e}")


async def periodic_converter_cleanup():
    while True:
        await asyncio.sleep(1800)  # every 30 minutes
        try:
            cleanup_old_converter_files()
        except Exception as e:
            logger.warning(f"Converter cache cleanup failed: {e}")
        try:
            cleanup_expired_convert_keys()
        except Exception as e:
            logger.warning(f"Convert key cleanup failed: {e}")


async def on_startup(bot: Bot) -> None:
    logger.info("Starting Unfazed Library Bot...")

    await start_health_server()

    await cache.initialize()
    await api.initialize()
    await db.create_tables()
    await db.seed_categories()

    if settings.openai_api_key:
        await ai.initialize()
        logger.info(f"AI features initialized (available={ai.available})")
    else:
        logger.info("AI features disabled - no OPENAI_API_KEY configured")

    from bot.utils.browser_downloader import init_browser
    await init_browser()

    asyncio.create_task(periodic_mirror_check())
    asyncio.create_task(periodic_converter_cleanup())

    from bot.handlers.alerts import run_alert_checker
    asyncio.create_task(run_alert_checker(bot))

    from bot.services.dashboard import start_web_dashboard
    asyncio.create_task(start_web_dashboard(port=int(os.environ.get("DASHBOARD_PORT", 8085))))

    bot_info = await bot.get_me()
    logger.info(f"Bot started: @{bot_info.username} (ID: {bot_info.id})")

    # Startup diagnostics
    logger.info("=== Startup Diagnostics ===")
    status = await api.get_status()
    mirror = status.get("mirror", {})
    logger.info(f"  Active mirror: {mirror.get('active_mirror', 'N/A')}")
    for m in mirror.get("mirrors", []):
        icon = "🟢" if m.get("healthy") else "🔴"
        active = " [ACTIVE]" if m.get("active") else ""
        caps = m.get("capabilities", {})
        cap_str = ", ".join(f"{k}={v}" for k, v in caps.items() if v)
        logger.info(f"  {icon} {m['url']}{active} | capabilities: {cap_str} | failures: {m.get('consecutive_failures', 0)}")
    logger.info(f"  Authentication: {'✅' if status.get('authenticated') else '❌'}")
    cache_info = status.get("cache", {})
    logger.info(f"  Cache: {'✅' if cache_info.get('enabled') else '❌'}")
    logger.info("=== End Diagnostics ===")


async def on_shutdown(bot: Bot) -> None:
    logger.info("Shutting down Unfazed Library Bot...")
    await api.close()
    await annas_archive.close()
    await cache.close()
    await db.engine.dispose()
    from bot.utils.browser_downloader import close_browser
    await close_browser()
    logger.info("Shutdown complete")


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    routers = [
        user.router,
        book.router,
        shelf.router,
        alerts.router,
        reader.router,
        bookclub.router,
        inline_query.router,
        ai_features.router,
        admin.router,
    ]
    for r in routers:
        r._parent_router = None
        dp.include_router(r)

    dp.message.middleware(LoggingMiddleware())
    dp.callback_query.middleware(LoggingMiddleware())
    dp.message.middleware(RegistrationMiddleware())
    dp.callback_query.middleware(RegistrationMiddleware())
    dp.message.middleware(RateLimitMiddleware())
    dp.callback_query.middleware(RateLimitMiddleware())

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    return dp


async def main() -> None:
    setup_logging()

    if not settings.bot_token:
        logger.error("BOT_TOKEN is not set. Check your .env file.")
        return

    if not settings.api_base_url:
        logger.error("API_BASE_URL is not set. Check your .env file.")
        return

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = create_dispatcher()

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except TelegramUnauthorizedError:
        logger.error(
            "Telegram rejected BOT_TOKEN (401 Unauthorized). "
            "The token is invalid or was revoked - generate a new one via "
            "@BotFather (/mybots -> API Token -> Revoke current token) "
            "and update BOT_TOKEN in your .env file."
        )
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
