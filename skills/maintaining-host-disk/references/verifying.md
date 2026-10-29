# Verifying

What to read after an install, an update, turning it on, and a retirement. Read the value directly: a green status can hide a run that never happened.

## After an install or update

- The installer's JSON: `action`, `staged_version`, `removed`, and `journald_restart`. An update with an unchanged journald drop-in doesn't restart journald.
- `cd / && sha256sum --strict -c usr/local/lib/cannobserv/disk-gc/MANIFEST` passes every line. The installer runs it; run it again whenever a file under `/usr/local/lib/cannobserv/disk-gc/` is in doubt.
- `cat /usr/local/lib/cannobserv/disk-gc/VERSION` is the pin's.
- `systemctl is-enabled cannobserv-disk-gc.timer cannobserv-disk-headroom.timer` is what it was before the update: an update never changes it.

## A repo test that loads the installed GC

Load it with bytecode off. `disk-gc` has no extension, so `SourceFileLoader` writes `__pycache__/disk-gc…pyc` beside it, and `-I` doesn't stop that: as a non-root user the write fails silently, but as root it adds a file MANIFEST doesn't list (#514). Set `sys.dont_write_bytecode = True` around `exec_module` (or run the test under `python3 -B`), and assert the load leaves only `disk-gc` in its directory (CannObserv/processor `5f6cb7c`). Whether a stray file there makes a later update or `current` check refuse is untested.

## The GC's and the sensor's runs

The GC's journal lines carry sd-daemon priorities: alerts `<3>`, warnings `<4>`, `ok` `<6>`. So `journalctl -p` works for it. Read the journal **with sudo**: for a user outside `adm` and `systemd-journal`, `journalctl` prints `-- No entries --` and exits 0, which reads exactly like "no alerts":

```bash
sudo journalctl -u cannobserv-disk-headroom.service -p err --since -1d     # alerts
sudo journalctl -u cannobserv-disk-gc.service -p warning --since -1d       # warnings and worse
systemctl list-timers 'cannobserv-disk-*'                             # next and last runs
```

A healthy sensor run reads like `ok: <host>: / is 48% used, 12.2G available (alert at 80%, clears at 75%)`, then `checked in ok (ok): HTTP 202`. The second line is the one that counts: `ok:` is logged before the check-in, which with no `monitor_id`, no key or no reachable co-status only warns (`not checking in`, `not sent`) while the unit still succeeds. The first `ok` after a hold says `recovered: alerting since <time>`. Each held run checks in `low-headroom` again and exits 3, so a monitor's *missing* means what it did before. `low-headroom`, held or not, takes precedence over `gc-failed` and `gc-stale`.

## A host's own scripts

**Don't trust `journalctl -p` on a script the skill retires or keeps.** journald files a script's plain stderr at `info`, so `-p err` finds nothing even when it fired: power-map's guard fired 8 times in a week that `-p err` counted none (CannObserv/power-map#665). For those:

- grep the message text: `sudo journalctl -u <unit> --since -7d | grep -c '<its alert text>'`; or
- first check that the script emits `<N>` prefixes when `$JOURNAL_STREAM` is set (power-map#690 shows the ~20-line stdlib pattern).

## After a retirement

- `retire-check.sh` run again finds nothing for the retired entry, and `canonical.timers` reads `enabled` where it should.
- The first GC run after it: what it removed, from its journal, against what the old tool used to. A day's growth the old tool caught and the GC doesn't is the retire check's checklist answered wrong; reopen it.
- `df -h /` the next morning, against the line.
