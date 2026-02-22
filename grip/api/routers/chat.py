"""Chat endpoint for the grip REST API.

POST /api/v1/chat — blocking request/response. Sends the user message
through the engine and returns the final response with metrics.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from grip.api.auth import require_auth
from grip.api.dependencies import check_rate_limit, check_token_rate_limit, get_engine
from grip.engines.types import EngineProtocol

router = APIRouter(prefix="/api/v1", tags=["chat"])

SESSION_KEY_PATTERN = re.compile(r"^[\w:.@\-]+$")
MAX_MESSAGE_LENGTH = 100_000


class ChatRequest(BaseModel):
    """Request body for the chat endpoint."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)
    session_key: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=256)

    @field_validator("session_key")
    @classmethod
    def validate_session_key(cls, v: str | None) -> str | None:
        if v is not None and not SESSION_KEY_PATTERN.match(v):
            msg = "session_key must match ^[\\w:.@-]+$"
            raise ValueError(msg)
        return v


class ChatResponse(BaseModel):
    """Response body from the chat endpoint."""

    model_config = ConfigDict(extra="forbid")

    response: str
    iterations: int
    usage: dict
    tool_calls_made: list[str]
    session_key: str


@router.post(
    "/chat",
    response_model=ChatResponse,
    dependencies=[Depends(check_rate_limit)],
)
async def chat(
    body: ChatRequest,
    request: Request,
    token: str = Depends(require_auth),
    engine: EngineProtocol = Depends(get_engine),  # noqa: B008
) -> ChatResponse:
    """Send a message to the agent and get a blocking response."""
    check_token_rate_limit(request, token)

    session_key = body.session_key or f"api:{uuid.uuid4().hex[:12]}"

    try:
        result = await engine.run(
            body.message,
            session_key=session_key,
            model=body.model,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Agent execution failed",
        ) from exc

    return ChatResponse(
        response=result.response,
        iterations=result.iterations,
        usage={
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
        },
        tool_calls_made=result.tool_calls_made,
        session_key=session_key,
    )
