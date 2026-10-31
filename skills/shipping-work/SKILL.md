---
name: shipping-work
description: "Finalizes work by ensuring everything is committed, pushed to the remote, and reflected on GitHub: closes issues, posts summary comments, and presents a completion table. Use when the user says 'ship it', 'push GH', 'close GH', or 'wrap up'. This is the fallback of last resort — use it for any stack with no dedicated shipping-work-* variant (Go, Rust, TypeScript, Java, and anything else unlisted)."
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git and gh CLI.
metadata:
  author: gregoryfoster
  version: "2.0"
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

<!-- skill:required id=skill-scripts -->
```bash
N=shipping-work
{ [ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh; } || exit 1
for S in doc-check.sh check-status.sh push.sh comment-issue.sh close-issue.sh pre-ship.sh; do SD=
  for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
    [ -f "$d/$S" ] && { SD="$d"; break; }
  done
  [ -n "$SD" ] || echo "$S not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/" >&2
  echo "<$S>=${SD:?}/$S"
done
bash "${SD:?}/$S"
```

The first line is a preflight: when `.skills/doctor.sh` is present, it heals any dangling vendor symlinks (or reports an actionable error); when absent, the group is a no-op. `|| exit 1` skips `pre-ship.sh` if the doctor reports unrecoverable state so the original "No such file or directory" noise doesn't drown out the doctor's message. The loop then resolves each script against the skill directory rather than the cwd — a bare `scripts/` path resolves relative to the project root, where the script does not exist ([#63](https://github.com/gregoryfoster/skills/issues/63)). A project-local `scripts/<name>` still wins, for that script alone: a `scripts/pre-ship.sh` — a wrapper that loads what the project needs and execs the skill's gate, or a whole gate for a toolchain the skill's cannot detect — must not send the other five looking beside it ([#301](https://github.com/gregoryfoster/skills/issues/301)). A script found nowhere stops the block here, by name. `pre-ship.sh` is listed last, so the final line runs it. Resolution runs *after* the doctor so a freshly healed symlink chain is visible to it.

In every later step a `<name.sh>` is a **placeholder** for the path printed for that script — substitute it literally (same convention as `init-project-fastapi` Phase 0). Each Bash invocation runs in a fresh shell, so nothing the block set is inherited.

```
NO CONTINUATION IF CHECKS FAIL
```

If pre-ship fails: stop, report the failure, fix before proceeding. Do not push failing code under any circumstances.

`pre-ship.sh` detects what the repo has and runs every check each toolchain owns: ruff check and format, an import check and pytest for uv; `composer validate`, `php -l` and `composer test` for composer; the declared `lint:js` / `format:js:check` / `test:js` for npm. Every check runs before it fails, naming each failure. Nothing detected is exit 1, never a pass. A pass on this exact tree is recorded and reused (`GATE_STAMP=off` forces a run). Why each check runs as it does, and the knobs: [references/gate-topology.md](references/gate-topology.md).

Its first line reads `Detected: …`. For each `framework <name>` there, read that framework's file before Step 1.5 — its doc-check defaults and its Step 8 next steps: [references/stack-fastapi.md](references/stack-fastapi.md), [references/stack-click.md](references/stack-click.md), [references/stack-php.md](references/stack-php.md).

### Step 1.5 — Documentation spot-check

```bash
bash "<doc-check.sh>"
```

`doc-check.sh` lists files changed on this branch vs the upstream default branch and flags any that match the project's sensitive-path list: AGENTS.md, README.md and each detected framework's paths (listed in its stack file), or a generic list of schema files and public-API directories when none is detected. Entries match path *segments*, so `src/api/` also covers `packages/<pkg>/src/api/`. When sensitive paths change, the matching doc sections may need updates too. Projects tailor the list by committing `.skills/doc-sensitive-paths` at the repo root (one path per line, `#`-comments ignored); it replaces the defaults rather than extending them. The advice printed on a hit — which doc sections to spot-check — is tailored the same way, by committing `.skills/doc-sections` (one section per line, same grammar); it too replaces the defaults. Tailor both together: the list says what the gate watches and the sections say what to do about a hit, so a repo that tailors only the list gets advice written for a stack it may not have. A hit says so when exactly one of the two is tailored, naming the half that is still the default.

If the script exits 1: review the listed files, decide whether each requires a doc update, and either commit the docs now or note them as deliberate skips. If the script exits 2 — or any code not named here, such as 127 when its path did not resolve — the doc check did not run: investigate the underlying error rather than proceeding. One exit-2 case is worth naming: when no entry in the list matches any tracked file, the script says so instead of passing, because a list that cannot hit anything would otherwise print the same clean green as a genuinely doc-neutral branch. Fix the list; do not wave the step through. The same goes for anything the project committed under `.skills/` that the script cannot use, the directory included: a tailoring never silently reverts to the built-in defaults, so an exit 2 there means the override is unusable, not absent.

### Step 2 — Ensure a clean working tree

```bash
bash "<check-status.sh>"
```

If the script exits 2, `git status` itself failed: the tree state is **unknown**, which is not the same as clean. Any code but 0 or 1 is no verdict either (127: the script was not found). Investigate the error rather than proceeding ([#257](https://github.com/gregoryfoster/skills/issues/257)).

If uncommitted changes exist, commit them following the project convention. Check AGENTS.md for project-specific overrides. Default format:

```
#<number> [type]: <description>       # with GH issue
[type]: <description>                 # without GH issue
```

Common `[type]` values: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`.

Multiple issues: `#19, #20 [type]: <description>`

### Step 2.5 — Worktree-aware merge (if applicable)

If this checkout is a worktree (test: `git rev-parse --show-toplevel` differs from the main checkout, listed first in `git worktree list`):

1. Commit current changes inside the worktree (Step 2 above)
2. Invoke `using-git-worktrees` Phase 4 to merge the branch back into the main checkout before continuing
3. The remaining steps (push, GH comments, close) run from the main checkout

If this is a single (non-worktree) checkout, skip this step.

### Step 3 — Ensure on main

If Step 2.5 applied, the merge already happened — you're on `main` in the main checkout; continue.
If Step 2.5 did not apply (single checkout) and you're on a feature branch, merge to `main` first.

### Step 4 — Push

```bash
bash "<push.sh>"
```

Confirm push succeeded before proceeding.

### Step 5 — Comment on GitHub issues

For each issue in scope:

```bash
bash "<comment-issue.sh>" <number> "<summary>"
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
bash "<close-issue.sh>" <number>
```

### Step 7 — Report

Present a summary table:

| Issue | Title | Status | Comment |
|---|---|---|---|
| #19 | ... | ✅ Closed | Summary posted |

### Step 8 — Next-steps notification

After the summary table, review commits and changes shipped to identify any post-deploy work the user may need to perform. A detected framework's stack file lists its own categories; use those. Otherwise, common categories:

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

**Self-budget:** held to a **6,000-token ratchet (estimate and exact)** by
`tests/structural/test_skill_self_budget.py` — both readings must clear it, so
no choice of measurement can loosen it.
