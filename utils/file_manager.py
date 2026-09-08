"""JSON file storage for users, lessons, and bot settings."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiogram.types import User

from config import (
    DATA_DIR,
    INITIAL_CHANNEL_ID,
    LESSONS_FILE,
    SETTINGS_FILE,
    USERS_FILE,
)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
    os.replace(temporary_path, path)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        _write_json(path, default)
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON fayli buzilgan: {path}") from error


def ensure_data_files() -> None:
    """Create all required files without overwriting existing data."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _read_json(USERS_FILE, {})
    _read_json(LESSONS_FILE, [])
    if not SETTINGS_FILE.exists():
        _write_json(SETTINGS_FILE, {"channel_id": INITIAL_CHANNEL_ID})
    else:
        _read_json(SETTINGS_FILE, {"channel_id": INITIAL_CHANNEL_ID})


def load_users() -> dict[str, dict[str, Any]]:
    users = _read_json(USERS_FILE, {})
    if not isinstance(users, dict):
        raise ValueError("users.json obyekt ko'rinishida bo'lishi kerak.")
    return users


def save_users(users: dict[str, dict[str, Any]]) -> None:
    _write_json(USERS_FILE, users)


def upsert_user(
    user: User, is_subscribed: bool, referrer_id: int | None = None
) -> dict[str, Any]:
    users = load_users()
    user_id = str(user.id)
    existing = users.get(user_id, {})
    if not isinstance(existing, dict):
        existing = {}
    record = {
        **existing,
        "user_id": user.id,
        "username": user.username or "",
        "full_name": user.full_name,
        "is_subscribed": is_subscribed,
        "is_banned": bool(existing.get("is_banned", False)),
        "referral_count": int(existing.get("referral_count", 0)),
        "last_checked_at": datetime.now(timezone.utc).isoformat(),
    }
    if (
        referrer_id
        and referrer_id != user.id
        and not existing.get("referred_by")
        and str(referrer_id) in users
    ):
        record["referred_by"] = referrer_id
        referrer = users[str(referrer_id)]
        referrer["referral_count"] = int(referrer.get("referral_count", 0)) + 1
    users[user_id] = record
    save_users(users)
    return record


def load_lessons() -> list[dict[str, Any]]:
    lessons = _read_json(LESSONS_FILE, [])
    if not isinstance(lessons, list):
        raise ValueError("lessons.json ro'yxat ko'rinishida bo'lishi kerak.")
    return lessons


def save_lessons(lessons: list[dict[str, Any]]) -> None:
    _write_json(LESSONS_FILE, lessons)


def get_settings() -> dict[str, Any]:
    settings = _read_json(SETTINGS_FILE, {"channel_id": INITIAL_CHANNEL_ID})
    if not isinstance(settings, dict):
        raise ValueError("settings.json obyekt ko'rinishida bo'lishi kerak.")
    settings.setdefault("required_channels", [])
    settings.setdefault("required_invites", 0)
    settings.setdefault("maintenance_mode", False)
    settings.setdefault(
        "welcome_text",
        "Assalomu alaykum. «Makhmudov Abdullajon» botiga xush kelibsiz.",
    )
    settings.setdefault(
        "subscription_text",
        "Botdan foydalanish uchun avval majburiy kanal(lar)ga a'zo bo'ling.",
    )
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    _write_json(SETTINGS_FILE, settings)


def get_channel_id() -> str | int | None:
    channels = get_required_channels()
    if channels:
        return channels[0].get("channel_id")
    channel_id = get_settings().get("channel_id")
    if channel_id in (None, ""):
        return None
    return channel_id


def get_required_channels() -> list[dict[str, Any]]:
    """Return all required channels and migrate the original single-channel format."""
    settings = get_settings()
    raw_channels = settings.get("required_channels") or []
    channels: list[dict[str, Any]] = []

    for item in raw_channels:
        if isinstance(item, str | int):
            channel_id = item
            channels.append(
                {
                    "channel_id": channel_id,
                    "title": str(channel_id),
                    "join_link": "",
                }
            )
        elif isinstance(item, dict) and item.get("channel_id") not in (None, ""):
            channels.append(
                {
                    "channel_id": item["channel_id"],
                    "title": item.get("title") or str(item["channel_id"]),
                    "join_link": item.get("join_link") or "",
                }
            )

    if not channels and settings.get("channel_id") not in (None, ""):
        channel_id = settings["channel_id"]
        if str(channel_id) != "@your_channel":
            channels.append(
                {
                    "channel_id": channel_id,
                    "title": str(channel_id),
                    "join_link": "",
                }
            )
    return channels


def get_required_invites() -> int:
    try:
        return max(0, int(get_settings().get("required_invites", 0)))
    except (TypeError, ValueError):
        return 0


def is_maintenance_mode() -> bool:
    return bool(get_settings().get("maintenance_mode", False))


def get_user_referral_count(user_id: int) -> int:
    user = load_users().get(str(user_id), {})
    try:
        return max(0, int(user.get("referral_count", 0)))
    except (TypeError, ValueError):
        return 0


def set_user_banned(user_id: int, is_banned: bool) -> None:
    users = load_users()
    if str(user_id) in users:
        users[str(user_id)]["is_banned"] = is_banned
        save_users(users)


def count_user_statuses() -> tuple[int, int, int]:
    users = load_users()
    total = len(users)
    subscribed = sum(1 for user in users.values() if user.get("is_subscribed"))
    banned = sum(1 for user in users.values() if user.get("is_banned"))
    return total, subscribed, banned
