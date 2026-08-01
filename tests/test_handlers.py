from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bot.utils.browser_downloader import DownloadResult
from bot.utils.helpers import (
    calculate_pages,
    format_file_size,
    format_date,
    sanitize_html,
    truncate_text,
    validate_search_query,
)
from bot.utils.helpers import sanitize_input, validate_page


def test_sanitize_html():
    assert sanitize_html("<b>bold</b>") == "&lt;b&gt;bold&lt;/b&gt;"
    assert sanitize_html("normal text") == "normal text"
    assert sanitize_html("") == ""
    assert sanitize_html(None) == ""


def test_truncate_text():
    assert truncate_text("Hello World", 5) == "He..."
    assert truncate_text("Short", 10) == "Short"
    assert truncate_text("", 10) == ""
    assert truncate_text(None, 10) == ""


def test_format_file_size():
    assert format_file_size(None) == "Unknown"
    assert format_file_size(500) == "500.0 B"
    assert format_file_size(2048) == "2.0 KB"
    assert format_file_size(1048576) == "1.0 MB"
    assert format_file_size(1073741824) == "1.0 GB"


def test_calculate_pages():
    assert calculate_pages(0, 10) == 1
    assert calculate_pages(10, 10) == 1
    assert calculate_pages(11, 10) == 2
    assert calculate_pages(100, 10) == 10


def test_validate_search_query():
    assert validate_search_query("test") is True
    assert validate_search_query("ab") is True
    assert validate_search_query("a") is False
    assert validate_search_query("") is False
    assert validate_search_query("<script>") is False
    assert validate_search_query("A" * 201) is False


def test_sanitize_input():
    assert sanitize_input("  hello  ") == "hello"
    assert sanitize_input("<script>") == "script"
    assert sanitize_input("") is None


def test_validate_page():
    assert validate_page(1, 10) == 1
    assert validate_page(0, 10) == 1
    assert validate_page(11, 10) == 10
    assert validate_page(5, 10) == 5


def test_format_date():
    from datetime import datetime, timezone
    dt = datetime(2024, 6, 15, tzinfo=timezone.utc)
    result = format_date(dt)
    assert result == "Jun 15, 2024"
    assert format_date(None) == "N/A"


@pytest.mark.asyncio
async def test_process_download_cf_uses_resolved_url_directly():
    from bot.database.models import User as DBUser
    from bot.handlers.book import process_download

    mock_callback = AsyncMock()
    mock_callback.message.answer = AsyncMock()

    mock_book = AsyncMock()
    mock_book.download_url = "https://z-lib.fm/dl/testhash"
    mock_book.title = "Test Book"
    mock_book.author = "Author"
    mock_book.id = "book-id"
    mock_book.external_id = "123"
    mock_book.file_size = 1000
    mock_book.file_extension = "epub"

    mock_db_user = AsyncMock(spec=DBUser)
    mock_db_user.id = 1
    mock_db_user.preferred_language = "en"

    with (
        patch("bot.handlers.book._is_cloudflare_protected", return_value=True),
        patch("bot.handlers.book._resolve_book_url",
              return_value=("https://z-lib.fm/dl/suggestedhash", None, None, None)),
        patch("bot.handlers.book.api.download_file") as mock_dl,
        patch("bot.handlers.book.try_browser_download",
              return_value=DownloadResult(success=True, data=b"PK\x03\x04...")) as mock_browser,
        patch("bot.handlers.book._send_book_file"),
        patch("bot.handlers.book._record_successful_download"),
        patch("bot.handlers.book.get_text", return_value="loading"),
        patch("bot.handlers.book.db") as mock_db,
    ):
        mock_db.get_book = AsyncMock(return_value=mock_book)
        await process_download(mock_callback, mock_book, mock_db_user)

        mock_dl.assert_not_called()
        assert mock_browser.await_count == 1
        assert mock_browser.await_args.args[0] == "https://z-lib.fm/dl/suggestedhash"


@pytest.mark.asyncio
async def test_process_download_skips_http_for_cf_url():
    from bot.database.models import User as DBUser
    from bot.handlers.book import process_download

    mock_callback = AsyncMock()
    mock_callback.message.answer = AsyncMock()

    mock_book = AsyncMock()
    mock_book.download_url = "https://z-lib.fm/dl/testhash"
    mock_book.title = "Test Book"
    mock_book.author = "Author"
    mock_book.id = "book-id"
    mock_book.external_id = "123"
    mock_book.file_size = 1000
    mock_book.file_extension = "epub"

    mock_db_user = AsyncMock(spec=DBUser)
    mock_db_user.id = 1
    mock_db_user.preferred_language = "en"

    with (
        patch("bot.handlers.book._is_cloudflare_protected", return_value=True),
        patch("bot.handlers.book._resolve_book_url",
              return_value=("https://z-lib.fm/dl/testhash", None, "token123", None)),
        patch("bot.handlers.book.api.download_file") as mock_dl,
        patch("bot.handlers.book.try_browser_download",
              return_value=DownloadResult(success=True, data=b"PK\x03\x04...")),
        patch("bot.handlers.book._send_book_file"),
        patch("bot.handlers.book._record_successful_download"),
        patch("bot.handlers.book.get_text", return_value="loading"),
        patch("bot.handlers.book.db") as mock_db,
    ):
        mock_db.get_book = AsyncMock(return_value=mock_book)
        await process_download(mock_callback, mock_book, mock_db_user)

        mock_dl.assert_not_called()
        from bot.handlers.book import _send_book_file as mock_send
        mock_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_download_http_phase_runs_for_non_cf_url():
    from bot.database.models import User as DBUser
    from bot.handlers.book import process_download

    mock_callback = AsyncMock()
    mock_callback.message.answer = AsyncMock()

    mock_book = AsyncMock()
    mock_book.download_url = "https://example.com/dl/testhash"
    mock_book.title = "Test Book"
    mock_book.author = "Author"
    mock_book.id = "book-id"
    mock_book.external_id = "123"
    mock_book.file_size = 1000
    mock_book.file_extension = "epub"

    mock_db_user = AsyncMock(spec=DBUser)
    mock_db_user.id = 1
    mock_db_user.preferred_language = "en"

    with (
        patch("bot.handlers.book._is_cloudflare_protected", return_value=False),
        patch("bot.handlers.book._resolve_book_url",
              return_value=("https://example.com/dl/testhash", None, None, None)),
        patch("bot.handlers.book.api.download_file", return_value=b"PK\x03\x04...") as mock_dl,
        patch("bot.handlers.book.try_browser_download") as mock_browser,
        patch("bot.handlers.book._send_book_file"),
        patch("bot.handlers.book._record_successful_download"),
        patch("bot.handlers.book.get_text", return_value=""),
        patch("bot.handlers.book.db") as mock_db,
    ):
        mock_db.get_book = AsyncMock(return_value=mock_book)
        await process_download(mock_callback, mock_book, mock_db_user)

        mock_dl.assert_called()
        mock_browser.assert_not_called()
