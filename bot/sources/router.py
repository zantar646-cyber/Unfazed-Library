from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from bot.services.api import BookResult
from bot.sources.annas_archive import FORMAT_PRIORITY, AnnasArchiveBook, annas_archive
from bot.sources.dedup import deduplicate_results, rank_results
from bot.sources.zlibrary import zlibrary

# Maximum number of ZL pages to fetch for instant responsiveness.
# Page 1 alone returns up to 100 books (10 full Telegram pages).
MAX_SEARCH_PAGES = 2
# Limit concurrent ZL page fetches to avoid overwhelming the API.
ZL_FETCH_CONCURRENCY = 2


class SourceRouter:
    """Orchestrates multi-source book search and download.

    Supports instant initial batch returns with progressive background enrichment.
    """

    async def search_first_batch(
        self,
        query: str,
        per_page: int = 50,
        language: Optional[str] = None,
    ) -> Tuple[list, int]:
        """Fetch Page 1 immediately (~0.5s) to display to the user without waiting."""
        t0 = time.monotonic()
        first, total = await self._try_zl_search(query, 1, per_page, language)
        if not first:
            # Fallback if ZL is empty: try Anna's Archive quickly
            aa_results, aa_total = await self._try_annas_search(query, 1, per_page)
            if aa_results:
                for r in aa_results:
                    r._source = "Anna's Archive"
                ranked = rank_results(deduplicate_results(aa_results), query)
                return ranked, len(ranked)
            return [], 0

        for r in first:
            r._source = "Z-Library"

        deduped = deduplicate_results(first)
        ranked = rank_results(deduped, query)
        elapsed = time.monotonic() - t0
        logger.info(
            f"Search first-batch '{query}': {len(ranked)} books in {elapsed:.3f}s (reported total={total})"
        )
        return ranked, total

    async def search_more_batches(
        self,
        query: str,
        per_page: int = 50,
        language: Optional[str] = None,
        existing: Optional[list] = None,
        max_pages: int = 4,
    ) -> list:
        """Fetch remaining batches in the background to enrich the user's session."""
        t0 = time.monotonic()
        existing_list = list(existing or [])

        async def _fetch_aa():
            try:
                async with asyncio.timeout(3.0):
                    res, _ = await self._try_annas_search(query, 1, per_page)
                    for r in res:
                        r._source = "Anna's Archive"
                    return res
            except Exception as e:
                logger.debug(f"Background AA fetch failed: {e}")
                return []

        async def _fetch_zl_remaining():
            more_zl: list = []
            sem = asyncio.Semaphore(ZL_FETCH_CONCURRENCY)

            async def _fetch_page(p: int) -> list:
                async with sem:
                    more, _ = await self._try_zl_search(query, p, per_page, language)
                    for r in more:
                        r._source = "Z-Library"
                    return more or []

            tasks = [_fetch_page(p) for p in range(2, max_pages + 1)]
            for coro in asyncio.as_completed(tasks):
                try:
                    more_zl.extend(await coro)
                except Exception as e:
                    logger.debug(f"Background ZL page fetch failed: {e}")
            return more_zl

        async def _fetch_openlibrary():
            try:
                from bot.sources.openlibrary import OpenLibrarySource
                async with asyncio.timeout(3.5):
                    res, _ = await OpenLibrarySource().search(query, per_page=15, language=language)
                    return res
            except Exception as e:
                logger.debug(f"Background OpenLibrary fetch failed: {e}")
                return []

        async def _fetch_libgen():
            try:
                from bot.sources.libgen import LibGenSource
                async with asyncio.timeout(3.5):
                    res, _ = await LibGenSource().search(query, per_page=15, language=language)
                    return res
            except Exception as e:
                logger.debug(f"Background LibGen fetch failed: {e}")
                return []

        aa_results, zl_results, ol_results, lg_results = await asyncio.gather(
            _fetch_aa(), _fetch_zl_remaining(), _fetch_openlibrary(), _fetch_libgen(), return_exceptions=True
        )
        aa_list = aa_results if isinstance(aa_results, list) else []
        zl_list = zl_results if isinstance(zl_results, list) else []
        ol_list = ol_results if isinstance(ol_results, list) else []
        lg_list = lg_results if isinstance(lg_results, list) else []

        combined = existing_list + zl_list + aa_list + ol_list + lg_list
        deduped = deduplicate_results(combined)
        ranked = rank_results(deduped, query)
        elapsed = time.monotonic() - t0
        logger.info(
            f"Search more-batches '{query}': {len(existing_list)} existing + {len(zl_list)} ZL + {len(aa_list)} AA + {len(ol_list)} OL + {len(lg_list)} LG "
            f"-> {len(ranked)} total unique in {elapsed:.3f}s"
        )
        return ranked

    async def search_books(
        self,
        query: str,
        page: int = 1,
        per_page: int = 10,
        language: Optional[str] = None,
    ) -> Tuple[list, int]:
        """Fetch, deduplicate, rank and return books for query."""
        return await self.search_first_batch(query, per_page=per_page, language=language)

    async def _try_zl_search(
        self, query: str, page: int, per_page: int, language: Optional[str]
    ) -> Tuple[list, int]:
        """Fetch a single page of Z-Library results."""
        try:
            return await zlibrary.search(query, page=page, per_page=per_page, language=language)
        except Exception as e:
            logger.error(f"ZL search failed (page={page}): {e}")
            return [], 0

    async def _try_zl_search_all(
        self, query: str, per_page: int, language: Optional[str]
    ) -> Tuple[list, int]:
        """Fetch ALL available pages from Z-Library and return combined results.

    1. Fetch page 1 → learn the API's reported total.
    2. Fetch remaining pages concurrently (up to MAX_SEARCH_PAGES).
    3. Return everything collected.
    """
        t0 = time.monotonic()

        # Step 1: first page to get the total
        first, total = await self._try_zl_search(query, 1, per_page, language)
        if not first:
            return [], 0

        # Fast path: 1 page of 100 results already provides 10 Telegram pages!
        # If we have at least 20 books or total <= len(first), return immediately.
        if len(first) >= 20 or total <= len(first):
            elapsed = time.monotonic() - t0
            logger.info(f"ZL search fast-return: {len(first)} results in {elapsed:.2f}s")
            return first, total

        all_results: list = list(first)
        total_pages = (total + per_page - 1) // per_page
        pages_to_fetch = min(total_pages, MAX_SEARCH_PAGES)

        logger.info(
            f"ZL search: total={total}, per_page={per_page}, "
            f"total_pages={total_pages}, fetching={pages_to_fetch}, "
            f"first_page={len(first)} results"
        )

        if pages_to_fetch <= 1:
            elapsed = time.monotonic() - t0
            logger.info(f"ZL search single-page: {len(all_results)} results in {elapsed:.2f}s")
            return all_results, total

        # Step 2: fetch remaining pages with bounded concurrency
        sem = asyncio.Semaphore(ZL_FETCH_CONCURRENCY)

        async def _fetch(p: int) -> list:
            async with sem:
                more, _ = await self._try_zl_search(query, p, per_page, language)
                return more or []

        tasks = [_fetch(p) for p in range(2, pages_to_fetch + 1)]

        # as_completed so partial failures don't block progress
        for coro in asyncio.as_completed(tasks):
            try:
                more = await coro
                all_results.extend(more)
            except Exception as e:
                logger.warning(f"ZL async page fetch failed: {e}")

        elapsed = time.monotonic() - t0
        logger.info(
            f"ZL search multi-page: {pages_to_fetch} pages requested, "
            f"{len(all_results)} results collected in {elapsed:.2f}s"
        )
        return all_results, total

    async def _try_annas_search(self, query: str, page: int = 1, per_page: int = 10) -> Tuple[list, int]:
        try:
            aa_results = await annas_archive.search(query, page=page, per_page=per_page)
            if not aa_results:
                return [], 0
            book_results = [self._aa_to_book_result(b) for b in aa_results]
            book_results = [b for b in book_results if b.title and b.title != "Unknown"]
            return book_results, len(book_results)
        except Exception as e:
            logger.warning(f"AA search threw exception: {e}")
            return [], 0

    def _aa_to_book_result(self, aa_book: AnnasArchiveBook) -> BookResult:
        ext = (aa_book.extension or "").lower().lstrip(".")
        return BookResult(
            id=aa_book.id or aa_book.md5 or "",
            title=aa_book.title or "Unknown",
            author=aa_book.author,
            description=aa_book.description,
            publisher=aa_book.publisher,
            publication_year=aa_book.publication_year,
            isbn=aa_book.isbn,
            file_size=aa_book.file_size,
            cover_url=aa_book.cover_url,
            language=aa_book.language,
            pages=aa_book.pages,
            extension=ext,
            download_url=aa_book.download_urls[0] if aa_book.download_urls else None,
            zlibrary_id=None,
            download_count=0,
        )

    async def download_book(
        self,
        book_id: str,
        download_url: str,
        fmt: str = "epub",
        file_token: Optional[str] = None,
    ) -> Tuple[Optional[bytes], Optional[str]]:
        # Z-Library first (fast HTTP with cookies, preferred over slow AA)
        data = await self._try_zl_download(book_id, download_url, fmt, file_token)
        if data:
            return data, "Z-Library"

        logger.info(f"ZL download failed for {book_id}, trying AA fallback")
        data = await self._try_aa_download(book_id, fmt)
        if data:
            return data, "Anna's Archive"

        return None, None

    async def _try_aa_download(self, book_id: str, fmt: str = "epub") -> Optional[bytes]:
        try:
            async with asyncio.timeout(30):
                links = await annas_archive.get_download_links(book_id)
                if not links:
                    logger.warning(f"AA no download links for {book_id}")
                    return None

                for link in links:
                    data = await annas_archive.download(link, expected_format=fmt)
                    if data:
                        return data
                return None
        except asyncio.TimeoutError:
            logger.warning(f"AA download timed out for {book_id}")
            return None
        except Exception as e:
            logger.warning(f"AA download threw exception: {e}")
            return None

    async def _try_zl_download(
        self,
        book_id: str,
        download_url: str,
        fmt: str = "epub",
        file_token: Optional[str] = None,
    ) -> Optional[bytes]:
        try:
            data = await zlibrary.download(download_url, fmt=fmt, file_token=file_token)
            return data
        except Exception as e:
            logger.warning(f"ZL download threw exception: {e}")
            return None

    async def fetch_book(self, query: str) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
        logger.info(f"Router fetch_book: '{query}'")

        result = await annas_archive.search(query)
        if result:
            best = self._select_best_match(result)
            details = await annas_archive.get_book_details(best.id)
            if details:
                for link in details.download_urls:
                    data = await annas_archive.download(link, expected_format=(details.extension or "epub"))
                    if data:
                        ext = details.extension or "epub"
                        filename = f"{best.title}.{ext}".replace(" ", "_")
                        return data, filename, "Anna's Archive"

        logger.info(f"AA failed for '{query}', trying Z-Library")
        try:
            zl_result = await zlibrary.get_best_match(query)
            if zl_result and zl_result.download_url:
                data = await zlibrary.download(
                    zl_result.download_url,
                    fmt=zl_result.extension or "epub",
                    alt_url=zl_result.read_online_url,
                    file_token=zl_result.file_token,
                )
                if data:
                    ext = zl_result.extension or "epub"
                    filename = f"{zl_result.title}.{ext}".replace(" ", "_")
                    return data, filename, "Z-Library"
        except Exception as e:
            logger.error(f"ZL fetch_book failed: {e}")

        return None, None, None

    @staticmethod
    def _select_best_match(books: List[AnnasArchiveBook]) -> AnnasArchiveBook:
        def sort_key(b: AnnasArchiveBook) -> tuple:
            ext = (b.extension or "").lower().lstrip(".")
            fmt_priority = FORMAT_PRIORITY.get(ext, 99)
            size = b.file_size or 0
            return (fmt_priority, -size)

        books_sorted = sorted(books, key=sort_key)
        return books_sorted[0] if books_sorted else books[0]


source_router = SourceRouter()


async def search_first_batch(query: str, per_page: int = 50, language: Optional[str] = None):
    return await source_router.search_first_batch(query, per_page=per_page, language=language)


async def search_more_batches(query: str, per_page: int = 50, language: Optional[str] = None, existing: Optional[list] = None, max_pages: int = 4):
    return await source_router.search_more_batches(query, per_page=per_page, language=language, existing=existing, max_pages=max_pages)

