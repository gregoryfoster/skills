# Pruning a dormant component

A component the probe calls `dormant` is patch surface, disk and attack surface for no benefit ([policy.md](policy.md#dormant-components)). One it calls `named` (`named:<name>`) is idle too, but the repo's `deploy/` names it in a comment or prose: it isn't a prune candidate until the operator reads what that says, and proposes the prune or declares `keep:<name>` (#491). The skill proposes a prune and the owner runs it, one stage at a time, each under its own approval. Two scripts cover the steps that are the same on every host: `prune-plan.sh` reads, and `prune.sh` acts on exactly what a plan names. They know the six components the probe reads, and [any other apt package](#any-other-apt-package) by name.

Where the component shipped with the image on every host, the prune belongs in the base image instead, so provisioning stays reproducible. Until it gets there, a prune on one host is drift from that image, and the knob declares it.

Tooling files under a home directory, such as VS Code's server builds, aren't a dormant component and have no class here: the canonical disk GC prunes them, and [`maintaining-host-disk`](../../maintaining-host-disk/SKILL.md) installs it.

## The calendar

A prune runs **disable → remove → purge**, each stage after the last one's soak:

| Stage | What it does | Declared in the knob, after it ran |
|---|---|---|
| disable | stops, disables and masks every unit the packages ship, sockets, timers and path units too, each in one `systemctl` call so systemd orders the stops: dockerd before the containerd it runs on. A unit whose file is under `/etc/systemd/system` is stopped and disabled, not masked: the mask would be that same path. A unit masked already is left as it is, and recorded in the run's `masks` | `exception disabled:<name> <review-by> <reason>` |
| savepoint (optional) | a tarball of the config and of the packages' other conffiles, and the packages' versions, as root at mode 600 | (none: the purge names it) |
| remove | `apt-get remove` of exactly the plan's packages, then the group's members dropped | `exception removed:<name> <review-by> <reason>` |
| purge | `apt-get purge` of exactly the plan's packages, the members dropped and the group deleted, then each `--purge-data` path | `exception purged:<name> <review-by> <reason>` |

The **review-by date is the soak**: 30 days by default, up to 90. A stage refuses while the last stage's date hasn't passed; an earlier date shortens a soak, and that is the owner's call. `prune.sh --today` never runs ahead of the clock, so the knob is the only place a soak ends early. When a date passes, the exception expires and the probe reports the component again, if it's one of the six it reads ([an `apt:` one isn't](#any-other-apt-package)); `prune-plan.sh`'s `stage` names the next one. A `purged:` line stays until the base image stops shipping the component.

**With a savepoint, the remove stage is skipped**: disable, then the savepoint, which may be taken while the disable soaks, then the purge once the soak ends. That's the better path for security. `remove` leaves config behind, sometimes with secrets in it, and an `rc` package the probe then has to explain. Without a savepoint, the remove stage is the reversible step, and stays. The purge takes `--savepoint DIR` only where its record is this component's, on this host, and its tarball still has the sha256 the record names: each attempt removes the last record first, and writes its own only once the tarball is read back.

`exception keep:<name>` stops every stage, wherever the prune got to: the owner keeps it until its review-by date, whatever stage lines the knob also holds.

## The plan

```
bash "<prune-plan.sh>" --component <name> --out <file>
```

It changes nothing. Its JSON is what the owner reads before approving a stage:
- `units`: each unit, socket and timer, with its state now. For Docker that is `docker.socket` as well as `docker.service`, and `containerd.service`;
- `packages`: what `apt-get -s remove` and `apt-get -s purge` would take, including anything dragged along, and any held;
- `autoremove_would_take`: what apt installed for them alone. No stage autoremoves, but a later `apt autoremove`, or unattended-upgrades' `Remove-Unused-Dependencies`, takes these: for docker.io installed with its recommends on noble, 47 packages, `iptables`, `git` and `openssh-client` among them (measured). With `--take-orphans` they're in the plan instead, as `packages.orphans` ([below](#any-other-apt-package));
- `reverse_depends`: what else installed depends on them and stays;
- `purge_scripts`: the lines in each package's purge script that delete files, and `debconf`, its answers. **Read these before a purge:** nginx-common's deletes `/etc/nginx` and `/var/log/nginx`, and postgresql-16's drops every cluster, data and config. It sets `postrm_purge_data` to true itself before it asks, and with no terminal nothing answers, so a false answer set beforehand keeps nothing (measured on noble). docker.io's leaves `/var/lib/docker`;
- `paths`: its config and data, with sizes, and `conffiles`: its packages' conffiles outside its config, such as `/etc/default/nginx` and `/etc/logrotate.d/nginx`. A purge deletes those too, so the savepoint keeps them;
- `clusters`: each Postgres cluster, and where it keeps its data. A purge drops every one, wherever its data is;
- `group`: the group it lets members into. watcher's Docker removal left `exedev` in the `docker` group, root-equivalent the moment Docker came back (CannObserv/watcher#336);
- `residue`: its packages removed with their config left (`rc`);
- `stage`: what the knob declares now, and the next stage.

The plan file binds an approval: **take a fresh one for each stage.** A stage refuses a plan from another host, or one more than 24 hours old, and any plan the host no longer matches. A package installed or removed, a unit, a conffile, a Postgres cluster or a group member added or gone since, each counts, so what the owner approved is exactly what runs.

## The stages

```
bash "<prune.sh>" --stage disable --plan <file>                          # prints what it would run
bash "<prune.sh>" --stage disable --plan <file> --approve
bash "<prune.sh>" --stage savepoint --plan <file> --approve              # optional
bash "<prune.sh>" --stage remove --plan <file> --approve
bash "<prune.sh>" --stage purge --plan <file> --approve [--savepoint <dir>] [--purge-data <path>]...
```

Without `--approve` a stage changes nothing, and its `actions` list every command it would run. With it, it makes the run's directory, runs those commands in that order, and writes its own records there (the savepoint's versions and record); it changes nothing else. Each command's output goes to `<run>/<stage>.log`, root's only (default run: `/var/backups/patching-hosts-prune-<name>`). Its `next` says the knob line to add.

- **No autoremove, ever.** Each apt command names the plan's packages and sets `APT::Get::AutomaticRemove=false`. Afterwards, each package must be gone, and any other package apt took fails the stage.
- **No data the owner doesn't name.** A purge deletes a data path only by `--purge-data`, and only one the plan names. A package's own purge script runs too, so where one deletes a data path, the purge refuses until `--purge-data` names it: `/var/log/nginx` for nginx, `/var/lib/postgresql` for Postgres. So does each Postgres cluster's data, wherever it is: with postgresql-common still installed, `pg_dropcluster` deletes a data directory outside `/var/lib/postgresql`, and with it purged first, the data stays (both measured on noble). Named, it's deleted after apt whichever ran. To keep that data, dump it off the node first, or leave the component removed.
- **The masks stay.** A unit masked at the disable stays masked after the purge, so a component that comes back with a later install stays down until someone unmasks it.
- **Undo a disable** with `systemctl unmask` for each unit it masked, then `systemctl enable` only for the units the plan recorded as enabled (`units[].enabled`), and `systemctl start` only for those it recorded as active (`units[].active`): the disable acted on every unit, whatever its state, so `enable --now` on them all would turn on units that were off before.
- **The savepoint holds no data.** Data differs by component, so its backup stays with the owner: dump it off the node, with a stated retention, as for a recovery point ([run.md](run.md#2-the-recovery-point)).

Remove and purge also refuse while a package manager runs, when `dpkg --audit` isn't clean, when apt would install anything to take the component away, and while one of its packages is held. `apt-get -s` takes a held package, but `apt-get -y` refuses to (measured on noble), and the hold is its owner's: the plan's `packages.held` names it. Before a remove, the owner releases it with `apt-mark unhold`. A purge takes `--release-hold`, which runs that as the command just before `apt-get purge`: a hold that kept a package off the bulk, as `held:fwupd` kept fwupd's conffile prompt off it, lets the next bulk reach it again if it's released any earlier (#370). If the purge then fails, `next` says to hold it again. A hold placed or released since the plan is drift.

## Components from outside apt

Ollama and Qdrant come from an installer, not apt. `prune.sh` disables their unit. A unit file under `/etc/systemd/system` can't be masked, since the mask would be that same path, so it's stopped and disabled only. Remove and purge refuse for them. Delete the unit file, the binary and the data by hand, and declare each stage in the knob as for any other.

## Any other apt package

```
bash "<prune-plan.sh>" --component apt:<package>[,<package>...] [--take-orphans] --out <file>
```

A dormant apt package outside the six is planned by its Debian name. One the six own is refused, naming the component to use, whose guards cover its data, its clusters and its group (CR 1641): `apt:postgresql-16` is `postgres`'s. So is a name of theirs, such as `apt:redis`, which would share the component's knob lines, and so is a package whose removal apt would take one of theirs with: `apt:libpq5` takes `postgresql-16` as a reverse dependency, and `--take-orphans` may take `containerd` (CR 1646). The case is fwupd on the exeuntu images, whose units the image masks and whose motd conffile it deletes ([the profile](environments/exe-dev-exeuntu.md#other-facts), #370). Its units are the ones its packages ship. It has no config or data directory of its own, so the savepoint keeps the conffiles still on disk, and a purge deletes data only by its packages' own purge scripts, which the plan lists. The knob and the run's directory call it by the list after `apt:`: `exception disabled:fwupd`, `/var/backups/patching-hosts-prune-fwupd`. **The probe doesn't read an `apt:` component**, so its stage lines prompt nothing when they expire: once a date passes, re-run `prune-plan.sh --component apt:<package>` and read its `stage`.

- **Units masked already** are recorded in `<run>/masks` and left as they are, for every component. Where every unit was, that record is the whole disable, and the owner may end its soak early in the knob: a unit masked since the image was built has been off since then.
- **`--take-orphans`** moves `autoremove_would_take` into the plan by name, as `packages.orphans`. Every apt command then names them one by one, and still never autoremoves: apt's orphans from before the prune stay. For fwupd that's a purge of 54, fwupd and 53 orphans, ModemManager, udisks2 and the tss2 stack among them, and their units join the disable. A stage whose fresh read orphans another set refuses, as drift. It's off by default, since it can take far more than the component: read the list before approving it. A remove of such a plan is refused, since the orphans' leftover config would be residue that no later plan names. Take the savepoint path instead.

**A savepoint's versions can't bring back a version the archive dropped.** When wslcb purged fwupd 1.9.33, only 2.0.20 and noble's 1.9.16 were left to install (CannObserv/wslcb-licensing-tracker#193). The versions list says what was there, not what can come back.
