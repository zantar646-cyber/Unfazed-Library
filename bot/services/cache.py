from __future__ import annotations

import json
import pickle
from typing import Any, Optional

import redis.asyncio as aioredis
from loguru import logger

from bot.config.settings import settings


class CacheService:
    def __init__(self) -> None:
        self._redis: Optional[aioredis.Redis] = None
        self._enabled = True

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
            logger.warning(f"Redis connection failed, cache disabled: {e}")
            self._enabled = False
            self._redis = None

    async def close(self) -> None:
        if self._redis:
            await self._redis.close()
            logger.info("Redis cache connection closed")

    async def get(self, key: str) -> Optional[Any]:
        if not self._enabled or not self._redis:
            return None
        try:
            data = await self._redis.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Cache get error for key {key}: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        if not self._enabled or not self._redis:
            return False
        try:
            data = json.dumps(value, default=str)
            await self._redis.setex(key, ttl or settings.redis_ttl, data)
            return True
        except Exception as e:
            logger.error(f"Cache set error for key {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        if not self._enabled or not self._redis:
            return False
        try:
            await self._redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache delete error for key {key}: {e}")
            return False

    async def exists(self, key: str) -> bool:
        if not self._enabled or not self._redis:
            return False
        try:
            return await self._redis.exists(key) > 0
        except Exception as e:
            logger.error(f"Cache exists error for key {key}: {e}")
            return False

    async def increment(self, key: str, amount: int = 1) -> Optional[int]:
        if not self._enabled or not self._redis:
            return None
        try:
            return await self._redis.incrby(key, amount)
        except Exception as e:
            logger.error(f"Cache increment error for key {key}: {e}")
            return None

    async def set_ttl(self, key: str, ttl: int) -> bool:
        if not self._enabled or not self._redis:
            return False
        try:
            await self._redis.expire(key, ttl)
            return True
        except Exception as e:
            logger.error(f"Cache set_ttl error for key {key}: {e}")
            return False

    async def clear_pattern(self, pattern: str) -> int:
        if not self._enabled or not self._redis:
            return 0
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

    @property
    def is_enabled(self) -> bool:
        return self._enabled


cache = CacheService()
