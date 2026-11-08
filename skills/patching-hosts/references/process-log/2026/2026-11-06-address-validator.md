## Session 2026-11-06 — address-validator

Host 2 of the step 0 round ([2026-09-29](2026-09-29-address-validator.md)). This was its first run under the scripts, in the maintenance lane, from the vendored skill at `227de51e`. That SHA was recorded at the session's start, after the daily auto-refresh had moved the pointer; nothing was pulled mid-run. The window was a one-off, set the same day when the owner moved the run from Sunday to a weekday (addendum 3 on CannObserv/address-validator#311). The record is on CannObserv/address-validator#311, which closed 2026-11-06T20:56Z.

### Environment

exe.dev (exeuntu), the Feb-2026 image, Ubuntu 24.04. A local PostgreSQL 16, backed up off the node by its own nightly unit. A Docker sidecar (libpostal) in the production path. Tailscale pinned, with auto-update off. NodeSource followed. The journal has been persistent since CannObserv/address-validator#241, and had never been through a reboot.

### Readings

- **Pending:** 72 security (exact, from a security-lane dry run of 139 s), 84 `-updates`, NodeSource 1, Tailscale 1, phased 2. ESM: Pro not attached, 26 esm-apps listed. The hold groups: postgres empty, docker held `containerd` (a point release), tailscale held its package.
- **The maintenance dry run** first exited 1 on fwupd's conffile prompt (below). After the fix it exited 0: 156 selected, 328 s, max RSS 262 MiB, a 315 MiB download, the GC's headroom projected at 53% against an 80% alert.
- **The recovery point:** the backup unit ran in 4 s and wrote its object off the node. The globals dump was kept on the node, 0600.
- **The bulk:** 154 packages in **926 s, 2.82× the dry run**, a data point for #556's span budget (since fixed). Max RSS 263 MiB. It auto-removed `libfwupd2` and `libgusb2`, which fwupd 2.0 had left unused. Nothing was taken unheld, and nothing moved version.
- **The held steps:** tailscale took 14 s, and docker 13 s.
  - tailscaled restarted from its postinst; `--daemon` matched the client.
  - containerd restarted itself. The libpostal container survived on its shim: neither docker.service nor libpostal.service moved.
- **The reboot was certain:**
  - PID 1 mapped 25 deleted files;
  - `reboot-required` was present (apparmor);
  - needrestart listed dbus, logind, journald, the Postgres cluster, the app and `user@`.
  - The chain ran from stop to reboot in 1 s. The platform kernel moved one build.
- **Down ~16 s,** from the chain's stop of the app to its startup-complete line. The app's first start after the boot succeeded with `NRestarts=0`; in step 0 it had failed once on a dependency (CannObserv/address-validator#239).
- **The persistent journal survived its first reboot:** `--list-boots` shows 2, and `-b -1` ends in `Journal stopped`. The chain correctly copied nothing.
- **After the boot:**
  - the post-boot probe's one finding was `session-adj` (below);
  - a fresh probe counted 0 in every apt class, with 0 findings;
  - `apt list --upgradable` was empty.

### What the skill got wrong or lacked

1. **The fwupd conffile trap's `--force-confmiss` remedy would have upgraded, not reinstalled.** The Feb-2026 image's fwupd build left `noble-updates` in February, so `--reinstall` resolves to the 2.0 candidate: a three-package upgrade outside every gate. What worked was restoring the conffile alone from the snapshot `.deb`, checked against dpkg's own md5. **Since fixed** (#582).
2. **The post-boot `session-adj` check ignored `exception session:adj`.** It passed no exception key, unlike the ordering check, so an excepted lineage still read as 1 finding after every reboot. **Since fixed** (#581).
3. **Where the one-off `--config` copy lives isn't said.** The coordinator's brief put it "in the run directory". But that directory is made by `recovery-point.sh`, which already reads `--config`, and it's root-only, 0700. So the copy went in the operator's home, outside the repo, and its diff went into the record. One line in `run.md`'s gate bullet would settle it.

### Decisions

- **A one-off window from a knob copy,** set at 20:00:45 UTC when the window opened, after the owner's approval. The committed knob's window test stays green, and the weekly Thursday window landed afterwards as its own PR.
- **The owner pre-approved every step in one message,** after the readings and spans were shown. Each step still ran through its own gate.
- **The backup unit's object was attested from its own success line.** Its upload uses `if_generation_match=0`, and the host has no CLI to list the bucket.
- **No Postgres held step:** its hold group was empty, so the cluster restarted only with the reboot. That left one caller outage instead of two.
- **The callers were told 2 h ahead,** each from its own repo's token. A private third caller was told by hand.

### Surprises

- **`index` came back relayed (DERP), not direct,** for about 7 min after the boot. The host's public egress address had changed. `codebase_health` stayed green through the relay, and the path went direct by itself.
- **The wslcb caller's quiet ranges were PDT-only.** Its timers run on Pacific time and the knob is UTC, so since 2026-11-01 its calls had fallen outside them. That's not the skill's to know, but a `caller` whose own schedule follows DST is worth a sentence in `knob.md`'s `quiet` row: cover both offsets. Fixed in CannObserv/address-validator#408.
- **The knob's recovery check was a `health` line,** written before #423 split the two. Every probe since then had made real requests and written audit rows. Moved to a `recovery` line in CannObserv/address-validator#408.
