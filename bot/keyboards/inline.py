from __future__ import annotations

from typing import List, Optional, Tuple

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import Book, Category
from bot.utils.helpers import LANGUAGES, language_flag


def main_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="\U0001f50d Search Books", callback_data="search:prompt")
    builder.button(text="\U0001f4ca Categories", callback_data="categories:list:1")
    builder.button(text="\U0001f525 Popular Books", callback_data="books:popular")
    builder.button(text="\U0001f4f0 Latest Books", callback_data="books:latest")
    builder.button(text="\u2764\ufe0f My Favorites", callback_data="favorites:list:1")
    builder.button(text="\U0001f4cb Download History", callback_data="history:list:1")
    builder.button(text="\U0001f4d6 My Shelf", callback_data="shelf:menu")
    builder.button(text="\U0001f514 Alerts", callback_data="alerts:list")
    builder.button(text="\U0001f1ec\U0001f1e7 Language", callback_data="lang:menu")
    builder.button(text="\u2753 Help", callback_data="help")
    builder.adjust(2)
    return builder.as_markup()


def category_list_keyboard(categories: List[Category], page: int, total_pages: int, back_callback: str = "menu") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for cat in categories:
        icon = cat.icon or "📖"
        name = f"{icon} {cat.name}"
        builder.row(
            InlineKeyboardButton(
                text=name,
                callback_data=f"category:{cat.id}:1",
            )
        )
    nav_buttons = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton(text="◀️ Prev", callback_data=f"categories:list:{page - 1}")
        )
    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(text="Next ▶️", callback_data=f"categories:list:{page + 1}")
        )
    if nav_buttons:
        builder.row(*nav_buttons)
    builder.row(InlineKeyboardButton(text="\u2b05\ufe0f Back", callback_data=back_callback))
    return builder.as_markup()


def book_list_keyboard(
    books: List[Book],
    page: int,
    total_pages: int,
    action_prefix: str = "book",
    back_callback: str = "menu",
    active_format: Optional[str] = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for book in books:
        title = book.title[:40] + "..." if len(book.title) > 40 else book.title
        builder.row(
            InlineKeyboardButton(
                text=title,
                callback_data=f"{action_prefix}:detail:{book.id}",
            )
        )
    nav_buttons = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton(text="◀️ Prev", callback_data=f"{action_prefix}:page:{page - 1}")
        )
    nav_buttons.append(
        InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="ignore")
    )
    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(text="Next ▶️", callback_data=f"{action_prefix}:page:{page + 1}")
        )
    if nav_buttons:
        builder.row(*nav_buttons)
    # Format filter row — only shown for search results
    if action_prefix == "search":
        fmt_buttons = []
        for label, fmt in [("PDF", "pdf"), ("EPUB", "epub"), ("MOBI", "mobi"), ("All", "all")]:
            prefix = "✓ " if active_format == fmt or (fmt == "all" and not active_format) else ""
            fmt_buttons.append(
                InlineKeyboardButton(
                    text=f"{prefix}{label}",
                    callback_data=f"search:format:{fmt}",
                )
            )
        builder.row(*fmt_buttons)
    builder.row(InlineKeyboardButton(text="Back", callback_data=back_callback))
    return builder.as_markup()


def language_toggle_button(current_lang: Optional[str], action_prefix: str) -> InlineKeyboardButton:
    """Return a single InlineKeyboardButton that toggles the search language filter."""
    lang_label = current_lang.upper() if current_lang else "Any"
    return InlineKeyboardButton(
        text=f"\U0001f30d Lang: {lang_label}",
        callback_data="search:lang:toggle",
    )


def book_detail_keyboard(
    book_id: str,
    is_favorite: bool = False,
    download_url: Optional[str] = None,
    back_callback: str = "menu",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="\u2b07\ufe0f Download", callback_data=f"download:{book_id}"),
        InlineKeyboardButton(
            text="\u2764\ufe0f Remove from Favorites" if is_favorite else "\u2764\ufe0f Add to Favorites",
            callback_data=f"favorite:toggle:{book_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="\U0001f4d6 Description", callback_data=f"desc:{book_id}"),
        InlineKeyboardButton(text="🔖 Shelf", callback_data=f"shelf:choose:{book_id}"),
        InlineKeyboardButton(text="📖 Read", callback_data=f"read:{book_id}:0:0"),
    )
    builder.row(InlineKeyboardButton(text="\u2b05\ufe0f Back", callback_data=back_callback))
    return builder.as_markup()


def pagination_keyboard(
    current_page: int,
    total_pages: int,
    prefix: str,
    back_callback: str = "menu",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    nav_buttons = []
    if current_page > 1:
        nav_buttons.append(
            InlineKeyboardButton(text="◀️", callback_data=f"{prefix}:page:{current_page - 1}")
        )
    nav_buttons.append(
        InlineKeyboardButton(text=f"{current_page}/{total_pages}", callback_data="ignore")
    )
    if current_page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(text="▶️", callback_data=f"{prefix}:page:{current_page + 1}")
        )
    if nav_buttons:
        builder.row(*nav_buttons)
    builder.row(InlineKeyboardButton(text="\u2b05\ufe0f Back", callback_data=back_callback))
    return builder.as_markup()


def confirm_download_keyboard(book_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Confirm Download", callback_data=f"download:confirm:{book_id}"),
        InlineKeyboardButton(text="Cancel", callback_data=f"book:detail:{book_id}"),
    )
    return builder.as_markup()


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Dashboard", callback_data="admin:dashboard"),
        InlineKeyboardButton(text="Users", callback_data="admin:users:1"),
    )
    builder.row(
        InlineKeyboardButton(text="Downloads", callback_data="admin:downloads"),
        InlineKeyboardButton(text="Banned Users", callback_data="admin:banned"),
    )
    builder.row(
        InlineKeyboardButton(text="Broadcast Message", callback_data="admin:broadcast"),
        InlineKeyboardButton(text="Admin Logs", callback_data="admin:logs"),
    )
    builder.row(InlineKeyboardButton(text="Close", callback_data="admin:close"))
    return builder.as_markup()


def download_complete_keyboard(book_id: str, convert_key: Optional[str] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="\U0001f4c2 Details", callback_data=f"book:detail:{book_id}"),
    )
    if convert_key:
        builder.row(
            InlineKeyboardButton(text="\U0001f504 Convert", callback_data=f"convert:{book_id}:{convert_key}"),
        )
    return builder.as_markup()


def close_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Close", callback_data="admin:close")
    return builder.as_markup()


def language_keyboard(current: Optional[str] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, name, _ in LANGUAGES:
        selected = " \u2705" if code == current else ""
        builder.button(
            text=f"{name}{selected}",
            callback_data=f"lang:set:{code}",
        )
    builder.adjust(3)
    if current:
        builder.row(
            InlineKeyboardButton(text="Any Language", callback_data="lang:clear"),
        )
    builder.row(InlineKeyboardButton(text="Back to Menu", callback_data="menu"))
    return builder.as_markup()
