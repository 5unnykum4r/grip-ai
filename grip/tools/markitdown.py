"""Document-to-markdown conversion using Microsoft MarkItDown.

Provides three entry points:
  - convert_file_to_markdown(): Convert any supported file to markdown text
  - convert_html_to_markdown(): Convert raw HTML to markdown (with fallback)
  - ConvertDocumentTool: LiteLLM tool for agent-triggered file conversion

Supported formats (via MarkItDown): PDF, DOCX, PPTX, XLSX, XLS, CSV, TSV,
JSON, XML, HTML, HTM, RTF, EPUB, MD, TXT, PNG, JPG, JPEG, GIF, BMP, TIFF,
WAV, MP3, ZIP.
"""

from __future__ import annotations

import asyncio
import functools
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from grip.tools.base import Tool, ToolContext

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".pptx",
        ".xlsx",
        ".xls",
        ".csv",
        ".tsv",
        ".json",
        ".xml",
        ".html",
        ".htm",
        ".rtf",
        ".epub",
        ".md",
        ".txt",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".tiff",
        ".wav",
        ".mp3",
        ".zip",
    }
)


@dataclass(slots=True)
class ConvertResult:
    """Result of converting a file to markdown."""

    text_content: str
    truncated: bool
    original_size: int
    file_name: str


@functools.lru_cache(maxsize=1)
def _get_markitdown():
    """Lazy-import and cache a single MarkItDown instance."""
    try:
        from markitdown import MarkItDown

        return MarkItDown()
    except ImportError:
        raise ImportError(
            "markitdown is required for document conversion. "
            "Install with: pip install 'markitdown[all]'"
        ) from None


def convert_file_to_markdown(
    file_path: str | Path,
    *,
    max_chars: int = 50_000,
) -> ConvertResult:
    """Convert a file to markdown using MarkItDown.

    Runs synchronously — callers in async contexts should use
    asyncio.to_thread(convert_file_to_markdown, ...).

    Args:
        file_path: Path to the file to convert.
        max_chars: Maximum characters in the output. Content beyond this
            limit is truncated with a suffix indicating the cutoff.

    Returns:
        ConvertResult with the markdown text and metadata.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    md = _get_markitdown()
    result = md.convert(str(path))
    text = result.text_content or ""
    original_size = len(text)
    truncated = False

    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[truncated at {max_chars} chars, {original_size} total]"
        truncated = True

    return ConvertResult(
        text_content=text,
        truncated=truncated,
        original_size=original_size,
        file_name=path.name,
    )


def convert_html_to_markdown(
    html_content: str,
    *,
    max_chars: int = 50_000,
) -> str:
    """Convert HTML to markdown, falling back to _TextExtractor if markitdown is unavailable.

    Writes the HTML to a temp file, converts via MarkItDown, then cleans up.
    If markitdown is not installed, falls back to the existing plain-text extractor
    so web tools degrade gracefully without the optional dependency.

    Args:
        html_content: Raw HTML string to convert.
        max_chars: Maximum output characters.

    Returns:
        Markdown-formatted string of the HTML content.
    """
    try:
        md = _get_markitdown()
    except ImportError:
        from grip.tools.web import _extract_text

        logger.debug("markitdown not installed, falling back to _TextExtractor")
        text = _extract_text(html_content)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[truncated at {max_chars} chars]"
        return text

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(html_content)
            tmp_path = Path(tmp.name)

        result = md.convert(str(tmp_path))
        text = result.text_content or ""

        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[truncated at {max_chars} chars]"

        return text
    except Exception as exc:
        logger.debug("MarkItDown HTML conversion failed, falling back: {}", exc)
        from grip.tools.web import _extract_text

        text = _extract_text(html_content)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[truncated at {max_chars} chars]"
        return text
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


class ConvertDocumentTool(Tool):
    """LiteLLM tool that converts workspace files to readable markdown."""

    @property
    def name(self) -> str:
        return "convert_document"

    @property
    def description(self) -> str:
        return (
            "Convert a document file (PDF, DOCX, PPTX, XLSX, HTML, images, etc.) "
            "to readable markdown text."
        )

    @property
    def category(self) -> str:
        return "document"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to convert (absolute or relative to workspace).",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters in the output (default 50000).",
                    "default": 50000,
                },
            },
            "required": ["file_path"],
        }

    async def execute(self, params: dict[str, Any], ctx: ToolContext) -> str:
        file_path = params["file_path"]
        max_chars = min(params.get("max_chars", 50_000), 500_000)

        path = Path(file_path)
        if not path.is_absolute():
            path = ctx.workspace_path / path

        if ctx.restrict_to_workspace:
            try:
                path.resolve().relative_to(ctx.workspace_path.resolve())
            except ValueError:
                return f"Error: Path '{file_path}' is outside the workspace sandbox."

        if not path.is_file():
            return f"Error: File not found: {file_path}"

        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return (
                f"Error: Unsupported file type '{ext}'. "
                f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        try:
            result = await asyncio.to_thread(convert_file_to_markdown, path, max_chars=max_chars)
        except ImportError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error converting {path.name}: {type(exc).__name__}: {exc}"

        header = f"## {result.file_name}\n\n"
        if result.truncated:
            header += (
                f"*Truncated: showing {max_chars:,} of {result.original_size:,} characters*\n\n"
            )

        return header + result.text_content


def create_markitdown_tools() -> list[Tool]:
    """Factory function returning document conversion tool instances."""
    return [ConvertDocumentTool()]
