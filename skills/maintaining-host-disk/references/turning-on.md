# Turning it on, per host

A first install leaves both timers off. Turning the GC on is per host, because its config, its lines and its monitor are. Each step here follows the contract's "Turning it on" ([#425's contract comment](https://github.com/gregoryfoster/skills/issues/425#issuecomment-6371095613)), with VERSION 2's changes ([release comment](https://github.com/gregoryfoster/skills/issues/425#issuecomment-6387455753)). Every step that changes the host needs the owner's approval, given in the host's own session.

The host's own files live in `/etc/cannobserv/disk-gc/` and never ship in the layer: `disk-gc.conf` and `checkin.key`. No script in this skill writes them.

## 1. The config

Copy `/usr/local/lib/cannobserv/disk-gc/disk-gc.conf.example` to `/etc/cannobserv/disk-gc/disk-gc.conf`, then edit:

- `homes`: whose trees the GC walks;
- `tiers`: which tiers run. The `docker` tier is off in the template; turn it on only where Docker builds ([retiring.md](retiring.md#docker));
- `npx_spec_files`: the repo's `.claude/settings.json`, so the pinned SocratiCode tree is kept ([repo-knobs.md](repo-knobs.md));
- `worktree_repos`: the repos whose orphaned worktree directories may go. The template has neither half of the `worktrees` tier: to turn it on, add `worktrees` to `tiers` **and** name the repo here. Either one alone does nothing;
- `uv_clean_above_mb`: the cache size above which `uv cache clean --force` runs too;
- `alert_at_percent` and `clear_at_percent`. **The template sets 85/80:** keep `clear_at_percent` below your alert line, or delete it to take the default (below);
- `monitor_id`: leave it empty until step 3's monitor exists, then set it before the timers (step 5). While it's empty, each sensor run logs `no [sensor] monitor_id: not checking in` and checks in nothing.

Anything unknown or malformed fails the run, which is what you want: a typo is never a silent default.

## 2. The report-only run

```bash
sudo /usr/bin/python3 -I /usr/local/lib/cannobserv/disk-gc/disk-gc gc
```

It reports what each tier would remove, and removes nothing. Read it before anything else: it is the first half of the retire check, and `retire-check.sh --run-gc-report` takes it for you.

## 3. The monitor

Request one on the host's co-status tenant, in CannObserv/status#48's shape:

| Field | Value |
|---|---|
| interval | 600 |
| grace | 1800 |
| renotify | 3600 |
| `title_template` | `{{ host }} disk: {{ kind }}` |
| `body_template` | `{{ body }}` |
| enabled | `false`, until step 6 |

Check-ins carry `host`, `kind` and `body`. The faults are `low-headroom`, `gc-failed`, `gc-stale`, `unreadable` and `test`. The request goes to another repo, so it needs the owner's approval like any filing.

## 4. The key

The tenant's key (keys are per tenant, status#48) goes in `/etc/cannobserv/disk-gc/checkin.key`, owned by root, mode `0600`. The units load it with `LoadCredential=`.

## 5. The timers

```bash
sudo systemctl enable --now cannobserv-disk-gc.timer cannobserv-disk-headroom.timer
```

Enable them in the same change that retires the host's own disk tooling, once its retire check has been read ([retiring.md](retiring.md)), so the host never runs two GCs. The GC runs daily at 05:15 UTC plus up to 30 minutes, with no catch-up at boot. The sensor runs every 10 minutes.

**A host whose own probe already reports its free space** enables only the GC timer, and sets `gc_stale_hours = 0`, as the contract says. With the sensor timer off, nothing reports for the GC: `gc_stale_hours = 0` matters only when the sensor runs at all (the rehearsal, or the sensor timer enabled later), where it turns the `gc-stale` fault off. A failed GC run (`gc-failed`) then goes unreported unless the host's own probe reads the GC's `/var/lib/cannobserv-disk-gc/state.json`.

## 6. The first check-in, then the monitor, then the rehearsal

In this order, and only this one:

1. **The first check-in:** wait for a sensor run from the timer to log `checked in ok (ok): HTTP 202` ([verifying.md](verifying.md#the-gcs-and-the-sensors-runs)). **`ok` alone proves nothing:** every run logs `ok: …` before it checks in, and with no `monitor_id`, no key or no reachable co-status it then only warns (`not checking in`, `not sent`) and still exits 0. Enabling the monitor on that pages *has stopped reporting*. If the run logs `gc-stale` with "No disk GC run is recorded" instead, the config is older than `gc_stale_hours` and no GC run has written `state.json` yet (a report-only run never does): wait for the GC timer's first run, at 05:15 UTC, and the sensor run after it.
2. **Enable the monitor** on co-status.
3. **Rehearse:**

   ```bash
   sudo systemd-run --wait -p LoadCredential=checkin-key:/etc/cannobserv/disk-gc/checkin.key \
     /usr/bin/python3 -I /usr/local/lib/cannobserv/disk-gc/disk-gc sensor --test-alert
   ```

   **It is a real page.** Tell whoever gets it first. The next `ok` clears it.

## Picking the lines

- **`alert_at_percent`:** pick it as before, from the host's baseline. Where a repo's gate leaves a large tree behind, size it from the baseline **plus** one gate's basetemp ([repo-knobs.md](repo-knobs.md#pytest-basetemps)).
- **`clear_at_percent`:** `low-headroom` alerts at the alert line and clears only at or below the clear line; between the two it keeps the previous state. Without the key, it is `alert_at_percent − 5`, floored at 0, so a config from VERSION 1 needs no edit. **The template sets 85/80:** keep `clear_at_percent` below your alert line, or delete it to take the default. A clear line at or above the alert line fails at config load, so a template copied with `alert_at_percent = 80` (co-provisioner's line) and its `clear_at_percent = 80` left in refuses.
- **A "prove it fires" test** that lowers the alert line must lower or remove any explicit `clear_at_percent` too, or the config refuses. A change to either line judges the next reading afresh, so putting the lines back clears the test's hold on the next run.
- The hold lives in `/var/lib/cannobserv-disk-gc/sensor.json`, beside the GC's `state.json`. A missing or unrecognised file reads as not held. No script here touches either.

## The cadence

The timer's quiet window is the default. A host that changes it does so with a drop-in on `OnCalendar=`, and then:

1. **installs the timer change first,**
2. **then** shortens the monitor's interval and renotify (CannObserv/status#60).

The reverse order pages *has stopped reporting* on the monitor's next sweep. **Don't move the GC to weekly:** VS Code shipped two ~640M server builds in one week on power-map (10-21 and 10-23), and its weekly prune fell behind, `/` going from 71% to 85% before Sunday.
