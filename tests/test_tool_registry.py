"""Tests for tool registration in the default ToolRegistry."""

from __future__ import annotations

from grip.tools import create_default_registry


class TestToolRegistry:
    def test_all_new_tools_registered(self):
        """Verify all 6 new tools are present in the default registry."""
        registry = create_default_registry()
        expected_new_tools = {
            "web_research",
            "code_analysis",
            "data_transform",
            "document_gen",
            "email_compose",
            "scheduler",
        }
        registered = set(registry.names())
        for tool_name in expected_new_tools:
            assert tool_name in registered, f"Tool '{tool_name}' not registered"

    def test_existing_tools_still_registered(self):
        """Verify pre-existing tools are not broken by new registrations."""
        registry = create_default_registry()
        registered = set(registry.names())
        for tool_name in ("read_file", "write_file", "exec", "web_search", "web_fetch"):
            assert tool_name in registered, f"Existing tool '{tool_name}' missing after registration changes"

    def test_registry_has_definitions_for_all(self):
        """Every registered tool should produce a valid OpenAI function-calling definition."""
        registry = create_default_registry()
        definitions = registry.get_definitions()
        assert len(definitions) == len(registry)
        for defn in definitions:
            assert defn["type"] == "function"
            assert "name" in defn["function"]
            assert "description" in defn["function"]
            assert "parameters" in defn["function"]
