#!/usr/bin/env bash
# pre-ship.sh (Python/Click variant)
# Runs lint, import check, and tests. Exits non-zero on any failure.
# Detects the git project root automatically; safe to invoke from any directory.
#
# Import target auto-detection: reads `[project] name` from pyproject.toml
# via tomllib (Python 3.11+), normalizes hyphens to underscores. If the
# heuristic picks the wrong package, commit a .skills/import-targets file
# at the repo root (one package per line) — the script consumes it instead.
#
# Stamp prefix auto-derived from $(basename "$(git rev-parse --show-toplevel)"),
# so a single canonical pre-ship.sh works across every consumer without per-
# project substitution.
#
# Usage: bash scripts/pre-ship.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash scripts/pre-ship.sh"
  echo ""
  echo "Runs 'uv run ruff check .', an import check (auto-detected from"
  echo "pyproject.toml or .skills/import-targets), and 'uv run pytest tests/'"
  echo "(only if a tests/ directory exists). Exits non-zero on any failure."
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
done < <(bash "$(dirname "$0")/detect-import-targets.sh")

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
#   1. top-level tests/
#   2. first entry in pyproject.toml [tool.pytest.ini_options].testpaths
# Projects that nest tests elsewhere (e.g., src/<pkg>/tests/) should set
# testpaths in pyproject.toml so this script discovers them.

echo ""
echo "=== Tests (Python) ==="

TESTS_DIR=""
if [[ -d tests ]]; then
  TESTS_DIR="tests"
elif [[ -f pyproject.toml ]]; then
  CANDIDATE=$(uv run python -c "
import sys, tomllib
try:
    with open('pyproject.toml', 'rb') as f:
        data = tomllib.load(f)
    paths = data.get('tool', {}).get('pytest', {}).get('ini_options', {}).get('testpaths', [])
    if isinstance(paths, str):
        paths = paths.split()
    if paths:
        print(paths[0])
except Exception as e:
    print(f'detect-testpaths: {e}', file=sys.stderr)
" || true)
  if [[ -n "$CANDIDATE" && -d "$CANDIDATE" ]]; then
    TESTS_DIR="$CANDIDATE"
  fi
fi

if [[ -z "$TESTS_DIR" ]]; then
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
    uv run pytest "$TESTS_DIR/" -v || { EC=$?; [ $EC -eq 5 ] || exit $EC; }
    if [[ -z "$WORKING_TREE_DIRTY" ]]; then
      touch "$STAMP_FILE"
    fi
  fi
fi

echo ""
echo "Pre-ship checks passed."
