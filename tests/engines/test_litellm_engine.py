"""Tests for LiteLLMRunner — the EngineProtocol wrapper around AgentLoop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from grip.config.schema import GripConfig
from grip.engines.types import AgentRunResult, EngineProtocol, ToolCallDetail

# ---------------------------------------------------------------------------
# Helpers: lightweight fakes for the "old" AgentLoop result types so we can
# construct them without importing real provider machinery.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _FakeTokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(slots=True)
class _FakeOldToolCallDetail:
    name: str = ""
    success: bool = True
    duration_ms: float = 0.0
    output_preview: str = ""


@dataclass(slots=True)
class _FakeOldRunResult:
    """Mirrors grip.agent.loop.AgentRunResult (the OLD format)."""

    response: str = ""
    iterations: int = 0
    total_usage: _FakeTokenUsage = field(default_factory=_FakeTokenUsage)
    tool_calls_made: list[str] = field(default_factory=list)
    tool_details: list[_FakeOldToolCallDetail] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace with standard subdirectories."""
    ws = tmp_path / "workspace"
    for dirname in ("sessions", "memory", "skills", "cron", "hooks", "workflows", "state"):
        (ws / dirname).mkdir(parents=True)
    (ws / "AGENT.md").write_text("# Test Agent\nYou are a test agent.")
    (ws / "memory" / "MEMORY.md").write_text("")
    (ws / "memory" / "HISTORY.md").write_text("")
    return ws


@pytest.fixture
def config(tmp_workspace: Path) -> GripConfig:
    """Minimal test config with semantic_cache_enabled=False to skip cache creation."""
    return GripConfig(
        agents={"defaults": {"workspace": str(tmp_workspace), "semantic_cache_enabled": False}},
        tools={"restrict_to_workspace": True},
    )


@pytest.fixture
def config_with_cache(tmp_workspace: Path) -> GripConfig:
    """Config with semantic_cache_enabled=True to test cache branch."""
    return GripConfig(
        agents={"defaults": {"workspace": str(tmp_workspace), "semantic_cache_enabled": True}},
        tools={"restrict_to_workspace": True},
    )


@pytest.fixture
def mock_workspace(tmp_workspace: Path) -> MagicMock:
    ws = MagicMock()
    ws.root = tmp_workspace
    return ws


@pytest.fixture
def mock_session_mgr() -> MagicMock:
    mgr = MagicMock()
    mgr.get_or_create = MagicMock()
    mgr.delete = MagicMock(return_value=True)
    mgr.save = MagicMock()
    return mgr


@pytest.fixture
def mock_memory_mgr() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Patch targets — we mock out the heavy dependencies that LiteLLMRunner
# instantiates in its constructor so tests never touch real LLM providers,
# tool registries, or semantic caches.
# ---------------------------------------------------------------------------

_PATCH_CREATE_PROVIDER = "grip.engines.litellm_engine.create_provider"
_PATCH_CREATE_REGISTRY = "grip.engines.litellm_engine.create_default_registry"
_PATCH_SEMANTIC_CACHE = "grip.engines.litellm_engine.SemanticCache"
_PATCH_AGENT_LOOP = "grip.engines.litellm_engine.AgentLoop"


def _build_runner(config, mock_workspace, mock_session_mgr, mock_memory_mgr, trust_mgr=None):
    """Construct a LiteLLMRunner with all heavy deps mocked out."""
    from grip.engines.litellm_engine import LiteLLMRunner

    with (
        patch(_PATCH_CREATE_PROVIDER) as mock_cp,
        patch(_PATCH_CREATE_REGISTRY) as mock_cr,
        patch(_PATCH_AGENT_LOOP) as mock_al,
    ):
        mock_cp.return_value = MagicMock(name="fake_provider")
        mock_cr.return_value = MagicMock(name="fake_registry")
        mock_al.return_value = MagicMock(name="fake_loop")

        runner = LiteLLMRunner(
            config=config,
            workspace=mock_workspace,
            session_mgr=mock_session_mgr,
            memory_mgr=mock_memory_mgr,
            trust_mgr=trust_mgr,
        )
    return runner


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLiteLLMRunnerIsEngineProtocol:
    """LiteLLMRunner must satisfy the EngineProtocol ABC."""

    def test_is_subclass(self):
        from grip.engines.litellm_engine import LiteLLMRunner

        assert issubclass(LiteLLMRunner, EngineProtocol)

    def test_isinstance_check(self, config, mock_workspace, mock_session_mgr, mock_memory_mgr):
        runner = _build_runner(config, mock_workspace, mock_session_mgr, mock_memory_mgr)
        assert isinstance(runner, EngineProtocol)


