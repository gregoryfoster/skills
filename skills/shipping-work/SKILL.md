---
name: shipping-work
description: "Finalizes work by ensuring everything is committed, pushed to the remote, and reflected on GitHub: runs the pre-ship gate, closes issues, posts summary comments, and presents a completion table. One skill for every stack: it detects the toolchain (uv, composer, npm) and framework (FastAPI, Click, PHP) and runs each tool's checks, and a repo it cannot detect supplies its own scripts/pre-ship.sh. Use when the user says 'ship it', 'push GH', 'close GH', or 'wrap up'."
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
for S in doc-check.sh check-status.sh push.sh comment-issue.sh close-issue.sh run-deploy-command.sh run-pre-restart.sh read-next-steps.sh merge-mode.sh pre-ship.sh; do SD=
  for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
    [ -f "$d/$S" ] && { SD="$d"; break; }
  done
  [ -n "$SD" ] || echo "$S not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/" >&2
  echo "<$S>=${SD:?}/$S"
done
bash "${SD:?}/$S"
```

The first line is a preflight: when `.skills/doctor.sh` is present, it heals any dangling vendor symlinks (or reports an actionable error); when absent, the group is a no-op. `|| exit 1` skips `pre-ship.sh` if the doctor reports unrecoverable state so the original "No such file or directory" noise doesn't drown out the doctor's message. The loop then resolves each script against the skill directory rather than the cwd — a bare `scripts/` path resolves relative to the project root, where the script does not exist ([#63](https://github.com/gregoryfoster/skills/issues/63)). A project-local `scripts/<name>` still wins, for that script alone: a `scripts/pre-ship.sh` — a wrapper that loads what the project needs and execs the skill's gate, or a whole gate for a toolchain the skill's cannot detect — must not send the others looking beside it ([#301](https://github.com/gregoryfoster/skills/issues/301)). A script found nowhere stops the block here, by name. `pre-ship.sh` is listed last, so the final line runs it. Resolution runs *after* the doctor so a freshly healed symlink chain is visible to it.

In every later step a `<name.sh>` is a **placeholder** for the path printed for that script — substitute it literally (same convention as `init-project-fastapi` Phase 0). Each Bash invocation runs in a fresh shell, so nothing the block set is inherited.

```
NO CONTINUATION IF CHECKS FAIL
```

If pre-ship fails: stop, report the failure, fix before proceeding. Do not push failing code under any circumstances.

`pre-ship.sh` detects what the repo has and runs every check each toolchain owns: ruff check and format, an import check and pytest for uv; `composer validate`, `php -l` and `composer test` for composer; the declared `lint:js` / `format:js:check` / `test:js` for npm. Every check runs before it fails, naming each failure. Nothing detected is exit 1, never a pass. A pass on this exact tree is recorded and reused (`GATE_STAMP=off` forces a run). Why each check runs as it does, and the knobs: [references/gate-topology.md](references/gate-topology.md).

Its first line reads `Detected: …`. For each `framework <name>` there, read that framework's file before Step 1.5 — its doc-check defaults and its Step 8 next steps: [references/stack-fastapi.md](references/stack-fastapi.md), [references/stack-click.md](references/stack-click.md), [references/stack-php.md](references/stack-php.md). On `undetermined framework`, judge from the members' dependencies.

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

**`pr` mode:** check it in either checkout shape. `bash "<merge-mode.sh>"` prints `direct` (no `.skills/merge_mode`: this procedure as written) or `pr`, where work lands through a PR merged on GitHub and each step's `pr` line below replaces what it names ([references/pr-mode.md](references/pr-mode.md)). Exit 2: the knob is unusable; fix it, never read it as `direct`. Here: no Phase 4 merge; stay on the branch, in the worktree or not. A PR already merged starts the post-merge pass (Step 8) instead.

### Step 3 — Ensure on main

If Step 2.5 applied, the merge already happened — you're on `main` in the main checkout; continue.
If Step 2.5 did not apply (single checkout) and you're on a feature branch, merge to `main` first.

Without `.skills/deploy_command`, a checkout that is a unit's `WorkingDirectory=` is production: merging into it, or in `pr` mode the post-merge pass's pull, *is* deploying. With the knob set, production runs what the deploy command builds, so a local merge deploys nothing.

**`pr` mode:** no merge. Refuse to ship from the default branch itself, or a detached HEAD: there is nothing to open a PR from. The HARD-GATE (Step 6) runs here, before the PR opens.

### Step 4 — Push

```bash
bash "<push.sh>"
```

Confirm push succeeded before proceeding.

**`pr` mode:** this pushes the branch. Then open the PR with `Closes #<n>` per in-scope issue, or let the push update an open one; `gh pr view` finds merged and closed PRs too, so read its `state`.

### Step 5 — Comment on GitHub issues

For each issue in scope:

```bash
bash "<comment-issue.sh>" <number> "<summary>"
```

