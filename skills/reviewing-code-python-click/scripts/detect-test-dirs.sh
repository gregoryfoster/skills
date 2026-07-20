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
# Usage: bash <SKILL_SCRIPTS>/detect-test-dirs.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash <SKILL_SCRIPTS>/detect-test-dirs.sh"
  echo ""
  echo "Emits one existing test directory per line to stdout."
  echo "Resolution: tests/ > pyproject.toml [tool.pytest.ini_options].testpaths."
  echo "Detection errors go to stderr; exits 0 with empty stdout when none found."
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

if [[ -d tests ]]; then
  echo "tests"
elif [[ -f pyproject.toml ]] && command -v uv >/dev/null 2>&1; then
  while IFS= read -r path; do
    [[ -n "$path" && -d "$path" ]] && echo "$path"
  done < <(uv run python -c "
import sys, tomllib
try:
    with open('pyproject.toml', 'rb') as f:
        data = tomllib.load(f)
    paths = data.get('tool', {}).get('pytest', {}).get('ini_options', {}).get('testpaths', [])
    if isinstance(paths, str):
        paths = paths.split()
    for p in paths:
        print(p)
except Exception as e:
    print(f'detect-test-dirs: {e}', file=sys.stderr)
" || true)
fi
