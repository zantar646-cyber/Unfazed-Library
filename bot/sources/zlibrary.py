from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from bot.services.api import BookResult, api


class ZLibraryError(Exception):
    pass


class ZLibrarySource:
    async def search(
        self,
        query: str,
        field: str = "title",
        page: int = 1,
        per_page: int = 10,
        language: Optional[str] = None,
    ) -> Tuple[List[BookResult], int]:
        logger.info(f"ZL search: query='{query}' field={field} page={page}")
        try:
            results, total = await api.search_books(
                query, field=field, page=page, per_page=per_page, language=language
            )
            logger.info(f"ZL search returned {len(results)} results (total={total})")
            return results, total
        except Exception as e:
            logger.error(f"ZL search failed: {e}")
            raise ZLibraryError(f"Search failed: {e}") from e

    async def get_book(self, book_id: str) -> Optional[BookResult]:
        logger.info(f"ZL get_book: id={book_id}")
        try:
            return await api.get_book(book_id)
        except Exception as e:
            logger.error(f"ZL get_book failed: {e}")
            return None

    async def download(
        self,
        url: str,
        fmt: str = "epub",
        alt_url: Optional[str] = None,
        file_token: Optional[str] = None,
    ) -> Optional[bytes]:
        logger.info(f"ZL download: url={url[:80]}... fmt={fmt}")
        try:
            data = await api.download_file(url, fmt=fmt, alt_url=alt_url, file_token=file_token)
            if data:
                logger.success(f"ZL download: {len(data)} bytes")
                return data
            logger.warning("ZL download returned no data")
            return None
        except Exception as e:
            logger.error(f"ZL download failed: {e}")
            return None

    async def get_best_match(
        self, query: str, preferred_format: str = "epub"
    ) -> Optional[BookResult]:
        results, _ = await self.search(query, page=1, per_page=20)

        exact_matches = [r for r in results if query.lower() in (r.title or "").lower()]
        if exact_matches:
            results = exact_matches

        def sort_key(book: BookResult) -> tuple:
            ext = (book.extension or "").lower().lstrip(".")
            fmt_priority = 0 if ext == preferred_format else (1 if ext == "pdf" else 2)
            size = book.file_size or 0
            return (fmt_priority, -size)

        results.sort(key=sort_key)
        return results[0] if results else None


zlibrary = ZLibrarySource()
