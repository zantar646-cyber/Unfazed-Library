"""bot/handlers/bookclub.py — Telegram group mode & book club voting (feature #13)."""
from __future__ import annotations

import html
from typing import Dict, List, Optional
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from bot.database.service import db
from bot.utils.helpers import sanitize_html

router = Router()

# In-memory vote tracker for active book club polls: group_id/chat_id -> {book_id: set(user_ids)}
_CLUB_VOTES: Dict[int, Dict[str, set]] = {}


@router.message(Command("bookclub"))
async def cmd_bookclub(message: Message) -> None:
    """Launch a Book Club vote for the group or display current club picks."""
    chat_id = message.chat.id
    popular_books = await db.get_popular_books(limit=4)

    if not popular_books:
        # Fallback to recent books
        popular_books = await db.get_recent_books(limit=4)

    if not popular_books:
        await message.answer("📚 No books available right now to start a Book Club vote. Try searching and adding books first!")
        return

    # Initialize voting ballot
    _CLUB_VOTES[chat_id] = {b.id: set() for b in popular_books}

    builder = InlineKeyboardBuilder()
    text_lines = [
        "🏆 <b>Book Club — Book of the Week Vote!</b>\n",
        "Vote for the book you'd like the group to read next:\n",
    ]

    for idx, book in enumerate(popular_books, 1):
        clean_title = sanitize_html(book.title[:35])
        author = sanitize_html(book.author or "Unknown")
        text_lines.append(f"{idx}. <b>{clean_title}</b> by <i>{author}</i>")
        builder.row(
            InlineKeyboardButton(
                text=f"Vote: {clean_title}",
                callback_data=f"club:vote:{book.id}",
            )
        )

    builder.row(InlineKeyboardButton(text="📊 View Results", callback_data="club:results"))

    text = "\n".join(text_lines)
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("club:vote:"))
async def callback_club_vote(callback: CallbackQuery) -> None:
    chat_id = callback.message.chat.id if callback.message else 0
    book_id = callback.data.split(":")[-1]
    user_id = callback.from_user.id if callback.from_user else 0

    if chat_id not in _CLUB_VOTES:
        _CLUB_VOTES[chat_id] = {}

    votes_dict = _CLUB_VOTES[chat_id]
    if book_id not in votes_dict:
        votes_dict[book_id] = set()

    # Toggle vote or switch vote
    for bid, voters in votes_dict.items():
        voters.discard(user_id)

    votes_dict[book_id].add(user_id)
    await callback.answer("🗳 Your vote has been recorded!", show_alert=False)


@router.callback_query(F.data == "club:results")
async def callback_club_results(callback: CallbackQuery) -> None:
    chat_id = callback.message.chat.id if callback.message else 0
    votes_dict = _CLUB_VOTES.get(chat_id, {})

    if not votes_dict:
        await callback.answer("No active votes yet.", show_alert=True)
        return

    lines = ["📊 <b>Current Book Club Voting Results:</b>\n"]
    for book_id, voters in votes_dict.items():
        book = await db.get_book(book_id)
        title = book.title[:30] if book else book_id[:8]
        lines.append(f"• <b>{html.escape(title)}</b>: {len(voters)} vote(s)")

    await callback.answer()
    await callback.message.reply("\n".join(lines), parse_mode="HTML")
