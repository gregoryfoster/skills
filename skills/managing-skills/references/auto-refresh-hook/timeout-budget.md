# The refresh hook's timeout budget ([#572](https://github.com/gregoryfoster/skills/issues/572))

Read this when a consumer's pre-commit or pre-push suite is slow, or when the hook's log ends part way through a test run. The hook's other mechanics are in [the parent reference](../auto-refresh-hook.md).

## The budget

The harness kills the hook at its `timeout`: 120 s, from `skills-submodule-update.install`. A consumer can raise it on its own entry, but only to 300 s, because the in-progress marker's owner is believed for at most `MARKER_MAX_AGE` (300 s). Everything a refresh does runs inside that budget:

- the heal and the reconcile of an earlier run's leftovers;
- the fetch and the submodule update;
- the doctor install;
- the commit, through the consumer's **pre-commit** hooks;
- the push, through its **pre-push** hooks.

The hook never passes `--no-verify`, so a consumer whose hooks run a full test suite spends the budget there. CannObserv/power-map's suite took about 550 s on a pointer-only commit and CannObserv/cli's took 112 s. A killed run leaves nothing on stderr, and its log ends mid-`pytest`. Since [#555](https://github.com/gregoryfoster/skills/issues/555) the next session tries again. The second run in a row killed inside its commit spends the day instead, and the session that finds it says on stderr that the commit did not fit and names this knob ([#575](https://github.com/gregoryfoster/skills/issues/575)). So a suite that never fits is tried twice on the first day and once a day after, until a commit finishes. A commit the hooks refuse counts as finished: the suite fit, and the refusal spends the day anyway (CR 1900).

### A push that does not fit ([#603](https://github.com/gregoryfoster/skills/issues/603))

A kill inside the push counts toward the same total as a kill inside the commit. Before each push, the hook writes a second line to `.git/skills-update.commit-kills`: `push pid <PID> <epoch>`. When a push returns, accepted or refused, the hook deletes the file, which resets the count. If the next session finds that line and the run that wrote it has exited, it counts a kill inside the push, once, keyed on that line. The second kill in a row, whether it was inside the commit or the push, stamps the day's lock. The session that counts it says once on stderr that the push did not fit, and names this knob.

- **`direct`:** the hook pushes from its reconcile at every session start. The reconcile runs ahead of the day's lock, so a stamped lock alone would not stop the push. So the reconcile makes no push while the count is 2 or more and the lock reads today. The hook's commit stays unpushed on `main` until the next UTC day's session pushes it, unless you push it by hand first. A refused push is rolled back, but a held one is not.
- **`pr` mode:** the push to `skills/submodule-refresh` runs inside the refresh, which is already behind the day's lock.

**Known limits:**
- When two sessions push at once they share the line. A push that returns can clear a slower session's record, so that session's kill goes uncounted, and the next kill is counted.
- The extension's ~2 s kill (#555) can land inside a reconcile push and be counted. It cannot back the push off alone, because the real session a second later pushes and resets the count.
- Because the count is shared, a back-off that began with a commit also holds the reconcile's push that day.

## `.skills/refresh-skip-hooks`

The fix is a list of the pre-commit hook ids that the hook's own commit and pushes skip. The ids go in the file one or more per line, separated by spaces, and a line that starts with `#` is a comment. The hook adds them to pre-commit's `SKIP` for its `git commit` and its `git push` only. An existing `SKIP` is kept and the ids are appended to it. A commit someone makes by hand still runs every hook.

```
# The full suite. pytest-vendored still runs on the refresh's commit.
pytest
ty
```

- **pre-commit only:** `SKIP` is read by the pre-commit framework and nothing else. A consumer whose hooks come from husky, lefthook or plain scripts in `.git/hooks/` sees no change. The alternative #572 deferred until such a consumer turns up: the hook marks its commit with an environment variable tied to the live `.git/skills-update.staging` marker, and the consumer's own hook checks it.
- **`pr` mode:** the commit is built with `git commit-tree`, which runs no hooks, and the push to `skills/submodule-refresh` carries the ids.
- **An unusable knob** (an id with a comma, a `#` after an id, no ids at all, or a path that is not a readable file) skips nothing. The commit runs every hook, and stderr says why, once in each run that commits or pushes. A session that does neither says nothing, and the doctor names the bad words every time it runs.
- **A stale id:** pre-commit ignores a `SKIP` id it doesn't know, so a renamed hook comes back into the refresh's commit without any message. The doctor names every id in the knob that is neither an `id:` nor an `alias:` in `.pre-commit-config.yaml`.

### Keep the tests that read the vendored tree

Skipping the whole suite also skips the tests a pointer bump can break, such as those that read `skills-vendor/` or pin a knob to a vendored script. Run those as their own hook, always, and list their files rather than selecting them by marker. Measured in power-map and cli on 2026-11-04, `pytest -m <marker>` spent 15–21 s collecting the full suite, while a file list ran in under 3 s.

```yaml
- id: pytest-vendored
  name: tests that read skills-vendor/
  entry: uv run pytest -q tests/test_vendored_skills.py tests/test_knob_parity.py
  language: system
  pass_filenames: false
  always_run: true
```

Keep a test in the consumer that fails when a test reading the vendored tree is missing from that list. That test, not this one, is what keeps the subset complete.

## Why the hook marks its commit, not a gate inside pre-commit

Before this knob, power-map and cli each wrapped their slow stages in a gate that recognised the hook's commit from its staged paths: registered `skills-vendor/` gitlinks plus `.skills/doctor.sh`. That list copies the hook's `COMMIT_PATHS`, and a path added to it would silently send every consumer back to the full suite. A path list also cannot tell the hook's commit from one made by hand, so the gate needed checks for deleted paths, gitlinks replaced by files, and a doctor turned into a symlink, each added only after review found it missing. Marking the commit in the hook needs none of them.

**Adopting it takes one bump made the old way.** The hook runs as a symlink into `skills-vendor/`, and bash reads it whole before running it. So the refresh that first brings this release in is run by the *previous* hook, which doesn't read the knob. For a consumer whose suite doesn't fit the budget, that first bump must be made by hand (`git submodule update --remote`, then a commit through the full suite), or by a hook still running under the local gate. If the gate is deleted first, the old hook's commit is killed. The heal then puts the content back on the old pointer, so the old hook runs again at the next session, and is killed again. In order:

1. Add the knob, and move the subset into its own hook.
2. Bump the pin past this release, by hand or under the gate. Committing the knob in the same commit as the bump works.
3. Delete the gate.

## Timing in the log

Each phase writes `timing: <phase> done at <N>s` to `.git/skills-update.log`. The phases are `refresh` (the update and the doctor), then `commit`, or `pull request` in `pr` mode. `push` is logged wherever the hook pushes to the default branch, and only then. That includes the push it makes before the refresh to share an earlier run's commit. In `pr` mode the branch push is part of `pull request`. `N` counts from the hook's start. A refresh that passes 90 s prints one stderr line naming its time and the knob, before the timeout arrives with no warning. **Known limit:** the harness does not hand the hook its `timeout`, so the line stays at 90 s. A consumer that raised its entry toward 300 s gets that stderr line on every run past 90 s, though such a run is not at risk. A run killed by `SIGKILL` writes nothing more, so its log ends at the last phase it finished.
