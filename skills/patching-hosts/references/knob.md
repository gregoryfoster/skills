# The host knob: `.skills/patching-hosts`

A consuming repo commits `.skills/patching-hosts` to tell the skill what only its owner knows. The skill reads it and never writes it. With no knob, every host is treated as `production` with posture `automatic`: the probe reports its deviations from that reference policy, and nothing is applied.

The grammar is one directive per line, and blank lines are ignored. **`#` starts a comment only at the start of a line or after whitespace**, so a command can hold a `#` (a URL fragment) as long as no space precedes it. `inflight` and `health` take the rest of the line as their command, run with `sh -c`, so a pipe works. It's the other knobs' `#`-comment line grammar, plus `[host <glob>]` sections, so it parses on stock Ubuntu with nothing extra installed. **A malformed line is a finding, never silently skipped**, reported by its line number and never echoed. It also makes every host report-only until it's fixed: a dropped `quiet` or `datastore` line would otherwise let a run through that the owner meant to stop.

`read-knob.sh` prints what the knob resolves to for one host, as JSON ([SKILL.md](../SKILL.md) has its resolution block). `probe.sh` and `apply.sh` read it through the same library, so every script sees the same knob.

## Hosts and sections

One file describes every host the repo deploys to: production, staging and dev hosts in one repo, or a primary plus throwaway workers in another.

```
class production              # applies to every host
posture scheduled

[host co-worker-*]            # overrides for the hosts it matches
class ephemeral
```

- Lines outside any section apply to all hosts. A `[host <glob>]` section overrides them for the hosts it matches. A glob uses only `*` and `?`.
- A host finds its sections by `--host NAME`, or else by `hostname`'s output as it stands.
- **Precedence:** global, then each matching glob from the least specific to the most, then an exact name. A glob's specificity is its count of characters that aren't `*` or `?`, so `[host co-worker-*]` refines `[host co-*]`.
- **Two matching globs equally specific** are a finding, not a silent choice. Neither applies, and the host is report-only until one is narrowed or an exact section is added.
- **A host that matches no section** gets the global lines only. With no global `posture`, that's `automatic`, report-only.
- A header that doesn't parse is malformed, and so is every line under it until the next header: they can't be placed, so they apply to no host. The same header twice is reported, and its lines are read as one section.

**How values combine** across the global lines and the sections that match:

| Kind | Directives | Rule |
|---|---|---|
| one value | `class`, `posture`, `image-owner`, `records` | the most specific scope that sets it wins |
| a list | `window`, `quiet`, `inflight`, `health`, `restarter`, `service`, `backup`, `caller` | the most specific scope that declares any replaces the whole list |
| keyed | `datastore` (per unit and database), `hold` (per step), `owner` (per component), `origin` (per origin), `exception` (per `<what>`) | entries accumulate across scopes; for one key, the most specific wins |

A one-value or keyed directive set twice at the same precedence is a finding, and the later line wins; a list simply holds every line. Two `datastore` lines for one unit add their databases together.

## Directives

**Times are UTC**, always, and carry no suffix. A range `HH:MM-HH:MM` whose end is earlier than its start **wraps past midnight**: `window Tue 14:15-07:25` opens Tuesday at 14:15 and closes Wednesday at 07:25. A weekday names the day the range starts. A range that ends where it starts is malformed: it could mean nothing or a whole day, and the reader won't guess.

