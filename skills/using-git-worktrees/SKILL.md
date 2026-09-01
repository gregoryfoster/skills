---
name: using-git-worktrees
description: A workflow for parallel branch checkouts via `git worktree`. Standardizes creation, lifecycle, and cleanup so multiple branches can be worked on simultaneously without colliding. Use when the user says "create worktree", "new worktree", "destroy worktree", "merge worktree", or "wt".
compatibility: Designed for Claude (claude.ai, Claude Code, or similar). Requires git. `lsof` is used for port cleanup in Phase 5 when a worktree records its dev-server port; install if needed.
metadata:
  author: gregoryfoster
  version: "1.0"
  triggers: create worktree, new worktree, destroy worktree, merge worktree, wt
---

# Using Git Worktrees

A workflow for parallel branch checkouts via `git worktree`. Standardizes creation, lifecycle, and cleanup so multiple branches can be worked on without colliding.

**Activation triggers:** "create worktree", "new worktree", "destroy worktree", "merge worktree", "wt".

## The Iron Law

```
NO WORKTREE DESTROY WITHOUT VERIFIED MERGE OR EXPLICIT DESCOPE
NO BRANCH CHECKED OUT IN TWO WORKTREES SIMULTANEOUSLY
```

If the branch hasn't been merged (or the user hasn't explicitly waived the merge), you cannot destroy the worktree.
If the target branch is already checked out in another worktree (visible in `git worktree list`), you cannot create another worktree for it — git refuses, and so do we.

## Rationalization prevention

| Thought | Reality |
|---|---|
| "I'll merge later, just destroy it" | Destroy = work loss if commits aren't on a tracked branch. Merge or document descope first. |
| "Same branch in two worktrees is fine, I'll be careful" | Git refuses for a reason — divergent commits race. Use a different branch or a separate clone. |
| "The dev server is still running, but I want to destroy now" | Free the port first. A live process pinning files in the worktree blocks cleanup and leaks state. |
| "Every branch needs a worktree" | Short patches don't. Phase 1 exists to filter; skip it and you pay the overhead for nothing. |
| "The project has no wrapper, I'll just `cd ~/wherever`" | Resolution order is explicit: env var → `.skills/worktree_root` → default. Ad-hoc paths defeat reproducibility. |

## Parameterized invocation

Trigger phrases may include the target branch inline — e.g., `create worktree feature/foo`, `wt feature/foo`, `destroy worktree feature/foo`. Apply the appended branch as the explicit target; skip the "ask for branch name" fallback.

## Script path resolution

The skill's `scripts/` directory is not at the project root — it ships inside the skill. Resolve it once, then substitute the printed path wherever `<SKILL_SCRIPTS>` appears below ([#63](https://github.com/gregoryfoster/skills/issues/63)):

<!-- skill:required -->
```bash
N=using-git-worktrees S=resolve-worktree-root.sh SD=
for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
  [ -f "$d/$S" ] && { SD="$d"; break; }
done
echo "SKILL_SCRIPTS=${SD:?not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}"
```

A project-local `scripts/` copy wins if one exists. `<SKILL_SCRIPTS>` is a **placeholder** for the literal path printed here, not an inherited shell variable — each Bash invocation runs in a fresh shell.

## Worktree root resolution

Every operation resolves the worktree directory in this order (first match wins):

1. **`WORKTREE_ROOT` env var** (highest priority) — explicit override for one-off invocations
2. **`.skills/worktree_root` file** — single-line file under the repo root; project's persistent default
3. **`<repo-root>/.worktrees/`** — fallback when neither of the above is set

Invoke `bash "<SKILL_SCRIPTS>/resolve-worktree-root.sh"` to print the resolved root. The final worktree path is always `<resolved-root>/<branch-slug>`, where `<branch-slug>` is the branch name with `/` replaced by `-` (e.g., `feature/foo` → `feature-foo`).

## Venv linking — `.skills/worktree_venv`

A worktree inherits no virtualenv, so `worktree-create.sh` symlinks the main checkout's `.venv` into it. The knob turns that off:

```bash
echo none > .skills/worktree_venv    # `link` (default) | `none`
```

Set it to `none` when **the main checkout is also a running service's `WorkingDirectory=`**. The symlink then hands every worktree one shared *mutable* environment while isolating it in every other respect, and the service's own tooling rewrites that environment under a worktree's test run. Two symptoms identify the case (uv 0.10.4; the shape generalizes to any tool whose *run* verb reinstalls the project):

- **`uv run` reinstalls the project.** A readiness timer running `uv run …` in the main checkout restamps `importlib.metadata.version(...)` to *main's* version mid-run, so a worktree suite on a bumped version fails `assert '0.38.0' == '0.37.0'` in a full run and passes in isolation.
- **`uv sync` prunes groups it was not asked for.** An `ExecStartPre=uv sync` deletes an opt-in dependency group whose test modules `pytest.importorskip` at module scope. Those become skips, not errors: hundreds of tests silently stop running against a suite that still reports green.

