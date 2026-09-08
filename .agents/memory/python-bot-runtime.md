---
name: Python bot runtime
description: Replit runtime setup needed for the Python Telegram bot.
---

The base Python runtime does not include usable pip tooling for this bot. Install a Python tools runtime before installing aiogram dependencies, then run the bot through its console workflow.

**Why:** Installing aiogram directly against the base runtime is blocked by the externally managed Python environment; the tools runtime provides the project-local package path.

**How to apply:** For future Python dependency changes, keep the Python tools runtime and update `requirements.txt`; do not try to mutate the immutable global Python installation.