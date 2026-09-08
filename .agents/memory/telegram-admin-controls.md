---
name: Telegram admin controls
description: Admin-configurable access rules and referral tracking for the Telegram bot.
---

The admin panel supports multiple mandatory channels and an optional invite threshold. Invite counts are credited only when a new user opens the bot through the inviter's `ref_<user_id>` deep link and joins the selected referral channel; the threshold gates lesson access after channel checks. Private invite links are join URLs, not chat IDs.

**Why:** The bot owner asked to control access rules entirely from Telegram without a web panel or external database.

**How to apply:** Keep access settings and referral counters in local JSON, and make new admin-controlled rules pass through the same subscription gate before exposing lessons. Store private channels with their numeric `-100...` chat ID plus a separate `https://t.me/+...` join link.