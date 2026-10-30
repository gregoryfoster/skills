# Turning it on, per host

A first install leaves both timers off. Turning the GC on is per host, because its config, its lines and its monitor are. Each step here follows the contract's "Turning it on" ([#425's contract comment](https://github.com/gregoryfoster/skills/issues/425#issuecomment-6371095613)), with VERSION 2's changes ([release comment](https://github.com/gregoryfoster/skills/issues/425#issuecomment-6387455753)) and VERSION 3's ([#510](https://github.com/gregoryfoster/skills/issues/510): the `vscode-servers` tier only, no config key changed). Every step that changes the host needs the owner's approval, given in the host's own session.

The host's own files live in `/etc/cannobserv/disk-gc/` and never ship in the layer: `disk-gc.conf` and `checkin.key`. No script in this skill writes them.

## 1. The config

Create it from the template, owned by root and mode `0644`. `/etc/cannobserv/disk-gc/` doesn't exist on a host the image didn't make, and a plain `cp` fails there, so `install -D` creates it:

```bash
sudo install -D -m 0644 -o root -g root \
  /usr/local/lib/cannobserv/disk-gc/disk-gc.conf.example /etc/cannobserv/disk-gc/disk-gc.conf
sudoedit /etc/cannobserv/disk-gc/disk-gc.conf
```

Then set:

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

The tenant's key (keys are per tenant, status#48) goes in `/etc/cannobserv/disk-gc/checkin.key`, owned by root, mode `0600`. The units load it with `LoadCredential=`. Create the file empty, then put the key in with an editor, so it never appears in a command line or the shell's history:

```bash
sudo install -m 0600 -o root -g root /dev/null /etc/cannobserv/disk-gc/checkin.key
sudoedit /etc/cannobserv/disk-gc/checkin.key
```

## 5. The timers

```bash
sudo systemctl enable --now cannobserv-disk-gc.timer cannobserv-disk-headroom.timer
```

Enable them in the same change that retires the host's own disk tooling, once its retire check has been read ([retiring.md](retiring.md)), so the host never runs two GCs. The GC runs daily at 05:15 UTC plus up to 30 minutes, with no catch-up at boot. The sensor runs every 10 minutes.

**A host whose own probe already reports its free space** enables only the GC timer, and sets `gc_stale_hours = 0`, as the contract says. It skips steps 3, 4 and 6: no monitor, no key, no rehearsal. With the sensor timer off, nothing reports for the GC, and `gc_stale_hours = 0` matters only if the sensor ever runs (the timer enabled later, say). There it turns off **both** GC faults, `gc-stale` and `gc-failed`: the GC checks either only while `gc_stale_hours` is non-zero. **On this path a failed GC run reports nothing.** The canonical `cannobserv-disk-gc.service` has no `OnFailure=`, and `gc-failed` comes only from the sensor, so a GC that exits 1 or 2, or hits `TimeoutStartSec=1800`, run after run, leaves only `state.json` and the journal (#522). Close it one of three ways:

- **(a) A drop-in `OnFailure=`** to the host's own notifier. It lives under `/etc`, so the installed unit is untouched and MANIFEST still passes, as with an `OnCalendar=` drop-in. Then `sudo systemctl daemon-reload`:

  ```ini
  # /etc/systemd/system/cannobserv-disk-gc.service.d/on-failure.conf
  [Unit]
  OnFailure=<host-notifier>@%n.service
  ```

- **(b) The host's probe reads `/var/lib/cannobserv-disk-gc/state.json`**, which the GC writes after every `--prune` run: alert on a non-zero `exit`, and on a `finished_at` more than about 25 hours old, since a run killed at its timeout may write nothing. A host down at 05:15 misses that day's run (there's no catch-up), so a stale `finished_at` after a reboot is expected once.
- **(c) Take both timers after all,** with steps 3, 4 and 6, and set `gc_stale_hours` back to non-zero: at 0 it turns off both GC faults. The sensor's `gc-failed` and `gc-stale` then cover it.

**A host retiring tooling that had a failure net** (an `OnFailure=`, a dead-man, a probe on its output) takes this path only with (a), (b) or (c) in the same change; otherwise the retirement removes a net the host had ([retiring.md](retiring.md#what-stays-by-hand), question 4). Whether the canonical unit should ship a hook a host can wire to its own notifier is the GC owner's call (CannObserv/provisioner#61), not this skill's.

## 6. The first check-in, then the monitor, then the rehearsal

In this order, and only this one:

1. **The first check-in:** wait for a sensor run from the timer to log `checked in ok (ok): HTTP 202` ([verifying.md](verifying.md#the-gcs-and-the-sensors-runs)). **`ok` alone proves nothing:** every run logs `ok: …` before it checks in, and with no `monitor_id`, no key or no reachable co-status it then only warns (`not checking in`, `not sent`) and still exits 0. Enabling the monitor on that pages *has stopped reporting*. If the run logs `gc-stale` with "No disk GC run is recorded" instead, the config is older than `gc_stale_hours` and no GC run has written `state.json` yet (a report-only run never does): wait for the GC timer's first run, at 05:15 UTC, and the sensor run after it.
2. **Enable the monitor** on co-status.
3. **Rehearse:**

   ```bash
   sudo systemd-run --wait --collect --pipe -u cannobserv-disk-rehearsal \
     -p LoadCredential=checkin-key:/etc/cannobserv/disk-gc/checkin.key \
     /usr/bin/python3 -I /usr/local/lib/cannobserv/disk-gc/disk-gc sensor --test-alert
   ```

   **It is a real page.** Tell whoever gets it first. The next `ok` clears it.

   **It exits 3, like any alert,** so `systemd-run` reports a failure: that's expected. Success is the line `checked in alert (test): HTTP 202` (`--pipe` shows it, and so does `sudo journalctl -u cannobserv-disk-rehearsal`). `check-in alert (test) not sent` means no page went out. `--collect` unloads the unit afterwards, so the expected failure isn't left in `systemctl --failed`.

## Picking the lines

- **`alert_at_percent`:** pick it as before, from the host's baseline. Where a repo's gate leaves a large tree behind, size it from the baseline **plus** one gate's basetemp ([repo-knobs.md](repo-knobs.md#pytest-basetemps)).
- **`clear_at_percent`:** `low-headroom` alerts at the alert line and clears only at or below the clear line; between the two it keeps the previous state. Without the key, it is `alert_at_percent − 5`, floored at 0, so a config from VERSION 1 needs no edit. **The template sets 85/80:** keep `clear_at_percent` below your alert line, or delete it to take the default. A clear line at or above the alert line fails at config load, so a template copied with `alert_at_percent = 80` and its `clear_at_percent = 80` left in refuses.
- **patching-hosts reads `[sensor] alert_at_percent` and `mount` as a floor** (#390). A patch run refuses a step whose download and install growth would take `[sensor] mount` to `alert_at_percent` or past it, and a config it can't parse stops the run, as it stops the GC.
- **A "prove it fires" test** that lowers the alert line must lower or remove any explicit `clear_at_percent` too, or the config refuses. A change to either line judges the next reading afresh, so putting the lines back clears the test's hold on the next run.
- The hold lives in `/var/lib/cannobserv-disk-gc/sensor.json`, beside the GC's `state.json`. A missing or unrecognised file reads as not held. No script here touches either.

## The cadence

The timer's quiet window is the default. A host that changes it does so with a drop-in on `OnCalendar=`, and then:

1. **installs the timer change first,**
2. **then** shortens the monitor's interval and renotify (CannObserv/status#60).

The reverse order pages *has stopped reporting* on the monitor's next sweep. **Don't move the GC to weekly:** VS Code shipped two ~640M server builds in one week on power-map (10-21 and 10-23), and its weekly prune fell behind, `/` going from 71% to 85% before Sunday.
