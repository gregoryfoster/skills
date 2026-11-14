#!/usr/bin/env bash
# deploying-releases-co-pypi: version 1
# deploying-releases-co-pypi-sha256: ff3579e022238c0b032d0a7f6ad14fdf3beb3ed787c690449ad867b2a7b788ce
#
# Run one uv command with a co-pypi access token in its environment
# (gregoryfoster/skills#632). Installed by deploying-releases' install.sh
# --co-pypi, with scripts/co_pypi_token.py; never edited here.
#
#   bash scripts/co-pypi.sh uv sync --locked --group dev   # a dev tree
#   bash scripts/co-pypi.sh uv lock                        # a pin change
#
# The token is minted by scripts/co_pypi_token.py from the co-pypi-reader key
# (CO_PYPI_KEY, else /etc/<[project].name>/co-pypi-reader.json) and given to the
# wrapped uv alone; it is never printed. The outer `uv run` starts from an
# allowlisted environment, so a loaded .env's PATs and a shell-wide
# GOOGLE_APPLICATION_CREDENTIALS reach neither uv. The two lists match
# co_pypi_token.py's ALLOWED and ALLOWED_PREFIXES, plus CO_PYPI_KEY. That
# module's own dependency is uv.lock's co-pypi group, run --frozen in this
# checkout (--project): the group comes from public PyPI, so it syncs before
# any token exists. A lock that holds no such group yet (a repo's first
# `uv lock`) can't be written without the token, so that run alone resolves
# the group's pin from PyPI, and says so. The wrapped uv runs where this was
# called from: scripts/deploy.sh calls it in a release.
set -euo pipefail

ALLOWED=(PATH HOME USER LOGNAME LANG TERM TMPDIR http_proxy https_proxy no_proxy all_proxy HTTP_PROXY HTTPS_PROXY NO_PROXY ALL_PROXY CO_PYPI_KEY)
PREFIXES=(LC_ XDG_ SSL_CERT_ UV_)

keep=()
while IFS= read -r name; do
  allowed=0
  for a in "${ALLOWED[@]}"; do [[ $name == "$a" ]] && allowed=1; done
  for p in "${PREFIXES[@]}"; do [[ $name == "$p"* ]] && allowed=1; done
  [[ $allowed == 1 ]] && keep+=("$name=${!name}")
done < <(compgen -e)

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
if grep -q '^co-pypi = \[' "$ROOT/uv.lock" 2>/dev/null; then
  group=(--project "$ROOT" --frozen --only-group co-pypi)
else
  echo "co-pypi.sh: $ROOT/uv.lock holds no co-pypi group yet, so this run resolves" \
    "google-auth from PyPI; commit the lock it writes" >&2
  group=(--no-project --with 'google-auth[requests]>=2,<3')
fi
exec env -i "${keep[@]}" uv run "${group[@]}" python "$HERE/co_pypi_token.py" "$@"
