"""Pydantic configuration models for grip.

All config is loaded from ~/.grip/config.json and can be overridden
via GRIP_ prefixed environment variables.
"""

from __future__ import annotations

import platform as _platform
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.main import JsonConfigSettingsSource


def _detect_platform() -> str:
    """Return normalized platform identifier: darwin, linux, or windows."""
    return _platform.system().lower()


def _detect_arch() -> str:
    """Return CPU architecture: arm64, x86_64, etc."""
    machine = _platform.machine().lower()
    if machine in ("aarch64", "arm64"):
        return "arm64"
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    return machine


class PlatformInfo(BaseModel):
    """Auto-detected host platform information.

    Populated at config load time. Used by tools to select
    platform-appropriate commands (e.g., open vs xdg-open,
    brew vs apt).
    """

    os: str = Field(default_factory=_detect_platform)
    arch: str = Field(default_factory=_detect_arch)
    python_version: str = Field(default_factory=_platform.python_version)


class AgentDefaults(BaseModel):
    """Default agent parameters applied to every agent run unless overridden."""

    workspace: Path = Field(
        default=Path("~/.grip/workspace"),
        description="Root workspace directory for agent files, sessions, and memory.",
    )
    model: str = Field(
        default="openrouter/anthropic/claude-sonnet-4",
        description="Default LLM model identifier in provider/model format.",
    )
    provider: str = Field(
        default="",
        description="Explicit provider name (e.g. 'openrouter', 'anthropic'). "
        "When set, overrides prefix-based provider detection from the model string. "
        "Useful when model names contain ambiguous prefixes "
        "(e.g. 'openai/gpt-oss-120b' on OpenRouter).",
    )
    max_tokens: int = Field(
        default=8192,
        ge=1,
        le=200_000,
        description="Maximum tokens the LLM can generate per response.",
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature for LLM responses.",
    )
    max_tool_iterations: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum LLM-tool round-trips before the agent stops.",
    )
    memory_window: int = Field(
        default=50,
        ge=5,
        le=500,
        description="Number of recent messages to include in LLM context.",
    )
    auto_consolidate: bool = Field(
        default=True,
        description="Automatically consolidate old messages when session exceeds 2x memory_window.",
    )
    consolidation_model: str = Field(
        default="",
        description="LLM model for summarization/consolidation. Empty = use main model. "
        "Set to a cheaper model (e.g. openrouter/google/gemini-flash-2.0) to save tokens.",
    )
    enable_self_correction: bool = Field(
        default=True,
        description="When True, the agent reflects on failed tool calls before proceeding.",
    )
    semantic_cache_enabled: bool = Field(
        default=True,
        description="Cache LLM responses for identical queries to save tokens and latency.",
    )
    semantic_cache_ttl: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Time-to-live for cached responses in seconds (default: 1 hour).",
    )
    max_daily_tokens: int = Field(
        default=0,
        ge=0,
        description="Maximum total tokens (prompt+completion) per day. 0 = unlimited.",
    )
    dry_run: bool = Field(
        default=False,
        description="When True, tools simulate execution without writing files or running commands.",
    )


class ModelTiersConfig(BaseModel):
    """Model overrides per complexity tier for the cost-aware router.

    Leave a tier empty to use agents.defaults.model for that complexity
    level. Only tiers with a model set will be routed differently.
    Example: set low to a fast/cheap model like gemini-flash, leave
    medium empty (uses default), and set high to claude-opus.
    """

    enabled: bool = Field(
        default=False,
        description="Enable automatic model routing based on prompt complexity.",
    )
    low: str = Field(
        default="",
        description="Model for simple queries (greetings, lookups, regex).",
    )
    medium: str = Field(
        default="",
        description="Model for moderate tasks (code changes, explanations).",
    )
    high: str = Field(
        default="",
        description="Model for complex tasks (architecture, refactors, debugging).",
    )


class ProviderEntry(BaseModel):
    """Connection details for a single LLM provider."""

    api_key: str = ""
    api_base: str = ""
    default_model: str = ""


class ChannelEntry(BaseModel):
    """Configuration for a single chat channel."""

    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(
        default_factory=list,
        description="User IDs allowed to interact. Empty list allows everyone.",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Channel-specific settings (bot_token, app_token, webhook_port, etc.).",
    )


class ChannelsConfig(BaseModel):
    """Top-level container for all chat channel configurations."""

    telegram: ChannelEntry = Field(default_factory=ChannelEntry)
    discord: ChannelEntry = Field(default_factory=ChannelEntry)
    slack: ChannelEntry = Field(default_factory=ChannelEntry)


class WebSearchProvider(BaseModel):
    """Configuration for a single web search backend."""

    enabled: bool = False
    api_key: str = ""
    max_results: int = Field(default=5, ge=1, le=20)


