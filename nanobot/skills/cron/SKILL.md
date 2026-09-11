---
name: cron
description: Schedule reminders and recurring tasks.
---

# Cron

Use the `cron` tool to schedule reminders or recurring tasks that should report back to the originating chat/session when they run.

Do not use `cron` for periodic background checks that should stay quiet when there is nothing useful to report. For those, update `HEARTBEAT.md`; the protected heartbeat job runs those checks and only delivers results that pass the notification gate.

## Three Modes

1. **Reminder** - message is sent directly to user
2. **Task** - message is a task description, agent executes and sends result
3. **One-time** - runs once at a specific time, then auto-deletes

## Examples

Fixed reminder:
```
cron(action="add", message="Time to take a break!", every_seconds=1200)
```

Dynamic task (agent executes each time):
```
cron(action="add", message="Check HKUDS/nanobot GitHub stars and report", every_seconds=600)
```

Deterministic shell command (with quiet mode to only notify on non-empty output/error):
```
cron(action="add", command="python scripts/check_health.py", every_seconds=300, quiet=True)
```

Destination routing (route operational output to staff, error logs privately to admin):
```
cron(
  action="add",
  name="poll-leads",
  command="python scripts/poll_leads.py",
  channel="telegram",
  chat_id="-1001234567890",
  cron_expr="*/15 * * * *",
  quiet=True
)
```

Deterministic skill script execution:
```
cron(action="add", skill_name="my_skill", script_name="sync.py", every_seconds=600, quiet=True)
```

One-time scheduled task (compute ISO datetime from current time):
```
cron(action="add", message="Remind me about the meeting", at="<ISO datetime>")
```

Timezone-aware cron:
```
cron(action="add", message="Morning standup", cron_expr="0 9 * * 1-5", tz="America/Vancouver")
```

List/remove:
```
cron(action="list")
cron(action="remove", job_id="abc123")
```

## Destination Routing & Stream Decoupling

Scheduled jobs can specify an explicit destination (`channel`, `chat_id`, optional `thread_id`):
- **`stdout` (Operational Output)**: Delivered to the configured `channel` and `chat_id` (e.g., a staff Telegram/Discord/Slack channel).
- **`stderr` & Failures (Technical Errors)**: Automatically routed back to the **originating session** (the administrator/developer who created the job). This prevents technical logs, stack traces, and runtime warnings from cluttering client-facing or staff groups.
- If a job produces only `stderr` (or logs an error to stderr and exits 0), the target receives nothing, and the originating admin receives a `⚠️ Scheduled task '...' [stderr]:` notification.
- **`quiet=True`**: Suppresses notifications when there is no output, but still delivers operational `stdout` to target and technical `stderr` / errors to the origin.

## Time Expressions

| User says | Parameters |
|-----------|------------|
| every 20 minutes | every_seconds: 1200 |
| every hour | every_seconds: 3600 |
| every day at 8am | cron_expr: "0 8 * * *" |
| weekdays at 5pm | cron_expr: "0 17 * * 1-5" |
| 9am Vancouver time daily | cron_expr: "0 9 * * *", tz: "America/Vancouver" |
| at a specific time | at: ISO datetime string (compute from current time) |

## Timezone

Use `tz` with `cron_expr` to schedule in a specific IANA timezone. Without `tz`, the server's local timezone is used.

