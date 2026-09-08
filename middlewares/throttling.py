"""Throttling middleware to protect the bot against rapid spam actions."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 0.5) -> None:
        self.rate_limit = rate_limit
        self.user_timestamps: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_id: int | None = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id:
            now = time.time()
            last_time = self.user_timestamps.get(user_id, 0.0)
            if now - last_time < self.rate_limit:
                # Throttled
                if isinstance(event, CallbackQuery):
                    await event.answer("Iltimos, biroz kuting...", show_alert=False)
                return None
            self.user_timestamps[user_id] = now

        return await handler(event, data)
