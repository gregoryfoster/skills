#!/usr/bin/env bash
# _probe-lib.sh — what probe.sh and the scripts that act reach a host
# through: the root they read under, how they reach root, a knob command's
# user and time limit, a unit's state on disk, stat and date on GNU or BSD,
# and a small JSON builder.
# The P_* and U_* variables are this library's output; its callers read them.
# shellcheck disable=SC2034
set -euo pipefail

probe_lib_usage() {
  cat <<'USAGE'
Usage: . _probe-lib.sh    (sourced by probe.sh, recovery-point.sh, apply.sh,
                          reboot-chain.sh, prune-plan.sh and prune.sh;
                          running it does nothing)

The primitives these scripts reach a host through:
  probe_init ROOT           sets P_ROOT ("" for /), P_LIVE, P_EUID, P_USER,
                            P_PRIV (root, sudo or none), P_KNOB_USER, P_NOW
                            and P_TMP, a scratch directory the caller removes
  as_root CMD...            runs CMD as root, directly or through sudo -n
                            (which sets LC_ALL=C again past sudo's
                            env_reset); returns 126 without running it when
                            neither works
  as_user USER CMD...       runs CMD as USER, the same way
  knob_cmd CMD              runs a knob command with sh -c, never as root,
                            under timeout KNOB_CMD_TIMEOUT where timeout(1)
                            exists, with a KILL KNOB_CMD_KILL_AFTER seconds
                            later; 124 means it timed out, and 126 that
                            there's no knob user to run it as
  have CMD                  whether CMD is on PATH
  capture VAR CMD...        VAR := CMD's stdout, CAP_RC := its status,
                            CAP_ERR := its first stderr line
  is_int VALUE              whether VALUE is an integer, - allowed
  in_words WORD LIST        whether WORD is in a space-separated LIST
  glob_match NAME GLOBS     whether NAME matches one of space-separated GLOBS
  unit_name VAR UNIT        a knob's unit, with .service when it has no suffix
  widens ENTRY              whether an unattended-upgrades origin entry takes
                            more than the security set and the release
                            pocket. UU_DISTRO_ID is the literal
                            ${distro_id}, which unattended-upgrade itself
                            reads as Ubuntu
  lane_patterns LANE        LANE_PATTERNS := the origins maintenance or
                            origin:<key> adds; 1 with LANE_WHY when it can't
  lane_conf PATTERN...      the APT_CONFIG text that adds them, on stdout
  lane_skip_conf NAME...    the APT_CONFIG text that skips those packages
  origin_names VAR KEY POLICY  VAR := |o=|names|: what a knob origin is
  origin_split KEEP SKIP NAMES SIM  the pending packages from those origins,
                            and every other one
  rss_timer FILE            TIMER := GNU time's words to record a command's
                            max RSS in FILE, or none where there's no GNU time
  rss_of VAR TEXT           VAR := the max RSS a TIMER file's TEXT holds
  APT_SIM_PHASED            the apt-get option that shows phased updates in a
                            simulation: unattended-upgrade takes them all
  unit_disk_state VAR UNIT  masked, masked-runtime, enabled, disabled, static
                            or not-found, read from the unit files under ROOT
  tmp_rule                  TMP_CLEARED := 1 when the boot empties /tmp, 0
                            when it keeps it, empty when no rule was found;
                            TMP_RULE and TMP_RULE_FILE := the rule and its
                            file, from tmpfiles' tmp.conf or tmp.mount
  unit_show UNIT PROP...    systemctl show, setting U_<PROP> for each PROP;
                            returns 1, every U_<PROP> empty, when it can't
  file_mode VAR PATH        permission bits as four octal digits, or empty
  file_mtime VAR PATH       modification time in epoch seconds, or empty
  file_owner VAR PATH       the owner's uid, or empty
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
# can't hang the probe, or a gate that waits on it. timeout waits for the
# command after its TERM, so one that ignores the TERM gets a KILL too.
KNOB_CMD_TIMEOUT=60 KNOB_CMD_KILL_AFTER=10
knob_cmd() {  # <command>
  local -a _kc_t=()
  if command -v timeout >/dev/null 2>&1; then _kc_t=(timeout -k "$KNOB_CMD_KILL_AFTER" "$KNOB_CMD_TIMEOUT"); fi
  if [ -z "$P_KNOB_USER" ]; then
    return 126
  elif [ "$P_EUID" -ne 0 ]; then
    ${_kc_t[@]+"${_kc_t[@]}"} sh -c "$1"
  else
    runuser -u "$P_KNOB_USER" -- ${_kc_t[@]+"${_kc_t[@]}"} sh -c "$1"
  fi
}

# --- shared by every script ---------------------------------------------------
have() { command -v "$1" >/dev/null 2>&1; }

capture() {  # <var> <cmd>...: VAR := its stdout; CAP_RC := its status; CAP_ERR := its first stderr line
  local _cv=$1 _co
  shift
  CAP_RC=0 CAP_ERR=""
  _co=$("$@" 2>"$P_TMP/stderr") || CAP_RC=$?
  IFS= read -r CAP_ERR <"$P_TMP/stderr" || true
  printf -v "$_cv" '%s' "$_co"
}

in_words() {  # <word> <space-separated list>
  case " $2 " in *" $1 "*) return 0 ;; esac
  return 1
}

