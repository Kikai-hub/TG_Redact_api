import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import router
from app.database import SessionLocal
from app.services import settings_store


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    db = SessionLocal()
    try:
        token = settings_store.get_secret_setting(db, "telegram_bot_token")
    finally:
        db.close()

    if not token:
        raise RuntimeError(
            "Telegram bot token is not configured. Set TELEGRAM_BOT_TOKEN before first boot, or "
            "configure it in the web panel under Settings, then restart this service (`docker compose restart bot`)."
        )

    bot = Bot(token=token)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
