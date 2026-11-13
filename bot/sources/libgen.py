"""bot/sources/libgen.py — Library Genesis (LibGen) source (feature #12)."""
from __future__ import annotations

import asyncio
import html as html_lib
import re
import urllib.parse
from typing import List, Optional, Tuple
import aiohttp
from bs4 import BeautifulSoup
from loguru import logger

from bot.config.settings import settings
from bot.services.api import BookResult
from bot.utils.net import proxy_kwargs


FILE_EXTENSIONS = ("pdf", "epub", "mobi", "azw3", "djvu", "fb2", "txt", "cbz", "cbr", "zip", "rar")
MAGIC = {
    "epub": b"PK",
    "pdf": b"%PDF",
    "mobi": b"BOOKMOBI",
    "azw3": b"BOOKMOBI",
    "djvu": b"AT&T",
    "fb2": b"<?xml",
}


def _parse_size(size_str: str) -> Optional[int]:
    match = re.search(r"([\d.]+)\s*([kmgt]?b)", size_str or "", re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    multiplier = {"b": 1, "kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3, "tb": 1024 ** 4}
    return int(value * multiplier.get(unit, 1)) or None


def is_libgen_url(url: str) -> bool:
    """Return True when *url* points at a LibGen resolver/download host."""
    host = (urllib.parse.urlparse(url or "").hostname or "").lower()
    if not host:
        return False
    return any(
        host == name or host.endswith("." + name)
        for name in (
            "libgen.li",
            "libgen.la",
            "libgen.bz",
            "libgen.vg",
            "libgen.is",
            "libgen.rs",
            "libgen.st",
            "libgen.pw",
            "library.lol",
            "booksdl.lc",
            "libgen.com.de",
        )
    )


class LibGenSource:
    """LibGen search provider with resilient mirror fallback and HTML table parsing."""

    # libgen.is/.rs/.st are unreachable from many networks; the .li family is
    # the currently working LibGen frontend.
    MIRRORS = [
        "https://libgen.li",
        "https://libgen.la",
        "https://libgen.bz",
    ]
    RESOLVER_BASE = "https://libgen.li"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    async def search(
        self,
        query: str,
        per_page: int = 25,
        language: Optional[str] = None,
    ) -> Tuple[List[BookResult], int]:
        logger.info(f"LibGen search: query='{query}' per_page={per_page} lang={language}")

        for base_url in self.MIRRORS:
            try:
                results, total = await self._search_mirror(base_url, query, per_page, language)
                if results:
                    return results, total
            except Exception as e:
                logger.debug(f"LibGen mirror {base_url} failed: {e}")
                continue

        logger.info(f"LibGen search completed with 0 results for '{query}'")
        return [], 0

    async def _search_mirror(
        self,
        base_url: str,
        query: str,
        per_page: int,
        language: Optional[str] = None,
    ) -> Tuple[List[BookResult], int]:
        encoded_query = urllib.parse.quote_plus(query)
        url = f"{base_url}/index.php?req={encoded_query}&res={per_page}&column=def"

        timeout = aiohttp.ClientTimeout(total=8.0)
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": self.USER_AGENT}) as session:
            async with session.get(url, **proxy_kwargs(url)) as resp:
                if resp.status != 200:
                    return [], 0
                html = await resp.text()

        results = self._parse_results(html, base_url, language)
        logger.info(f"LibGen mirror {base_url}: {len(results)} results for '{query}'")
        return results, len(results)

    def _parse_results(self, html: str, base_url: str, language: Optional[str]) -> List[BookResult]:
        results: List[BookResult] = []
        soup = BeautifulSoup(html or "", "html.parser")

        for row in soup.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) < 8:
                continue
            md5_match = re.search(r"md5=([a-fA-F0-9]{32})", str(row))
            if not md5_match:
                continue
            md5 = md5_match.group(1)

            modern = row.find(
                "a",
                href=re.compile(r"(edition\.php|file\.php\?id=|ads\.php\?md5=)", re.IGNORECASE),
            )
            book = (
                self._parse_modern_row(cols, md5, base_url)
                if modern
                else self._parse_legacy_row(cols, md5, base_url)
            )

            if not book:
                continue
            if language and book.language and language.lower() not in book.language.lower():
                continue
            results.append(book)

        return results

    def _parse_modern_row(self, cols, md5: str, base_url: str) -> Optional[BookResult]:
        """Parse the libgen.li/.la table layout."""
        title_anchor = cols[0].find("a", href=re.compile(r"edition\.php", re.IGNORECASE)) or cols[0].find("a")
        title = title_anchor.get_text(" ", strip=True) if title_anchor else cols[0].get_text(" ", strip=True)
        if not title:
            return None

        year_text = cols[3].get_text(" ", strip=True)
        pages_text = cols[5].get_text(" ", strip=True)
        ext = cols[7].get_text(" ", strip=True).lower().lstrip(".")

        return BookResult(
            id=f"libgen_{md5}",
            title=title,
            author=cols[1].get_text(" ", strip=True) or None,
            publisher=cols[2].get_text(" ", strip=True) or None,
            publication_year=int(year_text) if year_text.isdigit() else None,
            pages=int(pages_text) if pages_text.isdigit() else None,
            language=cols[4].get_text(" ", strip=True) or None,
            file_size=_parse_size(cols[6].get_text(" ", strip=True)),
            download_url=f"{base_url}/ads.php?md5={md5}",
            extension=ext if ext in FILE_EXTENSIONS else "pdf",
            _source="libgen",
        )

    def _parse_legacy_row(self, cols, md5: str, base_url: str) -> Optional[BookResult]:
        """Parse the older libgen.is/.rs table layout."""
        if len(cols) < 9:
            return None

        title_anchor = cols[2].find("a")
        title = title_anchor.get_text(" ", strip=True) if title_anchor else cols[2].get_text(" ", strip=True)
        if not title:
            return None

        year_text = cols[4].get_text(" ", strip=True)
        pages_text = cols[5].get_text(" ", strip=True)
        ext = cols[8].get_text(" ", strip=True).lower().lstrip(".")

        return BookResult(
            id=f"libgen_{md5}",
            title=title,
            author=cols[1].get_text(" ", strip=True) or None,
            publisher=cols[3].get_text(" ", strip=True) or None,
            publication_year=int(year_text) if year_text.isdigit() else None,
            pages=int(pages_text) if pages_text.isdigit() else None,
            language=cols[6].get_text(" ", strip=True) or None,
            file_size=_parse_size(cols[7].get_text(" ", strip=True)),
            download_url=f"{self.RESOLVER_BASE}/ads.php?md5={md5}",
            extension=ext if ext in FILE_EXTENSIONS else "pdf",
            _source="libgen",
        )

    async def download(
        self,
        url: str,
        fmt: str = "epub",
        max_bytes: Optional[int] = None,
        timeout_seconds: int = 120,
    ) -> Optional[bytes]:
        """Resolve a LibGen page/ads URL and return the actual book file bytes."""
        max_bytes = max_bytes or settings.max_file_size
        timeout = aiohttp.ClientTimeout(
            total=timeout_seconds, connect=10, sock_read=min(60, timeout_seconds)
        )
        headers = {"User-Agent": self.USER_AGENT, "Accept": "*/*"}

        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                direct_url = await self._resolve_download_url(session, url)
                if not direct_url:
                    # A dead ads.php page on one mirror is common; retry the
                    # same md5 against the other frontends before giving up.
                    md5_match = re.search(r"([a-fA-F0-9]{32})", url or "")
                    if md5_match:
                        for base in self.MIRRORS:
                            if base in (url or ""):
                                continue
                            direct_url = await self._resolve_download_url(
                                session, f"{base}/ads.php?md5={md5_match.group(1)}"
                            )
                            if direct_url:
                                break
                if not direct_url:
                    logger.warning(f"LibGen could not resolve a direct link from {url}")
                    return None

                async with session.get(direct_url, allow_redirects=True, **proxy_kwargs(direct_url)) as resp:
                    if resp.status != 200:
                        logger.warning(f"LibGen download HTTP {resp.status} from {direct_url}")
                        return None
                    data = await resp.read()

            if not data:
                return None
            if len(data) > max_bytes:
                logger.warning(f"LibGen file too large ({len(data)} bytes > {max_bytes})")
                return None
            if not self._is_real_file(data, fmt):
                preview = data[:120].decode("utf-8", errors="replace")
                logger.warning(f"LibGen returned non-file content ({len(data)} bytes): {preview!r}")
                return None
            return data
        except asyncio.TimeoutError:
            logger.warning(f"LibGen download timed out for {url}")
            return None
        except Exception as e:
            logger.warning(f"LibGen download failed for {url}: {e}")
            return None

    async def _resolve_download_url(self, session: aiohttp.ClientSession, url: str) -> Optional[str]:
        url = (url or "").strip()
        if not url:
            return None

        # A direct get.php link already carrying the key can be used as-is.
        if "get.php" in url and "key=" in url:
            return url

        md5_match = re.search(r"([a-fA-F0-9]{32})", url)
        if "ads.php" in url:
            ads_url = url
        elif md5_match:
            host = (urllib.parse.urlparse(url).hostname or "").lower()
            base = f"https://{host}" if host and is_libgen_url(url) else self.RESOLVER_BASE
            ads_url = f"{base}/ads.php?md5={md5_match.group(1)}"
        elif url.lower().split("?")[0].endswith(tuple(f".{ext}" for ext in FILE_EXTENSIONS)):
            return url
        else:
            ads_url = url

        async with session.get(ads_url, **proxy_kwargs(ads_url)) as resp:
            if resp.status != 200:
                logger.debug(f"LibGen ads page HTTP {resp.status}: {ads_url}")
                return None
            page = await resp.text()

        match = re.search(r"href=[\"']([^\"']*get\.php\?[^\"']+)", page, re.IGNORECASE)
        if not match:
            logger.debug(f"LibGen ads page has no get.php link: {ads_url}")
            return None
        return urllib.parse.urljoin(ads_url, html_lib.unescape(match.group(1)))

    @staticmethod
    def _is_real_file(data: bytes, fmt: str) -> bool:
        if not data:
            return False
        prefix = data[:200].lstrip().lower()
        if prefix.startswith((b"<!doctype", b"<html")):
            return False
        magic = MAGIC.get((fmt or "").lower())
        if magic is None:
            return True
        if (fmt or "").lower() in ("mobi", "azw3"):
            return magic in data[:256]
        return data.startswith(magic)
