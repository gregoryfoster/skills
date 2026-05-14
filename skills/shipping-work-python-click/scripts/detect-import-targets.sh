#!/usr/bin/env bash
# detect-import-targets.sh
# Resolves Python package names for the import check. Emits one name per
# line to stdout. Resolution order:
#   1. .skills/import-targets at the repo root (committed override; one
#      package per line, blank lines and `#`-comments ignored)
#   2. tomllib-parsed [project] name from pyproject.toml, with hyphens
#      normalized to underscores
#
# Detection errors are reported on stderr (uv warnings included — accept
# the noise so a broken pyproject.toml or an unusual layout doesn't fail
# silently). The script exits 0 with no stdout when nothing is found.
#
# Shared between gather-context.sh (reviewing-code-python-click) and
# pre-ship.sh (shipping-work-python-click) — review and ship must agree
# on the import target, so the resolution logic lives in one place.
#
# Usage: bash scripts/detect-import-targets.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash scripts/detect-import-targets.sh"
  echo ""
  echo "Emits one Python package name per line to stdout."
  echo "Resolution: .skills/import-targets > pyproject.toml [project] name."
  echo "Detection errors go to stderr; exits 0 with empty stdout when nothing detected."
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

if [[ -f .skills/import-targets ]]; then
  while IFS= read -r pkg; do
    [[ -z "$pkg" || "$pkg" =~ ^[[:space:]]*# ]] && continue
    echo "$pkg" | xargs
  done < .skills/import-targets
elif [[ -f pyproject.toml ]] && command -v uv >/dev/null 2>&1; then
  uv run python -c "
import sys, tomllib
try:
    with open('pyproject.toml', 'rb') as f:
        data = tomllib.load(f)
    name = data.get('project', {}).get('name', '')
    if name:
        print(name.replace('-', '_'))
except Exception as e:
    print(f'detect-import-targets: {e}', file=sys.stderr)
" || true
fi
