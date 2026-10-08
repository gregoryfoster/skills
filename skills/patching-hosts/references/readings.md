# Readings: what to measure before proposing a run

What `probe.sh` reads, and the checklist for what it leaves to you. Each reading is paired with **the mistake it prevents**: in #313's step 0 round, every one was misread, or found by hand, on at least one host. The readings are read-only, with two exceptions:

- `apt-get update` writes the package lists. The probe refreshes only with `--refresh-into DIR`, into `DIR/lists`.
- **The security count's dry run** (`unattended-upgrade --dry-run -d`) runs as root and downloads the whole set into apt's cache: about 290 MB and 9 minutes on address-validator. The probe runs it only with `--dry-run-into DIR`, with apt's cache pointed at `DIR/archives` through an `APT_CONFIG` file, since `unattended-upgrade` takes no `-o`. It leaves `DIR/summary`, whose wall time `apply.sh --dry-run DIR` takes as the floor of each step's expected duration, adding the time the health checks may take. `apply.sh` refuses a summary more than 24 hours old, which counted another day's set. Without it, the security count is a lower bound. With it, the count is exact only while the host's unattended-upgrades origins are `-security` alone: wider origins put `-updates` and third-party packages on the same line, and the probe's `security_only` says which.

A read can change the host without writing a file: a socket-activated daemon starts on its first client. exeuntu enables `docker.socket` and disables `docker.service`, so the probe asks Docker only while `docker.service` already runs. Asking an idle Docker would start it, and restart the idle clock its dormant verdict reads.

The probe reads the root-only readings through `sudo -n`, so it never prompts. With `--root DIR` it reads an image tree's files, and asks a running system only when `DIR/run/systemd/system` exists, the test systemd itself uses.

**Report an absent setting as `unknown`, never as its default.** A reading the probe couldn't take is `unknown`, not clean. That includes a read that needed root and failed: `/proc/<pid>/maps` of another user's process, needrestart's check, the Postgres catalogs.

## The environment

