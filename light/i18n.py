"""Lightweight i18n + language handling for the light bot.

Provides UI translations (EN/RU) mirroring bot/utils/i18n.py, the list of
content languages offered to users, and helpers to match book-language
values (``en``, ``eng``, ``English``, ``en-US`` ...) against a chosen
language code (``english``, ``russian``, ...).
"""

from __future__ import annotations

from typing import Optional

EN = "en"
RU = "ru"

LANG_TO_UI: dict[str, str] = {
    "english": EN,
    "russian": RU,
    "en": EN,
    "ru": RU,
}

# (code, display_name, flag) — the codes are passed to Z-Library as
# ``languages[]`` and stored as the user's preference.
LANGUAGES: list[tuple[str, str, str]] = [
    ("english", "English", "\U0001f1ec\U0001f1e7"),
    ("russian", "Russian", "\U0001f1f7\U0001f1fa"),
    ("german", "German", "\U0001f1e9\U0001f1ea"),
    ("french", "French", "\U0001f1eb\U0001f1f7"),
    ("spanish", "Spanish", "\U0001f1ea\U0001f1f8"),
    ("italian", "Italian", "\U0001f1ee\U0001f1f9"),
    ("portuguese", "Portuguese", "\U0001f1f5\U0001f1f9"),
    ("chinese", "Chinese", "\U0001f1e8\U0001f1f3"),
    ("japanese", "Japanese", "\U0001f1ef\U0001f1f5"),
    ("arabic", "Arabic", "\U0001f1e6\U0001f1ea"),
    ("hindi", "Hindi", "\U0001f1ee\U0001f1f3"),
    ("korean", "Korean", "\U0001f1f0\U0001f1f7"),
    ("dutch", "Dutch", "\U0001f1f3\U0001f1f1"),
    ("polish", "Polish", "\U0001f1f5\U0001f1f1"),
    ("turkish", "Turkish", "\U0001f1f9\U0001f1f7"),
]

# Aliases each chosen language code can appear as on a book record.
# Matching is STRICT: a book's language must be exactly one of these values.
# Covers the common ISO codes / names used by Z-Library and Anna's Archive.
LANGUAGE_ALIASES: dict[str, set[str]] = {
    "english": {"english", "en", "eng", "en-us", "en-gb", "en_us", "en_gb"},
    "russian": {"russian", "ru", "rus", "russkiy", "russkij"},
    "german": {"german", "de", "deu", "ger", "deutsch"},
    "french": {"french", "fr", "fra", "fre", "francais", "français"},
    "spanish": {"spanish", "es", "spa", "espanol", "español"},
    "italian": {"italian", "it", "ita", "italiano"},
    "portuguese": {"portuguese", "pt", "por", "portugues", "pt-br", "pt-pt", "pt_br", "pt_pt"},
    "chinese": {
        "chinese",
        "zh",
        "zho",
        "chi",
        "mandarin",
        "zh-cn",
        "zh-tw",
        "zh-hans",
        "zh-hant",
        "zh_cn",
        "zh_tw",
        "chinese-simplified",
        "chinese-traditional",
    },
    "japanese": {"japanese", "ja", "jpn"},
    "arabic": {"arabic", "ar", "ara"},
    "hindi": {"hindi", "hi", "hin"},
    "korean": {"korean", "ko", "kor"},
    "dutch": {"dutch", "nl", "nld", "dut"},
    "polish": {"polish", "pl", "pol"},
    "turkish": {"turkish", "tr", "tur"},
}

# Telegram locale prefixes (from ``from_user.language_code``) -> content code.
# Used to auto-detect a first-time user's language. Telegram does not expose
# user IPs to bots, so the client locale is the reliable signal.
TELEGRAM_LANG_TO_CODE: dict[str, str] = {
    "en": "english",
    "ru": "russian",
    "uk": "russian",
    "be": "russian",
    "de": "german",
    "fr": "french",
    "es": "spanish",
    "it": "italian",
    "pt": "portuguese",
    "zh": "chinese",
    "ja": "japanese",
    "ar": "arabic",
    "hi": "hindi",
    "ko": "korean",
    "nl": "dutch",
    "pl": "polish",
    "tr": "turkish",
}


