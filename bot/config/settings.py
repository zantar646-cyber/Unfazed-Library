from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Final, List

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    api_base_url: str = field(default_factory=lambda: os.getenv("API_BASE_URL", "").strip())
    api_key: str = field(default_factory=lambda: os.getenv("API_KEY", ""))
    zlibrary_email: str = field(default_factory=lambda: os.getenv("ZLIBRARY_EMAIL", ""))
    zlibrary_password: str = field(default_factory=lambda: os.getenv("ZLIBRARY_PASSWORD", ""))
    singlelogin_url: str = field(default_factory=lambda: os.getenv("SINGLELOGIN_URL", "https://z-library.sk"))
    zlibrary_remix_userkey: str = field(default_factory=lambda: os.getenv("ZLIBRARY_REMIX_USERKEY", ""))
    zlibrary_remix_userid: str = field(default_factory=lambda: os.getenv("ZLIBRARY_REMIX_USERID", ""))

    # Anna's Archive
    annas_archive_base_url: str = field(default_factory=lambda: os.getenv("ANNAS_ARCHIVE_BASE_URL", "https://annas-archive.org"))
    annas_archive_secret_key: str = field(default_factory=lambda: os.getenv("ANNAS_ARCHIVE_SECRET_KEY", ""))
    annas_archive_timeout: int = field(default_factory=lambda: int(os.getenv("ANNAS_ARCHIVE_TIMEOUT", "30")))
    annas_archive_cache_ttl_search: int = field(default_factory=lambda: int(os.getenv("ANNAS_ARCHIVE_CACHE_TTL_SEARCH", "3600")))
    annas_archive_cache_ttl_metadata: int = field(default_factory=lambda: int(os.getenv("ANNAS_ARCHIVE_CACHE_TTL_METADATA", "86400")))

    use_sqlite: bool = field(
        default_factory=lambda: os.getenv("USE_SQLITE", "true").lower() == "true"
    )

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

    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
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

    mirrors: List[str] = field(default_factory=lambda: [
        x.strip() for x in os.getenv("MIRRORS", "").split(",") if x.strip()
    ])

    @property
    def db_dsn(self) -> str:
        if self.use_sqlite:
            return f"sqlite+aiosqlite:///{self.db_name}.db"
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def db_dsn_sync(self) -> str:
        if self.use_sqlite:
            return f"sqlite:///{self.db_name}.db"
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"


settings: Final[Settings] = Settings()
