"""bot/utils/epub_reader.py — EPUB chapter extractor using standard zipfile (feature #11)."""
from __future__ import annotations

import html
import io
import re
import zipfile
from typing import List, Optional, Tuple
from loguru import logger


def extract_chapters_from_epub(epub_bytes: bytes) -> List[Tuple[str, str]]:
    """Extract (chapter_title, text_content) pairs from an EPUB file.
    
    EPUB files are zip archives with XHTML files listed in the OPF spine.
    """
    chapters: List[Tuple[str, str]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(epub_bytes)) as z:
            html_files = [
                name for name in z.namelist()
                if name.lower().endswith((".xhtml", ".html", ".htm"))
                and not any(x in name.lower() for x in ["cover", "title", "nav", "toc"])
            ]

            # If filtered list is empty, take all html files
            if not html_files:
                html_files = [name for name in z.namelist() if name.lower().endswith((".xhtml", ".html", ".htm"))]

            for idx, filename in enumerate(html_files[:50], 1):
                raw = z.read(filename).decode("utf-8", errors="ignore")
                # Extract title from <h1>, <h2> or <title>
                title_match = re.search(r"<h[12][^>]*>(.*?)</h[12]>", raw, re.DOTALL | re.IGNORECASE)
                if not title_match:
                    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.DOTALL | re.IGNORECASE)
                raw_title = title_match.group(1) if title_match else f"Chapter {idx}"
                clean_title = re.sub(r"<[^>]+>", "", raw_title).strip() or f"Chapter {idx}"

                # Extract text content
                body_match = re.search(r"<body[^>]*>(.*?)</body>", raw, re.DOTALL | re.IGNORECASE)
                body_html = body_match.group(1) if body_match else raw

                # Replace <p> and <br> with newlines, strip other tags
                text = re.sub(r"<(p|br|div)[^>]*>", "\n", body_html, flags=re.IGNORECASE)
                text = re.sub(r"<[^>]+>", "", text)
                text = html.unescape(text)
                text = re.sub(r"\n{3,}", "\n\n", text).strip()

                if len(text) > 80:  # Skip empty or spacer pages
                    chapters.append((clean_title, text))

    except Exception as e:
        logger.error(f"Error parsing EPUB: {e}")

    return chapters


def paginate_text(text: str, max_chars: int = 3500) -> List[str]:
    """Split chapter text into readable Telegram message chunks."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    paragraphs = text.split("\n\n")
    current_chunk = []
    current_len = 0

    for p in paragraphs:
        if current_len + len(p) + 2 > max_chars:
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_len = 0
            if len(p) > max_chars:
                # Long paragraph: slice by character limit
                for i in range(0, len(p), max_chars):
                    chunks.append(p[i : i + max_chars])
                continue
        current_chunk.append(p)
        current_len += len(p) + 2

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks
