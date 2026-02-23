"""Tests for grip.cli.mcp_interactive — interactive /mcp command."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from grip.cli.mcp_interactive import (
    ServerStatus,
    actions_for_status,
    determine_status,
)
from grip.config.schema import MCPServerConfig, OAuthConfig


@pytest.fixture
def stdio_config() -> MCPServerConfig:
    return MCPServerConfig(command="npx", args=["-y", "test-mcp"])


@pytest.fixture
def http_config() -> MCPServerConfig:
    return MCPServerConfig(url="https://mcp.example.com", type="http")


@pytest.fixture
def oauth_config() -> MCPServerConfig:
    return MCPServerConfig(
        url="https://mcp.example.com",
        oauth=OAuthConfig(
            client_id="cid",
            auth_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
        ),
    )


@pytest.fixture
def disabled_config() -> MCPServerConfig:
    return MCPServerConfig(command="npx", args=["-y", "test"], enabled=False)


class TestDetermineStatus:
    def test_disabled_server(self, disabled_config: MCPServerConfig):
        status = determine_status("test", disabled_config, None)
        assert status == ServerStatus.DISABLED

    def test_oauth_no_token(self, oauth_config: MCPServerConfig):
        status = determine_status("test", oauth_config, None)
        assert status == ServerStatus.AUTH_REQUIRED

    def test_disconnected_no_manager_stdio(self, stdio_config: MCPServerConfig):
        status = determine_status("test", stdio_config, None)
        assert status == ServerStatus.DISCONNECTED

    def test_http_no_tokens_shows_auth_required(self, http_config: MCPServerConfig):
        status = determine_status("test", http_config, None)
        assert status == ServerStatus.AUTH_REQUIRED

    def test_connected_via_manager(self, stdio_config: MCPServerConfig):
        mock_manager = MagicMock()
        mock_conn = MagicMock()
        mock_conn.is_connected = True
        mock_conn.error = ""
        mock_manager.get_connection.return_value = mock_conn
        status = determine_status("test", stdio_config, mock_manager)
        assert status == ServerStatus.CONNECTED

    def test_disconnected_via_manager(self, stdio_config: MCPServerConfig):
        mock_manager = MagicMock()
        mock_conn = MagicMock()
        mock_conn.is_connected = False
        mock_conn.error = ""
        mock_manager.get_connection.return_value = mock_conn
        status = determine_status("test", stdio_config, mock_manager)
        assert status == ServerStatus.DISCONNECTED

    def test_not_in_manager(self, stdio_config: MCPServerConfig):
        mock_manager = MagicMock()
        mock_manager.get_connection.return_value = None
        status = determine_status("test", stdio_config, mock_manager)
        assert status == ServerStatus.DISCONNECTED

    def test_oauth_login_required_error(self, http_config: MCPServerConfig):
        mock_manager = MagicMock()
        mock_conn = MagicMock()
        mock_conn.is_connected = False
        mock_conn.error = "OAuth login required"
        mock_manager.get_connection.return_value = mock_conn
        status = determine_status("test", http_config, mock_manager)
        assert status == ServerStatus.AUTH_REQUIRED


class TestActionsForStatus:
    def test_connected_actions(self):
        actions = actions_for_status(ServerStatus.CONNECTED)
        assert "Reconnect" in actions
        assert "Disable" in actions

    def test_disconnected_actions(self):
        actions = actions_for_status(ServerStatus.DISCONNECTED)
        assert "Connect" in actions
        assert "Login" in actions
        assert "Delete" in actions

    def test_auth_required_actions(self):
        actions = actions_for_status(ServerStatus.AUTH_REQUIRED)
        assert "Login" in actions
        assert "Delete" in actions

    def test_disabled_actions(self):
        actions = actions_for_status(ServerStatus.DISABLED)
        assert "Enable" in actions
        assert "Delete" in actions
