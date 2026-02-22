"""Tests for MCP failure logging."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from grip.tools import create_default_registry


class TestMCPFailureLogging:
    def test_registry_returned_despite_mcp_failure(self):
        """create_default_registry should return a valid registry even when MCP fails."""
        mock_server = MagicMock()
        mock_server.url = "http://broken:9999"
        mock_server.command = ""
        mock_server.headers = {}
        mock_server.args = []
        mock_server.env = {}
        
        registry = create_default_registry(mcp_servers={"broken": mock_server})
        assert registry is not None
        assert len(registry) > 0  # Should have built-in tools even if MCP failed

    def test_mcp_failure_does_not_crash(self):
        """Broken MCP config should not prevent registry creation."""
        registry = create_default_registry(mcp_servers={"bad": MagicMock()})
        assert registry is not None
