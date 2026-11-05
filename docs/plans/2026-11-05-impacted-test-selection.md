---
title: Impacted-test selection in this repo's pre-commit, from a traced map
date: 2026-11-05
status: approved
---

# Impacted-test selection in pre-commit

Follows [#537](https://github.com/gregoryfoster/skills/issues/537) Step 10 of
[2026-10-30-gate-topology.md](2026-10-30-gate-topology.md), which deferred
selection until a measurement showed it worth building.

## Problem

Every commit through the pre-commit hook runs the whole structural suite. Since
xdist landed (2026-10-31) it is the largest remaining cost on the commit path,
and it grows with the suite. Measured 2026-11-05:

- **The gate's own record.** 133 local passes in five days, 11.3 h in total.
  At 8 workers a run takes a median of 171 s. When parallel agents share the
  machine and each gets 3–4 workers, it takes 490–540 s.
- **Today's suite.** 211 files, 1,682 s serial-equivalent, 230 s at `-n 8`.
- **A replay of 287 commits.** The selection rule below would have run a median
  of 18–39% of suite time, depending on how widely "always run" is drawn. Only
  7% of commits change something too broad to map. Simulated under
  `--dist loadfile`, that saves 139–175 s per commit at 8 workers and 295–386 s
  at 4, against the plan's bar of "roughly one minute".

The obstacle is the map. Mapping tests to skills by *name* recalled only 42 of
54 tests that commits changed alongside a skill (78%). Every miss reached its
skill indirectly: through a shared helper module (the doc-check tests) or a
script path (the refresh-hook tests). A name-based map would skip about one
relevant test in five.

## Approach

**A traced map.** Derive the test→dependency map from what each test file
actually touches, not from what it names:

- A pytest plugin installs a `sys.addaudithook` that records the repo paths
  each test file opens, lists (`os.listdir`, `os.scandir`, `glob.glob`) or
  executes (`subprocess.Popen` argv, including script arguments).
- Paths reduce to dependency units:
  - a skill directory, since a skill's scripts reach only their own directory,
    so the directory bounds what one of its bash scripts can source;
  - a root file (`AGENTS.md`, `README.md`, `docs/*.md`, `retired-skills`,
    `.skills/*`);
  - *whole tree*, for a listing of `skills/` or the root, or `git ls-files`.

**Writing the map.** Every full run writes the map under `<git-common-dir>`.
It is not committed, so it is always as fresh as the last full pass.

**Selection in pre-commit.** Under `PRE_COMMIT=1`, `structural-tests.sh` maps
the staged paths to test files. Each kind of change runs:

| Staged change | What runs |
|---|---|
| a test file | that file |
| `skills/<x>/…` | every test that depends on `<x>` or on the whole tree |
| a mapped root file | every test that read it |
| `docs/plans/**` | nothing extra |
| a test the map has never seen | that test, always |
| anything else (`tests/utils`, `conftest.py`, the shared fixtures, `scripts/`, `pyproject.toml`, requirements, hooks) | the full suite |
| no map yet, or `GATE_SELECT=off` | the full suite |

**Stamps.** A selected run never records a pass that `check` reuses. It logs
one line to `<git-common-dir>/gate-select.log` for the measurement in Step 6,
so `shipping-work`'s shared `gate-stamp.sh` needs no change.

**Backstops.** Two full runs stay as backstops:
- `pre-ship.sh`, unchanged, which also refreshes the map;
- a new `pre-push` hook. It requires a full-pass stamp for the pushed tip's
  tree and runs the full suite when there is none. A push by SHA, which is how
  this repo ships from a worktree, cannot skip it.

## Tradeoffs / alternatives

- **Status quo (full suite per commit):** rejected. On a review round's 7–10
  commits it costs 15–20 minutes against roughly 3 minutes of selected runs
  plus one full pre-ship.
- **A name-grep map:** rejected. It is cheap and needs no full run, but the
  replay measured 78% recall, so it would skip a relevant test in one commit
  out of five.
- **Static import / AST analysis:** rejected. Tests reach skills through
  `Path` joins and subprocess calls to bash, which no import graph shows.
- **coverage.py or pytest-testmon:** rejected. Both see Python lines executed,
  not a bash script run or a SKILL.md read, and those are most of what this
  suite tests. testmon would also be a new dependency on the commit path.
- **Selection in CI or for the cohort:** out of scope. This repo has no test
  CI (#537 D3). `shipping-work`'s gate is unchanged, and a cohort repo can take
  this up later through a knob.

## Steps

1. **Tracer.** A pytest plugin (`tests/utils/gate_trace.py`, beside
   `gate_durations.py`), active only when
   `GATE_TRACE=<file>` is set, writes one JSON line per test file with its
   dependency units. Structural tests cover each kind of access: open, listing,
   `glob`, `Popen` argv, a bash script under a skill, and `git ls-files`. Two
   further tests check that a tmp path never enters the map and that xdist
   workers each write their own lines.
   *Verify:* the tests pass, and a traced full run costs under 5% more wall
   clock than an untraced one (measured, and recorded in this plan).

   *Done 2026-11-05.* `test_gate_trace.py` (8 cases). Six of them go red with
   the audit hook removed; the other two are a negative case and the
   per-worker files. Overhead: on a 40-file slice at `-n 8`, interleaved
   untraced and traced runs used 122–129 s and 121–124 s of CPU. That is
   within noise. A full-suite comparison of 228 s against 343 s wall clock
   was another session's load, not the tracer. Unplanned addition: the
   tracer also records `os.symlink` targets, so a fixture that links into
   the repo and works through the link is not invisible.
2. **Map builder and selector.** `scripts/gate-select.sh` (a bash entry over
   a stdlib Python core) builds the map from the trace, and prints the selected
   test files, or `FULL` with its reason, for a list of paths. Unit tests cover
   every rule in the table above.
   *Verify:* tests pass, `--help`, and shellcheck clean. The script is
   classified as a gate script in `GATE_SCRIPTS`.
3. **Validate before switching on.**
   - Replay the 287 commits since 2026-10-31 against the traced map. The bar:
     the recall proxy reaches 54/54 co-changed tests, and the simulated
     savings stay above one minute per commit at 8 workers.
   - A mutation sample: for 10 skills chosen across the heavy and light files,
     make one breaking edit each. The failing tests of a full run must all be
     inside the selected set.

   *Verify:* both results are recorded in this plan. A miss stops the plan
   here: revise the map units, then re-run the step.
4. **Wire pre-commit.**
   - `structural-tests.sh` selects under `PRE_COMMIT=1` when a map exists,
     and prints `selected N/M files, ~X% of suite time; full run at pre-ship
     and pre-push`.
   - A selected run writes a `gate-select.log` line, never a reusable stamp.
   - Full runs carry `GATE_TRACE` and refresh the map.

   *Verify:* a commit that touches one skill runs its selection;
   `GATE_SELECT=off` runs everything; pre-ship on that tree runs the full suite
   and does not reuse the selected run.
5. **Pre-push backstop.**
   - A `pre-push` stage hook (`scripts/pre-push-gate.sh`) checks for a
     full-pass stamp on each pushed ref's tree, and runs `structural-tests.sh`
     on any miss.
   - `pre-commit install --hook-type pre-push` goes in AGENTS.md's dev setup,
     in one line, since AGENTS.md has 115 tokens of headroom. The detail goes
     in `docs/STYLE.md`'s gate section, or a new `docs/GATE.md` if STYLE.md's
     147 tokens of headroom will not hold it.

   *Verify:* pushing a tree with only selected runs triggers a full run, and
   pushing one that passed pre-ship returns in about 1 s.
6. **Measure for a week, then decide.** Report on #537, from the stamp
   history:
   - pre-commit wall clock before and after;
   - the number of pre-ship or pre-push failures on trees whose commits had all
     passed selected runs.

   *Verify:* a #537 comment with the figures. Each such failure is a false
   skip. Any false skip gets its own issue. Two or more turn selection off
   (`GATE_SELECT=off` as the default) until the map is fixed.

## Open questions / risks

- **Map staleness between full runs.** A commit that makes a test newly depend
  on a skill changes that test file, so the test is selected. But the map does
  not know the new dependency until the next full run. Pre-ship and pre-push
  bound the gap to one push.
- **A test that depends on something the hook cannot see:** an env var, the
  network, or a file outside the repo. It is mapped to nothing beyond itself.
  The mutation sample in Step 3 is the check. Anything it surfaces becomes a
  *whole tree* unit.
- **Red intermediate commits.** A false skip leaves a commit that is red at
  the time it was made, while main stays green because of the backstops.
  `reviewing-code`'s blanket fixes revert the offending commit when the final
  gate goes red, and that still works, because the final gate is a full run.
- **Cloud workers** (Linux) run the same hook, so they get selection too. The
  per-worktree map is built after their first full run. Until then they run
  everything.
- **Decided (2026-11-05):** the pre-push backstop blocks a push from a machine
  with no venv, as pre-ship does.
