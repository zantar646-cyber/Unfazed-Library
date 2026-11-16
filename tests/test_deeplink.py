"""Tests for the Library -> Converter bot deep link payloads."""
from __future__ import annotations

import hashlib
import hmac
import re
from types import SimpleNamespace

import pytest

from bot.keyboards.inline import download_complete_keyboard
from bot.utils import deeplink


def _fake_settings(username: str = "TestConverterBot", secret: str = "") -> SimpleNamespace:
    return SimpleNamespace(converter_bot_username=username, deeplink_secret=secret)


def test_plain_deeplink_matches_telegram_format(monkeypatch):
    monkeypatch.setattr(deeplink, "settings", _fake_settings())
    assert (
        deeplink.build_convert_deeplink(12345)
        == "https://t.me/TestConverterBot?start=convert_12345"
    )


def test_payload_stays_telegram_safe_and_under_64_chars(monkeypatch):
    monkeypatch.setattr(deeplink, "settings", _fake_settings())
    payload = deeplink.build_convert_payload(10**14)
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", payload)
    assert len(payload) <= 64


def test_signed_payload_uses_the_same_algorithm_as_the_converter(monkeypatch):
    secret = "shared-secret"
    monkeypatch.setattr(deeplink, "settings", _fake_settings(secret=secret))

    payload = deeplink.build_convert_payload(987654321)

    assert re.fullmatch(r"convert_987654321_[0-9a-f]{16}", payload)
    signature = payload.rsplit("_", 1)[1]
    expected = hmac.new(
        secret.encode("utf-8"),
        b"convert_987654321",
        hashlib.sha256,
    ).hexdigest()[:16]
    assert signature == expected


def test_invalid_storage_ids_are_rejected(monkeypatch):
    monkeypatch.setattr(deeplink, "settings", _fake_settings())
    with pytest.raises(ValueError):
        deeplink.build_convert_payload(0)
    with pytest.raises(ValueError):
        deeplink.build_convert_payload(10**15)


def test_missing_converter_username_is_rejected(monkeypatch):
    monkeypatch.setattr(deeplink, "settings", _fake_settings(username=""))
    with pytest.raises(ValueError):
        deeplink.build_convert_deeplink(1)


def test_plain_link_falls_back_to_the_converter_bot(monkeypatch):
    monkeypatch.setattr(deeplink, "settings", _fake_settings())
    assert deeplink.converter_bot_link() == "https://t.me/TestConverterBot"

    monkeypatch.setattr(deeplink, "settings", _fake_settings(username="@TestConverterBot"))
    assert deeplink.converter_bot_link() == "https://t.me/TestConverterBot"

    monkeypatch.setattr(deeplink, "settings", _fake_settings(username=""))
    assert deeplink.converter_bot_link() is None


@pytest.mark.asyncio
async def test_convert_button_shows_even_without_a_storage_channel(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.handlers import book as book_handlers

    monkeypatch.setattr(deeplink, "settings", _fake_settings())

    async def _no_storage(*args, **kwargs):
        return None

    monkeypatch.setattr(book_handlers, "store_file_for_conversion", _no_storage)
    monkeypatch.setattr(book_handlers, "storage_chat_id", lambda: None)

    message = SimpleNamespace(
        bot=SimpleNamespace(copy_message=AsyncMock()),
        chat=SimpleNamespace(id=1),
        answer_document=AsyncMock(),
    )
    book = SimpleNamespace(
        id="book-1",
        title="A Book",
        author="An Author",
        file_size=1024,
        file_extension="epub",
        download_url="",
    )

    await book_handlers._send_book_file(message, book, b"data")

    markup = message.answer_document.await_args.kwargs["reply_markup"]
    buttons = [button for row in markup.inline_keyboard for button in row]
    convert_button = next(button for button in buttons if "Convert" in button.text)

    assert convert_button.url == "https://t.me/TestConverterBot"


def test_download_keyboard_uses_a_url_button_not_a_bot_to_bot_call():
    markup = download_complete_keyboard(
        "book-1", convert_url="https://t.me/TestConverterBot?start=convert_42"
    )
    buttons = [button for row in markup.inline_keyboard for button in row]
    convert_button = next(button for button in buttons if "Convert" in button.text)

    assert convert_button.url == "https://t.me/TestConverterBot?start=convert_42"
    assert convert_button.callback_data is None


def test_storage_chat_id_accepts_numeric_and_username(monkeypatch):
    from bot.utils import storage

    monkeypatch.setattr(storage, "settings", SimpleNamespace(storage_channel_id=""))
    assert storage.storage_chat_id() is None

    monkeypatch.setattr(storage, "settings", SimpleNamespace(storage_channel_id="-1001234567890"))
    assert storage.storage_chat_id() == -1001234567890

    monkeypatch.setattr(storage, "settings", SimpleNamespace(storage_channel_id="my_private_channel"))
    assert storage.storage_chat_id() == "@my_private_channel"


@pytest.mark.asyncio
async def test_storage_upload_is_a_noop_when_disabled(monkeypatch):
    from bot.utils import storage

    monkeypatch.setattr(storage, "settings", SimpleNamespace(storage_channel_id=""))
    result = await storage.store_file_for_conversion(
        None, b"data", "book.epub", "caption"
    )
    assert result is None
