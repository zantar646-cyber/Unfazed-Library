from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bot.services.api import (
    APIRateLimiter,
    APIResponse,
    BookResult,
    _is_cloudflare_protected,
    CLOUDFLARE_BLOCKED_HOSTS,
)


def test_cloudflare_blocked_hosts():
    assert "z-lib.fm" in CLOUDFLARE_BLOCKED_HOSTS
    assert "reader.z-lib.fm" in CLOUDFLARE_BLOCKED_HOSTS


def test_is_cloudflare_protected_matches_blocked():
    assert _is_cloudflare_protected("https://z-lib.fm/dl/abc123")
    assert _is_cloudflare_protected("https://reader.z-lib.fm/read/something")
    assert _is_cloudflare_protected("https://zlibrary-asia.se/book/123")
    assert _is_cloudflare_protected("http://z-lib.fm/dl/test")


def test_is_cloudflare_protected_subdomain():
    """Subdomains of blocked hosts should also be caught."""
    assert _is_cloudflare_protected("https://cdn.z-lib.fm/dl/file.epub")


def test_is_cloudflare_protected_non_blocked():
    assert not _is_cloudflare_protected("https://example.com/dl/file.pdf")
    assert not _is_cloudflare_protected("https://cdn.other-site.org/book.epub")
    assert not _is_cloudflare_protected("https://google.com")


def test_is_cloudflare_protected_empty():
    assert not _is_cloudflare_protected("")
    assert not _is_cloudflare_protected("not-a-url")


@pytest.mark.asyncio
async def test_rate_limiter():
    limiter = APIRateLimiter(max_calls=5, window=60)
    assert limiter.remaining == 5

    for _ in range(5):
        await limiter.acquire()

    assert limiter.remaining == 0


def test_book_result_creation():
    data = {
        "id": "123",
        "title": "Test Book",
        "author": "Author",
        "description": "A description",
        "publisher": "Publisher",
        "publication_year": 2024,
        "isbn": "978-0-123-45678-9",
        "file_size": 1024,
        "cover_url": "https://example.com/cover.jpg",
        "download_url": "https://example.com/book.pdf",
        "download_count": 10,
        "category": "Fiction",
        "pages": 300,
        "language": "English",
        "rating": 4.5,
    }
    book = BookResult(**data)
    assert book.title == "Test Book"
    assert book.author == "Author"
    assert book.zlibrary_id is None


def test_book_result_with_zlib_id():
    data = {
        "id": "123",
        "title": "Z-Lib Book",
        "author": "Author",
        "description": "Desc",
        "download_count": 5,
    }
    book = BookResult(**data)
    assert book.title == "Z-Lib Book"


def test_api_response():
    response = APIResponse(data={"key": "value"}, cached=True)
    assert response.data["key"] == "value"
    assert response.cached is True

    response2 = APIResponse(data=None)
    assert response2.data is None
    assert response2.cached is False
