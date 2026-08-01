from __future__ import annotations

from enum import Enum
from typing import Optional, Tuple

from bot.sources.router import source_router


class BookSource(Enum):
    ANNAS_ARCHIVE = "Anna's Archive"
    ZLIBRARY = "Z-Library"


router = source_router


async def fetch_book(query: str) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    return await router.fetch_book(query)


async def search_books(
    query: str, page: int = 1, per_page: int = 10, language: Optional[str] = None
) -> Tuple[list, int]:
    return await router.search_books(query, page=page, per_page=per_page, language=language)


async def download_book(
    book_id: str, download_url: str, fmt: str = "epub", file_token: Optional[str] = None
) -> Tuple[Optional[bytes], Optional[str]]:
    return await router.download_book(book_id, download_url, fmt=fmt, file_token=file_token)
