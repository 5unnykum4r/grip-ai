"""Unicode text sanitization for safe JSON serialization.

Strips lone surrogate codepoints (U+D800..U+DFFF) and other problematic
characters that can corrupt JSONL transcripts and cause HTTP 400 errors
when sent to LLM APIs. Python strings can contain lone surrogates via
subprocess output decoded with errors="surrogatepass" or from malformed
external data sources.

Applied at system boundaries: session persistence, API calls, and channel
message dispatch.
"""

from __future__ import annotations

import re

_LONE_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")

_CONTROL_CHAR_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f"
    r"\ufff0-\ufff8\ufffe\uffff"
    r"\U000e0000-\U000e007f]"
)


def sanitize_unicode(text: str, replacement: str = "\ufffd") -> str:
    """Remove lone surrogates and problematic control characters from text.

    Args:
        text: Input string, potentially containing invalid Unicode.
        replacement: Character to substitute for invalid codepoints.
                     Defaults to U+FFFD (Unicode replacement character).

    Returns:
        Cleaned string safe for JSON serialization and API transmission.
    """
    cleaned = _LONE_SURROGATE_RE.sub(replacement, text)
    cleaned = _CONTROL_CHAR_RE.sub("", cleaned)
    return cleaned


def is_safe_for_json(text: str) -> bool:
    """Check if a string is safe for JSON encoding without data loss."""
    if _LONE_SURROGATE_RE.search(text):
        return False
    try:
        text.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def safe_json_string(text: str) -> str:
    """Ensure a string can be round-tripped through JSON without corruption.

    Applies sanitize_unicode and verifies the result encodes cleanly.
    """
    cleaned = sanitize_unicode(text)
    try:
        cleaned.encode("utf-8")
    except UnicodeEncodeError:
        cleaned = cleaned.encode("utf-8", errors="replace").decode("utf-8")
    return cleaned
