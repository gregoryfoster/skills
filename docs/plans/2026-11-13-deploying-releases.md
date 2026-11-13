---
title: deploying-releases — one installed release-deploy core with per-repo hooks, fresh and retrofit modes
date: 2026-11-13
status: approved
---

# deploying-releases

For [#372](https://github.com/gregoryfoster/skills/issues/372), coordinated by
[#516](https://github.com/gregoryfoster/skills/issues/516). The requirements are
#372's body and its three comments (provisioner, observo, and replicator's carried
from #469). The [coordinator's pre-flight](https://github.com/gregoryfoster/skills/issues/372#issuecomment-6866010106)
is the baseline. The seed, CannObserv/broker `scripts/deploy.sh` at `bbf1c72f`, was
read through the API only; nothing was written to any other repo. "provisioner #4",
"observo #5" and "replicator #2" name item 4, 5 or 2 of that repo's comment on #372,
not an issue.

## Problem

Six cohort repos deploy from root-owned releases, and each runs its own
`scripts/deploy.sh`: broker 943 lines, archiver 768, status 679, processor 665,
observo 485, provisioner 389. None splits a core from its hooks, so every lesson
(status's five CR rounds, broker's #122 and #144) is relearned per copy. Seven
more still run their checkout. replicator#151 waits on this issue. Meanwhile
`init-project-fastapi` still scaffolds the checkout pattern every pilot has left:
`WorkingDirectory=/home/<user>/<p>`, a git-SHA `ExecStartPre`, the main-checkout
guard and the find-links wheelhouse.

## Decisions (operator, 2026-11-13; D6–D9 from the plan's review)

| # | Question | Decided |
|---|---|---|
| D1 | Name (Q1) | `deploying-releases`, no suffix: no sibling variant exists, and the stack-specific steps fall in hooks. |
| D2 | Default `SERVICE_USER` (Q2) | Fresh: a dedicated system user, with releases owned by root (observo's shape). Retrofit: starts on `exedev`, with the dedicated user as a named follow-up. |
| D3 | Enabling new units (Q3) | broker's shape: `ENABLE_NEW`, the repo's own list, enabled only after the deploy verifies, and **empty by default**. Empty behaves like status's "install, never enable, print the command". |
| D4 | The seed (Q4) | broker's script. |
| D5 | Units installed or only compared | **Installed**, and not a branch point. The core installs each unit that differs from its installed copy, as four pilots do. observo and provisioner widen their sudo grant when they adopt. |
| D6 | Keep `DEPLOY_TARGET=systemd-checkout`? | **Dropped.** `DEPLOY_TARGET` is `releases` (the default) or `none`. No new repo should be scaffolded onto the checkout pattern, and the seven checkout repos are retrofits. `systemd-deploy.md` is deleted. |
| D7 | Release ownership | **Root-owned only**, with no ownership knob (broker's `roots_alone`). processor (exedev-owned, `a-w`) and provisioner (exedev-owned, `a+rX,a-w`) move to root-owned releases when they adopt, and their deploy users need `sudo chown`. |
| D8 | shellcheck versions (provisioner #9) | **A documented floor.** The core is held clean at this repo's pinned 0.11 (`--severity=style`), and SKILL.md and the generated `DEPLOYMENT.md` name 0.11 as the floor. No `.shellcheckrc` ships with the core, and verdicts from apt's 0.9 or a Mac's 0.8 are unsupported. |
| D9 | Default check for a restarted unit | The core checks that its `MainPID` is new and resolves to the new release (`sudo readlink /proc/<pid>/cwd`, since a dedicated user's `/proc` is not the deployer's). processor's journal start record (the build, then `consuming`) is the recommended stronger `verify` hook, since it needs app-side logging. |

## Approach

A new skill, `skills/deploying-releases/`, ships one core script, extracted
from broker's. The core is **installed** into a consumer by `scripts/install.sh`,
not run from `skills-vendor/` and not symlinked. It is installed as the consumer's
`scripts/deploy.sh`, so every `.skills/deploy_command` that already names that path keeps working.
A marker line records the core's version and the sha256 of its body.
`install.sh --check` reports drift from the vendored copy. An upgrade is a diff in
the consumer's tree, never a silent submodule bump. The core sources
`scripts/deploy_hooks.sh`, which the repo owns. That file holds config variables and
at most six hook functions, and every hook has a no-op or refusing default. The skill
has two entry modes. **Fresh** is called from `init-project-fastapi` Phase 7b. It
writes the hooks from answers, the units from templates, the generated tests and
`DEPLOYMENT.md`. **Retrofit** is for a repo whose units run its checkout:
inventory, design note, cutover runbook, cleanup. replicator is retrofit's first
user. The six copies move onto the core afterwards, one issue per repo.

### The core's contract (derived from broker)

The core does these in order. Each step either says why it stopped or continues, so nothing exits silently under `set -e`.

0. **Preflight.** Refuses to run as root. Requires a checkout, and requires the root to be `root:root` and not group- or world-writable. Takes the lock with `flock` on the root. Requires whole-number knobs. Journals every path override that is not the host's default.
1. **Resolve.** `git fetch`. `live` takes only a commit on `origin/main`. `--target dev` also takes any `origin/*` commit (the body's rule).
2. **CI gate.** `CI=github`: the newest `push` run of `CI_WORKFLOW` on `main` for exactly this SHA, every job `success`, with `CI_JOBS` as a floor; a bounded wait while pending; an immediate refusal for an intermediate commit or a commit pushed by a workflow. `CI_AUTH=anonymous` (broker) or `gh` (observo, private repos: `env -u GH_TOKEN -u GITHUB_TOKEN gh api`). `CI=none` is a standing off switch (provisioner #7). `--skip-ci` is logged.
3. **Build.**
   - `git archive <sha> $SERVICE_DIR`, stripped to the release root (provisioner #1); after this, everything reads from the release.
   - A lock that resolves from `.wheelhouse` is refused (broker).
   - `uv sync --locked --no-dev --compile-bytecode --link-mode copy --python $PYTHON`, run through `UV_WRAPPER` when the repo names one (co-pypi; see [#632](https://github.com/gregoryfoster/skills/issues/632)).
   - The venv's `home` must not be under `/home`. `compileall` runs on the project's own sources.
   - Then the `build_extra` hook, the `REQUIRED_ARTIFACTS` check (observo #1), the `IMPORT_MODULES` probe and the `post_build_check` hook.
   - Finally `chmod -R a-w,a+rX`, `chown -R root:root`, `REVISION` written last by root, and a read-back from the release.
   - A linked release is never rebuilt. `--build-only` stops here.
4. **Pre-switch.** `User=` exists for every non-`DynamicUser=` unit (broker `check_users`), then `pre_switch_check <target>`.
5. **Migrate.** `migrate <target>`, before the switch; migrations are expand-only, so a switch back never needs a down migration.
6. **Switch.** `ln` to a temporary name, then `mv -T`, per target.
7. **Units.**
   - Each `$UNITS_DIR/$PROJECT-*.{service,timer}` and `$PROJECT-*@.service` that differs from its installed copy is installed, with the replaced copy kept aside. This covers handler templates (replicator #4) and `migrate@` (observo).
   - One `daemon-reload`, then `try-restart` on changed timers.
   - Each unit is checked as *loaded*: `NeedDaemonReload=no`, `WorkingDirectory` under the root (observo CR 13).
8. **Restart.** Each long-running unit (not `Type=oneshot`) that is enabled or active and runs a moved target gets `reset-failed` and then `restart`. The drain is the unit's own `TimeoutStopSec=` (replicator #1). Timers are never forced (broker).
9. **Verify.**
   - The core runs `verify <unit> <build>` for each unit this deploy changed. A unit that is installed but not enabled is named, never verified (provisioner #4).
   - The core's own default for a restarted unit (D9): its `MainPID` is new and resolves to the new release.
   - A unit the hook has no check for is a note, as in broker.
10. **Switch back on failure.**
    - The link and the units go back exactly, the service gets `reset-failed` and a restart, and the old build is verified the same way.
    - Exits 1 when the old build answers, and 4 when nothing answers.
11. **After a verified deploy.**
    - `ENABLE_NEW` entries this deploy added are enabled.
    - `post_verify <target>` runs; a failure there is a note, never a rollback (observo #6).
    - Units installed but missing from the release are named.
    - `HOST_CONFIGS` are compared byte for byte and `DERIVED_CONFIGS` against the previous release, never installed.
    - Prune keeps `KEEP` releases plus everything linked plus the release live replaced. `REVISION` is removed first.

**A unit's target is its `WorkingDirectory=`**, never a list. `/srv/<p>/live` is
live and `/srv/<p>/dev` is dev. Targets come out per unit (provisioner's dev API with
no dev consumer), and a repo with no `dev` unit has no dev target (observo's
"never"). That replaces the body's `targets` hook.

### Hooks and config, filled in per pilot

Read from each script's function list and #372's thread. Each repo's adoption issue confirms its own row.

| Repo | Targets | `SERVICE_DIR`, `UNITS_DIR` | `CI`, `UV_WRAPPER` | `build_extra`, `post_build_check` | `migrate` | `verify` | `ENABLE_NEW` |
|---|---|---|---|---|---|---|---|
| broker | live | `.`, `deploy/` | github anon, co-pypi | —, imports + `read_revision` | — | probe's next tick; backup's forced run; drift: none | drift timer |
| status | dev, live | `.`, `deploy/` | github, — | —, one Alembic head | `schema_state`, migrate unless ahead | sweep pass, `/ready`, `/health` build | — |
| processor | live | `.`, `deploy/` | github, co-pypi | —, venv imports | — | start record on the build, then the smoke run | its new timers, named |
| observo | live | `.`, `infra/` | github gh, co-pypi | npm build + bundle required, one head | `observo-migrate@<sha12>` oneshot | `/health` ok and `revision == sha12` | — |
| provisioner | dev (API only), live | `service/`, `deploy/` | none, own minter | —, one head | as deployer, skipped when ahead | `/health` names the build for the API and the consumer heartbeat | — |
| archiver | live (dev is a rehearsal) | `.`, `deploy/` | github, wheelhouse → co-pypi first | —, one head + every unit's entry module imports | migrate, `grant_readers` | `/health` `build_id`, a forced bus-health pass, `schema_serves` | — |
| replicator (first adopter) | live | from inventory | from inventory | —, imports | — | drained worker restarted on the new `REVISION`; handler units included | — |

The hook signatures, defaults and exit codes are listed in the skill's `references/hook-contract.md`.

| Hook | Runs | Contract |
|---|---|---|
| `build_extra` | in the release, as the deployer, before the chmod | non-zero refuses; nothing switched |
| `post_build_check` | in the release, after the `REVISION` read-back | non-zero refuses |
| `pre_switch_check <target>` | before migrate | non-zero refuses, journaled |
| `migrate <target>` | before the switch | idempotent; skips a database that is ahead; non-zero refuses. Shipped in two forms: as the deployer (status), and through a oneshot `<p>-migrate@<sha12>` with the app's user (observo), read back with `journalctl --sync` and `--since` (observo #8) |
| `verify <unit> <build>` | after the restart, per changed unit | 0 verified, 1 failed (switch back), 2 no check for this unit (a note). The shipped helpers are `verify_http_health`, `verify_next_tick`, `verify_forced_run` and `verify_started_on`, plus a heartbeat check that reads another unit's `/health` |
| `post_verify <target>` | after a verified deploy | failure is a note. A smoke hook must refuse a target that isn't `_dev`/`_test` (provisioner #10) |

### What the consumer gets (fresh mode)

- `scripts/deploy.sh` (the installed core) and `scripts/deploy_hooks.sh` (from a template).
- Unit templates on `WorkingDirectory=/srv/<p>/live`. They run the venv's entry point, never `uv`. They run as `User=<p>`, with the hardening and its pinned exclusions: `Delegate=yes`, and never `ProtectControlGroups=`, `MemoryDenyWriteExecute=` or `PrivateUsers=` (observo #5). The build id is copied to `/run/<p>/build-id` for `OnFailure=` handlers (replicator #3). Secrets go through `LoadCredential=` and settings through `EnvironmentFile=` (provisioner #5).
- `tests/deploy/`:
  - broker's stub harness: a temp root and a temp origin, with stubbed `uv`, `sudo`, `systemctl`, `curl`, `logger` and `rm`;
  - the hook contract test (`deploy_hooks.sh` defines only known names; the required variables are set; the core's marker hash matches its body);
  - the unit invariants: no `/home/`, no unit syncs, `WorkingDirectory=` under the root, a `-dev` name ↔ the dev target, every `deploy/` file a unit or a listed host config, no key-shaped value in an `EnvironmentFile=`;
  - an installed-unit parity check against the **live release**, never the working tree.

  *Revised in step 3 (2026-11-13):* broker's stub harness stays in this repo, where it tests the one core for every consumer (`tests/structural/test_deploying_releases_core.py`). A consumer gets the contract, unit-invariant and parity tests. A harness for testing a consumer's own hooks is a follow-up issue, to be filed when Part A ships.

  The harness needs GNU coreutils (`mv -T`, `flock`, `stat -c`), so on a Mac it uses Homebrew's `gnubin`. In a consumer it **fails** without them (provisioner #8).
- `DEPLOYMENT.md`, with the operator's one-time steps: the root, `/etc/<p>/`, the user, the sudo grant and the co-pypi reader key.

### Retrofit mode

The body's six steps, plus what the comments add:

1. **Inventory.** Units and timers. `EnvironmentFile=`s and the secrets each unit needs. Paths each unit writes. Each `ExecStartPre`, as integrity or health. `uv` sources by kind. Hand-run production steps in AGENTS.md and CLAUDE.md. **In-process checkout guards in `src/`** (replicator #2).
2. **Contract fallout.** The build field's source and format; any CHANGELOG entry or regenerated client.
3. **Safety gaps.** `db_safety` in `alembic/env.py`; a schema check where `/ready` can't be added; the main-checkout guard deleted, not ported; `Settings` tolerating an unreadable `EnvironmentFile=` (observo#695).
4. **Design note** from a template: a D-table answering broker#22 Q1–14, and **the oldest deployable commit** (observo #7).
5. **Cutover runbook.**
   - The operator creates the root and `/etc/<p>/`, and the sudo grant.
   - `deploy.sh --no-restart`, then install, restart and verify.
   - Credential paths are moved *before* the restart (observo#699's trap).
   - Prove that switching the checkout's branch leaves the build id unchanged.
   - Drill a rollback: forward, back, forward.
6. **Cleanup.**
   - Delete `.skills/worktree_venv` and set `.skills/deploy_command`.
   - Rewrite the parity test.
   - Remove the hand-run production steps from the docs, and retire memories that say the checkout runs timers.

### Out of v1, and where it goes

- **co-pypi on the init side:** [#632](https://github.com/gregoryfoster/skills/issues/632), filed 2026-11-13. Part A doesn't wait for it, because the core reaches the index only through `UV_WRAPPER`. Part B waits (step 7).
- **Part C's remainder:** [#536](https://github.com/gregoryfoster/skills/issues/536) carries the inverted deploy check in `reviewing-code-python-fastapi`. #345 and `using-git-worktrees/SKILL.md:75` are already done.
- **The drift check** (body §5: processor's module and timer, `RUNTIME_PATHS`, the co-status prerequisites): its own child, filed when v1 ships. broker's and processor's copies stay in place until then.
- **The wheelhouse in the core:** none. archiver leaves the wheelhouse before it adopts.

## Tradeoffs / alternatives

- **Run the core from `skills-vendor/`, or symlink it** — rejected. A submodule bump would silently change how production deploys, and a release has no `skills-vendor/` (D4's reasoning in the body).
- **Port status's script** (the body's Q4 alternative) — rejected (D4). broker is the newest lineage, the most tested, and already on the index.
- **Units compare-only as a branch point** — rejected (D5). Two modes double the switch-back paths and the tests, all to save one sudo grant.
- **A `targets` hook per repo** — rejected. Deriving the target from `WorkingDirectory=` can't disagree with the units, and it answers both provisioner's and observo's cases.
- **Keep the name `deploy_core.sh`, called from a per-repo `deploy.sh`** — rejected. A wrapper is a second file to drift, and the installed core *is* the entry point.
- **Keep `DEPLOY_TARGET=systemd-checkout`** (the body's deprecated legacy value) — rejected (D6).

## Steps

1. **Skeleton and core.**
   - `skills/deploying-releases/` holds `SKILL.md` (≤ 6,000 tokens), `assets/deploy.sh` (the core, extracted from broker `bbf1c72f`), `assets/deploy_hooks.sh.template` and `scripts/install.sh` (`--check`, `--help`, refuses to overwrite a non-core file).
   - SKILL.md names shellcheck 0.11 as the core's floor (D8).
   - Done when shellcheck 0.11 is clean at `--severity=style`, and a port of broker's harness passes against the core plus a broker-shaped hooks fixture, in a per-rule test file. Locally, a run without GNU coreutils skips loudly (`GNUBIN_REQUIRED=1` to fail).
2. **The hook contract.**
   - `references/hook-contract.md` and the six hooks, with the restart and verify rules and the verify helpers.
   - Done when the harness covers each hook's refuse, switch-back and note paths, plus status's dev-then-live order, provisioner's `SERVICE_DIR` and `CI=none`, and observo's `migrate@` and `REQUIRED_ARTIFACTS`. Each runs as its own fixture.
3. **Fresh-mode assets.**
   - The unit templates, the generated `tests/deploy/` and the `DEPLOYMENT.md` template.
   - Done when a fixture consumer renders from them and its generated tests pass.
4. **Retrofit reference.** `references/retrofit.md` and the design-note template, linked from SKILL.md and covered by the structural suite.
5. **Ship Part A.**
   - The gate, the review rounds and the README table.
   - #372 gets a progress comment, and stays open for Part B.
6. **replicator adopts (retrofit).**
   - The operator runs it in replicator's own thread, under replicator#151. Findings come back as fixes here before anyone else adopts.
   - Then the adoption issues are filed, each on its own authorization: the six checkout repos (repos already on the index or with no private deps first), then the six copies. broker goes first among the copies, since its move should be a near-no-op diff that proves the extraction. Then processor, observo, provisioner and status, and archiver last, after it leaves the wheelhouse. Each issue is framed as installing the core, plus `.skills/` config and hooks.
7. **#632 lands.** init-project-fastapi moves to the co-pypi index. This is a prerequisite for step 8.
8. **Part B: init-project-fastapi delegates.**
   - `DEPLOY_TARGET` becomes `releases` (the default) or `none`. No cohort repo's AGENTS.md carries the old value, so it's a rename with no alias [measured: code search across the CannObserv org, 2026-11-13].
   - Phase 7b calls `deploying-releases` in fresh mode, and `DEPLOY_HOME` is dropped.
   - `test_init_fastapi_env_handling.py` is rewritten to pin the inverse.
   - #500, #577 and #598 go after this or in the same thread.
   - Done when every file is at or under its target below, re-anchored.

| File | Now | Target | Change |
|---|---|---|---|
| init `SKILL.md` | 14,555 exact (cap 14,700) | ≤ 14,400 | the 7b delegation; drop `DEPLOY_HOME` and the `BUILD_ID`/`EnvironmentFile` invariant. The 155-token margin is for #500 |
| `references/systemd-deploy.md` | 2,976 | 0 (deleted) | the unit templates move to `deploying-releases` |
| `references/private-wheelhouse.md` | 7,356 | 0 (#632 replaces it) | — |
| `references/agents-md-template.md` | 5,921 exact, anchor lapsed | ≤ 5,921, re-anchored | 11 `DEPLOY_TARGET` mentions; the deploy recipe becomes `.skills/deploy_command` |
| `references/settings-scaffolding.md` | 1,798 | ≤ 1,950 | `get_build_id()` reads `REVISION` (`dev` when absent); `readable_env_files()` |
| `references/source-skeleton.md` | 4,810 | ≤ 4,900 | `get_build_id()` |
| `references/database-scaffolding.md` | 3,512 | ≤ 3,900 | `assert_database_safety()`; `src/core/schema_state.py` (exits 0/3/2) |
| `references/cohort-context.md` | 1,716 | ≤ 1,800 | rationale cites broker#22 and the pilots |
| `completion-report.md`, `core-config-files.md`, `init-socraticode/…/context-artifacts.md` | 1,059 / 628 / — | ± 0 | the value rename only |

## Open questions / risks

None open: D6–D9 settled the four questions the draft raised. Two risks remain:

1. **Risk: the core changes production deploys in six repos.** Mitigations: the install-and-diff model, broker's near-no-op move as the proof, and one repo per issue with its own gate.
2. **Risk: budget.** init's SKILL.md has 145 tokens of headroom. Part B is only safe after #632 removes the find-links prose; if #632 slips, step 8 waits.
