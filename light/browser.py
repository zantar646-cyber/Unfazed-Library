"""Headless-browser download fallback for JS-challenged hosts.

Z-Library's /dl/ endpoints return a Cloudflare "Checking your browser"
challenge over plain HTTP, so the aiohttp path can never fetch the file.  A
real Chromium (via Playwright) executes the challenge and catches the download.

Modeled on the original bot's bot/utils/browser_downloader.py.  Degrades
gracefully (returns None) when Playwright or the browser binary is missing.
"""

from __future__ import annotations

import asyncio
import logging
import time
import urllib.parse
from contextlib import suppress
from typing import Dict, Optional

log = logging.getLogger("light.browser")

try:
    from playwright.async_api import async_playwright
    BROWSER_AVAILABLE = True
except ImportError:
    async_playwright = None  # type: ignore
    BROWSER_AVAILABLE = False

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

CHALLENGE_TITLE = "Checking your browser..."
CHALLENGE_TIMEOUT_MS = 60_000
DOWNLOAD_TIMEOUT_MS = 45_000
BROWSER_OPERATION_TIMEOUT = 100.0
GOTO_TIMEOUT_MS = 30_000

_browser = None
_playwright = None
_browser_lock = asyncio.Lock()
_semaphore = asyncio.Semaphore(2)


async def init_browser() -> None:
    if not BROWSER_AVAILABLE:
        return
    async with _browser_lock:
        global _browser, _playwright
        if _browser is None or not _browser.is_connected():
            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(headless=True)
            log.info("Headless browser launched")


async def close_browser() -> None:
    if not BROWSER_AVAILABLE:
        return
    async with _browser_lock:
        global _browser, _playwright
        if _browser is not None:
            with suppress(Exception):
                await _browser.close()
            _browser = None
        if _playwright is not None:
            with suppress(Exception):
                await _playwright.stop()
            _playwright = None
        log.info("Headless browser shut down")


async def _wait_challenge_cleared(page) -> None:
    deadline = time.monotonic() + CHALLENGE_TIMEOUT_MS / 1000
    while time.monotonic() < deadline:
        try:
            title = await page.title()
            if title != CHALLENGE_TITLE:
                return
        except Exception:
            pass
        await asyncio.sleep(0.5)


async def _wait_for_download(page) -> Optional[object]:
    try:
        return await asyncio.wait_for(
            page.wait_for_event("download"), timeout=DOWNLOAD_TIMEOUT_MS / 1000
        )
    except Exception:
        return None


def _read_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


async def _download_one(url: str, cookies: Optional[Dict[str, str]]) -> Optional[bytes]:
    t0 = time.monotonic()
    try:
        async with asyncio.timeout(BROWSER_OPERATION_TIMEOUT):
            await init_browser()
            browser = _browser
            context = await browser.new_context(user_agent=USER_AGENT, accept_downloads=True)
            try:
                if cookies:
                    host = urllib.parse.urlparse(url).netloc.split(":")[0]
                    await context.add_cookies(
                        [
                            {"name": k, "value": v, "domain": host, "path": "/"}
                            for k, v in cookies.items()
                        ]
                    )
                page = await context.new_page()

                download_task = asyncio.create_task(_wait_for_download(page))
                await page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
                await _wait_challenge_cleared(page)

                download = await download_task
                if download is None:
                    log.debug("Browser: no download event for %s", url[:80])
                    return None

                path = await download.path()
                data = await asyncio.to_thread(_read_file, path)
                sniff = data[:512].strip().lower()
                if not data or sniff.startswith(b"<!doctype") or sniff.startswith(b"<html"):
                    return None
                log.info("Browser download: %s bytes in %.1fs", len(data), time.monotonic() - t0)
                return data
            finally:
                with suppress(Exception):
                    await context.close()
    except Exception as e:
        log.debug("Browser download failed for %s: %s", url[:80], e)
        return None


async def browser_download(
    url: str,
    cookies: Optional[Dict[str, str]] = None,
    file_token: Optional[str] = None,
) -> Optional[bytes]:
    """Download a file by rendering the page in a real browser.

    Tries the plain URL, then (when a token is known) the URL with the
    file_access_token query parameter.
    """
    if not BROWSER_AVAILABLE:
        return None
    candidates = [url]
    if file_token:
        sep = "&" if "?" in url else "?"
        candidates.append(f"{url}{sep}file_access_token={file_token}")
    for candidate in candidates:
        async with _semaphore:
            data = await _download_one(candidate, cookies)
        if data:
            return data
    return None
