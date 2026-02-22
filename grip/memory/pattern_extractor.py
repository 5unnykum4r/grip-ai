"""Rule-based behavioral pattern extraction — zero LLM calls.

Scans user messages and agent responses for recurring patterns:
user preferences, project decisions, error resolutions, and tool
usage frequency. Extracted patterns are stored in the KnowledgeBase
to improve future interactions.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

_MAX_EXTRACTIONS_PER_CALL = 3
_MAX_CONTENT_LENGTH = 120

# ---------------------------------------------------------------------------
# Extraction result
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ExtractedPattern:
    """A single pattern extracted from an interaction."""

    category: str
    content: str
    source: str  # "user_message", "agent_response", or "tool_usage"
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

_PREFERENCE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"(?:i (?:prefer|like|want|always use|love))\s+(.{5,80})",
        r"(?:my (?:favorite|preferred|default))\s+(?:is\s+)?(.{5,80})",
        r"(?:don'?t|do not|never|stop)\s+(?:use|show|suggest|include)\s+(.{5,80})",
        r"(?:please (?:always|never))\s+(.{5,80})",
    )
)

_DECISION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"(?:let'?s (?:use|go with|switch to|try))\s+(.{5,80})",
        r"(?:we (?:decided|agreed|chose|picked))\s+(?:to\s+)?(.{5,80})",
        r"(?:going (?:with|forward with))\s+(.{5,80})",
        r"(?:the plan is to)\s+(.{5,80})",
    )
)

_ERROR_RESOLUTION_PATTERN = re.compile(r"(?:Error|error|ERROR)[:\s]+(.{10,120})", re.DOTALL)

# Threshold: a tool must appear this many times in the accumulator
# before we record it as a frequent tool.
_TOOL_FREQUENCY_THRESHOLD = 5


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class PatternExtractor:
    """Extract behavioral patterns from interactions using regex heuristics.

    Stateful: tracks per-tool call counts across interactions so that
    frequently-used tools are recorded as ``system_behavior`` entries.
    """

    def __init__(self) -> None:
        self._tool_counts: Counter[str] = Counter()
        self._recorded_tools: set[str] = set()

    def extract(
        self,
        user_message: str,
        response: str,
        tool_calls: list[str],
    ) -> list[ExtractedPattern]:
        """Return up to ``_MAX_EXTRACTIONS_PER_CALL`` patterns from one interaction."""
        patterns: list[ExtractedPattern] = []

        self._extract_preferences(user_message, patterns)
        self._extract_decisions(user_message, patterns)
        self._extract_error_patterns(response, patterns)
        self._extract_tool_frequency(tool_calls, patterns)

        # Deduplicate by (category, content_lower)
        seen: set[tuple[str, str]] = set()
        unique: list[ExtractedPattern] = []
        for p in patterns:
            key = (p.category, p.content.strip().lower())
            if key not in seen:
                seen.add(key)
                unique.append(p)

        return unique[:_MAX_EXTRACTIONS_PER_CALL]

    # -- Private extraction helpers --

    def _extract_preferences(self, text: str, out: list[ExtractedPattern]) -> None:
        for pattern in _PREFERENCE_PATTERNS:
            match = pattern.search(text)
            if match:
                content = _clean(match.group(1))
                if content:
                    out.append(
                        ExtractedPattern(
                            category="user_preference",
                            content=content,
                            source="user_message",
                            tags=["preference"],
                        )
                    )

    def _extract_decisions(self, text: str, out: list[ExtractedPattern]) -> None:
        for pattern in _DECISION_PATTERNS:
            match = pattern.search(text)
            if match:
                content = _clean(match.group(1))
                if content:
                    out.append(
                        ExtractedPattern(
                            category="project_decision",
                            content=content,
                            source="user_message",
                            tags=["decision"],
                        )
                    )

    def _extract_error_patterns(self, response: str, out: list[ExtractedPattern]) -> None:
        match = _ERROR_RESOLUTION_PATTERN.search(response)
        if match:
            content = _clean(match.group(1))
            if content and len(content) >= 10:
                out.append(
                    ExtractedPattern(
                        category="error_pattern",
                        content=content,
                        source="agent_response",
                        tags=["error"],
                    )
                )

    def _extract_tool_frequency(self, tool_calls: list[str], out: list[ExtractedPattern]) -> None:
        for name in tool_calls:
            self._tool_counts[name] += 1
            if (
                self._tool_counts[name] >= _TOOL_FREQUENCY_THRESHOLD
                and name not in self._recorded_tools
            ):
                self._recorded_tools.add(name)
                out.append(
                    ExtractedPattern(
                        category="system_behavior",
                        content=f"Tool '{name}' is frequently used",
                        source="tool_usage",
                        tags=["tool_frequency", name],
                    )
                )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean(text: str) -> str:
    """Normalize extracted text: strip, collapse whitespace, truncate."""
    text = re.sub(r"\s+", " ", text).strip().rstrip(".,;:")
    return text[:_MAX_CONTENT_LENGTH]
