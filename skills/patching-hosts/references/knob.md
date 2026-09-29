# The host knob: `.skills/patching-hosts`

A consuming repo commits `.skills/patching-hosts` to tell the skill what only its owner knows. The skill reads it and never writes it. With no knob, every host is treated as `production` with posture `automatic`: the probe reports its deviations from that reference policy, and nothing is applied.

The grammar is one directive per line. `#` starts a comment, and blank lines are ignored. It's the same line grammar as the repo's other knobs, so it parses on stock Ubuntu with nothing extra installed. A malformed line is a finding, never silently skipped.

## Hosts and sections

One file describes every host the repo deploys to: production, staging and dev hosts in one repo, or a primary plus throwaway workers in another.

```
class production              # applies to every host
posture scheduled

[host co-worker-*]            # overrides for the hosts it matches
class ephemeral
```

- Lines outside any section apply to all hosts. A `[host <glob>]` section overrides them for the hosts it matches.
- A host finds its section by `--host NAME`, or else by `hostname`.
- **Precedence:** global, then a glob, then an exact name. An exact name beats a glob.
- **Two globs that match equally** are a configuration finding, not a silent choice.
- **A file with sections and no match** for this host gets the global lines only. With no global `posture`, that's `automatic`, report-only.

## Directives

**Times are UTC**, always, and carry no suffix. A range `HH:MM-HH:MM` whose end is earlier than its start **wraps past midnight**: `window Tue 14:15-07:25` opens Tuesday at 14:15 and closes Wednesday at 07:25. A weekday names the day the range starts.

| Directive | Meaning |
|---|---|
| `class production\|staging\|dev\|ephemeral` | An `ephemeral` host is patched by rebuilding its image, so it gets a report and never an apply. |
| `posture automatic\|scheduled` | [policy.md](policy.md). Absent: compared against `automatic`, report-only. |
| `window <weekday> <HH:MM-HH:MM>` | When the monthly run may happen. May repeat. |
| `quiet <HH:MM-HH:MM> [<weekday>]` | A range no step may overlap: an ingest run, a backup, the callers' busy hours. Without a weekday, every day. May repeat. |
| `inflight <command>` | Must print `0` before each step, and again inside the reboot chain. For a job queue, the in-flight count. For oneshot ingest, the active task units. |
| `restarter <unit>` | An in-host automatic restarter (a health timer, a watchdog, an `OnFailure=` chain). Stopped for a data-store restart, then proven active again. |
| `service <unit>` | A runbook service: stopped in the reboot chain, and checked after boot for its first start's result and its ordering. |
| `health <command>` | A health check. Must exit 0. May repeat. |
| `datastore postgres\|redis <unit> [<database>]` | What the recovery point captures, and what the reboot chain checkpoints and stops. |
| `backup <unit>` | The host's own backup regime. The recovery point prefers a recent success of this unit over a second dump. |
| `hold <package-glob>... <step>` | A package group applied as its own step: one or more globs, and the **last token is the step's name**. The defaults are `postgresql-* libpq5` as `postgres` and `docker.io containerd` as `docker`. A `hold` line naming a default step **replaces** that default; the other defaults stay. |
| `caller <repo>` | A repo whose service calls this host, told before a restart. |
| `owner <component-glob> <repo>` | The update owner of a component apt doesn't reach. `<repo>` is `owner/name`, `self` for this repo, or `image` for whoever owns the image. The default owner of what the image ships is `image`. |
| `origin <origin> follow\|pin <version>\|hold <reason>` | A third-party apt origin's policy in the maintenance lane. |
| `exception <what> <review-by YYYY-MM-DD> <reason>` | A declared deviation, expiring on its date ([policy.md](policy.md)). |
| `records <path-or-repo>` | Where run records go. |

## An example

Illustrative, shaped like a host with local Postgres, scheduled ingest and a health timer that restarts the app. It isn't any one repo's file.

```
class production
posture scheduled

window Tue 15:00-21:00
quiet 07:25-08:15                  # the 00:30 PT scrape and its backfill
quiet 13:25-14:15
quiet 08:55-10:10 Sun              # weekly backfill and disk hygiene

inflight systemctl list-units 'app-task@*' --state=active --no-legend | wc -l
service app-web.service
restarter app-healthcheck.timer
health curl -sf http://localhost:8000/api/v1/health

datastore postgres postgresql@16-main app
hold postgresql-* libpq5 postgres
hold docker.io containerd docker

owner /usr/local/bin/* image
owner scripts/bin/tailwindcss self

exception keep:nginx 2026-12-31 ships with the image; the prune belongs in the base image
```
