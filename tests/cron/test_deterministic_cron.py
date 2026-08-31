"""Tests for deterministic cron jobs (exec_command and skill_script)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.cron import CronTool
from nanobot.bus.events import OutboundMessage
from nanobot.cron.bound_runner import run_bound_deterministic_cron_job
from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronPayload, CronSchedule


class _MockRecorder:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    def write_run_record(self, run_id: str, record: dict[str, Any]) -> None:
        self.records[run_id] = record


def test_cron_payload_store_dict_roundtrip() -> None:
    payload = CronPayload(
        kind="exec_command",
        command="python test.py",
        skill_name="my_skill",
        script_name="sync.py",
        args=["--verbose", "--force"],
        session_key="telegram:12345",
        origin_channel="telegram",
        origin_chat_id="12345",
    )
    store_dict = {
        "kind": payload.kind,
        "command": payload.command,
        "skillName": payload.skill_name,
        "scriptName": payload.script_name,
        "args": payload.args,
        "sessionKey": payload.session_key,
        "originChannel": payload.origin_channel,
        "originChatId": payload.origin_chat_id,
    }
    restored = CronPayload.from_store_dict(store_dict)
    assert restored.kind == "exec_command"
    assert restored.command == "python test.py"
    assert restored.skill_name == "my_skill"
    assert restored.script_name == "sync.py"
    assert restored.args == ["--verbose", "--force"]
    assert restored.session_key == "telegram:12345"


def test_cron_tool_add_exec_command(tmp_path: Path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    tool = CronTool(service)

    with request_context(
        RequestContext(channel="telegram", chat_id="123", session_key="telegram:123")
    ):
        result = asyncio.run(
            tool.execute(
                action="add",
                command="echo 'hello world'",
                every_seconds=60,
            )
        )
    assert "Created job" in result
    jobs = service.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].payload.kind == "exec_command"
    assert jobs[0].payload.command == "echo 'hello world'"

    list_output = tool._list_jobs()
    assert "Command: echo 'hello world'" in list_output

    # Verify persistence to disk and reloading from fresh service instance
    service._save_store()
    reloaded_service = CronService(tmp_path / "cron" / "jobs.json")
    reloaded_jobs = reloaded_service.list_jobs()
    assert len(reloaded_jobs) == 1
    assert reloaded_jobs[0].payload.kind == "exec_command"
    assert reloaded_jobs[0].payload.command == "echo 'hello world'"


def test_cron_tool_add_skill_script(tmp_path: Path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    tool = CronTool(service)

    with request_context(
        RequestContext(channel="discord", chat_id="456", session_key="discord:456")
    ):
        result = asyncio.run(
            tool.execute(
                action="add",
                name="poll-leads",
                skill_name="poll-lead-sheets",
                script_name="poll.py",
                args=["--sheet", "inbound"],
                every_seconds=300,
            )
        )
    assert "Created job 'poll-leads'" in result
    jobs = service.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].payload.kind == "skill_script"
    assert jobs[0].payload.skill_name == "poll-lead-sheets"
    assert jobs[0].payload.script_name == "poll.py"
    assert jobs[0].payload.args == ["--sheet", "inbound"]

    list_output = tool._list_jobs()
    assert "Skill Script: poll-lead-sheets/poll.py" in list_output

    # Verify persistence to disk and reloading from fresh service instance
    service._save_store()
    reloaded_service = CronService(tmp_path / "cron" / "jobs.json")
    reloaded_jobs = reloaded_service.list_jobs()
    assert len(reloaded_jobs) == 1
    assert reloaded_jobs[0].payload.kind == "skill_script"
    assert reloaded_jobs[0].payload.skill_name == "poll-lead-sheets"
    assert reloaded_jobs[0].payload.script_name == "poll.py"
    assert reloaded_jobs[0].payload.args == ["--sheet", "inbound"]


async def test_run_bound_deterministic_exec_command(tmp_path: Path) -> None:
    recorder = _MockRecorder()
    delivered_messages: list[OutboundMessage] = []

    async def deliver(msg: OutboundMessage, **_kwargs: Any) -> None:
        delivered_messages.append(msg)

    job = CronJob(
        id="test-cmd",
        name="test-cmd",
        schedule=CronSchedule(kind="every", every_ms=60000),
        payload=CronPayload(
            kind="exec_command",
            command="echo 'deterministic task output'",
            session_key="telegram:123",
            origin_channel="telegram",
            origin_chat_id="123",
        ),
    )

    result = await run_bound_deterministic_cron_job(
        job,
        workspace=tmp_path,
        deliver_callback=deliver,
        cron=recorder,
    )

    assert result == "deterministic task output"
    assert len(delivered_messages) == 1
    assert delivered_messages[0].content == "deterministic task output"
    assert delivered_messages[0].channel == "telegram"
    assert delivered_messages[0].chat_id == "123"

    run_record = list(recorder.records.values())[-1]
    assert run_record["status"] == "ok"
    assert run_record["response"] == "deterministic task output"


async def test_run_bound_deterministic_exec_command_failure(tmp_path: Path) -> None:
    recorder = _MockRecorder()
    delivered_messages: list[OutboundMessage] = []

    async def deliver(msg: OutboundMessage, **_kwargs: Any) -> None:
        delivered_messages.append(msg)

    job = CronJob(
        id="test-fail",
        name="test-fail",
        schedule=CronSchedule(kind="every", every_ms=60000),
        payload=CronPayload(
            kind="exec_command",
            command="sh -c 'echo \"syntax error occurred\" >&2; exit 2'",
            session_key="telegram:123",
            origin_channel="telegram",
            origin_chat_id="123",
        ),
    )

    with pytest.raises(RuntimeError, match="syntax error occurred"):
        await run_bound_deterministic_cron_job(
            job,
            workspace=tmp_path,
            deliver_callback=deliver,
            cron=recorder,
        )

    assert len(delivered_messages) == 1
    assert "failed (code 2)" in delivered_messages[0].content
    assert "syntax error occurred" in delivered_messages[0].content

    run_record = list(recorder.records.values())[-1]
    assert run_record["status"] == "error"


async def test_run_bound_deterministic_skill_script(tmp_path: Path) -> None:
    # Create mock skill with script in workspace
    script_dir = tmp_path / "skills" / "demo-skill" / "scripts"
    script_dir.mkdir(parents=True)
    script_file = script_dir / "demo.py"
    script_file.write_text("import sys\nprint('demo output:', ' '.join(sys.argv[1:]))\n")

    recorder = _MockRecorder()
    delivered_messages: list[OutboundMessage] = []

    async def deliver(msg: OutboundMessage, **_kwargs: Any) -> None:
        delivered_messages.append(msg)

    job = CronJob(
        id="test-skill",
        name="test-skill",
        schedule=CronSchedule(kind="every", every_ms=60000),
        payload=CronPayload(
            kind="skill_script",
            skill_name="demo-skill",
            script_name="demo.py",
            args=["param1", "param2"],
            session_key="discord:456",
            origin_channel="discord",
            origin_chat_id="456",
        ),
    )

    result = await run_bound_deterministic_cron_job(
        job,
        workspace=tmp_path,
        deliver_callback=deliver,
        cron=recorder,
    )

    assert result == "demo output: param1 param2"
    assert len(delivered_messages) == 1
    assert delivered_messages[0].content == "demo output: param1 param2"
    assert delivered_messages[0].channel == "discord"
    assert delivered_messages[0].chat_id == "456"

