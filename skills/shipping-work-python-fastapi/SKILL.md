---
name: shipping-work-python-fastapi
description: "For Python/FastAPI projects (uv + ruff + pytest; Alembic migrations, systemd service restarts): finalizes work by ensuring everything is committed, pushed to the remote, and reflected on GitHub: closes issues, posts summary comments, and presents a completion table. Use when the user says 'ship it', 'push GH', 'close GH', or 'wrap up' and the project is a FastAPI service."
compatibility: Designed for Python FastAPI projects using uv, ruff, pytest. Requires git, gh, uv. pytest-cov is optional — pre-ship.sh auto-detects it and adds --no-cov when present.
metadata:
  author: gregoryfoster
  version: "1.4"
  triggers: ship it, push GH, close GH, wrap up
---

# Shipping Work — Python/FastAPI

Finalizes work: pre-ship checks, clean commit, push, GitHub issue comments, and closure. Tuned for Python FastAPI projects (uv + ruff + pytest).

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

<!-- skill:required -->
```bash
N=shipping-work-python-fastapi S=pre-ship.sh SD=
{ [ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh; } || exit 1
for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
  [ -f "$d/$S" ] && { SD="$d"; break; }
done
echo "SKILL_SCRIPTS=${SD:?not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}"
bash "${SD:?not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}/$S"
```

The first line is a preflight: when `.skills/doctor.sh` is present, it heals any dangling vendor symlinks (or reports an actionable error); when absent, the group is a no-op. `|| exit 1` skips `pre-ship.sh` if the doctor reports unrecoverable state so the original "No such file or directory" noise doesn't drown out the doctor's message. The loop then resolves the script against the skill directory rather than the cwd — a bare `scripts/` path resolves relative to the project root, where the script does not exist ([#63](https://github.com/gregoryfoster/skills/issues/63)). A project-local `scripts/` copy still wins if one exists; `${SD:?…}` fails loudly with the searched paths when no candidate resolves. Resolution runs *after* the doctor so a freshly healed symlink chain is visible to it.

Step 1 prints `SKILL_SCRIPTS=<path>`. In every later step `<SKILL_SCRIPTS>` is a **placeholder** for that literal path — substitute the value printed here (same convention as `init-project-fastapi` Phase 0). Each Bash invocation runs in a fresh shell, so the shell variable itself is not inherited.

```
NO CONTINUATION IF CHECKS FAIL
```

If checks fail: stop, report the failure, fix before proceeding. Do not push failing code under any circumstances.

### Step 1.5 — Documentation spot-check

```bash
bash "<SKILL_SCRIPTS>/doc-check.sh"
```

`doc-check.sh` lists files changed on this branch vs the upstream default branch and flags any that match the project's sensitive-path list — by default AGENTS.md, README.md, CHANGELOG.md, pyproject.toml, uv.lock, schema.sql, `alembic/versions/`, `deploy/`, route/model/core dirs, `.env.example`. Entries match path *segments*, so `src/models/` also covers `services/<svc>/src/models/` and `pyproject.toml` covers each workspace member's. When sensitive paths change, the matching doc sections may need updates too. Projects tailor the list by committing `.skills/doc-sensitive-paths` at the repo root (one path per line, `#`-comments ignored, same grammar as `.skills/import-targets`); it replaces the defaults rather than extending them. The advice printed on a hit — which doc sections to spot-check — is tailored the same way, by committing `.skills/doc-sections` (one section per line, same grammar); it too replaces the defaults. Tailor both together: the list says what the gate watches and the sections say what to do about a hit, so a repo that tailors only the list gets advice written for a stack it may not have.

If the script exits 1: review the listed files, decide whether each requires a doc update, and either commit the docs now or note them as deliberate skips. If the script exits 2: an infra/tooling problem prevented the doc check from running — investigate the underlying error rather than proceeding. One exit-2 case is worth naming: when no entry in the list matches any tracked file, the script says so instead of passing, because a list that cannot hit anything would otherwise print the same clean green as a genuinely doc-neutral branch. Fix the list; do not wave the step through. The same goes for an override file the project committed but the script cannot use — unreadable, a broken symlink, or not a regular file — so a tailoring never silently reverts to the built-in defaults.

### Step 2 — Ensure a clean working tree

```bash
bash "<SKILL_SCRIPTS>/check-status.sh"
```

If the script exits 2, `git status` itself failed: the tree state is **unknown**, which is not the same as clean. Investigate git's error rather than proceeding ([#257](https://github.com/gregoryfoster/skills/issues/257)).

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

After the summary table, review commits and changes shipped to identify any post-deploy work the user may need to perform. Common categories for Python/FastAPI:

| Category | Trigger | Example action |
|---|---|---|
| DB migration (alembic) | `alembic/versions/` changed | `uv run alembic upgrade head` (or the project's `migrate.sh`), then `systemctl restart <project>` |
| DB migration (raw SQL) | `schema.sql` changed | `apply_schema` or `systemctl restart <project>` |
| Service restart | Code change (no auto-reload in prod) | `systemctl restart <project>` |
| Integration tests | New `@pytest.mark.integration` tests | `uv run pytest -m integration` on a real env |
| Env var / secret | New config key | Add to `/etc/<project>/env` and restart |
| Dev-server cleanup | Worktree shutdown | `fuser -k <port>/tcp` for the project's port |

Present only the items that apply. Be specific — name the file, command, or path. Then **offer to execute** any item within your capabilities. Ask once — don't nag.

If nothing applies, omit this step entirely.

## Notes

- If `gh` CLI hits errors (e.g., Projects API changes), use `--json` flag workarounds as needed
- The project's AGENTS.md is authoritative for commit conventions — read it before committing
- `pre-ship.sh` auto-derives its per-SHA stamp prefix from `$(basename "$(git rev-parse --show-toplevel)")` — no project-name substitution needed

**Self-budget:** held to a **6,000-token ratchet (estimate and exact)** by
`tests/structural/test_skill_self_budget.py` — both readings must clear it, so
no choice of measurement can loosen it.