def detect_content_language(language_code: Optional[str]) -> Optional[str]:
    """Map a Telegram locale (``en-US``, ``pt_BR`` ...) to a content code."""
    if not language_code:
        return None
    base = (language_code.lower().split("-")[0].split("_")[0]).strip()
    return TELEGRAM_LANG_TO_CODE.get(base)

TRANSLATIONS: dict[str, dict[str, str]] = {
    EN: {
        # Rate limiting
        "rate_limited": "Too many requests. Please wait a minute and try again.",
        "rate_limited_alert": "Too many requests. Please wait a minute.",
        # Buttons
        "btn_prev": "\u25c0\ufe0f Prev",
        "btn_next": "Next \u25b6\ufe0f",
        "btn_close": "\u2716 Close",
        "btn_back": "\u2b05\ufe0f Back",
        "btn_download": "\u2b07\ufe0f Download",
        "btn_any_language": "\U0001f310 Any Language",
        # Search
        "search_short_query": "Please send a book title to search, e.g. <b>Atomic Habits</b>.",
        "search_query_too_long": "Query is too long (max 200 characters).",
        "search_loading": "\U0001f50d Searching for <b>{query}</b>...",
        "search_failed": "Search failed. Please try again.",
        "search_no_results": "No results found for <b>{query}</b>.",
        "search_results_header": (
            "\U0001f50d <b>{total}</b> {word} for <b>{query}</b>{filter}\n\n"
            "Tap a book to see details and download it."
        ),
        "search_page_header": (
            "\U0001f50d <b>{total}</b> {word} for <b>{query}</b>{filter} "
            "\u00b7 page {page}/{total_pages}\n\n"
            "Tap a book to see details and download it."
        ),
        "search_expired": "Search expired. Please search again.",
        # Book detail
        "book_not_found_recent": "Book not found in recent searches.",
        "book_not_found_download": "Book not found. Search for it first, then download from the results.",
        "unknown": "Unknown",
        "unknown_author": "Unknown Author",
        "details_header": "\U0001f4cb <b>Details</b>",
        "book_year": "\u2022 \U0001f4c5 <b>Year:</b> {value}",
        "book_pages": "\u2022 \U0001f4da <b>Pages:</b> {value}",
        "book_language": "\u2022 \U0001f310 <b>Language:</b> {value}",
        "book_format": "\u2022 <b>Format:</b> {emoji} {value}",
        "book_size": "\u2022 \U0001f4be <b>Size:</b> {value}",
        "book_formats": "\u2022 \U0001f4d1 <b>Formats:</b> {value}",
        # Download
        "download_usage": "Usage: /download <book_id>",
        "download_start": "\u2b07\ufe0f Downloading <b>{title}</b>\u2026",
        "download_progress": "\u2b07\ufe0f Downloading <b>{title}</b>\u2026\n\n`{bar}` {pct:.0f}%",
        "download_timed_out": "Download timed out. Please try again.",
        "download_failed": "Download failed. Please try again.",
        "download_unavailable": "This file is temporarily unavailable. Please try another edition or format.",
        "download_zl_fallback": (
            "Couldn't download automatically (site anti-bot).\n"
            "<a href=\"{url}\">Open download link</a>"
        ),
        "download_caption": (
            "\u2705 <b>{title}</b>\n"
            "<i>by {author}</i>\n\n"
            "\U0001f4c1 <b>{fmt}</b>  \u00b7  \U0001f4be <b>{size}</b>"
        ),
        "file_too_large": "File is too large to send on Telegram.",
        "file_too_large_zl": (
            "File is too large to send on Telegram.\n"
            "<a href=\"{url}\">Open download link</a>"
        ),
        # Language
        "language_title": "\U0001f310 <b>Language</b>",
        "language_title_with": "\U0001f310 <b>Language</b> ({name})",
        "language_description": (
            "<i>Choose the bot language. The interface and search results "
            "will change to your chosen language.</i>"
        ),
        "language_set": (
            "\u2705 <b>Language set to</b> <u>{name}</u>.\n\n"
            "<i>The bot is now in {name}. Search results will only show "
            "books in this language.</i>"
        ),
        "language_cleared": (
            "\u2705 <b>Language reset.</b>\n\n"
            "<i>The bot is back in English and showing all languages.</i>"
        ),
        # Main menu
        "menu_search": "Search",
        "menu_language": "Language",
        "menu_help": "Help",
        # Reply keyboard menu
        "menu_favorites": "Favorites",
        "menu_history": "History",
        "menu_settings": "Settings",
        "menu_support": "Support",
        "reply_placeholder": "Search a book title\u2026",
        # Home
        "home_welcome": (
            "\U0001f4da <b>Welcome to Unfazed Library</b>\n\n"
            "Search millions of books instantly.\n\n"
            "Search by:\n"
            "\u2022 Book title\n"
            "\u2022 Author\n"
            "\u2022 ISBN\n\n"
            "Or use the menu below to begin."
        ),
        "home_trending": "\U0001f525 <b>Trending</b>",
        # Search prompt
        "search_prompt": (
            "\U0001f50d <b>What are you looking for?</b>\n\n"
            "You can search using:\n"
            "\u2022 Book Title\n"
            "\u2022 Author\n"
            "\u2022 ISBN\n\n"
            "Examples\n"
            "<b>Atomic Habits</b>\n"
            "<b>Harry Potter</b>\n"
            "<b>Robert Greene</b>\n"
            "<b>9780135957059</b>"
        ),
        # Favorites
        "fav_title": "\u2b50 <b>Your Favorites</b>",
        "fav_empty": (
            "You haven't saved any books yet.\n\n"
            "Open a book and tap \u2b50 Add to Favorites."
        ),
        "fav_added": "\u2b50 Added to favorites",
        "fav_removed": "\u2705 Removed from favorites",
        "fav_toggle_add": "\u2b50 Add to Favorites",
        "fav_toggle_remove": "\u2705 Remove Favorite",
        "fav_page_hint": "\n\nPage {page} of {total_pages}",
        # History
        "hist_title": "\U0001f558 <b>History</b>",
        "hist_empty": (
            "No history yet.\n\n"
            "Your searches and downloads will appear here."
        ),
        "hist_search": "\U0001f50d {query}",
        "hist_download": "\u2b07\ufe0f {title}",
        "hist_clear": "\U0001f5d1 Clear History",
        "hist_cleared": "History cleared.",
        # Settings
        "settings_title": (
            "\u2699\ufe0f <b>Settings</b>\n\n"
            "Tap a setting to change it."
        ),
        "settings_format": "Preferred Format",
        "settings_page": "Results Per Page",
        "settings_notif": "Notifications",
        "settings_format_title": (
            "\U0001f4c4 <b>Preferred Format</b>\n\n"
            "File format used when you tap Download."
        ),
        "settings_page_title": (
            "\U0001f522 <b>Results Per Page</b>\n\n"
            "How many search results to show per page."
        ),
        "settings_notif_title": (
            "\U0001f514 <b>Notifications</b>\n\n"
            "Download progress updates can be turned off."
        ),
        "settings_format_set": "\u2705 Preferred format: {value}",
        "settings_page_set": "\u2705 Results per page: {value}",
        "settings_notif_on": "On",
        "settings_notif_off": "Off",
        "settings_notif_set": "\u2705 Notifications: {value}",
        # Help sections
        "help_index": "\u2753 <b>Help</b>\n\nChoose a topic:",
        "help_how_search": "How to Search",
        "help_downloads": "How Downloads Work",
        "help_formats": "Supported Formats",
        "help_faq": "Frequently Asked Questions",
        "help_report": "Report a Problem",
        "help_contact": "Contact Developer",
        "help_how_search_text": (
            "\U0001f50d <b>How to Search</b>\n\n"
            "Just type a book title, author, or ISBN and send it.\n\n"
            "\u2022 <i>author:Rowling</i> \u2014 search by author\n"
            "\u2022 <i>isbn:978\u2026</i> \u2014 search by ISBN\n\n"
            "Tap a result to open details, then tap Download."
        ),
        "help_downloads_text": (
            "\u2b07\ufe0f <b>How Downloads Work</b>\n\n"
            "Tap \u2b07 Download on a book to receive the file here in the chat.\n\n"
            "If several formats are available, you'll see a button for each.\n\n"
            "Very large files may be blocked by Telegram."
        ),
        "help_formats_text": (
            "\U0001f4c4 <b>Supported Formats</b>\n\n"
            "PDF, EPUB, MOBI, AZW3, FB2, DJVU, TXT and more.\n\n"
            "Set a default format in \u2699\ufe0f Settings \u2192 Preferred Format."
        ),
        "help_faq_text": (
            "\u2753 <b>FAQ</b>\n\n"
            "\u2022 <b>No results?</b> Try the exact title or an ISBN.\n"
            "\u2022 <b>Download fails?</b> Try another edition or format.\n"
            "\u2022 <b>Language filter?</b> Set it in \U0001f310 Language.\n"
            "\u2022 <b>Lost a book?</b> Check \U0001f558 History.\n"
            "\u2022 <b>Slow search?</b> The mirrors can be busy \u2014 retry in a minute."
        ),
        "help_report_text": (
            "\U0001f41e <b>Report a Problem</b>\n\n"
            "Describe what happened and what you expected.\n"
            "Include the book title if possible."
        ),
        "help_contact_text": (
            "\u2709\ufe0f <b>Contact Developer</b>\n\n"
            "For questions, feedback or feature ideas, message the developer."
        ),
        # Support
        "support_title": (
            "\U0001f48e <b>Support Unfazed Library</b>\n\n"
            "Enjoying Unfazed Library?\n\n"
            "Support the development of the project.\n\n"
            "Your support helps keep the bot online and continuously improving."
        ),
        "support_pay": "\U0001f4b3 Donate",
        "support_contact_btn": "\u2709\ufe0f Contact",
        # Navigation
        "btn_home": "\U0001f3e0 Home",
        "page_indicator": "Page {page} of {total}",
        "book_next": "Next \u25b6\ufe0f",
        "book_prev": "\u2b05\ufe0f Prev",
        # Book detail extras
        "book_publisher": "\u2022 \U0001f3e2 <b>Publisher:</b> {value}",
        "book_isbn": "\u2022 \U0001f3f7\ufe0f <b>ISBN:</b> {value}",
        "book_categories": "\u2022 \U0001f5c2\ufe0f <b>Categories:</b> {value}",
        "book_downloads": "\u2022 \u2b07\ufe0f <b>Downloads:</b> {value}",
        "book_edition": "\u2022 \U0001f4d5 <b>Edition:</b> {value}",
    },
    RU: {
        # Rate limiting
        "rate_limited": "Слишком много запросов. Подождите минуту и попробуйте снова.",
        "rate_limited_alert": "Слишком много запросов. Подождите минуту.",
        # Buttons
        "btn_prev": "\u25c0\ufe0f Назад",
        "btn_next": "Вперёд \u25b6\ufe0f",
        "btn_close": "\u2716 Закрыть",
        "btn_back": "\u2b05\ufe0f Назад",
        "btn_download": "\u2b07\ufe0f Скачать",
        "btn_any_language": "\U0001f310 Любой язык",
        # Search
        "search_short_query": "Отправьте название книги для поиска, например <b>Atomic Habits</b>.",
        "search_query_too_long": "Запрос слишком длинный (максимум 200 символов).",
        "search_loading": "\U0001f50d Ищу <b>{query}</b>...",
        "search_failed": "Поиск не удался. Попробуйте ещё раз.",
        "search_no_results": "По запросу <b>{query}</b> ничего не найдено.",
        "search_results_header": (
            "\U0001f50d <b>{total}</b> {word} по запросу <b>{query}</b>{filter}\n\n"
            "Нажмите на книгу, чтобы увидеть детали и скачать её."
        ),
        "search_page_header": (
            "\U0001f50d <b>{total}</b> {word} по запросу <b>{query}</b>{filter} "
            "\u00b7 страница {page}/{total_pages}\n\n"
            "Нажмите на книгу, чтобы увидеть детали и скачать её."
        ),
        "search_expired": "Поиск устарел. Выполните поиск заново.",
        # Book detail
        "book_not_found_recent": "Книга не найдена в последних поисках.",
        "book_not_found_download": "Книга не найдена. Сначала выполните поиск, затем скачайте из результатов.",
        "unknown": "Неизвестно",
        "unknown_author": "Автор неизвестен",
        "details_header": "\U0001f4cb <b>Детали</b>",
        "book_year": "\u2022 \U0001f4c5 <b>Год:</b> {value}",
        "book_pages": "\u2022 \U0001f4da <b>Страниц:</b> {value}",
        "book_language": "\u2022 \U0001f310 <b>Язык:</b> {value}",
        "book_format": "\u2022 <b>Формат:</b> {emoji} {value}",
        "book_size": "\u2022 \U0001f4be <b>Размер:</b> {value}",
        "book_formats": "\u2022 \U0001f4d1 <b>Форматы:</b> {value}",
        # Download
        "download_usage": "Использование: /download <id_книги>",
        "download_start": "\u2b07\ufe0f Скачиваю <b>{title}</b>\u2026",
        "download_progress": "\u2b07\ufe0f Скачиваю <b>{title}</b>\u2026\n\n`{bar}` {pct:.0f}%",
        "download_timed_out": "Время скачивания истекло. Попробуйте ещё раз.",
        "download_failed": "Скачивание не удалось. Попробуйте ещё раз.",
        "download_unavailable": "Этот файл временно недоступен. Попробуйте другое издание или формат.",
        "download_zl_fallback": (
            "Не удалось скачать автоматически (защита сайта).\n"
            "<a href=\"{url}\">Открыть ссылку для скачивания</a>"
        ),
        "download_caption": (
            "\u2705 <b>{title}</b>\n"
            "<i>от {author}</i>\n\n"
            "\U0001f4c1 <b>{fmt}</b>  \u00b7  \U0001f4be <b>{size}</b>"
        ),
        "file_too_large": "Файл слишком большой для отправки в Telegram.",
        "file_too_large_zl": (
            "Файл слишком большой для отправки в Telegram.\n"
            "<a href=\"{url}\">Открыть ссылку для скачивания</a>"
        ),
        # Language
        "language_title": "\U0001f310 <b>Язык</b>",
        "language_title_with": "\U0001f310 <b>Язык</b> ({name})",
        "language_description": (
            "<i>Выберите язык бота. Интерфейс и результаты поиска "
            "изменятся на выбранный язык.</i>"
        ),
        "language_set": (
            "\u2705 <b>Язык установлен:</b> <u>{name}</u>.\n\n"
            "<i>Бот теперь на {name}. В результатах поиска будут только "
            "книги на этом языке.</i>"
        ),
        "language_cleared": (
            "\u2705 <b>Язык сброшен.</b>\n\n"
            "<i>Бот переключён на английский и показывает все языки.</i>"
        ),
        # Main menu
        "menu_search": "Поиск",
        "menu_language": "Язык",
        "menu_help": "Помощь",
        # Reply keyboard menu
        "menu_favorites": "Избранное",
        "menu_history": "История",
        "menu_settings": "Настройки",
        "menu_support": "Поддержка",
        "reply_placeholder": "Введите название книги\u2026",
        # Home
        "home_welcome": (
            "\U0001f4da <b>Добро пожаловать в Unfazed Library</b>\n\n"
            "Поиск миллионов книг мгновенно.\n\n"
            "Ищите по:\n"
            "\u2022 Названию книги\n"
            "\u2022 Автору\n"
            "\u2022 ISBN\n\n"
            "Или воспользуйтесь меню ниже."
        ),
        "home_trending": "\U0001f525 <b>В тренде</b>",
        # Search prompt
        "search_prompt": (
            "\U0001f50d <b>Что вы ищете?</b>\n\n"
            "Можно искать по:\n"
            "\u2022 Названию книги\n"
            "\u2022 Автору\n"
            "\u2022 ISBN\n\n"
            "Примеры\n"
            "<b>Atomic Habits</b>\n"
            "<b>Гарри Поттер</b>\n"
            "<b>Роберт Грин</b>\n"
            "<b>9780135957059</b>"
        ),
        # Favorites
        "fav_title": "\u2b50 <b>Ваше избранное</b>",
        "fav_empty": (
            "Вы ещё не сохранили ни одной книги.\n\n"
            "Откройте книгу и нажмите \u2b50 «В избранное»."
        ),
        "fav_added": "\u2b50 Добавлено в избранное",
        "fav_removed": "\u2705 Удалено из избранного",
        "fav_toggle_add": "\u2b50 В избранное",
        "fav_toggle_remove": "\u2705 Убрать из избранного",
        "fav_page_hint": "\n\nСтраница {page} из {total_pages}",
        # History
        "hist_title": "\U0001f558 <b>История</b>",
        "hist_empty": (
            "История пуста.\n\n"
            "Здесь появятся ваши поиски и скачивания."
        ),
        "hist_search": "\U0001f50d {query}",
        "hist_download": "\u2b07\ufe0f {title}",
        "hist_clear": "\U0001f5d1 Очистить историю",
        "hist_cleared": "История очищена.",
        # Settings
        "settings_title": (
            "\u2699\ufe0f <b>Настройки</b>\n\n"
            "Нажмите на настройку, чтобы изменить её."
        ),
        "settings_format": "Формат по умолчанию",
        "settings_page": "Результатов на странице",
        "settings_notif": "Уведомления",
        "settings_format_title": (
            "\U0001f4c4 <b>Формат по умолчанию</b>\n\n"
            "Формат файла при нажатии «Скачать»."
        ),
        "settings_page_title": (
            "\U0001f522 <b>Результатов на странице</b>\n\n"
            "Сколько результатов показывать на странице."
        ),
        "settings_notif_title": (
            "\U0001f514 <b>Уведомления</b>\n\n"
            "Обновления прогресса скачивания можно отключить."
        ),
        "settings_format_set": "\u2705 Формат по умолчанию: {value}",
        "settings_page_set": "\u2705 Результатов на странице: {value}",
        "settings_notif_on": "Вкл",
        "settings_notif_off": "Выкл",
        "settings_notif_set": "\u2705 Уведомления: {value}",
        # Help sections
        "help_index": "\u2753 <b>Помощь</b>\n\nВыберите тему:",
        "help_how_search": "Как искать",
        "help_downloads": "Как работают скачивания",
        "help_formats": "Поддерживаемые форматы",
        "help_faq": "Частые вопросы",
        "help_report": "Сообщить о проблеме",
        "help_contact": "Связаться с разработчиком",
        "help_how_search_text": (
            "\U0001f50d <b>Как искать</b>\n\n"
            "Просто введите название книги, автора или ISBN.\n\n"
            "\u2022 <i>author:Пушкин</i> \u2014 поиск по автору\n"
            "\u2022 <i>isbn:978\u2026</i> \u2014 поиск по ISBN\n\n"
            "Нажмите на результат, чтобы открыть детали, затем «Скачать»."
        ),
        "help_downloads_text": (
            "\u2b07\ufe0f <b>Как работают скачивания</b>\n\n"
            "Нажмите \u2b07 «Скачать», чтобы получить файл прямо в чат.\n\n"
            "Если доступно несколько форматов, будет кнопка для каждого.\n\n"
            "Очень большие файлы Telegram может не пропустить."
        ),
        "help_formats_text": (
            "\U0001f4c4 <b>Поддерживаемые форматы</b>\n\n"
            "PDF, EPUB, MOBI, AZW3, FB2, DJVU, TXT и другие.\n\n"
            "Задайте формат по умолчанию в \u2699\ufe0f Настройки \u2192 Формат по умолчанию."
        ),
        "help_faq_text": (
            "\u2753 <b>Частые вопросы</b>\n\n"
            "\u2022 <b>Нет результатов?</b> Попробуйте точное название или ISBN.\n"
            "\u2022 <b>Не скачивается?</b> Попробуйте другое издание или формат.\n"
            "\u2022 <b>Фильтр языка?</b> Задайте его в \U0001f310 Язык.\n"
            "\u2022 <b>Потеряли книгу?</b> Загляните в \U0001f558 Историю.\n"
            "\u2022 <b>Медленный поиск?</b> Зеркала могут быть заняты \u2014 повторите через минуту."
        ),
        "help_report_text": (
            "\U0001f41e <b>Сообщить о проблеме</b>\n\n"
            "Опишите, что произошло и что вы ожидали.\n"
            "По возможности укажите название книги."
        ),
        "help_contact_text": (
            "\u2709\ufe0f <b>Связаться с разработчиком</b>\n\n"
            "Вопросы, отзывы или идеи \u2014 напишите разработчику."
        ),
        # Support
        "support_title": (
            "\U0001f48e <b>Поддержка Unfazed Library</b>\n\n"
            "Вам нравится Unfazed Library?\n\n"
            "Поддержите развитие проекта.\n\n"
            "Ваша поддержка помогает боту оставаться онлайн и постоянно развиваться."
        ),
        "support_pay": "\U0001f4b3 Пожертвовать",
        "support_contact_btn": "\u2709\ufe0f Написать",
        # Navigation
        "btn_home": "\U0001f3e0 Главная",
        "page_indicator": "Стр. {page} из {total}",
        "book_next": "Вперёд \u25b6\ufe0f",
        "book_prev": "\u2b05\ufe0f Назад",
        # Book detail extras
        "book_publisher": "\u2022 \U0001f3e2 <b>Издательство:</b> {value}",
        "book_isbn": "\u2022 \U0001f3f7\ufe0f <b>ISBN:</b> {value}",
        "book_categories": "\u2022 \U0001f5c2\ufe0f <b>Категории:</b> {value}",
        "book_downloads": "\u2022 \u2b07\ufe0f <b>Скачиваний:</b> {value}",
        "book_edition": "\u2022 \U0001f4d5 <b>Издание:</b> {value}",
    },
}


