"""Lightweight in-memory caches.

Replaces Redis (bot/services/cache.py) and the SQLAlchemy-backed search
session persistence with plain dicts + monotonic TTLs.  No extra deps.

PreferencesStore additionally persists to a small JSON file so user choices
(e.g. language) survive bot restarts.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional


class TTLCache:
    """Simple in-memory cache with per-key TTLs and a size cap."""

    def __init__(self, default_ttl: int = 300, max_entries: int = 10_000) -> None:
        self._default_ttl = default_ttl
        self._max = max_entries
        self._items: Dict[str, tuple] = {}

    def get(self, key: str) -> Optional[Any]:
        item = self._items.get(key)
        if item is None:
            return None
        value, expires = item
        if time.monotonic() > expires:
            del self._items[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        if len(self._items) >= self._max and key not in self._items:
            self._evict_one()
        expires = time.monotonic() + (ttl if ttl is not None else self._default_ttl)
        self._items[key] = (value, expires)

    def _evict_one(self) -> None:
        if self._items:
            self._items.pop(next(iter(self._items)), None)


class SearchSession:
    """A user's in-memory search result page session."""

    __slots__ = ("query", "results", "total", "page", "language", "timestamp")

    def __init__(
        self,
        query: str,
        results: List,
        total: int,
        page: int = 1,
        language: Optional[str] = None,
    ) -> None:
        self.query = query
        self.results = results
        self.total = total
        self.page = page
        self.language = language
        self.timestamp = time.monotonic()


class SessionStore:
    """Per-user search sessions (replaces DB-backed SearchService + Redis)."""

    def __init__(self, ttl: int = 1800, max_sessions: int = 500) -> None:
        self._ttl = ttl
        self._max = max_sessions
        self._sessions: Dict[int, SearchSession] = {}

    def get(self, user_id: int) -> Optional[SearchSession]:
        session = self._sessions.get(user_id)
        if session is None:
            return None
        if time.monotonic() - session.timestamp > self._ttl:
            del self._sessions[user_id]
            return None
        return session

    def put(self, user_id: int, session: SearchSession) -> None:
        if len(self._sessions) >= self._max and user_id not in self._sessions:
            self._sessions.pop(next(iter(self._sessions)), None)
        self._sessions[user_id] = session

    def find_book(self, book_id: str) -> Optional[Any]:
        """Look up a book by id across all recent sessions (for /download)."""
        for session in self._sessions.values():
            for book in session.results:
                if str(getattr(book, "id", "")) == book_id:
                    return book
        return None


class BookRegistry:
    """Temporary lookup of books shown outside a user's search session.

    Books rendered on the home screen (trending) and favorites can't be
    resolved via ``SessionStore`` alone, so they are registered here so
    ``book:detail`` callbacks can find them.
    """

    def __init__(self, max_entries: int = 5000) -> None:
        self._max = max_entries
        self._books: Dict[str, Any] = {}

    def put(self, book: Any) -> None:
        if book is None or not getattr(book, "id", None):
            return
        key = str(book.id)
        if len(self._books) >= self._max and key not in self._books:
            self._books.pop(next(iter(self._books)), None)
        self._books[key] = book

    def put_many(self, books) -> None:
        for b in books:
            self.put(b)

    def get(self, book_id: str) -> Optional[Any]:
        return self._books.get(str(book_id))


class PreferencesStore:
    """Per-user bot preferences (e.g. chosen language).

    Backed by an optional JSON file so choices survive restarts.  No deps.
    """

    def __init__(self, path: Optional[str] = None, max_users: int = 10_000) -> None:
        self._max = max_users
        self._path = path
        self._prefs: Dict[int, Dict[str, Any]] = {}
        if path:
            self._load()

    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self._prefs = {int(k): dict(v) for k, v in raw.items()}
        except (OSError, ValueError):
            self._prefs = {}

    def _save(self) -> None:
        if not self._path:
            return
        dirname = os.path.dirname(self._path)
        if dirname and not os.path.isdir(dirname):
            os.makedirs(dirname, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dirname or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._prefs, f, ensure_ascii=False, sort_keys=True)
            os.replace(tmp, self._path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def get_language(self, user_id: int) -> Optional[str]:
        prefs = self._prefs.get(user_id)
        if prefs is None:
            return None
        return prefs.get("language")

    def set_language(self, user_id: int, language: Optional[str]) -> None:
        prefs = self._prefs.get(user_id)
        if prefs is None:
            if len(self._prefs) >= self._max and user_id not in self._prefs:
                self._prefs.pop(next(iter(self._prefs)), None)
            prefs = {}
            self._prefs[user_id] = prefs
        if language is None:
            prefs.pop("language", None)
        else:
            prefs["language"] = language
        self._save()
