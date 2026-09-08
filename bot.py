"""Entry point for the Makhmudov Abdullajon Telegram bot."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from config import ADMIN_ID, BOT_TOKEN
from handlers import admin, user
from utils.file_manager import ensure_data_files


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise RuntimeError(
            "BOT_TOKEN sozlanmagan. Replit Secrets bo'limida BOT_TOKEN ni kiriting."
        )
    if ADMIN_ID <= 0:
        raise RuntimeError(
            "ADMIN_ID sozlanmagan. Replit environment variables bo'limida ADMIN_ID ni kiriting."
        )

    ensure_data_files()

    bot = Bot(token=BOT_TOKEN)
    dispatcher = Dispatcher()
    dispatcher.include_router(admin.router)
    dispatcher.include_router(user.router)

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Botni ishga tushirish"),
            BotCommand(command="darslar", description="Darslar ro'yxati"),
            BotCommand(command="admin", description="Admin panel"),
            BotCommand(command="cancel", description="Joriy amalni bekor qilish"),
        ]
    )

    logger.info("Makhmudov Abdullajon bot ishga tushdi")
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot to'xtatildi")
