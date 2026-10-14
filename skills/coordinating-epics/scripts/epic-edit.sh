#!/usr/bin/env bash
# epic-edit.sh — edit a coordinating-epics epic body, with every check a
# coordinator thread once skipped (gregoryfoster/skills#348).
#
# It fetches the live body and refuses unless it equals the last body this
# tool wrote, apart from box ticks you name as verified. It applies named
# operations in memory, checks anchors and derived checkbox counts, and lints
# the new lines. Then it writes through `gh api`, reads the body back, and
# saves the new baseline. All the logic is in _epic_edit.py beside this file.
#
# Usage: epic-edit.sh --repo OWNER/REPO --epic N [--ops FILE|-] [--dry-run]
#                     [--accept-ticks REFS] [--adopt-live] [--account]
#                     [--no-link-check] [--state-dir DIR]
#        epic-edit.sh --help    full usage, operations and exit codes
#
# Needs python3 (3.9+) and an authenticated gh. JSON summary on stdout;
# diffs, refusals and gh's own stderr on stderr.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v python3 >/dev/null 2>&1 || {
  echo "ERROR python3 is required" >&2
  exit 2
}

exec python3 "$HERE/_epic_edit.py" "$@"
