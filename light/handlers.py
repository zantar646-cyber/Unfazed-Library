"""Telegram handlers for the lightweight bot: search, pagination, download."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from html import unescape
from typing import List, Optional

from aiogram import BaseMiddleware, F, Router, types
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

try:
    from light.cache import SearchSession
    from light.config import DOWNLOAD_TIMEOUT, PAGE_SIZE, preferences, registry, sessions, source_router, userdata
    from light.i18n import (
        LANGUAGES,
        detect_content_language,
        get_text,
        language_display,
        language_flag,
        language_name,
        pluralize,
    )
    from light.sources import Book
except ImportError:  # running directly: python light/bot.py
    from cache import SearchSession  # type: ignore
    from config import DOWNLOAD_TIMEOUT, PAGE_SIZE, preferences, registry, sessions, source_router, userdata  # type: ignore
    from i18n import (  # type: ignore
        LANGUAGES,
        detect_content_language,
        get_text,
        language_display,
        language_flag,
        language_name,
        pluralize,
    )
    from sources import Book  # type: ignore

log = logging.getLogger("light.handlers")

router = Router()

_rate_hits: dict = {}


async def safe_answer(callback: CallbackQuery, *args, **kwargs) -> None:
    """Best-effort callback answer; ignores expired/invalid query errors."""
    try:
        await callback.answer(*args, **kwargs)
    except (TelegramBadRequest, TelegramNetworkError):
        pass


def _features():
    """Lazily import the features module (circular dependency: features
    imports this module, so it must be fetched at call time, not load time).
    Falls back to the flat module name when running directly (light/bot.py).
    """
    try:
        from light.features import send_help_index, send_home
    except ImportError:  # running directly: python light/bot.py
        from features import send_help_index, send_home  # type: ignore
    return send_home, send_help_index


def _user_lang(user: Optional[types.User]) -> Optional[str]:
    """Chosen content language; auto-detects once from the user's Telegram locale."""
    if user is None:
        return None
    pref = preferences.get_language(user.id)
    if pref is None:
        code = detect_content_language(getattr(user, "language_code", None))
        if code:
            preferences.set_language(user.id, code)
            pref = code
    return pref


def _rate_allowed(user_id: int, limit: int, window: int) -> bool:
    now = time.monotonic()
    hits = _rate_hits.get(user_id)
    if hits is None:
        _rate_hits[user_id] = [now]
        return True
    hits = [t for t in hits if now - t < window]
    if len(hits) >= limit:
        _rate_hits[user_id] = hits
        return False
    hits.append(now)
    _rate_hits[user_id] = hits
    return True


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, limit: int = 10, window: int = 60) -> None:
        self.limit = limit
        self.window = window

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        lang = _user_lang(user)
        user_id = getattr(user, "id", None)
        if user_id is not None and not _rate_allowed(user_id, self.limit, self.window):
            if isinstance(event, Message):
                await event.answer(get_text("rate_limited", lang))
            elif isinstance(event, CallbackQuery):
                await event.answer(get_text("rate_limited_alert", lang), show_alert=True)
            return
        return await handler(event, data)


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------

