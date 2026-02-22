---
title: Summarize
description: Summarize text, URLs, files, conversations, and documents into structured key points
category: utility
---
# Summarize

> Summarize text, URLs, files, conversations, and documents into structured key points. Use when the user asks to summarize, condense, extract key points, create a TL;DR, or distill information from any source.

## Source Types and How to Handle Them

### Direct Text

When the user provides text directly in the conversation, summarize it immediately without tool calls.

### URLs and Web Pages

Fetch the page, then summarize the extracted text:

```
1. Use web_fetch to retrieve the URL content
2. If the page is too large (>50K chars), focus on the first 30K chars
3. Summarize the extracted text using the format below
```

### Local Files

Read the file from the workspace:

```
1. Use read_file with the file path
2. For very long files (>2000 lines), read in chunks using offset/limit
3. Summarize each chunk, then create a unified summary
```

### Conversation History

When asked to summarize "our conversation" or "what we discussed":

```
1. Review the current session messages
2. Group by topic/decision
3. Highlight action items and unresolved questions
```

## Output Formats

Choose the format based on what the user needs. Default to **Key Points** if not specified.

### Key Points (Default)

```markdown
## Summary: [Source Title or Topic]

### Key Points
- First major point with specific details
- Second major point (include numbers, names, dates)
- Third major point

### Action Items
- [ ] Specific action with owner/deadline if mentioned
- [ ] Another action item

### Notable Details
- Supporting fact or statistic
- Exception or caveat worth remembering
```

### Executive Summary (for reports, long documents)

```markdown
## Executive Summary

**Bottom line:** [One sentence with the most important conclusion]

**Context:** [2-3 sentences of background]

**Key findings:**
1. Finding with supporting evidence
2. Finding with supporting evidence
3. Finding with supporting evidence

**Recommendation:** [What to do next, if applicable]
```

### Comparison Table (for "summarize the differences between X and Y")

```markdown
## Comparison: X vs Y

| Aspect | X | Y |
|--------|---|---|
| Performance | Detail | Detail |
| Cost | Detail | Detail |
| Ease of use | Detail | Detail |

**Verdict:** [Which is better for what use case]
```

### Timeline (for event sequences, changelogs, history)

```markdown
## Timeline: [Topic]

- **[Date/Version]** — What happened and why it matters
- **[Date/Version]** — What happened and why it matters
- **[Date/Version]** — What happened and why it matters

**Trend:** [Overall direction or pattern]
```

## Summarization Rules

1. **Preserve specifics** — keep exact numbers, version numbers, dates, names, and measurements. "Revenue grew 23% to $4.2B" not "Revenue grew significantly."

2. **Target 20-30% of original length** — unless the user specifies "brief" (~10%) or "detailed" (~50%).

3. **Front-load the most important point** — readers may only read the first bullet.

4. **Flag contradictions** — if the source contains conflicting information, call it out explicitly rather than picking one side.

5. **Separate facts from opinions** — "The author claims X" vs "The data shows X."

6. **Include source context** — when summarizing a URL, include the page title, publication date (if visible), and the URL itself.

7. **Acknowledge limitations** — if content was truncated, behind a paywall, or partially loaded, say so.

## Length Control

| User Request | Target Length |
|-------------|---------------|
| "TL;DR" or "one line" | 1-2 sentences |
| "brief summary" | 3-5 bullet points |
| "summarize" (default) | 5-10 bullet points with sections |
| "detailed summary" | Comprehensive with all sections |
| "summarize in N words" | Respect the explicit word count |

## Multi-Source Summarization

When summarizing multiple URLs or files:

```
1. Summarize each source independently first
2. Identify common themes across sources
3. Note where sources agree and disagree
4. Produce a unified summary with per-source citations

## Unified Summary

### Theme 1
- Point from Source A
- Corroborated by Source B
- Source C disagrees: [their view]

### Theme 2
...

### Sources
1. [Title A](url-a) — summarized on [date]
2. [Title B](url-b) — summarized on [date]
```
