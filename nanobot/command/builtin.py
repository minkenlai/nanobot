from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.bus.events import OutboundMessage

if TYPE_CHECKING:
    from nanobot.command import CommandContext, CommandRouter


async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """Show help for builtin commands."""
    msg = ctx.msg
    content = "**Available Commands:**\n"
    content += "- `/help`: Show this help\n"
    content += "- `/usage`: Show token usage for the current session\n"
    content += "- `/stop`: Cancel all active tasks in this session\n"
    content += "- `/restart`: Refresh code in-place (preserves PID)\n"
    content += "- `/restart --full`: Graceful full reboot (requires systemd)\n"
    content += "- `/shutdown`: Stop the gateway process (Manual mode only)\n"
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
            "If I perform a full restart, I won't be able to come back! "
            "Use `/restart` (in-place) to refresh code, or `/shutdown` to stop.",
        )

    async def _do_restart():
        # Record intent in lifecycle.log for the new process to pick up
        from datetime import datetime

        log_file = loop.workspace / "logs" / "lifecycle.log"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Use URI format for the target
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
            # For a full restart, we just stop the loop.
            # Systemd's Restart=always will handle the rest.
            loop.stop()
        else:
            # In-place restart preserves the PID
            os.execv(sys.executable, [sys.executable, "-m", "nanobot"] + sys.argv[1:])

    asyncio.create_task(_do_restart())
    content = (
        "🔄 Restarting (full)... See you in a moment!"
        if is_full
        else "🔄 Restarting in-place..."
    )
    return OutboundMessage(address=msg.address, content=content)


async def cmd_shutdown(ctx: CommandContext) -> OutboundMessage:
    """Gracefully shut down the process."""
    msg = ctx.msg
    loop = ctx.loop

    if loop.is_supervised:
        return OutboundMessage(
            address=msg.address,
            content="🛑 **Abort:** I am running under systemd. If I shut down, I will be "
            "restarted automatically! Please stop the service from the terminal "
            "if you want me to stay off.",
        )

    async def _do_shutdown():
        await asyncio.sleep(1)
        loop.stop()

    asyncio.create_task(_do_shutdown())
    return OutboundMessage(address=msg.address, content="👋 Goodbye! Shutting down...")


async def cmd_usage(ctx: CommandContext) -> OutboundMessage:
    """Show usage statistics for the current session."""
    msg = ctx.msg
    loop = ctx.loop
    usage = loop.get_usage(msg.session_key)
    content = f"**Token Usage (Session):**\n"
    content += f"- Input: {usage.get('input_tokens', 0):,}\n"
    content += f"- Output: {usage.get('output_tokens', 0):,}\n"
    content += f"- Total: {usage.get('total_tokens', 0):,}"
    return OutboundMessage(address=msg.address, content=content)


def register_builtin_commands(router: "CommandRouter") -> None:
    """Register all builtin commands."""
    router.exact("/help", cmd_help)
    router.exact("/stop", cmd_stop)
    router.exact("/restart", cmd_restart)
    router.exact("/usage", cmd_usage)
    router.exact("/shutdown", cmd_shutdown)
