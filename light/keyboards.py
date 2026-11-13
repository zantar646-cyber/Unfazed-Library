"""Keyboard builders for the light bot.

Two kinds of keyboards live here:

* the persistent reply menu (always visible under the input field)
* inline keyboards for home/favorites/history/settings/help/support

Everything is localized via :func:`light.i18n.get_text`.  Shared nav helpers
(``Prev | Page X of Y | Next`` and ``Back | Home | Close``) keep every page
consistent and prevent users from getting stuck in nested menus.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

try:
    from light.i18n import get_text
except ImportError:  # running directly: python light/bot.py
    from i18n import get_text  # type: ignore

# (i18n key, action, emoji) for each persistent reply-menu button, in order.
MENU_ROWS: List[tuple] = [
    ("menu_search", "search", "\U0001f50d"),
    ("menu_favorites", "favorites", "\u2764\ufe0f"),
    ("menu_history", "history", "\U0001f558"),
    ("menu_language", "language", "\U0001f310"),
    ("menu_settings", "settings", "\u2699\ufe0f"),
    ("menu_help", "help", "\u2753"),
    ("menu_support", "support", "\U0001f48e"),
]

# Settings format/per-page options (value, localized label is optional).
PREFERRED_FORMATS: List[str] = ["pdf", "epub", "mobi", "azw3"]
RESULTS_PER_PAGE: List[int] = [10, 20, 30, 50]


def main_reply_keyboard(lang: Optional[str] = None) -> ReplyKeyboardMarkup:
    """Persistent, resizable reply keyboard shown as the main menu."""
    labels = [f"{emoji} {get_text(key, lang)}" for key, _, emoji in MENU_ROWS]
    rows = [labels[i:i + 2] for i in range(0, len(labels), 2)]
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text) for text in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=get_text("reply_placeholder", lang),
    )


def _page_row(page: int, total_pages: int, prev_cb: str, next_cb: str, lang: Optional[str]) -> List[InlineKeyboardButton]:
    row: List[InlineKeyboardButton] = []
    if page > 1:
        row.append(InlineKeyboardButton(text=get_text("btn_prev", lang), callback_data=prev_cb))
    row.append(
        InlineKeyboardButton(
            text=get_text("page_indicator", lang).format(page=page, total=total_pages),
            callback_data="ignore",
        )
    )
    if page < total_pages:
        row.append(InlineKeyboardButton(text=get_text("btn_next", lang), callback_data=next_cb))
    return row


def _foot_row(lang: Optional[str], back_callback: str, include_close: bool = True) -> List[InlineKeyboardButton]:
    row = [
        InlineKeyboardButton(text=get_text("btn_back", lang), callback_data=back_callback),
        InlineKeyboardButton(text=get_text("btn_home", lang), callback_data="menu:main"),
    ]
    if include_close:
        row.append(InlineKeyboardButton(text=get_text("btn_close", lang), callback_data="close"))
    return row


def nav_keyboard(lang: Optional[str] = None, back_callback: str = "menu:main", include_close: bool = True) -> InlineKeyboardMarkup:
    """Standard Back | Home | Close footer for simple pages."""
    builder = InlineKeyboardBuilder()
    builder.row(*_foot_row(lang, back_callback, include_close))
    return builder.as_markup()


# --------------------------------------------------------------------------
# Home
# --------------------------------------------------------------------------

def home_trending_keyboard(books: List, lang: Optional[str] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for b in books:
        title = b.title[:40] + "..." if len(b.title) > 40 else b.title
        builder.row(InlineKeyboardButton(text=title, callback_data=f"book:detail:{b.id}"))
    return builder.as_markup()


# --------------------------------------------------------------------------
# Favorites
# --------------------------------------------------------------------------

def favorites_keyboard(
    favorites: List[Dict], offset: int, page: int, total_pages: int, lang: Optional[str] = None
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for idx, fav in enumerate(favorites, start=offset):
        title = fav.get("title") or get_text("unknown", lang)
        author = fav.get("author")
        label = f"{title} \u2014 {author}" if author else title
        label = label[:40] + "..." if len(label) > 40 else label
        builder.row(InlineKeyboardButton(text=label, callback_data=f"fav:open:{idx}"))
    builder.row(*_page_row(page, total_pages, f"fav:page:{page - 1}", f"fav:page:{page + 1}", lang))
    builder.row(*_foot_row(lang, "close"))
    return builder.as_markup()


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------

def history_keyboard(
    entries: List[Dict], offset: int, page: int, total_pages: int, lang: Optional[str] = None
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for idx, entry in enumerate(entries, start=offset):
        if entry.get("type") == "download":
            title = entry.get("title") or get_text("unknown", lang)
            label = get_text("hist_download", lang).format(title=title[:38])
            cb = f"book:detail:{entry.get('book_id', '')}"
        else:
            query = entry.get("query") or ""
            label = get_text("hist_search", lang).format(query=query[:38])
            cb = f"hist:go:{idx}"
        builder.row(InlineKeyboardButton(text=label, callback_data=cb))
    builder.row(*_page_row(page, total_pages, f"hist:page:{page - 1}", f"hist:page:{page + 1}", lang))
    builder.row(InlineKeyboardButton(text=get_text("hist_clear", lang), callback_data="hist:clear"))
    builder.row(*_foot_row(lang, "close"))
    return builder.as_markup()


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

def settings_keyboard(
    lang: Optional[str] = None,
    fmt: Optional[str] = None,
    per_page: Optional[int] = None,
    notif: Optional[bool] = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    fmt_label = (fmt or get_text("unknown", lang)).upper()
    builder.row(
        InlineKeyboardButton(
            text=f"\U0001f310 {get_text('menu_language', lang)}", callback_data="lang:menu"
        ),
        InlineKeyboardButton(
            text=f"\U0001f4c4 {get_text('settings_format', lang)} ({fmt_label})",
            callback_data="set:fmt",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=f"\U0001f522 {get_text('settings_page', lang)} ({per_page})",
            callback_data="set:page",
        ),
        InlineKeyboardButton(
            text=f"\U0001f514 {get_text('settings_notif', lang)} ({get_text('settings_notif_on' if notif else 'settings_notif_off', lang)})",
            callback_data="set:notif",
        ),
    )
    builder.row(*_foot_row(lang, "close"))
    return builder.as_markup()


def format_keyboard(lang: Optional[str] = None, current: Optional[str] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for f in PREFERRED_FORMATS:
        mark = " \u2705" if f == (current or "").lower() else ""
        builder.row(InlineKeyboardButton(text=f.upper() + mark, callback_data=f"set:fmt:{f}"))
    builder.row(*_foot_row(lang, "settings:open"))
    return builder.as_markup()


def per_page_keyboard(lang: Optional[str] = None, current: Optional[int] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for n in RESULTS_PER_PAGE:
        mark = " \u2705" if n == current else ""
        builder.row(InlineKeyboardButton(text=str(n) + mark, callback_data=f"set:page:{n}"))
    builder.row(*_foot_row(lang, "settings:open"))
    return builder.as_markup()


def notifications_keyboard(lang: Optional[str] = None, current: Optional[bool] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value, key in ((True, "settings_notif_on"), (False, "settings_notif_off")):
        mark = " \u2705" if value == current else ""
        builder.row(
            InlineKeyboardButton(text=get_text(key, lang) + mark, callback_data=f"set:notif:{'on' if value else 'off'}")
        )
    builder.row(*_foot_row(lang, "settings:open"))
    return builder.as_markup()


# --------------------------------------------------------------------------
# Help
# --------------------------------------------------------------------------

HELP_SECTIONS: List[tuple] = [
    ("how_search", "help_how_search", "\U0001f50d"),
    ("downloads", "help_downloads", "\u2b07\ufe0f"),
    ("formats", "help_formats", "\U0001f4c4"),
    ("faq", "help_faq", "\u2753"),
    ("report", "help_report", "\U0001f41e"),
    ("contact", "help_contact", "\u2709\ufe0f"),
]


def help_index_keyboard(lang: Optional[str] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for slug, key, emoji in HELP_SECTIONS:
        builder.row(InlineKeyboardButton(text=f"{emoji} {get_text(key, lang)}", callback_data=f"help:{slug}"))
    builder.row(*_foot_row(lang, "close"))
    return builder.as_markup()


def help_section_keyboard(lang: Optional[str] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(*_foot_row(lang, "help:index"))
    return builder.as_markup()


# --------------------------------------------------------------------------
# Support
# --------------------------------------------------------------------------

def support_keyboard(
    lang: Optional[str] = None,
    support_url: Optional[str] = None,
    contact_url: Optional[str] = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    row = []
    if support_url:
        row.append(InlineKeyboardButton(text=get_text("support_pay", lang), url=support_url))
    if contact_url:
        row.append(InlineKeyboardButton(text=get_text("support_contact_btn", lang), url=contact_url))
    if row:
        builder.row(*row)
    builder.row(
        InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu:main"),
        InlineKeyboardButton(text=get_text("btn_home", lang), callback_data="menu:main"),
    )
    builder.row(InlineKeyboardButton(text=get_text("btn_close", lang), callback_data="close"))
    return builder.as_markup()
