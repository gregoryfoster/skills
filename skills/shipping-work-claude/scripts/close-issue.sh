#!/usr/bin/env bash
# close-issue.sh <issue-number>
# Closes a GitHub issue via gh CLI.
# Usage: bash scripts/close-issue.sh 19
set -euo pipefail

ISSUE="${1:-}"

if [ -z "$ISSUE" ]; then
  echo "Error: issue number is required."
  echo "Usage: bash scripts/close-issue.sh <number>"
  exit 1
fi

gh issue close "$ISSUE"
echo "Issue #$ISSUE closed."
