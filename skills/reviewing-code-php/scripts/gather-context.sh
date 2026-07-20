#!/usr/bin/env bash
# gather-context.sh (PHP variant)
# Prints a structured summary of current repo state for use during code review.
# Also runs PHP-specific checks: composer validate (root + each discovered
# composer dir under themes/ and plugins/) and php -l on changed PHP files.
#
# Exit codes:
#   0 = success
#   2 = tooling/infra failure on a gate-like discovery step (find for
#       composer.json failed, mktemp failed). Reporting-only sections
#       (git status, diff, log) intentionally degrade silently and do not
#       map to exit 2.
#
# Usage: bash <SKILL_SCRIPTS>/gather-context.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\""
  echo ""
  echo "Prints git status, staged/unstaged diffs, recent commits, changed files,"
  echo "then runs composer validate at each composer.json location and php -l on"
  echo "changed PHP files."
  echo ""
  echo "Exit codes:"
  echo "  0 = success"
  echo "  2 = tooling/infra failure (find for composer.json failed, mktemp failed)"
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

echo "=== Project root ==="
echo "$PROJECT_ROOT"

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
CHANGED=$(git diff --name-only HEAD 2>/dev/null || true)
echo "$CHANGED"
STAGED=$(git diff --name-only --staged HEAD 2>/dev/null || true)
echo "$STAGED"

# --- PHP-specific checks ------------------------------------------------------
#
# Discovery convention: gate-like discovery steps (the `find` below) harden to
# ERROR/exit 2 on tool failure so a degraded composer-dir list never silently
# narrows the review surface. Reporting-only `git ... 2>/dev/null || true` sites
# above intentionally degrade-and-continue — a missing diff stat is acceptable
# context, a missing composer dir is not.

# Tempfile scalars (not an array) for bash 3.2 + `set -u` compatibility — only
# the find step uses tempfiles in this script.
FIND_OUT=""; FIND_ERR=""
trap 'rm -f "$FIND_OUT" "$FIND_ERR"' EXIT

# Discover composer dirs: root + every themes/<name>/ or plugins/<name>/ that
# ships a composer.json. Portable across BSD/GNU find (no -printf).
COMPOSER_DIRS=()
[[ -f composer.json ]] && COMPOSER_DIRS+=(".")

# Build find paths dynamically: passing a missing dir to `find` is itself an
# error (non-zero exit + stderr), which would falsely trip the ERROR handler
# below on repos that have only themes/ or only plugins/.
FIND_PATHS=()
[[ -d themes ]] && FIND_PATHS+=(themes)
[[ -d plugins ]] && FIND_PATHS+=(plugins)
if [[ ${#FIND_PATHS[@]} -gt 0 ]]; then
  FIND_OUT=$(mktemp) || { echo "ERROR: mktemp failed (FIND_OUT)" >&2; exit 2; }
  FIND_ERR=$(mktemp) || { echo "ERROR: mktemp failed (FIND_ERR)" >&2; exit 2; }
  FIND_RC=0
  find "${FIND_PATHS[@]}" -mindepth 2 -maxdepth 2 -name composer.json \
    >"$FIND_OUT" 2>"$FIND_ERR" || FIND_RC=$?
  if [[ $FIND_RC -ne 0 ]]; then
    echo "ERROR: find for composer.json failed (exit $FIND_RC):" >&2
    cat "$FIND_ERR" >&2
    exit 2
  fi
  # `find` can exit 0 yet still write to stderr (e.g. permission-denied on a
  # subdir). Surface those without aborting — discovered dirs are still valid.
  if [[ -s "$FIND_ERR" ]]; then
    echo "WARN: find for composer.json wrote diagnostics:" >&2
    cat "$FIND_ERR" >&2
  fi
  while IFS= read -r f; do
    [[ -n "$f" ]] && COMPOSER_DIRS+=("$(dirname "$f")")
  done < "$FIND_OUT"
fi

echo ""
echo "=== composer validate ==="
if [[ ${#COMPOSER_DIRS[@]} -eq 0 ]]; then
  echo "No composer.json found. Skipping."
else
  for dir in "${COMPOSER_DIRS[@]}"; do
    echo "--- $dir ---"
    (cd "$dir" && composer validate --no-check-publish) || echo "FAIL: $dir"
  done
fi

echo ""
echo "=== php -l on changed PHP files ==="
# Lint only changed PHP files (working tree + staged), deduped.
PHP_FILES=$(printf '%s\n%s\n' "$CHANGED" "$STAGED" | grep -E '\.php$' | sort -u || true)
if [[ -z "$PHP_FILES" ]]; then
  echo "No changed PHP files."
else
  while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    [[ ! -f "$file" ]] && continue
    php -l "$file" || echo "FAIL: $file"
  done <<< "$PHP_FILES"
fi
