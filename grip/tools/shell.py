"""Shell command execution tool with safety guards.

Runs commands via asyncio subprocess with configurable timeout and working
directory enforcement. Only blocks operations that would cause irreversible
catastrophic damage to the operating system.

Safety guards:
  1. Blocked base commands (mkfs, shutdown, reboot, halt, poweroff)
  2. Parsed rm detection for root-level recursive deletion
  3. Regex fallback for fork bombs and disk device writes
"""

from __future__ import annotations

import asyncio
import re
import shlex
from typing import Any

from loguru import logger

from grip.tools.base import Tool, ToolContext

# ---------------------------------------------------------------------------
# Layer 1: Commands that are always dangerous regardless of arguments
# ---------------------------------------------------------------------------
_BLOCKED_COMMANDS: frozenset[str] = frozenset(
    {
        "mkfs",
        "mkfs.ext2",
        "mkfs.ext3",
        "mkfs.ext4",
        "mkfs.xfs",
        "mkfs.btrfs",
        "mkfs.vfat",
        "mkfs.ntfs",
        "shutdown",
        "reboot",
        "halt",
        "poweroff",
    }
)

_BLOCKED_SYSTEMCTL_ACTIONS: frozenset[str] = frozenset(
    {
        "poweroff",
        "reboot",
        "halt",
    }
)

# ---------------------------------------------------------------------------
# Layer 2: rm flag normalization and dangerous target detection
# Only blocks rm -rf on root-level system paths (/, /usr, /bin, etc.)
# ---------------------------------------------------------------------------
_RM_LONG_FLAG_MAP: dict[str, str] = {
    "--recursive": "r",
    "--force": "f",
    "--interactive": "i",
    "--dir": "d",
    "--verbose": "v",
    "--no-preserve-root": "!",
}

_DANGEROUS_RM_TARGETS: tuple[str, ...] = (
    "/",
    "/*",
    "~",
    "$HOME",
    "/home",
    "/etc",
    "/var",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/boot",
    "/root",
    "/opt",
    "/srv",
)

# ---------------------------------------------------------------------------
# Layer 3: Regex fallback — only truly catastrophic patterns
# ---------------------------------------------------------------------------
_REGEX_DENY: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        # Fork bombs
        r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;",
        # dd writing to system disk devices
        r"\bdd\s+if=.*\s+of=/dev/sd[a-z]\b",
        r"\bdd\s+if=.*\s+of=/dev/nvme",
        r"\bdd\s+if=.*\s+of=/dev/disk",
        # Redirect to block devices
        r">\s*/dev/sd[a-z]",
        r">\s*/dev/nvme",
        r">\s*/dev/disk",
        # Recursive permission changes on root
        r"\bchmod\s+-R\s+.*\s+/\s*$",
        r"\bchown\s+-R\s+.*\s+/\s*$",
    )
)

_OUTPUT_LIMIT = 50_000


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _split_shell_commands(command: str) -> list[str]:
    """Split a shell command string on ; && || operators into subcommands.

    Respects single and double quoting so that separators inside strings
    are not treated as command boundaries.
    """
    parts: list[str] = []
    current: list[str] = []
    i = 0
    in_single = False
    in_double = False

    while i < len(command):
        ch = command[i]

        if ch == "\\" and i + 1 < len(command) and not in_single:
            current.append(ch)
            current.append(command[i + 1])
            i += 2
            continue

        if ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
            i += 1
            continue

        if ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
            i += 1
            continue

        if not in_single and not in_double:
            if command[i : i + 2] == "&&":
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                i += 2
                continue
            if command[i : i + 2] == "||":
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                i += 2
                continue
            if ch == ";":
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                i += 1
                continue

        current.append(ch)
        i += 1

    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def _tokenize(command: str) -> list[str]:
    """Tokenize a command with shlex, falling back to split on parse error."""
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _strip_sudo(tokens: list[str]) -> list[str]:
    """Strip leading 'sudo' (with optional flags like -u user) from tokens."""
    if not tokens or tokens[0] != "sudo":
        return tokens
    i = 1
    while i < len(tokens) and tokens[i].startswith("-"):
        i += 1
        if i < len(tokens):
            i += 1
    return tokens[i:] if i < len(tokens) else tokens