def sanitize_html(text: Optional[str]) -> str:
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def clean_text(text: Optional[str]) -> str:
    """Convert raw (possibly HTML- or markdown-laden) text into plain text."""
    if not text:
        return ""
    s = re.sub(r"<[^>]+>", " ", text)
    s = unescape(s)
    s = s.replace("**", "").replace("`", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def truncate_text(text: Optional[str], max_length: int = 200) -> str:
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def format_file_size(size_bytes: Optional[int], lang: Optional[str] = None) -> str:
    if size_bytes is None:
        return get_text("unknown", lang)
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


FORMAT_EMOJIS = {
    "pdf": "\U0001f4c4", "epub": "\U0001f4d6", "mobi": "\U0001f4f1", "azw3": "\U0001f4f1",
    "fb2": "\U0001f4c3", "djvu": "\U0001f4dc", "txt": "\U0001f4dd", "doc": "\U0001f4cb",
    "docx": "\U0001f4cb", "rtf": "\U0001f4c3", "cbz": "\U0001f4da", "cbr": "\U0001f4da",
    "zip": "\U0001f5dc\ufe0f", "rar": "\U0001f5dc\ufe0f",
}


def get_format_emoji(ext: Optional[str]) -> str:
    return FORMAT_EMOJIS.get((ext or "").lower().strip().lstrip("."), "\U0001f4c1")


def format_extension(ext: Optional[str], lang: Optional[str] = None) -> str:
    return (ext or "").lower().strip().lstrip(".").upper() or get_text("unknown", lang)


def _safe_filename(title: str) -> str:
    t = re.sub(r'[\\/:*?"<>|]', "", title).strip()
    return t or "book"


# --------------------------------------------------------------------------
# Keyboard builders
# --------------------------------------------------------------------------

def book_list_keyboard(books: List[Book], page: int, total_pages: int, lang: Optional[str] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for b in books:
        title = b.title[:40] + "..." if len(b.title) > 40 else b.title
        builder.row(InlineKeyboardButton(text=title, callback_data=f"book:detail:{b.id}"))
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text=get_text("btn_prev", lang), callback_data=f"search:page:{page - 1}"))
    nav.append(
        InlineKeyboardButton(
            text=get_text("page_indicator", lang).format(page=page, total=total_pages),
            callback_data="ignore",
        )
    )
    if page < total_pages:
        nav.append(InlineKeyboardButton(text=get_text("btn_next", lang), callback_data=f"search:page:{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(
        InlineKeyboardButton(text=get_text("btn_home", lang), callback_data="menu:main"),
        InlineKeyboardButton(text=get_text("btn_close", lang), callback_data="close"),
    )
    return builder.as_markup()


def book_detail_keyboard(
    book: Book,
    lang: Optional[str] = None,
    is_favorite: bool = False,
    prev_cb: Optional[str] = None,
    next_cb: Optional[str] = None,
    back_callback: str = "close",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=get_text("btn_download", lang), callback_data=f"download:{book.id}"))

    fmts = set((f or "").lower().lstrip(".") for f in book.formats if f)
    if book.extension:
        fmts.add(book.extension.lower().lstrip("."))
    if len(fmts) > 1:
        fmt_buttons = [
            InlineKeyboardButton(
                text=f"{get_format_emoji(f)} {f.upper()}",
                callback_data=f"download:{book.id}:{f}",
            )
            for f in sorted(fmts)
        ]
        for i in range(0, len(fmt_buttons), 4):
            builder.row(*fmt_buttons[i:i + 4])

    toggle_text = get_text("fav_toggle_remove" if is_favorite else "fav_toggle_add", lang)
    builder.row(InlineKeyboardButton(text=toggle_text, callback_data=f"fav:toggle:{book.id}"))

    nav = []
    if prev_cb:
        nav.append(InlineKeyboardButton(text=get_text("book_prev", lang), callback_data=prev_cb))
    if next_cb:
        nav.append(InlineKeyboardButton(text=get_text("book_next", lang), callback_data=next_cb))
    if nav:
        builder.row(*nav)

    builder.row(
        InlineKeyboardButton(text=get_text("btn_back", lang), callback_data=back_callback),
        InlineKeyboardButton(text=get_text("btn_home", lang), callback_data="menu:main"),
        InlineKeyboardButton(text=get_text("btn_close", lang), callback_data="close"),
    )
    return builder.as_markup()


def language_keyboard(current: Optional[str] = None, lang: Optional[str] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, name, flag in LANGUAGES:
        selected = " \u2705" if code == current else ""
        builder.row(
            InlineKeyboardButton(text=f"{flag} {name}{selected}", callback_data=f"lang:set:{code}")
        )
    if current:
        builder.row(
            InlineKeyboardButton(text=get_text("btn_any_language", lang), callback_data="lang:clear")
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text=f"{get_text('btn_any_language', lang)} \u2705", callback_data="ignore"
            )
        )
    builder.row(InlineKeyboardButton(text=get_text("btn_home", lang), callback_data="menu:main"))
    return builder.as_markup()


