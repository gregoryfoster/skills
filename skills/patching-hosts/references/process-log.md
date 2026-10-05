# Process Log — patching-hosts

What each run of the [`patching-hosts`](../SKILL.md) skill taught it, one entry per run. An entry records:
- the environment the probe detected, or that none matched;
- what the readings and the probe showed;
- what the profile got wrong or lacked;
- the decisions made, and why;
- what surprised the run.

Runs are appended in date order. A pattern that recurs is promoted, and listed under "Rules promoted into the skill" with the runs it came from. **It goes to one of two places.** A pattern that recurs on the same environment goes into that environment's profile (`environments/<id>.md`). A pattern that recurs across environments, or that every run needs, goes into the core: `SKILL.md` or the reference that owns the step.

**A profile fact goes stale.** Each one carries the date and host it was measured on. A run that contradicts one records the contradiction here, rather than trusting the profile.

**This file is the root of the index.** Each run is its own entry file under `process-log/<year>/`, named `<date>-<host>.md`. Each year's rows live in that year's own index, `process-log/<year>/index.md`. Journaling a run means two things: write the entry file, and add one row to that year's index. See "Adding an entry" at the foot of this file.

## Years

- **2026** — [run index](process-log/2026/index.md)

---

## Rules promoted into the skill

Which runs each rule came from, wherever it now lives. The 2026 entries are the step 0 round of [#313](https://github.com/gregoryfoster/skills/issues/313): ten exe.dev hosts were patched by hand, before the scripts existed, and their rules were written into the skill as it was built.

- **An absent setting is not a reading:** a default reported as a state is a finding, and the honest output is `unknown` ([readings.md](readings.md)). From 2026-09-21 broker and 2026-09-22 archiver.
- **The needrestart drop-in goes in before the apply, with `NEEDRESTART_MODE=l` kept too.** It's proven with `needrestart -m u -b -r l`, and never without `-r l` ([run.md](run.md) §1). From 2026-09-26 broker, 2026-09-26 archiver, and 2026-09-29 address-validator, which read it in the source.
- **The reboot is decided from needrestart's list taken after the whole run, and `reboot-required`; on exe.dev, never from a kernel** ([run.md](run.md) §4). From 2026-09-26 broker, 2026-09-26 archiver and 2026-09-27 power-map.
- **A data store restarts when its processes map a patched library,** even when its own package isn't in the set ([readings.md](readings.md), the "which processes map a library in the set" row, and the profile). From 2026-09-29 watcher, and every Postgres host since.
- **The apply's verdict comes from the exit code, `All upgrades installed` and `dpkg --audit`,** never from counting `Failed` lines ([run.md](run.md) §3, `apply.sh`). From 2026-09-28 host 6 and 2026-09-28 replicator.
- **The security count comes from the dry run's own selection,** not from `apt list --upgradable | grep -security` (`probe.sh --dry-run-into`). From 2026-09-26 usa-wa.
- **A data store's packages and a container runtime's major bump are held, and applied as their own steps** (the knob's hold groups, `apply.sh`). From 2026-09-26 usa-wa, 2026-09-27 power-map and 2026-09-28 host 6.
- **Which packages restart themselves, whatever needrestart says,** is a per-package table in the profile. From 2026-09-28 host 6, 2026-09-28 replicator, 2026-09-29 address-validator and 2026-09-29 wslcb-licensing-tracker.
- **The reboot is in-guest, and run as a detached root script;** its timer has `AccuracySec=1s` (`reboot-chain.sh`, [run.md](run.md) §5). From 2026-09-26 broker and 2026-09-29 wslcb-licensing-tracker.
- **Read where the journal actually is, not its `Storage=` setting.** Shutdown evidence on a volatile journal is a copy taken last in the chain ([readings.md](readings.md), the profile). From 2026-09-27 power-map, 2026-09-29 address-validator and 2026-09-29 wslcb-licensing-tracker.
- **Every in-host automatic restarter is stopped for a data-store restart, and proven running again** (the knob's `restarter`). From 2026-09-29 wslcb-licensing-tracker.
- **Nothing in flight, read right before each stop and inside the reboot chain** (the knob's `inflight`). From 2026-09-28 host 6 and 2026-09-29 watcher.
- **The recovery point:**
  - it prefers the host's own backup regime (2026-09-29 watcher);
  - each dump is attested off the node;
  - a pipe into a file must not mask the dump's own failure (2026-09-28 notifier);
  - it has a stated retention (2026-09-29 address-validator) (`recovery-point.sh`, [run.md](run.md) §2).
- **What's left pending is reported by class,** Ubuntu Pro/ESM included, and the apply's auto-removals apart from its upgrades ([policy.md](policy.md), `apply.sh`). From 2026-09-29 address-validator and 2026-09-29 wslcb-licensing-tracker.
- **`dormant` needs 30 days of evidence, from a named source** ([policy.md](policy.md)), and a prune covers groups and memberships ([pruning.md](pruning.md)). From 2026-09-28 notifier, 2026-09-28 host 6 and 2026-09-29 watcher.
- **The session's OOM score is read directly, up the chain to PID 1,** never from a test that can skip (the profile). From 2026-09-28 notifier, 2026-09-28 replicator, 2026-09-29 watcher and 2026-09-29 address-validator.
- **A creation-time setup script is re-delivered at every boot,** so the remedy is to revoke its key (the profile). From 2026-09-28 replicator and 2026-09-29 watcher.
- **Before a reboot, list anything staged under `/tmp`, and read a daemon's live arguments from `/proc/<pid>/cmdline`** (the profile, [readings.md](readings.md)). From 2026-09-29 wslcb-licensing-tracker.

---
## Adding an entry

**First: is this skill vendored here?** Where the host repo consumes it as a git submodule, the entry does **not** go in the vendored copy. Draft it in the host repo, and file it upstream as an issue against this repo, which adds the entry. Writing it in place leaves the host reporting a modified submodule. This is the same rule as `orchestrating-issue-backlog`'s log.

**Second: is the host's repo private?** This log is public. Where it is, the entry names no identifier of the host's own:
- not its repo, issues, units, paths, databases or routes;
- nothing that would let a reader find it.

Call it "host N" and describe the mechanism instead ("the app fails every job in flight at boot"). Check before drafting: a landed entry stays in git history.

**Third: is anything still pending?** **An entry that lists pending security updates lands only after they're applied.** It records counts and package families ("PostgreSQL 16", "a major `docker.io` bump"), never versions. A published version that's still pending tells a reader what the host is exposed to. This is the same rule as a run's own record ([run.md](run.md) §7).

1. Write `process-log/<year>/<date>-<host>.md`, opening with a `## Session <date> — <host>` heading. Use the date the run's apply ended, and the year it ran in; create the directory for a new year.
2. Add one row to `process-log/<year>/index.md`. Link the date cell to the entry as a bare filename, since the index sits beside its entries. For a new year, create its index from the previous year's, and add it to the Years list above.

**Keep the row to a headline of about 400 bytes,** and put the detail in the entry. A year's index is bound by the 10,000-token per-doc budget, and every run that year appends to it.
