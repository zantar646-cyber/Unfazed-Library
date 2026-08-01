from __future__ import annotations

import time
import uuid
from typing import Optional

from loguru import logger

CONVERT_KEYS: dict[str, dict] = {}
CONVERT_KEY_TTL = 3600


def create_convert_key(file_id: str, file_format: str) -> str:
    key = uuid.uuid4().hex[:16]
    CONVERT_KEYS[key] = {
        "file_id": file_id,
        "file_format": file_format,
        "created_at": time.time(),
    }
    logger.debug(f"Created convert key {key} for file_id={file_id} format={file_format}")
    return key


def resolve_convert_key(key: str) -> Optional[dict]:
    entry = CONVERT_KEYS.get(key)
    if not entry:
        return None
    if time.time() - entry["created_at"] > CONVERT_KEY_TTL:
        del CONVERT_KEYS[key]
        return None
    return {"file_id": entry["file_id"], "file_format": entry["file_format"]}


def cleanup_expired_convert_keys() -> int:
    now = time.time()
    expired = [k for k, v in CONVERT_KEYS.items() if now - v["created_at"] > CONVERT_KEY_TTL]
    for k in expired:
        del CONVERT_KEYS[k]
    if expired:
        logger.debug(f"Cleaned up {len(expired)} expired convert keys")
    return len(expired)
