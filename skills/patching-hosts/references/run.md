# The run: gates, recovery point, held steps

The procedure ten hosts followed by hand in #313's step 0 round, and the one the skill's scripts implement. Each step names the trap it avoids. Steps 4 to 7, the reboot and the record, are [reboot-and-record.md](reboot-and-record.md). The owner approves in the host's own session, and **nothing said in a chat channel counts as approval**.

## Approvals

Three, given separately:

1. **The needrestart drop-in**: a repo change, then its installation.
2. **The apply**: the bulk step, after the recovery point, on a host that declares a `datastore`.
3. **Restarts**:
   - **3(a)**: each held step that can restart a service (Postgres's cluster, Redis, containerd), with any `restarter` stopped around it. noble's `redis-server` restarts the server from its postinst on upgrade ([the profile](environments/exe-dev-exeuntu.md#packages-that-restart-their-own-services));
   - **3(b)**: the reboot.

   A maintainer script's restart is still a restart, so the owner approves it knowingly, not as a side effect of "the apply".

## Before each step: the gate

- **The step's whole span**, from now to now plus its expected duration, is inside a `window` and overlaps no `quiet` range. For a held step, the expected duration is the dry run's wall time. For the reboot, it's the chain's delay plus the boot and the post-boot checks. **The bulk's span is the rest of the run** (#362): the bulk at three times its dry run (replicator's took 2.2 times, wslcb's 2.5), each held step its selection reaches, and the reboot chain wherever the selection makes a reboot certain (a kernel, or a package owning a file PID 1 maps) or PID 1's files can't be read. Only PID 1 is read: [step 4](reboot-and-record.md#4-the-reboot-decision) also reboots for dbus, logind, `user@` or a data store, and a library only they map goes unpredicted. On watcher, PostgreSQL's backends mapped `libxml2`, which PID 1 doesn't. On wslcb a bulk that ended 12 minutes before the window closed left the 720 s chain no room, and the host ran 13 hours on deleted libraries. Checking only the start lets a 9-minute apply begun 5 minutes before a quiet range run into it.
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

Every host records its before-versions, which the bulk writes to its run directory (below). A host that declares a `datastore` also needs a dump that has left the node before the apply. `recovery-point.sh --approve --retain-until <date>` takes it, as below, and writes the record the bulk reads from the directory passed as its `--run`. **A host with none, such as a pure bus worker, has nothing to dump, and skips `recovery-point.sh`**, which exits 3 there: `recovery-point: refused: the knob declares no datastore, so there's nothing to dump: a host with none needs only its before-versions, which apply.sh records`. Its bulk takes no `--run`: it makes `/var/backups/patching-hosts-<UTC>` itself, records the before-versions there, and prints it as its JSON's `run`, which each held step and the reboot chain take. Like a step, it takes minutes: run it in the background. Each disk it writes, the run's and Docker's root for a Qdrant snapshot, must hold its share with §3's 128 MiB floor still free.

- **Prefer the host's own backup regime** when one exists and succeeded recently, for the datastores it covers: its `backup` line names them, and the rest are dumped. Start it by hand, then confirm the new object, its verification and its check-in (CannObserv/watcher#331).
  A Redis it covers is saved first, since the unit ships the RDB file as it stands ([datastores.md](datastores.md#the-recovery-point)).
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

  For Redis and Qdrant, each with what it takes, the logins and the snapshots: [datastores.md](datastores.md).

  A unit may carry its suffix or not: `postgresql@16-main` is `postgresql@16-main.service`, as in the knob. A `dump` is a file meant to leave the node, and the owner attests each one with `--offnode-sha256`, typed from their own copy. A `backup` is the host's own backup unit, which writes off the node itself, and one the knob's `backup` lines name (or the service a named timer starts), with the datastore units it covered (`<unit>:<db>` per database, [knob.md](knob.md), #480): its run must have *started* after `began` and succeeded, it stands in for the dumps of those datastores and no others, which its knob line must name too, and the owner names its object with `--offnode-object`. A datastore or database no backup covered needs its own dump. A `local` file, such as the globals dump, stays on the node and is never attested, and so does a Qdrant's `counts` file, which the checks after a restart read. `retain` is the stated retention, and `personal` flags a dump that holds personal data. `persistence` says how each Redis keeps what it holds, read from its own file and arguments, whether it was dumped or shipped by a backup. The bulk refuses a record that began more than 24 hours ago, or that misses a database a `datastore` line names.
- **A Redis restore under `appendonly yes` isn't a copy of the RDB file**, but the file staged as the AOF's base (#381; [datastores.md](datastores.md#a-restore-under-appendonly-yes)).
- A package rollback reinstalls the recorded version. Where the image carries `docker-clean`, as exeuntu does, apt's `.deb` cache is emptied after every run, so fetch it from snapshot.ubuntu.com ([the profile](environments/exe-dev-exeuntu.md#other-facts)).

## 3. The apply, in held steps

`apply.sh` runs this section: `--step bulk` (approval 2), then `--step <group>` for each held group (approval 3(a)). **Start each step in the background.** A step runs for minutes (address-validator's dry run alone took 9), longer than a foreground call allows (Claude Code's: 2 minutes by default, 10 at most), and a call that's cut off kills the step with it. A bulk killed once it has written the run's `holds` leaves every hold listed there on, and records no step, so no held step and no new bulk runs on that run. Treat it as the abort branch: check `dpkg --audit`, have the owner release or declare each hold `holds` lists, and start a new run. Besides the gate, it refuses a host where `unattended-upgrade` would reboot by itself: with `Automatic-Reboot` true it reboots once `reboot-required` appears, it takes no `-o`, and `APT_CONFIG` is read before `apt.conf.d`, so nothing passed to it overrides the host's setting. It also refuses origins wider than `-security` without `exception uu:origins`, and a `dpkg --audit` that isn't clean before the step. Where the apt timers run, it refuses an automatic apt run in progress, or a span that meets the range `apt-daily-upgrade.timer` can start in, its calendar time plus its random delay, which systemd draws again at every reload: that run's `unattended-upgrade` would hold the lock, and the step would fail with nothing upgraded.

**Each step is gated on the space it writes** (#390). Its download, each candidate's `Size` less an archive already in apt's cache at that size, must fit in apt's cache. Its install growth, `Installed-Size` against the installed version's, plus its largest upgrade, must fit on `/`: dpkg unpacks an upgrade beside the files it replaces, so for a moment both are there. Each filesystem also keeps **128 MiB free** for what no `Installed-Size` counts: a kernel install used 46 MiB more than apt said, 19 MiB of it the initrd (noble, 2026-10-26). Where apt's cache and `/` share a filesystem, the sum is checked once. The figures are apt's own, read from its metadata. `apt-get --assume-no` prints the same two, but it's no dry run: an install of exactly the packages it names asks no question, so it installs them. A held step is refused before it changes anything. The bulk reads its figures after its `apt-get update`, since only then are they the host's, and a shortfall stops it there with nothing held (exit 1): free space, then run it again. **Where the host runs the canonical disk GC** (`/etc/cannobserv/disk-gc/disk-gc.conf`, [maintaining-host-disk](../../maintaining-host-disk/references/turning-on.md#picking-the-lines)), a step whose download and growth would take the sensor's `[sensor] mount` to its `alert_at_percent` or past it, by its sensor's own `df` Use%, rounded up, is refused too: a patch run must not push the host into a headroom page. A key the file leaves out takes the GC's own default in VERSION 2 and 3 (85, `/`). A file that can't be read or parsed stops the step and never passes it, as it stops the GC.

Count first (`probe.sh --dry-run-into DIR` does both, with apt's cache in `DIR/archives`, and leaves `DIR/summary` for `apply.sh --dry-run DIR`):
- Count security from `sudo unattended-upgrade --dry-run -d`, from its `Packages that will be upgraded` line, while its origins are `-security` alone (the probe's `security_only`): wider origins put other packages on that line too. The `pkgs that look like they should be upgraded:` header lists the whole selection one per line, and `apt list | grep -security` undercounts (usa-wa: 178 against 185).
- Record the dry run's time and max RSS. Its `space` sizes what the run writes, with the free space on `/` and `/var/backups` beside it, and raises a finding wherever the gate above would stop a step.

Then:

1. **Refresh the host's own lists** (`apt-get update`): the probe counted against a scratch copy, and on a host whose timers are masked, the host's may be months old.
2. **Hold** each `hold` group in the set. Expand its globs against what's pending once the lists are fresh (`apt-get -s dist-upgrade`, any origin), record the names, and `sudo apt-mark hold` those names: the recorded list is exactly what step 4 releases. **Leave the owner's own holds alone:** a package in `apt-mark showhold` before the run was held on purpose, so the run never holds or unholds it. Report it as held by the owner. If it's in the pending set, that's a finding unless a `held:<package>` exception covers it ([policy.md](policy.md#exceptions)).
   **Read each held package's candidate there too, against the version the dry run counted** (#383). A release published between the two is what its held step takes: broker's dry run counted Tailscale 1.102.4, and its step installed 1.104.1. `apply.sh` lists each one that moved under the bulk's `verdict.version_moved`, for the owner to read before approving 3(a), and each held step does the same for what it installed. It's never a refusal. The security lane records the versions and compares none: the simulation shows a newer `-updates` version where there is one, and `unattended-upgrade` still takes the `-security` one.
3. **Bulk:** `sudo NEEDRESTART_MODE=l choom -n 0 -- unattended-upgrade -v`.
   - `choom -n 0` puts the apply at adj 0, so the kernel doesn't sacrifice a production service to protect a -1000 session.
   - **No hard memory cap:** a `MemoryMax` kill mid-dpkg leaves packages half-configured.
   - `NEEDRESTART_MODE=l` backs up the drop-in. In apt's hook there's no `-r`, so the variable wins.
4. **Each held group, under approval 3(a):**
   - stop each `restarter`;
   - unhold the packages the run held, and only those. In this order, a stop that fails leaves the group held, and the step can run again;
   - run the same command, and record what it installed (`dpkg-query -W`);
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

**An expedited run of one origin**, for a security bulletin's out-of-cycle window: `apply.sh --lane origin:<origin>`, counted first with `probe.sh --lane origin:<origin> --dry-run-into`. The origin must be one the knob follows. Its file adds that origin's pattern alone. At the bulk, after the lists refresh, every other pending package goes in `Unattended-Upgrade::Package-Blacklist`, each name anchored and escaped, since unattended-upgrade matches the list as regular expressions. Only the origin's own packages are candidates for a hold group. It's the same command, and the skip list leaves no hold to release. On noble with unattended-upgrade 2.9.1 (2026-10-03), it took `tailscale` alone out of 8 pending packages.

**It must take the origin's packages, or fail.** unattended-upgrade passes over an upgrade that needs a package the lane skips: it logs a "kept back" line, and with nothing else to take, "No packages found", and exits 0 (2.9.1). So the gate refuses a dry run that counted nothing from the origin, or would leave any of its pending upgrades (`dry_run.origin_left`): that window would take the rest, then fail. The bulk fails before any hold when nothing from it is pending against the refreshed lists. The probe's dry run doesn't run when it can't tell the origin's packages from the rest: when `apt-cache policy` couldn't be read, or lists no origin at its site. And after each step, `apt-get -s dist-upgrade` must no longer list any of the origin's packages that the step was to take (`upgrade.origin_left`).

**Then confirm the daemon runs the fix,** not just that the package is installed: a running daemon keeps its old binary until it restarts. For Tailscale, `tailscale version --daemon` prints a `Daemon:` line, which must match its `Client:` line. While tailscaled still runs the old binary, it warns `client version "…" != tailscaled server version "…"` on stderr. **Plain `tailscale version` never warns:** it prints the client's version alone. Measured on noble on 2026-10-04, with 1.102.4 installed over a 1.102.2 daemon. `tailscale status --json` and `tailscale set` warn too. The reprobe records both versions: `updates.tailscale.daemon_version`, read with `--daemon`, beside `version`, which is the CLI's. Tailscale's postinst restarts tailscaled itself, through `deb-systemd-invoke` (read in 1.102.4), so a stale daemon means that restart was denied or failed. The step's reprobe, `<run>/probe-after-<step>.json`, lists under `impact.reboot.needrestart_services` each service needrestart finds still running a replaced binary: after a one-origin bulk on noble that left tailscaled running 1.102.2, it was `["tailscaled.service"]` (2026-10-04).

**The recovery point applies to every lane.** On a host that declares a datastore, an expedited bulk refuses without one, like any other (§2). An origin can ship a data store itself, as PGDG ships Postgres, and the gate doesn't tell one origin from another. So take the recovery point before an urgent window opens, not inside it.

**The verdict** comes from the exit code, `All upgrades installed`, an empty `dpkg --audit`, and in the one-origin lane, nothing of the origin's left pending. **Never count `Failed` or `error` lines**: a clean apply logged about 100 needrestart "kernel versions" lines.

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
