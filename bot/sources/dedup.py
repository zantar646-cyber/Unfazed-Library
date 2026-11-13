from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Set, Tuple

from loguru import logger

from bot.services.api import BookResult

FILE_EXT_PATTERN = re.compile(
    r'\.(pdf|epub|mobi|azw3|fb2|djvu|txt|cbz|cbr|doc|docx|rtf|zip|rar)$',
    re.IGNORECASE,
)

EDITION_PATTERNS = [
    re.compile(r'\(?\d{4}\)?'),  # (2016) or 2016
    re.compile(r'\b(?:revised|updated|expanded|anniversary|collectors?|special|limited|hardcover|paperback|audible|audio)\s+edition\b', re.IGNORECASE),
    re.compile(r'\b\d+(?:st|nd|rd|th)\s+edition\b', re.IGNORECASE),
    re.compile(r'\b(?:volume|vol)\s*\.?\s*\d+\b', re.IGNORECASE),
    re.compile(r'\b\d+th\s+printing\b', re.IGNORECASE),
    re.compile(r'\b\d+th\s+impression\b', re.IGNORECASE),
]

FORMAT_PRIORITY = {
    "pdf": 0,
    "epub": 1,
    "mobi": 2,
    "azw3": 3,
    "fb2": 4,
    "djvu": 5,
    "txt": 6,
    "cbz": 7,
    "cbr": 8,
}

# Stop words that contribute negligible weight in relevance scoring
STOP_WORDS: Set[str] = {
    "the", "of", "for", "a", "an", "to", "and", "in", "is", "it",
    "on", "at", "by", "with", "or", "be", "as", "from", "that",
    "this", "are", "was", "were", "been", "its", "not", "but",
    "what", "which", "who", "whom", "when", "where", "why", "how",
    "all", "each", "every", "some", "any", "no", "nor", "if",
    "so", "than", "too", "very", "just", "also", "about", "up",
    "out", "off", "over", "into", "through", "during", "before",
    "after", "above", "below", "between", "under", "again",
    "further", "then", "once", "here", "there", "both", "few",
    "more", "most", "other", "such", "own", "do", "does", "did",
    "has", "have", "had", "can", "will", "would", "could", "should",
    "may", "might", "shall", "need", "done", "being", "having",
    "get", "got", "make", "made", "take", "took", "come", "came",
    "see", "saw", "know", "new", "one", "two", "like", "well",
}


def normalize_text(text: str) -> str:
    """Normalize text for comparison: lowercase, strip diacritics, remove punctuation."""
    if not text:
        return ""
    s = text.lower().strip()
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", errors="ignore").decode("ascii")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_title(title: str) -> str:
    """Normalize a book title: same as normalize_text but also strips file extensions and edition markers."""
    if not title:
        return ""
    s = title.lower().strip()
    s = FILE_EXT_PATTERN.sub("", s)
    for pat in EDITION_PATTERNS:
        s = pat.sub("", s)
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", errors="ignore").decode("ascii")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def fuzzy_similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _select_best_from_group(group: List[BookResult]) -> BookResult:
    def score(r: BookResult) -> Tuple:
        ext = (r.extension or "").lower().lstrip(".")
        fmt_priority = FORMAT_PRIORITY.get(ext, 99)
        size = r.file_size or 0
        meta = sum([
            1 if r.author else 0,
            1 if r.description else 0,
            1 if r.publication_year else 0,
            1 if r.isbn else 0,
            1 if r.publisher else 0,
            1 if r.pages else 0,
            1 if r.cover_url else 0,
        ])
        return (fmt_priority, -size, -meta)

    return min(group, key=score)


def deduplicate_results(results: List[BookResult]) -> List[BookResult]:
    if not results:
        return []

    # Fast O(N) grouping by exact normalized title (handles 80-90% of duplicates instantly)
    exact_dict: Dict[str, List[BookResult]] = {}
    for r in results:
        norm = normalize_title(r.title or "")
        if not norm:
            continue
        if norm in exact_dict:
            exact_dict[norm].append(r)
        else:
            exact_dict[norm] = [r]

    # Merge fuzzy-similar groups with pre-filtering to avoid O(N^2) SequenceMatcher calls
    merged_groups: List[Tuple[str, List[BookResult]]] = []
    for norm, group in exact_dict.items():
        len_norm = len(norm)
        merged = False
        for i, (mg_norm, mg_group) in enumerate(merged_groups):
            len_mg = len(mg_norm)
            # Length filter: ratio >= 0.9 is mathematically impossible if length diff > 12%
            if abs(len_norm - len_mg) > max(2, int(0.12 * max(len_norm, len_mg))):
                continue
            # Prefix filter: skip if starting character differs
            if norm[0] != mg_norm[0]:
                continue
            # Distinct number filter: don't merge different volumes / numbered editions
            digits_norm = re.findall(r'\d+', norm)
            digits_mg = re.findall(r'\d+', mg_norm)
            if digits_norm != digits_mg:
                continue
            matcher = SequenceMatcher(None, norm, mg_norm)
            if matcher.quick_ratio() >= 0.9 and matcher.ratio() >= 0.9:
                mg_group.extend(group)
                merged = True
                break
        if not merged:
            merged_groups.append((norm, group))

    deduped: List[BookResult] = []
    for _, group in merged_groups:
        best = _select_best_from_group(group)
        formats: Set[str] = set()
        sources: Set[str] = set()
        for r in group:
            if r.extension:
                formats.add(r.extension.lower().lstrip("."))
            src = getattr(r, "_source", None)
            if src:
                sources.add(src)
        best.formats = formats
        best.sources = sources
        deduped.append(best)

    return deduped


