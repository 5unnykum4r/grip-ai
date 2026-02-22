---
title: Web Researcher
description: Conduct structured web research with source verification and cited findings
category: research
---
# Web Researcher

> Conduct structured web research with source verification and cited findings. Use when the user asks to research a topic, compare options, find documentation, investigate a technology, or gather information from multiple sources.

## Research Methodology

### Phase 1: Discover Sources

Use `web_search` to find relevant pages. Run 2-3 searches with different query angles to avoid single-source bias.

```
Search 1: Direct query          → "FastAPI websocket authentication"
Search 2: Alternative framing   → "FastAPI ws auth middleware bearer token"
Search 3: Comparison/review     → "FastAPI vs Django channels websocket performance"
```

Aim for at least 3 independent sources before forming conclusions. Prefer primary sources (official docs, RFCs, author blogs) over aggregators.

### Phase 2: Deep Read

Use `web_fetch` to read the most promising results. Extract specific facts, code examples, and version numbers.

```
For each source:
1. Fetch the URL
2. Note the publication date (reject info older than 2 years for fast-moving tech)
3. Extract the specific claim or data point
4. Record the URL for citation
```

### Phase 3: Cross-Reference

Compare claims across sources. Flag contradictions explicitly:

```
Source A (official docs) says: "WebSocket connections are limited to 1000 concurrent"
Source B (blog post, 2024) says: "We ran 5000 concurrent WebSocket connections"
Resolution: The 1000 limit was removed in v0.100+ — Source B is using a newer version
```

### Phase 4: Synthesize and Report

Structure findings with citations:

```markdown
## Findings

### [Topic]

[Synthesized answer with specific details, version numbers, and caveats]

**Sources:**
1. [Official FastAPI docs — WebSocket guide](https://url)
2. [Author's blog — Performance benchmarks](https://url)
3. [GitHub issue #1234 — Limitation discussed](https://url)

### Confidence Level
- HIGH: Multiple authoritative sources agree
- MEDIUM: Sources partially agree or data is from a single authoritative source
- LOW: Conflicting information or only unofficial sources available
```

## Search Query Strategies

| Research Goal | Query Pattern |
|---------------|---------------|
| How to do X | `"X" tutorial site:docs.example.com` or `"X" guide 2024` |
| Compare A vs B | `"A vs B" benchmark` or `"A" OR "B" comparison` |
| Find official docs | `"X" site:github.com` or `"X" documentation` |
| Debug an error | `"exact error message"` (in quotes) |
| Find alternatives | `"X alternatives"` or `"similar to X"` |
| Check if X is current | `"X" deprecated` or `"X" changelog latest` |

## Evaluating Sources

**Prefer (in order):**
1. Official documentation and API references
2. GitHub repositories (README, issues, release notes)
3. Author/maintainer blog posts
4. Reputable tech publications (with dates)
5. Stack Overflow answers with high votes and recent activity

**Treat with caution:**
- Blog posts older than 18 months (for actively developed tech)
- AI-generated content farms (check for generic phrasing, no code examples)
- Forum posts without upvotes or verification
- Pages behind aggressive ad walls (often low-quality SEO content)

## Output Formats

### Quick Answer (1-2 sources needed)
User: "What's the latest Python version?"
→ One search, one fetch, direct answer with source link.

### Comparison Report (3+ sources needed)
User: "Compare Redis vs Memcached for session storage"
→ Multiple searches, structured comparison table, pros/cons, recommendation with reasoning.

### Deep Dive (5+ sources needed)
User: "Research how to implement OAuth 2.0 with PKCE in a Python CLI"
→ Full methodology, code examples from official docs, library comparison, security considerations, step-by-step implementation guide.

## When NOT to Use Web Research

- The answer is in the local codebase (use `read_file` / `list_dir` instead)
- The user asks about their own project's implementation (check workspace first)
- The question is about general programming concepts you already know well
- The user explicitly says "don't search the web"
