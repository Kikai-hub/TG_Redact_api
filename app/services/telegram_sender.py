from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo

# Cached per-token so a token change (edited in Settings) takes effect on the
# next call from a Celery worker without restarting the process. The
# long-polling bot process (app/bot/main.py) still needs a restart to pick up
# a new token — that's inherent to an active long-poll connection.
_bots: dict[str, Bot] = {}


def get_bot(token: str) -> Bot:
    bot = _bots.get(token)
    if bot is None:
        bot = Bot(token=token)
        _bots[token] = bot
    return bot


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
    # Telegram only shows the caption on the first item of an album.
    group = []
    for i, item in enumerate(items):
        cls = InputMediaVideo if item["type"] == "video" else InputMediaPhoto
        group.append(
            cls(media=item["url"], caption=caption if i == 0 else None, parse_mode="HTML" if i == 0 else None)
        )
    return group


async def send_moderation_message(
    token: str, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup, media: list | None = None
) -> list[int]:
    """Sends the post to a moderator: single photo/video with caption+buttons
    if there's one media item, the full album followed by a separate message
    carrying the moderation buttons if there are several (Telegram's API does
    not allow reply_markup on a media group), or just text if there's none.
    Returns all sent message IDs."""
    bot = get_bot(token)
    items = _normalize_media(media)

    if not items:
        message = await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
        return [message.message_id]

    if len(items) == 1:
        item = items[0]
        send = bot.send_video if item["type"] == "video" else bot.send_photo
        message = await send(chat_id, item["url"], caption=text, reply_markup=reply_markup, parse_mode="HTML")
        return [message.message_id]

    album_messages = await bot.send_media_group(chat_id, _build_media_group(items, text))
    keyboard_message = await bot.send_message(chat_id, "Действия по посту выше:", reply_markup=reply_markup)
    return [m.message_id for m in album_messages] + [keyboard_message.message_id]


async def publish_to_channel(token: str, chat_id: str, text: str, media: list | None = None) -> None:
    bot = get_bot(token)
    items = _normalize_media(media)

    if not items:
        await bot.send_message(chat_id, text, parse_mode="HTML")
    elif len(items) == 1:
        item = items[0]
        send = bot.send_video if item["type"] == "video" else bot.send_photo
        await send(chat_id, item["url"], caption=text, parse_mode="HTML")
    else:
        await bot.send_media_group(chat_id, _build_media_group(items, text))
