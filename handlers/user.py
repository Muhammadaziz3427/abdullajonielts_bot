"""User-facing Telegram handlers."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from utils.file_manager import (
    get_channel_id,
    load_lessons,
    upsert_user,
)
from utils.subscription import channel_link, check_subscription


router = Router(name="user")
logger = logging.getLogger(__name__)


def _subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Kanalga a'zo bo'lish",
                    url=channel_link(get_channel_id()),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Obunani tekshirish",
                    callback_data="check_subscription",
                )
            ],
        ]
    )


async def _subscription_gate(message: Message) -> bool:
    """Record the user and prevent all protected content before subscription."""
    if message.from_user is None:
        return False

    channel_id = get_channel_id()
    if not channel_id:
        await message.answer(
            "Majburiy kanal hali sozlanmagan. Iltimos, keyinroq qayta urinib ko'ring."
        )
        return False

    subscribed = await check_subscription(message.bot, message.from_user.id, channel_id)
    upsert_user(message.from_user, subscribed)

    if not subscribed:
        await message.answer(
            "Botdan foydalanish uchun avval kanalga a'zo bo'ling.\n"
            "A'zo bo'lgach, «Obunani tekshirish» tugmasini bosing.",
            reply_markup=_subscription_keyboard(),
        )
        return False
    return True


def _lessons_keyboard(lessons: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=str(lesson.get("title", "Nomsiz dars")),
                    callback_data=f"lesson:{lesson['id']}",
                )
            ]
            for lesson in lessons
        ]
    )


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    if await _subscription_gate(message):
        await message.answer(
            "Assalomu alaykum. «Makhmudov Abdullajon» botiga xush kelibsiz.\n\n"
            "Darslar ro'yxatini ko'rish uchun /darslar buyrug'ini yuboring."
        )


@router.callback_query(F.data == "check_subscription")
async def check_subscription_handler(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return

    channel_id = get_channel_id()
    if not channel_id:
        await callback.message.answer(
            "Majburiy kanal hali sozlanmagan. Iltimos, keyinroq qayta urinib ko'ring."
        )
        return

    subscribed = bool(
        await check_subscription(callback.bot, callback.from_user.id, channel_id)
    )
    upsert_user(callback.from_user, subscribed)

    if not subscribed:
        await callback.message.answer(
            "Siz hali kanalga a'zo bo'lmagansiz yoki a'zolik hali tasdiqlanmadi.",
            reply_markup=_subscription_keyboard(),
        )
        return

    await callback.message.answer(
        "Obuna tasdiqlandi. Endi /darslar buyrug'i orqali darslarni ko'rishingiz mumkin."
    )


@router.message(Command("darslar"))
async def lessons_handler(message: Message) -> None:
    if not await _subscription_gate(message):
        return

    lessons = load_lessons()
    if not lessons:
        await message.answer("Hozircha darslar qo'shilmagan.")
        return

    await message.answer(
        "Kerakli darsni tanlang:",
        reply_markup=_lessons_keyboard(lessons),
    )


@router.callback_query(F.data.startswith("lesson:"))
async def lesson_handler(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None or callback.from_user is None or callback.data is None:
        return

    channel_id = get_channel_id()
    subscribed = bool(
        channel_id
        and await check_subscription(callback.bot, callback.from_user.id, channel_id)
    )
    upsert_user(callback.from_user, subscribed)
    if not subscribed:
        await callback.message.answer(
            "Darsni olish uchun kanalga a'zo bo'lishingiz shart.",
            reply_markup=_subscription_keyboard(),
        )
        return

    lesson_id = callback.data.split(":", maxsplit=1)[1]
    lesson = next((item for item in load_lessons() if item.get("id") == lesson_id), None)
    if lesson is None:
        await callback.message.answer("Bu dars topilmadi yoki o'chirilgan.")
        return

    title = str(lesson.get("title", "Dars"))
    description = str(lesson.get("description", "")).strip()
    caption = f"{title}\n\n{description}".strip()

    video_file_id = lesson.get("video_file_id")
    pdf_file_id = lesson.get("pdf_file_id")
    if video_file_id:
        await callback.message.answer_video(video=video_file_id, caption=caption)
    if pdf_file_id:
        await callback.message.answer_document(document=pdf_file_id, caption=caption)
    if not video_file_id and not pdf_file_id:
        logger.error("Fayl ID si yo'q dars tanlandi: %s", lesson_id)
        await callback.message.answer("Bu dars uchun fayl mavjud emas.")
