from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from aiogram.types import Message
from loguru import logger

from bot.utils.i18n import get_text

_search_queries: dict[int, str] = {}


def is_real_file(data: bytes, expected_format: str) -> bool:
    MAGIC = {
        "epub": b"PK",
        "pdf": b"%PDF",
        "mobi": b"BOOKMOBI",
        "azw3": b"BOOKMOBI",
        "djvu": b"AT&T",
        "fb2": b"<?xml",
    }
    magic = MAGIC.get(expected_format.lower())
    if magic is None:
        return True
    if expected_format.lower() in ("mobi", "azw3"):
        return b"BOOKMOBI" in data[:256]
    return len(data) >= len(magic) and data[:len(magic)] == magic


def set_search_query(user_id: int, query: str) -> None:
    if len(_search_queries) > 1000:
        _search_queries.clear()
    _search_queries[user_id] = query


def get_search_query(user_id: int) -> str:
    if user_id in _search_queries:
        return _search_queries[user_id]
    try:
        from bot.services.search import search_service
        sess = search_service.get_session(user_id)
        if sess and sess.query:
            return sess.query
    except Exception:
        pass
    return ""


def format_file_size(size_bytes: Optional[int]) -> str:
    if size_bytes is None:
        return "Unknown"
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def format_date(dt: Optional[datetime]) -> str:
    if dt is None:
        return "N/A"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%b %d, %Y")


def truncate_text(text: Optional[str], max_length: int = 200) -> str:
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def sanitize_html(text: Optional[str]) -> str:
    if not text:
        return ""
    replacements = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def extract_command_args(message: Message) -> Optional[str]:
    if not message.text:
        return None
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1:
        return parts[1].strip()
    return None


def calculate_pages(total: int, per_page: int) -> int:
    return max(1, math.ceil(total / per_page))


def validate_search_query(query: str) -> bool:
    if not query or len(query.strip()) < 2:
        return False
    if len(query) > 200:
        return False
    if re.search(r"[<>{}|\\^~`]", query):
        return False
    return True


def build_book_caption(book_data: Dict[str, Any]) -> str:
    title = sanitize_html(book_data.get("title", "Unknown"))
    author = sanitize_html(book_data.get("author", "Unknown Author"))
    description = truncate_text(sanitize_html(book_data.get("description", "")), 300)
    publisher = sanitize_html(book_data.get("publisher", "N/A"))
    year = book_data.get("publication_year", "N/A")
    pages = book_data.get("pages", "N/A")
    language = sanitize_html(book_data.get("language", "N/A")) or "N/A"
    file_size = format_file_size(book_data.get("file_size"))
    downloads = book_data.get("download_count", 0)
    category = sanitize_html(str(book_data.get("category", "N/A")))

    caption = (
        f"<b>{title}</b>\n"
        f"<i>by {author}</i>\n\n"
        f"{description}\n\n"
        f"📋 <b>Details:</b>\n"
        f"• <b>Publisher:</b> {publisher}\n"
        f"• <b>Year:</b> {year}\n"
        f"• <b>Pages:</b> {pages}\n"
        f"• <b>Language:</b> {language}\n"
        f"• <b>Size:</b> {file_size}\n"
        f"• <b>Category:</b> {category}\n"
        f"• <b>Downloads:</b> {downloads:,}"
    )
    return caption