def _extract_rm_flags(tokens: list[str]) -> set[str]:
    """Extract normalized single-char flags from rm arguments."""
    flags: set[str] = set()
    for token in tokens[1:]:
        if token == "--":
            break
        if token.startswith("--"):
            mapped = _RM_LONG_FLAG_MAP.get(token)
            if mapped:
                flags.add(mapped)
        elif token.startswith("-") and len(token) > 1 and not token[1:].isdigit():
            for ch in token[1:]:
                flags.add(ch)
    return flags


def _extract_rm_targets(tokens: list[str]) -> list[str]:
    """Extract non-flag arguments (file/dir targets) from rm tokens."""
    targets: list[str] = []
    past_flags = False
    for token in tokens[1:]:
        if token == "--":
            past_flags = True
            continue
        if past_flags or not token.startswith("-"):
            targets.append(token)
    return targets


def _check_rm(tokens: list[str]) -> str | None:
    """Check if an rm command is dangerous based on parsed flags and targets."""
    flags = _extract_rm_flags(tokens)
    targets = _extract_rm_targets(tokens)

    if "!" in flags and "r" in flags:
        return "rm with --no-preserve-root and recursive flag"

    has_recursive = "r" in flags
    has_force = "f" in flags

    for target in targets:
        normalized = target.rstrip("/") or "/"
        if has_recursive and normalized == "/":
            return "rm -r on root filesystem"
        if has_recursive and has_force:
            for dangerous in _DANGEROUS_RM_TARGETS:
                if normalized == dangerous or normalized == dangerous.rstrip("/"):
                    return f"rm -rf on critical path: {target}"
    return None


def _is_dangerous(command: str) -> str | None:
    """Check for catastrophic shell commands.

    Only blocks operations that would cause irreversible system-level damage.
    Returns a description of why the command is blocked, or None if safe.
    """
    for subcmd in _split_shell_commands(command):
        tokens = _tokenize(subcmd)
        if not tokens:
            continue

        tokens = _strip_sudo(tokens)
        if not tokens:
            continue

        base_cmd = tokens[0].rsplit("/", maxsplit=1)[-1]

        # Layer 1: Unconditionally blocked commands
        if base_cmd in _BLOCKED_COMMANDS:
            return f"Blocked command: {base_cmd}"

        if base_cmd == "systemctl" and len(tokens) > 1 and tokens[1] in _BLOCKED_SYSTEMCTL_ACTIONS:
            return f"systemctl {tokens[1]} is blocked"

        if base_cmd == "init" and len(tokens) > 1 and tokens[1] in ("0", "6"):
            return f"init {tokens[1]} (system halt/reboot)"

        # Layer 2: rm with parsed flags on critical system paths
        if base_cmd == "rm":
            result = _check_rm(tokens)
            if result:
                return result

    # Layer 3: Regex fallback for fork bombs and disk device writes
    for pattern in _REGEX_DENY:
        if pattern.search(command):
            return f"Blocked: matches pattern '{pattern.pattern}'"

    return None


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


class ShellTool(Tool):
    @property
    def category(self) -> str:
        return "shell"

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "Execute a shell command and return stdout/stderr."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds. Defaults to the configured shell_timeout.",
                },
            },
            "required": ["command"],
        }

    async def execute(self, params: dict[str, Any], ctx: ToolContext) -> str:
        command = params["command"]
        timeout = params.get("timeout") or ctx.shell_timeout

        danger = _is_dangerous(command)
        if danger:
            logger.warning("Blocked dangerous command: {}", command)
            return f"Error: {danger}"

        if ctx.extra.get("dry_run"):
            return f"[DRY RUN] Would execute: {command} (timeout={timeout}s)"

        cwd = str(ctx.workspace_path)
        logger.info("Executing shell: {} (timeout={}s, cwd={})", command, timeout, cwd)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return f"Error: Command timed out after {timeout}s: {command}"

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            parts: list[str] = []
            if stdout:
                parts.append(stdout)
            if stderr:
                parts.append(f"[stderr]\n{stderr}")
            if proc.returncode != 0:
                parts.append(f"[exit code: {proc.returncode}]")

            output = "\n".join(parts) if parts else "(no output)"

            if len(output) > _OUTPUT_LIMIT:
                half = _OUTPUT_LIMIT // 2
                output = (
                    output[:half]
                    + f"\n\n[... truncated {len(output) - _OUTPUT_LIMIT} chars ...]\n\n"
                    + output[-half:]
                )

            return output

        except FileNotFoundError:
            return f"Error: Shell not found. Cannot execute: {command}"
        except OSError as exc:
            return f"Error: OS error executing command: {exc}"


def create_shell_tools() -> list[Tool]:
    return [ShellTool()]
