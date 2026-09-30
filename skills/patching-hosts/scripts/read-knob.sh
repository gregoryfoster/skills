#!/usr/bin/env bash
# read-knob.sh — resolve .skills/patching-hosts for one host and print it as JSON.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash read-knob.sh [--config FILE] [--host NAME] [--today YYYY-MM-DD]

Reads the patching-hosts knob, applies the global lines and the [host <glob>]
sections that match this host, and prints what results as one JSON object on
stdout. Read-only: it runs no command the knob names.

Options:
  --config FILE   the knob (default: .skills/patching-hosts at the repo root,
                  or in the current directory outside a repo)
  --host NAME     the host whose sections apply (default: `hostname`)
  --today DATE    the date exceptions are checked against (default: today, UTC)
  -h, --help      show this help

Output keys: knob, host, sections, class, posture, report_only,
report_only_reasons, window, quiet, inflight, health, restarter, service,
backup, caller, datastore, hold, owner, image_owner, origin, exception,
records, findings. Every value from the knob carries its line number; a
default carries line null. The grammar: references/knob.md.

A malformed line, an expired exception or an ambiguous section is a finding
in the output, not an error. A malformed line also makes the host report-only.

Exit codes:
  0  resolved; read findings and report_only
  2  usage error, an unreadable knob, or the library missing
USAGE
}

config="" host="" today=""
while [ "$#" -gt 0 ]; do
  case $1 in
    --config) [ "$#" -ge 2 ] || { echo "ERROR --config needs a file" >&2; exit 2; }; config=$2; shift 2 ;;
    --host) [ "$#" -ge 2 ] || { echo "ERROR --host needs a name" >&2; exit 2; }; host=$2; shift 2 ;;
    --today) [ "$#" -ge 2 ] || { echo "ERROR --today needs a date" >&2; exit 2; }; today=$2; shift 2 ;;
    -h | --help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1 (see --help)" >&2; exit 2 ;;
  esac
done

