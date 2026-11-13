from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
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
from bot.utils.net import get_proxy_for

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

FORMAT_PRIORITY = {"epub": 0, "pdf": 1, "mobi": 2, "azw3": 3, "fb2": 4, "djvu": 5, "txt": 6, "cbz": 7, "cbr": 8}


@dataclass
class AnnasArchiveBook:
    id: str = ""
    title: str = "Unknown"
    author: Optional[str] = None
    description: Optional[str] = None
    publisher: Optional[str] = None
    publication_year: Optional[int] = None
    isbn: Optional[str] = None
    file_size: Optional[int] = None
    file_size_display: Optional[str] = None
    cover_url: Optional[str] = None
    language: Optional[str] = None
    pages: Optional[int] = None
    extension: Optional[str] = None
    md5: Optional[str] = None
    download_urls: List[str] = field(default_factory=list)
    detail_url: Optional[str] = None


class AnnasArchiveError(Exception):
    pass


class AnnasArchiveBlockedError(AnnasArchiveError):
    """Raised when AA returns 403 or Cloudflare challenge, which should not be retried."""
    pass


class AnnasArchive:
    def __init__(self) -> None:
        self.base_url = settings.annas_archive_base_url.rstrip("/")
        self.secret_key = settings.annas_archive_secret_key
        self._client: Optional[httpx.AsyncClient] = None
        self._cache: Dict[str, Any] = {}
        self._cache_ttl: Dict[str, float] = {}
        self._last_request_time: float = 0.0
        self._user_agent_index: int = 0
        self._auth_cookies: Dict[str, str] = {}

    def _rotate_user_agent(self) -> str:
        ua = USER_AGENTS[self._user_agent_index % len(USER_AGENTS)]
        self._user_agent_index += 1
        return ua

    async def _ensure_auth(self) -> None:
        if not self.secret_key or self._auth_cookies:
            return
        try:
            client = await self._get_client()
            resp = await client.post(
                f"{self.base_url}/account/",
                data={"secret": self.secret_key},
                headers={"User-Agent": self._rotate_user_agent()},
            )
            if resp.status_code == 200 and "secret" not in resp.url.path:
                for cookie in client.cookies.jar:
                    self._auth_cookies[cookie.name] = cookie.value
                if self._auth_cookies:
                    logger.info("AA authenticated via secret key")
        except Exception as e:
            logger.debug(f"AA auth attempt failed: {e}")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                },
                timeout=httpx.Timeout(settings.annas_archive_timeout, connect=15, read=30),
                follow_redirects=True,
                # httpx honours proxy env vars itself, but passing the resolved
                # value explicitly also covers ALL_PROXY consistently.
                proxy=get_proxy_for(self.base_url),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _get_cache(self, key: str) -> Optional[Any]:
        if key in self._cache:
            expiry = self._cache_ttl.get(key, 0)
            if time.monotonic() < expiry:
                return self._cache[key]
            del self._cache[key]
            del self._cache_ttl[key]
        return None

    def _set_cache(self, key: str, value: Any, ttl: int) -> None:
        self._cache[key] = value
        self._cache_ttl[key] = time.monotonic() + ttl

    async def _rate_limit(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < 1.5:
            await asyncio.sleep(1.5 - elapsed)
        self._last_request_time = time.monotonic()

    @retry(
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout)),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.5, min=1, max=2),
        after=after_log(logger, "WARNING"),
        before_sleep=before_sleep_log(logger, "DEBUG"),
    )
    async def _request(self, url: str, use_cache: bool = True, cache_ttl: Optional[int] = None) -> httpx.Response:
        cached = self._get_cache(url) if use_cache else None
        if cached is not None:
            return cached

        await self._rate_limit()
        client = await self._get_client()
        ua = self._rotate_user_agent()
        client.headers["User-Agent"] = ua

        logger.debug(f"AA request: GET {url} [UA={ua[:50]}...]")

        response = await client.get(url)
        logger.debug(f"AA response: {url} -> {response.status_code} ({len(response.content)} bytes)")

        if response.status_code == 429:
            retry_after = 5
            logger.warning(f"AA rate-limited (429), waiting {retry_after}s")
            await asyncio.sleep(retry_after)
            raise AnnasArchiveError("Rate limited")

        if response.status_code == 403:
            logger.warning(f"AA blocked (403): {url}")
            raise AnnasArchiveBlockedError("Blocked by CDN")

        if response.status_code == 404:
            raise AnnasArchiveError("Not found")

        if response.status_code >= 500:
            raise AnnasArchiveError(f"Server error: {response.status_code}")

        if use_cache and cache_ttl:
            self._set_cache(url, response, cache_ttl)

        return response

    async def _try_api_search(self, query: str, limit: int = 10) -> Optional[List[dict]]:
        api_url = f"{self.base_url}/api/search"
        try:
            client = await self._get_client()
            ua = self._rotate_user_agent()
            params: Dict[str, Any] = {"q": query, "limit": limit, "format": "json"}
            if self.secret_key:
                params["secret"] = self.secret_key
            response = await client.get(
                api_url,
                params=params,
                headers={"User-Agent": ua, "Accept": "application/json"},
            )
            if response.status_code == 200:
                try:
                    data = response.json()
                    results = data.get("results", data.get("data", []))
                    if results:
                        logger.success(f"AA API search returned {len(results)} results for '{query}'")
                        return results
                except (json.JSONDecodeError, Exception) as e:
                    logger.debug(f"AA API search JSON parse failed: {e}")
            return None
        except Exception as e:
            logger.debug(f"AA API search failed: {e}")
            return None

    async def _try_api_book(self, md5: str) -> Optional[dict]:
        api_url = f"{self.base_url}/api/book/{md5}"
        try:
            client = await self._get_client()
            ua = self._rotate_user_agent()
            params: Dict[str, Any] = {}
            if self.secret_key:
                params["secret"] = self.secret_key
            response = await client.get(
                api_url,
                params=params or None,
                headers={"User-Agent": ua, "Accept": "application/json"},
            )
            if response.status_code == 200:
                try:
                    data = response.json()
                    logger.success(f"AA API book data retrieved for md5={md5}")
                    return data
                except (json.JSONDecodeError, Exception) as e:
                    logger.debug(f"AA API book JSON parse failed: {e}")
            return None
        except Exception as e:
            logger.debug(f"AA API book failed: {e}")
            return None

    async def search(self, query: str, page: int = 1, per_page: int = 10) -> List[AnnasArchiveBook]:
        cache_key = f"aa_search:{query}:{page}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            logger.debug(f"AA search cache hit for '{query}'")
            return cached

        results: List[AnnasArchiveBook] = []

        api_results = await self._try_api_search(query, limit=per_page)
        if api_results:
            for item in api_results:
                book = self._parse_api_search_result(item)
                if book:
                    results.append(book)

        if not results:
            results = await self._scrape_search(query, page)

        self._set_cache(cache_key, results, settings.annas_archive_cache_ttl_search)
        logger.info(f"AA search for '{query}': {len(results)} results")
        return results

    def _parse_api_search_result(self, item: dict) -> Optional[AnnasArchiveBook]:
        try:
            md5 = item.get("md5", item.get("id", ""))
            if not md5:
                return None

            file_size_str = item.get("filesize", item.get("file_size", ""))
            file_size = None
            if file_size_str:
                try:
                    file_size = int(file_size_str)
                except (ValueError, TypeError):
                    file_size = self._parse_file_size(str(file_size_str))

            return AnnasArchiveBook(
                id=md5,
                md5=md5,
                title=item.get("title", "Unknown"),
                author=item.get("author", item.get("creator")),
                extension=item.get("extension", item.get("format", "")).lower().lstrip("."),
                file_size=file_size,
                file_size_display=item.get("filesize_display") or item.get("size_display"),
                language=item.get("language"),
                publisher=item.get("publisher"),
                publication_year=self._safe_int(item.get("year")),
                isbn=item.get("isbn"),
                description=item.get("description"),
                pages=self._safe_int(item.get("pages")),
                cover_url=item.get("cover_url", item.get("cover")),
                detail_url=f"{self.base_url}/md5/{md5}",
            )
        except Exception as e:
            logger.debug(f"AA parse API search result failed: {e}")
            return None

    async def _scrape_search(self, query: str, page: int = 1) -> List[AnnasArchiveBook]:
        results: List[AnnasArchiveBook] = []
        url = f"{self.base_url}/search?q={urllib.parse.quote(query)}&page={page}"

        try:
            response = await self._request(url, use_cache=True, cache_ttl=settings.annas_archive_cache_ttl_search)
        except AnnasArchiveError as e:
            logger.warning(f"AA search scrape failed: {e}")
            return results

        soup = BeautifulSoup(response.text, "lxml")
        book_elements = soup.select("div[class*='book'], div[class*='result'], tr[class*='book'], table.search-results tr, div.search-result-item")

        if not book_elements:
            book_elements = soup.select("a[href*='/md5/']")
            book_elements = [a.find_parent("div") or a.find_parent("li") or a for a in book_elements[:20]]

        if not book_elements:
            book_elements = soup.select("a[href*='/md5/']")
            seen = set()
            unique_links = []
            for a in book_elements:
                href = a.get("href", "")
                if href not in seen:
                    seen.add(href)
                    unique_links.append(a)
            for a in unique_links:
                href = a.get("href", "")
                if "/md5/" in href:
                    full_url = href if href.startswith("http") else f"{self.base_url}{href}"
                    title = a.get_text(strip=True) or a.get("title", "") or ""
                    if title and len(title) > 3:
                        book = AnnasArchiveBook(
                            title=title,
                            detail_url=full_url,
                            extension=self._extract_format_from_element(a),
                        )
                        md5_match = re.search(r"/md5/([a-f0-9]{32})", href)
                        if md5_match:
                            book.id = md5_match.group(1)
                            book.md5 = md5_match.group(1)
                        results.append(book)

            if results:
                logger.info(f"AA scrape: extracted {len(results)} books from href fallback")
                return results
            return results

        for elem in book_elements:
            try:
                book = self._parse_book_element(elem)
                if book and book.title:
                    results.append(book)
            except Exception as e:
                logger.debug(f"AA parse element failed: {e}")
                continue

        logger.info(f"AA scrape: extracted {len(results)} books from HTML")
        return results

    def _parse_book_element(self, elem) -> Optional[AnnasArchiveBook]:
        title_tag = elem.select_one("a[href*='/md5/'], h3 a, h2 a, a[href*='/search/']")
        if not title_tag:
            title_tag = elem.select_one("a")
        if not title_tag:
            return None

        title = title_tag.get_text(strip=True)
        if not title or len(title) < 2:
            return None

        href = title_tag.get("href", "")
        detail_url = href if href.startswith("http") else f"{self.base_url}{href}"

        md5 = None
        md5_match = re.search(r"/md5/([a-f0-9]{32})", href)
        if md5_match:
            md5 = md5_match.group(1)

        author_elem = elem.select_one(".author, .contributor, span.author, td:nth-child(2), div:nth-child(2)")
        author = author_elem.get_text(strip=True) if author_elem else None

        ext_elem = elem.select_one(".format, .extension, span.format, td:nth-child(3), div:nth-child(3)")
        extension = ext_elem.get_text(strip=True).lower() if ext_elem else None

        size_elem = elem.select_one(".size, .filesize, span.size, td:nth-child(4)")
        file_size_display = size_elem.get_text(strip=True) if size_elem else None
        file_size = self._parse_file_size(file_size_display) if file_size_display else None

        return AnnasArchiveBook(
            id=md5 or detail_url,
            md5=md5,
            title=title,
            author=author,
            extension=extension,
            file_size=file_size,
            file_size_display=file_size_display,
            detail_url=detail_url,
        )

    def _extract_format_from_element(self, elem) -> Optional[str]:
        text = elem.get_text(strip=True)
        formats = ["pdf", "epub", "mobi", "azw3", "fb2", "djvu", "txt", "cbz", "cbr"]
        for fmt in formats:
            if fmt in text.lower():
                return fmt
        return None

    async def get_book_details(self, book_id: str) -> Optional[AnnasArchiveBook]:
        cache_key = f"aa_book:{book_id}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        api_data = None
        if re.match(r"^[a-f0-9]{32}$", book_id):
            api_data = await self._try_api_book(book_id)
            if api_data:
                book = self._parse_api_detail(api_data)
                if book:
                    self._set_cache(cache_key, book, settings.annas_archive_cache_ttl_metadata)
                    return book

        md5_param = book_id if re.match(r"^[a-f0-9]{32}$", book_id) else ""
        if md5_param:
            url = f"{self.base_url}/md5/{md5_param}"
        elif book_id.startswith("http"):
            url = book_id
        else:
            url = f"{self.base_url}/md5/{book_id}"

        try:
            response = await self._request(url, use_cache=True, cache_ttl=settings.annas_archive_cache_ttl_metadata)
        except AnnasArchiveError as e:
            logger.warning(f"AA get_book_details failed: {e}")
            return None

        book = self._scrape_detail_page(response.text, url)
        if book:
            self._set_cache(cache_key, book, settings.annas_archive_cache_ttl_metadata)
        return book

    def _parse_api_detail(self, data: dict) -> Optional[AnnasArchiveBook]:
        try:
            md5 = data.get("md5", "")
            file_size_str = data.get("filesize", data.get("file_size", ""))
            file_size = None
            if file_size_str:
                try:
                    file_size = int(file_size_str)
                except (ValueError, TypeError):
                    file_size = self._parse_file_size(str(file_size_str))

            return AnnasArchiveBook(
                id=md5,
                md5=md5,
                title=data.get("title", "Unknown"),
                author=data.get("author", data.get("creator")),
                extension=(data.get("extension", data.get("format", "")) or "").lower().lstrip("."),
                file_size=file_size,
                file_size_display=data.get("filesize_display"),
                language=data.get("language"),
                publisher=data.get("publisher"),
                publication_year=self._safe_int(data.get("year")),
                isbn=data.get("isbn"),
                description=data.get("description"),
                pages=self._safe_int(data.get("pages")),
                cover_url=data.get("cover_url", data.get("cover")),
                download_urls=data.get("download_urls", []),
                detail_url=f"{self.base_url}/md5/{md5}",
            )
        except Exception as e:
            logger.debug(f"AA parse API detail failed: {e}")
            return None

    def _scrape_detail_page(self, html: str, url: str) -> Optional[AnnasArchiveBook]:
        soup = BeautifulSoup(html, "lxml")

        md5 = None
        md5_match = re.search(r"/md5/([a-f0-9]{32})", url)
        if md5_match:
            md5 = md5_match.group(1)

        title_tag = soup.select_one("h1, h2.book-title, div.book-title h1")
        title = title_tag.get_text(strip=True) if title_tag else "Unknown"

        info_table = soup.select_one("table, div.book-info, dl.book-metadata")

        author = self._extract_field(soup, "author")
        publisher = self._extract_field(soup, "publisher")
        year = self._safe_int(self._extract_field(soup, "year"))
        isbn = self._extract_field(soup, "isbn")
        pages = self._safe_int(self._extract_field(soup, "pages"))
        language = self._extract_field(soup, "language")

        ext_elem = soup.select_one(".format, .file-format, span[class*='format'], td:contains('Format') + td")
        extension = ext_elem.get_text(strip=True).lower() if ext_elem else None
        if not extension:
            ext_match = re.search(r"\.(epub|pdf|mobi|azw3|fb2|djvu|txt|cbz|cbr)\b", html[:2000], re.IGNORECASE)
            if ext_match:
                extension = ext_match.group(1).lower()

        size_elem = soup.select_one(".size, .file-size, span[class*='size'], td:contains('Size') + td")
        file_size_display = size_elem.get_text(strip=True) if size_elem else None
        file_size = self._parse_file_size(file_size_display) if file_size_display else None

        desc_elem = soup.select_one(".description, div.description, .book-description, p.description")
        description = desc_elem.get_text(strip=True) if desc_elem else None

        cover_elem = soup.select_one(".cover img, img.cover, .book-cover img, img[src*='cover']")
        cover_url = cover_elem.get("src", "") if cover_elem else None
        if cover_url and cover_url.startswith("/"):
            cover_url = f"{self.base_url}{cover_url}"

        download_links = self._extract_download_links(soup)

        return AnnasArchiveBook(
            id=md5 or url,
            md5=md5,
            title=title,
            author=author,
            publisher=publisher,
            publication_year=year,
            isbn=isbn,
            pages=pages,
            language=language,
            extension=extension,
            file_size=file_size,
            file_size_display=file_size_display,
            description=description,
            cover_url=cover_url,
            download_urls=download_links,
            detail_url=url,
        )

    def _extract_field(self, soup, label: str) -> Optional[str]:
        patterns = [
            f"th:contains('{label.capitalize()}') + td",
            f"td:contains('{label.capitalize()}') + td",
            f"dt:contains('{label.capitalize()}') + dd",
            f"span.label:contains('{label.capitalize()}') + span.value",
            f"div.book-{label}",
            f"span.book-{label}",
        ]
        for pattern in patterns:
            elem = soup.select_one(pattern)
            if elem:
                text = elem.get_text(strip=True)
                if text:
                    return text

        for tag in soup.find_all(["th", "td", "dt", "dd", "span", "div"]):
            if label.lower() in tag.get_text(strip=True).lower():
                sibling = tag.find_next_sibling(["td", "dd", "span", "div"])
                if sibling:
                    text = sibling.get_text(strip=True)
                    if text:
                        return text
        return None

    def _extract_download_links(self, soup) -> List[str]:
        links = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            text = a.get_text(strip=True).lower()
            if "/dl/" in href or "slow" in href or "fast" in href or "download" in href:
                full_url = href if href.startswith("http") else f"{self.base_url}{href}"
                if full_url not in links:
                    links.append(full_url)

        for a in soup.select("a[href*='cloudflare'], a[href*='ipfs'], a[href*='gateway']"):
            href = a.get("href", "")
            full_url = href if href.startswith("http") else f"{self.base_url}{href}"
            if full_url not in links:
                links.append(full_url)

        return links

    async def get_download_links(self, book_id: str) -> List[str]:
        if self.secret_key and re.match(r"^[a-f0-9]{32}$", book_id):
            api_data = await self._try_api_book(book_id)
            if api_data and api_data.get("download_urls"):
                return api_data["download_urls"]
        book = await self.get_book_details(book_id)
        if book and book.download_urls:
            return book.download_urls
        return []

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, asyncio.TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        after=after_log(logger, "WARNING"),
        before_sleep=before_sleep_log(logger, "DEBUG"),
    )
    async def download(self, url: str, expected_format: str = "epub") -> Optional[bytes]:
        await self._ensure_auth()
        await self._rate_limit()
        client = await self._get_client()
        ua = self._rotate_user_agent()

        logger.info(f"AA download: {url} [expected={expected_format}]")

        try:
            response = await client.get(
                url,
                headers={"User-Agent": ua, "Accept": "*/*"},
                follow_redirects=True,
                timeout=httpx.Timeout(120, connect=15, read=90),
            )
        except httpx.HTTPError as e:
            logger.warning(f"AA download HTTP error: {e}")
            raise

        if response.status_code != 200:
            logger.warning(f"AA download HTTP {response.status_code}: {url}")
            return None

        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            logger.warning(f"AA download returned HTML (not a file): {url}")
            return None

        data = response.content
        if len(data) < 256:
            logger.warning(f"AA download too small ({len(data)} bytes): {url}")
            return None

        if self._is_valid_file(data, expected_format):
            logger.success(f"AA download: {len(data)} bytes from {url[:60]}...")
            return data

        logger.warning(f"AA download magic bytes mismatch for {expected_format}: {url}")
        return None

    @staticmethod
    def _is_valid_file(data: bytes, expected_format: str) -> bool:
        MAGIC = {
            "epub": b"PK",
            "pdf": b"%PDF",
            "mobi": b"BOOKMOBI",
            "azw3": b"BOOKMOBI",
            "djvu": b"AT&T",
            "fb2": b"<?xml",
            "txt": None,
            "cbz": b"PK",
            "cbr": b"Rar!",
        }
        magic = MAGIC.get(expected_format.lower())
        if magic is None:
            return True
        if expected_format.lower() in ("mobi", "azw3"):
            return b"BOOKMOBI" in data[:256]
        return len(data) >= len(magic) and data[:len(magic)] == magic

    @staticmethod
    def _parse_file_size(size_str: Optional[str]) -> Optional[int]:
        if not size_str:
            return None
        size_str = size_str.strip().upper()
        try:
            multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
            match = re.match(r"([\d.]+)\s*(B|KB|MB|GB|TB)", size_str)
            if match:
                value = float(match.group(1))
                unit = match.group(2)
                return int(value * multipliers[unit])
            return int(float(size_str))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None


annas_archive = AnnasArchive()
