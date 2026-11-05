# The refresh hook's timeout budget ([#572](https://github.com/gregoryfoster/skills/issues/572))

Read this when a consumer's pre-commit or pre-push suite is slow, or when the hook's log ends part way through a test run. The hook's other mechanics are in [the parent reference](../auto-refresh-hook.md).

## The budget

The harness kills the hook at its `timeout`: 120 s, from `skills-submodule-update.install`. A consumer can raise it on its own entry, but only to 300 s, because the in-progress marker's owner is believed for at most `MARKER_MAX_AGE` (300 s). Everything a refresh does runs inside that budget:

- the heal and the reconcile of an earlier run's leftovers;
- the fetch and the submodule update;
- the doctor install;
- the commit, through the consumer's **pre-commit** hooks;
- the push, through its **pre-push** hooks.

The hook never passes `--no-verify`, so a consumer whose hooks run a full test suite spends the budget there. CannObserv/power-map's suite took about 550 s on a pointer-only commit and CannObserv/cli's took 112 s. A killed run leaves nothing on stderr. Its log ends mid-`pytest`, and since [#555](https://github.com/gregoryfoster/skills/issues/555) the next session tries again ([#575](https://github.com/gregoryfoster/skills/issues/575) tracks the back-off).

## `.skills/refresh-skip-hooks`

The fix is a list of the pre-commit hook ids that the hook's own commit and pushes skip. The ids go in the file one or more per line, separated by spaces, and a line that starts with `#` is a comment. The hook adds them to pre-commit's `SKIP` for its `git commit` and its `git push` only. An existing `SKIP` is kept and the ids are appended to it. A commit someone makes by hand still runs every hook.

```
# The full suite. pytest-vendored still runs on the refresh's commit.
pytest
ty
```

- **`pr` mode:** the commit is built with `git commit-tree`, which runs no hooks, and the push to `skills/submodule-refresh` carries the ids.
- **An unusable knob** (an id with a comma, a `#` after an id, no ids at all, or a path that is not a readable file) skips nothing. The commit runs every hook, and stderr says why, once per run.
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

Before this knob, power-map and cli each wrapped their slow stages in a gate that recognised the hook's commit from its staged paths: registered `skills-vendor/` gitlinks plus `.skills/doctor.sh`. That list copies the hook's `COMMIT_PATHS`, and a path added to it would silently send every consumer back to the full suite. A path list also cannot tell the hook's commit from one made by hand, so the gate needed checks for deleted paths, gitlinks replaced by files, and a doctor turned into a symlink, each added only after review found it missing. Marking the commit in the hook needs none of them. To adopt the knob, delete the local gate, list its slow hook ids in the knob, and move its subset into a hook of its own. Land the knob in the same commit as the pin bump, or before it.

## Timing in the log

Each phase writes `timing: <phase> done at <N>s` to `.git/skills-update.log`. The phases are `refresh` (the update and the doctor), then `commit` and `push`, or `pull request` in `pr` mode. `N` counts from the hook's start. A refresh that passes 90 s prints one stderr line naming its time and the knob, before the timeout arrives with no warning. A run killed by `SIGKILL` writes nothing more, so its log ends at the last phase it finished.
