"""Tests for .mcp.json file discovery in grip.config.loader."""

from __future__ import annotations

import json
from pathlib import Path

from grip.config.loader import load_mcp_json
from grip.config.schema import MCPServerConfig


class TestLoadMcpJson:
    def test_missing_file_returns_empty(self, tmp_path: Path):
        result = load_mcp_json(tmp_path)
        assert result == {}

    def test_valid_stdio_server(self, tmp_path: Path):
        data = {
            "mcpServers": {
                "github": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "ghp_test"},
                }
            }
        }
        (tmp_path / ".mcp.json").write_text(json.dumps(data), encoding="utf-8")

        result = load_mcp_json(tmp_path)
        assert "github" in result
        assert isinstance(result["github"], MCPServerConfig)
        assert result["github"].command == "npx"
        assert result["github"].args == ["-y", "@modelcontextprotocol/server-github"]
        assert result["github"].env == {"GITHUB_TOKEN": "ghp_test"}

    def test_valid_http_server(self, tmp_path: Path):
        data = {
            "mcpServers": {
                "docs": {
                    "type": "http",
                    "url": "https://code.claude.com/docs/mcp",
                }
            }
        }
        (tmp_path / ".mcp.json").write_text(json.dumps(data), encoding="utf-8")

        result = load_mcp_json(tmp_path)
        assert "docs" in result
        assert result["docs"].url == "https://code.claude.com/docs/mcp"
        assert result["docs"].type == "http"

    def test_multiple_servers(self, tmp_path: Path):
        data = {
            "mcpServers": {
                "s1": {"command": "npx", "args": ["-y", "s1"]},
                "s2": {"url": "https://s2.example.com"},
            }
        }
        (tmp_path / ".mcp.json").write_text(json.dumps(data), encoding="utf-8")

        result = load_mcp_json(tmp_path)
        assert len(result) == 2

    def test_invalid_json_returns_empty(self, tmp_path: Path):
        (tmp_path / ".mcp.json").write_text("{{invalid json", encoding="utf-8")
        result = load_mcp_json(tmp_path)
        assert result == {}

    def test_missing_mcp_servers_key(self, tmp_path: Path):
        (tmp_path / ".mcp.json").write_text('{"other": "data"}', encoding="utf-8")
        result = load_mcp_json(tmp_path)
        assert result == {}

    def test_non_dict_entry_skipped(self, tmp_path: Path):
        data = {"mcpServers": {"bad": "not a dict", "good": {"command": "npx", "args": []}}}
        (tmp_path / ".mcp.json").write_text(json.dumps(data), encoding="utf-8")
        result = load_mcp_json(tmp_path)
        assert "bad" not in result
        assert "good" in result

    def test_new_fields_supported(self, tmp_path: Path):
        data = {
            "mcpServers": {
                "s": {
                    "url": "https://s.example.com",
                    "type": "sse",
                    "timeout": 30,
                    "enabled": False,
                    "allowed_tools": ["mcp__s__*"],
                }
            }
        }
        (tmp_path / ".mcp.json").write_text(json.dumps(data), encoding="utf-8")

        result = load_mcp_json(tmp_path)
        srv = result["s"]
        assert srv.type == "sse"
        assert srv.timeout == 30
        assert srv.enabled is False
        assert srv.allowed_tools == ["mcp__s__*"]

    def test_supabase_mcp_config(self, tmp_path: Path):
        data = {
            "mcpServers": {
                "supabase": {
                    "url": "https://mcp.supabase.com/mcp",
                    "type": "http",
                }
            }
        }
        (tmp_path / ".mcp.json").write_text(json.dumps(data), encoding="utf-8")

        result = load_mcp_json(tmp_path)
        assert "supabase" in result
        srv = result["supabase"]
        assert isinstance(srv, MCPServerConfig)
        assert srv.url == "https://mcp.supabase.com/mcp"
        assert srv.type == "http"
        assert srv.enabled is True
        assert srv.timeout == 60

    def test_supabase_ci_config_with_headers(self, tmp_path: Path):
        data = {
            "mcpServers": {
                "supabase": {
                    "type": "http",
                    "url": "https://mcp.supabase.com/mcp",
                    "headers": {
                        "Authorization": "Bearer test_token_123"
                    },
                }
            }
        }
        (tmp_path / ".mcp.json").write_text(json.dumps(data), encoding="utf-8")

        result = load_mcp_json(tmp_path)
        srv = result["supabase"]
        assert srv.headers == {"Authorization": "Bearer test_token_123"}
        assert srv.type == "http"

    def test_supabase_with_project_ref_in_url(self, tmp_path: Path):
        data = {
            "mcpServers": {
                "supabase": {
                    "type": "http",
                    "url": "https://mcp.supabase.com/mcp?project_ref=abc123&read_only=true",
                }
            }
        }
        (tmp_path / ".mcp.json").write_text(json.dumps(data), encoding="utf-8")

        result = load_mcp_json(tmp_path)
        srv = result["supabase"]
        assert "project_ref=abc123" in srv.url
        assert "read_only=true" in srv.url

    def test_loads_project_mcp_json(self):
        """Verify the actual .mcp.json in the PyClaw project root loads correctly."""
        project_root = Path(__file__).parent.parent
        result = load_mcp_json(project_root)
        assert "supabase" in result
        assert result["supabase"].url == "https://mcp.supabase.com/mcp"
        assert result["supabase"].type == "http"
