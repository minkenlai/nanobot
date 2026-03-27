---
name: anacron
description: Catch up on missed cron reminders after server downtime. Use when the user asks to check for missed reminders, greets implying some time away, or run periodically via HEARTBEAT.md.
---

# Anacron

The `anacron` skill provides a script to catch up on missed non-recurring cron jobs (`kind: "at"`) after the nanobot gateway has been offline.

## How it works

The script reads the cron `jobs.json` file and looks for `at` jobs that were scheduled to run in the past.
- **Grace Period:** Jobs older than 7 days are safely disabled.
- **Avalanche Control:** If there are more than 3 missed jobs, it suppresses individual pings and creates a single consolidated summary message.
- **Contextual Tagging:** If there are 3 or fewer missed jobs, they are executed immediately with a `⏰ [Missed Reminder]` prefix.

## Usage

To check for missed reminders, execute the catchup script:

```bash
python3 /mnt/wsl/workspace/nanobot/nanobot/skills/anacron/scripts/catchup.py
```

You can run this manually when requested, or add it to `HEARTBEAT.md` to run periodically.