# --- shared library -------------------------------------------------------
# Resolved through a symlink chain first: the skill is usually reached through
# a symlinked vendor tree, where ${BASH_SOURCE[0]}'s dirname holds no library.
_self="${BASH_SOURCE[0]}"
_n=0
while [ -L "$_self" ] && [ "$_n" -lt 10 ]; do
  _t="$(readlink "$_self" 2>/dev/null)" || break
  case "$_t" in
    /*) _self="$_t" ;;
    *) _self="$(dirname "$_self")/$_t" ;;
  esac
  _n=$((_n + 1))
done
_libdir="$(cd "$(dirname "$_self")" 2>/dev/null && pwd -P)" || _libdir=""
if [ -z "$_libdir" ] || [ ! -f "$_libdir/_knob-lib.sh" ]; then
  echo "ERROR _knob-lib.sh not found next to $_self" >&2
  exit 2
fi
# shellcheck source=_knob-lib.sh
. "$_libdir/_knob-lib.sh"

if [ -z "$config" ]; then
  config="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.skills/patching-hosts"
fi
[ -n "$host" ] || host=$(hostname)
[ -n "$today" ] || today=$(date -u +%Y-%m-%d)
_knob_is_date "$today" || { echo "ERROR --today takes YYYY-MM-DD, not $today" >&2; exit 2; }

knob_load "$config" "$host" "$today" || exit 2

# --- JSON -------------------------------------------------------------------
# Knob text holds no control character but a tab (the parser rejects the rest),
# so escaping the backslash, the quote and the tab is complete.
js() {
  local s=$1
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  s=${s//$'\t'/\\t}
  printf '"%s"' "$s"
}
js_or_null() { if [ -n "$1" ]; then js "$1"; else printf null; fi; }
num_or_null() { if [ -n "$1" ]; then printf '%s' "$1"; else printf null; fi; }
js_words() {  # space-separated words -> JSON array
  local w first=1
  local -a words=()
  [ -z "$1" ] || read -r -a words <<<"$1"
  printf '['
  for w in ${words[@]+"${words[@]}"}; do
    [ "$first" -eq 1 ] || printf ', '
    first=0
    js "$w"
  done
  printf ']'
}
js_bool() { if [ "$1" -eq 1 ]; then printf true; else printf false; fi; }

# Prints one key holding an array of objects, one record each, built by <fn>.
# A record's empty fields survive the split (US isn't whitespace), except a
# trailing one, which each builder defaults.
emit_records() {  # <key> <fn> <trailer> <records>...
  local key=$1 fn=$2 trailer=$3 rec first=1
  local -a f=()
  shift 3
  printf '  "%s": [' "$key"
  for rec in "$@"; do
    if [ "$first" -eq 1 ]; then printf '\n'; else printf ',\n'; fi
    first=0
    IFS=$KNOB_US read -r -a f <<<"$rec"
    printf '    '
    "$fn" ${f[@]+"${f[@]}"}
  done
  if [ "$first" -eq 1 ]; then printf ']%s\n' "$trailer"; else printf '\n  ]%s\n' "$trailer"; fi
}

js_list() {  # <strings>... -> JSON array
  local s first=1
  printf '['
  for s in "$@"; do
    [ "$first" -eq 1 ] || printf ', '
    first=0
    js "$s"
  done
  printf ']'
}

o_window() { printf '{"weekday": %s, "start": %s, "end": %s, "wraps": %s, "line": %s}' "$(js "$1")" "$(js "$2")" "$(js "$3")" "$(js_bool "$4")" "$5"; }
o_quiet() { printf '{"weekday": %s, "start": %s, "end": %s, "wraps": %s, "line": %s}' "$(js_or_null "$1")" "$(js "$2")" "$(js "$3")" "$(js_bool "$4")" "$5"; }
o_command() { printf '{"command": %s, "line": %s}' "$(js "$1")" "$2"; }
o_unit() { printf '{"unit": %s, "line": %s}' "$(js "$1")" "$2"; }
o_caller() { printf '{"repo": %s, "line": %s}' "$(js "$1")" "$2"; }
o_datastore() { printf '{"engine": %s, "unit": %s, "databases": %s, "line": %s}' "$(js "$1")" "$(js "$2")" "$(js_words "$3")" "$4"; }
o_hold() { printf '{"step": %s, "globs": %s, "line": %s}' "$(js "$1")" "$(js_words "$2")" "$(num_or_null "${3:-}")"; }
o_owner() { printf '{"component": %s, "repo": %s, "line": %s}' "$(js "$1")" "$(js "$2")" "$3"; }
o_origin() { printf '{"origin": %s, "policy": %s, "value": %s, "line": %s}' "$(js "$1")" "$(js "$2")" "$(js_or_null "$3")" "$4"; }
o_exception() { printf '{"what": %s, "review_by": %s, "reason": %s, "expired": %s, "line": %s}' "$(js "$1")" "$(js "$2")" "$(js "$3")" "$(js_bool "$4")" "$5"; }
o_finding() { printf '{"line": %s, "kind": %s, "message": %s}' "$(num_or_null "$1")" "$(js "$2")" "$(js "$3")"; }

printf '{\n'
printf '  "knob": {"path": %s, "present": %s},\n' "$(js "$KNOB_PATH")" "$(js_bool "$KNOB_PRESENT")"
printf '  "host": %s,\n' "$(js "$KNOB_HOST")"
printf '  "sections": %s,\n' "$(js_list ${KNOB_SECTIONS[@]+"${KNOB_SECTIONS[@]}"})"
printf '  "class": {"value": %s, "line": %s},\n' "$(js "$KNOB_CLASS")" "$(num_or_null "$KNOB_CLASS_LINE")"
printf '  "posture": {"value": %s, "line": %s},\n' "$(js "$KNOB_POSTURE")" "$(num_or_null "$KNOB_POSTURE_LINE")"
printf '  "report_only": %s,\n' "$(js_bool "$KNOB_REPORT_ONLY")"
printf '  "report_only_reasons": %s,\n' "$(js_list ${KNOB_REPORT_ONLY_WHY[@]+"${KNOB_REPORT_ONLY_WHY[@]}"})"
emit_records window o_window , ${KNOB_WINDOW[@]+"${KNOB_WINDOW[@]}"}
emit_records quiet o_quiet , ${KNOB_QUIET[@]+"${KNOB_QUIET[@]}"}
emit_records inflight o_command , ${KNOB_INFLIGHT[@]+"${KNOB_INFLIGHT[@]}"}
emit_records health o_command , ${KNOB_HEALTH[@]+"${KNOB_HEALTH[@]}"}
emit_records restarter o_unit , ${KNOB_RESTARTER[@]+"${KNOB_RESTARTER[@]}"}
emit_records service o_unit , ${KNOB_SERVICE[@]+"${KNOB_SERVICE[@]}"}
emit_records backup o_unit , ${KNOB_BACKUP[@]+"${KNOB_BACKUP[@]}"}
emit_records caller o_caller , ${KNOB_CALLER[@]+"${KNOB_CALLER[@]}"}
emit_records datastore o_datastore , ${KNOB_DATASTORE[@]+"${KNOB_DATASTORE[@]}"}
emit_records hold o_hold , ${KNOB_HOLD[@]+"${KNOB_HOLD[@]}"}
emit_records owner o_owner , ${KNOB_OWNER[@]+"${KNOB_OWNER[@]}"}
printf '  "image_owner": {"value": %s, "line": %s},\n' "$(js_or_null "$KNOB_IMAGE_OWNER")" "$(num_or_null "$KNOB_IMAGE_OWNER_LINE")"
emit_records origin o_origin , ${KNOB_ORIGIN[@]+"${KNOB_ORIGIN[@]}"}
emit_records exception o_exception , ${KNOB_EXCEPTION[@]+"${KNOB_EXCEPTION[@]}"}
printf '  "records": {"value": %s, "line": %s},\n' "$(js_or_null "$KNOB_RECORDS")" "$(num_or_null "$KNOB_RECORDS_LINE")"
emit_records findings o_finding "" ${KNOB_FINDING[@]+"${KNOB_FINDING[@]}"}
printf '}\n'
