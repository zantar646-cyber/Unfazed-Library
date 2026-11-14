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

TRANSLATIONS: dict[str, dict[str, str]] = {
    EN: {
        # Start
        "start_welcome": (
            "<b>\U0001f4da Welcome to <u>Unfazed Library</u></b> \U0001f680\n\n"
            "<i>Your gateway to a world of knowledge is now open.</i>\n\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\u2728 <b>What you can do:</b>\n"
            "\U0001f50d <i>Search</i> for books by title or author\n"
            "\U0001f4c2 <i>Browse</i> categories and genres\n"
            "\U0001f4e5 <i>Download</i> books instantly\n"
            "\u2764\ufe0f <i>Build</i> your favorites list\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "Whether you're a <b>student</b>, <b>researcher</b>, or <b>lifelong learner</b>, "
            "Unfazed Library is here for you.\n\n"
            "<blockquote>\U0001f4d6 <i>\"The more that you read, the more things you will know.\"</i></blockquote>\n\n"
            "<i>Start by searching or pick an option below!</i>\n\n"
            "\u2014 Team <b>Unfazed Library</b> \U0001f4da\u2764\ufe0f"
        ),
        # Help
        "help_title": "<b>\U0001f4da <u>Unfazed Library \u2014 Help Center</u></b>",
        "help_searching_header": "\U0001f50d <u><b>Searching</b></u>",
        "help_searching_items": (
            "\u2022 Type any <i>book title</i> directly in chat\n"
            "\u2022 <code>/search &lt;title&gt;</code> \u2014 Search by <i>title</i>\n"
            "\u2022 <code>/search author:&lt;name&gt;</code> \u2014 Search by <i>author</i>\n"
            "\u2022 <code>/search isbn:&lt;isbn&gt;</code> \u2014 Search by <i>ISBN</i>"
        ),
        "help_browsing_header": "\U0001f4c2 <u><b>Browsing</b></u>",
        "help_browsing_items": (
            "\u2022 <code>/latest</code> \u2014 <i>Newest</i> additions to the library\n"
            "\u2022 <code>/categories</code> \u2014 Browse books by <i>category</i>\n"
            "\u2022 <code>/popular</code> \u2014 <i>Most downloaded</i> books"
        ),
        "help_downloads_header": "\U0001f4e5 <u><b>Downloads</b></u>",
        "help_downloads_items": (
            "\u2022 Tap \u2b07\ufe0f <b>Download</b> on any book to get it\n"
            "\u2022 Files are sent directly as <i>documents</i>\n"
            "\u2022 Click \U0001f504 <b>Convert</b> to forward to format converter"
        ),
        "help_account_header": "\U0001f464 <u><b>Your Library</b></u>",
        "help_account_items": (
            "\u2022 <code>/favorites</code> \u2014 Your saved <i>bookmarks</i>\n"
            "\u2022 <code>/history</code> \u2014 Your <i>download history</i>\n"
            "\u2022 <code>/profile</code> \u2014 Your <i>stats &amp; preferences</i>\n"
            "\u2022 <code>/language</code> \u2014 Set <i>content language</i> filter"
        ),
        "help_tips_header": "\U0001f4a1 <u><b>Tips</b></u>",
        "help_tips_items": (
            "\u2022 Use the <b>reply keyboard</b> shortcuts below\n"
            "\u2022 Book details include <i>description, format, size</i>"
        ),
        "help_footer": "\u2753 <i>Need more help?</i> Contact the administrator.",
        # Menu
        "menu_text": (
            "<b>\U0001f4da <u>Unfazed Library</u></b>\n\n"
            "<i>Your gateway to a world of knowledge is open.</i> \U0001f680\n\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\u2728 <b>What you can do:</b>\n"
            "\U0001f50d <i>Search</i> for books by title or author\n"
            "\U0001f4c2 <i>Browse</i> categories and genres\n"
            "\U0001f4e5 <i>Download</i> books instantly\n"
            "\u2764\ufe0f <i>Build</i> your favorites list\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "<i>Pick an option below or just type to search!</i>"
        ),
        # Search
        "search_prompt": (
            "\U0001f50d <b><u>Search Books</u></b>\n\n"
            "<i>Type your search query directly in the chat.</i>\n\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "<b>Examples:</b>\n"
            "\u2022 <code>artificial intelligence</code>\n"
            "\u2022 <code>author:Tolkien</code>\n"
            "\u2022 <code>isbn:9780262033848</code>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "Or use <code>/search &lt;query&gt;</code>"
        ),
        "search_loading": "<i>Searching for</i> <b>{query}</b> <i>...</i>",
        "search_no_query": (
            "\U0001f50d <b><u>Search Books</u></b>\n\n"
            "<i>Please provide a search query.</i>\n\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "<b>Examples:</b>\n"
            "\u2022 <code>/search artificial intelligence</code>\n"
            "\u2022 <code>/search author:Tolkien</code>\n"
            "\u2022 <code>/search isbn:9780262033848</code>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "<i>You can also type a query directly!</i>"
        ),
        "search_invalid_query": "\u26a0\ufe0f <i>Invalid search query.</i> Use <b>2\u2013200</b> characters.",
        "search_failed": "\u274c <b>Search failed.</b> <i>Please try again later.</i>",
        "search_no_results": "<i>No books found for</i> '<b>{query}</b>'.\n\n\U0001f50d <i>Try different keywords or browse categories.</i>",
        "search_results": "\U0001f50d <i>Found</i> <b>{total}</b> <i>book(s) for</i> '<b>{query}</b>':",
        # Latest
        "latest_loading": "<i>Fetching latest books...</i>",
        "latest_failed": "\u274c <b>Failed</b> to fetch latest books. <i>Try again later.</i>",
        "latest_no_results": "\U0001f4ed <i>No recent books found.</i>",
        "latest_title": "\U0001f4f0 <b><u>Latest Books</u></b>\n\n<i>Recently added to the library:</i>",
        # Popular
        "popular_loading": "<i>Fetching popular books...</i>",
        "popular_failed": "\u274c <b>Failed</b> to fetch popular books.",
        "popular_no_results": "\U0001f4ed <i>No popular books found.</i>",
        "popular_title": "\U0001f525 <b><u>Popular Books</u></b>\n\n<i>Most downloaded books:</i>",
        # Profile
        "profile_title": "<b>\U0001f464 <u>Your Profile</u></b>",
        "profile_id": "\U0001f511 <b>ID:</b> <code>{id}</code>",
        "profile_username": "\U0001f517 <b>Username:</b> @{username}",
        "profile_name": "\U0001f4ac <b>Name:</b> {name}",
        "profile_language": "\U0001f1ec\U0001f1e7 <b>Language Filter:</b> {lang}",
        "profile_registered": "\U0001f4c5 <b>Registered:</b> {date}",
        "profile_last_active": "\u23f3 <b>Last Active:</b> {date}",
        "profile_downloads": "\U0001f4e5 <b>Downloads:</b> <code>{count}</code>",
        "profile_favorites": "\u2764\ufe0f <b>Favorites:</b> <code>{count}</code>",
        "profile_any_lang": "Any",
        # Language
        "language_title": "<b>\U0001f1ec\U0001f1e7 <u>Preferred Language</u></b>",
        "language_title_with": "<b>\U0001f1ec\U0001f1e7 <u>Preferred Language</u></b> ({name})",
        "language_description": "<i>Select a language to filter search results.</i>\nBooks will be shown only in your chosen language.",
        "language_set": "\u2705 <b>Language set to</b> <u>{name}</u>.\n\n<i>Future searches will filter results to this language.</i>",
        "language_cleared": "\u2705 <b>Language filter cleared.</b>\n\n<i>Showing all languages.</i>",
        # Categories
        "categories_title": "\U0001f4ca <b><u>Book Categories</u></b>\n\n<i>Select a category to browse books:</i>",
        "categories_no_results": "\U0001f4ed <i>No categories available.</i>",
        "category_books_header": "<b>{name}</b> \u2014 <i>Page {page}/{total}</i> (<code>{count}</code> books):",
        "category_not_found": "\u274c <i>Category not found.</i>",
        "category_fetch_failed": "\u274c <i>Failed to fetch books for</i> <b>{name}</b>.\n\nPlease try again later.",
        "category_no_books": "\U0001f4ed <i>No books found in</i> <b>{name}</b>.",
        # Favorites
        "favorites_empty": "\u2764\ufe0f <i>You haven't added any favorites yet.</i>\n\n\U0001f50d Browse books and add them to your favorites!",
        "favorites_title": "\u2764\ufe0f <b><u>Your Favorites</u></b> (<code>{total}</code> books):",
        # History
        "history_empty": "\U0001f4ed <i>You haven't downloaded any books yet.</i>",
        "history_title": "\U0001f4cb <b><u>Your Download History</u></b>",
        "history_title_page": "\U0001f4cb <b><u>Your Download History</u></b> <i>(page {page}/{total})</i>",
        # Download
        "download_usage": (
            "\U0001f4e5 <b><u>Download a Book</u></b>\n\n"
            "<i>Usage:</i> <code>/download &lt;book_id&gt;</code>\n\n"
            "Get a book's ID from search results.\n"
            "<b>Example:</b> <code>/download 1234567</code>"
        ),
        "download_not_found": "\u274c <i>Book with ID</i> <code>{id}</code> <i>not found.</i>\n\n\U0001f50d Try searching for the book first with <code>/search</code>.",
        "download_no_url": "\u26a0\ufe0f <i>Download is not available for this book at the moment.</i>",
        "download_too_large": "\u26a0\ufe0f <i>This book is</i> <b>{size}</b>, <i>which exceeds Telegram's limit.</i>\n\nA direct download link will be provided.",
        "download_unavailable": "\u26a0\ufe0f <i>Download is not available for this book at the moment.</i>",
        "download_suggested": "\U0001f50d <i>I found a similar book:</i> <b>{title}</b> <i>by</i> {author}.\n\nIs this what you meant?",
        "download_confirm": "\u2705 Yes, download this",
        "download_cancel": "\u274c Cancel",
        "download_link": "\U0001f4e5 <b>Download</b> <u>{title}</u> <i>by</i> {author}:\n<code>{url}</code>",
        "download_loading": "\u23f3 <i>Fetching your book...</i>",
        "download_failed": "\u274c <i>Download failed. Please try again in a moment.</i>",
        # Book detail
        "book_not_found": "\u274c <i>Book not found.</i>",
        "book_detail_header": "<b>{title}</b>\n<i>by {author}</i>\n\n{description}",
        "book_detail_section": "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\U0001f4cb <b><u>Details</u></b>",
        "book_detail_publisher": "\U0001f4d6 <b>Publisher:</b> {value}",
        "book_detail_year": "\U0001f4c5 <b>Year:</b> {value}",
        "book_detail_pages": "\U0001f4c4 <b>Pages:</b> {value}",
        "book_detail_isbn": "\U0001f517 <b>ISBN:</b> <code>{value}</code>",
        "book_detail_language": "\U0001f310 <b>Language:</b> {value}",
        "book_detail_format": "{emoji} <b>Format:</b> {value}",
        "book_detail_size": "\U0001f4be <b>Size:</b> {value}",
        "book_detail_category": "\U0001f4c2 <b>Category:</b> {value}",
        "book_detail_downloads": "\U0001f4e5 <b>Downloads:</b> <code>{count}</code>",
        # Description
        "desc_no_description": "\U0001f4ed <i>No description available.</i>",
        # Convert
        "convert_title": "\U0001f504 <b><u>Convert this file</u></b>",
        "convert_message": (
            "<i>To convert this file to another format, forward it to</i> "
            "<b>@Unfazed_File_Convertor_bot</b>.\n\n"
            "\U0001f4cb <b>Supported formats:</b> "
            "<i>PDF, EPUB, DOCX, images, audio, video, and more.</i>"
        ),
        "convert_button": "\U0001f504 Open @Unfazed_File_Convertor_bot",
        # Misc
        "start_first": "\u26a0\ufe0f <i>Please start the bot first with</i> <code>/start</code>.",
        "user_not_found": "\u274c <i>User not found.</i>",
        "no_results": "\U0001f4ed <i>No results found.</i>",
        "loading": "\u23f3 <i>Loading...</i>",
        # Favorites toggle
        "favorite_added": "\u2764\ufe0f <i>Added to favorites!</i>",
        "favorite_removed": "\u274c <i>Removed from favorites.</i>",
        "favorite_error": "\u26a0\ufe0f <i>Error updating favorite.</i>",
        # History page
        "history_entry": "\U0001f4c5 {title} \u2014 <i>{date}</i>",
        "history_unknown_book": "Unknown",
        "history_page": "\U0001f4cb <b><u>Your Download History</u></b> <i>(page {page}/{total})</i>\n\n",
        # Pagination
        "page_format": "<i>Page</i> <b>{page}/{total}</b>:",
        "page_label": "{page}/{total}",
        # Source attribution
        "source_annas_archive": "\U0001f4e6 <i>Downloaded via Anna's Archive</i>",
        "source_zlibrary": "\U0001f4e5 <i>Downloaded via Z-Library (fallback)</i>",
        "source_unknown": "\U0001f4e5 <i>Downloaded</i>",
        "fallback_trying_zlibrary": "\U0001f50d <i>Anna's Archive didn't find results. Trying Z-Library as backup...</i>",
        "both_sources_failed": "\U0001f4ed <i>Sorry, I couldn't find or download this book from any available source. Try a different title, author, or ISBN.</i>",
    },
    RU: {
        "start_welcome": (
            "<b>\U0001f4da <u>Добро пожаловать в Unfazed Library</u></b> \U0001f680\n\n"
            "<i>Ваш путь в мир знаний открыт.</i>\n\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\u2728 <b>Что вы можете делать:</b>\n"
            "\U0001f50d <i>Искать</i> книги по названию или автору\n"
            "\U0001f4c2 <i>Просматривать</i> категории и жанры\n"
            "\U0001f4e5 <i>Скачивать</i> книги мгновенно\n"
            "\u2764\ufe0f <i>Составлять</i> список избранного\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "Студент, <b>исследователь</b> или просто <b>любитель чтения</b> \u2014 "
            "Unfazed Library всегда с вами.\n\n"
            "<blockquote>\U0001f4d6 <i>«Кто много читает, тот много знает.»</i></blockquote>\n\n"
            "<i>Начните с поиска или выберите опцию ниже!</i>\n\n"
            "\u2014 Команда <b>Unfazed Library</b> \U0001f4da\u2764\ufe0f"
        ),
        "help_title": "<b>\U0001f4da <u>Unfazed Library \u2014 Центр помощи</u></b>",
        "help_searching_header": "\U0001f50d <u><b>Поиск</b></u>",
        "help_searching_items": (
            "\u2022 Просто введите <i>название книги</i> в чат\n"
            "\u2022 <code>/search &lt;название&gt;</code> \u2014 Поиск по <i>названию</i>\n"
            "\u2022 <code>/search author:&lt;имя&gt;</code> \u2014 Поиск по <i>автору</i>\n"
            "\u2022 <code>/search isbn:&lt;isbn&gt;</code> \u2014 Поиск по <i>ISBN</i>"
        ),
        "help_browsing_header": "\U0001f4c2 <u><b>Просмотр</b></u>",
        "help_browsing_items": (
            "\u2022 <code>/latest</code> \u2014 <i>Новые</i> поступления\n"
            "\u2022 <code>/categories</code> \u2014 <i>Категории</i> книг\n"
            "\u2022 <code>/popular</code> \u2014 <i>Популярные</i> книги"
        ),
        "help_downloads_header": "\U0001f4e5 <u><b>Скачивание</b></u>",
        "help_downloads_items": (
            "\u2022 Нажмите \u2b07\ufe0f <b>Скачать</b> на любой книге\n"
            "\u2022 Файлы приходят прямо в чат как <i>документы</i>\n"
            "\u2022 Нажмите \U0001f504 <b>Конвертировать</b> для смены формата"
        ),
        "help_account_header": "\U0001f464 <u><b>Ваша библиотека</b></u>",
        "help_account_items": (
            "\u2022 <code>/favorites</code> \u2014 <i>Избранные</i> книги\n"
            "\u2022 <code>/history</code> \u2014 <i>История</i> скачиваний\n"
            "\u2022 <code>/profile</code> \u2014 <i>Статистика</i> и настройки\n"
            "\u2022 <code>/language</code> \u2014 <i>Языковой</i> фильтр"
        ),
        "help_tips_header": "\U0001f4a1 <u><b>Советы</b></u>",
        "help_tips_items": (
            "\u2022 Используйте <b>клавиатуру быстрого доступа</b>\n"
            "\u2022 В деталях книги: <i>описание, формат, размер</i>"
        ),
        "help_footer": "\u2753 <i>Нужна помощь?</i> Свяжитесь с администратором.",
        "menu_text": (
            "<b>\U0001f4da <u>Unfazed Library</u></b>\n\n"
            "<i>Ваш путь в мир знаний открыт.</i> \U0001f680\n\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\u2728 <b>Что вы можете делать:</b>\n"
            "\U0001f50d <i>Искать</i> книги по названию или автору\n"
            "\U0001f4c2 <i>Просматривать</i> категории и жанры\n"
            "\U0001f4e5 <i>Скачивать</i> книги мгновенно\n"
            "\u2764\ufe0f <i>Составлять</i> список избранного\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "<i>Выберите опцию ниже или просто введите текст для поиска!</i>"
        ),
        "search_prompt": (
            "\U0001f50d <b><u>Поиск книг</u></b>\n\n"
            "<i>Введите поисковый запрос прямо в чат.</i>\n\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "<b>Примеры:</b>\n"
            "\u2022 <code>искусственный интеллект</code>\n"
            "\u2022 <code>author:Пушкин</code>\n"
            "\u2022 <code>isbn:9780262033848</code>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "Или используйте <code>/search &lt;запрос&gt;</code>"
        ),
        "search_loading": "<i>Ищу</i> <b>{query}</b> <i>...</i>",
        "search_no_query": (
            "\U0001f50d <b><u>Поиск книг</u></b>\n\n"
            "<i>Пожалуйста, укажите поисковый запрос.</i>\n\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "<b>Примеры:</b>\n"
            "\u2022 <code>/search искусственный интеллект</code>\n"
            "\u2022 <code>/search author:Толкин</code>\n"
            "\u2022 <code>/search isbn:9780262033848</code>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            "<i>Вы также можете просто ввести запрос!</i>"
        ),
        "search_invalid_query": "\u26a0\ufe0f <i>Недопустимый запрос.</i> Используйте <b>2\u2013200</b> символов.",
        "search_failed": "\u274c <b>Поиск не удался.</b> <i>Попробуйте позже.</i>",
        "search_no_results": "<i>Ничего не найдено по запросу</i> '<b>{query}</b>'.\n\n\U0001f50d <i>Попробуйте другие ключевые слова.</i>",
        "search_results": "\U0001f50d <i>Найдено</i> <b>{total}</b> <i>книг(и) по запросу</i> '<b>{query}</b>':",
        "latest_loading": "<i>Загружаю новые книги...</i>",
        "latest_failed": "\u274c <b>Ошибка</b> загрузки новых книг. <i>Попробуйте позже.</i>",
        "latest_no_results": "\U0001f4ed <i>Новых книг не найдено.</i>",
        "latest_title": "\U0001f4f0 <b><u>Новые книги</u></b>\n\n<i>Недавно добавленные в библиотеку:</i>",
        "popular_loading": "<i>Загружаю популярные книги...</i>",
        "popular_failed": "\u274c <b>Ошибка</b> загрузки популярных книг.",
        "popular_no_results": "\U0001f4ed <i>Популярных книг не найдено.</i>",
        "popular_title": "\U0001f525 <b><u>Популярные книги</u></b>\n\n<i>Самые скачиваемые книги:</i>",
        "profile_title": "<b>\U0001f464 <u>Ваш профиль</u></b>",
        "profile_id": "\U0001f511 <b>ID:</b> <code>{id}</code>",
        "profile_username": "\U0001f517 <b>Username:</b> @{username}",
        "profile_name": "\U0001f4ac <b>Имя:</b> {name}",
        "profile_language": "\U0001f1ec\U0001f1e7 <b>Языковой фильтр:</b> {lang}",
        "profile_registered": "\U0001f4c5 <b>Зарегистрирован:</b> {date}",
        "profile_last_active": "\u23f3 <b>Был в сети:</b> {date}",
        "profile_downloads": "\U0001f4e5 <b>Скачиваний:</b> <code>{count}</code>",
        "profile_favorites": "\u2764\ufe0f <b>Избранное:</b> <code>{count}</code>",
        "profile_any_lang": "Любой",
        "language_title": "<b>\U0001f1ec\U0001f1e7 <u>Язык фильтрации</u></b>",
        "language_title_with": "<b>\U0001f1ec\U0001f1e7 <u>Язык фильтрации</u></b> ({name})",
        "language_description": "<i>Выберите язык для фильтрации результатов поиска.</i>\nКниги будут показаны только на выбранном языке.",
        "language_set": "\u2705 <b>Язык установлен:</b> <u>{name}</u>.\n\n<i>Поиск будет фильтровать результаты по этому языку.</i>",
        "language_cleared": "\u2705 <b>Языковой фильтр снят.</b>\n\n<i>Показываются все языки.</i>",
        "categories_title": "\U0001f4ca <b><u>Категории книг</u></b>\n\n<i>Выберите категорию:</i>",
        "categories_no_results": "\U0001f4ed <i>Категории недоступны.</i>",
        "category_books_header": "<b>{name}</b> \u2014 <i>Страница {page}/{total}</i> (<code>{count}</code> книг):",
        "category_not_found": "\u274c <i>Категория не найдена.</i>",
        "category_fetch_failed": "\u274c <i>Не удалось загрузить книги категории</i> <b>{name}</b>.\n\nПопробуйте позже.",
        "category_no_books": "\U0001f4ed <i>В категории</i> <b>{name}</b> <i>книг не найдено.</i>",
        "favorites_empty": "\u2764\ufe0f <i>У вас пока нет избранных книг.</i>\n\n\U0001f50d Добавьте книги в избранное!",
        "favorites_title": "\u2764\ufe0f <b><u>Избранное</u></b> (<code>{total}</code> книг):",
        "history_empty": "\U0001f4ed <i>Вы еще не скачивали книги.</i>",
        "history_title": "\U0001f4cb <b><u>История скачиваний</u></b>",
        "history_title_page": "\U0001f4cb <b><u>История скачиваний</u></b> <i>(стр. {page}/{total})</i>",
        "download_usage": (
            "\U0001f4e5 <b><u>Скачать книгу</u></b>\n\n"
            "<i>Использование:</i> <code>/download &lt;id_книги&gt;</code>\n\n"
            "ID книги можно получить из результатов поиска.\n"
            "<b>Пример:</b> <code>/download 1234567</code>"
        ),
        "download_not_found": "\u274c <i>Книга с ID</i> <code>{id}</code> <i>не найдена.</i>\n\n\U0001f50d Сначала найдите книгу через <code>/search</code>.",
        "download_no_url": "\u26a0\ufe0f <i>Скачивание для этой книги временно недоступно.</i>",
        "download_too_large": "\u26a0\ufe0f <i>Эта книга весит</i> <b>{size}</b>, <i>что превышает лимит Telegram.</i>\n\nБудет предоставлена прямая ссылка для скачивания.",
        "download_unavailable": "\u26a0\ufe0f <i>Скачивание для этой книги временно недоступно.</i>",
        "download_suggested": "\U0001f50d <i>Я нашел похожую книгу:</i> <b>{title}</b>, <i>{author}</i>.\n\nВы это имели в виду?",
        "download_confirm": "\u2705 Да, скачать это",
        "download_cancel": "\u274c Отмена",
        "download_link": "\U0001f4e5 <b>Скачать</b> <u>{title}</u> <i>от</i> {author}:\n<code>{url}</code>",
        "download_loading": "\u23f3 <i>Загружаю книгу...</i>",
        "download_failed": "\u274c <i>Не удалось скачать. Попробуйте ещё раз через минуту.</i>",
        "book_not_found": "\u274c <i>Книга не найдена.</i>",
        "desc_no_description": "\U0001f4ed <i>Описание недоступно.</i>",
        "book_detail_header": "<b>{title}</b>\n<i>by {author}</i>\n\n{description}",
        "book_detail_section": "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\U0001f4cb <b><u>Детали</u></b>",
        "book_detail_publisher": "\U0001f4d6 <b>Издатель:</b> {value}",
        "book_detail_year": "\U0001f4c5 <b>Год:</b> {value}",
        "book_detail_pages": "\U0001f4c4 <b>Страниц:</b> {value}",
        "book_detail_isbn": "\U0001f517 <b>ISBN:</b> <code>{value}</code>",
        "book_detail_language": "\U0001f310 <b>Язык:</b> {value}",
        "book_detail_format": "{emoji} <b>Формат:</b> {value}",
        "book_detail_size": "\U0001f4be <b>Размер:</b> {value}",
        "book_detail_category": "\U0001f4c2 <b>Категория:</b> {value}",
        "book_detail_downloads": "\U0001f4e5 <b>Скачиваний:</b> <code>{count}</code>",
        "convert_title": "\U0001f504 <b><u>Конвертировать файл</u></b>",
        "convert_message": (
            "<i>Чтобы конвертировать этот файл в другой формат, "
            "перешлите его</i> <b>@Unfazed_File_Convertor_bot</b>.\n\n"
            "\U0001f4cb <b>Поддерживаемые форматы:</b> "
            "<i>PDF, EPUB, DOCX, изображения, аудио, видео и другие.</i>"
        ),
        "convert_button": "\U0001f504 Открыть @Unfazed_File_Convertor_bot",
        "start_first": "\u26a0\ufe0f <i>Сначала запустите бота командой</i> <code>/start</code>.",
        "user_not_found": "\u274c <i>Пользователь не найден.</i>",
        "no_results": "\U0001f4ed <i>Ничего не найдено.</i>",
        "loading": "\u23f3 <i>Загрузка...</i>",
        "favorite_added": "\u2764\ufe0f <i>Добавлено в избранное!</i>",
        "favorite_removed": "\u274c <i>Удалено из избранного.</i>",
        "favorite_error": "\u26a0\ufe0f <i>Ошибка при обновлении избранного.</i>",
        "history_entry": "\U0001f4c5 {title} \u2014 <i>{date}</i>",
        "history_unknown_book": "Неизвестно",
        "history_page": "\U0001f4cb <b><u>История скачиваний</u></b> <i>(стр. {page}/{total})</i>\n\n",
        "page_format": "<i>Страница</i> <b>{page}/{total}</b>:",
        "page_label": "{page}/{total}",
        "source_annas_archive": "\U0001f4e6 <i>Скачано через Anna's Archive</i>",
        "source_zlibrary": "\U0001f4e5 <i>Скачано через Z-Library (резервный источник)</i>",
        "source_unknown": "\U0001f4e5 <i>Скачано</i>",
        "fallback_trying_zlibrary": "\U0001f50d <i>Anna's Archive ничего не нашёл. Пробую Z-Library как резервный источник...</i>",
        "both_sources_failed": "\U0001f4ed <i>Извините, не удалось найти или скачать эту книгу ни из одного доступного источника. Попробуйте другое название, автора или ISBN.</i>",
    },
}


def get_text(key: str, lang: Optional[str] = None) -> str:
    lang = (lang or EN).lower()
    lang = LANG_TO_UI.get(lang, lang)
    if lang not in TRANSLATIONS:
        lang = EN
    return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS[EN].get(key, key))
