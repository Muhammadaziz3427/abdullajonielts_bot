"""Bot configuration.

For Replit, set BOT_TOKEN and ADMIN_ID in the Secrets/environment variables
panel. The placeholder values below also make it clear what must be changed
when running the project locally.
"""

from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE").strip()

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

# This value is used only when settings.json is created for the first time.
# It can also be changed later from the Telegram /admin panel.
INITIAL_CHANNEL_ID = os.getenv("CHANNEL_ID", "@your_channel").strip()

USERS_FILE = DATA_DIR / "users.json"
LESSONS_FILE = DATA_DIR / "lessons.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
