"""bot/handlers/reader.py — In-Telegram chapter-by-chapter reader (feature #11)."""
from __future__ import annotations

import html
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from bot.database.models import User as DBUser
from bot.database.service import db
from bot.services.api import api
from bot.sources.router import source_router
from bot.utils.browser_downloader import BROWSER_AVAILABLE, try_browser_download
from bot.utils.epub_reader import extract_chapters_from_epub, paginate_text
from bot.utils.helpers import is_real_file, safe_edit_or_send, sanitize_html

router = Router()

READER_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "reader_cache"
READER_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# In-memory cache for loaded chapters: book_id -> list of (title, [pages])
_READER_CACHE: Dict[str, List[Tuple[str, List[str]]]] = {}


def _reader_keyboard(
    book_id: str,
    chapter_idx: int,
    page_idx: int,
    total_pages: int,
    total_chapters: int,
    read_online_url: Optional[str] = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    # Page navigation
    page_nav = []
    if page_idx > 0:
        page_nav.append(
            InlineKeyboardButton(text="◀️ Prev Page", callback_data=f"read:{book_id}:{chapter_idx}:{page_idx - 1}")
        )
    page_nav.append(InlineKeyboardButton(text=f"Pg {page_idx + 1}/{total_pages}", callback_data="ignore"))
    if page_idx < total_pages - 1:
        page_nav.append(
            InlineKeyboardButton(text="Next Page ▶️", callback_data=f"read:{book_id}:{chapter_idx}:{page_idx + 1}")
        )
    builder.row(*page_nav)

    # Chapter navigation
    chap_nav = []
    if chapter_idx > 0:
        chap_nav.append(
            InlineKeyboardButton(text="⏮ Prev Chap", callback_data=f"read:{book_id}:{chapter_idx - 1}:0")
        )
    chap_nav.append(InlineKeyboardButton(text=f"Ch {chapter_idx + 1}/{total_chapters}", callback_data="ignore"))
    if chapter_idx < total_chapters - 1:
        chap_nav.append(
            InlineKeyboardButton(text="Next Chap ⏭", callback_data=f"read:{book_id}:{chapter_idx + 1}:0")
        )
    builder.row(*chap_nav)

    action_row = []
    if read_online_url and read_online_url.startswith("http"):
        action_row.append(InlineKeyboardButton(text="🌐 Web Reader", url=read_online_url))
    action_row.append(InlineKeyboardButton(text="⬅️ Back to Book", callback_data=f"book:detail:{book_id}"))
    builder.row(*action_row)

    return builder.as_markup()


def _web_reader_fallback_keyboard(book_id: str, read_online_url: Optional[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if read_online_url and read_online_url.startswith("http"):
        builder.row(InlineKeyboardButton(text="🌐 Open in Web Reader (Instant)", url=read_online_url))
    builder.row(
        InlineKeyboardButton(text="⬇️ Download Book", callback_data=f"download:{book_id}"),
        InlineKeyboardButton(text="⬅️ Back to Book", callback_data=f"book:detail:{book_id}"),
    )
    return builder.as_markup()


@router.callback_query(F.data.startswith("read:"))
async def callback_read(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("Invalid reader request.", show_alert=True)
        return

    book_id = parts[1]
    chapter_idx = int(parts[2])
    page_idx = int(parts[3])

    book = await db.get_book(book_id)
    if not book:
        await callback.answer("Book not found in database.", show_alert=True)
        return

    cached_data = _READER_CACHE.get(book_id)

    # Check local disk cache
    disk_file = READER_CACHE_DIR / f"{book_id}.epub"
    if not cached_data and disk_file.exists():
        try:
            file_bytes = disk_file.read_bytes()
            raw_chapters = extract_chapters_from_epub(file_bytes)
            if raw_chapters:
                cached_data = []
                for title, full_text in raw_chapters:
                    pages = paginate_text(full_text)
                    cached_data.append((title, pages))
                _READER_CACHE[book_id] = cached_data
                logger.info(f"Loaded {len(cached_data)} chapters from disk cache for {book_id}")
        except Exception as exc:
            logger.warning(f"Error reading disk cache for {book_id}: {exc}")

    # If still not in memory, download file
    if not cached_data:
        file_ext = (getattr(book, "file_extension", "") or "").lower().lstrip(".")
        if file_ext and file_ext not in ("epub", "zip"):
            # Non-EPUB format (e.g. PDF) — provide Web Reader or direct download
            await callback.answer()
            text = (
                f"📖 <b>{sanitize_html(book.title)}</b>\n"
                f"<i>by {sanitize_html(book.author or 'Unknown')}</i>\n\n"
                f"This book is in <b>{file_ext.upper()}</b> format. You can read it directly online via the Web Reader or download the complete file:"
            )
            await safe_edit_or_send(
                callback.message,
                text,
                reply_markup=_web_reader_fallback_keyboard(book.id, book.read_online_url),
            )
            return

        # Notify user we are loading chapters
        await callback.answer("Loading chapters...", show_alert=False)

        file_bytes: Optional[bytes] = None

        # 1. Try download_book via source router (handles ZL with cookies + Anna's Archive fallback)
        if book.download_url:
            try:
                file_bytes, _ = await source_router.download_book(
                    book.external_id or book.id,
                    book.download_url,
                    fmt="epub",
                    file_token=book.file_token,
                )
            except Exception as exc:
                logger.warning(f"source_router.download_book failed for reader: {exc}")

        # 2. Try direct API download
        if not file_bytes and book.download_url:
            try:
                file_bytes = await api.download_file(
                    book.download_url, fmt="epub", file_token=book.file_token
                )
            except Exception as exc:
                logger.warning(f"api.download_file failed for reader: {exc}")

        # 3. Try browser download if Cloudflare protected
        if not file_bytes and book.download_url and BROWSER_AVAILABLE:
            try:
                cookies = {}
                if api._remix_userkey and api._remix_userid:
                    cookies = {"remix_userkey": api._remix_userkey, "remix_userid": api._remix_userid}
                res = await try_browser_download(
                    book.download_url,
                    book.id,
                    alt_url=book.read_online_url,
                    file_token=book.file_token,
                    remix_cookies=cookies,
                )
                if res.success and res.data and is_real_file(res.data, "epub"):
                    file_bytes = res.data
            except Exception as exc:
                logger.warning(f"try_browser_download failed for reader: {exc}")

        # 4. Check if extracted successfully
        if file_bytes:
            try:
                raw_chapters = extract_chapters_from_epub(file_bytes)
                if raw_chapters:
                    cached_data = []
                    for title, full_text in raw_chapters:
                        pages = paginate_text(full_text)
                        cached_data.append((title, pages))
                    _READER_CACHE[book_id] = cached_data
                    disk_file.write_bytes(file_bytes)
                    logger.info(f"Successfully extracted {len(cached_data)} chapters for {book.title}")
            except Exception as exc:
                logger.error(f"Error parsing EPUB for reader: {exc}")

    # If we couldn't parse chapters, gracefully present the Web Reader screen
    if not cached_data:
        text = (
            f"📖 <b>{sanitize_html(book.title)}</b>\n"
            f"<i>by {sanitize_html(book.author or 'Unknown')}</i>\n\n"
            f"⚡ <b>Read Online:</b>\n"
            f"The complete book is available immediately in the official Web Reader. Tap below to read in your browser or Telegram WebApp:"
        )
        await safe_edit_or_send(
            callback.message,
            text,
            reply_markup=_web_reader_fallback_keyboard(book.id, book.read_online_url),
        )
        return

    # Bound indices
    total_chapters = len(cached_data)
    chapter_idx = max(0, min(chapter_idx, total_chapters - 1))
    chap_title, pages = cached_data[chapter_idx]
    total_pages = len(pages)
    page_idx = max(0, min(page_idx, total_pages - 1))

    content = pages[page_idx]
    header = (
        f"📖 <b>{sanitize_html(chap_title)}</b>\n"
        f"<i>Chapter {chapter_idx + 1}/{total_chapters} • Page {page_idx + 1}/{total_pages}</i>\n\n"
    )
    text = header + html.escape(content)

    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=_reader_keyboard(
            book_id,
            chapter_idx,
            page_idx,
            total_pages,
            total_chapters,
            read_online_url=book.read_online_url,
        ),
    )
    try:
        await callback.answer()
    except Exception:
        pass
