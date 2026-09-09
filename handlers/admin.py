"""Complete Telegram-only admin control panel with database support, Excel export, and quiz management."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import ADMIN_ID
from utils.db import (
    add_channel,
    add_lesson,
    add_lesson_material,
    add_quiz,
    count_user_statuses,
    delete_channel,
    delete_lesson,
    delete_lesson_material,
    delete_quizzes_for_lesson,
    get_all_users,
    get_lesson,
    get_lesson_material,
    get_lesson_materials,
    get_lessons,
    get_quizzes_for_lesson,
    get_required_channels,
    get_required_invites,
    get_setting,
    get_user,
    is_maintenance_mode,
    set_setting,
    set_user_banned,
    update_lesson,
)
from utils.excel_exporter import export_users_to_excel
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


class MaterialCreation(StatesGroup):
    lesson_id = State()
    file_id = State()
    file_type = State()
    title = State()


class QuizCreation(StatesGroup):
    lesson_id = State()
    question = State()
    options = State()
    correct_option = State()
    explanation = State()


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


class UserSearchState(StatesGroup):
    user_id = State()


async def _is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    if ADMIN_ID > 0 and user_id == ADMIN_ID:
        return True
    user = await get_user(user_id)
    if user and user.get("is_admin"):
        return True
    return False

async def _check_admin(message: Message) -> bool:
    if await _is_admin(message.from_user.id if message.from_user else None):
        return True
    await message.answer("Bu bo'lim faqat admin uchun.")
    return False

async def _check_admin_callback(callback: CallbackQuery) -> bool:
    if await _is_admin(callback.from_user.id if callback.from_user else None):
        return True
    await callback.answer("Bu bo'lim faqat admin uchun.", show_alert=True)
    return False


def _admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Dashboard / Statistika", callback_data="admin:dashboard"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📚 Darslarni boshqarish", callback_data="admin:lessons"
                ),
                InlineKeyboardButton(
                    text="➕ Yangi dars", callback_data="admin:add_lesson"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👥 Foydalanuvchilar (Admin/Ban)", callback_data="admin:users"
                ),
                InlineKeyboardButton(
                    text="📥 Excel yuklab olish", callback_data="admin:excel"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📢 Ommaviy xabar (Rassilka)", callback_data="admin:broadcast"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Obuna va bot sozlamalari",
                    callback_data="admin:settings",
                )
            ],
        ]
    )


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Admin panelga qaytish", callback_data="admin:menu")]
        ]
    )


def _settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Kanal qo'shish", callback_data="admin:channel:add"
                ),
                InlineKeyboardButton(
                    text="📋 Kanallar ro'yxati", callback_data="admin:channel:list"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔍 Kanal huquqini tekshirish",
                    callback_data="admin:channel:check",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Majburiy takliflar soni", callback_data="admin:invites"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛠 Texnik xizmat rejimi", callback_data="admin:maintenance"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Xush kelibsiz matni", callback_data="admin:welcome"
                ),
                InlineKeyboardButton(
                    text="✏️ Obuna matni", callback_data="admin:subscription_text"
                ),
            ],
            [InlineKeyboardButton(text="🔙 Admin panel", callback_data="admin:menu")],
        ]
    )


def _lesson_actions(lesson_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📎 Materiallar (PDF)",
                    callback_data=f"admin:materials:{lesson_id}",
                ),
                InlineKeyboardButton(
                    text="➕ PDF/Material biriktirish",
                    callback_data=f"admin:material:add:{lesson_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📝 Test qo'shish",
                    callback_data=f"admin:quiz:add:{lesson_id}",
                ),
                InlineKeyboardButton(
                    text="🗑 Testlarni tozalash",
                    callback_data=f"admin:quiz:clear:{lesson_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Tahrirlash",
                    callback_data=f"admin:lesson:edit:{lesson_id}",
                ),
                InlineKeyboardButton(
                    text="🗑 O'chirish",
                    callback_data=f"admin:lesson:delete:{lesson_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Darslar ro'yxatiga qaytish",
                    callback_data="admin:lessons",
                )
            ],
        ]
    )


from aiogram import Bot
# Get connection to DB
from utils.db import get_connection

@router.message(Command(commands=["health"]))
async def health_cmd(message: Message, bot: Bot):
    if not await _check_admin(message):
        return
    
    # DB check
    try:
        async with get_connection() as conn:
            await conn.execute("SELECT 1;")
        db_ok = "✅ DB OK"
    except Exception as e:
        db_ok = f"❌ DB error: {e}"
        
    # API check
    try:
        await bot.get_me()
        api_ok = "✅ API OK"
    except Exception as e:
        api_ok = f"❌ API error: {e}"
        
    await message.answer(f"Health check:\n{db_ok}\n{api_ok}")


@router.message(Command(commands=["admin"]))
async def admin_start(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return
    await state.clear()
    await message.answer(
        "⚡️ <b>To'liq Admin Boshqaruv Paneli:</b>\n\nBarcha sozlamalar, darslar va foydalanuvchilar shu yerdan boshqariladi.",
        parse_mode="HTML",
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
    await callback.message.edit_text(
        "⚡️ <b>To'liq Admin Boshqaruv Paneli:</b>\n\nBarcha sozlamalar, darslar va foydalanuvchilar shu yerdan boshqariladi.",
        parse_mode="HTML",
        reply_markup=_admin_keyboard(),
    )


# ==========================================
# DASHBOARD
# ==========================================

@router.callback_query(F.data == "admin:dashboard")
async def dashboard_handler(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return

    total, subscribed, banned = await count_user_statuses()
    lessons = await get_lessons(active_only=False)
    channels = await get_required_channels()
    req_invites = await get_required_invites()
    m_mode = "Yoqilgan ⚠️" if await is_maintenance_mode() else "O'chirilgan ✅"

    text = (
        "📊 <b>Bot Statistikasi va Holati:</b>\n\n"
        f"👥 <b>Jami foydalanuvchilar:</b> {total} ta\n"
        f"✅ <b>Obuna bo'lgan faollar:</b> {subscribed} ta\n"
        f"🚫 <b>Bloklangan foydalanuvchilar:</b> {banned} ta\n\n"
        f"📚 <b>Jami darslar soni:</b> {len(lessons)} ta\n"
        f"📢 <b>Majburiy kanallar:</b> {len(channels)} ta\n"
        f"👥 <b>Majburiy takliflar soni:</b> {req_invites} ta\n"
        f"🛠 <b>Texnik xizmat rejimi:</b> {m_mode}\n"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_back_keyboard())


# ==========================================
# EXCEL EXPORT
# ==========================================

@router.callback_query(F.data == "admin:excel")
async def excel_export_handler(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return

    await callback.answer("Excel fayl tayyorlanmoqda...", show_alert=False)
    excel_stream = await export_users_to_excel()
    document = BufferedInputFile(excel_stream.read(), filename="bot_foydalanuvchilar.xlsx")

    await callback.message.answer_document(
        document=document,
        caption="📊 <b>Barcha foydalanuvchilar va ularning to'liq statistikasi</b> (Excel formati).",
        parse_mode="HTML",
    )


# ==========================================
# LESSON MANAGEMENT
# ==========================================

@router.callback_query(F.data == "admin:lessons")
async def admin_lessons_list(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return

    lessons = await get_lessons(active_only=False)
    if not lessons:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➕ Yangi dars qo'shish", callback_data="admin:add_lesson")],
                [InlineKeyboardButton(text="🔙 Admin panel", callback_data="admin:menu")],
            ]
        )
        await callback.message.edit_text("Hozircha darslar mavjud emas.", reply_markup=kb)
        return

    kb_rows = []
    for idx, l in enumerate(lessons, 1):
        kb_rows.append(
            [
                InlineKeyboardButton(
                    text=f"{idx}. {l['title']}",
                    callback_data=f"admin:lesson:view:{l['id']}",
                )
            ]
        )
    kb_rows.append([InlineKeyboardButton(text="➕ Yangi dars qo'shish", callback_data="admin:add_lesson")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Admin panel", callback_data="admin:menu")])

    await callback.message.edit_text(
        "📚 <b>Mavjud darslar ro'yxati:</b>\nBoshqarish uchun darsni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )


@router.callback_query(F.data.startswith("admin:lesson:view:"))
async def admin_lesson_detail(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return

    lesson_id = callback.data.split(":", maxsplit=3)[3]
    lesson = await get_lesson(lesson_id)
    if not lesson:
        await callback.message.edit_text("Dars topilmadi.", reply_markup=_back_keyboard())
        return

    quizzes = await get_quizzes_for_lesson(lesson_id)
    materials = await get_lesson_materials(lesson_id)
    media_type = "Video 🎥" if lesson.get("video_file_id") else ("Asosiy PDF 📄" if lesson.get("pdf_file_id") else "Asosiy videosiz ❌")

    materials_info = ""
    if materials:
        materials_info = "\n\n📎 <b>Biriktirilgan materiallar (PDF/Fayllar):</b>\n" + "\n".join(
            [f"• {m.get('title', 'Fayl')} ({m.get('file_type', 'fayl')})" for m in materials]
        )
    else:
        materials_info = "\n\n📎 <b>Biriktirilgan materiallar:</b> Hozircha qo'shilmagan."

    text = (
        f"📖 <b>Dars:</b> {lesson['title']}\n\n"
        f"📝 <b>Tavsif:</b>\n{lesson.get('description', '')}\n\n"
        f"🎥 <b>Asosiy media:</b> {media_type}\n"
        f"❓ <b>Biriktirilgan testlar:</b> {len(quizzes)} ta"
        f"{materials_info}"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_lesson_actions(lesson_id))


@router.callback_query(F.data == "admin:add_lesson")
async def add_lesson_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return

    await state.set_state(LessonCreation.title)
    await callback.message.edit_text(
        "➕ <b>Yangi dars qo'shish:</b>\n\n1-qadam: Dars nomini (sarlavhasini) kiriting:\n(Bekor qilish uchun /cancel)",
        parse_mode="HTML",
    )


@router.message(LessonCreation.title)
async def lesson_title_received(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return
    title = (message.text or "").strip()
    if not title:
        await message.answer("Iltimos, dars nomini matn ko'rinishida kiriting:")
        return
    await state.update_data(title=title)
    await state.set_state(LessonCreation.description)
    await message.answer("2-qadam: Dars tavsifini (matnini) kiriting:")


@router.message(LessonCreation.description)
async def lesson_desc_received(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return
    desc = (message.text or "").strip()
    await state.update_data(description=desc)
    await state.set_state(LessonCreation.file)
    await message.answer("3-qadam: Dars uchun <b>Video</b> yoki <b>PDF fayl</b> yuboring (yoki o'tkazib yuborish uchun <code>yo'q</code> deb yozing):", parse_mode="HTML")


@router.message(LessonCreation.file)
async def lesson_file_received(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return

    data = await state.get_data()
    video_id = message.video.file_id if message.video else None
    pdf_id = message.document.file_id if message.document else None

    lesson_id = await add_lesson(
        title=data["title"],
        description=data.get("description", ""),
        video_file_id=video_id,
        pdf_file_id=pdf_id,
    )
    await state.clear()
    await message.answer(
        f"✅ <b>Dars muvaffaqiyatli qo'shildi!</b> (ID: <code>{lesson_id}</code>)",
        parse_mode="HTML",
        reply_markup=_back_keyboard(),
    )


@router.callback_query(F.data.startswith("admin:lesson:delete:"))
async def delete_lesson_handler(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return

    lesson_id = callback.data.split(":", maxsplit=3)[3]
    await delete_lesson(lesson_id)
    await callback.message.edit_text("🗑 Dars o'chirildi.", reply_markup=_back_keyboard())


# ==========================================
# LESSON MATERIALS MANAGEMENT (PDFs & Files)
# ==========================================

@router.callback_query(F.data.startswith("admin:materials:"))
async def admin_materials_list(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return

    lesson_id = callback.data.split(":", maxsplit=2)[2]
    lesson = await get_lesson(lesson_id)
    if not lesson:
        await callback.message.edit_text("Dars topilmadi.", reply_markup=_back_keyboard())
        return

    materials = await get_lesson_materials(lesson_id)
    kb_rows = []
    for m in materials:
        m_title = m.get("title") or "Fayl"
        kb_rows.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 O'chirish: {m_title}",
                    callback_data=f"admin:material:del:{m['id']}:{lesson_id}",
                )
            ]
        )
    kb_rows.append(
        [
            InlineKeyboardButton(
                text="➕ Yangi PDF/Material biriktirish",
                callback_data=f"admin:material:add:{lesson_id}",
            )
        ]
    )
    kb_rows.append(
        [
            InlineKeyboardButton(
                text="🔙 Darsga qaytish",
                callback_data=f"admin:lesson:view:{lesson_id}",
            )
        ]
    )

    mat_count = len(materials)
    await callback.message.edit_text(
        f"📎 <b>«{lesson['title']}» darsining biriktirilgan materiallari:</b>\n\n"
        f"Jami materiallar: {mat_count} ta.\n"
        f"O'chirish uchun kerakli material ustiga bosing yoki yangi fayl qo'shing:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )


@router.callback_query(F.data.startswith("admin:material:del:"))
async def admin_material_delete(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return

    parts = callback.data.split(":")
    mat_id = parts[3]
    lesson_id = parts[4]
    await delete_lesson_material(mat_id)
    await callback.answer("✅ Material o'chirildi!", show_alert=True)

    materials = await get_lesson_materials(lesson_id)
    kb_rows = []
    for m in materials:
        m_title = m.get("title") or "Fayl"
        kb_rows.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 O'chirish: {m_title}",
                    callback_data=f"admin:material:del:{m['id']}:{lesson_id}",
                )
            ]
        )
    kb_rows.append(
        [
            InlineKeyboardButton(
                text="➕ Yangi PDF/Material biriktirish",
                callback_data=f"admin:material:add:{lesson_id}",
            )
        ]
    )
    kb_rows.append(
        [
            InlineKeyboardButton(
                text="🔙 Darsga qaytish",
                callback_data=f"admin:lesson:view:{lesson_id}",
            )
        ]
    )
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@router.callback_query(F.data.startswith("admin:material:add:"))
async def add_material_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return

    lesson_id = callback.data.split(":", maxsplit=3)[3]
    await state.set_state(MaterialCreation.file_id)
    await state.update_data(lesson_id=lesson_id)

    await callback.message.edit_text(
        "📎 <b>Darsga yangi PDF yoki material biriktirish:</b>\n\n"
        "1-qadam: Biriktirmoqchi bo'lgan <b>PDF hujjat</b>, rasm yoki faylni yuboring:\n"
        "(Bekor qilish uchun /cancel)",
        parse_mode="HTML",
    )


@router.message(MaterialCreation.file_id)
async def material_file_received(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return

    file_id = None
    file_type = "document"

    if message.document:
        file_id = message.document.file_id
        file_type = "document"
        default_title = message.document.file_name or "PDF Hujjat"
    elif message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
        default_title = "Rasm / Jadval"
    elif message.video:
        file_id = message.video.file_id
        file_type = "video"
        default_title = "Qo'shimcha video"
    elif message.audio:
        file_id = message.audio.file_id
        file_type = "audio"
        default_title = message.audio.file_name or "Audio fayl"
    else:
        await message.answer("Iltimos, fayl yuboring (PDF, hujjat, rasm yoki audio):")
        return

    caption = (message.caption or "").strip()
    if caption:
        data = await state.get_data()
        lesson_id = data["lesson_id"]
        await add_lesson_material(
            lesson_id=lesson_id,
            title=caption,
            file_id=file_id,
            file_type=file_type,
        )
        await state.clear()
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➕ Yana material qo'shish", callback_data=f"admin:material:add:{lesson_id}")],
                [InlineKeyboardButton(text="🔙 Darsga qaytish", callback_data=f"admin:lesson:view:{lesson_id}")],
            ]
        )
        await message.answer(
            f"✅ <b>Material muvaffaqiyatli biriktirildi!</b>\n\n📌 <b>Sarlavha:</b> {caption}",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return

    await state.update_data(file_id=file_id, file_type=file_type, default_title=default_title)
    await state.set_state(MaterialCreation.title)
    await message.answer(
        f"2-qadam: Ushbu fayl uchun sarlavha (nom) kiriting:\n\n"
        f"<i>(Masalan: «1-mavzu so'z boyligi (PDF)» yoki o'z holicha qoldirish uchun «+» yuboring)</i>",
        parse_mode="HTML",
    )


@router.message(MaterialCreation.title)
async def material_title_received(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return

    text = (message.text or "").strip()
    data = await state.get_data()
    lesson_id = data["lesson_id"]
    file_id = data["file_id"]
    file_type = data.get("file_type", "document")
    title = text if text and text != "+" else data.get("default_title", "Material")

    await add_lesson_material(
        lesson_id=lesson_id,
        title=title,
        file_id=file_id,
        file_type=file_type,
    )
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Yana material qo'shish", callback_data=f"admin:material:add:{lesson_id}")],
            [InlineKeyboardButton(text="🔙 Darsga qaytish", callback_data=f"admin:lesson:view:{lesson_id}")],
        ]
    )
    await message.answer(
        f"✅ <b>Material muvaffaqiyatli biriktirildi!</b>\n\n📌 <b>Nomi:</b> {title}",
        parse_mode="HTML",
        reply_markup=kb,
    )


# ==========================================
# QUIZ MANAGEMENT (FOR LESSONS)
# ==========================================

@router.callback_query(F.data.startswith("admin:quiz:add:"))
async def add_quiz_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return

    lesson_id = callback.data.split(":", maxsplit=3)[3]
    await state.set_state(QuizCreation.question)
    await state.update_data(lesson_id=lesson_id)

    await callback.message.edit_text(
        "📝 <b>Darsga yangi test savolini qo'shish:</b>\n\n"
        "1-qadam: Savol matnini kiriting:\n(Bekor qilish uchun /cancel)",
        parse_mode="HTML",
    )


@router.message(QuizCreation.question)
async def quiz_question_received(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return
    q = (message.text or "").strip()
    if not q:
        await message.answer("Savol matnini kiriting:")
        return
    await state.update_data(question=q)
    await state.set_state(QuizCreation.options)
    await message.answer(
        "2-qadam: Javob variantlarini har bir qatorda bittadan kiriting.\nMasalan:\n\n"
        "Variant A\nVariant B\nVariant C\nVariant D"
    )


@router.message(QuizCreation.options)
async def quiz_options_received(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return
    lines = [line.strip() for line in (message.text or "").split("\n") if line.strip()]
    if len(lines) < 2:
        await message.answer("Kamida 2 ta variant bo'lishi kerak. Qaytadan kiriting:")
        return

    await state.update_data(options=lines)
    await state.set_state(QuizCreation.correct_option)

    opts_preview = "\n".join([f"{idx + 1}. {opt}" for idx, opt in enumerate(lines)])
    await message.answer(
        f"3-qadam: Qaysi variant to'g'ri? Raqamini kiriting (1 dan {len(lines)} gacha):\n\n{opts_preview}"
    )


@router.message(QuizCreation.correct_option)
async def quiz_correct_opt_received(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return

    data = await state.get_data()
    options = data.get("options", [])
    try:
        val = int((message.text or "").strip())
        if val < 1 or val > len(options):
            raise ValueError
        correct_idx = val - 1
    except ValueError:
        await message.answer(f"Iltimos, 1 dan {len(options)} gacha bo'lgan raqam kiriting:")
        return

    await state.update_data(correct_option_index=correct_idx)
    await state.set_state(QuizCreation.explanation)
    await message.answer("4-qadam: Noto'g'ri javob berilganda chiqadigan izoh (yoki o'tkazib yuborish uchun <code>yo'q</code> deb yozing):", parse_mode="HTML")


@router.message(QuizCreation.explanation)
async def quiz_explanation_received(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return

    exp = (message.text or "").strip()
    if exp.lower() in ("yo'q", "yoq", "none", "-"):
        exp = ""

    data = await state.get_data()
    await add_quiz(
        lesson_id=data["lesson_id"],
        question=data["question"],
        options=data["options"],
        correct_option_index=data["correct_option_index"],
        explanation=exp,
    )
    await state.clear()
    await message.answer("✅ <b>Test savoli darsga muvaffaqiyatli qo'shildi!</b>", parse_mode="HTML", reply_markup=_back_keyboard())


@router.callback_query(F.data.startswith("admin:quiz:clear:"))
async def clear_quizzes_handler(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    lesson_id = callback.data.split(":", maxsplit=3)[3]
    await delete_quizzes_for_lesson(lesson_id)
    await callback.message.edit_text("🗑 Bu darsdagi barcha testlar o'chirildi.", reply_markup=_back_keyboard())


# ==========================================
# USER MANAGEMENT & BANNING
# ==========================================

@router.callback_query(F.data == "admin:users")
async def admin_users_menu(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return

    total, subscribed, banned = await count_user_statuses()
    await state.set_state(UserSearchState.user_id)
    await callback.message.edit_text(
        f"👥 <b>Foydalanuvchilar bo'limi:</b>\n\n"
        f"Jami: {total} ta | Obunachi: {subscribed} ta | Bloklangan: {banned} ta\n\n"
        f"Foydalanuvchini boshqarish (<b>Admin qilish/olish</b> yoki <b>Bloklash/ochish</b>) uchun uning <b>Telegram ID</b> sini yuboring:\n\n"
        f"<i>Masalan: 123456789</i>",
        parse_mode="HTML",
        reply_markup=_back_keyboard(),
    )


@router.message(UserSearchState.user_id)
async def user_search_handler(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return

    try:
        user_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("Iltimos, to'g'ri raqamli ID kiriting:")
        return

    user = await get_user(user_id)
    if not user:
        await message.answer("Bunday ID li foydalanuvchi topilmadi.", reply_markup=_back_keyboard())
        return

    await state.clear()
    is_ban = bool(user.get("is_banned"))
    is_admin = bool(user.get("is_admin"))
    
    action_text = "Blokdan chiqarish ✅" if is_ban else "Bloklash 🚫"
    action_callback = f"admin:user:unban:{user_id}" if is_ban else f"admin:user:ban:{user_id}"
    
    admin_text = "Admindan olish ❌" if is_admin else "Admin qilish 👑"
    admin_callback = f"admin:user:removeadmin:{user_id}" if is_admin else f"admin:user:makeadmin:{user_id}"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=action_text, callback_data=action_callback)],
            [InlineKeyboardButton(text=admin_text, callback_data=admin_callback)],
            [InlineKeyboardButton(text="🔙 Qaytish", callback_data="admin:menu")],
        ]
    )

    text = (
        f"👤 <b>Foydalanuvchi ma'lumoti:</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"👤 Ism: {user.get('full_name')}\n"
        f"🔗 Username: @{user.get('username') or 'yoq'}\n"
        f"👥 Taklif qilganlari: {user.get('referral_count', 0)} ta\n"
        f"🚫 Blok holati: {'Bloklangan' if is_ban else 'Faol'}\n"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("admin:user:ban:"))
async def ban_user_handler(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    user_id = int(callback.data.split(":")[3])
    await set_user_banned(user_id, True)
    await callback.message.edit_text(f"🚫 Foydalanuvchi ({user_id}) bloklandi.", reply_markup=_back_keyboard())


@router.callback_query(F.data.startswith("admin:user:unban:"))
async def unban_user_handler(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    user_id = int(callback.data.split(":")[3])
    await set_user_banned(user_id, False)
    await callback.message.edit_text(f"✅ Foydalanuvchi ({user_id}) blokdan chiqarildi.", reply_markup=_back_keyboard())

from utils.db import set_user_admin

@router.callback_query(F.data.startswith("admin:user:makeadmin:"))
async def makeadmin_user_handler(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    user_id = int(callback.data.split(":")[3])
    await set_user_admin(user_id, True)
    await callback.message.edit_text(f"👑 Foydalanuvchi ({user_id}) admin qilindi.", reply_markup=_back_keyboard())

@router.callback_query(F.data.startswith("admin:user:removeadmin:"))
async def removeadmin_user_handler(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    user_id = int(callback.data.split(":")[3])
    await set_user_admin(user_id, False)
    await callback.message.edit_text(f"❌ Foydalanuvchi ({user_id}) dan admin huquqi olindi.", reply_markup=_back_keyboard())


# ==========================================
# BROADCAST (RASSILKA)
# ==========================================

@router.callback_query(F.data == "admin:broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return
    await state.set_state(BroadcastState.text)
    await callback.message.edit_text(
        "📢 <b>Barcha foydalanuvchilarga ommaviy xabar yuborish:</b>\n\n"
        "Xabar matnini yoki mediali postni yuboring:\n(Bekor qilish uchun /cancel)",
        parse_mode="HTML",
    )


@router.message(BroadcastState.text)
async def broadcast_send(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return

    await state.clear()
    users = await get_all_users()
    status_msg = await message.answer(f"⏳ Xabar {len(users)} ta foydalanuvchiga yuborilmoqda...")

    success = 0
    failed = 0
    for u in users:
        try:
            await message.copy_to(chat_id=u["user_id"])
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"✅ <b>Ommaviy xabar yuborildi!</b>\n\n"
        f"Yetib bordi: <b>{success}</b> ta\n"
        f"Yetib bormadi (bloklangan/o'chirilgan): <b>{failed}</b> ta",
        parse_mode="HTML",
        reply_markup=_back_keyboard(),
    )


# ==========================================
# SETTINGS & CHANNELS
# ==========================================

@router.callback_query(F.data == "admin:settings")
async def admin_settings_handler(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    await callback.message.edit_text("⚙️ <b>Bot Sozlamalari:</b>", parse_mode="HTML", reply_markup=_settings_keyboard())


@router.callback_query(F.data == "admin:channel:list")
async def channel_list_handler(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return

    channels = await get_required_channels()
    if not channels:
        await callback.message.edit_text("Hozircha majburiy kanallar qo'shilmagan.", reply_markup=_settings_keyboard())
        return

    kb_rows = []
    for ch in channels:
        kb_rows.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 O'chirish: {ch.get('title', ch['channel_id'])}",
                    callback_data=f"admin:channel:del:{ch['channel_id']}",
                )
            ]
        )
    kb_rows.append([InlineKeyboardButton(text="🔙 Sozlamalar", callback_data="admin:settings")])

    await callback.message.edit_text(
        "📋 <b>Majburiy kanallar ro'yxati:</b>\nO'chirish uchun kanalni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )


@router.callback_query(F.data.startswith("admin:channel:del:"))
async def channel_delete_handler(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    channel_id = callback.data.split(":", maxsplit=3)[3]
    await delete_channel(channel_id)
    await callback.message.edit_text("🗑 Kanal o'chirildi.", reply_markup=_settings_keyboard())


@router.callback_query(F.data == "admin:channel:check")
async def channel_check_handler(callback: CallbackQuery, bot: Bot) -> None:
    if not await _check_admin_callback(callback):
        return

    channels = await get_required_channels()
    if not channels:
        await callback.message.edit_text(
            "📋 Majburiy kanallar ro'yxati bo'sh.",
            reply_markup=_settings_keyboard(),
        )
        return

    bot_info = await bot.get_me()
    results = []
    for ch in channels:
        ch_id = ch.get("channel_id")
        title = ch.get("title", str(ch_id))
        try:
            from utils.subscription import _chat_id
            member = await bot.get_chat_member(chat_id=_chat_id(ch_id), user_id=bot_info.id)
            if member.status in ("administrator", "creator"):
                results.append(f"✅ <b>{title}</b> (<code>{ch_id}</code>):\nBot kanalda <b>ADMIN</b>!")
            else:
                results.append(f"⚠️ <b>{title}</b> (<code>{ch_id}</code>):\nBot a'zo, lekin <b>ADMIN EMAS</b> (status: {member.status})")
        except TelegramForbiddenError:
            results.append(f"❌ <b>{title}</b> (<code>{ch_id}</code>):\nBot kanalda mavjud emas yoki huquqi yo'q (Forbidden)!")
        except Exception as e:
            results.append(f"❓ <b>{title}</b> (<code>{ch_id}</code>):\nXatolik: {e}")

    await callback.message.edit_text(
        "🔍 <b>Kanallar huquqini tekshirish natijasi:</b>\n\n" + "\n\n".join(results),
        parse_mode="HTML",
        reply_markup=_settings_keyboard(),
    )


@router.callback_query(F.data == "admin:channel:add")
async def channel_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return
    await state.set_state(ChannelCreation.channel_id)
    await callback.message.edit_text(
        "➕ <b>Yangi majburiy kanal qo'shish:</b>\n\n"
        "1-qadam: Kanal username (masalan: <code>@kanal_nomi</code>) yoki ID sini (masalan: <code>-1001234567890</code>) kiriting:\n\n"
        "<i>Eslatma: Bot ushbu kanalda admin bo'lishi shart!</i>",
        parse_mode="HTML",
    )


@router.message(ChannelCreation.channel_id)
async def channel_id_received(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return
    cid = (message.text or "").strip()
    await state.update_data(channel_id=cid)
    await state.set_state(ChannelCreation.title)
    await message.answer("2-qadam: Kanal nomini (tugmada ko'rinadigan sarlavhani) kiriting:")


@router.message(ChannelCreation.title)
async def channel_title_received(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return
    title = (message.text or "").strip()
    await state.update_data(title=title)
    await state.set_state(ChannelCreation.link)
    await message.answer("3-qadam: Kanal taklif havolasini (linkini) kiriting (yoki o'tkazib yuborish uchun <code>yo'q</code> deb yozing):", parse_mode="HTML")


@router.message(ChannelCreation.link)
async def channel_link_received(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return
    link = (message.text or "").strip()
    if link.lower() in ("yo'q", "yoq", "none", "-"):
        link = ""

    data = await state.get_data()
    await add_channel(channel_id=data["channel_id"], title=data["title"], join_link=link)
    await state.clear()
    await message.answer("✅ <b>Majburiy kanal muvaffaqiyatli qo'shildi!</b>", parse_mode="HTML", reply_markup=_settings_keyboard())


@router.callback_query(F.data == "admin:invites")
async def invites_setting_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_admin_callback(callback):
        return
    curr = await get_required_invites()
    await state.set_state(NumberSetting.value)
    await callback.message.edit_text(
        f"👥 <b>Majburiy takliflar soni sozlamasi:</b>\n\n"
        f"Hozirgi talab: <b>{curr} ta</b>\n\n"
        f"Yangi sonni kiriting (o'chirib qo'yish uchun <code>0</code> yozing):",
        parse_mode="HTML",
    )


@router.message(NumberSetting.value)
async def invites_setting_save(message: Message, state: FSMContext) -> None:
    if not await _check_admin(message):
        return
    try:
        val = int((message.text or "").strip())
        if val < 0:
            raise ValueError
    except ValueError:
        await message.answer("Iltimos, musbat butun son kiriting (masalan: 0, 1, 3, 5):")
        return

    await set_setting("required_invites", str(val))
    await state.clear()
    await message.answer(f"✅ Majburiy takliflar soni <b>{val} ta</b> qilib belgilandi!", parse_mode="HTML", reply_markup=_settings_keyboard())


@router.callback_query(F.data == "admin:maintenance")
async def maintenance_toggle(callback: CallbackQuery) -> None:
    if not await _check_admin_callback(callback):
        return
    curr = await is_maintenance_mode()
    new_val = not curr
    await set_setting("maintenance_mode", "true" if new_val else "false")
    status_str = "Yoqildi ⚠️" if new_val else "O'chirildi ✅"
    await callback.message.edit_text(f"🛠 <b>Texnik xizmat rejimi:</b> {status_str}", parse_mode="HTML", reply_markup=_settings_keyboard())