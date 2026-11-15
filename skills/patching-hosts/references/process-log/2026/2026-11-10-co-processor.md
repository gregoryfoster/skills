## Session 2026-11-10 — co-processor

The host's third run ([2026-11-03](2026-11-03-co-processor.md)), and its first window under `posture automatic`, from the vendored skill at `b51f3c24`. It's also the first window with the host's own "patch due" check-in (CannObserv/processor#113). The record is a comment on that issue, which closed 2026-11-10T16:44Z.

**The check worked, and the window was still missed.** It asked at the window's opening (`due`, 05:00:32Z) and every hour after that. The coordinator session asked the owner at 05:07Z (Monday 21:07 Pacific) and got no answer. The check went to `missed` at 10:00:34Z. The run happened out of window the same afternoon, owner-attended. Its record turned the check `ok` at its next hourly tick, 3 min later.

### Environment

- exe.dev, `exe-dev-exeuntu`, booted 2026-10-30T17:54Z. The journal is persistent. needrestart is at `restart=l` from a tracked drop-in.
- **`posture automatic` since 2026-11-05.** The apt timers were moved clear of the window: `apt-daily` at 12:00 + 30 min, `apt-daily-upgrade` at 13:00 + 60 min.
- No data store. Hold groups: the default `redis` group (for the scratch server) and `tailscale`.

### Readings

- **Between the window and the run, the security lane did its job.** unattended-upgrades took the Perl family and `python3-pyasn1` at 13:42Z. The run's dry run then read security 0.
- **The maintenance-lane dry run**, after `apt-get update`:
  - 8 `-updates` packages: `sqlite3`, `libsqlite3-0`, `linux-libc-dev`, `snapd`, and four `distro-info`/`lintian` packages, phased at 10%;
  - 24 s, max RSS 260 MiB, a 26 MiB download;
  - no findings.
- **A reboot was already due before the bulk.** PID 1 mapped 5 deleted files, and needrestart listed `systemd-manager`, dbus, journald, logind, polkit, cron and timesyncd. These are residue from the security lane's earlier days, not from this set.
- **The bulk** (approval 2) took all 8 packages in **128 s, 5.3× its dry run**. Health 2/2, nothing auto-removed, no held step pending. `snapd`'s postinst left `snapd.socket` alone ("disabled or a static unit not running, not starting it").
- **The reboot chain** (approval 3(b)):
  - gate passed 15:22:46Z; `processor.service` stopped in 3 s;
  - the journal was persistent, so nothing was copied;
  - `systemctl reboot` at 15:22:49Z, booted 15:22:59Z;
  - the bus worker was consuming again at 15:23:04Z, **about 18 s of downtime**.
  - **The platform kernel moved two builds** at this in-guest reboot (the promoted rule held).
- **`--post-boot`:** 12/12 ok. **After** (`--refresh-into`): 0 in every apt class, 0 findings, and 0 advisories in the live `uv.lock`.

### What the skill got wrong or lacked

- **The bulk ran at 5.3× its dry run,** above the 2.0–4.0 run.md cites as measured. The set was small (8 packages), and `lintian` and `snapd` were the heavy unpacks. A small dry run probably has a fixed setup cost that a ratio misprices. The gate's 3× estimate (372 s, with 300 s of health) still held, because the health term dominated, so nothing failed. For a short window, the ratio underestimates small sets.
- **The bulk's span ignored a reboot that was already due.** `apply.sh`'s `run_span` read `"reboot": false`, because the selection itself made no reboot certain. But PID 1 already mapped deleted files from the security lane. Under `posture automatic`, that will be the usual state on attended-run day, so the span should count the chain whenever the host already needs one. Here the 4-hour one-off window left room. In a window sized to the bulk alone, the chain would have been refused.
- **A dated `window` reason beginning with `#` is silently dropped.** The line `window 2026-11-10 14:10-18:10 #113-out-of-window` parsed with `reason: null`: `#` after whitespace starts a comment, which is reasonable. But nothing warned, and the 2026-11-03 run's `processor#113` worked only because it didn't begin with `#`. `read-knob.sh` could say when a dated line's trailing comment looks like an intended reason, or knob.md could note it. co-index's dated lines did the same ([2026-11-03](2026-11-03-co-index.md)).

### Decisions

- **Run out of window, the same day,** for the second week running: the owner's call. A missed week under `automatic` costs only `-updates` and the deferred reboot, since `-security` arrives daily.
- **A one-off window from `date -u`, set when the owner approved,** in a `--config` copy (14:10–18:10Z). The promoted rule, used a second time on this host.
- **Each step approved on its own:** bulk, then the chain. The chain was printed without `--approve` first, for the owner to read.
- **The reboot taken in the same run,** decided from host state, not from the set ([reboot-and-record.md](../../reboot-and-record.md) §4).

### Surprises

- **A reminder doesn't make the owner available.** The window is 21:00–02:00 Pacific, and the ask went unanswered. The `missed` alert did its job: the owner acted on it the same day. Whether the window itself suits the owner is the host's question, not the skill's.
- **The session survived the in-guest reboot.** The agent session (Claude Code) resumed after the boot with its scheduled jobs intact, so the post-boot checks, the after-probe and the record followed without a hand-off. A written hand-off was prepared anyway.
