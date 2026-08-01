from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from bot.services.api import BookResult
from bot.sources.annas_archive import FORMAT_PRIORITY, AnnasArchiveBook, annas_archive
from bot.sources.dedup import deduplicate_results, rank_results
from bot.sources.zlibrary import zlibrary

# Maximum number of ZL pages to fetch (safety cap).
# At BATCH_SIZE=100 this allows up to 5000 results.
MAX_SEARCH_PAGES = 50
# Limit concurrent ZL page fetches to avoid overwhelming the API.
ZL_FETCH_CONCURRENCY = 3


class SourceRouter:
    """Orchestrates multi-source book search and download.

    This class is stateless — all search caching lives in SearchService.
    """

    async def search_books(
        self,
        query: str,
        page: int = 1,
        per_page: int = 10,
        language: Optional[str] = None,
    ) -> Tuple[list, int]:
        """Fetch, deduplicate, rank and return *all* unique books for *query*.

        Unlike the name suggests this ignores *page* — it retrieves every
        available result from Z-Library (paginating internally), combines
        them with Anna's Archive results, deduplicates, ranks, and returns
        the full set.  Callers (SearchService) are responsible for slicing
        into pages for the user.

        Returns (list[BookResult], total_count).
        """
        t0 = time.monotonic()

        # Search both sources concurrently.
        # AA: one-shot fetch (no pagination metadata from AA).
        # ZL: fetch ALL pages so the cache holds the complete dataset.
        aa_task = self._try_annas_search(query, page, per_page)
        zl_task = self._try_zl_search_all(query, per_page, language)

        aa_results, zl_results = await asyncio.gather(aa_task, zl_task, return_exceptions=True)

        if isinstance(aa_results, Exception):
            logger.warning(f"AA search failed for '{query}': {aa_results}")
            aa_results = []
        if isinstance(zl_results, Exception):
            logger.warning(f"ZL search failed for '{query}': {zl_results}")
            zl_results = []

        aa_list, aa_total = aa_results if isinstance(aa_results, tuple) else (aa_results, 0)
        zl_list, zl_total = zl_results if isinstance(zl_results, tuple) else (zl_results, 0)

        if not aa_list and not zl_list:
            logger.warning(f"Both sources returned no results for '{query}'")
            return [], 0

        t1 = time.monotonic()

        # Tag each result with its source
        for r in zl_list:
            r._source = "Z-Library"
        for r in aa_list:
            r._source = "Anna's Archive"

        # Combine all results (keeping duplicates for dedup)
        combined = zl_list + aa_list

        # Deduplicate by normalized title + fuzzy matching
        deduped = deduplicate_results(combined)

        # Rank by relevance to the query
        ranked = rank_results(deduped, query)

        # ── Return the FULL dataset ───────────────────────────────
        # The caller (SearchService) slices into pages for display.
        # NEVER truncate here — doing so causes empty pages later.
        final = ranked  # was: ranked[:per_page]

        # The authoritative total is the number of books we actually
        # have.  ZL's reported total may be larger (unfetched pages)
        # or smaller (AA contributed extra unique books).
        total = len(final)
        elapsed = time.monotonic() - t0
        logger.info(
            f"Search '{query}': {len(aa_list)} AA + {len(zl_list)} ZL "
            f"-> {len(deduped)} unique -> {len(final)} total "
            f"(zl_api_total={zl_total}, ranking={t1-t0:.3f}s, elapsed={elapsed:.3f}s)"
        )

        return final, total

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
