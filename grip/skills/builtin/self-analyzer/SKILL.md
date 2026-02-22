---
title: Self Analyzer
description: Analyze grip's own source code to identify performance bottlenecks and architectural improvements
category: code-quality
---
# Self Analyzer

> Analyze grip's own source code to identify performance bottlenecks, architectural improvements, and potential PRs for its own core.

## When to Use

Activate this skill when:
- During idle time or low-priority moments
- The user asks "how can grip be improved?"
- After a session with repeated errors or slow performance
- When exploring grip internals for debugging
- The user invokes `/self-analyze` or asks for a self-review

## Self-Analysis Protocol

### Step 1: Scope the Analysis

Choose one of these analysis modes:

| Mode | Focus | Trigger |
|------|-------|---------|
| **Performance** | Slow operations, token waste, unnecessary I/O | After slow sessions |
| **Architecture** | Module boundaries, coupling, cohesion | On user request |
| **Security** | Exposed secrets, unsafe operations, missing validation | Periodic review |
| **Quality** | Dead code, unused imports, inconsistent patterns | Before releases |
| **Reliability** | Error handling gaps, missing retries, race conditions | After failures |

### Step 2: Read the Relevant Source

Navigate to grip's own source code (the `grip/` directory in the workspace) and analyze:

**Performance analysis targets:**
- `agent/loop.py` — LLM call patterns, unnecessary iterations
- `memory/manager.py` — File I/O frequency, consolidation efficiency
- `memory/semantic_cache.py` — Cache hit rates, eviction patterns
- `session/manager.py` — Serialization overhead, cache effectiveness
- `tools/*.py` — Tool execution latency, redundant operations

**Architecture analysis targets:**
- `config/schema.py` — Config complexity, unused fields
- `agent/router.py` — Routing accuracy, tier coverage
- `tools/base.py` — Tool registration overhead, context threading
- All `__init__.py` — Import chains, circular dependency risks

**Security analysis targets:**
- `security/sanitizer.py` — Pattern coverage, false positive rate
- `tools/shell.py` — Deny pattern completeness
- `tools/filesystem.py` — Path traversal protection
- `api/auth.py` — Token handling, timing safety

### Step 3: Generate Findings

For each finding, document:

```
## Finding: [Title]

**Severity**: LOW | MEDIUM | HIGH | CRITICAL
**Category**: performance | architecture | security | quality | reliability
**Location**: file_path:line_range
**Description**: What the issue is and why it matters
**Current behavior**: What happens now
**Proposed fix**: Specific code changes or architectural adjustments
**Estimated effort**: trivial | small | medium | large
**Risk of change**: low | medium | high (what could break)
```

### Step 4: Prioritize and Report

Sort findings by: severity (descending) > effort (ascending) > risk (ascending)

Present the top 5 findings to the user with:
1. A one-line summary of each
2. The recommended fix for the highest-priority item
3. An estimate of the total improvement (token savings, latency reduction, security hardening)

### Step 5: Generate PRs (on user approval)

If the user approves a fix:
1. Create a focused diff addressing only that finding
2. Include a clear commit message explaining the why
3. Run lint and tests to verify the change doesn't break anything
4. Present the diff for review before applying

## Analysis Checklists

### Performance Checklist
- [ ] Are there redundant file reads in the same session?
- [ ] Is the semantic cache being utilized effectively?
- [ ] Are consolidation runs happening at optimal thresholds?
- [ ] Is the context builder re-computing static sections?
- [ ] Are tool definitions being serialized on every iteration?
- [ ] Is the model router avoiding unnecessary complexity for simple queries?

### Architecture Checklist
- [ ] Are module boundaries clean (no circular imports)?
- [ ] Is each module under 400 lines?
- [ ] Are there god-classes with too many responsibilities?
- [ ] Is error handling consistent across modules?
- [ ] Are type hints present on all public interfaces?
- [ ] Is the config schema backwards-compatible with older configs?

### Security Checklist
- [ ] Are all secret patterns in sanitizer.py still current?
- [ ] Are shell deny patterns covering latest attack vectors?
- [ ] Is path traversal impossible in all file tools?
- [ ] Are API tokens compared with constant-time operations?
- [ ] Is user input sanitized before reaching exec_command?
- [ ] Are temporary files cleaned up after use?

### Quality Checklist
- [ ] Are there unused imports or dead code paths?
- [ ] Are all public functions documented?
- [ ] Is test coverage adequate for critical paths?
- [ ] Are error messages helpful and actionable?
- [ ] Are logging levels appropriate (debug vs info vs warning)?
- [ ] Are magic numbers replaced with named constants?

## Reporting Format

```
# grip Self-Analysis Report
Generated: {timestamp}
Mode: {analysis_mode}
Files analyzed: {count}
Lines scanned: {count}

## Summary
- {count} findings total
- {count} HIGH severity
- {count} MEDIUM severity
- {count} LOW severity

## Top Findings
1. [HIGH] {title} — {one-line description}
2. [MEDIUM] {title} — {one-line description}
3. ...

## Recommended Actions
1. {action} (effort: {effort}, impact: {impact})
2. ...
```

## Limitations

- This skill analyzes source code statically — it does not profile runtime performance
- Complex architectural issues may require human judgment beyond pattern matching
- Security analysis covers known patterns but cannot detect novel attack vectors
- Generated PRs should always be reviewed by a human before merging
