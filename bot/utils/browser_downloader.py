from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp
from loguru import logger

from bot.utils.net import proxy_kwargs

try:
    from playwright.async_api import async_playwright
    BROWSER_AVAILABLE = True
except ImportError:
    BROWSER_AVAILABLE = False

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

CHALLENGE_TITLE = "Checking your browser..."
BROWSER_TIMEOUT = 30_000
POLL_INTERVAL = 500
DOWNLOAD_WAIT = 20_000


@dataclass
class DownloadResult:
    success: bool
    data: Optional[bytes] = None


_browser: Optional[any] = None
_playwright: Optional[any] = None
_browser_lock = asyncio.Lock()


async def init_browser() -> None:
    if not BROWSER_AVAILABLE:
        return
    async with _browser_lock:
        global _browser, _playwright
        if _browser is None:
            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(headless=True)
            logger.info("Persistent browser instance launched")


async def close_browser() -> None:
    async with _browser_lock:
        global _browser, _playwright
        if _browser:
            await _browser.close()
            _browser = None
        if _playwright:
            await _playwright.stop()
            _playwright = None
            logger.info("Persistent browser instance shut down")


async def get_browser():
    async with _browser_lock:
        global _browser, _playwright
        if _browser is None or not _browser.is_connected():
            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(headless=True)
            logger.info("Browser instance re-launched")
        return _browser


def _looks_like_html(data: bytes) -> bool:
    sniff = data[:512].strip().lower()
    return sniff.startswith(b"<!doctype") or sniff.startswith(b"<html") or sniff.startswith(b"<!")

async def _download_with_cookies(url: str, cookies: list[dict]) -> Optional[bytes]:
    cookie_dict = {c["name"]: c["value"] for c in cookies}
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    connector = aiohttp.TCPConnector(force_close=True)
    async with aiohttp.ClientSession(connector=connector, cookies=cookie_dict) as session:
        async with session.get(
            url, headers=headers, ssl=False, timeout=aiohttp.ClientTimeout(total=30), **proxy_kwargs(url)
        ) as resp:
            if resp.status != 200:
                return None
            content = await resp.read()
            if len(content) < 256:
                return None
            ct = resp.headers.get("Content-Type", "")
            if "text/html" in ct or "text/plain" in ct:
                return None
            if _looks_like_html(content):
                logger.warning(f"Downloaded content looks like HTML, rejecting: {url[:80]}")
                return None
            return content


async def _find_download_url(page) -> Optional[str]:
    return await page.evaluate("""
        () => {
            const sel = [
                'a[download]',
                'a.dl-button',
                'a.btn-download',
                'a[href*="/dl/"]',
                'a[href*="download"]',
                'a[href*="get"]',
            ];
            for (const s of sel) {
                const el = document.querySelector(s);
                if (el && el.href) return el.href;
            }
            for (const a of document.querySelectorAll('a')) {
                const t = (a.textContent || '').trim().toLowerCase();
                if (t === 'download' || t === 'get' || t === 'download book' || t === 'download file') {
                    if (a.href) return a.href;
                }
            }
            return null;
        }
    """) or None


