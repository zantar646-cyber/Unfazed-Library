"""Per-user persistent data for the light bot: favorites, history, settings.

Backed by a single JSON file (atomic writes, restart-safe) so users keep
their data across bot restarts.  No database engine needed.

The Book snapshot helpers serialize ``light.sources.Book`` to plain JSON
dicts so favorites can be reopened and re-downloaded later without a
re-search.  ``alternates`` are intentionally omitted to keep files small.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, List, Optional

try:
    from light.sources import Book
except ImportError:  # running directly: python light/bot.py
    from sources import Book  # type: ignore

HISTORY_LIMIT = 50

# Fields persisted for each favorite book.  Kept in sync with light.sources.Book.
_BOOK_FIELDS = (
    "id", "title", "author", "description", "publisher", "publication_year",
    "isbn", "file_size", "cover_url", "download_url", "download_urls",
    "file_token", "extension", "pages", "language", "source",
    "categories", "edition", "downloads",
)


def book_to_dict(book: Book) -> dict:
    data = {k: getattr(book, k, None) for k in _BOOK_FIELDS}
    data["formats"] = sorted(book.formats or ())
    data["sources"] = sorted(book.sources or ())
    return data


def book_from_dict(data: dict) -> Book:
    book = Book(**{k: data.get(k) for k in _BOOK_FIELDS})
    book.formats = set(data.get("formats") or ())
    book.sources = set(data.get("sources") or ())
    return book


class UserDataStore:
    """Per-user favorites / history / settings with JSON-file persistence."""

    def __init__(self, path: Optional[str] = None, max_users: int = 100_000) -> None:
        self._max = max_users
        self._path = path
        self._data: Dict[int, Dict[str, Any]] = {}
        if path:
            self._load()

    # -- file IO (atomic, same pattern as PreferencesStore) ----------------

    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self._data = {int(k): dict(v) for k, v in raw.items()}
        except (OSError, ValueError):
            self._data = {}

    def _save(self) -> None:
        if not self._path:
            return
        dirname = os.path.dirname(self._path)
        if dirname and not os.path.isdir(dirname):
            os.makedirs(dirname, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dirname or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, sort_keys=True)
            os.replace(tmp, self._path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def _user(self, user_id: int) -> Dict[str, Any]:
        user = self._data.get(user_id)
        if user is None:
            if len(self._data) >= self._max and user_id not in self._data:
                self._data.pop(next(iter(self._data)), None)
            user = {"favorites": [], "history": [], "settings": {}}
            self._data[user_id] = user
        user.setdefault("favorites", [])
        user.setdefault("history", [])
        user.setdefault("settings", {})
        return user

    # -- favorites ---------------------------------------------------------

    def get_favorites(self, user_id: int) -> List[dict]:
        return list(self._user(user_id)["favorites"])

    def add_favorite(self, user_id: int, book: Book) -> bool:
        favs = self._user(user_id)["favorites"]
        if any(str(f.get("id")) == str(book.id) for f in favs):
            return False
        favs.insert(0, book_to_dict(book))
        self._save()
        return True

    def remove_favorite(self, user_id: int, book_id: str) -> bool:
        favs = self._user(user_id)["favorites"]
        new = [f for f in favs if str(f.get("id")) != str(book_id)]
        if len(new) == len(favs):
            return False
        self._data[user_id]["favorites"] = new
        self._save()
        return True

    def has_favorite(self, user_id: int, book_id: str) -> bool:
        return any(str(f.get("id")) == str(book_id) for f in self._user(user_id)["favorites"])

    def get_favorite_book(self, user_id: int, book_id: str) -> Optional[Book]:
        for f in self._user(user_id)["favorites"]:
            if str(f.get("id")) == str(book_id):
                return book_from_dict(f)
        return None

    # -- history -----------------------------------------------------------

    def add_history(self, user_id: int, entry: dict) -> None:
        hist = self._user(user_id)["history"]
        hist.insert(0, entry)
        del hist[HISTORY_LIMIT:]
        self._save()

    def get_history(self, user_id: int, limit: int = 20) -> List[dict]:
        return self._user(user_id)["history"][:limit]

    def clear_history(self, user_id: int) -> None:
        self._data[user_id]["history"] = []
        self._save()

    # -- settings ----------------------------------------------------------

    def get_setting(self, user_id: int, key: str, default: Any = None) -> Any:
        return self._user(user_id)["settings"].get(key, default)

    def set_setting(self, user_id: int, key: str, value: Any) -> None:
        self._user(user_id)["settings"][key] = value
        self._save()
