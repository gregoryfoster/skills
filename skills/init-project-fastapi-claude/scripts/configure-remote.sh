#!/usr/bin/env bash
# configure-remote.sh <project-name> <github-org>
# Adds an SSH host alias for the deploy key and sets the git remote.
#
# Usage: bash skills/init-project-fastapi/scripts/configure-remote.sh <project-name> <github-org>
set -euo pipefail

if [[ "${1:-}" == "--help" || $# -lt 2 ]]; then
  echo "Usage: bash skills/init-project-fastapi/scripts/configure-remote.sh <project-name> <github-org>"
  echo ""
  echo "Adds ~/.ssh/config entry for github-<project-name> and sets git remote to use it."
  exit 0
fi

PROJECT_NAME="$1"
GITHUB_ORG="$2"
KEY_PATH="$HOME/.ssh/${PROJECT_NAME}_deploy_key"
HOST_ALIAS="github-${PROJECT_NAME}"

# Add SSH host alias if not already present
if ! grep -q "Host ${HOST_ALIAS}" "$HOME/.ssh/config" 2>/dev/null; then
  mkdir -p "$HOME/.ssh"
  chmod 700 "$HOME/.ssh"
  cat >> "$HOME/.ssh/config" << EOF

Host ${HOST_ALIAS}
  HostName github.com
  User git
  IdentityFile ${KEY_PATH}
  IdentitiesOnly yes
EOF
  chmod 600 "$HOME/.ssh/config"
  echo "Added SSH host alias: ${HOST_ALIAS}"
else
  echo "SSH host alias ${HOST_ALIAS} already exists — skipping."
fi

# Set git remote
git remote set-url origin "git@${HOST_ALIAS}:${GITHUB_ORG}/${PROJECT_NAME}.git"
echo "Git remote set to: git@${HOST_ALIAS}:${GITHUB_ORG}/${PROJECT_NAME}.git"

echo ""
echo "=== Verifying SSH connectivity ==="
ssh -o StrictHostKeyChecking=no -T "git@${HOST_ALIAS}" 2>&1 || true
