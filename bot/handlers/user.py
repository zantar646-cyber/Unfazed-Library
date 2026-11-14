from __future__ import annotations

import asyncio
from typing import Optional

from aiogram import F, Router, types
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.database.models import User as DBUser
from bot.database.service import db
from bot.keyboards.inline import main_menu_keyboard
from bot.keyboards.reply import main_reply
from bot.services.api import api
from bot.services.search import search_service
from bot.sources import router as source_router
from bot.utils.helpers import (
    LANGUAGES,
    calculate_pages,
    extract_command_args,
    format_date,
    language_flag,
    safe_edit_or_send,
    sanitize_html,
    set_search_query,
    validate_search_query,
)
from bot.utils.i18n import get_text

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject = None, db_user: Optional[DBUser] = None) -> None:
    lang = db_user.preferred_language if db_user else None

    # Handle referral argument: /start ref_<code>
    if command and command.args and command.args.startswith("ref_"):
        code = command.args[4:]  # strip "ref_" prefix
        try:
            await db.apply_referral(message.from_user.id, code)
        except AttributeError:
            pass  # method not yet available; added by feat-models
        except Exception as e:
            logger.warning(f"apply_referral failed for code='{code}': {e}")

    await message.answer(get_text("start_welcome", lang), reply_markup=main_reply)


@router.message(Command("help"))
@router.message(F.text.lower() == "help")
async def cmd_help(message: Message, db_user: Optional[DBUser] = None) -> None:
    lang = db_user.preferred_language if db_user else None
    text = (
        f"{get_text('help_title', lang)}\n\n"
        f"\U0001f50d {get_text('help_searching_header', lang)}\n"
        f"{get_text('help_searching_items', lang)}\n\n"
        f"\U0001f4c2 {get_text('help_browsing_header', lang)}\n"
        f"{get_text('help_browsing_items', lang)}\n\n"
        f"\U0001f4e5 {get_text('help_downloads_header', lang)}\n"
        f"{get_text('help_downloads_items', lang)}\n\n"
        f"\U0001f464 {get_text('help_account_header', lang)}\n"
        f"{get_text('help_account_items', lang)}\n\n"
        f"\U0001f4a1 {get_text('help_tips_header', lang)}\n"
        f"{get_text('help_tips_items', lang)}\n\n"
        f"{get_text('help_footer', lang)}"
    )
    await message.answer(text, reply_markup=main_menu_keyboard())


@router.message(Command("language"))
async def cmd_language(message: Message, db_user: Optional[DBUser] = None) -> None:
    from bot.keyboards.inline import language_keyboard

    current = db_user.preferred_language if db_user else None
    lang = current
    current_name = ""
    for code, name, _ in LANGUAGES:
        if code == current:
            current_name = f" ({name})"
            break

    await message.answer(
        get_text("language_title_with", lang).format(name=current_name) if current_name
        else get_text("language_title", lang) + "\n\n" + get_text("language_description", lang),
        reply_markup=language_keyboard(current),
    )


