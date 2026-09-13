"""Tests for WorkflowService persistence and run logging."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.workflow.schema import (
    ExecState,
    LLMState,
    PassState,
    SucceedState,
    TaskState,
    ToolState,
    WorkflowDefinition,
)
from nanobot.workflow.service import WorkflowService


@pytest.mark.asyncio
async def test_workflow_service_crud_and_runs(tmp_path: Path) -> None:
    service = WorkflowService(workflows_dir=tmp_path / "workflows")

    assert service.list_workflows() == []
    assert service.get_workflow("nonexistent") is None

    wf = WorkflowDefinition(
        id="sample_flow",
        name="Sample Flow",
        description="A test workflow",
        start_at="step1",
        states={
            "step1": PassState(result={"key": "val"}, result_path="$.data", next="step2"),
            "step2": SucceedState(),
        },
    )

    # Save
    service.save_workflow(wf)
    listed = service.list_workflows()
    assert len(listed) == 1
    assert listed[0]["id"] == "sample_flow"

    # Get
    loaded = service.get_workflow("sample_flow")
    assert loaded is not None
    assert loaded.name == "Sample Flow"
    assert len(loaded.states) == 2

    # Execute run
    run_record = await service.run_workflow("sample_flow")
    assert run_record.status == "succeeded"
    assert run_record.workflow_id == "sample_flow"
    assert run_record.final_context["data"]["key"] == "val"

    # Inspect runs
    stored_run = service.get_run(run_record.run_id)
    assert stored_run is not None
    assert stored_run.run_id == run_record.run_id
    assert stored_run.status == "succeeded"

    all_runs = service.list_runs()
    assert len(all_runs) == 1
    assert all_runs[0].run_id == run_record.run_id

    # Delete
    assert service.delete_workflow("sample_flow") is True
    assert service.get_workflow("sample_flow") is None


def test_workflow_service_path_sanitization_and_fallbacks(tmp_path: Path) -> None:
    service = WorkflowService(workflows_dir=tmp_path / "workflows")

    # Workflow ID sanitization and fallbacks
    assert service._file_for_workflow("safe-wf_1").name == "safe-wf_1.json"
    assert service._file_for_workflow("../../../etc/passwd").name == "etcpasswd.json"
    assert service._file_for_workflow("@#$%!").name == "unnamed.json"
    assert service._file_for_workflow("").name == "unnamed.json"

    # Run ID sanitization and fallbacks
    assert service._file_for_run("run_123").name == "run_123.json"
    assert service._file_for_run("../secret").name == "secret.json"
    assert service._file_for_run("???").name == "unknown_run.json"
    assert service._file_for_run("").name == "unknown_run.json"

    assert service.list_workflows() == []


@pytest.mark.asyncio
async def test_workflow_service_dispatcher_actions(tmp_path: Path) -> None:
    service = WorkflowService(workflows_dir=tmp_path / "workflows")

    # 1. First-class ExecState
    wf_exec = WorkflowDefinition(
        id="exec_flow",
        name="Exec Flow",
        start_at="run_cmd",
        states={
            "run_cmd": ExecState(
                command="echo '{\"new_activity\": true, \"count\": 3}'",
                result_path="$.cmd_out",
                end=True,
            ),
        },
    )
    service.save_workflow(wf_exec)
    run_res = await service.run_workflow("exec_flow")
    assert run_res.status == "succeeded"
    assert run_res.final_context["cmd_out"]["exit_code"] == 0
    assert run_res.final_context["cmd_out"]["new_activity"] is True
    assert run_res.final_context["cmd_out"]["count"] == 3
    assert run_res.final_context["cmd_out"]["json"]["new_activity"] is True

    # 2. Standard ASL TaskState with resource="nanobot:exec"
    wf_asl_exec = WorkflowDefinition(
        id="asl_exec_flow",
        name="ASL Exec Flow",
        start_at="step1",
        states={
            "step1": TaskState(
                resource="nanobot:exec",
                command="echo 'asl resource test'",
                result_path="$.asl_out",
                end=True,
            ),
        },
    )
    service.save_workflow(wf_asl_exec)
    run_asl = await service.run_workflow("asl_exec_flow")
    assert run_asl.status == "succeeded"
    assert run_asl.final_context["asl_out"]["stdout"] == "asl resource test"

    # 3. LLMState failure when live agent is not available
    wf_llm = WorkflowDefinition(
        id="llm_flow",
        name="LLM Flow",
        start_at="llm_step",
        states={
            "llm_step": LLMState(
                prompt="Summarize today's logs",
                result_path="$.summary",
                end=True,
            ),
        },
    )
    service.save_workflow(wf_llm)
    run_llm = await service.run_workflow("llm_flow")
    assert run_llm.status == "failed"
    assert run_llm.error is not None
    assert "Agent loop is not available" in run_llm.error
    assert len(run_llm.steps) == 1
    assert run_llm.steps[0].status == "failed"
    assert "Agent loop is not available" in (run_llm.steps[0].error or "")

    # 4. LLMState with mocked agent loop
    mock_loop = MagicMock()
    mock_outbound = MagicMock()
    mock_outbound.content = "Summary generated by AI"
    mock_loop.process_direct = AsyncMock(return_value=mock_outbound)
    service.agent_loop = mock_loop

    run_llm_live = await service.run_workflow("llm_flow")
    assert run_llm_live.status == "succeeded"
    assert run_llm_live.final_context["summary"] == "Summary generated by AI"
    mock_loop.process_direct.assert_called_once()

    # 5. First-class ToolState with mocked tool registry
    mock_tool = MagicMock()
    mock_tool.execute = AsyncMock(return_value="tool execution result")
    mock_loop.tools = {"test_tool": mock_tool}

    wf_tool = WorkflowDefinition(
        id="tool_flow",
        name="Tool Flow",
        start_at="tool_step",
        states={
            "tool_step": ToolState(
                tool="test_tool",
                args={"arg1": "val1"},
                result_path="$.tool_out",
                end=True,
            ),
        },
    )
    service.save_workflow(wf_tool)
    run_tool = await service.run_workflow("tool_flow")
    assert run_tool.status == "succeeded"
    assert run_tool.final_context["tool_out"] == "tool execution result"
    mock_tool.execute.assert_called_once_with(arg1="val1")

    # 6. Deterministic error for unsupported action
    wf_unsupported = WorkflowDefinition(
        id="bad_action",
        name="Bad Action",
        start_at="bad_step",
        states={
            "bad_step": TaskState(
                action="invalid_action_name",
                result_path="$.bad_out",
                end=True,
            ),
        },
    )
    service.save_workflow(wf_unsupported)
    run_bad = await service.run_workflow("bad_action")
    assert run_bad.status == "failed"
    assert run_bad.error is not None
    assert "Unsupported action 'invalid_action_name'" in run_bad.error

    # 7. Deterministic error for missing required parameter
    wf_missing_param = WorkflowDefinition(
        id="missing_cmd",
        name="Missing Command",
        start_at="step1",
        states={
            "step1": TaskState(
                action="exec",
                result_path="$.err_out",
                end=True,
            ),
        },
    )
    service.save_workflow(wf_missing_param)
    run_missing = await service.run_workflow("missing_cmd")
    assert run_missing.status == "failed"
    assert run_missing.error is not None
    assert "Missing required parameter 'command'" in run_missing.error

