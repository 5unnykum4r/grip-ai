"""Tool abstraction layer: base class, context, and registry.

Every built-in and MCP tool implements the Tool ABC. The ToolRegistry
manages registration, schema generation (OpenAI function-calling format),
and dispatches execution calls to the correct tool.

Tools can return either a plain string or a Pydantic BaseModel instance.
BaseModel returns are automatically serialized to JSON for the LLM.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

try:
    from pydantic import BaseModel as PydanticBaseModel
except ImportError:
    PydanticBaseModel = None  # type: ignore[assignment, misc]

# Tool.execute() can return a plain string or a Pydantic model.
# Pydantic models are auto-serialized to JSON by ToolRegistry.execute().
ToolResult = str | Any  # str | PydanticBaseModel when pydantic is installed


def _serialize_result(result: ToolResult) -> str:
    """Convert a ToolResult to a string for the LLM.

    Strings pass through unchanged. Pydantic BaseModel instances are
    serialized to indented JSON. Dicts/lists are serialized via json.dumps.
    Anything else is converted via str().
    """
    if isinstance(result, str):
        return result
    if PydanticBaseModel is not None and isinstance(result, PydanticBaseModel):
        return result.model_dump_json(indent=2)
    if isinstance(result, (dict, list)):
        return json.dumps(result, indent=2, default=str)
    return str(result)


@dataclass(slots=True)
class ToolContext:
    """Runtime context passed to every tool execution.

    Provides access to workspace path, config values, and references
    needed by tools that interact with the broader system (e.g. spawn,
    message).
    """

    workspace_path: Path
    restrict_to_workspace: bool = False
    shell_timeout: int = 60
    session_key: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    """Abstract base class for all grip tools.

    Subclasses define a unique name, description, JSON Schema for parameters,
    and an async execute method. Tools also declare a category for grouped
    presentation in the system prompt.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier used in tool_call function_name."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """One-line description shown to the LLM."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema (type: object) describing accepted parameters."""
        ...

    @property
    def category(self) -> str:
        """Tool category for grouped system prompt display.

        Override in subclasses. Valid categories: filesystem, shell, web,
        messaging, orchestration, finance. Defaults to 'general'.
        """
        return "general"

    @abstractmethod
    async def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Run the tool with validated parameters and return a result.

        Can return a plain string or a Pydantic BaseModel instance.
        BaseModel instances are automatically serialized to JSON by the
        ToolRegistry before being sent to the LLM.

        Implementations should catch their own exceptions and return
        error messages as strings rather than raising, so the LLM can
        see what went wrong and adapt.
        """
        ...

    def to_definition(self) -> dict[str, Any]:
        """Serialize this tool to the OpenAI function-calling schema format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Central registry for tool instances.

    Handles registration, lookup, definition export, and execution dispatch.
    Thread-safe for reads; registration is expected to happen once at startup.
    """

    __slots__ = ("_tools", "_category_cache", "mcp_manager")

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._category_cache: dict[str, list[Tool]] | None = None
        self.mcp_manager: Any = None

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            logger.warning("Overwriting existing tool registration: {}", tool.name)
        self._tools[tool.name] = tool
        self._category_cache = None
        logger.debug("Registered tool: {}", tool.name)

    def register_many(self, tools: list[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def unregister(self, name: str) -> bool:
        if name in self._tools:
            del self._tools[name]
            self._category_cache = None
            logger.debug("Unregistered tool: {}", name)
            return True
        return False

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def get_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI function-calling definitions for all registered tools."""
        return [tool.to_definition() for tool in self._tools.values()]

    def get_tools_by_category(self) -> dict[str, list[Tool]]:
        """Return registered tools grouped by category for system prompt generation.

        Result is cached and invalidated on register/unregister.
        """
        if self._category_cache is not None:
            return self._category_cache
        groups: dict[str, list[Tool]] = {}
        for tool in self._tools.values():
            groups.setdefault(tool.category, []).append(tool)
        self._category_cache = groups
        return groups

    async def execute(self, name: str, params: dict[str, Any], ctx: ToolContext) -> str:
        """Look up a tool by name and execute it.

        Returns error string (not exception) if tool is not found or fails.
        Pydantic BaseModel results are serialized to indented JSON automatically.
        """
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: Unknown tool '{name}'. Available: {', '.join(self._tools.keys())}"

        try:
            result = await tool.execute(params, ctx)
            return _serialize_result(result)
        except Exception as exc:
            logger.error("Unhandled error in tool {}: {}", name, exc, exc_info=True)
            return f"Error executing {name}: {type(exc).__name__}: {exc}"

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
