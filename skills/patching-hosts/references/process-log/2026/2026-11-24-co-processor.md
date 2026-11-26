## Session 2026-11-24 — co-processor

The host's fifth run ([2026-11-10](2026-11-10-co-processor.md)), and its first under `posture automatic` taken inside its own window. The weekly window is Tue 05:00–10:00Z. The 2026-11-10 and 2026-11-17 runs had both been taken out of window, after `missed`. Maintenance lane, from the vendored skill at `be7c5809`. The record is a comment on CannObserv/processor#113.

**Asked on time and answered on time.**
- The host's patch-due check read `due` at 05:00:32Z.
- The owner approved the run in the host's own session, each sudo step as it came.
- The record was posted at 05:33:16Z, 33 min after the window opened.
- The check read `ok` at its next hourly tick, 06:00:32Z.

### Environment

- exe.dev, `exe-dev-exeuntu`. The journal is persistent. needrestart is at `restart=l` from a tracked drop-in.
- `posture automatic`. The apt timers run outside the window: `apt-daily` at 12:00 + 30 min, `apt-daily-upgrade` at 13:00 + 60 min.
- No data store. Hold groups: the default `redis` (the scratch server) and `tailscale`.
- Dormant components `docker` and `nginx` were masked on 2026-11-17 (prune stage 1). Each is covered by a `disabled:` exception whose last day is this window's date.

### Readings

- **The maintenance-lane dry run** (`--refresh-into` beside `--dry-run-into`), after `apt-get update`:
  - 13 `-updates`: the systemd family (10 packages, `libsystemd0`, `libsystemd-shared` and `udev` among them), `linux-libc-dev`, and the two `ubuntu-dev-tools` packages;
  - 4 security: `tzdata`, the two `libssh` packages, `python3-oauthlib`. The daily security lane hadn't taken them yet, so the maintenance bulk took them too;
  - 26 s, max RSS 257 MiB, an 11 MiB download. No conffile prompts, no removals, no held step pending;
  - **0 findings.** `docker` and `nginx` read `kept`, each naming its exception's knob line and `review by 2026-11-24`.
- **`apply.sh`'s span counted the reboot from the set:** `"reboot": true`, `"reboot_why": "libsystemd-shared, which owns a file PID 1 maps"`, `reboot_due: false`. The estimate was 1158 s, chain included, and fit easily. This answers the 2026-11-10 entry's case from the other side: here the set itself made a reboot likely.
- **The bulk** (approval 2): all 17 in **64 s, 2.5× its dry run**. Exit 0, health 2/2, nothing auto-removed. The service wasn't restarted.
- **The reboot decision** (step 6), read 9 min after the bulk:
  - no `/run/reboot-required`;
  - **PID 1 mapped no deleted file.** systemd's postinst had re-executed it;
  - the service's own process mapped none either;
  - **needrestart listed** dbus, polkit, systemd-logind, the scratch redis-server and the user manager, all through `libsystemd0`/`libsystemd-shared`.
  - A reboot rather than restarting dbus and logind in place.
- **The reboot chain** (approval 3(b)): printed first without `--approve`, then launched.
  - Gate passed at its fire time.
  - The service stopped in 6 s.
  - No volatile journal to copy.
  - Booted 6 s after `systemctl reboot`.
  - The service was down **about 14 s**.
  - The platform kernel did not move this time.
- **`--post-boot`:** 12/12 ok. **After** (`--refresh-into`): 0 in every apt class, 0 findings, 0 advisories in the live `uv.lock`, and 25 esm-apps updates visible (Pro not attached, unchanged).

### What the skill got wrong or lacked

- **After a systemd-family update, `pid1_deleted_maps` reads 0 and says nothing about a reboot.** The postinst re-executes PID 1 onto the new `libsystemd-shared`, so the reading that flagged the 2026-11-10 reboot is clean here. The reboot is still due, through the daemons that link `libsystemd0` (dbus, logind, polkit). reboot-and-record.md §4 already decides from needrestart's list plus `reboot-required`, and that held. But a reader who takes "PID 1 maps no deleted file" as the all-clear would skip the reboot. The profile could say so: after the systemd family, read needrestart's list, not PID 1's maps. Folded in the same set: the profile's restart table and [§4](../../reboot-and-record.md#4-the-reboot-decision) now say so.
- **A running component's `in-use` verdict doesn't survive the run's own reboot.** Before the run, the scratch `redis` read `in-use` ("no key now, but 3789 key lookups since it started"). The after-probe read `unknown` ("no key, but up only 0 days: fewer than 30"): its counters restart with the process. It isn't a finding. But on a host that reboots at every weekly run, the record's after reading never shows a running component as `in-use`. This is #633's mechanism (evidence that resets at boot) for an active unit rather than a never-started one. The after-probe could carry the before-probe's verdict forward when the only change is a restart inside the run.

### Decisions

- **The security packages went in with the maintenance bulk,** not left for the 13:00Z security lane. The lane takes the security set too, and the reboot was going to happen anyway.
- **A reboot, not in-place restarts,** decided from needrestart's list after the bulk. It matched the pattern measured on co-broker and co-status after the same family.
- **The exceptions were left to end on the window's day,** as written on 2026-11-17. They covered this run, and the reader reports the end of the soak from the next day. That date is the prompt for the purge (stage 3), clear of the window.

### Surprises

- **The run took 25 min, attended, end to end:** from `apt-get update` (05:08Z) to the record (05:33Z). Most of that was waiting for the reboot timer and the first post-boot check-ins.
- **The agent session survived the in-guest reboot again** (as on 2026-11-10, but not 2026-11-17). Only a foreground wait that spanned the boot was killed. A hand-off note was written to the session's scratch directory before the chain was launched, which is now the habit on this host.
- **The host's patch-due check ticked 5 min after boot, before the record was posted,** and read `due` a second time (05:32:01Z). The next hourly tick read `ok`. Harmless: the record can't be written until post-boot is read.
