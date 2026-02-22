---
title: Cron
description: Schedule tasks, reminders, and recurring jobs
category: automation
always_loaded: true
---
# Cron

> Schedule tasks, reminders, and recurring jobs. Use when the user wants to automate, set reminders, run periodic checks, or schedule one-time future actions.

## Scheduling Patterns

### Reminders — Send a Message at a Specific Time

The agent sends a message directly to the user. No task execution, just notification.

**IMPORTANT:** When creating cron jobs from a channel session (Telegram, Discord, Slack), always include `--reply-to` with the current session key so results are delivered back to the user. The session key is available in Runtime Info.

```bash
# CLI: add a daily standup reminder at 9 AM (from a channel session)
grip cron add "standup-reminder" "0 9 * * 1-5" "Remind the user: daily standup in 15 minutes" --reply-to "telegram:12345"

# One-time reminder for tomorrow at 3 PM
grip cron add "meeting-prep" "0 15 22 2 *" "Remind the user: prepare slides for the 4 PM client meeting" --reply-to "telegram:12345"

# From CLI (no --reply-to needed, results are logged)
grip cron add "disk-check" "0 */6 * * *" "Check disk usage with df -h"
```

### Tasks — Execute and Report Results

The agent runs a full agent loop (with tool access) and sends the result. Use for automated checks, reports, and maintenance. Always include `--reply-to` when running from a channel so results reach the user.

```bash
# Check disk usage every 6 hours (from Telegram)
grip cron add "disk-check" "0 */6 * * *" "Check disk usage with df -h. If any partition exceeds 85%, alert the user with specifics." --reply-to "telegram:12345"

# Weekly dependency audit on Mondays at 8 AM
grip cron add "dep-audit" "0 8 * * 1" "Run uv pip list --outdated in the project directory. Summarize packages with available updates." --reply-to "telegram:12345"

# Daily git log summary at 6 PM
grip cron add "git-summary" "0 18 * * 1-5" "Run git log --oneline --since=yesterday in ~/projects/main. Summarize today's commits." --reply-to "telegram:12345"
```

### Management Commands

```bash
grip cron list                    # Show all scheduled jobs with next run time
grip cron remove <job-id>         # Delete a job permanently
grip cron enable <job-id>         # Re-enable a paused job
grip cron disable <job-id>        # Pause without deleting
```

## Cron Expression Reference

```
┌───────────── minute (0-59)
│ ┌───────────── hour (0-23)
│ │ ┌───────────── day of month (1-31)
│ │ │ ┌───────────── month (1-12)
│ │ │ │ ┌───────────── day of week (0-7, 0 and 7 = Sunday)
│ │ │ │ │
* * * * *
```

| Expression | Meaning |
|------------|---------|
| `*/15 * * * *` | Every 15 minutes |
| `0 * * * *` | Every hour on the hour |
| `0 9 * * 1-5` | Weekdays at 9 AM |
| `0 0 * * 0` | Sundays at midnight |
| `0 9,17 * * *` | At 9 AM and 5 PM daily |
| `30 8 1 * *` | 8:30 AM on the 1st of each month |
| `0 */4 * * *` | Every 4 hours |

### Natural Language CRON Generation

When the user gives a natural language scheduling request (e.g., "every tuesday at 5pm"), always translate it into the proper cron syntax (`0 17 * * 2`) before using the `grip cron add` command. 

## Writing Effective Cron Prompts

The prompt field is what the agent executes. Write it as a clear instruction:

**Good**: "Check the grip API health endpoint at localhost:18800/health. If it returns anything other than 200, restart the service with `grip serve` and notify the user."

**Bad**: "Check health" (too vague — the agent won't know which service, what endpoint, or what to do on failure)

Include:
1. What to check or do (specific commands, paths, URLs)
2. Success criteria (what "normal" looks like)
3. Failure action (what to do when something is wrong)
4. Notification preference (always report, or only on failure)

## API Endpoints

```
GET    /api/v1/cron              # List all jobs
POST   /api/v1/cron              # Create job: {name, schedule, prompt, enabled}
DELETE /api/v1/cron/{id}         # Delete job
POST   /api/v1/cron/{id}/enable  # Enable job
POST   /api/v1/cron/{id}/disable # Disable job
```

## Session Isolation

Each cron job runs with its own session key (`cron:<job-id>`), keeping its conversation history separate from interactive sessions. This means a cron job remembers its own past runs but doesn't pollute your main chat history.

## Channel Delivery

When a cron job has a `reply_to` session key (set via `--reply-to`), its output is automatically sent to that channel and chat. This is how reminders reach Telegram, Discord, or Slack users. Always set `--reply-to` to the current session key when creating cron jobs from channel conversations.
