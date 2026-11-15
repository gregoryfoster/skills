#!/usr/bin/env bash
# create-from-plan.sh — create a drafted epic's children in dependency order,
# then the epic, from a JSON plan; substitute each SUBn id across every body;
# check the epic's number against its prediction; end in epic-edit.sh
# --adopt-live --lint-all (gregoryfoster/skills#396). Children may sit in
# other repos: a cross-repo parent. All the logic is in _create_from_plan.py
# beside this file.
#
# Usage: create-from-plan.sh --repo OWNER/REPO --plan PLAN.json [--dry-run]
#                            [--state FILE] [--state-dir DIR] [--no-link-check]
#                            [--token-for OWNER/REPO=VAR]...
#        create-from-plan.sh --help    the plan's shape, the order, exit codes
#
# Exit codes as epic-edit.sh's: 0 ok, 1 usage, 2 infrastructure, 3 refused,
# 4 not confirmed; 6 created, but the closing epic-edit.sh failed. Needs python3 (3.9+)
# and an authenticated gh. JSON summary on stdout; refusals and gh's own
# stderr, whole, on stderr.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v python3 >/dev/null 2>&1 || {
  echo "ERROR python3 is required" >&2
  exit 2
}

exec python3 "$HERE/_create_from_plan.py" "$@"
