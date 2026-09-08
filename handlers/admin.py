"""Complete Telegram-only admin control panel."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
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
    count_user_statuses,
    get_required_channels,
    get_required_invites,
    get_referral_channel,
    get_settings,
    get_user_referral_count,
    is_maintenance_mode,
    load_lessons,
    load_users,
    save_lessons,
    save_settings,
    save_users,
    set_user_banned,
)
from utils.subscription import check_required_subscriptions, join_link_for_channel


router = Router(name="admin")
logger = logging.getLogger(__name__)


class LessonCreation(StatesGroup):
    title = State()
    description = State()
    file = State()


class LessonEdit(StatesGroup):
    title = State()
    description = State()
    file = State()


class ChannelCreation(StatesGroup):
    channel_id = State()
    title = State()
    link = State()


class NumberSetting(StatesGroup):
    value = State()


class TextSetting(StatesGroup):
    value = State()


class BroadcastState(StatesGroup):
    text = State()


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
                    text="Dashboard / statistika", callback_data="admin:dashboard"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Darslarni boshqarish", callback_data="admin:lessons"
                ),
                InlineKeyboardButton(
                    text="Yangi dars", callback_data="admin:add_lesson"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Foydalanuvchilar", callback_data="admin:users"
                ),
                InlineKeyboardButton(
                    text="Xabar yuborish", callback_data="admin:broadcast"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Obuna va taklif sozlamalari",
                    callback_data="admin:settings",
                )
            ],
        ]
    )


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Admin panel", callback_data="admin:menu")]
        ]
    )


def _settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Kanal qo'shish", callback_data="admin:channel:add"
                ),
                InlineKeyboardButton(
                    text="Kanallar ro'yxati", callback_data="admin:channel:list"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Majburiy takliflar soni", callback_data="admin:invites"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Referral kanalini tanlash",
                    callback_data="admin:referral_channel",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Texnik xizmat rejimi", callback_data="admin:maintenance"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Xush kelibsiz matni", callback_data="admin:welcome"
                ),
                InlineKeyboardButton(
                    text="Obuna matni", callback_data="admin:subscription_text"
                ),
            ],
            [InlineKeyboardButton(text="Admin panel", callback_data="admin:menu")],
        ]
    )


def _lesson_actions(lesson_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Tahrirlash",
                    callback_data=f"admin:lesson:edit:{lesson_id}",
                ),
                InlineKeyboardButton(
                    text="O'chirish",
                    callback_data=f"admin:lesson:delete:{lesson_id}",
                ),
            ]
        ]
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


def _save_channels(channels: list[dict[str, Any]]) -> None:
    settings = get_settings()
    settings["required_channels"] = channels
    settings["channel_id"] = channels[0]["channel_id"] if channels else ""
    save_settings(settings)


def _setting_text(key: str, default: str) -> str:
    return str(get_settings().get(key, default))


@router.message(Command("admin"))
async def admin_handler(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return
    await state.clear()
    await message.answer(
        "To'liq admin panel. Barcha bot sozlamalari shu yerdan boshqariladi:",
        reply_markup=_admin_keyboard(),
    )


@router.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Bekor qilinadigan faol amal yo'q.")
        return
    await state.clear()
    await message.answer("Joriy amal bekor qilindi.", reply_markup=_back_keyboard())


@router.callback_query(F.data == "admin:menu")
async def admin_menu_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.answer("Admin panel:", reply_markup=_admin_keyboard())


@router.callback_query(F.data == "admin:dashboard")
async def dashboard_callback(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    await callback.answer()
    total, subscribed, banned = count_user_statuses()
    settings = get_settings()
    lessons = load_lessons()
    channels = get_required_channels()
    await callback.message.answer(
        "BOT DASHBOARD\n\n"
        f"Jami foydalanuvchilar: {total}\n"
        f"Obunasi tasdiqlangan: {subscribed}\n"
        f"Bloklanganlar: {banned}\n"
        f"Darslar: {len(lessons)}\n"
        f"Majburiy kanallar: {len(channels)}\n"
        f"Majburiy takliflar: {get_required_invites()} ta\n"
        f"Texnik xizmat: {'yoqilgan' if settings.get('maintenance_mode') else 'o‘chirilgan'}",
        reply_markup=_back_keyboard(),
    )


@router.callback_query(F.data == "admin:settings")
async def settings_callback(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    await callback.answer()
    settings = get_settings()
    await callback.message.answer(
        "Obuna va umumiy sozlamalar:\n\n"
        f"Majburiy kanallar: {len(get_required_channels())} ta\n"
        f"Har bir foydalanuvchi taklif qilishi kerak: {get_required_invites()} ta\n"
        f"Referral kanali: {(get_referral_channel() or {}).get('title', 'tanlanmagan')}\n"
        f"Texnik xizmat: {'yoqilgan' if settings.get('maintenance_mode') else 'o‘chirilgan'}",
        reply_markup=_settings_keyboard(),
    )


@router.callback_query(F.data == "admin:lessons")
async def lessons_admin_list(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    await callback.answer()
    lessons = load_lessons()
    if not lessons:
        await callback.message.answer(
            "Hozircha darslar yo'q.", reply_markup=_back_keyboard()
        )
        return
    await callback.message.answer("Darslar ro'yxati:")
    for lesson in lessons:
        await callback.message.answer(
            f"📚 {lesson.get('title', 'Nomsiz dars')}\n"
            f"{lesson.get('description', '')}",
            reply_markup=_lesson_actions(str(lesson["id"])),
        )
    await callback.message.answer("Boshqa amalni tanlang:", reply_markup=_back_keyboard())


@router.callback_query(F.data == "admin:add_lesson")
async def add_lesson_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return
    await state.set_state(LessonCreation.title)
    await callback.answer()
    await callback.message.answer(
        "Yangi dars nomini yuboring.\nBekor qilish uchun /cancel."
    )


@router.message(LessonCreation.title, F.text)
async def lesson_title_handler(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Dars nomi bo'sh bo'lmasligi kerak.")
        return
    await state.update_data(title=title)
    await state.set_state(LessonCreation.description)
    await message.answer("Dars tavsifini yuboring.")


@router.message(LessonCreation.description, F.text)
async def lesson_description_handler(message: Message, state: FSMContext) -> None:
    description = (message.text or "").strip()
    if not description:
        await message.answer("Tavsif bo'sh bo'lmasligi kerak.")
        return
    await state.update_data(description=description)
    await state.set_state(LessonCreation.file)
    await message.answer("Video yoki PDF fayl yuboring.")


async def _save_new_lesson(message: Message, state: FSMContext, file_data: dict[str, Any]) -> None:
    data = await state.get_data()
    lesson = {
        "id": uuid.uuid4().hex[:12],
        "title": data["title"],
        "description": data["description"],
        "video_file_id": file_data.get("video_file_id"),
        "pdf_file_id": file_data.get("pdf_file_id"),
    }
    lessons = load_lessons()
    lessons.append(lesson)
    save_lessons(lessons)
    await state.clear()
    await message.answer(
        f"«{lesson['title']}» darsi qo'shildi.", reply_markup=_back_keyboard()
    )


@router.message(LessonCreation.file, F.video)
async def lesson_video_handler(message: Message, state: FSMContext) -> None:
    if message.video:
        await _save_new_lesson(
            message, state, {"video_file_id": message.video.file_id}
        )


@router.message(LessonCreation.file, F.document)
async def lesson_document_handler(message: Message, state: FSMContext) -> None:
    if not message.document:
        return
    filename = (message.document.file_name or "").lower()
    mime_type = (message.document.mime_type or "").lower()
    if not filename.endswith(".pdf") and mime_type != "application/pdf":
        await message.answer("Faqat PDF fayl yuboring.")
        return
    await _save_new_lesson(
        message, state, {"pdf_file_id": message.document.file_id}
    )


@router.message(LessonCreation.file)
async def invalid_lesson_file_handler(message: Message) -> None:
    await message.answer("Iltimos, video yoki PDF fayl yuboring.")


@router.callback_query(F.data.startswith("admin:lesson:delete:"))
async def delete_lesson(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    lesson_id = (callback.data or "").split(":", maxsplit=3)[3]
    lessons = load_lessons()
    remaining = [lesson for lesson in lessons if lesson.get("id") != lesson_id]
    save_lessons(remaining)
    await callback.answer(
        "Dars o'chirildi." if len(remaining) < len(lessons) else "Dars topilmadi."
    )


@router.callback_query(F.data.startswith("admin:lesson:edit:"))
async def edit_lesson_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return
    lesson_id = (callback.data or "").split(":", maxsplit=3)[3]
    if not any(item.get("id") == lesson_id for item in load_lessons()):
        await callback.answer("Dars topilmadi.", show_alert=True)
        return
    await state.update_data(lesson_id=lesson_id)
    await state.set_state(LessonEdit.title)
    await callback.answer()
    await callback.message.answer(
        "Yangi nomni yuboring yoki o'zgartirmaslik uchun /skip yuboring."
    )


@router.message(LessonEdit.title, F.text)
async def edit_lesson_title(message: Message, state: FSMContext) -> None:
    if message.text != "/skip":
        value = (message.text or "").strip()
        if not value:
            await message.answer("Nom bo'sh bo'lmasligi kerak.")
            return
        await state.update_data(title=value)
    await state.set_state(LessonEdit.description)
    await message.answer("Yangi tavsifni yuboring yoki /skip.")


@router.message(LessonEdit.description, F.text)
async def edit_lesson_description(message: Message, state: FSMContext) -> None:
    if message.text != "/skip":
        value = (message.text or "").strip()
        if not value:
            await message.answer("Tavsif bo'sh bo'lmasligi kerak.")
            return
        await state.update_data(description=value)
    await state.set_state(LessonEdit.file)
    await message.answer("Yangi video/PDF yuboring yoki faylni saqlash uchun /skip.")


async def _finish_lesson_edit(
    message: Message, state: FSMContext, file_data: dict[str, Any] | None = None
) -> None:
    data = await state.get_data()
    lessons = load_lessons()
    for lesson in lessons:
        if lesson.get("id") == data.get("lesson_id"):
            if "title" in data:
                lesson["title"] = data["title"]
            if "description" in data:
                lesson["description"] = data["description"]
            if file_data:
                lesson["video_file_id"] = file_data.get("video_file_id")
                lesson["pdf_file_id"] = file_data.get("pdf_file_id")
            save_lessons(lessons)
            await state.clear()
            await message.answer("Dars yangilandi.", reply_markup=_back_keyboard())
            return
    await state.clear()
    await message.answer("Dars topilmadi.")


@router.message(LessonEdit.file, F.video)
async def edit_lesson_video(message: Message, state: FSMContext) -> None:
    if message.video:
        await _finish_lesson_edit(
            message, state, {"video_file_id": message.video.file_id}
        )


@router.message(LessonEdit.file, F.document)
async def edit_lesson_document(message: Message, state: FSMContext) -> None:
    if not message.document:
        return
    if not (
        (message.document.file_name or "").lower().endswith(".pdf")
        or (message.document.mime_type or "").lower() == "application/pdf"
    ):
        await message.answer("Faqat PDF fayl yuboring.")
        return
    await _finish_lesson_edit(
        message, state, {"pdf_file_id": message.document.file_id}
    )


@router.message(LessonEdit.file, F.text)
async def edit_lesson_skip_file(message: Message, state: FSMContext) -> None:
    if message.text == "/skip":
        await _finish_lesson_edit(message, state)
    else:
        await message.answer("Video/PDF yuboring yoki /skip.")


@router.callback_query(F.data == "admin:users")
async def users_admin_list(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    await callback.answer("Ro'yxat yangilanmoqda...")
    users = load_users()
    channels = get_required_channels()
    for user_id_text, user in users.items():
        try:
            user_id = int(user_id_text)
        except ValueError:
            continue
        user["is_subscribed"] = (
            await check_required_subscriptions(callback.bot, user_id, channels)
        )[0]
    save_users(users)

    total, subscribed, banned = count_user_statuses()
    await callback.message.answer(
        f"Foydalanuvchilar: {total} ta\n"
        f"Obunasi tasdiqlangan: {subscribed} ta\n"
        f"Bloklangan: {banned} ta"
    )
    for user_id_text, user in list(users.items())[:50]:
        username = f"@{user['username']}" if user.get("username") else "username yo'q"
        status = "a'zo" if user.get("is_subscribed") else "a'zo emas"
        banned_status = " | BLOKLANGAN" if user.get("is_banned") else ""
        await callback.message.answer(
            f"{user.get('full_name', 'Nomaʼlum')} | {username}\n"
            f"ID: {user_id_text} | {status}{banned_status}\n"
            f"Takliflari: {user.get('referral_count', 0)} ta",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Blokdan chiqarish"
                            if user.get("is_banned")
                            else "Bloklash",
                            callback_data=f"admin:user:toggle:{user_id_text}",
                        )
                    ]
                ]
            ),
        )
    await callback.message.answer("Admin panel:", reply_markup=_back_keyboard())


@router.callback_query(F.data.startswith("admin:user:toggle:"))
async def toggle_user_ban(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    user_id_text = (callback.data or "").split(":", maxsplit=3)[3]
    users = load_users()
    if user_id_text not in users:
        await callback.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return
    new_value = not bool(users[user_id_text].get("is_banned"))
    set_user_banned(int(user_id_text), new_value)
    await callback.answer("Foydalanuvchi holati yangilandi.")


@router.callback_query(F.data == "admin:broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return
    await state.set_state(BroadcastState.text)
    await callback.answer()
    await callback.message.answer(
        "Barcha bloklanmagan foydalanuvchilarga yuboriladigan xabarni yozing."
    )


@router.message(BroadcastState.text, F.text)
async def broadcast_handler(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Xabar bo'sh bo'lmasligi kerak.")
        return
    sent = 0
    failed = 0
    for user_id_text, user in load_users().items():
        if user.get("is_banned"):
            continue
        try:
            await message.bot.send_message(int(user_id_text), text)
            sent += 1
            await asyncio.sleep(0.05)
        except (TelegramAPIError, ValueError):
            failed += 1
    await state.clear()
    await message.answer(
        f"Xabar yuborildi.\nYetkazildi: {sent} ta\nXato: {failed} ta",
        reply_markup=_back_keyboard(),
    )


@router.callback_query(F.data == "admin:channel:add")
async def channel_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return
    await state.set_state(ChannelCreation.channel_id)
    await callback.answer()
    await callback.message.answer(
        "Kanal username yoki ID sini yuboring.\n"
        "Misol: @kanal_nomi yoki -1001234567890"
    )


@router.message(ChannelCreation.channel_id, F.text)
async def channel_id_handler(message: Message, state: FSMContext) -> None:
    channel_id = _normalize_channel_id(message.text or "")
    if channel_id is None:
        await message.answer("@kanal_nomi yoki -100... ko'rinishida yuboring.")
        return
    await state.update_data(channel_id=channel_id)
    await state.set_state(ChannelCreation.title)
    await message.answer("Kanal nomini yuboring yoki /skip.")


@router.message(ChannelCreation.title, F.text)
async def channel_title_handler(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if title == "/skip":
        title = str((await state.get_data())["channel_id"])
    if not title:
        await message.answer("Kanal nomi bo'sh bo'lmasin.")
        return
    await state.update_data(title=title)
    await state.set_state(ChannelCreation.link)
    await message.answer(
        "Kanalga kirish havolasini yuboring yoki public kanal bo'lsa /skip."
    )


@router.message(ChannelCreation.link, F.text)
async def channel_link_handler(message: Message, state: FSMContext) -> None:
    link = (message.text or "").strip()
    if link == "/skip":
        link = ""
    elif not link.startswith(("https://t.me/", "http://t.me/")):
        await message.answer("Havola https://t.me/... ko'rinishida bo'lishi kerak.")
        return
    data = await state.get_data()
    channels = get_required_channels()
    channels.append(
        {
            "channel_id": data["channel_id"],
            "title": data["title"],
            "join_link": link,
        }
    )
    _save_channels(channels)
    await state.clear()
    await message.answer("Majburiy kanal qo'shildi.", reply_markup=_settings_keyboard())


@router.callback_query(F.data == "admin:channel:list")
async def channel_list_callback(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    await callback.answer()
    channels = get_required_channels()
    if not channels:
        await callback.message.answer(
            "Majburiy kanallar sozlanmagan.", reply_markup=_settings_keyboard()
        )
        return
    await callback.message.answer("Majburiy kanallar:")
    for index, channel in enumerate(channels):
        await callback.message.answer(
            f"{index + 1}. {channel.get('title')} — {channel.get('channel_id')}\n"
            f"Havola: {join_link_for_channel(channel)}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="O'chirish",
                            callback_data=f"admin:channel:delete:{index}",
                        )
                    ]
                ]
            ),
        )
    await callback.message.answer("Sozlamalar:", reply_markup=_settings_keyboard())


@router.callback_query(F.data.startswith("admin:channel:delete:"))
async def channel_delete_callback(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    try:
        index = int((callback.data or "").split(":", maxsplit=3)[3])
    except ValueError:
        await callback.answer("Noto'g'ri kanal.", show_alert=True)
        return
    channels = get_required_channels()
    if index < 0 or index >= len(channels):
        await callback.answer("Kanal topilmadi.", show_alert=True)
        return
    channels.pop(index)
    _save_channels(channels)
    await callback.answer("Kanal o'chirildi.")


@router.callback_query(F.data == "admin:invites")
async def invites_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return
    await state.set_state(NumberSetting.value)
    await state.update_data(setting_key="required_invites")
    await callback.answer()
    await callback.message.answer(
        f"Har bir foydalanuvchi nechta odam taklif qilishi shart?\n"
        f"Hozirgi qiymat: {get_required_invites()}.\n"
        "0 yuborsangiz, bu talab o'chadi."
    )


@router.callback_query(F.data == "admin:referral_channel")
async def referral_channel_start(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    channels = get_required_channels()
    if not channels:
        await callback.answer("Avval kamida bitta majburiy kanal qo'shing.", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(
        "Referral hisobiga tushadigan kanalni tanlang:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=str(channel.get("title")),
                        callback_data=f"admin:referral:set:{index}",
                    )
                ]
                for index, channel in enumerate(channels)
            ]
            + [[InlineKeyboardButton(text="Orqaga", callback_data="admin:settings")]]
        ),
    )


@router.callback_query(F.data.startswith("admin:referral:set:"))
async def referral_channel_set(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    try:
        index = int((callback.data or "").split(":", maxsplit=3)[3])
    except ValueError:
        await callback.answer("Noto'g'ri kanal.", show_alert=True)
        return
    channels = get_required_channels()
    if index < 0 or index >= len(channels):
        await callback.answer("Kanal topilmadi.", show_alert=True)
        return
    settings = get_settings()
    settings["referral_channel_id"] = channels[index]["channel_id"]
    save_settings(settings)
    await callback.answer("Referral kanali saqlandi.")
    await callback.message.answer(
        f"Referral kanali: {channels[index].get('title')}",
        reply_markup=_settings_keyboard(),
    )


@router.message(NumberSetting.value, F.text)
async def number_setting_handler(message: Message, state: FSMContext) -> None:
    try:
        value = int((message.text or "").strip())
        if value < 0:
            raise ValueError
    except ValueError:
        await message.answer("Faqat 0 yoki undan katta butun son yuboring.")
        return
    data = await state.get_data()
    settings = get_settings()
    settings[data.get("setting_key", "required_invites")] = value
    save_settings(settings)
    await state.clear()
    await message.answer(
        f"Majburiy takliflar soni {value} ta qilib saqlandi.",
        reply_markup=_settings_keyboard(),
    )


@router.callback_query(F.data == "admin:maintenance")
async def maintenance_callback(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    settings = get_settings()
    settings["maintenance_mode"] = not bool(settings.get("maintenance_mode"))
    save_settings(settings)
    await callback.answer(
        "Texnik xizmat rejimi yoqildi."
        if settings["maintenance_mode"]
        else "Texnik xizmat rejimi o'chirildi."
    )


@router.callback_query(F.data.in_({"admin:welcome", "admin:subscription_text"}))
async def text_setting_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return
    key = "welcome_text" if callback.data == "admin:welcome" else "subscription_text"
    await state.set_state(TextSetting.value)
    await state.update_data(setting_key=key)
    await callback.answer()
    await callback.message.answer(
        "Yangi matnni yuboring. Bekor qilish uchun /cancel.\n\n"
        f"Amaldagi matn:\n{_setting_text(key, '')}"
    )


@router.message(TextSetting.value, F.text)
async def text_setting_handler(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value:
        await message.answer("Matn bo'sh bo'lmasligi kerak.")
        return
    data = await state.get_data()
    settings = get_settings()
    settings[data.get("setting_key", "welcome_text")] = value
    save_settings(settings)
    await state.clear()
    await message.answer("Matn saqlandi.", reply_markup=_settings_keyboard())