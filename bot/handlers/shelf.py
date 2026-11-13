"""bot/handlers/shelf.py — Reading Shelf handler (feature #5)."""
from __future__ import annotations

from typing import Optional

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from bot.database.service import db
from bot.utils.helpers import calculate_pages
from bot.utils.i18n import get_text

try:
    from bot.database.models import ReadingStatus  # noqa: F401
except ImportError:
    ReadingStatus = None  # type: ignore

try:
    from bot.database.models import User as DBUser
except ImportError:
    DBUser = None  # type: ignore

router = Router()

_STATUS_LABELS = {
    "want_to_read": "📚 Want to Read",
    "reading": "📖 Currently Reading",
    "finished": "✅ Finished",
}


# ── Helper keyboard ──────────────────────────────────────────────────────────

def shelf_status_keyboard(book_id: str, current_status: Optional[str] = None) -> InlineKeyboardMarkup:
    """Inline keyboard with 3 status buttons + optional Remove button."""
    builder = InlineKeyboardBuilder()
    for status, label in _STATUS_LABELS.items():
        prefix = "✓ " if status == current_status else ""
        builder.button(
            text=f"{prefix}{label}",
            callback_data=f"shelf:set:{book_id}:{status}",
        )
    builder.adjust(1)
    if current_status:
        builder.row(
            InlineKeyboardButton(
                text="🗑 Remove from Shelf",
                callback_data=f"shelf:remove:{book_id}",
            )
        )
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data=f"book:detail:{book_id}"))
    return builder.as_markup()


def _shelf_menu_keyboard(lang: Optional[str] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for status, label in _STATUS_LABELS.items():
        builder.button(text=label, callback_data=f"shelf:list:{status}:1")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="menu"))
    return builder.as_markup()


def _shelf_list_keyboard(books: list, page: int, total_pages: int, status: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for book in books:
        raw_title = getattr(book, "title", None) or "Unknown"
        title = (raw_title[:40] + "…") if len(raw_title) > 40 else raw_title
        book_id = getattr(book, "book_id", None) or getattr(book, "id", "?")
        builder.row(
            InlineKeyboardButton(
                text=title,
                callback_data=f"book:detail:{book_id}",
            )
        )
    nav_buttons = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton(text="◀️ Prev", callback_data=f"shelf:list:{status}:{page - 1}")
        )
    nav_buttons.append(
        InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="ignore")
    )
    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(text="Next ▶️", callback_data=f"shelf:list:{status}:{page + 1}")
        )
    if nav_buttons:
        builder.row(*nav_buttons)
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="shelf:menu"))
    return builder.as_markup()


# ── Handlers ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "shelf:menu")
async def callback_shelf_menu(callback: CallbackQuery, db_user=None) -> None:
    lang = db_user.preferred_language if db_user else None
    await callback.message.edit_text(
        "📖 <b>My Reading Shelf</b>\n\nChoose a list to view:",
        parse_mode="HTML",
        reply_markup=_shelf_menu_keyboard(lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("shelf:list:"))
async def callback_shelf_list(callback: CallbackQuery, db_user=None) -> None:
    lang = db_user.preferred_language if db_user else None
    # Format: shelf:list:{status}:{page}
    parts = callback.data.split(":")
    # parts = ["shelf", "list", status, page]
    if len(parts) < 4:
        await callback.answer("Invalid request.", show_alert=True)
        return

    status = parts[2]
    try:
        page = int(parts[3])
    except (ValueError, IndexError):
        page = 1

    user_id = callback.from_user.id if callback.from_user else (db_user.id if db_user else None)
    if not user_id:
        await callback.answer("Cannot identify user.", show_alert=True)
        return

    per_page = 10
    try:
        books, total = await db.get_user_reading_shelf(user_id, status=status, page=page, per_page=per_page)
    except Exception as exc:
        logger.error(f"shelf list error: {exc}")
        await callback.answer("Error loading shelf.", show_alert=True)
        return

    total_pages = max(1, calculate_pages(total, per_page))
    status_label = _STATUS_LABELS.get(status, status)

    if not books:
        text = f"<b>{status_label}</b>\n\nYour shelf is empty here. Start adding books!"
    else:
        text = f"<b>{status_label}</b>  —  page {page}/{total_pages}\n\n{total} book(s)"

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=_shelf_list_keyboard(books, page, total_pages, status),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("shelf:set:"))
async def callback_shelf_set(callback: CallbackQuery, db_user=None) -> None:
    # Format: shelf:set:{book_id}:{status}
    parts = callback.data.split(":")
    # Could be shelf:set:<uuid-with-dashes>:status — uuid might contain colons? No. Split carefully.
    # parts[0]=shelf, parts[1]=set, parts[-1]=status, parts[2:-1]=book_id pieces
    if len(parts) < 4:
        await callback.answer("Invalid request.", show_alert=True)
        return

    status = parts[-1]
    book_id = ":".join(parts[2:-1])

    user_id = callback.from_user.id if callback.from_user else (db_user.id if db_user else None)
    if not user_id:
        await callback.answer("Cannot identify user.", show_alert=True)
        return

    try:
        await db.set_reading_status(user_id, book_id, status)
    except Exception as exc:
        logger.error(f"shelf set error: {exc}")
        await callback.answer("Error updating shelf.", show_alert=True)
        return

    status_label = _STATUS_LABELS.get(status, status)
    await callback.answer(f"✅ Added to {status_label}", show_alert=False)


@router.callback_query(F.data.startswith("shelf:remove:"))
async def callback_shelf_remove(callback: CallbackQuery, db_user=None) -> None:
    # Format: shelf:remove:{book_id}
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Invalid request.", show_alert=True)
        return

    book_id = ":".join(parts[2:])
    user_id = callback.from_user.id if callback.from_user else (db_user.id if db_user else None)
    if not user_id:
        await callback.answer("Cannot identify user.", show_alert=True)
        return

    try:
        await db.remove_reading_status(user_id, book_id)
    except Exception as exc:
        logger.error(f"shelf remove error: {exc}")
        await callback.answer("Error removing from shelf.", show_alert=True)
        return

    await callback.answer("🗑 Removed from shelf", show_alert=False)


@router.callback_query(F.data.startswith("shelf:choose:"))
async def callback_shelf_choose(callback: CallbackQuery, db_user=None) -> None:
    parts = callback.data.split(":")
    book_id = ":".join(parts[2:])
    user_id = callback.from_user.id if callback.from_user else (db_user.id if db_user else None)
    current_status = None
    if user_id:
        try:
            status_obj = await db.get_reading_status(user_id, book_id)
            if status_obj:
                current_status = status_obj.status
        except Exception:
            pass
    await callback.message.edit_reply_markup(reply_markup=shelf_status_keyboard(book_id, current_status))
    await callback.answer()

