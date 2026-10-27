#!/usr/bin/env bash
# _python.sh — what inventory.sh and check-dependabot.sh share: picking the
# interpreter their Python helpers run under. Sourced; running it does
# nothing. PY is its output.
# PY is read by the scripts that source this, which shellcheck can't see.
# shellcheck disable=SC2034
set -euo pipefail

python_lib_usage() {
  cat <<'USAGE'
Usage: . _python.sh    (sourced by inventory.sh and check-dependabot.sh;
                       running it does nothing)

  pick_python WHO   PY := the command that runs a helper. The helpers need
                    Python 3.11+ (tomllib) and PyYAML: a python3 that
                    imports both is used as it is, and otherwise uv
                    supplies them, PyYAML pinned to PYYAML_PIN. With
                    neither, prints why as WHO and returns 2
USAGE
}

case "${0##*/}" in
  _python.sh) case "${1-}" in -h | --help) python_lib_usage; exit 0 ;; esac ;;
esac

PYYAML_PIN="pyyaml==6.0.3"

pick_python() {
  local who=$1
  # tomllib is 3.11+, so importing it is the version check.
  if command -v python3 >/dev/null && python3 -I -c 'import tomllib, yaml' 2>/dev/null; then
    PY=(python3 -I -B)
  elif command -v uv >/dev/null; then
    PY=(uv run --no-project --quiet --python '>=3.11' --with "$PYYAML_PIN" python3 -I -B)
  else
    echo "$who: needs python3 3.11+ with PyYAML, or uv to supply both" >&2
    return 2
  fi
}
