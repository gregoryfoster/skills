# Profile: exe.dev VMs on the exeuntu image

This profile records how exe.dev's exeuntu image behaves where it differs from stock Ubuntu 24.04. Every fact carries its source and date. Most come from the step 0 round of [#313](https://github.com/gregoryfoster/skills/issues/313): ten hosts patched by hand, 2026-09-21 to 09-29, synthesised in [#313 comment 5898628226](https://github.com/gregoryfoster/skills/issues/313#issuecomment-5898628226). A measurement is an event: it stays true of the run that made it, and a newer image may differ. Re-measure before relying on it.

## Detection

The guest can't see its own image digest (CannObserv/broker#65, 2026-09-25), so detect the image by markers:

- the kernel's `init=/exe.dev/bin/exe-init` in `/proc/cmdline`;
- no installed `linux-image-*` package, and a platform kernel (6.12.93 in the round);
- `/exe.dev/` present;
- `/usr/local/bin/exeuntu` (absent on older images);
- `exe-setup.service` (absent on the Feb-2026 images).

## Two image generations

The round met two generations. The probe reports which one it's on, because the checks differ.

| | Feb-2026 images | Newer images |
|---|---|---|
| Hosts | power-map, address-validator, wslcb-licensing-tracker | broker, archiver, notifier, replicator, watcher |
| `exe-init` | runs as `init=`, execs exeuntu's `/usr/local/bin/init`, which execs systemd; nothing stays resident | stays resident; sessions start under it |
| `exe-setup.service` | none, and no `/exe.dev/setup` | present; re-runs the creation-time script on every boot |
| Journal | **volatile**: `systemd-journal-flush.service` is masked, so `/var/log/journal` stays empty despite `Storage=persistent` | persistent |
| Session path | through exe.dev's own `/exe.dev/bin/sshd`, at adj -1000 | through `exe-init`, until the session is reparented to PID 1 |

Not every row was read on every host. For the newer images, the unit's presence comes from all five hosts, but its re-run on every boot was counted on replicator and watcher only. notifier's failed on every boot, which is consistent with it. The journal row comes from notifier, replicator and watcher, and the session path from replicator and watcher. For the Feb-2026 images, the journal row comes from all three, and the `exe-init` and session rows from address-validator and wslcb.

usa-wa's image (May 2026) sat between the two: it has `exe-setup.service` but no `exeuntu`, and masks 3 units rather than 5 (CannObserv/usa-wa#430). Detect each marker on its own rather than inferring one from another.

On a volatile journal the reboot erases everything before it. That's how address-validator lost 51 days (CannObserv/address-validator#241, 2026-09-29), and wslcb 10 (CannObserv/wslcb-licensing-tracker#186). Copy the journal as the last step of the reboot chain ([run.md](../run.md)).

## Update channels

| Channel | State on the image | Owner |
|---|---|---|
| apt (Ubuntu archive + security) | **off**: `apt-daily.timer`, `apt-daily-upgrade.timer` and `unattended-upgrades.service` are masked, 3 units on usa-wa's image. The newer images, and exeuntu `main` at `ae8be4d` (#313, 2026-09-24), mask both `update-notifier` timers too, for 5 | the host's run ([policy.md](../policy.md)) |
| `APT::Periodic::Enable` | **0**, from `/etc/apt/apt.conf.d/docker-disable-periodic-update`, a Docker-base-image file. It makes the timers no-ops even when they're unmasked (CannObserv/archiver#278). A policy that turns them on must set `"1"` in a file sorting after it. | image |
| Kernel | the platform's; no guest kernel, so a kernel never decides a reboot | platform |
| `exeuntu update` | the agent binaries the image ships under `/usr/local/bin` | image / platform |
| Third-party apt | NodeSource or Tailscale on some hosts; not on others | per origin ([policy.md](../policy.md)) |
| Outside apt | `uv`, `claude`, `codex`, `gh`, `shelley`, container images, repo-installed pins | image, or the repo that installed it |

`20auto-upgrades` may say `1`/`1` while all of the above holds. Read the effective value with `apt-config shell E APT::Periodic::Enable`, never the file.

## Packages that restart their own services

The needrestart drop-in (`$nrconf{restart} = 'l';`) governs needrestart's apt hook only. Maintainer scripts restart what they like. Measured across the round:

