---
title: Memory
description: Manage long-term memory and searchable history
category: memory
---
# Memory

> Manage long-term memory and searchable history. Use when storing user preferences, project context, relationships, or recalling past interactions.

## Two-Layer Memory System

grip uses two complementary files in your workspace:

### MEMORY.md — Durable Facts (Always in Context)

This file is loaded into every conversation. Store only high-value, long-lived information:

- **User preferences**: communication style, timezone, preferred languages, tool restrictions
- **Project context**: repo names, tech stacks, deployment targets, team members
- **Relationships**: who reports to whom, client names, project owners
- **Standing instructions**: "always use TypeScript", "never commit to main directly"
- **Credentials context**: which API keys are configured (never store actual secrets)

Write to MEMORY.md **immediately** when the user states a preference or fact. Do not wait until end of conversation.

```
# Updating MEMORY.md — use append_file to add, edit_file to modify existing entries

## User Preferences
- Timezone: Asia/Kolkata
- Prefers concise responses without emojis
- Primary language: Python 3.12+

## Project: grip
- Repo: github.com/user/grip
- Stack: Python, FastAPI, Pydantic, uv
- Deploy target: VPS with Docker
```

**Size discipline**: Keep MEMORY.md under 200 lines. When it grows beyond that, consolidate related entries and remove outdated facts.

### HISTORY.md — Event Log (Search Only)

This file is append-only and grows over time. Never read the entire file — always search with specific terms.

Contents are auto-appended after each agent run: timestamps, topics discussed, actions taken, key decisions.

**Searching HISTORY.md:**

When the user asks "what did we discuss about X" or "when did I last deploy", search HISTORY.md:

```
# Use the exec tool to grep HISTORY.md
grep -i "deploy" ~/.grip/workspace/memory/HISTORY.md | tail -20
```

Or use the memory search API endpoint: `GET /api/v1/memory/search?q=deploy`

## When to Write vs When to Search

| Situation | Action |
|-----------|--------|
| User says "I prefer dark mode" | Write to MEMORY.md immediately |
| User asks "what's my timezone?" | Read from MEMORY.md (already in context) |
| User asks "when did we set up the API?" | Search HISTORY.md |
| User shares a project deadline | Write to MEMORY.md |
| Conversation covered 5 topics | HISTORY.md auto-appends (no manual action) |
| MEMORY.md has outdated info | Edit the specific entry in MEMORY.md |

## Memory Consolidation

When conversations grow long, grip auto-consolidates:
1. Extracts durable facts from old messages → appends to MEMORY.md
2. Writes a topic summary to HISTORY.md
3. Trims the session to stay within the context window

You can trigger manual consolidation by recognizing when you've accumulated significant new context that should persist.
