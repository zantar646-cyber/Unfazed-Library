from __future__ import annotations

import time
from collections import defaultdict
from typing import Awaitable, Callable, Dict, List

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, CallbackQuery
from loguru import logger

from bot.config.settings import settings


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.user_requests: Dict[int, List[float]] = defaultdict(list)
        self.max_requests = settings.rate_limit_per_user
        self.window = settings.rate_limit_window

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable],
        event: TelegramObject,
        data: dict,
    ) -> None:
        if isinstance(event, (Message, CallbackQuery)):
            user_id = event.from_user.id if event.from_user else None
            if user_id:
                now = time.monotonic()
                user_history = self.user_requests[user_id]
                cutoff = now - self.window

                self.user_requests[user_id] = [t for t in user_history if t > cutoff]

                if len(self.user_requests[user_id]) >= self.max_requests:
                    retry_after = int(self.user_requests[user_id][0] + self.window - now)
                    logger.warning(f"Rate limit exceeded for user {user_id}")

                    if isinstance(event, Message):
                        await event.answer(
                            f"Please slow down. You can try again in {retry_after} seconds."
                        )
                    elif isinstance(event, CallbackQuery):
                        await event.answer(
                            f"Please wait {retry_after}s before next action.",
                            show_alert=True,
                        )
                    return

                self.user_requests[user_id].append(now)

        await handler(event, data)
