"""Task tracking tools: TodoWrite and TodoRead for managing agent task lists.

Persists todos to workspace/tasks.json. Designed to mirror the Claude Agent
SDK TodoWrite/TodoRead API so agents can plan and track multi-step work
without losing state across tool iterations.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from grip.tools.base import Tool, ToolContext

VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
VALID_PRIORITIES = {"low", "medium", "high"}

STATUS_ICONS = {
    "pending": "○",
    "in_progress": "◑",
    "completed": "●",
    "cancelled": "✗",
}


class TodoWriteTool(Tool):
    """Replace the full task list with a new set of todos.

    Each call replaces the entire list — include all todos, not just new ones.
    Persists to workspace/tasks.json so todos survive across iterations.
    """

    @property
    def category(self) -> str:
        return "task_management"

    @property
    def name(self) -> str:
        return "todo_write"

    @property
    def description(self) -> str:
        return (
            "Create or update the task list. Replaces ALL existing todos with the provided list. "
            "Use for tasks with 3+ steps. Set status to 'in_progress' before starting a task, "
            "'completed' when done. Always include the full list on every call."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "Complete replacement list of all todos.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Short unique identifier (e.g. '1', 'task-2').",
                            },
                            "content": {
                                "type": "string",
                                "description": "Description of what needs to be done.",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed", "cancelled"],
                                "description": "Current status of the task.",
                            },
                            "priority": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                                "description": "Priority level (optional).",
                            },
                        },
                        "required": ["id", "content", "status"],
                    },
                }
            },
            "required": ["todos"],
        }

    async def execute(self, params: dict[str, Any], ctx: ToolContext) -> str:
        todos = params.get("todos", [])

        for t in todos:
            if t.get("status") not in VALID_STATUSES:
                return (
                    f"Error: Invalid status '{t.get('status')}' for todo '{t.get('id')}'. "
                    f"Must be one of: {', '.join(sorted(VALID_STATUSES))}."
                )
            if "priority" in t and t["priority"] not in VALID_PRIORITIES:
                return (
                    f"Error: Invalid priority '{t.get('priority')}' for todo '{t.get('id')}'. "
                    f"Must be one of: {', '.join(sorted(VALID_PRIORITIES))}."
                )

        tasks_path = ctx.workspace_path / "tasks.json"
        try:
            tasks_path.write_text(json.dumps(todos, indent=2))
        except OSError as exc:
            return f"Error: Could not save tasks: {exc}"

        completed = sum(1 for t in todos if t["status"] == "completed")
        in_progress = sum(1 for t in todos if t["status"] == "in_progress")
        pending = sum(1 for t in todos if t["status"] == "pending")

        logger.debug(
            "Task list saved: {} total ({} pending, {} in_progress, {} completed)",
            len(todos),
            pending,
            in_progress,
            completed,
        )
        return (
            f"Task list updated: {len(todos)} total "
            f"({pending} pending, {in_progress} in_progress, {completed} completed)."
        )


class TodoReadTool(Tool):
    """Read the current task list from workspace/tasks.json."""

    @property
    def category(self) -> str:
        return "task_management"

    @property
    def name(self) -> str:
        return "todo_read"

    @property
    def description(self) -> str:
        return (
            "Read the current task list. Returns all todos with their statuses and priorities. "
            "Use this to check progress before continuing a multi-step task."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, params: dict[str, Any], ctx: ToolContext) -> str:
        tasks_path = ctx.workspace_path / "tasks.json"
        if not tasks_path.exists():
            return "No task list found. Use todo_write to create one."

        try:
            todos = json.loads(tasks_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            return f"Error reading task list: {exc}"

        if not todos:
            return "Task list is empty."

        lines = [f"Task list ({len(todos)} total):\n"]
        for t in todos:
            icon = STATUS_ICONS.get(t.get("status", "pending"), "○")
            priority = t.get("priority", "")
            priority_label = f" [{priority}]" if priority else ""
            lines.append(
                f"  {icon} [{t['id']}]{priority_label} {t['content']} — {t.get('status', 'pending')}"
            )

        completed = sum(1 for t in todos if t.get("status") == "completed")
        in_progress = sum(1 for t in todos if t.get("status") == "in_progress")
        pending = sum(1 for t in todos if t.get("status") == "pending")
        lines.append(
            f"\nSummary: {pending} pending, {in_progress} in_progress, {completed} completed."
        )
        return "\n".join(lines)


def create_todo_tools() -> list[Tool]:
    return [TodoWriteTool(), TodoReadTool()]