async def browser_login(email: str, password: str, domains: list[str]) -> tuple[Optional[str], Optional[str]]:
    """Log in to Z-Library via Playwright browser to bypass Cloudflare.

    Returns (remix_userkey, remix_userid) on success, (None, None) on failure.
    """
    if not BROWSER_AVAILABLE:
        return None, None

    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )

    for domain in domains:
        domain = domain.rstrip("/")
        t0 = time.monotonic()
        try:
            async with asyncio.timeout(60):
                browser = await get_browser()
                context = await browser.new_context(user_agent=user_agent, locale="en-US")
                page = await context.new_page()
                try:
                    await page.goto(domain, wait_until="domcontentloaded", timeout=30000)

                    for _ in range(60000 // 500):
                        try:
                            title = await page.title()
                            if title != CHALLENGE_TITLE:
                                break
                        except Exception:
                            pass
                        await page.wait_for_timeout(500)

                    page_url = page.url
                    if "login" not in page_url.lower():
                        login_link = await page.query_selector('a[href*="login"]')
                        if login_link:
                            await login_link.click()
                            await page.wait_for_timeout(2000)

                    email_input = await page.query_selector('input[type="email"], input[name="email"], input[type="text"]')
                    if not email_input:
                        continue

                    await email_input.fill(email)
                    pass_input = await page.query_selector('input[type="password"]')
                    if pass_input:
                        await pass_input.fill(password)

                    submit = await page.query_selector('button[type="submit"], input[type="submit"]')
                    if submit:
                        await submit.click()
                    else:
                        await page.keyboard.press("Enter")

                    await page.wait_for_timeout(5000)

                    cookies = await context.cookies()
                    remix_userkey = None
                    remix_userid = None
                    for c in cookies:
                        if c["name"] == "remix_userkey":
                            remix_userkey = c["value"]
                        elif c["name"] == "remix_userid":
                            remix_userid = c["value"]

                    if remix_userkey and remix_userid:
                        elapsed = time.monotonic() - t0
                        logger.success(f"Browser login successful via {domain} in {elapsed:.1f}s")
                        return remix_userkey, remix_userid

                    elapsed = time.monotonic() - t0
                    logger.warning(f"Browser login: no remix cookies after {elapsed:.1f}s on {domain}")
                finally:
                    await context.close()
        except asyncio.TimeoutError:
            logger.warning(f"Browser login timed out on {domain}")
            continue
        except Exception as e:
            logger.warning(f"Browser login failed on {domain}: {e}")
            continue

    return None, None


async def try_direct_download(url: str) -> DownloadResult:
    t0 = time.monotonic()
    try:
        async with asyncio.timeout(10):
            connector = aiohttp.TCPConnector(ttl_dns_cache=300)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(
                    url,
                    headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
                    ssl=False,
                    timeout=aiohttp.ClientTimeout(total=10),
                    allow_redirects=True,
                    **proxy_kwargs(url),
                ) as resp:
                    status = resp.status
                    if status in (403, 429, 503):
                        logger.info(f"Direct download: HTTP {status} in {time.monotonic() - t0:.1f}s, falling back")
                        return DownloadResult(success=False)
                    if status != 200:
                        logger.info(f"Direct download: HTTP {status} in {time.monotonic() - t0:.1f}s, falling back")
                        return DownloadResult(success=False)
                    ct = resp.headers.get("Content-Type", "")
                    if "text/html" in ct or "application/json" in ct:
                        logger.info(f"Direct download: HTML/JSON Content-Type in {time.monotonic() - t0:.1f}s, falling back")
                        return DownloadResult(success=False)
                    data = await resp.read()
                    elapsed = time.monotonic() - t0
                    if len(data) < 1024:
                        logger.info(f"Direct download: only {len(data)} bytes in {elapsed:.1f}s, falling back")
                        return DownloadResult(success=False)
                    if _looks_like_html(data):
                        logger.info(f"Direct download: HTML body in {elapsed:.1f}s, falling back")
                        return DownloadResult(success=False)
                    sniff = data[:100].strip()
                    if sniff.startswith(b"{") or sniff.startswith(b"["):
                        logger.info(f"Direct download: JSON body in {elapsed:.1f}s, falling back")
                        return DownloadResult(success=False)
                    logger.info(f"Direct download: {len(data)} bytes in {elapsed:.1f}s")
                    return DownloadResult(success=True, data=data)
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - t0
        logger.info(f"Direct download timed out after {elapsed:.1f}s, falling back")
        return DownloadResult(success=False)
    except Exception as e:
        elapsed = time.monotonic() - t0
        logger.info(f"Direct download failed ({type(e).__name__}) in {elapsed:.1f}s, falling back")
        return DownloadResult(success=False)


async def try_browser_download(url: str, book_id: str = "", alt_url: Optional[str] = None, file_token: Optional[str] = None,
                               remix_cookies: Optional[dict[str, str]] = None) -> DownloadResult:
    if not BROWSER_AVAILABLE:
        return DownloadResult(success=False)
    t0 = time.monotonic()

    candidates = [url]
    # reader.z-lib.fm URLs are HTML reader pages, not download URLs — skip them
    if file_token:
        candidates.append(f"{url}?file_access_token={file_token}")

    for candidate_url in candidates:
        result = await _try_browser_one(candidate_url, book_id, remix_cookies=remix_cookies)
        if result.success:
            return result

    return DownloadResult(success=False)


async def _try_browser_one(url: str, book_id: str, remix_cookies: Optional[dict[str, str]] = None) -> DownloadResult:
    t0 = time.monotonic()
    try:
        async with asyncio.timeout(60):
            browser = await get_browser()
            context = await browser.new_context(user_agent=USER_AGENT, accept_downloads=True)
            if remix_cookies:
                for name, value in remix_cookies.items():
                    await context.add_cookies([{
                        "name": name,
                        "value": value,
                        "domain": "." + url.split("/")[2].split(":")[0],
                        "path": "/",
                    }])
            page = await context.new_page()
            try:
                download_event = asyncio.create_task(page.wait_for_event("download"))
                await page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)

                title = await page.title()
                if title == CHALLENGE_TITLE:
                    for _ in range(BROWSER_TIMEOUT // POLL_INTERVAL):
                        try:
                            title = await page.title()
                            if title != CHALLENGE_TITLE:
                                break
                        except Exception:
                            pass
                        await page.wait_for_timeout(POLL_INTERVAL)

                download = None
                try:
                    download = await asyncio.wait_for(download_event, timeout=DOWNLOAD_WAIT)
                except (asyncio.TimeoutError, Exception):
                    pass

                if download is not None:
                    path = await download.path()
                    with open(path, "rb") as f:
                        data = f.read()
                    elapsed = time.monotonic() - t0
                    logger.info(f"Browser download: {len(data)} bytes in {elapsed:.1f}s")
                    return DownloadResult(success=True, data=data)

                cookies = await context.cookies()
                has_cf = any(c["name"] == "cf_clearance" for c in cookies)

                if has_cf:
                    result = await _download_with_cookies(url, cookies)
                    if result is not None:
                        elapsed = time.monotonic() - t0
                        logger.info(f"Browser cookie-fallback: {len(result)} bytes in {elapsed:.1f}s")
                        return DownloadResult(success=True, data=result)

                dl_url = await _find_download_url(page)
                if dl_url:
                    download_event = asyncio.create_task(page.wait_for_event("download"))
                    try:
                        await page.goto(dl_url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
                    except Exception:
                        pass
                    try:
                        download = await asyncio.wait_for(download_event, timeout=DOWNLOAD_WAIT)
                    except (asyncio.TimeoutError, Exception):
                        pass
                    if download is not None:
                        path = await download.path()
                        with open(path, "rb") as f:
                            data = f.read()
                        elapsed = time.monotonic() - t0
                        logger.info(f"Browser download (found link): {len(data)} bytes in {elapsed:.1f}s")
                        return DownloadResult(success=True, data=data)

                    if has_cf:
                        result = await _download_with_cookies(dl_url, cookies)
                        if result is not None:
                            elapsed = time.monotonic() - t0
                            logger.info(f"Browser cookie-fallback (found link): {len(result)} bytes in {elapsed:.1f}s")
                            return DownloadResult(success=True, data=result)

                elapsed = time.monotonic() - t0
                logger.info(f"Browser download: all methods failed after {elapsed:.1f}s")
                return DownloadResult(success=False)
            finally:
                await context.close()
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - t0
        logger.warning(f"Browser download timed out after {elapsed:.1f}s for book {book_id}")
        return DownloadResult(success=False)
    except Exception as e:
        elapsed = time.monotonic() - t0
        logger.error(f"Browser download failed for {url[:80]}: {e} after {elapsed:.1f}s")
        return DownloadResult(success=False)
