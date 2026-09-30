# The run: gates, recovery point, held steps, reboot, verification

The procedure ten hosts followed by hand in #313's step 0 round, and the one the skill's scripts implement. Each step names the trap it avoids. The owner approves in the host's own session, and **nothing said in a chat channel counts as approval**.

## Approvals

Three, given separately:

1. **The needrestart drop-in**: a repo change, then its installation.
2. **The apply**: the bulk step, after the recovery point.
3. **Restarts**:
   - **3(a)**: each held step that restarts a service (Postgres's cluster, containerd), with any `restarter` stopped around it;
   - **3(b)**: the reboot.

   A maintainer script's restart is still a restart, so the owner approves it knowingly, not as a side effect of "the apply".

## Before each step: the gate

- The time is inside a `window` and clear of every `quiet` range.
- Every `inflight` command prints `0`. Read it right before the step, not at the window's start (watcher's queue; wslcb's ingest).
- No dev server or hand-started instance is in use.
- Each `restarter`'s state is read and recorded.
- **Before approval 3(a) or 3(b), each `caller` has been told:** the window, the expected outage, and what the caller does while this host is down. A caller whose degraded path is permanent needs to know most (CannObserv/power-map#589 stores addresses unstandardized for good). The notice goes where the knob's `records` says, or to the caller's own repo on approval.

## 1. The needrestart drop-in

Track it in the repo (for example `infra/needrestart.conf.d/<repo>.conf` with a test), then install it:

```
$nrconf{restart} = 'l';
```

**Prove it:** `sudo needrestart -m u -b -r l` must print `Disabling Ubuntu mode, explicit restart mode configured`, and restart nothing. In needrestart 3.6, `-m u` clears `$nrconf{restart}`, the config and `conf.d` are evaluated, and the Ubuntu-mode test reads only the config's value. So that line means **a file** set the key, and `-r l` keeps the proof list-only. **Never run the proof without `-r l`**: if the file fails to load, Ubuntu mode sets `restart='a'` and the proof restarts everything (read in noble's needrestart 3.6-7ubuntu4.5).

## 2. The recovery point

Every host records its before-versions (below). A host that declares a `datastore` also needs a dump that has left the node before the apply. A host with none, such as a pure bus worker, has nothing to dump.

- **Prefer the host's own backup regime** when one exists and succeeded recently. Start it by hand, then confirm the new object, its verification and its check-in (CannObserv/watcher#331).
- **Otherwise, dump each data store as root**, mode 600 from creation. A `>` from the session shell can't write to `/var/backups` (CannObserv/address-validator#235):

  ```
  sudo -u postgres pg_dump -Fc <db> | sudo sh -c 'umask 077; cat > /var/backups/<db>-<utc>.dump'
  echo "${PIPESTATUS[@]}"                                                 # gate 1: must be "0 0"
  sudo pg_restore --list /var/backups/<db>-<utc>.dump >/dev/null          # gate 2: the TOC
  sudo pg_restore -f /dev/null /var/backups/<db>-<utc>.dump               # gate 3: a full read
  stat -c %a /var/backups/<db>-<utc>.dump                                  # 600
  sha256sum /var/backups/<db>-<utc>.dump
  ```

  **`--list` alone isn't a gate.** A custom-format dump written to a pipe puts its table of contents first, so a dump cut off mid-data (pg_dump killed, disk full) still lists cleanly. The pipeline's exit status and a full read are what catch it. watcher's backup regime does the full read too.

  For Redis: `BGSAVE`, wait for it to finish, then copy the RDB file the same way.
- **The owner copies the dump off the node** with their own `scp`, and checks it against that sha256 **before the apply**.
- **On the node only:**
  - `pg_dumpall --globals-only` (role hashes);
  - the before-versions, `dpkg-query -W`;
  - `apt-mark showauto` and `apt-mark showhold`.
- **Secrets never travel:** the service's env file, keys and DSNs stay put.
- **State a retention** for every recovery-point file, and flag a dump that holds personal data. address-validator's held its audit log's raw input.
- A package rollback fetches the recorded version from snapshot.ubuntu.com, because `docker-clean` empties apt's `.deb` cache.

## 3. The apply, in held steps

Count first:
- Count security from `sudo unattended-upgrade --dry-run -d`, from its `Packages that will be upgraded` line. The `pkgs that look like they should be upgraded:` header lists the whole selection one per line, and `apt list | grep -security` undercounts (usa-wa: 178 against 185).
- Record the dry run's time and max RSS, and free disk against the download size.

Then:

1. **Hold** each `hold` group in the set: `sudo apt-mark hold <packages>`. **Leave the owner's own holds alone:** a package in `apt-mark showhold` before the run was held on purpose, so the run never holds or unholds it. Report it as held by the owner.
2. **Bulk:** `sudo NEEDRESTART_MODE=l choom -n 0 -- unattended-upgrade -v`.
   - `choom -n 0` puts the apply at adj 0, so the kernel doesn't sacrifice a production service to protect a -1000 session.
   - **No hard memory cap:** a `MemoryMax` kill mid-dpkg leaves packages half-configured.
   - `NEEDRESTART_MODE=l` backs up the drop-in. In apt's hook there's no `-r`, so the variable wins.
3. **Each held group, under approval 3(a):**
   - unhold the packages the run held, and only those;
   - stop each `restarter`;
   - run the same command;
   - poll health **every second, logging each code with its timestamp**, until two 200s in a row;
   - start each `restarter` again, and confirm `is-active`.
4. **Record auto-removals** apart from upgrades (`Remove-New-Unused-Dependencies`).
5. Confirm `apt-mark showhold` matches the list recorded before the run: the run's own holds are gone, and the owner's are still there.

**The maintenance lane** runs in the same window, after the security steps, with the same command, holds, `choom`, `NEEDRESTART_MODE` and verdict. Only the selection widens, through an `APT_CONFIG` file:

```
# /var/backups/maintenance-<utc>.conf, root-owned
Unattended-Upgrade::Origins-Pattern {
  "origin=Ubuntu,archive=${distro_codename}-updates";
  "origin=<each origin whose policy is follow>";
};
```

```
sudo APT_CONFIG=/var/backups/maintenance-<utc>.conf NEEDRESTART_MODE=l choom -n 0 -- unattended-upgrade --dry-run -d   # check the selection first
sudo APT_CONFIG=/var/backups/maintenance-<utc>.conf NEEDRESTART_MODE=l choom -n 0 -- unattended-upgrade -v
```

apt lists accumulate across config files, so this widens the stock security selection rather than replacing it. **Never use a bare `apt-get upgrade`**: it takes every upgradable package from every origin, including those whose policy is *hold*. The dry run's selection must contain nothing from a *hold* or *pin* origin.

**The verdict** comes from the exit code, `All upgrades installed`, and an empty `dpkg --audit`. **Never count `Failed` or `error` lines**: a clean apply logged about 100 needrestart "kernel versions" lines.

**A data-store step checks recovery, not just health.** A fail-open cache or audit writer hides a database outage from callers, and from the operator. So prove the path works:
- a real request through it;
- a new row where one should appear;
- a cache hit on a repeat;
- the fail-open warnings back to flat.

An engine without `pool_pre_ping` can serve 503s from a pooled connection opened before the restart. address-validator had one 503, 2 s after Postgres was ready. wslcb had none after ready, because its 1 s poll surfaced the dead connection during the outage.

**Docker:** the `docker.io` package doesn't restart dockerd, so the old daemon runs until a restart or the reboot. Keep the Docker step close to the reboot. If the reboot is deferred, restart explicitly under 3(a).

**Abort branch.** Any of these means **stop: no further held step, and no reboot**:
- a non-zero exit;
- a failing health check;
- anything from `dpkg --audit`;
- a failed recovery check.

Consider `sudo dpkg --configure -a`, record the state, and the owner decides. **List the run's own holds in the record**: the owner releases each one, or declares it as an `exception` with a review-by date. An abort never leaves an undeclared hold behind, because both lanes, and `automatic`, would skip that package indefinitely. The round never needed this branch; it's untested on a real host.

## 4. The reboot decision

After the last step:
- `sudo needrestart -b -r l`;
- `sudo grep -c '(deleted)' /proc/1/maps`;
- `/var/run/reboot-required` and its `.pkgs`.

`/proc/<pid>/maps` of another user's process needs root: without `sudo` it's "Permission denied", and a read that failed is `unknown`, never 0.

Reboot when any of them calls for it: dbus, logind, `user@`, a data store, or PID 1 mapping deleted libraries. **Never decide from a kernel**: exe.dev has no guest kernel. PID 1 re-executing itself during the apply (it did on most hosts) doesn't mean no reboot.

## 5. The reboot chain

Run it detached, as a 0700 root script, so the operator's disconnect can't cut it off. Log it to `/var/backups/`:

```
sudo systemd-run --unit=reboot-chain --on-active=120 --timer-property=AccuracySec=1s /var/backups/reboot-chain-<utc>.sh
```

`AccuracySec=1s` matters: by default the transient timer fired 41 s late (CannObserv/wslcb-licensing-tracker#184). The script's steps:

1. **The gate** again: every `inflight` is 0, run as the invoking user (`runuser -u <user> --`), never as root. Abort otherwise. The script shows each knob command verbatim, so the owner approves exactly what runs ([knob.md](knob.md)).
2. Stop each `restarter`, then each `service`. A timer with `Requires=` on the service stops with it anyway.
3. Checkpoint, then stop each data store. Postgres: `sudo -u postgres psql -c CHECKPOINT`. Redis: `systemctl stop` saves the RDB file when save points are configured; with none, run `SAVE` first.
4. `journalctl --sync`.
5. **Copy the journal, last**, so it holds every stop line. On a volatile journal this copy is the only record of the shutdown:

   ```
   install -d -m 700 /var/backups/journal-<utc>
   cp -a /run/log/journal/<machine-id>/. /var/backups/journal-<utc>/   # or /var/log/journal/…
   chmod -R go-rwx /var/backups/journal-<utc>
   journalctl -D /var/backups/journal-<utc> -n 5                       # the read-back
   ```

   `cp -a` alone keeps the source's `systemd-journal` group and its 2755 mode, so the copy would stay readable by that group. A journal can hold secrets: archiver's setup-script key was in its journal. The copy is a recovery-point file, so it gets a stated retention (§2).
6. `sync`, then `systemctl reboot`. **In-guest only**: a platform restart is a hard reset.

Before launching:
- post the post-boot checklist in the record;
- list anything staged under `/tmp`, which the boot will empty.

If the reboot slips out of the window, say so, and redo the gate and the quiet-hour check.

## 6. After the boot

- **A clean shutdown:** the data store's own log, no EXT4 orphan recovery, and the chain's journal copy. For Postgres: `database system was shut down at …` and no `redo starts`.
- **Each `service`:**
  - `NRestarts` and **the first start's result**, not just `is-active`. address-validator's first start failed on a dependency that wasn't ready yet (CannObserv/address-validator#239);
  - **its ordering**: `systemd-analyze critical-chain <service>` includes its data store, and the unit has `After=` on it. wslcb's first start succeeded by luck, until `After=postgresql.service` made it configured. Don't add `Wants=`: it would start a cluster an operator stopped on purpose.
- **Each `restarter`** is active.
- **The timers** are scheduled. Record any `Persistent=` catch-up, and whether any run was cut off: `Persistent=` catches up a run *missed* while down, not one *killed* part-way.
- **needrestart is clean**, `sudo grep -c '(deleted)' /proc/1/maps` reads 0, and `reboot-required` is gone.
- **The session adj, read directly** up the chain to PID 1. Never trust a test that can skip.
- **Containers are back.** On power-map, qdrant waited for first use despite `unless-stopped`. On wslcb, with `docker.service` enabled, both came back at boot.
- **The downtime**, from the stop line or the last request to the first good response.
- **Every `health` check passes**, and `systemctl --failed` is empty.

## 7. The record

Post the before and after readings where the knob's `records` says:
- counts;
- times and RSS;
- restarts by maintainer scripts;
- auto-removals;
- the downtime;
- what's left pending, by class ([policy.md](policy.md)).

A record that lists pending security updates is published only after they're applied, and gives counts and families, not versions.
