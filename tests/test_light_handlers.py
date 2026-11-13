from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import light.handlers as handlers
from light.cache import PreferencesStore
from light.handlers import (
    _detail_nav,
    _find_book,
    _user_lang,
    book_detail_keyboard,
    book_list_keyboard,
    callback_book_detail,
    callback_close,
    callback_favorite_toggle,
    callback_menu_main,
    show_book_detail,
)
from light.sources import Book
from light.features import _MENU_LABELS
from light.keyboards import main_reply_keyboard


def _callback_datas(kb):
    return {btn.callback_data for row in kb.inline_keyboard for btn in row}


def _button_texts(kb):
    return {btn.text for row in kb.inline_keyboard for btn in row}


def _any_text_contains(kb, substring):
    return any(substring in t for t in _button_texts(kb))


class FakeData:
    def __init__(self):
        self.favs = []
        self.settings = {}

    def has_favorite(self, uid, book_id):
        return book_id in self.favs

    def add_favorite(self, uid, book):
        if book.id in self.favs:
            return False
        self.favs.append(book.id)
        return True

    def remove_favorite(self, uid, book_id):
        self.favs = [f for f in self.favs if f != book_id]
        return True

    def get_favorites(self, uid):
        return [{"id": f} for f in self.favs]

    def get_setting(self, uid, key, default=None):
        return self.settings.get(key, default)


# --------------------------------------------------------------------------
# Reply menu + label routing
# --------------------------------------------------------------------------

def test_main_reply_keyboard_layout():
    kb = main_reply_keyboard("en")
    assert kb.is_persistent is True
    assert kb.resize_keyboard is True
    assert [btn.text for btn in kb.keyboard[0]] == ["\U0001f50d Search", "\u2764\ufe0f Favorites"]
    assert [btn.text for btn in kb.keyboard[2]] == ["\u2699\ufe0f Settings", "\u2753 Help"]
    assert [btn.text for btn in kb.keyboard[3]] == ["\U0001f48e Support"]


def test_menu_label_map_covers_both_languages():
    assert _MENU_LABELS["\U0001f50d Search"] == "search"
    assert _MENU_LABELS["\U0001f310 \u042f\u0437\u044b\u043a"] == "language"
    assert _MENU_LABELS["\U0001f48e \u041f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0430"] == "support"


# --------------------------------------------------------------------------
# Keyboards
# --------------------------------------------------------------------------

def test_book_list_keyboard_pagination_and_home():
    books = [Book(id=str(i), title=f"Book {i}") for i in range(3)]
    kb = book_list_keyboard(books, 2, 5, "en")
    datas = _callback_datas(kb)
    assert {"search:page:1", "search:page:3", "ignore", "menu:main", "close"} <= datas
    assert "Page 2 of 5" in _button_texts(kb)


def test_book_detail_keyboard_actions():
    book = Book(id="1", title="Atomic Habits", extension="epub", formats={"epub", "pdf"})
    kb = book_detail_keyboard(
        book,
        "en",
        is_favorite=False,
        prev_cb="book:detail:0",
        next_cb="book:detail:2",
        back_callback="search:page:1",
    )
    datas = _callback_datas(kb)
    assert "download:1" in datas
    assert {"download:1:epub", "download:1:pdf"} <= datas
    assert "fav:toggle:1" in datas
    assert {"book:detail:0", "book:detail:2"} <= datas
    assert {"search:page:1", "menu:main", "close"} <= datas
    assert _any_text_contains(kb, "Add to Favorites")


def test_book_detail_keyboard_favorite_state():
    book = Book(id="1", title="T", extension="epub")
    kb = book_detail_keyboard(book, "en", is_favorite=True)
    assert _any_text_contains(kb, "Remove Favorite")
    kb2 = book_detail_keyboard(book, "en", is_favorite=False)
    assert _any_text_contains(kb2, "Add to Favorites")


# --------------------------------------------------------------------------
# Detail navigation
# --------------------------------------------------------------------------

def test_detail_nav_from_session():
    books = [Book(id="a", title="A"), Book(id="b", title="B"), Book(id="c", title="C")]

    class FakeSession:
        results = books
        page = 2

    original = handlers.sessions.get
    handlers.sessions.get = lambda uid: FakeSession()
    try:
        prev, nxt, back = _detail_nav(1, books[1])
    finally:
        handlers.sessions.get = original
    assert prev == "book:detail:a"
    assert nxt == "book:detail:c"
    assert back == "search:page:2"


def test_detail_nav_from_favorites():
    data = FakeData()
    data.favs = ["a", "b"]
    original_sessions = handlers.sessions.get
    original_userdata = handlers.userdata
    handlers.sessions.get = lambda uid: None
    handlers.userdata = data
    try:
        prev, nxt, back = _detail_nav(1, Book(id="a"))
    finally:
        handlers.sessions.get = original_sessions
        handlers.userdata = original_userdata
    assert prev is None
    assert nxt == "fav:open:1"
    assert back == "fav:page:1"


# --------------------------------------------------------------------------
# Book resolution
# --------------------------------------------------------------------------

def test_find_book_resolution_order():
    book = Book(id="r1", title="Registry book")
    original_find = handlers.sessions.find_book
    original_get = handlers.registry.get
    handlers.sessions.find_book = lambda bid: None
    handlers.registry.get = lambda bid: book if bid == "r1" else None
    try:
        assert _find_book("r1") is book
        assert _find_book("zzz") is None
    finally:
        handlers.sessions.find_book = original_find
        handlers.registry.get = original_get


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------

def _make_callback(data="fav:toggle:b1", message_kwargs=None):
    callback = AsyncMock()
    callback.from_user = None
    callback.data = data
    callback.answer = AsyncMock()
    message_kwargs = message_kwargs or {}
    callback.message = AsyncMock(caption=None, **message_kwargs)
    return callback


