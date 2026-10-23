#!/usr/bin/env bash
# tightened-rules.sh — rank the sentences a class-C tightening rewrote by how
# likely the rewrite dropped or weakened a rule each states: a "never", a
# condition, an exception or a reason that --claims' atoms can't see.
# Advisory and opt-in: it asks TypeSafe one question per sentence, only once
# the repo opts in, and never touches the gate. The logic is in
# _tightened_rules.py beside this file (gregoryfoster/skills#442).
#
# Usage: tightened-rules.sh [CANDIDATES] [--threshold P] [--dry-run]
#        tightened-rules.sh --help    full usage, output columns, exit codes
#
# CANDIDATES is what `prove-no-loss.sh --claims --candidates FILE` wrote. Needs
# python3 (3.9+). TSV on stdout, one summary line on stderr. Exits 2 (a
# failure) and 4 (skipped) are advisory: carry on as if the pass hadn't run.
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
exec python3 -I -B "$HERE/_tightened_rules.py" "$@"
