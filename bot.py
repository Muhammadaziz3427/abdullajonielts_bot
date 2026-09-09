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

from typing import Any, Optional, cast
from aiohttp import ClientError, ClientSession, TCPConnector
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType

from config import ADMIN_ID, BOT_TOKEN
from handlers import admin, user
from middlewares.throttling import ThrottlingMiddleware
from utils.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


class PythonAnywhereSession(AiohttpSession):
    """Native aiohttp proxy session tailored for PythonAnywhere free tier with retries."""

    def __init__(self, proxy: str = "http://proxy.server:3128", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pa_proxy = proxy

    async def create_session(self) -> ClientSession:
        if self._should_reset_connector:
            await self.close()

        if self._session is None or self._session.closed:
            self._session = ClientSession(
                connector=TCPConnector(),
                trust_env=True,
            )
            self._should_reset_connector = False

        return self._session

    async def make_request(
        self, bot: Bot, method: TelegramMethod[TelegramType], timeout: Optional[int] = None
    ) -> TelegramType:
        session = await self.create_session()
        url = self.api.api_url(token=bot.token, method=method.__api_method__)
        form = self.build_form_data(bot=bot, method=method)

        last_err: Optional[Exception] = None
        for attempt in range(4):
            try:
                async with session.post(
                    url,
                    data=form,
                    proxy=self._pa_proxy,
                    timeout=self.timeout if timeout is None else timeout,
                ) as resp:
                    raw_result = await resp.text()
                response = self.check_response(
                    bot=bot, method=method, status_code=resp.status, content=raw_result
                )
                return cast(TelegramType, response.result)
            except (asyncio.TimeoutError, ClientError) as e:
                last_err = e
                if attempt < 3:
                    await asyncio.sleep(0.4 * (attempt + 1))

        if isinstance(last_err, asyncio.TimeoutError):
            raise TelegramNetworkError(method=method, message="Request timeout error")
        raise TelegramNetworkError(method=method, message=f"Network error after retries: {last_err}")


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

    if proxy:
        logger.info("PythonAnywhere native proxy orqali ulanish: %s", proxy)
        session = PythonAnywhereSession(proxy=proxy)
        bot = Bot(token=BOT_TOKEN, session=session)
    else:
        bot = Bot(token=BOT_TOKEN)

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
