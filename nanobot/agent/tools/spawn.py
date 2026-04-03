"""Spawn tool for creating background subagents."""

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import Address

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


class SpawnTool(Tool):
    """Tool to spawn a subagent for background task execution."""

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
        self._origin = Address(channel="cli", segments=("direct",))
        self._session_key = "cli:direct"

    def set_context(self, address: Address, session_key: str) -> None:
        """Set the origin context for subagent announcements."""
        self._origin = address
        self._session_key = session_key

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "The subagent will complete the task and report back when done. "
            "Subagents automatically inherit the core persona (SOUL.md), user preferences (USER.md), "
            "and operational guardrails (SUBAGENT.md), so you don't need to repeat these in the task. "
            "For deliverables or existing projects, inspect the workspace first "
            "and use a dedicated subdirectory when helpful."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task for the subagent to complete",
                },
                "label": {
                    "type": "string",
                    "description": "Optional short label for the task (for display)",
                },
                "agent": {
                    "type": "string",
                    "description": "Optional agent profile to use (e.g., 'deep', 'fast'). Overrides the default agent.",
                },
            },
            "required": ["task"],
        }

    async def execute(
        self, task: str, label: str | None = None, agent: str | None = None, **kwargs: Any
    ) -> str:
        """Spawn a subagent to execute the given task."""
        return await self._manager.spawn(
            task=task,
            label=label,
            agent=agent,
            origin=self._origin,
            session_key=self._session_key,
        )
