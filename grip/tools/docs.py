"""TOOLS.md generator: auto-generates a capability manifest from the live registry.

Produces a markdown document listing all built-in tools (grouped by category),
loaded skills (grouped by skill category), and configured MCP servers.
This file is written to the workspace at startup and injected into the system
prompt so the agent always knows exactly what it can do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from grip.skills.loader import Skill
    from grip.tools.base import Tool, ToolRegistry

# Display order for tool categories in the generated document.
_TOOL_CATEGORY_ORDER: list[tuple[str, str]] = [
    ("finance", "Finance"),
    ("web", "Web"),
    ("filesystem", "Filesystem"),
    ("shell", "Shell"),
    ("messaging", "Messaging"),
    ("orchestration", "Orchestration"),
    ("mcp", "MCP (External)"),
    ("general", "General"),
]
_TOOL_CAT_RANK = {cat: idx for idx, (cat, _) in enumerate(_TOOL_CATEGORY_ORDER)}
_TOOL_CAT_LABELS = dict(_TOOL_CATEGORY_ORDER)

# Display order for skill categories.
_SKILL_CATEGORY_ORDER: list[tuple[str, str]] = [
    ("automation", "Automation"),
    ("debugging", "Debugging"),
    ("code-quality", "Code Quality"),
    ("research", "Research"),
    ("memory", "Memory"),
    ("finance", "Finance"),
    ("devops", "DevOps"),
    ("utility", "Utility"),
    ("general", "General"),
]
_SKILL_CAT_RANK = {cat: idx for idx, (cat, _) in enumerate(_SKILL_CATEGORY_ORDER)}
_SKILL_CAT_LABELS = dict(_SKILL_CATEGORY_ORDER)

_TOOL_ROUTING_INSTRUCTIONS = """\
## Tool Usage Guidelines

IMPORTANT: Always prefer specialized tools over generic fallbacks.
Before using `exec` or `web_search`, check if a dedicated tool already handles the task:

- **Stock prices, crypto, market data** → use `stock_quote` (NOT exec + python, NOT web_search)
- **Historical price data (OHLCV)** → use `stock_history`
- **Company fundamentals** → use `company_info`
- **Reading/writing/editing files** → use filesystem tools (read_file, write_file, edit_file)
- **Listing directory contents** → use `list_dir`
- **Fetching web page content** → use `web_fetch`

Only fall back to `exec` when no specialized tool covers the operation (e.g., git commands, \
running custom scripts, installing packages). Only use `web_search` when you genuinely need \
to search for information not available through a dedicated tool.

