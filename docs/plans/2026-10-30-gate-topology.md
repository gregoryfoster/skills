---
title: Gate topology — run each check once per change, at the stage that owns it, and fold shipping-work-* back into one skill
date: 2026-10-30
status: approved  # 2026-10-30; implementation starts after Wave 5 of #516 merges (D1)
---

# Gate topology and one `shipping-work`

## Problem

Validation cost has grown faster than the code it guards, and nothing decides
which stage owns which check, so the same suite runs two to four times per
change. The skills that set those gates up have drifted apart, so the cohort
cannot be fixed one consistent way.

- **This repo.** `tests/structural/` grew from 73 files / 1.7 MB (2026-09-01)
  to 175 files / 4.2 MB / 8,986 tests. Measured serially it takes **16:18**
  (381 s user, 379 s sys; the sys half is subprocess spawn: 134 files shell
  out, 19 build git repos). The pre-commit hook runs all of it on every commit
  (`always_run`), and `scripts/pre-ship.sh` runs it again with no record that
  it already passed. 472 commits landed on main in the last week; each one
  paid the full suite at least once. ruff and the context budget each run
  twice per commit: as a hook, and again inside the suite.
- **The cohort.** Over 30 days, 14 repos billed 9,444 minutes for 7,011 actual.
  2,433 of those minutes (26%) are rounding waste. Only the 4 private repos
  pay: observo, cli, cannobserv and wordpress, at 4,006 billed minutes.
  - Every push+PR repo re-runs CI on the merge commit. That is 641 billed
    minutes (37%) in archiver and 375 in observo.
  - notifier's spend comes from how many jobs it runs, not how long they take:
    689 of its 798 jobs finish in under 60 s.
  - The uncached cannobserv wheelhouse sync takes 40–77% of the job time in
    watcher, archiver, broker and replicator.
  - Trigger models: push+PR in 7 repos, PR-only in 2, no test CI in 4. Only 4
    of the 14 run the suite in pre-commit.
- **The `shipping-work` family has drifted apart.**
  - It is four skills: a baseline stub plus `-php`, `-python-click` and
    `-python-fastapi`, with 1,269 lines of `pre-ship.sh` and three forked
    `doc-check.sh` copies, each 22–23 lines off the base.
  - The click gate has no format check, no `-x`, no integration deselect and
    no `--no-cov`. php has no stamp. Their npm blocks disagree on whether
    they stop at the first failure.
  - `detect-test-dirs.sh` and `detect-import-targets.sh` are copied into
    `reviewing-code-python-click` too.
  - Every cohort repo links exactly one variant by name, and none links the
    baseline: 10 link fastapi, 2 link click, 1 links php. Four keep local
    override directories naming a variant: archiver, wordpress, wslcb and
    watcher.

Raw data:
`/private/tmp/claude-501/-Users-gregoryfoster-Documents-organizations-foojutsu-code-skills/512fab1e-bdc3-4955-aa37-93b51b26353a/scratchpad/ci/`
(cohort job census) and `.../scratchpad/junit.xml` (suite profile).

## Approach

**A gate-topology contract.** Each check gets exactly one authoritative stage,
and every other stage either runs a cheaper subset or reuses a recorded pass:

| Stage | Owns | Budget |
|---|---|---|
| pre-commit | Lint, format, budget gates; tests **in parallel** (full, or impacted-only, see Step 10) | about 2–3 min |
| ship gate (`pre-ship.sh`) | The full suite, **skipped when a pass is already recorded for this exact tree** | 0 or one suite |
| CI (where a repo has it) | The full suite once per change: one consolidated job, on PRs; push-to-main only for direct pushes | under 5 jobs, no sub-minute jobs |
| scheduled | Exact or billed measurement (unchanged) | weekly |

Three mechanisms carry the contract:

