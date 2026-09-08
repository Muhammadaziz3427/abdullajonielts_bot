"""Entry point for the Makhmudov Abdullajon Telegram bot."""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiogram.exceptions import TelegramAPIError
import aiohttp

from config import ADMIN_ID, BOT_TOKEN
from handlers import admin, user
from middlewares.throttling import ThrottlingMiddleware
from utils.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN sozlanmagan.")

    # Initialize SQLite database and run migrations
    await init_db()
    logger.info("Ma'lumotlar bazasi (SQLite) tayyorlandi.")

    proxy = os.getenv("PROXY_URL")
    # Auto-detect PythonAnywhere environment
    if not proxy and ("PYTHONANYWHERE_DOMAIN" in os.environ or "PYTHONANYWHERE_SITE" in os.environ or os.path.exists("/home/abdullajonbot")):
        proxy = "http://proxy.server:3128"

    max_attempts = 5
    base_delay = 0.5
    for attempt in range(max_attempts):
        try:
            if proxy:
                if attempt == 0:
                    logger.info("Proxy orqali ulanish: %s", proxy)
                from aiogram.client.session.aiohttp import AiohttpSession
                session = AiohttpSession(proxy=proxy)
                bot = Bot(token=BOT_TOKEN, session=session)
            else:
                bot = Bot(token=BOT_TOKEN)
            break
        except (aiohttp.ClientError, TelegramAPIError) as e:
            logger.warning("Proxy/session ulanishda xatolik (urinish %s): %s", attempt + 1, e)
            if attempt == max_attempts - 1:
                raise RuntimeError("Bot sessiyasini yaratib bo'lmadi")
            await asyncio.sleep(base_delay * (2 ** attempt))

    dispatcher = Dispatcher()

    # Register anti-spam throttling middleware
    throttling = ThrottlingMiddleware(rate_limit=0.4)
    dispatcher.message.middleware(throttling)
    dispatcher.callback_query.middleware(throttling)

    # Register routers
    dispatcher.include_router(admin.router)
    dispatcher.include_router(user.router)

    # Set bot commands in menu
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Botni ishga tushirish"),
                BotCommand(command="darslar", description="Kurs darslari"),
                BotCommand(command="profil", description="Shaxsiy kabinet"),
                BotCommand(command="reyting", description="Foydalanuvchilar reytingi"),
                BotCommand(command="admin", description="Admin boshqaruv paneli"),
                BotCommand(command="cancel", description="Joriy amalni bekor qilish"),
            ]
        )
    except Exception as e:
        logger.warning("Bot buyruqlarini sozlashda xatolik: %s", e)

    logger.info("Makhmudov Abdullajon bot ishga tushdi")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot to'xtatildi")
