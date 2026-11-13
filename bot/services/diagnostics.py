"""bot/services/diagnostics.py — Outbound source reachability probe.

Used by the protected ``/api/sources_check`` endpoint to explain, from the
runtime that actually serves the bot (Vercel/AWS or local), which book sources
are reachable and whether an outbound proxy is in effect.

The report never contains credentials, proxy URLs, or cookies.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, List

import aiohttp
from loguru import logger

from bot.config.settings import settings
from bot.utils.net import get_proxy_for, proxy_kwargs

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_TIMEOUT = aiohttp.ClientTimeout(total=8, connect=5, sock_read=6)


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        value = (item or "").strip().rstrip("/")
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


async def _fetch(
    session: aiohttp.ClientSession,
    url: str,
    method: str = "GET",
    expect: tuple = (),
    parse_json: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    started = time.monotonic()
    try:
        async with session.request(method, url, **proxy_kwargs(url), **kwargs) as resp:
            body = await resp.read()
            content_type = resp.headers.get("Content-Type", "")
        text = body[:300_000].decode("utf-8", errors="replace")
        lowered = text.lower()
        result: Dict[str, Any] = {
            "url": url,
            "status": resp.status,
            "bytes": len(body),
            "content_type": content_type.split(";")[0],
            "seconds": round(time.monotonic() - started, 2),
            "ok": resp.status < 400,
        }
        if parse_json:
            try:
                payload = json.loads(text)
                result["json"] = True
                result["json_keys"] = (
                    sorted(payload.keys())[:8] if isinstance(payload, dict) else []
                )
            except Exception:
                result["json"] = False
        if expect:
            result["matched"] = [token for token in expect if token.lower() in lowered]
        parked = [
            marker
            for marker in (
                "domain for sale",
                "buy this domain",
                "hugedomains",
                "afternic",
                "suspendedpage",
                "account suspended",
            )
            if marker in lowered
        ]
        if parked:
            result["parked"] = parked
        return result
    except Exception as e:
        return {
            "url": url,
            "status": None,
            "error": f"{type(e).__name__}: {str(e)[:160]}",
            "seconds": round(time.monotonic() - started, 2),
            "ok": False,
        }


async def _egress(session: aiohttp.ClientSession) -> Dict[str, Any]:
    """Report the outbound IP/ASN so datacenter blocks are obvious."""
    info: Dict[str, Any] = {}
    url = "https://ipinfo.io/json"
    try:
        async with session.get(url, **proxy_kwargs(url)) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                info = {
                    "ip": data.get("ip"),
                    "org": data.get("org"),
                    "country": data.get("country"),
                }
    except Exception as e:
        logger.debug(f"ipinfo lookup failed: {e}")

    if not info.get("ip"):
        try:
            async with session.get(
                "https://api.ipify.org?format=json", **proxy_kwargs("https://api.ipify.org")
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    info = {"ip": data.get("ip")}
        except Exception as e:
            logger.debug(f"ipify lookup failed: {e}")

    return info


async def _probe_zl(session: aiohttp.ClientSession, base: str) -> Dict[str, Any]:
    home = await _fetch(session, f"{base}/")

    cookies = {}
    if settings.zlibrary_remix_userkey and settings.zlibrary_remix_userid:
        cookies = {
            "remix_userkey": settings.zlibrary_remix_userkey,
            "remix_userid": settings.zlibrary_remix_userid,
        }

    search = await _fetch(
        session,
        f"{base}/eapi/book/search",
        method="POST",
        data={"message": "test", "page": "1", "limit": "3"},
        cookies=cookies,
        parse_json=True,
    )
    usable = bool(
        search.get("ok")
        and search.get("json")
        and ({"books", "success"} & set(search.get("json_keys") or []))
    )
    return {"base": base, "usable": usable, "home": home, "search": search}


async def _probe_aa(session: aiohttp.ClientSession, base: str) -> Dict[str, Any]:
    home = await _fetch(session, f"{base}/")
    search = await _fetch(session, f"{base}/search?q=test", expect=("/md5/",))
    api = await _fetch(session, f"{base}/api/search?q=test", parse_json=True)
    usable = bool(
        search.get("ok")
        and search.get("matched")
        and not search.get("parked")
    )
    return {"base": base, "usable": usable, "home": home, "search": search, "api": api}


async def _probe_libgen() -> Dict[str, Any]:
    started = time.monotonic()
    try:
        from bot.sources.libgen import LibGenSource

        results, total = await asyncio.wait_for(
            LibGenSource().search("test", per_page=3), timeout=12
        )
        return {
            "ok": bool(results),
            "results": len(results),
            "total": total,
            "seconds": round(time.monotonic() - started, 2),
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:160]}",
            "seconds": round(time.monotonic() - started, 2),
        }


async def _probe_openlibrary() -> Dict[str, Any]:
    started = time.monotonic()
    try:
        from bot.sources.openlibrary import OpenLibrarySource

        results, total = await asyncio.wait_for(
            OpenLibrarySource().search("test", per_page=3), timeout=12
        )
        return {
            "ok": bool(results),
            "results": len(results),
            "total": total,
            "seconds": round(time.monotonic() - started, 2),
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:160]}",
            "seconds": round(time.monotonic() - started, 2),
        }


def _config_summary() -> Dict[str, Any]:
    return {
        "deployment": "vercel" if settings.is_vercel else "local",
        "commit": (os.getenv("VERCEL_GIT_COMMIT_SHA") or "local")[:7],
        "database": (
            "postgresql"
            if settings.database_url
            else ("sqlite (/tmp)" if settings.is_vercel else "sqlite")
        ),
        "database_url_set": bool(settings.database_url),
        "zlibrary_base": settings.api_base_url or None,
        "zlibrary_mirrors": settings.mirrors,
        "zlibrary_email_set": bool(settings.zlibrary_email),
        "zlibrary_password_set": bool(settings.zlibrary_password),
        "zlibrary_remix_tokens_set": bool(
            settings.zlibrary_remix_userkey and settings.zlibrary_remix_userid
        ),
        "annas_archive_base": settings.annas_archive_base_url or None,
        "annas_archive_secret_set": bool(settings.annas_archive_secret_key),
        "proxy_configured": bool(get_proxy_for("https://example.com")),
        "no_proxy_set": bool(os.getenv("NO_PROXY") or os.getenv("no_proxy")),
    }


async def check_sources() -> Dict[str, Any]:
    """Probe every configured source from the current runtime."""
    aa_bases = _dedupe(
        [
            settings.annas_archive_base_url,
            "https://annas-archive.gs",
            "https://annas-archive.pk",
            "https://annas-archive.org",
            "https://annas-archive.se",
            "https://annas-archive.li",
        ]
    )
    zl_bases = _dedupe(
        [settings.api_base_url, *settings.mirrors, "https://z-library.sk", "https://z-lib.gl"]
    )

    async with aiohttp.ClientSession(
        timeout=_TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as session:
        tasks = [
            _egress(session),
            *[_probe_aa(session, base) for base in aa_bases],
            *[_probe_zl(session, base) for base in zl_bases],
            _probe_libgen(),
            _probe_openlibrary(),
        ]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    def _safe(value: Any) -> Any:
        if isinstance(value, Exception):
            return {"ok": False, "error": f"{type(value).__name__}: {str(value)[:160]}"}
        return value

    egress = _safe(outcomes[0])
    aa_count = len(aa_bases)
    aa = [_safe(item) for item in outcomes[1 : 1 + aa_count]]
    zl = [_safe(item) for item in outcomes[1 + aa_count : 1 + aa_count + len(zl_bases)]]
    libgen = _safe(outcomes[-2])
    openlibrary = _safe(outcomes[-1])

    working = []
    if libgen.get("ok"):
        working.append("libgen")
    if openlibrary.get("ok"):
        working.append("openlibrary")
    for entry in aa:
        if entry.get("usable"):
            working.append(f"annas_archive:{entry['base']}")
    for entry in zl:
        if entry.get("usable"):
            working.append(f"z-lib:{entry['base']}")

    return {
        "config": _config_summary(),
        "egress": egress,
        "working_sources": working,
        "libgen": libgen,
        "openlibrary": openlibrary,
        "annas_archive": aa,
        "z_library": zl,
    }
