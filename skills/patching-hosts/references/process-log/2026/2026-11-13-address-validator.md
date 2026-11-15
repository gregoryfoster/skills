## Session 2026-11-13 — address-validator

The host's second run under the scripts ([2026-11-06](2026-11-06-address-validator.md)), and its first weekly one: a catch-up for the Thursday 2026-11-12 window, which passed unrun. Maintenance lane, from the vendored skill at `1803026d`. The owner bumped it by hand before the run, because the day's auto-refresh had already failed. The window was a one-off from a `--config` copy of the knob, set when the owner's approval arrived. The record is a comment on CannObserv/address-validator#311, posted 2026-11-13T18:57Z.

### Environment

As on 2026-11-06: exe.dev (exeuntu), the Feb-2026 image, Ubuntu 24.04. A local PostgreSQL 16 backed up off the node by its own unit, a Docker sidecar in the production path, Tailscale and NodeSource followed, and the journal persistent. The apt timers are masked, so the host's own lists were 167 h old.

### Readings

- **Pending:** 12 security (exact, from the security-lane dry run): the libc6 family, perl, and two Python libraries. 5 `-updates`, all phased at 40%. NodeSource 1, Tailscale 1. ESM: Pro not attached, 26 esm-apps listed. Only the tailscale hold group had anything pending.
- **The dry runs counted 0 at first** (below). With `--refresh-into` they counted 19 in 39 s (maintenance) and 12 in 24 s (security). Max RSS 257 MiB, a 120 MiB download, the GC's headroom projected at 53%.
- **The recovery point:** the backup unit ran in 3 s and wrote its object off the node.
- **The bulk:** 18 packages in **113 s, 2.90× the dry run**. Max RSS 262 MiB. Nothing auto-removed, nothing moved version, nothing taken unheld. Only snapd restarted itself. PID 1 re-executed for libc6.
- **Tailscale's held step:** 14 s. Its postinst restarted tailscaled; `--daemon` matched the client. The candidate had moved one patch release since the 11-06 run, and the dry run counted the version it took.
- **The reboot was certain** even with PID 1 mapping no deleted file:
  - `reboot-required` named libc6;
  - needrestart listed dbus, logind, journald, the Postgres cluster, the app, the sidecar and `user@`.
  - The chain ran from stop to reboot in 1 s and copied nothing, since the journal is persistent. The platform kernel didn't move.
- **Down ~23 s,** from the chain's stop of the app at 18:53:51Z to its startup-complete line at 18:54:14Z. On 11-06 it was ~16 s.
- **After the boot:**
  - `--post-boot`: 0 findings. The recovery line passed, and `session-adj` was matched by its exception (#581 verified);
  - a fresh probe counted 0 in every apt class, with 0 findings;
  - `apt list --upgradable`, `showhold` and `dpkg --audit` were all empty;
  - the tailnet peer was direct straight away. On 11-06 it was relayed for ~7 min.

### What the skill got wrong or lacked

1. **A dry run counted against stale lists passes the bulk's gate.** Without `--refresh-into`, `--dry-run-into` raised `lists:stale` and still wrote `exit=0 count=0 wall_seconds=3`. `apply.sh`'s `gate_dry` refused a 0 count only in the `origin:` lane, so the bulk would have been budgeted at 9 s against a real 113 s. [2026-10-21](2026-10-21-co-status.md)'s entry had assumed the 0 refuses. **Since fixed** (#629): the probe won't count against stale lists in any lane, and the bulk's gate refuses a summary counted against them.
2. **Where the one-off `--config` copy lives is still unsaid** (gap 3 of 2026-11-06). It went under the operator's home again, outside the repo, because `/tmp` is wiped at every boot on this host and the run directory is root-only.

### Decisions

- **Both dry runs again, with `--refresh-into`,** instead of trusting the 0, which contradicted the refresh probe from a minute before.
- **The owner approved every remaining step in one message:** the notices, the window, the recovery point, the bulk, the tailscale step and the reboot. Each still ran through its own gate, with the clock re-read before it.
- **The backup unit's object was attested from its own success line,** as on 11-06.
- **The callers were told about 7 minutes ahead,** each from its own repo's token. One caller's notice could now name a repair path: its fallback rows are swept since that day. A private third caller was told by hand.

### Surprises

- **The missed Thursday window wasn't a `cadence:overdue` finding, by design.** It opened 5 d 22 h after the previous run, a Friday, and under `weekly` a window counts only more than 6 days after the last run. So a host whose run slips past its weekday window shifts its next counted window a week later. The probe would first have said so on 11-19.
- **The day's skills auto-refresh had failed on a push** and stamped its daily lock. Without the owner's hand bump, the run would have used the copy from before #581, #582 and #592.
