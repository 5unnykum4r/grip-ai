"""Tests for session persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from grip.providers.types import LLMMessage
from grip.session.manager import Session, SessionManager


@pytest.fixture
def session_mgr(tmp_path: Path) -> SessionManager:
    return SessionManager(tmp_path / "sessions")


def test_create_new_session(session_mgr: SessionManager):
    session = session_mgr.get_or_create("test:user1")
    assert session.key == "test:user1"
    assert session.message_count == 0


def test_add_messages(session_mgr: SessionManager):
    session = session_mgr.get_or_create("test:user1")
    session.add_message(LLMMessage(role="user", content="hello"))
    session.add_message(LLMMessage(role="assistant", content="hi"))
    assert session.message_count == 2


def test_save_and_reload(session_mgr: SessionManager):
    session = session_mgr.get_or_create("test:persist")
    session.add_message(LLMMessage(role="user", content="save me"))
    session_mgr.save(session)

    session_mgr.clear_cache()
    loaded = session_mgr.get_or_create("test:persist")
    assert loaded.message_count == 1
    assert loaded.messages[0].content == "save me"


def test_list_sessions(session_mgr: SessionManager):
    for key in ("a:1", "b:2", "c:3"):
        s = session_mgr.get_or_create(key)
        s.add_message(LLMMessage(role="user", content="x"))
        session_mgr.save(s)

    keys = session_mgr.list_sessions()
    assert len(keys) == 3


def test_delete_session(session_mgr: SessionManager):
    s = session_mgr.get_or_create("delete:me")
    s.add_message(LLMMessage(role="user", content="bye"))
    session_mgr.save(s)

    assert session_mgr.delete("delete:me") is True
    assert session_mgr.delete("delete:me") is False


def test_get_recent_window():
    session = Session(key="test")
    for i in range(100):
        session.add_message(LLMMessage(role="user", content=f"msg {i}"))

    recent = session.get_recent(10)
    assert len(recent) == 10
    assert recent[0].content == "msg 90"