def build_book_message(book: Any, lang: Optional[str] = None) -> str:
    title = sanitize_html(getattr(book, "title", "Unknown"))
    author = sanitize_html(getattr(book, "author", "Unknown Author"))
    description = truncate_text(sanitize_html(getattr(book, "description", "")), 300)
    publisher = sanitize_html(getattr(book, "publisher", "N/A"))
    year = getattr(book, "publication_year", "N/A")
    pages = getattr(book, "pages", "N/A")
    language = sanitize_html(getattr(book, "language", "N/A")) or "N/A"
    file_ext = getattr(book, "file_extension", None) or ""
    file_size = format_file_size(getattr(book, "file_size", None))
    downloads = getattr(book, "download_count", 0)
    category = sanitize_html(str(getattr(getattr(book, "category", None), "name", "N/A")))
    isbn = sanitize_html(getattr(book, "isbn", "N/A")) or "N/A"
    fmt_emoji = get_format_emoji(file_ext)
    fmt_name = format_extension(file_ext)

    caption = (
        f"{get_text('book_detail_header', lang).format(title=title, author=author, description=description)}\n\n"
        f"{get_text('book_detail_section', lang)}\n"
        f"{get_text('book_detail_publisher', lang).format(value=publisher)}\n"
        f"{get_text('book_detail_year', lang).format(value=year)}\n"
        f"{get_text('book_detail_pages', lang).format(value=pages)}\n"
        f"{get_text('book_detail_isbn', lang).format(value=isbn)}\n"
        f"{get_text('book_detail_language', lang).format(value=language)}\n"
        f"{get_text('book_detail_format', lang).format(emoji=fmt_emoji, value=fmt_name)}\n"
        f"{get_text('book_detail_size', lang).format(value=file_size)}\n"
        f"{get_text('book_detail_category', lang).format(value=category)}\n"
        f"{get_text('book_detail_downloads', lang).format(count=f'{downloads:,}')}"
    )
    return caption


LANGUAGES = [
    ("english", "English", "\U0001f1ec\U0001f1e7"),
    ("russian", "Russian", "\U0001f1f7\U0001f1fa"),
    ("german", "German", "\U0001f1e9\U0001f1ea"),
    ("french", "French", "\U0001f1eb\U0001f1f7"),
    ("spanish", "Spanish", "\U0001f1ea\U0001f1f8"),
    ("italian", "Italian", "\U0001f1ee\U0001f1f9"),
    ("portuguese", "Portuguese", "\U0001f1f5\U0001f1f9"),
    ("chinese", "Chinese", "\U0001f1e8\U0001f1f3"),
    ("japanese", "Japanese", "\U0001f1ef\U0001f1f5"),
    ("arabic", "Arabic", "\U0001f1e6\U0001f1ea"),
    ("hindi", "Hindi", "\U0001f1ee\U0001f1f3"),
    ("korean", "Korean", "\U0001f1f0\U0001f1f7"),
    ("dutch", "Dutch", "\U0001f1f3\U0001f1f1"),
    ("polish", "Polish", "\U0001f1f5\U0001f1f1"),
    ("turkish", "Turkish", "\U0001f1f9\U0001f1f7"),
]


def language_flag(lang: str) -> str:
    for code, name, flag in LANGUAGES:
        if lang == code or lang.lower() == name.lower():
            return flag
    return "\U0001f310"


FORMAT_EMOJIS: Dict[str, str] = {
    "pdf": "\U0001f4c4",
    "epub": "\U0001f4d6",
    "mobi": "\U0001f4f1",
    "azw3": "\U0001f4f1",
    "fb2": "\U0001f4c3",
    "djvu": "\U0001f4dc",
    "txt": "\U0001f4dd",
    "doc": "\U0001f4cb",
    "docx": "\U0001f4cb",
    "rtf": "\U0001f4c3",
    "cbz": "\U0001f4da",
    "cbr": "\U0001f4da",
    "zip": "\U0001f5dc\ufe0f",
    "rar": "\U0001f5dc\ufe0f",
}


def get_format_emoji(file_extension: Optional[str]) -> str:
    if not file_extension:
        return "\U0001f4c1"
    ext = file_extension.lower().strip().lstrip(".")
    return FORMAT_EMOJIS.get(ext, "\U0001f4c1")


def format_extension(file_extension: Optional[str]) -> str:
    if not file_extension:
        return "Unknown"
    return file_extension.lower().strip().lstrip(".").upper()


async def safe_edit_or_send(message: Message, text: str, reply_markup=None, parse_mode: str = "HTML") -> None:
    try:
        if message.caption is not None:
            await message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)


def sanitize_input(text: str, max_length: int = 200) -> Optional[str]:
    if not text or not text.strip():
        return None
    text = text.strip()[:max_length]
    text = re.sub(r"[<>{}\\\^~`]", "", text)
    return text


def validate_page(page: int, total_pages: int) -> int:
    return max(1, min(page, total_pages))



