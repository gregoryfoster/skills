#!/usr/bin/env bash
# retire-check.sh — list a host's own disk tooling from #425's retire list,
# beside the canonical GC's report-only run. It only reads.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash retire-check.sh [--root DIR] [--gc-report FILE | --run-gc-report]
                            [--python CMD] [--gc-timeout SEC]

Finds what on this host runs an implementation the canonical GC replaces
(references/retiring.md has the list): a systemd service (system, or per
user from each etc/passwd home), with its drop-ins from every directory
merged as systemd merges them, its timer, or a crontab, anacrontab or
cron.<period> entry. A match is a whole word of a command (inside sh -c
too) or the unit's own name; enabled follows the wants links, and for
cron.<period>, run-parts' own rules. Then puts the GC's report-only
`gc` run beside it, so the two can be read together before anything retires.

It reads unit files, drop-ins and crontabs, and changes nothing. What it
can't do is read an arbitrary script and say what it removed that the GC
keeps: that stays the by-hand checklist in references/retiring.md, and its
JSON says which entries are by hand only.

  found       each retire-list match: repo, entry, kind (systemd or cron),
              scope (system, user, user:<name> or cron), unit, timer,
              enabled, match (the word that matched), where (file:line)
              and command
  candidates  host-local units and cron lines that look like disk tooling
              but match no entry: read each one; packaged units under lib/
              are never offered
  by_hand     retire-list entries with no fixed name to match
  canonical   whether the GC is installed, its VERSION, and each timer:
              enabled, disabled or absent
  gc_report   the report: exit, json (from --run-gc-report), lines,
              truncated and total_lines (at most 500 lines), or null
  unreadable  directories it couldn't read: run it as root
  next        what to do with it

Options:
  --root DIR        read under DIR instead of / (a scratch root, or a
                    mounted image)
  --gc-report FILE  the output of a report-only run you took:
                    sudo /usr/bin/python3 -I \
                      /usr/local/lib/cannobserv/disk-gc/disk-gc gc
  --run-gc-report   take that run here, as `<python> -I /usr/local/lib/
                    cannobserv/disk-gc/disk-gc gc --json`, and carry its
                    JSON. It removes nothing: without --prune the GC never
                    removes. Only with --root / (the GC reads the live
                    config and /proc whatever --root says), and needs root
                    to read every home. Not with --gc-report
  --gc-timeout SEC  how long that run may take (default 900); past it,
                    gc_report.exit is "timeout"
  --python CMD      the interpreter for --run-gc-report (default
                    /usr/bin/python3, the one the GC's units run); one that
                    can't be run is a usage error
  -h, --help        show this help

Every command is printed redacted, since the JSON is meant for the host's
adoption issue: NAME=value and --name value where the name says token, key,
secret, pass or auth, an Authorization header, and a URL's userinfo, path
and query (its host stays) all read <redacted>.

Output: one JSON document on stdout. Exit codes: 0 read, 2 usage (a bad
or conflicting flag, --run-gc-report off /, a report or interpreter that
can't be read or run).
USAGE
}

for a in "$@"; do
  case "$a" in -h | --help) usage; exit 0 ;; esac
done
command -v python3 >/dev/null || { echo "retire-check: needs python3 on PATH" >&2; exit 2; }
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec python3 -I -B "$HERE/_retire_scan.py" "$@"
