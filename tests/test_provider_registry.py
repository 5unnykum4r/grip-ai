"""Tests for provider registry model resolution and provider creation."""

from __future__ import annotations

import json

from grip.config.schema import AgentDefaults, AgentsConfig, GripConfig, ProviderEntry
from grip.providers.registry import ProviderRegistry, create_provider


class TestResolveModel:
    """Test ProviderRegistry.resolve_model() with various inputs."""

    def test_openai_prefix_routes_to_openai(self):
        spec, bare = ProviderRegistry.resolve_model("openai/gpt-4o")
        assert spec.name == "openai"
        assert bare == "gpt-4o"

    def test_anthropic_prefix(self):
        spec, bare = ProviderRegistry.resolve_model("anthropic/claude-sonnet-4")
        assert spec.name == "anthropic"
        assert bare == "claude-sonnet-4"

    def test_openrouter_prefix(self):
        spec, bare = ProviderRegistry.resolve_model("openrouter/openai/gpt-4o")
        assert spec.name == "openrouter"
        assert bare == "openai/gpt-4o"

    def test_ollama_prefix(self):
        spec, bare = ProviderRegistry.resolve_model("ollama/llama3.2")
        assert spec.name == "ollama"
        assert bare == "llama3.2"

    def test_deepseek_prefix(self):
        spec, bare = ProviderRegistry.resolve_model("deepseek/deepseek-chat")
        assert spec.name == "deepseek"
        assert bare == "deepseek-chat"

    def test_groq_prefix(self):
        spec, bare = ProviderRegistry.resolve_model("groq/llama-3.3-70b-versatile")
        assert spec.name == "groq"
        assert bare == "llama-3.3-70b-versatile"

    def test_gemini_prefix(self):
        spec, bare = ProviderRegistry.resolve_model("gemini/gemini-2.5-pro")
        assert spec.name == "gemini"
        assert bare == "gemini-2.5-pro"

    def test_no_prefix_falls_back_to_openrouter(self):
        spec, bare = ProviderRegistry.resolve_model("gpt-4o")
        assert spec.name == "openrouter"
        assert bare == "gpt-4o"

    def test_explicit_provider_overrides_prefix(self):
        """Core bug fix: 'openai/gpt-oss-120b' with provider='openrouter' routes to OpenRouter."""
        spec, bare = ProviderRegistry.resolve_model("openai/gpt-oss-120b", provider="openrouter")
        assert spec.name == "openrouter"
        # Model string kept intact since openai/ is NOT openrouter's prefix
        assert bare == "openai/gpt-oss-120b"

    def test_explicit_provider_strips_own_prefix(self):
        """When provider='openai' and model starts with 'openai/', strip the prefix."""
        spec, bare = ProviderRegistry.resolve_model("openai/gpt-4o", provider="openai")
        assert spec.name == "openai"
        assert bare == "gpt-4o"

    def test_explicit_provider_not_found_falls_back_to_prefix(self):
        """Unknown explicit provider falls back to prefix detection."""
        spec, bare = ProviderRegistry.resolve_model(
            "openai/gpt-4o", provider="nonexistent_provider"
        )
        assert spec.name == "openai"
        assert bare == "gpt-4o"

    def test_explicit_provider_with_bare_model(self):
        """Explicit provider with a bare model name (no prefix in string)."""
        spec, bare = ProviderRegistry.resolve_model("gpt-4o", provider="openai")
        assert spec.name == "openai"
        assert bare == "gpt-4o"

    def test_explicit_provider_ollama_with_bare_model(self):
        spec, bare = ProviderRegistry.resolve_model("llama3.2", provider="ollama")
        assert spec.name == "ollama"
        assert bare == "llama3.2"

    def test_empty_provider_string_uses_prefix(self):
        """Empty provider string should behave like no provider set."""
        spec, bare = ProviderRegistry.resolve_model("openai/gpt-4o", provider="")
        assert spec.name == "openai"
        assert bare == "gpt-4o"

    def test_lmstudio_prefix(self):
        spec, bare = ProviderRegistry.resolve_model("lmstudio/llama-3.2-3b-instruct")
        assert spec.name == "lmstudio"
        assert bare == "llama-3.2-3b-instruct"


