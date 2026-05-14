---
name: shipping-work-php
description: "Finalizes work by ensuring everything is committed, pushed to the remote, and reflected on GitHub: closes issues, posts summary comments, and presents a completion table. Use when the user says 'ship it', 'push GH', 'close GH', or 'wrap up'."
compatibility: Designed for PHP 8.4 WordPress/Bedrock/Sage 11 monorepos with Composer. Requires git, gh, composer, php.
metadata:
  author: gregoryfoster
  version: "1.0"
  triggers: ship it, push GH, close GH, wrap up
---

# Shipping Work — PHP

Finalizes work: pre-ship checks, clean commit, push, GitHub issue comments, and closure. Tuned for PHP/WordPress/Bedrock/Sage 11 monorepos.

## The Iron Law

```
NO PUSH WITHOUT PASSING PRE-SHIP CHECKS — VERIFIED IN THIS SESSION
NO ISSUE CLOSURE WITHOUT FULL IMPLEMENTATION — VERIFIED AGAINST ORIGINAL REQUIREMENTS
```

## Rationalization prevention

| Thought | Reality |
|---|---|
| "Checks passed earlier in this session" | Run them again. State can change. Require fresh output. |
| "It's basically done, just needs minor cleanup" | Incomplete = not done. Finish or explicitly descope before closing. |
| "The issue will track follow-up work" | Only close if the core requirement is fully met. Open a new issue for follow-up. |
| "gh push is failing, I'll skip it" | Resolve the error. Do not mark as shipped without a successful push. |
| "User is in a hurry" | A bad ship is slower than a good one. Run the checklist. |

## Parameterized invocation

Trigger phrases may include scope inline — e.g., `wrap up #19 #20`, `ship it #14`. Apply the appended issue numbers as the explicit scope (step 1 of Scope detection); skip the conversation-context fallback.

## Scope detection

Determine which GitHub issue(s) to close (priority order):
1. **Explicit scope** — user specifies issue number(s)
2. **Conversation context** — issues referenced in recent commit messages or discussion
3. **Ask** — if ambiguous, confirm before closing anything

## Procedure

### Step 1 — Run pre-ship checks

```bash
bash scripts/pre-ship.sh
```

> Lint runs 4 parallel `php -l` workers by default; tune via `PRE_SHIP_PHP_LINT_JOBS=N bash scripts/pre-ship.sh` for very large monorepos.

```
NO CONTINUATION IF CHECKS FAIL
```

If checks fail: stop, report the failure, fix before proceeding. Do not push failing code under any circumstances.

### Step 1.5 — Documentation spot-check

```bash
bash scripts/doc-check.sh
```

`doc-check.sh` lists files changed on this branch vs the upstream default branch and flags any that match the project's `SENSITIVE_PATHS` array (AGENTS.md, README.md, composer files, theme/plugin dirs, ACF JSON, `.env.example`). When sensitive paths change, the matching doc sections may need updates too.

If the script exits 1: review the listed files, decide whether each requires a doc update, and either commit the docs now or note them as deliberate skips. If the script exits 2: an infra/tooling problem prevented the doc check from running — investigate the underlying error rather than proceeding.

### Step 2 — Ensure a clean working tree

```bash
bash scripts/check-status.sh
```

If uncommitted changes exist, commit them following the project convention. Check AGENTS.md for project-specific overrides. Default format:

```
#<number> [type]: <description>       # with GH issue
[type]: <description>                 # without GH issue
```

Common `[type]` values: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`.

Multiple issues: `#19, #20 [type]: <description>`

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

<HARD-GATE>
Before closing any issue, verify the original requirements against what was implemented:
1. Re-read the issue body
2. Confirm each stated requirement is addressed in commits
3. If any requirement is missing: do NOT close — ask the user whether to descope or continue
</HARD-GATE>

```bash
bash scripts/close-issue.sh <number>
```

### Step 7 — Report

Present a summary table:

| Issue | Title | Status | Comment |
|---|---|---|---|
| #19 | ... | ✅ Closed | Summary posted |

### Step 8 — Next-steps notification

After the summary table, review commits and changes shipped to identify any post-deploy work the user may need to perform. Common categories for WordPress/Bedrock/Sage 11:

| Category | Trigger | Example action |
|---|---|---|
| ACF JSON sync | `acf-json/` changed | `wp acf import` or "Sync changes" in admin |
| Asset build | `resources/assets/` changed | `yarn bud build` then `wp acorn view:clear` |
| WP-CLI cache | Code change touching cached output | `wp cache flush; wp rewrite flush` |
| Composer deps | `composer.lock` changed | `composer install --no-dev` on deploy box |
| Env vars | `.env.example` updated | Propagate to production `.env` |

Present only the items that apply. Be specific — name the file, command, or path. Then **offer to execute** any item within your capabilities (e.g., running `wp cache flush` against a local environment). Ask once — don't nag.

If nothing applies, omit this step entirely.

## Notes

- If `gh` CLI hits errors (e.g., Projects API changes), use `--json` flag workarounds as needed
- The project's AGENTS.md is authoritative for commit conventions — read it before committing