Comment must include:
- What was implemented (2–4 bullets)
- Key commit SHAs or commit range

Then up to three sections, last and in this order. A `coordinating-epics` check-in harvests them, so spell the leads exactly:
- `**Follow-up:**` work left for later, with its issue if filed
- `**Known limits:**` what shipped unverified, or with an accepted gap
- `**For #N:**` a note for later issue N, one lead per issue

Each lead is its own line, a blank line before it, its notes list items under it (a plain paragraph falls outside it). Leave an empty section out; never write "none".

**`pr` mode:** the comment links the PR, above the sections.

### Step 6 — Close GitHub issues

With `.skills/deploy_command` or `.skills/pre_restart` set, run Step 8 first and close after it: a requirement about what production runs can't be checked before the deploy or restart.

<HARD-GATE>
Before closing any issue, verify the original requirements against what was implemented:
1. Re-read the issue body
2. Confirm each stated requirement is addressed in commits
3. If any requirement is missing: do NOT close — ask the user whether to descope or continue
4. With `.skills/deploy_command` set: if a requirement concerns what production runs, the deploy has run and exited 0 in this session. A failed deploy closes nothing
5. With `.skills/pre_restart` set: such a requirement needs the check to have passed in this session. A refusal closes nothing
</HARD-GATE>

```bash
bash "<close-issue.sh>" <number>
```

**`pr` mode:** close nothing: the merge closes each `Closes #<n>` issue. With `.skills/deploy_command`, a production requirement gets `Refs #<n>` instead, closed by the post-merge pass once the deploy exits 0.

### Step 7 — Report

Present a summary table:

| Issue | Title | Status | Comment |
|---|---|---|---|
| #19 | ... | ✅ Closed | Summary posted |

**`pr` mode:** Status reads `PR #<m> open, awaiting review`.

### Step 8 — Deploy, or next-steps notification

**`pr` mode:** this step waits for the **post-merge pass**, the next "ship it" once the PR shows merged: in the main checkout, `git switch <default>` and `git pull --ff-only`, then this step there (`run-deploy-command.sh` refuses any branch but the default), then the held issues, then `using-git-worktrees` Phase 5.

**With `.skills/deploy_command` set**, the project deploys through its own command, and this step runs after Step 5, before Step 6 ([references/deploy-command.md](references/deploy-command.md)):

1. List the rows that apply, from the source below, **minus** the DB migration and service restart rows: the command owns them. Do a row the new code needs first, such as an env var it reads, before the deploy.
2. `bash "<run-deploy-command.sh>" --check` prints the command line, with the pushed SHA last. If it exits 2, fix what it names before offering. Offer to run it, once. On a yes, run `bash "<run-deploy-command.sh>"`.
3. Report its exit status and the tail of its output. Exit 1 is a failed deploy: quote the command's own exit code and output verbatim, and close nothing. Exit 2 means nothing ran; fix what it names. A command that detaches without waiting exits 0 once the deploy has *started*, so check production the project's own way before Step 6.

**Without it** (`--check` exits 3), after the summary table (with `.skills/pre_restart` set, after Step 5, before Step 6), review commits and changes shipped to identify any post-deploy work the user may need to perform, from one source, and name it. `bash "<read-next-steps.sh>"` prints the project's own rows (`.skills/next-steps`, [#564](https://github.com/gregoryfoster/skills/issues/564)), which replace the rest; exit 2: fix the file, never fall back. Exit 3: the detected framework's stack file, else these common categories:

| Category | Trigger | Example action |
|---|---|---|
| DB migration | `schema.sql` changed, new table/column/index | `apply_schema` or restart service |
| Service restart | Any production code change (no auto-reload) | `systemctl restart <project>` or gunicorn signal |
| Data migration | New normalizer, field rename, backfill script | Run the relevant `scripts/` file |
| Env var / secret | New config key added | Add to the project's env file and restart |
| Index bootstrap | New unique index on dirty table | Deduplicate first, then re-run `apply_schema` |

Present only the items that apply, under **Next steps for production**, each naming its file, table or command. Then **offer to execute** any within your capabilities, once — don't nag.

Before offering a row that restarts the service (a DB migration, a restart, an env var's restart; any project row, as those can't be told apart), run `bash "<run-pre-restart.sh>"`, the project's check (`.skills/pre_restart`, [#557](https://github.com/gregoryfoster/skills/issues/557)). Exit 1: it refused, so offer none of those rows; quote its code and output verbatim, and close no issue whose "Done when" is about production. Exit 2: fix the knob. Exit 3: no check.

If nothing applies, omit this step entirely.

## Notes

- If `gh` CLI hits errors (e.g., Projects API changes), use `--json` flag workarounds as needed
- The project's AGENTS.md is authoritative for commit conventions — read it before committing

**Self-budget:** held to a **6,000-token ratchet (estimate and exact)** by
`tests/structural/test_skill_self_budget.py` — both readings must clear it, so
no choice of measurement can loosen it.
