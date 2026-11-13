from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import aiohttp
from loguru import logger

from bot.config.settings import settings
from bot.utils.net import proxy_kwargs


@dataclass
class MirrorCapabilities:
    search: bool = False
    categories: bool = False
    downloads: bool = False
    book_details: bool = False


@dataclass
class MirrorEntry:
    url: str
    healthy: bool = False
    capabilities: MirrorCapabilities = field(default_factory=MirrorCapabilities)
    last_checked: float = 0.0
    consecutive_failures: int = 0
    total_failures: int = 0


class NoHealthyMirrorError(Exception):
    pass


class MirrorManager:
    FAILURE_THRESHOLD: int = 3

    def __init__(
        self,
        primary_url: str,
        additional_urls: Optional[List[str]] = None,
        remix_userkey: str = "",
        remix_userid: str = "",
    ) -> None:
        self._session: Optional[aiohttp.ClientSession] = None
        self._remix_userkey = remix_userkey
        self._remix_userid = remix_userid
        self._lock = asyncio.Lock()
        self._active_index: int = 0
        self._mirrors: List[MirrorEntry] = []

        seen: set = set()
        all_urls = [primary_url] + (additional_urls or [])
        for url in all_urls:
            url = url.rstrip("/")
            if url and url not in seen:
                seen.add(url)
                self._mirrors.append(MirrorEntry(url=url))

    async def initialize(self) -> None:
        self._session = aiohttp.ClientSession(
            headers={
                "Accept": "application/json",
                "User-Agent": "DigitalLibraryBot/1.0 (MirrorManager)",
            },
            timeout=aiohttp.ClientTimeout(total=15, connect=5, sock_read=10),
            connector=aiohttp.TCPConnector(limit=10, ttl_dns_cache=300),
        )

        logger.info(f"Running health checks on {len(self._mirrors)} mirror(s)...")

        for mirror in self._mirrors:
            caps = await self._check_mirror(mirror.url)
            mirror.capabilities = caps
            mirror.healthy = caps.search
            mirror.last_checked = time.time()
            status = "HEALTHY" if mirror.healthy else "UNHEALTHY"
            logger.info(
                f"  Mirror {mirror.url}: {status} "
                f"(search={caps.search}, categories={caps.categories}, "
                f"downloads={caps.downloads}, book_details={caps.book_details})"
            )

        healthy = [m for m in self._mirrors if m.healthy]
        if not healthy:
            logger.warning("No healthy mirrors found! Bot may not function correctly.")

        self._mirrors.sort(
            key=lambda m: (
                not m.healthy,
                -(m.capabilities.search + m.capabilities.categories + m.capabilities.downloads),
            )
        )

        active = self._mirrors[0]
        logger.info(f"Active mirror: {active.url} (healthy={active.healthy})")

    async def close(self) -> None:
        if self._session:
            await self._session.close()

    async def get_active_base_url(self) -> str:
        async with self._lock:
            mirror = self._mirrors[self._active_index]
            if not mirror.healthy:
                await self._switch_mirror()
            return self._mirrors[self._active_index].url

    async def record_failure(self, url: str) -> None:
        async with self._lock:
            for i, m in enumerate(self._mirrors):
                if m.url == url:
                    m.consecutive_failures += 1
                    m.total_failures += 1
                    logger.warning(
                        f"Mirror {url}: consecutive_failures={m.consecutive_failures}/{self.FAILURE_THRESHOLD}"
                    )
                    if m.consecutive_failures >= self.FAILURE_THRESHOLD:
                        m.healthy = False
                        if i == self._active_index:
                            await self._switch_mirror()
                    return

    async def record_success(self, url: str) -> None:
        async with self._lock:
            for m in self._mirrors:
                if m.url == url:
                    m.consecutive_failures = 0
                    return

    @property
    def active_mirror(self) -> str:
        return self._mirrors[self._active_index].url if self._mirrors else ""

    @property
    def active_capabilities(self) -> MirrorCapabilities:
        return self._mirrors[self._active_index].capabilities if self._mirrors else MirrorCapabilities()

    async def get_status(self) -> Dict:
        async with self._lock:
            mirrors_info = []
            for i, m in enumerate(self._mirrors):
                mirrors_info.append({
                    "url": m.url,
                    "active": i == self._active_index,
                    "healthy": m.healthy,
                    "capabilities": {
                        "search": m.capabilities.search,
                        "categories": m.capabilities.categories,
                        "downloads": m.capabilities.downloads,
                        "book_details": m.capabilities.book_details,
                    },
                    "consecutive_failures": m.consecutive_failures,
                    "total_failures": m.total_failures,
                    "last_checked": m.last_checked,
                })
            return {
                "active_mirror": self._mirrors[self._active_index].url if self._mirrors else "",
                "total_mirrors": len(self._mirrors),
                "healthy_count": sum(1 for m in self._mirrors if m.healthy),
                "mirrors": mirrors_info,
            }

    async def check_all_mirrors(self) -> None:
        async with self._lock:
            logger.info(f"Re-checking {len(self._mirrors)} mirror(s)...")
            for mirror in self._mirrors:
                caps = await self._check_mirror(mirror.url)
                mirror.capabilities = caps
                was_healthy = mirror.healthy
                mirror.healthy = caps.search
                mirror.last_checked = time.time()
                if mirror.healthy != was_healthy:
                    logger.info(f"  Mirror {mirror.url}: {'HEALTHY' if mirror.healthy else 'UNHEALTHY'}")
            self._mirrors.sort(
                key=lambda m: (
                    not m.healthy,
                    -(m.capabilities.search + m.capabilities.categories + m.capabilities.downloads),
                )
            )
            healthy = [m for m in self._mirrors if m.healthy]
            if not healthy:
                logger.warning("No healthy mirrors found after re-check!")
            elif not self._mirrors[self._active_index].healthy:
                old = self._mirrors[self._active_index].url
                await self._switch_mirror()
                logger.info(f"Switched active mirror from {old} to {self._mirrors[self._active_index].url}")

    async def _switch_mirror(self) -> None:
        n = len(self._mirrors)
        for offset in range(1, n + 1):
            idx = (self._active_index + offset) % n
            if self._mirrors[idx].healthy:
                old = self._mirrors[self._active_index].url
                new = self._mirrors[idx].url
                logger.warning(f"Switching mirror: {old} -> {new}")
                self._active_index = idx
                return
        raise NoHealthyMirrorError("No healthy mirrors available to switch to")

    async def _check_mirror(self, url: str) -> MirrorCapabilities:
        caps = MirrorCapabilities()
        cookies = {}
        if self._remix_userkey and self._remix_userid:
            cookies = {"remix_userkey": self._remix_userkey, "remix_userid": self._remix_userid}

        caps.search = await self._check_search(url, cookies)
        if caps.search:
            caps.book_details = await self._check_book_details(url, cookies)
            caps.downloads = await self._check_download(url, cookies)
        return caps

    async def _check_search(self, url: str, cookies: Dict) -> bool:
        try:
            async with self._session.post(
                f"{url}/eapi/book/search",
                data={"message": "test", "page": "1", "limit": "3"},
                cookies=cookies,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=10),
                **proxy_kwargs(url),
            ) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                books = data.get("books", [])
                return len(books) > 0 and data.get("success") == 1
        except Exception as e:
            logger.debug(f"  Search check failed for {url}: {e}")
            return False

    async def _check_book_details(self, url: str, cookies: Dict) -> bool:
        try:
            async with self._session.get(
                f"{url}/eapi/book/search",
                params={"message": "test", "page": "1", "limit": "1"},
                cookies=cookies,
                timeout=aiohttp.ClientTimeout(total=10),
                **proxy_kwargs(url),
            ) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def _check_download(self, url: str, cookies: Dict) -> bool:
        try:
            async with self._session.post(
                f"{url}/eapi/book/search",
                data={"message": "test", "page": "1", "limit": "1"},
                cookies=cookies,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=10),
                **proxy_kwargs(url),
            ) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                books = data.get("books", [])
                if not books:
                    return False
                dl = books[0].get("dl") or books[0].get("download_url")
                if not dl:
                    return False
                dl_url = f"{url}{dl}" if str(dl).startswith("/") else dl
                async with self._session.get(
                    dl_url,
                    cookies=cookies,
                    timeout=aiohttp.ClientTimeout(total=10),
                    allow_redirects=False,
                    **proxy_kwargs(dl_url),
                ) as dl_resp:
                    if dl_resp.status == 503:
                        body = await dl_resp.read()
                        decoded = body[:500].decode("utf-8", errors="replace").lower()
                        if "checking your browser" in decoded or "cloudflare" in decoded:
                            return False
                    if dl_resp.status == 200:
                        body = await dl_resp.read()
                        decoded = body[:200].decode("utf-8", errors="replace").lower()
                        if "<!doctype html" not in decoded and not decoded.startswith("{"):
                            return True
                    return False
        except Exception:
            return False