| Package | Behaviour | Hosts |
|---|---|---|
| `postgresql-16` | stops and starts its cluster; 1.46–2.8 s down, no `redo starts` | every Postgres host that took it |
| `containerd` | restarts itself; containers survive on their shims | 3 of 4 (not power-map) |
| `docker.io` | **does not** restart dockerd (debconf `docker.io/restart` is false when noninteractive); the old daemon runs until a restart or reboot | 4 of 4 |
| `polkit` | restarts itself | 3 of 4 (not watcher) |
| `libc6` / `systemd` | PID 1 re-executes itself | replicator, watcher, address-validator, wslcb |
| `systemd` | the user manager re-executes, and journald and timesyncd restart | wslcb. On address-validator, needrestart still listed journald and timesyncd after the apply, so they hadn't restarted there. |
| `redis-server` | restarts the server from its postinst on upgrade (read in noble's 7.0.15-1ubuntu0.24.04.4, 2026-09-30); not measured, since broker held it | — |
| `packagekit` | D-Bus-activated, not restarted | — |

A data store needs a restart when its processes map a library in the set (`libc6`, `libssl3t64`, `libxml2`, `libsystemd0`), **even if its own package isn't in the set**. That was true on watcher, address-validator and wslcb.

`noble-security` shipped major bumps in the round: docker.io 28→29 and containerd 1.7→2.2. With no `/etc/containerd/config.toml` there was nothing to migrate (CannObserv/power-map#574).

## Package removals during a security apply

u-u's `Remove-New-Unused-Dependencies` removed packages the upgrade left unused: `libde265-0` and `libheif-plugin-libde265`, on both Feb-2026 hosts that measured it (address-validator, wslcb). They count in the dry run's selection. Record removals apart from upgrades.

## `/tmp` and `/var/tmp`

noble's systemd 255.4-1ubuntu8.17 ships `D /tmp 1777 root root 30d`, and `systemd-tmpfiles-setup.service` runs `--create --remove --boot`, so **`/tmp` is emptied at every boot** (read in the package, 2026-09-29; measured on wslcb). `/var/tmp` isn't. Anything staged under `/tmp` is lost at the reboot; list it first.

## Provisioning leftovers: `exe-setup.service`

- `ConditionPathExists=/exe.dev/setup`, `User=exedev`. Its cleanup is an `ExecStartPost=` `rm`, which runs only if `ExecStart` succeeded. So a failing script leaves itself, and any secret in it, on disk (CannObserv/notifier#93, 2026-09-28).
- **The platform delivers the creation-time script again on every boot.** On replicator it ran 5 of 5 in-guest reboots and 1 of 1 platform reset (CannObserv/replicator#122). On watcher it ran 4 of 4 (CannObserv/watcher#331). The file is absent between boots, so an absent file isn't evidence of cleanup.
- A VM created without a script has nothing to deliver ("condition unmet"). A Feb-2026 image has no consumer at all.
- **The remedy that lasts is revoking the key.** Shredding the file removes only the current copy. Asking the platform to clear its stored script is an open question.

## Clean-shutdown and boot evidence

- PID 1's log target is `console` (`console=hvc0` on the cmdline), so its journal lines are sporadic. Use instead:
  - the service's own stop line;
  - journald's `Journal stopped`, where the journal is persistent;
  - the data store's own log (Postgres: `CHECKPOINT` → `fast shutdown request` → `database system is shut down`);
  - no EXT4 orphan recovery at the next boot;
  - on a volatile journal, the copy the reboot chain took.
- **A platform restart or resize is a hard reset.** replicator's resize left no stop line and forced orphan recovery. Reboot in-guest only.
- `who -b` was wrong on three hosts. Read `/proc/stat` btime.

## Sessions and OOM

- Agent sessions run at `oom_score_adj` -1000 (CannObserv/notifier#88; the platform confirmed some `exe-init` builds do this, CannObserv/wslcb-licensing-tracker#182). Neither the kernel nor earlyoom will kill them, so under pressure a production service goes first.
- **Run an apply at adj 0**: `choom -n 0 -- …`. Don't use a hard memory cap: a kill mid-dpkg is worse than the risk it covers. A dry run peaked at 261–268 MiB in the round.
- **A session's path to PID 1 changes over its life.** A long-lived VS Code server is reparented to PID 1 through an `sh`, so a host test that looks for `exe-init` or `sshd` as the parent skips and reads green (CannObserv/watcher#333, CannObserv/address-validator#236). Read the adj of every process up the chain directly.

## Other facts

- `docker-clean` empties apt's `.deb` cache after every run, so a rollback fetches the recorded version from snapshot.ubuntu.com.
- The ingress is exe.dev's own `sshd` in `init.scope`. `ssh.service` is disabled and `ssh.socket` masked, so an openssh-server upgrade touches nothing live (power-map, address-validator, wslcb).
- nginx ships with the image, disabled, and was in the security set on six hosts: patched for nothing. A dormant-component candidate ([policy.md](../policy.md)).

## What belongs to the image owner

These are image findings, not host findings. They go to the repo the knob's `image-owner` line names ([knob.md](../knob.md)), not to each host. With no such line, they're reported and nothing is proposed:

1. the masked apt timers and `Periodic::Enable "0"`;
2. the volatile journal on the Feb-2026 images;
3. the setup script re-delivered on every boot;
4. `exe-init` builds that start sessions at -1000.
