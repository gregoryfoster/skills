## Session 2026-10-21 — three hosts of a private project

The consuming project's repo is **private**, so this entry names no identifier from it, and describes its hosts by shape. It's the execution record for the scenario #464 describes: #464 was filed the morning of the release, before anything ran, and this entry is what happened when the procedure met a real release.

This was a **hand run of the skill's procedure**: the scripts are vendored but not wired into this consumer, so each step was run by hand, following SKILL.md and run.md. The trigger was the PHP project's **pre-announced critical release**: two CVSS 9.2 advisories in Core, announced the day before for 14:00 UTC. Three hosts were in scope:
- **a cloud VM** with no local data store (its database is a managed cluster), on Ubuntu 24.04, PHP from the `ondrej/php` PPA, amd64;
- **a dev VM** under a desktop hypervisor, with a local MariaDB dev database and a host-mounted project tree, the same PPA, arm64;
- **the operator's workstation**, PHP from Homebrew.

A fourth host was **put out of scope by the owner**, with the reason recorded in the consumer.

### Decisions

- **Owner approval, given once before the release:** auto-apply on all three hosts as each one's fixed build appears, with the checks per host named, and any failed check stopping the run before the next host.
- **The workstation's end-of-life runtime kegs were retired** before the release, with the owner's approval. The release then confirmed it: the oldest supported line got no release.
- **Scope was the runtime's packages alone.** Every other pending package was left for the hosts' own scheduled runs.

### Readings and prep, before the release

- **Before-versions were recorded** on each host. The cloud VM was **8 patch releases behind**: #464's finding.
- **Lists were refreshed, and the origin confirmed reachable**, on both apt hosts.
- **The recovery point on the dev VM:** `mysqldump --single-transaction --routines --triggers --events`, written through the host mount, which takes it off the VM. Each dump was checked for its `-- Dump completed` trailer, and its sha256 recorded. It went in a **subdirectory**, because a sibling tool picks "the newest `*.sql.gz`" from the parent directory and would have loaded a dev dump as a production one. The cloud VM has no data store, so its rollback is the before-versions.
- **Baselines were taken through the runtime:** a front page and an API namespace index, through the local vhost on each host. Plus the dev VM's full unit test tier, which passed.
- **CI** (a hosted runner with a setup action) resolves the latest patch release by itself; its baseline was read from the last run's log.

### Timeline of the release, UTC

| Time | Event |
|---|---|
| ~13:37 | **Upstream released, 23 min before the announced time**: fixed releases on four supported lines. The changelog named both advisories at release. |
| 14:13–14:31 | Homebrew bump PRs opened. |
| 14:36 | PPA builds dispatched, all architectures. |
| 14:45 | PPA source publication accepted. |
| 15:57 | PPA **amd64 built**. |
| 16:38 | Homebrew versioned-formula PR merged. |
| ~17:00 | Its bottle for the workstation's tag visible in the formula API, about 20 min after the merge. **Workstation, minor line patched.** |
| 17:46 | PPA **arm64 built**. |
| ~18:10 | Homebrew unversioned formula's bottle visible. **Workstation done.** |
| ~18:16 | PPA **amd64 published**, 2 h 19 m after it was built. |
| 18:25 | **Cloud VM done**, after one failed attempt (lesson 2). |
| ~19:36 | PPA **arm64 published**, 1 h 50 m after it was built. |
| 19:47 | **Dev VM done.** |

From the upstream tag to an installable package took **about 4 h 40 m (amd64) and 6 h (arm64)**. Most of the lag was between "built" and "published". At 16:52, Launchpad's binary-publication API had **no record at all** of the amd64 build finished an hour earlier, not even a pending one.

### Lessons

#### 1. The watched channel must be the install channel

A watcher polled five channels every 5 minutes: the upstream release JSON, the PPA's `Packages.gz` for each architecture, and the Homebrew formula API, filtered on a bottle for the host's own tag (read from `brew ruby -e 'puts Utils::Bottles.tag'`). It exited on the first channel to change. Then that host was patched and the watcher re-armed for the rest. The upstream channel fired first, and was useful only as information. Each install channel arrived on its own clock, hours apart.

#### 2. Release-day CDN 503s, and the all-or-nothing set

The PPA's CDN served **intermittent HTTP 503s for hours**: on the indexes, then on the `.deb`s.
- `apt-get update` **exited 0** after `Err:`/`Ign:` lines on the origin's `Packages`. The stale candidate was indistinguishable from "not released yet".
- **The cloud VM's first apply failed at fetch:** 5 of 11 `.deb`s returned 503, and apt exited 100 after 4 minutes, before reaching dpkg. Nothing was installed: `dpkg --audit` was clean, the old version still ran, and the service was untouched. The 6 that downloaded stayed in apt's cache.
- **The second pass split download from install:** a loop of `apt-get install -y -d -o Acquire::Retries=5 --only-upgrade '<pattern>'`, with a 30 s pause, up to 30 attempts, gated on every candidate being in the cache. Then `apt-get install --no-download -o Dpkg::Options::=--force-confold` under `NEEDRESTART_MODE=l`. The cloud VM got its set on attempt 1 of the loop, the dev VM on attempt 2.

That split is what turned the 503s from a gamble into a non-event: dpkg sees the whole set or nothing.

#### 3. A watcher that masks one channel's failures with another's success

