"""New-library UI: home screen, persistent reply menu, favorites,
history, settings, help sections and support.

Most views are inline-keyboard pages with a consistent
``Prev | Page X of Y | Next`` + ``Back | Home | Close`` footer so users can
never get stuck in nested menus.  The persistent reply keyboard (see
``light.keyboards.main_reply_keyboard``) is always visible under the input
field, so "Home" is always one tap away.

Book detail rendering, downloading and search live in ``light.handlers`` and
are reused here to avoid duplicated logic.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Dict, List, Optional

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

try:
    from light.config import (
        CONTACT_URL,
        SUPPORT_URL,
        preferences,
        registry,
        userdata,
        zl,
    )
    from light.handlers import _do_search, _edit_or_send, _user_lang, language_keyboard, safe_answer, show_book_detail
    from light.i18n import EN, RU, get_text
    from light.keyboards import (
        MENU_ROWS,
        favorites_keyboard,
        format_keyboard,
        help_index_keyboard,
        help_section_keyboard,
        history_keyboard,
        home_trending_keyboard,
        main_reply_keyboard,
        nav_keyboard,
        notifications_keyboard,
        per_page_keyboard,
        settings_keyboard,
        support_keyboard,
    )
    from light.userdata import book_from_dict
except ImportError:  # running directly: python light/bot.py
    from config import (  # type: ignore
        CONTACT_URL,
        SUPPORT_URL,
        preferences,
        registry,
        userdata,
        zl,
    )
    from handlers import _do_search, _edit_or_send, _user_lang, language_keyboard, safe_answer, show_book_detail  # type: ignore
    from i18n import EN, RU, get_text  # type: ignore
    from keyboards import (  # type: ignore
        MENU_ROWS,
        favorites_keyboard,
        format_keyboard,
        help_index_keyboard,
        help_section_keyboard,
        history_keyboard,
        home_trending_keyboard,
        main_reply_keyboard,
        nav_keyboard,
        notifications_keyboard,
        per_page_keyboard,
        settings_keyboard,
        support_keyboard,
    )
    from userdata import book_from_dict  # type: ignore

log = logging.getLogger("light.features")

features_router = Router()

# --------------------------------------------------------------------------
# Persistent reply-menu routing
# --------------------------------------------------------------------------

# Map every localized reply-menu label (all supported UI languages) to an action.
_MENU_LABELS: Dict[str, str] = {}
for _key, _action, _emoji in MENU_ROWS:
    for _ui_lang in (EN, RU):
        _MENU_LABELS[f"{_emoji} {get_text(_key, _ui_lang)}"] = _action

# Trending cache so navigation ("Home") stays instant between fetches.
_TRENDING_CACHE: List = []
_TRENDING_AT: float = 0.0
_TRENDING_TTL = 600.0


@features_router.message(F.text.in_(_MENU_LABELS))
async def handle_menu_tap(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    lang = _user_lang(message.from_user)
    action = _MENU_LABELS.get(message.text or "")
    if action == "search":
        await message.answer(get_text("search_prompt", lang))
    elif action == "favorites":
        await show_favorites(message, user_id, lang, 1)
    elif action == "history":
        await show_history(message, user_id, lang, 1)
    elif action == "language":
        current = preferences.get_language(user_id)
        text = get_text("language_title", lang) + "\n\n" + get_text("language_description", lang)
        await message.answer(text, reply_markup=language_keyboard(current, lang))
    elif action == "settings":
        await show_settings(message, user_id, lang)
    elif action == "help":
        await send_help_index(message, lang)
    elif action == "support":
        await show_support(message, lang)


# --------------------------------------------------------------------------
# Home
# --------------------------------------------------------------------------

async def _cached_trending(allow_fetch: bool = True) -> List:
    global _TRENDING_CACHE, _TRENDING_AT
    fresh = bool(_TRENDING_CACHE) and time.monotonic() - _TRENDING_AT < _TRENDING_TTL
    if fresh or not allow_fetch:
        return _TRENDING_CACHE
    try:
        books = await asyncio.wait_for(zl.popular(5), timeout=15)
    except Exception as e:
        log.debug("Trending fetch failed: %s", e)
        books = []
    if books:
        _TRENDING_CACHE = books
        _TRENDING_AT = time.monotonic()
    return books


async def send_home(
    message: Message,
    lang: Optional[str] = None,
    user_id: Optional[int] = None,
    edit: bool = False,
    fetch_trending: bool = False,
) -> None:
    """Show the home screen: welcome message + persistent reply keyboard.

    With ``fetch_trending=True`` (used on /start) the trending block is
    refreshed if stale; navigation calls keep it instant by reusing the cache.
    """
    text = get_text("home_welcome", lang)
    kb = main_reply_keyboard(lang)
    if edit:
        await _edit_or_send(message, text, kb)
    else:
        await message.answer(text, reply_markup=kb)

    trending = await _cached_trending(allow_fetch=fetch_trending)
    if trending and not edit:
        registry.put_many(trending)
        try:
            await message.answer(
                get_text("home_trending", lang), reply_markup=home_trending_keyboard(trending, lang)
            )
        except Exception:
            pass


# --------------------------------------------------------------------------
# Favorites
# --------------------------------------------------------------------------

async def show_favorites(message: Message, user_id: int, lang: Optional[str], page: int = 1, edit: bool = False) -> None:
    favs = userdata.get_favorites(user_id)
    if not favs:
        text = get_text("fav_empty", lang)
        kb = nav_keyboard(lang, "close")
        if edit:
            await _edit_or_send(message, text, kb)
        else:
            await message.answer(text, reply_markup=kb)
        return

    per_page = int(userdata.get_setting(user_id, "per_page", 10) or 10)
    total_pages = max(1, math.ceil(len(favs) / per_page))
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    text = get_text("fav_title", lang) + get_text("fav_page_hint", lang).format(page=page, total_pages=total_pages)
    kb = favorites_keyboard(favs[start:start + per_page], start, page, total_pages, lang)
    if edit:
        await _edit_or_send(message, text, kb)
    else:
        await message.answer(text, reply_markup=kb)


@features_router.callback_query(F.data.startswith("fav:open:"))
async def callback_favorite_open(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    lang = _user_lang(callback.from_user)
    try:
        idx = int(callback.data.split(":")[-1])
    except ValueError:
        await safe_answer(callback)
        return
    favs = userdata.get_favorites(user_id)
    if not (0 <= idx < len(favs)):
        await safe_answer(callback)
        return
    book = book_from_dict(favs[idx])
    registry.put(book)
    await show_book_detail(callback.message, book, user_id, lang)
    await safe_answer(callback)


@features_router.callback_query(F.data.startswith("fav:page:"))
async def callback_favorite_page(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    lang = _user_lang(callback.from_user)
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        await safe_answer(callback)
        return
    await show_favorites(callback.message, user_id, lang, page, edit=True)
    await safe_answer(callback)


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------

HISTORY_PAGE_SIZE = 10


async def show_history(message: Message, user_id: int, lang: Optional[str], page: int = 1, edit: bool = False) -> None:
    hist = userdata.get_history(user_id, 50)
    if not hist:
        text = get_text("hist_empty", lang)
        kb = nav_keyboard(lang, "close")
        if edit:
            await _edit_or_send(message, text, kb)
        else:
            await message.answer(text, reply_markup=kb)
        return

    total_pages = max(1, math.ceil(len(hist) / HISTORY_PAGE_SIZE))
    page = max(1, min(page, total_pages))
    start = (page - 1) * HISTORY_PAGE_SIZE
    text = get_text("hist_title", lang) + get_text("fav_page_hint", lang).format(page=page, total_pages=total_pages)
    kb = history_keyboard(hist[start:start + HISTORY_PAGE_SIZE], start, page, total_pages, lang)
    if edit:
        await _edit_or_send(message, text, kb)
    else:
        await message.answer(text, reply_markup=kb)


@features_router.callback_query(F.data.startswith("hist:go:"))
async def callback_history_go(callback: CallbackQuery) -> None:
    user = callback.from_user
    user_id = user.id if user else 0
    lang = _user_lang(user)
    try:
        idx = int(callback.data.split(":")[-1])
    except ValueError:
        await safe_answer(callback)
        return
    hist = userdata.get_history(user_id, 50)
    if not (0 <= idx < len(hist)):
        await safe_answer(callback)
        return
    entry = hist[idx]
    if entry.get("type") == "search" and entry.get("query"):
        await safe_answer(callback)
        await _do_search(callback.message, entry["query"], user=user, user_id=user_id)
    else:
        await safe_answer(callback, get_text("search_expired", lang), show_alert=True)


@features_router.callback_query(F.data.startswith("hist:page:"))
async def callback_history_page(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    lang = _user_lang(callback.from_user)
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        await safe_answer(callback)
        return
    await show_history(callback.message, user_id, lang, page, edit=True)
    await safe_answer(callback)


@features_router.callback_query(F.data == "hist:clear")
async def callback_history_clear(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    lang = _user_lang(callback.from_user)
    userdata.clear_history(user_id)
    await _edit_or_send(callback.message, get_text("hist_cleared", lang), nav_keyboard(lang, "close"))
    await safe_answer(callback)


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

async def show_settings(message: Message, user_id: int, lang: Optional[str], edit: bool = False) -> None:
    fmt = userdata.get_setting(user_id, "format")
    per_page = userdata.get_setting(user_id, "per_page")
    notif = userdata.get_setting(user_id, "notifications", True)
    text = get_text("settings_title", lang)
    kb = settings_keyboard(lang, fmt, per_page, notif)
    if edit:
        await _edit_or_send(message, text, kb)
    else:
        await message.answer(text, reply_markup=kb)


@features_router.callback_query(F.data == "settings:open")
async def callback_settings_open(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    lang = _user_lang(callback.from_user)
    await show_settings(callback.message, user_id, lang, edit=True)
    await safe_answer(callback)


@features_router.callback_query(F.data == "set:fmt")
async def callback_format_menu(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    lang = _user_lang(callback.from_user)
    current = userdata.get_setting(user_id, "format")
    text = get_text("settings_format_title", lang)
    await _edit_or_send(callback.message, text, format_keyboard(lang, current))
    await safe_answer(callback)


@features_router.callback_query(F.data.startswith("set:fmt:"))
async def callback_format_set(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    lang = _user_lang(callback.from_user)
    fmt = callback.data.split(":", 2)[-1].lower()
    userdata.set_setting(user_id, "format", fmt)
    text = get_text("settings_format_set", lang).format(value=fmt.upper())
    await _edit_or_send(callback.message, text, format_keyboard(lang, fmt))
    await safe_answer(callback)


@features_router.callback_query(F.data == "set:page")
async def callback_page_menu(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    lang = _user_lang(callback.from_user)
    current = userdata.get_setting(user_id, "per_page")
    text = get_text("settings_page_title", lang)
    await _edit_or_send(callback.message, text, per_page_keyboard(lang, current))
    await safe_answer(callback)


@features_router.callback_query(F.data.startswith("set:page:"))
async def callback_page_set(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    lang = _user_lang(callback.from_user)
    try:
        value = int(callback.data.split(":")[-1])
    except ValueError:
        await safe_answer(callback)
        return
    if value not in (10, 20, 30, 50):
        await safe_answer(callback)
        return
    userdata.set_setting(user_id, "per_page", value)
    text = get_text("settings_page_set", lang).format(value=value)
    await _edit_or_send(callback.message, text, per_page_keyboard(lang, value))
    await safe_answer(callback)


@features_router.callback_query(F.data == "set:notif")
async def callback_notif_menu(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    lang = _user_lang(callback.from_user)
    current = userdata.get_setting(user_id, "notifications", True)
    text = get_text("settings_notif_title", lang)
    await _edit_or_send(callback.message, text, notifications_keyboard(lang, current))
    await safe_answer(callback)


@features_router.callback_query(F.data.startswith("set:notif:"))
async def callback_notif_set(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    lang = _user_lang(callback.from_user)
    value = callback.data.split(":")[-1] == "on"
    userdata.set_setting(user_id, "notifications", value)
    label = get_text("settings_notif_on" if value else "settings_notif_off", lang)
    text = get_text("settings_notif_set", lang).format(value=label)
    await _edit_or_send(callback.message, text, notifications_keyboard(lang, value))
    await safe_answer(callback)


# --------------------------------------------------------------------------
# Help
# --------------------------------------------------------------------------

_HELP_TEXT_KEYS = {
    "how_search": "help_how_search_text",
    "downloads": "help_downloads_text",
    "formats": "help_formats_text",
    "faq": "help_faq_text",
    "report": "help_report_text",
    "contact": "help_contact_text",
}


async def send_help_index(message: Message, lang: Optional[str] = None) -> None:
    await message.answer(get_text("help_index", lang), reply_markup=help_index_keyboard(lang))


@features_router.callback_query(F.data == "help:index")
async def callback_help_index(callback: CallbackQuery) -> None:
    lang = _user_lang(callback.from_user)
    await _edit_or_send(callback.message, get_text("help_index", lang), help_index_keyboard(lang))
    await safe_answer(callback)


@features_router.callback_query(F.data.startswith("help:"))
async def callback_help_section(callback: CallbackQuery) -> None:
    lang = _user_lang(callback.from_user)
    slug = callback.data.split(":", 1)[-1]
    text = get_text(_HELP_TEXT_KEYS.get(slug, "help_how_search_text"), lang)
    await _edit_or_send(callback.message, text, help_section_keyboard(lang))
    await safe_answer(callback)


# --------------------------------------------------------------------------
# Support
# --------------------------------------------------------------------------

async def show_support(message: Message, lang: Optional[str] = None) -> None:
    text = get_text("support_title", lang)
    kb = support_keyboard(lang, support_url=SUPPORT_URL or None, contact_url=CONTACT_URL or None)
    await message.answer(text, reply_markup=kb)