| Reading | How | Mistake it prevents |
|---|---|---|
| Which profile, and which image generation | markers, not a digest ([environments/exe-dev-exeuntu.md](environments/exe-dev-exeuntu.md)) | assuming the newer image's `exe-setup`, journal and session path on a Feb-2026 host |
| Boot time | `/proc/stat` btime | `who -b` was wrong on three hosts |
| **Where the journal actually lives** | files under `/var/log/journal`; `systemctl is-enabled systemd-journal-flush`; the days the oldest entry reaches back | `Storage=persistent` with the flush masked: address-validator's 51 days were lost at the reboot |
| PID 1's log target | `systemd-analyze get-log-target` | expecting PID 1's lines as clean-shutdown evidence when it logs to `console` |
| **The session's chain to PID 1** | the adj of every process from `$$` up, read directly. The session's own part ends below the platform's agent, `exe-init` or `sshd`, whose -1000 is reported apart: stock OpenSSH's listener runs at -1000 and starts each session at 0, as exe.dev's `sshd` does on the older layouts (#353, #346) | a host test that skips when the parent isn't `exe-init`/`sshd`, reading green (CannObserv/watcher#333) |
| **What consumes a setup script** | `exe-setup.service`'s `LoadState`, and its `ConditionResult` and `Result` for each retained boot; `/exe.dev/setup`'s mode and owner, and whether the unit is disabled; secret patterns by name and line, **never the value** | taking an absent file as cleanup, when the platform delivers it again every boot; and reporting a file contained in place, root's alone with the unit disabled, as a leftover |
| **Anything staged under `/tmp`** | `ls -la /tmp`; `/usr/lib/tmpfiles.d/tmp.conf` and `/etc/tmpfiles.d/` | losing a staged binary to `D /tmp` at the reboot (CannObserv/wslcb-licensing-tracker#182) |

## What updates this host

| Reading | How | Mistake it prevents |
|---|---|---|
| The apt timers and service | `systemctl is-enabled`, or the mask symlinks on disk (works offline) | trusting `20auto-upgrades`' `1`/`1` |
| **The effective `Periodic::Enable`, and which file sets it** | `apt-config shell E APT::Periodic::Enable`; grep `/etc/apt/apt.conf.d/` | missing `docker-disable-periodic-update`'s `0`, which makes unmasked timers no-ops |
| Every apt source, and each origin | `/etc/apt/sources.list.d/`, `apt-cache policy` | treating a third-party origin as Ubuntu's |
| **Each followed origin's scope** | `apt-cache policy`: the priority on its release lines, which a `Package: *` pin for its site moves, and its `Pinned packages:`; then `apt-cache policy` over every installed package, for each candidate's site | a third-party package taking an Ubuntu name's place at 500, or the lane taking whatever the origin serves that's installed, not what it was added for ([policy.md](policy.md#two-lanes)) |
| The needrestart config in force | `sudo needrestart -m u -b -r l`'s `Disabling Ubuntu mode` line | a drop-in that doesn't load, leaving the hook in automatic mode |
| Tailscale's running version | `tailscale version --daemon --json`'s `daemonLong`, beside `tailscale version`'s client version | an upgrade whose restart didn't happen: the CLI reports the fix while tailscaled still runs the old binary, and plain `tailscale version` never says so |
| Tailscale's own auto-update | `tailscale debug prefs`: `AutoUpdate.Apply` is true, false, or null when nothing ever set it on the node. The tailnet's setting configures a device only as it joins, and never changes an existing one | the host's tailnet path, and anything that reaches it over the tailnet, dropped by an upgrade nobody scheduled |
| **Everything outside apt, with its owner** | `/usr/local/bin`, `~/.local/bin`, container images and their age, pinned tools | a component nobody patches because nobody owns it |

## The pending set, by class

| Reading | How | Mistake it prevents |
|---|---|---|
| List age | the security `InRelease` mtime | a count against stale lists, which measures provisioning, not the image |
| **Security, counted right** | `unattended-upgrade --dry-run -d`'s `Packages that will be upgraded` line | `apt list \| grep -security` undercounts (usa-wa: 178 against 185), and `grep \| head` on the one-per-line header truncates |
| `-updates` and third-party | `apt list --upgradable` against each origin | treating the security count as "everything" |
| **Ubuntu Pro / ESM** | `pro security-status` | "0 security pending" read as covering `universe` (wslcb: 29 esm-apps pending) |
| **Phased updates** | the simulation with `APT::Get::Always-Include-Phased-Updates`, and `(phased N%)` in `apt-cache policy` | a count that leaves out what the lane takes: apt defers a phased update outside its phase, and unattended-upgrade takes it anyway (replicator: 34 counted, 35 taken; #354) |
| The dry run against the classes | what the dry run selects that no class list names, and each package it passes over at a conffile prompt, with the state of its conffiles on disk. Its class still counts it, and `by_class.passed_over` marks it there (#361) | a package reaching the host that the proposal never showed, or a count promising one the lane won't install |
| The dry run's cost | wall time, max RSS, download size, free disk | a disk-full or memory-starved apply on a host that shares memory with sessions |
| Held-group candidates | which `hold` globs are in the set | a major version bump (docker.io 28→29) going in with the bulk |
| **Owner holds** | `apt-mark showhold` against the pending set and the knob's `held:` exceptions | a security fix deferred indefinitely by a hold nobody declared ([policy.md](policy.md#exceptions)) |

## Impact

| Reading | How | Mistake it prevents |
|---|---|---|
| **Which processes map a library in the set** | `sudo` read of `/proc/*/maps` against the set's shared objects | "Postgres isn't in the set, so no restart": its backends mapped libc6 and libxml2 (watcher, address-validator, wslcb) |
| Each data store's source and collation | `datcollate` and provider per database; `datcollversion` unless C.UTF-8 on libc | a collation-version change after a libc or ICU upgrade |
| **Undeclared databases** | the cluster's databases, less the templates and a `postgres` with no table of its own, against the knob's `datastore` lines | a database the recovery point doesn't cover ([knob.md](knob.md)) |
| **Live arguments** | `/proc/<pid>/cmdline` | reading a daemon's config from its journal. wslcb quoted earlyoom's boot-time block, not its last start |
| **Boot ordering** of each service | its `After=`, and `systemd-analyze critical-chain` | a first start that succeeds by luck, and fails on the next boot (CannObserv/address-validator#239) |
| **In-host automatic restarters** | timers or services that run `systemctl restart`; an `OnFailure=` target that starts or restarts a service, read through what it runs, one script deep, or that can't be read. One that only notifies isn't one (#351). A timer's service is read the same way, so a restart inside the script it runs is found (#368); one running a program the scan can't follow, a binary or `uv run`, leaves the scan incomplete until the knob declares it a restarter or `not-restarter:<service>`. Unit files and scripts are read as root where the user can't, and one even root can't read leaves the scan incomplete, not clean (#360) | a health timer restarting the app, unapproved, during a 1.5 s database outage |
| **Units that `Requires=` a service** | `systemctl list-dependencies --reverse <service>` | a stop and a later `start` leaving the dependent inactive: wslcb's health timer stopped with the app, and only a `restart` brings it back |
| **A backup regime** | timers or cron that dump each data store, and their last success | taking a second dump when a verified off-node regime exists, or assuming one that doesn't |
| The health baseline | each knob `health`, the suite's pass and skip counts, `systemctl --failed`, the timers' last results | no baseline to compare the post-boot state against |
| Callers and traffic | the service's own access or audit log, by UTC hour | a window in the busy hour; a caller whose degraded path is permanent (CannObserv/power-map#589) |
| What reads 200 while degraded | the code path for each dependency down | a fail-open cache hiding the outage, or a caller stamping a 200 `unavailable` as done (CannObserv/wslcb-licensing-tracker#183) |

## Dormant components

For each engine the probe knows (Docker, Postgres, Redis, nginx, Ollama, Qdrant to start with):
- the unit's state and whether it's enabled;
- its listeners;
- its workload: containers, databases with their sizes and their writes and sessions since the statistics were reset, Redis's keys, lookups, expirations, subscriptions and clients, enabled sites;
- whether the repo's units, docs or knob name it;
- its packages in the security set;
- whether it shipped with the image or was installed later.

The verdict rules are in [policy.md](policy.md). **Name the evidence source for each verdict.** A journal that holds 10 days can't show 30 days of idleness.

## What the probe leaves to you

A reading it couldn't take is `null` in its output and named in `not_read`: no root, no running system, or no `pro`. These it never takes, so read them yourself:

- **callers and traffic**, from the service's own access or audit log;
- **what reads 200 while degraded**, from the code;
- **the suite's pass and skip counts**, for the health baseline;
- **whether a component came with the image**: that needs the image's build date, which the guest can't see;
- **the downtime** after a boot, from the stop line or the last request to the first good response.
