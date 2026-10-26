#!/usr/bin/env bash
# _manifest-lib.sh — what install-disk-gc.sh and remove-disk-gc.sh share:
# reading a MANIFEST strictly, the paths it may name, systemctl, and JSON.
# Sourced; running it does nothing. M_PATHS, M_HASHES and REFUSED are its
# output.
# shellcheck disable=SC2034
set -euo pipefail

manifest_lib_usage() {
  cat <<'USAGE'
Usage: . _manifest-lib.sh    (sourced by install-disk-gc.sh and
                             remove-disk-gc.sh; running it does nothing)

  read_manifest FILE WHAT   M_PATHS and M_HASHES := FILE's lines, in order;
                            a line that isn't sha256sum's format, or a path
                            outside usr/local/lib/, refuses as WHAT's
  safe_rel PATH             whether PATH is relative, under usr/local/lib/,
                            of [A-Za-z0-9._+@/-] only, with no '..', '.'
                            or empty component and no .wh. whiteout
  no_symlink_under ROOT P   refuses when P, or a directory between ROOT and
                            it, is a symlink
  hash_of FILE              FILE's sha256 hex, or "absent"
  refuse WHY                add WHY to REFUSED
  json_str S / json_list    a JSON string; a JSON array of the arguments
  run_systemctl ARGS...     ARGS to $SYSTEMCTL, when RUN_SYSTEMCTL is 1;
                            each call is added to SYSTEMCTL_CALLS
USAGE
}

case "${0##*/}" in
  _manifest-lib.sh) case "${1-}" in -h | --help) manifest_lib_usage; exit 0 ;; esac ;;
esac

GC_DIR=usr/local/lib/cannobserv/disk-gc
MANIFEST_REL=$GC_DIR/MANIFEST
VERSION_REL=$GC_DIR/VERSION
JOURNALD_DIR=usr/local/lib/systemd/journald.conf.d/
TIMERS="cannobserv-disk-gc.timer cannobserv-disk-headroom.timer"
REFUSED=()
SYSTEMCTL_CALLS=()

refuse() { REFUSED+=("$1"); }

safe_rel() {
  local p=$1
  case "$p" in
    usr/local/lib/?*) ;;
    *) return 1 ;;
  esac
  [[ $p =~ ^[A-Za-z0-9._+@/-]+$ ]] || return 1
  case "/$p/" in
    */../* | */./* | *//* | */.wh.*) return 1 ;;
  esac
  return 0
}

read_manifest() {
  local file=$1 what=$2 line hash path n=0 re='^([0-9a-f]{64})  (.+)$'
  M_PATHS=() M_HASHES=()
  while IFS= read -r line || [ -n "$line" ]; do
    n=$((n + 1))
    if ! [[ $line =~ $re ]]; then
      refuse "$what MANIFEST line $n is not sha256sum's format"
      return 0
    fi
    hash=${BASH_REMATCH[1]} path=${BASH_REMATCH[2]}
    if ! safe_rel "$path"; then
      refuse "$what MANIFEST lists $path, outside usr/local/lib/ or not a plain path"
      return 0
    fi
    if [ "$path" = "$MANIFEST_REL" ]; then
      refuse "$what MANIFEST lists itself"
      return 0
    fi
    M_HASHES+=("$hash")
    M_PATHS+=("$path")
  done <"$file"
  [ "$n" -gt 0 ] || refuse "$what MANIFEST lists nothing"
  return 0
}

no_symlink_under() {
  local root=$1 rel=$2 sofar=""
  local IFS=/
  local part
  for part in $rel; do
    sofar=${sofar:+$sofar/}$part
    if [ -L "$root/$sofar" ]; then
      refuse "$sofar is a symlink under the root"
      return 0
    fi
  done
  return 0
}

hash_of() {
  if [ -f "$1" ] && [ ! -L "$1" ]; then
    local h
    h=$(sha256sum "$1")
    printf '%s\n' "${h%% *}"
  else
    printf 'absent\n'
  fi
}

json_str() {
  local s=$1
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  printf '"%s"' "$s"
}

json_list() {
  local first=1 item
  printf '['
  for item in "$@"; do
    [ "$first" = 1 ] || printf ', '
    first=0
    json_str "$item"
  done
  printf ']'
}

run_systemctl() {
  SYSTEMCTL_CALLS+=("$*")
  if [ "${RUN_SYSTEMCTL:-0}" = 1 ]; then
    "$SYSTEMCTL" "$@"
  fi
}
