#!/usr/bin/env bash
# pre-ship.sh (Python/Click variant)
# Runs lint, import check, and tests. Exits non-zero on any failure.
# Detects the git project root automatically; safe to invoke from any directory.
#
# Import target resolution is delegated to detect-import-targets.sh
# (shared with gather-context.sh). Test-location resolution prefers a
# top-level tests/ directory, falling back to pyproject.toml
# [tool.pytest.ini_options].testpaths.
#
# Stamp prefix auto-derived from $(basename "$(git rev-parse --show-toplevel)"),
# so a single canonical pre-ship.sh works across every consumer without per-
# project substitution.
#
# Usage: bash scripts/pre-ship.sh [--help]
set -euo pipefail

# Capture the script's own directory *before* any cd, so helper lookups
# resolve correctly regardless of invocation cwd.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash scripts/pre-ship.sh"
  echo ""
  echo "Runs 'uv run ruff check .', an import check (auto-detected from"
  echo "pyproject.toml or .skills/import-targets via detect-import-targets.sh),"
  echo "and 'uv run pytest' (auto-discovers tests/ or pyproject.toml"
  echo "[tool.pytest.ini_options].testpaths). Exits non-zero on any failure."
  echo "Must pass before committing or pushing."
  echo ""
  echo "Exit codes:"
  echo "  0  All checks passed"
  echo "  1  Lint, import, or test failure"
  echo "  2  uv not installed"
  echo ""
  echo "Skips pytest when HEAD hasn't changed AND working tree is clean (per-SHA stamp)."
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv not installed. This variant is for uv-managed Python projects." >&2
  exit 2
fi

echo "=== Lint (ruff) ==="
uv run ruff check .

# --- Import check ------------------------------------------------------------
# Resolution handled by detect-import-targets.sh (shared with gather-context.sh).

echo ""
echo "=== Import check ==="
IMPORT_TARGETS=()
while IFS= read -r pkg; do
  [[ -n "$pkg" ]] && IMPORT_TARGETS+=("$pkg")
done < <(bash "$SCRIPT_DIR/detect-import-targets.sh")

if [[ ${#IMPORT_TARGETS[@]} -eq 0 ]]; then
  echo "No import target detected (no .skills/import-targets and no [project] name in pyproject.toml). Skipping."
else
  for pkg in "${IMPORT_TARGETS[@]}"; do
    echo "--- import $pkg ---"
    uv run python -c "import $pkg"
  done
fi

# --- Tests -------------------------------------------------------------------
# Per-SHA stamp: skip pytest if HEAD hasn't changed AND working tree is clean.
# A missing test suite is acceptable — shared libraries may not have one;
# ruff + import-check still gate the ship.
#
# Test-location resolution:
#   1. top-level tests/ (single dir)
#   2. every entry in pyproject.toml [tool.pytest.ini_options].testpaths
# Projects that nest tests elsewhere (e.g., src/<pkg>/tests/) should set
# testpaths in pyproject.toml so this script discovers them.

echo ""
echo "=== Tests (Python) ==="

TEST_DIRS=()
if [[ -d tests ]]; then
  TEST_DIRS=("tests/")
elif [[ -f pyproject.toml ]]; then
  while IFS= read -r path; do
    [[ -n "$path" && -d "$path" ]] && TEST_DIRS+=("$path/")
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
    print(f'detect-testpaths: {e}', file=sys.stderr)
" || true)
fi

if [[ ${#TEST_DIRS[@]} -eq 0 ]]; then
  echo "No tests directory found (checked tests/ and pyproject.toml [tool.pytest.ini_options].testpaths). Skipping pytest. (This is acceptable for shared libraries without a suite.)"
else
  CURRENT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
  STAMP_PREFIX="$(basename "$PROJECT_ROOT")-tests-clean"
  STAMP_FILE="/tmp/${STAMP_PREFIX}-${CURRENT_SHA}"
  WORKING_TREE_DIRTY=$(git status --porcelain 2>/dev/null \
    | grep -v '^??' \
    || true)

  if [[ -f "$STAMP_FILE" && -z "$WORKING_TREE_DIRTY" ]]; then
    echo "Test suite already passed for commit ${CURRENT_SHA:0:7} with a clean working tree — skipping."
  else
    # Exit code 5 = no tests collected (acceptable on an empty suite).
    uv run pytest "${TEST_DIRS[@]}" -v || { EC=$?; [ $EC -eq 5 ] || exit $EC; }
    if [[ -z "$WORKING_TREE_DIRTY" ]]; then
      touch "$STAMP_FILE"
    fi
  fi
fi

echo ""
echo "Pre-ship checks passed."
