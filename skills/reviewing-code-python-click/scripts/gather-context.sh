#!/usr/bin/env bash
# gather-context.sh (Python/Click variant)
# Prints a structured summary of current repo state for use during code review.
# Runs ruff + import-check + (if a suite exists) pytest informationally —
# failures become Phase 3 findings, not gather-context errors. Pytest is
# included in this variant (unlike the FastAPI variant) because CLI test
# suites are typically fast and the audit found existing downstream
# consumers already run them at review time.
#
# Import target resolution is delegated to detect-import-targets.sh
# (shared with pre-ship.sh). Test directory resolution is delegated to
# detect-test-dirs.sh (also shared with pre-ship.sh), so review and ship
# always agree on what to import-check and where the test suite lives.
#
# Usage: bash <SKILL_SCRIPTS>/gather-context.sh [--help]
set -euo pipefail

# Capture the script's own directory *before* any cd, so helper lookups
# resolve correctly regardless of invocation cwd.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\""
  echo ""
  echo "Prints git status, staged/unstaged diffs, recent commits, changed files,"
  echo "then runs 'uv run ruff check .', an import check (auto-detected from"
  echo "pyproject.toml or .skills/import-targets), and 'uv run pytest tests/'"
  echo "(only if a tests/ directory exists). All checks are informational —"
  echo "failures become Phase 3 findings, not gather-context errors."
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

echo "=== Project root ==="
echo "$PROJECT_ROOT"

echo ""
echo "=== Branch ==="
git branch --show-current 2>/dev/null || true

echo ""
echo "=== Git status ==="
git status --short

echo ""
echo "=== Staged diff ==="
git diff --staged --stat 2>/dev/null || true

echo ""
echo "=== Unstaged diff ==="
git diff --stat 2>/dev/null || true

echo ""
echo "=== Recent commits ==="
git log --oneline -10 2>/dev/null || true

echo ""
echo "=== Changed files (working tree vs HEAD) ==="
git diff --name-only HEAD 2>/dev/null || true
git diff --name-only --staged HEAD 2>/dev/null || true

if ! command -v uv >/dev/null 2>&1; then
  echo ""
  echo "uv not installed; skipping ruff/import/pytest. (uv is required by this variant.)"
  exit 0
fi

# --- Informational lint ------------------------------------------------------

echo ""
echo "=== ruff check (informational) ==="
uv run ruff check . 2>&1 || true

# --- Informational import check ----------------------------------------------
# Resolution handled by detect-import-targets.sh (shared with pre-ship.sh).
# Failures here are NOT gather-context errors — they become Phase 3 findings.

echo ""
echo "=== import check (informational) ==="
IMPORT_TARGETS=()
while IFS= read -r pkg; do
  [[ -n "$pkg" ]] && IMPORT_TARGETS+=("$pkg")
done < <(bash "$SCRIPT_DIR/detect-import-targets.sh")

if [[ ${#IMPORT_TARGETS[@]} -eq 0 ]]; then
  echo "No import target detected (no .skills/import-targets and no [project] name in pyproject.toml). Skipping."
else
  for pkg in "${IMPORT_TARGETS[@]}"; do
    echo "--- import $pkg ---"
    uv run python -c "import $pkg" 2>&1 || true
  done
fi

# --- Informational pytest ----------------------------------------------------
# Test directory resolution is delegated to detect-test-dirs.sh (shared
# with pre-ship.sh), so review and ship agree on test discovery. A
# missing suite is a warning, not an error (the cannobserv shared-library
# case has no test suite).

echo ""
echo "=== pytest (informational) ==="
TEST_DIRS=()
while IFS= read -r dir; do
  [[ -n "$dir" ]] && TEST_DIRS+=("${dir%/}/")
done < <(bash "$SCRIPT_DIR/detect-test-dirs.sh")

if [[ ${#TEST_DIRS[@]} -eq 0 ]]; then
  echo "No tests directory found (checked tests/ and pyproject.toml [tool.pytest.ini_options].testpaths). Skipping pytest. (This is acceptable for shared libraries without a suite.)"
else
  uv run pytest "${TEST_DIRS[@]}" 2>&1 || true
fi