glob_match() {  # <name> <space-separated globs>
  local _g
  local -a _gs=()
  read -r -a _gs <<<"$2" || true
  for _g in ${_gs[@]+"${_gs[@]}"}; do
    # The knob's hold globs are patterns on purpose.
    # shellcheck disable=SC2254
    case $1 in $_g) return 0 ;; esac
  done
  return 1
}

unit_name() {  # <var> <unit>: a knob's unit name, with .service when it has no suffix
  case $2 in
    *.*) printf -v "$1" '%s' "$2" ;;
    *) printf -v "$1" '%s.service' "$2" ;;
  esac
}

# unattended-upgrades' own variable, not a shell expansion.
# shellcheck disable=SC2016
UU_DISTRO_ID='${distro_id}'

# GNU time, for a command's max RSS: BSD's takes no -f. Found on PATH rather
# than at /usr/bin/time, so a test can stand in for it. Its line is keyed:
# when the command fails, GNU time writes "Command exited with non-zero
# status N" above it (noble's time 1.9, read 2026-10-01).
TIMER=()
rss_timer() {  # <file>: TIMER := the words that time a command into FILE, or none
  local _rt
  TIMER=()
  _rt=$(type -P time 2>/dev/null) || return 0
  if "$_rt" -f max_rss_kib=%M -o /dev/null true 2>/dev/null; then
    TIMER=("$_rt" -f max_rss_kib=%M -o "$1")
  fi
}

rss_of() {  # <var> <text>: VAR := the max RSS in KiB a TIMER file holds, or empty
  local _ro_l _ro=""
  while IFS= read -r _ro_l; do
    case $_ro_l in max_rss_kib=*) _ro=${_ro_l#max_rss_kib=} ;; esac
  done <<<"$2"
  is_int "$_ro" || _ro=""
  printf -v "$1" '%s' "$_ro"
}

# Whether an Allowed-Origins or Origins-Pattern entry takes more than the
# security set. The release pocket itself doesn't: Ubuntu's stock
# 50unattended-upgrades lists "${distro_id}:${distro_codename}", which never
# changes after release and is there for the dependencies.
# Only an archive names one pocket. Every Ubuntu pocket carries the
# release's codename (noble-updates' Release says "Codename: noble"), and
# unattended-upgrade matches each field with fnmatch, so a glob takes every
# pocket it matches (2.9.1's match_whitelist_string; both read 2026-10-01).
widens() {  # <entry>
  local suite
  case $1 in *-security*) return 1 ;; esac
  case $1 in
    *archive=*) suite=${1#*archive=} suite=${suite%%,*} ;;
    *=*) return 0 ;;
    *:*) suite=${1##*:} ;;
    *) return 0 ;;
  esac
  case $1 in
    "$UU_DISTRO_ID"* | Ubuntu* | *origin=Ubuntu* | *"origin=$UU_DISTRO_ID"*) ;;
    *) return 0 ;;
  esac
  case $suite in *-* | *[*?[]*) return 0 ;; esac
  return 1
}

