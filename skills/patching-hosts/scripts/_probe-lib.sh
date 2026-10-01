#!/usr/bin/env bash
# _probe-lib.sh — what probe.sh reads a host through: the root it reads
# under, how it reaches root for the few readings that need it, a unit's state
# on disk, stat and date on GNU or BSD, and a small JSON builder.
# The P_* and U_* variables are this library's output; its callers read them.
# shellcheck disable=SC2034
set -euo pipefail

probe_lib_usage() {
  cat <<'USAGE'
Usage: . _probe-lib.sh    (sourced by probe.sh; running it does nothing)

The primitives probe.sh reads a host through:
  probe_init ROOT           sets P_ROOT ("" for /), P_LIVE, P_EUID, P_USER,
                            P_PRIV (root, sudo or none), P_KNOB_USER, P_NOW
                            and P_TMP, a scratch directory the caller removes
  as_root CMD...            runs CMD as root, directly or through sudo -n,
                            with LC_ALL=C; returns 126 without running it
                            when neither works
  as_user USER CMD...       runs CMD as USER, the same way
  knob_cmd CMD              runs a knob command with sh -c, never as root,
                            under timeout KNOB_CMD_TIMEOUT where timeout(1)
                            exists; 124 means it timed out
  unit_disk_state VAR UNIT  masked, masked-runtime, enabled, disabled, static
                            or not-found, read from the unit files under ROOT
  unit_show UNIT PROP...    systemctl show, setting U_<PROP> for each PROP;
                            returns 1, every U_<PROP> empty, when it can't
  file_mode VAR PATH        permission bits as four octal digits, or empty
  file_mtime VAR PATH       modification time in epoch seconds, or empty
  iso_utc VAR EPOCH         the time as 2026-09-30T12:00:00Z, or empty
  json_str VAR STRING       VAR := STRING as a JSON string
  jadd VAR KEY JSON         appends "KEY": JSON to an object body in VAR;
                            jadds, jaddsn, jaddn and jaddb take a string,
                            a string or null, a number and a 1/0 flag
  jpush VAR JSON            appends JSON to an array body in VAR; jpushs
                            takes a string

P_LIVE is 1 when ROOT/run/systemd/system exists, the test systemd itself
uses for "booted with systemd". Readings that ask a running system
(systemctl, journalctl, docker, psql, needrestart) are taken only then.
USAGE
}

case "${0##*/}" in
  _probe-lib.sh) case "${1-}" in -h | --help) probe_lib_usage; exit 0 ;; esac ;;
esac

probe_init() {  # <root>
  P_ROOT=${1%/}
  P_LIVE=0
  if [ -d "$P_ROOT/run/systemd/system" ]; then P_LIVE=1; fi
  P_EUID=$(id -u)
  P_USER=$(id -un)
  P_PRIV=none
  if [ "$P_EUID" -eq 0 ]; then
    P_PRIV=root
  elif command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    P_PRIV=sudo
  fi
  # Knob commands come from a committed file, so they never run as root
  # (knob.md): under sudo they run as the user who invoked it, and with no
  # such user they don't run.
  P_KNOB_USER=""
  if [ "$P_EUID" -ne 0 ]; then
    P_KNOB_USER=$P_USER
  elif [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then
    P_KNOB_USER=$SUDO_USER
  fi
  P_NOW=$(date +%s)
  P_TMP=$(mktemp -d "${TMPDIR:-/tmp}/probe.XXXXXX")
}

# Through sudo, LC_ALL=C is set again on the far side: sudoers' env_reset
# can drop it, and the lines the probe parses (needrestart's "Disabling Ubuntu
# mode", unattended-upgrade's "Packages that will be upgraded") are
# translated by gettext. runuser keeps the environment.
as_root() {
  case $P_PRIV in
    root) "$@" ;;
    sudo) sudo -n -- env LC_ALL=C "$@" ;;
    *) return 126 ;;
  esac
}

as_user() {  # <user> <cmd>...
  local u=$1
  shift
  if [ "$u" = "$P_USER" ]; then
    "$@"
    return
  fi
  case $P_PRIV in
    root) runuser -u "$u" -- "$@" ;;
    sudo) sudo -n -u "$u" -- env LC_ALL=C "$@" ;;
    *) return 126 ;;
  esac
}

# A knob command is bounded, so a check that hangs (a curl to a dead host)
# can't hang the probe, or a gate that waits on it.
KNOB_CMD_TIMEOUT=60
knob_cmd() {  # <command>
  local -a _kc_t=()
  if command -v timeout >/dev/null 2>&1; then _kc_t=(timeout "$KNOB_CMD_TIMEOUT"); fi
  if [ -z "$P_KNOB_USER" ]; then
    return 126
  elif [ "$P_EUID" -ne 0 ]; then
    ${_kc_t[@]+"${_kc_t[@]}"} sh -c "$1"
  else
    runuser -u "$P_KNOB_USER" -- ${_kc_t[@]+"${_kc_t[@]}"} sh -c "$1"
  fi
}