@pytest.mark.asyncio
async def test_callback_close_returns_home():
    from light import features

    original_trending = features._cached_trending
    features._cached_trending = AsyncMock(return_value=[])
    try:
        callback = _make_callback()
        await callback_close(callback)
    finally:
        features._cached_trending = original_trending

    callback.message.delete.assert_awaited_once()
    callback.answer.assert_awaited_once()
    assert callback.message.answer.await_count >= 1
    text = callback.message.answer.await_args_list[0].args[0]
    assert "Unfazed Library" in text
    kb = callback.message.answer.await_args_list[0].kwargs["reply_markup"]
    assert [btn.text for btn in kb.keyboard[0]] == ["\U0001f50d Search", "\u2764\ufe0f Favorites"]


@pytest.mark.asyncio
async def test_callback_menu_main_edits_home():
    from light import features

    original_trending = features._cached_trending
    features._cached_trending = AsyncMock(return_value=[])
    try:
        callback = _make_callback()
        await callback_menu_main(callback)
    finally:
        features._cached_trending = original_trending

    text = callback.message.edit_text.await_args.args[0]
    assert "Unfazed Library" in text
    kb = callback.message.edit_text.await_args.kwargs["reply_markup"]
    assert [btn.text for btn in kb.keyboard[0]] == ["\U0001f50d Search", "\u2764\ufe0f Favorites"]


@pytest.mark.asyncio
async def test_favorite_toggle_adds_and_updates_instantly():
    book = Book(id="b1", title="Book", extension="epub")
    data = FakeData()
    original_userdata = handlers.userdata
    original_get = handlers.registry.get
    handlers.userdata = data
    handlers.registry.get = lambda bid: book if bid == "b1" else None
    try:
        callback = _make_callback()
        await callback_favorite_toggle(callback)
    finally:
        handlers.userdata = original_userdata
        handlers.registry.get = original_get

    assert data.favs == ["b1"]
    assert "Added to favorites" in callback.answer.await_args.args[0]
    kb = callback.message.edit_text.await_args.kwargs["reply_markup"]
    assert _any_text_contains(kb, "Remove Favorite")


@pytest.mark.asyncio
async def test_favorite_toggle_removes_and_updates_instantly():
    book = Book(id="b1", title="Book", extension="epub")
    data = FakeData()
    data.favs = ["b1"]
    original_userdata = handlers.userdata
    original_get = handlers.registry.get
    handlers.userdata = data
    handlers.registry.get = lambda bid: book if bid == "b1" else None
    try:
        callback = _make_callback()
        await callback_favorite_toggle(callback)
    finally:
        handlers.userdata = original_userdata
        handlers.registry.get = original_get

    assert data.favs == []
    assert callback.answer.await_args.args[0] and "Removed from favorites" in callback.answer.await_args.args[0]
    kb = callback.message.edit_text.await_args.kwargs["reply_markup"]
    assert _any_text_contains(kb, "Add to Favorites")


@pytest.mark.asyncio
async def test_callback_book_detail_renders():
    book = Book(id="d1", title="Deep Work", author="Cal Newport", extension="pdf")
    data = FakeData()
    original_userdata = handlers.userdata
    original_get = handlers.registry.get
    handlers.userdata = data
    handlers.registry.get = lambda bid: book if bid == "d1" else None
    try:
        callback = _make_callback(data="book:detail:d1")
        await callback_book_detail(callback)
    finally:
        handlers.userdata = original_userdata
        handlers.registry.get = original_get

    assert callback.message.edit_text.await_count == 1
    text = callback.message.edit_text.await_args.args[0]
    assert "Deep Work" in text and "Cal Newport" in text
    kb = callback.message.edit_text.await_args.kwargs["reply_markup"]
    assert {"download:d1", "fav:toggle:d1", "menu:main", "close"} <= _callback_datas(kb)


@pytest.mark.asyncio
async def test_show_book_detail_with_cover_uses_photo():
    book = Book(id="c1", title="Covered", cover_url="https://example.com/c.jpg")
    data = FakeData()
    original_userdata = handlers.userdata
    handlers.userdata = data
    try:
        message = AsyncMock(caption=None)
        await show_book_detail(message, book, 1, "en")
    finally:
        handlers.userdata = original_userdata

    message.answer_photo.assert_awaited_once()
    message.delete.assert_awaited_once()


# --------------------------------------------------------------------------
# Language detection (kept from the previous suite)
# --------------------------------------------------------------------------

def test_user_lang_auto_detects_and_persists(tmp_path):
    store = PreferencesStore(path=str(tmp_path / "p.json"))
    original = _user_lang.__globals__["preferences"]
    _user_lang.__globals__["preferences"] = store
    try:
        class GermanUser:
            id = 42
            language_code = "de-DE"

        class UnknownUser:
            id = 7
            language_code = "fil"

        assert _user_lang(GermanUser()) == "german"
        assert store.get_language(42) == "german"
        assert _user_lang(UnknownUser()) is None
        assert store.get_language(7) is None
        assert _user_lang(None) is None
    finally:
        _user_lang.__globals__["preferences"] = original


def test_user_lang_respects_existing_choice(tmp_path):
    store = PreferencesStore(path=str(tmp_path / "p.json"))
    store.set_language(42, "english")
    original = _user_lang.__globals__["preferences"]
    _user_lang.__globals__["preferences"] = store
    try:
        class RussianUser:
            id = 42
            language_code = "ru"

        assert _user_lang(RussianUser()) == "english"
    finally:
        _user_lang.__globals__["preferences"] = original
