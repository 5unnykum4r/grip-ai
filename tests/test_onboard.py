"""Tests for the onboarding wizard flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from grip.config.schema import GripConfig
from grip.providers.registry import ProviderRegistry
from grip.providers.types import LLMResponse, TokenUsage, ToolCall


class TestProviderChoiceConstants:
    """Verify the provider ordering constants match the registry."""

    def test_cloud_providers_match_expected_order(self):
        from grip.cli.onboard import _CLOUD_PROVIDERS

        expected = [
            "openrouter",
            "anthropic",
            "openai",
            "deepseek",
            "groq",
            "gemini",
            "qwen",
            "minimax",
            "moonshot",
            "ollama_cloud",
        ]
        assert expected == _CLOUD_PROVIDERS

    def test_all_cloud_providers_exist_in_registry(self):
        from grip.cli.onboard import _CLOUD_PROVIDERS

        for name in _CLOUD_PROVIDERS:
            spec = ProviderRegistry.get_spec(name)
            assert spec is not None, f"Provider '{name}' not found in registry"

    def test_local_providers_exist_in_registry(self):
        from grip.cli.onboard import _LOCAL_SUBMENU

        for name in _LOCAL_SUBMENU:
            spec = ProviderRegistry.get_spec(name)
            assert spec is not None, f"Local provider '{name}' not found in registry"

    def test_llamacpp_in_registry(self):
        spec = ProviderRegistry.get_spec("llamacpp")
        assert spec is not None
        assert spec.display_name == "Llama.cpp (Local)"
        assert spec.api_base == "http://localhost:8080/v1"


class TestBuildProviderChoices:
    """Test the InquirerPy choice builder functions."""

    def test_provider_choices_count(self):
        from grip.cli.onboard import _build_provider_choices

        choices = _build_provider_choices()
        # Claude SDK + 10 cloud providers + "Ollama (Local)" + "Other Models"
        assert len(choices) == 13

    def test_provider_choices_end_with_local_options(self):
        from grip.cli.onboard import _build_provider_choices

        choices = _build_provider_choices()
        assert choices[-2].value == "_local_ollama"
        assert choices[-1].value == "_local_other"

    def test_provider_choices_start_with_openrouter(self):
        from grip.cli.onboard import _build_provider_choices

        choices = _build_provider_choices()
        assert choices[0].value == "_claude_sdk"

    def test_local_choices_count(self):
        from grip.cli.onboard import _build_local_choices

        choices = _build_local_choices()
        assert len(choices) == 4

    def test_local_choices_includes_custom(self):
        from grip.cli.onboard import _build_local_choices

        choices = _build_local_choices()
        values = [c.value for c in choices]
        assert "_custom_openai" in values
        assert "ollama" in values
        assert "llamacpp" in values
        assert "lmstudio" in values


class TestAutoTestConnection:
    """Test the auto-test connection function."""

    @patch("grip.cli.onboard.create_provider")
    @patch("grip.cli.onboard.asyncio")
    def test_success_with_tool_calls(self, mock_asyncio, mock_create_provider):
        from grip.cli.onboard import _auto_test_connection

        mock_provider = MagicMock()
        mock_create_provider.return_value = mock_provider

        chat_response = LLMResponse(content="grip ready!", usage=TokenUsage(), raw={})
        tool_response = LLMResponse(
            tool_calls=[
                ToolCall(
                    id="call_1",
                    function_name="get_current_time",
                    arguments={},
                )
            ],
            usage=TokenUsage(),
            raw={},
        )
        mock_asyncio.run.side_effect = [chat_response, tool_response]

        config = GripConfig()
        result = _auto_test_connection(config, "openrouter/openai/gpt-4o")
        assert result is True

    @patch("grip.cli.onboard.create_provider")
    @patch("grip.cli.onboard.asyncio")
    def test_success_without_tool_calls_still_passes(self, mock_asyncio, mock_create_provider):
        """Chat succeeds but model doesn't use tools — should still return True."""
        from grip.cli.onboard import _auto_test_connection

        mock_provider = MagicMock()
        mock_create_provider.return_value = mock_provider

        chat_response = LLMResponse(content="grip ready!", usage=TokenUsage(), raw={})
        no_tool_response = LLMResponse(content="It is 3pm.", usage=TokenUsage(), raw={})
        mock_asyncio.run.side_effect = [chat_response, no_tool_response]

        config = GripConfig()
        result = _auto_test_connection(config, "openrouter/openai/gpt-4o")
        assert result is True

    @patch("grip.cli.onboard.create_provider")
    def test_connection_failure_returns_false(self, mock_create_provider):
        from grip.cli.onboard import _auto_test_connection

        mock_create_provider.side_effect = Exception("Connection refused")

        config = GripConfig()
        result = _auto_test_connection(config, "openrouter/openai/gpt-4o")
        assert result is False