def _detail_nav(user_id: int, book: Book) -> tuple:
    """Compute Prev/Next/Back callbacks for a book detail view."""
    bid = str(book.id)
    prev_cb = next_cb = None
    back_cb = "close"

    session = sessions.get(user_id)
    if session is not None:
        for i, b in enumerate(session.results):
            if str(b.id) == bid:
                if i > 0:
                    prev_cb = f"book:detail:{session.results[i - 1].id}"
                if i < len(session.results) - 1:
                    next_cb = f"book:detail:{session.results[i + 1].id}"
                back_cb = f"search:page:{session.page}"
                return prev_cb, next_cb, back_cb

    per_page = int(userdata.get_setting(user_id, "per_page", PAGE_SIZE) or PAGE_SIZE)
    for i, fav in enumerate(userdata.get_favorites(user_id)):
        if str(fav.get("id")) == bid:
            if i > 0:
                prev_cb = f"fav:open:{i - 1}"
            if i < len(userdata.get_favorites(user_id)) - 1:
                next_cb = f"fav:open:{i + 1}"
            back_cb = f"fav:page:{i // per_page + 1}"
            return prev_cb, next_cb, back_cb

    return prev_cb, next_cb, back_cb


def build_book_caption(book: Book, lang: Optional[str] = None) -> str:
    fmt = book.extension or ""
    lines = [
        f"\U0001f4d6 <b>{sanitize_html(book.title)}</b>",
        f"\u270d\ufe0f <i>{sanitize_html(book.author or get_text('unknown_author', lang))}</i>",
    ]
    desc = truncate_text(sanitize_html(clean_text(book.description)), 300)
    if desc:
        lines += ["", desc]
    lines += ["", get_text("details_header", lang)]
    if book.publication_year:
        lines.append(get_text("book_year", lang).format(value=book.publication_year))
    if book.publisher:
        lines.append(get_text("book_publisher", lang).format(value=sanitize_html(book.publisher)))
    if book.edition:
        lines.append(get_text("book_edition", lang).format(value=sanitize_html(book.edition)))
    if book.isbn:
        lines.append(get_text("book_isbn", lang).format(value=sanitize_html(book.isbn)))
    if book.pages:
        lines.append(get_text("book_pages", lang).format(value=book.pages))
    if book.language:
        lines.append(get_text("book_language", lang).format(value=sanitize_html(language_display(book.language, lang))))
    if book.categories:
        lines.append(
            get_text("book_categories", lang).format(
                value=sanitize_html(", ".join(str(c) for c in book.categories[:6]))
            )
        )
    lines.append(get_text("book_format", lang).format(emoji=get_format_emoji(fmt), value=format_extension(fmt, lang)))
    if book.file_size:
        lines.append(get_text("book_size", lang).format(value=format_file_size(book.file_size, lang)))
    if len(book.formats) > 1:
        lines.append(get_text("book_formats", lang).format(value=", ".join(sorted(f.upper() for f in book.formats))))
    if book.downloads:
        lines.append(get_text("book_downloads", lang).format(value=book.downloads))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Message helpers
# --------------------------------------------------------------------------

async def _edit_or_send(message: Message, text: str, reply_markup=None) -> None:
    try:
        if message.caption is not None:
            await message.edit_caption(caption=text, reply_markup=reply_markup)
        else:
            await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        try:
            await message.answer(text, reply_markup=reply_markup)
        except Exception:
            pass


def _find_book(book_id: str) -> Optional[Book]:
    """Resolve a book id across sessions, the registry and favorites."""
    book = sessions.find_book(book_id)
    if book is not None:
        return book
    book = registry.get(book_id)
    if book is not None:
        return book
    return None


async def show_book_detail(
    message: Message,
    book: Book,
    user_id: int,
    lang: Optional[str] = None,
    try_photo: bool = True,
) -> None:
    """Render a book's details, cover (if possible) and action buttons."""
    is_favorite = userdata.has_favorite(user_id, book.id)
    prev_cb, next_cb, back_cb = _detail_nav(user_id, book)
    caption = build_book_caption(book, lang)
    kb = book_detail_keyboard(
        book, lang, is_favorite=is_favorite, prev_cb=prev_cb, next_cb=next_cb, back_callback=back_cb
    )

    if try_photo and book.cover_url:
        try:
            await message.answer_photo(photo=book.cover_url, caption=caption, reply_markup=kb)
            try:
                await message.delete()
            except Exception:
                pass
            return
        except Exception:
            pass

    await _edit_or_send(message, caption, kb)


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    lang = _user_lang(message.from_user)
    send_home, _ = _features()
    await send_home(message, lang=lang, user_id=user_id)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    lang = _user_lang(message.from_user)
    _, send_help_index = _features()
    await send_help_index(message, lang)


