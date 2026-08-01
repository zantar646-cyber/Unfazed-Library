from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import aiohttp
from aiohttp import CookieJar
from yarl import URL as YarlURL
from loguru import logger
from tenacity import (
    after_log,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from bot.config.settings import settings
from bot.services.cache import cache
from bot.services.mirror_manager import MirrorManager, NoHealthyMirrorError
from bot.utils.browser_downloader import BROWSER_AVAILABLE, browser_login


CLOUDFLARE_BLOCKED_HOSTS = frozenset({
    "z-lib.fm",
    "zlibrary-asia.se",
    "zlibrary-europe.se",
    "zlibrary-north-america.se",
    "zlibrary-south-america.se",
    "zlibrary-oceania.se",
    "zlibrary-africa.se",
    "zlibrary-antarctica.se",
    "z-library.sk",
    "reader.z-lib.fm",
    "cdn.reader.gd",
    "singlelogin.re",
    "singlelogin.site",
})


def _is_cloudflare_protected(url: str) -> bool:
    """Return True if *url*'s hostname is known to be behind Cloudflare.

    Matches exact hostnames and subdomains against *CLOUDFLARE_BLOCKED_HOSTS*.
    """
    host = urllib.parse.urlparse(url).hostname or ""
    return any(host == blocked or host.endswith("." + blocked) for blocked in CLOUDFLARE_BLOCKED_HOSTS)


class RateLimitExceeded(Exception):
    pass


class APIError(Exception):
    pass


class APIRateLimiter:
    def __init__(self, max_calls: int, window: int) -> None:
        self.max_calls = max_calls
        self.window = window
        self.calls: List[float] = []

    def _cleanup(self) -> None:
        now = time.monotonic()
        cutoff = now - self.window
        self.calls = [t for t in self.calls if t > cutoff]

    async def acquire(self) -> None:
        self._cleanup()
        if len(self.calls) >= self.max_calls:
            sleep_time = self.calls[0] + self.window - time.monotonic()
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
                self._cleanup()
        self.calls.append(time.monotonic())

    @property
    def remaining(self) -> int:
        self._cleanup()
        return max(0, self.max_calls - len(self.calls))


class APIResponse:
    def __init__(self, data: Any, cached: bool = False):
        self.data = data
        self.cached = cached


@dataclass
class BookResult:
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
    download_count: int = 0
    category: Optional[str] = None
    pages: Optional[int] = None
    language: Optional[str] = None
    rating: Optional[float] = None
    zlibrary_id: Optional[int] = None
    read_online_url: Optional[str] = None
    file_token: Optional[str] = None
    extension: Optional[str] = None
    _source: Optional[str] = None
    formats: Optional[Set[str]] = field(default=None, repr=False)
    sources: Optional[Set[str]] = field(default=None, repr=False)

    def fingerprint(self) -> str:
        return hashlib.md5(
            f"{self.id}:{self.title}".encode()
        ).hexdigest()


class APIService:
    def __init__(self) -> None:
        self.base_url = settings.api_base_url.rstrip("/")
        self.api_key = settings.api_key
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limiter = APIRateLimiter(
            max_calls=settings.api_rate_limit,
            window=settings.api_rate_window,
        )
        self._search_endpoint = "/eccbc87e4b5ce2fe28308fd9f2a7baf3-1"
        self._remix_userkey: Optional[str] = None
        self._remix_userid: Optional[str] = None
        self._last_search_fingerprints: List[str] = []
        self.mirror_manager: Optional[MirrorManager] = None

    async def _sync_base_url(self) -> str:
        if self.mirror_manager:
            try:
                self.base_url = await self.mirror_manager.get_active_base_url()
            except NoHealthyMirrorError:
                logger.error("No healthy mirrors, falling back to configured base_url")
        return self.base_url

    async def _login(self) -> None:
        if settings.zlibrary_remix_userkey and settings.zlibrary_remix_userid:
            self._remix_userkey = settings.zlibrary_remix_userkey
            self._remix_userid = settings.zlibrary_remix_userid
            logger.info("Z-Library authentication using remix tokens from env")
            return

        email = settings.zlibrary_email
        password = settings.zlibrary_password
        if not email or not password:
            logger.warning("Z-Library credentials not set, proceeding without auth")
            return

        singlelogin_domains = [
            settings.singlelogin_url,
            "https://z-library.sk",
            "https://singlelogin.re",
            "https://1lib.fr",
            "https://singlelogin.site",
            settings.api_base_url.rstrip("/"),
        ]

        for domain in singlelogin_domains:
            rpc_url = domain.rstrip("/") + "/rpc.php"
            try:
                async with aiohttp.ClientSession(
                    headers={"User-Agent": "DigitalLibraryBot/1.0"},
                    cookie_jar=CookieJar(unsafe=True),
                ) as temp_session:
                    async with temp_session.post(
                        rpc_url,
                        data={
                            "isModal": "True",
                            "email": email,
                            "password": password,
                            "site_mode": "books",
                            "action": "login",
                            "isSingleLogin": "1",
                            "redirectUrl": "",
                            "gg_json_mode": "1",
                        },
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            data = json.loads(text)
                            login_data = data.get("response", data)
                            if login_data.get("validationError"):
                                logger.warning(f"Login rejected by {domain}: {login_data['validationError']}")
                                continue
                            for cookie in temp_session.cookie_jar:
                                if cookie.key == "remix_userkey":
                                    self._remix_userkey = cookie.value
                                elif cookie.key == "remix_userid":
                                    self._remix_userid = cookie.value
                            if self._remix_userkey and self._remix_userid:
                                logger.info(f"Z-Library authenticated via {domain}")
                                return
            except Exception as e:
                logger.debug(f"Login attempt on {domain} failed: {e}")
                continue

        logger.warning("All HTTP Z-Library login attempts failed, trying browser login...")
        browser_domains = [
            settings.singlelogin_url,
            "https://z-library.sk",
            "https://singlelogin.re",
            "https://1lib.fr",
            "https://singlelogin.site",
        ]
        remix_key, remix_id = await browser_login(email, password, browser_domains)
        if remix_key and remix_id:
            self._remix_userkey = remix_key
            self._remix_userid = remix_id
            logger.success("Z-Library authenticated via browser login")
            return

        logger.warning("All Z-Library login attempts failed, proceeding without auth")

    async def initialize(self) -> None:
        timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "DigitalLibraryBot/1.0 (Telegram)",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self.session = aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
            connector=aiohttp.TCPConnector(limit=20, ttl_dns_cache=300),
        )
        logger.info(f"API service initialized (base: {self.base_url})")

        await self._login()

        self.mirror_manager = MirrorManager(
            primary_url=self.base_url,
            additional_urls=settings.mirrors if settings.mirrors else None,
            remix_userkey=self._remix_userkey or "",
            remix_userid=self._remix_userid or "",
        )
        await self.mirror_manager.initialize()
        await self._sync_base_url()

        if self._remix_userkey:
            logger.info(f"Z-Library authenticated as user {self._remix_userid}")

    async def close(self) -> None:
        if self.mirror_manager:
            await self.mirror_manager.close()
        if self.session:
            await self.session.close()
            logger.info("API session closed")

    def _build_cache_key(self, endpoint: str, params: Optional[Dict] = None) -> str:
        key = f"api:{endpoint}"
        if params:
            sorted_params = sorted(params.items())
            param_str = "&".join(f"{k}={v}" for k, v in sorted_params if v is not None)
            if param_str:
                key += f"?{param_str}"
        return key

    def _parse_zlib_book(self, data: Dict) -> BookResult:
        zlib_id = data.get("id")
        raw_download_url = data.get("download_url")
        dl = data.get("dl", "")
        download_url = raw_download_url
        if not download_url and dl:
            download_url = f"{self.base_url}{dl}" if str(dl).startswith("/") else dl
        if download_url:
            url = download_url.strip()
            if url.startswith("//"):
                download_url = "https:" + url
            elif url.startswith("/"):
                download_url = f"{self.base_url}{url}"
            elif url.startswith(("http://", "https://")):
                download_url = url
            else:
                download_url = None
        read_online_url = data.get("readOnlineUrl") or data.get("read_online_url")
        file_token = None
        if read_online_url:
            token_match = re.search(r'file_access_token=([^&]+)', read_online_url)
            if token_match:
                file_token = token_match.group(1)
        extension = data.get("extension") or ""
        logger.debug(f"_parse_zlib_book: id={zlib_id} title='{data.get('title', 'N/A')}' "
                     f"raw_download_url={raw_download_url!r} dl={dl!r} resolved={download_url!r} "
                     f"has_token={bool(file_token)} ext={extension}")
        return BookResult(
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
            download_count=data.get("download_count", 0),
            category=data.get("category"),
            pages=data.get("pages"),
            language=data.get("language"),
            rating=data.get("rating"),
            zlibrary_id=zlib_id,
            read_online_url=read_online_url,
            file_token=file_token,
            extension=extension,
        )

    @retry(
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError, APIError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        after=after_log(logger, "WARNING"),
        before_sleep=before_sleep_log(logger, "DEBUG"),
    )
    async def _request(
        self,
        method: str,
        url: str = "",
        path: str = "",
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        use_cache: bool = True,
        cache_ttl: Optional[int] = None,
    ) -> APIResponse:
        if not self.session:
            raise APIError("API session not initialized")

        if path:
            base = self.base_url
            if self.mirror_manager:
                try:
                    base = await self.mirror_manager.get_active_base_url()
                except NoHealthyMirrorError:
                    pass
            url = f"{base}{path}"

        cache_key = self._build_cache_key(
            url.replace(self.base_url, "").split("?")[0],
            params or json_data,
        )

        if use_cache and method.upper() == "GET":
            cached = await cache.get(cache_key)
            if cached is not None:
                logger.debug(f"CACHE HIT for key={cache_key}")
                return APIResponse(data=cached, cached=True)

        await self.rate_limiter.acquire()

        logger.debug(f"API request: {method} {url} params={params} json={json_data}")

        cookies = None
        if self._remix_userkey and self._remix_userid:
            cookies = {"remix_userkey": self._remix_userkey, "remix_userid": self._remix_userid}

        try:
            async with self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                cookies=cookies,
            ) as response:
                if response.status == 429:
                    retry_after = int(response.headers.get("Retry-After", "5"))
                    logger.warning(f"Rate limited by API, waiting {retry_after}s")
                    await asyncio.sleep(retry_after)
                    raise APIError(f"Rate limited, retry after {retry_after}s")

                if response.status == 401:
                    raise APIError("Authentication failed - check API key")

                if response.status == 404:
                    return APIResponse(data=None)

                if response.status >= 500:
                    if self.mirror_manager:
                        mirror_url = self.mirror_manager.active_mirror
                        await self.mirror_manager.record_failure(mirror_url)
                        logger.warning(f"Mirror {mirror_url} returned {response.status}, recorded failure")
                    raise APIError(f"API server error: {response.status}")

                if response.status != 200:
                    error_text = await response.text()
                    raise APIError(f"API error {response.status}: {error_text[:200]}")

                data = await response.json()

                if self.mirror_manager:
                    await self.mirror_manager.record_success(self.mirror_manager.active_mirror)

                if use_cache:
                    await cache.set(cache_key, data, ttl=cache_ttl)

                return APIResponse(data=data)

        except aiohttp.ClientError as e:
            if self.mirror_manager:
                await self.mirror_manager.record_failure(self.mirror_manager.active_mirror)
            logger.error(f"HTTP client error: {e}")
            raise APIError(f"HTTP client error: {e}") from e
        except asyncio.TimeoutError as e:
            if self.mirror_manager:
                await self.mirror_manager.record_failure(self.mirror_manager.active_mirror)
            logger.error(f"Request timeout: {e}")
            raise APIError(f"Request timeout: {e}") from e
        except Exception as e:
            if isinstance(e, APIError):
                raise
            if self.mirror_manager:
                await self.mirror_manager.record_failure(self.mirror_manager.active_mirror)
            logger.error(f"Unexpected API error: {e}")
            raise APIError(f"Unexpected error: {e}") from e

    def _extract_total(self, data: Dict, books: List[BookResult]) -> int:
        total = data.get("total")
        if total is None:
            total = data.get("count")
        if total is None:
            pagination = data.get("pagination") or {}
            total = pagination.get("total_items")
        if total is None:
            total = data.get("exactBooksCount")
        if total is None:
            total = len(books)
        return total

    async def _parse_search_response(self, data: Any) -> Tuple[List[BookResult], int]:
        if data is None:
            return [], 0

        books_data = data.get("books", [])
        if not books_data:
            books_data = data.get("results", data.get("data", []))

        if not books_data:
            return [], 0

        books = [self._parse_zlib_book(b) for b in books_data]
        total = self._extract_total(data, books)

        return books, total

    def _results_look_repeated(self, books: List[BookResult], threshold: float = 0.8) -> bool:
        if not books or not self._last_search_fingerprints:
            return False

        current = {b.fingerprint() for b in books if b.id}
        if not current:
            return False

        overlap = len(current & set(self._last_search_fingerprints))
        ratio = overlap / len(current) if current else 0
        return ratio >= threshold

    def _results_match_query(self, query: str, books: List[BookResult]) -> bool:
        if not query or not books:
            return True

        query_lower = query.lower()
        query_words = set(query_lower.split())

        if not query_words:
            return True

        for book in books:
            title_lower = (book.title or "").lower()
            words_found = sum(1 for w in query_words if w in title_lower)
            if words_found >= max(1, len(query_words) // 2):
                return True

        return False

    async def search_books(
        self,
        query: str,
        field: str = "title",
        page: int = 1,
        per_page: int = 10,
        language: Optional[str] = None,
        category_slug: Optional[str] = None,
    ) -> Tuple[List[BookResult], int]:
        query = query.strip()
        logger.info(f"=== SEARCH: query='{query}' field={field} page={page} limit={per_page} lang={language} cat={category_slug} ===")

        await self._sync_base_url()

        cookies = None
        if self._remix_userkey and self._remix_userid:
            cookies = {"remix_userkey": self._remix_userkey, "remix_userid": self._remix_userid}

        eapi_url = f"{self.base_url}/eapi/book/search"
        eapi_payload: Dict[str, Any] = {"message": query, "page": page, "limit": per_page}
        if language:
            eapi_payload["languages[]"] = language
        if category_slug:
            eapi_payload["categories[]"] = category_slug

        form_data = {k: str(v) if not isinstance(v, str) else v for k, v in eapi_payload.items()}

        hash_url = f"{self.base_url}{self._search_endpoint}"
        hash_payload: Dict[str, Any] = {"query": query, "page": page, "limit": per_page}
        if field == "author":
            hash_payload["query"] = f"author:{query}"
        elif field == "isbn":
            hash_payload["query"] = f"isbn:{query}"

        get_url = f"{self.base_url}/search"
        get_params = {"q": query, "page": str(page), "limit": str(per_page)}
        if language:
            get_params["languages[]"] = language
        if category_slug:
            get_params["categories[]"] = category_slug

        last_error = None

        # Attempt 1: GET /search?q=... (most standard, likely to respect query)
        try:
            books, total = await self._try_get_search(get_url, get_params, cookies)
            if books:
                logger.success(f"  [method=GET /search] {len(books)} books, total={total}")
                for b in books[:3]:
                    logger.info(f"    [{b.id}] {b.title} / {b.author}")
                if await self._accept_results(query, books):
                    return books, total
        except Exception as e:
            last_error = e
            logger.warning(f"  [method=GET /search] FAILED: {e}")

        # Attempt 2: POST /eapi/book/search (JSON)
        try:
            books, total = await self._try_eapi_json(eapi_url, eapi_payload, cookies)
            if books:
                logger.success(f"  [method=EAPI JSON] {len(books)} books, total={total}")
                for b in books[:3]:
                    logger.info(f"    [{b.id}] {b.title} / {b.author}")
                if await self._accept_results(query, books):
                    return books, total
        except Exception as e:
            last_error = e
            logger.warning(f"  [method=EAPI JSON] FAILED: {e}")

        # Attempt 3: POST /eapi/book/search (form-encoded)
        try:
            books, total = await self._try_eapi_form(eapi_url, form_data, cookies)
            if books:
                logger.success(f"  [method=EAPI form] {len(books)} books, total={total}")
                for b in books[:3]:
                    logger.info(f"    [{b.id}] {b.title} / {b.author}")
                if await self._accept_results(query, books):
                    return books, total
        except Exception as e:
            last_error = e
            logger.warning(f"  [method=EAPI form] FAILED: {e}")

        # Attempt 4: POST hash endpoint (legacy), fallback to GET /search via _request
        try:
            books, total = await self._try_hash_endpoint(hash_url, hash_payload, query)
            if books:
                logger.success(f"  [method=hash endpoint] {len(books)} books, total={total}")
                for b in books[:3]:
                    logger.info(f"    [{b.id}] {b.title} / {b.author}")
                self._last_search_fingerprints = [b.fingerprint() for b in books]
                return books, total
        except Exception as e:
            last_error = e
            logger.warning(f"  [method=hash endpoint] FAILED: {e}")

        logger.error(f"All search methods failed for '{query}'. Last error: {last_error}")
        return [], 0

    async def _accept_results(self, query: str, books: List[BookResult]) -> bool:
        if not query:
            return True

        if self._results_look_repeated(books):
            self._last_search_fingerprints = [b.fingerprint() for b in books]
            logger.debug(f"  Results rejected: >80% overlap with previous search")
            return False

        if not self._results_match_query(query, books):
            self._last_search_fingerprints = [b.fingerprint() for b in books]
            logger.debug(f"  Results rejected: no title matches query words")
            return False

        self._last_search_fingerprints = [b.fingerprint() for b in books]
        return True

    async def _try_get_search(
        self, url: str, params: Dict, cookies: Optional[Dict]
    ) -> Tuple[List[BookResult], int]:
        await self.rate_limiter.acquire()
        async with self.session.get(url, params=params, cookies=cookies) as resp:
            logger.info(f"    GET {url} params={params} -> status={resp.status}")
            if resp.status == 429:
                retry_after = int(resp.headers.get("Retry-After", "5"))
                await asyncio.sleep(retry_after)
            resp.raise_for_status()
            if resp.status != 200:
                text = (await resp.text())[:200]
                raise APIError(f"HTTP {resp.status}: {text}")
            data = await resp.json()
            logger.info(f"    Response keys: {list(data.keys())}")
            return await self._parse_search_response(data)

    async def _try_eapi_json(
        self, url: str, payload: Dict, cookies: Optional[Dict]
    ) -> Tuple[List[BookResult], int]:
        await self.rate_limiter.acquire()

        async with self.session.post(url, json=payload, cookies=cookies) as resp:
            if resp.status != 200:
                raw_text = await resp.text()
                logger.warning(f"EAPI JSON POST {url} -> {resp.status}")
                raise APIError(f"HTTP {resp.status}: {raw_text[:200]}")

            data = await resp.json()
            books = data.get("books", [])
            logger.debug(f"EAPI JSON {url}: {len(books)} books, success={data.get('success')}")
            return await self._parse_search_response(data)

    async def _try_eapi_form(
        self, url: str, form_data: Dict, cookies: Optional[Dict]
    ) -> Tuple[List[BookResult], int]:
        await self.rate_limiter.acquire()

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        async with self.session.post(url, data=form_data, cookies=cookies, headers=headers) as resp:
            if resp.status != 200:
                raw_text = await resp.text()
                logger.warning(f"EAPI form POST {url} -> {resp.status}")
                raise APIError(f"HTTP {resp.status}: {raw_text[:200]}")

            data = await resp.json()
            books = data.get("books", [])
            logger.debug(f"EAPI form {url}: {len(books)} books, success={data.get('success')}")
            return await self._parse_search_response(data)

    async def _try_hash_endpoint(
        self, url: str, payload: Dict, query: str
    ) -> Tuple[List[BookResult], int]:
        try:
            response = await self._request("POST", url, json_data=payload, use_cache=True, cache_ttl=120)
            logger.info(f"    POST {url} -> data type={type(response.data).__name__}")
            return await self._parse_search_response(response.data)
        except Exception as e:
            logger.warning(f"    Hash endpoint failed: {e}")
            params = {"q": query, "page": payload.get("page", 1), "limit": payload.get("limit", 10)}
            logger.info(f"    Fallback GET /search params={params}")
            response = await self._request("GET", path="/search", params=params, use_cache=True, cache_ttl=120)
            return await self._parse_search_response(response.data)

    async def get_book(self, book_id: str) -> Optional[BookResult]:
        await self._sync_base_url()

        for p in [f"/book/{book_id}", f"/books/{book_id}"]:
            try:
                response = await self._request("GET", path=p, use_cache=True, cache_ttl=300)
                if response.data is not None:
                    book_data = response.data.get("book", response.data)
                    return self._parse_zlib_book(book_data)
            except Exception:
                continue

        # Fallback: search via EAPI form
        try:
            cookies = None
            if self._remix_userkey and self._remix_userid:
                cookies = {"remix_userkey": self._remix_userkey, "remix_userid": self._remix_userid}
            async with self.session.post(
                f"{self.base_url}/eapi/book/search",
                data={"message": book_id, "page": "1", "limit": "5"},
                cookies=cookies,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for b in data.get("books", []):
                        if str(b.get("id")) == str(book_id):
                            return self._parse_zlib_book(b)
        except Exception:
            pass

        return None

    @staticmethod
    def _is_real_file(data: bytes, expected_format: str) -> bool:
        MAGIC = {
            "epub": b"PK",
            "pdf": b"%PDF",
            "mobi": b"BOOKMOBI",
            "azw3": b"BOOKMOBI",
            "djvu": b"AT&T",
            "fb2": b"<?xml",
        }
        magic = MAGIC.get(expected_format.lower())
        if magic is None:
            return True
        if expected_format.lower() in ("mobi", "azw3"):
            return b"BOOKMOBI" in data[:256]
        return len(data) >= len(magic) and data[:len(magic)] == magic

    def _is_cloudflare_body(self, body: bytes) -> bool:
        decoded = body[:500].decode("utf-8", errors="replace").lower()
        return ("checking your browser" in decoded or "cf-browser-verification" in decoded
                or "just a moment" in decoded or "cloudflare" in decoded)

    @staticmethod
    def _normalize_url(raw_url: Optional[str]) -> Optional[str]:
        if not raw_url:
            return None
        url = raw_url.strip()
        if not url:
            return None
        if url.startswith("//"):
            url = url.replace("//", "https://", 1)
        elif url.startswith("/"):
            return None
        if not url.startswith(("http://", "https://")):
            return None
        return url

    async def _download_with_retry(self, url: str, cookies: Optional[Dict], max_bytes: int, fmt: str = "epub",
                                    extra_headers: Optional[Dict] = None) -> Optional[bytes]:
        """Single download attempt with redirect following and response validation."""
        current_url = self._normalize_url(url)
        if not current_url:
            logger.warning(f"  Invalid URL (not absolute): {url!r}")
            return None
        redirect_count = 0
        max_redirects = 10
        retried = False
        headers = {"Accept": "*/*"}
        if extra_headers:
            headers.update(extra_headers)

        while redirect_count < max_redirects:
            async with self.session.get(
                current_url,
                cookies=cookies,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120, sock_read=60),
                allow_redirects=False,
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location")
                    logger.info(f"  Redirect: {current_url} -> {location}")
                    if not location:
                        logger.warning(f"  Empty redirect Location from {current_url}")
                        return None
                    location = location.strip()
                    if location.startswith("/"):
                        try:
                            base = YarlURL(current_url)
                            joined = str(base.origin()) + location
                            location = joined
                        except Exception:
                            logger.warning(f"  Could not resolve relative redirect: {location}")
                            return None
                    else:
                        location = self._normalize_url(location)
                        if not location:
                            logger.warning(f"  Invalid redirect Location from {current_url}: {resp.headers.get('Location')!r}")
                            return None
                    current_url = location
                    redirect_count += 1
                    continue

                if resp.status != 200:
                    body = await resp.read()
                    if self._is_cloudflare_body(body):
                        logger.warning(f"  Cloudflare challenge at {current_url} (HTTP {resp.status})")
                    else:
                        logger.warning(f"  Non-200: HTTP {resp.status} for {current_url}")
                    return None

                ct = resp.headers.get("Content-Type", "")
                if "text/html" in ct:
                    logger.warning(f"  HTML Content-Type at {current_url}, session may be expired")
                    if not retried:
                        logger.info("  Re-authenticating and retrying...")
                        await self._login()
                        retried = True
                        continue
                    logger.error(f"  HTML Content-Type after re-auth, giving up: {current_url}")
                    return None

                raw_chunk = await resp.content.read(200)
                decoded = raw_chunk.decode("utf-8", errors="replace").lower()
                is_html = "<!doctype html" in decoded or "<html" in decoded
                if is_html or self._is_cloudflare_body(raw_chunk):
                    logger.warning(f"  HTML response (not a file): {current_url}")
                    if not retried:
                        logger.info("  Re-authenticating and retrying...")
                        await self._login()
                        retried = True
                        continue
                    return None
                if decoded.startswith("{"):
                    logger.warning(f"  JSON response (not a file): {current_url}")
                    return None
                if len(raw_chunk) == 0:
                    logger.warning(f"  Empty response: {current_url}")
                    return None

                remainder = await resp.content.read()
                file_bytes = raw_chunk + remainder
                actual_size = len(file_bytes)
                content_length = resp.content_length
                if content_length and content_length > max_bytes:
                    logger.warning(f"  File too large: {content_length} bytes (max {max_bytes})")
                    return None
                if actual_size == 0:
                    return None
                logger.info(f"  Downloaded {actual_size} bytes from {current_url}")
                if not self._is_real_file(file_bytes, fmt):
                    logger.warning(f"  Magic bytes mismatch for {fmt}: "
                                   f"{file_bytes[:100].decode('utf-8', errors='replace')!r}")
                    return None
                return file_bytes

        logger.warning(f"  Too many redirects")
        return None

    async def download_file(self, url: str, max_bytes: int = 52428800,
                            alt_url: Optional[str] = None, file_token: Optional[str] = None,
                            fmt: str = "epub") -> Optional[bytes]:
        logger.info("=== DOWNLOAD TRACE: Step 3 - File Request ===")
        cookies = None
        if self._remix_userkey and self._remix_userid:
            cookies = {"remix_userkey": self._remix_userkey, "remix_userid": self._remix_userid}

        clean_url = self._normalize_url(url)
        logger.info(f"  3.1 Primary URL: {clean_url} (original: {url!r})")
        logger.info(f"  3.2 Alt URL: {alt_url}")
        logger.info(f"  3.3 Has file_token: {bool(file_token)}")
        logger.info(f"  3.4 Cookies: remix_userid={'set' if cookies and cookies.get('remix_userid') else 'none'}, "
                     f"remix_userkey={'set' if cookies and cookies.get('remix_userkey') else 'none'}")
        logger.info(f"  3.5 Expected format: {fmt}")

        if not clean_url:
            logger.warning(f"  Invalid primary URL (not absolute): {url!r}")
            return None

        # Strategy 1: Try primary URL with remix cookies
        logger.info("  Attempt 1: primary URL with remix cookies")
        result = await self._download_with_retry(clean_url, cookies, max_bytes, fmt)
        if result:
            return result

        # Strategy 2: Re-authenticate and retry once (handles expired sessions)
        logger.info("  Re-authenticating for retry...")
        await self._login()
        if self._remix_userkey and self._remix_userid:
            cookies = {"remix_userkey": self._remix_userkey, "remix_userid": self._remix_userid}
        result = await self._download_with_retry(clean_url, cookies, max_bytes, fmt)
        if result:
            return result

        # Strategy 3: Try with file_access_token appended (bypasses Cloudflare for some mirrors)
        if file_token:
            token_url = f"{clean_url}?file_access_token={file_token}"
            logger.info(f"  Attempt 3: URL with file_access_token")
            result = await self._download_with_retry(token_url, cookies, max_bytes, fmt)
            if result:
                return result

        # Strategies 4/5: alt_url (readOnlineUrl) skipped — it's always an HTML reader page,
        # never a file download. Browser downloader handles Cloudflare directly.

        logger.warning("  Download failed (likely Cloudflare protected), falling through to browser download")
        return None

    async def get_categories(self) -> List[Dict]:
        await self._sync_base_url()
        FALLBACK_CATEGORIES = [
            {"slug": "fiction", "name": "Fiction"},
            {"slug": "non-fiction", "name": "Non-Fiction"},
            {"slug": "science", "name": "Science"},
            {"slug": "history", "name": "History"},
            {"slug": "philosophy", "name": "Philosophy"},
            {"slug": "psychology", "name": "Psychology"},
            {"slug": "religion", "name": "Religion"},
            {"slug": "computers", "name": "Computers & Technology"},
            {"slug": "business", "name": "Business & Economics"},
            {"slug": "self-help", "name": "Self-Help"},
            {"slug": "health", "name": "Health & Fitness"},
            {"slug": "art", "name": "Art"},
            {"slug": "biography", "name": "Biography"},
            {"slug": "education", "name": "Education & Teaching"},
            {"slug": "entertainment", "name": "Entertainment"},
            {"slug": "mystery", "name": "Mystery"},
            {"slug": "romance", "name": "Romance"},
            {"slug": "sci-fi", "name": "Science Fiction"},
            {"slug": "fantasy", "name": "Fantasy"},
            {"slug": "horror", "name": "Horror"},
            {"slug": "thriller", "name": "Thriller"},
            {"slug": "cooking", "name": "Cooking & Food"},
            {"slug": "travel", "name": "Travel"},
            {"slug": "sports", "name": "Sports"},
            {"slug": "comics", "name": "Comics"},
            {"slug": "children", "name": "Children"},
            {"slug": "poetry", "name": "Poetry"},
            {"slug": "technical", "name": "Technical"},
            {"slug": "literature", "name": "Literature"},
        ]

        url = f"{self.base_url}/categories"
        try:
            response = await self._request("GET", url, use_cache=True, cache_ttl=600)
            if response.data is not None:
                categories = response.data.get("categories", response.data.get("results", []))
                if categories:
                    return categories
        except Exception:
            logger.debug("GET /categories failed, using hardcoded fallback")

        return FALLBACK_CATEGORIES

    async def get_popular_books(self, limit: int = 10) -> List[BookResult]:
        await self._sync_base_url()
        url = f"{self.base_url}/eapi/book/most-popular"
        try:
            response = await self._request("GET", url, use_cache=True, cache_ttl=300)
            if response.data and response.data.get("books"):
                books_data = response.data["books"][:limit]
                logger.info(f"Popular books from /eapi/book/most-popular: {len(books_data)} books")
                return [self._parse_zlib_book(b) for b in books_data]
        except Exception:
            pass

        for fallback_path in ["/books/popular", "/trending"]:
            try:
                response = await self._request("GET", path=fallback_path, params={"limit": limit}, use_cache=True, cache_ttl=300)
                if response.data is not None:
                    books_data = response.data.get("books", response.data.get("results", []))
                    if books_data:
                        logger.info(f"Popular books from {fallback_path}: {len(books_data)} books")
                        return [self._parse_zlib_book(b) for b in books_data]
            except Exception:
                continue

        return []

    async def get_recent_books(self, limit: int = 10) -> List[BookResult]:
        await self._sync_base_url()

        for path in ["/eapi/book/recently", "/books/recent", "/latest"]:
            try:
                response = await self._request("GET", path=path, params={"limit": limit}, use_cache=True, cache_ttl=300)
                if response.data and response.data.get("books"):
                    books_data = response.data["books"][:limit]
                    logger.info(f"Recent books from {path}: {len(books_data)} books")
                    return [self._parse_zlib_book(b) for b in books_data]
            except Exception:
                continue

        return []

    async def get_book_by_isbn(self, isbn: str) -> Optional[BookResult]:
        books, total = await self.search_books(isbn, field="isbn", page=1, per_page=1)
        if books:
            return books[0]
        return None

    async def get_books_by_category(
        self, category_slug: str, page: int = 1, per_page: int = 10, language: Optional[str] = None
    ) -> Tuple[List[BookResult], int]:
        logger.info(f"=== CATEGORY BROWSE: slug='{category_slug}' page={page} language={language} ===")
        await self._sync_base_url()

        cookies = None
        if self._remix_userkey and self._remix_userid:
            cookies = {"remix_userkey": self._remix_userkey, "remix_userid": self._remix_userid}

        # Try GET /search with category filter first
        search_params = {"q": "", "page": str(page), "limit": str(per_page), "categories[]": category_slug}
        if language:
            search_params["languages[]"] = language

        try:
            await self.rate_limiter.acquire()
            async with self.session.get(f"{self.base_url}/search", params=search_params, cookies=cookies) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    books_data = data.get("books", [])
                    if books_data:
                        books = [self._parse_zlib_book(b) for b in books_data]
                        total = self._extract_total(data, books)
                        logger.info(f"  GET /search (category) -> {len(books)} books, total={total}")
                        return books, total
        except Exception as e:
            logger.warning(f"  GET /search for category failed: {e}")

        # Fallback: EAPI POST (form-encoded — JSON ignores payload on this mirror)
        # Use category slug as search query first so results are relevant even if categories[] filter is ignored
        queries = [category_slug.replace("-", " "), " ", "the", ""]
        for query_fallback in queries:
            form_payload: Dict[str, Any] = {
                "message": query_fallback,
                "page": page,
                "limit": per_page,
                "categories[]": category_slug,
            }
            if language:
                form_payload["languages[]"] = language
            try:
                await self.rate_limiter.acquire()
                form_headers = {"Content-Type": "application/x-www-form-urlencoded"}
                form_data = {k: str(v) if not isinstance(v, str) else v for k, v in form_payload.items()}
                async with self.session.post(f"{self.base_url}/eapi/book/search", data=form_data, cookies=cookies, headers=form_headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        books_data = data.get("books", [])
                        if books_data:
                            books = [self._parse_zlib_book(b) for b in books_data]
                            total = self._extract_total(data, books)
                            logger.info(f"  EAPI form (category, query='{query_fallback}') -> {len(books)} books, total={total}")
                            return books, total
            except Exception as e:
                logger.warning(f"  EAPI form (query='{query_fallback}') for category failed: {e}")

        try:
            await self.rate_limiter.acquire()
            async with self.session.post(f"{self.base_url}/eapi/book/search", json={"message": "", "page": page, "limit": per_page, "categories[]": category_slug}, cookies=cookies) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    books_data = data.get("books", [])
                    if books_data:
                        books = [self._parse_zlib_book(b) for b in books_data]
                        total = self._extract_total(data, books)
                        logger.info(f"  EAPI JSON (category) -> {len(books)} books, total={total}")
                        return books, total
        except Exception as e:
            logger.warning(f"  EAPI JSON for category failed: {e}")

        logger.warning(f"All category browse attempts failed for slug='{category_slug}'")
        return [], 0

    async def get_status(self) -> Dict:
        status = {
            "authenticated": bool(self._remix_userkey and self._remix_userid),
            "base_url": self.base_url,
        }
        if self.mirror_manager:
            mirror_status = await self.mirror_manager.get_status()
            status["mirror"] = mirror_status
        else:
            status["mirror"] = {"active_mirror": self.base_url, "mirrors": []}

        if hasattr(cache, "is_enabled"):
            status["cache"] = {
                "enabled": cache.is_enabled if hasattr(cache, "is_enabled") else False,
            }
        else:
            status["cache"] = {"enabled": False}

        return status


api = APIService()
