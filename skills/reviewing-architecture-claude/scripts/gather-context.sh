#!/usr/bin/env bash
# gather-context.sh
# Prints a structured architectural snapshot of the repo.
# Run from the project root.
set -euo pipefail

echo "=== Directory tree (depth 3) ==="
find . -not -path '*/.git/*' -not -path '*/__pycache__/*' \
       -not -path '*/.venv/*' -not -path '*/node_modules/*' \
       -not -path '*/.mypy_cache/*' \
  | sort | head -120

echo ""
echo "=== File sizes (lines) ==="
find . -name '*.py' -o -name '*.ts' -o -name '*.js' -o -name '*.go' -o -name '*.rb' \
  | grep -v -E '(\.venv|node_modules|__pycache__|\.git)' \
  | xargs wc -l 2>/dev/null | sort -rn | head -40

echo ""
echo "=== Dependency manifest ==="
for f in pyproject.toml package.json go.mod Gemfile requirements.txt; do
  [ -f "$f" ] && echo "--- $f ---" && cat "$f" && echo
done

echo ""
echo "=== Recent commits ==="
git log --oneline -15 2>/dev/null || true
