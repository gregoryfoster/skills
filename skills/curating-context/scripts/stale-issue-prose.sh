#!/usr/bin/env bash
# stale-issue-prose.sh — rank verify-facts.sh --issues rows by how likely the
# sentence around each reference is stale: a closed issue still called
# pending, or an open one called done. Advisory and opt-in: it asks TypeSafe
# one question per occurrence, only once the repo opts in, and never changes a
# verdict. The logic is in _stale_issue_prose.py beside this file
# (gregoryfoster/skills#438).
#
# Usage: stale-issue-prose.sh [TSV] [--repo SLUG] [--threshold P] [--dry-run]
#                             [--skip-archival]
#        stale-issue-prose.sh --help    full usage, output columns, exit codes
#
# Needs python3 (3.9+) and an authenticated gh. TSV on stdout, one summary line
# on stderr. Exits 2 (a failure) and 4 (skipped) are advisory: carry on as if
# the pass hadn't run.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v python3 >/dev/null 2>&1 || {
  echo "ERROR python3 is required" >&2
  exit 2
}

# -I: a json.py in the agent's cwd can't shadow the standard library. The
# module puts its own directory back on the path for its two siblings.
# -B: importing those siblings would otherwise write __pycache__/ into the
# vendored skill, and -I ignores PYTHONDONTWRITEBYTECODE.
exec python3 -I -B "$HERE/_stale_issue_prose.py" "$@"
