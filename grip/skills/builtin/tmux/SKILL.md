---
title: tmux
description: Remote-control tmux sessions — create sessions, send keystrokes, capture output, and orchestrate parallel workflows
category: utility
---
# tmux

> Remote-control tmux sessions: create sessions, send keystrokes, capture output, and orchestrate parallel terminal workflows. Use when the user needs interactive CLI control, long-running processes, parallel terminal sessions, or monitoring running programs.

## Prerequisites

tmux must be installed on the system:

```bash
# macOS
brew install tmux

# Ubuntu/Debian
apt install tmux

# Verify
tmux -V
```

All commands below use the `exec` tool.

## Session Management

```bash
# Create a named session
tmux new-session -d -s mywork

# Create with a specific starting directory
tmux new-session -d -s project -c ~/projects/grip

# List active sessions
tmux list-sessions

# Kill a session
tmux kill-session -t mywork

# Kill all sessions
tmux kill-server
```

## Sending Commands to Sessions

Use `send-keys` to type into a tmux pane. Always use the `-l` (literal) flag to prevent tmux key interpretation:

```bash
# Send a command and press Enter
tmux send-keys -t mywork -l "python manage.py runserver" && tmux send-keys -t mywork Enter

# Send Ctrl+C to stop a running process
tmux send-keys -t mywork C-c

# Send text without pressing Enter (useful for building up commands)
tmux send-keys -t mywork -l "git commit -m 'fix: "
```

**Always use `-l` for literal text.** Without it, tmux interprets special sequences — `C-c` means Ctrl+C, but `-l "C-c"` types the literal characters "C-c".

## Capturing Output

```bash
# Capture the visible pane content
tmux capture-pane -t mywork -p

# Capture with more scrollback history (last 500 lines)
tmux capture-pane -t mywork -p -S -500

# Capture and join wrapped lines (recommended for parsing)
tmux capture-pane -t mywork -p -J -S -200

# Capture to a file
tmux capture-pane -t mywork -p -J -S -500 > /tmp/tmux-output.txt
```

**For reading output, always use `-p -J`:** `-p` prints to stdout (instead of paste buffer), `-J` joins wrapped lines.

## Multi-Pane Workflows

```bash
# Split horizontally (top/bottom)
tmux split-window -v -t mywork

# Split vertically (left/right)
tmux split-window -h -t mywork

# Target specific panes (session:window.pane)
tmux send-keys -t mywork:0.0 -l "npm run dev" && tmux send-keys -t mywork:0.0 Enter
tmux send-keys -t mywork:0.1 -l "npm run test -- --watch" && tmux send-keys -t mywork:0.1 Enter

# Resize panes
tmux resize-pane -t mywork:0.1 -D 10   # 10 lines down
tmux resize-pane -t mywork:0.0 -R 20   # 20 columns right
```

## Wait-for-Output Pattern

When you need to wait for a command to finish before proceeding:

```bash
# Send command, wait, then capture
tmux send-keys -t mywork -l "make build" && tmux send-keys -t mywork Enter
sleep 5
OUTPUT=$(tmux capture-pane -t mywork -p -J -S -50)
echo "$OUTPUT"
```

For more reliable waiting, poll for a known completion marker:

```bash
# Wait for a prompt character or specific output
for i in $(seq 1 30); do
    OUTPUT=$(tmux capture-pane -t mywork -p -J -S -5 | tail -1)
    if echo "$OUTPUT" | grep -q '\$'; then
        echo "Command completed"
        break
    fi
    sleep 2
done
tmux capture-pane -t mywork -p -J -S -100
```

## Parallel Agent Sessions

Run multiple agents or processes simultaneously:

```bash
# Create a session with multiple windows
tmux new-session -d -s agents
tmux new-window -t agents -n "researcher"
tmux new-window -t agents -n "coder"
tmux new-window -t agents -n "reviewer"

# Start different tasks in each window
tmux send-keys -t agents:researcher -l "python research.py" && tmux send-keys -t agents:researcher Enter
tmux send-keys -t agents:coder -l "python implement.py" && tmux send-keys -t agents:coder Enter
tmux send-keys -t agents:reviewer -l "python review.py" && tmux send-keys -t agents:reviewer Enter

# Check status of all windows
tmux list-windows -t agents

# Read output from a specific window
tmux capture-pane -t agents:researcher -p -J -S -50
```

## Common Use Cases

### Monitor a Long-Running Build

```bash
tmux new-session -d -s build -c ~/project
tmux send-keys -t build -l "make all 2>&1 | tee build.log" && tmux send-keys -t build Enter
# ... later, check progress:
tmux capture-pane -t build -p -J -S -20
```

### Run a Dev Server and Watch Logs

```bash
tmux new-session -d -s dev
tmux send-keys -t dev -l "uvicorn app:main --reload" && tmux send-keys -t dev Enter
tmux split-window -v -t dev
tmux send-keys -t dev:0.1 -l "tail -f logs/app.log" && tmux send-keys -t dev:0.1 Enter
```

### Interactive REPL Control

```bash
tmux new-session -d -s repl
tmux send-keys -t repl -l "python3" && tmux send-keys -t repl Enter
sleep 1
tmux send-keys -t repl -l "import pandas as pd" && tmux send-keys -t repl Enter
tmux send-keys -t repl -l "df = pd.read_csv('data.csv')" && tmux send-keys -t repl Enter
tmux send-keys -t repl -l "print(df.describe())" && tmux send-keys -t repl Enter
sleep 1
tmux capture-pane -t repl -p -J -S -30
```

## Cleanup

Always clean up sessions when done:

```bash
# Kill a specific session
tmux kill-session -t mywork

# List all sessions to verify cleanup
tmux list-sessions 2>/dev/null || echo "No tmux sessions running"
```
