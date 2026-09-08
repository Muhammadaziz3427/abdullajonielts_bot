"""SQLite database manager for the Makhmudov Abdullajon Telegram bot.

Uses aiosqlite for non-blocking asynchronous operations, provides automatic
schema initialization, migration from existing JSON data, and helper functions
for users, lessons, quizzes, progress tracking, channels, and settings.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
from aiogram.types import User

from config import (
    DATA_DIR,
    DB_FILE,
    INITIAL_CHANNEL_ID,
    LESSONS_FILE,
    SETTINGS_FILE,
    USERS_FILE,
)

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_connection() -> aiosqlite.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(DB_FILE)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL;")
    return conn


async def init_db() -> None:
    """Initialize database tables and run migrations from JSON if needed."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with await get_connection() as conn:
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                is_subscribed BOOLEAN DEFAULT 0,
                is_banned BOOLEAN DEFAULT 0,
                referral_count INTEGER DEFAULT 0,
                referred_by INTEGER,
                referral_credited BOOLEAN DEFAULT 0,
                created_at TEXT,
                last_active_at TEXT
            );

            CREATE TABLE IF NOT EXISTS lessons (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                video_file_id TEXT,
                pdf_file_id TEXT,
                order_num INTEGER DEFAULT 1,
                is_active BOOLEAN DEFAULT 1,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS quizzes (
                id TEXT PRIMARY KEY,
                lesson_id TEXT NOT NULL,
                question TEXT NOT NULL,
                options_json TEXT NOT NULL,
                correct_option_index INTEGER NOT NULL,
                explanation TEXT,
                created_at TEXT,
                FOREIGN KEY (lesson_id) REFERENCES lessons(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS user_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                lesson_id TEXT NOT NULL,
                is_completed BOOLEAN DEFAULT 0,
                quiz_score INTEGER DEFAULT 0,
                quiz_passed BOOLEAN DEFAULT 0,
                completed_at TEXT,
                UNIQUE(user_id, lesson_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (lesson_id) REFERENCES lessons(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY,
                title TEXT,
                join_link TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        await conn.commit()

    # Migrate legacy JSON files if they exist and DB tables are empty
    await _migrate_from_json_if_needed()


async def _migrate_from_json_if_needed() -> None:
    """Safely migrate legacy JSON data into SQLite tables if empty."""
    async with await get_connection() as conn:
        # 1. Migrate settings
        cursor = await conn.execute("SELECT COUNT(*) as cnt FROM settings;")
        row = await cursor.fetchone()
        if row and row["cnt"] == 0:
            default_settings = {
                "required_invites": "0",
                "maintenance_mode": "false",
                "welcome_text": "Assalomu alaykum. «Makhmudov Abdullajon» botiga xush kelibsiz.",
                "subscription_text": "Botdan foydalanish uchun avval majburiy kanal(lar)ga a'zo bo'ling.",
                "referral_channel_id": "",
            }
            if SETTINGS_FILE.exists():
                try:
                    with SETTINGS_FILE.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                    default_settings["required_invites"] = str(data.get("required_invites", 0))
                    default_settings["maintenance_mode"] = str(bool(data.get("maintenance_mode", False))).lower()
                    default_settings["welcome_text"] = str(data.get("welcome_text", default_settings["welcome_text"]))
                    default_settings["subscription_text"] = str(data.get("subscription_text", default_settings["subscription_text"]))
                    default_settings["referral_channel_id"] = str(data.get("referral_channel_id") or "")

                    # channels migration
                    channels = data.get("required_channels", [])
                    for ch in channels:
                        if isinstance(ch, dict) and ch.get("channel_id"):
                            await conn.execute(
                                """
                                INSERT OR IGNORE INTO channels (channel_id, title, join_link, is_active, created_at)
                                VALUES (?, ?, ?, 1, ?)
                                """,
                                (
                                    str(ch["channel_id"]),
                                    ch.get("title", str(ch["channel_id"])),
                                    ch.get("join_link", ""),
                                    _utc_now(),
                                ),
                            )
                except Exception as e:
                    logger.warning("JSON settings migratsiyasida xatolik: %s", e)

            for k, v in default_settings.items():
                await conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?);",
                    (k, v),
                )
            await conn.commit()

        # 2. Migrate lessons
        cursor = await conn.execute("SELECT COUNT(*) as cnt FROM lessons;")
        row = await cursor.fetchone()
        if row and row["cnt"] == 0 and LESSONS_FILE.exists():
            try:
                with LESSONS_FILE.open("r", encoding="utf-8") as f:
                    lessons_data = json.load(f)
                if isinstance(lessons_data, list):
                    for idx, item in enumerate(lessons_data, 1):
                        lesson_id = item.get("id") or uuid.uuid4().hex[:12]
                        await conn.execute(
                            """
                            INSERT OR IGNORE INTO lessons (id, title, description, video_file_id, pdf_file_id, order_num, is_active, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                            """,
                            (
                                lesson_id,
                                item.get("title", f"Dars #{idx}"),
                                item.get("description", ""),
                                item.get("video_file_id"),
                                item.get("pdf_file_id"),
                                idx,
                                _utc_now(),
                            ),
                        )
                    await conn.commit()
            except Exception as e:
                logger.warning("JSON lessons migratsiyasida xatolik: %s", e)

        # 3. Migrate users
        cursor = await conn.execute("SELECT COUNT(*) as cnt FROM users;")
        row = await cursor.fetchone()
        if row and row["cnt"] == 0 and USERS_FILE.exists():
            try:
                with USERS_FILE.open("r", encoding="utf-8") as f:
                    users_data = json.load(f)
                if isinstance(users_data, dict):
                    for uid, u in users_data.items():
                        await conn.execute(
                            """
                            INSERT OR IGNORE INTO users (user_id, username, full_name, is_subscribed, is_banned, referral_count, referred_by, referral_credited, created_at, last_active_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                int(u.get("user_id", uid)),
                                u.get("username", ""),
                                u.get("full_name", ""),
                                1 if u.get("is_subscribed") else 0,
                                1 if u.get("is_banned") else 0,
                                int(u.get("referral_count", 0)),
                                u.get("referred_by"),
                                1 if u.get("referral_credited") else 0,
                                u.get("created_at", _utc_now()),
                                u.get("last_checked_at", _utc_now()),
                            ),
                        )
                    await conn.commit()
            except Exception as e:
                logger.warning("JSON users migratsiyasida xatolik: %s", e)


# ==========================================
# USER OPERATIONS
# ==========================================

async def upsert_user(
    user: User,
    is_subscribed: bool = False,
    referrer_id: int | None = None,
) -> dict[str, Any]:
    """Insert or update user information and handle initial referral linking."""
    now = _utc_now()
    async with await get_connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM users WHERE user_id = ?;", (user.id,)
        )
        existing = await cursor.fetchone()

        if existing is None:
            # Check if referrer exists and is valid
            valid_referrer = None
            if referrer_id and referrer_id != user.id:
                ref_cursor = await conn.execute(
                    "SELECT user_id FROM users WHERE user_id = ?;", (referrer_id,)
                )
                if await ref_cursor.fetchone():
                    valid_referrer = referrer_id

            await conn.execute(
                """
                INSERT INTO users (
                    user_id, username, full_name, is_subscribed, is_banned,
                    referral_count, referred_by, referral_credited, created_at, last_active_at
                ) VALUES (?, ?, ?, ?, 0, 0, ?, 0, ?, ?);
                """,
                (
                    user.id,
                    user.username or "",
                    user.full_name or "",
                    1 if is_subscribed else 0,
                    valid_referrer,
                    now,
                    now,
                ),
            )
            await conn.commit()
        else:
            await conn.execute(
                """
                UPDATE users
                SET username = ?, full_name = ?, is_subscribed = ?, last_active_at = ?
                WHERE user_id = ?;
                """,
                (
                    user.username or "",
                    user.full_name or "",
                    1 if is_subscribed else 0,
                    now,
                    user.id,
                ),
            )
            await conn.commit()

        cursor = await conn.execute(
            "SELECT * FROM users WHERE user_id = ?;", (user.id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else {}


async def get_user(user_id: int) -> dict[str, Any] | None:
    async with await get_connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM users WHERE user_id = ?;", (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_users() -> list[dict[str, Any]]:
    async with await get_connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC;"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def set_user_banned(user_id: int, is_banned: bool) -> None:
    async with await get_connection() as conn:
        await conn.execute(
            "UPDATE users SET is_banned = ? WHERE user_id = ?;",
            (1 if is_banned else 0, user_id),
        )
        await conn.commit()


async def credit_referral_if_eligible(user_id: int, is_eligible: bool) -> None:
    """Credit inviter +1 referral count once if the invited user is eligible."""
    if not is_eligible:
        return
    async with await get_connection() as conn:
        cursor = await conn.execute(
            "SELECT referred_by, referral_credited FROM users WHERE user_id = ?;",
            (user_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return
        referrer_id = row["referred_by"]
        already_credited = bool(row["referral_credited"])

        if referrer_id and not already_credited:
            await conn.execute(
                """
                UPDATE users
                SET referral_count = referral_count + 1
                WHERE user_id = ?;
                """,
                (referrer_id,),
            )
            await conn.execute(
                "UPDATE users SET referral_credited = 1 WHERE user_id = ?;",
                (user_id,),
            )
            await conn.commit()


async def get_leaderboard(limit: int = 10) -> list[dict[str, Any]]:
    """Return top users ranked by referral count."""
    async with await get_connection() as conn:
        cursor = await conn.execute(
            """
            SELECT user_id, username, full_name, referral_count
            FROM users
            WHERE is_banned = 0 AND referral_count > 0
            ORDER BY referral_count DESC, created_at ASC
            LIMIT ?;
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def count_user_statuses() -> tuple[int, int, int]:
    """Return total users, active subscribed users, and banned users."""
    async with await get_connection() as conn:
        cursor = await conn.execute("SELECT COUNT(*) as total FROM users;")
        total = (await cursor.fetchone())["total"]

        cursor = await conn.execute(
            "SELECT COUNT(*) as sub FROM users WHERE is_subscribed = 1 AND is_banned = 0;"
        )
        sub = (await cursor.fetchone())["sub"]

        cursor = await conn.execute(
            "SELECT COUNT(*) as ban FROM users WHERE is_banned = 1;"
        )
        ban = (await cursor.fetchone())["ban"]

        return total, sub, ban


# ==========================================
# LESSON OPERATIONS
# ==========================================

async def get_lessons(active_only: bool = True) -> list[dict[str, Any]]:
    async with await get_connection() as conn:
        query = "SELECT * FROM lessons"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY order_num ASC, created_at ASC;"
        cursor = await conn.execute(query)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_lesson(lesson_id: str) -> dict[str, Any] | None:
    async with await get_connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM lessons WHERE id = ?;", (lesson_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def add_lesson(
    title: str,
    description: str = "",
    video_file_id: str | None = None,
    pdf_file_id: str | None = None,
) -> str:
    lesson_id = uuid.uuid4().hex[:12]
    now = _utc_now()
    async with await get_connection() as conn:
        cursor = await conn.execute(
            "SELECT COALESCE(MAX(order_num), 0) + 1 as next_order FROM lessons;"
        )
        next_order = (await cursor.fetchone())["next_order"]

        await conn.execute(
            """
            INSERT INTO lessons (
                id, title, description, video_file_id, pdf_file_id, order_num, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?);
            """,
            (
                lesson_id,
                title,
                description,
                video_file_id,
                pdf_file_id,
                next_order,
                now,
            ),
        )
        await conn.commit()
    return lesson_id


async def update_lesson(
    lesson_id: str,
    title: str | None = None,
    description: str | None = None,
    video_file_id: str | None = None,
    pdf_file_id: str | None = None,
) -> None:
    async with await get_connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM lessons WHERE id = ?;", (lesson_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return
        curr = dict(row)
        new_title = title if title is not None else curr["title"]
        new_desc = description if description is not None else curr["description"]
        new_video = video_file_id if video_file_id is not None else curr["video_file_id"]
        new_pdf = pdf_file_id if pdf_file_id is not None else curr["pdf_file_id"]

        await conn.execute(
            """
            UPDATE lessons
            SET title = ?, description = ?, video_file_id = ?, pdf_file_id = ?
            WHERE id = ?;
            """,
            (new_title, new_desc, new_video, new_pdf, lesson_id),
        )
        await conn.commit()


async def delete_lesson(lesson_id: str) -> None:
    async with await get_connection() as conn:
        await conn.execute("DELETE FROM quizzes WHERE lesson_id = ?;", (lesson_id,))
        await conn.execute("DELETE FROM user_progress WHERE lesson_id = ?;", (lesson_id,))
        await conn.execute("DELETE FROM lessons WHERE id = ?;", (lesson_id,))
        await conn.commit()


# ==========================================
# PROGRESS & COMPLETION OPERATIONS
# ==========================================

async def get_user_progress(user_id: int) -> dict[str, dict[str, Any]]:
    """Return dictionary mapping lesson_id -> progress record."""
    async with await get_connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM user_progress WHERE user_id = ?;", (user_id,)
        )
        rows = await cursor.fetchall()
        return {r["lesson_id"]: dict(r) for r in rows}


async def mark_lesson_completed(
    user_id: int, lesson_id: str, quiz_score: int = 0, quiz_passed: bool = True
) -> None:
    now = _utc_now()
    async with await get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO user_progress (user_id, lesson_id, is_completed, quiz_score, quiz_passed, completed_at)
            VALUES (?, ?, 1, ?, ?, ?)
            ON CONFLICT(user_id, lesson_id) DO UPDATE SET
                is_completed = 1,
                quiz_score = excluded.quiz_score,
                quiz_passed = excluded.quiz_passed,
                completed_at = excluded.completed_at;
            """,
            (user_id, lesson_id, quiz_score, 1 if quiz_passed else 0, now),
        )
        await conn.commit()


async def is_lesson_unlocked(user_id: int, lesson_id: str) -> bool:
    """Check if the user has completed all previous lessons in order."""
    lessons = await get_lessons(active_only=True)
    target_idx = -1
    for idx, l in enumerate(lessons):
        if l["id"] == lesson_id:
            target_idx = idx
            break

    if target_idx <= 0:
        return True  # First lesson or not found is open

    prev_lesson = lessons[target_idx - 1]
    async with await get_connection() as conn:
        cursor = await conn.execute(
            """
            SELECT is_completed FROM user_progress
            WHERE user_id = ? AND lesson_id = ?;
            """,
            (user_id, prev_lesson["id"]),
        )
        row = await cursor.fetchone()
        return bool(row and row["is_completed"])


async def get_user_stats(user_id: int) -> dict[str, Any]:
    """Get overall stats for user profile."""
    lessons = await get_lessons(active_only=True)
    total_lessons = len(lessons)

    async with await get_connection() as conn:
        cursor = await conn.execute(
            """
            SELECT COUNT(*) as completed_count
            FROM user_progress
            WHERE user_id = ? AND is_completed = 1;
            """,
            (user_id,),
        )
        completed = (await cursor.fetchone())["completed_count"]

    percent = int((completed / total_lessons * 100)) if total_lessons > 0 else 0
    return {
        "total_lessons": total_lessons,
        "completed_lessons": completed,
        "percent": percent,
    }


# ==========================================
# QUIZ OPERATIONS
# ==========================================

async def get_quizzes_for_lesson(lesson_id: str) -> list[dict[str, Any]]:
    async with await get_connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM quizzes WHERE lesson_id = ? ORDER BY created_at ASC;",
            (lesson_id,),
        )
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["options"] = json.loads(d["options_json"])
            except Exception:
                d["options"] = []
            result.append(d)
        return result


async def add_quiz(
    lesson_id: str,
    question: str,
    options: list[str],
    correct_option_index: int,
    explanation: str = "",
) -> str:
    quiz_id = uuid.uuid4().hex[:12]
    now = _utc_now()
    async with await get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO quizzes (
                id, lesson_id, question, options_json, correct_option_index, explanation, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                quiz_id,
                lesson_id,
                question,
                json.dumps(options, ensure_ascii=False),
                correct_option_index,
                explanation,
                now,
            ),
        )
        await conn.commit()
    return quiz_id


async def delete_quizzes_for_lesson(lesson_id: str) -> None:
    async with await get_connection() as conn:
        await conn.execute("DELETE FROM quizzes WHERE lesson_id = ?;", (lesson_id,))
        await conn.commit()


# ==========================================
# CHANNEL OPERATIONS
# ==========================================

async def get_required_channels() -> list[dict[str, Any]]:
    async with await get_connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM channels WHERE is_active = 1 ORDER BY created_at ASC;"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def add_channel(channel_id: str | int, title: str, join_link: str = "") -> None:
    now = _utc_now()
    async with await get_connection() as conn:
        await conn.execute(
            """
            INSERT OR REPLACE INTO channels (channel_id, title, join_link, is_active, created_at)
            VALUES (?, ?, ?, 1, ?);
            """,
            (str(channel_id), title, join_link, now),
        )
        await conn.commit()


async def delete_channel(channel_id: str | int) -> None:
    async with await get_connection() as conn:
        await conn.execute(
            "DELETE FROM channels WHERE channel_id = ?;", (str(channel_id),)
        )
        await conn.commit()


async def get_referral_channel() -> dict[str, Any] | None:
    ref_id = await get_setting("referral_channel_id", "")
    channels = await get_required_channels()
    if ref_id:
        for ch in channels:
            if str(ch["channel_id"]) == str(ref_id):
                return ch
    return channels[0] if channels else None


# ==========================================
# SETTINGS OPERATIONS
# ==========================================

async def get_setting(key: str, default: str = "") -> str:
    async with await get_connection() as conn:
        cursor = await conn.execute(
            "SELECT value FROM settings WHERE key = ?;", (key,)
        )
        row = await cursor.fetchone()
        return str(row["value"]) if row else default


async def set_setting(key: str, value: str) -> None:
    async with await get_connection() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?);",
            (key, str(value)),
        )
        await conn.commit()


async def get_required_invites() -> int:
    val = await get_setting("required_invites", "0")
    try:
        return max(0, int(val))
    except ValueError:
        return 0


async def is_maintenance_mode() -> bool:
    val = await get_setting("maintenance_mode", "false")
    return val.lower() in ("true", "1", "yes")
