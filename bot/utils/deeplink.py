"""Deep-link payloads for the Library -> Converter bot bridge.

Telegram bots cannot talk to each other, and a ``file_id`` is only valid for
the bot that received it. Files are therefore stored in a shared private
channel, and the Library bot sends the user to the Converter bot with the
channel message id as the start payload.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from typing import Optional

from bot.config.settings import settings

# Telegram allows A-Z, a-z, 0-9, _ and - in a ?start= payload, max 64 chars.
_PAYLOAD_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_MESSAGE_ID_DIGITS = 15


def _sign(payload: str) -> str:
    return hmac.new(
        settings.deeplink_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]


def build_convert_payload(storage_message_id: int) -> str:
    """Build a safe ``?start=`` payload for a storage-channel message."""
    message_id = int(storage_message_id)
    if message_id <= 0:
        raise ValueError("storage_message_id must be positive")
    if len(str(message_id)) > _MAX_MESSAGE_ID_DIGITS:
        raise ValueError("storage_message_id is too large for a start payload")

    payload = f"convert_{message_id}"
    if settings.deeplink_secret:
        payload = f"{payload}_{_sign(payload)}"

    if not _PAYLOAD_RE.match(payload):
        raise ValueError(f"Invalid deep-link payload: {payload!r}")
    return payload


def _converter_username() -> str:
    return (settings.converter_bot_username or "").strip().lstrip("@")


def converter_bot_link() -> Optional[str]:
    """Return the plain t.me link to the Converter bot (no start payload).

    Used as a fallback when no shared storage channel is configured: the button
    still opens the Converter bot, the user just forwards the file manually
    instead of the bridge handing it over automatically.
    """
    username = _converter_username()
    return f"https://t.me/{username}" if username else None


def build_convert_deeplink(storage_message_id: int) -> str:
    """Return the t.me deep link that opens the Converter bot."""
    username = _converter_username()
    if not username:
        raise ValueError("CONVERTER_BOT_USERNAME is not configured")
    return f"https://t.me/{username}?start={build_convert_payload(storage_message_id)}"
