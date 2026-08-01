from __future__ import annotations

from typing import Optional

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.database.models import User as DBUser
from bot.database.service import db
from bot.keyboards.inline import ai_action_keyboard, book_detail_keyboard
from bot.services.ai import ai
from bot.utils.helpers import sanitize_html
from bot.utils.i18n import get_text

router = Router()

AI_KEYS = {
    "summary": "ai_summary",
    "lessons": "ai_lessons",
    "notes": "ai_notes",
    "similar": "ai_similar",
    "question": "ai_question",
}


@router.callback_query(F.data.startswith("ai:"))
async def callback_ai_action(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    lang = db_user.preferred_language if db_user else None
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer("Invalid request.", show_alert=True)
        return

    action = parts[1]
    book_id = parts[2]

    book = await db.get_book(book_id)
    if not book:
        await callback.message.edit_text(get_text("book_not_found", lang))
        await callback.answer()
        return

    title = book.title
    author = book.author
    description = book.description
    ai_header = get_text(AI_KEYS.get(action, "ai_summary"), lang)

    if action == "question":
        await callback.message.edit_text(
            get_text("ai_question_prompt", lang).format(title=sanitize_html(title)),
            reply_markup=ai_action_keyboard(book_id, lang),
        )
        await callback.message.answer(
            get_text("ai_question_instruction", lang).format(title=sanitize_html(title)),
            reply_markup=None,
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        get_text("ai_generating", lang).format(header=ai_header, title=sanitize_html(title)),
        reply_markup=None,
    )
    await callback.answer()

    try:
        if action == "summary":
            result = await ai.generate_summary(title, author, description)
        elif action == "lessons":
            result = await ai.extract_lessons(title, author, description)
        elif action == "notes":
            result = await ai.generate_study_notes(title, author, description)
        elif action == "similar":
            result = await ai.suggest_similar_books(title, author, description)
        else:
            result = "Unknown action."

        is_fav = callback.from_user and await db.is_favorite(callback.from_user.id, book_id)
        keyboard = book_detail_keyboard(
            book_id=book_id,
            is_favorite=is_fav,
        )

        max_length = 4000
        if len(result) > max_length:
            parts_result = [result[i:i + max_length] for i in range(0, len(result), max_length)]
            for idx, part in enumerate(parts_result):
                if idx == 0:
                    header = f"{ai_header}\n\n"
                    await callback.message.edit_text(
                        header + part,
                        parse_mode="HTML",
                        reply_markup=keyboard if idx == len(parts_result) - 1 else None,
                    )
                else:
                    await callback.message.answer(
                        part,
                        parse_mode="HTML",
                        reply_markup=keyboard if idx == len(parts_result) - 1 else None,
                    )
        else:
            await callback.message.edit_text(
                f"{ai_header}\n\n{result}",
                parse_mode="HTML",
                reply_markup=keyboard,
            )

    except Exception as e:
        logger.error(f"AI action error ({action}): {e}")
        await callback.message.edit_text(
            get_text("ai_error", lang),
            reply_markup=ai_action_keyboard(book_id, lang),
        )


@router.message(F.reply_to_message)
async def handle_ai_question(message: Message, db_user: Optional[DBUser] = None) -> None:
    lang = db_user.preferred_language if db_user else None
    reply = message.reply_to_message
    if not reply or not reply.text:
        return

    reply_text = reply.text
    import re
    match = re.search(r"<b>(.+?)</b>", reply_text)
    if not match:
        await message.answer(get_text("book_not_found", lang))
        return

    title = match.group(1)
    question = message.text
    if not question:
        await message.answer(get_text("ai_question_prompt", lang).format(title=sanitize_html(title)))
        return

    sent = await message.answer(get_text("ai_generating", lang).format(header=get_text("ai_question", lang), title=sanitize_html(title)))

    result = await ai.answer_question(title, None, question)

    sent_text = f"❓ <b>Q: {sanitize_html(question)}</b>\n\n{result}"

    max_length = 4000
    if len(sent_text) > max_length:
        await sent.edit_text(sent_text[:max_length])
        remaining = sent_text[max_length:]
        while remaining:
            await message.answer(remaining[:max_length])
            remaining = remaining[max_length:]
    else:
        await sent.edit_text(sent_text, parse_mode="HTML")
