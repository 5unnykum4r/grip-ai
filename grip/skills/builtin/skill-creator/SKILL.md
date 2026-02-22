---
title: Skill Creator
description: Create, structure, and package new grip skills
category: utility
---
# Skill Creator

> Create, structure, and package new grip skills. Use when the user wants to build a custom skill, extend agent capabilities, or create reusable instruction sets.

## Skill Anatomy

Every skill lives in a folder with a `SKILL.md` file:

```
skill-name/
├── SKILL.md              # Required: name, description, instructions
├── scripts/              # Optional: executable code (Python, Bash)
├── references/           # Optional: docs loaded into context on demand
└── assets/               # Optional: templates, config samples, data files
```

Flat single-file skills (`skill-name.md`) also work but folders are preferred for anything beyond simple instructions.

## SKILL.md Format

```markdown
# Skill Name

> One-line description of WHAT the skill does AND WHEN to use it.
<!-- always_loaded -->   ← optional: inject into every conversation

## Section Heading

Step-by-step instructions for the agent...
```

**Required elements:**
- `# Heading` — becomes the skill name (H1, first one found)
- `> Blockquote` — becomes the description (first blockquote found)

**Optional flags:**
- `<!-- always_loaded -->` — skill body is always in the system prompt (use sparingly, adds to every request's token count)

## Writing the Description

The description is the ONLY thing evaluated for skill triggering. It must contain:

1. **What** the skill does: "Schedule tasks and reminders"
2. **When** to activate: "Use when the user wants to automate, set reminders, or schedule jobs"

**Good**: "Search and analyze financial market data including stock prices, company fundamentals, and crypto. Use when the user asks about stocks, investments, portfolio, or market data."

**Bad**: "Financial data skill" (too vague — won't trigger reliably)

## Writing Instructions

Instructions are loaded when the skill activates. Keep under 400 lines. Split longer content into `references/` files.

### Principles

1. **Be specific** — include exact commands, tool names, parameter formats
2. **Show examples** — concrete input/output pairs the agent can follow
3. **Define boundaries** — what the skill handles vs what it doesn't
4. **Reference grip tools by name** — `read_file`, `write_file`, `edit_file`, `exec`, `web_search`, `web_fetch`, `spawn`, `send_message`
5. **Include error handling** — what to do when a command fails or data is missing

### Structure Template

```markdown
# Skill Name

> Description with trigger words.

## When to Use
- Trigger condition 1
- Trigger condition 2

## How It Works
Step-by-step process the agent follows.

## Commands / Tools Used
Specific tool invocations with parameters.

## Examples
Concrete input → output demonstrations.

## Limitations
What this skill does NOT handle.
```

## Installing Skills

```bash
# List all loaded skills (built-in + workspace)
grip skills list

# Install a skill file to workspace (overrides built-in with same name)
grip skills install /path/to/skill-name.md

# Remove a workspace skill (cannot remove built-ins)
grip skills remove skill-name
```

Workspace skills live in `~/.grip/workspace/skills/` and override built-in skills with the same name.

## Creating a Skill Step-by-Step

### 1. Define the Purpose

Answer: "When a user says ___, the agent should ___."

### 2. Create the Folder

```bash
mkdir -p ~/.grip/workspace/skills/my-skill
```

### 3. Write SKILL.md

Start with the template above. Fill in real commands and examples from your testing.

### 4. Add Reference Files (if needed)

```
my-skill/
├── SKILL.md
└── references/
    ├── api-docs.md        # API documentation excerpts
    └── common-patterns.md # Frequently used patterns
```

Reference files are loaded by the agent on demand using `read_file` when the skill instructions say to.

### 5. Test the Skill

```bash
# Reload skills and verify it appears
grip skills list

# Test in a conversation
grip agent "Use the my-skill skill to do X"
```

### 6. Iterate

Watch how the agent uses the skill. Refine instructions based on where it struggles. Add more examples for edge cases.

## Naming Conventions

- Folder name: lowercase, hyphens, alphanumeric (`web-researcher`, `yfinance`, `code-review`)
- Max 64 characters
- No spaces, underscores, or special characters
- Name should hint at purpose without reading the description

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Description only says what, not when | Add trigger phrases: "Use when..." |
| Instructions reference tools that don't exist | Use only grip's registered tools |
| Skill body is 1000+ lines | Split into SKILL.md (core) + references/ (detail) |
| Using `always_loaded` on a niche skill | Reserve for skills needed in every conversation (memory, code-review) |
| Vague instructions like "do the thing" | Specific: "Run `exec` with command `git log --oneline -10`" |
