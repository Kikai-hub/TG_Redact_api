from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InputMediaPhoto

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


async def send_moderation_message(
    token: str, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup, media: list[str] | None = None
) -> int:
    bot = get_bot(token)
    if media:
        message = await bot.send_photo(
            chat_id, media[0], caption=text, reply_markup=reply_markup, parse_mode="HTML"
        )
    else:
        message = await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
    return message.message_id


async def publish_to_channel(token: str, chat_id: str, text: str, media: list[str] | None = None) -> None:
    bot = get_bot(token)
    if not media:
        await bot.send_message(chat_id, text, parse_mode="HTML")
    elif len(media) == 1:
        await bot.send_photo(chat_id, media[0], caption=text, parse_mode="HTML")
    else:
        album = [
            InputMediaPhoto(media=url, caption=text if i == 0 else None, parse_mode="HTML" if i == 0 else None)
            for i, url in enumerate(media)
        ]
        await bot.send_media_group(chat_id, album)