1. **pytest-xdist.** Measured here with `-n 8 --dist loadfile`: **2:30 against
   16:18**, with the same results (8,632 passed, 354 skipped, nothing failed).
   It is also safe in shuffled order (pytest-randomly, `--dist load`: same
   results, 2:36). `-n 6` took 3:10 and `-n 12` took 2:40, so 8 is where it
   stops getting faster on 14 cores.
2. **A tree-keyed pass stamp.** The key is `git write-tree` plus the lockfile
   or requirements hash, the interpreter, the OS, the env names, and the
   content hash of any configured untracked inputs (D5). Whichever gate runs
   the full suite on a tree writes the stamp, and every later gate on the same
   tree reuses it.
3. **A worker-count resolver** (D2, below), shared by every gate.

**One `shipping-work` skill** (D4) owns the contract, so cohort repos can't
drift apart again:

- Its single `pre-ship.sh` detects what the repo has and runs **one
  implementation per check**, instead of switching on a named stack:
  - `pyproject.toml` with uv: ruff check and format, an import check, pytest
    with the integration deselect.
  - `composer.json`: validate, `php -l`, `composer test`.
  - `package.json`: whichever npm scripts it declares.
  - None of these: today's stub, exit 1 with the remedy.
- What is genuinely specific to a stack moves to `references/stack-*.md`,
  loaded only when that stack is detected: alembic and systemd restarts for
  FastAPI services, `--help` output for Click, Bedrock and Sage for PHP.
- Drift becomes structurally impossible, not something a parity test has to
  catch after the fact.

## Decisions recorded (review, 2026-10-30)

- **D1: when to land it.** Start after Wave 5 of #516 merges, rebased onto
  that main. Nothing lands mid-wave.
- **D2: worker count, configurable several ways, resolved first match wins:**
  1. **`PYTEST_XDIST_AUTO_NUM_WORKERS`**, pytest-xdist's own variable that
     `-n auto` already reads. The coordinator sets it in each worker brief
     (cores ÷ live agents), since it is the one party that knows how many
     agents are running.
  2. **`.skills/test-workers`**: `off`, `auto`, or a number. This is the
     project's standing choice, for example `off` for fastapi repos whose
     tests share a database.
  3. **Automatic:**
     - **2 cores or fewer** (every exe.dev VM shares two vCPUs): serial,
       unless a measurement on an exe.dev VM shows that `-n 2` pays for
       itself even with agents sharing the VM (Step 1).
     - **Otherwise:** `min(8, cores ÷ active gates)`. Active gates are
       counted from slot files under `$(git rev-parse --git-common-dir)`,
       which covers concurrent worktrees of one repo when no coordinator
       is present.
- **D3: a Linux backstop for this repo.** You had no opinion, so I'm
  deciding: none for now. Revisit at the second Linux-only failure; #526
  is the first.
- **D4: where the contract lives.** Inside `shipping-work`, which is
  re-aggregated as described above.
- **D5: which untracked inputs a stamp depends on.** This varies by repo, so
  it is configured, with recommended defaults. Resolved first match wins:
  1. **`GATE_STAMP_INPUTS`**, a colon-separated list.
  2. **`.skills/gate-stamp-inputs`**: one path or glob per line, `#`
     comments. It **replaces** the default list, so a repo can also drop a
     default.
  3. **Default:** `.env`.

  Only a content hash ever enters the key. The stamp records which inputs
  were hashed, never their values. A configured path that doesn't exist is
  hashed as absent, so creating it later invalidates the stamp.
- **D6: the `reviewing-code-*` family.** It folds the same way, as a
  follow-on: #536, sequenced after Part B ships.

## Tradeoffs / alternatives

- **Keep the variants and add a drift test.** Rejected. Content-invariant tests
  already exist, and the drift happened anyway, because they compare named
  fragments and the flags live in code. One implementation is the only fix
  that removes the cause.
- **Name the stack in a knob, instead of detecting it.** Rejected as the
  default, because detection already exists in the variants (FastAPI vs Click
  is only telling apart alembic or systemd from Click entry points). A
  `.skills/stack` override stays available for a repo that detects wrong.