@router.message(F.text.lower() == "help")
async def cmd_help_text(message: Message) -> None:
    lang = _user_lang(message.from_user)
    _, send_help_index = _features()
    await send_help_index(message, lang)


@router.message(F.text.lower().in_({"menu", "start", "main"}))
async def cmd_menu_text(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    lang = _user_lang(message.from_user)
    send_home, _ = _features()
    await send_home(message, lang=lang, user_id=user_id)


@router.message(Command("language"))
async def cmd_language(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    lang = _user_lang(message.from_user)
    current = preferences.get_language(user_id)
    if current:
        text = get_text("language_title_with", lang).format(name=language_name(current))
    else:
        text = get_text("language_title", lang) + "\n\n" + get_text("language_description", lang)
    await message.answer(text, reply_markup=language_keyboard(current, lang))


@router.callback_query(F.data == "lang:menu")
async def callback_language_menu(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    lang = _user_lang(callback.from_user)
    current = preferences.get_language(user_id)
    text = get_text("language_title", lang) + "\n\n" + get_text("language_description", lang)
    await callback.message.edit_text(text, reply_markup=language_keyboard(current, lang))
    await safe_answer(callback)


@router.callback_query(F.data.startswith("lang:set:"))
async def callback_language_set(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    code = callback.data.split(":", 2)[-1].lower()
    if code not in {c for c, _, _ in LANGUAGES}:
        await safe_answer(callback)
        return
    preferences.set_language(user_id, code)
    name = language_name(code)
    lang = code
    text = (
        get_text("language_title_with", lang).format(name=name)
        + "\n\n"
        + get_text("language_set", lang).format(name=name)
    )
    await callback.message.edit_text(text, reply_markup=language_keyboard(code, lang))
    await safe_answer(callback)


@router.callback_query(F.data == "lang:clear")
async def callback_language_clear(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    preferences.set_language(user_id, None)
    text = get_text("language_title", None) + "\n\n" + get_text("language_cleared", None)
    await callback.message.edit_text(text, reply_markup=language_keyboard(None, None))
    await safe_answer(callback)


@router.message(Command("search"))
async def cmd_search_command(message: Message, command: CommandObject) -> None:
    await _do_search(message, (command.args or "").strip())


@router.message(F.text)
async def handle_text(message: Message) -> None:
    text = (message.text or "").strip()
    if text.startswith("/") or not text:
        return
    await _do_search(message, text)


async def _do_search(
    message: Message,
    query: str,
    user: Optional[types.User] = None,
    user_id: Optional[int] = None,
) -> None:
    user = user or message.from_user
    if user_id is None:
        user_id = user.id if user else 0
    lang = _user_lang(user)
    language = preferences.get_language(user_id)

    if not query or len(query) < 2:
        await message.answer(get_text("search_short_query", lang))
        return
    if len(query) > 200:
        await message.answer(get_text("search_query_too_long", lang))
        return

    field = "title"
    if query.lower().startswith("author:"):
        query = query[len("author:"):].strip()
        field = "author"
    elif query.lower().startswith("isbn:"):
        query = query[len("isbn:"):].strip()
        field = "isbn"

    sent = await message.answer(get_text("search_loading", lang).format(query=sanitize_html(query)))
    try:
        books, total = await asyncio.wait_for(
            source_router.search(query, per_page=100, field=field, language=language), timeout=60
        )
    except Exception as e:
        log.error("Search failed for '%s': %s", query, e)
        try:
            await sent.edit_text(get_text("search_failed", lang))
        except TelegramBadRequest:
            pass
        return

    if not books:
        await sent.edit_text(get_text("search_no_results", lang).format(query=sanitize_html(query)))
        return

    registry.put_many(books)
    userdata.add_history(user_id, {"type": "search", "query": query, "ts": time.time()})
    per_page = int(userdata.get_setting(user_id, "per_page", PAGE_SIZE) or PAGE_SIZE)

    sessions.put(
        user_id,
        SearchSession(query=query, results=books, total=total, page=1, language=language),
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    filter_suffix = f" \u00b7 {language_flag(language)} <i>{language_name(language)}</i>" if language else ""
    text = get_text("search_results_header", lang).format(
        total=total,
        word=pluralize(total, lang),
        query=sanitize_html(query),
        filter=filter_suffix,
    )
    await _edit_or_send(sent, text, book_list_keyboard(books[:per_page], 1, total_pages, lang))


@router.callback_query(F.data.startswith("search:page:"))
async def callback_search_page(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    lang = _user_lang(callback.from_user)
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        await safe_answer(callback)
        return

    session = sessions.get(user_id)
    if session is None:
        await safe_answer(callback, get_text("search_expired", lang), show_alert=True)
        return

    per_page = int(userdata.get_setting(user_id, "per_page", PAGE_SIZE) or PAGE_SIZE)
    total_pages = max(1, (session.total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    page_books = session.results[start:start + per_page]
    session.page = page
    filter_suffix = (
        f" \u00b7 {language_flag(session.language)} <i>{language_name(session.language)}</i>"
        if session.language else ""
    )
    text = get_text("search_page_header", lang).format(
        total=session.total,
        word=pluralize(session.total, lang),
        query=sanitize_html(session.query),
        filter=filter_suffix,
        page=page,
        total_pages=total_pages,
    )

    if callback.message.caption is not None:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=book_list_keyboard(page_books, page, total_pages, lang))
    else:
        await _edit_or_send(callback.message, text, book_list_keyboard(page_books, page, total_pages, lang))
    await safe_answer(callback)


# --------------------------------------------------------------------------
# Book details
# --------------------------------------------------------------------------

@router.callback_query(F.data.startswith("book:detail:"))
async def callback_book_detail(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    lang = _user_lang(callback.from_user)
    book_id = callback.data.split(":", 2)[-1]
    book = _find_book(book_id)
    if book is None:
        await safe_answer(callback, get_text("book_not_found_recent", lang), show_alert=True)
        return
    await show_book_detail(callback.message, book, user_id, lang)
    await safe_answer(callback)


@router.callback_query(F.data.startswith("fav:toggle:"))
async def callback_favorite_toggle(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    lang = _user_lang(callback.from_user)
    book_id = callback.data.split(":", 2)[-1]
    book = _find_book(book_id) or userdata.get_favorite_book(user_id, book_id)
    if book is None:
        await safe_answer(callback, get_text("book_not_found_recent", lang), show_alert=True)
        return

    if userdata.has_favorite(user_id, book.id):
        userdata.remove_favorite(user_id, book.id)
        await safe_answer(callback, get_text("fav_removed", lang))
    else:
        userdata.add_favorite(user_id, book)
        await safe_answer(callback, get_text("fav_added", lang))

    await show_book_detail(callback.message, book, user_id, lang, try_photo=False)


# --------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------

@router.callback_query(F.data.startswith("download:"))
async def callback_download(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    lang = _user_lang(callback.from_user)
    parts = callback.data.split(":")
    book_id = parts[1] if len(parts) > 1 else ""
    fmt = parts[2] if len(parts) > 2 else None
    book = _find_book(book_id)
    if book is None:
        await safe_answer(callback, get_text("book_not_found_recent", lang), show_alert=True)
        return
    await safe_answer(callback)
    await _download_book(callback.message, book, fmt, user_id=user_id)


@router.message(Command("download"))
async def cmd_download(message: Message, command: CommandObject) -> None:
    lang = _user_lang(message.from_user)
    user_id = message.from_user.id if message.from_user else 0
    book_id = (command.args or "").strip()
    if not book_id:
        await message.answer(get_text("download_usage", lang))
        return
    book = _find_book(book_id)
    if book is None:
        await message.answer(get_text("book_not_found_download", lang))
        return
    await _download_book(message, book, user_id=user_id)


async def _download_book(
    message: Message, book: Book, fmt: Optional[str] = None, user_id: Optional[int] = None
) -> None:
    user = message.from_user
    if user_id is None:
        user_id = user.id if user else 0
    lang = _user_lang(user)

    preferred = userdata.get_setting(user_id, "format")
    if not fmt:
        candidates = {book.extension, *(f.lower() for f in (book.formats or ()))}
        if preferred and (preferred.lower() in candidates or not candidates):
            fmt = preferred.lower()
        else:
            fmt = book.extension
    fmt = (fmt or "epub").lower().lstrip(".")
    title = sanitize_html(book.title)

    userdata.add_history(user_id, {"type": "download", "book_id": book.id, "title": book.title, "ts": time.time()})

    status = await message.answer(get_text("download_start", lang).format(title=title))

    task = asyncio.create_task(source_router.download(book, fmt=fmt))
    bar_len = 14
    started = time.monotonic()
    if userdata.get_setting(user_id, "notifications", True):
        while not task.done():
            await asyncio.sleep(1.5)
            elapsed = time.monotonic() - started
            pct = min(98.0, 100.0 * (1.0 - math.exp(-elapsed / 8.0)))
            filled = round(pct / 100.0 * bar_len)
            bar = "█" * filled + "░" * (bar_len - filled)
            try:
                await status.edit_text(
                    get_text("download_progress", lang).format(title=title, bar=bar, pct=pct)
                )
            except Exception:
                pass
    else:
        await asyncio.wait_for(asyncio.shield(task), timeout=DOWNLOAD_TIMEOUT)

    try:
        data, _ = await asyncio.wait_for(asyncio.shield(task), timeout=DOWNLOAD_TIMEOUT)
    except asyncio.TimeoutError:
        task.cancel()
        await status.edit_text(get_text("download_timed_out", lang))
        return
    except Exception as e:
        log.error("Download error for %s: %s", book.id, e)
        await status.edit_text(get_text("download_failed", lang))
        return

    if data:
        try:
            await status.delete()
        except Exception:
            pass
        await _send_book_file(message, book, data, fmt)
        return

    if book.source == "Z-Library" and book.download_url:
        await status.edit_text(
            get_text("download_zl_fallback", lang).format(url=sanitize_html(book.download_url)),
            disable_web_page_preview=True,
        )
    else:
        await status.edit_text(get_text("download_unavailable", lang))


async def _send_book_file(message: Message, book: Book, data: bytes, fmt: str) -> None:
    lang = _user_lang(message.from_user)
    ext = "." + fmt if fmt and not fmt.startswith(".") else (fmt or ".epub")
    filename = f"{_safe_filename(book.title)}{ext}".replace(" ", "_")
    if len(filename) > 64:
        base, _, e = filename.rpartition(".")
        filename = base[:60] + "." + e

    caption = get_text("download_caption", lang).format(
        title=sanitize_html(book.title),
        author=sanitize_html(book.author or get_text("unknown", lang)),
        fmt=format_extension(fmt, lang),
        size=format_file_size(len(data), lang),
    )
    try:
        await message.answer_document(
            BufferedInputFile(file=data, filename=filename),
            caption=caption,
        )
    except TelegramBadRequest:
        if book.source == "Z-Library" and book.download_url:
            await message.answer(
                get_text("file_too_large_zl", lang).format(url=sanitize_html(book.download_url)),
                disable_web_page_preview=True,
            )
        else:
            await message.answer(get_text("file_too_large", lang))


# --------------------------------------------------------------------------
# Misc callbacks
# --------------------------------------------------------------------------

@router.callback_query(F.data == "close")
async def callback_close(callback: CallbackQuery) -> None:
    lang = _user_lang(callback.from_user)
    user_id = callback.from_user.id if callback.from_user else 0
    try:
        await callback.message.delete()
    except Exception:
        pass
    send_home, _ = _features()
    await send_home(callback.message, lang=lang, user_id=user_id)
    await safe_answer(callback)


@router.callback_query(F.data == "menu:main")
async def callback_menu_main(callback: CallbackQuery) -> None:
    lang = _user_lang(callback.from_user)
    user_id = callback.from_user.id if callback.from_user else 0
    send_home, _ = _features()
    await send_home(callback.message, lang=lang, user_id=user_id, edit=True)
    await safe_answer(callback)


@router.callback_query(F.data == "ignore")
async def callback_ignore(callback: CallbackQuery) -> None:
    await safe_answer(callback)
