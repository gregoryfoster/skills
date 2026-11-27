## Session 2026-11-17 — co-processor

The host's fourth run ([2026-11-10](2026-11-10-co-processor.md)), maintenance lane, from the vendored skill at `063ba5db`. The record is a comment on CannObserv/processor#113.

**The window was missed for the second week running.**
- The host's patch-due check read `due` at 05:00:33Z and `missed` at 10:00:32Z.
- The owner approved an out-of-window run at 15:50:42Z.
- It ran from a dated `window 2026-11-17 15:50-19:50` line in a `--config` copy of the knob, set when the approval came (the promoted rule). The committed knob was not changed.

### Environment

As on 2026-11-10:
- exe.dev, `exe-dev-exeuntu`, journal persistent;
- needrestart at `restart=l` from a tracked drop-in;
- `posture automatic`, with the apt timers outside the window;
- no data store; hold groups `redis` (a scratch server) and `tailscale`.

### Readings

- **The security lane had done its job since the last run.** unattended-upgrades took the libc6 family and `locales` (11-13), plus single packages on 11-11, 11-16 and 11-17. The dry run read security 0.
- **A reboot had been due for four days.** `/run/reboot-required` (libc6) had been set since 11-13 13:01Z. needrestart listed cron, dbus, polkit, the scratch redis-server, journald, logind, timesyncd and the user manager.
  - **The service didn't need a restart.** A deploy on 11-16, after the libc update, had already restarted it, so it mapped no deleted file.
  - PID 1 mapped no deleted file either.
- **The maintenance-lane dry run**, after `apt-get update`:
  - The refresh changed the set. An hour before, only NodeSource's `nodejs` and `tailscale` were pending. The update added 8 `-updates`: `alsa-ucm-conf` and 7 Mesa packages, phased at 10%. The dry run took them.
  - 10 packages, 21 s, a ~104 MiB download. The bulk took 9 and held `tailscale` for its own step. No conffile prompts, no removals.
- **New findings: `named:docker` and `dormant:nginx`.** The 11-10 run had none. The vendored skill had been bumped twice in between.
  - docker read `named` because the repo's docs and units mention it.
  - nginx read `dormant`: disabled, inactive since the image's install, empty logs.
  - Both were left open for a separate decision.
- **The bulk** (approval 2): 9 packages in **48 s, 2.3× its dry run**. Health 2/2, nothing auto-removed, the service not restarted.
- **The held `tailscale` step** (approval 3(a)): 17 s. tailscaled restarted, `broker` still resolved, and the service logged nothing at WARNING or above.
- **The reboot chain** (approval 3(b)):
  - gate passed; the service stopped in 6 s;
  - no volatile journal to copy;
  - booted 7 s after `systemctl reboot`;
  - **about 19 s down**;
  - the platform kernel did not move.
- **`--post-boot`:** 12/12 ok. **After** (`--refresh-into`): 0 in every apt class, 0 advisories in the live `uv.lock`. The two dormant findings remained.

### What the skill got wrong or lacked

- **Under `automatic`, a reboot that the security lane makes due waits for the attended run.** Here that was four days with dbus, logind and journald on an old libc, and the missed window stretched it further. The skill already reports `reboot:pending` as a finding. But the host's own patch-due check doesn't report it: its service user can't run needrestart. So the reboot's age showed up only when a person ran the probe. That's a host gap more than a skill gap. Still, the finding's text could carry its age. `reboot:pending` says only "already pending from an earlier upgrade", at `063ba5db` and at `be7c5809`. The record dated it only because the run read `/run/reboot-required`'s time by hand. The probe could read the file's mtime and put it in the finding, so a long wait is visible in the finding itself. Folded in the same set: the finding now says since when, from the file's mtime, as a date and whole days.
- **A skill bump can turn findings on between runs.** The two dormant findings appeared without any change on the host. That was correct, and it led straight to a prune. But nothing in the bump said a host would get new findings. A line in the bump's notes ("the probe now reports X") would let a host expect them.

### Decisions

- **Run out of window, the same day,** on the owner's approval. A dated window in a `--config` copy, set when the approval came.
- **The Tailscale upgrade as its own held step,** approved apart: its postinst restarts tailscaled, the host's only path to the broker.
- **The reboot in the same run,** from `reboot-required` plus needrestart's list, rather than restarting dbus and logind in place.
- **The dormant findings left out of the run.** That evening the owner started a separate prune ([pruning.md](../../pruning.md)): both were masked at 21:57Z (stage 1), with dated `disabled:` exceptions running until the next window's date, 2026-11-24. The purge was scheduled for after the 7-day soak.

### Surprises

- **The agent session didn't survive the in-guest reboot** (on 2026-11-10 it had). A new session picked up the run after the boot.
- **The session's scratch directory under `/tmp` survived** (the image's tmpfiles rule doesn't clear `/tmp` at boot). So did the `--config` copy of the knob in it, and the run finished from it. This is the opposite of 2026-11-16 watcher (#681). The difference is the `/tmp` rule, which `reboot-chain.sh` reports. Since then, a hand-off note goes into the scratch directory before each chain launches.
- **The phased Mesa set arrived between two readings an hour apart,** and the run's own `apt-get update` brought it in. It's another case for the rule that a dry run counts only against fresh lists.
