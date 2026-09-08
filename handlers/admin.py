"""Admin panel handlers implemented entirely inside Telegram."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import ADMIN_ID
from utils.file_manager import (
    get_channel_id,
    load_lessons,
    load_users,
    save_lessons,
    save_settings,
    save_users,
)
from utils.subscription import check_subscription


router = Router(name="admin")
logger = logging.getLogger(__name__)


class LessonCreation(StatesGroup):
    title = State()
    description = State()
    file = State()


class ChannelSettings(StatesGroup):
    channel_id = State()


def _is_admin(user_id: int | None) -> bool:
    return user_id is not None and ADMIN_ID > 0 and user_id == ADMIN_ID


async def _check_admin(message: Message) -> bool:
    if _is_admin(message.from_user.id if message.from_user else None):
        return True
    await message.answer("Bu bo'lim faqat admin uchun.")
    return False


async def _check_admin_callback(callback: CallbackQuery) -> bool:
    if _is_admin(callback.from_user.id if callback.from_user else None):
        return True
    await callback.answer("Bu bo'lim faqat admin uchun.", show_alert=True)
    return False


def _admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Yangi dars qo'shish", callback_data="admin:add"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Darslarni boshqarish", callback_data="admin:list"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Foydalanuvchilar", callback_data="admin:users"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Majburiy kanalni o'zgartirish",
                    callback_data="admin:channel",
                )
            ],
        ]
    )


def _back_to_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Admin panel", callback_data="admin:menu")]
        ]
    )


@router.message(Command("admin"))
async def admin_handler(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return
    await state.clear()
    await message.answer(
        "Admin panelga xush kelibsiz. Kerakli amalni tanlang:",
        reply_markup=_admin_keyboard(),
    )


@router.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Bekor qilinadigan faol amal yo'q.")
        return
    await state.clear()
    await message.answer("Joriy amal bekor qilindi.")


@router.callback_query(F.data == "admin:menu")
async def admin_menu_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Admin panel:", reply_markup=_admin_keyboard()
        )


@router.callback_query(F.data == "admin:add")
async def add_lesson_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return
    await state.set_state(LessonCreation.title)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Yangi dars nomini yuboring.\nBekor qilish uchun /cancel ni yuboring."
        )


@router.message(LessonCreation.title, F.text)
async def lesson_title_handler(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Dars nomi bo'sh bo'lmasligi kerak. Qayta yuboring.")
        return
    await state.update_data(title=title)
    await state.set_state(LessonCreation.description)
    await message.answer("Endi dars tavsifini yuboring.")


@router.message(LessonCreation.description, F.text)
async def lesson_description_handler(message: Message, state: FSMContext) -> None:
    description = (message.text or "").strip()
    if not description:
        await message.answer("Tavsif bo'sh bo'lmasligi kerak. Qayta yuboring.")
        return
    await state.update_data(description=description)
    await state.set_state(LessonCreation.file)
    await message.answer(
        "Endi dars faylini yuboring: video yoki PDF hujjat.\n"
        "Fayl Telegram serverida qoladi, bot esa uning file_id sini saqlaydi."
    )


@router.message(LessonCreation.file, F.video)
async def lesson_video_handler(message: Message, state: FSMContext) -> None:
    if message.video is None:
        return
    data = await state.get_data()
    lesson = {
        "id": uuid.uuid4().hex[:12],
        "title": data["title"],
        "description": data["description"],
        "video_file_id": message.video.file_id,
        "pdf_file_id": None,
    }
    lessons = load_lessons()
    lessons.append(lesson)
    save_lessons(lessons)
    await state.clear()
    await message.answer(
        f"«{lesson['title']}» darsi muvaffaqiyatli qo'shildi.",
        reply_markup=_back_to_admin_keyboard(),
    )


@router.message(LessonCreation.file, F.document)
async def lesson_document_handler(message: Message, state: FSMContext) -> None:
    if message.document is None:
        return
    filename = (message.document.file_name or "").lower()
    mime_type = (message.document.mime_type or "").lower()
    if not filename.endswith(".pdf") and mime_type != "application/pdf":
        await message.answer("Faqat PDF fayl yuboring yoki amalni /cancel bilan bekor qiling.")
        return

    data = await state.get_data()
    lesson = {
        "id": uuid.uuid4().hex[:12],
        "title": data["title"],
        "description": data["description"],
        "video_file_id": None,
        "pdf_file_id": message.document.file_id,
    }
    lessons = load_lessons()
    lessons.append(lesson)
    save_lessons(lessons)
    await state.clear()
    await message.answer(
        f"«{lesson['title']}» darsi muvaffaqiyatli qo'shildi.",
        reply_markup=_back_to_admin_keyboard(),
    )


@router.message(LessonCreation.file)
async def invalid_lesson_file_handler(message: Message) -> None:
    await message.answer("Iltimos, video yoki PDF fayl yuboring.")


@router.callback_query(F.data == "admin:list")
async def lessons_admin_list(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    await callback.answer()
    lessons = load_lessons()
    if callback.message is None:
        return
    if not lessons:
        await callback.message.answer(
            "Hozircha darslar yo'q.", reply_markup=_back_to_admin_keyboard()
        )
        return

    await callback.message.answer("Darslar:")
    for lesson in lessons:
        await callback.message.answer(
            f"{lesson.get('title', 'Nomsiz dars')}\n"
            f"{lesson.get('description', '')}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="O'chirish",
                            callback_data=f"admin:delete:{lesson['id']}",
                        )
                    ]
                ]
            ),
        )
    await callback.message.answer(
        "Boshqa amalni tanlang:", reply_markup=_back_to_admin_keyboard()
    )


@router.callback_query(F.data.startswith("admin:delete:"))
async def delete_lesson(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    if callback.data is None:
        return
    lesson_id = callback.data.split(":", maxsplit=2)[2]
    lessons = load_lessons()
    remaining = [lesson for lesson in lessons if lesson.get("id") != lesson_id]
    await callback.answer(
        "Dars o'chirildi." if len(remaining) < len(lessons) else "Dars topilmadi."
    )
    save_lessons(remaining)


@router.callback_query(F.data == "admin:users")
async def users_admin_list(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    await callback.answer("Ro'yxat yangilanmoqda...")
    users = load_users()
    channel_id = get_channel_id()

    for user_id_text, user in users.items():
        try:
            user_id = int(user_id_text)
        except ValueError:
            continue
        user["is_subscribed"] = bool(
            channel_id and await check_subscription(callback.bot, user_id, channel_id)
        )
    save_users(users)

    if callback.message is None:
        return
    if not users:
        await callback.message.answer(
            "Hozircha foydalanuvchilar yo'q.",
            reply_markup=_back_to_admin_keyboard(),
        )
        return

    lines = ["Foydalanuvchilar ro'yxati:"]
    for user in users.values():
        status = "a'zo" if user.get("is_subscribed") else "a'zo emas"
        username = f"@{user['username']}" if user.get("username") else "username yo'q"
        display_name = user.get("full_name", "Noma'lum")
        lines.append(
            f"{display_name} | {username} | "
            f"ID: {user.get('user_id')} | {status}"
        )

    text = "\n".join(lines)
    for start in range(0, len(text), 3900):
        await callback.message.answer(text[start : start + 3900])
    await callback.message.answer(
        "Boshqa amalni tanlang:", reply_markup=_back_to_admin_keyboard()
    )


@router.callback_query(F.data == "admin:channel")
async def channel_settings_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return
    await state.set_state(ChannelSettings.channel_id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Kanal username yoki ID sini yuboring.\n"
            "Misol: @kanal_nomi yoki -1001234567890\n"
            "Bekor qilish uchun /cancel ni yuboring."
        )


def _normalize_channel_id(value: str) -> str | int | None:
    value = value.strip()
    if value.startswith("https://t.me/"):
        value = "@" + value.removeprefix("https://t.me/").strip("/")
    if value.startswith("@") and len(value) > 1:
        return value
    if value.lstrip("-").isdigit():
        return int(value)
    return None


@router.message(ChannelSettings.channel_id, F.text)
async def channel_settings_handler(message: Message, state: FSMContext) -> None:
    channel_id = _normalize_channel_id(message.text or "")
    if channel_id is None:
        await message.answer(
            "Noto'g'ri kanal manzili. @kanal_nomi yoki -100... ko'rinishida yuboring."
        )
        return
    save_settings({"channel_id": channel_id})
    await state.clear()
    await message.answer(
        f"Majburiy kanal saqlandi: {channel_id}",
        reply_markup=_back_to_admin_keyboard(),
    )
