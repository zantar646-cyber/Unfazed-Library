"""Shared private storage channel used by the Library <-> Converter bridge.

The Library bot uploads every downloadable file to a private channel and keeps
only the resulting ``message_id``. The Converter bot later calls ``copyMessage``
with that id, which works across bots because no ``file_id`` is exchanged.
"""
from __future__ import annotations

from typing import Any, Optional

from aiogram import Bot
from aiogram.types import BufferedInputFile
from loguru import logger

from bot.config.settings import settings


def storage_chat_id() -> Optional[Any]:
    """Return the configured channel id, or None when the bridge is disabled."""
    raw = (settings.storage_channel_id or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        # Public channel usernames are also accepted by the Bot API.
        return raw if raw.startswith("@") else f"@{raw}"


async def store_file_for_conversion(
    bot: Bot,
    file_bytes: bytes,
    filename: str,
    caption: str,
) -> Optional[int]:
    """Upload a file to the storage channel and return its message id.

    Returns ``None`` when the channel is not configured or the upload fails;
    callers should then fall back to sending the file directly to the user.
    """
    chat_id = storage_chat_id()
    if chat_id is None:
        return None

    try:
        message = await bot.send_document(
            chat_id=chat_id,
            document=BufferedInputFile(file=file_bytes, filename=filename),
            caption=caption[:1024],
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.exception(f"Failed to store file in the conversion channel: {exc}")
        return None

    logger.info(f"Stored conversion file in channel (message_id={message.message_id})")
    return message.message_id
