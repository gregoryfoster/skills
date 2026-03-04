#!/usr/bin/env bash
# check-status.sh
# Reports working tree state. Exits 0 if clean, 1 if there are uncommitted changes.
set -euo pipefail

echo "=== Branch ==="
git branch --show-current

echo ""
echo "=== Status ==="
git status --short

echo ""
echo "=== Recent commits ==="
git log --oneline -5

if [ -n "$(git status --porcelain)" ]; then
  echo ""
  echo "UNCOMMITTED CHANGES DETECTED"
  exit 1
fi

echo ""
echo "Working tree is clean."
