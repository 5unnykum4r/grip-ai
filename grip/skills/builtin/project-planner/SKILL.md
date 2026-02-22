---
title: Project Planner
description: Break down complex tasks into actionable implementation plans with dependency analysis and phased execution
category: devops
---
# Project Planner

> Break down complex tasks into actionable implementation plans with dependency analysis, file mapping, and phased execution. Use when the user asks to plan a feature, architect a system, scope a project, estimate work, or organize a multi-step implementation.

## Planning Process

### Phase 1: Understand the Scope

Before writing any plan, gather:

1. **What exists** — read relevant source files to understand current architecture
2. **What's requested** — clarify ambiguous requirements (ask the user if unclear)
3. **What's constrained** — tech stack, timeline, existing conventions, backward compatibility

Use `read_file` and `list_dir` to map the existing codebase. Never plan changes to code you haven't read.

### Phase 2: Map the Impact

For every planned change, identify:

```markdown
## Impact Map

### Files to Create
| File | Purpose | Lines (est.) |
|------|---------|-------------|
| path/to/new_file.py | What it does | ~50-100 |

### Files to Modify
| File | Change Description |
|------|-------------------|
| path/to/existing.py | Add X method, update Y import |

### Files NOT Changed (but considered)
| File | Why Left Alone |
|------|---------------|
| path/to/other.py | No changes needed, interface compatible |
```

This prevents missing files during implementation and makes review easier.

### Phase 3: Define Tasks

Break the work into discrete, verifiable tasks. Each task should:

- **Do one thing** — if you need "and" to describe it, split it
- **Be independently testable** — you can verify it works without completing later tasks
- **State its inputs and outputs** — what does it need, what does it produce
- **Include verification criteria** — how do you know it's done correctly

```markdown
### Task 1: [Imperative title — "Add user model"]

**What:** Create the User dataclass with fields for id, name, email, created_at.

**Why:** Needed by Task 2 (API endpoint) and Task 3 (database migration).

**Files:** Create `models/user.py`

**Verify:**
- [ ] File exists and imports cleanly
- [ ] Linter passes (ruff check)
- [ ] Unit test for serialization passes
```

### Phase 4: Order Dependencies

Identify which tasks block others:

```markdown
## Execution Order

### Layer 1 (parallel — no dependencies)
- Task 1: Add user model
- Task 2: Add database migration helper

### Layer 2 (depends on Layer 1)
- Task 3: Add user repository (needs Task 1 + 2)
- Task 4: Add auth middleware (needs Task 1)

### Layer 3 (depends on Layer 2)
- Task 5: Add API endpoints (needs Task 3 + 4)

### Layer 4 (depends on Layer 3)
- Task 6: Add integration tests (needs Task 5)
```

Tasks within the same layer can be done in parallel. Tasks in later layers wait for their dependencies.

## Plan Document Format

```markdown
# Plan: [Feature Name]

## Goal
One paragraph describing what we're building and why.

## Current State
What exists today that's relevant to this work.

## Approach
High-level strategy (2-3 sentences). If there were multiple approaches considered, note why this one was chosen.

## Impact Map
[Files to create / modify / leave alone — see Phase 2]

## Tasks
[Numbered, ordered tasks — see Phase 3]

## Execution Order
[Dependency layers — see Phase 4]

## Risks and Open Questions
- Risk: [What could go wrong]
  Mitigation: [How to handle it]
- Question: [What's still unclear]
  Default: [What we'll do if not answered]

## Verification
How to confirm the entire feature works end-to-end after all tasks complete.
```

## Estimation Guidelines

Do not give time estimates (they're unreliable). Instead, describe complexity:

| Complexity | Indicators |
|-----------|------------|
| **Simple** | Single file change, clear pattern to follow, no new dependencies |
| **Moderate** | 2-5 files, some new abstractions, follows existing patterns |
| **Complex** | 5+ files, new patterns introduced, cross-cutting concerns |
| **Significant** | New subsystem, multiple integration points, requires research |

## Using spawn for Parallel Execution

When implementing a plan, independent tasks can use the `spawn` tool to run in parallel:

```
Layer 1 tasks → spawn each as a separate agent task
Wait for all Layer 1 to complete
Layer 2 tasks → spawn each
...continue through layers
```

## When to Re-Plan

Stop and revise the plan when:

- A task reveals the approach won't work (don't force through)
- Requirements change mid-implementation
- A dependency turns out to be more complex than mapped
- You discover existing code that already solves part of the problem

Update the plan document and communicate what changed and why before continuing.

## Anti-Patterns to Avoid

| Anti-Pattern | Better Approach |
|-------------|----------------|
| "Step 1: Build everything" | Break into 5+ specific tasks |
| Tasks without verification | Every task needs a "how to test" section |
| Linear-only ordering | Identify parallel opportunities |
| Planning without reading code | Read existing files first, always |
| Vague tasks like "refactor code" | Specific: "Extract auth logic from handler.py into auth/middleware.py" |
| Ignoring backward compatibility | Note what existing callers/tests need updating |
