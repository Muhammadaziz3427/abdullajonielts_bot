---
name: Telegram bot storage
description: Storage and access model for the Telegram education bot.
---

The bot intentionally keeps only Telegram file IDs and metadata in local JSON files; uploaded videos and PDFs remain on Telegram's servers, and no external database is part of the design.

**Why:** The product requirement explicitly avoids MySQL, PostgreSQL, and external file storage while still allowing admins to send files directly to the bot.

**How to apply:** Preserve the JSON-only model when adding bot features; do not introduce a database or download Telegram media unless the product requirement changes.