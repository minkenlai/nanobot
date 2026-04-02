from __future__ import annotations

import asyncio
import os
import sys
import traceback
from datetime import datetime
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
    content += "- `/repl`: Execute Python code in the current environment\n"
    content += "- `/restart`: Refresh code in-place (preserves PID)\n"
    content += "- `/restart --full`: Graceful full reboot (requires systemd)\n"
    content += "- `/halt`: Stop the gateway process (Manual mode only)\n"
    content += "- `/RIP`: Witty alias for `/halt`\n"
    return OutboundMessage(address=msg.address, content=content)


async def cmd_status(ctx: CommandContext) -> OutboundMessage:
    """Show system status and version."""
    import time

    msg = ctx.msg
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)

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

    # Uptime
    uptime_s = int(time.time() - getattr(loop, "_start_time", time.time()))
    uptime_str = f"{uptime_s // 60}m {uptime_s % 60}s"

    # Tokens
    usage = loop.get_usage(msg.session_key)

    # Context Estimation
    try:
        context_tokens, _ = loop.memory_consolidator.estimate_session_prompt_tokens(session)
        # Assuming a default window for the stat
        window = getattr(loop, "context_window_tokens", 64000)
        pct = int(context_tokens / window * 100) if window else 0
        context_str = f"{context_tokens // 1000}k/{window // 1000}k ({pct}%)"
    except Exception:
        context_str = "unknown"

    # Tasks
    running_tasks = getattr(loop.subagents, "get_running_count", lambda: 0)()

    content = f"**System Status:** {status}\n"
    content += f"**Branch:** `{branch}`\n"
    content += f"**Commit:** `{sha}`\n"
    content += f"**PID:** `{os.getpid()}`\n\n"

    model = getattr(loop.provider, "get_default_model", lambda: "unknown")()
    content += f"**Model:** `{model}`\n"
    content += (
        f"**Tokens:** {usage.get('input_tokens', 0):,} in / {usage.get('output_tokens', 0):,} out\n"
    )
    content += f"**Context:** {context_str}\n"
    content += f"**Session:** {len(session.messages)} messages\n"
    content += f"**Tasks:** {running_tasks} active\n"
    content += f"**Uptime:** {uptime_str}"

    # Render as text so it looks nice
    return OutboundMessage(address=msg.address, content=content, metadata={"render_as": "text"})


async def cmd_stop(ctx: CommandContext) -> OutboundMessage:
    """Stop all active tasks in the current session."""
    from loguru import logger

    logger.error(
        f"CMD STOP session_key: {ctx.msg.session_key}, active_tasks keys: {list(ctx.loop._active_tasks.keys())}"
    )
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


async def cmd_repl(ctx: CommandContext) -> OutboundMessage:
    """Execute Python code in the current environment."""
    msg = ctx.msg
    loop = ctx.loop
    code = ctx.raw or ""

    repl_cfg = loop.config.repl
    if not repl_cfg.enable:
        return OutboundMessage(
            address=msg.address,
            content="🛑 **REPL is disabled.** Enable it in `config.json` via `repl.enable: true` to use this command.",
        )

    # Check user-based ACL
    if repl_cfg.allow_users:
        user_key = f"{msg.channel}:{msg.sender_id}"
        if user_key not in repl_cfg.allow_users:
            from loguru import logger

            logger.warning("REPL access denied for user: {}", user_key)
            return OutboundMessage(
                address=msg.address,
                content="🛑 **Access Denied:** You are not authorized to use the REPL command.",
            )

    if not code.strip():
        return OutboundMessage(address=msg.address, content="Usage: `/repl <python statement>`")

    log_file = loop.workspace / "logs" / "repl.log"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target = msg.address.to_uri()

    # Prepare environment for execution
    env = {
        "ctx": ctx,
        "loop": loop,
        "session": ctx.session,
        "msg": msg,
        "asyncio": asyncio,
        "os": os,
        "sys": sys,
    }

    import io
    from contextlib import redirect_stdout

    output = ""
    stdout_buf = io.StringIO()
    try:
        with redirect_stdout(stdout_buf):
            # Try to evaluate as an expression first
            try:
                result = eval(code, env)
                if asyncio.iscoroutine(result):
                    result = await result
                output = repr(result)
            except SyntaxError:
                # If eval fails, it might be a statement
                exec(code, env)
                if "result" in env:
                    result = env["result"]
                    if asyncio.iscoroutine(result):
                        result = await result
                    output = repr(result)
                else:
                    output = "Done (no result variable set)"
    except Exception:
        output = traceback.format_exc()

    stdout_val = stdout_buf.getvalue()
    if stdout_val:
        output = f"--- stdout ---\n{stdout_val}\n--- return ---\n{output}"

    # Log to repl.log
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as f:
            f.write(f"[{now}] REPL {target}\nIN:  {code}\nOUT: {output}\n{'-' * 40}\n")
    except Exception:
        pass

    return OutboundMessage(
        address=msg.address,
        content=f"**REPL Output:**\n```python\n{output}\n```",
    )


def register_builtin_commands(router: CommandRouter) -> None:
    """Register all builtin commands."""
    router.exact("/new", cmd_new)
    router.exact("/help", cmd_help)
    router.exact("/status", cmd_status)
    router.priority("/stop", cmd_stop)
    router.priority("/repl", cmd_repl)
    router.priority("/restart", cmd_restart)
    router.priority("/halt", cmd_halt)
    router.priority("/RIP", cmd_halt)
