# Retrofit mode: moving a repo's units off its checkout

For a repo whose units still run `/home/<user>/<repo>`, with a `BUILD_ID` git stamp, a main-checkout guard, or an `ExecStartPre=` that syncs. Seven cohort repos were in this state when #372 was planned (replicator, usa-wa, watcher, notifier, wslcb-licensing-tracker, power-map, address-validator); replicator goes first (replicator#151).

The work is mostly inventory and cutover, which a bootstrap never does. It lands in the repo's own tree under its own issue. Its decisions go in a design note from [assets/design-note.md.tmpl](../assets/design-note.md.tmpl), and the cutover runs in the host's own session with the operator.

## 1. Inventory

Record each in the design note; every one changes what the hooks or the units say.

- **Units and timers:** every `deploy/` unit, and what's installed in `/etc/systemd/system` that the repo doesn't have. Handler templates (`<repo>-failure-notify@.service`) carry their own `WorkingDirectory=` and are units like any other.
- **Environment:** every `EnvironmentFile=`, and which secrets each unit actually reads. A repo `.env` drops out entirely, since units read `/etc/<repo>/` only. `/etc/<repo>/.env` may hold secrets: don't assume a settings-only file.
- **Written paths:** every path a unit writes under its `WorkingDirectory`. A release is read-only, so each moves to `StateDirectory=`, `/var/lib/<repo>` or `/run/<repo>`.
- **`ExecStartPre=` lines,** each classed as *deploy-time integrity* (moves into the build or `post_build_check`) or *runtime health* (stays, running from the release). A wheelhouse sync is neither: it is retired with the move to the co-pypi index ([#632](https://github.com/gregoryfoster/skills/issues/632)).
- **`uv` sources by kind** (registry, git, path, find-links), and how each resolves inside a `git archive`: a path source outside the repo doesn't, and a `.wheelhouse` lock is refused.
- **Hand-run production steps** in AGENTS.md or CLAUDE.md, such as `alembic upgrade head` from the checkout.
- **Checkout guards in `src/`.** Removing the `ExecStartPre=` guard is not enough: grep `src/` for an in-process check of the branch, the checkout path or `.git`, which refuses every write when the code runs from a release (replicator).

## 2. Contract fallout

- **The build field** in the health endpoint changes source (`REVISION`, not git) and may change format. A repo with a changelog trigger or a vendored client owes a CHANGELOG entry and a regenerated client.
- **`Settings`** must read only the env files it can open. systemd exports a root-only `EnvironmentFile=` before switching user, and pydantic-settings raises on an `env_file` it can't read (observo#695).

## 3. Safety gaps the move exposes

- Alembic not asserting the database it is about to migrate is the configured one (CannObserv/status#15).
- No schema check, where `/ready` can't be added unauthenticated.
- The old main-checkout guard, which is **deleted, not ported**.
- **The oldest deployable commit.** A commit from before the move has no release shape and can never be a rollback target. Name it in the design note (observo's rollback drill went forward, back, forward on its first two releases).

## 4. The design note

From [assets/design-note.md.tmpl](../assets/design-note.md.tmpl), at `docs/plans/<date>-releases.md` in the repo. Its D-table answers broker#22's Q1–14. The core settles most of them, so a row says "as the core" unless the repo differs, and the note cites the pilot whose answer it adopts.

## 5. The cutover runbook

In the host's own session, with the operator. Each step is checked before the next.

1. **The operator's one-time steps** from the repo's `DEPLOYMENT.md`: the root, `/etc/<repo>/` and the credentials, and the service user when it is a dedicated one. A retrofit starts on `exedev` (D2), with the dedicated user as a named follow-up issue.
2. **Credential paths first.** Anything a unit reads from the old tree (a key under `~/<repo>`, a profile pointing at a checkout file) moves *before* the restart, or the first verify fails and switches back (observo#699).
3. **`scripts/deploy.sh --no-restart`:** builds the release, migrates, switches `live`, installs the units, and restarts nothing.
4. **Restart and verify:** `sudo systemctl restart <units>`, then `scripts/deploy.sh` again, which reuses the release and verifies each unit.
5. **Prove branch-switch invariance:** switch the checkout to another branch, restart a unit, and check its build id is unchanged.
6. **Drill a rollback:** deploy the previous build (`scripts/deploy.sh <sha12>`), then the current one again.

## 6. Cleanup

- Delete `.skills/worktree_venv` (its `.pth` hazard shrinks once no unit runs the checkout's venv), and set `.skills/deploy_command` to `scripts/deploy.sh`.
- Rewrite any installed-unit parity test to compare with the **live release**, never the working tree, or it goes red on every merge not yet deployed (CannObserv/archiver#330).
- Remove the hand-run production steps from AGENTS.md, CLAUDE.md and the README.
- Retire any agent memory or doc line that says the checkout runs the timers.
- File the follow-ups the design note names: the dedicated user, and any unit left on the checkout on purpose (broker#22 Q11: a dev service that runs the dev tree is named, so it can't become a loophole).
