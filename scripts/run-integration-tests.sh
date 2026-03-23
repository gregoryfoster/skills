#!/usr/bin/env bash
set -euo pipefail

# Export vars from env file if present (provides ANTHROPIC_API_KEY etc.)
if [[ -f env ]]; then
  export $(xargs < env)
fi

source .venv/bin/activate
exec pytest tests/integration/ -v -m integration