class TestLiteLLMRunnerConstructor:
    """Constructor should wire up provider, registry, loop, and optional cache."""

    def test_creates_provider_and_registry(self, config, mock_workspace, mock_session_mgr, mock_memory_mgr):
        from grip.engines.litellm_engine import LiteLLMRunner

        with (
            patch(_PATCH_CREATE_PROVIDER) as mock_cp,
            patch(_PATCH_CREATE_REGISTRY) as mock_cr,
            patch(_PATCH_AGENT_LOOP) as mock_al,
        ):
            mock_cp.return_value = MagicMock(name="provider")
            mock_cr.return_value = MagicMock(name="registry")
            mock_al.return_value = MagicMock(name="loop")

            LiteLLMRunner(
                config=config,
                workspace=mock_workspace,
                session_mgr=mock_session_mgr,
                memory_mgr=mock_memory_mgr,
            )

            mock_cp.assert_called_once_with(config)
            mock_cr.assert_called_once_with(mcp_servers=config.tools.mcp_servers)

    def test_creates_agent_loop_with_correct_args(
        self, config, mock_workspace, mock_session_mgr, mock_memory_mgr
    ):
        from grip.engines.litellm_engine import LiteLLMRunner

        fake_provider = MagicMock(name="provider")
        fake_registry = MagicMock(name="registry")

        with (
            patch(_PATCH_CREATE_PROVIDER, return_value=fake_provider),
            patch(_PATCH_CREATE_REGISTRY, return_value=fake_registry),
            patch(_PATCH_AGENT_LOOP) as mock_al,
        ):
            mock_al.return_value = MagicMock(name="loop")

            LiteLLMRunner(
                config=config,
                workspace=mock_workspace,
                session_mgr=mock_session_mgr,
                memory_mgr=mock_memory_mgr,
            )

            mock_al.assert_called_once_with(
                config,
                fake_provider,
                mock_workspace,
                tool_registry=fake_registry,
                session_manager=mock_session_mgr,
                memory_manager=mock_memory_mgr,
                semantic_cache=None,
                trust_manager=None,
            )

    def test_creates_semantic_cache_when_enabled(
        self, config_with_cache, mock_workspace, mock_session_mgr, mock_memory_mgr
    ):
        from grip.engines.litellm_engine import LiteLLMRunner

        with (
            patch(_PATCH_CREATE_PROVIDER, return_value=MagicMock()),
            patch(_PATCH_CREATE_REGISTRY, return_value=MagicMock()),
            patch(_PATCH_SEMANTIC_CACHE) as mock_sc,
            patch(_PATCH_AGENT_LOOP) as mock_al,
        ):
            fake_cache = MagicMock(name="semantic_cache")
            mock_sc.return_value = fake_cache
            mock_al.return_value = MagicMock(name="loop")

            LiteLLMRunner(
                config=config_with_cache,
                workspace=mock_workspace,
                session_mgr=mock_session_mgr,
                memory_mgr=mock_memory_mgr,
            )

            mock_sc.assert_called_once()
            # The AgentLoop should have received the cache
            call_kwargs = mock_al.call_args.kwargs
            assert call_kwargs["semantic_cache"] is fake_cache

    def test_passes_trust_manager(self, config, mock_workspace, mock_session_mgr, mock_memory_mgr):
        from grip.engines.litellm_engine import LiteLLMRunner

        fake_trust = MagicMock(name="trust_mgr")

        with (
            patch(_PATCH_CREATE_PROVIDER, return_value=MagicMock()),
            patch(_PATCH_CREATE_REGISTRY, return_value=MagicMock()),
            patch(_PATCH_AGENT_LOOP) as mock_al,
        ):
            mock_al.return_value = MagicMock(name="loop")

            LiteLLMRunner(
                config=config,
                workspace=mock_workspace,
                session_mgr=mock_session_mgr,
                memory_mgr=mock_memory_mgr,
                trust_mgr=fake_trust,
            )

            call_kwargs = mock_al.call_args.kwargs
            assert call_kwargs["trust_manager"] is fake_trust


class TestLiteLLMRunnerProperties:
    """The loop and registry properties expose internals for legacy callers."""

    def test_loop_property(self, config, mock_workspace, mock_session_mgr, mock_memory_mgr):
        runner = _build_runner(config, mock_workspace, mock_session_mgr, mock_memory_mgr)
        assert runner.loop is not None

    def test_registry_property(self, config, mock_workspace, mock_session_mgr, mock_memory_mgr):
        runner = _build_runner(config, mock_workspace, mock_session_mgr, mock_memory_mgr)
        assert runner.registry is not None


