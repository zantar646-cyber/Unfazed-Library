from __future__ import annotations

import asyncio
from typing import Optional

from aiogram import F, Router, types
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.config.settings import settings
from bot.database.models import User as DBUser
from bot.database.service import db
from bot.keyboards.inline import admin_menu_keyboard, close_keyboard
from bot.services.api import api
from bot.utils.helpers import calculate_pages, format_date, sanitize_html

router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


@router.message(Command("admin"))
async def cmd_admin(message: Message, db_user: Optional[DBUser] = None) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("Access denied. You are not an administrator.")
        return

    await message.answer(
        "<b>Admin Panel</b>\n\nWelcome to the administration panel.",
        reply_markup=admin_menu_keyboard(),
    )


@router.callback_query(F.data.startswith("admin:"))
async def callback_admin(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    action = callback.data.split(":")[1]

    if action == "dashboard":
        await show_dashboard(callback)
    elif action == "users":
        page = int(callback.data.split(":")[2]) if len(callback.data.split(":")) > 2 else 1
        await show_users(callback, page)
    elif action == "downloads":
        await show_downloads(callback)
    elif action == "banned":
        await show_banned(callback)
    elif action == "broadcast":
        await start_broadcast(callback)
    elif action == "logs":
        await show_logs(callback)
    elif action == "close":
        await callback.message.delete()
    else:
        await callback.answer("Unknown action.")

    await callback.answer()


async def show_dashboard(callback: CallbackQuery) -> None:
    stats = await db.get_dashboard_stats()
    new_today = await db.get_new_users_today()
    top_books = await db.get_top_downloaded_books(limit=5)

    text = (
        "<b>📊 Admin Dashboard</b>\n\n"
        f"<b>Users:</b>\n"
        f"• Total: {stats['total_users']:,}\n"
        f"• Active: {stats['active_users']:,}\n"
        f"• New Today: {new_today:,}\n\n"
        f"<b>Content:</b>\n"
        f"• Books: {stats['total_books']:,}\n"
        f"• Downloads: {stats['total_downloads']:,}\n"
        f"• Favorites: {stats['total_favorites']:,}\n\n"
    )

    if top_books:
        text += "<b>Top Downloaded Books:</b>\n"
        for i, book in enumerate(top_books[:5], 1):
            text += f"{i}. {sanitize_html(book.title)} — {book.download_count} downloads\n"

    await callback.message.edit_text(text, reply_markup=admin_menu_keyboard())


async def show_users(callback: CallbackQuery, page: int = 1) -> None:
    users, total = await db.get_users_by_page(page=page, per_page=10)
    total_pages = calculate_pages(total, 10)

    text = f"<b>Users</b> (Page {page}/{total_pages}) — Total: {total:,}\n\n"
    for user in users:
        name = user.first_name or "N/A"
        username = f"@{user.username}" if user.username else "no username"
        status = "🔴 Banned" if user.is_banned else "🟢 Active"
        reg_date = format_date(user.registered_at)
        text += (
            f"• <b>{sanitize_html(name)}</b> {username}\n"
            f"  ID: <code>{user.id}</code> | {status} | {reg_date}\n"
        )

    from bot.keyboards.inline import pagination_keyboard
    await callback.message.edit_text(
        text,
        reply_markup=pagination_keyboard(
            page, total_pages, "admin:users", "admin:dashboard"
        ),
    )


@router.callback_query(F.data.startswith("admin:users:page:"))
async def callback_admin_users_page(callback: CallbackQuery) -> None:
    page = int(callback.data.split(":")[-1])
    await show_users(callback, page)


@router.callback_query(F.data == "admin:dashboard")
async def callback_admin_dashboard(callback: CallbackQuery) -> None:
    await show_dashboard(callback)


async def show_downloads(callback: CallbackQuery) -> None:
    stats = await db.get_download_stats(days=30)

    text = (
        "<b>📥 Download Statistics</b>\n\n"
        f"• Total Downloads: {stats['total_downloads']:,}\n"
        f"• Last 30 Days: {stats['downloads_last_30_days']:,}\n\n"
        "<b>Top Downloaded Books:</b>\n"
    )

    for i, book in enumerate(stats.get("top_books", [])[:10], 1):
        text += f"{i}. {sanitize_html(book['title'])} — {book['count']} downloads\n"

    if not stats.get("top_books"):
        text += "No downloads recorded yet.\n"

    await callback.message.edit_text(text, reply_markup=admin_menu_keyboard())


async def show_banned(callback: CallbackQuery) -> None:
    banned = await db.get_banned_users()

    text = "<b>🔴 Banned Users</b>\n\n"
    if not banned:
        text += "No banned users."
    else:
        for user in banned:
            name = user.first_name or "N/A"
            username = f"@{user.username}" if user.username else "no username"
            text += f"• <b>{sanitize_html(name)}</b> {username} (ID: <code>{user.id}</code>)\n"

    await callback.message.edit_text(text, reply_markup=admin_menu_keyboard())


async def start_broadcast(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "<b>📢 Broadcast Message</b>\n\n"
        "Reply to this message with the text you want to broadcast to all users.\n\n"
        "Format with HTML tags is supported.",
        reply_markup=close_keyboard(),
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return

    stats = await db.get_dashboard_stats()
    await message.answer(
        f"<b>📊 Quick Stats</b>\n\n"
        f"Users: {stats['total_users']:,}\n"
        f"Books: {stats['total_books']:,}\n"
        f"Downloads: {stats['total_downloads']:,}\n"
        f"Favorites: {stats['total_favorites']:,}",
        parse_mode="HTML",
    )


@router.message(Command("users"))
async def cmd_users(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return

    count = await db.get_user_count()
    await message.answer(f"Total active users: <b>{count:,}</b>")


@router.message(Command("downloads"))
async def cmd_downloads(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return

    stats = await db.get_download_stats(days=30)
    await message.answer(
        f"<b>Download Stats</b>\n\n"
        f"Total: {stats['total_downloads']:,}\n"
        f"Last 30 days: {stats['downloads_last_30_days']:,}",
        parse_mode="HTML",
    )


@router.message(Command("banned"))
async def cmd_banned(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return

    banned = await db.get_banned_users()
    text = f"<b>Banned Users: {len(banned)}</b>\n\n"
    for user in banned:
        text += f"• {sanitize_html(user.first_name or 'N/A')} (ID: <code>{user.id}</code>)\n"
    await message.answer(text, parse_mode="HTML")


@router.message(Command("ban"))
async def cmd_ban(message: Message, command: CommandObject) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return

    if not command.args:
        await message.answer("Usage: /ban <user_id>")
        return

    try:
        user_id = int(command.args.strip())
        success = await db.ban_user(user_id)
        if success:
            await message.answer(f"User <code>{user_id}</code> has been banned.")
            await db.log_admin_action(
                admin_id=message.from_user.id,
                action="ban_user",
                target_type="user",
                target_id=str(user_id),
            )
        else:
            await message.answer(f"User <code>{user_id}</code> not found.")
    except ValueError:
        await message.answer("Invalid user ID.")


@router.message(Command("unban"))
async def cmd_unban(message: Message, command: CommandObject) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return

    if not command.args:
        await message.answer("Usage: /unban <user_id>")
        return

    try:
        user_id = int(command.args.strip())
        success = await db.unban_user(user_id)
        if success:
            await message.answer(f"User <code>{user_id}</code> has been unbanned.")
            await db.log_admin_action(
                admin_id=message.from_user.id,
                action="unban_user",
                target_type="user",
                target_id=str(user_id),
            )
        else:
            await message.answer(f"User <code>{user_id}</code> not found.")
    except ValueError:
        await message.answer("Invalid user ID.")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return

    if not command.args:
        await message.answer("Usage: /broadcast <message>")
        return

    text = command.args
    sent_msg = await message.answer("Broadcasting message to all users...")

    users, total = await db.get_all_users(page=1, per_page=10000)
    success_count = 0
    fail_count = 0

    for user in users:
        if user.is_banned or not user.is_active:
            continue
        try:
            await message.bot.send_message(
                chat_id=user.id,
                text=f"<b>📢 Broadcast</b>\n\n{text}",
                parse_mode="HTML",
            )
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            fail_count += 1
            logger.warning(f"Broadcast failed for user {user.id}: {e}")

    await sent_msg.edit_text(
        f"<b>Broadcast Complete</b>\n\n"
        f"Sent: {success_count}\n"
        f"Failed: {fail_count}\n"
        f"Total active users processed: {success_count + fail_count}",
    )

    await db.log_admin_action(
        admin_id=message.from_user.id,
        action="broadcast",
        details=f"Sent: {success_count}, Failed: {fail_count}",
    )


async def show_logs(callback: CallbackQuery) -> None:
    logs = await db.get_admin_logs(limit=20)

    text = "<b>📋 Admin Logs (Last 20)</b>\n\n"
    if not logs:
        text += "No admin actions recorded yet."
    else:
        for log in logs:
            date_str = format_date(log.created_at)
            text += (
                f"• <b>{sanitize_html(log.action)}</b> by <code>{log.admin_id}</code>\n"
                f"  {date_str}\n"
            )

    await callback.message.edit_text(text, reply_markup=admin_menu_keyboard())


@router.message(Command("system_status"))
async def cmd_system_status(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return

    status = await api.get_status()
    mirror = status.get("mirror", {})
    active_url = mirror.get("active_mirror", "N/A")
    caps = mirror.get("mirrors", [])
    active_caps = {}
    for m in caps:
        if m.get("url") == active_url:
            active_caps = m.get("capabilities", {})
            break

    lines = [
        "<b>🔧 System Status</b>\n",
        f"<b>Active Mirror:</b> <code>{active_url}</code>",
    ]

    if caps:
        healthy = sum(1 for m in caps if m.get("healthy"))
        total = len(caps)
        lines.append(f"<b>Mirrors:</b> {healthy}/{total} healthy")
        for m in caps:
            status_icon = "🟢" if m.get("healthy") else "🔴"
            active_mark = " ← active" if m.get("active") else ""
            failures = m.get("consecutive_failures", 0)
            lines.append(f"  {status_icon} <code>{m['url']}</code>{active_mark} (failures: {failures})")
    else:
        lines.append("<b>Mirrors:</b> Not configured")

    lines.append("")
    lines.append("<b>Capabilities:</b>")
    lines.append(f"  Search: {'✅' if active_caps.get('search') else '❌'}")
    lines.append(f"  Categories: {'✅' if active_caps.get('categories') else '❌'}")
    lines.append(f"  Downloads: {'✅' if active_caps.get('downloads') else '❌'}")
    lines.append(f"  Book Details: {'✅' if active_caps.get('book_details') else '❌'}")

    lines.append("")
    lines.append(f"<b>Authentication:</b> {'✅ Authenticated' if status.get('authenticated') else '❌ Not authenticated'}")
    cache_info = status.get("cache", {})
    lines.append(f"<b>Cache:</b> {'✅ Enabled' if cache_info.get('enabled') else '⚠ Disabled'}")

    await message.answer("\n".join(lines))
