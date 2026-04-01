from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

from nanobot.bus.events import OutboundMessage

if TYPE_CHECKING:
    from nanobot.command import CommandContext, CommandRouter


async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """Show help for builtin commands."""
    msg = ctx.msg
    content = "**Available Commands:**\n"
    content += "- `/new`: Start a fresh conversation (clears context)\n"
    content += "- `/help`: Show this help\n"
    content += "- `/status`: Show system status and version\n"
    content += "- `/tasks`: List current and recent background tasks\n"
    content += "- `/usage`: Show token usage for the current session\n"
    content += "- `/stop`: Cancel all active tasks in this session\n"
    content += "- `/restart`: Refresh code in-place (preserves PID)\n"
    content += "- `/restart --full`: Graceful full reboot (requires systemd)\n"
    content += "- `/halt`: Stop the gateway process (Manual mode only)\n"
    content += "- `/RIP`: Witty alias for `/halt`\n"
    return OutboundMessage(address=msg.address, content=content)


async def cmd_status(ctx: CommandContext) -> OutboundMessage:
    """Show system status and version."""
    msg = ctx.msg
    loop = ctx.loop

    # Get version/commit info if possible
    sha = "unknown"
    branch = "unknown"
    try:
        import subprocess

        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=loop.workspace / "nanobot-dev", text=True
        ).strip()
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=loop.workspace / "nanobot-dev",
            text=True,
        ).strip()
    except Exception:
        pass

    status = "🟢 Running"
    if loop.is_supervised:
        status += " (Supervised)"
    else:
        status += " (Manual)"

    content = f"**System Status:** {status}\n"
    content += f"**Branch:** `{branch}`\n"
    content += f"**Commit:** `{sha}`\n"
    content += f"**PID:** `{os.getpid()}`"
    return OutboundMessage(address=msg.address, content=content)


async def cmd_stop(ctx: CommandContext) -> OutboundMessage:
    """Stop all active tasks in the current session."""
    msg = ctx.msg
    loop = ctx.loop
    cancelled = await loop.stop_tasks_by_session(msg.session_key)
    sub_cancelled = await loop.subagents.cancel_by_session(msg.session_key)
    total = cancelled + sub_cancelled
    content = f"Stopped {total} task(s)." if total else "No active task to stop."
    return OutboundMessage(address=msg.address, content=content)


async def cmd_restart(ctx: CommandContext) -> OutboundMessage:
    """Restart the process (in-place or full via systemd)."""
    msg = ctx.msg
    loop = ctx.loop
    raw = ctx.raw or ""
    args = raw.split()
    is_full = "--full" in args or "-f" in args

    if is_full and not loop.is_supervised:
        return OutboundMessage(
            address=msg.address,
            content="🛑 **Abort:** I am not running under a supervisor (systemd). "
            "Use `/restart` (in-place) to refresh code, or `/shutdown` to stop.",
        )

    async def _do_restart():
        from datetime import datetime

        log_file = loop.workspace / "logs" / "lifecycle.log"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        target = msg.address.to_uri()

        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with log_file.open("a", encoding="utf-8") as f:
                type_str = "FULL" if is_full else "IN-PLACE"
                f.write(f"[{now}] SHUTDOWN: RESTART_REQ {target} ({type_str})\n")
        except Exception:
            pass

        await asyncio.sleep(1)

        if is_full:
            loop.stop()
        else:
            os.execv(sys.executable, [sys.executable, "-m", "nanobot"] + sys.argv[1:])

    asyncio.create_task(_do_restart())
    content = (
        "🔄 Restarting (full)... See you in a moment!" if is_full else "🔄 Restarting in-place..."
    )
    return OutboundMessage(address=msg.address, content=content)


async def cmd_halt(ctx: CommandContext) -> OutboundMessage:
    """Gracefully shut down the process."""
    msg = ctx.msg
    loop = ctx.loop

    if loop.is_supervised:
        return OutboundMessage(
            address=msg.address,
            content="🛑 **Abort:** I am running under systemd. "
            "Please stop the service via systemd if you want me to stay off.",
        )

    async def _do_halt():
        await asyncio.sleep(1)
        loop.stop()

    asyncio.create_task(_do_halt())
    return OutboundMessage(address=msg.address, content="👋 Goodbye! Halting...")


async def cmd_usage(ctx: CommandContext) -> OutboundMessage:
    """Show usage statistics for the current session."""
    msg = ctx.msg
    loop = ctx.loop
    usage = loop.get_usage(msg.session_key)
    content = "**Token Usage (Session):**\n"
    content += f"- Input: {usage.get('input_tokens', 0):,}\n"
    content += f"- Output: {usage.get('output_tokens', 0):,}\n"
    content += f"- Total: {usage.get('total_tokens', 0):,}"
    return OutboundMessage(address=msg.address, content=content)


async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """Start a fresh session."""
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    snapshot = session.messages[session.last_consolidated :]
    session.clear()
    loop.sessions.save(session)
    loop.sessions.invalidate(session.key)
    if snapshot:
        loop._schedule_background(loop.memory_consolidator.archive_messages(snapshot))
    return OutboundMessage(
        address=ctx.msg.address,
        content="New session started.",
    )


async def cmd_tasks(ctx: CommandContext) -> OutboundMessage:
    """List current and recent background tasks."""
    msg = ctx.msg
    loop = ctx.loop
    records = loop.subagents.get_all_records()

    if not records:
        return OutboundMessage(address=msg.address, content="No background tasks found.")

    content = "**Background Tasks (Recent):**\n\n"
    for r in records[:10]:  # Show last 10
        status_emoji = {"running": "⚙️", "done": "✅", "error": "❌"}.get(r.status, "❓")
        started = r.started_at.strftime("%H:%M:%S")
        content += f"{status_emoji} **{r.label}** (`{r.task_id}`)\n"
        content += f"  - Status: {r.status} (Started: {started})\n"
        if r.result_summary:
            content += f"  - Result: {r.result_summary}\n"
        content += "\n"

    return OutboundMessage(address=msg.address, content=content)


def register_builtin_commands(router: CommandRouter) -> None:
    """Register all builtin commands."""
    router.exact("/new", cmd_new)
    router.exact("/help", cmd_help)
    router.exact("/status", cmd_status)
    router.exact("/tasks", cmd_tasks)
    router.exact("/usage", cmd_usage)
    router.priority("/stop", cmd_stop)
    router.priority("/restart", cmd_restart)
    router.priority("/halt", cmd_halt)
    router.priority("/RIP", cmd_halt)