Minimize tool calls: if one tool call can answer the question, do not chain multiple calls."""


def _format_tool_row(tool: Tool) -> str:
    """Format a single tool as a markdown table row."""
    defn = tool.to_definition()
    fn = defn.get("function", defn)
    name = fn.get("name", "unknown")
    desc = fn.get("description", "No description")
    params = fn.get("parameters", {})
    required = set(params.get("required", []))
    properties = params.get("properties", {})

    param_parts: list[str] = []
    for pname in properties:
        marker = " (required)" if pname in required else ""
        param_parts.append(f"{pname}{marker}")

    params_str = ", ".join(param_parts) if param_parts else "none"
    return f"| `{name}` | {params_str} | {desc} |"


def _build_tools_section(registry: ToolRegistry) -> str:
    """Generate the Built-in Tools section with one table per category."""
    groups = registry.get_tools_by_category()

    sorted_cats = sorted(
        groups.keys(),
        key=lambda c: _TOOL_CAT_RANK.get(c, 999),
    )

    sections: list[str] = ["## Built-in Tools"]
    for cat in sorted_cats:
        label = _TOOL_CAT_LABELS.get(cat, cat.title())
        tools = groups[cat]
        lines: list[str] = [
            f"\n### {label}\n",
            "| Tool | Parameters | Description |",
            "|------|-----------|-------------|",
        ]
        for tool in tools:
            lines.append(_format_tool_row(tool))
        sections.append("\n".join(lines))

    return "\n".join(sections)


def _build_skills_section(skills: list[Skill]) -> str:
    """Generate the Skills section with one table per skill category."""
    if not skills:
        return ""

    groups: dict[str, list[Skill]] = {}
    for skill in skills:
        groups.setdefault(skill.category, []).append(skill)

    sorted_cats = sorted(
        groups.keys(),
        key=lambda c: _SKILL_CAT_RANK.get(c, 999),
    )

    sections: list[str] = ["## Skills"]
    for cat in sorted_cats:
        label = _SKILL_CAT_LABELS.get(cat, cat.title())
        cat_skills = groups[cat]
        lines: list[str] = [
            f"\n### {label}\n",
            "| Skill | Description | Always Loaded |",
            "|-------|-------------|---------------|",
        ]
        for skill in cat_skills:
            loaded = "Yes" if skill.always_loaded else "No"
            lines.append(f"| {skill.display_name} | {skill.description} | {loaded} |")
        sections.append("\n".join(lines))

    return "\n".join(sections)


def _build_mcp_section(mcp_servers: dict[str, Any]) -> str:
    """Generate the MCP Servers section from config."""
    if not mcp_servers:
        return ""

    lines: list[str] = [
        "## MCP Servers\n",
        "| Server | Transport | Tools |",
        "|--------|-----------|-------|",
    ]
    for name, srv in mcp_servers.items():
        if hasattr(srv, "url") and srv.url:
            transport = srv.url
        elif hasattr(srv, "command") and srv.command:
            args = " ".join(srv.args) if hasattr(srv, "args") and srv.args else ""
            transport = f"`{srv.command} {args}`".strip()
        else:
            transport = "unknown"
        lines.append(f"| {name} | {transport} | (discovered at runtime) |")

    return "\n".join(lines)


def generate_tools_md(
    registry: ToolRegistry,
    skills: list[Skill],
    mcp_servers: dict[str, Any] | None = None,
) -> str:
    """Generate TOOLS.md from the live registry (used by the LiteLLM engine).

    Called at agent startup and written to the workspace. The resulting file
    is injected into the system prompt so the LLM has an accurate manifest
    of available capabilities.
    """
    parts: list[str] = [
        "# grip — Available Tools & Skills\n",
        "> Auto-generated at startup. Lists all built-in tools, skills, and MCP integrations.\n",
        _TOOL_ROUTING_INSTRUCTIONS,
        _build_tools_section(registry),
    ]

    skills_section = _build_skills_section(skills)
    if skills_section:
        parts.append(skills_section)

    mcp_section = _build_mcp_section(mcp_servers or {})
    if mcp_section:
        parts.append(mcp_section)

    return "\n\n".join(parts) + "\n"


_SDK_CUSTOM_TOOLS: list[tuple[str, str, str]] = [
    ("send_message", "text, session_key", "Send a text message to the user via the configured channel."),
    ("send_file", "file_path, caption, session_key", "Send a file to the user via the configured channel."),
    ("remember", "fact, category", "Store a fact in long-term memory for future recall."),
    ("recall", "query_text", "Search long-term memory for facts matching the query."),
    ("stock_quote", "symbol", "Fetch the current stock price for a ticker symbol. (requires yfinance)"),
]


def _build_sdk_tools_section() -> str:
    """Generate the custom tools table for Claude SDK engine mode."""
    lines = [
        "## Custom Tools\n",
        "These tools are provided by grip on top of the Claude SDK's built-in tools",
        "(Read, Write, Edit, Bash, Glob, Grep, WebFetch, WebSearch, etc.):\n",
        "| Tool | Parameters | Description |",
        "|------|-----------|-------------|",
    ]
    for name, params, desc in _SDK_CUSTOM_TOOLS:
        lines.append(f"| `{name}` | {params} | {desc} |")
    return "\n".join(lines)


def generate_sdk_tools_md(
    skills: list[Skill],
    mcp_servers: dict[str, Any] | None = None,
) -> str:
    """Generate TOOLS.md for the Claude SDK engine.

    The SDK engine uses Claude's built-in tools plus grip's custom tools.
    This generates a manifest reflecting those, instead of listing the full
    default registry which only applies to the LiteLLM engine.
    """
    parts: list[str] = [
        "# grip — Available Tools & Skills\n",
        "> Auto-generated at startup. Lists custom tools, skills, and MCP integrations.\n",
        _TOOL_ROUTING_INSTRUCTIONS,
        _build_sdk_tools_section(),
    ]

    skills_section = _build_skills_section(skills)
    if skills_section:
        parts.append(skills_section)

    mcp_section = _build_mcp_section(mcp_servers or {})
    if mcp_section:
        parts.append(mcp_section)

    return "\n\n".join(parts) + "\n"
