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
   - *Revised 2026-10-31:* the parity harness is `test_gate_parity.py` (no
     "none" fixture: the variants never ran there, and row 2 is pinned in
     `test_unified_pre_ship.py`). "Retarget" became "cover the unified gate
     too": while the variants still ship, their tests stay, and every
     property they protect gains a unified-gate case, so release 2 deletes
     rows and nothing else. Dropping the `VARIANT_FAMILIES` rows, with the
     xfail-keying rewrite, the description change and the billed routing
     re-run, moves to release 2 (Step 9): it must land in the commit that
     deletes the directories, since either half alone fails the suite.
   - *Done 2026-10-31:* the unified gate now carries every property the
     variant tests protect — #304's real-pytest marker cases, the knob,
     CRLF and help cases, the env-name export, the resolver's exit 2, the
     commit-less repo, segment matching per framework, and the variants'
     next-steps categories (`test_shipping_work_stack_references.py`).
   - **Left for Step 8 (release 1):** `init-project-fastapi` points its
     scaffold at `shipping-work-python-fastapi`'s recipe
     (`references/agents-md-template.md` and `SKILL.md`, whose line on the
     per-SHA stamp is now stale) and `test_init_fastapi_env_handling.py`'s
     `RECIPE_VARIANT` with it.
   - **Left for release 2, in the deleting commit:** drop the variant rows
     from every list (`test_pre_ship_env_override`, `_env_worktree`,
     `_uv_invocation`, `test_gate_producer_exit_codes`,
     `test_per_script_resolution`, `doc_check_fixtures`); point
     `run_doc_check`'s default at `shipping-work` and give `CLICK_LIVE_TREE`
     a pyproject that declares click; drop `TestBodyParity`, the per-variant
     `TestShippingWork*` classes and the click side of
     `TestPythonClickHelperByteEquality`; delete `test_gate_parity.py` and
     `test_pre_ship_unresolved_head.py`; rewrite
     `test_trigger_xfail_keying.py`'s examples on the reviewing-code family;
     drop the `VARIANT_FAMILIES` rows and reword the baseline's "fallback"
     description; then re-run `test_trigger_routing` (billed).
8. **Rename map, then release 1.**
   - The vendor ships a `retired-skills` map (`shipping-work-* →
     shipping-work`). The doctor, which syncs itself first on every run,
     repoints those symlinks.
   - An override directory is reported, never rewritten.
   - The variants stay, marked deprecated, so nothing dangles.
   - Update AGENTS.md, README, `docs/CONVENTIONS.md`, `docs/KNOBS.md`
     and the `init-project-fastapi` references to the single name.
   - *Done 2026-10-31:* the map is `retired-skills` at the repo root. The
     doctor (`repoint_retired`) moves `skills/<old>` and
     `.claude/skills/<old>` onto `<new>` before its dangling scan, and again
     after an init when that pass found no map
     (`test_doctor_retired_skills.py`). One rule was added in implementation:
     a tracked file naming `skills/<old>/` **holds** the link unless it
     already dangles. Every fastapi consumer's scaffolded AGENTS.md
     `load_env` line and every wrapper's `DELEGATE` names the variant path,
     and repointing under them would break the gate in every consumer at
     once. So in most of the cohort the repoint lands when the Step 9 issue
     rewrites those lines and re-runs the doctor, not unattended. The
     variants carry `metadata.deprecated` and a banner, with descriptions
     unchanged; `init-project-fastapi` scaffolds `shipping-work`.
     `docs/CONVENTIONS.md` names a variant only in a historical incident,
     so it is unchanged.
   - **Added to release 2's deleting commit:** STYLE.md's canonical
     `FIND_RC` pointer (only the PHP variant's `pre-ship.sh` carries it;
     the relative-link test will fail on the deletion); README's three
     deprecated rows and KNOBS' deprecated readers; and the `shipping-work`
     description, which still says "fallback of last resort".