# --- the maintenance lane --------------------------------------------------
# Its selection is Ubuntu's -updates and each origin the knob follows, added
# to the host's own unattended-upgrades origins: APT_CONFIG is read before
# apt.conf.d, and a list there adds to the host's, so its -security stays
# (unattended-upgrade 2.9.1 on noble, 2026-10-02). A pinned or held origin
# is never named. The knob names an origin by its o= field, with _ for each
# space, or by its site, which holds a dot: unattended-upgrade matches both.
# The one-origin lane, origin:<key>, takes one origin the knob follows and
# nothing else, for a security bulletin's out-of-cycle window: its pattern
# alone, with every other pending package in Package-Blacklist (lane_skip_conf).
LANE_PATTERNS=() LANE_WHY=""
lane_patterns() {  # <maintenance|origin:<key>>
  local _lp_r _lp_k _lp_want="" _lp_seen=0
  local -a _lp_f=()
  LANE_PATTERNS=() LANE_WHY=""
  case $1 in
    maintenance)
      # unattended-upgrade's own variable, which it expands; not the shell's.
      # shellcheck disable=SC2016
      LANE_PATTERNS=('o=Ubuntu,a=${distro_codename}-updates') ;;
    origin:?*) _lp_want=${1#origin:} ;;
    *)
      LANE_WHY="no lane $1: maintenance, or origin:<an origin the knob follows>"
      return 1 ;;
  esac
  for _lp_r in ${KNOB_ORIGIN[@]+"${KNOB_ORIGIN[@]}"}; do
    IFS=$KNOB_US read -r -a _lp_f <<<"$_lp_r"
    _lp_k=${_lp_f[0]}
    if [ -n "$_lp_want" ]; then
      [ "$_lp_k" = "$_lp_want" ] || continue
      _lp_seen=1
      if [ "${_lp_f[1]}" != follow ]; then
        LANE_WHY="knob line ${_lp_f[3]} ${_lp_f[1]}s the origin $_lp_k: an expedited run takes a followed origin's updates alone"
        return 1
      fi
    fi
    [ "${_lp_f[1]}" = follow ] || continue
    # A quote, a comma or a backslash would change the pattern apt reads.
    case $_lp_k in *[!A-Za-z0-9._+:~-]*)
      LANE_WHY="knob line ${_lp_f[3]}: the origin $_lp_k holds a character an unattended-upgrades pattern can't carry"
      return 1 ;;
    esac
    case $_lp_k in
      *.*) LANE_PATTERNS+=("site=$_lp_k") ;;
      *) LANE_PATTERNS+=("o=${_lp_k//_/ }") ;;
    esac
  done
  if [ -n "$_lp_want" ] && [ "$_lp_seen" -eq 0 ]; then
    LANE_WHY="the knob names no origin $_lp_want: an expedited run takes one it follows (origin $_lp_want follow)"
    return 1
  fi
}

lane_conf() {  # <pattern>...
  local _lc_p
  printf '%s\n' "// patching-hosts: the lane's origins, added to the host's own"
  printf 'Unattended-Upgrade::Origins-Pattern {\n'
  for _lc_p in "$@"; do printf '  "%s";\n' "$_lc_p"; done
  printf '};\n'
}

# unattended-upgrade matches its blacklist with re.match (2.9.1), so each
# name is anchored and its . and + escaped: libstdc++6 is a pattern otherwise.
lane_skip_conf() {  # <package>...
  local _ls_p
  printf 'Unattended-Upgrade::Package-Blacklist {\n'
  for _ls_p in "$@"; do
    _ls_p=${_ls_p//./\\.}
    printf '  "^%s$";\n' "${_ls_p//+/\\+}"
  done
  printf '};\n'
}

# The o= names a knob origin stands for, as |name|name|: the key itself, _
# for each space, or for a site, a key with a dot, each o= that
# `apt-cache policy` (POLICY, its output) lists under that site.
origin_names() {  # <var> <key> <policy output>
  local _on_l _on_v _on_o="" _on_n="|"
  local -a _on_kv=()
  case $2 in
    *.*)
      while IFS= read -r _on_l; do
        case $_on_l in
          *" release "*)
            _on_o=""
            IFS=, read -r -a _on_kv <<<"${_on_l#*release }"
            for _on_v in ${_on_kv[@]+"${_on_kv[@]}"}; do
              case $_on_v in o=*) _on_o=${_on_v#o=} ;; esac
            done ;;
          *" origin "*)
            if [ -n "$_on_o" ] && [ "${_on_l#*origin }" = "$2" ]; then
              case $_on_n in *"|$_on_o|"*) ;; *) _on_n="$_on_n$_on_o|" ;; esac
            fi
            _on_o="" ;;
        esac
      done <<<"$3" ;;
    *) _on_n="|${2//_/ }|" ;;
  esac
  printf -v "$1" '%s' "$_on_n"
}

