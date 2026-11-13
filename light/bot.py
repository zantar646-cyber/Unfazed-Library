"""Lightweight Telegram book-search bot entry point.

Run:  python light/bot.py   (from the repo root, .env loaded from cwd)
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError

try:
    from light.browser import close_browser, init_browser
    from light.config import (
        BOT_TOKEN,
        LOG_LEVEL,
        RATE_LIMIT_PER_USER,
        RATE_LIMIT_WINDOW,
        TELEGRAM_PROXY,
        TELEGRAM_REQUEST_TIMEOUT,
        aa,
        zl,
    )
    from light.handlers import RateLimitMiddleware, router
    from light.features import features_router
except ImportError:  # running directly: python light/bot.py
    from browser import close_browser, init_browser  # type: ignore
    from config import (  # type: ignore
        BOT_TOKEN,
        LOG_LEVEL,
        RATE_LIMIT_PER_USER,
        RATE_LIMIT_WINDOW,
        TELEGRAM_PROXY,
        TELEGRAM_REQUEST_TIMEOUT,
        aa,
        zl,
    )
    from handlers import RateLimitMiddleware, router  # type: ignore
    from features import features_router  # type: ignore

RETRY_LIMIT = 5


async def retry_middleware(make_request, bot, method):
    """Retry flaky Telegram API calls with exponential backoff."""
    log = logging.getLogger("light.bot")
    for attempt in range(RETRY_LIMIT):
        try:
            return await make_request(bot, method)
        except TelegramRetryAfter as exc:
            if attempt == RETRY_LIMIT - 1:
                raise
            await asyncio.sleep(min(exc.retry_after, 30))
        except (TelegramNetworkError, TelegramServerError, asyncio.TimeoutError):
            if attempt == RETRY_LIMIT - 1:
                raise
            log.warning(
                "Telegram request %s failed (attempt %s/%s), retrying",
                type(method).__name__,
                attempt + 1,
                RETRY_LIMIT,
            )
            await asyncio.sleep(min(2**attempt, 5))


def build_session() -> AiohttpSession:
    session = AiohttpSession(
        timeout=TELEGRAM_REQUEST_TIMEOUT,
        proxy=TELEGRAM_PROXY or None,
    )
    session.middleware.register(retry_middleware)
    return session


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def main() -> None:
    setup_logging()
    log = logging.getLogger("light.bot")

    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set. Add it to .env and try again.")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=build_session(),
    )
    dp = Dispatcher()
    dp.message.middleware(RateLimitMiddleware(limit=RATE_LIMIT_PER_USER, window=RATE_LIMIT_WINDOW))
    # features first so the reply-menu text routing runs before generic search.
    dp.include_router(features_router)
    dp.include_router(router)

    @dp.startup()
    async def on_startup() -> None:
        await zl.initialize()
        await aa.initialize()
        with suppress(Exception):
            await init_browser()
        log.info("Light Library bot started (Z-Library: %s, Anna's Archive: %s)", zl.base_url, aa.base_url)

    @dp.shutdown()
    async def on_shutdown() -> None:
        await zl.close()
        await aa.close()
        with suppress(Exception):
            await close_browser()
        with suppress(Exception):
            await bot.session.close()
        log.info("Bot shut down cleanly")

    try:
        await dp.start_polling(bot)
    except TelegramNetworkError as exc:
        log.error(
            "Could not reach the Telegram API: %s. "
            "Check your internet connection or the TELEGRAM_PROXY setting.",
            exc,
        )
    finally:
        with suppress(Exception):
            await dp.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.getLogger("light.bot").info("Interrupted by user, exiting")
