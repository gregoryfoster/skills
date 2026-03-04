---
name: shipping-work-claude
description: "Finalizes work by ensuring everything is committed, pushed to the remote, and reflected on GitHub: closes issues, posts summary comments, and presents a completion table. Use when the user says 'ship it', 'push GH', 'close GH', or 'wrap up'."
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git and gh CLI.
metadata:
  author: gregoryfoster
  version: "1.0"
  triggers: ship it, push GH, close GH, wrap up
---

# Shipping Work

Finalizes work: clean commit, push, GitHub issue comments, and closure.

## Scope detection

Determine which GitHub issue(s) to close (priority order):
1. **Explicit scope** — user specifies issue number(s) (e.g., `wrap up #19 #20`)
2. **Conversation context** — issues referenced in recent commit messages or discussion
3. **Ask** — if ambiguous, confirm before closing anything

## Procedure

### Step 1 — Run tests

If tests haven't been run this session, run them now before proceeding. Do not push failing tests.

### Step 2 — Ensure a clean working tree

```bash
bash scripts/check-status.sh
```

If uncommitted changes exist, commit them following the project convention. Check AGENTS.md for the project's commit message format. Default:
```
#<issue>: <type>: <description>
```
For multiple issues: `#19, #20: feat: description`

### Step 3 — Ensure on main

If on a feature branch, merge to `main` first. Then continue.

### Step 4 — Push

```bash
bash scripts/push.sh
```

Confirm push succeeded before proceeding.

### Step 5 — Comment on GitHub issues

For each issue in scope:

```bash
bash scripts/comment-issue.sh <number> "<summary>"
```

Comment must include:
- What was implemented (2–4 bullets)
- Key commit SHAs or commit range
- Any follow-up items or known limitations

### Step 6 — Close GitHub issues

```bash
bash scripts/close-issue.sh <number>
```

Never close an issue that wasn't fully implemented — ask first if uncertain.

### Step 7 — Report

Present a summary table:

| Issue | Title | Status | Comment |
|---|---|---|---|
| #19 | ... | ✅ Closed | Summary posted |

## Notes

- If `gh` CLI hits errors (e.g., Projects API changes), use `--json` flag workarounds as needed
- The project's AGENTS.md is authoritative for commit conventions — read it before committing
