from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from bot.database.service import db
from bot.services.cache import cache
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
    background_task: Optional[asyncio.Task] = None
    format_filter: Optional[str] = None


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
        self._cleanup_expired(now)
        session = self._sessions.get(user_id)

        # Cache hit: same query + language, not expired
        if (
            session is not None
            and session.results  # never serve a cached empty result
            and session.query == query
            and session.language == language
            and (now - session.timestamp) < CACHE_TTL_SECONDS
        ):
            # If user clicked Next (page > 1) and background enrichment is running:
            if page > 1 and session.background_task and not session.background_task.done():
                start = (page - 1) * per_page
                # If requested page isn't yet available, wait briefly (up to 1.5s) for background task
                if start >= len(session.results):
                    try:
                        await asyncio.wait_for(asyncio.shield(session.background_task), timeout=1.5)
                    except (asyncio.TimeoutError, Exception):
                        pass

            available = len(session.results)
            total_pages = max(1, (session.total + per_page - 1) // per_page)
            if page > total_pages:
                page = total_pages
            start = (page - 1) * per_page
            end = start + per_page

            # Defensive slice: never slice past actual results
            if start >= available:
                start = max(0, ((available - 1) // per_page) * per_page)
                end = available

            page_results = session.results[start:end]
            session.current_page = page
            logger.info(
                f"Search cache HIT for user={user_id} query='{query}' "
                f"page={page}/{total_pages} ({len(page_results)} books) "
                f"available={available}"
            )
            return page_results, session.total, True

        # Level 2 Cache: Global cross-user cache (shared across all users)
        global_cache_key = f"global_search:{query.lower().strip()}:{language or ''}"
        cached_ids = await cache.get(global_cache_key)
        if cached_ids and isinstance(cached_ids, list):
            db_books = await db.get_books_by_ids(cached_ids)
            if db_books:
                total_cached = len(db_books)
                self._sessions[user_id] = SearchSession(
                    query=query,
                    results=db_books,
                    total=total_cached,
                    current_page=page,
                    timestamp=now,
                    language=language,
                )
                start = (page - 1) * per_page
                end = start + per_page
                logger.info(
                    f"Search global cache HIT for query='{query}' "
                    f"({total_cached} books loaded in 0.001s)"
                )
                return db_books[start:end], total_cached, True

        # Cancel previous background task for this user if still running
        if session and session.background_task and not session.background_task.done():
            session.background_task.cancel()

        # Cache miss: fetch fresh results from the source router
        logger.info(
            f"Search cache MISS for user={user_id} query='{query}' "
            f"language={language} — fetching from router"
        )

        try:
            # 1. Fetch Page 1 immediately (~0.5s)
            results, total_reported = await source_router.search_first_batch(
                query,
                per_page=BATCH_SIZE,
                language=language,
            )
        except Exception as e:
            logger.error(f"Search failed for '{query}': {e}")
            return [], 0, False

        if not results:
            # Do not cache empty results: a transient source outage must not
            # mask retries for the next 30 minutes.
            self._sessions.pop(user_id, None)
            logger.info(f"Search returned no results for '{query}' (not cached)")
            return [], 0, False

        # Store first batch in database
        books = await self._store_search_results(results)

        # Initial total: use API reported total so 'Next' button is immediately active
        initial_total = max(len(books), total_reported)
        new_session = SearchSession(
            query=query,
            results=books,
            total=initial_total,
            current_page=page,
            timestamp=now,
            language=language,
        )
        self._sessions[user_id] = new_session

        # Spawn background enrichment task to discover more books across sources/pages
        if total_reported > len(books) or len(books) < 50:
            new_session.background_task = asyncio.create_task(
                self._background_enrich(new_session, user_id, query, language, results)
            )

        # Slice and return page 1 immediately
        start = (page - 1) * per_page
        end = start + per_page
        page_books = books[start:end]

        logger.info(
            f"Search Page 1 returned for '{query}': "
            f"{len(page_books)} books displayed, background search ongoing"
        )
        return page_books, initial_total, False

    async def _background_enrich(
        self,
        session: SearchSession,
        user_id: int,
        query: str,
        language: Optional[str],
        initial_results: list,
    ) -> None:
        """Fetch further pages and secondary sources in background, updating session results."""
        try:
            logger.info(f"Background enrichment started for '{query}' (user={user_id})")
            more_results = await source_router.search_more_batches(
                query, per_page=BATCH_SIZE, language=language, existing=initial_results
            )
            if not more_results:
                return

            db_books = await self._store_search_results(more_results)

            # Update session if user is still on this query
            if session.query == query and self._sessions.get(user_id) is session:
                session.results = db_books
                session.total = len(db_books)
                logger.info(
                    f"Background enrichment finished for '{query}': "
                    f"updated from {len(initial_results)} to {len(db_books)} books"
                )

            # Update global cache
            global_cache_key = f"global_search:{query.lower().strip()}:{language or ''}"
            book_ids = [b.id for b in db_books]
            await cache.set(global_cache_key, book_ids, ttl=CACHE_TTL_SECONDS)
        except Exception as e:
            logger.warning(f"Background enrichment failed for '{query}': {e}")

    def get_session(self, user_id: int) -> Optional[SearchSession]:
        """Get the current search session for a user, or None."""
        return self._sessions.get(user_id)

    def invalidate(self, user_id: int) -> None:
        """Clear cached results for a user (e.g. on new search)."""
        old = self._sessions.pop(user_id, None)
        if old is not None:
            if old.background_task and not old.background_task.done():
                old.background_task.cancel()
            logger.debug(f"Invalidated search cache for user={user_id}")

    def _cleanup_expired(self, now: float) -> None:
        """Evict expired sessions and cap maximum sessions in memory."""
        expired = [uid for uid, sess in self._sessions.items() if (now - sess.timestamp) >= CACHE_TTL_SECONDS]
        for uid in expired:
            old = self._sessions.pop(uid, None)
            if old and old.background_task and not old.background_task.done():
                old.background_task.cancel()
        if len(self._sessions) > 500:
            oldest = sorted(self._sessions.items(), key=lambda item: item[1].timestamp)[:100]
            for uid, _ in oldest:
                old = self._sessions.pop(uid, None)
                if old and old.background_task and not old.background_task.done():
                    old.background_task.cancel()

    async def _store_search_results(self, results) -> List[Any]:
        """Upsert BookResult objects into the database in bulk and return Book objects."""
        stored_data = []
        for r in results:
            ext_id = str(r.zlibrary_id or r.id)
            source_label = getattr(r, "_source", None)
            stored_data.append({
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
        return await db.bulk_upsert_books_by_external_id(stored_data)

    async def store_search_results(self, results) -> List[Any]:
        """Public alias for _store_search_results."""
        return await self._store_search_results(results)


search_service = SearchService()
