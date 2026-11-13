from __future__ import annotations

from unittest.mock import AsyncMock

from light.cache import PreferencesStore, SearchSession
from light.i18n import (
    LANGUAGES,
    detect_content_language,
    get_text,
    language_display,
    language_flag,
    language_matches,
    language_name,
    pluralize,
)
from light.sources import Book, SourceRouter


def test_get_text_defaults_to_english():
    assert get_text("rate_limited") == get_text("rate_limited", "english")
    assert get_text("rate_limited", None) == get_text("rate_limited", "en")
    assert "Please wait a minute" in get_text("rate_limited")


def test_get_text_russian():
    ru = get_text("rate_limited", "russian")
    assert ru != get_text("rate_limited", "english")
    assert "минуту" in ru


def test_get_text_falls_back_to_english_for_unknown_lang():
    assert get_text("rate_limited", "german") == get_text("rate_limited", "en")


def test_get_text_unknown_key_returns_key():
    assert get_text("no_such_key") == "no_such_key"
    assert get_text("no_such_key", "ru") == "no_such_key"


def test_language_name_and_flag():
    assert language_name("russian") == "Russian"
    assert language_name("english") == "English"
    assert language_name("klingon") == "klingon"
    assert language_flag("french") == "\U0001f1eb\U0001f1f7"
    assert language_flag("nope") == "\U0001f310"


def test_languages_list_is_valid():
    codes = {c for c, _, _ in LANGUAGES}
    assert "english" in codes
    assert "russian" in codes
    # every code must have a translation target or fall back to English
    for code, _, _ in LANGUAGES:
        assert get_text("rate_limited", code)


def test_language_matches():
    assert language_matches("English", "english")
    assert language_matches("en", "english")
    assert language_matches("en-US", "english")
    assert language_matches("en_US", "english")
    assert language_matches("eng", "english")
    assert language_matches("pt-BR", "portuguese")
    assert language_matches("zh-Hans", "chinese")
    assert language_matches("русский", None)  # no filter matches anything
    assert language_matches(None, None)
    assert not language_matches("english", "russian")
    assert not language_matches("de", "english")
    assert not language_matches(None, "english")
    assert not language_matches("", "english")
    assert language_matches("zh", "chinese")


def test_language_matches_is_strict():
    # a compound/bilingual language value must NOT match either of its parts
    assert not language_matches("en fr", "english")
    assert not language_matches("en fr", "french")
    assert not language_matches("es eng", "spanish")
    assert not language_matches("por eng", "portuguese")
    assert not language_matches("English; German", "english")
    # country codes are not accepted as languages
    assert not language_matches("us", "english")
    assert not language_matches("gb", "english")
    assert not language_matches("uk", "english")
    # a different-but-similar language never matches
    assert not language_matches("Deutsch", "dutch")
    assert not language_matches("francais", "english")


def test_language_display():
    assert language_display("en") == "English"
    assert language_display("fr") == "French"
    assert language_display("mystery-lang") == "mystery-lang"
    assert language_display(None) == "Unknown"


def test_pluralize_english():
    assert pluralize(1, "en") == "result"
    assert pluralize(5, "en") == "results"
    assert pluralize(1) == "result"


def test_pluralize_russian():
    assert pluralize(1, "ru") == "книга"
    assert pluralize(2, "ru") == "книги"
    assert pluralize(5, "ru") == "книг"
    assert pluralize(21, "ru") == "книга"
    assert pluralize(12, "ru") == "книг"


def test_preferences_store():
    store = PreferencesStore()
    assert store.get_language(42) is None
    store.set_language(42, "russian")
    assert store.get_language(42) == "russian"
    store.set_language(42, None)
    assert store.get_language(42) is None
    assert store.get_language(99) is None


def test_preferences_store_persists_across_restarts(tmp_path):
    path = str(tmp_path / "prefs.json")
    store = PreferencesStore(path=path)
    store.set_language(42, "english")
    store.set_language(7, "russian")

    reloaded = PreferencesStore(path=path)
    assert reloaded.get_language(42) == "english"
    assert reloaded.get_language(7) == "russian"

    reloaded.set_language(7, None)
    again = PreferencesStore(path=path)
    assert again.get_language(42) == "english"
    assert again.get_language(7) is None


def test_preferences_store_tolerates_missing_or_corrupt_file(tmp_path):
    assert PreferencesStore(path=str(tmp_path / "nope.json")).get_language(1) is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert PreferencesStore(path=str(bad)).get_language(1) is None


def test_search_session_stores_language():
    session = SearchSession(query="test", results=[], total=0, language="russian")
    assert session.language == "russian"
    assert session.query == "test"


def test_search_session_default_language_none():
    session = SearchSession(query="test", results=[], total=0)
    assert session.language is None


async def test_source_router_filters_by_language():
    router = SourceRouter(AsyncMock(), AsyncMock())
    books = [
        Book(id="1", title="English Book", language="english", source="Z-Library"),
        Book(id="2", title="Russian Book", language="russian", source="Z-Library"),
        Book(id="3", title="Another English", language="en", source="Anna's Archive"),
        Book(id="4", title="No Lang", language=None, source="Z-Library"),
    ]
    router._zl_search_all = AsyncMock(return_value=books)
    router._aa_search = AsyncMock(return_value=[])

    en_results, en_total = await router.search("book", language="english")
    ru_results, ru_total = await router.search("book", language="russian")
    any_results, any_total = await router.search("book")

    assert {b.title for b in en_results} == {"English Book", "Another English"}
    assert en_total == 2
    assert {b.title for b in ru_results} == {"Russian Book"}
    assert ru_total == 1
    assert len(any_results) == 4
    assert any_total == 4


async def test_source_router_empty_when_no_language_match():
    router = SourceRouter(AsyncMock(), AsyncMock())
    books = [Book(id="1", title="English Book", language="english", source="Z-Library")]
    router._zl_search_all = AsyncMock(return_value=books)
    router._aa_search = AsyncMock(return_value=[])

    results, total = await router.search("book", language="turkish")
    assert results == []
    assert total == 0


def test_detect_content_language():
    assert detect_content_language("en-US") == "english"
    assert detect_content_language("en") == "english"
    assert detect_content_language("EN") == "english"
    assert detect_content_language("pt_BR") == "portuguese"
    assert detect_content_language("de-de") == "german"
    assert detect_content_language("uk") == "russian"
    assert detect_content_language("zh-Hant") == "chinese"
    assert detect_content_language("fil") is None
    assert detect_content_language(None) is None
    assert detect_content_language("") is None
