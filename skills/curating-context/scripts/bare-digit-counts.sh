#!/usr/bin/env bash
# bare-digit-counts.sh — rank the bare digits check-counts.sh passed over by how
# likely each states a tally: a count of things in the repo that goes stale
# when they change, rather than a port, a status code, a version or a limit.
# Advisory and opt-in: it asks TypeSafe one question per clause, only once the
# repo opts in, and never touches the gate. The logic is in
# _bare_digit_counts.py beside this file (gregoryfoster/skills#441).
#
# Usage: bare-digit-counts.sh [CANDIDATES] [--threshold P] [--dry-run]
#        bare-digit-counts.sh --help    full usage, output columns, exit codes
#
# CANDIDATES is what `check-counts.sh --candidates FILE` wrote. Needs python3
# (3.9+). TSV on stdout, one summary line on stderr. Exits 2 (a failure) and 4
# (skipped) are advisory: carry on as if the pass hadn't run.
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
exec python3 -I -B "$HERE/_bare_digit_counts.py" "$@"
