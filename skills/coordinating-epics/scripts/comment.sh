#!/usr/bin/env bash
# comment.sh — lint a coordinating-epics comment (a brief, a write-back, a
# closing note) with epic-edit.sh's own rules, then post it through `gh api`
# and read it back (gregoryfoster/skills#395). --lint-file lints a body with
# no issue and writes nothing: a new epic's, before `gh issue create`. All the
# logic is in _comment.py beside this file.
#
# Usage: comment.sh --repo OWNER/REPO --issue N --body-file F [--dry-run]
#                   [--no-link-check] [--token-for OWNER/REPO=VAR]...
#        comment.sh --repo OWNER/REPO --lint-file F [--predicted N]
#                   [--no-link-check] [--token-for OWNER/REPO=VAR]...
#        comment.sh --help    full usage and exit codes
#
# Exit codes as epic-edit.sh's: 0 ok, 1 usage, 2 infrastructure, 3 refused,
# 4 not confirmed. Needs python3 (3.9+) and an authenticated gh. JSON summary
# on stdout; refusals and gh's own stderr, whole, on stderr.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v python3 >/dev/null 2>&1 || {
  echo "ERROR python3 is required" >&2
  exit 2
}

exec python3 "$HERE/_comment.py" "$@"
