import asyncio
import mimetypes
import random
from html import escape

import httpx
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo

from app.services.formatting import format_post_text

MEDIA_FETCH_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NewsAggregatorBot/1.0)"}
MEDIA_FETCH_TIMEOUT = 20
MEDIA_MAX_BYTES = 45 * 1024 * 1024  # stay under Telegram's ~50MB bot upload ceiling


def _normalize_media(media: list | None) -> list[dict]:
    """Post.raw_media entries are {"url": str, "type": "photo"|"video"} dicts.
    Also accepts legacy plain URL strings (pre-media-type rows) and treats
    them as photos, matching prior behavior."""
    normalized = []
    for item in media or []:
        if isinstance(item, str):
            normalized.append({"url": item, "type": "photo"})
        else:
            normalized.append({"url": item["url"], "type": item.get("type", "photo")})
    return normalized


def _build_media_group(items: list[dict], caption: str):
    # Telegram only shows the caption on the first item of an album. Each item's
    # "file" key (set by _redownload_for_album), when present, takes priority over
    # its "url" — that's how a re-uploaded item is threaded back into the album.
    group = []
    for i, item in enumerate(items):
        cls = InputMediaVideo if item["type"] == "video" else InputMediaPhoto
        group.append(
            cls(
                media=item.get("file", item["url"]),
                caption=caption if i == 0 else None,
                parse_mode="HTML" if i == 0 else None,
            )
        )
    return group


def _dropped(item: dict, exc: Exception) -> dict:
    return {"url": item["url"], "type": item["type"], "error": str(exc)}


async def _download_media(url: str) -> BufferedInputFile | None:
    """Fetches a media URL ourselves and hands Telegram the raw bytes instead
    of asking its Bot API to fetch the URL server-side. Telegram's own
    fetcher sometimes can't retrieve/classify a URL a plain HTTP client has
    no trouble with (e.g. rate limits its own IPs differently, stricter
    timeouts) — that's the "wrong type of the web page content" class of
    error. Returns None if the URL isn't reachable or doesn't look like
    actual media, letting the caller fall back to dropping the item."""
    try:
        async with httpx.AsyncClient(timeout=MEDIA_FETCH_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, headers=MEDIA_FETCH_HEADERS)
        response.raise_for_status()
    except httpx.HTTPError:
        return None

    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    if not (content_type.startswith("image/") or content_type.startswith("video/")):
        return None
    if not response.content or len(response.content) > MEDIA_MAX_BYTES:
        return None

    extension = mimetypes.guess_extension(content_type) or ""
    return BufferedInputFile(response.content, filename=f"media{extension}")


async def _send_one(send, chat_id: int, item: dict, caption: str | None, reply_markup=None):
    """Tries the scraped URL directly first (cheap, works for the vast
    majority of directly-hosted media), then falls back to downloading the
    file ourselves and re-uploading its bytes if Telegram rejects the URL.
    Returns (message, None) on success or (None, last_exception) if both
    attempts failed."""
    try:
        message = await send(
            chat_id, item["url"], caption=caption, reply_markup=reply_markup, parse_mode="HTML" if caption else None
        )
        return message, None
    except TelegramBadRequest as exc:
        error: Exception = exc

    input_file = await _download_media(item["url"])
    if input_file is None:
        return None, error

    try:
        message = await send(
            chat_id, input_file, caption=caption, reply_markup=reply_markup, parse_mode="HTML" if caption else None
        )
        return message, None
    except TelegramBadRequest as exc:
        return None, exc


