"""bot/sources/openlibrary.py — Open Library source (feature #12)."""
from __future__ import annotations

import asyncio
from typing import List, Optional, Tuple
import aiohttp
from loguru import logger

from bot.services.api import BookResult
from bot.utils.net import proxy_kwargs


class OpenLibrarySource:
    """Free public catalog via Open Library JSON API."""

    BASE_URL = "https://openlibrary.org/search.json"

    async def search(
        self,
        query: str,
        per_page: int = 20,
        language: Optional[str] = None,
    ) -> Tuple[List[BookResult], int]:
        logger.info(f"OpenLibrary search: query='{query}' per_page={per_page} lang={language}")
        params = {
            "q": query,
            "limit": str(per_page),
            "fields": "key,title,author_name,first_publish_year,isbn,number_of_pages_median,language,publisher,cover_i",
        }

        try:
            timeout = aiohttp.ClientTimeout(total=8.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    self.BASE_URL, params=params, **proxy_kwargs(self.BASE_URL)
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"OpenLibrary returned HTTP {resp.status}")
                        return [], 0
                    data = await resp.json(content_type=None)

            docs = data.get("docs", [])
            total_found = data.get("numFound", len(docs))
            results: List[BookResult] = []

            for doc in docs:
                title = doc.get("title")
                if not title:
                    continue

                key = doc.get("key", "")
                authors = doc.get("author_name") or []
                author = ", ".join(authors[:3]) if authors else None
                year = doc.get("first_publish_year")
                publishers = doc.get("publisher") or []
                publisher = publishers[0] if publishers else None
                isbns = doc.get("isbn") or []
                isbn = isbns[0] if isbns else None
                pages = doc.get("number_of_pages_median")
                cover_i = doc.get("cover_i")
                cover_url = f"https://covers.openlibrary.org/b/id/{cover_i}-M.jpg" if cover_i else None
                read_url = f"https://openlibrary.org{key}" if key else None

                doc_langs = doc.get("language") or []
                book_lang = doc_langs[0] if doc_langs else None
                if language and doc_langs:
                    lang_lower = language.lower()
                    if not any(lang_lower in str(l).lower() for l in doc_langs):
                        continue

                book_id = f"ol_{key.replace('/works/', '').replace('/', '_')}" if key else f"ol_{hash(title)}"
                book = BookResult(
                    id=book_id,
                    title=title,
                    author=author,
                    publisher=publisher,
                    publication_year=int(year) if year else None,
                    isbn=isbn,
                    pages=int(pages) if pages else None,
                    language=book_lang,
                    cover_url=cover_url,
                    read_online_url=read_url,
                    download_url=None,
                    extension="pdf",
                    _source="openlibrary",
                )
                results.append(book)

            logger.info(f"OpenLibrary found {len(results)} books for '{query}' (total={total_found})")
            return results, total_found

        except asyncio.TimeoutError:
            logger.warning(f"OpenLibrary search timed out for '{query}'")
            return [], 0
        except Exception as e:
            logger.warning(f"OpenLibrary search error for '{query}': {e}")
            return [], 0