class TestCreateProvider:
    """Test create_provider() uses the provider override correctly."""

    def test_explicit_provider_routes_to_openrouter(self):
        """create_provider reads config.agents.defaults.provider to pick provider."""
        config = GripConfig(
            agents=AgentsConfig(
                defaults=AgentDefaults(
                    model="openai/gpt-oss-120b",
                    provider="openrouter",
                ),
            ),
            providers={
                "openrouter": ProviderEntry(
                    api_key="test-key",
                    api_base="https://openrouter.ai/api/v1",
                ),
            },
        )
        provider = create_provider(config)
        assert "OpenRouter" in provider.name

    def test_empty_provider_falls_back_to_prefix(self):
        """When provider='' (default), fall back to prefix-based resolution."""
        config = GripConfig(
            agents=AgentsConfig(
                defaults=AgentDefaults(
                    model="openai/gpt-4o",
                    provider="",
                ),
            ),
            providers={
                "openai": ProviderEntry(
                    api_key="test-key",
                    api_base="https://api.openai.com/v1",
                ),
            },
        )
        provider = create_provider(config)
        assert "OpenAI" in provider.name

    def test_local_provider_creates_openai_compat(self):
        """Ollama provider creates OpenAICompatProvider."""
        config = GripConfig(
            agents=AgentsConfig(
                defaults=AgentDefaults(
                    model="ollama/llama3.2",
                    provider="ollama",
                ),
            ),
        )
        provider = create_provider(config)
        assert "Ollama" in provider.name

    def test_ollama_local_has_http_base(self):
        """Regression for #7: Ollama (Local) must have a usable http:// base URL."""
        spec = ProviderRegistry.get_spec("ollama")
        assert spec.api_base.startswith("http://")
        assert "11434" in spec.api_base

    def test_lmstudio_local_has_http_base(self):
        spec = ProviderRegistry.get_spec("lmstudio")
        assert spec.api_base.startswith("http://")

    def test_ollama_no_entry_uses_spec_base(self):
        """#7: with no provider entry, ollama still gets a non-empty base URL."""
        config = GripConfig(
            agents=AgentsConfig(
                defaults=AgentDefaults(model="qwen2.5-coder:7b", provider="ollama")
            ),
        )
        provider = create_provider(config)
        assert provider._api_base.startswith("http://")

    def test_ollama_empty_configured_base_falls_back(self):
        """#7: even an explicitly blank api_base must not produce a scheme-less URL."""
        config = GripConfig(
            agents=AgentsConfig(defaults=AgentDefaults(model="qwen2.5", provider="ollama")),
            providers={"ollama": ProviderEntry(api_base="")},
        )
        provider = create_provider(config)
        assert provider._api_base.startswith("http://"), (
            "empty base should fall back to localhost, not crash httpx with UnsupportedProtocol"
        )

    def test_fallback_skips_model_without_key(self):
        """A fallback whose provider has no configured key is dropped, not sent unauthenticated."""
        config = GripConfig(
            agents=AgentsConfig(
                defaults=AgentDefaults(
                    model="anthropic/claude-sonnet-4-6",
                    fallback_models=["openai/gpt-4o-mini"],  # no openai key below
                ),
            ),
            providers={"anthropic": ProviderEntry(api_key="ak")},
        )
        provider = create_provider(config)
        assert provider._fallback_deployments == []
        assert provider.router is None  # no usable fallbacks → no Router

    def test_fallback_skips_local_provider(self):
        """Local providers aren't reliably routable via litellm.Router, so they're
        skipped (with a warning) rather than crashing Router construction."""
        config = GripConfig(
            agents=AgentsConfig(
                defaults=AgentDefaults(
                    model="anthropic/claude-sonnet-4-6",
                    fallback_models=["ollama/llama3.2"],
                ),
            ),
            providers={"anthropic": ProviderEntry(api_key="ak")},
        )
        provider = create_provider(config)  # must not raise
        assert provider._fallback_deployments == []
        assert provider.router is None

    def test_num_retries_forwarded_to_provider(self):
        config = GripConfig(
            agents=AgentsConfig(
                defaults=AgentDefaults(model="openai/gpt-4o", num_retries=4),
            ),
            providers={"openai": ProviderEntry(api_key="test-key")},
        )
        provider = create_provider(config)
        assert provider._num_retries == 4

    def test_fallback_models_build_router_deployments(self):
        config = GripConfig(
            agents=AgentsConfig(
                defaults=AgentDefaults(
                    model="anthropic/claude-sonnet-4-6",
                    fallback_models=["openai/gpt-4o-mini", "groq/llama-3.3-70b-versatile"],
                ),
            ),
            providers={
                "anthropic": ProviderEntry(api_key="ak"),
                "openai": ProviderEntry(api_key="ok"),
                "groq": ProviderEntry(api_key="gk"),
            },
        )
        provider = create_provider(config)
        # Two fallback deployments are built and the Router is active.
        assert len(provider._fallback_deployments) == 2
        assert provider.router is not None
        # Each deployment carries a routable model string and its own key.
        models = [d["model"] for d in provider._fallback_deployments]
        assert "openai/gpt-4o-mini" in models
        assert provider._fallback_deployments[0]["api_key"] == "ok"


class TestAgentDefaultsProvider:
    """Test the provider field on AgentDefaults."""

    def test_default_is_empty(self):
        defaults = AgentDefaults()
        assert defaults.provider == ""

    def test_provider_set(self):
        defaults = AgentDefaults(provider="openrouter")
        assert defaults.provider == "openrouter"

    def test_provider_in_config_dump(self):
        config = GripConfig(
            agents={"defaults": {"provider": "anthropic"}},
        )
        data = config.model_dump(mode="json")
        assert data["agents"]["defaults"]["provider"] == "anthropic"

    def test_provider_survives_round_trip(self, tmp_path):
        """Provider field persists through save/load cycle."""
        from grip.config import save_config

        config = GripConfig(
            agents=AgentsConfig(
                defaults=AgentDefaults(
                    model="openai/gpt-oss-120b",
                    provider="openrouter",
                ),
            ),
            providers={
                "openrouter": ProviderEntry(
                    api_key="test-key",
                    default_model="openai/gpt-oss-120b",
                ),
            },
        )
        path = tmp_path / "config.json"
        save_config(config, path)

        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["agents"]["defaults"]["provider"] == "openrouter"
