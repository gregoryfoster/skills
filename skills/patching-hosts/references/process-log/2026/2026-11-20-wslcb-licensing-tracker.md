## Session 2026-11-20 — wslcb-licensing-tracker

This is the host's fourth run. The earlier ones: [2026-09-29](2026-09-29-wslcb-licensing-tracker.md), [2026-10-07](2026-10-07-wslcb-licensing-tracker.md), [2026-11-07](2026-11-07-wslcb-licensing-tracker.md). This one ran in the maintenance lane, from the vendored skill at `817963f6`, so the entry came upstream as #685. The record is CannObserv/wslcb-licensing-tracker#255 (comments 7031038388 and 7031153545), which closed 2026-11-20T17:17Z.

### Environment
- **Platform:** exe.dev (`exe-dev-exeuntu`), Feb-2026 image, Ubuntu 24.04.
- **Data stores:** one local PostgreSQL 16 cluster. The app's database is backed up off the node by its own nightly unit. The pytest database is dumped by the recovery point.
- **Docker:** a pair of containers (SocratiCode's Qdrant and Ollama), holding derived data, excepted.
- **Followed origins:** Tailscale and NodeSource, each its own held step.
- **Journal:** persistent.
- **Session:** runs at `oom_score_adj` -1000.
- **PID 1's log target:** set by a `system.conf.d` drop-in since 11-18 (`LogTarget=journal-or-kmsg`).

### Readings
- **Overdue, and reported.** The last run was 2026-11-06. One Tuesday window (11-17) closed with no run. This time the probe said so itself (`cadence:overdue`, #592). The run was brought forward with dated knob lines: the first was set from `date -u` once the owner chose to run now, and two later ones were the fallbacks. All three were removed after the run.
- **Pending** (`--refresh-into`, lists 0 h old):
  - 20 security (lower bound): glibc, perl, needrestart, four python3 packages, sosreport, `linux-libc-dev`, and nginx (dormant; a prune is pending in its own issue);
  - 27 `-updates`: the systemd/udev family, phased at 10% with this host in the phase, plus mesa, distro-info and snapd;
  - Tailscale 1 and NodeSource 1;
  - ESM: Pro isn't attached; 26 esm-apps listed;
  - language: 4 advisories in 2 packages in `uv.lock`, each with a fix available.
- **The set grew between pre-flight and run:** 16 + 13 (+2 third-party) on 11-18, 20 + 27 (+2) on 11-20. The systemd family, nginx and three others arrived in between.
- **The maintenance dry run:** 49 selected, 87 s, max RSS 260 MiB, a 162 MiB download. `/` projected at 69%, against the GC's 80% alert.
- **The recovery point:** `recovery-point.sh` started the backup unit, which ran 22 s and wrote its object, and dumped the pytest database (12 MB). The owner checked their off-node copy's sha256.
  - The backup's object name still isn't printed. Its `next` says `--offnode-object <its name>`, so the name was read from the unit's journal, as on [watcher's run](2026-11-16-watcher.md) (#682).
- **The bulk:** 47 packages in **231 s, 2.66× the dry run**. Max RSS 259 MiB. Nothing auto-removed, nothing taken unheld, no version moved. `run_span` budgeted 2115 s, the reboot included.
  - PID 1 re-executed twice.
  - needrestart upgraded itself, and the host's `conf.d` list-mode file survived. The proof still prints `Disabling Ubuntu mode`.
- **The held steps:**
  - tailscale, 17 s: tailscaled restarted from its postinst, and `--daemon` matched the client;
  - nodejs, 18 s: the bundled npm changed, but the `_npx` key SocratiCode is pinned by didn't.
- **The reboot was certain:** PID 1, dbus, logind and the Postgres cluster mapped libc6 or libsystemd, and `reboot-required` named libc6. PID 1 mapped no deleted files after its re-exec, which on its own would have read as no reboot needed. The chain ran from start to reboot in 1 s.
- **Down 12.3 s,** from the app's `Finished server process` to `Uvicorn running`. That's the same as the 11-07 run.
- **After the boot:**
  - 14 of 15 post-boot checks passed. The one failure is `session-adj` (-1000), a known host gap.
  - The after-probe counted 0 in every apt class. Its findings were `session:adj` and `dormant:nginx`, and `cadence:overdue` cleared.

### What the skill got wrong or lacked
- **PID 1's log target after a boot comes from exe-init's argv,** `--log-target=syslog`, which systemd reads as `journal`. `system.conf.d` takes effect only at the first daemon-reload or re-exec. So:
  - the profile's "`console`" is the image override's post-reload state, not the boot's;
  - `--post-boot`'s `pid1_log_target` reads the new boot, not the shutdown that the PID 1 lines evidence.

  Filed as #684, since fixed: the probe reads the target from argv, conf, kernel and environment, and what a reload and a re-exec would apply ([the profile](../../environments/exe-dev-exeuntu.md)). Boot −1 here shows the trap: a reload on 11-12 put PID 1 on `console` for six days.
- **The backup unit's object name isn't printed** by `recovery-point.sh`. This is a recurrence of #669's gap, tracked as #682 and addressed in the same set: the script shows the unit's journal lines from the run it watched; nothing new filed.

### Decisions
- **nginx in the bulk.** nginx had a security update while a prune of it was pending in its own issue. The bulk upgraded it in place: holding it would have left security above 0. One change per window, so the prune runs on its own.
- **The window.** It was set by the owner's choice in the session, written as a dated knob line from `date -u`, merged and gated before the apply. The owner approved every step at once.
