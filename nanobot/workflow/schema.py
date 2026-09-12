"""Pydantic schemas for declarative state machine workflows."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class TriggerConfig(BaseModel):
    """Trigger configuration for automated workflow execution."""

    model_config = ConfigDict(extra="ignore")

    cron: str | None = Field(default=None, description="Standard cron expression (e.g. '0 9 * * 1-5' or '*/15 * * * *')")
    tz: str | None = Field(default=None, description="Timezone name (e.g. 'UTC', 'America/Los_Angeles')")
    enabled: bool = Field(default=True, description="Whether automated triggering is enabled")


class ChoiceRule(BaseModel):
    """Comparison condition for conditional branching in Choice states."""

    model_config = ConfigDict(extra="ignore")

    variable: str = Field(description="JSONPath or dot-notation path to state variable (e.g. '$.analysis.urgency')")
    equals: Any | None = Field(default=None, description="Exact equality comparison")
    not_equals: Any | None = Field(default=None, description="Inequality comparison")
    numeric_gt: float | None = Field(default=None, description="Numeric greater than (>)")
    numeric_gte: float | None = Field(default=None, description="Numeric greater than or equal (>=)")
    numeric_lt: float | None = Field(default=None, description="Numeric less than (<)")
    numeric_lte: float | None = Field(default=None, description="Numeric less than or equal (<=)")
    boolean_equals: bool | None = Field(default=None, description="Boolean equality check")
    is_null: bool | None = Field(default=None, description="Check if variable is null / missing")
    contains: str | None = Field(default=None, description="Substring or collection membership check")
    starts_with: str | None = Field(default=None, description="String prefix check")
    ends_with: str | None = Field(default=None, description="String suffix check")
    next: str = Field(description="Name of next state to transition to if this rule matches")


class BaseTaskState(BaseModel):
    """Base model for executable workflow states."""

    model_config = ConfigDict(extra="ignore")

    input_path: str | None = Field(default=None, description="JSONPath to select subset of context as input")
    result_path: str | None = Field(
        default=None,
        description="JSONPath/dot path to store output into workflow context (e.g. '$.inbox', 'analysis')",
    )
    output_path: str | None = Field(default=None, description="JSONPath to select subset of context to pass forward")
    next: str | None = Field(default=None, description="Name of next state to transition to")
    end: bool = Field(default=False, description="Whether this state terminates the workflow")
    comment: str | None = Field(default=None, description="Optional description or note")
    timeout_seconds: float | None = Field(default=None, description="Execution timeout for this state in seconds")


class TaskState(BaseTaskState):
    """Standard ASL Task state executing an action, tool, shell command, or message dispatch."""

    type: Literal["task"] = "task"
    resource: str | None = Field(
        default=None,
        description="Optional ASL Resource URI (e.g. 'nanobot:exec', 'nanobot:tool:read_file', 'nanobot:llm')",
    )
    action: str = Field(
        default="prompt",
        description="Deterministic action type: 'prompt' (LLM turn), 'exec' (shell command), 'tool' (agent tool), 'send_message', or 'pass'",
    )
    prompt: str | None = Field(default=None, description="Prompt template for 'prompt' action")
    command: str | None = Field(default=None, description="Shell command string for 'exec' action")
    tool: str | None = Field(default=None, description="Tool name for 'tool' action")
    args: dict[str, Any] = Field(default_factory=dict, description="Arguments dictionary for 'tool' action")
    params: dict[str, Any] = Field(default_factory=dict, description="Additional parameters forwarded to action")


class LLMState(BaseTaskState):
    """First-class state representing an LLM prompt turn."""

    type: Literal["llm"] = "llm"
    prompt: str = Field(description="Prompt template submitted to the LLM agent")
    params: dict[str, Any] = Field(default_factory=dict, description="Optional extra parameters (e.g. session_key)")


class ExecState(BaseTaskState):
    """First-class state executing a shell command."""

    type: Literal["exec"] = "exec"
    command: str = Field(description="Shell command to execute")
    params: dict[str, Any] = Field(default_factory=dict, description="Optional parameters (e.g. timeout)")


class ToolState(BaseTaskState):
    """First-class state executing an agent tool."""

    type: Literal["tool"] = "tool"
    tool: str = Field(description="Name of the agent tool to invoke (e.g. 'read_file', 'web_search')")
    args: dict[str, Any] = Field(default_factory=dict, description="Arguments to pass to the tool")
    params: dict[str, Any] = Field(default_factory=dict, description="Optional parameters")



class ChoiceState(BaseModel):
    """Choice state selecting a transition based on boolean condition rules."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["choice"] = "choice"
    choices: list[ChoiceRule] = Field(default_factory=list, description="Ordered list of comparison rules")
    default: str | None = Field(default=None, description="Fallback state name if no choice rule matches")
    comment: str | None = Field(default=None, description="Optional description or note")


class PassState(BaseModel):
    """Pass state injecting static data or transforming state without external calls."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["pass"] = "pass"
    result: Any = Field(default=None, description="Static data to inject")
    result_path: str | None = Field(default=None, description="Target path in workflow context")
    next: str | None = Field(default=None, description="Name of next state to transition to")
    end: bool = Field(default=False, description="Whether this state terminates the workflow")
    comment: str | None = Field(default=None, description="Optional description or note")


class FailState(BaseModel):
    """Terminal state representing workflow failure."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["fail"] = "fail"
    error: str | None = Field(default=None, description="Error code or title")
    cause: str | None = Field(default=None, description="Human-readable cause of failure")


class SucceedState(BaseModel):
    """Terminal state representing successful workflow completion."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["succeed"] = "succeed"
    comment: str | None = Field(default=None, description="Optional description or note")


WorkflowState = Annotated[
    Union[TaskState, LLMState, ExecState, ToolState, ChoiceState, PassState, FailState, SucceedState],
    Field(discriminator="type"),
]


class WorkflowDefinition(BaseModel):
    """Declarative state machine workflow definition."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Unique workflow identifier (e.g. 'morning_triage')")
    name: str = Field(description="Human-readable workflow title")
    description: str = Field(default="", description="Workflow summary or instructions")
    enabled: bool = Field(default=True, description="Whether the workflow is active")
    trigger: TriggerConfig | None = Field(default=None, description="Automated schedule trigger")
    start_at: str = Field(description="Name of the initial state to execute")
    states: dict[str, WorkflowState] = Field(description="Mapping of state names to state configurations")
    max_steps: int = Field(default=100, description="Circuit breaker for maximum step transitions to prevent infinite loops")
    timeout_seconds: float = Field(default=300.0, description="Maximum total workflow execution timeout in seconds")


class StepExecutionRecord(BaseModel):
    """Execution telemetry record for a single step execution within a run."""

    state_name: str
    state_type: str
    started_at: str
    completed_at: str
    duration_ms: float
    status: Literal["succeeded", "failed", "skipped"]
    next_state: str | None = None
    output: Any | None = None
    error: str | None = None


class WorkflowRunRecord(BaseModel):
    """Authoritative execution record for a workflow instance."""

    run_id: str
    workflow_id: str
    status: Literal["running", "succeeded", "failed", "timeout", "cancelled"]
    started_at: str
    completed_at: str | None = None
    total_duration_ms: float = 0.0
    initial_context: dict[str, Any] = Field(default_factory=dict)
    final_context: dict[str, Any] = Field(default_factory=dict)
    steps: list[StepExecutionRecord] = Field(default_factory=list)
    error: str | None = None
