from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Final, List

from dotenv import load_dotenv

# .env is this project's config source of truth. override=True prevents a stale
# BOT_TOKEN left over in the ambient environment from silently winning.
load_dotenv(override=True)


def _detect_use_sqlite() -> bool:
    raw = os.getenv("USE_SQLITE", "").strip().lower()
    if raw in ("false", "0", "no"):
        return False
    db_url = os.getenv("DATABASE_URL", os.getenv("POSTGRES_URL", "")).strip().lower()
    if db_url and ("postgres" in db_url or "supabase" in db_url):
        return False
    if raw in ("true", "1", "yes"):
        return True
    if db_url and "sqlite" in db_url:
        return True
    return True


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", "").strip())
    api_base_url: str = field(default_factory=lambda: os.getenv("API_BASE_URL", "https://z-library.ec").strip())
    api_key: str = field(default_factory=lambda: os.getenv("API_KEY", ""))
    zlibrary_email: str = field(default_factory=lambda: os.getenv("ZLIBRARY_EMAIL", ""))
    zlibrary_password: str = field(default_factory=lambda: os.getenv("ZLIBRARY_PASSWORD", ""))
    singlelogin_url: str = field(default_factory=lambda: os.getenv("SINGLELOGIN_URL", "https://z-library.ec"))
    zlibrary_remix_userkey: str = field(default_factory=lambda: os.getenv("ZLIBRARY_REMIX_USERKEY", ""))
    zlibrary_remix_userid: str = field(default_factory=lambda: os.getenv("ZLIBRARY_REMIX_USERID", ""))

    # Anna's Archive
    annas_archive_base_url: str = field(default_factory=lambda: os.getenv("ANNAS_ARCHIVE_BASE_URL", "https://annas-archive.gl"))
    annas_archive_secret_key: str = field(default_factory=lambda: os.getenv("ANNAS_ARCHIVE_SECRET_KEY", ""))
    annas_archive_timeout: int = field(default_factory=lambda: int(os.getenv("ANNAS_ARCHIVE_TIMEOUT", "30")))
    annas_archive_cache_ttl_search: int = field(default_factory=lambda: int(os.getenv("ANNAS_ARCHIVE_CACHE_TTL_SEARCH", "3600")))
    annas_archive_cache_ttl_metadata: int = field(default_factory=lambda: int(os.getenv("ANNAS_ARCHIVE_CACHE_TTL_METADATA", "86400")))

    use_sqlite: bool = field(default_factory=_detect_use_sqlite)

    # Supabase credentials (optional, auto-configured when DATABASE_URL is set)
    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", "").strip())
    supabase_anon_key: str = field(default_factory=lambda: os.getenv("SUPABASE_ANON_KEY", "").strip())
    supabase_service_role_key: str = field(default_factory=lambda: os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip())

    db_host: str = field(default_factory=lambda: os.getenv("DB_HOST", "localhost"))
    db_port: int = field(default_factory=lambda: int(os.getenv("DB_PORT", "5432")))
    db_name: str = field(default_factory=lambda: os.getenv("DB_NAME", "digital_library"))
    db_user: str = field(default_factory=lambda: os.getenv("DB_USER", "postgres"))
    db_password: str = field(default_factory=lambda: os.getenv("DB_PASSWORD", ""))

    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    redis_ttl: int = field(default_factory=lambda: int(os.getenv("REDIS_TTL", "300")))

    admin_ids: List[int] = field(default_factory=lambda: [
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
    ])

    google_books_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_BOOKS_API_KEY", ""))

    rate_limit_per_user: int = field(default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_USER", "10")))
    rate_limit_window: int = field(default_factory=lambda: int(os.getenv("RATE_LIMIT_WINDOW", "60")))

    max_file_size: int = field(default_factory=lambda: int(os.getenv("MAX_FILE_SIZE", "52428800")))
    download_base_url: str = field(default_factory=lambda: os.getenv("DOWNLOAD_BASE_URL", ""))

    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))

    db_pool_min: int = field(default_factory=lambda: int(os.getenv("DB_POOL_MIN", "1")))
    db_pool_max: int = field(default_factory=lambda: int(os.getenv("DB_POOL_MAX", "5")))

    api_rate_limit: int = field(default_factory=lambda: int(os.getenv("API_RATE_LIMIT", "30")))
    api_rate_window: int = field(default_factory=lambda: int(os.getenv("API_RATE_WINDOW", "60")))

    mirror_recheck_interval: int = field(
        default_factory=lambda: int(os.getenv("MIRROR_RECHECK_INTERVAL", "3600"))
    )

    mirrors: List[str] = field(default_factory=lambda: (
        [x.strip() for x in os.getenv("MIRRORS", "").split(",") if x.strip()]
        or ["https://z-lib.gl"]
    ))

    webhook_url: str = field(default_factory=lambda: os.getenv("WEBHOOK_URL", "").strip())
    webhook_secret: str = field(default_factory=lambda: os.getenv("WEBHOOK_SECRET", "").strip())
    diag_token: str = field(default_factory=lambda: os.getenv("DIAG_TOKEN", "").strip())
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", os.getenv("POSTGRES_URL", "")).strip())
    is_vercel: bool = field(default_factory=lambda: bool(os.getenv("VERCEL")))

    # Library <-> File Converter bridge
    storage_channel_id: str = field(default_factory=lambda: os.getenv("STORAGE_CHANNEL_ID", "").strip())
    converter_bot_username: str = field(
        default_factory=lambda: os.getenv("CONVERTER_BOT_USERNAME", "Unfazed_File_Convertor_bot").strip().lstrip("@")
    )
    deeplink_secret: str = field(default_factory=lambda: os.getenv("DEEPLINK_SECRET", "").strip())

    @property
    def db_dsn(self) -> str:
        if self.database_url:
            url = self.database_url
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif url.startswith("sqlite://") and not url.startswith("sqlite+aiosqlite://"):
                url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
            return url

        if self.use_sqlite:
            # On Vercel, the root filesystem is read-only, only /tmp is writable
            if self.is_vercel or os.getenv("VERCEL"):
                return f"sqlite+aiosqlite:////tmp/{self.db_name}.db"
            return f"sqlite+aiosqlite:///{self.db_name}.db"
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def db_dsn_sync(self) -> str:
        if self.database_url:
            url = self.database_url
            if url.startswith("postgresql+asyncpg://"):
                url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
            elif url.startswith("sqlite+aiosqlite://"):
                url = url.replace("sqlite+aiosqlite://", "sqlite://", 1)
            return url

        if self.use_sqlite:
            if self.is_vercel or os.getenv("VERCEL"):
                return f"sqlite:////tmp/{self.db_name}.db"
            return f"sqlite:///{self.db_name}.db"
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"


settings: Final[Settings] = Settings()
