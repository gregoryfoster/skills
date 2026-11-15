#!/usr/bin/env bash
# verify-ci.sh — report CI by job on a coordinating-epics child's final SHA and
# on the tip of the default branch (gregoryfoster/skills#394): the jobs the
# push should have run, from the workflows' own path filters, each job's
# status and (once completed) conclusion, and each active workflow's latest
# run on the branch, scheduled ones included. Read-only on GitHub; the logic is
# in _verify_ci.py beside this file.
#
# Usage: verify-ci.sh --repo OWNER/REPO --sha SHA [--base SHA] [--branch B]
#                     [--wait SECONDS] [--interval SECONDS]
#                     [--token-for OWNER/REPO=VAR]...
#        verify-ci.sh --help    full usage, the verdicts and exit codes
#
# Needs an authenticated gh, and python3 3.9+ with PyYAML: a python3 that
# imports yaml is used as it is, otherwise uv supplies both, PyYAML pinned
# below (the pattern adopting-dependabot's _python.sh uses, copied, since a
# skill is self-contained). JSON report on stdout. Exit codes as scan.sh's:
# 0 report written, whatever the verdict; 1 usage; 2 gh failed, with gh's own
# stderr, whole, on stderr.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYYAML_PIN="pyyaml==6.0.3"

# The import is the check: its own error would only say yaml is missing, which
# the branch below says for it.
if command -v python3 >/dev/null 2>&1 &&
  python3 -I -c 'import sys, yaml; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
  PY=(python3 -I -B)
elif command -v uv >/dev/null 2>&1; then
  PY=(uv run --no-project --quiet --python '>=3.9' --with "$PYYAML_PIN" python3 -I -B)
else
  echo "ERROR verify-ci.sh needs python3 3.9+ with PyYAML, or uv to supply both" >&2
  exit 2
fi

exec "${PY[@]}" "$HERE/_verify_ci.py" "$@"
