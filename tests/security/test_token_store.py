"""Tests for grip.security.token_store — OAuth token persistence."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from grip.security.token_store import StoredToken, TokenStore


class TestStoredToken:
    def test_defaults(self):
        token = StoredToken()
        assert token.access_token == ""
        assert token.refresh_token == ""
        assert token.expires_at == 0.0
        assert token.token_type == "Bearer"
        assert token.scopes == []

    def test_not_expired_when_zero(self):
        token = StoredToken(expires_at=0.0)
        assert not token.is_expired

    def test_not_expired_when_future(self):
        token = StoredToken(expires_at=time.time() + 3600)
        assert not token.is_expired

    def test_expired_when_past(self):
        token = StoredToken(expires_at=time.time() - 60)
        assert token.is_expired

    def test_expired_within_buffer(self):
        # Token that expires in 10 seconds should be considered expired (30-second buffer)
        token = StoredToken(expires_at=time.time() + 10)
        assert token.is_expired

    def test_not_expired_beyond_buffer(self):
        token = StoredToken(expires_at=time.time() + 60)
        assert not token.is_expired


class TestTokenStore:
    @pytest.fixture
    def store(self, tmp_path: Path) -> TokenStore:
        return TokenStore(tokens_path=tmp_path / "tokens.json")

    def test_get_nonexistent_returns_none(self, store: TokenStore):
        assert store.get("nonexistent") is None

    def test_save_and_retrieve(self, store: TokenStore):
        token = StoredToken(
            access_token="test_access_123",
            refresh_token="test_refresh_456",
            expires_at=time.time() + 3600,
            scopes=["read", "write"],
        )
        store.save("test_server", token)
        retrieved = store.get("test_server")
        assert retrieved is not None
        assert retrieved.access_token == "test_access_123"
        assert retrieved.refresh_token == "test_refresh_456"
        assert retrieved.scopes == ["read", "write"]

    def test_save_overwrites(self, store: TokenStore):
        store.save("s1", StoredToken(access_token="old"))
        store.save("s1", StoredToken(access_token="new"))
        assert store.get("s1").access_token == "new"

    def test_delete_existing(self, store: TokenStore):
        store.save("s1", StoredToken(access_token="tok"))
        assert store.delete("s1") is True
        assert store.get("s1") is None

    def test_delete_nonexistent(self, store: TokenStore):
        assert store.delete("nope") is False

    def test_list_servers(self, store: TokenStore):
        store.save("a", StoredToken(access_token="1"))
        store.save("b", StoredToken(access_token="2"))
        names = store.list_servers()
        assert sorted(names) == ["a", "b"]

    def test_file_permissions(self, store: TokenStore):
        store.save("s", StoredToken(access_token="t"))
        stat = os.stat(store._path)
        # 0o600 = owner read/write only
        assert stat.st_mode & 0o777 == 0o600

    def test_multiple_servers(self, store: TokenStore):
        store.save("s1", StoredToken(access_token="t1"))
        store.save("s2", StoredToken(access_token="t2"))
        assert store.get("s1").access_token == "t1"
        assert store.get("s2").access_token == "t2"

    def test_corrupted_file_returns_none(self, tmp_path: Path):
        tokens_path = tmp_path / "tokens.json"
        tokens_path.write_text("not valid json{{{", encoding="utf-8")
        store = TokenStore(tokens_path=tokens_path)
        assert store.get("any") is None
        assert store.list_servers() == []

    def test_atomic_write(self, store: TokenStore):
        store.save("s", StoredToken(access_token="t"))
        # No .tmp file should remain
        tmp_path = store._path.with_suffix(".tmp")
        assert not tmp_path.exists()
        # Main file should have valid JSON
        data = json.loads(store._path.read_text(encoding="utf-8"))
        assert "s" in data
