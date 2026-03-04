#!/usr/bin/env bash
# comment-issue.sh <issue-number> <comment-body>
# Posts a comment to a GitHub issue via gh CLI.
# Usage: bash scripts/comment-issue.sh 19 "Implemented X. Commits: abc123..def456"
set -euo pipefail

ISSUE="${1:-}"
BODY="${2:-}"

if [ -z "$ISSUE" ] || [ -z "$BODY" ]; then
  echo "Error: issue number and comment body are required."
  echo "Usage: bash scripts/comment-issue.sh <number> <body>"
  exit 1
fi

gh issue comment "$ISSUE" --body "$BODY"
echo "Comment posted to issue #$ISSUE."
