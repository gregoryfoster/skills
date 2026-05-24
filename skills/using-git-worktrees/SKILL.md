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

## Worktree root resolution

Every operation resolves the worktree directory in this order (first match wins):

1. **`WORKTREE_ROOT` env var** (highest priority) — explicit override for one-off invocations
2. **`.skills/worktree_root` file** — single-line file under the repo root; project's persistent default
3. **`<repo-root>/.worktrees/`** — fallback when neither of the above is set

Invoke `bash scripts/resolve-worktree-root.sh` to print the resolved root. The final worktree path is always `<resolved-root>/<branch-slug>`, where `<branch-slug>` is the branch name with `/` replaced by `-` (e.g., `feature/foo` → `feature-foo`).

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
bash scripts/worktree-create.sh <branch>          # existing branch
bash scripts/worktree-create.sh --new <branch>    # create the branch too
```

The script:
- Resolves the worktree root
- Refuses if `<branch>` is already checked out elsewhere (per the Iron Law)
- Runs `git worktree add <root>/<slug> <branch>` (or `add -b <branch> <root>/<slug>` with `--new`)
- Prints the absolute worktree path on stdout
- Exits 0 on success, 1 on Iron Law violation (double checkout), 2 on tooling failure

### Phase 3 — Work inside the worktree

`cd` into the worktree path printed by Phase 2. Two responsibilities the calling agent must handle (the upstream skill cannot prescribe specifics — projects vary):

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
2. `cd` to the main checkout — its path is the first row of `bash scripts/worktree-list.sh` (or `git worktree list | head -n1 | awk '{print $1}'`)
3. `git switch main` (or the project's default branch)
4. `git merge <branch>` — or open a PR if the project requires review; consult AGENTS.md for the project's PR-vs-direct-merge policy
5. Confirm the merge succeeded before Phase 5

If the branch is **descoped** (will not be merged), document why before Phase 5: a one-line note in the related issue or PR. The descope reason is required input to `worktree-destroy.sh --descoped <reason>`.

### Phase 5 — Destroy the worktree

```bash
bash scripts/worktree-destroy.sh <branch>
bash scripts/worktree-destroy.sh <branch> --descoped "<reason>"
bash scripts/worktree-destroy.sh <branch> --base <ref>   # verify merge into <ref> instead of project default
```

The script:
- Verifies the branch is an ancestor of the base ref (the actual "merged" check, not just "pushed"). Default base resolution: `.skills/default_branch` → origin's HEAD → `main`, preferring `origin/<base>` over local `<base>` so unpublished local merges don't fool the gate. Pass `--base <ref>` to verify against an explicit non-default integration branch instead (e.g., `batch/<x>` in a multi-agent orchestration); the supplied ref is used as-given. Refuses if the branch is not merged AND `--descoped <reason>` was not supplied.
- If `<worktree>/.port` exists, kills any process bound to that port via `lsof -ti tcp:<port>` (portable to macOS + Linux). Falls back to a warning if `lsof` isn't installed.
- Runs `git worktree remove <path>`
- Runs `git worktree prune` to clean stale metadata
- Exits 0 on success, 1 on Iron Law violation (unmerged work without `--descoped`), 2 on tooling failure

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