# --- units on disk ---------------------------------------------------------
# Read from the files, so the answer holds offline, in an image no systemd
# runs: a mask is a symlink to /dev/null, and an enablement is a symlink in a
# .wants or .requires directory.
unit_disk_state() {  # <var> <unit>
  local _uds_u=$2 _uds_r=$P_ROOT _uds_d _uds_f _uds_file="" _uds_tmpl=""
  for _uds_d in etc/systemd/system run/systemd/system; do
    _uds_f=$_uds_r/$_uds_d/$_uds_u
    if [ -L "$_uds_f" ] && [ "$(readlink "$_uds_f")" = /dev/null ]; then
      if [ "$_uds_d" = etc/systemd/system ]; then
        printf -v "$1" masked
      else
        printf -v "$1" masked-runtime
      fi
      return 0
    fi
  done
  for _uds_f in "$_uds_r"/etc/systemd/system/*.wants/"$_uds_u" "$_uds_r"/etc/systemd/system/*.requires/"$_uds_u"; do
    if [ -L "$_uds_f" ] || [ -e "$_uds_f" ]; then
      printf -v "$1" enabled
      return 0
    fi
  done
  case $_uds_u in *@*.*) _uds_tmpl=${_uds_u%%@*}@.${_uds_u##*.} ;; esac
  for _uds_d in etc/systemd/system run/systemd/system usr/local/lib/systemd/system usr/lib/systemd/system lib/systemd/system; do
    for _uds_f in "$_uds_r/$_uds_d/$_uds_u" ${_uds_tmpl:+"$_uds_r/$_uds_d/$_uds_tmpl"}; do
      if [ -f "$_uds_f" ]; then
        _uds_file=$_uds_f
        break 2
      fi
    done
  done
  if [ -z "$_uds_file" ]; then
    printf -v "$1" not-found
  elif grep -q '^\[Install\]' "$_uds_file" 2>/dev/null; then
    printf -v "$1" disabled
  else
    printf -v "$1" static
  fi
}

unit_show() {  # <unit> <prop>...
  local _us_u=$1 _us_p _us_line _us_k _us_out
  local -a _us_args=()
  shift
  for _us_p in "$@"; do
    printf -v "U_$_us_p" '%s' ""
    _us_args+=(-p "$_us_p")
  done
  if [ "$P_LIVE" -ne 1 ] || ! command -v systemctl >/dev/null 2>&1; then
    return 1
  fi
  _us_out=$(systemctl show --timestamp=unix "${_us_args[@]}" -- "$_us_u" 2>/dev/null) || return 1
  while IFS= read -r _us_line; do
    _us_k=${_us_line%%=*}
    case " $* " in *" $_us_k "*) printf -v "U_$_us_k" '%s' "${_us_line#*=}" ;; esac
  done <<<"$_us_out"
}

# --- GNU or BSD --------------------------------------------------------------
# GNU first: `stat -c` is an illegal option on BSD, and on GNU `stat -f`
# means the filesystem, not the file (preflight.sh's pattern).
file_mode() {  # <var> <path>
  local _fm
  _fm=$(stat -c %a "$2" 2>/dev/null || stat -f %Lp "$2" 2>/dev/null) || _fm=""
  case $_fm in
    '' | *[!0-7]*) printf -v "$1" '%s' "" ;;
    *) printf -v "$1" '%04d' "$((10#$_fm))" ;;
  esac
}

file_mtime() {  # <var> <path>
  local _ft
  _ft=$(stat -c %Y "$2" 2>/dev/null || stat -f %m "$2" 2>/dev/null) || _ft=""
  case $_ft in '' | *[!0-9]*) _ft="" ;; esac
  printf -v "$1" '%s' "$_ft"
}

iso_utc() {  # <var> <epoch>
  local _iu=""
  case $2 in
    '' | *[!0-9]*) ;;
    *) _iu=$(date -u -d "@$2" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null ||
      date -u -r "$2" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null) || _iu="" ;;
  esac
  printf -v "$1" '%s' "$_iu"
}

is_int() {
  local re='^-?[0-9]+$'
  [[ ${1-} =~ $re ]]
}

# --- JSON ----------------------------------------------------------------------
# A host's strings (a file name under /tmp, a process's argv, a unit name) can
# hold any byte. Under LC_ALL=C, every byte that isn't printable ASCII becomes
# '?': the output stays valid JSON, and no escape sequence reaches a terminal.
json_str() {  # <var> <string>
  local _js=$2
  _js=${_js//[![:print:]]/?}
  _js=${_js//\\/\\\\}
  _js=${_js//\"/\\\"}
  printf -v "$1" '"%s"' "$_js"
}

# A key is escaped like a value: some come from the host too, such as a
# third-party origin's name, which its repository chooses.
jadd() {  # <var> <key> <json>
  local _jadd_k=$2
  _jadd_k=${_jadd_k//[![:print:]]/?}
  _jadd_k=${_jadd_k//\\/\\\\}
  _jadd_k=${_jadd_k//\"/\\\"}
  if [ -n "${!1}" ]; then
    printf -v "$1" '%s, "%s": %s' "${!1}" "$_jadd_k" "$3"
  else
    printf -v "$1" '"%s": %s' "$_jadd_k" "$3"
  fi
}

jadds() {  # <var> <key> <string>
  local _ja
  json_str _ja "$3"
  jadd "$1" "$2" "$_ja"
}

jaddsn() {  # <var> <key> <string, or empty for null>
  if [ -n "$3" ]; then jadds "$1" "$2" "$3"; else jadd "$1" "$2" null; fi
}

jaddn() {  # <var> <key> <integer, or anything else for null>
  if is_int "$3"; then jadd "$1" "$2" "$3"; else jadd "$1" "$2" null; fi
}

jaddb() {  # <var> <key> <1, 0, or empty for null>
  case $3 in
    1) jadd "$1" "$2" true ;;
    0) jadd "$1" "$2" false ;;
    *) jadd "$1" "$2" null ;;
  esac
}

jpush() {  # <var> <json>
  if [ -n "${!1}" ]; then
    printf -v "$1" '%s, %s' "${!1}" "$2"
  else
    printf -v "$1" '%s' "$2"
  fi
}

jpushs() {  # <var> <string>
  local _jp
  json_str _jp "$2"
  jpush "$1" "$_jp"
}
