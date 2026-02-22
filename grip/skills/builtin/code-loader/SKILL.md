---
title: Code Loader
description: AST-aware incremental context loading — only load the code chunks that are mathematically relevant to the current task
category: code-quality
---
# Code Loader

> AST-aware incremental context loading — only load the code chunks that are mathematically relevant to the current task.

## When to Use

Activate this skill when:
- Working with a large codebase (10+ files)
- The user asks to modify, debug, or understand a specific function/class
- You need to trace a call chain across multiple files
- Full file reads would waste context window space

## Incremental Loading Protocol

### Step 1: Identify the Target

Parse the user's request to extract:
- **Target symbol**: function name, class name, variable, endpoint
- **Operation type**: read, modify, debug, trace, explain
- **Scope**: single function, class, module, or cross-file

### Step 2: Map the Codebase Structure

Before loading any code, build a lightweight map:

```
1. List project files by extension (*.py, *.ts, *.js, etc.)
2. Read only the first 30 lines of key files (imports + class/function signatures)
3. Identify the entry points relevant to the target symbol
```

Use `exec_command` with language-specific tools when available:
- Python: `grep -n "def target_func\|class TargetClass" **/*.py`
- TypeScript: `grep -n "function target\|export.*target\|class Target" **/*.ts`
- Go: `grep -n "func.*Target" **/*.go`

### Step 3: Load Only Relevant Chunks

Instead of reading entire files, extract targeted sections:

**For a function:**
```
1. Find the function definition line number
2. Read from that line to the next function/class definition
3. Load only the imports used by that function
```

**For a class:**
```
1. Find the class definition
2. Read the class body (up to next top-level definition)
3. Load parent class definitions if inheritance is used
```

**For a call chain:**
```
1. Start at the entry point function
2. Identify all function calls within it
3. Recursively load each called function (depth limit: 3 levels)
4. Stop at standard library or well-known framework calls
```

### Step 4: Build Minimal Context

Assemble loaded chunks into a context block:

```
# Context for: fixing the authentication bug in login()

## auth/login.py:45-78 (target function)
def login(request):
    ...

## auth/validators.py:12-30 (called by login)
def validate_credentials(username, password):
    ...

## models/user.py:5-25 (User model referenced)
class User:
    ...
```

### Step 5: Progressive Deepening

If the initial context isn't sufficient:
1. Expand the loaded region by 20 lines in each direction
2. Load the next level of the call chain
3. Include test files for the target function
4. Load configuration files referenced by the target

## Language-Specific Loading Strategies

### Python
- Parse imports to find local module dependencies
- Check `__init__.py` for re-exports
- Look for decorators that modify behavior (`@app.route`, `@property`, `@classmethod`)
- Track dataclass/pydantic model definitions used as type hints

### TypeScript/JavaScript
- Follow `import`/`require` statements
- Check `index.ts` barrel exports
- Load type definition files (`.d.ts`) when types are ambiguous
- Include relevant `interface` and `type` definitions

### Go
- Follow package imports within the module
- Load `interface` definitions that the target implements
- Check for `init()` functions in the package

## Context Budget Management

Track loaded context size and enforce limits:

| Context Budget | Strategy |
|---------------|----------|
| < 2000 tokens | Load freely, include full functions |
| 2000-5000 tokens | Trim comments, collapse simple getters/setters |
| 5000-8000 tokens | Show only signatures + key logic blocks |
| > 8000 tokens | Summarize peripheral code, keep only target in full |

## Integration with Memory

After loading and analyzing code:
1. Store the codebase structure map in MEMORY.md for faster future lookups
2. Cache function signatures in the knowledge base (category: `system_behavior`)
3. Record dependency chains so future traces start from a warm cache

## Anti-Patterns

- **Loading entire files** when only one function is needed
- **Re-reading files** already loaded in the current session
- **Loading test files** before understanding the implementation
- **Ignoring imports** and then failing to understand type errors
- **Loading all files** in a directory instead of tracing from the entry point
