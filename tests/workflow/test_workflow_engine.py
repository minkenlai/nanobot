"""Tests for state machine workflow execution engine."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.workflow.engine import WorkflowEngine
from nanobot.workflow.schema import (
    ChoiceRule,
    ChoiceState,
    FailState,
    PassState,
    SucceedState,
    TaskState,
    WorkflowDefinition,
)


@pytest.mark.asyncio
async def test_workflow_engine_sequential_and_data_passing() -> None:
    # Action dispatcher simulating steps
    async def mock_dispatcher(action: str, prompt: str | None, params: dict[str, Any], context: dict[str, Any]) -> Any:
        if action == "fetch":
            return {"items": ["task1", "task2"], "count": 2}
        elif action == "summarize":
            return f"Summarized {params.get('count')} items"
        return {}

    wf = WorkflowDefinition(
        id="test_sequential",
        name="Sequential Workflow",
        start_at="step_fetch",
        states={
            "step_fetch": TaskState(
                action="fetch",  # type: ignore[arg-type]
                result_path="$.fetch_result",
                next="step_summarize",
            ),
            "step_summarize": TaskState(
                action="summarize",  # type: ignore[arg-type]
                params={"count": "{{$.fetch_result.count}}"},
                result_path="$.summary",
                end=True,
            ),
        },
    )

    engine = WorkflowEngine(dispatcher=mock_dispatcher)
    record = await engine.run(wf)

    assert record.status == "succeeded"
    assert len(record.steps) == 2
    assert record.steps[0].state_name == "step_fetch"
    assert record.steps[1].state_name == "step_summarize"
    assert record.final_context["fetch_result"]["count"] == 2
    assert record.final_context["summary"] == "Summarized 2 items"


@pytest.mark.asyncio
async def test_workflow_engine_choice_branching() -> None:
    async def mock_dispatcher(action: str, prompt: str | None, params: dict[str, Any], context: dict[str, Any]) -> Any:
        return {"category": params.get("target_category", "billing")}

    wf = WorkflowDefinition(
        id="test_choice",
        name="Choice Workflow",
        start_at="classify",
        states={
            "classify": TaskState(
                action="classify",  # type: ignore[arg-type]
                params={"target_category": "urgent_refund"},
                result_path="$.ticket",
                next="branch_category",
            ),
            "branch_category": ChoiceState(
                choices=[
                    ChoiceRule(variable="$.ticket.category", equals="urgent_refund", next="handle_urgent"),
                    ChoiceRule(variable="$.ticket.category", equals="general", next="handle_general"),
                ],
                default="handle_fallback",
            ),
            "handle_urgent": PassState(
                result={"action_taken": "escalated to manager"},
                result_path="$.resolution",
                next="finish",
            ),
            "handle_general": PassState(
                result={"action_taken": "queued standard"},
                result_path="$.resolution",
                next="finish",
            ),
            "handle_fallback": PassState(
                result={"action_taken": "fallback"},
                result_path="$.resolution",
                next="finish",
            ),
            "finish": SucceedState(),
        },
    )

    engine = WorkflowEngine(dispatcher=mock_dispatcher)
    record = await engine.run(wf)

    assert record.status == "succeeded"
    step_names = [s.state_name for s in record.steps]
    assert step_names == ["classify", "branch_category", "handle_urgent", "finish"]
    assert record.final_context["resolution"]["action_taken"] == "escalated to manager"


@pytest.mark.asyncio
async def test_workflow_engine_loop_and_circuit_breaker() -> None:
    # A workflow that increments a counter in a loop until counter >= 3
    async def mock_dispatcher(action: str, prompt: str | None, params: dict[str, Any], context: dict[str, Any]) -> Any:
        current_val = context.get("counter", 0)
        return current_val + 1

    wf = WorkflowDefinition(
        id="test_loop",
        name="Loop Workflow",
        start_at="init",
        max_steps=20,
        states={
            "init": PassState(
                result=0,
                result_path="$.counter",
                next="increment",
            ),
            "increment": TaskState(
                action="inc",  # type: ignore[arg-type]
                result_path="$.counter",
                next="check_counter",
            ),
            "check_counter": ChoiceState(
                choices=[
                    ChoiceRule(variable="$.counter", numeric_gte=3, next="done"),
                ],
                default="increment",
            ),
            "done": SucceedState(),
        },
    )

    engine = WorkflowEngine(dispatcher=mock_dispatcher)
    record = await engine.run(wf)

    assert record.status == "succeeded"
    assert record.final_context["counter"] == 3
    # init (1) + (increment + check_counter) * 3 + done (1) = 8 steps
    assert len(record.steps) == 8


@pytest.mark.asyncio
async def test_workflow_engine_fail_state() -> None:
    wf = WorkflowDefinition(
        id="test_failure",
        name="Fail Workflow",
        start_at="start",
        states={
            "start": PassState(next="abort"),
            "abort": FailState(error="ValidationFailed", cause="Invalid user credentials"),
        },
    )

    engine = WorkflowEngine()
    record = await engine.run(wf)

    assert record.status == "failed"
    assert "ValidationFailed" in (record.error or "")
    assert "Invalid user credentials" in (record.error or "")
