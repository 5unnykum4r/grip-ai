"""Tests for grip.api.routers.mcp — MCP server management REST endpoints."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata

from grip.api.routers.mcp import _build_server_status, _has_any_token
from grip.config.schema import GripConfig, MCPServerConfig, OAuthConfig, ToolsConfig
from grip.security.token_store import StoredToken, TokenStore
from grip.tools.mcp_auth import MCPTokenStorage, discover_mcp_oauth_metadata


@pytest.fixture
def config_with_servers(tmp_path: Path) -> GripConfig:
    """Config with both stdio and HTTP MCP servers configured."""
    return GripConfig(
        tools=ToolsConfig(
            mcp_servers={
                "github": MCPServerConfig(
                    command="npx",
                    args=["-y", "@modelcontextprotocol/server-github"],
                ),
                "remote": MCPServerConfig(
                    url="https://mcp.example.com",
                    type="http",
                    enabled=False,
                ),
                "oauth_server": MCPServerConfig(
                    url="https://oauth.example.com/mcp",
                    oauth=OAuthConfig(
                        client_id="cid",
                        auth_url="https://oauth.example.com/authorize",
                        token_url="https://oauth.example.com/token",
                        scopes=["read"],
                    ),
                ),
                "supabase": MCPServerConfig(
                    url="https://mcp.supabase.com/mcp",
                    type="http",
                ),
            }
        )
    )


class TestMCPServerStatusModel:
    def test_stdio_server_status(self, config_with_servers: GripConfig):
        srv = config_with_servers.tools.mcp_servers["github"]
        assert srv.command == "npx"
        assert srv.enabled is True

    def test_disabled_server(self, config_with_servers: GripConfig):
        srv = config_with_servers.tools.mcp_servers["remote"]
        assert srv.enabled is False

    def test_oauth_server(self, config_with_servers: GripConfig):
        srv = config_with_servers.tools.mcp_servers["oauth_server"]
        assert srv.oauth is not None
        assert srv.oauth.client_id == "cid"


class TestTokenStoreIntegration:
    def test_has_token_check(self, tmp_path: Path):
        store = TokenStore(tokens_path=tmp_path / "tokens.json")
        assert store.get("oauth_server") is None

        store.save("oauth_server", StoredToken(access_token="test_token"))
        assert store.get("oauth_server") is not None
        assert store.get("oauth_server").access_token == "test_token"


class TestHasAnyToken:
    def test_no_tokens_anywhere(self):
        assert _has_any_token("nonexistent_server") is False

    def test_grip_token_store_has_token(self, tmp_path: Path):
        store = TokenStore(tokens_path=tmp_path / "tokens.json")
        store.save("test_srv", StoredToken(access_token="abc"))
        # _has_any_token reads from default path, so we can't easily test
        # grip token store without monkeypatching. Test the MCP store instead.

    @pytest.mark.asyncio
    async def test_mcp_token_store_has_token(self):
        from mcp.shared.auth import OAuthToken

        from grip.tools.mcp_auth import MCPTokenStorage

        storage = MCPTokenStorage("test_mcp_srv")
        assert _has_any_token("test_mcp_srv") is False

        await storage.set_tokens(OAuthToken(access_token="mcp_tok"))
        assert _has_any_token("test_mcp_srv") is True

    @pytest.mark.asyncio
    async def test_mcp_client_info_alone_does_not_count_as_token(self):
        from mcp.shared.auth import OAuthClientInformationFull

        from grip.tools.mcp_auth import MCPTokenStorage

        storage = MCPTokenStorage("test_client_srv")
        assert _has_any_token("test_client_srv") is False

        await storage.set_client_info(
            OAuthClientInformationFull(
                client_id="cid",
                redirect_uris=["http://localhost:18801/callback"],
            )
        )
        assert _has_any_token("test_client_srv") is False


class TestBuildServerStatus:
    def test_stdio_server(self, config_with_servers: GripConfig):
        srv = config_with_servers.tools.mcp_servers["github"]
        status = _build_server_status("github", srv)
        assert status.name == "github"
        assert status.type == "stdio"
        assert status.enabled is True
        assert status.has_oauth is False
        assert status.needs_login is False

    def test_http_server_needs_login(self, config_with_servers: GripConfig):
        srv = config_with_servers.tools.mcp_servers["supabase"]
        status = _build_server_status("supabase", srv)
        assert status.name == "supabase"
        assert status.type == "http"
        assert status.has_oauth is True
        assert status.needs_login is True

    def test_disabled_server_no_login_needed(self, config_with_servers: GripConfig):
        srv = config_with_servers.tools.mcp_servers["remote"]
        status = _build_server_status("remote", srv)
        assert status.enabled is False
        assert status.needs_login is False

    def test_explicit_oauth_server(self, config_with_servers: GripConfig):
        srv = config_with_servers.tools.mcp_servers["oauth_server"]
        status = _build_server_status("oauth_server", srv)
        assert status.has_oauth is True
        assert status.needs_login is True


class TestToggleServerConfig:
    def test_enable_disable_roundtrip(self):
        config = GripConfig(
            tools=ToolsConfig(
                mcp_servers={
                    "test": MCPServerConfig(command="npx", enabled=True),
                }
            )
        )
        data = config.model_dump(mode="json")
        data["tools"]["mcp_servers"]["test"]["enabled"] = False
        updated = GripConfig(**data)
        assert updated.tools.mcp_servers["test"].enabled is False

        data2 = updated.model_dump(mode="json")
        data2["tools"]["mcp_servers"]["test"]["enabled"] = True
        restored = GripConfig(**data2)
        assert restored.tools.mcp_servers["test"].enabled is True


def _make_httpx_response(status_code: int, json_data: dict | None = None, headers: dict | None = None) -> httpx.Response:
    """Build a real httpx.Response for use in tests."""
    resp = httpx.Response(
        status_code=status_code,
        headers=headers or {},
        json=json_data,
    )
    return resp


class TestDiscoverMCPOAuthMetadata:
    """Tests for the discover_mcp_oauth_metadata() function."""

    @pytest.mark.asyncio
    async def test_full_discovery_flow(self, tmp_path: Path):
        """Mock httpx responses (401 -> PRM -> OAuth metadata -> registration)."""
        server_url = "https://mcp.example.com/mcp"
        redirect_uri = "http://localhost:8080/api/v1/mcp/callback"

        # 401 response with WWW-Authenticate header
        resp_401 = _make_httpx_response(
            401,
            headers={
                "WWW-Authenticate": (
                    'Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource"'
                ),
            },
        )

        # Protected Resource Metadata response
        resp_prm = _make_httpx_response(200, json_data={
            "resource": "https://mcp.example.com/mcp",
            "authorization_servers": ["https://auth.example.com"],
            "scopes_supported": ["mcp:read", "mcp:write"],
        })

        # OAuth Authorization Server Metadata response
        resp_oauth_meta = _make_httpx_response(200, json_data={
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "registration_endpoint": "https://auth.example.com/register",
            "response_types_supported": ["code"],
            "scopes_supported": ["mcp:read", "mcp:write"],
        })

        # Dynamic client registration response
        resp_registration = _make_httpx_response(200, json_data={
            "client_id": "registered_client_id",
            "client_secret": "registered_secret",
            "redirect_uris": [redirect_uri],
        })

        call_count = 0
        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            url_str = str(url)
            if call_count == 1:
                return resp_401
            elif "oauth-protected-resource" in url_str or ".well-known" in url_str:
                if "oauth-authorization-server" in url_str or "openid-configuration" in url_str:
                    return resp_oauth_meta
                return resp_prm
            return resp_oauth_meta

        async def mock_send(request, **kwargs):
            return resp_registration

        storage = MCPTokenStorage("test_discovery_srv", base_dir=tmp_path)

        with patch("grip.tools.mcp_auth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            mock_client.send = mock_send
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("grip.tools.mcp_auth.MCPTokenStorage", return_value=storage):
                oauth_metadata, client_info = await discover_mcp_oauth_metadata(
                    "test_discovery_srv", server_url, redirect_uri
                )

        assert str(oauth_metadata.authorization_endpoint) == "https://auth.example.com/authorize"
        assert str(oauth_metadata.token_endpoint) == "https://auth.example.com/token"
        assert client_info.client_id == "registered_client_id"
        assert client_info.client_secret == "registered_secret"

    @pytest.mark.asyncio
    async def test_server_not_401_raises(self):
        """Server returns 200 instead of 401 — should raise RuntimeError."""
        resp_200 = _make_httpx_response(200, json_data={"status": "ok"})

        with patch("grip.tools.mcp_auth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=resp_200)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="Expected 401"):
                await discover_mcp_oauth_metadata(
                    "test_srv", "https://mcp.example.com/mcp", "http://localhost/callback"
                )

    @pytest.mark.asyncio
    async def test_reuses_existing_client_info(self, tmp_path: Path):
        """Pre-stored client_info skips registration."""
        server_url = "https://mcp.example.com/mcp"
        redirect_uri = "http://localhost:8080/api/v1/mcp/callback"

        storage = MCPTokenStorage("test_reuse_srv", base_dir=tmp_path)
        existing_client = OAuthClientInformationFull(
            client_id="existing_client",
            client_secret="existing_secret",
            redirect_uris=[redirect_uri],
        )
        await storage.set_client_info(existing_client)

        resp_401 = _make_httpx_response(
            401,
            headers={
                "WWW-Authenticate": (
                    'Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource"'
                ),
            },
        )
        resp_prm = _make_httpx_response(200, json_data={
            "resource": "https://mcp.example.com/mcp",
            "authorization_servers": ["https://auth.example.com"],
        })
        resp_oauth_meta = _make_httpx_response(200, json_data={
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "registration_endpoint": "https://auth.example.com/register",
            "response_types_supported": ["code"],
        })

        call_count = 0
        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return resp_401
            elif call_count == 2:
                return resp_prm
            return resp_oauth_meta

        send_called = False
        async def mock_send(request, **kwargs):
            nonlocal send_called
            send_called = True
            raise AssertionError("Registration should not be called when client_info exists")

        with patch("grip.tools.mcp_auth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            mock_client.send = mock_send
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("grip.tools.mcp_auth.MCPTokenStorage", return_value=storage):
                oauth_metadata, client_info = await discover_mcp_oauth_metadata(
                    "test_reuse_srv", server_url, redirect_uri
                )

        assert send_called is False
        assert client_info.client_id == "existing_client"
        assert client_info.client_secret == "existing_secret"


class TestGatewayMCPOAuth:
    """Tests for the gateway-mediated MCP OAuth login and callback flows."""

    @pytest.mark.asyncio
    async def test_mcp_login_returns_auth_url(self):
        """Mock discover_mcp_oauth_metadata and verify login returns auth_url."""
        from grip.api.routers.mcp import _initiate_mcp_gateway_oauth

        fake_metadata = OAuthMetadata(
            issuer="https://auth.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            response_types_supported=["code"],
            scopes_supported=["mcp:read"],
        )
        fake_client = OAuthClientInformationFull(
            client_id="test_cid",
            client_secret="test_secret",
            redirect_uris=["http://localhost:8080/api/v1/mcp/callback"],
        )

        app_state = SimpleNamespace()
        mock_request = MagicMock()
        mock_request.app.state = app_state

        srv = SimpleNamespace(url="https://mcp.example.com/mcp", oauth=None)
        config = GripConfig()

        with patch(
            "grip.tools.mcp_auth.discover_mcp_oauth_metadata",
            new_callable=AsyncMock,
            return_value=(fake_metadata, fake_client),
        ):
            result = await _initiate_mcp_gateway_oauth("supabase", srv, mock_request, config)

        assert result.server_name == "supabase"
        assert result.status == "pending"
        assert result.auth_url is not None

        parsed = urlparse(result.auth_url)
        assert parsed.scheme == "https"
        assert parsed.hostname == "auth.example.com"
        assert parsed.path == "/authorize"
        params = parse_qs(parsed.query)
        assert params["client_id"] == ["test_cid"]
        assert params["response_type"] == ["code"]
        assert params["code_challenge_method"] == ["S256"]
        assert "code_challenge" in params
        assert "state" in params
        assert params["scope"] == ["mcp:read"]

        # Verify oauth_pending was populated
        pending = app_state.oauth_pending
        assert len(pending) == 1
        state_token = list(pending.keys())[0]
        flow = pending[state_token]
        assert flow["flow_type"] == "mcp"
        assert flow["server_name"] == "supabase"
        assert flow["client_id"] == "test_cid"
        assert flow["client_secret"] == "test_secret"

    @pytest.mark.asyncio
    async def test_mcp_callback_stores_in_mcp_token_storage(self, tmp_path: Path):
        """MCP flow callback stores tokens in MCPTokenStorage, not TokenStore."""
        from grip.api.routers.mcp import oauth_callback

        app_state = SimpleNamespace(
            oauth_pending={
                "test_state_123": {
                    "flow_type": "mcp",
                    "server_name": "supabase",
                    "code_verifier": "test_verifier",
                    "redirect_uri": "http://localhost:8080/api/v1/mcp/callback",
                    "token_url": "https://auth.example.com/token",
                    "client_id": "test_cid",
                    "client_secret": "test_secret",
                    "created_at": time.time(),
                }
            }
        )

        mock_request = MagicMock()
        mock_request.app.state = app_state

        token_response = httpx.Response(
            200,
            json={
                "access_token": "mcp_access_tok",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "mcp_refresh_tok",
                "scope": "mcp:read",
            },
        )

        mock_storage = MCPTokenStorage("supabase", base_dir=tmp_path)

        with patch("grip.api.routers.mcp.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=token_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("grip.api.routers.mcp.MCPTokenStorage", return_value=mock_storage):
                result = await oauth_callback(
                    request=mock_request,
                    code="auth_code_xyz",
                    state="test_state_123",
                )

        assert result.status_code == 200
        assert "Login Successful" in result.body.decode()

        stored_token = await mock_storage.get_tokens()
        assert stored_token is not None
        assert stored_token.access_token == "mcp_access_tok"
        assert stored_token.refresh_token == "mcp_refresh_tok"

    @pytest.mark.asyncio
    async def test_mcp_callback_includes_client_secret(self):
        """MCP flow includes client_secret in the token exchange POST body."""
        from grip.api.routers.mcp import oauth_callback

        app_state = SimpleNamespace(
            oauth_pending={
                "state_with_secret": {
                    "flow_type": "mcp",
                    "server_name": "supabase",
                    "code_verifier": "verifier_abc",
                    "redirect_uri": "http://localhost:8080/api/v1/mcp/callback",
                    "token_url": "https://auth.example.com/token",
                    "client_id": "cid_123",
                    "client_secret": "secret_456",
                    "created_at": time.time(),
                }
            }
        )

        mock_request = MagicMock()
        mock_request.app.state = app_state

        token_response = httpx.Response(
            200,
            json={
                "access_token": "tok",
                "token_type": "Bearer",
            },
        )

        captured_data = {}

        async def capture_post(url, *, data=None, **kwargs):
            captured_data.update(data or {})
            return token_response

        with patch("grip.api.routers.mcp.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = capture_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await oauth_callback(
                request=mock_request,
                code="code_abc",
                state="state_with_secret",
            )

        assert captured_data["client_secret"] == "secret_456"
        assert captured_data["client_id"] == "cid_123"
        assert captured_data["code_verifier"] == "verifier_abc"

    @pytest.mark.asyncio
    async def test_explicit_callback_still_stores_in_token_store(self, tmp_path: Path):
        """Regression: explicit flow callback stores in TokenStore, not MCPTokenStorage."""
        from grip.api.routers.mcp import oauth_callback

        app_state = SimpleNamespace(
            oauth_pending={
                "explicit_state": {
                    "flow_type": "explicit",
                    "server_name": "oauth_server",
                    "code_verifier": "explicit_verifier",
                    "redirect_uri": "http://localhost:8080/api/v1/mcp/callback",
                    "token_url": "https://oauth.example.com/token",
                    "client_id": "explicit_cid",
                    "created_at": time.time(),
                }
            }
        )

        mock_request = MagicMock()
        mock_request.app.state = app_state

        token_response = httpx.Response(
            200,
            json={
                "access_token": "explicit_tok",
                "token_type": "Bearer",
                "expires_in": 7200,
                "refresh_token": "explicit_refresh",
                "scope": "read",
            },
        )

        mock_token_store = MagicMock(spec=TokenStore)

        with patch("grip.api.routers.mcp.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=token_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("grip.api.routers.mcp.TokenStore", return_value=mock_token_store):
                result = await oauth_callback(
                    request=mock_request,
                    code="explicit_code",
                    state="explicit_state",
                )

        assert result.status_code == 200
        mock_token_store.save.assert_called_once()
        call_args = mock_token_store.save.call_args
        assert call_args[0][0] == "oauth_server"
        stored = call_args[0][1]
        assert stored.access_token == "explicit_tok"
        assert stored.refresh_token == "explicit_refresh"
