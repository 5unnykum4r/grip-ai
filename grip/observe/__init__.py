"""Observability module: tracing and metrics for grip.

Requires the [observe] optional dependency group:
  pip install grip[observe]
"""

from grip.observe.tracing import get_tracer, init_tracing

__all__ = ["get_tracer", "init_tracing"]