The hazard runs both ways: a worktree's own `uv sync` mutates what the live workers import from. With `none`, `worktree-create.sh` creates no `.venv` and says so on stderr; provision one — sub-second against a warm cache.

**Tracking.** Read from the **primary checkout**, like `.skills/worktree_root`, so untracked works: such a file does not exist in a linked worktree at all, and reading the current checkout would drop the opt-out exactly where it is needed. Commit it only if it holds for every clone — a service's working directory is a property of one machine, not of the repo.

## Procedure

### Phase 1 — Decide whether a worktree is appropriate

A worktree is appropriate when at least one applies:
- Branch is long-lived (days+, not minutes)
- You need to work on a different branch without disturbing the current branch's environment
- The branch requires an isolated dev server, env config, or DB state
- A reviewer needs a clean main checkout to compare against

A worktree is **not** appropriate for:
- Short patches that will be committed and merged in one sitting (`git switch` is faster)
- Branches the user will switch back to immediately

If none apply, stop. Don't create a worktree just because the trigger phrase fired.

### Phase 2 — Create the worktree

```bash
bash "<SKILL_SCRIPTS>/worktree-create.sh" <branch>          # existing branch
bash "<SKILL_SCRIPTS>/worktree-create.sh" --new <branch>    # create the branch too
```

The script:
- Resolves the worktree root
- Refuses if `<branch>` is already checked out elsewhere (per the Iron Law)
- Runs `git worktree add <root>/<slug> <branch>` (or `add -b <branch> <root>/<slug>` with `--new`)
- Symlinks the main checkout's `.venv` into the worktree when it has one, unless `.skills/worktree_venv` is `none`
- Prints the absolute worktree path on stdout
- Exits 0 on success, 1 on Iron Law violation (double checkout), 2 on tooling failure

### Phase 3 — Work inside the worktree

`cd` into the worktree path printed by Phase 2. Three responsibilities the calling agent must handle (the upstream skill cannot prescribe specifics — projects vary):

- **Interpreter environment** — a worktree inherits no `.venv` / `node_modules`. `worktree-create.sh` links a `.venv` for you, but a worktree provisioned by something else — notably the Claude Code Agent tool's `isolation: "worktree"`, which calls `git worktree add` directly — never runs it. There, link it by hand **before the first test run**:

  ```bash
  ln -s "$(dirname "$(cd "$(git rev-parse --git-common-dir)" && pwd)")/.venv" .venv
  ```

  Link, don't re-create. A symlink is by construction the same interpreter and the same installed packages; a freshly resolved environment is a *different* one that can silently collect fewer tests and still report a green suite — a failure with no error message to notice. Unless `.skills/worktree_venv` is `none` — see above.
- **Env separation** — if the project ships env files (`.env`, `/etc/<project>/.env`), copy or symlink them into the worktree. Consult the project's AGENTS.md.
- **Port allocation** — if the branch runs a dev server, allocate a distinct port so it doesn't collide with the main checkout's. Project AGENTS.md is authoritative for the scheme; if none is documented, pick an unused port and record it in `<worktree>/.port` so destroy can free it.

### Phase 3.5 — Verify worktree health

Before doing substantial work:

- `git rev-parse --show-toplevel` prints the **worktree** path (not the main checkout)
- `git status` is clean (or shows only the expected branch state)
- The dev server (if any) listens on the allocated port

If any check fails, fix before proceeding. Work in the wrong checkout silently lands on the wrong branch.

### Phase 4 — Merge back to the main checkout

When the branch is ready:

