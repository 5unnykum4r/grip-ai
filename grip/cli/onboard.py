"""grip onboard -- interactive setup wizard with arrow-key selection.

Walks the user through provider selection, API key entry, model choice,
workspace initialization, and automatic connectivity verification.
"""

from __future__ import annotations

import asyncio
import platform

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from grip.config import GripConfig, save_config
from grip.config.schema import (
    AgentDefaults,
    AgentsConfig,
    ChannelEntry,
    ChannelsConfig,
    ProviderEntry,
    SearchConfig,
    ToolsConfig,
)
from grip.providers.registry import ProviderRegistry, create_provider
from grip.providers.types import LLMMessage
from grip.workspace import WorkspaceManager

console = Console()

_CLOUD_PROVIDERS = [
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

_LOCAL_SUBMENU = ["ollama", "llamacpp", "lmstudio"]

_BANNER = r"""
██████╗ ██████╗ ██╗██████╗
██╔════╝ ██╔══██╗██║██╔══██╗
██║  ███╗██████╔╝██║██████╔╝
██║   ██║██╔══██╗██║██╔═══╝
╚██████╔╝██║  ██║██║██║
 ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝
"""


def _print_header() -> None:
    console.print()
    console.print(_BANNER, style="bold cyan")
    console.print()
    console.print(
        "[bold cyan]Your AI Agent Platform[/bold cyan]\n\n"
        "• Claude Agent SDK (recommended) + multi-provider LLM support (OpenAI, Anthropic, Ollama, and more)\n"
        "• Tool calling & function execution\n"
        "• Multi-channel integration (Telegram, Discord, Slack)\n"
        "• Cron jobs & scheduled automation\n"
        "• MCP server support"
    )
    console.print()


def _print_step(step: int, total: int, title: str) -> None:
    console.print()
    console.print("  [bold cyan]━[/bold cyan] " * 20)
    console.print()
    console.print(f"  [bold cyan]Step {step}/{total}:[/bold cyan] {title}")
    console.print()


def _build_provider_choices() -> list[Choice]:
    """Build the InquirerPy choice list for provider selection.

    The Claude Agent SDK option is placed first as the recommended default.
    Cloud providers from _CLOUD_PROVIDERS follow, then local options at the end.
    """
    choices: list[Choice] = [
        Choice(value="_claude_sdk", name="  Anthropic — Claude Agent SDK (Recommended)"),
    ]
    for name in _CLOUD_PROVIDERS:
        spec = ProviderRegistry.get_spec(name)
        if spec:
            choices.append(Choice(value=spec.name, name=f"  {spec.display_name}"))

    choices.append(Choice(value="_local_ollama", name="  Ollama (Local)"))
    choices.append(Choice(value="_local_other", name="  Other Models (Local / OpenAI Compatible)"))
    return choices


def _build_local_choices() -> list[Choice]:
    """Build sub-menu choices for local model providers."""
    return [
        Choice(value="ollama", name="  Ollama"),
        Choice(value="llamacpp", name="  Llama.cpp"),
        Choice(value="lmstudio", name="  LM Studio"),
        Choice(value="_custom_openai", name="  Others (OpenAI Compatible)"),
    ]


def _select_provider() -> tuple[str, bool]:
    """Run the provider selection prompt.

    Returns (provider_name, is_custom).
    Special value "_claude_sdk" signals that the Claude Agent SDK path was chosen.
    """
    choices = _build_provider_choices()
    selected = inquirer.select(  # type: ignore[attr-defined]
        message="Choose your LLM provider:",
        choices=choices,
        default="_claude_sdk",
        pointer=">",
    ).execute()

    if selected == "_claude_sdk":
        return "_claude_sdk", False

    if selected == "_local_ollama":
        return "ollama", False

    if selected == "_local_other":
        local_choices = _build_local_choices()
        local_selected = inquirer.select(
            message="Choose local model type:",
            choices=local_choices,
            pointer=">",
        ).execute()
        if local_selected == "_custom_openai":
            return "", True
        return local_selected, False

    return selected, False


def _ask_linux_user() -> None:
    """On Linux, offer to create a dedicated grip user."""
    if platform.system().lower() != "linux":
        return

    create_user = inquirer.confirm(
        message="Create a dedicated 'grip' user for running the agent?",
        default=False,
    ).execute()

    if create_user:
        console.print(
            "\n[dim]Run these commands to create the user:[/dim]\n"
            "  [cyan]sudo useradd -m -s /bin/bash grip[/cyan]\n"
            "  [cyan]sudo su - grip[/cyan]\n"
            "  [cyan]grip onboard[/cyan]\n"
        )
        console.print(
            "[yellow]Please create the user manually and re-run onboard as that user.[/yellow]"
        )
        return


def _auto_test_connection(config: GripConfig, full_model: str) -> bool:
    """Automatically test chat and tool calling. Returns True on success."""
    import warnings

    warnings.filterwarnings("ignore", category=RuntimeWarning)

    from loguru import logger

    logger.disable("grip")
    logger.disable("litellm")

    console.print("\n")
    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Testing connection...", total=None)

        try:
            provider = create_provider(config)

            progress.update(task, description="[cyan]Testing chat completion...")
            asyncio.run(
                provider.chat(
                    [LLMMessage(role="user", content="Say 'grip ready!' in 3 words or less.")],
                    model=full_model,
                    max_tokens=20,
                    temperature=0.0,
                )
            )

            progress.update(task, description="[cyan]Testing tool calling...")
            tool_def = [
                {
                    "type": "function",
                    "function": {
                        "name": "get_current_time",
                        "description": "Get the current date and time",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                }
            ]
            asyncio.run(
                provider.chat(
                    [LLMMessage(role="user", content="What time is it right now?")],
                    model=full_model,
                    tools=tool_def,
                    max_tokens=100,
                    temperature=0.0,
                )
            )

            progress.update(task, description="[green]✓ All tests passed!", completed=True)
            return True

        except Exception as exc:
            progress.update(task, description="[red]✗ Connection failed!", completed=True)
            console.print()
            console.print(
                Panel(
                    f"[red]{exc}[/red]",
                    title="Connection Error",
                    border_style="red",
                    expand=False,
                )
            )
            return False
        finally:
            logger.enable("grip")
            logger.enable("litellm")


def _auto_pull_ollama_embedding(model_name: str = "nomic-embed-text") -> None:
    """Offer to pull an Ollama embedding model during onboarding."""
    import subprocess

    pull = inquirer.confirm(
        message=f"Pull {model_name} now?",
        default=True,
    ).execute()
    if not pull:
        console.print(
            f"  [dim]Skipped. Run manually before first use:[/dim]\n"
            f"    [cyan]ollama pull {model_name}[/cyan]"
        )
        return

    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"[cyan]Pulling {model_name}...", total=None)
        try:
            result = subprocess.run(
                ["ollama", "pull", model_name],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode == 0:
                progress.update(task, description=f"[green]✓ {model_name} ready!", completed=True)
            else:
                progress.update(task, description="[red]✗ Pull failed", completed=True)
                console.print(f"  [dim]{result.stderr.strip()}[/dim]")
                console.print(f"  [dim]Run manually: ollama pull {model_name}[/dim]")
        except FileNotFoundError:
            progress.update(task, description="[red]✗ Ollama not found", completed=True)
            console.print("  [dim]Install Ollama first: https://ollama.com[/dim]")
        except subprocess.TimeoutExpired:
            progress.update(task, description="[red]✗ Pull timed out", completed=True)
            console.print(f"  [dim]Run manually: ollama pull {model_name}[/dim]")


_SDK_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "claude-opus-4-5",
    "claude-sonnet-4-5",
]

# Providers that have a native embedding endpoint.
# Maps provider name → (default litellm model string, dimensions).
_EMBEDDING_MODELS: dict[str, tuple[str, int]] = {
    "openrouter": ("openrouter/openai/text-embedding-3-small", 1536),
    "openai": ("openai/text-embedding-3-small", 1536),
    "ollama": ("ollama/nomic-embed-text", 768),
    "ollama_cloud": ("ollama_cloud/nomic-embed-text", 768),
}

# Available embedding model choices per provider (model_id, dims, label).
_EMBEDDING_CHOICES: dict[str, list[tuple[str, int, str]]] = {
    "openrouter": [
        (
            "openrouter/openai/text-embedding-3-small",
            1536,
            "text-embedding-3-small — best value ($0.02/1M tokens)",
        ),
        (
            "openrouter/openai/text-embedding-3-large",
            3072,
            "text-embedding-3-large — highest quality ($0.13/1M tokens)",
        ),
    ],
    "openai": [
        (
            "openai/text-embedding-3-small",
            1536,
            "text-embedding-3-small — best value ($0.02/1M tokens)",
        ),
        (
            "openai/text-embedding-3-large",
            3072,
            "text-embedding-3-large — highest quality ($0.13/1M tokens)",
        ),
    ],
    "ollama": [
        ("ollama/nomic-embed-text", 768, "nomic-embed-text — 768 dims (free, local)"),
        ("ollama/mxbai-embed-large", 1024, "mxbai-embed-large — 1024 dims (free, local)"),
        ("ollama/all-minilm", 384, "all-minilm — 384 dims, fastest (free, local)"),
    ],
    "ollama_cloud": [
        ("ollama_cloud/nomic-embed-text", 768, "nomic-embed-text — 768 dims"),
        ("ollama_cloud/mxbai-embed-large", 1024, "mxbai-embed-large — 1024 dims"),
    ],
}


def _auto_test_sdk_connection(api_key: str, model: str) -> bool:
    """Test Claude Agent SDK connection.

    Tries the SDK first. If the SDK package is not installed, falls back to
    testing via LiteLLM with the same API key and model to verify the key works.
    """
    import os

    os.environ["ANTHROPIC_API_KEY"] = api_key

    console.print("\n")
    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Testing SDK connection...", total=None)

        try:
            try:
                from claude_agent_sdk import ClaudeAgentOptions, query

                async def _test():
                    async for _ in query(
                        prompt="Say 'ready' in one word.",
                        options=ClaudeAgentOptions(
                            model=model,
                            allowed_tools=[],
                            permission_mode="acceptEdits",
                        ),
                    ):
                        pass

                asyncio.run(_test())
                progress.update(task, description="[green]SDK connection OK!", completed=True)
                return True
            except ImportError:
                # SDK not installed -- verify the API key via LiteLLM instead
                progress.update(
                    task, description="[cyan]SDK not installed, testing key via LiteLLM..."
                )
                from grip.providers.litellm_provider import LiteLLMProvider

                provider = LiteLLMProvider(
                    provider_name="Anthropic",
                    model_prefix="anthropic",
                    api_key=api_key,
                    api_base="https://api.anthropic.com/v1",
                    default_model=model,
                )
                asyncio.run(
                    provider.chat(
                        [LLMMessage(role="user", content="Say 'ready'")],
                        model=f"anthropic/{model}",
                        max_tokens=20,
                        temperature=0.0,
                    )
                )
                progress.update(
                    task,
                    description="[green]API key verified (SDK will be used at runtime)!",
                    completed=True,
                )
                return True
        except Exception as exc:
            progress.update(task, description="[red]Connection failed!", completed=True)
            console.print()
            console.print(
                Panel(
                    f"[red]{exc}[/red]",
                    title="Connection Error",
                    border_style="red",
                    expand=False,
                )
            )
            return False


def _handle_test_failure() -> str:
    """Show retry options after a failed connection test. Returns chosen action."""
    return inquirer.select(
        message="What would you like to do?",
        choices=[
            Choice(value="retry", name="  Test again"),
            Choice(value="restart", name="  Setup again (restart wizard)"),
        ],
        pointer=">",
    ).execute()


def onboard_command() -> None:
    """Interactive setup wizard for grip.

    Delegates to _run_onboard_wizard() in a loop so that "restart wizard"
    re-runs without recursive calls (which would blow the stack after
    enough retries).
    """
    while True:
        if not _run_onboard_wizard():
            return


def _run_onboard_wizard() -> bool:
    """Single pass of the onboard wizard. Returns True to restart, False when done."""
    console.clear()
    _print_header()

    console.print(
        Panel(
            "[bold yellow]DISCLAIMER[/bold yellow]\n\n"
            "grip is an AI agent that can execute shell commands, read/write files,\n"
            "and modify your system based on AI-generated decisions. While safety\n"
            "guards are in place (dangerous command blocking, delete-to-trash, etc.),\n"
            "[bold]no AI system is infallible[/bold].\n\n"
            "[bold]Recommendations:[/bold]\n"
            "  - Do NOT run as root\n"
            "  - Keep backups of important data\n"
            "  - Use [cyan]--dry-run[/cyan] mode when testing\n"
            "  - Review actions before critical operations\n\n"
            "[dim]By continuing, you acknowledge that you use grip at your own risk.[/dim]",
            border_style="yellow",
            expand=False,
        )
    )

    continue_setup = inquirer.confirm(
        message="Continue with setup?",
        default=True,
    ).execute()
    if not continue_setup:
        console.print(
            "\n[dim]👋 Setup cancelled. Run [cyan]grip onboard[/cyan] anytime to set up.[/dim]"
        )
        return False
    console.print("[dim]Great! Let's get you set up...[/dim]")

    _ask_linux_user()

    # ── Track which engine the user chose: "claude_sdk" or "litellm" ──
    use_sdk = False
    selected_spec = None

    console.print()
    _print_step(1, 7, "Choose your LLM provider")
    provider_name, is_custom = _select_provider()

    if provider_name == "_claude_sdk":
        # ── Claude Agent SDK path ──────────────────────────────────────
        use_sdk = True

        _print_step(2, 7, "Configure API key")
        console.print(
            Panel(
                "Enter your [bold cyan]Anthropic[/bold cyan] API key\n"
                "[dim]Environment variable: ANTHROPIC_API_KEY[/dim]",
                border_style="cyan",
                expand=False,
            )
        )
        while True:
            api_key = inquirer.secret(
                message="API key:",
                default="",
            ).execute()
            if not api_key.strip():
                console.print("[red]API key is required. Please enter a valid key.[/red]")
                continue
            break

        _print_step(3, 7, "Choose a Claude model")
        sdk_model_choices = [Choice(value=m, name=f"  {m}") for m in _SDK_MODELS]
        sdk_model = inquirer.select(
            message="Select Claude model:",
            choices=sdk_model_choices,
            default="claude-sonnet-4-6",
            pointer=">",
        ).execute()

        provider_name = "anthropic"
        full_model = sdk_model
        bare_model = sdk_model
        api_base = ""

        console.print()
        console.print(
            Panel(
                "[bold green]✓ Engine:[/bold green] Claude Agent SDK\n"
                f"[bold green]✓ Model:[/bold green] {sdk_model}",
                border_style="green",
                expand=False,
            )
        )

    elif is_custom:
        # ── Custom OpenAI-compatible provider path ─────────────────────
        while True:
            api_base = inquirer.text(
                message="Enter API base URL:",
                default="http://localhost:8080/v1",
            ).execute()
            if not api_base.strip():
                console.print("[red]API base URL is required. Please enter a valid URL.[/red]")
                continue
            break

        while True:
            bare_model = inquirer.text(
                message="Enter model name:",
            ).execute()
            if not bare_model.strip():
                console.print("[red]Model name is required. Please enter a valid model name.[/red]")
                continue
            break

        api_key = inquirer.secret(
            message="Enter API key (or press Enter if none needed):",
            default="",
        ).execute()
        selected_spec = ProviderRegistry.get_spec("vllm")
        provider_name = "vllm"
        full_model = bare_model

        console.print()
        console.print(
            Panel(
                f"[bold green]✓ Provider:[/bold green] {selected_spec.display_name if selected_spec else provider_name}\n"
                f"[bold green]✓ Model:[/bold green] {full_model}",
                border_style="green",
                expand=False,
            )
        )
    else:
        # ── Standard LiteLLM provider path ─────────────────────────────
        selected_spec = ProviderRegistry.get_spec(provider_name)
        if not selected_spec:
            console.print("[red]Provider not found. Using OpenRouter as default.[/red]")
            selected_spec = ProviderRegistry.get_spec("openrouter")
            provider_name = "openrouter"

        _print_step(2, 7, "Configure API key & Endpoint")
        api_key = ""
        api_base = selected_spec.api_base if selected_spec else ""

        local_providers = ["ollama", "llamacpp", "lmstudio"]
        is_local = provider_name in local_providers

        if is_local:
            console.print()
            spec_name = selected_spec.display_name if selected_spec else provider_name
            console.print(f"  [dim]{spec_name} is a local model - no API key needed.[/dim]")
        elif selected_spec and selected_spec.api_key_env:
            while True:
                console.print(
                    Panel(
                        f"Enter your [bold cyan]{selected_spec.display_name}[/bold cyan] API key\n"
                        f"[dim]Environment variable: {selected_spec.api_key_env}[/dim]",
                        border_style="cyan",
                        expand=False,
                    )
                )
                api_key = inquirer.secret(
                    message="API key:",
                    default="",
                ).execute()

                if not api_key.strip():
                    console.print("[red]API key is required. Please enter a valid key.[/red]")
                    continue

                break
        elif selected_spec:
            custom_base = inquirer.text(
                message="API base URL (Enter to keep default):",
                default=selected_spec.api_base or "",
            ).execute()
            if custom_base.strip():
                api_base = custom_base.strip()

        _print_step(3, 7, "Choose a default model")

        if selected_spec and selected_spec.default_models:
            model_choices = [Choice(value=m, name=m) for m in selected_spec.default_models]
            model_choices.append(Choice(value="_custom", name="Enter custom model name..."))

            model_selected = inquirer.fuzzy(  # type: ignore[attr-defined]
                message="Search or select model:",
                choices=model_choices,
                pointer=">",
            ).execute()

            if model_selected == "_custom":
                while True:
                    bare_model = inquirer.text(  # type: ignore[attr-defined]
                        message="Enter model name:",
                    ).execute()
                    if not bare_model.strip():
                        console.print(
                            "[red]Model name is required. Please enter a valid model name.[/red]"
                        )
                        continue
                    break
            else:
                bare_model = model_selected
        else:
            while True:
                bare_model = inquirer.text(  # type: ignore[attr-defined]
                    message="Enter model name:",
                ).execute()
                if not bare_model.strip():
                    console.print(
                        "[red]Model name is required. Please enter a valid model name.[/red]"
                    )
                    continue
                break

        full_model = bare_model

        console.print()
        console.print(
            Panel(
                f"[bold green]✓ Provider:[/bold green] {selected_spec.display_name if selected_spec else provider_name}\n"
                f"[bold green]✓ Model:[/bold green] {full_model}",
                border_style="green",
                expand=False,
            )
        )

    # Build providers_dict early so the embedding step can check existing keys.
    providers_dict: dict[str, ProviderEntry] = {}

    # ── Step 4: Embedding model for hybrid search ────────────────────
    _print_step(4, 7, "Configure memory search")

    # Determine which provider will serve embeddings.
    # If the user's chat provider has a known embedding model, use it.
    # Otherwise offer OpenRouter (most common) or BM25-only.
    emb_provider = provider_name if not use_sdk else "anthropic"
    search_cfg = SearchConfig()  # defaults
    extra_emb_provider: tuple[str, ProviderEntry] | None = None

    if emb_provider in _EMBEDDING_MODELS:
        is_ollama_provider = emb_provider in ("ollama", "ollama_cloud")

        if is_ollama_provider:
            cost_line = "Cost: [green]Free (runs locally)[/green]"
        else:
            cost_line = "Cost: ~$0.02 per 1M tokens (very cheap)"

        console.print(
            Panel(
                f"Hybrid search uses a small embedding model for semantic matching.\n"
                f"Your provider ({emb_provider}) supports embeddings natively.\n\n"
                f"  {cost_line}",
                border_style="cyan",
                expand=False,
            )
        )
        use_hybrid = inquirer.confirm(
            message="Enable hybrid search (BM25 + vector)?",
            default=True,
        ).execute()
        if use_hybrid:
            # Let the user pick an embedding model if there are choices
            choices = _EMBEDDING_CHOICES.get(emb_provider, [])
            if len(choices) > 1:
                emb_model_choices = [
                    Choice(value=(model_id, dims), name=f"  {label}")
                    for model_id, dims, label in choices
                ]
                selected_emb = inquirer.select(
                    message="Choose embedding model:",
                    choices=emb_model_choices,
                    default=emb_model_choices[0].value,
                    pointer=">",
                ).execute()
                chosen_model, chosen_dims = selected_emb
            else:
                chosen_model, chosen_dims = _EMBEDDING_MODELS[emb_provider]

            if is_ollama_provider:
                # Extract bare model name for the pull command
                pull_model = chosen_model.split("/", 1)[-1] if "/" in chosen_model else chosen_model
                _auto_pull_ollama_embedding(pull_model)

            search_cfg = SearchConfig(
                enabled=True,
                embedding_model=chosen_model,
                embedding_dimensions=chosen_dims,
            )
            console.print(f"  [bold green]✓ Hybrid search enabled ({chosen_model})[/bold green]")
        else:
            search_cfg = SearchConfig(enabled=False)
            console.print("  [dim]Using keyword search only (BM25)[/dim]")
    else:
        # Provider has no embedding endpoint (Anthropic, DeepSeek, Groq, etc.)
        console.print(
            Panel(
                f"Hybrid search uses a small embedding model for semantic matching.\n"
                f"Your chat provider ({emb_provider}) doesn't have an embedding endpoint.\n\n"
                "Options:\n"
                "  1. Use [cyan]OpenRouter[/cyan] for embeddings (needs API key, ~$0.02/1M tokens)\n"
                "  2. Use keyword search only (BM25, no API key needed)",
                border_style="cyan",
                expand=False,
            )
        )
        emb_choice = inquirer.select(
            message="Choose search mode:",
            choices=[
                Choice(value="openrouter", name="  OpenRouter embeddings (recommended)"),
                Choice(value="bm25_only", name="  Keyword search only (no extra key)"),
            ],
            default="openrouter",
            pointer=">",
        ).execute()

        if emb_choice == "openrouter":
            # Check if the user already has an OpenRouter key in providers_dict
            existing_or_key = ""
            if "openrouter" in providers_dict:
                existing_or_key = providers_dict["openrouter"].api_key.get_secret_value()

            if existing_or_key:
                console.print("  [dim]Using your existing OpenRouter API key for embeddings.[/dim]")
            else:
                console.print("\n  [dim]Get a key at: https://openrouter.ai/keys[/dim]")
                while True:
                    emb_api_key = inquirer.secret(
                        message="OpenRouter API key for embeddings:",
                        default="",
                    ).execute()
                    if not emb_api_key.strip():
                        console.print("[red]API key is required for embeddings.[/red]")
                        continue
                    break
                extra_emb_provider = (
                    "openrouter",
                    ProviderEntry(api_key=emb_api_key.strip()),
                )

            # Let user choose embedding model
            or_choices = _EMBEDDING_CHOICES["openrouter"]
            emb_model_choices = [
                Choice(value=(model_id, dims), name=f"  {label}")
                for model_id, dims, label in or_choices
            ]
            selected_emb = inquirer.select(
                message="Choose embedding model:",
                choices=emb_model_choices,
                default=emb_model_choices[0].value,
                pointer=">",
            ).execute()
            chosen_model, chosen_dims = selected_emb

            search_cfg = SearchConfig(
                enabled=True,
                embedding_model=chosen_model,
                embedding_dimensions=chosen_dims,
            )
            console.print(
                f"  [bold green]✓ Hybrid search enabled via OpenRouter ({chosen_model})[/bold green]"
            )
        else:
            search_cfg = SearchConfig(enabled=False)
            console.print("  [dim]Using keyword search only (BM25)[/dim]")

    # ── Step 5: Telegram ───────────────────────────────────────────────
    _print_step(5, 7, "Connect Telegram bot")
    console.print(
        Panel(
            "Chat with your AI agent directly from Telegram\n\n"
            "To create a bot:\n"
            "  1. Open Telegram -> search [cyan]@BotFather[/cyan]\n"
            "  2. Send [yellow]/newbot[/yellow] and follow instructions\n"
            "  3. Copy your bot token\n"
            "  4. Message [cyan]@userinfobot[/cyan] to get your user ID",
            border_style="blue",
            expand=False,
        )
    )

    channels_config = ChannelsConfig()
    telegram_allow_from: list[str] = []

    setup_telegram = inquirer.confirm(
        message="Set up Telegram now?",
        default=True,
    ).execute()

    if setup_telegram:
        while True:
            bot_token = inquirer.secret(
                message="Bot token:",
                default="",
            ).execute()
            if not bot_token.strip():
                console.print(
                    "[red]Bot token is required. Please enter your Telegram bot token.[/red]"
                )
                continue
            break

        while True:
            user_id = inquirer.text(
                message="Your Telegram user ID:",
                default="",
            ).execute()
            if not user_id.strip():
                console.print(
                    "[red]User ID is required for security. Only you will be able to use the bot.[/red]"
                )
                continue
            break

        telegram_allow_from = [user_id.strip()]

        channels_config = ChannelsConfig(
            telegram=ChannelEntry(
                enabled=True,
                token=bot_token.strip(),
                allow_from=telegram_allow_from,
            ),
        )
        console.print("  [bold green]✓ Telegram configured![/bold green]")
    else:
        console.print("  [dim]Skipped. Set up later with:[/dim]")
        console.print("    [cyan]grip config set channels.telegram.enabled true[/cyan]")

    # ── Step 5: File access mode ───────────────────────────────────────
    _print_step(6, 7, "Configure file access mode")

    access_mode = inquirer.select(
        message="Choose file access mode:",
        choices=[
            Choice(
                value="prompt",
                name="  Ask before accessing (recommended)",
            ),
            Choice(
                value="trust_all",
                name="  Trust all directories",
            ),
            Choice(
                value="workspace_only",
                name="  Workspace only (restricted)",
            ),
        ],
        default="prompt",
        pointer=">",
    ).execute()

    trust_mode = access_mode
    restrict_to_workspace = access_mode == "workspace_only"

    tools_config = ToolsConfig(
        restrict_to_workspace=restrict_to_workspace,
        trust_mode=trust_mode,
    )

    # ── Step 7: Save config & workspace ────────────────────────────────
    _print_step(7, 7, "Setting up workspace & saving config")

    # Add the extra embedding provider entry if one was collected in step 4
    if extra_emb_provider is not None:
        emb_prov_name, emb_prov_entry = extra_emb_provider
        if emb_prov_name not in providers_dict:
            providers_dict[emb_prov_name] = emb_prov_entry

    if use_sdk:
        providers_dict["anthropic"] = ProviderEntry(api_key=api_key)
        config = GripConfig(
            agents=AgentsConfig(
                defaults=AgentDefaults(
                    engine="claude_sdk",
                    model=sdk_model,
                    sdk_model=sdk_model,
                    provider="anthropic",
                    search=search_cfg,
                ),
            ),
            providers=providers_dict,
            channels=channels_config,
            tools=tools_config,
        )
    else:
        local_providers = ["ollama", "llamacpp", "lmstudio"]
        is_local = provider_name in local_providers

        if not is_local and api_key:
            default_api_base = selected_spec.api_base if selected_spec else ""
            if api_base and api_base != default_api_base:
                providers_dict[provider_name] = ProviderEntry(
                    api_key=api_key,
                    api_base=api_base,
                    default_model=bare_model,
                )
            else:
                providers_dict[provider_name] = ProviderEntry(
                    api_key=api_key,
                    default_model=bare_model,
                )

        config = GripConfig(
            agents=AgentsConfig(
                defaults=AgentDefaults(
                    engine="litellm",
                    model=full_model,
                    provider=provider_name,
                    search=search_cfg,
                ),
            ),
            providers=providers_dict,
            channels=channels_config,
            tools=tools_config,
        )

    from grip.cli.app import state

    config_path = save_config(config, state.config_path)

    ws_path = config.agents.defaults.workspace.expanduser().resolve()
    ws = WorkspaceManager(ws_path)
    ws.initialize()

    console.print()
    console.print(
        Panel(
            f"✓ Config saved: [cyan]{config_path}[/cyan]\n✓ Workspace: [cyan]{ws_path}[/cyan]",
            border_style="green",
            expand=False,
        )
    )

    if trust_mode == "trust_all":
        console.print("  [dim]File access: unrestricted (trust all)[/dim]")
    elif trust_mode == "workspace_only":
        console.print("  [dim]File access: workspace only[/dim]")
    else:
        console.print("  [dim]File access: prompt before trusting new directories[/dim]")

    # ── Connection test ────────────────────────────────────────────────
    if use_sdk:
        while True:
            success = _auto_test_sdk_connection(api_key, sdk_model)
            if success:
                break
            action = _handle_test_failure()
            if action == "retry":
                continue
            else:
                return True
    elif api_key or (selected_spec and not selected_spec.api_key_env):
        while True:
            success = _auto_test_connection(config, full_model)
            if success:
                break
            action = _handle_test_failure()
            if action == "retry":
                continue
            else:
                return True

    # ── Success panel ──────────────────────────────────────────────────
    engine_line = "[dim]Powered by Claude Agent SDK[/dim]\n\n" if use_sdk else ""

    console.print()
    console.print(
        Panel(
            f"[bold green]Setup Complete![/bold green]\n\n"
            f"{engine_line}"
            "Next steps:\n"
            "  [cyan]grip agent[/cyan]          → Start an interactive chat\n"
            "  [cyan]grip agent -m 'hello'[/cyan] → Send a one-shot message\n"
            "  [cyan]grip status[/cyan]         → Check system status\n"
            "  [cyan]grip config show[/cyan]    → View your configuration\n\n"
            "[dim]Run [cyan]grip gateway[/cyan] to start the Telegram bot![/dim]",
            title="All Done!",
            border_style="green",
            expand=False,
        )
    )
    return False
