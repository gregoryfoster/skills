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

  pick_python WHO   PY := the command that runs a helper. The helpers parse
                    YAML, so they need PyYAML: a python3 that imports it is
                    used as it is, and otherwise uv supplies it, pinned to
                    PYYAML_PIN. With neither, prints why as WHO and
                    returns 2
USAGE
}

case "${0##*/}" in
  _python.sh) case "${1-}" in -h | --help) python_lib_usage; exit 0 ;; esac ;;
esac

PYYAML_PIN="pyyaml==6.0.3"

pick_python() {
  local who=$1
  if command -v python3 >/dev/null && python3 -I -c 'import yaml' 2>/dev/null; then
    PY=(python3 -I -B)
  elif command -v uv >/dev/null; then
    PY=(uv run --no-project --quiet --with "$PYYAML_PIN" python3 -I -B)
  else
    echo "$who: needs python3 with PyYAML, or uv to supply $PYYAML_PIN" >&2
    return 2
  fi
}