- **Remove the variant directories in the same release.** Rejected. The daily
  auto-refresh bumps every cohort submodule within a day, so removing them
  outright would leave dangling `skills/shipping-work-*` links in 13 repos at
  once. Two releases: the first adds the replacement and the rename map, the
  second deletes the variants.
- **Impacted-test selection in pre-commit from day one.** Deferred. Replayed
  over 300 commits it selects a median of 54% of suite time (p75 65%), with a
  floor around 41% from repo-wide invariant files. On top of xdist that is
  about a minute per commit, at the risk of a false skip. Decide from a
  measurement (Step 10).
- **Moving the full suite to GitHub Actions, or sharding it across a
  matrix.** Rejected. This repo ships by direct push, so CI would only see a
  breakage after it was on main. Every shard is rounded up separately. And
  the hosted runner (4 vCPU) is slower than local `-n 8`.
- **A blanket `cancel-in-progress` and `paths-ignore: '**.md'`.** Rejected:
  `auditing-ci-cost` lists both as non-levers when applied without
  measurement. Path filters ship only after a zero-false-skip replay.

## Steps

Every step lands gated by `scripts/pre-ship.sh`. Step 0 comes first; after it,
the parts run in order: A, then B, then C.

0. **Wait for Wave 5 to merge**, then branch from main in a dedicated worktree.

**A — this repo's gates**

1. **Pin, parallelize, resolve the worker count.**
   - Add `pytest-xdist` to `requirements-test.txt`, and pin `pytest`
     exactly. Today it is `>=8.0`, and the next major turns the
     class-scoped-fixture deprecations already showing in 4 files into
     failures. Fix those 4 files.
   - Put the D2 resolver in a sourced `gate-workers.sh` (`.skills/`
     knob, slot files), and have `structural-tests.sh` use it with
     `--dist loadfile`.
   - Measure the 2-vCPU case once on an exe.dev VM, and record what the
     automatic default chose and why. This is still open after Part A,
     which ships the serial default for 2 cores or fewer. Changing that
     default needs the measurement first.
   - Verify: green under a shuffled order, and at or under 3 min on this
     Mac.
2. **Tree stamp.** `gate-stamp.sh` with `key`, `check` and `write`.
   - The key includes the D5 inputs. Document the knob in
     `docs/KNOBS.md`, and hold it with the knob-inventory test.
   - pre-commit writes a stamp for the index tree after a green full
     run.
   - `pre-ship.sh` checks `HEAD^{tree}` on a clean tree and skips the
     suite on a match, naming the stamp it reused.
   - `TestGateScriptHardening` covers both scripts. Verify: a commit
     followed by pre-ship runs the suite once.
3. ~~**Remove the in-suite duplicates of ruff and the budget gate.**~~
   **Dropped during implementation, from a measurement.** The in-suite ruff
   tests take 0.14 s, and the AGENTS.md budget tests 0.75 s. Most of what
   those files hold tests the gates themselves, such as version probes and
   hook wiring, rather than repeating them. Removing them saves under a
   second and costs the check that still runs outside pre-commit.
4. **Suite-cost telemetry, not a gate.** Revised during implementation:
   - Every gate run ends with the wall clock and the 15 slowest files.
     A pytest plugin, `tests/utils/gate_durations.py`, does this, and
     `structural-tests.sh` loads it.
   - Every recorded pass carries its seconds, so `gate-stamp.sh list` is
     the local time series.
   - The weekly cadence row was **dropped**. Its workflow is generated by
     `curating-context` for every cohort repo, and a suite timing from a
     hosted runner says nothing about local wall clock.
   - File the issue for the patching-hosts rigs: about 300 s serially
     (31%), to share fixtures and spawn fewer subprocesses.

**B — one `shipping-work` (release 1 adds it, release 2 removes the variants)**

