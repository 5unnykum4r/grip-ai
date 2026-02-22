"""Tool endpoints for the grip REST API.

GET  /api/v1/tools              — list all registered tool definitions
POST /api/v1/tools/{name}/execute — execute a tool directly (gated by config)

The execute endpoint is disabled by default (enable_tool_execute=False)
because it allows arbitrary tool invocation including shell commands.
When enabled, the existing tool-level security (workspace sandbox, shell
deny patterns) still applies.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from grip.api.auth import require_auth
from grip.api.dependencies import check_rate_limit, check_token_rate_limit, get_config
from grip.config.schema import GripConfig
from grip.tools.base import ToolContext, ToolRegistry

router = APIRouter(prefix="/api/v1", tags=["tools"])


class ToolExecuteRequest(BaseModel):
    """Request body for direct tool execution."""

    parameters: dict[str, Any] = {}


class ToolExecuteResponse(BaseModel):
    """Response from a tool execution."""

    tool: str
    output: str
    success: bool


@router.get(
    "/tools",
    dependencies=[Depends(check_rate_limit)],
)
async def list_tools(
    request: Request,
    token: str = Depends(require_auth),
) -> dict:
    """List all registered tool definitions."""
    check_token_rate_limit(request, token)

    registry: ToolRegistry = request.app.state.tool_registry
    definitions = registry.get_definitions()
    return {"tools": definitions, "count": len(definitions)}


@router.post(
    "/tools/{name}/execute",
    response_model=ToolExecuteResponse,
    dependencies=[Depends(check_rate_limit)],
)
async def execute_tool(
    name: str,
    body: ToolExecuteRequest,
    request: Request,
    token: str = Depends(require_auth),
    config: GripConfig = Depends(get_config),  # noqa: B008
) -> ToolExecuteResponse:
    """Execute a tool by name. Gated behind enable_tool_execute config flag."""
    check_token_rate_limit(request, token)

    if not config.gateway.api.enable_tool_execute:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Direct tool execution is disabled. Set gateway.api.enable_tool_execute=true to enable.",
        )

    registry: ToolRegistry = request.app.state.tool_registry
    if name not in registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{name}' not found",
        )

    defaults = config.agents.defaults
    ctx = ToolContext(
        workspace_path=defaults.workspace.expanduser().resolve(),
        restrict_to_workspace=config.tools.restrict_to_workspace,
        shell_timeout=config.tools.shell_timeout,
        session_key="api:direct",
    )

    output = await registry.execute(name, body.parameters, ctx)
    success = not output.startswith("Error:")

    return ToolExecuteResponse(tool=name, output=output, success=success)
