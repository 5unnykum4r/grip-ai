"""grip REST API module.

Provides create_api_app() factory for building the FastAPI application.
FastAPI and uvicorn are core dependencies installed with `uv sync`.
"""

from __future__ import annotations

import importlib.util


def is_available() -> bool:
    """Check if FastAPI and uvicorn are installed."""
    return (
        importlib.util.find_spec("fastapi") is not None
        and importlib.util.find_spec("uvicorn") is not None
    )


__all__ = ["is_available"]
