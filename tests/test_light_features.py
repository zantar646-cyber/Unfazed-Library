"""Tests for the new-library modules: persistent user data, caches, keyboards."""

from __future__ import annotations

from light.cache import BookRegistry
from light.keyboards import (
    favorites_keyboard,
    format_keyboard,
    help_index_keyboard,
    history_keyboard,
    nav_keyboard,
    notifications_keyboard,
    per_page_keyboard,
    settings_keyboard,
    support_keyboard,
)
from light.sources import Book
from light.userdata import UserDataStore, book_from_dict, book_to_dict


def _callback_datas(kb):
    return {btn.callback_data for row in kb.inline_keyboard for btn in row}


# --------------------------------------------------------------------------
# Book (de)serialization
# --------------------------------------------------------------------------

def test_book_round_trip():
    book = Book(
        id="42", title="Atomic Habits", author="James Clear", extension="epub",
        formats={"epub", "pdf"}, sources={"Z-Library"}, publisher="Avery",
        publication_year=2018, isbn="9780735211292", pages=320, language="english",
        file_size=1234567, categories=["self-help"], edition="1st", downloads=5,
    )
    restored = book_from_dict(book_to_dict(book))
    assert restored.id == "42"
    assert restored.title == "Atomic Habits"
    assert restored.formats == {"epub", "pdf"}
    assert restored.sources == {"Z-Library"}
    assert restored.categories == ["self-help"]
    assert restored.edition == "1st"
    assert restored.downloads == 5
    assert restored.publication_year == 2018


def test_book_from_dict_tolerates_missing_fields():
    book = book_from_dict({"id": "1", "title": "T"})
    assert book.id == "1"
    assert book.formats == set()


# --------------------------------------------------------------------------
# UserDataStore
# --------------------------------------------------------------------------

def test_favorites_add_remove(tmp_path):
    store = UserDataStore(path=str(tmp_path / "u.json"))
    book = Book(id="b1", title="T", extension="epub")
    assert store.add_favorite(1, book) is True
    assert store.add_favorite(1, book) is False
    assert store.has_favorite(1, "b1") is True
    assert len(store.get_favorites(1)) == 1
    assert store.remove_favorite(1, "b1") is True
    assert store.remove_favorite(1, "b1") is False
    assert store.has_favorite(1, "b1") is False


def test_history_prepends_and_caps(tmp_path):
    store = UserDataStore(path=str(tmp_path / "u.json"))
    for i in range(60):
        store.add_history(1, {"type": "search", "query": f"q{i}", "ts": i})
    hist = store.get_history(1, 20)
    assert hist[0]["query"] == "q59"
    assert len(store.get_history(1, 50)) == 50
    store.clear_history(1)
    assert store.get_history(1) == []


def test_settings_persist_and_reload(tmp_path):
    path = str(tmp_path / "u.json")
    store = UserDataStore(path=path)
    store.set_setting(1, "format", "pdf")
    store.set_setting(1, "per_page", 30)
    store.set_setting(1, "notifications", False)
    reloaded = UserDataStore(path=path)
    assert reloaded.get_setting(1, "format") == "pdf"
    assert reloaded.get_setting(1, "per_page") == 30
    assert reloaded.get_setting(1, "notifications") is False
    assert reloaded.get_setting(1, "missing", "x") == "x"


def test_corrupt_userdata_file_tolerated(tmp_path):
    path = tmp_path / "u.json"
    path.write_text("{not json", encoding="utf-8")
    store = UserDataStore(path=str(path))
    assert store.get_favorites(1) == []


def test_userdata_favorites_survive_reload(tmp_path):
    path = str(tmp_path / "u.json")
    store = UserDataStore(path=path)
    store.add_favorite(1, Book(id="b9", title="Nine", extension="pdf"))
    reloaded = UserDataStore(path=path)
    fav = reloaded.get_favorites(1)[0]
    assert fav["id"] == "b9"
    restored = reloaded.get_favorite_book(1, "b9")
    assert restored is not None and restored.title == "Nine"


# --------------------------------------------------------------------------
# In-memory caches
# --------------------------------------------------------------------------

def test_book_registry():
    reg = BookRegistry()
    book = Book(id="x", title="X")
    reg.put_many([book, Book(id="y", title="Y")])
    assert reg.get("x").title == "X"
    assert reg.get("missing") is None


# --------------------------------------------------------------------------
# Keyboards
# --------------------------------------------------------------------------

def test_favorites_keyboard_rows_and_nav():
    favs = [{"id": str(i), "title": f"Book {i}"} for i in range(5)]
    kb = favorites_keyboard(favs, 0, 1, 2, "en")
    datas = _callback_datas(kb)
    assert "fav:open:0" in datas
    assert "fav:open:4" in datas
    assert "fav:page:2" in datas


def test_history_keyboard_entries():
    entries = [
        {"type": "search", "query": "atomic habits"},
        {"type": "download", "book_id": "77", "title": "Deep Work"},
    ]
    kb = history_keyboard(entries, 0, 1, 1, "en")
    datas = _callback_datas(kb)
    assert "hist:go:0" in datas
    assert "book:detail:77" in datas
    assert "hist:clear" in datas


def test_settings_keyboard_opens_submenus():
    kb = settings_keyboard("en", fmt="pdf", per_page=20, notif=True)
    datas = _callback_datas(kb)
    assert {"lang:menu", "set:fmt", "set:page", "set:notif"} <= datas


def test_format_and_page_and_notif_keyboards():
    kb = format_keyboard("en", "epub")
    datas = _callback_datas(kb)
    assert {"set:fmt:pdf", "set:fmt:epub", "set:fmt:mobi", "set:fmt:azw3", "settings:open"} <= datas

    kb2 = per_page_keyboard("en", 20)
    assert {"set:page:10", "set:page:20", "set:page:30", "set:page:50"} <= _callback_datas(kb2)

    kb3 = notifications_keyboard("en", True)
    assert {"set:notif:on", "set:notif:off"} <= _callback_datas(kb3)


def test_help_index_keyboard_sections():
    kb = help_index_keyboard("en")
    datas = _callback_datas(kb)
    assert {"help:how_search", "help:downloads", "help:formats", "help:faq", "help:report", "help:contact"} <= datas


def test_support_keyboard_with_links():
    kb = support_keyboard("en", support_url="https://pay.example/x", contact_url="https://t.me/dev")
    urls = {btn.url for row in kb.inline_keyboard for btn in row if btn.url}
    assert urls == {"https://pay.example/x", "https://t.me/dev"}


def test_nav_keyboard():
    kb = nav_keyboard("en", "help:index")
    assert _callback_datas(kb) == {"help:index", "menu:main", "close"}
