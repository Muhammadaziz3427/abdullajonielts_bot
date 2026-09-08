"""Bot configuration.

Reads settings from environment variables or uses default values.
"""

from __future__ import annotations

import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

BOT_TOKEN = os.getenv("BOT_TOKEN", "8861024990:AAGVhWrMxB6nFO4B7Cme5i2EgE83fZj_xAI").strip()

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "1350472397"))
except ValueError:
    ADMIN_ID = 1350472397

INITIAL_CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()

USERS_FILE = DATA_DIR / "users.json"
LESSONS_FILE = DATA_DIR / "lessons.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
DB_FILE = DATA_DIR / "bot.db"
