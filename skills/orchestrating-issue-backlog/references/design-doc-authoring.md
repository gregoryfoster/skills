# Authoring and publishing the backlog design doc

Step 8 of [`SKILL.md`](../SKILL.md) commits the backlog design doc in the
orchestrator's worktree and pushes it to `main` before launching workers, by default. This file carries why the
push is not optional, and the alternatives for when a feature branch + PR is
forced instead — a host project that enforces filesystem isolation for plan
creation (a workspace-isolation pre-commit hook naming "spec/plan creation" as
an in-worktree activity), or a user who wants a review checkpoint before agents
launch.

Demoted from the body in #161: every run reaches the *decision*, but only a run
that answers it "feature branch" needs the routes.

## Why the push is half of the default

Worker worktrees are cut from `origin/main`, independent of the orchestrator's
checked-out branch (Rule 3 in [`execution.md`](execution.md)). A doc committed
in the orchestrator's worktree and left unpushed is therefore on disk for the orchestrator and
for nobody else — and the gap is invisible from the orchestrator's side, since
it can read the very plan it is briefing from while every worker's tree lacks
it. Committing on `main` is the cheap default only once the push is counted as
part of it. Skip the push and you are running route 2 below at *best* — and
only if you happened to brief the plan in every worker prompt anyway. Skip
both and no route ran: the workers have neither the doc nor the brief, and
nothing in the launch reports it (#288).

Rule 1's pre-launch sync does not cover this. It fast-forwards the
orchestrator's worktree *from* `origin/main`; nothing about it moves a local
commit outward. Push per Rule 2 — rebased onto a fresh fetch, a fast-forward
of `orchestrate/<topic>` onto `main`.

## The alternatives

Choose one of three.

### 1. Merge the doc PR before launching workers

Cleanest. The merge puts the doc on `origin/main`, the ref worker worktrees are
cut from, so nothing about the launch sequence changes.

### 2. Include the plan in the Agent tool's prompt when launching each worker

Workers do not actually need the doc on disk to function. Acceptable when the
user wants the doc PR to land alongside the batch branch rather than ahead of
it.

### 3. Write the plan inside a docs-only worktree, then merge from `main`

For projects whose worktree-create tooling supports a lightweight "no DB clone /
docs-only" flag (e.g. `--shared-db` in `cannabis.observer-wordpress`).

```bash
# provision the worktree with the project's own script, then:
git -C <worktree> commit -F /tmp/<branch>-msg.txt   # apostrophe-safe
git merge --no-ff <branch>                          # from the orchestrator's worktree
# destroy the worktree
```

`-F <file>` rather than `-m` for the same reason Step 9 passes `--body-file` to
`gh issue create`: an apostrophe in the message breaks the heredoc form even
under single quotes.