def parse_query(query: str) -> Tuple[List[str], List[str], bool]:
    """Parse a search query into tokens and phrases.

    Returns (tokens, phrases, has_phrases).
    Tokens are individual search terms with stop words removed and normalized.
    Phrases are quoted substrings extracted from the query.
    has_phrases indicates if any quoted phrases were found.
    """
    query = query.strip()
    if not query:
        return [], [], False

    phrases = re.findall(r'"([^"]+)"', query)
    has_phrases = bool(phrases)

    non_phrase = re.sub(r'"[^"]+"', "", query).strip()
    raw_tokens = non_phrase.split()

    tokens = []
    for t in raw_tokens:
        norm = normalize_text(t)
        for subtoken in norm.split():
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
    """Compute a relevance score for a book title against a search query.

    Scoring tiers (higher is better):
      1. Exact title match (normalized)                    -> 100_000
      2. Title starts with the query                       -> 50_000
      3. Exact phrase appears in title                     -> 30_000
      4. All non-stop tokens appear in title               -> 10_000
      5. IDF-weighted individual token matches             ->    100 per token
      6. Partial / substring token matches                 ->     50 per token
      7. Fuzzy similarity bonus against non-stopped query  ->      0-5000

    The score is designed so that no amount of lower-tier matches can
    outrank a single higher-tier match.
    """
    title_raw = (title or "").strip()
    title_norm = normalize_text(title_raw)
    query_norm = normalize_text(query)

    if not title_norm:
        return 0.0

    score = 0.0

    # Tier 1: Exact normalized title match
    if title_norm == query_norm:
        return 100_000.0 + 0.01  # tiny edge for consistent ordering

    # Tier 2: Title starts with the query
    if title_norm.startswith(query_norm):
        score += 50_000.0

    # Tier 3: Any quoted phrase appears in the title
    for phrase in phrases:
        if phrase in title_norm:
            score += 30_000.0
            break
    else:
        # Even without quotes, the full query as a contiguous string is valuable
        if query_norm in title_norm:
            score += 10_000.0

    title_tokens = set(title_norm.split())

    # Tier 4: All query tokens present in title
    if tokens:
        tokens_in_title = [t for t in tokens if t in title_tokens]
        if len(tokens_in_title) == len(tokens):
            score += 10_000.0

    # Tier 5: IDF-weighted individual token matches
    for t in tokens:
        if t in title_tokens:
            score += 100.0

    # Tier 6: Partial / substring token matches
    for t in tokens:
        if t not in title_tokens:
            for wt in title_tokens:
                if t in wt or wt in t:
                    score += 50.0
                    break

    # Tier 7: Fuzzy similarity bonus — only when needed (few direct matches)
    if score < 5_000.0:
        len_q = len(query_norm)
        len_t = len(title_norm)
        if abs(len_q - len_t) <= max(3, int(0.35 * max(len_q, len_t))):
            matcher = SequenceMatcher(None, query_norm, title_norm)
            if matcher.quick_ratio() >= 0.7:
                sim = matcher.ratio()
                if sim >= 0.7:
                    score += sim * 5_000.0

    return score


def rank_results(results: List[BookResult], query: str) -> List[BookResult]:
    """Rank results by relevance to the query using a multi-tier scoring system.

    The ranking prioritises:
      1. Exact title match
      2. Title starts with query
      3. Complete phrase in title
      4. All query words present
      5. Individual word matches (weighted by rarity via proxy)
      6. Partial matches
      7. Fuzzy similarity (only when few direct matches exist)

    Stop words are ignored in token-level scoring.
    """
    tokens, phrases, has_phrases = parse_query(query)

    def key_fn(r: BookResult) -> Tuple:
        title = r.title or ""
        s = compute_relevance_score(title, query, tokens, phrases, has_phrases)
        title_lower = title.lower().strip()
        # Secondary sort: higher score first, then alphabetical for ties
        return (-s, title_lower)

    return sorted(results, key=key_fn)