class TestSelectProvider:
    """Test provider selection logic with mocked InquirerPy."""

    @patch("grip.cli.onboard.inquirer")
    def test_cloud_provider_selection(self, mock_inquirer):
        from grip.cli.onboard import _select_provider

        mock_prompt = MagicMock()
        mock_prompt.execute.return_value = "anthropic"
        mock_inquirer.select.return_value = mock_prompt

        name, is_custom = _select_provider()
        assert name == "anthropic"
        assert is_custom is False

    @patch("grip.cli.onboard.inquirer")
    def test_ollama_shortcut(self, mock_inquirer):
        from grip.cli.onboard import _select_provider

        mock_prompt = MagicMock()
        mock_prompt.execute.return_value = "_local_ollama"
        mock_inquirer.select.return_value = mock_prompt

        name, is_custom = _select_provider()
        assert name == "ollama"
        assert is_custom is False

    @patch("grip.cli.onboard.inquirer")
    def test_local_other_custom_openai(self, mock_inquirer):
        from grip.cli.onboard import _select_provider

        # First call returns _local_other, second returns _custom_openai
        mock_prompt1 = MagicMock()
        mock_prompt1.execute.return_value = "_local_other"
        mock_prompt2 = MagicMock()
        mock_prompt2.execute.return_value = "_custom_openai"
        mock_inquirer.select.side_effect = [mock_prompt1, mock_prompt2]

        name, is_custom = _select_provider()
        assert name == ""
        assert is_custom is True

    @patch("grip.cli.onboard.inquirer")
    def test_local_other_llamacpp(self, mock_inquirer):
        from grip.cli.onboard import _select_provider

        mock_prompt1 = MagicMock()
        mock_prompt1.execute.return_value = "_local_other"
        mock_prompt2 = MagicMock()
        mock_prompt2.execute.return_value = "llamacpp"
        mock_inquirer.select.side_effect = [mock_prompt1, mock_prompt2]

        name, is_custom = _select_provider()
        assert name == "llamacpp"
        assert is_custom is False


