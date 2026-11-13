from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Optional

from loguru import logger

from bot.config.settings import settings

# Serverless platforms (Vercel) only allow writes under /tmp.
CONVERTER_CACHE_DIR = (
    Path("/tmp") / "converter_cache"
    if settings.is_vercel
    else Path(__file__).resolve().parent.parent.parent / "converter_cache"
)
CONVERTER_FILE_TTL = 3600  # 1 hour


def _ensure_dir() -> None:
    CONVERTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def save_converter_file(file_bytes: bytes, filename: str) -> tuple[str, str]:
    _ensure_dir()
    token = uuid.uuid4().hex[:16]
    file_dir = CONVERTER_CACHE_DIR / token
    file_dir.mkdir(parents=True, exist_ok=True)
    file_path = file_dir / filename
    file_path.write_bytes(file_bytes)
    logger.debug(f"Saved converter file: {file_path} (token={token})")
    return token, str(file_path)


def get_converter_file_path(token: str, filename: str) -> Optional[str]:
    file_path = CONVERTER_CACHE_DIR / token / filename
    if file_path.exists():
        return str(file_path)
    return None


def get_converter_file_bytes(token: str, filename: str) -> Optional[bytes]:
    file_path = CONVERTER_CACHE_DIR / token / filename
    if file_path.exists():
        return file_path.read_bytes()
    return None


def get_converter_dir(token: str) -> Optional[str]:
    dir_path = CONVERTER_CACHE_DIR / token
    if dir_path.exists():
        return str(dir_path)
    return None


def cleanup_old_converter_files() -> int:
    _ensure_dir()
    now = time.time()
    removed = 0
    for entry in CONVERTER_CACHE_DIR.iterdir():
        if entry.is_dir():
            mtime = entry.stat().st_mtime
            if now - mtime > CONVERTER_FILE_TTL:
                for f in entry.iterdir():
                    f.unlink()
                entry.rmdir()
                removed += 1
    if removed:
        logger.debug(f"Cleaned up {removed} expired converter file directories")
    return removed
