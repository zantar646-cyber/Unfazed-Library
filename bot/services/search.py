from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from bot.database.service import db
from bot.sources.router import source_router


CACHE_TTL_SECONDS = 1800  # 30 minutes
BATCH_SIZE = 100  # fetch this many raw results per API page (router paginates internally)
PAGE_SIZE = 10  # results per page shown to the user


@dataclass
class SearchSession:
    query: str
    results: List[Any] = field(default_factory=list)
    total: int = 0
    current_page: int = 1
    timestamp: float = 0.0
    language: Optional[str] = None


class SearchService:
    """Per-user search session cache with instant pagination.

    On the first search for a given user+query, all results are fetched from
    the source router, stored in the database, and cached in memory. Subsequent
    page navigations just slice the cached list — no API calls, no DB queries
    for the book list itself.
    """

    def __init__(self) -> None:
        self._sessions: Dict[int, SearchSession] = {}

    async def search(
        self,
        user_id: int,
        query: str,
        page: int = 1,
        per_page: int = PAGE_SIZE,
        language: Optional[str] = None,
    ) -> Tuple[List[Any], int, bool]:
        """Return a page of search results.

        Returns (page_books, total_count, from_cache).
        from_cache is True when the results came from the session cache
        (i.e. no API calls were made).
        """
        now = time.monotonic()
        session = self._sessions.get(user_id)

        # Cache hit: same query + language, not expired
        if (
            session is not None
            and session.query == query
            and session.language == language
            and (now - session.timestamp) < CACHE_TTL_SECONDS
        ):
            total_pages = max(1, (session.total + per_page - 1) // per_page)
            if page > total_pages:
                logger.warning(
                    f"Page {page} > total_pages {total_pages} "
                    f"(total={session.total}, cached={len(session.results)}) "
                    f"— clamping to page {total_pages}"
                )
                page = total_pages
            start = (page - 1) * per_page
            end = start + per_page

            # ── Defensive slice guard ─────────────────────────────
            # Never slice beyond the actual list length.
            available = len(session.results)
            if start >= available:
                logger.error(
                    f"Slice start {start} >= available results {available} "
                    f"(total={session.total}, page={page}/{total_pages}) — "
                    f"returning empty; session.results was truncated or total was inflated"
                )
                return [], session.total, True

            page_results = session.results[start:end]
            session.current_page = page
            logger.info(
                f"Search cache HIT for user={user_id} query='{query}' "
                f"page={page}/{total_pages} ({len(page_results)} books) "
                f"slice=({start}:{end}) available={available}"
            )
            return page_results, session.total, True

        # Cache miss: fetch fresh results from the source router
        logger.info(
            f"Search cache MISS for user={user_id} query='{query}' "
            f"language={language} — fetching from router"
        )

        try:
            # Router now returns ALL unique books (paginates ZL internally).
            # We pass per_page=BATCH_SIZE as the ZL page size, not a limit.
            results, total = await source_router.search_books(
                query,
                page=1,
                per_page=BATCH_SIZE,
                language=language,
            )
        except Exception as e:
            logger.error(f"Search failed for '{query}': {e}")
            return [], 0, False

        if not results:
            self._sessions[user_id] = SearchSession(
                query=query,
                results=[],
                total=0,
                current_page=1,
                timestamp=now,
                language=language,
            )
            return [], 0, False

        # Store results in the database so they have Book UUIDs
        books = await self._store_search_results(results)

        # ── Consistency guard ─────────────────────────────────────
        # total from the router is the length of the deduped+ranked
        # list we actually hold.  It MUST equal len(books).
        # If the router ever returns a mismatched total, trust the data.
        if total != len(results):
            logger.warning(
                f"Total mismatch: router reported total={total} but "
                f"returned {len(results)} results — correcting to {len(results)}"
            )
            total = len(results)

        if len(books) != len(results):
            logger.warning(
                f"DB storage mismatch: {len(results)} results in, "
                f"{len(books)} books out"
            )

        # Cache the DB Book objects for instant pagination
        self._sessions[user_id] = SearchSession(
            query=query,
            results=books,
            total=total,
            current_page=page,
            timestamp=now,
            language=language,
        )

        # Slice the first page
        start = (page - 1) * per_page
        end = start + per_page
        page_books = books[start:end]
        total_pages = max(1, (total + per_page - 1) // per_page)

        logger.info(
            f"Search completed for '{query}': "
            f"router returned {len(results)} results (total={total}), "
            f"stored {len(books)} books in DB, "
            f"page={page}/{total_pages} ({len(page_books)} books), "
            f"slice=({start}:{end})"
        )
        return page_books, total, False

    def get_session(self, user_id: int) -> Optional[SearchSession]:
        """Get the current search session for a user, or None."""
        return self._sessions.get(user_id)

    def invalidate(self, user_id: int) -> None:
        """Clear cached results for a user (e.g. on new search)."""
        old = self._sessions.pop(user_id, None)
        if old is not None:
            logger.debug(f"Invalidated search cache for user={user_id}")

    async def _store_search_results(self, results) -> List[Any]:
        """Upsert BookResult objects into the database and return Book objects.

        This is identical to the old _store_search_results in user.py but
        lives in the search service so both user.py and book.py can share it.
        """
        stored = []
        for r in results:
            ext_id = str(r.zlibrary_id or r.id)
            source_label = getattr(r, "_source", None)
            book = await db.upsert_book_by_external_id({
                "external_id": ext_id,
                "title": r.title,
                "author": r.author,
                "description": r.description,
                "publisher": r.publisher,
                "publication_year": r.publication_year,
                "isbn": r.isbn,
                "pages": r.pages,
                "language": r.language,
                "file_size": r.file_size,
                "cover_url": r.cover_url,
                "download_url": r.download_url,
                "download_count": r.download_count,
                "file_extension": r.extension,
                "source": source_label,
                "file_token": getattr(r, "file_token", None),
                "read_online_url": getattr(r, "read_online_url", None),
            })
            stored.append(book)
        return stored


search_service = SearchService()
