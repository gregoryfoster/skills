---
name: shipping-work
description: "Finalizes work by ensuring everything is committed, pushed to the remote, and reflected on GitHub: closes issues, posts summary comments, and presents a completion table. Use when the user says 'ship it', 'push GH', 'close GH', or 'wrap up'."
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git and gh CLI.
metadata:
  author: gregoryfoster
  version: "1.3"
  triggers: ship it, push GH, close GH, wrap up
---

# Shipping Work

Finalizes work: clean commit, push, GitHub issue comments, and closure.

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
N=shipping-work S=pre-ship.sh
{ [ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh; } || exit 1
for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
  [ -f "$d/$S" ] && { SD="$d"; break; }
done
echo "SKILL_SCRIPTS=${SD:?not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}"
bash "$SD/$S"
```

The first line is a preflight: when `.skills/doctor.sh` is present, it heals any dangling vendor symlinks (or reports an actionable error); when absent, the group is a no-op. `|| exit 1` skips `pre-ship.sh` if the doctor reports unrecoverable state so the original "No such file or directory" noise doesn't drown out the doctor's message. The loop then resolves the script against the skill directory rather than the cwd — a bare `scripts/` path resolves relative to the project root, where the script does not exist ([#63](https://github.com/gregoryfoster/skills/issues/63)). A project-local `scripts/` copy still wins if one exists; `${SD:?…}` fails loudly with the searched paths when no candidate resolves. Resolution runs *after* the doctor so a freshly healed symlink chain is visible to it.

Step 1 prints `SKILL_SCRIPTS=<path>`. In every later step `<SKILL_SCRIPTS>` is a **placeholder** for that literal path — substitute the value printed here (same convention as `init-project-fastapi` Phase 0). Each Bash invocation runs in a fresh shell, so the shell variable itself is not inherited.

```
NO CONTINUATION IF CHECKS FAIL
```

If pre-ship fails: stop, report the failure, fix before proceeding. Do not push failing code under any circumstances.

### Step 1.5 — Documentation spot-check

```bash
bash "<SKILL_SCRIPTS>/doc-check.sh"
```

`doc-check.sh` lists files changed on this branch vs the upstream default branch and flags any that match the project's `SENSITIVE_PATHS` array (AGENTS.md, README.md, schema files, public-API directories, etc.). When sensitive paths change, the matching doc sections may need updates too.

If the script exits 1: review the listed files, decide whether each requires a doc update, and either commit the docs now or note them as deliberate skips. If the script exits 2: an infra/tooling problem prevented the doc check from running — investigate the underlying error rather than proceeding. If the project doesn't ship a `doc-check.sh`, skip this step.

### Step 2 — Ensure a clean working tree

```bash
bash "<SKILL_SCRIPTS>/check-status.sh"
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
bash "<SKILL_SCRIPTS>/push.sh"
```

Confirm push succeeded before proceeding.

### Step 5 — Comment on GitHub issues

For each issue in scope:

```bash
bash "<SKILL_SCRIPTS>/comment-issue.sh" <number> "<summary>"
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
bash "<SKILL_SCRIPTS>/close-issue.sh" <number>
```

### Step 7 — Report

Present a summary table:

| Issue | Title | Status | Comment |
|---|---|---|---|
| #19 | ... | ✅ Closed | Summary posted |

### Step 8 — Next-steps notification

After the summary table, review commits and changes shipped to identify any post-deploy work the user may need to perform. Common categories:

| Category | Trigger | Example action |
|---|---|---|
| DB migration | `schema.sql` changed, new table/column/index | `apply_schema` or restart service |
| Service restart | Any production code change (no auto-reload) | `systemctl restart power-map` or gunicorn signal |
| Data migration | New normalizer, field rename, backfill script | Run the relevant `scripts/` file |
| Env var / secret | New config key added | Add to `/etc/power-map/env` and restart |
| Index bootstrap | New unique index on dirty table | Deduplicate first, then re-run `apply_schema` |

Present only the items that apply. Be specific — name the file, table, or command. Example:

```
**Next steps for production:**
- `apply_schema` required — `schema.sql` changed (new `link_types`/`links` tables + migration)
- Restart uvicorn/gunicorn — code changes don't auto-reload in production
```

Then **offer to execute** any item within your capabilities (e.g., running `apply_schema`, running a migration script). Ask once — don't nag.

If nothing applies, omit this step entirely.

## Notes

- If `gh` CLI hits errors (e.g., Projects API changes), use `--json` flag workarounds as needed
- The project's AGENTS.md is authoritative for commit conventions — read it before committing
