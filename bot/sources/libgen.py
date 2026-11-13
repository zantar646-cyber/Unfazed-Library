"""bot/sources/libgen.py — Library Genesis (LibGen) source (feature #12)."""
from __future__ import annotations

import asyncio
import re
import urllib.parse
from typing import List, Optional, Tuple
import aiohttp
from loguru import logger

from bot.services.api import BookResult
from bot.utils.net import proxy_kwargs


class LibGenSource:
    """LibGen search provider with resilient mirror fallback and HTML table parsing."""

    MIRRORS = [
        "https://libgen.is",
        "https://libgen.rs",
        "https://libgen.st",
    ]

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
        url = f"{base_url}/search.php?req={encoded_query}&res={per_page}&column=def"

        timeout = aiohttp.ClientTimeout(total=6.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }
            async with session.get(url, headers=headers, **proxy_kwargs(url)) as resp:
                if resp.status != 200:
                    return [], 0
                html = await resp.text()

        # Parse table rows: LibGen results table has class or standard <tr> structures
        # Look for table with headers: ID, Author(s), Title, Publisher, Year, Pages, Language, Size, Extension, Mirrors
        results: List[BookResult] = []
        rows = re.findall(r"<tr valign=top bgcolor=#[A-Fa-f0-9]+>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE)

        for row in rows:
            cols = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL | re.IGNORECASE)
            if len(cols) < 9:
                continue

            # cols[0]: ID
            raw_id = re.sub(r"<[^>]+>", "", cols[0]).strip()
            # cols[1]: Author(s)
            author = re.sub(r"<[^>]+>", "", cols[1]).strip()
            # cols[2]: Title (contains <a>)
            title_match = re.search(r"<a[^>]+>(.*?)</a>", cols[2], re.DOTALL | re.IGNORECASE)
            title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else re.sub(r"<[^>]+>", "", cols[2]).strip()
            # cols[3]: Publisher
            publisher = re.sub(r"<[^>]+>", "", cols[3]).strip() or None
            # cols[4]: Year
            year_str = re.sub(r"<[^>]+>", "", cols[4]).strip()
            year = int(year_str) if year_str.isdigit() else None
            # cols[5]: Pages
            pages_str = re.sub(r"<[^>]+>", "", cols[5]).strip()
            pages = int(pages_str) if pages_str.isdigit() else None
            # cols[6]: Language
            book_lang = re.sub(r"<[^>]+>", "", cols[6]).strip() or None
            # cols[7]: Size (e.g. "2 Mb")
            size_str = re.sub(r"<[^>]+>", "", cols[7]).strip()
            # cols[8]: Extension
            ext = re.sub(r"<[^>]+>", "", cols[8]).strip().lower()

            if language and book_lang and language.lower() not in book_lang.lower():
                continue

            # Mirror links are in cols[9] or later
            md5_match = re.search(r"md5=([a-fA-F0-9]{32})", row)
            md5 = md5_match.group(1) if md5_match else None
            download_url = f"https://library.lol/main/{md5}" if md5 else None

            # Parse size in bytes approximately
            size_bytes = 0
            if "mb" in size_str.lower():
                val = re.search(r"([\d\.]+)", size_str)
                if val:
                    size_bytes = int(float(val.group(1)) * 1024 * 1024)
            elif "kb" in size_str.lower():
                val = re.search(r"([\d\.]+)", size_str)
                if val:
                    size_bytes = int(float(val.group(1)) * 1024)

            book = BookResult(
                id=f"libgen_{raw_id or md5 or hash(title)}",
                title=title or "Unknown",
                author=author or None,
                publisher=publisher,
                publication_year=year,
                pages=pages,
                language=book_lang,
                file_size=size_bytes if size_bytes > 0 else None,
                download_url=download_url,
                extension=ext or "pdf",
                _source="libgen",
            )
            results.append(book)

        return results, len(results)
