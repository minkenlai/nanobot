"""Asynchronous state machine workflow execution engine."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable

from loguru import logger

from nanobot.workflow.evaluator import (
    evaluate_choice,
    interpolate_obj,
    interpolate_template,
    set_path,
)
from nanobot.workflow.schema import (
    BaseTaskState,
    ChoiceState,
    ExecState,
    LLMState,
    PassState,
    StepExecutionRecord,
    SucceedState,
    TaskState,
    ToolState,
    WorkflowDefinition,
    WorkflowRunRecord,
)

ActionDispatcher = Callable[[str, str | None, dict[str, Any], dict[str, Any]], Awaitable[Any]]


class WorkflowExecutionError(Exception):
    """Raised when a workflow execution encounters a terminal failure."""


class WorkflowEngine:
    """State machine execution engine for WorkflowDefinition instances."""

    def __init__(
        self,
        dispatcher: ActionDispatcher | None = None,
    ) -> None:
        self.dispatcher = dispatcher

    async def run(
        self,
        workflow: WorkflowDefinition,
        initial_context: dict[str, Any] | None = None,
        *,
        run_id: str | None = None,
    ) -> WorkflowRunRecord:
        """Execute a workflow definition to completion."""
        actual_run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
        start_time = time.monotonic()
        now_iso = datetime.now().astimezone().isoformat()

        context: dict[str, Any] = dict(initial_context or {})
        step_records: list[StepExecutionRecord] = []
        current_state_name: str | None = workflow.start_at
        steps_executed = 0
        error_msg: str | None = None
        status: str = "succeeded"

        logger.info("Starting workflow '{}' ({}) run_id={}", workflow.name, workflow.id, actual_run_id)

        try:
            async with asyncio.timeout(workflow.timeout_seconds):
                while current_state_name is not None:
                    if steps_executed >= workflow.max_steps:
                        raise WorkflowExecutionError(
                            f"Workflow exceeded maximum allowed steps ({workflow.max_steps})"
                        )

                    if current_state_name not in workflow.states:
                        raise WorkflowExecutionError(
                            f"State '{current_state_name}' not defined in workflow '{workflow.id}'"
                        )

                    state = workflow.states[current_state_name]
                    step_start = time.monotonic()
                    step_start_iso = datetime.now().astimezone().isoformat()
                    next_state_name: str | None = None
                    step_output: Any = None
                    step_error: str | None = None
                    step_status: str = "succeeded"

                    try:
                        if isinstance(state, BaseTaskState):
                            step_output, next_state_name = await self._execute_task(
                                state, context
                            )
                        elif isinstance(state, ChoiceState):
                            next_state_name = self._execute_choice(state, context)
                        elif isinstance(state, PassState):
                            step_output, next_state_name = self._execute_pass(
                                state, context
                            )
                        elif isinstance(state, SucceedState):
                            next_state_name = None
                        else:
                            step_status = "failed"
                            step_error = f"{state.error or 'FailState'}: {state.cause or 'Workflow reached failure state'}"
                            raise WorkflowExecutionError(step_error)

                    except Exception as exc:
                        step_status = "failed"
                        step_error = str(exc)
                        step_duration = (time.monotonic() - step_start) * 1000
                        step_records.append(
                            StepExecutionRecord(
                                state_name=current_state_name,
                                state_type=state.type,
                                started_at=step_start_iso,
                                completed_at=datetime.now().astimezone().isoformat(),
                                duration_ms=round(step_duration, 2),
                                status="failed",
                                next_state=None,
                                output=None,
                                error=step_error,
                            )
                        )
                        raise

                    step_duration = (time.monotonic() - step_start) * 1000
                    step_records.append(
                        StepExecutionRecord(
                            state_name=current_state_name,
                            state_type=state.type,
                            started_at=step_start_iso,
                            completed_at=datetime.now().astimezone().isoformat(),
                            duration_ms=round(step_duration, 2),
                            status=step_status,  # type: ignore[arg-type]
                            next_state=next_state_name,
                            output=step_output,
                            error=None,
                        )
                    )

                    steps_executed += 1
                    current_state_name = next_state_name

        except TimeoutError:
            status = "timeout"
            error_msg = f"Workflow execution timed out after {workflow.timeout_seconds}s"
            logger.error("Workflow '{}' timed out: {}", workflow.id, error_msg)
        except WorkflowExecutionError as exc:
            status = "failed"
            error_msg = str(exc)
            logger.error("Workflow '{}' failed: {}", workflow.id, error_msg)
        except Exception as exc:
            status = "failed"
            error_msg = f"Unexpected error during workflow execution: {exc}"
            logger.exception("Workflow '{}' encountered unhandled error", workflow.id)

        total_duration = (time.monotonic() - start_time) * 1000
        completed_at_iso = datetime.now().astimezone().isoformat()

        logger.info(
            "Workflow '{}' finished with status={} in {:.2f}ms ({} steps)",
            workflow.id,
            status,
            total_duration,
            len(step_records),
        )

        return WorkflowRunRecord(
            run_id=actual_run_id,
            workflow_id=workflow.id,
            status=status,  # type: ignore[arg-type]
            started_at=now_iso,
            completed_at=completed_at_iso,
            total_duration_ms=round(total_duration, 2),
            initial_context=dict(initial_context or {}),
            final_context=context,
            steps=step_records,
            error=error_msg,
        )

    async def _execute_task(
        self, state: BaseTaskState, context: dict[str, Any]
    ) -> tuple[Any, str | None]:
        """Execute a BaseTaskState using the registered ActionDispatcher."""
        prompt: str | None = None
        params: dict[str, Any] = {}
        action = "prompt"

        if isinstance(state, LLMState):
            action = "prompt"
            prompt = interpolate_template(state.prompt, context)
            params = interpolate_obj(state.params, context)
        elif isinstance(state, ExecState):
            action = "exec"
            params = interpolate_obj(state.params, context)
            params["command"] = interpolate_template(state.command, context)
        elif isinstance(state, ToolState):
            action = "tool"
            params = interpolate_obj(state.params, context)
            params["tool"] = interpolate_template(state.tool, context)
            params["args"] = interpolate_obj(state.args, context)
        elif isinstance(state, TaskState):
            action = state.action
            if state.resource:
                res = state.resource.strip()
                if res.startswith("nanobot:exec"):
                    action = "exec"
                elif res.startswith("nanobot:llm") or res.startswith("nanobot:prompt"):
                    action = "prompt"
                elif res.startswith("nanobot:tool:"):
                    action = "tool"
                    params["tool"] = res.split(":", 2)[2]
                elif res.startswith("nanobot:tool"):
                    action = "tool"

            if state.prompt:
                prompt = interpolate_template(state.prompt, context)
            if state.command:
                params["command"] = interpolate_template(state.command, context)
            if state.tool:
                params["tool"] = interpolate_template(state.tool, context)
            if state.args:
                params["args"] = interpolate_obj(state.args, context)

            extra_params = interpolate_obj(state.params, context)
            params = {**extra_params, **params}

        if self.dispatcher is not None:
            output = await self.dispatcher(action, prompt, params, context)
        else:
            output = {"status": "ok", "action": action, "prompt": prompt}

        if state.result_path:
            set_path(context, state.result_path, output)

        next_state = None if state.end else state.next
        return output, next_state

    def _execute_choice(self, state: ChoiceState, context: dict[str, Any]) -> str:
        """Evaluate ChoiceState rules and determine the next transition."""
        for rule in state.choices:
            if evaluate_choice(rule, context):
                return rule.next
        if state.default:
            return state.default
        raise WorkflowExecutionError("No ChoiceRule matched in state and no default transition specified")

    def _execute_pass(
        self, state: PassState, context: dict[str, Any]
    ) -> tuple[Any, str | None]:
        """Execute a PassState, injecting or transforming state."""
        result = interpolate_obj(state.result, context)
        if state.result_path and result is not None:
            set_path(context, state.result_path, result)
        next_state = None if state.end else state.next
        return result, next_state
