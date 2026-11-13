"""Lightweight multi-source book search + download (aiohttp + stdlib only).

This replaces the heavy stack from the original bot:
  httpx/tenacity/beautifulsoup4/lxml  ->  aiohttp + re / html.unescape
  Redis cache                          ->  light.cache.TTLCache
  Playwright browser downloads         ->  direct HTTP only (no Cloudflare bypass)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from html import unescape
from typing import Any, Dict, List, Optional, Set, Tuple

import aiohttp
from aiohttp import CookieJar

try:
    from light.cache import TTLCache
except ImportError:  # running directly: python light/bot.py
    from cache import TTLCache  # type: ignore

try:
    from light.i18n import language_matches
except ImportError:  # running directly: python light/bot.py
    from i18n import language_matches  # type: ignore

try:
    from light.browser import BROWSER_AVAILABLE, browser_download
except ImportError:  # running directly: python light/bot.py
    try:
        from browser import BROWSER_AVAILABLE, browser_download  # type: ignore
    except ImportError:
        BROWSER_AVAILABLE = False  # type: ignore
        browser_download = None  # type: ignore

log = logging.getLogger("light.sources")


# --------------------------------------------------------------------------
# Book model
# --------------------------------------------------------------------------

@dataclass
class Book:
    id: str = ""
    title: str = "Unknown"
    author: Optional[str] = None
    description: Optional[str] = None
    publisher: Optional[str] = None
    publication_year: Optional[int] = None
    isbn: Optional[str] = None
    file_size: Optional[int] = None
    cover_url: Optional[str] = None
    download_url: Optional[str] = None
    download_urls: List[str] = field(default_factory=list)
    file_token: Optional[str] = None
    extension: Optional[str] = None
    pages: Optional[int] = None
    language: Optional[str] = None
    source: Optional[str] = None
    formats: Set[str] = field(default_factory=set)
    sources: Set[str] = field(default_factory=set)
    alternates: List["Book"] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    edition: Optional[str] = None
    downloads: Optional[int] = None


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

CLOUDFLARE_BLOCKED_HOSTS = frozenset({
    "z-lib.fm", "zlibrary-asia.se", "zlibrary-europe.se",
    "zlibrary-north-america.se", "zlibrary-south-america.se",
    "zlibrary-oceania.se", "zlibrary-africa.se", "zlibrary-antarctica.se",
    "z-library.sk", "reader.z-lib.fm", "cdn.reader.gd",
    "singlelogin.re", "singlelogin.site",
})

MAGIC_BYTES = {
    "epub": b"PK",
    "pdf": b"%PDF",
    "mobi": b"BOOKMOBI",
    "azw3": b"BOOKMOBI",
    "djvu": b"AT&T",
    "fb2": b"<?xml",
}


def _is_cloudflare_protected(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    return any(host == b or host.endswith("." + b) for b in CLOUDFLARE_BLOCKED_HOSTS)


def _is_cloudflare_body(body: bytes) -> bool:
    decoded = body[:500].decode("utf-8", errors="replace").lower()
    return any(
        s in decoded
        for s in ("checking your browser", "cf-browser-verification", "just a moment", "cloudflare")
    )


def _normalize_url(raw_url: Optional[str]) -> Optional[str]:
    if not raw_url:
        return None
    url = raw_url.strip()
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        return None
    if not url.startswith(("http://", "https://")):
        return None
    return url


def _is_real_file(data: bytes, fmt: str) -> bool:
    magic = MAGIC_BYTES.get(fmt.lower())
    if magic is None:
        return True
    if fmt.lower() in ("mobi", "azw3"):
        return b"BOOKMOBI" in data[:256]
    return len(data) >= len(magic) and data[: len(magic)] == magic


def _parse_file_size(size_str: Optional[str]) -> Optional[int]:
    if not size_str:
        return None
    size_str = size_str.strip().upper()
    try:
        match = re.match(r"([\d.]+)\s*(B|KB|MB|GB|TB)", size_str)
        if match:
            multipliers = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
            return int(float(match.group(1)) * multipliers[match.group(2)])
        return int(float(size_str))
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


class APIRateLimiter:
    """Simple sliding-window rate limiter."""

    def __init__(self, max_calls: int, window: int) -> None:
        self.max_calls = max_calls
        self.window = window
        self.calls: List[float] = []

    async def acquire(self) -> None:
        now = time.monotonic()
        cutoff = now - self.window
        self.calls = [t for t in self.calls if t > cutoff]
        if len(self.calls) >= self.max_calls:
            sleep_time = self.calls[0] + self.window - now
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
                self.calls = [t for t in self.calls if t > time.monotonic() - self.window]
        self.calls.append(time.monotonic())


# --------------------------------------------------------------------------
# Z-Library
# --------------------------------------------------------------------------

# Known Z-Library (SingleLogin) mirrors. Tried in order when the primary
# mirror is down or rate-limited (HTTP 503 / 429).
ZL_MIRRORS: List[str] = [
    "https://z-library.sk",
    "https://1lib.fr",
    "https://singlelogin.re",
    "https://singlelogin.site",
    "https://zlibrary-asia.se",
    "https://z-lib.io",
    "https://z-lib.gs",
]

class ZLibrary:
    def __init__(
        self,
        base_url: str,
        email: str = "",
        password: str = "",
        remix_userkey: str = "",
        remix_userid: str = "",
        max_file_size: int = 52_428_800,
        api_rate_limit: int = 30,
        api_rate_window: int = 60,
        mirrors: Optional[List[str]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        candidates = [self.base_url] + [m.strip().rstrip("/") for m in (mirrors or ZL_MIRRORS) if m and m.strip()]
        self.mirrors = list(dict.fromkeys(candidates))
        self.email = email
        self.password = password
        self._remix_userkey = remix_userkey or ""
        self._remix_userid = remix_userid or ""
        self.max_file_size = max_file_size
        self.session: Optional[aiohttp.ClientSession] = None
        self._cache = TTLCache(default_ttl=300, max_entries=2000)
        self._limiter = APIRateLimiter(max_calls=api_rate_limit, window=api_rate_window)
        self._search_endpoint = "/eccbc87e4b5ce2fe28308fd9f2a7baf3-1"

    # -- lifecycle ---------------------------------------------------------

    async def initialize(self) -> None:
        if self.session and not self.session.closed:
            return
        timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)
        self.session = aiohttp.ClientSession(
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "LightLibraryBot/1.0 (Telegram)",
            },
            timeout=timeout,
            connector=aiohttp.TCPConnector(limit=20, ttl_dns_cache=300),
        )
        if not (self._remix_userkey and self._remix_userid):
            await self._login()

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    def _cookies(self) -> Optional[Dict[str, str]]:
        if self._remix_userkey and self._remix_userid:
            return {"remix_userkey": self._remix_userkey, "remix_userid": self._remix_userid}
        return None

    async def _login(self) -> None:
        if not self.email or not self.password:
            log.warning("Z-Library credentials not set - searching without auth")
            return
        for domain in self.mirrors:
            rpc_url = domain.rstrip("/") + "/rpc.php"
            try:
                async with aiohttp.ClientSession(
                    headers={"User-Agent": "LightLibraryBot/1.0"},
                    cookie_jar=CookieJar(unsafe=True),
                ) as temp:
                    async with temp.post(
                        rpc_url,
                        data={
                            "isModal": "True",
                            "email": self.email,
                            "password": self.password,
                            "site_mode": "books",
                            "action": "login",
                            "isSingleLogin": "1",
                            "redirectUrl": "",
                            "gg_json_mode": "1",
                        },
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        if resp.status != 200:
                            continue
                        data = json.loads(await resp.text())
                        login_data = data.get("response", data)
                        if login_data.get("validationError"):
                            continue
                        for cookie in temp.cookie_jar:
                            if cookie.key == "remix_userkey":
                                self._remix_userkey = cookie.value
                            elif cookie.key == "remix_userid":
                                self._remix_userid = cookie.value
                        if self._remix_userkey and self._remix_userid:
                            log.info("Z-Library authenticated via %s", domain)
                            return
            except Exception as e:
                log.debug("Login on %s failed: %s", domain, e)
        log.warning("Z-Library login failed - proceeding without auth")

    # -- search ------------------------------------------------------------

    async def search(
        self,
        query: str,
        field: str = "title",
        page: int = 1,
        per_page: int = 10,
        language: Optional[str] = None,
    ) -> Tuple[List[Book], int]:
        if not self.session:
            await self.initialize()
        q = query.strip()
        cache_key = f"zl:{q}:{field}:{page}:{per_page}:{language or 'any'}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        cookies = self._cookies()
        for domain in self.mirrors:
            try:
                books, total = await self._try_domain(domain, q, page, per_page, field, cookies, language)
            except Exception as e:
                log.warning("ZL mirror %s failed: %s", domain, e)
                continue
            if books:
                self._cache.set(cache_key, (books, total))
                if domain != self.base_url:
                    log.info("Z-Library mirror rotated %s -> %s", self.base_url, domain)
                    self.base_url = domain
                return books, total
        return [], 0

    async def _try_domain(self, domain, query, page, per_page, field, cookies, language=None) -> Tuple[List[Book], int]:
        strategies = [
            ("GET /search", lambda: self._try_get_search(domain, query, page, per_page, field, cookies, language)),
            ("EAPI form", lambda: self._try_eapi_form(domain, query, page, per_page, cookies, language)),
            ("hash endpoint", lambda: self._try_hash_endpoint(domain, query, page, per_page, language)),
        ]
        for name, make_coro in strategies:
            try:
                books, total = await make_coro()
                if books:
                    return books, total
            except Exception as e:
                log.warning("ZL %s failed on %s: %s", name, domain, e)
        return [], 0

    async def _try_get_search(self, base_url, query, page, per_page, field, cookies, language=None) -> Tuple[List[Book], int]:
        await self._limiter.acquire()
        params: Dict[str, Any] = {"q": query, "page": str(page), "limit": str(per_page)}
        if field == "author":
            params["q"] = f"author:{query}"
        elif field == "isbn":
            params["q"] = f"isbn:{query}"
        if language:
            params["languages[]"] = language
        async with self.session.get(f"{base_url}/search", params=params, cookies=cookies) as resp:
            if resp.status == 429:
                retry_after = int(resp.headers.get("Retry-After", "5"))
                await asyncio.sleep(retry_after)
            resp.raise_for_status()
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            return self._parse_search_response(await resp.json(), base_url)

    async def _try_eapi_form(self, base_url, query, page, per_page, cookies, language=None) -> Tuple[List[Book], int]:
        await self._limiter.acquire()
        payload = {"message": query, "page": str(page), "limit": str(per_page)}
        if language:
            payload["languages[]"] = language
        async with self.session.post(
            f"{base_url}/eapi/book/search",
            data=payload,
            cookies=cookies,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            return self._parse_search_response(await resp.json(), base_url)

    async def _try_hash_endpoint(self, base_url, query, page, per_page, language=None) -> Tuple[List[Book], int]:
        await self._limiter.acquire()
        payload = {"query": query, "page": str(page), "limit": str(per_page)}
        if language:
            payload["languages[]"] = language
        async with self.session.post(
            f"{base_url}{self._search_endpoint}",
            json=payload,
            cookies=self._cookies(),
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            return self._parse_search_response(await resp.json(), base_url)

    def _parse_search_response(self, data: Any, base_url: str) -> Tuple[List[Book], int]:
        if data is None:
            return [], 0
        books_data = data.get("books") or data.get("results") or data.get("data") or []
        books = [self._parse_book(b, base_url) for b in books_data]
        books = [b for b in books if b.title and b.title != "Unknown"]
        total = data.get("total")
        if total is None:
            total = data.get("count")
        if total is None:
            total = (data.get("pagination") or {}).get("total_items")
        if total is None:
            total = data.get("exactBooksCount")
        if total is None:
            total = len(books)
        return books, total or 0

    def _parse_book(self, data: Dict, base_url: str = "") -> Book:
        base_url = base_url or self.base_url
        zlib_id = data.get("id")
        download_url = data.get("download_url") or ""
        dl = data.get("dl") or ""
        if not download_url and dl:
            download_url = f"{base_url}{dl}" if str(dl).startswith("/") else str(dl)
        if download_url:
            u = download_url.strip()
            if u.startswith("//"):
                download_url = "https:" + u
            elif u.startswith("/"):
                download_url = f"{base_url}{u}"
            elif not u.startswith(("http://", "https://")):
                download_url = None
        read_online_url = data.get("readOnlineUrl") or data.get("read_online_url")
        file_token = None
        if read_online_url:
            m = re.search(r"file_access_token=([^&]+)", read_online_url)
            if m:
                file_token = m.group(1)
        return Book(
            id=str(zlib_id) if zlib_id else str(data.get("book_id", "")),
            title=data.get("title", "Unknown"),
            author=data.get("author"),
            description=data.get("description"),
            publisher=data.get("publisher"),
            publication_year=data.get("year") or data.get("publication_year"),
            isbn=data.get("isbn"),
            file_size=data.get("filesize") or data.get("file_size"),
            cover_url=data.get("cover") or data.get("cover_url"),
            download_url=download_url,
            file_token=file_token,
            extension=data.get("extension") or "",
            pages=data.get("pages"),
            language=data.get("language"),
            source="Z-Library",
            categories=[str(c) for c in (data.get("categories") or []) if c],
            edition=data.get("edition") or data.get("series"),
            downloads=data.get("downloads") or data.get("downloads_count") or data.get("download_count"),
        )

    # -- browse / discovery -------------------------------------------------

    def _maybe_rotate(self, domain: str) -> None:
        if domain != self.base_url:
            log.info("Z-Library mirror rotated %s -> %s", self.base_url, domain)
            self.base_url = domain

    async def popular(self, limit: int = 10) -> List[Book]:
        """Trending / most-popular books with mirror + endpoint fallbacks."""
        if not self.session:
            await self.initialize()
        cache_key = f"zl:popular:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        for domain in self.mirrors:
            for path in ("/eapi/book/most-popular", "/books/popular", "/trending"):
                try:
                    await self._limiter.acquire()
                    async with self.session.get(
                        f"{domain}{path}",
                        params={"limit": str(limit)},
                        cookies=self._cookies(),
                    ) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()
                        books_data = data.get("books") or data.get("results") or []
                        books = [self._parse_book(b, domain) for b in books_data]
                        books = [b for b in books if b.title and b.title != "Unknown"][:limit]
                        if books:
                            self._cache.set(cache_key, books, ttl=300)
                            self._maybe_rotate(domain)
                            return books
                except Exception as e:
                    log.debug("popular %s%s failed: %s", domain, path, e)
        return []

    # -- download ----------------------------------------------------------

    async def download(self, url: str, fmt: str = "epub", file_token: Optional[str] = None) -> Optional[bytes]:
        clean = _normalize_url(url)
        if not clean:
            log.warning("Invalid download URL: %r", url)
            return None
        cookies = self._cookies()
        result = await self._download_with_retry(clean, cookies, fmt)
        if result:
            return result
        if file_token:
            result = await self._download_with_retry(f"{clean}?file_access_token={file_token}", cookies, fmt)
            if result:
                return result
        if BROWSER_AVAILABLE and browser_download is not None:
            log.info("HTTP download blocked, falling back to browser: %s", clean[:80])
            try:
                data = await browser_download(clean, cookies=cookies, file_token=file_token)
                if data and len(data) > 256 and _is_real_file(data, fmt):
                    return data
            except Exception as e:
                log.warning("Browser download failed for %s: %s", clean[:80], e)
        return None

    async def _download_with_retry(self, url: str, cookies, fmt: str) -> Optional[bytes]:
        current_url = url
        for _ in range(10):
            try:
                async with self.session.get(
                    current_url,
                    cookies=cookies,
                    headers={"Accept": "*/*"},
                    timeout=aiohttp.ClientTimeout(total=120, sock_read=60),
                    allow_redirects=False,
                ) as resp:
                    if resp.status in (301, 302, 303, 307, 308):
                        location = resp.headers.get("Location")
                        if not location:
                            return None
                        current_url = urllib.parse.urljoin(current_url, location.strip())
                        continue
                    if resp.status != 200:
                        return None
                    if resp.content_length and resp.content_length > self.max_file_size:
                        log.warning("File too large: %s bytes", resp.content_length)
                        return None
                    if "text/html" in resp.headers.get("Content-Type", ""):
                        return None
                    chunk = await resp.content.read(200)
                    decoded = chunk.decode("utf-8", errors="replace").lower()
                    if not chunk or _is_cloudflare_body(chunk) or "<html" in decoded or decoded.startswith("{"):
                        return None
                    data = chunk + await resp.content.read()
                    if not data or not _is_real_file(data, fmt):
                        return None
                    return data
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                log.debug("Download attempt failed for %s: %s", current_url[:80], e)
                return None
        return None


# --------------------------------------------------------------------------
# Anna's Archive
# --------------------------------------------------------------------------

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


class AnnasArchive:
    def __init__(self, base_url: str, secret_key: str = "", timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.secret_key = secret_key
        self.timeout = timeout
        self.session: Optional[aiohttp.ClientSession] = None
        self._cache = TTLCache(default_ttl=3600, max_entries=2000)
        self._last_request = 0.0
        self._ua_index = 0
        self._auth_cookies: Dict[str, str] = {}

    # -- lifecycle ---------------------------------------------------------

    async def initialize(self) -> None:
        if self.session and not self.session.closed:
            return
        self.session = aiohttp.ClientSession(
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
            timeout=aiohttp.ClientTimeout(total=self.timeout, connect=15, sock_read=30),
        )
        await self._ensure_auth()

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    def _rotate_ua(self) -> str:
        ua = USER_AGENTS[self._ua_index % len(USER_AGENTS)]
        self._ua_index += 1
        return ua

    async def _rate_limit(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request
        if elapsed < 1.5:
            await asyncio.sleep(1.5 - elapsed)
        self._last_request = time.monotonic()

    async def _ensure_auth(self) -> None:
        if not self.secret_key or self._auth_cookies:
            return
        try:
            await self._rate_limit()
            async with self.session.post(
                f"{self.base_url}/account/",
                data={"secret": self.secret_key},
                headers={"User-Agent": self._rotate_ua()},
            ) as resp:
                if resp.status == 200:
                    for cookie in self.session.cookie_jar:
                        self._auth_cookies[cookie.name] = cookie.value
                    if self._auth_cookies:
                        log.info("Anna's Archive authenticated via secret key")
        except Exception as e:
            log.debug("AA auth failed: %s", e)

    async def _get_json(self, url: str, params: Optional[Dict] = None) -> Optional[Any]:
        await self._rate_limit()
        async with self.session.get(
            url,
            params=params,
            headers={"User-Agent": self._rotate_ua(), "Accept": "application/json"},
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.json()

    # -- search ------------------------------------------------------------

    async def search(self, query: str, limit: int = 10) -> List[Book]:
        if not self.session:
            await self.initialize()
        cache_key = f"aa:search:{query}:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        results: List[Book] = []
        api_data = await self._api_search(query, limit)
        if api_data:
            results = [b for b in (self._parse_api_result(i) for i in api_data) if b is not None]
        if not results:
            results = await self._scrape_search(query)

        self._cache.set(cache_key, results)
        return results

    async def _api_search(self, query: str, limit: int) -> Optional[List[dict]]:
        params: Dict[str, Any] = {"q": query, "limit": limit, "format": "json"}
        if self.secret_key:
            params["secret"] = self.secret_key
        try:
            data = await self._get_json(f"{self.base_url}/api/search", params)
            if data:
                results = data.get("results", data.get("data", []))
                if results:
                    return results
        except Exception as e:
            log.debug("AA API search failed: %s", e)
        return None

    def _parse_api_result(self, item: dict) -> Optional[Book]:
        try:
            md5 = item.get("md5", item.get("id", ""))
            if not md5:
                return None
            size_str = item.get("filesize", item.get("file_size"))
            urls = item.get("download_urls") or []
            return Book(
                id=md5,
                title=item.get("title", "Unknown"),
                author=item.get("author", item.get("creator")),
                extension=(item.get("extension", item.get("format", "")) or "").lower().lstrip("."),
                file_size=_parse_file_size(size_str) if size_str else None,
                language=item.get("language"),
                publisher=item.get("publisher"),
                publication_year=_safe_int(item.get("year")),
                isbn=item.get("isbn"),
                description=item.get("description"),
                pages=_safe_int(item.get("pages")),
                cover_url=item.get("cover_url", item.get("cover")),
                download_url=urls[0] if urls else None,
                download_urls=urls,
                source="Anna's Archive",
            )
        except Exception:
            return None

    async def _scrape_search(self, query: str) -> List[Book]:
        url = f"{self.base_url}/search?q={urllib.parse.quote(query)}"
        results: List[Book] = []
        try:
            await self._rate_limit()
            async with self.session.get(url, headers={"User-Agent": self._rotate_ua()}) as resp:
                if resp.status != 200:
                    return results
                html = await resp.text()
        except Exception as e:
            log.debug("AA scrape search failed: %s", e)
            return results

        seen: Set[str] = set()
        # Each result is a row that starts with the same flex wrapper.
        for row in re.split(r'<div class="flex\s+pt-3\s+pb-3\s+border-b[^"]*"[^>]*>', html)[1:]:
            m = re.search(r'href="/md5/([a-f0-9]{32})"', row)
            if not m:
                continue
            md5 = m.group(1)
            if md5 in seen:
                continue
            seen.add(md5)
            book = _parse_search_row(row, md5)
            if book is not None:
                results.append(book)
        return results

    # -- details -----------------------------------------------------------

    async def get_book_details(self, book_id: str) -> Optional[Book]:
        cache_key = f"aa:detail:{book_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        book: Optional[Book] = None
        if re.match(r"^[a-f0-9]{32}$", book_id):
            api_data = await self._api_book(book_id)
            if api_data:
                book = self._parse_api_detail(api_data)
        if book is None:
            book = await self._scrape_detail(book_id)

        if book is not None:
            self._cache.set(cache_key, book)
        return book

    async def _api_book(self, md5: str) -> Optional[dict]:
        params: Dict[str, Any] = {}
        if self.secret_key:
            params["secret"] = self.secret_key
        try:
            return await self._get_json(f"{self.base_url}/api/book/{md5}", params)
        except Exception:
            return None

    def _parse_api_detail(self, data: dict) -> Optional[Book]:
        try:
            md5 = data.get("md5", "")
            urls = data.get("download_urls") or []
            size_str = data.get("filesize", data.get("file_size"))
            return Book(
                id=md5,
                title=data.get("title", "Unknown"),
                author=data.get("author", data.get("creator")),
                extension=(data.get("extension", data.get("format", "")) or "").lower().lstrip("."),
                file_size=_parse_file_size(size_str) if size_str else None,
                language=data.get("language"),
                publisher=data.get("publisher"),
                publication_year=_safe_int(data.get("year")),
                isbn=data.get("isbn"),
                description=data.get("description"),
                pages=_safe_int(data.get("pages")),
                cover_url=data.get("cover_url", data.get("cover")),
                download_url=urls[0] if urls else None,
                download_urls=urls,
                source="Anna's Archive",
            )
        except Exception:
            return None

    async def _scrape_detail(self, book_id: str) -> Optional[Book]:
        url = f"{self.base_url}/md5/{book_id}"
        try:
            await self._rate_limit()
            async with self.session.get(url, headers={"User-Agent": self._rotate_ua()}) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
        except Exception as e:
            log.debug("AA scrape detail failed: %s", e)
            return None
        return _parse_detail_html(html, url, self.base_url)

    async def get_download_links(self, book_id: str) -> List[str]:
        if self.secret_key and re.match(r"^[a-f0-9]{32}$", book_id):
            api_data = await self._api_book(book_id)
            if api_data and api_data.get("download_urls"):
                return api_data["download_urls"]
        book = await self.get_book_details(book_id)
        if book and book.download_urls:
            return book.download_urls
        return []

    async def download(self, url: str, expected_format: str = "epub") -> Optional[bytes]:
        for attempt in range(3):
            try:
                await self._rate_limit()
                async with self.session.get(
                    url,
                    headers={"User-Agent": self._rotate_ua(), "Accept": "*/*"},
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=120, connect=15, sock_read=90),
                ) as resp:
                    if resp.status != 200:
                        return None
                    if "text/html" in resp.headers.get("Content-Type", ""):
                        return None
                    data = await resp.read()
                    if len(data) < 256 or not _is_real_file(data, expected_format):
                        return None
                    return data
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                log.debug("AA download attempt %d failed: %s", attempt + 1, e)
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
        return None


def _parse_search_row(row: str, md5: str) -> Optional[Book]:
    """Parse one Anna's Archive search-result row.

    A row looks like (classes shortened):
      <div class="flex pt-3 pb-3 border-b ...">
        <a href="/md5/<md5>" ...> cover img + fallback (data-content title/author) </a>
        <div>
          <div class="...font-mono">filepath (contains "(2018, ...)")</div>
          <a href="/md5/<md5>" class="...js-vim-focus...">Title</a>
          <a href="/search?q=Author" class="...line-clamp-[2]..."><span ...></span> Author</a>
          <div class="text-gray-800 ... font-semibold ... mt-2">
             English [en] &middot; PDF &middot; 26.0MB &middot; Book (non-fiction) &middot; /lgli/zlib ...
          </div>
        </div>
      </div>
    """
    title = None
    tm = re.search(r'href="/md5/[a-f0-9]{32}"[^>]*class="[^"]*js-vim-focus[^"]*"[^>]*>([^<]+)</a>', row)
    if tm:
        title = unescape(tm.group(1)).strip()
    if not title or len(title) < 3:
        dm = re.findall(r'data-content="([^"]*)"', row)
        if dm:
            title = unescape(dm[0]).strip()
    if not title or len(title) < 3:
        return None

    author = None
    am = re.search(r'href="/search\?q=[^"]+"[^>]*>.*?</span>\s*([^<]+?)\s*</a>', row, re.DOTALL)
    if am:
        author = unescape(am.group(1)).strip()
    if not author:
        dm = re.findall(r'data-content="([^"]*)"', row)
        if len(dm) >= 2:
            author = unescape(dm[1]).strip()

    cover = None
    cm = re.search(r'<img[^>]+src="(https://[^"]+)"', row)
    if cm:
        cover = cm.group(1)

    publication_year = None
    ym = re.search(r"\((\d{4})[,)]", row)
    if ym:
        publication_year = _safe_int(ym.group(1))

    description = None
    dm2 = re.search(
        r'class="[^"]*line-clamp-\[2\][^"]*text-gray-600[^"]*"[^>]*>([^<]+)</div>', row
    )
    if dm2:
        description = unescape(dm2.group(1)).strip()

    language, extension, file_size = _parse_aa_meta_line(row)

    return Book(
        id=md5,
        title=title,
        author=author or None,
        description=description,
        publication_year=publication_year,
        file_size=file_size,
        cover_url=cover,
        extension=extension,
        language=language,
        source="Anna's Archive",
    )


KNOWN_AA_FORMATS = frozenset({
    "pdf", "epub", "mobi", "azw3", "fb2", "djvu", "txt", "cbz", "cbr",
    "doc", "docx", "rtf", "zip", "rar", "mp3", "m4b", "djvu", "chm",
})


def _parse_aa_meta_line(row: str) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """Extract language / format / size from a search-row meta line.

    Expected line: ``English [en] &middot; PDF &middot; 26.0MB &middot; ...``
    Returns (language, extension, file_size_bytes).
    """
    language = extension = None
    file_size = None
    mm = re.search(r'class="[^"]*text-gray-800[^"]*font-semibold[^"]*"[^>]*>(.*?)</div>', row, re.DOTALL)
    if not mm:
        return None, None, None
    meta = unescape(re.sub(r"<[^>]+>", "", mm.group(1)))
    for part in re.split(r"\s*[·•]\s*|\s{2,}", meta):
        part = part.strip()
        if not part:
            continue
        lm = re.match(r"^([A-Za-z ]+?)\s*\[([a-z]{2})\]$", part)
        if lm and language is None:
            language = lm.group(2)
            continue
        sm = re.match(r"^([\d.]+)\s*(B|KB|MB|GB|TB)$", part, re.IGNORECASE)
        if sm and file_size is None:
            file_size = _parse_file_size(part)
            continue
        if extension is None and part.lower() in KNOWN_AA_FORMATS:
            extension = part.lower()
    if extension is None:
        em = re.search(r"\.(pdf|epub|mobi|azw3|fb2|djvu|txt|cbz|cbr)(?:\.|$)", row[:3000], re.IGNORECASE)
        if em:
            extension = em.group(1).lower()
    return language, extension, file_size


def _parse_detail_html(html: str, url: str, base_url: str) -> Optional[Book]:
    md5 = ""
    m = re.search(r"/md5/([a-f0-9]{32})", url)
    if m:
        md5 = m.group(1)

    title = "Unknown"
    ttm = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if ttm:
        title = re.sub(r"<[^>]+>", "", ttm.group(1)).strip()
        for suffix in ("- Anna's Archive", "- Anna’s Archive"):
            if title.endswith(suffix):
                title = title[: -len(suffix)].strip()
    if not title or title == "Unknown":
        tm = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
        if tm:
            title = re.sub(r"<[^>]+>", "", tm.group(1)).strip()

    author = None
    if " - " in title:
        head = title.split(" - ", 1)[0].strip()
        if " by " in head:
            _, _, author = head.rpartition(" by ")
            title = head[: -(len(author) + 4)].strip()
    title = title or "Unknown"

    language = None
    for lm in re.finditer(
        r'<span class="[^"]*bg-\[#aaa\][^"]*"[^>]*>(.*?)</span>\s*<span[^>]*>(.*?)</span>',
        html,
    ):
        label = re.sub(r"<[^>]+>", "", lm.group(1)).strip()
        value = re.sub(r"<[^>]+>", "", lm.group(2)).strip()
        if label.lower() == "language" and value:
            language = value
            break

    extension = None
    em = re.search(r"\.(epub|pdf|mobi|azw3|fb2|djvu|txt|cbz|cbr)\b", html[:2000], re.IGNORECASE)
    if em:
        extension = em.group(1).lower()

    file_size = None
    fm = re.search(r'filesize_bytes:(\d+)', html)
    if fm:
        file_size = _safe_int(fm.group(1))

    links: List[str] = []
    for lm in re.finditer(r'href="([^"]+)"', html, re.IGNORECASE):
        href = lm.group(1).strip()
        low = href.lower()
        if any(k in low for k in ("/dl/", "slow", "fast", "download", "cloudflare", "ipfs", "gateway")):
            full = href if href.startswith("http") else base_url + ("/" if not href.startswith("/") else "") + href
            if full not in links:
                links.append(full)

    description = None
    dm = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html, re.IGNORECASE)
    if dm:
        description = unescape(dm.group(1))

    return Book(
        id=md5,
        title=unescape(title),
        author=author,
        extension=extension,
        file_size=file_size,
        language=language,
        description=description,
        download_urls=links,
        download_url=links[0] if links else None,
        source="Anna's Archive",
    )


# --------------------------------------------------------------------------
# Dedup + relevance ranking (ported from bot/sources/dedup.py)
# --------------------------------------------------------------------------

FILE_EXT_PATTERN = re.compile(r"\.(pdf|epub|mobi|azw3|fb2|djvu|txt|cbz|cbr|doc|docx|rtf|zip|rar)$", re.IGNORECASE)

EDITION_PATTERNS = [
    re.compile(r"\(?\d{4}\)?"),
    re.compile(r"\b(?:revised|updated|expanded|anniversary|collectors?|special|limited|hardcover|paperback|audible|audio)\s+edition\b", re.IGNORECASE),
    re.compile(r"\b\d+(?:st|nd|rd|th)\s+edition\b", re.IGNORECASE),
    re.compile(r"\b(?:volume|vol)\s*\.?\s*\d+\b", re.IGNORECASE),
    re.compile(r"\b\d+th\s+printing\b", re.IGNORECASE),
    re.compile(r"\b\d+th\s+impression\b", re.IGNORECASE),
]

FORMAT_PRIORITY = {"pdf": 0, "epub": 1, "mobi": 2, "azw3": 3, "fb2": 4, "djvu": 5, "txt": 6, "cbz": 7, "cbr": 8}

STOP_WORDS: Set[str] = {
    "the", "of", "for", "a", "an", "to", "and", "in", "is", "it", "on", "at", "by", "with",
    "or", "be", "as", "from", "that", "this", "are", "was", "were", "been", "its", "not",
    "but", "what", "which", "who", "whom", "when", "where", "why", "how", "all", "each",
    "every", "some", "any", "no", "nor", "if", "so", "than", "too", "very", "just", "also",
    "about", "up", "out", "off", "over", "into", "through", "during", "before", "after",
    "above", "below", "between", "under", "again", "further", "then", "once", "here",
    "there", "both", "few", "more", "most", "other", "such", "own", "do", "does", "did",
    "has", "have", "had", "can", "will", "would", "could", "should", "may", "might",
    "shall", "need", "done", "being", "having", "get", "got", "make", "made", "take",
    "took", "come", "came", "see", "saw", "know", "new", "one", "two", "like", "well",
    "my", "your", "our", "their", "his", "her", "me", "him", "them", "us", "you",
    "these", "those",
}


def normalize_text(text: str) -> str:
    if not text:
        return ""
    s = text.lower().strip()
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", errors="ignore").decode("ascii")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_title(title: str) -> str:
    if not title:
        return ""
    s = title.lower().strip()
    s = FILE_EXT_PATTERN.sub("", s)
    for pat in EDITION_PATTERNS:
        s = pat.sub("", s)
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", errors="ignore").decode("ascii")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fuzzy_similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


_STEM_SUFFIXES = ("ing", "ed", "es", "s", "ly")


def _simple_stem(word: str) -> str:
    """Lightweight suffix-stripping stemmer used for keyword matching."""
    if not word:
        return word
    for suffix in _STEM_SUFFIXES:
        if len(word) - len(suffix) >= 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _longest_consecutive_run(positions: List[int]) -> int:
    """Longest run of keyword positions that are consecutive words in the title."""
    if not positions:
        return 0
    best = 1
    cur = 1
    for i in range(1, len(positions)):
        if positions[i] == positions[i - 1] + 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


# Match tiers between a title word and a query keyword, from strongest to weakest.
# 0 exact, 1 stemmed, 2 fuzzy, 3 substring, -1 no match.
_TIER_WEIGHTS: Tuple[float, ...] = (1.0, 0.9, 0.7, 0.5)


def _token_match_tier(word: str, token: str) -> int:
    if word == token:
        return 0
    if _simple_stem(word) == _simple_stem(token):
        return 1
    if len(word) >= 3 and len(token) >= 3 and fuzzy_similar(word, token) >= 0.7:
        return 2
    if len(word) >= 3 and len(token) >= 3 and (token in word or word in token):
        return 3
    return -1


def _select_best_from_group(group: List[Book]) -> Book:
    def score(r: Book) -> tuple:
        ext = (r.extension or "").lower().lstrip(".")
        fmt_priority = FORMAT_PRIORITY.get(ext, 99)
        src_priority = 0 if (r.source or "").lower() == "z-library" else 1
        size = r.file_size or 0
        meta = sum([
            1 if r.author else 0, 1 if r.description else 0,
            1 if r.publication_year else 0, 1 if r.isbn else 0,
            1 if r.publisher else 0, 1 if r.pages else 0, 1 if r.cover_url else 0,
        ])
        return (src_priority, fmt_priority, -size, -meta)

    return min(group, key=score)


def deduplicate_results(results: List[Book]) -> List[Book]:
    groups: List[Tuple[str, List[Book]]] = []
    for r in results:
        norm = normalize_title(r.title or "")
        if not norm:
            continue
        for i, (group_norm, group) in enumerate(groups):
            if norm == group_norm or fuzzy_similar(norm, group_norm) >= 0.9:
                group.append(r)
                break
        else:
            groups.append((norm, [r]))

    deduped: List[Book] = []
    for _, group in groups:
        best = _select_best_from_group(group)
        formats: Set[str] = set()
        sources: Set[str] = set()
        for r in group:
            if r.extension:
                formats.add(r.extension.lower().lstrip("."))
            if r.source:
                sources.add(r.source)
        best.formats = formats
        best.sources = sources
        best.alternates = [r for r in group if r is not best]
        deduped.append(best)
    return deduped


def _parse_query(query: str) -> Tuple[List[str], List[str], bool]:
    query = query.strip()
    if not query:
        return [], [], False
    phrases = re.findall(r'"([^"]+)"', query)
    has_phrases = bool(phrases)
    non_phrase = re.sub(r'"[^"]+"', "", query).strip()
    tokens = []
    for t in non_phrase.split():
        for subtoken in normalize_text(t).split():
            if subtoken and subtoken not in STOP_WORDS:
                tokens.append(subtoken)
    normalized_phrases = [normalize_text(p) for p in phrases if normalize_text(p)]
    return tokens, normalized_phrases, has_phrases


def compute_relevance_score(
    title: str,
    query: str,
    tokens: List[str],
    phrases: List[str],
    has_phrases: bool,
) -> float:
    title_norm = normalize_text(title or "")
    query_norm = normalize_text(query)
    if not title_norm:
        return 0.0

    if title_norm == query_norm:
        return 100_000.0

    score = 0.0

    # The full query appearing inside the title, or as its prefix, is a strong
    # signal that the result is (a version of) the requested book.
    if query_norm in title_norm:
        score += 30_000.0
    if title_norm.startswith(query_norm):
        score += 15_000.0

    # Quoted phrases must appear verbatim.
    if has_phrases and any(p in title_norm for p in phrases):
        score += 20_000.0

    title_words = title_norm.split()

    if not tokens:
        return score + fuzzy_similar(query_norm, title_norm) * 5_000.0

    # Position of each query keyword inside the title (best available tier:
    # exact, stemmed, fuzzy, then substring).
    matched: List[Tuple[int, int]] = []  # (position, tier)
    for t in tokens:
        best: Optional[Tuple[int, int]] = None
        for i, w in enumerate(title_words):
            tier = _token_match_tier(w, t)
            if tier >= 0 and (best is None or tier < best[1]):
                best = (i, tier)
        if best is not None:
            matched.append(best)

    n_found = len(matched)

    # How much of the query is covered, weighted by match quality.
    score += (sum(_TIER_WEIGHTS[tier] for _, tier in matched) / len(tokens)) * 25_000.0

    if n_found > 1:
        positions = [p for p, _ in matched]
        # Keywords in the same relative order as the query rank higher.
        preserved = sum(
            1 for a in range(n_found) for b in range(a + 1, n_found) if positions[a] < positions[b]
        )
        total_pairs = n_found * (n_found - 1) // 2
        score += (preserved / total_pairs) * 8_000.0

        # Adjacent keywords in the title outrank scattered ones.
        run = _longest_consecutive_run(positions)
        if run >= 2:
            score += run * 2_500.0

        # The closer the keywords cluster together, the better.
        span = positions[-1] - positions[0]
        score += max(0.0, 1.0 - span / max(1.0, len(title_words))) * 3_000.0

    # Fallback for results too dissimilar to score on keywords: fuzzy title match.
    if score < 5_000.0:
        sim = fuzzy_similar(query_norm, title_norm)
        if sim >= 0.5:
            score += sim * 5_000.0

    return score


def rank_results(results: List[Book], query: str) -> List[Book]:
    tokens, phrases, has_phrases = _parse_query(query)

    def key_fn(r: Book) -> tuple:
        s = compute_relevance_score(r.title, query, tokens, phrases, has_phrases)
        return (-s, (r.title or "").lower().strip())

    return sorted(results, key=key_fn)


# --------------------------------------------------------------------------
# Source router (search + download orchestration)
# --------------------------------------------------------------------------

class SourceRouter:
    def __init__(self, zlibrary: ZLibrary, annas: AnnasArchive, max_pages: int = 5) -> None:
        self.zl = zlibrary
        self.aa = annas
        self.max_pages = max_pages

    async def search(self, query: str, per_page: int = 100, field: str = "title", language: Optional[str] = None) -> Tuple[List[Book], int]:
        aa_task = self._aa_search(query)
        zl_task = self._zl_search_all(query, per_page, field, language)
        aa_results, zl_results = await asyncio.gather(aa_task, zl_task, return_exceptions=True)
        aa_results = [] if isinstance(aa_results, Exception) else aa_results
        zl_results = [] if isinstance(zl_results, Exception) else zl_results

        combined = list(zl_results) + list(aa_results)
        if not combined:
            return [], 0
        if language:
            filtered = [b for b in combined if language_matches(b.language, language)]
            if not filtered:
                return [], 0
            combined = filtered
        deduped = deduplicate_results(combined)
        ranked = rank_results(deduped, query)
        return ranked, len(ranked)

    async def _zl_search_all(self, query, per_page, field, language=None) -> List[Book]:
        try:
            first, total = await self.zl.search(query, field=field, page=1, per_page=per_page, language=language)
        except Exception as e:
            log.warning("ZL search failed for '%s': %s", query, e)
            return []
        if not first:
            return []
        all_results = list(first)
        total_pages = max(1, (int(total or 0) + per_page - 1) // per_page)
        pages = min(total_pages, self.max_pages)
        if pages <= 1:
            return all_results

        sem = asyncio.Semaphore(3)

        async def _fetch(p: int) -> List[Book]:
            async with sem:
                more, _ = await self.zl.search(query, field=field, page=p, per_page=per_page, language=language)
                return more or []

        tasks = [_fetch(p) for p in range(2, pages + 1)]
        for coro in asyncio.as_completed(tasks):
            try:
                all_results.extend(await coro)
            except Exception:
                pass
        return all_results

    async def _aa_search(self, query) -> List[Book]:
        try:
            return await self.aa.search(query, limit=50)
        except Exception as e:
            log.warning("AA search failed for '%s': %s", query, e)
            return []

    async def download(self, book: Book, fmt: str = "epub") -> Tuple[Optional[bytes], Optional[str]]:
        # Prefer Z-Library: it's the only source whose files can actually be
        # fetched from this host.  Anna's Archive downloads require a paid
        # membership (slow links are DDoS-guarded, fast links member-only).
        fmt = (fmt or "epub").lower().lstrip(".")
        zl_book = await self._zl_book_for_format(book, fmt)
        if zl_book is not None:
            data = await self._zl_download(zl_book, zl_book.extension or fmt)
            if data:
                return data, None
        if (
            book.source == "Anna's Archive"
            and (book.extension or "").lower().lstrip(".") == fmt
        ):
            data = await self._aa_download(book, fmt)
            if data:
                return data, None
        return None, None

    async def _zl_book_for_format(self, book: Book, fmt: str) -> Optional[Book]:
        """Return a download-ready Z-Library book of the requested format.

        Checks the book itself and its dedup group members first (no extra
        requests), then falls back to a Z-Library search by title.
        """
        candidates = [book]
        for alt in getattr(book, "alternates", []):
            if alt is not book:
                candidates.append(alt)
        for c in candidates:
            ext = (c.extension or "").lower().lstrip(".")
            if c.source == "Z-Library" and ext == fmt and c.download_url:
                return c
        try:
            results, _ = await self.zl.search(book.title, page=1, per_page=20)
        except Exception as e:
            log.warning("ZL format search failed for %s: %s", book.id, e)
            return None
        target = normalize_title(book.title or "")
        best: Optional[Book] = None
        best_sim = 0.0
        for r in results:
            if (r.extension or "").lower().lstrip(".") != fmt or not r.download_url:
                continue
            sim = fuzzy_similar(normalize_title(r.title or ""), target)
            if sim > best_sim:
                best_sim = sim
                best = r
        return best if best_sim >= 0.85 else None

    async def _zl_download(self, book: Book, fmt: str) -> Optional[bytes]:
        url = book.download_url
        if not url:
            url = await self._resolve_zl_url(book)
            if not url:
                return None
        try:
            return await self.zl.download(url, fmt=fmt, file_token=book.file_token)
        except Exception as e:
            log.warning("ZL download failed for %s: %s", book.id, e)
            return None

    async def _resolve_zl_url(self, book: Book) -> Optional[str]:
        try:
            results, _ = await self.zl.search(book.title, page=1, per_page=10)
        except Exception:
            return None
        for r in results:
            if r.download_url and str(r.id) == str(book.id):
                book.file_token = book.file_token or r.file_token
                return r.download_url
        for r in results:
            if r.download_url and (r.title or "").strip().lower() == (book.title or "").strip().lower():
                book.file_token = book.file_token or r.file_token
                return r.download_url
        return None

    async def _aa_download(self, book: Book, fmt: str) -> Optional[bytes]:
        try:
            links = await self.aa.get_download_links(book.id)
            for link in links:
                data = await self.aa.download(link, expected_format=fmt)
                if data:
                    return data
        except Exception as e:
            log.warning("AA download failed for %s: %s", book.id, e)
        return None
