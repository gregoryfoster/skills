#!/usr/bin/env bash
# gather-context.sh
# Prints a structured architectural snapshot of the repo.
# Detects the git project root automatically; safe to invoke from any directory.
#
# Usage: bash scripts/gather-context.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash scripts/gather-context.sh"
  echo ""
  echo "Prints directory tree, source file sizes, dependency manifests, and recent commits."
  echo "Automatically resolves the git project root regardless of invocation directory."
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

echo "=== Project root ==="
echo "$PROJECT_ROOT"

echo ""
echo "=== Directory tree (depth 3) ==="
find . -not -path '*/.git/*' -not -path '*/__pycache__/*' \
       -not -path '*/.venv/*' -not -path '*/node_modules/*' \
       -not -path '*/.mypy_cache/*' \
  | sort | head -120

echo ""
echo "=== File sizes (lines) ==="
find . \( -name '*.py' -o -name '*.ts' -o -name '*.js' -o -name '*.go' -o -name '*.rb' \) \
  -not -path '*/.git/*' -not -path '*/.venv/*' -not -path '*/node_modules/*' \
  -not -path '*/__pycache__/*' \
  | xargs wc -l 2>/dev/null | sort -rn | head -40

echo ""
echo "=== Dependency manifest ==="
found=0
for f in pyproject.toml package.json go.mod Gemfile requirements.txt; do
  if [ -f "$f" ]; then
    echo "--- $f ---"
    cat "$f"
    echo ""
    found=1
  fi
done
[ "$found" -eq 0 ] && echo "(none found)"

echo ""
echo "=== Recent commits ==="
git log --oneline -15 2>/dev/null || true