@router.callback_query(F.data == "lang:menu")
async def callback_language_menu(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    from bot.keyboards.inline import language_keyboard

    current = db_user.preferred_language if db_user else None
    lang = current
    text = get_text("language_title", lang) + "\n\n" + get_text("language_description", lang)
    await callback.message.edit_text(text, reply_markup=language_keyboard(current))
    await callback.answer()


@router.callback_query(F.data.startswith("lang:set:"))
async def callback_language_set(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    if not db_user:
        await callback.answer("Please start the bot first.", show_alert=True)
        return

    code = callback.data.split(":")[-1]
    await db.update_user_language(db_user.id, code)

    name = code
    for c, n, _ in LANGUAGES:
        if c == code:
            name = n
            break

    from bot.keyboards.inline import language_keyboard
    await callback.message.edit_text(
        get_text("language_title", code) + "\n\n" + get_text("language_set", code).format(name=name),
        reply_markup=language_keyboard(code),
    )
    await callback.answer(f"Language set to {name}")


@router.callback_query(F.data == "lang:clear")
async def callback_language_clear(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    if not db_user:
        return

    await db.update_user_language(db_user.id, None)

    from bot.keyboards.inline import language_keyboard
    await callback.message.edit_text(
        get_text("language_title", None) + "\n\n" + get_text("language_cleared", None),
        reply_markup=language_keyboard(None),
    )
    await callback.answer("Language filter cleared")


@router.message(Command("search"))
@router.message(F.text.lower().startswith("search "))
async def cmd_search(message: Message, db_user: Optional[DBUser] = None) -> None:
    lang = db_user.preferred_language if db_user else None
    query = extract_command_args(message)
    logger.info(f"cmd_search: user={message.from_user.id if message.from_user else '?'} query='{query}'")
    if not query:
        await message.answer(get_text("search_no_query", lang), reply_markup=main_menu_keyboard())
        return

    if not validate_search_query(query):
        logger.warning(f"Invalid search query rejected: '{query}'")
        await message.answer(get_text("search_invalid_query", lang))
        return

    await perform_search(message, query, "all", db_user)


async def perform_search(message: Message, query: str, field: str = "all", db_user: Optional[DBUser] = None) -> None:
    logger.info(f"perform_search: query='{query}' field={field} user={message.from_user.id if message.from_user else '?'}")
    lang = db_user.preferred_language if db_user else None
    sent = await message.answer(get_text("search_loading", lang).format(query=sanitize_html(query)))

    user_id = message.from_user.id or 0
    language = lang

    try:
        if field == "author" or query.lower().startswith("author:"):
            actual_query = query.replace("author:", "", 1).strip()
            logger.info(f"  Author search: '{actual_query}'")
            books, total, from_cache = await search_service.search(user_id, actual_query, page=1, language=language)
        elif field == "isbn" or query.lower().startswith("isbn:"):
            actual_query = query.replace("isbn:", "", 1).strip()
            logger.info(f"  ISBN search: '{actual_query}'")
            books, total, from_cache = await search_service.search(user_id, actual_query, page=1, language=language)
        else:
            logger.info(f"  Title search: '{query}'")
            books, total, from_cache = await search_service.search(user_id, query, page=1, language=language)
    except Exception as e:
        logger.error(f"Search error for '{query}': {e}")
        await sent.edit_text(get_text("search_failed", lang))
        return

    if not books:
        logger.info(f"No results for '{query}'")
        await sent.edit_text(
            get_text("search_no_results", lang).format(query=sanitize_html(query)),
            reply_markup=main_menu_keyboard(),
        )
        return

    set_search_query(message.from_user.id, query)
    total_pages = calculate_pages(total, 10)

    logger.info(f"Search results for '{query}': {len(books)} books, {total_pages} pages, total={total}")
    for b in books[:3]:
        logger.info(f"  DB book: id={b.id} external_id={b.external_id} title='{b.title}' author='{b.author}'")

    from bot.keyboards.inline import book_list_keyboard
    text = get_text("search_results", lang).format(total=total, query=sanitize_html(query))

    await sent.edit_text(
        text,
        reply_markup=book_list_keyboard(
            books=books,
            page=1,
            total_pages=total_pages,
            action_prefix="search",
            back_callback="menu",
        ),
    )





async def _store_search_results(results) -> list:
    return await search_service.store_search_results(results)


@router.message(Command("latest"))
@router.message(F.text.lower() == "latest")
async def cmd_latest(message: Message, db_user: Optional[DBUser] = None) -> None:
    logger.info(f"cmd_latest: user={message.from_user.id if message.from_user else '?'}")
    lang = db_user.preferred_language if db_user else None
    sent = await message.answer(get_text("latest_loading", lang))

    try:
        results = await api.get_recent_books(limit=10)
    except Exception as e:
        logger.error(f"Latest books error: {e}")
        await sent.edit_text(get_text("latest_failed", lang))
        return

    if not results:
        logger.info("No recent books found from API")
        await sent.edit_text(get_text("latest_no_results", lang), reply_markup=main_menu_keyboard())
        return

    books = await _store_search_results(results)
    logger.info(f"cmd_latest: {len(books)} books displayed")

    from bot.keyboards.inline import book_list_keyboard
    await sent.edit_text(
        get_text("latest_title", lang),
        reply_markup=book_list_keyboard(
            books=books, page=1, total_pages=1,
            action_prefix="latest", back_callback="menu",
        ),
    )


@router.message(Command("download"))
async def cmd_download(message: Message, command: CommandObject, db_user: Optional[DBUser] = None) -> None:
    if not db_user:
        await message.answer("Please start the bot first with /start.")
        return

    lang = db_user.preferred_language if db_user else None
    book_id = command.args.strip() if command.args else None
    if not book_id:
        await message.answer(get_text("download_usage", lang))
        return

    from bot.handlers.book import process_download_from_id
    await process_download_from_id(message, book_id, db_user)


@router.message(Command("profile"))
@router.message(F.text.lower() == "profile")
async def cmd_profile(message: Message, db_user: Optional[DBUser] = None) -> None:
    if not db_user:
        return

    user = await db.get_user(db_user.id)
    if not user:
        lang = db_user.preferred_language if db_user else None
        await message.answer(get_text("user_not_found", lang))
        return

    reg_date = format_date(user.registered_at)
    last_active = format_date(user.last_active_at) if user.last_active_at else "N/A"
    fav_count_result = await db.get_user_favorites(user.id, page=1, per_page=1)
    _, fav_total = fav_count_result

    lang = user.preferred_language
    lang_display = get_text("profile_any_lang", lang)
    if user.preferred_language:
        for code, name, _ in LANGUAGES:
            if code == user.preferred_language:
                lang_display = name
                break

    text = (
        f"{get_text('profile_title', lang)}\n\n"
        f"{get_text('profile_id', lang).format(id=user.id)}\n"
        f"{get_text('profile_username', lang).format(username=sanitize_html(user.username or 'N/A'))}\n"
        f"{get_text('profile_name', lang).format(name=sanitize_html(user.first_name or 'N/A'))}\n"
        f"{get_text('profile_language', lang).format(lang=lang_display)}\n"
        f"{get_text('profile_registered', lang).format(date=reg_date)}\n"
        f"{get_text('profile_last_active', lang).format(date=last_active)}\n"
        f"{get_text('profile_downloads', lang).format(count=user.total_downloads)}\n"
        f"{get_text('profile_favorites', lang).format(count=fav_total)}"
    )
    await message.answer(text, reply_markup=main_menu_keyboard())


@router.message(F.text.lower() == "categories")
async def cmd_categories(message: Message, db_user: Optional[DBUser] = None) -> None:
    logger.info(f"cmd_categories: user={message.from_user.id if message.from_user else '?'}")
    lang = db_user.preferred_language if db_user else None
    categories = await db.get_all_categories()

    # The serverless SQLite database lives in /tmp and starts empty on a cold
    # instance. Re-seed so the Categories button always opens a real list.
    if not categories:
        await db.seed_categories()
        categories = await db.get_all_categories()

    if not categories:
        await message.answer(get_text("categories_no_results", lang))
        return

    from bot.keyboards.inline import category_list_keyboard

    items_per_page = 5
    total_pages = max(1, calculate_pages(len(categories), items_per_page))
    page_categories = categories[:items_per_page]

    await message.answer(
        get_text("categories_title", lang),
        reply_markup=category_list_keyboard(page_categories, 1, total_pages),
    )


@router.message(F.text.lower() == "popular")
async def cmd_popular(message: Message, db_user: Optional[DBUser] = None) -> None:
    logger.info(f"cmd_popular: user={message.from_user.id if message.from_user else '?'}")
    lang = db_user.preferred_language if db_user else None
    sent = await message.answer(get_text("popular_loading", lang))
    try:
        results = await api.get_popular_books(limit=10)
    except Exception as e:
        logger.error(f"Popular books error: {e}")
        await sent.edit_text(get_text("popular_failed", lang))
        return

    if not results:
        logger.info("No popular books found from API")
        await sent.edit_text(get_text("popular_no_results", lang), reply_markup=main_menu_keyboard())
        return

    books = await _store_search_results(results)
    logger.info(f"cmd_popular: {len(books)} books displayed")

    from bot.keyboards.inline import book_list_keyboard
    await sent.edit_text(
        get_text("popular_title", lang),
        reply_markup=book_list_keyboard(
            books=books, page=1, total_pages=1,
            action_prefix="popular", back_callback="menu",
        ),
    )


@router.message(F.text.lower() == "recent")
async def cmd_recent(message: Message) -> None:
    await cmd_latest(message)


@router.message(F.text.lower() == "favorites")
@router.message(Command("favorites"))
async def cmd_favorites(message: Message, db_user: Optional[DBUser] = None) -> None:
    if not db_user:
        return

    lang = db_user.preferred_language if db_user else None
    favorites, total = await db.get_user_favorites(db_user.id, page=1, per_page=10)

    if not favorites:
        await message.answer(get_text("favorites_empty", lang), reply_markup=main_menu_keyboard())
        return

    from bot.keyboards.inline import book_list_keyboard

    total_pages = calculate_pages(total, 10)
    books = [fav.book for fav in favorites if fav.book]

    text = get_text("favorites_title", lang).format(total=total)
    await message.answer(
        text,
        reply_markup=book_list_keyboard(
            books=books,
            page=1,
            total_pages=total_pages,
            action_prefix="favorites",
            back_callback="menu",
        ),
    )


@router.message(F.text.lower() == "history")
@router.message(F.text.lower() == "📋 history")
@router.message(Command("history"))
async def cmd_history(message: Message, db_user: Optional[DBUser] = None) -> None:
    if not db_user:
        return

    lang = db_user.preferred_language if db_user else None
    downloads, total = await db.get_user_download_history(db_user.id, page=1, per_page=10)

    if not downloads:
        await message.answer(get_text("history_empty", lang), reply_markup=main_menu_keyboard())
        return

    from bot.keyboards.inline import pagination_keyboard

    total_pages = calculate_pages(total, 10)
    text = get_text("history_title", lang) + "\n\n"
    for dl in downloads:
        book_title = sanitize_html(dl.book.title) if dl.book else get_text("history_unknown_book", lang)
        date_str = dl.downloaded_at.strftime("%b %d, %Y") if dl.downloaded_at else "N/A"
        text += get_text("history_entry", lang).format(title=book_title, date=date_str) + "\n"

    await message.answer(
        text,
        reply_markup=pagination_keyboard(1, total_pages, "history", "menu"),
    )


@router.message(Command("share"))
async def cmd_share(message: Message, db_user: Optional[DBUser] = None) -> None:
    if not db_user:
        await message.answer("Please start the bot first with /start.")
        return

    lang = db_user.preferred_language if db_user else None

    # Retrieve (or generate) the user's referral code
    try:
        code = await db.get_or_create_referral_code(db_user.id)
    except AttributeError:
        # Method not yet available — will be added by feat-models worker
        await message.answer(
            get_text("share_unavailable", lang) if get_text("share_unavailable", lang) != "share_unavailable"
            else "🔗 Referral feature coming soon! Check back later.",
        )
        return

    # Build the share link using bot username if obtainable
    try:
        bot_me = await message.bot.get_me()
        bot_username = bot_me.username
        share_link = f"https://t.me/{bot_username}?start=ref_{code}"
    except Exception:
        share_link = f"ref_{code}"

    text = (
        f"🔗 <b>Share this bot with friends!</b>\n\n"
        f"Your referral link:\n<code>{share_link}</code>\n\n"
        f"When a friend joins using your link, you'll both get rewards! 🎁"
    )
    await message.answer(text, parse_mode="HTML")


@router.callback_query(F.data.startswith("search:format:"))
async def callback_search_format(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    if not db_user:
        await callback.answer()
        return

    lang = db_user.preferred_language if db_user else None
    fmt = callback.data.split(":")[-1]  # pdf / epub / mobi / all

    user_id = callback.from_user.id
    session = search_service.get_session(user_id)
    if not session or not session.results:
        await callback.answer("No active search session. Please search again.", show_alert=True)
        return

    # Store chosen format in session
    session.format_filter = fmt if fmt != "all" else None

    # Filter results
    if fmt == "all":
        filtered = session.results
    else:
        filtered = [b for b in session.results if getattr(b, "file_extension", "").lower() == fmt]

    total_filtered = len(filtered)
    per_page = 10
    total_pages = max(1, calculate_pages(total_filtered, per_page))
    page_books = filtered[:per_page]

    from bot.keyboards.inline import book_list_keyboard

    active_format = fmt if fmt != "all" else None
    if not page_books:
        await callback.answer(f"No {fmt.upper()} books in current results.", show_alert=True)
        return

    text = (
        get_text("search_results", lang).format(total=total_filtered, query=sanitize_html(session.query))
        + (f"\n<i>Filter: {fmt.upper()}</i>" if fmt != "all" else "")
    )

    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=book_list_keyboard(
            books=page_books,
            page=1,
            total_pages=total_pages,
            action_prefix="search",
            back_callback="menu",
            active_format=active_format,
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "search:lang:toggle")
async def callback_search_lang_toggle(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    if not db_user:
        await callback.answer()
        return

    lang = db_user.preferred_language if db_user else None

    # Toggle preferred_language: set → None, None → "english"
    new_lang = None if lang else "english"

    # Save to DB
    try:
        await db.update_user_language(db_user.id, new_lang)
        db_user.preferred_language = new_lang
    except Exception as e:
        logger.warning(f"update_user_language failed: {e}")

    # Re-run last search with updated language
    user_id = callback.from_user.id
    session = search_service.get_session(user_id)
    if not session:
        await callback.answer(
            f"Language set to {new_lang or 'Any'}. Search again to apply.",
            show_alert=True,
        )
        return

    query = session.query
    try:
        books, total, _ = await search_service.search(user_id, query, page=1, language=new_lang)
    except Exception as e:
        logger.error(f"Re-search after lang toggle failed: {e}")
        await callback.answer("Failed to refresh search results.", show_alert=True)
        return

    from bot.keyboards.inline import book_list_keyboard

    total_pages = max(1, calculate_pages(total, 10))
    text = get_text("search_results", new_lang).format(total=total, query=sanitize_html(query))

    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=book_list_keyboard(
            books=books,
            page=1,
            total_pages=total_pages,
            action_prefix="search",
            back_callback="menu",
        ),
    )
    await callback.answer(f"Language filter: {new_lang.capitalize() if new_lang else 'Any'}")


@router.message()
async def handle_text(message: Message, db_user: Optional[DBUser] = None) -> None:
    text = message.text
    if not text:
        return

    if not validate_search_query(text):
        return

    logger.info(f"handle_text (direct search): user={message.from_user.id if message.from_user else '?'} query='{text}'")
    await perform_search(message, text, "all", db_user)


@router.callback_query(F.data == "menu")
async def callback_menu(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    lang = db_user.preferred_language if db_user else None
    await safe_edit_or_send(
        callback.message,
        get_text("menu_text", lang),
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "search:prompt")
async def callback_search_prompt(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    lang = db_user.preferred_language if db_user else None
    await callback.answer()
    await callback.message.answer(
        get_text("search_prompt", lang),
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(F.data == "help")
async def callback_help(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    await cmd_help(callback.message, db_user)
    await callback.answer()


@router.callback_query(F.data == "books:popular")
async def callback_books_popular(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    await cmd_popular(callback.message, db_user)
    await callback.answer()


@router.callback_query(F.data == "books:latest")
async def callback_books_latest(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    await cmd_latest(callback.message, db_user)
    await callback.answer()


@router.callback_query(F.data == "favorites:list:1")
async def callback_favorites_list(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    await cmd_favorites(callback.message, db_user)
    await callback.answer()


@router.callback_query(F.data == "history:list:1")
async def callback_history_list(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    await cmd_history(callback.message, db_user)
    await callback.answer()


@router.callback_query(F.data.startswith("history:page:"))
async def callback_history_page(callback: CallbackQuery, db_user: Optional[DBUser] = None) -> None:
    if not db_user:
        return

    lang = db_user.preferred_language if db_user else None
    page = int(callback.data.split(":")[-1])
    downloads, total = await db.get_user_download_history(db_user.id, page=page, per_page=10)
    total_pages = calculate_pages(total, 10)

    from bot.keyboards.inline import pagination_keyboard

    text = get_text("history_page", lang).format(page=page, total=total_pages)
    for dl in downloads:
        book_title = sanitize_html(dl.book.title) if dl.book else get_text("history_unknown_book", lang)
        date_str = dl.downloaded_at.strftime("%b %d, %Y") if dl.downloaded_at else "N/A"
        text += get_text("history_entry", lang).format(title=book_title, date=date_str) + "\n"

    await callback.message.edit_text(
        text,
        reply_markup=pagination_keyboard(page, total_pages, "history", "menu"),
    )
    await callback.answer()