def get_text(key: str, lang: Optional[str] = None) -> str:
    lang = (lang or EN).lower()
    lang = LANG_TO_UI.get(lang, lang)
    if lang not in TRANSLATIONS:
        lang = EN
    return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS[EN].get(key, key))


def language_name(code: str) -> str:
    code = (code or "").lower()
    for c, name, _ in LANGUAGES:
        if c == code:
            return name
    return code or ""


def language_flag(code: str) -> str:
    code = (code or "").lower()
    for c, _, flag in LANGUAGES:
        if c == code:
            return flag
    return "\U0001f310"


def language_matches(book_language: Optional[str], target_code: Optional[str]) -> bool:
    """Whether a book's language value matches the chosen language code.

    Strict: the value must be exactly one of the aliases for the target code.
    A blank/unknown book language never matches a filtered search.
    """
    if not target_code:
        return True
    if not book_language or not book_language.strip():
        return False
    bl = book_language.strip().lower()
    aliases = LANGUAGE_ALIASES.get(target_code.lower(), {target_code.lower()})
    return bl in aliases


def language_display(value: Optional[str], lang: Optional[str] = None) -> str:
    """Human-readable language name for a raw book-language value."""
    if not value:
        return get_text("unknown", lang)
    for code, name, _ in LANGUAGES:
        if language_matches(value, code):
            return name
    return value


def _ru_plural(count: int, one: str, few: str, many: str) -> str:
    n = abs(int(count)) % 100
    n1 = n % 10
    if 10 < n < 20:
        return many
    if 1 < n1 < 5:
        return few
    if n1 == 1:
        return one
    return many


def pluralize(count: int, lang: Optional[str] = None) -> str:
    lang = (lang or EN).lower()
    if LANG_TO_UI.get(lang) == RU:
        return _ru_plural(count, "книга", "книги", "книг")
    return "result" if count == 1 else "results"
