# Deploying through `.skills/deploy_command`

Without the knob, Step 8 assumes the main checkout *is* the deployment, so
shipping is "migrate, then restart". That stops being true when a project's
production runs immutable releases, with a deploy script as the only way code
reaches a unit ([#345](https://github.com/gregoryfoster/skills/issues/345)).
It is wrong there both ways:

- **`systemctl restart <project>` restarts the old release.** It deploys
  nothing, but it reads as though it did.
- **A hand migration runs outside the deploy's order.** The deploy migrates,
  switches, verifies and can switch back. A migration run from the checkout
  goes straight to live, skipping the deploy's rehearsal and its rollback
  check.

## The knob

`.skills/deploy_command` names the command, as one line, in the **primary
checkout**: the first `git worktree list` entry, as for `worktree_root`. The
command runs from that checkout's root.

```
# .skills/deploy_command
setsid -w scripts/deploy.sh
```

- **Grammar.** One command line of whitespace-separated words. Blank lines and
  whole-line `#` comments are ignored. There's no shell evaluation, so a pipe,
  a redirect or `&&` belongs in the project's script, not here. A first word
  without a `/` is looked up on `PATH`, so a repo script needs its path:
  `scripts/deploy.sh` or `./deploy.sh`, never a bare `deploy.sh`.
- **The SHA.** `run-deploy-command.sh` appends the SHA that was pushed as the
  last argument (the operator's decision, 2026-10-30). The line above runs as
  `setsid -w scripts/deploy.sh <sha>`. HEAD must equal its upstream, so only
  pushed code is deployed.
- **Detaching is the command's job.** `setsid -w` gives the deploy its own
  session and still waits, so its exit code is the deploy's. A plain `setsid`
  returns as soon as the deploy has started, so a 0 means it started, not that
  it worked. With such a command, the HARD-GATE's production clause needs the
  project's own check, such as `/health`'s revision against the pushed SHA.
- **Non-interactive.** The command's stdin is `/dev/null`, so a prompt fails
  rather than hangs. Use `sudo -n` in the project's script, never a bare
  `sudo`. A deploy can outlast a shell tool's default timeout, so run it with a
  long one.

## `run-deploy-command.sh`

| Exit | Meaning | Step 8 does |
|---|---|---|
| 0 | the command exited 0 (`--check`: the knob is usable, and the line is printed) | report the tail of its output; Step 6 may close |
| 1 | the command exited non-zero; its own code is printed | report the code and output verbatim, and close no issue |
| 2 | nothing ran: the knob (or `.skills/merge_mode`) is unusable, HEAD isn't what was pushed, in `pr` mode HEAD isn't the default branch, or git failed | fix what it names; a present but unusable knob never reads as absent |
| 3 | no knob | today's Step 8: the next-steps table |

**Non-zero means failure, whatever the code.** The project documents its own
codes. CannObserv/status's deploy uses 1 for "failed, switched back" and 4 for
"a target is left on a build that doesn't answer". The skill doesn't need to
know them: any non-zero exit means stop and report.

**`--check` runs nothing.** It is Step 8's offer line. A project's CI or its
own `scripts/pre-ship.sh` wrapper can also run it, to check that the named
command exists and is executable. Not `.skills/doctor.sh`: that file is a
vendored copy, and its own sync rewrites it.

## What the knob changes

- **Step 3.** With the knob set, a local merge into the main checkout deploys
  nothing, so it is safe. Without it, a checkout that is a unit's
  `WorkingDirectory=` is production, and merging into it *is* deploying.
- **In `pr` mode** (`.skills/merge_mode`, [pr-mode.md](pr-mode.md)) the
  deploy waits for the post-merge pass, and the script refuses (exit 2)
  unless HEAD is on the default branch as well as equal to its upstream. A
  pushed feature branch passes the upstream check, so without this the
  branch tip would deploy unreviewed. Absent or `direct`, the branch isn't
  checked: Step 3 has already put the agent on the default branch.
- **Step 8 runs before Step 6.** When an issue's "Done when" is about what
  production runs, the HARD-GATE can pass only after the deploy, so Step 8
  moves between Steps 5 and 6.
- **The next-steps table loses two rows.** The command owns the DB migration
  rows and the service restart row. The others stay: data migration,
  integration tests, index bootstrap, and env var or secret. A row the new
  code needs in place first, such as an env var it reads, is done *before*
  the deploy, and its "then restart" becomes the deploy.
- **`.skills/pre_restart` isn't run.** It guards the default table's restart
  rows; with this knob the deploy command owns the restart, so it runs its
  own reachability check, as its first step.

## What it doesn't do

- **No second command for checking afterwards.** A post-deploy check, such as
  CannObserv/observo's root-only re-run of its live guards, goes inside the
  deploy command, as its verify step. The command's exit code is then the
  whole verdict, and the skill trusts no green run that skipped it.
- **It doesn't generate the release layout.** That is the project's own
  packaging step (CannObserv/broker#22).
