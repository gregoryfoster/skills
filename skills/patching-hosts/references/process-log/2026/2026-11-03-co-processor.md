## Session 2026-11-03 — co-processor

The host's second run ([2026-10-26](2026-10-26-co-processor.md)), and the first in its weekly window (`Tue 05:00-10:00`, `posture scheduled`, `cadence` weekly by default). **The window passed with no run, because nothing asked the owner.** The run happened out of window the same afternoon, owner-attended, under a one-off window. The record is a comment on CannObserv/processor#113, the issue the miss was filed on.

### Environment

- exe.dev, `exe-dev-exeuntu`. Booted 2026-10-30T17:54Z, after a hard reset (CannObserv/processor#83).
- The journal is persistent, reaching back to 2026-09-29.
- The apt timers are masked, `APT::Periodic::Enable` is 0, and needrestart is at `restart=l` from a tracked drop-in.
- The session runs at `oom_score_adj` 0.
- No data store is declared. The scratch `redis-server` stays the default `redis` hold group, and Tailscale is its own held step.

### Readings

- **`probe.sh --refresh-into`, with the lists refreshed:**
  - security 0 (a lower bound), `-updates` 0, ESM visible 0;
  - third-party 2: NodeSource `nodejs` and Tailscale `tailscale`;
  - reboot not due: no `reboot-required`, no needrestart services, `pid1_deleted_maps` 0;
  - **language: 11 advisories in the live tree's `uv.lock`** (pypdf ×7, pyasn1 ×4; owner `self`).
- **The maintenance-lane dry run** (`--dry-run-into`): 2 packages, 10 s, max RSS 249 MiB, a 77 MiB download, no conffile prompts. Disk projected at 63%, under the GC config's 85% `alert_at_percent`.
- **The bulk took 4 packages in 29 s (2.9× the dry run):** `nodejs`, plus three `bind9` client packages (`dnsutils`, `host`, `libs`) from `-updates`, published between the probe's refresh and the bulk's own.
  - The gate passed: the lane covers `-updates`, and only a held group's candidate moving is checked (#488).
  - Health 2/2, nothing auto-removed.
- **The held `tailscale` step:** 15 s, RSS 188 MiB. Its postinst restarted tailscaled once, with one `linkChange`. The bus worker logged no WARNING across it, and the broker still resolved over MagicDNS.
- **No reboot** after the run, by the same three reads.
- **After** (`--refresh-into`): 0 in every apt class, and no findings. The language class still read 11, owned by the repo and tracked there; the repo cleared them the same day (CannObserv/processor#112, live 17:05Z).

### What the skill got wrong or lacked

- **Nothing solicits the owner's approval for a `scheduled` window.** The posture rests on the owner approving "each run in that host's own session" ([policy.md](../../policy.md)), but nothing reminds the owner when the window opens.
  - This window fell at 21:00–02:00 Pacific, and nobody opened a session.
  - The coordinator's own periodic check found the miss at 12:47Z, after the window had closed.
  - A missed window defers `-security` by a whole cadence.

  The cohort survey (9 hosts' knobs, all `scheduled`) found no host with a reminder. The host has since built its own (CannObserv/processor#113):
  - **`posture automatic` for `-security`.** The apt timers were moved clear of the window, because `apply.sh`'s `gate_apt` refuses any step whose span meets `apt-daily-upgrade.timer`'s range, and the stock 06:00 + 60 min falls inside a Tuesday 05:00–10:00 window.
  - **An hourly "patch due" check-in to the cohort's monitor**, which alerts once the window opens until a run record exists. A record is an issue comment whose first line is `## Patch run record: co-processor`, from a public member.

  **Since fixed** (#592): a window that closed with no run since is a `cadence:overdue` finding, wherever the probe runs. wslcb-licensing-tracker's four missed Tuesday windows were the second occurrence (its run of 2026-11-06). The reminder itself stays the host's to build, and so does a convention for a record's first line that a machine can read.
- **The dry run's selection is a snapshot,** and the bulk's refresh can widen it. Three `-updates` packages arrived unannounced. Harmless here, but the proposal the owner approved named two packages, not five.
- **`--dry-run-into`'s root-owned `archives/` cache** and three `--refresh-into` list directories took 182 MB of the scratch directory until removed with `sudo`. The probe says to remove the cache, but not the lists.

### Decisions

- **Run outside the window, the same day:** the owner's call, rather than deferring a week.
- **A one-off window from `date -u` at approval** (15:37–17:37Z, reason `processor#113`), in a `--config` copy of the knob, so the committed knob didn't change. This is the promoted rule; it worked first time.
- **Both steps approved together.** `tailscale`'s restart was accepted as a seconds-long tailnet gap: the bus worker's in-flight entries stay pending and are reclaimed, and liveness has 900 s of grace.
- **The record went on the issue the miss was filed on,** per the knob's `records`.

### Surprises

- **The language class found what the lock audit had been reporting, unread, for 2.5 days:** pypdf ×7 in the extraction child, which parses untrusted PDFs. The run read it in seconds, and the repo fixed it the same day with an extraction-stack bump.
- **The record became machine-read three days later.** The patch-due check counts a record only from an `OWNER` or `MEMBER` author, and the repo is public. An anonymous read sees a private org member as `CONTRIBUTOR`, so the owner's membership had to be made public before the check could count this very record.
