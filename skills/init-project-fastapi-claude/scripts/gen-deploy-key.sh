#!/usr/bin/env bash
# gen-deploy-key.sh <project-name> <key-label>
# Generates an ed25519 SSH deploy key for a project.
# Prints the public key to stdout for adding to GitHub.
#
# Usage: bash skills/init-project-fastapi/scripts/gen-deploy-key.sh <project-name> <key-label>
set -euo pipefail

if [[ "${1:-}" == "--help" || $# -lt 2 ]]; then
  echo "Usage: bash skills/init-project-fastapi/scripts/gen-deploy-key.sh <project-name> <key-label>"
  echo ""
  echo "Generates an ed25519 SSH key at ~/.ssh/<project-name>_deploy_key"
  echo "and prints the public key."
  exit 0
fi

PROJECT_NAME="$1"
KEY_LABEL="$2"
KEY_PATH="$HOME/.ssh/${PROJECT_NAME}_deploy_key"

if [ -f "$KEY_PATH" ]; then
  echo "Key already exists at $KEY_PATH — skipping generation."
else
  ssh-keygen -t ed25519 -C "$KEY_LABEL" -f "$KEY_PATH" -N ""
fi

echo ""
echo "=== Public key (add to GitHub as deploy key with write access) ==="
cat "${KEY_PATH}.pub"
