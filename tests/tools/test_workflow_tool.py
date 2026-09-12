"""Tests for ManageWorkflowTool actions."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.tools.workflow import ManageWorkflowTool
from nanobot.workflow.service import WorkflowService


@pytest.mark.asyncio
async def test_manage_workflow_tool_lifecycle(tmp_path: Path) -> None:
    service = WorkflowService(workflows_dir=tmp_path / "workflows")
    tool = ManageWorkflowTool(service=service)

    # 1. List empty
    res = await tool.execute(action="list")
    assert "No workflows configured" in str(res)

    # 2. Save / create workflow
    wf_dict = {
        "id": "triage",
        "name": "Triage Flow",
        "start_at": "init",
        "states": {
            "init": {
                "type": "pass",
                "result": {"status": "ok"},
                "result_path": "$.result",
                "next": "done",
            },
            "done": {
                "type": "succeed",
            },
        },
    }
    res_save = await tool.execute(action="save", workflow_id="triage", definition=wf_dict)
    assert "successfully saved" in str(res_save)

    # 3. List
    res_list = await tool.execute(action="list")
    assert "triage: Triage Flow" in str(res_list)

    # 4. Get
    res_get = await tool.execute(action="get", workflow_id="triage")
    assert '"id": "triage"' in str(res_get)

    # 5. Run
    res_run = await tool.execute(action="run", workflow_id="triage")
    assert "completed with status: succeeded" in str(res_run)
    assert '"status": "ok"' in str(res_run)

    # 6. Runs
    res_runs = await tool.execute(action="runs", workflow_id="triage")
    assert "Recent runs" in str(res_runs)

    # 7. Delete
    res_del = await tool.execute(action="delete", workflow_id="triage")
    assert "successfully deleted" in str(res_del)
    assert "No workflows configured" in str(await tool.execute(action="list"))


def test_manage_workflow_tool_enabled_config() -> None:
    from unittest.mock import MagicMock

    from nanobot.agent.tools.context import ToolContext
    from nanobot.config.schema import Config, WorkflowsConfig

    # 1. Default config (enabled=True)
    cfg_default = Config()
    ctx_default = MagicMock(spec=ToolContext)
    ctx_default.config = cfg_default
    assert ManageWorkflowTool.enabled(ctx_default) is True

    # 2. Disabled config (enabled=False)
    cfg_disabled = Config(workflows=WorkflowsConfig(enabled=False))
    ctx_disabled = MagicMock(spec=ToolContext)
    ctx_disabled.config = cfg_disabled
    assert ManageWorkflowTool.enabled(ctx_disabled) is False


@pytest.mark.asyncio
async def test_manage_workflow_tool_validate(tmp_path: Path) -> None:
    service = WorkflowService(workflows_dir=tmp_path / "workflows")
    tool = ManageWorkflowTool(service=service)

    # 1. Validate a valid definition
    valid_wf = {
        "id": "valid_flow",
        "name": "Valid Flow",
        "start_at": "step1",
        "states": {
            "step1": {
                "type": "exec",
                "command": "echo hello",
                "result_path": "$.out",
                "next": "step2",
            },
            "step2": {
                "type": "llm",
                "prompt": "Evaluate {{$.out.stdout}}",
                "end": True,
            },
        },
    }
    res_valid = await tool.execute(action="validate", definition=valid_wf)
    assert "Workflow 'valid_flow' is valid" in str(res_valid)
    assert "step1, step2" in str(res_valid)

    # 2a. Validate schema failure (missing command on exec state)
    invalid_schema_wf = {
        "id": "broken_flow",
        "name": "Broken Flow",
        "start_at": "step1",
        "states": {
            "step1": {
                "type": "exec",
                "next": "step2",
            },
        },
    }
    res_schema_invalid = await tool.execute(action="validate", definition=invalid_schema_wf)
    assert "validation failed with 1 error(s)" in str(res_schema_invalid)
    assert "Schema validation failed" in str(res_schema_invalid)

    # 2b. Validate graph integrity failure (dangling next transition)
    invalid_graph_wf = {
        "id": "broken_graph",
        "name": "Broken Graph",
        "start_at": "step1",
        "states": {
            "step1": {
                "type": "exec",
                "command": "echo 123",
                "next": "nonexistent_step",
            },
        },
    }
    res_graph_invalid = await tool.execute(action="validate", definition=invalid_graph_wf)
    assert "validation failed with 1 error(s)" in str(res_graph_invalid)
    assert "transitions to unknown state 'nonexistent_step'" in str(res_graph_invalid)

    # 3. Validate existing saved workflow by workflow_id
    await tool.execute(action="save", workflow_id="valid_flow", definition=valid_wf)
    res_saved_val = await tool.execute(action="validate", workflow_id="valid_flow")
    assert "Workflow 'valid_flow' is valid" in str(res_saved_val)

