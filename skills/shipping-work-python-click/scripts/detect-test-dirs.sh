#!/usr/bin/env bash
# detect-test-dirs.sh
# Resolves pytest test directories. Emits one path per line, only for
# directories that exist on disk. Resolution order:
#   1. top-level tests/ (single dir; takes precedence when present)
#   2. every entry in pyproject.toml [tool.pytest.ini_options].testpaths
#
# Trailing-slash normalization is the caller's responsibility — paths
# are emitted as-given. Detection errors go to stderr.
#
# Shared between gather-context.sh (reviewing-code-python-click) and
# pre-ship.sh (shipping-work-python-click) — review and ship must agree
# on which directories contain the test suite, so the resolution logic
# lives in one place.
#
# Exit codes:
#   0  resolved (possibly to nothing — an empty answer is a valid one)
#   2  the resolver could not run. Never reported as "no test directories":
#      pre-ship.sh skips pytest on an empty list, so a silent tooling
#      failure here ships a commit having run no tests (#255).
#
# Usage: bash <SKILL_SCRIPTS>/detect-test-dirs.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\""
  echo ""
  echo "Emits one existing test directory per line to stdout."
  echo "Resolution: tests/ > pyproject.toml [tool.pytest.ini_options].testpaths."
  echo "Detection errors go to stderr; exits 0 with empty stdout when none found."
  echo ""
  echo "Exit codes:"
  echo "  0  resolved (an empty list is a valid answer)"
  echo "  2  the resolver could not run (uv failed, mktemp failed) — a"
  echo "     tooling failure must not read as 'this project has no tests'"
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

if [[ -d tests ]]; then
  echo "tests"
elif [[ -f pyproject.toml ]] && command -v uv >/dev/null 2>&1; then
  # Tempfile + scalar RC capture, not `done < <(uv run …)`: this list drives a
  # gate, so the producer's exit code has to be visible in this shell
  # (docs/STYLE.md, "Gate-script discipline"). pre-ship.sh runs pytest over
  # exactly these directories and skips it outright when the list comes back
  # empty — so a `uv` that cannot run (no venv, a resolution failure, a network
  # wall) used to ship a commit having run no tests, announcing "No tests
  # directory found" while it did it. Its caller captures this script's exit
  # code carefully; the old `|| true` defeated that from the inside (#255).
  #
  # The python snippet catches its own parse errors and still exits 0, so a
  # non-zero code here is uv itself failing — a malformed pyproject.toml stays
  # a stderr note, not a blocked ship. `import tomllib` sits INSIDE that try
  # for the same reason: on a project pinned to Python 3.10 it is a detection
  # limit, not a broken toolchain.
  TESTPATHS_OUT=$(mktemp) || { echo "detect-test-dirs: mktemp failed" >&2; exit 2; }
  trap 'rm -f "$TESTPATHS_OUT"' EXIT
  UV_RC=0
  uv run python -c "
import sys
try:
    import tomllib
    with open('pyproject.toml', 'rb') as f:
        data = tomllib.load(f)
    paths = data.get('tool', {}).get('pytest', {}).get('ini_options', {}).get('testpaths', [])
    if isinstance(paths, str):
        paths = paths.split()
    for p in paths:
        print(p)
except Exception as e:
    print(f'detect-test-dirs: {e}', file=sys.stderr)
" >"$TESTPATHS_OUT" || UV_RC=$?
  if [[ $UV_RC -ne 0 ]]; then
    echo "detect-test-dirs: uv run python failed (exit $UV_RC) reading [tool.pytest.ini_options].testpaths" >&2
    exit 2
  fi

  # `if`, not `[[ … ]] && echo`: the loop's status is its body's last command,
  # and a final entry that does not exist on disk would make the whole script
  # exit 1 under `set -e` — which the caller reports as "detect-test-dirs.sh
  # failed", a tooling error where the truth is "that directory is not there".
  while IFS= read -r path; do
    if [[ -n "$path" && -d "$path" ]]; then
      echo "$path"
    fi
  done < "$TESTPATHS_OUT"
fi
