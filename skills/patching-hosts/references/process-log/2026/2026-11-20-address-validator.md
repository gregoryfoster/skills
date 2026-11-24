## Session 2026-11-20 — address-validator

The host's third run under the scripts ([2026-11-13](2026-11-13-address-validator.md)), and its second catch-up in a row: the Thursday 2026-11-19 window passed unrun. Maintenance lane, from the vendored skill at `284c3d9e`, so the entry came upstream as #687. The coordinator's read-only pre-flight had run from `817963f6`, an ancestor 10 patching-hosts commits older. Two one-off windows from a `--config` copy of the knob, each set when an approval arrived. The record is on CannObserv/address-validator#311, posted 2026-11-20T17:06Z.

### Environment

As on 2026-11-13: exe.dev (exeuntu), the Feb-2026 image, Ubuntu 24.04. A local PostgreSQL 16 backed up off the node by its own unit, a Docker sidecar in the production path, Tailscale and NodeSource followed, the journal persistent, and the apt timers masked.

### Readings

- **Pending:** 6 security (exact): a perl library, gstreamer, needrestart itself, two Python libraries and sosreport. 22 `-updates`, **every one phased**: the systemd/udev family at 10%, mesa at 80%, alsa-ucm-conf at 60%, ubuntu-dev-tools at 40%, and linux-libc-dev. No third-party packages. ESM: Pro not attached, 26 esm-apps listed. Every hold group was empty.
- **The dry runs, both with `--refresh-into`:** maintenance 28 in 51 s; security 6 in 24 s, max RSS 260 MiB.
- **`apt-get -s upgrade` on the same lists took 15 and deferred 13 for phasing**: the systemd/udev family and ubuntu-dev-tools. The maintenance lane takes all 22, since unattended-upgrade ignores phasing.
- **The recovery point:** the backup unit ran in 3 s and wrote its object off the node.
- **The bulk:** 28 packages in **112 s, 2.20× the dry run**. Max RSS 263 MiB. Nothing auto-removed, nothing moved version, nothing taken unheld. PID 1 re-executed, then journald and timesyncd restarted. resolved and udevd are masked on this image.
- **The reboot was certain** from needrestart alone: dbus, logind, the Postgres cluster and `user@`. PID 1 mapped no deleted file, and `reboot-required` was absent, since no libc6 was in the set.
- **Down ~17 s,** from the chain's stop of the app at 17:02:35 to its startup-complete line at 17:02:52 (17.1 s apart). The platform kernel didn't move.
- **After the boot:** `--post-boot` 0 findings, the recovery line passed, and a fresh probe counted 0 in every apt class with 0 findings. The tailnet peer was direct straight away. The needrestart drop-in still proved after needrestart's own upgrade.

### What the skill got wrong or lacked

1. **The maintenance lane can't respect apt's phasing** (#686). The owner's brief said not to force phased updates and expected apt to hold most back. The skill offered the security lane, which drops the 9 updates this machine was in phase for, or the maintenance lane, which forces systemd at 10% and makes the reboot certain. #354 made the phased packages visible in the count, but nothing says which of them apt would defer here; the operator found that by running `apt-get -s upgrade` by hand.
2. **`impact.maps` isn't scoped to `--lane`** (same issue). The security-lane probe listed `libsystemd0` mapped by PID 1 and Postgres, although no systemd package was in that lane.

### Decisions

- **The owner took the maintenance lane, all 28,** once shown the deferral: forcing the phased updates knowingly, over an off-skill hold-and-release.
- **The first window started at the end of a quiet range.** The approval arrived at 05:28 inside 02:30–06:15, so the line read 06:15–07:25, ending where the next quiet range starts. The recovery point waited for 06:15 too, clear of the nightly jobs.
- **The second window was set from `date -u` at the fresh 3(b),** 17:00–02:30, and the callers' notices were updated before it.

### Surprises

- **The owner's 3(b) arrived 8 h 20 min after it was asked,** after the window had closed and inside the 13:25–15:15 quiet range. `reboot-chain.sh`'s gate refused on both counts and stopped nothing. The host then ran healthy for 10 h 44 min on deleted systemd libraries (Postgres, dbus, logind), with no security fix waiting on them. The bulk's span had budgeted the reboot inside the first window, but nothing holds an approval to it. The chain's own gate is what caught it.
- **The missed Thursday wasn't a `cadence:overdue` finding again,** for the same reason as on 11-13: the last run was a Friday, so the next Thursday window opened under 6 days later. Two consecutive catch-ups have moved this host's runs to Fridays without the probe flagging either miss. It recurred, so it's promoted ([knob.md](../../knob.md)'s `cadence` row).
