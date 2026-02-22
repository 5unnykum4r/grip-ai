---
title: Temporal Memory
description: Give grip time awareness — schedule reminders, track deadlines, and reference temporal context
category: memory
---
# Temporal Memory

> Give grip time awareness — schedule reminders, track deadlines, and reference temporal context in conversations.

## When to Use

Activate this skill when the user:
- Asks to be reminded about something later
- References time-based deadlines or schedules
- Wants to track temporal events or milestones
- Needs time-relative context ("what did I do yesterday?", "follow up in 2 hours")

## Time Awareness Protocol

### Step 1: Parse Temporal Intent

Extract the temporal components from the user's request:

- **Absolute time**: "at 3pm", "on March 15", "next Monday"
- **Relative time**: "in 2 hours", "tomorrow morning", "next week"
- **Recurring**: "every day at 9am", "weekly on Fridays"
- **Contextual**: "after the deploy", "when tests pass", "before the meeting"

### Step 2: Select the Right Mechanism

| Intent | Mechanism | Tool |
|--------|-----------|------|
| One-time reminder | Cron job with auto-delete | `exec_command` to write cron script |
| Recurring reminder | Persistent cron entry | `exec_command` + cron skill |
| Deadline tracking | Knowledge base entry | `write_file` to MEMORY.md |
| Time-relative query | Search history by date | `search_memory` tool |

### Step 3: Implement Time-Aware Actions

**For reminders and scheduled tasks:**

```bash
# Calculate target timestamp
target=$(date -d "+2 hours" "+%Y-%m-%d %H:%M")

# Create a cron-compatible reminder
# Use the cron skill for proper scheduling
```

Write reminder entries to the knowledge base with format:
```
[REMINDER] {timestamp} | {message} | status: pending
```

**For temporal queries ("what happened yesterday?"):**

1. Calculate the date range from the natural language reference
2. Search HISTORY.md for entries matching that date range
3. Search MEMORY.md consolidated entries by date headers
4. Present findings chronologically

### Step 4: Track and Update

After creating any temporal entry:
1. Confirm the scheduled time with the user in their local timezone
2. Write the entry to MEMORY.md under a `## Scheduled` section
3. If using cron, verify the cron job was registered successfully

## Temporal Context Injection

When building context for any conversation, scan MEMORY.md for:
- Upcoming deadlines within the next 24 hours
- Overdue items that haven't been addressed
- Recently completed scheduled tasks

Format these as temporal context hints:
```
[Upcoming] Deploy deadline: tomorrow 5pm UTC
[Overdue] Follow-up with API team (was due 2 hours ago)
[Done] Daily standup notes submitted at 9:15am
```

## Date Parsing Reference

| Input | Interpretation |
|-------|---------------|
| "in 30 minutes" | now + 30m |
| "tomorrow" | next day 09:00 local |
| "tomorrow morning" | next day 09:00 local |
| "tomorrow evening" | next day 18:00 local |
| "next week" | next Monday 09:00 local |
| "end of day" | today 17:00 local |
| "EOD Friday" | this/next Friday 17:00 local |

## Integration with Cron Skill

For scheduled execution, delegate to the cron skill:
- Use `at`-style one-shot jobs for reminders
- Use crontab entries for recurring schedules
- Always include cleanup logic for one-shot reminders (remove after firing)

## Limitations

- Time precision depends on cron granularity (1 minute minimum)
- Timezone handling uses the system timezone unless the user specifies otherwise
- Reminders only fire if grip's gateway is running at the scheduled time
