"""Tests for grip.security.oauth — OAuth 2.0 Authorization Code flow with PKCE."""

from __future__ import annotations

import base64
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from grip.config.schema import OAuthConfig
from grip.security.oauth import OAuthFlow, OAuthFlowError
from grip.security.token_store import StoredToken


@pytest.fixture
def oauth_config() -> OAuthConfig:
    return OAuthConfig(
        client_id="test_client_id",
        auth_url="https://auth.example.com/authorize",
        token_url="https://auth.example.com/token",
        scopes=["read", "write"],
        redirect_port=19999,
    )


@pytest.fixture
def flow(oauth_config: OAuthConfig) -> OAuthFlow:
    return OAuthFlow(oauth_config, server_name="test_server", timeout=5)


class TestOAuthFlow:
    def test_redirect_uri(self, flow: OAuthFlow):
        assert flow.redirect_uri == "http://localhost:19999/callback"

    def test_build_auth_url_includes_all_params(self, flow: OAuthFlow):
        url = flow.build_auth_url()
        assert "client_id=test_client_id" in url
        assert "response_type=code" in url
        assert "redirect_uri=" in url
        assert "state=" in url
        assert "code_challenge=" in url
        assert "code_challenge_method=S256" in url
        assert "scope=read+write" in url
        assert url.startswith("https://auth.example.com/authorize?")

    def test_code_challenge_is_sha256(self, flow: OAuthFlow):
        verifier = flow._code_verifier
        expected_digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected_challenge = base64.urlsafe_b64encode(expected_digest).rstrip(b"=").decode("ascii")
        assert flow._code_challenge == expected_challenge

    def test_state_is_random(self, oauth_config: OAuthConfig):
        flow1 = OAuthFlow(oauth_config, "s1")
        flow2 = OAuthFlow(oauth_config, "s2")
        assert flow1._state != flow2._state

    def test_code_verifier_is_random(self, oauth_config: OAuthConfig):
        flow1 = OAuthFlow(oauth_config, "s1")
        flow2 = OAuthFlow(oauth_config, "s2")
        assert flow1._code_verifier != flow2._code_verifier

    def test_parse_token_response(self, flow: OAuthFlow):
        data = {
            "access_token": "at_123",
            "refresh_token": "rt_456",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "read write",
        }
        token = flow._parse_token_response(data)
        assert isinstance(token, StoredToken)
        assert token.access_token == "at_123"
        assert token.refresh_token == "rt_456"
        assert token.token_type == "Bearer"
        assert token.scopes == ["read", "write"]
        assert token.expires_at > 0

    def test_parse_token_response_no_refresh(self, flow: OAuthFlow):
        data = {"access_token": "at_only", "expires_in": 60}
        token = flow._parse_token_response(data)
        assert token.access_token == "at_only"
        assert token.refresh_token == ""

    def test_parse_token_response_no_expiry(self, flow: OAuthFlow):
        data = {"access_token": "at_no_exp"}
        token = flow._parse_token_response(data)
        assert token.expires_at == 0.0
        assert not token.is_expired

    @pytest.mark.asyncio
    async def test_refresh_success(self, flow: OAuthFlow):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_at",
            "refresh_token": "new_rt",
            "expires_in": 3600,
        }

        with patch("grip.security.oauth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            token = await flow.refresh("old_rt")
            assert token.access_token == "new_at"
            assert token.refresh_token == "new_rt"

    @pytest.mark.asyncio
    async def test_refresh_failure_raises(self, flow: OAuthFlow):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with patch("grip.security.oauth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with pytest.raises(OAuthFlowError, match="Token refresh failed"):
                await flow.refresh("bad_rt")

    def test_build_auth_url_no_scopes(self):
        config = OAuthConfig(
            client_id="cid",
            auth_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            scopes=[],
        )
        flow = OAuthFlow(config, "s")
        url = flow.build_auth_url()
        assert "scope=" not in url
