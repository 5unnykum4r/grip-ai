"""Tests for grip.tools.mcp_auth — MCP OAuth adapter and token storage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from grip.tools.mcp_auth import MCPTokenStorage, create_mcp_oauth_auth


class TestMCPTokenStorage:
    """MCPTokenStorage stores and retrieves MCP OAuth tokens and client info."""

    @pytest.mark.asyncio
    async def test_get_tokens_returns_none_when_empty(self, tmp_path: Path):
        storage = MCPTokenStorage("supabase", base_dir=tmp_path)
        result = await storage.get_tokens()
        assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get_tokens(self, tmp_path: Path):
        from mcp.shared.auth import OAuthToken

        storage = MCPTokenStorage("supabase", base_dir=tmp_path)
        token = OAuthToken(
            access_token="abc123",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="refresh_xyz",
        )
        await storage.set_tokens(token)

        loaded = await storage.get_tokens()
        assert loaded is not None
        assert loaded.access_token == "abc123"
        assert loaded.refresh_token == "refresh_xyz"
        assert loaded.expires_in == 3600

    @pytest.mark.asyncio
    async def test_tokens_persist_to_file(self, tmp_path: Path):
        from mcp.shared.auth import OAuthToken

        storage = MCPTokenStorage("test_server", base_dir=tmp_path)
        token = OAuthToken(access_token="tok1")
        await storage.set_tokens(token)

        raw = json.loads((tmp_path / "mcp_tokens.json").read_text())
        assert "test_server" in raw
        assert raw["test_server"]["access_token"] == "tok1"

    @pytest.mark.asyncio
    async def test_multiple_servers_isolated(self, tmp_path: Path):
        from mcp.shared.auth import OAuthToken

        s1 = MCPTokenStorage("server_a", base_dir=tmp_path)
        s2 = MCPTokenStorage("server_b", base_dir=tmp_path)

        await s1.set_tokens(OAuthToken(access_token="tok_a"))
        await s2.set_tokens(OAuthToken(access_token="tok_b"))

        loaded_a = await s1.get_tokens()
        loaded_b = await s2.get_tokens()
        assert loaded_a.access_token == "tok_a"
        assert loaded_b.access_token == "tok_b"

    @pytest.mark.asyncio
    async def test_get_client_info_returns_none_when_empty(self, tmp_path: Path):
        storage = MCPTokenStorage("supabase", base_dir=tmp_path)
        result = await storage.get_client_info()
        assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get_client_info(self, tmp_path: Path):
        from mcp.shared.auth import OAuthClientInformationFull

        storage = MCPTokenStorage("supabase", base_dir=tmp_path)
        client_info = OAuthClientInformationFull(
            client_id="dyn_client_123",
            client_secret="secret_456",
            redirect_uris=["http://localhost:18801/callback"],
        )
        await storage.set_client_info(client_info)

        loaded = await storage.get_client_info()
        assert loaded is not None
        assert loaded.client_id == "dyn_client_123"
        assert loaded.client_secret == "secret_456"

    @pytest.mark.asyncio
    async def test_client_info_persists_to_separate_file(self, tmp_path: Path):
        from mcp.shared.auth import OAuthClientInformationFull

        storage = MCPTokenStorage("supabase", base_dir=tmp_path)
        await storage.set_client_info(
            OAuthClientInformationFull(
                client_id="cid",
                redirect_uris=["http://localhost:18801/callback"],
            )
        )

        assert (tmp_path / "mcp_clients.json").exists()
        raw = json.loads((tmp_path / "mcp_clients.json").read_text())
        assert raw["supabase"]["client_id"] == "cid"

    @pytest.mark.asyncio
    async def test_corrupt_tokens_file_returns_none(self, tmp_path: Path):
        (tmp_path / "mcp_tokens.json").write_text("not json!!!")
        storage = MCPTokenStorage("supabase", base_dir=tmp_path)
        result = await storage.get_tokens()
        assert result is None

    @pytest.mark.asyncio
    async def test_corrupt_clients_file_returns_none(self, tmp_path: Path):
        (tmp_path / "mcp_clients.json").write_text("{bad")
        storage = MCPTokenStorage("supabase", base_dir=tmp_path)
        result = await storage.get_client_info()
        assert result is None

    @pytest.mark.asyncio
    async def test_creates_base_dir_on_write(self, tmp_path: Path):
        nested = tmp_path / "deep" / "nested"
        storage = MCPTokenStorage("test", base_dir=nested)

        from mcp.shared.auth import OAuthToken

        await storage.set_tokens(OAuthToken(access_token="x"))
        assert nested.exists()
        assert (nested / "mcp_tokens.json").exists()


class TestCreateMCPOAuthAuth:
    """create_mcp_oauth_auth() builds an OAuthClientProvider."""

    def test_returns_oauth_client_provider(self):
        auth = create_mcp_oauth_auth("supabase", "https://mcp.supabase.com/mcp")
        from mcp.client.auth import OAuthClientProvider

        assert isinstance(auth, OAuthClientProvider)

    def test_custom_callback_port(self):
        auth = create_mcp_oauth_auth(
            "test", "https://mcp.example.com", callback_port=19999
        )
        assert auth is not None

    def test_returns_none_when_mcp_auth_missing(self):
        from unittest.mock import patch

        with patch.dict("sys.modules", {"mcp.client.auth": None}):
            result = create_mcp_oauth_auth("test", "https://example.com")
            assert result is None