class WebSearchConfig(BaseModel):
    """Web search tool configuration with multiple backends."""

    brave: WebSearchProvider = Field(default_factory=WebSearchProvider)
    duckduckgo: WebSearchProvider = Field(default_factory=lambda: WebSearchProvider(enabled=True))
    perplexity: WebSearchProvider = Field(default_factory=WebSearchProvider)


class MCPServerConfig(BaseModel):
    """MCP server connection definition (stdio or HTTP transport)."""

    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)


class ToolsConfig(BaseModel):
    """Global tool settings."""

    web: WebSearchConfig = Field(default_factory=WebSearchConfig)
    shell_timeout: int = Field(
        default=60,
        ge=1,
        le=600,
        description="Default shell command timeout in seconds.",
    )
    restrict_to_workspace: bool = Field(
        default=False,
        description="When True, file tools are sandboxed to the workspace directory. "
        "When False, file tools can read/write anywhere the OS user has permissions.",
    )
    trust_mode: str = Field(
        default="prompt",
        description="Directory trust mode for file access outside workspace. "
        "'prompt' = ask before accessing new directories (default), "
        "'trust_all' = access any directory without prompting, "
        "'workspace_only' = same as restrict_to_workspace=True.",
    )
    mcp_servers: dict[str, MCPServerConfig] = Field(
        default_factory=dict,
        description="Named MCP server definitions (stdio or HTTP).",
    )


class HeartbeatConfig(BaseModel):
    """Periodic autonomous wake-up settings.

    Each heartbeat triggers a full agent loop run which consumes tokens
    (typically 2-5K per run depending on context size). Set the interval
    appropriately to avoid unnecessary token spend.
    """

    enabled: bool = False
    interval_minutes: int = Field(
        default=30,
        ge=5,
        le=1440,
        description="Minutes between heartbeat runs. Minimum 5 to prevent excessive token usage.",
    )


class CronConfig(BaseModel):
    """Scheduled task execution settings."""

    exec_timeout_minutes: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Maximum runtime per cron job execution.",
    )


class APIConfig(BaseModel):
    """REST API security and rate limiting settings.

    auth_token is auto-generated on first API startup if left empty.
    The grip_ prefix makes tokens detectable by _mask_secrets().
    enable_tool_execute is disabled by default because it allows
    arbitrary tool invocation (including shell) over HTTP.
    """

    auth_token: str = ""
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10000)
    rate_limit_per_minute_per_ip: int = Field(default=30, ge=1, le=10000)
    cors_allowed_origins: list[str] = Field(default_factory=list)
    max_request_body_bytes: int = Field(default=1_048_576, ge=1024, le=52_428_800)
    enable_tool_execute: bool = False


class GatewayConfig(BaseModel):
    """Network settings for the gateway (API server + channels)."""

    host: str = "127.0.0.1"
    port: int = Field(default=18800, ge=1024, le=65535)
    api: APIConfig = Field(default_factory=APIConfig)


class AgentProfile(BaseModel):
    """Named agent profile with its own model, tool subset, and system prompt.

    Profiles let you configure specialized agents (e.g. a "researcher" that
    uses a cheaper model with only web tools, or a "coder" with shell access).
    Fields left empty inherit from agents.defaults at runtime.
    """

    model: str = ""
    max_tokens: int = 0
    temperature: float = -1.0
    max_tool_iterations: int = 0
    tools_allowed: list[str] = Field(
        default_factory=list,
        description="Tool names this profile can use. Empty = all tools.",
    )
    tools_denied: list[str] = Field(
        default_factory=list,
        description="Tool names explicitly blocked for this profile.",
    )
    system_prompt_file: str = Field(
        default="",
        description="Workspace-relative path to a custom identity file (e.g. 'agents/researcher.md').",
    )


class AgentsConfig(BaseModel):
    """Agent configuration section with default settings and named profiles."""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)
    model_tiers: ModelTiersConfig = Field(default_factory=ModelTiersConfig)
    profiles: dict[str, AgentProfile] = Field(
        default_factory=dict,
        description="Named agent profiles. Each profile can override model, tools, and system prompt.",
    )


class GripConfig(BaseSettings):
    """Root configuration for the entire grip platform.

    Loaded from ~/.grip/config.json with GRIP_ env var overrides.
    Uses JsonConfigSettingsSource so pydantic-settings reads the JSON file
    and merges it with environment variable overrides.
    """

    model_config = SettingsConfigDict(
        env_prefix="GRIP_",
        env_nested_delimiter="__",
        json_file=Path("~/.grip/config.json").expanduser(),
        json_file_encoding="utf-8",
        extra="ignore",
    )

    platform: PlatformInfo = Field(default_factory=PlatformInfo)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    providers: dict[str, ProviderEntry] = Field(default_factory=dict)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    cron: CronConfig = Field(default_factory=CronConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):
        """Enable JSON file loading alongside env vars and init kwargs."""
        return (
            kwargs.get("init_settings"),
            kwargs.get("env_settings"),
            JsonConfigSettingsSource(settings_cls),
        )
