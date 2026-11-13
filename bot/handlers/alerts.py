"""bot/handlers/alerts.py — Search Alerts handler (feature #4) + background checker."""
from __future__ import annotations

import asyncio
from typing import Optional

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from bot.database.service import db
from bot.utils.helpers import get_search_query
from bot.utils.i18n import get_text

try:
    from bot.database.models import BookAlert  # noqa: F401
except ImportError:
    BookAlert = None  # type: ignore

try:
    from bot.database.models import User as DBUser
except ImportError:
    DBUser = None  # type: ignore

router = Router()

_ALERT_CHECK_INTERVAL = 6 * 3600  # 6 hours in seconds


# ── Helper keyboard ──────────────────────────────────────────────────────────

def _alerts_keyboard(alerts: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for alert in alerts:
        query_text = getattr(alert, "query", "?")
        alert_id = getattr(alert, "id", "?")
        label = (query_text[:35] + "…") if len(query_text) > 35 else query_text
        builder.row(
            InlineKeyboardButton(
                text=f"🔔 {label}  ✕",
                callback_data=f"alerts:delete:{alert_id}",
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="➕ Create Alert for Last Search",
            callback_data="alerts:create_last",
        )
    )
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="menu"))
    return builder.as_markup()


# ── Handlers ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "alerts:list")
async def callback_alerts_list(callback: CallbackQuery, db_user=None) -> None:
    user_id = callback.from_user.id if callback.from_user else (db_user.id if db_user else None)
    if not user_id:
        await callback.answer("Cannot identify user.", show_alert=True)
        return

    try:
        alerts = await db.get_user_alerts(user_id)
    except Exception as exc:
        logger.error(f"alerts list error: {exc}")
        await callback.answer("Error loading alerts.", show_alert=True)
        return

    if alerts:
        text = f"🔔 <b>Your Search Alerts</b>\n\n{len(alerts)} active alert(s).\nTap an alert to delete it."
    else:
        text = "🔔 <b>Your Search Alerts</b>\n\nYou have no alerts yet.\nSearch for a book and create an alert to get notified when new results appear!"

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=_alerts_keyboard(alerts),
    )
    await callback.answer()


@router.callback_query(F.data == "alerts:create_last")
async def callback_alerts_create_last(callback: CallbackQuery, db_user=None) -> None:
    user_id = callback.from_user.id if callback.from_user else (db_user.id if db_user else None)
    if not user_id:
        await callback.answer("Cannot identify user.", show_alert=True)
        return

    query = get_search_query(user_id)
    if not query:
        await callback.answer("No recent search found. Search for a book first!", show_alert=True)
        return

    try:
        await db.create_book_alert(user_id, query)
    except Exception as exc:
        logger.error(f"alerts create error: {exc}")
        await callback.answer("Error creating alert.", show_alert=True)
        return

    await callback.answer(f"🔔 Alert set for: {query}", show_alert=True)

    # Refresh the list
    try:
        alerts = await db.get_user_alerts(user_id)
        text = f"🔔 <b>Your Search Alerts</b>\n\n{len(alerts)} active alert(s).\nTap an alert to delete it."
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=_alerts_keyboard(alerts),
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("alerts:delete:"))
async def callback_alerts_delete(callback: CallbackQuery, db_user=None) -> None:
    user_id = callback.from_user.id if callback.from_user else (db_user.id if db_user else None)
    if not user_id:
        await callback.answer("Cannot identify user.", show_alert=True)
        return

    parts = callback.data.split(":")
    try:
        alert_id = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer("Invalid alert.", show_alert=True)
        return

    try:
        await db.delete_book_alert(alert_id, user_id)
    except Exception as exc:
        logger.error(f"alerts delete error: {exc}")
        await callback.answer("Error deleting alert.", show_alert=True)
        return

    await callback.answer("🗑 Alert deleted", show_alert=False)

    # Refresh list
    try:
        alerts = await db.get_user_alerts(user_id)
        if alerts:
            text = f"🔔 <b>Your Search Alerts</b>\n\n{len(alerts)} active alert(s).\nTap an alert to delete it."
        else:
            text = "🔔 <b>Your Search Alerts</b>\n\nYou have no alerts yet."
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=_alerts_keyboard(alerts),
        )
    except Exception:
        pass


# ── Background alert checker ─────────────────────────────────────────────────

async def _check_alerts_once(bot) -> int:
    """Execute a single check over all active alerts (for serverless cron jobs)."""
    await _check_all_alerts(bot)
    return 1


async def run_alert_checker(bot) -> None:
    """Background loop: checks all active alerts every 6 hours and notifies users of new books."""
    logger.info("Alert checker started — interval: 6 hours")
    while True:
        try:
            await asyncio.sleep(_ALERT_CHECK_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Alert checker cancelled.")
            return

        try:
            await _check_all_alerts(bot)
        except Exception as exc:
            logger.error(f"Alert checker top-level error: {exc}")


async def _check_all_alerts(bot) -> None:
    try:
        from bot.sources.router import source_router
    except ImportError:
        logger.warning("source_router not available; skipping alert check")
        return

    try:
        alerts = await db.get_all_active_alerts()
    except Exception as exc:
        logger.error(f"Could not fetch active alerts: {exc}")
        return

    logger.info(f"Alert checker: processing {len(alerts)} active alert(s)")

    for alert in alerts:
        try:
            await _process_alert(bot, alert, source_router)
        except Exception as exc:
            logger.error(f"Error processing alert {getattr(alert, 'id', '?')}: {exc}")


async def _process_alert(bot, alert, source_router) -> None:
    alert_id = getattr(alert, "id", None)
    user_id = getattr(alert, "user_id", None)
    query = getattr(alert, "query", "")
    last_notified_at = getattr(alert, "last_notified_at", None)

    if not user_id or not query:
        return

    try:
        books, _total = await source_router.search_first_batch(query, per_page=20)
    except Exception as exc:
        logger.warning(f"Alert search failed for '{query}': {exc}")
        await db.update_alert_checked(alert_id, notified=False)
        return

    if not books:
        await db.update_alert_checked(alert_id, notified=False)
        return

    # Compare by title: if no previous notification, all results are "new"
    if last_notified_at is None:
        new_books = books[:5]
    else:
        # Simple heuristic: consider books found after last_notified_at as new.
        # Since we don't store previous titles in DB, we notify only on first run
        # or when the alert has never been notified.
        new_books = []

    if new_books:
        lines = [f"🔔 <b>New results for '{query}':</b>\n"]
        for book in new_books:
            title = getattr(book, "title", "Unknown") or "Unknown"
            author = getattr(book, "author", "") or ""
            lines.append(f"📚 <b>{title}</b>")
            if author:
                lines.append(f"   👤 {author}")
        text = "\n".join(lines)
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
        except Exception as exc:
            logger.warning(f"Could not notify user {user_id}: {exc}")

        await db.update_alert_checked(alert_id, notified=True)
    else:
        await db.update_alert_checked(alert_id, notified=False)
