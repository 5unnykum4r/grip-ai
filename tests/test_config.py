"""Tests for the configuration system."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from grip.config.schema import (
    AgentDefaults,
    AgentProfile,
    APIConfig,
    GatewayConfig,
    GripConfig,
    MCPServerConfig,
    OAuthConfig,
    ProviderEntry,
    ToolsConfig,
)


def test_default_config_loads():
    """AgentDefaults should have sensible defaults when constructed directly."""
    defaults = AgentDefaults()
    assert defaults.model == "openrouter/anthropic/claude-sonnet-4"
    assert defaults.max_tokens == 8192
    assert defaults.temperature == 0.7


def test_api_config_defaults():
    """APIConfig should have secure defaults."""
    api = APIConfig()
    assert api.auth_token.get_secret_value() == ""
    assert api.rate_limit_per_minute == 60
    assert api.rate_limit_per_minute_per_ip == 30
    assert api.enable_tool_execute is False
    assert api.max_request_body_bytes == 1_048_576


def test_gateway_includes_api():
    """GatewayConfig should nest APIConfig."""
    gw = GatewayConfig()
    assert gw.host == "127.0.0.1"
    assert gw.port == 18800
    assert isinstance(gw.api, APIConfig)


def test_agent_profile_empty_inherits():
    """Empty AgentProfile fields signal inheritance from defaults."""
    profile = AgentProfile()
    assert profile.model == ""
    assert profile.tools_allowed == []
    assert profile.tools_denied == []


def test_agent_profiles_in_config():
    """Profiles dict should be accessible from agents config."""
    config = GripConfig(
        agents={
            "defaults": {},
            "profiles": {
                "researcher": {
                    "model": "openai/gpt-4o",
                    "tools_allowed": ["web_search", "web_fetch"],
                },
            },
        }
    )
    assert "researcher" in config.agents.profiles
    assert config.agents.profiles["researcher"].model == "openai/gpt-4o"


def test_workspace_path_expansion():
    """Workspace path with ~ should be expandable."""
    defaults = AgentDefaults()
    expanded = defaults.workspace.expanduser()
    assert "~" not in str(expanded)


def test_save_config_strips_empty_providers(tmp_path):
    """save_config should not write provider entries with no api_key and no default_model."""
    from grip.config import save_config

    config = GripConfig(
        providers={
            "openrouter": ProviderEntry(api_key="real-key", default_model="gpt-4o"),
            "lmstudio": ProviderEntry(),
        },
    )
    path = tmp_path / "config.json"
    save_config(config, path)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "openrouter" in saved["providers"]
    assert "lmstudio" not in saved["providers"]


def test_save_config_keeps_provider_with_key(tmp_path):
    """Providers with api_key set should not be stripped."""
    from grip.config import save_config

    config = GripConfig(
        providers={
            "anthropic": ProviderEntry(api_key="sk-test"),
        },
    )
    path = tmp_path / "config.json"
    save_config(config, path)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "anthropic" in saved["providers"]


def test_save_config_keeps_provider_with_default_model(tmp_path):
    """Providers with default_model set should not be stripped even without api_key."""
    from grip.config import save_config

    config = GripConfig(
        providers={
            "ollama": ProviderEntry(default_model="llama3.2"),
        },
    )
    path = tmp_path / "config.json"
    save_config(config, path)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "ollama" in saved["providers"]


# ---------------------------------------------------------------------------
# Tests: MCPServerConfig new fields
# ---------------------------------------------------------------------------


class TestMCPServerConfig:
    def test_defaults(self):
        srv = MCPServerConfig()
        assert srv.command == ""
        assert srv.args == []
        assert srv.env == {}
        assert srv.url == ""
        assert srv.headers == {}
        assert srv.type == ""
        assert srv.allowed_tools == []
        assert srv.timeout == 60
        assert srv.enabled is True
        assert srv.oauth is None

    def test_stdio_server(self):
        srv = MCPServerConfig(command="npx", args=["-y", "test-mcp"], env={"KEY": "val"})
        assert srv.command == "npx"
        assert srv.args == ["-y", "test-mcp"]
        assert srv.env == {"KEY": "val"}

    def test_http_server_with_type(self):
        srv = MCPServerConfig(url="https://mcp.example.com", type="http")
        assert srv.url == "https://mcp.example.com"
        assert srv.type == "http"

    def test_sse_type(self):
        srv = MCPServerConfig(url="https://mcp.example.com/sse", type="sse")
        assert srv.type == "sse"

    def test_enabled_false(self):
        srv = MCPServerConfig(command="npx", enabled=False)
        assert srv.enabled is False

    def test_allowed_tools_patterns(self):
        srv = MCPServerConfig(
            command="npx",
            allowed_tools=["mcp__github__*", "mcp__github__create_issue"],
        )
        assert len(srv.allowed_tools) == 2
        assert "mcp__github__*" in srv.allowed_tools

    def test_timeout_custom(self):
        srv = MCPServerConfig(command="npx", timeout=120)
        assert srv.timeout == 120

    def test_timeout_bounds(self):
        with pytest.raises(ValidationError):
            MCPServerConfig(command="npx", timeout=0)
        with pytest.raises(ValidationError):
            MCPServerConfig(command="npx", timeout=601)

    def test_with_oauth(self):
        oauth = OAuthConfig(
            client_id="cid",
            auth_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            scopes=["read"],
        )
        srv = MCPServerConfig(url="https://mcp.example.com", oauth=oauth)
        assert srv.oauth is not None
        assert srv.oauth.client_id == "cid"
        assert srv.oauth.scopes == ["read"]

    def test_json_roundtrip(self):
        srv = MCPServerConfig(
            command="npx",
            args=["-y", "test"],
            type="",
            allowed_tools=["mcp__test__*"],
            timeout=30,
            enabled=False,
        )
        data = srv.model_dump(mode="json")
        restored = MCPServerConfig(**data)
        assert restored.command == "npx"
        assert restored.allowed_tools == ["mcp__test__*"]
        assert restored.timeout == 30
        assert restored.enabled is False


class TestOAuthConfig:
    def test_defaults(self):
        oauth = OAuthConfig()
        assert oauth.client_id == ""
        assert oauth.auth_url == ""
        assert oauth.token_url == ""
        assert oauth.scopes == []
        assert oauth.redirect_port == 18801

    def test_custom_values(self):
        oauth = OAuthConfig(
            client_id="my_client",
            auth_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            scopes=["read", "write"],
            redirect_port=19000,
        )
        assert oauth.client_id == "my_client"
        assert oauth.scopes == ["read", "write"]
        assert oauth.redirect_port == 19000

    def test_redirect_port_bounds(self):
        with pytest.raises(ValidationError):
            OAuthConfig(redirect_port=1023)
        with pytest.raises(ValidationError):
            OAuthConfig(redirect_port=65536)

    def test_json_roundtrip(self):
        oauth = OAuthConfig(
            client_id="cid",
            auth_url="https://a.com/auth",
            token_url="https://a.com/token",
            scopes=["read"],
            redirect_port=19999,
        )
        data = oauth.model_dump(mode="json")
        restored = OAuthConfig(**data)
        assert restored.client_id == "cid"
        assert restored.redirect_port == 19999


class TestSecretStrFields:
    """Verify that sensitive config fields use SecretStr for masking."""

    def test_provider_api_key_is_secret(self):
        from pydantic import SecretStr

        entry = ProviderEntry(api_key="sk-test-123")
        assert isinstance(entry.api_key, SecretStr)
        assert entry.api_key.get_secret_value() == "sk-test-123"
        assert "sk-test-123" not in repr(entry)

    def test_channel_token_is_secret(self):
        from pydantic import SecretStr

        from grip.config.schema import ChannelEntry

        ch = ChannelEntry(token="bot-token-abc")
        assert isinstance(ch.token, SecretStr)
        assert ch.token.get_secret_value() == "bot-token-abc"
        assert "bot-token-abc" not in repr(ch)

    def test_api_auth_token_is_secret(self):
        from pydantic import SecretStr

        api = APIConfig(auth_token="grip_secret_xyz")
        assert isinstance(api.auth_token, SecretStr)
        assert api.auth_token.get_secret_value() == "grip_secret_xyz"
        assert "grip_secret_xyz" not in repr(api)

    def test_web_search_api_key_is_secret(self):
        from pydantic import SecretStr

        from grip.config.schema import WebSearchProvider

        ws = WebSearchProvider(api_key="brave-key-456")
        assert isinstance(ws.api_key, SecretStr)
        assert ws.api_key.get_secret_value() == "brave-key-456"
        assert "brave-key-456" not in repr(ws)

    def test_json_roundtrip_preserves_values(self, tmp_path):
        """SecretStr fields should serialize to raw strings in JSON and roundtrip correctly."""
        from grip.config import save_config

        config = GripConfig(
            providers={"anthropic": ProviderEntry(api_key="sk-roundtrip")},
            gateway={"api": {"auth_token": "grip_rt_token"}},
        )
        path = tmp_path / "config.json"
        save_config(config, path)

        import json

        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["providers"]["anthropic"]["api_key"] == "sk-roundtrip"
        assert saved["gateway"]["api"]["auth_token"] == "grip_rt_token"


class TestToolsConfigEnableToolSearch:
    def test_default_value(self):
        tc = ToolsConfig()
        assert tc.enable_tool_search == "auto"

    def test_custom_values(self):
        for val in ("true", "false", "auto:20"):
            tc = ToolsConfig(enable_tool_search=val)
            assert tc.enable_tool_search == val

    def test_in_grip_config(self):
        config = GripConfig(tools={"enable_tool_search": "auto:15"})
        assert config.tools.enable_tool_search == "auto:15"
