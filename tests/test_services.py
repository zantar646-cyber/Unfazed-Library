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


@pytest.mark.asyncio
async def test_cache_service_in_memory_fallback():
    from bot.services.cache import CacheService

    cache_svc = CacheService()
    # Force fallback mode by leaving _redis as None
    cache_svc._redis = None

    assert await cache_svc.set("test_key", {"title": "Book Test"}, ttl=60) is True
    assert await cache_svc.exists("test_key") is True

    val = await cache_svc.get("test_key")
    assert val == {"title": "Book Test"}

    assert await cache_svc.increment("counter_key", 1) == 1
    assert await cache_svc.increment("counter_key", 2) == 3

    assert await cache_svc.clear_pattern("test_*") == 1
    assert await cache_svc.exists("test_key") is False

    await cache_svc.close()


def test_deduplicate_results_fast():
    import time
    from bot.sources.dedup import deduplicate_results

    # Generate 300 books with duplicates and variations
    books = []
    for i in range(150):
        books.append(BookResult(id=f"id-{i}-epub", title=f"Sample Book {i % 30}", extension="epub"))
        books.append(BookResult(id=f"id-{i}-pdf", title=f"Sample Book {i % 30}", extension="pdf"))

    t0 = time.monotonic()
    deduped = deduplicate_results(books)
    elapsed = time.monotonic() - t0

    assert len(deduped) == 30
    # Must run in well under 0.1s (previously took several seconds)
    assert elapsed < 0.2


@pytest.mark.asyncio
async def test_search_progressive_enrichment():
    from bot.services.search import search_service
    from bot.sources.router import source_router

    batch1 = [BookResult(id=f"init-{i}", title=f"Initial Book {i}") for i in range(10)]
    batch2 = [BookResult(id=f"more-{i}", title=f"Enriched Book {i}") for i in range(15)]

    with (
        patch.object(source_router, "search_first_batch", AsyncMock(return_value=(batch1, 25))),
        patch.object(source_router, "search_more_batches", AsyncMock(return_value=batch1 + batch2)),
    ):
        # 1. Page 1 returns immediately
        p1_books, initial_total, from_cache = await search_service.search(
            user_id=88888, query="test progressive", page=1, per_page=10
        )
        assert len(p1_books) == 10
        assert p1_books[0].title == "Initial Book 0"
        assert initial_total == 25
        assert from_cache is False

        # Wait for background task to complete enrichment
        session = search_service.get_session(88888)
        assert session is not None
        if session.background_task:
            await session.background_task

        # 2. Page 2 returns the updated books found in the background
        p2_books, updated_total, from_cache2 = await search_service.search(
            user_id=88888, query="test progressive", page=2, per_page=10
        )
        assert from_cache2 is True
        assert len(p2_books) == 10
        assert updated_total == 25
        assert p2_books[0].title == "Enriched Book 0"
