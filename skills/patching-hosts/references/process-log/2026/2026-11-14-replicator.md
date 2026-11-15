## Session 2026-11-14 — replicator

co-replicator's second full run under the scripts, after its first on [2026-10-06](2026-10-06-replicator.md) (CannObserv/replicator#131) and a one-origin Tailscale run on 2026-10-23. It was overdue: the cadence went weekly on 2026-11-06, and the probe raised `cadence:overdue` with 14 windows closed. Maintenance lane, from the vendored skill at `1803026d`. The record is CannObserv/replicator#198, which closed 2026-11-14T01:44Z.

### Environment

exe.dev (exeuntu, generation `newer`), Ubuntu 24.04. A bus worker with no local data store: no `datastore` line, so no recovery point. apt's timers are masked. Tailscale is followed, with auto-update off on the node and on the tailnet. The canonical disk GC is installed, `alert_at_percent 85` on `/`, which read 81% at the start. The journal is persistent.

### Readings

- **Pending:** 71 security (a lower bound: the unattended-upgrades origins include the release pocket and ESM), 20 `-updates`, Tailscale 1, 5 phased. ESM: Pro not attached, 25 esm-apps. Hold groups: redis (a masked local `redis-server`, 2 packages), docker (`containerd`, units disabled), tailscale.
- **The maintenance dry run, first attempt,** `--dry-run-into` without `--refresh-into`: it read the host's own lists, 525 h old. `unattended-upgrade --dry-run` hit a 404 on a superseded `bind9-dnsutils` `.deb` and exited 1, leaving no summary, after a 60 MiB download. This is the fail-closed twin of address-validator's fail-open `count=0` the day before ([2026-11-13](2026-11-13-address-validator.md)).
- **The dry run with both flags, into the same directory** (apt reused the archives): 92 selected, 192 s, max RSS 260 MiB, a 161 MiB download. The GC's headroom was projected at 83% against 85.
- **The disk budget was the run's constraint.** The sensor rounds Use% up, so the real ceiling was 84.0%: ~411 MiB of room once the dry run's cache sat on `/`. The bulk's peak was a 227 MiB `locales-all` unpack. Nothing was reclaimed. The owner approved deleting the dry run's 162 MiB cache after the bulk.
- **The bulk:** 88 packages in **670 s, 3.5× the dry run**, inside its 876 s budget. Nothing auto-removed, nothing taken unheld, nothing moved version. The worker was never restarted (`restart l`).
- **The held steps:** redis 19 s (the masked unit stayed down), docker 19 s (containerd stayed disabled), tailscale 17 s (tailscaled restarted from its postinst; `Apply` stayed false).
- **The reboot was certain:** `libapparmor1` owns a file PID 1 maps, and libc6 and systemd were in the set. The chain ran from gate to reboot in 6 s. It copied no journal, since the journal is persistent. The platform kernel moved two builds.
- **Down 32 s,** from the chain's stop to the worker's `worker ready`. `NRestarts=0`, and `InactiveEnterTimestamp` unset. The fetch-policy replay was clean: 503 messages, 10 hosts, 53 ms.
- **After the boot:** all 12 post-boot checks passed, including `tailscale:auto-update` (#357's fix, confirmed on the host that found it). A fresh probe counted 0 in every class, with 0 findings.

### What the skill got wrong or lacked

1. **`--dry-run-into` without `--refresh-into` on a masked-timer host** aborted on a 404, a second data point for #629. SKILL.md step 1 showed the flags separately. **Since fixed** (#629): the probe won't count against stale lists in any lane, and the bulk's gate refuses a summary counted against them.
2. **Dormancy read the masked local `redis-server` as `in-use`.** `named_by` matched `redis` inside `check_redis_floor.sh` on the unit's `ExecStartPre` line, a script that checks a remote broker (the #491 family). **Since fixed** (#634): a script's filename is no longer read as use.
3. **The headroom gate checks download plus growth, not the unpack peak.** Here the peak (~322 MiB) would still have left Use% at 84. On a host closer to its line, the transient could page while the gate passes. Unmeasured: the sensor runs every 10 min, and the peak lasted seconds.

### Decisions

- **The run was held past a neighbour's window.** archiver's patch window was 22:00–23:59Z that night. Readings ran inside it; nothing that changed the host did, so that each host's outage reads cleanly. The bulk started at 00:33Z.
- **The owner approved every step in one message,** after the readings, the disk budget and the plan. Each step still ran through its own gate.
- **`exception setup-script:redelivered`** was added to the knob (review-by 2027-02-14), now that #352's fix gives it a declared remedy. The key was revoked in CannObserv/replicator#131.
- **No marker was written.** The bulk's run directory dates the run, and `cadence:overdue` cleared without one.