5. **Decide each drifted check once.**
   - Tabulate every check the four `pre-ship.sh` and three `doc-check.sh`
     copies run: ruff check and format, `-x`, integration deselect,
     `--no-cov`, exit 5, npm stop-at-first-failure, php lint jobs,
     stamp, `.skills/pre-ship-uv-args`, `PRE_SHIP_ENV_NAMES`.
   - Record one decision per row in the skill's references, so the
     choice is written down rather than living in code.
6. **Build the unified skill.**
   - A single `pre-ship.sh` that detects the stack and calls one function
     per check, built on the gate-workers and gate-stamp libraries.
   - One `doc-check.sh`.
   - The detect scripts move into `shipping-work`, and
     `reviewing-code-python-click` reaches them through per-script
     resolution instead of a copy.
   - The contract goes in `references/gate-topology.md`; stack prose
     goes in `references/stack-{fastapi,click,php}.md`.
   - SKILL.md stays under its 6,000-token ratchet.
7. **Parity harness, then retarget the tests.**
   - Build fixture repos in the shape of fastapi, click, php,
     npm-alongside and none. For each, run the old variant gate and the
     new gate and compare verdicts and exit codes. Every difference must
     match a Step 5 decision.
   - Then move the roughly 15 structural files that parametrize over
     variants onto the stack fixtures. Among them:
     `test_pre_ship_env_override`, `_env_worktree`, `_uv_invocation`,
     `_unresolved_head`, `test_doctor_override_drift`,
     `test_override_required_fragments` and
     `test_gate_producer_exit_codes`.
   - Drop the `shipping-work` rows from `VARIANT_FAMILIES`, and re-run
     `test_trigger_routing` by hand. It is billed.
8. **Rename map, then release 1.**
   - The vendor ships a `retired-skills` map (`shipping-work-* →
     shipping-work`). The doctor, which syncs itself first on every run,
     repoints those symlinks.
   - An override directory is reported, never rewritten.
   - The variants stay, marked deprecated, so nothing dangles.
   - Update AGENTS.md, README, `docs/CONVENTIONS.md`, `docs/KNOBS.md`
     and the `init-project-fastapi` references to the single name.
9. **Cohort migration, then release 2.**
   - File one issue per repo (per-action authorization applies). Each
     issue covers:
     - confirming that the doctor repointed the link;
     - rewriting any override to `overrides: gregoryfoster/shipping-work`;
       archiver's bare `exec` wrapper becomes a plain symlink;
     - the repo's `.skills/test-workers`;
     - its `auditing-ci-cost` findings (Step 11). That makes one issue
       per repo, not two.
   - When all 13 are on `shipping-work`, delete the variant directories.
     The rename map stays, to heal stragglers.
10. **Selection decision.** After a week of commits under Steps 1–2, compare
    pre-commit wall clock against the roughly one minute that selection would
    save. If it is worth it, selection gets its own plan, built on a
    generated, test-enforced skill→test map, with pre-ship's full run as the
    backstop.

**C — CI**

11. **The `init-project-fastapi` CI template, and what `auditing-ci-cost`
    prescribes:**
    - Triggers: `pull_request`, plus `push: main` behind a job-level `if`
      that skips commits a merged PR already tested. A skipped job costs no
      minutes. Prototype it in archiver, which has the most re-runs.
    - One job that runs lint and tests together.
    - `concurrency` keyed on the ref, cancelling superseded runs on all
      refs.
    - `timeout-minutes`, and a cached uv and wheelhouse.
    - Path filters only through the replay.
    - Then work the per-repo findings through the Step 9 issues, in this
      order:
      1. observo: post-merge re-runs, a path filter on `test.yml`, folding
         eslint and vitest into one job.
      2. cannobserv: `checks` is at 64 s, so trimming it gets one billed
         minute instead of two.
      3. notifier: job count.
      4. The wheelhouse cache in watcher, archiver, broker and replicator.
      5. archiver: post-merge re-runs.

## Step 5 — one decision per drifted check (drafted 2026-10-31, for review)

