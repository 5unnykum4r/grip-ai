---
title: Debug
description: Diagnose and troubleshoot grip issues — config problems, provider failures, tool errors, and connectivity issues
category: debugging
---
# Debug

> Diagnose and troubleshoot grip issues: config problems, provider failures, tool errors, session corruption, and connectivity issues. Use when something isn't working, the agent fails to respond, tools produce errors, or the user reports unexpected behavior.

## Diagnostic Flowchart

Start at the top and work down. Each section has the commands to run.

```
Agent not responding?
├── Config valid?          → grip config show
├── Provider reachable?    → Test LLM connectivity
├── API key set?           → Check provider env vars
└── Model exists?          → Verify model string format

Tool execution failing?
├── Tool registered?       → Check tool registry
├── Workspace accessible?  → Check permissions
├── Sandbox blocking?      → Check restrict_to_workspace
└── Shell denied?          → Check deny pattern list

API server issues?
├── FastAPI installed?     → uv pip list | grep fastapi
├── Port in use?           → lsof -i :18800
├── Auth token valid?      → Check config.gateway.api.auth_token
└── Rate limited?          → Check response headers

Sessions/Memory corrupt?
├── JSON parseable?        → Validate session files
├── Disk space?            → df -h
└── Permissions?           → ls -la on workspace dirs
```

## Step 1: Config Validation

```bash
# Show full config (secrets masked)
grip config show

# Check config file location and readability
grip config path
cat ~/.grip/config.json | python -m json.tool

# Verify workspace exists and has correct structure
ls -la ~/.grip/workspace/
ls -la ~/.grip/workspace/memory/
ls -la ~/.grip/workspace/sessions/
ls -la ~/.grip/workspace/skills/
```

**Common config issues:**
- Missing `config.json` → run `grip onboard` to create
- Invalid JSON (trailing comma, missing quote) → validate with `python -m json.tool`
- Wrong model format → must be `provider/model` (e.g., `openrouter/anthropic/claude-sonnet-4`)

## Step 2: Provider Connectivity

```bash
# Check which provider is configured
grip config show | grep -A5 "providers"

# Test if the API key env var is set
echo $OPENROUTER_API_KEY
echo $ANTHROPIC_API_KEY
echo $OPENAI_API_KEY

# Quick connectivity test (replace with your provider)
curl -s -o /dev/null -w "%{http_code}" https://openrouter.ai/api/v1/models

# Test with a minimal LLM call
grip agent "Say hello in exactly 3 words"
```

**Common provider issues:**
- 401 Unauthorized → API key is wrong or expired
- 429 Too Many Requests → rate limited, wait and retry
- 503 Service Unavailable → provider is down, try a different one
- Connection timeout → check network, firewall, or proxy settings
- `litellm.exceptions.BadRequestError` → model name is incorrect for the provider

## Step 3: Tool Registry

```bash
# List all registered tools via the API
curl -H "Authorization: Bearer TOKEN" http://localhost:18800/api/v1/tools

# Or check in a conversation
grip agent "List all your available tools and their descriptions"
```

**Expected built-in tools (10):** read_file, write_file, edit_file, append_file, list_dir, exec, web_search, web_fetch, send_message, spawn

**Common tool issues:**
- `exec` returns "Command denied" → matches a shell deny pattern (rm -rf /, mkfs, dd, etc.)
- Filesystem tools return "Path outside workspace" → `restrict_to_workspace` is true, use absolute paths within workspace
- `web_search` returns empty → no Brave API key configured, DuckDuckGo fallback may also fail
- `web_fetch` timeout → target URL is slow or blocked, try a different URL
- MCP tools missing → check `grip config show` for mcp_servers section, verify MCP package is installed

## Step 4: Session Inspection

```bash
# List all session files
ls -la ~/.grip/workspace/sessions/

# Check a specific session's JSON validity
python -m json.tool ~/.grip/workspace/sessions/cli_user.json > /dev/null && echo "Valid" || echo "Corrupt"

# Count messages in a session
python -c "import json; d=json.load(open('$HOME/.grip/workspace/sessions/cli_user.json')); print(f'Messages: {len(d.get(\"messages\", []))}')"

# Delete a corrupt session to start fresh
rm ~/.grip/workspace/sessions/cli_user.json
```

