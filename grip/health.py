"""Health checks for external dependencies.

Provides health check functions to verify LLM providers,
tools, and other external services are available.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx


class HealthStatus(StrEnum):
    """Health check status values."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    message: str = ""
    latency_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


class HealthChecker:
    """Manages health checks for all external dependencies."""

    def __init__(self) -> None:
        pass

    async def check_llm_provider(
        self,
        provider: Any,
        timeout: float = 5.0,
    ) -> HealthCheckResult:
        """Check if an LLM provider is healthy."""

        start = time.perf_counter()
        try:
            if hasattr(provider, "health_check"):
                result = await asyncio.wait_for(provider.health_check(), timeout=timeout)
                latency = (time.perf_counter() - start) * 1000
                return HealthCheckResult(
                    name="llm_provider",
                    status=HealthStatus.HEALTHY if result else HealthStatus.DEGRADED,
                    message="Provider responding" if result else "Provider not responding",
                    latency_ms=latency,
                )
            elif hasattr(provider, "complete"):
                latency = (time.perf_counter() - start) * 1000
                return HealthCheckResult(
                    name="llm_provider",
                    status=HealthStatus.HEALTHY,
                    message="Provider has complete method",
                    latency_ms=latency,
                )
            else:
                return HealthCheckResult(
                    name="llm_provider",
                    status=HealthStatus.UNKNOWN,
                    message="Provider has no health check method",
                    latency_ms=0.0,
                )
        except (TimeoutError, httpx.TimeoutException):
            latency = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name="llm_provider",
                status=HealthStatus.UNHEALTHY,
                message="Provider check timed out",
                latency_ms=latency,
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name="llm_provider",
                status=HealthStatus.UNHEALTHY,
                message=f"Provider check failed: {e}",
                latency_ms=latency,
            )

    async def check_http_endpoint(
        self,
        url: str,
        timeout: float = 5.0,
    ) -> HealthCheckResult:
        """Check if an HTTP endpoint is healthy."""

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url)
                latency = (time.perf_counter() - start) * 1000
                if response.status_code < 400:
                    return HealthCheckResult(
                        name=f"http:{url}",
                        status=HealthStatus.HEALTHY,
                        message=f"Status {response.status_code}",
                        latency_ms=latency,
                        details={"status_code": response.status_code},
                    )
                else:
                    return HealthCheckResult(
                        name=f"http:{url}",
                        status=HealthStatus.DEGRADED,
                        message=f"Status {response.status_code}",
                        latency_ms=latency,
                        details={"status_code": response.status_code},
                    )
        except (TimeoutError, httpx.TimeoutException):
            latency = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name=f"http:{url}",
                status=HealthStatus.UNHEALTHY,
                message="Request timed out",
                latency_ms=latency,
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name=f"http:{url}",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                latency_ms=latency,
            )

    async def check_tool_executable(
        self,
        tool_name: str,
        command: list[str],
    ) -> HealthCheckResult:
        """Check if a tool executable is available."""

        start = time.perf_counter()
        try:
            result = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(result.communicate(), timeout=5.0)
            except (TimeoutError, httpx.TimeoutException):
                result.kill()
                await result.wait()

            latency = (time.perf_counter() - start) * 1000

            if result.returncode == 0 or result.returncode == 1:
                return HealthCheckResult(
                    name=f"tool:{tool_name}",
                    status=HealthStatus.HEALTHY,
                    message=f"Executable found (exit code: {result.returncode})",
                    latency_ms=latency,
                )
            else:
                return HealthCheckResult(
                    name=f"tool:{tool_name}",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Executable error (exit code: {result.returncode})",
                    latency_ms=latency,
                )
        except FileNotFoundError:
            latency = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name=f"tool:{tool_name}",
                status=HealthStatus.UNHEALTHY,
                message=f"Executable not found: {command[0]}",
                latency_ms=latency,
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name=f"tool:{tool_name}",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                latency_ms=latency,
            )

    async def check_workspace(
        self,
        workspace_path: Path,
    ) -> HealthCheckResult:
        """Check if workspace is accessible."""

        start = time.perf_counter()
        try:
            path = workspace_path.expanduser().resolve()
            if path.exists():
                latency = (time.perf_counter() - start) * 1000
                return HealthCheckResult(
                    name="workspace",
                    status=HealthStatus.HEALTHY,
                    message=f"Workspace accessible at {path}",
                    latency_ms=latency,
                    details={"path": str(path)},
                )
            else:
                latency = (time.perf_counter() - start) * 1000
                return HealthCheckResult(
                    name="workspace",
                    status=HealthStatus.DEGRADED,
                    message="Workspace directory does not exist",
                    latency_ms=latency,
                )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name="workspace",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                latency_ms=latency,
            )

    async def check_all(
        self,
        provider: Any = None,
        workspace: Any = None,
        tools: list[tuple[str, list[str]]] | None = None,
    ) -> dict[str, HealthCheckResult]:
        """Run all health checks."""
        results: dict[str, HealthCheckResult] = {}

        if provider is not None:
            results["llm_provider"] = await self.check_llm_provider(provider)

        if workspace is not None:
            results["workspace"] = await self.check_workspace(workspace)

        if tools:
            for name, cmd in tools:
                results[f"tool:{name}"] = await self.check_tool_executable(name, cmd)

        return results


_global_checker: HealthChecker | None = None


def get_health_checker() -> HealthChecker:
    """Get the global health checker."""
    global _global_checker
    if _global_checker is None:
        _global_checker = HealthChecker()
    return _global_checker
