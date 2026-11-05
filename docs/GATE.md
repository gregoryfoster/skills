# This repo's gate: what runs when

The structural suite (`tests/structural/`) is this repo's test gate. It runs at
three points, and only the first may run part of it
([#537](https://github.com/gregoryfoster/skills/issues/537), plan
[2026-11-05-impacted-test-selection.md](plans/2026-11-05-impacted-test-selection.md)).

| When | Script | Runs |
|---|---|---|
| `git commit` (pre-commit hook) | `scripts/structural-tests.sh` | the test files the staged paths reach, or everything when a change is shared or no map exists |
| `bash scripts/pre-ship.sh` | the same script | the full suite, unless this exact tree already passed it |
| `git push` (pre-push hook) | `scripts/pre-push-gate.sh` | the full suite on the pushed commit's tree, unless that tree already passed it |

A partial run never records a pass. Only a full pass lets pre-ship or pre-push
skip, so nothing leaves this machine without the full suite having passed on
exactly what is pushed.

## The map

Every full run that passes is traced by `tests/utils/gate_trace.py`. Its
audit hook records which repo paths each test file opens, lists or hands to a
subprocess, and which commands it runs from inside the repo.
`scripts/gate_select.py build` turns that into
`<git-common-dir>/gate-map.json`. The map is not committed: it is rebuilt by
each full pass, and shared by every worktree.

Each test file depends on some of:

- a skill directory: anything under `skills/<name>/`;
- a file or a listed directory;
- the whole tree: it listed the repo root or `skills/`, or ran an
  interpreter, or git not aimed at a fixture, from inside the repo.

## What a commit runs

| Staged change | Runs |
|---|---|
| a test file | that file |
| `skills/<name>/…` | every test depending on that skill |
| `docs/plans/…` | nothing extra |
| `tests/…` but a test file, `scripts/…`, hooks, `pyproject.toml`, requirements, `.pre-commit-config.yaml`, `.github/` | the full suite |
| anything else | every test that read it |

Every whole-tree test, and every test file the map has never seen, runs on
every commit.

## Knobs and logs

- `GATE_SELECT=off` makes the commit hook run everything.
- `GATE_STAMP=off` makes every gate run, reusing nothing.
- Each partial run appends a line to `<git-common-dir>/gate-select.log`: the
  time, the seconds it took, the files run, the files on disk, and its exit
  code. A full run's record is in `gate-stamp.sh list`.

## Installing the hooks

`pre-commit install` installs both stages, because `.pre-commit-config.yaml`
sets `default_install_hook_types`. A checkout that installed the hooks before
the pre-push stage existed needs `pre-commit install --hook-type pre-push`
once.

The pre-push hook blocks when the suite cannot run (no venv), as pre-ship does.
