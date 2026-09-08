"""Telegram channel membership checks."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError


logger = logging.getLogger(__name__)


def _chat_id(value: str | int) -> str | int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text) if text.lstrip("-").isdigit() else text


def channel_link(channel_id: str | int | None) -> str:
    """Build a usable join link for public channels."""
    if channel_id is None:
        return "https://t.me/"
    text = str(channel_id).strip()
    if text.startswith("https://t.me/"):
        return text
    if text.startswith("@"):
        return f"https://t.me/{text[1:]}"
    return "https://t.me/"


async def check_subscription(
    bot: Bot, user_id: int, channel_id: str | int
) -> bool:
    """Return true only for current channel members or channel admins."""
    try:
        member: Any = await bot.get_chat_member(
            chat_id=_chat_id(channel_id),
            user_id=user_id,
        )
    except TelegramAPIError as error:
        logger.warning(
            "Kanal obunasini tekshirishda Telegram xatosi: %s", error.__class__.__name__
        )
        return False

    if member.status in {"member", "administrator", "creator"}:
        return True
    return member.status == "restricted" and bool(getattr(member, "is_member", False))