Read from the four `pre-ship.sh` copies (baseline stub, fastapi, click, php)
and the four `doc-check.sh` copies. "Today" names which variants do it. This
table moves into `shipping-work/references/gate-topology.md` at Step 6, and
the Step 7 parity harness holds every old-vs-new difference to a row here.

| # | Check | Today | Decision |
|---|---|---|---|
| 1 | Which gate runs | Picked by the variant's name | **Detected per repo, and every detected stack runs.** uv `pyproject.toml` → the Python checks; `composer.json` → the PHP checks; `package.json` → its npm scripts. A repo with two stacks (wordpress has composer and npm; a FastAPI app can have a `package.json`) runs both. |
| 1b | Which docs apply | Picked by the variant's name | **Framework, detected separately from toolchain.** fastapi when `fastapi` is among `[project].dependencies`; click when `click` or `typer` is and fastapi isn't; php for any `composer.json`. It chooses only doc-check defaults (row 23) and which `references/stack-*.md` loads, never which checks run. A repo can match more than one, and gets the union. |
| 2 | Nothing detected | Baseline: stub, exit 1 | Same: exit 1 with the remedy. A repo-root `scripts/pre-ship.sh` still wins (#301). |
| 3 | Stack detected, tool missing | uv / composer / node missing → exit 2 | Same. |
| 4 | Worktree-zombie audit | All four, a warning only | Same, run once. |
| 5 | `ruff check` | fastapi, click | Every uv repo. |
| 6 | `ruff format --check` | fastapi only | **Every uv repo.** A click repo that has never been formatted goes red once; its Step 9 issue does the one-time `ruff format`. |
| 7 | Import check (`detect-import-targets.sh`) | click only | **Every uv repo**, with today's rules: `.skills/import-targets`, else `[project] name` with `-` → `_`, else skipped with a note. A repo whose project name isn't its import name sets the knob, which its Step 9 issue checks. |
| 8 | Test-directory detection (`detect-test-dirs.sh`) | click only | **Dropped from the gate.** pytest's own `testpaths` and rootdir rules decide, and exit 5 (row 9) covers a library with no suite. The script stays, because `reviewing-code-python-click` uses it. |
| 9 | pytest exit 5 (collected nothing) | fastapi, click: a pass | Same, plus a visible NOTE. (This repo's own gate fails on 5, but that is its repo-root wrapper.) |
| 10 | `-x` | fastapi yes, click no | **Off.** Under xdist a full run costs little more, and an agent fixes every failure in one pass instead of one per run. |
| 11 | `-v` | click yes, fastapi no | **Off.** Verbose output puts thousands of lines into agent context. |
| 12 | Integration deselect (the per-run plugin, never `-m`, #304) | fastapi only | **Every uv repo.** Integration tests are never in the ship gate (the contract). |
| 13 | `--no-cov` when pytest-cov is installed | fastapi only | **Every uv repo.** A coverage threshold belongs in CI. |
| 14 | xdist | None | **New.** `-n N --dist loadfile` from `gate-workers.sh` when the project's environment can import xdist; otherwise serial with a NOTE. The gate never adds a dependency. `.skills/test-workers off` is for suites that share a database or port. |
| 15 | Pass stamp | fastapi, click: `/tmp/<repo>-tests-clean-<HEAD sha>[-env-<hash>]`, pytest only; untracked files and modified `vendor/` paths still count as clean. php, npm: none | **`gate-stamp.sh` over the whole gate, every stack.** The key is the tree (lockfiles are tracked, so it covers them), the OS, the stack tools' versions, the `PRE_SHIP_ENV_NAMES` names, and D5's inputs. An untracked file or a dirty submodule means no stamp. That is stricter than today's rule and can only cost a re-run, never fake a pass. |
| 16 | `PRE_SHIP_ENV_NAMES` (#497) | fastapi, click | Same contract: the names enter the key, and an exported but empty list writes no stamp. The wrapper-don't-fork recipe is unchanged. |
| 17 | `.skills/pre-ship-uv-args` | fastapi, click | Same, for every uv call. |
| 18 | `composer validate` | php: the root, plus `themes/*/` and `plugins/*/` at the repo root | Same. Whether a Bedrock layout (`web/app/themes`) needs those paths is a Step 7 fixture question, not a Step 5 change. |
| 19 | `php -l` | php: parallel, `PRE_SHIP_PHP_LINT_JOBS` or 4 | `PRE_SHIP_PHP_LINT_JOBS`, else `gate-workers.sh`'s answer with 0 read as 1, so a 2-vCPU VM lints on one job. |
| 20 | `composer test` | php, when the script exists; `run-script --list` stderr discarded | Same, but stderr is shown when that probe fails (gate-script| 23 | `doc-check.sh` | Four copies that differ only in default watch paths and one advice line | **One script.** Every repo watches `AGENTS.md` and `README.md`, plus each framework's paths from row 1b, exactly as its variant does today. fastapi: `CHANGELOG.md`, `pyproject.toml`, `uv.lock`, `schema.sql`, `alembic/versions/`, `deploy/`, `src/{api,models,core}/`, `.env.example`. click: `pyproject.toml`, `uv.lock`, `src/`, `.env.example`. php: `composer.json`, `composer.lock`, `package.json`, `web/app/{themes,plugins,acf-json}/`, `.env.example`. A repo with no framework keeps the baseline's list. The AGENTS.md advice line names each matched framework's inventory: route table, command inventory, or CPT/Skills tables. `.skills/doc-sensitive-paths` and `.skills/doc-sections` still replace the defaults. |ffer only in default watch paths and one advice line | **One script.** Defaults are the shared list plus each detected stack's additions: fastapi `alembic/versions/`, `deploy/`, `src/core/`, `CHANGELOG.md`, `uv.lock`; click `src/`, `uv.lock`; php `composer.lock`, `web/app/{themes,plugins,acf-json}/`; `.env.example` for all three. `.skills/doc-sensitive-paths` and `.skills/doc-sections` still replace them. |
| 21 | npm `lint:js`, `format:js:check`, `test:js` | All four, identical, but python stops at the first failure and php continues | Same scripts, under row 22's policy. |
| 22 | What a failing check does | python: stop (`set -e`); php: run everything, then exit 1 | **Run every check, then exit 1, naming each failure.** Same reason as row 10. A tooling failure (exit 2) still stops at once. |
| 23 | `doc-check.sh` | Four copies that differ only in default watch paths and one advice line | **One script.** Every repo watches `AGENTS.md` and `README.md`, plus each framework's paths from row 1b, exactly as its variant does today. fastapi: `CHANGELOG.md`, `pyproject.toml`, `uv.lock`, `schema.sql`, `alembic/versions/`, `deploy/`, `src/{api,models,core}/`, `.env.example`. click: `pyproject.toml`, `uv.lock`, `src/`, `.env.example`. php: `composer.json`, `composer.lock`, `package.json`, `web/app/{themes,plugins,acf-json}/`, `.env.example`. A repo with no framework keeps the baseline's list. The AGENTS.md advice line names each matched framework's inventory: route table, command inventory, or CPT/Skills tables. `.skills/doc-sensitive-paths` and `.skills/doc-sections` still replace the defaults. |
| 24 | Exit codes | 0 / 1 / 2 in all four | Same: 0 pass, 1 a check failed, 2 tooling. |

## Open questions / risks

- **The ordering of doctor and refresh.** The rename map only works if the
  doctor syncs itself before it heals, in the same run. Step 8 must test
  that order directly, since a miss would leave the repo with a doctor that
  doesn't know the map yet.
- **Watcher runs integration tests in its ship gate.** The unified gate keeps
  integration tests out. Watcher's repo-root `pre-ship.sh` wrapper stays its
  own business, but the Step 9 issue should say so explicitly.
