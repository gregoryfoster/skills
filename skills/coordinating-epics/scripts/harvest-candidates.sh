#!/usr/bin/env bash
# harvest-candidates.sh — rank which paragraphs of a closed child's thread bear
# on which open child of the epic, so a note reaches a child it never names.
# Named pairs (a `For #N` scope, a linked #N) come first without a call; every
# other pair gets one TypeSafe question, only once the repo opts in. Advisory
# and read-only on GitHub; the logic is in _harvest.py beside this file
# (gregoryfoster/skills#436).
#
# Usage: harvest-candidates.sh --repo OWNER/REPO --epic N --source N
#                              [--since TS] [--until TS] [--max-calls N]
#                              [--dry-run]
#        harvest-candidates.sh --help    full usage, output columns, exit codes
#
# Needs python3 (3.9+) and an authenticated gh. TSV on stdout, one summary line
# on stderr. Exits 2 (a failure) and 4 (skipped) are advisory: harvest by
# reading, as if the step hadn't run.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v python3 >/dev/null 2>&1 || {
  echo "ERROR python3 is required" >&2
  exit 2
}

# -I: a json.py in the agent's cwd can't shadow the standard library. The
# module puts its own directory back on the path for its siblings.
# -B: importing those siblings would otherwise write __pycache__/ into the
# vendored skill, and -I ignores PYTHONDONTWRITEBYTECODE.
exec python3 -I -B "$HERE/_harvest.py" "$@"
