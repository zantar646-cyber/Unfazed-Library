"""Environment config + wiring for the lightweight bot.

Loads .env, builds the source clients and the in-memory session store.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

try:
    from light.cache import BookRegistry, PreferencesStore, SessionStore
    from light.sources import AnnasArchive, SourceRouter, ZLibrary
    from light.userdata import UserDataStore
except ImportError:  # running directly: python light/bot.py
    from cache import BookRegistry, PreferencesStore, SessionStore  # type: ignore
    from sources import AnnasArchive, SourceRouter, ZLibrary  # type: ignore
    from userdata import UserDataStore  # type: ignore

def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


BOT_TOKEN = _env("BOT_TOKEN")
LOG_LEVEL = _env("LOG_LEVEL", "INFO").upper()
TELEGRAM_REQUEST_TIMEOUT = int(_env("TELEGRAM_REQUEST_TIMEOUT", "120"))
TELEGRAM_PROXY = _env("TELEGRAM_PROXY")
PAGE_SIZE = int(_env("PAGE_SIZE", "10"))
RATE_LIMIT_PER_USER = int(_env("RATE_LIMIT_PER_USER", "10"))
RATE_LIMIT_WINDOW = int(_env("RATE_LIMIT_WINDOW", "60"))
MAX_SEARCH_PAGES = int(_env("MAX_SEARCH_PAGES", "5"))
SEARCH_CACHE_TTL = int(_env("SEARCH_CACHE_TTL", "1800"))
DOWNLOAD_TIMEOUT = int(_env("DOWNLOAD_TIMEOUT", "120"))
MAX_FILE_SIZE = int(_env("MAX_FILE_SIZE", "52428800"))

zl = ZLibrary(
    base_url=_env("API_BASE_URL", "https://z-library.sk"),
    email=_env("ZLIBRARY_EMAIL"),
    password=_env("ZLIBRARY_PASSWORD"),
    remix_userkey=_env("ZLIBRARY_REMIX_USERKEY"),
    remix_userid=_env("ZLIBRARY_REMIX_USERID"),
    max_file_size=MAX_FILE_SIZE,
    api_rate_limit=int(_env("API_RATE_LIMIT", "30")),
    api_rate_window=int(_env("API_RATE_WINDOW", "60")),
    mirrors=[m.strip() for m in _env("MIRRORS", "").split(",") if m.strip()],
)

aa = AnnasArchive(
    base_url=_env("ANNAS_ARCHIVE_BASE_URL", "https://annas-archive.org"),
    secret_key=_env("ANNAS_ARCHIVE_SECRET_KEY"),
    timeout=int(_env("ANNAS_ARCHIVE_TIMEOUT", "30")),
)

sessions = SessionStore(ttl=SEARCH_CACHE_TTL)
_preferences_file = _env("PREFERENCES_FILE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "preferences.json")
preferences = PreferencesStore(path=_preferences_file)
_userdata_file = _env("USERDATA_FILE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "userdata.json")
userdata = UserDataStore(path=_userdata_file)
registry = BookRegistry()
source_router = SourceRouter(zl, aa, max_pages=MAX_SEARCH_PAGES)

# Support / contact links shown on the Support page (optional).
SUPPORT_URL = _env("SUPPORT_URL")
CONTACT_URL = _env("CONTACT_URL")
