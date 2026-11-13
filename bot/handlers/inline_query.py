"""bot/handlers/inline_query.py — Inline search mode via @botname query (feature #3)."""
from __future__ import annotations

import html
from typing import Optional

from aiogram import Router
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from loguru import logger

from bot.sources.router import search_first_batch
from bot.utils.helpers import format_file_size

router = Router()


@router.inline_query()
async def inline_search(inline_query: InlineQuery) -> None:
    query_text = inline_query.query.strip()

    if not query_text or len(query_text) < 2:
        prompt_item = InlineQueryResultArticle(
            id="prompt",
            title="🔍 Search Books",
            description="Type a book title or author to search...",
            input_message_content=InputTextMessageContent(
                message_text="🔍 Use inline mode to search books by typing <code>@bot query</code>",
                parse_mode="HTML",
            ),
        )
        await inline_query.answer([prompt_item], cache_time=10, is_personal=True)
        return

    try:
        results, total = await search_first_batch(query_text, per_page=10)
    except Exception as exc:
        logger.error(f"Inline search failed for '{query_text}': {exc}")
        results = []

    articles = []
    for idx, book in enumerate(results[:8]):
        book_id = str(getattr(book, "id", None) or getattr(book, "external_id", None) or idx)
        title = getattr(book, "title", "Unknown Title") or "Unknown Title"
        author = getattr(book, "author", "Unknown Author") or "Unknown Author"
        ext = (getattr(book, "file_extension", "") or "pdf").upper()
        size_bytes = getattr(book, "file_size", 0) or 0
        size_str = format_file_size(size_bytes) if size_bytes else ""
        year = getattr(book, "publication_year", None)
        cover_url = getattr(book, "cover_url", None)

        desc_parts = [author]
        if ext:
            desc_parts.append(ext)
        if size_str:
            desc_parts.append(size_str)
        if year:
            desc_parts.append(str(year))
        desc = " | ".join(desc_parts)[:100]

        msg_lines = [
            f"📚 <b>{html.escape(title)}</b>",
            f"👤 {html.escape(author)}",
        ]
        if year:
            msg_lines.append(f"📅 Year: {year}")
        if ext:
            msg_lines.append(f"💾 Format: {ext} {size_str}")

        dl_url = getattr(book, "download_url", None)
        if dl_url:
            msg_lines.append(f'\n<a href="{html.escape(dl_url)}">⬇️ Download File</a>')

        article = InlineQueryResultArticle(
            id=f"book_{book_id}_{idx}",
            title=title[:100],
            description=desc,
            thumbnail_url=cover_url if (cover_url and cover_url.startswith("http")) else None,
            input_message_content=InputTextMessageContent(
                message_text="\n".join(msg_lines),
                parse_mode="HTML",
                disable_web_page_preview=False,
            ),
        )
        articles.append(article)

    if not articles:
        articles.append(
            InlineQueryResultArticle(
                id="no_results",
                title="No books found",
                description=f"No results for '{query_text}'",
                input_message_content=InputTextMessageContent(
                    message_text=f"🔍 No books found matching <b>{html.escape(query_text)}</b>.",
                    parse_mode="HTML",
                ),
            )
        )

    await inline_query.answer(articles, cache_time=300, is_personal=True)
