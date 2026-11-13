from __future__ import annotations

import asyncio
from typing import Optional

import aiohttp
from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger

from bot.config.settings import settings
from bot.database.models import User as DBUser
from bot.database.service import db
from bot.keyboards.inline import (
    book_detail_keyboard,
    book_list_keyboard,
    category_list_keyboard,
    confirm_download_keyboard,
    download_complete_keyboard,
)
from bot.utils.helpers import (
    build_book_message,
    calculate_pages,
    format_extension,
    format_file_size,
    get_format_emoji,
    get_search_query,
    is_real_file,
    safe_edit_or_send,
    sanitize_html,
)
from bot.services.api import _is_cloudflare_protected, api
from bot.services.search import search_service
from bot.sources import router as source_router
from bot.utils.browser_downloader import (
    try_browser_download,
)
from bot.utils.convert_storage import create_convert_key
from bot.utils.i18n import get_text
from bot.utils.net import proxy_kwargs

router = Router()


async def _store_search_results(results) -> list:
    return await search_service.store_search_results(results)


@router.callback_query(F.data.startswith("categories:list:"))
async def callback_categories_list(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    lang = db_user.preferred_language if db_user else None
    page = int(callback.data.split(":")[-1])
    categories = await db.get_all_categories()

    items_per_page = 5
    total_pages = calculate_pages(len(categories), items_per_page)
    start = (page - 1) * items_per_page
    page_categories = categories[start: start + items_per_page]

    await callback.message.edit_text(
        get_text("categories_title", lang),
        reply_markup=category_list_keyboard(page_categories, page, total_pages),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("category:"))
async def callback_category_books(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    lang = db_user.preferred_language if db_user else None
    parts = callback.data.split(":")
    category_id = int(parts[1])
    page = int(parts[2])
    logger.info(f"callback_category_books: category_id={category_id} page={page} user={callback.from_user.id if callback.from_user else '?'}")

    category = await db.get_category(category_id)
    if not category:
        logger.warning(f"Category {category_id} not found")
        await callback.message.edit_text(get_text("category_not_found", lang), reply_markup=None)
        await callback.answer()
        return

    language = db_user.preferred_language if db_user else None
    logger.info(f"  category: '{category.name}' slug='{category.slug}' language={language}")

    try:
        results, total = await api.get_books_by_category(category.slug, page=page, per_page=10, language=language)
    except Exception as e:
        logger.error(f"Category API error for {category.slug}: {e}")
        await callback.message.edit_text(
            get_text("category_fetch_failed", lang).format(name=sanitize_html(category.name)),
        )
        await callback.answer()
        return

    books = await _store_search_results(results)
    total_pages = calculate_pages(total, 10)

    if not books:
        logger.info(f"No books found in category '{category.name}'")
        await callback.message.edit_text(
            get_text("category_no_books", lang).format(name=sanitize_html(category.name)),
            reply_markup=None,
        )
        await callback.answer()
        return

    logger.info(f"Category '{category.name}': {len(books)} books, page {page}/{total_pages}, total={total}")
    for b in books[:3]:
        logger.info(f"  [{b.id}] {b.title} / {b.author}")

    text = get_text("category_books_header", lang).format(
        name=sanitize_html(category.name), page=page, total=total_pages, count=total,
    )
    await callback.message.edit_text(
        text,
        reply_markup=book_list_keyboard(
            books=books,
            page=page,
            total_pages=total_pages,
            action_prefix=f"cat_{category_id}",
            back_callback="categories:list:1",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cat_"))
async def callback_category_book_page(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    lang = db_user.preferred_language if db_user else None
    parts = callback.data.split(":")
    prefix = parts[0]
    action = parts[1]
    category_id = int(prefix.split("_")[1])
    logger.info(f"callback_category_book_page: prefix={prefix} action={action} cat_id={category_id} user={callback.from_user.id if callback.from_user else '?'}")

    if action == "page":
        page = int(parts[2])
        category = await db.get_category(category_id)
        if not category:
            await callback.message.edit_text(get_text("category_not_found", lang), reply_markup=None)
            await callback.answer()
            return

        language = db_user.preferred_language if db_user else None
        logger.info(f"  Paginate category: '{category.name}' slug='{category.slug}' page={page}")
        try:
            results, total = await api.get_books_by_category(category.slug, page=page, per_page=10, language=language)
        except Exception as e:
            logger.error(f"Category page API error for {category.slug}: {e}")
            await callback.answer("Failed to fetch books.", show_alert=True)
            return

        books = await _store_search_results(results)
        total_pages = calculate_pages(total, 10)
        text = get_text("category_books_header", lang).format(
            name=sanitize_html(category.name), page=page, total=total_pages, count=total,
        )

        logger.info(f"  Category page: {len(books)} books, page {page}/{total_pages}")
        await safe_edit_or_send(
            callback.message,
            text,
            reply_markup=book_list_keyboard(
                books=books,
                page=page,
                total_pages=total_pages,
                action_prefix=prefix,
                back_callback="categories:list:1",
            ),
        )
    elif action == "detail":
        book_id = parts[2]
        back_callback = f"{prefix}:page:1"
        logger.info(f"  Book detail from category: id={book_id} back_callback={back_callback}")
        await show_book_detail(callback.message, book_id, callback, back_callback, lang)
        await callback.answer()
        return

    await callback.answer()


@router.callback_query(F.data.startswith(("search:", "popular:", "latest:", "recent:", "favorites:")))
async def callback_list_action(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    lang = db_user.preferred_language if db_user else None
    parts = callback.data.split(":")
    prefix = parts[0]
    action = parts[1]
    logger.info(f"callback_list_action: prefix={prefix} action={action} data={callback.data} user={callback.from_user.id if callback.from_user else '?'}")

    if action == "page":
        page = int(parts[2])
        books = []
        total = 0

        if prefix == "search":
            user_id = callback.from_user.id if callback.from_user else 0
            query_line = get_search_query(user_id)
            if not query_line:
                import re
                logger.warning("No search query found in memory, trying fallback regex on message text")
                text_content = callback.message.text or ""
                fallback_match = re.search(r"for '<b>([^<]+)</b>'", text_content)
                if fallback_match:
                    query_line = fallback_match.group(1)

            language = db_user.preferred_language if db_user else None
            try:
                logger.info(f"  Paginating search: query='{query_line}' page={page}")
                books, total, from_cache = await search_service.search(user_id, query_line, page=page, language=language)
                if from_cache:
                    logger.info(f"  Pagination from cache: page={page} ({len(books)} books)")
                else:
                    logger.info(f"  Pagination fetched new data: page={page} ({len(books)} books)")

                # Defensive: if we got an empty page but there should be results,
                # log a diagnostic so we can detect remaining bugs.
                if not books and total > 0:
                    session = search_service.get_session(user_id)
                    cached_count = len(session.results) if session else 0
                    logger.error(
                        f"EMPTY PAGE for query='{query_line}' page={page}: "
                        f"total={total}, cached_results={cached_count}, "
                        f"from_cache={from_cache}"
                    )
            except Exception as e:
                logger.error(f"  Search pagination failed: {e}, falling back to DB search")
                books, total = await db.search_books(query_line, page=page, per_page=10)
        elif prefix == "popular":
            books = await db.get_popular_books(limit=10)
            total = len(books)
        elif prefix in ("latest", "recent"):
            books = await db.get_recent_books(limit=10)
            total = len(books)
        elif prefix == "favorites" and db_user:
            favs, total = await db.get_user_favorites(db_user.id, page=page, per_page=10)
            books = [fav.book for fav in favs if fav.book]

        total_pages = calculate_pages(total, 10)
        text = get_text("page_format", lang).format(page=page, total=total_pages)
        logger.info(f"  Displaying page {page}/{total_pages} with {len(books)} books")

        await safe_edit_or_send(
            callback.message,
            text,
            reply_markup=book_list_keyboard(
                books=books,
                page=page,
                total_pages=total_pages,
                action_prefix=prefix,
                back_callback="menu",
            ),
        )
    elif action == "detail":
        book_id = parts[2]
        back_callback = f"{prefix}:page:1"
        logger.info(f"  Book detail: id={book_id} back_callback={back_callback}")
        await show_book_detail(callback.message, book_id, callback, back_callback, lang)

    await callback.answer()


async def show_book_detail(message: Message, book_id: str, callback: Optional[CallbackQuery] = None, back_callback: str = "menu", lang: Optional[str] = None) -> None:
    book = await db.get_book(book_id)
    if not book:
        text = get_text("book_not_found", lang)
        if callback:
            await callback.message.edit_text(text)
        else:
            await message.answer(text)
        return

    is_fav = False
    uid = callback.from_user.id if callback and callback.from_user else None
    if uid:
        is_fav = await db.is_favorite(uid, book_id)

    caption = build_book_message(book, lang)

    if book.cover_url:
        try:
            await message.answer_photo(
                photo=book.cover_url,
                caption=caption,
                parse_mode="HTML",
                reply_markup=book_detail_keyboard(
                    book_id=book.id,
                    is_favorite=is_fav,
                    download_url=book.download_url,
                    back_callback=back_callback,
                ),
            )
            if callback:
                try:
                    await callback.message.delete()
                except Exception:
                    pass
            return
        except Exception:
            logger.warning(f"Failed to send cover image for book {book_id}")

    if callback:
        try:
            await callback.message.edit_text(
                caption,
                parse_mode="HTML",
                reply_markup=book_detail_keyboard(
                    book_id=book.id,
                    is_favorite=is_fav,
                    download_url=book.download_url,
                    back_callback=back_callback,
                ),
            )
        except TelegramBadRequest:
            await callback.message.answer(
                caption,
                parse_mode="HTML",
                reply_markup=book_detail_keyboard(
                    book_id=book.id,
                    is_favorite=is_fav,
                    download_url=book.download_url,
                    back_callback=back_callback,
                ),
            )
    else:
        await message.answer(
            caption,
            parse_mode="HTML",
            reply_markup=book_detail_keyboard(
                book_id=book.id,
                is_favorite=is_fav,
                download_url=book.download_url,
                back_callback=back_callback,
            ),
        )


@router.callback_query(F.data.startswith("book:detail:"))
async def callback_book_detail(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    lang = db_user.preferred_language if db_user else None
    book_id = callback.data.split(":")[-1]
    await show_book_detail(callback.message, book_id, callback, lang=lang)
    await callback.answer()


@router.callback_query(F.data.startswith("favorite:toggle:"))
async def callback_favorite_toggle(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    if not db_user:
        await callback.answer("Please start the bot first.", show_alert=True)
        return

    book_id = callback.data.split(":")[-1]

    back_callback = "menu"
    if callback.message and callback.message.reply_markup:
        for row in callback.message.reply_markup.inline_keyboard:
            for btn in row:
                if btn.text == "\u2b05\ufe0f Back":
                    back_callback = btn.callback_data or "menu"
                    break

    is_fav = await db.is_favorite(db_user.id, book_id)

    try:
        if is_fav:
            await db.remove_favorite(db_user.id, book_id)
            await callback.answer("Removed from favorites.")
        else:
            await db.add_favorite(db_user.id, book_id)
            await callback.answer("Added to favorites!")
    except Exception as e:
        logger.error(f"Favorite toggle error: {e}")
        await callback.answer("Error updating favorite.", show_alert=True)
        return

    new_is_fav = not is_fav
    await callback.message.edit_reply_markup(
        reply_markup=book_detail_keyboard(
            book_id=book_id,
            is_favorite=new_is_fav,
            back_callback=back_callback,
        ),
    )


@router.callback_query(F.data.startswith("download:"))
async def callback_download(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    if not db_user:
        await callback.answer("Please start the bot first.", show_alert=True)
        return

    lang = db_user.preferred_language if db_user else None
    await callback.answer()

    parts = callback.data.split(":")
    action = parts[1]

    if action == "confirm":
        book_id = parts[2]
        await process_download(callback, book_id, db_user)
        return

    book_id = parts[1]
    book = await db.get_book(book_id)
    if not book:
        await callback.answer("Book not found.", show_alert=True)
        return

    file_size = book.file_size or 0
    if file_size > settings.max_file_size:
        await callback.message.answer(
            get_text("download_too_large", lang).format(size=format_file_size(file_size)),
            parse_mode="HTML",
            reply_markup=confirm_download_keyboard(book_id),
        )
    else:
        await process_download(callback, book_id, db_user)


async def _resolve_book_url(book: Book, skip_stored: bool = False) -> tuple[Optional[str], Optional[str], Optional[str], Optional[Book]]:
    if book.download_url and not skip_stored:
        logger.info(f"  Using stored download_url: {book.download_url}")
        return (book.download_url, None, None, None)

    if not book.title:
        return (None, None, None, None)

    ext_id = str(book.external_id or book.id)
    logger.info(f"  Title-based search for '{book.title}' (ext_id={ext_id})")
    try:
        async with asyncio.timeout(10):
            results, _ = await api.search_books(book.title, page=1, per_page=10)
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"  Title search error: {e}")
        return (None, None, None, None)

    # Tier 1: exact external_id match — always correct
    for r in results:
        if r.download_url and str(r.id) == ext_id:
            logger.info(f"  Exact ID match: id={r.id}")
            return (r.download_url, r.read_online_url, r.file_token, None)

    # Tier 2: exact title match (case-insensitive)
    normalized = book.title.strip().lower()
    for r in results:
        if r.download_url and r.title.strip().lower() == normalized:
            logger.info(f"  Exact title match: '{r.title}' (id={r.id})")
            return (r.download_url, r.read_online_url, r.file_token, None)

    return (None, None, None, None)


def _get_file_extension(book: Any) -> str:
    ext = getattr(book, "file_extension", None) or ""
    if ext:
        return ext if ext.startswith(".") else f".{ext}"
    dl = getattr(book, "download_url", None) or ""
    url_ext = dl.rsplit(".", 1)[-1].lower() if "." in dl else ""
    known_exts = {"pdf", "epub", "mobi", "azw3", "fb2", "djvu", "txt", "doc", "docx", "rtf", "cbz", "cbr", "zip", "rar"}
    if url_ext in known_exts:
        return f".{url_ext}"
    return ".epub"


async def _send_book_file(
    message: Message,
    book: Any,
    file_bytes: bytes,
    source: Optional[str] = None,
    fmt_override: Optional[str] = None,
) -> None:
    ext = f".{fmt_override.lstrip('.')}" if fmt_override else _get_file_extension(book)
    filename = f"{sanitize_html(book.title)}{ext}"
    filename = filename.replace(" ", "_")
    if len(filename) > 64:
        name_part = filename.rsplit(".", 1)
        if len(name_part) == 2:
            base, ext2 = name_part
            filename = base[:60] + "." + ext2
        else:
            filename = filename[:64]

    file_ext = (fmt_override or getattr(book, "file_extension", None) or ext.lstrip(".")).lstrip(".")
    fmt_emoji = get_format_emoji(file_ext)
    fmt_name = format_extension(file_ext)
    caption = (
        f"{fmt_emoji} <b>{sanitize_html(book.title)}</b>\n"
        f"<i>by {sanitize_html(book.author or 'Unknown')}</i>\n\n"
        f"\U0001f4c1 <b>Format:</b> {fmt_name}  |  "
        f"\U0001f4be <b>Size:</b> {format_file_size(book.file_size)}"
    )

    sent = await message.answer_document(
        document=BufferedInputFile(file=file_bytes, filename=filename),
        caption=caption,
        parse_mode="HTML",
    )

    if sent.document:
        file_id = sent.document.file_id
        convert_key = create_convert_key(file_id, file_ext)
        await sent.edit_reply_markup(
            reply_markup=download_complete_keyboard(book.id, convert_key)
        )


async def _record_successful_download(book_id: str, db_user: DBUser, method: str, book: Any) -> None:
    await db.record_download(
        user_id=db_user.id,
        book_id=book_id,
        method=method,
        file_size=book.file_size,
    )
    await db.increment_download_count(book_id)


async def _try_fallback_file(book: Any, fmt: str) -> tuple[Optional[bytes], Optional[str], Optional[str]]:
    """Find the same title on LibGen when the primary source is blocked.

    Z-Library search works from most hosts, but its ``/dl`` endpoints sit behind
    a Cloudflare challenge that a plain HTTP client cannot pass. Anna's Archive
    is likewise DDoS-Guard protected. LibGen remains downloadable, so use it as
    a cross-source fallback instead of sending the user a link.

    The whole lookup is bounded so it cannot exhaust the serverless time budget.

    Returns ``(file_bytes, extension, source_label)``.
    """
    title = (book.title or "").strip()
    if not title:
        return None, None, None

    from bot.sources.libgen import is_libgen_url

    if book.download_url and is_libgen_url(book.download_url):
        return None, None, None

    try:
        return await asyncio.wait_for(_fallback_file(book, title, fmt), timeout=20)
    except asyncio.TimeoutError:
        logger.warning(f"Fallback download timed out for '{title}'")
        return None, None, None


async def _fallback_file(
    book: Any, title: str, fmt: str
) -> tuple[Optional[bytes], Optional[str], Optional[str]]:
    from bot.sources.dedup import fuzzy_similar, normalize_title
    from bot.sources.libgen import LibGenSource

    target = normalize_title(title)
    author_norm = normalize_title(book.author or "")
    source = LibGenSource()

    results = []
    for query in [f"{title} {book.author or ''}".strip(), title]:
        try:
            found, _ = await asyncio.wait_for(source.search(query, per_page=10), timeout=6)
        except Exception as e:
            logger.debug(f"Fallback LibGen search failed for '{query}': {e}")
            continue
        if found:
            results = found
            break

    if not results:
        return None, None, None

    scored = []
    for result in results:
        candidate = normalize_title(result.title or "")
        if not candidate:
            continue
        score = fuzzy_similar(target, candidate)
        shorter = min(len(target), len(candidate))
        longer = max(len(target), len(candidate)) or 1
        if target and (target in candidate or candidate in target) and shorter >= 0.6 * longer:
            score = max(score, 0.9)
        result_author = normalize_title(result.author or "")
        if author_norm and result_author and (
            author_norm in result_author
            or result_author in author_norm
            or fuzzy_similar(author_norm, result_author) >= 0.7
        ):
            score += 0.05
        if (result.extension or "").lower().lstrip(".") == (fmt or "").lower():
            score += 0.03
        if score >= 0.7:
            scored.append((score, result))

    scored.sort(key=lambda item: -item[0])
    for _, candidate in scored[:2]:
        data = await source.download(
            candidate.download_url,
            fmt=candidate.extension or fmt,
            timeout_seconds=16,
        )
        if data:
            logger.info(f"Fallback LibGen delivered '{candidate.title}' for '{title}'")
            return data, candidate.extension or fmt, "LibGen (fallback)"
    return None, None, None


async def process_download(callback: CallbackQuery, book_id: str, db_user: DBUser) -> None:
    book = await db.get_book(book_id)
    if not book:
        lang = db_user.preferred_language if db_user else None
        await callback.message.answer(get_text("book_not_found", lang))
        return

    fmt = book.file_extension or "epub"
    logger.info(f"process_download: id={book.id} ext_id={book.external_id} title='{book.title}' stored_dl={book.download_url} fmt={fmt} source={book.source}")

    book_source = book.source or ""

    # Step 1: Try Anna's Archive download if the book is from AA
    if book_source == "Anna's Archive" and (book.external_id or book.download_url):
        data, download_source = await source_router.download_book(
            book.external_id or book.id,
            book.download_url or "",
            fmt=fmt,
        )
        if data:
            await _send_book_file(callback.message, book, data, source=download_source)
            await _record_successful_download(book_id, db_user, download_source or "direct", book)
            logger.info(f"Download successful via {download_source}: {book.title}")
            return

    _cf_protected = False

    # Short-circuit: Cloudflare-protected URLs skip HTTP phases entirely
    if book.download_url and _is_cloudflare_protected(book.download_url):
        logger.info("URL is Cloudflare-protected, skipping HTTP — going straight to browser")
        download_url, alt_url, file_token, _ = await _resolve_book_url(book, skip_stored=True)
        if not download_url:
            download_url = book.download_url
            file_token = getattr(book, "file_token", None)
            logger.info("Resolve returned no alternative CF URL — falling back to stored URL")
        _cf_protected = True
    # Fast path: try stored URL directly while starting resolution in parallel
    elif book.download_url:
        resolve_task = asyncio.create_task(_resolve_book_url(book, skip_stored=True))
        data, download_source = await source_router.download_book(
            book.external_id or book.id,
            book.download_url,
            fmt=fmt,
            file_token=getattr(book, "file_token", None),
        )
        if data:
            resolve_task.cancel()
            await _send_book_file(callback.message, book, data, source=download_source)
            await _record_successful_download(book_id, db_user, download_source or "direct", book)
            logger.info(f"Download successful via {download_source}: {book.title}")
            return
        logger.error(
            f"Download returned bad content for {book.title}: "
            f"failed validation or HTML (fmt={fmt})"
        )
        download_url, alt_url, file_token, _ = await resolve_task
        # If resolve_task couldn't find a new URL, fall back to the stored one
        # so the browser downloader (which handles Cloudflare) can still try.
        if not download_url:
            download_url = book.download_url
            file_token = getattr(book, "file_token", None)
            logger.info(f"Resolve returned no alternative URL — falling back to stored URL")
        # Try with alt URL / file_token before giving up on this URL
        if file_token and not data:
            data = await api.download_file(download_url, fmt=fmt, alt_url=alt_url, file_token=file_token)
            if data:
                await _send_book_file(callback.message, book, data, source="Z-Library")
                await _record_successful_download(book_id, db_user, "direct", book)
                logger.info(f"Direct download successful (with token): {book.title}")
                return
    else:
        download_url, alt_url, file_token, _ = await _resolve_book_url(book, skip_stored=True)

    if not download_url:
        data, alt_fmt, alt_source = await _try_fallback_file(book, fmt)
        if data:
            await _send_book_file(
                callback.message, book, data, source=alt_source, fmt_override=alt_fmt
            )
            await _record_successful_download(
                book_id, db_user, alt_source or "fallback", book
            )
            logger.info(f"Fallback download successful for {book.title}")
            return
        lang = db_user.preferred_language if db_user else None
        await callback.message.answer(get_text("download_unavailable", lang))
        await db.record_download(
            user_id=db_user.id,
            book_id=book_id,
            method="api",
            successful=False,
            error="No download URL returned",
        )
        return

    # Phase 2 — direct HTTP (skipped for Cloudflare-protected URLs)
    if not _cf_protected:
        data = await api.download_file(download_url, fmt=fmt, alt_url=alt_url, file_token=file_token)
        if data:
            await _send_book_file(callback.message, book, data, source="Z-Library")
            await _record_successful_download(book_id, db_user, "direct", book)
            logger.info(f"Direct download successful (resolved): {book.title}")
            return
        logger.error(
            f"Resolved download returned bad content for {book.title}: "
            f"failed validation or HTML (fmt={fmt})"
        )

    # Last resort: browser download (try reader domain / token URL first)
    lang = db_user.preferred_language if db_user else None
    fallback_tried = False

    # Vercel has no browser runtime for Cloudflare challenges. Try the
    # cross-source LibGen fallback before wasting the serverless budget on it.
    if settings.is_vercel and (
        _cf_protected or book_source in ("Z-Library", "Anna's Archive", "OpenLibrary")
    ):
        data, alt_fmt, alt_source = await _try_fallback_file(book, fmt)
        fallback_tried = True
        if data:
            await _send_book_file(
                callback.message, book, data, source=alt_source, fmt_override=alt_fmt
            )
            await _record_successful_download(book_id, db_user, alt_source or "fallback", book)
            logger.info(f"Fallback download successful for {book.title}")
            return

    status_msg = await callback.message.answer(get_text("download_loading", lang))
    browser_cookies = {}
    if api._remix_userkey and api._remix_userid:
        browser_cookies = {"remix_userkey": api._remix_userkey, "remix_userid": api._remix_userid}
    result = await try_browser_download(download_url, book_id, alt_url=alt_url, file_token=file_token, remix_cookies=browser_cookies)
    await status_msg.delete()

    if result.success and is_real_file(result.data, fmt):
        await _send_book_file(callback.message, book, result.data, source="Z-Library (browser)")
        await _record_successful_download(book_id, db_user, "browser", book)
        logger.info(f"Browser download successful: {book.title}")
        return

    # Cross-source fallback: Z-Library/AA blocked the file, but LibGen may
    # still have the same title. Deliver the file instead of a link.
    if not fallback_tried:
        data, alt_fmt, alt_source = await _try_fallback_file(book, fmt)
        if data:
            await _send_book_file(
                callback.message, book, data, source=alt_source, fmt_override=alt_fmt
            )
            await _record_successful_download(book_id, db_user, alt_source or "fallback", book)
            logger.info(f"Fallback download successful for {book.title}")
            return

    if result.success:
        logger.error(
            f"Browser download returned bad content for {book.title}: "
            f"{result.data[:100].decode('utf-8', errors='replace')!r} "
            f"(expected {fmt}, got {len(result.data)} bytes)"
        )
        await db.record_download(
            user_id=db_user.id,
            book_id=book_id,
            method="browser",
            successful=False,
            error="Downloaded HTML/garbage instead of file",
        )
        await callback.message.answer(
            get_text("download_link", lang).format(
                title=sanitize_html(book.title),
                author=sanitize_html(book.author or 'Unknown'),
                url=download_url,
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    else:
        await db.record_download(
            user_id=db_user.id,
            book_id=book_id,
            method="link",
            file_size=book.file_size,
        )
        await db.increment_download_count(book_id)
        await callback.message.answer(
            get_text("download_link", lang).format(
                title=sanitize_html(book.title),
                author=sanitize_html(book.author or 'Unknown'),
                url=download_url,
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


async def process_download_from_id(message: Message, book_id: str, db_user: DBUser) -> None:
    lang = db_user.preferred_language if db_user else None
    external_id = book_id.strip()
    book = await db.get_book_by_external_id(external_id)

    if not book:
        await message.answer(get_text("download_not_found", lang).format(id=sanitize_html(external_id)))
        return

    logger.info(f"process_download_from_id: id={book.id} ext_id={book.external_id} title='{book.title}' stored_dl={book.download_url}")
    fmt = book.file_extension or "epub"

    download_url, alt_url, file_token, _ = await _resolve_book_url(book)

    if not download_url:
        data, alt_fmt, alt_source = await _try_fallback_file(book, fmt)
        if data:
            await _send_book_file(message, book, data, source=alt_source, fmt_override=alt_fmt)
            await _record_successful_download(book.id, db_user, alt_source or "fallback", book)
            logger.info(f"Fallback download successful for /download: {book.title}")
            return
        await message.answer(get_text("download_unavailable", lang))
        await db.record_download(
            user_id=db_user.id,
            book_id=book.id,
            method="api",
            successful=False,
            error="No download URL returned",
        )
        return

    # Deliver the actual file when possible; fall back to a link only if every
    # download path fails.
    data, download_source = await source_router.download_book(
        book.external_id or book.id,
        download_url,
        fmt=fmt,
        file_token=file_token,
    )
    if not data:
        data = await api.download_file(download_url, fmt=fmt, alt_url=alt_url, file_token=file_token)
    if data:
        await _send_book_file(message, book, data, source=download_source)
        await _record_successful_download(book.id, db_user, download_source or "direct", book)
        logger.info(f"Direct download successful for /download: {book.title}")
        return

    data, alt_fmt, alt_source = await _try_fallback_file(book, fmt)
    if data:
        await _send_book_file(message, book, data, source=alt_source, fmt_override=alt_fmt)
        await _record_successful_download(book.id, db_user, alt_source or "fallback", book)
        logger.info(f"Fallback download successful for /download: {book.title}")
        return

    await db.record_download(
        user_id=db_user.id,
        book_id=book.id,
        method="link",
        file_size=book.file_size,
    )
    await db.increment_download_count(book.id)

    await message.answer(
        get_text("download_link", lang).format(
            title=sanitize_html(book.title),
            author=sanitize_html(book.author or 'Unknown'),
            url=download_url,
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def fetch_description_openlibrary(title: str, author: Optional[str] = None) -> Optional[str]:
    query = f"{title} {author or ''}".strip()
    params = {"q": query, "limit": 1}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://openlibrary.org/search.json",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
                **proxy_kwargs("https://openlibrary.org/search.json"),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Open Library API returned {resp.status}")
                    return None
                data = await resp.json()
                docs = data.get("docs")
                if not docs:
                    return None
                first = docs[0]
                key = first.get("key")
                if not key:
                    return None
                async with session.get(
                    f"https://openlibrary.org{key}.json",
                    timeout=aiohttp.ClientTimeout(total=10),
                    **proxy_kwargs("https://openlibrary.org"),
                ) as wr:
                    if wr.status != 200:
                        return None
                    work_data = await wr.json()
                    desc_data = work_data.get("description")
                    if isinstance(desc_data, dict):
                        return desc_data.get("value")
                    return desc_data
    except Exception as e:
        logger.warning(f"Open Library fetch failed: {e}")
        return None


async def fetch_description_google_books(title: str, author: Optional[str] = None) -> Optional[str]:
    if not settings.google_books_api_key:
        return None
    query = f"{title} {author or ''}".strip()
    params = {
        "q": query,
        "maxResults": 1,
        "printType": "books",
        "fields": "items(volumeInfo/description)",
        "key": settings.google_books_api_key,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://www.googleapis.com/books/v1/volumes",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
                **proxy_kwargs("https://www.googleapis.com"),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                items = data.get("items")
                if not items:
                    return None
                return items[0].get("volumeInfo", {}).get("description")
    except Exception as e:
        logger.warning(f"Google Books API failed: {e}")
        return None


@router.callback_query(F.data.startswith("desc:"))
async def callback_book_description(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    lang = db_user.preferred_language if db_user else None
    book_id = callback.data.split(":")[-1]
    book = await db.get_book(book_id)
    if not book:
        await callback.answer("Book not found.", show_alert=True)
        return

    description = book.description
    logger.info(f"Description button: book='{book.title}' desc_len={len(description) if description else 0}")

    if not description:
        description = await fetch_description_google_books(book.title, book.author)
    if not description:
        description = await fetch_description_openlibrary(book.title, book.author)

    if description:
        safe_text = sanitize_html(description)
        text = f"<b>{sanitize_html(book.title)}</b>\n\n{safe_text}"
        if len(text) > 4096:
            text = text[:4093] + "..."
        await callback.message.answer(text, parse_mode="HTML")
        await callback.answer()
    else:
        await callback.answer(get_text("desc_no_description", lang), show_alert=True)
        await callback.answer()


@router.callback_query(F.data == "ignore")
async def callback_ignore(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("convert:"))
async def callback_convert(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    lang = db_user.preferred_language if db_user else None
    await callback.answer()
    text = (
        f"{get_text('convert_title', lang)}\n\n"
        f"{get_text('convert_message', lang)}"
    )
    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=get_text("convert_button", lang),
                url="https://t.me/Unfazed_File_Convertor_bot"
            )]
        ])
    )
