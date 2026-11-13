from __future__ import annotations

import fnmatch
import json
import time
from typing import Any, Dict, Optional, Tuple

import redis.asyncio as aioredis
from loguru import logger

from bot.config.settings import settings


class CacheService:
    def __init__(self) -> None:
        self._redis: Optional[aioredis.Redis] = None
        self._enabled = True
        self._mem_cache: Dict[str, Tuple[Any, float]] = {}

    def _cleanup_mem_cache(self, now: float) -> None:
        expired = [k for k, (_, exp) in self._mem_cache.items() if now > exp]
        for k in expired:
            self._mem_cache.pop(k, None)
        if len(self._mem_cache) > 2000:
            oldest = sorted(self._mem_cache.items(), key=lambda x: x[1][1])[:400]
            for k, _ in oldest:
                self._mem_cache.pop(k, None)

    async def initialize(self) -> None:
        try:
            self._redis = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            await self._redis.ping()
            logger.info("Redis cache connected successfully")
        except Exception as e:
            logger.warning(f"Redis connection failed, falling back to in-memory cache: {e}")
            self._enabled = True
            self._redis = None

    async def close(self) -> None:
        if self._redis:
            await self._redis.close()
            logger.info("Redis cache connection closed")
        self._mem_cache.clear()

    async def get(self, key: str) -> Optional[Any]:
        if not self._enabled:
            return None
        if self._redis:
            try:
                data = await self._redis.get(key)
                if data:
                    return json.loads(data)
                return None
            except Exception as e:
                logger.error(f"Cache get error for key {key}: {e}")
                return None
        else:
            now = time.monotonic()
            item = self._mem_cache.get(key)
            if item is None:
                return None
            val, exp = item
            if now > exp:
                self._mem_cache.pop(key, None)
                return None
            return val

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        if not self._enabled:
            return False
        if self._redis:
            try:
                data = json.dumps(value, default=str)
                await self._redis.setex(key, ttl or settings.redis_ttl, data)
                return True
            except Exception as e:
                logger.error(f"Cache set error for key {key}: {e}")
                return False
        else:
            now = time.monotonic()
            self._cleanup_mem_cache(now)
            expire_at = now + (ttl or settings.redis_ttl)
            self._mem_cache[key] = (value, expire_at)
            return True

    async def delete(self, key: str) -> bool:
        if not self._enabled:
            return False
        if self._redis:
            try:
                await self._redis.delete(key)
                return True
            except Exception as e:
                logger.error(f"Cache delete error for key {key}: {e}")
                return False
        else:
            return self._mem_cache.pop(key, None) is not None

    async def exists(self, key: str) -> bool:
        if not self._enabled:
            return False
        if self._redis:
            try:
                return await self._redis.exists(key) > 0
            except Exception as e:
                logger.error(f"Cache exists error for key {key}: {e}")
                return False
        else:
            now = time.monotonic()
            item = self._mem_cache.get(key)
            if item is None:
                return False
            val, exp = item
            if now > exp:
                self._mem_cache.pop(key, None)
                return False
            return True

    async def increment(self, key: str, amount: int = 1) -> Optional[int]:
        if not self._enabled:
            return None
        if self._redis:
            try:
                return await self._redis.incrby(key, amount)
            except Exception as e:
                logger.error(f"Cache increment error for key {key}: {e}")
                return None
        else:
            now = time.monotonic()
            item = self._mem_cache.get(key)
            current_val = 0
            exp = now + settings.redis_ttl
            if item is not None:
                val, old_exp = item
                if now <= old_exp and isinstance(val, int):
                    current_val = val
                    exp = old_exp
            new_val = current_val + amount
            self._mem_cache[key] = (new_val, exp)
            return new_val

    async def set_ttl(self, key: str, ttl: int) -> bool:
        if not self._enabled:
            return False
        if self._redis:
            try:
                await self._redis.expire(key, ttl)
                return True
            except Exception as e:
                logger.error(f"Cache set_ttl error for key {key}: {e}")
                return False
        else:
            now = time.monotonic()
            item = self._mem_cache.get(key)
            if item is None:
                return False
            val, exp = item
            if now > exp:
                self._mem_cache.pop(key, None)
                return False
            self._mem_cache[key] = (val, now + ttl)
            return True

    async def clear_pattern(self, pattern: str) -> int:
        if not self._enabled:
            return 0
        if self._redis:
            try:
                cursor = 0
                deleted = 0
                while True:
                    cursor, keys = await self._redis.scan(cursor=cursor, match=pattern, count=100)
                    if keys:
                        deleted += await self._redis.delete(*keys)
                    if cursor == 0:
                        break
                return deleted
            except Exception as e:
                logger.error(f"Cache clear_pattern error for {pattern}: {e}")
                return 0
        else:
            matching = [k for k in self._mem_cache.keys() if fnmatch.fnmatch(k, pattern)]
            for k in matching:
                self._mem_cache.pop(k, None)
            return len(matching)

    @property
    def is_enabled(self) -> bool:
        return self._enabled


cache = CacheService()
