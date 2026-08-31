"""Execution helpers for session-bound cron jobs."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Protocol

from nanobot.agent.tools.cron import CronTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.cron.session_delivery import origin_delivery_context
from nanobot.cron.session_turns import CRON_DEFER_UNTIL_IDLE_META, CRON_TRIGGER_META
from nanobot.cron.types import CronJob
from nanobot.cron.webui_metadata import cron_proactive_delivery_metadata
from nanobot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from nanobot.agent.tools.registry import ToolRegistry


class BoundCronAgent(Protocol):
    tools: ToolRegistry

    async def submit_cron_turn(self, msg: InboundMessage) -> OutboundMessage | None:
        ...


class CronRunRecorder(Protocol):
    def write_run_record(self, run_id: str, record: dict[str, Any]) -> None:
        ...


def _cron_prompt_ref(prompt: str) -> dict[str, Any]:
    return {
        "id": "cron.agent_turn.reminder",
        "version": 1,
        "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }


def _bound_session_delivery_context(
    job: CronJob,
    *,
    turn_seed: str,
    source_label: str | None,
) -> tuple[str, str, dict[str, Any]]:
    channel, chat_id, metadata = origin_delivery_context(job)

    if channel == "websocket":
        metadata["webui"] = True
        metadata.update(
            cron_proactive_delivery_metadata(
                "websocket",
                metadata,
                turn_seed=turn_seed,
                source_label=source_label,
            )
        )

    return channel, chat_id, metadata


async def run_bound_cron_job(
    job: CronJob,
    *,
    agent: BoundCronAgent,
    cron: CronRunRecorder,
) -> str | None:
    """Execute a session-bound cron job as a normal agent session turn."""
    session_key = job.payload.session_key
    if not session_key:
        raise ValueError(f"cron job {job.id} is missing payload.session_key")

    prompt = render_template(
        "agent/cron_reminder.md",
        strip=True,
        message=job.payload.message,
    )
    prompt_ref = _cron_prompt_ref(prompt)
    run_id = f"{job.id}:{int(time.time() * 1000)}:{uuid.uuid4().hex[:8]}"
    channel, chat_id, metadata = _bound_session_delivery_context(
        job,
        turn_seed=f"cron:{job.id}",
        source_label=job.name,
    )
    metadata[CRON_TRIGGER_META] = {
        "job_id": job.id,
        "job_name": job.name,
        "run_id": run_id,
        "prompt_ref": prompt_ref,
        "persist_content": (
            f"Scheduled cron job triggered: {job.name}\n\n{job.payload.message}"
        ),
    }
    metadata[CRON_DEFER_UNTIL_IDLE_META] = True
    run_record_base: dict[str, Any] = {
        "job_id": job.id,
        "job_name": job.name,
        "session_key": session_key,
        "prompt_ref": prompt_ref,
        "prompt_vars": {"message": job.payload.message},
        "rendered_prompt": prompt,
    }

    cron.write_run_record(
        run_id,
        {
            **run_record_base,
            "status": "queued",
        },
    )

    cron_tool = agent.tools.get("cron")
    cron_token = None
    if isinstance(cron_tool, CronTool):
        cron_token = cron_tool.set_cron_context(True)
    try:
        resp = await agent.submit_cron_turn(
            InboundMessage(
                channel=channel,
                sender_id="cron",
                chat_id=chat_id,
                content=prompt,
                metadata=metadata,
                session_key_override=session_key,
            )
        )
    except (Exception, asyncio.CancelledError) as exc:
        error_text = str(exc) or exc.__class__.__name__
        cron.write_run_record(
            run_id,
            {
                **run_record_base,
                "status": "error",
                "error": error_text,
            },
        )
        raise
    finally:
        if isinstance(cron_tool, CronTool) and cron_token is not None:
            cron_tool.reset_cron_context(cron_token)

    response = resp.content if resp else ""
    cron.write_run_record(
        run_id,
        {
            **run_record_base,
            "status": "ok",
            "response": response,
        },
    )
    return response


async def run_bound_deterministic_cron_job(
    job: CronJob,
    *,
    workspace: Path,
    deliver_callback: Callable[..., Coroutine[Any, Any, None]] | None = None,
    cron: CronRunRecorder,
    timeout: float = 120.0,
) -> str | None:
    """Execute a session-bound deterministic cron job (command or skill script) without LLM."""
    session_key = job.payload.session_key
    if not session_key:
        raise ValueError(f"cron job {job.id} is missing payload.session_key")

    run_id = f"{job.id}:{int(time.time() * 1000)}:{uuid.uuid4().hex[:8]}"
    channel, chat_id, metadata = _bound_session_delivery_context(
        job,
        turn_seed=f"cron:{job.id}",
        source_label=job.name,
    )
    metadata[CRON_TRIGGER_META] = {
        "job_id": job.id,
        "job_name": job.name,
        "run_id": run_id,
        "persist_content": f"Scheduled deterministic job triggered: {job.name}",
    }

    run_record_base: dict[str, Any] = {
        "job_id": job.id,
        "job_name": job.name,
        "session_key": session_key,
        "kind": job.payload.kind,
    }

    cron.write_run_record(
        run_id,
        {
            **run_record_base,
            "status": "running",
        },
    )

    try:
        if job.payload.kind == "exec_command":
            cmd = (job.payload.command or job.payload.message or "").strip()
            if not cmd:
                raise ValueError("exec_command cron job requires a non-empty command")
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise TimeoutError(f"Command timed out after {timeout}s") from None

            stdout_str = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr_str = stderr_bytes.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                err_msg = stderr_str or stdout_str or f"Exited with code {proc.returncode}"
                response = f"⚠️ Scheduled task '{job.name}' failed (code {proc.returncode}):\n{err_msg}"
                if deliver_callback is not None:
                    await deliver_callback(
                        OutboundMessage(
                            channel=channel,
                            chat_id=chat_id,
                            content=response,
                            metadata=metadata,
                        ),
                        record=True,
                        session_key=session_key,
                    )
                cron.write_run_record(
                    run_id,
                    {
                        **run_record_base,
                        "status": "error",
                        "response": response,
                        "error": err_msg,
                    },
                )
                raise RuntimeError(err_msg)

            response = stdout_str or f"Scheduled task '{job.name}' completed with no output."
            if stderr_str:
                response += f"\n[stderr]: {stderr_str}"

        elif job.payload.kind == "skill_script":
            skill_name = (job.payload.skill_name or "").strip()
            script_name = (job.payload.script_name or "").strip()
            args = job.payload.args or []
            if not skill_name or not script_name:
                raise ValueError("skill_script cron job requires skill_name and script_name")

            from nanobot.agent.tools.skill_script import RunSkillScriptTool

            tool = RunSkillScriptTool(workspace=workspace, timeout=timeout)  # pyright: ignore[reportAbstractUsage]
            res = await tool.execute(skill_name=skill_name, script_name=script_name, args=args)
            if getattr(res, "is_error", False):
                err_msg = str(res)
                response = f"⚠️ Scheduled task '{job.name}' failed:\n{err_msg}"
                if deliver_callback is not None:
                    await deliver_callback(
                        OutboundMessage(
                            channel=channel,
                            chat_id=chat_id,
                            content=response,
                            metadata=metadata,
                        ),
                        record=True,
                        session_key=session_key,
                    )
                cron.write_run_record(
                    run_id,
                    {
                        **run_record_base,
                        "status": "error",
                        "response": response,
                        "error": err_msg,
                    },
                )
                raise RuntimeError(err_msg)

            response = str(res)
        else:
            raise ValueError(f"Unsupported deterministic cron payload kind: {job.payload.kind}")

        if deliver_callback is not None and response:
            await deliver_callback(
                OutboundMessage(
                    channel=channel,
                    chat_id=chat_id,
                    content=response,
                    metadata=metadata,
                ),
                record=True,
                session_key=session_key,
            )

        cron.write_run_record(
            run_id,
            {
                **run_record_base,
                "status": "ok",
                "response": response,
            },
        )
        return response

    except (Exception, asyncio.CancelledError) as exc:
        err = str(exc) or exc.__class__.__name__
        cron.write_run_record(
            run_id,
            {
                **run_record_base,
                "status": "error",
                "error": err,
            },
        )
        raise