**Common session issues:**
- Corrupt JSON → delete the session file, it will be recreated
- Session too large (>10MB) → old conversations haven't been consolidated, memory_window may be too high
- Wrong session loading → check session_key format (should be `channel:identifier`)

## Step 5: Memory Inspection

```bash
# Check memory file sizes
wc -l ~/.grip/workspace/memory/MEMORY.md
wc -l ~/.grip/workspace/memory/HISTORY.md

# Verify MEMORY.md content is reasonable
head -50 ~/.grip/workspace/memory/MEMORY.md

# Search history for recent activity
grep -c "^##" ~/.grip/workspace/memory/HISTORY.md
tail -30 ~/.grip/workspace/memory/HISTORY.md
```

## Step 6: "Time Travel" — Git History Context

When debugging a broken file, trace its history to understand **who** changed **what** and **when**:

```bash
# Show line-by-line blame for the broken file
git blame path/to/broken_file.py

# Blame a specific line range (e.g., lines 40-60 where the bug is)
git blame -L 40,60 path/to/broken_file.py

# Show full commit history for the file (including renames)
git log --follow --oneline path/to/broken_file.py

# Show what changed in each commit touching this file
git log --follow -p path/to/broken_file.py

# Find when a specific function/string was added or removed
git log -S "function_name" --oneline path/to/broken_file.py

# Show the diff between the last known working commit and current state
git diff <last_good_commit> HEAD -- path/to/broken_file.py

# Find the commit that introduced the bug via binary search
git bisect start
git bisect bad HEAD
git bisect good <last_known_good_commit>
# Then test at each step and mark: git bisect good / git bisect bad
```

**When to use these:**
- A function used to work but now fails → `git log -S` to find when it changed
- A file has mysterious edits → `git blame` to identify the responsible commit
- Need the author's reasoning → `git log --follow -p` to read their diffs and messages
- Regression hunting → `git bisect` to pinpoint the exact breaking commit

## Step 7: API Server Diagnostics


```bash
# Check if the server is running
curl -s http://localhost:18800/health

# Check if auth works
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer YOUR_TOKEN" http://localhost:18800/api/v1/health

# Check if the port is in use by something else
lsof -i :18800

# View API metrics
curl -H "Authorization: Bearer TOKEN" http://localhost:18800/api/v1/metrics
```

**Common API issues:**
- Port already in use → another grip instance or different service, kill it or use `--port`
- 401 on all requests → auth token mismatch, check `grip config show` for `gateway.api.auth_token`
- 403 on tool execute → `enable_tool_execute` is false (default), set to true if needed
- 429 Too Many Requests → rate limiter triggered, wait for Retry-After seconds

## Step 8: Log Analysis

```bash
# Find log files
ls -la ~/.grip/workspace/logs/

# View recent log entries
tail -100 ~/.grip/workspace/logs/grip.log

# Filter for errors only
grep -i "error\|exception\|traceback" ~/.grip/workspace/logs/grip.log | tail -30

# Filter for a specific component
grep "AgentLoop" ~/.grip/workspace/logs/grip.log | tail -20
grep "ToolRegistry" ~/.grip/workspace/logs/grip.log | tail -20
```

## Quick Health Check Script

Run this as a single diagnostic pass:

```bash
echo "=== grip Health Check ==="
echo "Config: $(grip config path)"
echo "Workspace: $(ls -d ~/.grip/workspace 2>/dev/null && echo 'EXISTS' || echo 'MISSING')"
echo "Sessions: $(ls ~/.grip/workspace/sessions/*.json 2>/dev/null | wc -l | tr -d ' ') files"
echo "Memory: $(wc -l < ~/.grip/workspace/memory/MEMORY.md 2>/dev/null || echo 0) lines"
echo "History: $(wc -l < ~/.grip/workspace/memory/HISTORY.md 2>/dev/null || echo 0) lines"
echo "Skills: $(ls -d ~/.grip/workspace/skills/*/ 2>/dev/null | wc -l | tr -d ' ') installed"
echo "Cron jobs: $(python -c "import json; print(len(json.load(open('$HOME/.grip/workspace/cron/jobs.json')).get('jobs',[])))" 2>/dev/null || echo 0)"
echo "API: $(curl -s -o /dev/null -w '%{http_code}' http://localhost:18800/health 2>/dev/null || echo 'NOT RUNNING')"
echo "Python: $(python --version 2>&1)"
echo "uv: $(uv --version 2>&1)"
```
