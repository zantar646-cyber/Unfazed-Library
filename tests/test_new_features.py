"""Unit tests for the 14 new features implemented across the bot."""
from __future__ import annotations

import io
import zipfile
import pytest
from bot.database.models import Book, BookAlert, DailyStats, ReadingStatus, User
from bot.database.service import db
from bot.keyboards.inline import book_list_keyboard, main_menu_keyboard, language_toggle_button
from bot.services.dashboard import handle_api_stats
from bot.sources.openlibrary import OpenLibrarySource
from bot.sources.libgen import LibGenSource
from bot.utils.epub_reader import extract_chapters_from_epub, paginate_text


@pytest.mark.asyncio
async def test_book_alerts_crud():
    await db.create_tables()

    # Create user
    user = await db.get_or_create_user(99901, "alert_user")
    assert user is not None

    # Create alert
    alert = await db.create_book_alert(99901, "Deep Learning Goodfellow")
    assert alert.id is not None
    assert alert.query == "Deep Learning Goodfellow"
    assert alert.is_active is True

    # List alerts
    alerts = await db.get_user_alerts(99901)
    assert len(alerts) >= 1

    # Active alerts for worker
    active = await db.get_all_active_alerts()
    assert len(active) >= 1

    # Update alert checked
    await db.update_alert_checked(alert.id, notified=True)

    # Delete alert
    deleted = await db.delete_book_alert(alert.id, 99901)
    assert deleted is True


@pytest.mark.asyncio
async def test_reading_shelf_crud():
    import uuid
    await db.create_tables()

    uid = uuid.uuid4().int % 10000000
    user = await db.get_or_create_user(uid, "shelf_user")
    book_id = f"test-book-{uuid.uuid4().hex[:8]}"
    book = await db.create_book({"id": book_id, "title": "Clean Code", "author": "Robert Martin"})

    # Set status
    status = await db.set_reading_status(user.id, book.id, "reading")
    assert status.status == "reading"

    # Get status
    current = await db.get_reading_status(user.id, book.id)
    assert current is not None
    assert current.status == "reading"

    # Upsert to finished
    updated = await db.set_reading_status(user.id, book.id, "finished")
    assert updated.status == "finished"

    # Get shelf
    items, total = await db.get_user_reading_shelf(user.id, status="finished")
    assert total >= 1
    assert any(item.book_id == book_id for item in items)

    # Remove status
    removed = await db.remove_reading_status(user.id, book.id)
    assert removed is True


@pytest.mark.asyncio
async def test_daily_stats_and_referral():
    await db.create_tables()

    # Increment stat
    await db.increment_daily_stat("new_users")
    await db.increment_daily_stat("total_downloads")
    await db.increment_daily_stat("total_searches")

    weekly = await db.get_weekly_stats()
    assert len(weekly) >= 1
    today_stat = weekly[-1]
    assert today_stat.new_users >= 1
    assert today_stat.total_downloads >= 1
    assert today_stat.total_searches >= 1

    # Referral system with fresh user IDs
    import random
    uid1 = random.randint(1000000, 9000000)
    uid2 = uid1 + 1
    user1 = await db.get_or_create_user(uid1, "referrer")
    code = await db.get_or_create_referral_code(user1.id)
    assert len(code) == 8

    user2 = await db.get_or_create_user(uid2, "referee")
    success = await db.apply_referral(user2.id, code)
    assert success is True

    # Applying again should return False (already has referrer)
    second_try = await db.apply_referral(user2.id, code)
    assert second_try is False


def test_keyboards_features():
    # Main menu has My Shelf and Alerts
    menu = main_menu_keyboard()
    button_texts = [btn.text for row in menu.inline_keyboard for btn in row]
    assert any("Shelf" in t for t in button_texts)
    assert any("Alert" in t for t in button_texts)

    # Book list keyboard has format filter when action_prefix == "search"
    book = Book(id="b1", title="Test Book", file_extension="pdf")
    kb_search = book_list_keyboard([book], page=1, total_pages=1, action_prefix="search")
    search_texts = [btn.text for row in kb_search.inline_keyboard for btn in row]
    assert any("PDF" in t for t in search_texts)
    assert any("EPUB" in t for t in search_texts)

    # Language toggle button
    btn_en = language_toggle_button("en", "search")
    assert "EN" in btn_en.text
    btn_any = language_toggle_button(None, "search")
    assert "Any" in btn_any.text


def test_epub_chapter_extraction():
    # Create an in-memory dummy EPUB zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "chapter1.xhtml",
            "<html><head><title>Chapter 1: The Beginning</title></head><body><h1>Chapter 1: The Beginning</h1><p>It was a dark and stormy night. The rain poured heavily upon the roof of the library.</p></body></html>",
        )
        z.writestr(
            "chapter2.xhtml",
            "<html><head><title>Chapter 2: The Journey</title></head><body><h2>Chapter 2: The Journey</h2><p>Dawn broke over the horizon with brilliant hues of crimson and gold.</p></body></html>",
        )

    epub_data = buf.getvalue()
    chapters = extract_chapters_from_epub(epub_data)
    assert len(chapters) == 2
    assert "Chapter 1" in chapters[0][0]
    assert "Chapter 2" in chapters[1][0]

    # Test text pagination
    sample_text = "Paragraph 1\n\nParagraph 2\n\nParagraph 3"
    pages = paginate_text(sample_text, max_chars=20)
    assert len(pages) >= 2