# Each pending package from those origins, and every other one. An Inst line
# of `apt-get -s dist-upgrade` (SIM, its output) names the candidate's
# origins in its parentheses, each as <o>:<archive or site>, ", " apart:
# "Inst tailscale [1.102.2] (1.102.4 Tailscale:pkgs.tailscale.com [arm64])".
origin_split() {  # <keep var> <skip var> <|names|> <sim output>
  local _os_l _os_n _os_r _os_e _os_k="" _os_s="" _os_hit
  while IFS= read -r _os_l; do
    case $_os_l in 'Inst '*) ;; *) continue ;; esac
    _os_n=${_os_l#Inst }
    _os_n=${_os_n%% *}
    _os_r=${_os_l#*(}
    _os_r=${_os_r%)*}
    _os_r=${_os_r#* }
    _os_r=${_os_r% \[*}
    _os_hit=0
    while [ -n "$_os_r" ]; do
      _os_e=${_os_r%%, *}
      if [ "$_os_e" = "$_os_r" ]; then _os_r=""; else _os_r=${_os_r#*, }; fi
      case $3 in *"|${_os_e%%:*}|"*) _os_hit=1 ;; esac
    done
    if [ "$_os_hit" -eq 1 ]; then _os_k="$_os_k $_os_n"; else _os_s="$_os_s $_os_n"; fi
  done <<<"$4"
  printf -v "$1" '%s' "${_os_k# }"
  printf -v "$2" '%s' "${_os_s# }"
}

# --- units on disk ---------------------------------------------------------
# Read from the files, so the answer holds offline, in an image no systemd
# runs: a mask is a symlink to /dev/null or an empty unit file
# (systemd.unit(5)), and an enablement is a symlink in a .wants or .requires
# directory.
# apt's resolver defers a phased update on a machine outside its phase, so
# apt-get -s leaves it out. unattended-upgrade 2.9.1 takes it whatever the
# phase: of 40 machine ids on noble, apt-get -s took a 10%-phased -updates
# package for 3, and unattended-upgrade for all 40 (2026-10-06, #354). So a
# simulation that stands for what a lane takes shows them all.
APT_SIM_PHASED=(-o APT::Get::Always-Include-Phased-Updates=true)

unit_disk_state() {  # <var> <unit>
  local _uds_u=$2 _uds_r=$P_ROOT _uds_d _uds_f _uds_file="" _uds_tmpl=""
  for _uds_d in etc/systemd/system run/systemd/system; do
    _uds_f=$_uds_r/$_uds_d/$_uds_u
    if { [ -L "$_uds_f" ] && [ "$(readlink "$_uds_f")" = /dev/null ]; } ||
      { [ -f "$_uds_f" ] && [ ! -s "$_uds_f" ]; }; then
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

# Whether the boot empties /tmp: the first tmp.conf in tmpfiles' order, or
# an enabled tmp.mount. An image can override Ubuntu's D rule with d, which
# keeps /tmp (boldsoftware/exeuntu 120bf12, #346).
tmp_rule() {
  local _tr_f _tr_line _tr_t _tr_p _tr_m
  TMP_RULE="" TMP_RULE_FILE="" TMP_CLEARED=""
  for _tr_f in "$P_ROOT/etc/tmpfiles.d/tmp.conf" "$P_ROOT/run/tmpfiles.d/tmp.conf" "$P_ROOT/usr/lib/tmpfiles.d/tmp.conf" "$P_ROOT/lib/tmpfiles.d/tmp.conf"; do
    if [ -L "$_tr_f" ] && [ "$(readlink "$_tr_f")" = /dev/null ]; then
      TMP_RULE_FILE=${_tr_f#"$P_ROOT"} TMP_RULE=masked TMP_CLEARED=0
      break
    fi
    [ -f "$_tr_f" ] || continue
    TMP_RULE_FILE=${_tr_f#"$P_ROOT"}
    while IFS= read -r _tr_line || [ -n "$_tr_line" ]; do
      read -r _tr_t _tr_p _ <<<"$_tr_line"
      [ "$_tr_p" = /tmp ] || continue
      TMP_RULE=$_tr_line
      case $_tr_t in D | D! | Q | Q!) TMP_CLEARED=1 ;; *) TMP_CLEARED=0 ;; esac
    done <"$_tr_f"
    break
  done
  unit_disk_state _tr_m tmp.mount
  if [ "$_tr_m" = enabled ]; then TMP_CLEARED=1 TMP_RULE="tmp.mount (tmpfs)"; fi
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

file_owner() {  # <var> <path>
  local _fo
  _fo=$(stat -c %u "$2" 2>/dev/null || stat -f %u "$2" 2>/dev/null) || _fo=""
  case $_fo in '' | *[!0-9]*) _fo="" ;; esac
  printf -v "$1" '%s' "$_fo"
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