async def _redownload_for_album(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Used when Telegram rejects the whole album while fetching item URLs
    itself — the single most common reason sendMediaGroup fails wholesale for
    scraped news images (hotlink protection, unusual user-agent checks, rate
    limiting Telegram's own fetcher differently — see _download_media).
    Downloads every item's bytes ourselves in parallel so the album can be
    retried without relying on Telegram's server-side fetch. Items that can't
    be downloaded at all are dropped instead of blocking the rest of the
    album. Returns (items-with-"file"-key, dropped)."""
    files = await asyncio.gather(*(_download_media(item["url"]) for item in items))
    successful: list[dict] = []
    dropped: list[dict] = []
    for item, input_file in zip(items, files):
        if input_file is None:
            dropped.append(_dropped(item, RuntimeError("media unreachable for re-upload")))
        else:
            successful.append({**item, "file": input_file})
    return successful, dropped


async def _send_album_with_fallback(
    bot: Bot, chat_id: int, text: str, items: list[dict]
) -> tuple[list[int], list[dict]]:
    """sendMediaGroup fails as a whole if even one item is bad — Telegram gives no
    per-item indication of which — so on failure this re-downloads every item's
    bytes ourselves and retries the album with those instead of Telegram fetching
    the URLs itself, dropping only whichever items truly can't be fetched at all.
    Only if that retry still leaves fewer than two items (or itself fails) does
    this give up on grouping and fall back to sending items one-by-one."""
    try:
        album_messages = await bot.send_media_group(chat_id, _build_media_group(items, text))
        return [m.message_id for m in album_messages], []
    except TelegramBadRequest:
        pass

    downloaded, dropped = await _redownload_for_album(items)
    if len(downloaded) >= 2:
        try:
            album_messages = await bot.send_media_group(chat_id, _build_media_group(downloaded, text))
            return [m.message_id for m in album_messages], dropped
        except TelegramBadRequest:
            pass

    message_ids: list[int] = []
    dropped = []
    for item in items:
        send = bot.send_video if item["type"] == "video" else bot.send_photo
        caption = text if not message_ids else None
        message, error = await _send_one(send, chat_id, item, caption)
        if message is not None:
            message_ids.append(message.message_id)
        else:
            dropped.append(_dropped(item, error))

    if not message_ids:
        message = await bot.send_message(chat_id, text, parse_mode="HTML")
        message_ids.append(message.message_id)

    return message_ids, dropped


async def _send_post(
    bot: Bot, chat_id: int, text: str, items: list[dict], reply_markup: InlineKeyboardMarkup | None
) -> tuple[list[int], list[dict]]:
    """Sends text + media as single photo/video/album depending on item count —
    same shape as before, but a media item Telegram's Bot API rejects when
    fetching the URL itself (e.g. "wrong type of the web page content") gets
    one more try via _send_one's download-and-reupload fallback before being
    dropped, so the post keeps its media in the common case instead of losing
    it. Returns (message_ids, dropped) — dropped is empty unless an item
    failed both attempts."""
    if not items:
        message = await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
        return [message.message_id], []

    if len(items) == 1:
        item = items[0]
        send = bot.send_video if item["type"] == "video" else bot.send_photo
        message, error = await _send_one(send, chat_id, item, text, reply_markup)
        if message is not None:
            return [message.message_id], []
        fallback = await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
        return [fallback.message_id], [_dropped(item, error)]

    message_ids, dropped = await _send_album_with_fallback(bot, chat_id, text, items)
    if reply_markup is not None:
        keyboard_message = await bot.send_message(chat_id, "Действия по посту выше:", reply_markup=reply_markup)
        message_ids.append(keyboard_message.message_id)
    return message_ids, dropped


async def _pick_custom_emoji_id(bot: Bot, pack_name: str, emoji: str) -> str | None:
    """Custom emoji packs (t.me/addemoji/<name>) are fetched the same way as
    sticker packs — Bot API represents them as a StickerSet with
    sticker_type="custom_emoji" — but what we need out of each entry is
    custom_emoji_id, not file_id (custom emoji aren't sent as standalone
    messages the way regular stickers are)."""
    try:
        emoji_set = await bot.get_sticker_set(pack_name)
    except Exception:
        return None
    matches = [s.custom_emoji_id for s in emoji_set.stickers if s.emoji == emoji and s.custom_emoji_id]
    return random.choice(matches) if matches else None


async def _resolve_mood_emoji_html(bot: Bot, emoji_pack_name: str | None, mood_emoji: str | None) -> str | None:
    """Looks up a custom emoji from the admin-configured pack (Settings →
    emoji_pack_name) whose associated emoji matches the AI's "mood_emoji"
    field, and returns Telegram's <tg-emoji> HTML snippet for it — a real
    custom emoji "подстать комментарию" embedded right in the post text, not
    just the plain emoji character. Bots have been able to send custom emoji
    this way since Bot API 6.4 regardless of whether the bot account itself
    has Telegram Premium; viewers without Premium just see the fallback
    character in the tag body. Best-effort and silent on any failure (pack
    not configured, pack not found, no entry with that emoji) — this is a
    cosmetic flourish, never worth blocking or failing the post over."""
    if not emoji_pack_name or not mood_emoji:
        return None
    custom_emoji_id = await _pick_custom_emoji_id(bot, emoji_pack_name, mood_emoji)
    if custom_emoji_id is None:
        return None
    return f'<tg-emoji emoji-id="{custom_emoji_id}">{escape(mood_emoji)}</tg-emoji>'


async def send_moderation_message(
    token: str,
    chat_id: int,
    ai_data: dict,
    reply_markup: InlineKeyboardMarkup | None = None,
    media: list | None = None,
    emoji_pack_name: str | None = None,
) -> tuple[list[int], list[dict]]:
    """Sends the post to a moderator: single photo/video with caption+buttons
    if there's one media item, the full album followed by a separate message
    carrying the moderation buttons if there are several (Telegram's API does
    not allow reply_markup on a media group), or just text if there's none.
    Returns (message_ids, dropped) — see _send_post for what "dropped" means.

    reply_markup may be None for a read-only preview (e.g. a scheduled post
    opened from the "Отложка" list, where the moderation buttons don't apply
    anymore) — in the album case, the follow-up buttons message is skipped
    entirely rather than sent with no buttons on it.

    Takes the raw AI JSON (ai_data) rather than a pre-built string — the
    matching custom emoji (see _resolve_mood_emoji_html, needs a live Bot to
    look up) has to be resolved before format_post_text builds the final
    text, since it's rendered onto the comment line, not appended after.

    Opens a fresh Bot (and aiohttp session) per call rather than reusing a
    cached one: callers on the Celery side wrap this in a new asyncio.run()
    per task, which closes its event loop when done, and a session left over
    from a previous call would be bound to that now-closed loop."""
    items = _normalize_media(media)
    bot = Bot(token=token)
    try:
        mood_html = await _resolve_mood_emoji_html(bot, emoji_pack_name, ai_data.get("mood_emoji"))
        text = format_post_text(ai_data, mood_html)
        return await _send_post(bot, chat_id, text, items, reply_markup)
    finally:
        await bot.session.close()


async def publish_to_channel(
    token: str,
    chat_id: str,
    ai_data: dict,
    media: list | None = None,
    emoji_pack_name: str | None = None,
) -> list[dict]:
    """Returns the list of media items Telegram rejected (see _send_post) —
    empty if the post published with all its media intact."""
    items = _normalize_media(media)
    bot = Bot(token=token)
    try:
        mood_html = await _resolve_mood_emoji_html(bot, emoji_pack_name, ai_data.get("mood_emoji"))
        text = format_post_text(ai_data, mood_html)
        _message_ids, dropped = await _send_post(bot, chat_id, text, items, reply_markup=None)
        return dropped
    finally:
        await bot.session.close()
