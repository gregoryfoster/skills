#!/usr/bin/env bash
# scan.sh — report what changed around a coordinating-epics epic since the
# last check-in, by three cursors: numbers above the watermark, everything
# updated since the last check-in (with new comments on the epic and its
# items), and the commit range from the last verified SHA. Also lists every
# cross-repo ref the body links, with its state. Read-only on GitHub; the logic
# is in _scan.py beside this file (gregoryfoster/skills#348).
#
# Usage: scan.sh --repo OWNER/REPO --epic N [--since TS] [--watermark N]
#                [--from-sha SHA] [--git-dir DIR] [--ref REF] [--no-fetch]
#        scan.sh --help    full usage and exit codes
#
# Needs python3 (3.9+), git and an authenticated gh. JSON report on stdout,
# with warnings inside it: a git failure, git's stderr included, costs the
# commit cursor only, and commits_skipped names it. With no --ref the tip is
# origin/HEAD, else origin/<GitHub's default branch> (#411). gh failing on
# the epic, a listing or a comment read exits 2, with gh's own stderr on
# stderr; on one cross-repo ref, one PR's closing issues or the default
# branch, it is a warning with gh's whole stderr, and the exit is 0.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v python3 >/dev/null 2>&1 || {
  echo "ERROR python3 is required" >&2
  exit 2
}

exec python3 "$HERE/_scan.py" "$@"
