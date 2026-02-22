---
title: GitHub
description: Interact with GitHub repositories, issues, pull requests, and CI/CD workflows
category: devops
---
# GitHub

> Interact with GitHub repositories, issues, pull requests, and CI/CD workflows using the gh CLI. Use when the user mentions GitHub, issues, PRs, CI checks, releases, or repository management.

## Prerequisites

The `gh` CLI must be installed and authenticated:

```bash
# Check if gh is available
gh auth status

# If not authenticated
gh auth login
```

## Issues

```bash
# List open issues (default: 30)
gh issue list

# Filter by label, assignee, or milestone
gh issue list --label "bug" --assignee "@me"
gh issue list --milestone "v1.0" --state all

# Create an issue
gh issue create --title "Fix login timeout" --body "Users experience 30s timeout on login page" --label "bug"

# View issue details and comments
gh issue view 42
gh issue view 42 --comments

# Close with a comment
gh issue close 42 --comment "Fixed in PR #45"

# JSON output for programmatic use
gh issue list --json number,title,labels,assignees --jq '.[] | "\(.number): \(.title)"'
```

## Pull Requests

```bash
# List open PRs
gh pr list

# Create a PR from current branch
gh pr create --title "Add user auth" --body "Implements JWT-based authentication"

# Create with reviewers and labels
gh pr create --title "Fix timeout" --reviewer "teammate" --label "bug,urgent"

# View PR details: diff stats, checks, reviews
gh pr view 45
gh pr view 45 --comments

# Check CI status on a PR
gh pr checks 45

# Review a PR (approve, comment, or request changes)
gh pr review 45 --approve --body "LGTM, clean implementation"
gh pr review 45 --request-changes --body "Need error handling on line 42"

# Merge strategies
gh pr merge 45 --squash --delete-branch
gh pr merge 45 --rebase
gh pr merge 45 --merge
```

## CI/CD Workflows

```bash
# List recent workflow runs
gh run list --limit 10

# View a specific run (shows jobs and steps)
gh run view 123456

# View failed step logs (most useful for debugging CI)
gh run view 123456 --log-failed

# Watch a running workflow in real-time
gh run watch 123456

# Re-run a failed workflow
gh run rerun 123456

# Re-run only failed jobs
gh run rerun 123456 --failed

# List workflows (not runs)
gh workflow list
```

## Advanced API Queries

Use `gh api` for operations not covered by built-in commands:

```bash
# Get repository info
gh api repos/{owner}/{repo}

# List contributors
gh api repos/{owner}/{repo}/contributors --jq '.[].login'

# Get PR review comments
gh api repos/{owner}/{repo}/pulls/45/comments --jq '.[] | "\(.user.login): \(.body)"'

# Get commit status checks
gh api repos/{owner}/{repo}/commits/{sha}/status

# Search across repos
gh api search/issues -f q="repo:{owner}/{repo} is:issue label:bug is:open" --jq '.items[] | "\(.number): \(.title)"'

# Paginate results (100 per page, page 2)
gh api repos/{owner}/{repo}/issues --method GET -f per_page=100 -f page=2
```

## Common Workflows

### Triage Incoming Issues

```bash
# See unlabeled issues
gh issue list --label "" --limit 50
# Then label and assign
gh issue edit 42 --add-label "bug,P1" --add-assignee "@me"
```

### Debug a Failed CI Run

```bash
gh run list --status failure --limit 5
gh run view <run-id> --log-failed
# Read the failed logs, identify the error, then fix locally
```

### Create a Release

```bash
gh release create v1.0.0 --title "v1.0.0" --notes "First stable release" --target main
# With auto-generated release notes
gh release create v1.1.0 --generate-notes
```

### "What Changed?" Bug Finder

When debugging a recently broken feature, use git to find the exact delta and ask the LLM to analyze it.

```bash
# Get the diff of the last commit or between working state and current
git log -p -1
# Pass this output to the LLM to identify potential breaking changes
```

### Git "Therapist" Message Committer

Analyze the git diff and write highly empathetic, context-aware commit messages autonomously.

```bash
# Get the current diff
git diff --staged
# Ask the LLM to generate an empathetic commit message based on the diff, then commit it
# e.g., git commit -m "chore: Removed traumatic spaghetti code from auth flow. I feel lighter."
```

### Automated PR Generation & Code Review

Autonomously write perfect PR descriptions and assign reviewers based on the branch diff.

```bash
# Push the current branch and create a PR with an LLM-generated title and body from the diff
gh pr create --title "<LLM_GENERATED>" --body "<LLM_GENERATED>" --reviewer "@teammate"
```

## Output Formatting

Always use `--json` and `--jq` when you need to process results programmatically:

```bash
# Get PR titles and authors as JSON
gh pr list --json title,author --jq '.[] | "\(.author.login): \(.title)"'

# Count issues by label
gh issue list --json labels --jq '[.[].labels[].name] | group_by(.) | map({label: .[0], count: length}) | sort_by(-.count)'
```
