# The core's contract and the hook interface

What `scripts/deploy.sh` (the core) does, what `scripts/deploy_hooks.sh` (the repo's) may set, and what each hook is handed and must return. Derived from CannObserv/broker's `scripts/deploy.sh` at `bbf1c72f`. The decisions behind it (D1–D9) are in [the plan](../../../docs/plans/2026-11-13-deploying-releases.md).

## The steps, in order

Per target, dev before live. A unit's target is its `WorkingDirectory=`: `<root>/live` is live, `<root>/dev` is dev, a timer goes with its service, and a unit under neither goes with live (with dev only when the release has no live unit), so a dev deploy never changes a unit production uses. A repo with no dev unit has no dev target.

| # | Step | Refuses or fails with |
|---|---|---|
| 0 | Preflight: bash 4+, the hooks file, `PROJECT`, whole-number knobs, not root, a checkout, the root and `releases/` `root:root` and not group- or world-writable, `flock` on the root. A path seam that is not the host's default is journaled. | exit 1, nothing done |
| 1 | Resolve: `git fetch`; live takes a commit on `origin/main`; `--target dev` also takes a commit on any pushed branch | exit 1 |
| 2 | CI (`CI=github`): the newest push run of `CI_WORKFLOW` for the SHA (on `main` for a main commit), every job `success`, at least `CI_JOBS`; a bounded wait; an immediate refusal for a commit behind the tip or pushed by a workflow | exit 1, nothing built |
| 3 | Build once, or reuse an intact release: `git archive` of `SERVICE_DIR`; refuse a `.wheelhouse` lock; `uv sync --locked --no-dev --compile-bytecode --link-mode copy --python $PYTHON` through `UV_WRAPPER`; the venv's `home` outside `/home`; `compileall` over `SOURCE_DIRS`; **`build_extra`**; `REQUIRED_ARTIFACTS`; the import probe; read-only, `root:root`; `REVISION` last and read back; **`post_build_check`**. A release a link names is never rebuilt. `--build-only` stops here. | exit 1, nothing switched |
| 4 | Every non-`DynamicUser=` unit's `User=` exists; then **`pre_switch_check <target>`** | exit 1, nothing switched |
| 5 | **`migrate <target>`** | exit 1, nothing switched for that target |
| 6 | Switch: `ln` to `<link>.new`, `mv -T` over the link | exit 1 |
| 7 | Install the target's units that differ, each replaced copy kept aside; one `daemon-reload`; each installed service checked as loaded (`NeedDaemonReload=no`, its `WorkingDirectory=`); changed timers `try-restart`ed | switch back |
| 8 | Restart each long-running service of the target (not `Type=oneshot`) that is enabled or active and runs the moved link or changed: `reset-failed`, `restart`. The drain is the unit's own `TimeoutStopSec=`. Timers are never forced. `--no-restart` stops here; `--verify` treats every target's link as moved, so a build already live is restarted and proved. | switch back |
| 9 | Verify each changed service that is meant to run: **`verify <unit> <want>`**; for a restarted unit the hook has no check for, `verify_started_on`. A long-running unit not enabled, or a oneshot whose timer is not active, is named and not verified. | switch back |
| 10 | Switch back: the link and the units exactly as they were, restart, verify the old build | exit 1 when it answers, 4 when not |
| 11 | Verified: enable each `ENABLE_NEW` unit this deploy added; **`post_verify <target>`**; name installed units the release lacks; compare `HOST_CONFIGS` (and `DERIVED_CONFIGS` against the previous release); prune to `KEEP` plus every link plus what each target replaced, `REVISION` first | notes only |

## The repo's variables

All optional except `PROJECT`, and `GITHUB_REPO` when `CI=github`.

| Variable | Default | Meaning |
|---|---|---|
| `PROJECT` | — | Unit prefix (`<p>.service`, `<p>-*.service`/`.timer`, `<p>@*.service`), journald tag `<p>-deploy`, knob prefix `<P>_DEPLOY_` |
| `SERVICE_DIR` | `.` | The subtree `git archive` takes; the release's root is its root (provisioner: `service`) |
| `UNITS_DIR` | `deploy` | Where the units are, in the release (observo: `infra`) |
| `CI` | `github` | `github` or `none` (a local gate: a standing switch) |
| `CI_AUTH` | `anonymous` | `anonymous` (curl, a public repo) or `gh` (gh's own login, `GH_TOKEN`/`GITHUB_TOKEN` unset) |
| `CI_WORKFLOW`, `GITHUB_REPO`, `CI_JOBS` | `ci.yml`, —, `()` | The workflow, `<owner>/<repo>`, the job names a run must have |
| `PYTHON` | `/usr/bin/python3.12` | The system interpreter every venv runs |
| `UV_WRAPPER` | empty | The checkout's credential wrapper (co-pypi: `scripts/co-pypi.sh`) |
| `SOURCE_DIRS` | `(src)` | Compiled to bytecode in the release |
| `IMPORT_MODULES`, `REVISION_PROBE` | `()`, empty | Imported, then the build printed (the core reads `REVISION` unless a probe prints it as the app does) |
| `REQUIRED_ARTIFACTS` | `()` | Paths every release must have after `build_extra` |
| `HOST_CONFIGS`, `DERIVED_CONFIGS` | `()` | `"<file>=<installed path>"` compared byte for byte; derived ones against the previous release |
| `ENABLE_NEW` | `()` | New units enabled once a deploy verifies (D3: empty by default) |
| `KEEP` | `5` | Releases kept besides the linked and the replaced |

Env knobs, as `<P>_DEPLOY_<NAME>`: `ROOT` (`/srv/<p>`), `HOST` (a test's tree), `KEEP`, `PYTHON`, `CI_WAIT_SECONDS` (600), `CI_POLL_SECONDS` (30), `VERIFY_SECONDS` (120), `TICK_SECONDS` (900), `RUN_WAIT_SECONDS` (660), `POLL_SECONDS` (10).

## The hooks

A hook runs in a subshell with errexit on: a failing command is its failure, and nothing it sets reaches the core. The core never calls one under `||` or `if`, where bash would ignore errexit inside it. A hook may read, and never set: `$build` (the sha12), `$sha`, `$release` (its directory), `$ROOT`, `$UNIT_DIR`, `$UNITS_DIR`, `$PROJECT` and `$TAG`, and call `note`, `say` and `journal`.

| Hook | Runs | Returns |
|---|---|---|
| `build_extra` | in the release, as the deploy user, before it is made read-only | non-zero refuses |
| `post_build_check` | in the release, after `REVISION` is read back | non-zero refuses, and takes `REVISION` back off |
| `pre_switch_check <target>` | from the checkout, before migrate | non-zero refuses, journaled |
| `migrate <target>` | from the checkout, before the switch | non-zero refuses. Idempotent, expand-only, skipping a database that is ahead (a rollback) |
| `verify <unit> <want>` | after the restart, per changed service | 0 verified, 1 failed (switch back), 2 no check for this unit |
| `post_verify <target>` | after a verified deploy | non-zero is a note, never a rollback. A smoke run here must refuse a target that isn't `_dev`/`_test` (provisioner) |

**Migrating through a oneshot unit** (observo, whose deploy user can't read the DSN): `migrate` runs `sudo -n systemctl start <p>-migrate@<sha12>.service`, a template with the app's `User=` and `EnvironmentFile=`, then reads its outcome with `journalctl --sync` and `--since`, or it reads the previous run's line. The template is in `UNITS_DIR` like any unit, but `migrate` runs before step 7: on the deploy that adds or changes it, the hook installs it from the release itself.

### The verify helpers

Each returns 0 when the unit proved `<want>`, and 1 with a note when it did not.

| Helper | Proves | From |
|---|---|---|
| `verify_http_health <url> <want> [<jq>]` | the endpoint answers JSON that `<jq>` holds of, `$want` bound; default `.revision == $want` | status, observo, archiver |
| `verify_next_tick <service> <want> [<message>]` | the timer's next natural tick (never forced) exits 0 and, given `<message>`, logs a JSON line with that message and `.revision == <want>` | broker's probe |
| `verify_forced_run <service> <want> [<file> <jq>]` | one forced run of a oneshot, after any run already going, exits 0 and leaves a file `<jq>` holds of | broker's backup |
| `verify_started_on <service> <want>` | a new main PID, active, whose `/proc/<pid>/cwd` is the release `<want>` names (D9) | the core's default |
| `require_active_timer <timer>` | for `pre_switch_check`: refuses when the tick a verify waits for never comes | broker |

A worker with no HTTP port (provisioner's consumer, archiver's bus consumer) is verified through whichever unit reports its heartbeat: `verify_http_health <api>/health <want> '.consumer.build == $want'`. A stronger check than `verify_started_on` for an app that logs one is its journal start record naming the build (processor).

## Each pilot's hooks, filled in

Read from each script's function list and #372's thread; each repo's adoption issue confirms its own row.

| Repo | Targets | `SERVICE_DIR`, `UNITS_DIR` | `CI`, `UV_WRAPPER` | `build_extra`, `post_build_check` | `migrate` | `verify` | `ENABLE_NEW` |
|---|---|---|---|---|---|---|---|
| broker | live | `.`, `deploy` | github anon, co-pypi | —, imports + `read_revision` | — | probe: next tick; backup: forced run; drift: none | drift timer |
| status | dev, live | `.`, `deploy` | github, — | —, one Alembic head | `schema_state`, migrate unless ahead | sweep pass, `/ready`, `/health` build | — |
| processor | live | `.`, `deploy` | github, co-pypi | —, venv imports | — | start record on the build, then the smoke run | its new timers, named |
| observo | live | `.`, `infra` | github gh, co-pypi | npm build + bundle required, one head | `observo-migrate@<sha12>` oneshot | `/health` ok and `revision == sha12` | — |
| provisioner | dev (API only), live | `service`, `deploy` | none, own minter | —, one head | as the deploy user, skipped when ahead | `/health` names the build for the API and the consumer heartbeat | — |
| archiver | live (dev a rehearsal) | `.`, `deploy` | github, wheelhouse → co-pypi first | —, one head + every unit's entry module | migrate, `grant_readers` | `/health` `build_id`, a forced bus-health pass, `schema_serves` | — |
| replicator | live | from its inventory | from its inventory | —, imports | — | the drained worker restarted on the new `REVISION`; handler units included | — |

Adopting the core changes two pilots' trees: processor's and provisioner's releases become root-owned (D7), and observo and provisioner start installing units (D5), which widens their deploy user's sudo grant to `install` into `/etc/systemd/system`.
