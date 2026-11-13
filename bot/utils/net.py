"""Outbound proxy helpers.

Vercel/AWS datacenter IPs are frequently blocked by Cloudflare-protected book
sources. Set ``HTTPS_PROXY`` (or ``HTTP_PROXY`` / ``ALL_PROXY``) in the
environment to route outbound requests through a proxy.

``httpx`` honours these variables automatically, but ``aiohttp`` only reads
``http_proxy``/``https_proxy`` (and ignores ``ALL_PROXY``). Callers therefore
pass ``proxy=get_proxy_for(url)`` explicitly. ``NO_PROXY`` is respected.
"""
from __future__ import annotations

import os
import urllib.parse
from typing import Optional


def _first_env(*names: str) -> Optional[str]:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


def _bypasses_proxy(host: str) -> bool:
    raw = _first_env("NO_PROXY", "no_proxy")
    if not raw:
        return False
    for entry in raw.split(","):
        entry = entry.strip().lower().lstrip(".")
        if not entry:
            continue
        if entry == "*" or host == entry or host.endswith("." + entry):
            return True
    return False


def get_proxy_for(url: str) -> Optional[str]:
    """Return the proxy URL configured for *url*, or ``None``.

    Scheme-specific variables win over the generic ``ALL_PROXY``. A host match
    in ``NO_PROXY`` disables proxying for that request.
    """
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host or _bypasses_proxy(host):
        return None
    if parsed.scheme.lower() == "https":
        return _first_env("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")
    return _first_env("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")


def proxy_kwargs(url: str) -> dict:
    """Return ``{"proxy": ...}`` suitable for ``aiohttp`` request calls."""
    proxy = get_proxy_for(url)
    return {"proxy": proxy} if proxy else {}
