"""Execution helpers for session-bound cron jobs."""

from __future__ import annotations

import asyncio
import hashlib
import sys
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Protocol

from nanobot.agent.tools.cron import CronTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.cron.session_delivery import (
    has_custom_target,
    origin_delivery_context,
    target_delivery_context,
)
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
    use_target: bool = False,
) -> tuple[str, str, dict[str, Any]]:
    if use_target and has_custom_target(job):
        channel, chat_id, metadata = target_delivery_context(job)
    else:
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
        use_target=True,
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
    if has_custom_target(job):
        run_record_base["target_channel"] = channel
        run_record_base["target_chat_id"] = chat_id

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
        target_session = (
            f"{channel}:{chat_id}"
            if has_custom_target(job) and job.payload.record_session
            else session_key
        )
        resp = await agent.submit_cron_turn(
            InboundMessage(
                channel=channel,
                sender_id="cron",
                chat_id=chat_id,
                content=prompt,
                metadata=metadata,
                session_key_override=target_session,
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
    exec_config: Any | None = None,
) -> str | None:
    """Execute a session-bound deterministic cron job (command, skill script, or direct message) without LLM."""
    session_key = job.payload.session_key
    if not session_key:
        raise ValueError(f"cron job {job.id} is missing payload.session_key")

    run_id = f"{job.id}:{int(time.time() * 1000)}:{uuid.uuid4().hex[:8]}"
    origin_channel, origin_chat_id, origin_metadata = _bound_session_delivery_context(
        job,
        turn_seed=f"cron:{job.id}",
        source_label=job.name,
        use_target=False,
    )
    target_channel, target_chat_id, target_metadata = _bound_session_delivery_context(
        job,
        turn_seed=f"cron:{job.id}",
        source_label=job.name,
        use_target=True,
    )
    is_custom_target = has_custom_target(job)

    origin_metadata[CRON_TRIGGER_META] = {
        "job_id": job.id,
        "job_name": job.name,
        "run_id": run_id,
        "persist_content": f"Scheduled deterministic job triggered: {job.name}",
    }
    target_metadata[CRON_TRIGGER_META] = {
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
    if is_custom_target:
        run_record_base["target_channel"] = target_channel
        run_record_base["target_chat_id"] = target_chat_id

    cron.write_run_record(
        run_id,
        {
            **run_record_base,
            "status": "running",
        },
    )

    try:
        stdout_str = ""
        stderr_str = ""
        if job.payload.kind == "direct_message":
            msg_text = (job.payload.message or "").strip()
            if not msg_text:
                raise ValueError("direct_message cron job requires a non-empty message")
            stdout_str = msg_text
            response = msg_text

        elif job.payload.kind == "exec_command":
            cmd = (job.payload.command or job.payload.message or "").strip()
            if not cmd:
                raise ValueError("exec_command cron job requires a non-empty command")
            exec_cmd = cmd
            sandbox = getattr(exec_config, "sandbox", "") or ""
            if sandbox and sys.platform != "win32":
                from nanobot.agent.tools.sandbox import wrap_command

                sandbox_ro_binds = list(getattr(exec_config, "sandbox_ro_binds", []) or [])
                sandbox_rw_binds = list(getattr(exec_config, "sandbox_rw_binds", []) or [])
                exec_cmd = wrap_command(
                    sandbox,
                    cmd,
                    str(workspace),
                    str(workspace),
                    sandbox_ro_binds=sandbox_ro_binds,
                    sandbox_rw_binds=sandbox_rw_binds,
                )
            proc = await asyncio.create_subprocess_shell(
                exec_cmd,
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
                    # Anomalous/error output always routes to the originating session
                    await deliver_callback(
                        OutboundMessage(
                            channel=origin_channel,
                            chat_id=origin_chat_id,
                            content=response,
                            metadata=origin_metadata,
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

            if stdout_str and stderr_str:
                response = f"{stdout_str}\n[stderr]: {stderr_str}"
            elif stderr_str:
                response = f"Scheduled task '{job.name}' completed with no output.\n[stderr]: {stderr_str}"
            else:
                response = stdout_str or f"Scheduled task '{job.name}' completed with no output."

        elif job.payload.kind == "skill_script":
            skill_name = (job.payload.skill_name or "").strip()
            script_name = (job.payload.script_name or "").strip()
            args = job.payload.args or []
            if not skill_name or not script_name:
                raise ValueError("skill_script cron job requires skill_name and script_name")

            from nanobot.agent.tools.skill_script import RunSkillScriptTool

            sandbox = getattr(exec_config, "sandbox", "") or ""
            sandbox_ro_binds = list(getattr(exec_config, "sandbox_ro_binds", []) or [])
            sandbox_rw_binds = list(getattr(exec_config, "sandbox_rw_binds", []) or [])

            tool = RunSkillScriptTool(
                workspace=workspace,
                timeout=timeout,
                sandbox=sandbox,
                sandbox_ro_binds=sandbox_ro_binds,
                sandbox_rw_binds=sandbox_rw_binds,
            )  # pyright: ignore[reportAbstractUsage]
            res = await tool.execute(skill_name=skill_name, script_name=script_name, args=args)
            if getattr(res, "is_error", False):
                err_msg = str(res)
                response = f"⚠️ Scheduled task '{job.name}' failed:\n{err_msg}"
                if deliver_callback is not None:
                    # Anomalous/error output always routes to the originating session
                    await deliver_callback(
                        OutboundMessage(
                            channel=origin_channel,
                            chat_id=origin_chat_id,
                            content=response,
                            metadata=origin_metadata,
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

            raw_stdout = getattr(res, "stdout", None)
            raw_stderr = getattr(res, "stderr", None)
            if raw_stdout is None and raw_stderr is None:
                res_str = str(res).strip()
                no_output_marker = f"Skill script '{script_name}' executed successfully with no output."
                stdout_str = "" if res_str == no_output_marker else res_str
                stderr_str = ""
            else:
                stdout_str = raw_stdout or ""
                stderr_str = raw_stderr or ""

            if stdout_str and stderr_str:
                response = f"{stdout_str}\n[stderr]: {stderr_str}"
            elif stderr_str:
                response = f"Skill script '{script_name}' completed with no output.\n[stderr]: {stderr_str}"
            else:
                response = stdout_str or f"Skill script '{script_name}' executed successfully with no output."
        else:
            raise ValueError(f"Unsupported deterministic cron payload kind: {job.payload.kind}")

        if deliver_callback is not None:
            if is_custom_target:
                # Custom destination routing: route stdout to target, stderr to origin
                if stdout_str:
                    target_session_key = f"{target_channel}:{target_chat_id}"
                    await deliver_callback(
                        OutboundMessage(
                            channel=target_channel,
                            chat_id=target_chat_id,
                            content=stdout_str,
                            metadata=target_metadata,
                        ),
                        record=job.payload.record_session,
                        session_key=target_session_key,
                    )
                if stderr_str:
                    stderr_msg = f"⚠️ Scheduled task '{job.name}' [stderr]:\n{stderr_str}"
                    await deliver_callback(
                        OutboundMessage(
                            channel=origin_channel,
                            chat_id=origin_chat_id,
                            content=stderr_msg,
                            metadata=origin_metadata,
                        ),
                        record=True,
                        session_key=session_key,
                    )
                elif not stdout_str and not job.payload.quiet:
                    # No output and quiet is False: deliver notification to origin
                    await deliver_callback(
                        OutboundMessage(
                            channel=origin_channel,
                            chat_id=origin_chat_id,
                            content=response,
                            metadata=origin_metadata,
                        ),
                        record=False,
                        session_key=session_key,
                    )
            else:
                has_output = bool(stdout_str or stderr_str)
                if has_output:
                    await deliver_callback(
                        OutboundMessage(
                            channel=origin_channel,
                            chat_id=origin_chat_id,
                            content=response,
                            metadata=origin_metadata,
                        ),
                        record=job.payload.record_session,
                        session_key=session_key,
                    )
                elif not job.payload.quiet:
                    await deliver_callback(
                        OutboundMessage(
                            channel=origin_channel,
                            chat_id=origin_chat_id,
                            content=response,
                            metadata=origin_metadata,
                        ),
                        record=False,
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
