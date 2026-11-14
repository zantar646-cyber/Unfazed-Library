"""Helper for wiring the shared storage channel.

The Library <-> Converter bridge needs the numeric id of a private channel
(`-100...`). Adding a bot to a channel is an update the bot actually receives,
so the bot can report the id instead of making the operator hunt for it.
"""
from __future__ import annotations

from aiogram import Bot, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import ChatMemberUpdated
from loguru import logger

from bot.config.settings import settings

router = Router()

_ACTIVE_STATUSES = {
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.CREATOR,
}


def build_channel_id_text(chat_id: int, title: str) -> str:
    return (
        "\U0001f4e1 <b>Channel connected</b>\n\n"
        f"<b>{title}</b>\n"
        f"<code>{chat_id}</code>\n\n"
        "Use this as <code>STORAGE_CHANNEL_ID</code> in both the Library and "
        "Converter bots. Both bots must stay administrators of this channel."
    )


def _is_trusted(user_id: int) -> bool:
    # Before ADMIN_IDS is configured the first operator has to be able to
    # finish the setup, so an empty list means "allow".
    return not settings.admin_ids or user_id in settings.admin_ids


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated) -> None:
    if event.chat.type not in (ChatType.CHANNEL, ChatType.SUPERGROUP):
        return
    if event.new_chat_member.status not in _ACTIVE_STATUSES:
        return

    added_by = event.from_user
    if added_by and not added_by.is_bot and not _is_trusted(added_by.id):
        logger.info(f"Bot added to chat {event.chat.id} by untrusted user {added_by.id}")
        return

    text = build_channel_id_text(event.chat.id, event.chat.title or "Untitled chat")

    if added_by and not added_by.is_bot:
        try:
            await event.bot.send_message(added_by.id, text)
            return
        except Exception as exc:
            logger.debug(f"Could not DM channel id to {added_by.id}: {exc}")

    # Fallback: the bot was just promoted, so it can post in the chat itself.
    try:
        await event.bot.send_message(event.chat.id, text)
    except Exception as exc:
        logger.warning(f"Could not report chat id for {event.chat.id}: {exc}")
