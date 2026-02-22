"""Cost-aware execution router.

Analyzes prompt complexity and dynamically selects the appropriate LLM
tier to minimize cost while maintaining quality. Simple queries (greetings,
regex, simple lookups) route to cheaper/faster models while complex tasks
(architecture, multi-file refactors, debugging) route to premium models.

Complexity is estimated by heuristics: message length, keyword signals,
tool call history, and conversation depth. No LLM call is needed for
the routing decision itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from loguru import logger


class ComplexityTier(StrEnum):
    """Prompt complexity classification tiers."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ModelTiers:
    """Maps complexity tiers to model identifiers.

    If a tier's model is empty, the default model is used instead.
    This lets users configure only the tiers they want to override.
    """

    low: str = ""
    medium: str = ""
    high: str = ""


# Keyword patterns that signal high-complexity tasks
_HIGH_COMPLEXITY_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"refactor\w*",
        r"architect\w*",
        r"design.*system",
        r"implement.*from scratch",
        r"debug.*complex",
        r"security.*audit",
        r"performance.*optim",
        r"migrate\w*",
        r"review.*entire",
        r"rewrite\w*",
        r"scale\w*",
        r"deploy\w*.*prod",
        r"infrastructure",
        r"multi.?file",
        r"cross.?platform",
        r"distributed",
        r"concurren",
        r"async.*pattern",
    )
)

# Keyword patterns that signal low-complexity tasks
_LOW_COMPLEXITY_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^(hi|hello|hey|thanks|thank you|ok|okay|yes|no|sure)\b",
        r"what (is|are|was|were) ",
        r"how (do|does|to) ",
        r"^(list|show|display|print) ",
        r"(regex|regexp) for",
        r"(convert|translate) .{0,30} to ",
        r"what time",
        r"remind me",
        r"summarize",
        r"^explain ",
    )
)


def classify_complexity(
    message: str,
    *,
    tool_calls_in_session: int = 0,
    message_count_in_session: int = 0,
) -> ComplexityTier:
    """Classify the complexity of a user message.

    Uses heuristics based on message characteristics:
    - Message length (longer = more complex)
    - Keyword signals (architecture, refactor, debug → high)
    - Session depth (many prior tool calls → likely complex task)
    - Code block presence (multi-line code → likely medium+)
    """
    # Check for high-complexity keyword signals first
    for pattern in _HIGH_COMPLEXITY_PATTERNS:
        if pattern.search(message):
            logger.debug("Router: HIGH complexity (keyword match)")
            return ComplexityTier.HIGH

    # Short messages with low-complexity signals → LOW
    if len(message) < 200:
        for pattern in _LOW_COMPLEXITY_PATTERNS:
            if pattern.search(message):
                logger.debug("Router: LOW complexity (simple query)")
                return ComplexityTier.LOW

    # Session context signals
    if tool_calls_in_session > 10 or message_count_in_session > 30:
        logger.debug("Router: HIGH complexity (deep session)")
        return ComplexityTier.HIGH

    # Message length heuristics
    if len(message) > 2000:
        logger.debug("Router: HIGH complexity (long message)")
        return ComplexityTier.HIGH

    # Code blocks indicate at least medium complexity
    if "```" in message or message.count("\n") > 10:
        logger.debug("Router: MEDIUM complexity (code/multi-line)")
        return ComplexityTier.MEDIUM

    if len(message) < 100:
        logger.debug("Router: LOW complexity (short message)")
        return ComplexityTier.LOW

    logger.debug("Router: MEDIUM complexity (default)")
    return ComplexityTier.MEDIUM


def select_model(
    default_model: str,
    tiers: ModelTiers,
    complexity: ComplexityTier,
) -> str:
    """Select the appropriate model based on complexity tier.

    Returns the tier-specific model if configured, otherwise falls back
    to the default model.
    """
    tier_model = getattr(tiers, complexity.value, "")
    if tier_model:
        logger.info("Router selected '{}' model for {} complexity", tier_model, complexity.value)
        return tier_model
    return default_model
