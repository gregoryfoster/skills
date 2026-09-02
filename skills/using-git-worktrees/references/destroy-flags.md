# Destroy flags in depth

When each `worktree-destroy.sh` flag is the right instrument, and what each one
does **not** cover. The invocations and the one-line rules stay in
[SKILL.md](../SKILL.md#phase-5--destroy-the-worktree); this is the reasoning
behind them, which a destroy needs only when a flag is actually in question.

## Worktrees the harness provisioned

The Claude Code Agent tool's `isolation: "worktree"` checks out branch `worktree-agent-<id>` at `.claude/worktrees/agent-<id>/` — branch and directory leaf under different names, so no `WORKTREE_ROOT` override can reach it. Branch-first lookup handles it with no configuration and no extra flags.

## `--force`

git's `worktree remove` refuses to act on worktrees containing checked-out submodules (`fatal: working trees containing submodules cannot be moved or removed`). If the project ships submodules (e.g., `skills-vendor/*` consumed via `managing-skills`), every destroy will hit this — pass `--force` to bypass git's submodule refusal. The Iron Law's merge gate is unaffected — `--force` only controls the final removal mechanics. **Caveat:** `--force` also bypasses git's dirty-working-tree refusal, so any uncommitted changes in the worktree are silently discarded; verify the worktree is clean before forcing.

## `--unlock`

Normally never. The Agent tool releases its lock when the agent exits, and teardown runs after that, so the plain invocation is the normal path. Pass `--unlock` only when a destroy actually reports a held lock — which means the owner is still running or died without releasing, so check which before overriding. git refuses to remove a locked worktree and `--force` is *not* the remedy: it is a single `-f`, and git demands `-f -f` for a lock. `--unlock` releases the lock and changes nothing else, so uncommitted work still blocks removal. A gitignored `.venv` symlink is invisible to git's clean check and needs neither flag.

## `--dry-run`

It reports the resolved path, base ref, merge verdict, lock state and removal command, then exits without side effects — with the exit code the real run would return (1 on an Iron Law violation, 2 on a lock with no `--unlock`). Safe to point at a live worktree, including one an agent is working in.
