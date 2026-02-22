---
title: Code Review
description: Review code for bugs, security vulnerabilities, performance issues, and adherence to best practices
category: code-quality
always_loaded: true
---
# Code Review

> Review code for bugs, security vulnerabilities, performance issues, and adherence to best practices. Use when asked to review code, audit a file, check a PR, or assess code quality.

## Review Process

### 1. Read Before Judging

Always read the complete file or diff before commenting. Understand the surrounding context — what the function does, who calls it, what data flows through it.

### 2. Check These Categories (in priority order)

**Security** (Critical)
- Injection vectors: SQL, command, XSS, SSTI, LDAP
- Hardcoded secrets: API keys, passwords, tokens, connection strings
- Path traversal: user input used in file paths without sanitization
- Deserialization: pickle.loads, yaml.load (without SafeLoader), eval(), exec()
- Auth bypass: missing authentication checks, broken access control
- SSRF: user-controlled URLs passed to HTTP clients

**Correctness** (Critical)
- Logic errors: inverted conditions, wrong operator, off-by-one
- Null/None handling: unguarded attribute access, missing null checks
- Race conditions: shared mutable state without synchronization
- Resource leaks: unclosed files, connections, cursors (missing context managers)
- Error handling: bare except, swallowed exceptions, wrong exception types
- Type mismatches: string vs int comparisons, wrong return types

**Performance** (Warning)
- N+1 queries: database calls inside loops
- Unnecessary allocations: creating objects in hot paths, string concatenation in loops
- Missing indexes: queries filtering on unindexed columns
- Blocking calls in async code: time.sleep, synchronous I/O in async functions
- Redundant computation: recalculating values that could be cached

**Maintainability** (Info)
- Dead code: unreachable branches, unused imports, commented-out blocks
- Overly complex functions: cyclomatic complexity > 10, functions > 50 lines
- Poor naming: single-letter variables (except loop counters), misleading names
- Missing error context: raise without "from" clause, generic error messages

### 3. Report Format

For each finding, provide:

```
[SEVERITY] Category — file:line

Problem: What's wrong and why it matters.
Fix: Specific code change to resolve it.
```

### Severity Levels

- **CRITICAL**: Exploitable security vulnerability, data loss risk, or crash in production. Must fix before merge.
- **WARNING**: Performance degradation, maintainability concern, or potential bug under edge conditions. Should fix.
- **INFO**: Style improvement, minor optimization, or suggestion for clarity. Nice to have.

### 4. What NOT to Flag

- Style preferences that aren't bugs (tabs vs spaces, quote style) — defer to project linter
- Missing docstrings on private methods
- Import ordering (automated by ruff/isort)
- Type annotations on obvious return types
- Test file organization preferences