1. Commit and push from inside the worktree
2. `cd` to the main checkout — its path is the first row of `bash "<SKILL_SCRIPTS>/worktree-list.sh"` (or `git worktree list | head -n1 | awk '{print $1}'`)
3. `git switch main` (or the project's default branch)
4. `git merge <branch>` — or open a PR if the project requires review; consult AGENTS.md for the project's PR-vs-direct-merge policy
5. Confirm the merge succeeded before Phase 5

If the branch is **descoped** (will not be merged), document why before Phase 5: a one-line note in the related issue or PR. The descope reason is required input to `worktree-destroy.sh --descoped <reason>`.

### Phase 5 — Destroy the worktree

```bash
bash "<SKILL_SCRIPTS>/worktree-destroy.sh" <branch>
bash "<SKILL_SCRIPTS>/worktree-destroy.sh" <branch> --descoped "<reason>"
bash "<SKILL_SCRIPTS>/worktree-destroy.sh" <branch> --base <ref>   # verify merge into <ref> instead of project default
bash "<SKILL_SCRIPTS>/worktree-destroy.sh" <branch> --force        # required when the worktree contains submodules
bash "<SKILL_SCRIPTS>/worktree-destroy.sh" <branch> --unlock       # only when the destroy reports a held lock
bash "<SKILL_SCRIPTS>/worktree-destroy.sh" <branch> --dry-run      # preview the decision, change nothing
```

The script:
- **Finds the worktree by branch**, via `git worktree list --porcelain`, so any layout works regardless of how the directory leaf is named. Only when the branch has no registered worktree does it fall back to the `<root>/<slug>` scheme `worktree-create.sh` uses, so a mistyped branch still names a concrete path.
- Verifies the branch is an ancestor of the base ref (the actual "merged" check, not just "pushed"). Default base resolution: `.skills/default_branch` → origin's HEAD → `main`, preferring `origin/<base>` over local `<base>` so unpublished local merges don't fool the gate. Pass `--base <ref>` to verify against an explicit non-default integration branch instead (e.g., `batch/<x>` in a multi-agent orchestration); the supplied ref is used as-given. Refuses if the branch is not merged AND `--descoped <reason>` was not supplied.
- Refuses to destroy the worktree it is being run from. `cd` to the main checkout first.
- If `<worktree>/.port` exists, kills any process bound to that port via `lsof -ti tcp:<port>` (portable to macOS + Linux). Falls back to a warning if `lsof` isn't installed.
- Runs `git worktree remove <path>` (or `git worktree remove --force <path>` if `--force` was supplied)
- Runs `git worktree prune` to clean stale metadata
- Exits 0 on success, 1 on Iron Law violation (unmerged work without `--descoped`), 2 on tooling failure

**Agent-provisioned worktrees.** The Claude Code Agent tool's `isolation: "worktree"` checks out branch `worktree-agent-<id>` at `.claude/worktrees/agent-<id>/` — branch and directory leaf under different names, so no `WORKTREE_ROOT` override can reach it. Branch-first lookup handles it with no configuration and no extra flags.

**When to pass `--force`:** git's `worktree remove` refuses to act on worktrees containing checked-out submodules (`fatal: working trees containing submodules cannot be moved or removed`). If the project ships submodules (e.g., `skills-vendor/*` consumed via `managing-skills`), every destroy will hit this — pass `--force` to bypass git's submodule refusal. The Iron Law's merge gate is unaffected — `--force` only controls the final removal mechanics. **Caveat:** `--force` also bypasses git's dirty-working-tree refusal, so any uncommitted changes in the worktree are silently discarded; verify the worktree is clean before forcing.

**When to pass `--unlock`:** normally never. The Agent tool releases its lock when the agent exits, and teardown runs after that, so the plain invocation is the normal path. Pass `--unlock` only when a destroy actually reports a held lock — which means the owner is still running or died without releasing, so check which before overriding. git refuses to remove a locked worktree and `--force` is *not* the remedy: it is a single `-f`, and git demands `-f -f` for a lock. `--unlock` releases the lock and changes nothing else, so uncommitted work still blocks removal. A gitignored `.venv` symlink is invisible to git's clean check and needs neither flag.

**`--dry-run`** reports the resolved path, base ref, merge verdict, lock state and removal command, then exits without side effects — with the exit code the real run would return (1 on an Iron Law violation, 2 on a lock with no `--unlock`). Safe to point at a live worktree, including one an agent is working in.

The branch ref itself is **not** deleted — that's a separate decision. Use `git branch -d <branch>` afterward if you also want to drop the local ref.

### Auditing for zombie processes

Operators sometimes bypass `worktree-destroy.sh` (raw `git worktree remove`, manual `rm -rf`), leaving behind processes spawned from inside the now-gone worktree. Run the audit script to surface them. From the consuming project's repo root:

```bash
bash skills/using-git-worktrees/scripts/audit-worktree-zombies.sh         # prints zombies, exits 1 if any
bash skills/using-git-worktrees/scripts/audit-worktree-zombies.sh --quiet # silent; exit code only — wire into pre-flight
```

Adjust the path prefix when the skill is vendored under a different layout (e.g. `skills-vendor/<owner>-<repo>/skills/using-git-worktrees/scripts/audit-worktree-zombies.sh`).

Detection-only — it does not kill anything. The operator decides whether to kill the listed PIDs.

## Project-local wrapper scripts

When a project ships a wrapper (e.g., `./infrastructure/scripts/dev.sh worktree create|destroy`), it must invoke the upstream scripts under the hood, not reimplement them. The wrapper may:

- Pre-populate env files
- Allocate a port and write it to `<worktree>/.port`
- Run extra bootstrap (`composer install`, `npm install`, `uv sync`)

Wrappers must not silently bypass the Iron Law gates. If the wrapper genuinely needs to skip a gate, it must pass the explicit `--descoped <reason>` flag through to the upstream script — never delete the check.

## Notes

- `git worktree list` is authoritative — never maintain a separate registry
- A branch may be deleted while a worktree on it exists; reattach with `git worktree repair` if you need to recover
- Bare repositories: out of scope; the consumers covered by this skill are all non-bare

**Self-budget:** held to a **6,000-token ratchet (estimate and exact)** by
`tests/structural/test_skill_self_budget.py` — both readings must clear it, so
no choice of measurement can loosen it.
