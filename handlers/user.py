"""User-facing Telegram handlers."""

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
    Message,
)

from config import ADMIN_ID
from utils.file_manager import (
    credit_referral_if_eligible,
    get_required_channels,
    get_required_invites,
    get_referral_channel,
    get_settings,
    get_user_referral_count,
    is_maintenance_mode,
    load_lessons,
    load_users,
    upsert_user,
)
from utils.subscription import (
    check_required_subscriptions,
    join_link_for_channel,
)


router = Router(name="user")
logger = logging.getLogger(__name__)


def _subscription_keyboard(
    channels: list[dict[str, Any]] | None = None,
) -> InlineKeyboardMarkup:
    channels = channels if channels is not None else get_required_channels()
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
                text="Obunani tekshirish",
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


async def _blocked_message(message: Message, reason: str) -> None:
    await message.answer(reason)


async def _subscription_gate(
    message: Message, referrer_id: int | None = None
) -> bool:
    """Record the user and prevent protected content until every rule passes."""
    if message.from_user is None:
        return False

    existing = load_users().get(str(message.from_user.id), {})
    if existing.get("is_banned"):
        await _blocked_message(message, "Sizning botdan foydalanishingiz bloklangan.")
        return False

    record = upsert_user(
        message.from_user,
        is_subscribed=False,
        referrer_id=referrer_id,
    )

    if is_maintenance_mode() and message.from_user.id != ADMIN_ID:
        await _blocked_message(
            message,
            "Bot vaqtincha texnik xizmatda. Iltimos, keyinroq qayta urinib ko'ring.",
        )
        return False

    channels = get_required_channels()
    if not channels:
        await _blocked_message(
            message,
            "Majburiy kanal hali sozlanmagan. Iltimos, keyinroq qayta urinib ko'ring.",
        )
        return False

    subscribed, missing_channels = await check_required_subscriptions(
        message.bot,
        message.from_user.id,
        channels,
    )
    record = upsert_user(message.from_user, subscribed)
    referral_channel = get_referral_channel()
    referral_eligible = bool(
        referral_channel
        and (
            await check_required_subscriptions(
                message.bot,
                message.from_user.id,
                [referral_channel],
            )
        )[0]
    )
    credit_referral_if_eligible(message.from_user.id, referral_eligible)
    record = load_users().get(str(message.from_user.id), record)

    required_invites = get_required_invites()
    referral_count = int(record.get("referral_count", 0))
    if not subscribed:
        settings = get_settings()
        prompt = str(
            settings.get(
                "subscription_text",
                "Botdan foydalanish uchun avval majburiy kanal(lar)ga a'zo bo'ling.",
            )
        )
        await message.answer(
            f"{prompt}\n"
            f"Qolgan kanal(lar): {len(missing_channels)} ta.",
            reply_markup=_subscription_keyboard(missing_channels),
        )
        return False

    if referral_count < required_invites:
        link = await _referral_link(message)
        share_url = (
            "https://t.me/share/url?url="
            f"{quote_plus(link)}&text={quote_plus('Botga qo‘shiling!')}"
            if link
            else ""
        )
        rows = []
        if share_url:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="Do'stlarni taklif qilish",
                        url=share_url,
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Holatni tekshirish",
                    callback_data="check_subscription",
                )
            ]
        )
        await message.answer(
            f"Botdan foydalanish uchun yana "
            f"{required_invites - referral_count} ta foydalanuvchini taklif qiling.\n"
            f"Siz taklif qilganlar: {referral_count}/{required_invites}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
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
    if not await _subscription_gate(message, _referral_payload(message)):
        return
    welcome = str(
        get_settings().get(
            "welcome_text",
            "Assalomu alaykum. «Makhmudov Abdullajon» botiga xush kelibsiz.",
        )
    )
    await message.answer(
        f"{welcome}\n\nDarslar ro'yxati uchun /darslar buyrug'ini yuboring."
    )


@router.callback_query(F.data == "check_subscription")
async def check_subscription_handler(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return

    fake_message = callback.message
    channels = get_required_channels()
    subscribed, missing_channels = await check_required_subscriptions(
        callback.bot,
        callback.from_user.id,
        channels,
    )
    record = upsert_user(callback.from_user, subscribed)
    referral_channel = get_referral_channel()
    referral_eligible = bool(
        referral_channel
        and (
            await check_required_subscriptions(
                callback.bot,
                callback.from_user.id,
                [referral_channel],
            )
        )[0]
    )
    credit_referral_if_eligible(callback.from_user.id, referral_eligible)
    record = load_users().get(str(callback.from_user.id), record)
    if not subscribed:
        await fake_message.answer(
            f"Hali barcha shartlar bajarilmagan. Qolgan kanal(lar): "
            f"{len(missing_channels)} ta.",
            reply_markup=_subscription_keyboard(missing_channels),
        )
        return

    required_invites = get_required_invites()
    referral_count = int(record.get("referral_count", 0))
    if referral_count < required_invites:
        await fake_message.answer(
            f"Obuna tasdiqlandi, lekin belgilangan kanalda referral orqali "
            f"yana "
            f"{required_invites - referral_count} ta taklif kerak."
        )
        return
    await fake_message.answer(
        "Barcha shartlar tasdiqlandi. Endi /darslar buyrug'ini yuboring."
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

    channels = get_required_channels()
    subscribed, missing_channels = await check_required_subscriptions(
        callback.bot,
        callback.from_user.id,
        channels,
    )
    record = upsert_user(callback.from_user, subscribed)
    referral_channel = get_referral_channel()
    referral_eligible = bool(
        referral_channel
        and (
            await check_required_subscriptions(
                callback.bot,
                callback.from_user.id,
                [referral_channel],
            )
        )[0]
    )
    credit_referral_if_eligible(callback.from_user.id, referral_eligible)
    record = load_users().get(str(callback.from_user.id), record)
    if not subscribed:
        await callback.message.answer(
            "Darsni olish uchun barcha majburiy kanallarga a'zo bo'ling.",
            reply_markup=_subscription_keyboard(missing_channels),
        )
        return
    if int(record.get("referral_count", 0)) < get_required_invites():
        await callback.message.answer(
            "Darsni olishdan oldin belgilangan kanalga majburiy referral "
            "takliflari sonini bajaring."
        )
        return

    lesson_id = callback.data.split(":", maxsplit=1)[1]
    lesson = next((item for item in load_lessons() if item.get("id") == lesson_id), None)
    if lesson is None:
        await callback.message.answer("Bu dars topilmadi yoki o'chirilgan.")
        return

    title = str(lesson.get("title", "Dars"))
    description = str(lesson.get("description", "")).strip()
    caption = f"{title}\n\n{description}".strip()[:1024]
    video_file_id = lesson.get("video_file_id")
    pdf_file_id = lesson.get("pdf_file_id")
    if video_file_id:
        await callback.message.answer_video(video=video_file_id, caption=caption)
    if pdf_file_id:
        await callback.message.answer_document(document=pdf_file_id, caption=caption)
    if not video_file_id and not pdf_file_id:
        logger.error("Fayl ID si yo'q dars tanlandi: %s", lesson_id)
        await callback.message.answer("Bu dars uchun fayl mavjud emas.")