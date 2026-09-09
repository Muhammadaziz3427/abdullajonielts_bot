"""User-facing Telegram handlers with rich LMS features, quizzes, and personal cabinet."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from config import ADMIN_ID
from utils.db import (
    credit_referral_if_eligible,
    get_leaderboard,
    get_lesson,
    get_lesson_materials,
    get_lessons,
    get_quizzes_for_lesson,
    get_referral_channel,
    get_required_channels,
    get_required_invites,
    get_setting,
    get_user,
    get_user_progress,
    get_user_stats,
    is_lesson_unlocked,
    is_maintenance_mode,
    mark_lesson_completed,
    upsert_user,
)
from utils.subscription import (
    check_required_subscriptions,
    join_link_for_channel,
)

router = Router(name="user")
logger = logging.getLogger(__name__)


def _main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Persistent user bottom keyboard."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Darslar"), KeyboardButton(text="📝 IELTS Mock Test")],
            [KeyboardButton(text="👤 Shaxsiy kabinet"), KeyboardButton(text="🏆 Reyting")],
            [KeyboardButton(text="📢 Kanalimiz"), KeyboardButton(text="ℹ️ Yordam")],
        ],
        resize_keyboard=True,
    )


def _subscription_keyboard(
    channels: list[dict[str, Any]],
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"A'zo bo'lish: {channel.get('title', 'Kanal')}",
                url=join_link_for_channel(channel),
            )
        ]
        for channel in channels
        if join_link_for_channel(channel) != "https://t.me/"
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="🔄 Obunani tekshirish",
                callback_data="check_subscription",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _referral_payload(message: Message) -> int | None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].startswith("ref_"):
        return None
    try:
        referrer_id = int(parts[1].removeprefix("ref_"))
    except ValueError:
        return None
    return referrer_id if referrer_id > 0 else None


async def _referral_link(message: Message) -> str:
    bot_user = await message.bot.get_me()
    if not bot_user.username or not message.from_user:
        return ""
    return f"https://t.me/{bot_user.username}?start=ref_{message.from_user.id}"


async def _subscription_gate(
    message: Message, referrer_id: int | None = None
) -> bool:
    """Record user and enforce channels subscription and invite quotas."""
    if message.from_user is None:
        return False

    existing = await get_user(message.from_user.id)
    if existing and existing.get("is_banned"):
        await message.answer("Sizning botdan foydalanishingiz bloklangan.")
        return False

    if await is_maintenance_mode() and message.from_user.id != ADMIN_ID:
        await message.answer(
            "Bot vaqtincha texnik xizmatda. Iltimos, keyinroq qayta urinib ko'ring."
        )
        return False

    channels = await get_required_channels()
    if not channels:
        await upsert_user(message.from_user, is_subscribed=True, referrer_id=referrer_id)
        return True

    subscribed, missing_channels = await check_required_subscriptions(
        message.bot,
        message.from_user.id,
        channels,
    )

    await upsert_user(
        message.from_user,
        is_subscribed=subscribed,
        referrer_id=referrer_id,
    )

    referral_channel = await get_referral_channel()
    if referral_channel:
        ref_sub, _ = await check_required_subscriptions(
            message.bot,
            message.from_user.id,
            [referral_channel],
        )
        referral_eligible = ref_sub
    else:
        referral_eligible = subscribed

    await credit_referral_if_eligible(message.from_user.id, referral_eligible)

    user_record = await get_user(message.from_user.id)
    referral_count = int(user_record.get("referral_count", 0)) if user_record else 0
    required_invites = await get_required_invites()

    if not subscribed:
        sub_text = await get_setting(
            "subscription_text",
            "Botdan foydalanish uchun avval majburiy kanal(lar)ga a'zo bo'ling.",
        )
        await message.answer(
            f"{sub_text}\n\nQolgan kanal(lar): {len(missing_channels)} ta.",
            reply_markup=_subscription_keyboard(missing_channels),
        )
        return False

    if referral_count < required_invites:
        link = await _referral_link(message)
        share_url = (
            "https://t.me/share/url?url="
            f"{quote_plus(link)}&text={quote_plus('Darslarni bepul o‘rganish uchun botga qo‘shiling!')}"
            if link
            else ""
        )
        rows = []
        if share_url:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="👥 Do'stlarni taklif qilish",
                        url=share_url,
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔄 Holatni tekshirish",
                    callback_data="check_subscription",
                )
            ]
        )
        await message.answer(
            f"Botdan foydalanish uchun yana <b>{required_invites - referral_count} ta</b> do'stingizni taklif qiling.\n\n"
            f"Siz taklif qilganlar: <b>{referral_count} / {required_invites}</b> ta\n"
            f"Sizning taklif havolangiz:\n<code>{link}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        return False

    return True


async def _build_lessons_keyboard(user_id: int) -> InlineKeyboardMarkup:
    lessons = await get_lessons(active_only=True)
    progress_map = await get_user_progress(user_id)

    keyboard: list[list[InlineKeyboardButton]] = []
    for idx, lesson in enumerate(lessons, 1):
        lesson_id = lesson["id"]
        is_completed = bool(progress_map.get(lesson_id, {}).get("is_completed"))
        is_unlocked = await is_lesson_unlocked(user_id, lesson_id)

        if is_completed:
            status_icon = "✅"
        elif is_unlocked:
            status_icon = "▶️"
        else:
            status_icon = "🔒"

        btn_text = f"{status_icon} {idx}-dars: {lesson['title']}"
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=btn_text,
                    callback_data=f"lesson:view:{lesson_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    if not await _subscription_gate(message, _referral_payload(message)):
        return

    welcome = await get_setting(
        "welcome_text",
        "Assalomu alaykum. «Makhmudov Abdullajon» ta'lim botiga xush kelibsiz!",
    )
    
    watermark = "\n\n<i>By <a href='https://t.me/yursinaliev'>Yursinaliev Muhammadaziz</a></i>"
    
    await message.answer(
        f"{welcome}\n\nQuyidagi menyu orqali kerakli bo'limni tanlang:{watermark}",
        parse_mode="HTML",
        reply_markup=_main_menu_keyboard(),
    )


@router.callback_query(F.data == "check_subscription")
async def check_subscription_handler(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return

    channels = await get_required_channels()
    subscribed, missing_channels = await check_required_subscriptions(
        callback.bot,
        callback.from_user.id,
        channels,
    )
    await upsert_user(callback.from_user, is_subscribed=subscribed)

    referral_channel = await get_referral_channel()
    if referral_channel:
        ref_sub, _ = await check_required_subscriptions(
            callback.bot,
            callback.from_user.id,
            [referral_channel],
        )
        referral_eligible = ref_sub
    else:
        referral_eligible = subscribed

    await credit_referral_if_eligible(callback.from_user.id, referral_eligible)

    user_record = await get_user(callback.from_user.id)
    referral_count = int(user_record.get("referral_count", 0)) if user_record else 0
    required_invites = await get_required_invites()

    if not subscribed:
        await callback.message.answer(
            f"❌ Hali barcha shartlar bajarilmagan. Qolgan kanal(lar): {len(missing_channels)} ta.",
            reply_markup=_subscription_keyboard(missing_channels),
        )
        return

    if referral_count < required_invites:
        await callback.message.answer(
            f"✅ Obuna tasdiqlandi!\nLekin botdan to'liq foydalanish uchun yana "
            f"<b>{required_invites - referral_count} ta</b> do'stingizni taklif qilishingiz kerak.",
            parse_mode="HTML",
        )
        return

    await callback.message.answer(
        "🎉 Barcha shartlar muvaffaqiyatli bajarildi! Darslarni boshlash uchun <b>📚 Darslar</b> tugmasini bosing.",
        parse_mode="HTML",
        reply_markup=_main_menu_keyboard(),
    )


@router.message(Command("darslar"))
@router.message(F.text == "📚 Darslar")
async def lessons_handler(message: Message) -> None:
    if not await _subscription_gate(message):
        return

    lessons = await get_lessons(active_only=True)
    if not lessons:
        await message.answer("Hozircha darslar yuklanmagan. Tez orada yangi darslar qo'shiladi!")
        return

    kb = await _build_lessons_keyboard(message.from_user.id)
    await message.answer(
        "📚 <b>Kurs darslari ro'yxati:</b>\n\n"
        "✅ — Tugatilgan darslar\n"
        "▶️ — O'rganish uchun ochiq dars\n"
        "🔒 — Keyingi dars (oldingi darsni tugatgach ochiladi)\n\n"
        "O'rganmoqchi bo'lgan darsingizni tanlang:",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("lesson:view:"))
async def lesson_view_handler(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None or callback.from_user is None or callback.data is None:
        return

    lesson_id = callback.data.split(":", maxsplit=2)[2]
    lesson = await get_lesson(lesson_id)
    if not lesson or not lesson.get("is_active"):
        await callback.message.answer("Bu dars topilmadi yoki o'chirilgan.")
        return

    # Check lock
    is_unlocked = await is_lesson_unlocked(callback.from_user.id, lesson_id)
    if not is_unlocked:
        await callback.message.answer(
            "🔒 <b>Bu dars hozircha qulflangan!</b>\n\n"
            "Ketma-ketlik qoidasiga ko'ra, bu darsni ochish uchun avval oldingi darslarni ko'rib chiqishingiz yoki testini topshirishingiz kerak.",
            parse_mode="HTML",
        )
        return

    quizzes = await get_quizzes_for_lesson(lesson_id)
    progress_map = await get_user_progress(callback.from_user.id)
    is_completed = bool(progress_map.get(lesson_id, {}).get("is_completed"))

    # Action buttons below lesson
    action_buttons = []
    if quizzes:
        action_buttons.append(
            [
                InlineKeyboardButton(
                    text="📝 Testni topshirish",
                    callback_data=f"quiz:start:{lesson_id}:0:0",
                )
            ]
        )
    else:
        if not is_completed:
            action_buttons.append(
                [
                    InlineKeyboardButton(
                        text="✅ Darsni yakunlash",
                        callback_data=f"lesson:complete:{lesson_id}",
                    )
                ]
            )

    action_buttons.append(
        [
            InlineKeyboardButton(
                text="🔙 Darslar ro'yxatiga qaytish",
                callback_data="lesson:list",
            )
        ]
    )
    kb = InlineKeyboardMarkup(inline_keyboard=action_buttons)

    title = str(lesson.get("title", "Dars"))
    description = str(lesson.get("description", "")).strip()
    caption = f"📖 <b>{title}</b>\n\n{description}".strip()[:1024]

    video_file_id = lesson.get("video_file_id")
    pdf_file_id = lesson.get("pdf_file_id")
    materials = await get_lesson_materials(lesson_id)

    # If there are attached materials or multiple items:
    if materials:
        # 1. Send main video if available
        if video_file_id:
            await callback.message.answer_video(
                video=video_file_id,
                caption=caption,
                parse_mode="HTML",
            )
        elif pdf_file_id:
            await callback.message.answer_document(
                document=pdf_file_id,
                caption=caption,
                parse_mode="HTML",
            )
        elif caption:
            await callback.message.answer(
                caption,
                parse_mode="HTML",
            )

        # 2. Send each attached material (PDF, doc, photo, etc.)
        for idx, m in enumerate(materials, 1):
            m_title = m.get("title") or f"Material #{idx}"
            m_type = m.get("file_type", "document")
            m_cap = f"📎 <b>{m_title}</b>"

            try:
                if m_type == "photo":
                    await callback.message.answer_photo(photo=m["file_id"], caption=m_cap, parse_mode="HTML")
                elif m_type == "audio":
                    await callback.message.answer_audio(audio=m["file_id"], caption=m_cap, parse_mode="HTML")
                elif m_type == "video":
                    await callback.message.answer_video(video=m["file_id"], caption=m_cap, parse_mode="HTML")
                else:
                    await callback.message.answer_document(document=m["file_id"], caption=m_cap, parse_mode="HTML")
            except Exception as err:
                logger.error("Material yuborishda xatolik (%s): %s", m.get("id"), err)

        # 3. Finally send action keyboard
        await callback.message.answer(
            "📌 <i>Dars videosi va barcha biriktirilgan materiallarni to'liq o'rganib chiqqach, pastdagi tugma orqali davom eting:</i>",
            parse_mode="HTML",
            reply_markup=kb,
        )
    else:
        # Single item fallback
        if video_file_id:
            await callback.message.answer_video(
                video=video_file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=kb,
            )
        elif pdf_file_id:
            await callback.message.answer_document(
                document=pdf_file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=kb,
            )
        else:
            await callback.message.answer(
                caption or "Dars ma'lumotlari yuklanmoqda...",
                parse_mode="HTML",
                reply_markup=kb,
            )


@router.callback_query(F.data == "lesson:list")
async def lesson_list_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message and callback.from_user:
        kb = await _build_lessons_keyboard(callback.from_user.id)
        await callback.message.answer(
            "📚 <b>Kurs darslari:</b>",
            parse_mode="HTML",
            reply_markup=kb,
        )


@router.callback_query(F.data.startswith("lesson:complete:"))
async def lesson_complete_handler(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None or callback.from_user is None or callback.data is None:
        return

    lesson_id = callback.data.split(":", maxsplit=2)[2]
    await mark_lesson_completed(callback.from_user.id, lesson_id, quiz_score=100, quiz_passed=True)

    kb = await _build_lessons_keyboard(callback.from_user.id)
    await callback.message.answer(
        "🎉 <b>Tabriklaymiz! Dars muvaffaqiyatli yakunlandi.</b>\n\n"
        "Keyingi dars ochildi!",
        parse_mode="HTML",
        reply_markup=kb,
    )


# ==========================================
# QUIZ HANDLERS
# ==========================================

@router.callback_query(F.data.startswith("quiz:start:"))
async def quiz_start_handler(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None or callback.from_user is None or callback.data is None:
        return

    parts = callback.data.split(":")
    lesson_id = parts[2]
    q_index = int(parts[3])
    score = int(parts[4])

    quizzes = await get_quizzes_for_lesson(lesson_id)
    if not quizzes or q_index >= len(quizzes):
        # Completed all questions
        total_q = len(quizzes)
        passed = score >= (total_q * 0.6) if total_q > 0 else True
        await mark_lesson_completed(
            callback.from_user.id, lesson_id, quiz_score=int(score / max(total_q, 1) * 100), quiz_passed=passed
        )

        status_text = "🎉 <b>Testdan muvaffaqiyatli o'tdingiz!</b>" if passed else "⚠️ <b>Test natijasi pastroq, lekin dars o'rganildi deb belgilandi.</b>"
        await callback.message.answer(
            f"{status_text}\n\n"
            f"To'g'ri javoblar: <b>{score} / {total_q}</b> ta\n"
            f"Keyingi dars o'rganish uchun ochildi!",
            parse_mode="HTML",
            reply_markup=await _build_lessons_keyboard(callback.from_user.id),
        )
        return

    quiz = quizzes[q_index]
    options = quiz.get("options", [])

    kb_rows = []
    for opt_idx, opt_text in enumerate(options):
        kb_rows.append(
            [
                InlineKeyboardButton(
                    text=f"{chr(65 + opt_idx)}) {opt_text}",
                    callback_data=f"quiz:ans:{lesson_id}:{q_index}:{score}:{opt_idx}",
                )
            ]
        )
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    await callback.message.answer(
        f"📝 <b>Savol {q_index + 1} / {len(quizzes)}:</b>\n\n"
        f"{quiz['question']}",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("quiz:ans:"))
async def quiz_answer_handler(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None or callback.from_user is None or callback.data is None:
        return

    parts = callback.data.split(":")
    lesson_id = parts[2]
    q_index = int(parts[3])
    score = int(parts[4])
    chosen_opt = int(parts[5])

    quizzes = await get_quizzes_for_lesson(lesson_id)
    if not quizzes or q_index >= len(quizzes):
        return

    quiz = quizzes[q_index]
    correct_idx = int(quiz.get("correct_option_index", 0))

    if chosen_opt == correct_idx:
        score += 1
        msg = "✅ <b>To'g'ri javob!</b>"
    else:
        corr_letter = chr(65 + correct_idx)
        explanation = quiz.get("explanation", "").strip()
        msg = f"❌ <b>Noto'g'ri javob.</b> To'g'ri variant: <b>{corr_letter}</b>"
        if explanation:
            msg += f"\n💡 <i>Izoh: {explanation}</i>"

    await callback.message.answer(msg, parse_mode="HTML")

    # Proceed to next question
    next_data = f"quiz:start:{lesson_id}:{q_index + 1}:{score}"
    next_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="➡️ Keyingi savol", callback_data=next_data)]]
    )
    await callback.message.answer("Davom etish uchun bosing:", reply_markup=next_kb)


# ==========================================
# PERSONAL PROFILE & LEADERBOARD
# ==========================================

@router.message(Command("profil"))
@router.message(F.text == "👤 Shaxsiy kabinet")
async def profile_handler(message: Message) -> None:
    if not await _subscription_gate(message):
        return

    user = await get_user(message.from_user.id)
    if not user:
        return

    stats = await get_user_stats(message.from_user.id)
    link = await _referral_link(message)
    req_invites = await get_required_invites()
    ref_count = user.get("referral_count", 0)

    # Progress bar
    percent = stats["percent"]
    filled = percent // 10
    bar = "█" * filled + "░" * (10 - filled)

    share_url = (
        "https://t.me/share/url?url="
        f"{quote_plus(link)}&text={quote_plus('Darslarni bepul o‘rganish uchun botga qo‘shiling!')}"
        if link
        else ""
    )
    rows = []
    if share_url:
        rows.append(
            [InlineKeyboardButton(text="👥 Do'stlarni taklif qilish", url=share_url)]
        )

    profile_text = (
        f"👤 <b>Shaxsiy Kabinet</b>\n\n"
        f"🆔 <b>ID:</b> <code>{user['user_id']}</code>\n"
        f"👤 <b>Ism:</b> {user.get('full_name', 'Foydalanuvchi')}\n"
        f"🔗 <b>Username:</b> @{user['username'] if user.get('username') else 'mavjud emas'}\n\n"
        f"📊 <b>Darslar progressi:</b>\n"
        f"[{bar}] <b>{percent}%</b>\n"
        f"Tugatilgan darslar: <b>{stats['completed_lessons']} / {stats['total_lessons']}</b> ta\n\n"
        f"👥 <b>Referral statistikasi:</b>\n"
        f"Taklif qilgan do'stlaringiz: <b>{ref_count}</b> ta (Talab: {req_invites} ta)\n\n"
        f"🔗 <b>Sizning taklif havolangiz:</b>\n<code>{link}</code>\n\n"
        f"👨‍💻 <i>Dasturchi: @yursinaliev (By Yursinaliev Muhammadaziz)</i>"
    )

    await message.answer(
        profile_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None,
    )


@router.message(Command("reyting"))
@router.message(F.text == "🏆 Reyting")
async def leaderboard_handler(message: Message) -> None:
    if not await _subscription_gate(message):
        return

    leaders = await get_leaderboard(limit=10)
    if not leaders:
        await message.answer("🏆 Hozircha reytingda hech kim yo'q. Do'stlaringizni birinchi bo'lib taklif qiling!")
        return

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    text_lines = ["🏆 <b>Eng ko'p do'st taklif qilgan faollar (TOP-10):</b>\n"]

    for idx, row in enumerate(leaders):
        medal = medals[idx] if idx < len(medals) else f"{idx + 1}."
        name = row.get("full_name") or (f"@{row['username']}" if row.get("username") else f"ID: {row['user_id']}")
        count = row.get("referral_count", 0)
        text_lines.append(f"{medal} <b>{name}</b> — <b>{count}</b> ta taklif")

    await message.answer("\n".join(text_lines), parse_mode="HTML")


@router.message(F.text == "📢 Kanalimiz")
async def channels_info_handler(message: Message) -> None:
    channels = await get_required_channels()
    if not channels:
        await message.answer("Hozircha rasmiy kanallar ulanmagan.")
        return

    kb_rows = [
        [
            InlineKeyboardButton(
                text=f"📢 {ch.get('title', 'Kanal')}",
                url=join_link_for_channel(ch),
            )
        ]
        for ch in channels
        if join_link_for_channel(ch) != "https://t.me/"
    ]
    await message.answer(
        "Rasmiy kanallarimizga a'zo bo'ling va eng so'nggi yangiliklardan boxabar bo'ling:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )


@router.message(F.text == "ℹ️ Yordam")
async def help_handler(message: Message) -> None:
    await message.answer(
        "ℹ️ <b>Botdan qanday foydalaniladi?</b>\n\n"
        "1. <b>📚 Darslar</b> — kurs darslarini ketma-ket tomosha qiling va testlarni yeching.\n"
        "2. <b>📝 IELTS Mock Test</b> — Reading, Listening va Writing bo'limlaridan haqiqiy mock testlar topshiring.\n"
        "3. <b>👤 Shaxsiy kabinet</b> — o'zlashtirish foizingiz va taklif havolangizni oling.\n"
        "4. <b>🏆 Reyting</b> — eng ko'p do'st chaqirgan yetakchilar ro'yxati.\n"
        "5. Savol yoki takliflar bo'lsa adminga murojaat qiling.\n\n"
        "<i>By <a href='https://t.me/yursinaliev'>Yursinaliev Muhammadaziz</a></i>",
        parse_mode="HTML",
    )


# ==========================================
# IELTS MOCK TEST SECTION (WEB APP & INFO)
# ==========================================

@router.message(F.text == "📝 IELTS Mock Test")
async def ielts_mock_menu_handler(message: Message) -> None:
    if not await _subscription_gate(message):
        return

    webapp_url = await get_setting("mock_webapp_url", "")

    rows = []
    if webapp_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🚀 WebApp Mock Testni Ochish",
                    web_app=WebAppInfo(url=webapp_url),
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(text="📖 Reading Mock #1", callback_data="mock:info:reading"),
            InlineKeyboardButton(text="🎧 Listening Mock #1", callback_data="mock:info:listening"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="✍️ Writing Mock #1", callback_data="mock:info:writing"),
        ]
    )

    text = (
        "🎯 <b>IELTS Mock Exam Platform:</b>\n\n"
        "Haqiqiy imtihon standartlari asosida tuzilgan Mock testlar:\n\n"
        "• <b>Reading Mock:</b> 3 ta akademik passage, 40 ta savol, 60 daqiqa va avtomatik Band hisoblagich.\n"
        "• <b>Listening Mock:</b> 4 ta audio qism, 40 ta savol, 30 daqiqa va avto-tahlil.\n"
        "• <b>Writing Mock:</b> Task 1 (Report 150+ so'z) va Task 2 (Essay 250+ so'z) - jonli so'z hisoblagich bilan.\n\n"
        "<i>Boshlash uchun kerakli bo'limni tanlang:</i>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("mock:info:"))
async def mock_info_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    module = callback.data.split(":")[2]
    webapp_url = await get_setting("mock_webapp_url", "")

    if module == "reading":
        title = "📖 IELTS Reading Mock #1"
        info = (
            "<b>Format:</b> 3 ta ilmiy-ommabop passage, 40 ta savol.\n"
            "<b>Vaqt:</b> 60 daqiqa.\n"
            "<b>Imkoniyat:</b> Test yakunida avtomatik ravishda IELTS Band Score (5.5 - 9.0) ballingiz chiqariladi."
        )
        sub_url = f"{webapp_url.rstrip('/')}/reading.html" if webapp_url else ""
    elif module == "listening":
        title = "🎧 IELTS Listening Mock #1"
        info = (
            "<b>Format:</b> 4 ta audio suhbat va ma'ruza, 40 ta savol.\n"
            "<b>Vaqt:</b> 30 daqiqa + 10 daqiqa ko'chirish.\n"
            "<b>Imkoniyat:</b> O'rnatilgan audio pleyer va avtomatik javoblar tahlili."
        )
        sub_url = f"{webapp_url.rstrip('/')}/listening.html" if webapp_url else ""
    else:
        title = "✍️ IELTS Writing Mock #1"
        info = (
            "<b>Format:</b> Task 1 (Academic Report, min 150 so'z) va Task 2 (Essay, min 250 so'z).\n"
            "<b>Vaqt:</b> 60 daqiqa.\n"
            "<b>Imkoniyat:</b> Jonli so'zlar hisoblagichi (Word Counter) va namuna insholar."
        )
        sub_url = f"{webapp_url.rstrip('/')}/writing.html" if webapp_url else ""

    kb_rows = []
    if sub_url:
        kb_rows.append([InlineKeyboardButton(text="🚀 Testni Boshlash (Web App)", web_app=WebAppInfo(url=sub_url))])
    kb_rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="mock:back")])

    await callback.message.answer(
        f"🎯 <b>{title}</b>\n\n{info}\n\n<i>Mock testlar fayllari bot serverida (<code>webapp/</code> papkasida) tayyorlangan.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )


@router.callback_query(F.data == "mock:back")
async def mock_back_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.delete()