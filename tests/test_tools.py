"""Tests for the tool system: registry, context, and built-in tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from grip.tools.base import Tool, ToolContext, ToolRegistry


class DummyTool(Tool):
    """Minimal tool implementation for testing."""

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "A dummy tool for testing."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]}

    async def execute(self, params: dict[str, Any], ctx: ToolContext) -> str:
        return f"echo: {params.get('msg', '')}"


def test_registry_register_and_get():
    """Register a tool and retrieve it by name."""
    registry = ToolRegistry()
    tool = DummyTool()
    registry.register(tool)

    assert "dummy" in registry
    assert registry.get("dummy") is tool
    assert len(registry) == 1


def test_registry_names():
    registry = ToolRegistry()
    registry.register(DummyTool())
    assert "dummy" in registry.names()


def test_registry_unregister():
    registry = ToolRegistry()
    registry.register(DummyTool())
    assert registry.unregister("dummy") is True
    assert registry.unregister("dummy") is False
    assert len(registry) == 0


def test_registry_get_definitions():
    registry = ToolRegistry()
    registry.register(DummyTool())
    defs = registry.get_definitions()
    assert len(defs) == 1
    assert defs[0]["function"]["name"] == "dummy"


@pytest.mark.asyncio
async def test_registry_execute(tmp_path: Path):
    registry = ToolRegistry()
    registry.register(DummyTool())
    ctx = ToolContext(workspace_path=tmp_path)
    result = await registry.execute("dummy", {"msg": "hello"}, ctx)
    assert result == "echo: hello"


@pytest.mark.asyncio
async def test_registry_execute_unknown(tmp_path: Path):
    registry = ToolRegistry()
    ctx = ToolContext(workspace_path=tmp_path)
    result = await registry.execute("nonexistent", {}, ctx)
    assert "Error: Unknown tool" in result


def test_tool_context_defaults():
    ctx = ToolContext(workspace_path=Path("/tmp"))
    assert ctx.restrict_to_workspace is False
    assert ctx.shell_timeout == 60
    assert ctx.session_key == ""


def test_create_default_registry():
    """create_default_registry should return a registry with built-in tools."""
    from grip.tools import create_default_registry
    registry = create_default_registry()
    assert len(registry) >= 5
    assert "exec" in registry
    assert "read_file" in registry
    assert "write_file" in registry
    assert "spawn" in registry
    assert "send_message" in registry
