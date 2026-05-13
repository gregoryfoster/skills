#!/usr/bin/env bash
# pre-ship.sh (PHP variant)
# Pre-ship gate for PHP/WordPress/Bedrock/Sage 11 monorepos:
#   1. composer validate --no-check-publish at root + every discovered
#      composer dir under themes/ and plugins/
#   2. php -l on ALL tracked PHP files (comprehensive — pre-ship cardinality
#      differs from gather-context, which lints only changed files)
#   3. Test runner if the root composer.json defines a "test" script
#
# Exits non-zero if any check fails.
#
# Usage: bash scripts/pre-ship.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash scripts/pre-ship.sh"
  echo ""
  echo "Runs composer validate at each composer.json, php -l on every tracked"
  echo "PHP file, and 'composer test' if defined. Fails fast on any error."
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel)
cd "$PROJECT_ROOT"

FAIL=0

# --- composer validate --------------------------------------------------------

COMPOSER_DIRS=()
[[ -f composer.json ]] && COMPOSER_DIRS+=(".")
if [[ -d themes ]] || [[ -d plugins ]]; then
  while IFS= read -r f; do
    [[ -n "$f" ]] && COMPOSER_DIRS+=("$(dirname "$f")")
  done < <(find themes plugins -mindepth 2 -maxdepth 2 -name composer.json 2>/dev/null || true)
fi

echo "=== composer validate ==="
if [[ ${#COMPOSER_DIRS[@]} -eq 0 ]]; then
  echo "No composer.json found. Skipping."
else
  for dir in "${COMPOSER_DIRS[@]}"; do
    echo "--- $dir ---"
    if ! (cd "$dir" && composer validate --no-check-publish); then
      echo "FAIL: composer validate in $dir" >&2
      FAIL=1
    fi
  done
fi

# --- php -l on all tracked PHP files ------------------------------------------

echo ""
echo "=== php -l (all tracked PHP files) ==="
TRACKED_PHP=$(git ls-files '*.php' 2>/dev/null || true)
if [[ -z "$TRACKED_PHP" ]]; then
  echo "No tracked PHP files."
else
  while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    [[ ! -f "$file" ]] && continue
    if ! php -l "$file" >/dev/null; then
      echo "FAIL: php -l $file" >&2
      FAIL=1
    fi
  done <<< "$TRACKED_PHP"
  echo "Lint OK."
fi

# --- test runner (optional) ---------------------------------------------------

echo ""
echo "=== composer test ==="
if [[ -f composer.json ]] && composer run-script --list 2>/dev/null | grep -qE '^\s*test\s'; then
  if ! composer test; then
    echo "FAIL: composer test" >&2
    FAIL=1
  fi
else
  echo "No 'test' script defined in composer.json. Skipping."
fi

if [[ $FAIL -ne 0 ]]; then
  echo ""
  echo "Pre-ship checks failed." >&2
  exit 1
fi

echo ""
echo "Pre-ship checks passed."