The first watcher counted a poll as healthy when **any** channel fetched. With the PPA's indexes on 503 and Homebrew's API answering, it stayed silent about the PPA for about an hour. That would have meant a late patch, not a wrong one. It was fixed with a failure streak per channel, three retries per poll, and an error after six failed polls in a row.

#### 4. The FPM package restarts itself

On both apt hosts, the PHP 8.4 FPM package's maintainer script **restarted** the service (a new main PID) during configure. Measured: under 1 s, with `pm = ondemand`. needrestart in list mode listed nothing for the runtime. On the dev VM it listed `dbus`, `systemd-logind`, `unattended-upgrades` and the user manager, all from the VM's own unrelated backlog, since PHP maps none of their libraries. The FPM drop-ins in `conf.d/` and `pool.d/` survived, confirmed by `php-fpm -tt`. No `.dpkg-dist` or `.dpkg-new` files appeared.

#### 5. A health check that never reaches the runtime

The site's `/health` is answered by **the web server itself**, with a static 200, so it was green throughout and proved nothing about PHP. The checks that counted went through the pool: the front page (status and size), and an API index, byte-identical before and after on the cloud VM. The front page's first request after the restart took 2.8 s, against a 1.6 s baseline, then 1.7, 1.5 and 1.1 s as the opcode cache warmed.

#### 6. A stale baseline, and the second recovery point that explained it

After the dev VM's apply, its front page was **45% larger** than the morning's baseline. There were no PHP warnings, the size was stable across repeats, and no application code had changed. The cause was data: the dev database had changed during the day. The **second recovery point**, taken just before the apply because the first was 6 hours old, showed it: diffing the two dumps' row counts per table showed changes in three content tables. Without the pair, the change would have been misread as a runtime regression, or waved through unexplained.

#### 7. Advance approval held its scope

The apply ran unattended across about 6 hours under the one approval. The abort rule never fired. The only failure (lesson 2) stopped before dpkg, by apt's own ordering, not by the rule.

#### 8. The workstation, outside apt

- **The inventory was wrong as first read.** `brew list --versions` printed a stale, unlinked keg of the **unversioned** formula on an older line, not an installed versioned formula for that line. The `opt/` symlinks for two older lines were aliases of the unversioned formula. The first plan's `brew upgrade` of three formulae would have **installed** a new release on an end-of-life line. Read versions per keg, with `ls -la $(brew --prefix)/opt`, and install receipts.
- **Retiring end-of-life kegs:** check `brew uses --installed`, `brew services list`, the launch agents, shell rc files, and any project's runtime constraint (all were floors, not ceilings). Then `brew uninstall`. Uninstalling leaves `etc/<runtime>/<line>/` behind; diff it against `.default` before deleting.
- **A third-party tap shadowed the core formula's name.** After the tap's own kegs were gone, a bare `brew cleanup php` still resolved to the tap's `php.rb`. **Homebrew's untrusted-tap guard then blocked `brew untap`, with or without `--force`,** because untapping loads the tap's same-named formula. Trusting the tap only to remove it would evaluate its Ruby. So: confirm that nothing in `bin/` or `share/` links into the tap directory, then delete the tap directory.
- **A pin from an older line blocked the fix.** The unversioned formula was pinned, which blocks `brew upgrade <f>` and makes `brew cleanup` skip its stale kegs. The owner unpinned it. Separately, `brew cleanup <f>` skips while the newest version isn't installed ("most recent version … not installed"), so the stale keg went only after the upgrade.
- **The upgrade upgrades dependencies too.** Upgrading the versioned formula pulled 13 dependency bumps (curl, openldap and sqlite among them), and upgrading the unversioned one also upgraded two tools that depend on it.
- **The re-link trap.** The runtime on PATH was the **keg-only versioned formula, force-linked**. `brew upgrade` of the unversioned formula re-linked it over the top, so `php -v` **silently became the newer minor line**. It was restored with `brew unlink php && brew link --force --overwrite php@<line>`. The dependent tools follow PATH (`#!/usr/bin/env php`), so verify through them too: `composer --version`, for one, reports the runtime it runs on.
- **The channel's lag:** the bottle appeared in the formula API about 20 min after the PR merged. Watch for the host's bottle tag, not the version string, or `brew upgrade` builds from source.

#### 9. A config test that needs root

On the dev VM, `php-fpm<line> -t` without sudo printed `ERROR: FPM initialization failed` on a config that tested clean as root a moment later. It's a false finding, not a broken config.

### Results

| Host | Change | Downtime | Verified by |
|---|---|---|---|
| cloud VM | 11 runtime packages, one patch line | under 1 s (maintainer restart) | the runtime's `-v` (CLI and FPM), `dpkg --audit`, pool settings, front page and API index through the pool against baseline |
| dev VM | 13 runtime packages, one patch line | under 1 s | the same, plus the full unit tier, identical to baseline |
| workstation | the versioned and unversioned formulae; end-of-life kegs retired | none | `php -v` after the re-link fix, dependent tools' reported runtime, a style-gate run |

CI is confirmed on its next run, and a golden image on its next build: neither is a host this skill patches.

### Other notes

- **The silent drift (#464's finding) explained the cloud VM's backlog,** and this release would have found it 8 patch releases behind had no one been watching. The case for #464's `origin <origin> expedite` stands. This run is evidence that the expedited path also needs lesson 2's download-first gate, because release day is exactly when the origin's CDN is overloaded.
