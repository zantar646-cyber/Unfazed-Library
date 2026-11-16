"""Tests for the Library -> Converter pull bridge (deep link + storage mapping)."""
from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.keyboards.inline import book_detail_keyboard, download_complete_keyboard
from bot.utils import deeplink


def _fake_settings(username: str = "TestConverterBot", secret: str = "") -> SimpleNamespace:
    return SimpleNamespace(converter_bot_username=username, deeplink_secret=secret)


def _book(storage_message_id=None) -> SimpleNamespace:
    return SimpleNamespace(
        id="book-1",
        title="A Book",
        author="An Author",
        file_size=1024,
        file_extension="epub",
        download_url="",
        storage_message_id=storage_message_id,
    )


def _message() -> SimpleNamespace:
    return SimpleNamespace(
        bot=SimpleNamespace(copy_message=AsyncMock()),
        chat=SimpleNamespace(id=1),
        answer_document=AsyncMock(),
    )


def _convert_buttons(markup) -> list:
    return [
        button
        for row in markup.inline_keyboard
        for button in row
        if "Convert" in button.text
    ]


def _markup_from_copy(message) -> object:
    return message.bot.copy_message.await_args.kwargs["reply_markup"]


@pytest.mark.asyncio
async def test_download_uploads_once_and_persists_the_message_id(monkeypatch):
    from bot.handlers import book as book_handlers

    monkeypatch.setattr(deeplink, "settings", _fake_settings(secret="s3cret"))
    monkeypatch.setattr(book_handlers, "storage_chat_id", lambda: -1001234567890)
    upload = AsyncMock(return_value=777)
    monkeypatch.setattr(book_handlers, "store_file_for_conversion", upload)
    persist = AsyncMock(return_value=True)
    monkeypatch.setattr(book_handlers.db, "set_book_storage_message", persist)

    message = _message()
    book = _book()

    await book_handlers._send_book_file(message, book, b"data")

    upload.assert_awaited_once()
    persist.assert_awaited_once_with("book-1", 777)
    assert book.storage_message_id == 777

    copy_kwargs = message.bot.copy_message.await_args.kwargs
    assert copy_kwargs["from_chat_id"] == -1001234567890
    assert copy_kwargs["message_id"] == 777

    convert_button = _convert_buttons(_markup_from_copy(message))[0]
    assert convert_button.url.startswith(
        "https://t.me/TestConverterBot?start=convert_777"
    )
    assert re.fullmatch(
        r"https://t\.me/TestConverterBot\?start=convert_777_[0-9a-f]{16}",
        convert_button.url,
    )
    message.answer_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeat_download_reuses_the_stored_channel_copy(monkeypatch):
    from bot.handlers import book as book_handlers

    monkeypatch.setattr(deeplink, "settings", _fake_settings(secret="s3cret"))
    monkeypatch.setattr(book_handlers, "storage_chat_id", lambda: -1001234567890)
    upload = AsyncMock(return_value=999)
    monkeypatch.setattr(book_handlers, "store_file_for_conversion", upload)
    persist = AsyncMock(return_value=True)
    monkeypatch.setattr(book_handlers.db, "set_book_storage_message", persist)

    message = _message()
    book = _book(storage_message_id=42)

    await book_handlers._send_book_file(message, book, b"data", fmt_override="pdf")

    upload.assert_not_awaited()
    persist.assert_not_awaited()
    assert message.bot.copy_message.await_args.kwargs["message_id"] == 42

    convert_button = _convert_buttons(_markup_from_copy(message))[0]
    assert convert_button.url.startswith(
        "https://t.me/TestConverterBot?start=convert_42"
    )


@pytest.mark.asyncio
async def test_deleted_storage_message_triggers_a_fresh_upload(monkeypatch):
    from bot.handlers import book as book_handlers

    monkeypatch.setattr(deeplink, "settings", _fake_settings())
    monkeypatch.setattr(book_handlers, "storage_chat_id", lambda: -1001234567890)
    upload = AsyncMock(return_value=888)
    monkeypatch.setattr(book_handlers, "store_file_for_conversion", upload)
    persist = AsyncMock(return_value=True)
    monkeypatch.setattr(book_handlers.db, "set_book_storage_message", persist)

    message = _message()
    # First copy (stored id 42) fails because the channel message was deleted.
    message.bot.copy_message.side_effect = [RuntimeError("message to copy not found"), None]
    book = _book(storage_message_id=42)

    await book_handlers._send_book_file(message, book, b"data")

    upload.assert_awaited_once()
    persist.assert_awaited_once_with("book-1", 888)
    assert message.bot.copy_message.await_args.kwargs["message_id"] == 888
    message.answer_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_failure_still_delivers_the_file(monkeypatch):
    from bot.handlers import book as book_handlers

    monkeypatch.setattr(deeplink, "settings", _fake_settings())
    monkeypatch.setattr(book_handlers, "storage_chat_id", lambda: -1001234567890)
    monkeypatch.setattr(
        book_handlers, "store_file_for_conversion", AsyncMock(return_value=None)
    )

    message = _message()
    book = _book()

    await book_handlers._send_book_file(message, book, b"data")

    message.answer_document.assert_awaited_once()
    convert_button = _convert_buttons(
        message.answer_document.await_args.kwargs["reply_markup"]
    )[0]
    assert convert_button.url == "https://t.me/TestConverterBot"


def test_book_detail_shows_convert_only_when_a_link_exists():
    with_link = book_detail_keyboard(
        "book-1", convert_url="https://t.me/TestConverterBot?start=convert_42"
    )
    without_link = book_detail_keyboard("book-1")

    assert _convert_buttons(with_link)[0].url == (
        "https://t.me/TestConverterBot?start=convert_42"
    )
    assert _convert_buttons(without_link) == []


def test_download_card_keeps_convert_next_to_details():
    markup = download_complete_keyboard(
        "book-1", convert_url="https://t.me/TestConverterBot?start=convert_42"
    )
    labels = [button.text for row in markup.inline_keyboard for button in row]

    assert any("Details" in label for label in labels)
    assert any("Convert" in label for label in labels)
