from __future__ import annotations

from typing import Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, CallbackQuery
from loguru import logger

from bot.database.service import db


class RegistrationMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable],
        event: TelegramObject,
        data: dict,
    ) -> None:
        if isinstance(event, (Message, CallbackQuery)):
            user = event.from_user
            if user and not user.is_bot:
                try:
                    db_user = await db.get_or_create_user(
                        telegram_id=user.id,
                        username=user.username,
                        first_name=user.first_name,
                        last_name=user.last_name,
                        language_code=user.language_code,
                    )
                    data["db_user"] = db_user

                    if db_user.is_banned:
                        if isinstance(event, Message):
                            await event.answer(
                                "Your account has been banned. Contact support for assistance."
                            )
                        elif isinstance(event, CallbackQuery):
                            await event.answer(
                                "Your account has been banned. Contact support for assistance.",
                                show_alert=True,
                            )
                        return
                except Exception as e:
                    logger.error(f"Registration middleware error: {e}")

        await handler(event, data)
