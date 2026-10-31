# The run, continued: the reboot and the record

[run.md](run.md)'s steps 1 to 3 come first: the approvals, the gate, the recovery point and the apply.

## 4. The reboot decision

After the last step:
- `sudo needrestart -b -r l`;
- `sudo grep -c '(deleted)' /proc/1/maps`;
- `/var/run/reboot-required` and its `.pkgs`.

`/proc/<pid>/maps` of another user's process needs root: without `sudo` it's "Permission denied", and a read that failed is `unknown`, never 0.

Reboot when any of them calls for it: dbus, logind, `user@`, a data store, PID 1 mapping deleted libraries, or a pending kernel (needrestart's `NEEDRESTART-KSTA` of 2 or 3). **On exe.dev, never decide from a kernel:** there's no guest kernel, so its kernel lines mean nothing ([the profile](environments/exe-dev-exeuntu.md#update-channels)). PID 1 re-executing itself during the apply (it did on most hosts) doesn't mean no reboot.

## 5. The reboot chain

Run it detached, as a 0700 root script, so the operator's disconnect can't cut it off. `reboot-chain.sh --run <dir>` prints the chain for the owner to read; with `--approve` it writes it into the run's directory, with its log and the journal copy beside it, and launches it:

```
sudo systemd-run --unit=patching-hosts-reboot-<utc> --on-active=120 --timer-property=AccuracySec=1s <dir>/reboot-chain.sh
```

`AccuracySec=1s` matters: by default the transient timer fired 41 s late (CannObserv/wslcb-licensing-tracker#184). The script's steps:

1. **The gate** again: no package manager is running, since a reboot then could cut dpkg off mid-run, and every `inflight` is 0, run as the non-root user recorded when the chain was written (`runuser -u <user> --`), never as root. Abort otherwise: an aborted chain stopped nothing, and `reboot-chain.sh` launches it again once the gate would pass. The script shows each knob command verbatim, so the owner approves exactly what runs ([knob.md](knob.md)).
2. Stop each `restarter`, then each `service`. A timer with `Requires=` on the service stops with it anyway.
3. Checkpoint, then stop each data store. Postgres: `sudo -u postgres psql -c CHECKPOINT`. Redis: `systemctl stop` saves the RDB file where save points are set, and fsyncs the AOF under `appendonly yes`; with neither, `SAVE` first ([datastores.md](datastores.md#the-chains-stop)). Qdrant: no checkpoint, since its container's `docker stop` is its clean shutdown.
4. `journalctl --sync`.
5. **Copy the volatile journal, last**, so it holds every stop line. This copy is the only record of the shutdown:

   ```
   install -d -m 700 <run>/journal/_run_log_journal
   cp -a /run/log/journal/. <run>/journal/_run_log_journal/
   chmod -R go-rwx <run>/journal/_run_log_journal
   journalctl -D <run>/journal/_run_log_journal -n 5                   # the read-back
   ```

   That's where `reboot-chain.sh` puts it, and where `probe.sh --post-boot` looks for it (#356). It copies a source only where it fits, its `du -sk` plus [run.md](run.md) §3's 128 MiB within the free space under `<run>/journal` (#390). Otherwise, or where either can't be read, the chain logs why and copies nothing of it, and it removes a copy that fails part-way: a partial one would fill the disk the host boots from. One copied whole but not read back is kept, and logged so.

   `cp -a` alone keeps the source's `systemd-journal` group and its 2755 mode, so the copy would stay readable by that group. A journal can hold secrets: archiver's setup-script key was in its journal. The copy is a recovery-point file, so it gets a stated retention ([run.md](run.md) §2). A persistent journal, in `/var/log/journal`, survives the boot, so it isn't copied: a copy of one, up to journald's 4 GiB cap, would land on the disk the data stores boot from.
6. `sync`, then `systemctl reboot`. **In-guest only**: a platform restart is a hard reset.

Before launching:
- post the post-boot checklist in the record;
- list anything staged under `/tmp`, where the boot empties it. `reboot-chain.sh` reads the tmpfiles rule: under a `d` rule, as on the exeuntu images since 2026-07-17, the boot keeps `/tmp`, and nothing is listed (#355).

If the reboot slips out of the window, say so, and redo the gate and the quiet-hour check.

## 6. After the boot

`probe.sh --post-boot` takes these checks, and each one that fails is a finding. The downtime, and any `Persistent=` catch-up, are left to you.

- **A clean shutdown:** the data store's own log, no EXT4 orphan recovery, and the journal's record. For Postgres: `database system was shut down at …` and no `redo starts`; for Redis, `ready to exit, bye bye`. A volatile journal's record is the chain's copy in `<run>/journal`: `--post-boot --run <dir>` names the run, and without it the newest `/var/backups/patching-hosts-<UTC>` is read. A persistent journal's is `Journal stopped` among the previous boot's last lines.
- **Each `service`:**
  - `NRestarts` and **the first start's result**, not just `is-active`. address-validator's first start failed on a dependency that wasn't ready yet (CannObserv/address-validator#239). A start by hand after a failure leaves `NRestarts` at 0, so read `InactiveEnterTimestamp`: unset, the unit never stopped or failed after it started. Set, only PID 1's lines in the journal tell a failure from a stop by hand;
  - **its ordering**: `systemd-analyze critical-chain <service>` includes its data store, and the unit has `After=` on it. wslcb's first start succeeded by luck, until `After=postgresql.service` made it configured. Don't add `Wants=`: it would start a cluster an operator stopped on purpose.
- **Each Redis**, from its own log: a clean shutdown before the boot, then a load and a ready. **Each Qdrant** against its recovery point's counts. Each also after a held step that restarted it ([datastores.md](datastores.md)).
- **Each `restarter`** is active.
- **The timers** are scheduled. Record any `Persistent=` catch-up, and whether any run was cut off: `Persistent=` catches up a run *missed* while down, not one *killed* part-way.
- **needrestart is clean**, `sudo grep -c '(deleted)' /proc/1/maps` reads 0, and `reboot-required` is gone.
- **The session adj, read directly** up the chain to PID 1. Never trust a test that can skip.
- **Containers are back.** On power-map, qdrant waited for first use despite `unless-stopped`. On wslcb, with `docker.service` enabled, both came back at boot. The difference is `docker.service`: disabled, nothing starts dockerd at boot, so no restart policy runs until something asks Docker through `docker.socket` (measured in the exeuntu image, 2026-10-01). Check before the reboot whether it's enabled, and after it, start by hand what should be back. The probe reads the containers from disk while dockerd is down, and fails the check for each one a restart policy should have brought back.
- **The downtime**, from the stop line or the last request to the first good response.
- **Every `health` check passes**, so does each `recovery` line (#423), and `systemctl --failed` is empty.

## 7. The record

**Take the after reading last, in every run, whether it rebooted or not:** `probe.sh --refresh-into <dir>`. It's the only probe that reads the language class: `--post-boot`, `--dry-run-into` alone and `apply.sh`'s probe after each step leave it in `not_read`. A class in `not_read`, or a tree not audited (`audited: false`, `lockfile: null` among them), is recorded as *no read*, never as 0.

Post the before and after readings where the knob's `records` says:
- counts;
- times and RSS;
- restarts by maintainer scripts;
- auto-removals;
- the downtime;
- what's left pending, by class ([policy.md](policy.md)), language dependencies included;
- for each tree with a repo as its owner, that repo's own update mechanism: an audit gate in CI, and whether its bot is working, not just configured. A config alone reads "on" while the bot is silent behind a full PR limit, as notifier's was for five weeks (#366), or while the dependency graph is off and no advisory opens a PR (CannObserv/notifier#140). `adopting-dependabot`'s `check-dependabot.sh --repo <owner/name>` reads both; read a Renovate config by hand.

A record that lists pending security updates is published only after they're applied, and gives counts and families, not versions.
