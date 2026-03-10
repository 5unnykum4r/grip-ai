"""Tests for the SSE streaming chat endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grip.api.rate_limit import SlidingWindowRateLimiter
from grip.api.routers.chat import router
from grip.engines.types import StreamEvent


async def _mock_run_stream_simple(*_args, **_kwargs):
    """Yield a basic token + done stream."""
    yield StreamEvent(type="token", text="Hello!")
    yield StreamEvent(
        type="done",
        iterations=1,
        prompt_tokens=10,
        completion_tokens=5,
        tool_calls_made=[],
    )


async def _mock_run_stream_with_tools(*_args, **_kwargs):
    """Yield a stream that includes tool events."""
    yield StreamEvent(type="tool_start", tool_name="web_search")
    yield StreamEvent(type="tool_end", tool_name="web_search")
    yield StreamEvent(type="token", text="Test response")
    yield StreamEvent(
        type="done",
        iterations=2,
        prompt_tokens=15,
        completion_tokens=8,
        tool_calls_made=["web_search"],
    )


async def _mock_run_stream_error(*_args, **_kwargs):
    raise RuntimeError("Engine blew up")
    yield  # make it an async generator  # noqa: E501, RUF028


def _build_test_app(run_stream_fn) -> FastAPI:
    """Create a minimal FastAPI app with the chat router and mocked engine."""
    app = FastAPI()
    app.include_router(router)

    engine_mock = AsyncMock()
    engine_mock.run_stream = run_stream_fn

    app.state.auth_token = "test-token-123"
    app.state.engine = engine_mock
    app.state.ip_rate_limiter = SlidingWindowRateLimiter(max_requests=100, window_seconds=60)
    app.state.token_rate_limiter = SlidingWindowRateLimiter(max_requests=100, window_seconds=60)
    return app


AUTH_HEADERS = {"Authorization": "Bearer test-token-123"}


class TestStreamEndpointContentType:
    def test_stream_endpoint_returns_event_stream(self):
        app = _build_test_app(_mock_run_stream_simple)
        client = TestClient(app)

        response = client.post(
            "/api/v1/chat/stream",
            json={"message": "Hello"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]


class TestStreamEndpointAuth:
    def test_stream_requires_auth(self):
        app = _build_test_app(_mock_run_stream_simple)
        client = TestClient(app)

        response = client.post(
            "/api/v1/chat/stream",
            json={"message": "Hello"},
        )
        assert response.status_code == 401

    def test_stream_rejects_bad_token(self):
        app = _build_test_app(_mock_run_stream_simple)
        client = TestClient(app)

        response = client.post(
            "/api/v1/chat/stream",
            json={"message": "Hello"},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 401


class TestStreamEventStructure:
    def test_stream_events_include_start_token_done(self):
        app = _build_test_app(_mock_run_stream_simple)
        client = TestClient(app)

        response = client.post(
            "/api/v1/chat/stream",
            json={"message": "Test input"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200

        body = response.text
        assert "event: start" in body
        assert "event: token" in body
        assert "event: done" in body

    def test_stream_start_event_contains_session_key(self):
        app = _build_test_app(_mock_run_stream_simple)
        client = TestClient(app)

        response = client.post(
            "/api/v1/chat/stream",
            json={"message": "Hello", "session_key": "test:session1"},
            headers=AUTH_HEADERS,
        )
        body = response.text
        assert '"session_key": "test:session1"' in body or '"session_key":"test:session1"' in body

    def test_stream_done_event_contains_usage(self):
        app = _build_test_app(_mock_run_stream_simple)
        client = TestClient(app)

        response = client.post(
            "/api/v1/chat/stream",
            json={"message": "Hello"},
            headers=AUTH_HEADERS,
        )
        body = response.text
        assert "10" in body
        assert "5" in body

    def test_stream_token_event_contains_text(self):
        app = _build_test_app(_mock_run_stream_simple)
        client = TestClient(app)

        response = client.post(
            "/api/v1/chat/stream",
            json={"message": "Hello"},
            headers=AUTH_HEADERS,
        )
        body = response.text
        assert '"text": "Hello!"' in body or '"text":"Hello!"' in body

    def test_stream_includes_tool_events(self):
        app = _build_test_app(_mock_run_stream_with_tools)
        client = TestClient(app)

        response = client.post(
            "/api/v1/chat/stream",
            json={"message": "Search"},
            headers=AUTH_HEADERS,
        )
        body = response.text
        assert "event: tool_start" in body
        assert "event: tool_end" in body
        assert "web_search" in body

    def test_stream_error_event_on_engine_failure(self):
        app = _build_test_app(_mock_run_stream_error)
        client = TestClient(app)

        response = client.post(
            "/api/v1/chat/stream",
            json={"message": "Hello"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200
        body = response.text
        assert "event: error" in body
        assert "Agent execution failed" in body
