---
title: Codebase Mapper
description: Build a local knowledge graph of the codebase for function dependencies, module relationships, and ripple effects
category: code-quality
---
# Codebase Mapper

> Build a local knowledge graph of the codebase so grip deeply understands function dependencies, module relationships, and ripple effects of changes.

## When to Use

Activate this skill when:
- The user asks "what would break if I change X?"
- Refactoring a function/class used across multiple files
- Planning a migration or large-scale rename
- Analyzing technical debt or circular dependencies
- The user asks for an architecture overview

## Mapping Protocol

### Step 1: Discover Project Boundaries

Identify the project root and language:

```
1. Look for package markers: pyproject.toml, package.json, go.mod, Cargo.toml
2. Identify the source root: src/, lib/, app/, or root-level modules
3. Count files by type to determine primary language
4. Note framework indicators: manage.py (Django), next.config (Next.js), main.go
```

### Step 2: Build the Module Graph

For each source file, extract:

**Exports** (what this file provides):
- Function definitions with signatures
- Class definitions with public methods
- Exported constants and type aliases
- Route/endpoint registrations

**Imports** (what this file depends on):
- Local module imports (within the project)
- Third-party package imports
- Transitive re-exports from barrel files

**Connections** (function-level call graph):
- Which exported functions call which other functions
- Database queries and external API calls
- Event emissions and handler registrations

### Step 3: Record the Map

Store the codebase map in the knowledge base with structured entries:

```
[system_behavior] Module auth/login.py exports: login(), logout(), refresh_token()
[system_behavior] Module auth/login.py imports: models.User, validators.validate_credentials, utils.hash_password
[system_behavior] Function login() calls: validate_credentials(), User.get_by_email(), create_session()
[system_behavior] Function login() called_by: routes/auth.py:handle_login, api/v1/auth.py:login_endpoint
```

### Step 4: Analyze Ripple Effects

When the user wants to change a function:

1. **Direct dependents**: files that import/call the target
2. **Transitive dependents**: files that depend on the direct dependents
3. **Test coverage**: test files that exercise the target
4. **Configuration references**: config files, env vars, or constants that affect the target

Present the impact analysis:
```
Changing `validate_credentials()` in auth/validators.py would affect:

Direct (3 files):
  - auth/login.py:23 → login() calls validate_credentials()
  - auth/register.py:45 → register() calls validate_credentials()
  - tests/test_auth.py:12 → test_login_valid() mocks validate_credentials()

Transitive (2 files):
  - routes/auth.py → imports login() and register()
  - api/v1/auth.py → imports login()

Risk assessment: MEDIUM
  - 3 direct callers need signature updates
  - 1 test file needs mock updates
  - No database schema changes required
```

### Step 5: Detect Architectural Patterns

Identify and document:

- **Circular dependencies**: A imports B imports A
- **God modules**: Files with 20+ exports or 500+ lines
- **Orphan code**: Functions/classes never imported anywhere
- **Bottleneck modules**: Files imported by 10+ other files
- **Layer violations**: UI code importing database modules directly

## Supported Languages

| Language | Import Parsing | Call Graph | Class Hierarchy |
|----------|---------------|------------|-----------------|
| Python | `import X`, `from X import Y` | Function calls via name matching | `class A(B)` inheritance |
| TypeScript | `import { X }`, `require()` | Function calls, JSX components | `extends`, `implements` |
| JavaScript | `import`, `require` | Function calls | `extends` |
| Go | `import "pkg"` | Package-qualified calls | Interface implementation |

## Incremental Updates

The codebase map doesn't need full rebuilds:

1. **On file change**: Re-scan only the changed file and its direct dependents
2. **On new file**: Add its exports/imports to the graph
3. **On file delete**: Remove its entries and flag dangling references
4. **Periodic**: Run a full scan weekly or on user request

## Output Formats

### Text Summary (default)
```
Project: grip (Python, 80 files, ~8500 lines)
Core modules: agent/, config/, memory/, session/, tools/
Entry points: cli/app.py, api/app.py, gateway/
Hottest modules: tools/base.py (imported 12x), config/schema.py (imported 9x)
```

### Dependency Tree
```
agent/loop.py
├── agent/context.py
├── agent/router.py
├── config/schema.py
├── memory/manager.py
├── memory/semantic_cache.py
├── providers/types.py
├── session/manager.py
├── tools/base.py
└── workspace/manager.py
```

### Risk Heatmap
```
HIGH RISK (many dependents + complex logic):
  ██████████ tools/base.py (12 dependents, 280 lines)
  ████████░░ config/schema.py (9 dependents, 300 lines)
  ███████░░░ agent/loop.py (5 dependents, 400 lines)

LOW RISK (few dependents, simple):
  ██░░░░░░░░ security/sanitizer.py (2 dependents, 75 lines)
  █░░░░░░░░░ workspace/manager.py (3 dependents, 90 lines)
```

## Integration with Other Skills

- **code-loader**: Use the codebase map to determine which chunks to load
- **code-review**: Reference the map to check if changes have unreviewed ripple effects
- **project-planner**: Use dependency data to sequence implementation tasks
- **debug**: Trace the call graph to narrow down bug sources