class TestFetchProviderModels:
    """_fetch_provider_models verifies the key and loads live models (Fix)."""

    def _spec(self):
        return ProviderRegistry.get_spec("openrouter")

    def _resp(self, status_code, json_data=None, raises=False):
        r = MagicMock()
        r.status_code = status_code
        if raises:
            r.json.side_effect = ValueError("bad json")
        else:
            r.json.return_value = json_data or {}
        return r

    def test_success_returns_model_ids(self):
        from grip.cli.onboard import _fetch_provider_models

        payload = {"data": [{"id": "anthropic/claude-opus-4.6"}, {"id": "openai/gpt-4o"}]}
        with patch("httpx.get", return_value=self._resp(200, payload)):
            models, err = _fetch_provider_models(self._spec(), "sk-key", "")
        assert err is None
        assert "openai/gpt-4o" in models
        assert "anthropic/claude-opus-4.6" in models

    def test_invalid_key_returns_auth_error(self):
        from grip.cli.onboard import _fetch_provider_models

        with patch("httpx.get", return_value=self._resp(401)):
            models, err = _fetch_provider_models(self._spec(), "bad", "")
        assert models is None
        assert err == "auth"

    def test_forbidden_returns_auth_error(self):
        from grip.cli.onboard import _fetch_provider_models

        with patch("httpx.get", return_value=self._resp(403)):
            models, err = _fetch_provider_models(self._spec(), "bad", "")
        assert err == "auth"

    def test_server_error_falls_back(self):
        from grip.cli.onboard import _fetch_provider_models

        with patch("httpx.get", return_value=self._resp(500)):
            models, err = _fetch_provider_models(self._spec(), "k", "")
        assert models is None
        assert err is None  # non-auth failure → caller falls back to static list

    def test_network_error_falls_back(self):
        from grip.cli.onboard import _fetch_provider_models

        with patch("httpx.get", side_effect=OSError("network down")):
            models, err = _fetch_provider_models(self._spec(), "k", "")
        assert models is None
        assert err is None

    def test_malformed_json_falls_back(self):
        from grip.cli.onboard import _fetch_provider_models

        with patch("httpx.get", return_value=self._resp(200, raises=True)):
            models, err = _fetch_provider_models(self._spec(), "k", "")
        assert models is None
        assert err is None

    def test_empty_model_list_falls_back(self):
        from grip.cli.onboard import _fetch_provider_models

        with patch("httpx.get", return_value=self._resp(200, {"data": []})):
            models, err = _fetch_provider_models(self._spec(), "k", "")
        assert models is None
        assert err is None

    def test_openrouter_verifies_key_despite_public_models(self):
        """OpenRouter's /models is public, so a bad key must be caught via /key."""
        from grip.cli.onboard import _fetch_provider_models

        def by_url(url, **_kwargs):
            if url.endswith("/key"):
                return self._resp(401)  # key rejected by authenticated endpoint
            return self._resp(200, {"data": [{"id": "openai/gpt-4o"}]})  # public

        with patch("httpx.get", side_effect=by_url):
            models, err = _fetch_provider_models(self._spec(), "bad-key", "")
        assert models is None
        assert err == "auth"

    def test_openrouter_valid_key_loads_models(self):
        from grip.cli.onboard import _fetch_provider_models

        def by_url(url, **_kwargs):
            if url.endswith("/key"):
                return self._resp(200, {"data": {"label": "ok"}})
            return self._resp(200, {"data": [{"id": "openai/gpt-4o"}, {"id": "x-ai/grok-4.1"}]})

        with patch("httpx.get", side_effect=by_url):
            models, err = _fetch_provider_models(self._spec(), "good-key", "")
        assert err is None
        assert "openai/gpt-4o" in models

    def test_non_openrouter_uses_models_as_auth_gate(self):
        """Providers whose /models requires auth need no separate /key probe."""
        from grip.cli.onboard import _fetch_provider_models

        spec = ProviderRegistry.get_spec("openai")
        with patch("httpx.get", return_value=self._resp(401)) as mock_get:
            models, err = _fetch_provider_models(spec, "bad", "")
        assert err == "auth"
        # Only /models is probed for non-openrouter providers (no /key call).
        assert all(call.args[0].endswith("/models") for call in mock_get.call_args_list)

    def test_non_string_ids_are_ignored(self):
        from grip.cli.onboard import _fetch_provider_models

        spec = ProviderRegistry.get_spec("openai")
        payload = {"data": [{"id": "gpt-4o"}, {"id": 123}, {"id": None}, {"nope": "x"}]}
        with patch("httpx.get", return_value=self._resp(200, payload)):
            models, err = _fetch_provider_models(spec, "k", "")
        assert err is None
        assert models == ["gpt-4o"]

    def test_custom_api_base_overrides_spec(self):
        from grip.cli.onboard import _fetch_provider_models

        spec = ProviderRegistry.get_spec("openai")
        captured = {}

        def by_url(url, **_kwargs):
            captured["url"] = url
            return self._resp(200, {"data": [{"id": "local-model"}]})

        with patch("httpx.get", side_effect=by_url):
            _fetch_provider_models(spec, "k", "https://proxy.local/v1/")
        assert captured["url"] == "https://proxy.local/v1/models"  # trailing slash trimmed
