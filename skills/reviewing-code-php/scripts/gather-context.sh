#!/usr/bin/env bash
# gather-context.sh (PHP variant)
# Prints a structured summary of current repo state for use during code review.
# Also runs PHP-specific checks: composer validate (root + each discovered
# composer dir under themes/ and plugins/) and php -l on changed PHP files.
#
# Usage: bash scripts/gather-context.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash scripts/gather-context.sh"
  echo ""
  echo "Prints git status, staged/unstaged diffs, recent commits, changed files,"
  echo "then runs composer validate at each composer.json location and php -l on"
  echo "changed PHP files."
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

# Discover composer dirs: root + every themes/<name>/ or plugins/<name>/ that
# ships a composer.json. Portable across BSD/GNU find (no -printf).
COMPOSER_DIRS=()
[[ -f composer.json ]] && COMPOSER_DIRS+=(".")
if [[ -d themes ]] || [[ -d plugins ]]; then
  while IFS= read -r f; do
    [[ -n "$f" ]] && COMPOSER_DIRS+=("$(dirname "$f")")
  done < <(find themes plugins -mindepth 2 -maxdepth 2 -name composer.json 2>/dev/null || true)
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
