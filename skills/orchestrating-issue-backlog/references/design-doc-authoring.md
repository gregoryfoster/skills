# Authoring the design doc when `main` is not writable

Step 8 of [`SKILL.md`](../SKILL.md) commits the backlog design doc directly to
`main` by default. This file carries the alternatives, which apply only when a
feature branch + PR is forced — a host project that enforces filesystem
isolation for plan creation (a workspace-isolation pre-commit hook naming
"spec/plan creation" as an in-worktree activity), or a user who wants a review
checkpoint before agents launch.

Demoted from the body in #161: every run reaches the *decision*, but only a run
that answers it "feature branch" needs the routes.

Choose one of three.

## 1. Merge the doc PR before launching workers

Cleanest. Workers' local `main` sees the doc on disk, so nothing about the
launch sequence changes.

## 2. Include the plan in the Agent tool's prompt when launching each worker

Workers do not actually need the doc on disk to function. Acceptable when the
user wants the doc PR to land alongside the batch branch rather than ahead of
it.

## 3. Write the plan inside a docs-only worktree, then merge from `main`

For projects whose worktree-create tooling supports a lightweight "no DB clone /
docs-only" flag (e.g. `--shared-db` in `cannabis.observer-wordpress`).

```bash
# provision the worktree with the project's own script, then:
git -C <worktree> commit -F /tmp/<branch>-msg.txt   # apostrophe-safe
git merge --no-ff <branch>                          # from the main checkout
# destroy the worktree
```

`-F <file>` rather than `-m` for the same reason Step 9 passes `--body-file` to
`gh issue create`: an apostrophe in the message breaks the heredoc form even
under single quotes.