| Directive | Meaning |
|---|---|
| `class production\|staging\|dev\|ephemeral` | An `ephemeral` host is patched by rebuilding its image, so it gets a report and never an apply. |
| `posture automatic\|scheduled` | [policy.md](policy.md). Absent: compared against `automatic`, report-only. |
| `window <weekday> <HH:MM-HH:MM>` | When the monthly run may happen. Each step's whole span must fit inside one, or `apply.sh` refuses it, so a host with none gets no apply. May repeat. |
| `quiet <HH:MM-HH:MM> [<weekday>]` | A range no step may overlap: an ingest run, a backup, the callers' busy hours. Without a weekday, every day. May repeat. |
| `inflight <command>` | Must print `0` before each step, and again inside the reboot chain. For a job queue, the in-flight count. For oneshot ingest, the task units that are running: a `Type=oneshot` unit is `activating` while its command runs, and never `active` without `RemainAfterExit=`, so count `--state=activating,active,deactivating` (#359). |
| `restarter <unit>` | An in-host automatic restarter (a health timer, a watchdog, an `OnFailure=` target that starts or restarts a service; one that only notifies isn't one). Stopped for a data-store restart, then proven active again. |
| `service <unit>` | A runbook service: stopped in the reboot chain, and checked after boot for its first start's result and its ordering. |
| `health <command>` | A health check. Must exit 0. May repeat. |
| `datastore postgres <unit> <database>...` or `datastore redis <unit>` | What the recovery point captures, and what the reboot chain checkpoints and stops. A Postgres line names each database to dump. A database the cluster holds that no line names is a finding, because the recovery point wouldn't cover it. `template0` and `template1` are exempt, and so is `postgres` while it holds no table of its own: it's the default database, so an app may keep its tables there. May repeat; a unit named twice is checkpointed and stopped once. |
| `backup <unit> <datastore unit>...` | The host's own backup regime, and each datastore unit it covers, as a `datastore` line names it. The recovery point prefers a recent success of this unit over a second dump of those datastores: `recovery-point.sh` starts it, or the service a declared timer starts, and needs that run to succeed. **It stands in for the datastores it names and no others**: each one any backup line doesn't cover is dumped. A line that names no datastore is malformed, and one that names a datastore no `datastore` line declares is refused (CR 194). May repeat. |
| `hold <package-glob>... <step>` | A package group applied as its own step: one or more globs, and the **last token is the step's name**. The defaults are `postgresql-* libpq5` as `postgres`, `redis-server redis-tools` as `redis`, and `docker.io containerd` as `docker`. A `hold` line naming a default step **replaces** that default; the other defaults stay. |
| `caller <repo>` | A repo whose service calls this host, told before a restart. |
| `owner <component-glob> <repo>` | The update owner of a component apt doesn't reach. `<repo>` is `owner/name`, `self` for this repo, or `image` for whoever owns the image. The default owner of what the image ships is `image`. |
| `image-owner <owner/name>` | Whom `image` means: the repo that owns this host's image. The profile's image-level findings, and notices for what the image ships, go there. Absent: they're reported with owner `image`, and no notice is proposed. **A public repo whose image owner is private leaves it out**, since committing it would publish that repo's name (#350). |
| `origin <origin> follow\|pin <version>\|hold <reason>` | A third-party apt origin's policy in the maintenance lane: it takes a `follow` origin's updates, and never a `pin` or `hold` one's. `<origin>` is its `o=` field as `apt-cache policy` prints it, with `_` for each space, or its site, read as a site because it holds a dot. A third-party origin with no line is a finding. A *follow* origin is scoped by apt pins, not here: a `Package: *` pin below 500 for its site, and a package pin for each package it was added for ([policy.md](policy.md#two-lanes)). |
| `exception <what> <review-by YYYY-MM-DD> <reason>` | A declared deviation, expiring on its date ([policy.md](policy.md)). |
| `records <path-or-repo>` | Where run records go. |

## Commands from the knob

`inflight` and `health` are shell commands read from a committed file. **They never run as root.** They run as `$SUDO_USER` when a script is started with `sudo`, or else as the user who started it. The reboot chain, which is root, records that user's name when it's written and drops to it with `runuser -u <user> --`. A script refuses to run a knob command when the user resolves to root. The chain script prints each one verbatim, so the owner approves the exact commands with the chain. Otherwise, anyone who can commit the knob could get a command run as root at the next patch run.

Each one runs under a 60-second limit where `timeout` exists, as it does on every Ubuntu host, and one that hits it is reported as timed out. One that ignores the TERM is killed 10 seconds later. A check that hangs, such as a `curl` to a dead host, can't hang the probe or a gate that waits on it.

## An example

Illustrative, shaped like a host with local Postgres, scheduled ingest and a health timer that restarts the app. It isn't any one repo's file.

```
class production
posture scheduled

window Tue 15:00-21:00
quiet 07:25-08:15                  # the 00:30 PT scrape and its backfill
quiet 13:25-14:15
quiet 08:55-10:10 Sun              # weekly backfill and disk hygiene

inflight systemctl list-units 'app-task@*' --state=activating,active,deactivating --no-legend | wc -l
service app-web.service
restarter app-healthcheck.timer
health curl -sf http://localhost:8000/api/v1/health

datastore postgres postgresql@16-main app
hold postgresql-* libpq5 postgres
hold docker.io containerd docker

image-owner example-org/base-image
owner scripts/bin/tailwindcss self

exception keep:nginx 2026-12-31 ships with the image; the prune belongs in the base image
```
