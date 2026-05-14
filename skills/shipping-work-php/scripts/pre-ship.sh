#!/usr/bin/env bash
# pre-ship.sh (PHP variant)
# Pre-ship gate for PHP/WordPress/Bedrock/Sage 11 monorepos:
#   1. composer validate --no-check-publish at root + every discovered
#      composer dir under themes/ and plugins/
#   2. php -l on ALL tracked PHP files (comprehensive — pre-ship cardinality
#      differs from gather-context, which lints only changed files).
#      Parallelized via xargs -P; override worker count with PRE_SHIP_PHP_LINT_JOBS
#      (default: 4).
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
  echo "PHP file (parallel; PRE_SHIP_PHP_LINT_JOBS=N to tune, default 4), and"
  echo "'composer test' if defined. Fails fast on any error."
  echo ""
  echo "Exit codes:"
  echo "  0 = pass"
  echo "  1 = check failure (composer validate, php -l, or composer test)"
  echo "  2 = tooling/infra failure (composer missing, git ls-files failed,"
  echo "      mktemp failed)"
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel)
cd "$PROJECT_ROOT"

if ! command -v composer >/dev/null; then
  echo "ERROR: composer not installed. This variant is for Composer-managed repos." >&2
  exit 2
fi

FAIL=0
JOBS_DEFAULT=4

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

# Run git to a tempfile so its exit code is observable — process substitution
# hides the producer's status. Tempfile also preserves NUL separators.
TRACKED_PHP=()
LS_OUT=""; LS_ERR=""
trap 'rm -f "$LS_OUT" "$LS_ERR"' EXIT  # set before mktemps; rm -f "" is a no-op
LS_OUT=$(mktemp) || { echo "ERROR: mktemp failed (LS_OUT)" >&2; exit 2; }
LS_ERR=$(mktemp) || { echo "ERROR: mktemp failed (LS_ERR)" >&2; exit 2; }

LS_RC=0
git ls-files -z '*.php' >"$LS_OUT" 2>"$LS_ERR" || LS_RC=$?
if [[ $LS_RC -ne 0 ]]; then
  echo "ERROR: git ls-files failed (exit $LS_RC): $(cat "$LS_ERR")" >&2
  exit 2
fi

while IFS= read -r -d '' f; do TRACKED_PHP+=("$f"); done < "$LS_OUT"

echo ""
if [[ ${#TRACKED_PHP[@]} -eq 0 ]]; then
  echo "=== php -l (all tracked PHP files) ==="
  echo "No tracked PHP files."
else
  JOBS="${PRE_SHIP_PHP_LINT_JOBS:-$JOBS_DEFAULT}"
  if ! [[ "$JOBS" =~ ^[1-9][0-9]*$ ]]; then
    echo "WARN: PRE_SHIP_PHP_LINT_JOBS='$JOBS' invalid (expected positive integer); using $JOBS_DEFAULT." >&2
    JOBS=$JOBS_DEFAULT
  fi
  echo "=== php -l (all tracked PHP files, ${JOBS} parallel workers) ==="
  # xargs returns 123 if any worker exits 1-125; we map that to FAIL=1 and let
  # php -l's stderr (multi-line syntax errors) flow through to the user.
  # shellcheck disable=SC2016  # $1 is expanded by the inner bash -c, intentional
  if ! printf '%s\0' "${TRACKED_PHP[@]}" | xargs -0 -P "$JOBS" -I {} \
      bash -c '[[ -f "$1" ]] || exit 0; php -l "$1" >/dev/null || { echo "FAIL: php -l $1" >&2; exit 1; }' _ {}; then
    FAIL=1
  else
    echo "Lint OK."
  fi
fi

# --- test runner (optional) ---------------------------------------------------

echo ""
echo "=== composer test ==="
if [[ -f composer.json ]] && composer run-script --list 2>/dev/null | grep -qE '^[[:space:]]*test[[:space:]]'; then
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