9. **Cohort migration, then release 2.**
   - File one issue per repo (per-action authorization applies). Each
     issue covers:
     - rewriting every tracked `skills/shipping-work-*/` path (the
       `load_env` line in AGENTS.md, a wrapper's `DELEGATE`, `forked-ok`)
       and re-running the doctor, then confirming it repointed the link and
       committing the `git add` it prints;
     - **symlinks and configuration, not overrides** (user, 2026-10-31):
       overrides have proven to fall out of sync too easily, so every
       override of a vendored skill in the repo — the `shipping-work-*`
       ones (archiver, wordpress, wslcb, watcher) first — is replaced by a
       whole-directory symlink. What the override carried moves into
       `.skills/` knobs (`doc-sections`, `doc-sensitive-paths`,
       `import-targets`, `pre-ship-uv-args`, `test-workers`,
       `gate-stamp-inputs`), a repo-root `scripts/pre-ship.sh` wrapper
       (wrap, don't fork), or AGENTS.md guidance. A delta that none of
       these can express is filed upstream as a knob request, and the
       issue names it. It is not a reason to keep the override. Archiver's
       bare `exec` wrapper becomes a plain symlink;
     - the repo's `.skills/test-workers`;
     - its `auditing-ci-cost` findings (Step 11). That makes one issue
       per repo, not two.
   - When all 13 are on `shipping-work`, delete the variant directories.
     The rename map stays, to heal stragglers.
   - *Done 2026-11-05.* The issues were filed 2026-10-31. The roster grew to
     17 on 2026-11-03: status (its own coordinator's status#83), processor
     (processor#115), and index and provisioner, which were already on
     `shipping-work`. All 17 had migrated by 2026-11-05. The overrides
     folded into knobs, wrappers or AGENTS.md, plus two new knobs: #342's
     `merge_mode` (wordpress's replaced Step 3) and #345's `deploy_command`.
     Release 2 is one commit, as planned. Two things were found in it:
     - `test_pr_mode_docs.py` held the description for this reword, and
       goes with it.
     - The deleted PHP variant was STYLE.md's canonical home for `LS_RC`,
       `FIND_RC` and the scalar EXIT trap. Those now point at shipping-work's
       `pre-ship.sh` and reviewing-code-php's `gather-context.sh`.

     The doc-check fixtures declare click in `pyproject.toml`, so they keep
     the old default variant's defaults. The billed `test_trigger_routing`
     re-run routes `ship it` and `wrap up` to `shipping-work`, with `push
     GH` and `close GH` still xfail. The run had about 21 other failures, in
     skills this change does not touch. Main (`38f378dc`) fails the same
     set, give or take three flaky cases.
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

## Step 5 — one decision per drifted check

Approved 2026-10-31 ("go"). The 25-row table now lives in
`skills/shipping-work/references/gate-topology.md`, reworded for a consuming
repo, and the Step 7 parity harness holds every old-vs-new difference to a
row there.

**Step 6 revisions (2026-10-31):**

- `reviewing-code-python-click` keeps its own `detect-import-targets.sh`
  rather than reaching `shipping-work`'s: the suite holds that a skill may
  not reach into another skill's scripts. The unified gate carries a third
  byte-equal copy, and `TestPythonClickHelperByteEquality` holds all three.
- `shipping-work`'s `description:` is unchanged: it is the selection surface,
  and Step 7 owns that change with the routing re-run.
- Row 7 revised with the user after a run on a scratch clone of notifier:
  watcher, notifier, archiver, broker and power-map package their code as
  `src`, so `import <project name>` failed in each. A guessed target now runs
  only when `<name>/` or `src/<name>/` exists; `.skills/import-targets`
  always runs.
- `pre-ship.sh` prints a `Detected: …` line, and SKILL.md loads
  `references/stack-<framework>.md` from it, so no seventh script joins the
  Step 1 resolution loop.

## Open questions / risks

- **The ordering of doctor and refresh.** The rename map only works if the
  doctor syncs itself before it heals, in the same run. Step 8 must test
  that order directly, since a miss would leave the repo with a doctor that
  doesn't know the map yet.
  *Resolved in Step 8:* "the same run" is not achievable, and not needed.
  A doctor that predates the map has no repoint code, so even once it has
  synced, it cannot repoint in that run. The run after does
  (`TestADoctorThatPredatesTheMap`), and nothing dangles in between because
  release 1 keeps the variants. Hook consumers skip even that lag, since
  the hook re-installs the doctor right after a bump (#299). The only real
  requirement is that release 1 reaches every consumer's doctor before
  release 2 deletes anything. A repo that jumps straight from pre-release-1
  to release 2 fails one doctor run ("still dangling"), then heals on the
  next.
- **Watcher runs integration tests in its ship gate.** The unified gate keeps
  integration tests out. Watcher's repo-root `pre-ship.sh` wrapper stays its
  own business, but the Step 9 issue should say so explicitly.
