#!/usr/bin/env bash
set -euo pipefail

# Source project env file if present (provides ANTHROPIC_API_KEY etc.)
if [[ -f env ]]; then
  set -a
  source env
  set +a
fi

source .venv/bin/activate
exec pytest tests/integration/ -v -m integration