class TestLiteLLMRunnerRun:
    """run() should delegate to AgentLoop.run() and translate the result."""

    @pytest.mark.asyncio
    async def test_run_delegates_to_loop(self, config, mock_workspace, mock_session_mgr, mock_memory_mgr):
        runner = _build_runner(config, mock_workspace, mock_session_mgr, mock_memory_mgr)

        old_result = _FakeOldRunResult(
            response="Hello from loop",
            iterations=3,
            total_usage=_FakeTokenUsage(prompt_tokens=100, completion_tokens=50),
            tool_calls_made=["read_file", "shell"],
            tool_details=[
                _FakeOldToolCallDetail(name="read_file", success=True, duration_ms=10.0, output_preview="content..."),
                _FakeOldToolCallDetail(name="shell", success=False, duration_ms=200.0, output_preview="error"),
            ],
        )

        runner.loop.run = AsyncMock(return_value=old_result)

        result = await runner.run("test message", session_key="test:session", model="gpt-4")

        runner.loop.run.assert_awaited_once_with(
            "test message", session_key="test:session", model="gpt-4"
        )

        assert isinstance(result, AgentRunResult)
        assert result.response == "Hello from loop"
        assert result.iterations == 3
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 50
        assert result.tool_calls_made == ["read_file", "shell"]
        assert len(result.tool_details) == 2

    @pytest.mark.asyncio
    async def test_run_translates_tool_details(self, config, mock_workspace, mock_session_mgr, mock_memory_mgr):
        runner = _build_runner(config, mock_workspace, mock_session_mgr, mock_memory_mgr)

        old_result = _FakeOldRunResult(
            response="done",
            iterations=1,
            total_usage=_FakeTokenUsage(prompt_tokens=50, completion_tokens=25),
            tool_calls_made=["web_search"],
            tool_details=[
                _FakeOldToolCallDetail(
                    name="web_search", success=True, duration_ms=500.5, output_preview="results..."
                ),
            ],
        )
        runner.loop.run = AsyncMock(return_value=old_result)

        result = await runner.run("search something")

        detail = result.tool_details[0]
        assert isinstance(detail, ToolCallDetail)
        assert detail.name == "web_search"
        assert detail.success is True
        assert detail.duration_ms == 500.5
        assert detail.output_preview == "results..."

    @pytest.mark.asyncio
    async def test_run_uses_default_kwargs(self, config, mock_workspace, mock_session_mgr, mock_memory_mgr):
        """run() with no explicit session_key or model passes the defaults through."""
        runner = _build_runner(config, mock_workspace, mock_session_mgr, mock_memory_mgr)

        old_result = _FakeOldRunResult(response="ok")
        runner.loop.run = AsyncMock(return_value=old_result)

        await runner.run("hi")

        runner.loop.run.assert_awaited_once_with(
            "hi", session_key="cli:default", model=None
        )

    @pytest.mark.asyncio
    async def test_run_with_zero_tokens(self, config, mock_workspace, mock_session_mgr, mock_memory_mgr):
        """When the old result has zero tokens, the new result should too."""
        runner = _build_runner(config, mock_workspace, mock_session_mgr, mock_memory_mgr)

        old_result = _FakeOldRunResult(
            response="cached",
            iterations=0,
            total_usage=_FakeTokenUsage(prompt_tokens=0, completion_tokens=0),
            tool_calls_made=[],
            tool_details=[],
        )
        runner.loop.run = AsyncMock(return_value=old_result)

        result = await runner.run("cached query")
        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0
        assert result.total_tokens == 0


class TestLiteLLMRunnerConsolidateSession:
    """consolidate_session() should look up the session and delegate to the loop."""

    @pytest.mark.asyncio
    async def test_consolidate_session_delegates(
        self, config, mock_workspace, mock_session_mgr, mock_memory_mgr
    ):
        runner = _build_runner(config, mock_workspace, mock_session_mgr, mock_memory_mgr)

        fake_session = MagicMock(name="session")
        mock_session_mgr.get_or_create.return_value = fake_session
        runner.loop.consolidate_session = AsyncMock()

        await runner.consolidate_session("test:session")

        mock_session_mgr.get_or_create.assert_called_once_with("test:session")
        runner.loop.consolidate_session.assert_awaited_once_with(fake_session)


class TestLiteLLMRunnerResetSession:
    """reset_session() should delegate to session_mgr.delete()."""

    @pytest.mark.asyncio
    async def test_reset_session_calls_delete(
        self, config, mock_workspace, mock_session_mgr, mock_memory_mgr
    ):
        runner = _build_runner(config, mock_workspace, mock_session_mgr, mock_memory_mgr)

        await runner.reset_session("test:session")

        mock_session_mgr.delete.assert_called_once_with("test:session")
