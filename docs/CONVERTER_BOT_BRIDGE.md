# Library ⇄ Converter bridge (pull via deep link)

Telegram bots cannot forward files to each other: a `file_id` is only valid for
the bot that received the file. The Library bot therefore **pushes** each
downloaded book into a private channel that both bots administer, stores the
resulting `message_id` with the book, and hands the user a deep link. The
Converter bot **pulls** the file with `copyMessage`, which is a server-side copy
and needs no `file_id` exchange.

```
Library bot                       Private channel                Converter bot
-----------                       ---------------                -------------
answer_document(user)  <--copy--  send_document(book)   --copy-->  /start convert_<id>
store message_id in DB                                            copyMessage -> format buttons
button: t.me/Converter?start=convert_<id>
```

## 1. Shared storage channel

1. Create a private channel.
2. Add **both** bots as administrators (post messages is enough).
3. Both bots report the channel id when they are promoted; copy it into
   `STORAGE_CHANNEL_ID` (numeric, e.g. `-1001234567890`).
4. Set the **same** `DEEPLINK_SECRET` in both projects. The Converter bot
   refuses to start with a channel configured and no secret, and rejects
   unsigned payloads, so this is mandatory for the bridge.

## 2. Library bot behaviour

- `bot/utils/storage.py` uploads the file to the channel and returns the
  `message_id`.
- `bot/handlers/book.py` stores that id in `books.storage_message_id` via
  `db.set_book_storage_message(...)`, so the mapping survives restarts and cold
  serverless instances. Repeat downloads reuse the stored copy instead of
  uploading again.
- `bot/utils/deeplink.py` builds
  `https://t.me/<CONVERTER_BOT_USERNAME>?start=convert_<id>[_<signature>]`.
- The Convert button is attached to the delivered file card and to the book
  detail card whenever the book has a stored copy. Books that have never been
  downloaded fall back to the plain bot link (user forwards the file).

`STORAGE_CHANNEL_ID` is optional for the Library bot; without it downloads keep
working and the Convert button still appears, but nothing is pre-loaded.

## 3. Payload format

```
convert_<message_id>                 unsigned (rejected by the converter)
convert_<message_id>_<signature>     HMAC-SHA256(secret, "convert_<id>")[:16]
```

- `message_id`: 1–15 digits.
- Total payload length must stay ≤ 64 characters (Telegram's limit for
  `?start=`).
- Signature is lowercase hex.

Regex:

```python
_CONVERT_PAYLOAD_RE = re.compile(r"^convert_(\d{1,15})(?:_([0-9a-f]{16}))?$")
```

## 4. Converter bot reference handler

The converter bot must ignore a plain `/start` and treat `convert_*` as a pull
request. This is the complete routing logic (aiogram v3 shown; the Python
Telegram Bot version is in the converter project's
`handlers/start_handler.py`):

```python
import hashlib
import hmac
import re

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import DEEPLINK_SECRET, STORAGE_CHANNEL_ID

router = Router()

_PAYLOAD_RE = re.compile(r"^convert_(\d{1,15})(?:_([0-9a-f]{16}))?$")


def parse_convert_payload(payload: str) -> int | None:
    """Return the storage message id, or None when the payload is invalid."""
    if not payload or len(payload) > 64:
        return None

    match = _PAYLOAD_RE.match(payload)
    if not match:
        return None

    message_id = int(match.group(1))
    signature = match.group(2)
    if not DEEPLINK_SECRET or not signature:
        return None

    expected = hmac.new(
        DEEPLINK_SECRET.encode("utf-8"),
        f"convert_{message_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
    if not hmac.compare_digest(signature, expected):
        return None

    return message_id


def format_keyboard() -> InlineKeyboardMarkup:
    # Replace with the formats supported for the pulled file's mime type.
    targets = ["PDF", "EPUB", "DOCX", "TXT"]
    rows = [
        [
            InlineKeyboardButton(
                text=target,
                callback_data=f"convert:{target.lower()}",
            )
            for target in targets[i:i + 3]
        ]
        for i in range(0, len(targets), 3)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text.startswith("/start"))
async def start(message: Message) -> None:
    args = message.text.split(maxsplit=1)
    payload = args[1].strip() if len(args) == 2 else ""

    if not payload.startswith("convert_"):
        await message.answer("Send me a file to convert it.")
        return

    message_id = parse_convert_payload(payload)
    if message_id is None:
        await message.answer(
            "This conversion link is malformed or expired. "
            "Download the book again from the library."
        )
        return

    if not STORAGE_CHANNEL_ID:
        await message.answer("The storage channel is not configured.")
        return

    try:
        # Server-side copy: no file_id crosses bots.
        copied = await message.bot.copy_message(
            chat_id=message.chat.id,
            from_chat_id=STORAGE_CHANNEL_ID,
            message_id=message_id,
        )
    except Exception:
        await message.answer(
            "That file is no longer in storage. Download the book again."
        )
        return

    document = copied.document
    if document is None:
        await message.answer("The stored message is not a file.")
        return

    await message.answer(
        f"Got <b>{document.file_name or 'file'}</b>. Choose a target format:",
        parse_mode="HTML",
        reply_markup=format_keyboard(),
    )


@router.callback_query(F.data.startswith("convert:"))
async def choose_format(callback: CallbackQuery) -> None:
    target = callback.data.split(":", 1)[1]
    await callback.answer(f"Converting to {target.upper()}…")
    # Download the copied file, convert it, and send the result back.
```

Notes:

- `copyMessage` does not download or re-upload the file; it is a single
  Telegram-side hop, so it is fast and works for files up to the channel's
  limits.
- Converting still requires the converter bot to download the copy with
  `getFile`; the cloud Bot API caps that at **20 MB**. A local Bot API server
  removes the cap.
- The file stays in the channel, so the same link can be opened repeatedly
  until the library removes the stored message.

## 5. Verifying the bridge

1. Download a book in the Library bot; the file card must show **🔄 Convert**.
2. Open the book details again; the Convert button must still be there (this
   proves `storage_message_id` was persisted).
3. Tap Convert: the Converter bot should immediately show that book's filename
   and the format buttons.
4. Check `books.storage_message_id` is populated for the downloaded book.
