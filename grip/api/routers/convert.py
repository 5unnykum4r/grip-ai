"""Document conversion endpoint for the grip REST API.

Accepts file uploads via multipart/form-data and returns the file
content converted to markdown using MarkItDown.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from loguru import logger

from grip.api.auth import require_auth
from grip.api.dependencies import check_rate_limit, check_token_rate_limit
from grip.tools.markitdown import SUPPORTED_EXTENSIONS, convert_file_to_markdown

router = APIRouter(prefix="/api/v1", tags=["convert"])


@router.post(
    "/convert",
    dependencies=[Depends(check_rate_limit)],
)
async def convert_document(
    file: UploadFile,
    request: Request,
    token: str = Depends(require_auth),
    max_chars: int = 50_000,
) -> dict:
    """Convert an uploaded document file to markdown.

    Accepts multipart/form-data with a single 'file' field.
    Supports PDF, DOCX, PPTX, XLSX, HTML, images, and more.
    """
    check_token_rate_limit(request, token)

    if max_chars < 1 or max_chars > 500_000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="max_chars must be between 1 and 500000",
        )

    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    tmp_path = None
    try:
        content = await file.read()
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        result = await asyncio.to_thread(
            convert_file_to_markdown, tmp_path, max_chars=max_chars
        )

        return {
            "filename": filename,
            "size_bytes": len(content),
            "markdown": result.text_content,
            "truncated": result.truncated,
        }
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("Document conversion failed for {}: {}", filename, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Conversion failed: {type(exc).__name__}: {exc}",
        ) from exc
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
