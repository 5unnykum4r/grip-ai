# Changelog

All notable changes to grip are documented here. This project follows
[Semantic Versioning](https://semver.org/). Versions prior to 1.6.0 are
recorded in the git history and release tags.

## [1.6.0] - 2026-05-29

### Added
- **Real cross-provider fallback** via `litellm.Router`. Configure an ordered
  `fallback_models` chain; each fallback carries its own resolved API key
  (credentials never touch `os.environ`). Local and keyless providers are
  skipped from the chain with a warning instead of failing the run.
- **Automatic retries** with exponential backoff on every LiteLLM call via the
  `num_retries` config field (default 2).
- **Per-call USD cost tracking** — a LiteLLM success callback records
  `response_cost` into the daily `TokenTracker`; surfaced as `cost_usd` in
  status output (LiteLLM engine path).
- **Unified tool surface across engines** — grip's built-in tool registry is
  bridged into the Claude Agent SDK engine as in-process MCP tools. Categories
  the SDK covers natively (filesystem, shell, orchestration, messaging) are
  skipped; configurable via `sdk_expose_grip_tools` and
  `sdk_tool_skip_categories`.
- **Onboarding key verification + live model loading** — for cloud providers,
  `grip onboard` now verifies the API key and fetches the provider's live model
  catalogue (OpenRouter is verified against its authenticated `/key` endpoint
  since `/models` is public). Falls back to the curated list when offline.

### Fixed
- **#7**: Ollama (Local) / LM Studio crashed with
  `httpx.UnsupportedProtocol` because their `api_base` resolved to empty. Local
  providers now have sensible localhost defaults, `create_provider` falls back
  to a localhost base if blank, and onboarding prompts for / persists the local
  server URL.
- Onboarding wizard routed cloud providers to the no-key "API base URL" branch,
  skipping key entry, verification, and model fetching. Restored the
  cloud-provider API-key branch.
- Slim interactive output: routine INFO logs (tool calls, LLM requests, loop
  iterations) now go to `~/.grip/logs/grip.log` instead of the chat UI. Use
  `grip -v agent` to surface them on the console.
- Silenced LiteLLM's import-time bedrock/sagemaker pre-load warnings.

### Changed
- Test suite grew from 826 to 882 tests covering the above.
