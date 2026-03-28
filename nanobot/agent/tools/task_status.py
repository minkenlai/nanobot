"""Task status tool for querying spawned subagent progress."""

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


class TaskStatusTool(Tool):
    """Tool to query the status of spawned background subagent tasks."""

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager

    @property
    def name(self) -> str:
        return "task_status"

    @property
    def description(self) -> str:
        return (
            "Query the status of spawned background subagent tasks. "
            "Returns a summary table of all running and recently completed tasks, "
            "including task ID, label, status, duration, and a brief result snippet. "
            "Use when the user asks about task progress, what's running, or what completed."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Optional: filter to a specific task ID. Omit to list all.",
                },
            },
            "required": [],
        }

    async def execute(self, task_id: str | None = None, **kwargs: Any) -> str:
        records = self._manager.get_all_records()

        if not records:
            return "No subagent tasks have been spawned in this session."

        if task_id:
            records = [r for r in records if r.task_id == task_id]
            if not records:
                return f"No task found with ID '{task_id}'."

        lines = ["| ID | Label | Status | Duration | Result |",
                 "|----|-------|--------|----------|--------|"]

        for r in records:
            status_icon = {"running": "⏳", "done": "✅", "error": "❌"}.get(r.status, "?")
            status_str = f"{status_icon} {r.status}"

            if r.finished_at:
                secs = int((r.finished_at - r.started_at).total_seconds())
                duration = f"{secs}s"
            else:
                from datetime import datetime, timezone
                secs = int((datetime.now(timezone.utc) - r.started_at).total_seconds())
                duration = f"{secs}s (running)"

            snippet = r.result_summary or "—"
            # Escape pipes in snippet so table doesn't break
            snippet = snippet.replace("|", "\\|").replace("\n", " ")
            if len(snippet) > 80:
                snippet = snippet[:77] + "…"

            lines.append(f"| {r.task_id} | {r.label} | {status_str} | {duration} | {snippet} |")

        return "\n".join(lines)
