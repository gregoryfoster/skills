# The run: gates, recovery point, held steps, reboot, verification

The procedure ten hosts followed by hand in #313's step 0 round, and the one the skill's scripts implement. Each step names the trap it avoids. The owner approves in the host's own session, and **nothing said in a chat channel counts as approval**.

## Approvals

Three, given separately:

1. **The needrestart drop-in**: a repo change, then its installation.
2. **The apply**: the bulk step, after the recovery point.
3. **Restarts**:
   - **3(a)**: each held step that can restart a service (Postgres's cluster, Redis, containerd), with any `restarter` stopped around it. noble's `redis-server` restarts the server from its postinst on upgrade ([the profile](environments/exe-dev-exeuntu.md#packages-that-restart-their-own-services));
   - **3(b)**: the reboot.

   A maintainer script's restart is still a restart, so the owner approves it knowingly, not as a side effect of "the apply".

## Before each step: the gate

- **The step's whole span**, from now to now plus its expected duration, is inside a `window` and overlaps no `quiet` range. For an apply step, the expected duration is at least the dry run's wall time. For the reboot, it's the chain's delay plus the boot and the post-boot checks. Checking only the start lets a 9-minute apply begun 5 minutes before a quiet range run into it.
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

Every host records its before-versions (below). A host that declares a `datastore` also needs a dump that has left the node before the apply. A host with none, such as a pure bus worker, has nothing to dump. `recovery-point.sh --approve --retain-until <date>` takes it, as below, and writes the record the bulk reads. Like a step, it takes minutes: run it in the background.

- **Prefer the host's own backup regime** when one exists and succeeded recently. Start it by hand, then confirm the new object, its verification and its check-in (CannObserv/watcher#331).
- **Otherwise, dump each data store as root**, mode 600 from creation. A `>` from the session shell can't write to `/var/backups` (CannObserv/address-validator#235):

  ```
  sudo -u postgres pg_dump -Fc <db> | sudo sh -c 'umask 077; cat > /var/backups/<db>-<utc>.dump'; \
    echo "${PIPESTATUS[@]}"                                               # gate 1: must be "0 0"
  sudo pg_restore --list /var/backups/<db>-<utc>.dump >/dev/null          # gate 2: the TOC
  sudo pg_restore -f /dev/null /var/backups/<db>-<utc>.dump               # gate 3: a full read
  stat -c %a /var/backups/<db>-<utc>.dump                                  # 600
  sha256sum /var/backups/<db>-<utc>.dump
  ```

  **`--list` alone isn't a gate.** A custom-format dump written to a pipe puts its table of contents first, so a dump cut off mid-data (pg_dump killed, disk full) still lists cleanly. The pipeline's exit status and a full read are what catch it. watcher's backup regime does the full read too.

  **Send the pipeline and gate 1 as one command.** `PIPESTATUS` belongs to the shell that ran the pipeline, and an agent's tool starts a fresh shell for each call. There, it describes whatever that shell ran last, not the dump.

  For Redis: `BGSAVE`, wait for it to finish, then copy the RDB file the same way.
- **The owner copies the dump off the node** with their own `scp`, and checks it against that sha256 **before the apply**.
- **On the node only**, each written like the dump, through `| sudo sh -c 'umask 077; cat > /var/backups/<name>-<utc>'`, and checked with `stat` for mode 600:
  - `sudo -u postgres pg_dumpall --globals-only` (role password hashes);
  - the before-versions, `dpkg-query -W`;
  - `apt-mark showauto` and `apt-mark showhold`.

  `apply.sh --step bulk` writes the last two into the run's directory itself.

  A `>` from the session shell can't write there, and `sudo tee` creates the file at 644, readable by every user on the host.
- **Secrets never travel:** the service's env file, keys and DSNs stay put.
- **State a retention** for every recovery-point file, and flag a dump that holds personal data. address-validator's held its audit log's raw input.
- **The record**, `recovery-point` in the run's directory (0700, the file 0600), which `recovery-point.sh` writes and `apply.sh` reads, one line each:

  ```
  began <epoch seconds>
  retain <YYYY-MM-DD>
  dump postgres <unit> <database> <sha256> <path>
  dump redis <unit> <sha256> <path>
  backup <unit>
  local <path>
  personal <path>
  ```

  A unit may carry its suffix or not: `postgresql@16-main` is `postgresql@16-main.service`, as in the knob. A `dump` is a file meant to leave the node, and the owner attests each one with `--offnode-sha256`, typed from their own copy. A `backup` is the host's own backup unit, which writes off the node itself, and one the knob's `backup` lines name (or the service a named timer starts): its run must have *started* after `began` and succeeded, it stands in for every dump, and the owner names its object with `--offnode-object`. A `local` file, such as the globals dump, stays on the node and is never attested. `retain` is the stated retention, and `personal` flags a dump that holds personal data. The bulk refuses a record that began more than 24 hours ago, or that misses a database a `datastore` line names.
- A package rollback reinstalls the recorded version. Where the image carries `docker-clean`, as exeuntu does, apt's `.deb` cache is emptied after every run, so fetch it from snapshot.ubuntu.com ([the profile](environments/exe-dev-exeuntu.md#other-facts)).

## 3. The apply, in held steps

`apply.sh` runs this section: `--step bulk` (approval 2), then `--step <group>` for each held group (approval 3(a)). **Start each step in the background.** A step runs for minutes (address-validator's dry run alone took 9), longer than a foreground call allows (Claude Code's: 2 minutes by default, 10 at most), and a call that's cut off kills the step with it. A bulk killed once it has written the run's `holds` leaves every hold listed there on, and records no step, so no held step and no new bulk runs on that run. Treat it as the abort branch: check `dpkg --audit`, have the owner release or declare each hold `holds` lists, and start a new run. Besides the gate, it refuses a host where `unattended-upgrade` would reboot by itself: with `Automatic-Reboot` true it reboots once `reboot-required` appears, it takes no `-o`, and `APT_CONFIG` is read before `apt.conf.d`, so nothing passed to it overrides the host's setting. It also refuses origins wider than `-security` without `exception uu:origins`, and a `dpkg --audit` that isn't clean before the step. Where the apt timers run, it refuses an automatic apt run in progress, or a span that meets the range `apt-daily-upgrade.timer` can start in, its calendar time plus its random delay, which systemd draws again at every reload: that run's `unattended-upgrade` would hold the lock, and the step would fail with nothing upgraded.

Count first (`probe.sh --dry-run-into DIR` does both, with apt's cache in `DIR/archives`, and leaves `DIR/summary` for `apply.sh --dry-run DIR`):
- Count security from `sudo unattended-upgrade --dry-run -d`, from its `Packages that will be upgraded` line, while its origins are `-security` alone (the probe's `security_only`): wider origins put other packages on that line too. The `pkgs that look like they should be upgraded:` header lists the whole selection one per line, and `apt list | grep -security` undercounts (usa-wa: 178 against 185).
- Record the dry run's time and max RSS, and free disk against the download size.

Then:

1. **Refresh the host's own lists** (`apt-get update`): the probe counted against a scratch copy, and on a host whose timers are masked, the host's may be months old.
2. **Hold** each `hold` group in the set. Expand its globs against what's pending once the lists are fresh (`apt-get -s dist-upgrade`, any origin), record the names, and `sudo apt-mark hold` those names: the recorded list is exactly what step 4 releases. **Leave the owner's own holds alone:** a package in `apt-mark showhold` before the run was held on purpose, so the run never holds or unholds it. Report it as held by the owner. If it's in the pending set, that's a finding unless a `held:<package>` exception covers it ([policy.md](policy.md#exceptions)).
3. **Bulk:** `sudo NEEDRESTART_MODE=l choom -n 0 -- unattended-upgrade -v`.
   - `choom -n 0` puts the apply at adj 0, so the kernel doesn't sacrifice a production service to protect a -1000 session.
   - **No hard memory cap:** a `MemoryMax` kill mid-dpkg leaves packages half-configured.
   - `NEEDRESTART_MODE=l` backs up the drop-in. In apt's hook there's no `-r`, so the variable wins.
4. **Each held group, under approval 3(a):**
   - stop each `restarter`;
   - unhold the packages the run held, and only those. In this order, a stop that fails leaves the group held, and the step can run again;
   - run the same command;
   - poll every `health` command **every second, logging each result with its timestamp**, until all of them exit 0 twice in a row;
   - start each `restarter` again, and confirm `is-active`.
5. **Record auto-removals** apart from upgrades (`Remove-New-Unused-Dependencies`).
6. Confirm `apt-mark showhold` matches the list recorded before the run: the run's own holds are gone, and the owner's are still there.

**The maintenance lane** is the same run, with the same gates, recovery point, holds, `choom`, `NEEDRESTART_MODE` and verdict: `apply.sh --lane maintenance`, counted first with `probe.sh --lane maintenance --dry-run-into`. Only the selection widens, through an `APT_CONFIG` file the bulk writes to the run's directory, root-only, and each held step reads:

```
// <run>/lane.conf
Unattended-Upgrade::Origins-Pattern {
  "o=Ubuntu,a=${distro_codename}-updates";
  "o=<each origin the knob follows>";   // "site=<its site>" when the knob names a site
};
```

`APT_CONFIG` is read before `apt.conf.d`, and its list adds to the host's own (unattended-upgrade 2.9.1 on noble, 2026-10-02), so the lane takes everything the security lane takes, plus `-updates` and the followed origins: run alone, it covers both. **Never use a bare `apt-get upgrade`**: it takes every upgradable package from every origin, including those whose policy is *hold*. The lane never names a *hold* or *pin* origin, and the step refuses when the host's own origins could take one (a wider entry `uu:origins` let through), when apt doesn't read the file, and when a held step's knob follows other origins than its bulk's did.

**An expedited run of one origin**, for a security bulletin's out-of-cycle window: `apply.sh --lane origin:<origin>`, counted first with `probe.sh --lane origin:<origin> --dry-run-into`. The origin must be one the knob follows. Its file adds that origin's pattern alone. At the bulk, after the lists refresh, every other pending package goes in `Unattended-Upgrade::Package-Blacklist`, each name anchored and escaped, since unattended-upgrade matches the list as regular expressions. Only the origin's own packages are candidates for a hold group. It's the same command, and it leaves no hold to release. On noble with unattended-upgrade 2.9.1 (2026-10-03), it took `tailscale` alone out of 8 pending packages.

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

Consider `sudo dpkg --configure -a`, record the state, and the owner decides. **List the run's own holds in the record**: the owner releases each one, or declares it as `exception held:<package> <review-by> <reason>`. An abort never leaves an undeclared hold behind, because both lanes, and `automatic`, would skip that package indefinitely. The round never needed this branch; it's untested on a real host.

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
3. Checkpoint, then stop each data store. Postgres: `sudo -u postgres psql -c CHECKPOINT`. Redis: `systemctl stop` saves the RDB file when save points are configured; with none, run `SAVE` first.
4. `journalctl --sync`.
5. **Copy the volatile journal, last**, so it holds every stop line. This copy is the only record of the shutdown:

   ```
   install -d -m 700 /var/backups/journal-<utc>
   cp -a /run/log/journal/<machine-id>/. /var/backups/journal-<utc>/
   chmod -R go-rwx /var/backups/journal-<utc>
   journalctl -D /var/backups/journal-<utc> -n 5                       # the read-back
   ```

   `cp -a` alone keeps the source's `systemd-journal` group and its 2755 mode, so the copy would stay readable by that group. A journal can hold secrets: archiver's setup-script key was in its journal. The copy is a recovery-point file, so it gets a stated retention (§2). A persistent journal, in `/var/log/journal`, survives the boot, so it isn't copied: a copy of one, up to journald's 4 GiB cap, would land on the disk the data stores boot from.
6. `sync`, then `systemctl reboot`. **In-guest only**: a platform restart is a hard reset.

Before launching:
- post the post-boot checklist in the record;
- list anything staged under `/tmp`, which the boot will empty.

If the reboot slips out of the window, say so, and redo the gate and the quiet-hour check.

## 6. After the boot

`probe.sh --post-boot` takes these checks, and each one that fails is a finding. The downtime, and any `Persistent=` catch-up, are left to you.

- **A clean shutdown:** the data store's own log, no EXT4 orphan recovery, and the chain's journal copy. For Postgres: `database system was shut down at …` and no `redo starts`.
- **Each `service`:**
  - `NRestarts` and **the first start's result**, not just `is-active`. address-validator's first start failed on a dependency that wasn't ready yet (CannObserv/address-validator#239). A start by hand after a failure leaves `NRestarts` at 0, so read `InactiveEnterTimestamp`: unset, the unit never stopped or failed after it started. Set, only PID 1's lines in the journal tell a failure from a stop by hand;
  - **its ordering**: `systemd-analyze critical-chain <service>` includes its data store, and the unit has `After=` on it. wslcb's first start succeeded by luck, until `After=postgresql.service` made it configured. Don't add `Wants=`: it would start a cluster an operator stopped on purpose.
- **Each `restarter`** is active.
- **The timers** are scheduled. Record any `Persistent=` catch-up, and whether any run was cut off: `Persistent=` catches up a run *missed* while down, not one *killed* part-way.
- **needrestart is clean**, `sudo grep -c '(deleted)' /proc/1/maps` reads 0, and `reboot-required` is gone.
- **The session adj, read directly** up the chain to PID 1. Never trust a test that can skip.
- **Containers are back.** On power-map, qdrant waited for first use despite `unless-stopped`. On wslcb, with `docker.service` enabled, both came back at boot. The difference is `docker.service`: disabled, nothing starts dockerd at boot, so no restart policy runs until something asks Docker through `docker.socket` (measured in the exeuntu image, 2026-10-01). Check before the reboot whether it's enabled, and after it, start by hand what should be back. The probe reads the containers from disk while dockerd is down, and fails the check for each one a restart policy should have brought back.
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
