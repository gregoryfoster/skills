## Session 2026-11-07 — wslcb-licensing-tracker

The host's third run ([2026-09-29](2026-09-29-wslcb-licensing-tracker.md), [2026-10-07](2026-10-07-wslcb-licensing-tracker.md)), in the maintenance lane, from the vendored skill at `227de51e`. The run was on 2026-11-06, and its record's second part was posted at 22:18Z that day. The record is CannObserv/wslcb-licensing-tracker#248 (comments 6697146224 and 6697237556); the entry is dated by that issue's close, which waited on the 2026-11-07 check-ins.

### Environment

- exe.dev (`exe-dev-exeuntu`), the Feb-2026 image, Ubuntu 24.04.
- One local PostgreSQL 16 cluster. The app's database is backed up off the node by its own nightly unit; the pytest database is dumped by the recovery point.
- A Docker pair (SocratiCode's Qdrant and Ollama: derived data, excepted).
- Tailscale and NodeSource followed, each its own held step.
- The journal has been persistent since CannObserv/wslcb-licensing-tracker#186. The session runs at `oom_score_adj` -1000.

### Readings

- **Overdue.** The last run was 2026-10-06. Four Tuesday windows passed with no run and no finding. The knob had no `cadence` line, so weekly by default; it now states it.
- **Pending** (`--refresh-into`): 56 security (a lower bound), 17 `-updates` (containerd's point release among them), Tailscale 1, nodejs 0. ESM: Pro not attached, 26 esm-apps listed. Language: one transitive package with 4 advisories in `uv.lock`, the same package co-processor's run found ([2026-11-03](2026-11-03-co-processor.md)). The repo fixed it, and synced the host, the next day (CannObserv/wslcb-licensing-tracker#250).
- **The maintenance dry run:** 74 selected, 171 s, max RSS 264 MiB, a 180 MiB download, `/` projected at 68% against the GC's 80% alert.
- **The recovery point:** `recovery-point.sh` started the backup unit, which ran 25 s and wrote its object, and dumped the pytest database (12 MB). The owner checked their off-node copy's sha256.
- **The bulk:** 72 packages in **345 s, 2.0× the dry run**, the lowest ratio measured: #556's spread was 2.2–4.0, and this is a data point for its span budget (since fixed). Max RSS 265 MiB. Nothing auto-removed, nothing taken unheld, no version moved.
- **The held steps:**
  - tailscale, 11 s: tailscaled restarted from its postinst, and `--daemon` matched the client;
  - docker (containerd only), 13 s: containerd restarted itself, and both containers stayed up on their shims.
- **The reboot was certain:** PID 1 mapped 15 deleted files; needrestart listed dbus, logind, the Postgres cluster, the app, journald and `user@`. There was no `reboot-required`. The chain ran from start to reboot in under a second. The platform kernel moved one build, as on [address-validator](2026-11-06-address-validator.md) the same day.
- **Down 12.3 s**, from the app's `Finished server process` to `Uvicorn running`.
- **After the boot:**
  - 14 of 15 post-boot checks passed; the one failure is `session-adj` (-1000, a known host gap);
  - `-b -1` ends `Journal stopped`;
  - both containers came back at boot (docker.service is enabled);
  - the after-probe counted 0 in every apt class, and its only finding was `session:adj`.

### What the skill got wrong or lacked

- **A missed `scheduled` window is silent.** This is the second occurrence, after co-processor's. **Since fixed** (#592): a window that closed with no run since is a `cadence:overdue` finding.
- **The after-probe refused `--lane` without `--dry-run-into`** (exit 2), and §7 didn't say the after-probe takes no lane. **Since fixed** (#593).
- **`pending.language` gave counts, not advisory IDs or fixed-in versions,** so a hand `uv audit` was needed for the repo's issue. **Since fixed** (#594). The repo's own read then found none of the four reachable on this host, which the IDs alone wouldn't have shown either.
- **A host test that asserts "no findings on a far-future date"** (wslcb's knob guard, at 2099-12-31) fails as soon as the knob carries a dated `window`, which reads `past-window` there. The host tolerated `past-window` beside `expired-exception`. knob.md could note that a dated line expires like an exception.

### Decisions

- **The one-off window was set ahead, not at approval:** dated knob lines for that day and the next as a fallback, both 17:00–23:30Z and clear of every quiet range, merged before the apply. This departs from the promoted rule (set it from `date -u` at approval). It held because the range was wide (6.5 h) and the owner approved every step at once, within the hour. The lines were removed after the run.
- **The off-node object was named from the backup unit's own success line.** The owner confirmed the dump's sha256, but not the object separately.
- **No nodejs step**, since nothing was pending. The repo's npx key check ran after the boot anyway, and found the pinned tree.

### Surprises

- **The bulk ran fast** (2.0×) on a set dominated by small library upgrades, plus systemd's re-exec.
- **`/tmp` is emptied at boot here** (`D`, the Feb-2026 image). The profile already says so, and `reboot-chain.sh` listed what was staged. The operator still had scratch files there and moved them first, because the run's working files lived in an agent scratch directory under `/tmp`. Reading the chain's `tmp_staged` before launch is what caught it.
