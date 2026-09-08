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


def upsert_user(user: User, is_subscribed: bool) -> None:
    users = load_users()
    user_id = str(user.id)
    users[user_id] = {
        "user_id": user.id,
        "username": user.username or "",
        "full_name": user.full_name,
        "is_subscribed": is_subscribed,
        "last_checked_at": datetime.now(timezone.utc).isoformat(),
    }
    save_users(users)


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
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    _write_json(SETTINGS_FILE, settings)


def get_channel_id() -> str | int | None:
    channel_id = get_settings().get("channel_id")
    if channel_id in (None, ""):
        return None
    return channel_id
