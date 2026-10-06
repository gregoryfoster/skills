## Session 2026-10-06 — replicator

The first run under the skill's scripts, end to end, on any host (#313 step 8b). CannObserv/replicator#131. A pure bus worker with no data store: patch, one followed third-party origin in its own held step, and a reboot. It was also the host's maintenance-lane catch-up: `-updates` and Tailscale as well as security.

### Environment

exe.dev, `exe-dev-exeuntu`, generation newer, 7 days since the last boot. The journal is persistent, reaching back 24 days, and PID 1 logs to `console`. **`/tmp` isn't emptied at boot here:** a local `/etc/tmpfiles.d/tmp.conf` overrides the image's `D` rule with `d … 30d`, and the probe read it (`cleared_at_boot: false`).

### Readings

- **The knob read clean on its first commit.** Its pieces:
  - `inflight` is a repo script: it sums `XPENDING`'s per-consumer counts for this worker's own consumer names only, and fails closed;
  - `health` checks `is-active`, plus a broker round-trip through the same script;
  - Tailscale is `follow`, scoped by apt pins (site at 100; `tailscale` and its keyring at 600), with its own `hold`.
- **The maintenance-lane dry run counted 35 packages:** 12 security, 21 `-updates`, Tailscale, and one more. **The probe's classes summed to 34.** The extra was a **phased** `-updates` package (dnsmasq-base, phased at 10%), which unattended-upgrade took and the class count left out.
- **The bulk took 34 packages in 172 s** against the dry run's 80 s, with max RSS 262 MiB.
  - Security families: OpenSSL, libevent, FreeType, libheif, libXpm, sg3-utils, Authen::SASL.
  - `-updates` families: Kerberos, audit, AppArmor, Mesa, ALSA UCM, dmidecode, libpciaccess, linux-libc-dev, sosreport, dnsmasq.
  - **No maintainer script restarted anything;** dbus re-read its config four times.
- **The `tailscale` step took a newer release than the dry run had seen.** A version landed between the two, and the step's fresh lists took it. Its postinst restarted tailscaled, which was `Running` 2 s later. The daemon matched the client, and tailscaled's `oom_score_adj` drop-in held. The worker, ordered `After=` tailscaled only, wasn't restarted and logged nothing.
- **The reboot was called for:** needrestart listed dbus, logind and systemd-manager, and PID 1 mapped 15 deleted libraries.
  - The chain fired on time.
  - The worker drained in 3 s, and `Journal stopped` was the last line of the boot.
  - There was no orphan recovery, and the first start succeeded with 0 restarts. The broker floor check needed 2 s for MagicDNS.
  - **Downtime: 17 s,** from the chain's stop to `worker ready`.

### What the skill got wrong or lacked

- **`restarter:<unit>` from `OnFailure=`.** This unit's `OnFailure=` starts a notifier, not a restart. Declaring it would stop the worker around every held step.
- **`setup-script:redelivered` can't clear.** The key was revoked, but nothing the probe reads changes, and the finding takes no exception.
- **`session:adj` fires on exe-init's own -1000.** Every session process under it reads 0. The post-boot check repeats the same reading.
- **A phased `-updates` package is missing from the class counts,** though the lane takes it.
- **The reboot chain lists `/tmp` as staged** on a host where the probe read that `/tmp` survives the boot.
- **The post-boot journal-copy check looks under `/var/backups/journal-*`.** The chain writes `<run>/journal`, and on a persistent journal it writes none, so the check reads `null` rather than "not needed".
- **Tailscale's auto-update came back at the reboot.** `tailscale set --auto-update=false` at 16:14Z held through tailscaled's postinst restart. At the boot, tailscaled logged `using tailnet default auto-update setting: true` and set `Apply=true` again. That refutes policy.md's "the tailnet's setting configures a device only as it joins". `--post-boot` doesn't read it, so it was caught by hand.

Each is filed as its own issue, #351 to #357, and each was fixed before the next host's run.

### Decisions

- **Tailscale is `follow` plus a `hold`, not `hold` alone.** Because the worker orders `After=` tailscaled without depending on it, tailscaled's restart costs only a tailnet blip. The held step fences that restart under its own approval.
- **The in-flight count is per consumer, not per group.** A dead consumer's stale entries would hold the gate shut.
- **The run directory stays on the default `/var/backups/patching-hosts-<UTC>`,** which survives the reboot.

### Surprises

The tailnet default re-applied over an explicit node setting. And the bulk ran more than twice as long as its dry run.
