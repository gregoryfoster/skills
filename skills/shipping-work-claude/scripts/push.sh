#!/usr/bin/env bash
# push.sh
# Pushes the current branch to origin.
set -euo pipefail

BRANCH=$(git branch --show-current)
echo "Pushing $BRANCH to origin..."
git push origin "$BRANCH"
echo "Push succeeded."
