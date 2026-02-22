---
title: Optimization Rules
description: Calculate and use the most efficient sequence of tools and skills to accomplish tasks
category: code-quality
always_loaded: true
---
# Optimization Rules

> Calculate and use the most efficient sequence of tools and skills to accomplish tasks. Proactively suggest better approaches.

## When to Use

This skill is always loaded. Apply these optimization rules to every task before executing:
- Before running a multi-step plan
- When the user asks for something that could be done multiple ways
- When you detect an inefficient pattern in the current approach
- Before making LLM calls that could be avoided

## Core Optimization Principles

### 1. Minimize LLM Round-Trips

Every LLM call costs tokens and time. Reduce them by:

- **Batch related questions**: If you need to ask 3 things, ask them in one message
- **Pre-gather context**: Read all relevant files before starting analysis — don't read one, analyze, read another, re-analyze
- **Use tools directly**: If you can solve it with a tool call (file read, search, shell command), skip the LLM reasoning step

### 2. Tool Selection Priority

Always pick the most direct tool for the job:

| Task | Preferred Tool | Avoid |
|------|---------------|-------|
| Check if file exists | `read_file` | `exec_command` with `ls` or `test -f` |
| Search file content | `read_file` + scan | `exec_command` with `grep` |
| Create/edit files | `write_file` / `edit_file` | `exec_command` with `echo >` or `sed` |
| Get system info | Config platform field | `exec_command` with `uname` |
| Search history | `search_memory` | Reading entire HISTORY.md |

### 3. Parallel Execution When Possible

Identify independent sub-tasks and execute them in parallel:

```
BAD (sequential, 3 round-trips):
  1. Read package.json
  2. Read tsconfig.json
  3. Read .env.example

GOOD (parallel, 1 round-trip):
  1. Read package.json + tsconfig.json + .env.example simultaneously
```

### 4. Cache-Aware Operations

Before making an expensive operation:
1. Check if the semantic cache has a recent answer
2. Check if MEMORY.md already contains the needed fact
3. Check if the knowledge base has a relevant entry

### 5. Fail Fast, Recover Smart

- Check prerequisites before starting multi-step operations
- Validate inputs at the boundary, not deep in the chain
- If step 1 of 5 fails, don't attempt steps 2-5 blindly
- Use the self-correction mechanism to adjust approach on tool failure

## Proactive Suggestions

When you detect these patterns, suggest the optimization:

| Detection | Suggestion |
|-----------|------------|
| User asks to run same command repeatedly | "I can set up a cron job for this" |
| User manually edits config each time | "I can save this as a preference in the knowledge base" |
| User searches for the same thing often | "I've cached this — future lookups will be instant" |
| Multi-step task with clear dependencies | "Here's the optimal execution order with parallel steps" |
| Large file being read repeatedly | "I'll extract the relevant section and cache it" |
| User doing manual file operations | "I can automate this with a workspace script" |

## Execution Order Algorithm

When planning a multi-step task:

1. **Decompose** into atomic operations
2. **Map dependencies** between operations (A must finish before B)
3. **Identify parallel groups** (operations with no dependencies between them)
4. **Estimate cost** per operation (cheap tool call vs expensive LLM call)
5. **Schedule**: run cheap prerequisite checks first, then parallel groups, then dependent operations
6. **Report** the plan to the user before executing if it involves more than 3 steps

## Token Budget Awareness

Monitor token usage during long sessions:
- If approaching daily limit, switch to concise responses
- Prefer tool-based solutions over LLM-heavy reasoning
- Suggest consolidation if context window is getting full
- Route simple follow-up questions through the semantic cache

## Anti-Patterns to Detect and Correct

- **Reading the same file twice** in one session without changes
- **Making an LLM call** to answer something already in MEMORY.md
- **Sequential tool calls** that could be parallelized
- **Full file reads** when only a specific section is needed
- **Unnecessary confirmations** for safe, reversible operations
- **Re-computing** values that are already in the knowledge base

## Content Formatting Rules

Match output structure to the content type the user requests. Never produce a generic flat document when a specific format is implied.

| User says | Format to produce |
|-----------|-------------------|
| "write an article" | **Article**: Compelling headline, author/date line, lead paragraph (who/what/when/where/why), body with H2 subheadings, conclusion. Use engaging prose, not bullet lists. |
| "write a report" | **Report**: Title page info, executive summary (3-5 sentences), table of contents, numbered sections with findings, data tables where relevant, recommendations, appendix if needed. |
| "write a blog post" | **Blog post**: SEO-friendly title, hook opening, conversational tone, H2/H3 subheadings, short paragraphs (2-4 sentences), bullet lists for scannability, CTA at the end. |
| "write documentation" | **Docs**: Overview, prerequisites, step-by-step instructions with code blocks, configuration reference tables, troubleshooting section, related links. |
| "write a README" | **README**: Project name + one-line description, badges placeholder, features list, installation, quick start, usage examples, configuration, contributing, license. |
| "write an email" | **Email**: Subject line, greeting, concise body (context → ask → next steps), sign-off. Professional tone unless user specifies otherwise. |
| "write a proposal" | **Proposal**: Problem statement, proposed solution, scope, timeline/milestones, budget/resources, success criteria, risks. |
| "create a presentation" | **Slides outline**: Title slide, agenda, one key point per slide (6-8 slides), supporting data/visuals notes, summary slide, Q&A slide. |
| "write a changelog" | **Changelog**: Grouped by version (newest first), categorized entries (Added, Changed, Fixed, Removed), one line per change with PR/issue links. |
| "summarize" | **Summary**: Use the `summarize` skill format — key points, structured bullets, TL;DR at top. |

When the content type is ambiguous, ask the user: "Would you like this as a [format A] or [format B]?"

For all long-form content:
- Use proper markdown heading hierarchy (H1 → H2 → H3, never skip levels)
- Include section transitions between major topics
- Vary sentence structure — mix short punchy sentences with longer explanatory ones
- Avoid walls of bullets; use prose paragraphs for narrative content and bullets only for lists of items
