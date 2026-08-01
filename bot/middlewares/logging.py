from __future__ import annotations

import time
from typing import Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, CallbackQuery
from loguru import logger


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable],
        event: TelegramObject,
        data: dict,
    ) -> None:
        start = time.monotonic()

        if isinstance(event, Message):
            user = event.from_user
            logger.info(
                f"Message from {user.id} (@{user.username or 'N/A'}): "
                f"'{event.text or '[non-text]'}'"
            )
        elif isinstance(event, CallbackQuery):
            user = event.from_user
            logger.info(
                f"Callback from {user.id} (@{user.username or 'N/A'}): "
                f"'{event.data}'"
            )

        await handler(event, data)

        elapsed = time.monotonic() - start
        if isinstance(event, (Message, CallbackQuery)):
            logger.debug(f"Handler took {elapsed:.3f}s for {event.from_user.id if event.from_user else 'unknown'}")
