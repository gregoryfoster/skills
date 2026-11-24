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
                            P_PRIV (root, sudo or none), P_KNOB_USER, P_NOW.
                            P_NO_SUDO=1 before it keeps a non-root P_PRIV
                            none: nothing goes through sudo (#490)
                            and P_TMP, a scratch directory the caller removes
  as_root CMD...            runs CMD as root, directly or through sudo -n
                            (which sets LC_ALL=C again past sudo's
                            env_reset); returns 126 without running it when
                            neither works
  as_user USER CMD...       runs CMD as USER, the same way
  as_reader CMD... FILE     runs CMD as the user when FILE is readable, as
                            root otherwise; 126 when neither can
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
  origin_split KEEP SKIP NAMES SIM POLICY  the pending packages from those
                            origins, and every other one
  inst_class VAR LINE POLICY  VAR := an Inst line's class, a third party's
                            keyed on its repo's o= (#695)
  rss_timer FILE            TIMER := GNU time's words to record a command's
                            max RSS in FILE, or none where there's no GNU time
  rss_of VAR TEXT           VAR := the max RSS a TIMER file's TEXT holds
  APT_SIM_PHASED            the apt-get option that shows phased updates in a
                            simulation: unattended-upgrade takes them all
  phased_of VAR POLICY NAMES  VAR := " name=N ... ", each of NAMES whose
                            candidate apt phases at N%
  phased_deferred VAR WITH WITHOUT PHASED  VAR := the phased updates apt
                            would defer here: in the simulation WITH
                            APT_SIM_PHASED, not WITHOUT it (#686)
  SPACE_FLOOR_KIB           the KiB every filesystem a patch run writes keeps
                            free, beyond what the run counts it needs
  fs_reading PATH           FS_FREE, FS_USED (KiB) and FS_MOUNT from df -Pk,
                            at PATH's nearest existing directory; 1 when unread
  step_space PKG...         SS_DOWNLOAD, SS_GROWTH, SS_PEAK (KiB) and SS_N: what
                            upgrading PKGs writes, from apt's metadata, through
                            SS_APT_GET, SS_APT_CACHE and SS_DPKGQ; 1 with SS_WHY
  disk_gc_conf              GC_STATE (absent, ok or bad), GC_ALERT, GC_MOUNT and
                            GC_WHY, from the canonical disk GC's config
  space_gate WHAT           SPACE_WHY, SPACE_KIND and SPACE_ID: where the SS_*
                            figures don't fit, or cross the GC's headroom line;
                            SPACE_JSON: what was read
  unit_disk_state VAR UNIT  masked, masked-runtime, enabled, disabled, static
                            or not-found, read from the unit files under ROOT
  tmp_rule                  TMP_CLEARED := 1 when the boot empties /tmp, 0
                            when it keeps it, empty when no rule was found;
                            TMP_RULE and TMP_RULE_FILE := the rule and its
                            file, from tmpfiles' tmp.conf or tmp.mount
  unit_show UNIT PROP...    systemctl show, setting U_<PROP> for each PROP;
                            returns 1, every U_<PROP> empty, when it can't
  redis_engine UNIT         RE_ENGINE (redis or valkey), RE_CLI and
                            RE_CHECK_RDB := the server a Redis unit runs, and
                            the client and RDB checker it takes (#706)
  redis_conf UNIT           RC_* := what a Redis unit's file, read as root,
                            and its own arguments set: port, bind, socket,
                            logfile, dir, dbfilename, save, appendonly,
                            whether an aclfile or a user line sets the users
                            (RC_ACL_WHY says which), and whether an include
                            is there
  redis_addr                RA_ARGS := the client's words for the address
                            redis_conf read (-s, or -h and -p), RA_PORT its
                            port
  redis_persistence VAR     aof, rdb, none or unknown, from redis_conf
  hold_group_versions VAR SIM
                            "<pkg>=<version>" for each pending package a hold
                            group takes, from apt-get -s dist-upgrade's SIM
  version_in VAR WORDS PKG  PKG's version in hold_group_versions' WORDS, or
                            empty
  redis_restart_check UNIT  RL_OK (1, 0, or "" unread) and RL_WHY: a clean
                            shutdown before, and a load and a ready after,
                            from Redis's logfile or its unit's journal
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
  elif [ "${P_NO_SUDO:-0}" -ne 1 ] && command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
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

# A unit file or a script can be root's alone: wslcb's health-check unit is
# 0600 (#360). So a read the user can't take is taken as root.
as_reader() {  # <cmd>... <file, the last argument>
  if [ -r "${*: -1}" ]; then "$@"; else as_root "$@"; fi
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

# Whether the last capture failed on a read-only filesystem: EROFS's C-locale
# text anywhere in its stderr, not only the first line, since pro prints a
# traceback (#501).
cap_read_only() { grep -q 'Read-only file system' "$P_TMP/stderr" 2>/dev/null; }

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

# systemd's drop-in order, journald.conf(5) and systemd.unit(5) alike: every
# *.conf across the directories given, a name in a higher-priority directory
# masking the same name lower down, then all of them applied in filename
# order, whatever directory each is in. A link to /dev/null masks and reads
# as nothing, so it's left out (#515, #484). The probe read /etc and /usr/lib
# by directory for journald, and /etc and /run for a unit's.
dropin_files() {  # <var> <directory, highest priority first>...: VAR := the files, a line each
  local _df_v=$1 _df_d _df_f _df_n _df_seen=$'\n' _df_out=""
  local -a _df_l=()
  shift
  for _df_d in "$@"; do
    for _df_f in "$_df_d"/*.conf; do
      [ -e "$_df_f" ] || [ -L "$_df_f" ] || continue
      _df_n=${_df_f##*/}
      case $_df_seen in *$'\n'"$_df_n"$'\n'*) continue ;; esac
      _df_seen="$_df_seen$_df_n"$'\n'
      [ -f "$_df_f" ] || continue
      _df_l+=("$_df_n/$_df_f")
    done
  done
  if [ "${#_df_l[@]}" -gt 0 ]; then
    # A name holds no /, so the first / ends the sort key.
    _df_out=$(printf '%s\n' "${_df_l[@]}" | LC_ALL=C sort -t/ -k1,1 | cut -d/ -f2-)
  fi
  printf -v "$_df_v" '%s' "$_df_out"
}

# Where systemd looks for a unit's files, highest priority first.
UNIT_DIRS="etc/systemd/system run/systemd/system usr/local/lib/systemd/system usr/lib/systemd/system lib/systemd/system"

unit_dropins() {  # <var> <unit> [<its template>]: VAR := its drop-ins, in systemd's order, a line each
  local _ud_d
  local -a _ud_dirs=()
  for _ud_d in $UNIT_DIRS; do
    _ud_dirs+=("$P_ROOT/$_ud_d/$2.d")
    if [ -n "${3:-}" ]; then _ud_dirs+=("$P_ROOT/$_ud_d/$3.d"); fi
  done
  dropin_files "$1" "${_ud_dirs[@]}"
}

cover_name() {  # <var> <cover>: a backup cover's unit with its suffix, and its databases kept
  local _cn
  unit_name _cn "${2%%:*}"
  case $2 in *:*) _cn="$_cn:${2#*:}" ;; esac
  printf -v "$1" '%s' "$_cn"
}

# What one backup line stands in for (CR 194, #480). A cover is a datastore
# unit a datastore line declares, or <unit>:<db>,<db>... for the databases a
# backup takes of a Postgres one, split at the first colon. A Postgres unit
# named whole, whose datastore lines name more than one database, is
# refused: a backup that dumps one of them would cover the rest silently, as
# wslcb's dumped wslcb and never wslcb_test. The recovery point, the bulk
# and the probe all read a line through this, so each refuses the same way.
# BC_COVERS := what it covers, space-separated, each a unit with its suffix
# or <unit>:<db>; BC_WHY := each reason the line can't stand in for a dump,
# and BC_WHY_DS the datastore unit each one is about.
BC_COVERS="" BC_WHY=() BC_WHY_DS=()
backup_covers() {  # <a KNOB_BACKUP record>
  local _r _t _du _dd _dl _db _eng _dbs _u _x _fix
  local -a _f=() _g=() _ts=() _ls=()
  BC_COVERS="" BC_WHY=() BC_WHY_DS=()
  IFS=$KNOB_US read -r -a _f <<<"$1"
  unit_name _u "${_f[0]}"
  read -r -a _ts <<<"${_f[1]}"
  for _t in ${_ts[@]+"${_ts[@]}"}; do
    _dl=""
    case $_t in *:*) _dl=${_t#*:} ;; esac
    unit_name _du "${_t%%:*}"
    _eng="" _dbs=""
    for _r in ${KNOB_DATASTORE[@]+"${KNOB_DATASTORE[@]}"}; do
      IFS=$KNOB_US read -r -a _g <<<"$_r"
      unit_name _dd "${_g[1]}"
      [ "$_dd" = "$_du" ] || continue
      _eng=${_g[0]}
      if [ "$_eng" = postgres ] && ! in_words "${_g[2]}" "$_dbs"; then _dbs="$_dbs ${_g[2]}"; fi
    done
    _dbs=${_dbs# }
    if [ -z "$_eng" ]; then
      BC_WHY+=("backup $_u (knob line ${_f[2]}) names $_du, which no datastore line declares")
      BC_WHY_DS+=("$_du")
    elif [ -n "$_dl" ] && [ "$_eng" != postgres ]; then
      BC_WHY+=("backup $_u (knob line ${_f[2]}) names databases on $_du, a $_eng datastore, which has none: name the unit alone")
      BC_WHY_DS+=("$_du")
    elif [ -n "$_dl" ]; then
      IFS=, read -r -a _ls <<<"$_dl"
      for _db in "${_ls[@]}"; do
        if ! in_words "$_db" "$_dbs"; then
          BC_WHY+=("backup $_u (knob line ${_f[2]}) names $_du:$_db, which no datastore postgres line declares")
          BC_WHY_DS+=("$_du")
        elif ! in_words "$_du:$_db" "$BC_COVERS"; then
          BC_COVERS="$BC_COVERS $_du:$_db"
        fi
      done
    elif [ "$_eng" = postgres ] && [ "$_dbs" != "${_dbs%% *}" ]; then
      _fix=""
      for _x in "${_ts[@]}"; do
        if [ "$_x" = "$_t" ]; then _x="$_t:${_dbs// /,}"; fi
        _fix="$_fix $_x"
      done
      BC_WHY+=("backup $_u (knob line ${_f[2]}) covers $_du, whose datastore lines name $_dbs, and doesn't say which of them it takes: one it doesn't dump would go undumped (#480). Write the line as backup ${_f[0]}$_fix, then drop each database the backup doesn't dump, and the recovery point dumps those")
      BC_WHY_DS+=("$_du")
    elif ! in_words "$_du" "$BC_COVERS"; then
      BC_COVERS="$BC_COVERS $_du"
    fi
  done
  BC_COVERS=${BC_COVERS# }
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
# releases in its parentheses, ", " apart, each by its Label: inst_origins
# maps each to <o=>:<archive or site> from apt-cache policy (POLICY, its
# output), so a Label-less repo's packages, or a PPA's whose Label isn't its
# Origin, are told apart by the o= a knob names (#695):
# "Inst tailscale [1.102.2] (1.102.4 Tailscale:pkgs.tailscale.com [arm64])".
# OS_AMBIG := each release text a pending package printed that two repos
# print alike, quoted and ", " apart: no package from it can be told to be
# the origin's (CR 2795).
OS_AMBIG=""
origin_split() {  # <keep var> <skip var> <|names|> <sim output> <policy output>
  local _os_l _os_n _os_r _os_e _os_k="" _os_s="" _os_hit
  OS_AMBIG=""
  while IFS= read -r _os_l; do
    case $_os_l in 'Inst '*) ;; *) continue ;; esac
    _os_n=${_os_l#Inst }
    _os_n=${_os_n%% *}
    inst_origins _os_r "$_os_l" "${5-}"
    if [ -n "$INST_AMBIG" ]; then
      case $OS_AMBIG in
        *"\"$INST_AMBIG\""*) ;;
        *) OS_AMBIG="$OS_AMBIG, \"$INST_AMBIG\"" ;;
      esac
    fi
    _os_hit=0
    while [ -n "$_os_r" ]; do
      _os_e=${_os_r%%, *}
      if [ "$_os_e" = "$_os_r" ]; then _os_r=""; else _os_r=${_os_r#*, }; fi
      case $3 in *"|${_os_e%%:*}|"*) _os_hit=1 ;; esac
    done
    if [ "$_os_hit" -eq 1 ]; then _os_k="$_os_k $_os_n"; else _os_s="$_os_s $_os_n"; fi
  done <<<"$4"
  OS_AMBIG=${OS_AMBIG#, }
  printf -v "$1" '%s' "${_os_k# }"
  printf -v "$2" '%s' "${_os_s# }"
}

# apt's resolver defers a phased update on a machine outside its phase, so
# apt-get -s leaves it out. unattended-upgrade 2.9.1 takes it whatever the
# phase: of 40 machine ids on noble, apt-get -s took a 10%-phased -updates
# package for 3, and unattended-upgrade for all 40 (2026-10-06, #354). So a
# simulation that stands for what a lane takes shows them all.
APT_SIM_PHASED=(-o APT::Get::Always-Include-Phased-Updates=true)

# Each package whose candidate apt phases, as " name=N ... " for N%, from
# apt-cache policy's output over NAMES: it marks the version "(phased N%)".
phased_of() {  # <var> <apt-cache policy output> <" name ... ">
  local _po_l _po_n="" _po_c="" _po_v _po_p _po_o=" "
  while IFS= read -r _po_l; do
    case $_po_l in
      [!\ ]*:) _po_n=${_po_l%:} _po_c="" ;;
      "  Candidate: "*) _po_c=${_po_l#  Candidate: } ;;
      *"(phased "*"%)")
        read -r _po_v _ <<<"${_po_l# \*\*\* }"
        if [ -n "$_po_n" ] && [ "$_po_v" = "$_po_c" ] && in_words "$_po_n" "$3"; then
          _po_p=${_po_l##*(phased }
          _po_o="$_po_o$_po_n=${_po_p%\%)} "
        fi ;;
    esac
  done <<<"$2"
  printf -v "$1" '%s' "$_po_o"
}

# The phased updates apt would defer on this machine (#686): each one the
# simulation with APT_SIM_PHASED installs and the one without it doesn't.
# Only a package PHASED names (phased_of's) can be one, so a simulation that
# printed nothing defers no other package. The Inst lines decide, never apt's
# "deferred due to phasing" header: apt lifts phasing for a package with a
# pending security update, and installs its phased version though the
# header lists it (measured, apt 2.8.3, CR 2807).
phased_deferred() {  # <var> <simulation with> <simulation without> <phased_of's>
  local _pd_k _pd_p _pd_r _pd_w=" " _pd_o=""
  while read -r _pd_k _pd_p _pd_r; do
    if [ "$_pd_k" = Inst ]; then _pd_w="$_pd_w$_pd_p "; fi
  done <<<"$3"
  while read -r _pd_k _pd_p _pd_r; do
    [ "$_pd_k" = Inst ] || continue
    case $4 in *" $_pd_p="*) ;; *) continue ;; esac
    case $_pd_w in *" $_pd_p "*) continue ;; esac
    _pd_o="$_pd_o $_pd_p"
  done <<<"$2"
  printf -v "$1" '%s' "${_pd_o# }"
}

# --- free space (#390) -----------------------------------------------------
# What a step writes, against the free space where it lands. The figures are
# apt's own, read from its metadata: each candidate's Size, less one already
# in apt's cache at that size, is the download, and its Installed-Size
# against the installed version's is the install growth. Summed, they are
# what `apt-get --assume-no` prints as "Need to get" and "After this
# operation" (noble, apt 2.8.3: 2379 kB and 280 kB both ways, 2026-10-26).
# --assume-no itself is no dry run: it answers a prompt, and an install of
# exactly the packages named asks none, so it installs them.
#
# The floor every filesystem a step writes keeps, beyond what apt counts:
# an initramfs rebuild, dpkg's and apt's logs and records. A kernel install
# took 47124 KiB more than apt's "After this operation" (114116 KiB used
# for 68.6 MB; its initrd alone 19165 KiB, gzip, linux-image-virtual on
# noble, 2026-10-26), and a generic kernel's initrd is larger: 128 MiB.
SPACE_FLOOR_KIB=131072
APT_ARCHIVES=/var/cache/apt/archives
# The canonical disk GC's config (maintaining-host-disk). Its sensor pages
# at [sensor] alert_at_percent of [sensor] mount; a key it leaves out takes
# the GC's own default in VERSION 2, 3 and 4 (load_config): 85 and /.
DISK_GC_CONF=/etc/cannobserv/disk-gc/disk-gc.conf
DISK_GC_ALERT_DEFAULT=85
DISK_GC_MOUNT_DEFAULT=/
# The commands step_space reads apt and dpkg with: a caller may prefix them
# (as_root, apt_env) or add options (a scratch copy of the lists).
SS_APT_GET=(apt-get -s -o Dir::Log::Planner=/dev/null)
SS_APT_CACHE=(apt-cache)
SS_DPKGQ=(dpkg-query)
# dpkg-query's format: the expansions are its own.
# shellcheck disable=SC2016
DPKG_SIZES='${Package}:${Architecture} ${Installed-Size}\n'

trim() {  # <var> <text>: VAR := TEXT without leading or trailing blanks
  local _tr=$2
  _tr=${_tr#"${_tr%%[![:space:]]*}"}
  _tr=${_tr%"${_tr##*[![:space:]]}"}
  printf -v "$1" '%s' "$_tr"
}

# A path that isn't there yet is read where it would be made: its nearest
# directory that is, as recovery-point.sh reads the run's.
fs_reading() {  # <path>: FS_FREE and FS_USED in KiB, and FS_MOUNT; 1 when df can't say
  local _fr_d=$1 _fr_out _fr_l _fr_n=0
  local -a _fr_f=()
  FS_FREE="" FS_USED="" FS_MOUNT=""
  while [ ! -d "$_fr_d" ] && [ "$_fr_d" != / ] && [ -n "$_fr_d" ]; do _fr_d=$(dirname "$_fr_d"); done
  capture _fr_out df -Pk -- "$_fr_d"
  [ "$CAP_RC" -eq 0 ] || return 1
  while IFS= read -r _fr_l; do
    _fr_n=$((_fr_n + 1))
    if [ "$_fr_n" -eq 2 ]; then read -r -a _fr_f <<<"$_fr_l" || true; fi
  done <<<"$_fr_out"
  # Filesystem, 1024-blocks, Used, Available, Capacity, then the mount.
  [ "${#_fr_f[@]}" -ge 6 ] || return 1
  case ${_fr_f[2]}:${_fr_f[3]} in *[!0-9:]* | :* | *:) return 1 ;; esac
  FS_USED=${_fr_f[2]} FS_FREE=${_fr_f[3]} FS_MOUNT=${_fr_f[*]:5}
}

# The step's change set comes from apt's own resolution of its packages:
# `apt-get -s install --only-upgrade`, which adds what they pull in, and
# simulates a held package's upgrade as the step that releases it takes it.
step_space() {  # <package>...: SS_DOWNLOAD, SS_GROWTH, SS_PEAK in KiB, SS_N; 1 with SS_WHY when unread
  local _ss_out _ss_l _ss_r _ss_n _ss_b _ss_a _ss_o _ss_v _ss_k _ss_x _ss_want=" " _ss_up=" "
  local _ss_db=" " _ss_p="" _ss_pa="" _ss_pv="" _ss_sz="" _ss_is="" _ss_got=" " _ss_f _ss_bytes=0
  local -a _ss_q=() _ss_keys=()
  SS_DOWNLOAD=0 SS_GROWTH=0 SS_PEAK=0 SS_N=0 SS_WHY=""
  [ "$#" -gt 0 ] || return 0
  capture _ss_out "${SS_APT_GET[@]}" "${APT_SIM_PHASED[@]}" install --only-upgrade "$@"
  if [ "$CAP_RC" -ne 0 ]; then
    SS_WHY="apt-get -s install --only-upgrade exited $CAP_RC${CAP_ERR:+: $CAP_ERR}"
    return 1
  fi
  # "Inst <name> [<installed>] (<candidate> <origins> [<arch>])": the
  # installed version only for an upgrade, and <name> with :<arch> for a
  # foreign one.
  while IFS= read -r _ss_l; do
    case $_ss_l in "Inst "*) ;; *) continue ;; esac
    _ss_r=${_ss_l#Inst }
    _ss_n=${_ss_r%% *}
    _ss_r=${_ss_r#"$_ss_n"}
    _ss_o=""
    case $_ss_r in " ["*) _ss_o=${_ss_r# \[} _ss_o=${_ss_o%%\]*} ;; esac
    _ss_v=${_ss_r#*(}
    _ss_a=${_ss_v%)*}
    _ss_a=${_ss_a##*\[}
    _ss_a=${_ss_a%%\]*}
    _ss_v=${_ss_v%% *}
    _ss_b=${_ss_n%%:*}
    if [ -z "$_ss_v" ] || [ -z "$_ss_a" ] || [ "$_ss_v" = "$_ss_r" ]; then
      SS_WHY="apt-get -s printed an Inst line it doesn't read: $_ss_l"
      return 1
    fi
    _ss_k="$_ss_b:$_ss_a=$_ss_v"
    in_words "$_ss_k" "$_ss_want" && continue
    _ss_want="$_ss_want$_ss_k "
    _ss_keys+=("$_ss_k")
    if [ -n "$_ss_o" ]; then _ss_up="$_ss_up$_ss_k "; fi
    _ss_q+=("$_ss_n=$_ss_v")
  done <<<"$_ss_out"
  SS_N=${#_ss_keys[@]}
  [ "$SS_N" -gt 0 ] || return 0
  capture _ss_out "${SS_APT_CACHE[@]}" show "${_ss_q[@]}"
  if [ "$CAP_RC" -ne 0 ]; then
    SS_WHY="apt-cache show exited $CAP_RC${CAP_ERR:+: $CAP_ERR}"
    return 1
  fi
  # Exit 1 is a package dpkg doesn't have: a new one, which grows by all of
  # its Installed-Size.
  capture _ss_x "${SS_DPKGQ[@]}" -W -f "$DPKG_SIZES" "${_ss_keys[@]%%=*}"
  if [ "$CAP_RC" -gt 1 ]; then
    SS_WHY="dpkg-query -W exited $CAP_RC${CAP_ERR:+: $CAP_ERR}"
    return 1
  fi
  while read -r _ss_k _ss_l; do
    if [ -n "$_ss_k" ]; then _ss_db="$_ss_db$_ss_k=${_ss_l:-0} "; fi
  done <<<"$_ss_x"
  # A stanza per version: the blank line after each closes it.
  while IFS= read -r _ss_l; do
    case $_ss_l in
      "Package: "*) _ss_p=${_ss_l#Package: } ;;
      "Architecture: "*) _ss_pa=${_ss_l#Architecture: } ;;
      "Version: "*) _ss_pv=${_ss_l#Version: } ;;
      "Size: "*) _ss_sz=${_ss_l#Size: } ;;
      "Installed-Size: "*) _ss_is=${_ss_l#Installed-Size: } ;;
      "")
        _ss_k="$_ss_p:$_ss_pa=$_ss_pv"
        if [ -n "$_ss_p" ] && in_words "$_ss_k" "$_ss_want" && ! in_words "$_ss_k" "$_ss_got"; then
          case $_ss_sz:$_ss_is in
            *[!0-9:]* | :* | *:)
              SS_WHY="apt-cache show gave $_ss_k no Size or Installed-Size"
              return 1 ;;
          esac
          _ss_got="$_ss_got$_ss_k "
          # Already in the cache at its size: apt fetches nothing for it.
          _ss_f="$P_ROOT$APT_ARCHIVES/${_ss_p}_${_ss_pv//:/%3a}_$_ss_pa.deb"
          _ss_x=""
          if [ -f "$_ss_f" ]; then _ss_x=$(wc -c <"$_ss_f" 2>/dev/null) || _ss_x=""; fi
          trim _ss_x "$_ss_x"
          if [ "$_ss_x" != "$_ss_sz" ]; then _ss_bytes=$((_ss_bytes + _ss_sz)); fi
          _ss_x=${_ss_db#*" $_ss_p:$_ss_pa="}
          if [ "$_ss_x" = "$_ss_db" ]; then _ss_x=0; else _ss_x=${_ss_x%% *}; fi
          case $_ss_x in '' | *[!0-9]*) _ss_x=0 ;; esac
          SS_GROWTH=$((SS_GROWTH + _ss_is - _ss_x))
          # An upgrade unpacks beside the files it replaces, then renames
          # them over: for a moment both are on disk. A 195313 KiB package
          # took 196508 KiB more at its peak, and nothing after (dpkg 1.22,
          # noble, 2026-10-26).
          if in_words "$_ss_k" "$_ss_up" && [ "$_ss_is" -gt "$SS_PEAK" ]; then SS_PEAK=$_ss_is; fi
        fi
        _ss_p="" _ss_pa="" _ss_pv="" _ss_sz="" _ss_is="" ;;
    esac
  done <<<"$_ss_out"$'\n'
  for _ss_k in "${_ss_keys[@]}"; do
    in_words "$_ss_k" "$_ss_got" && continue
    SS_WHY="apt-cache show printed no record of $_ss_k"
    return 1
  done
  SS_DOWNLOAD=$(((_ss_bytes + 1023) / 1024))
}

# The canonical GC's config, read as strictly as the GC reads it: an
# unreadable file, or one whose syntax, sections or [sensor] keys it would
# reject, is never read as absent. VERSION 2's, 3's and 4's load_config parses it with
# configparser.ConfigParser(interpolation=None, default_section="\0none"):
# [section] headers, each once; "key = value" or "key: value" lines, keys
# case-folded, each once per section; # and ; comments on their own line; an
# indented line continuing the value above; a % as itself. [DEFAULT] is no
# fallback there but a section like any other, and its _KEYS know [gc] and
# [sensor] alone, so any other section is refused, and so is any [sensor]
# key but these six (CR 582). [gc]'s keys aren't judged here: they're the
# GC's to refuse.
DISK_GC_SENSOR_KEYS="mount alert_at_percent clear_at_percent gc_stale_hours status_url monitor_id"
disk_gc_conf() {  # GC_STATE := absent, ok or bad; GC_ALERT and GC_MOUNT when ok; GC_WHY when bad
  local _gc_t _gc_l _gc_s _gc_n=0 _gc_k _gc_v _gc_sect="" _gc_last="" _gc_sects=" " _gc_keys=" "
  local _gc_a="" _gc_ha=0 _gc_m="" _gc_hm=0
  GC_PATH=$P_ROOT$DISK_GC_CONF GC_STATE=absent GC_ALERT="" GC_MOUNT="" GC_WHY=""
  if [ ! -e "$GC_PATH" ] && [ ! -L "$GC_PATH" ]; then return 0; fi
  GC_STATE=bad
  if [ ! -f "$GC_PATH" ]; then
    GC_WHY="it isn't a regular file"
    return 0
  fi
  capture _gc_t as_reader cat -- "$GC_PATH"
  if [ "$CAP_RC" -ne 0 ]; then
    GC_WHY="it couldn't be read${CAP_ERR:+ ($CAP_ERR)}"
    return 0
  fi
  while IFS= read -r _gc_l || [ -n "$_gc_l" ]; do
    _gc_n=$((_gc_n + 1))
    _gc_l=${_gc_l%$'\r'}
    trim _gc_s "$_gc_l"
    case $_gc_s in '' | '#'* | ';'*) continue ;; esac
    case $_gc_l in
      [[:space:]]*)
        if [ -n "$_gc_last" ]; then
          case $_gc_last in
            sensor.alert_at_percent | sensor.mount)
              GC_WHY="line $_gc_n continues [sensor] ${_gc_last#*.} onto a second line"
              return 0 ;;
          esac
          continue
        fi ;;
    esac
    case $_gc_s in
      \[*\])
        _gc_k=${_gc_s#\[}
        _gc_k=${_gc_k%\]}
        if [ -z "$_gc_k" ]; then
          GC_WHY="line $_gc_n is an empty section header"
          return 0
        fi
        case $_gc_sects in *" $_gc_k "*)
          GC_WHY="line $_gc_n repeats the section [$_gc_k]"
          return 0 ;;
        esac
        case $_gc_k in
          gc | sensor) ;;
          *)
            GC_WHY="line $_gc_n has an unknown section [$_gc_k]: the GC knows [gc] and [sensor] alone"
            return 0 ;;
        esac
        _gc_sects="$_gc_sects$_gc_k " _gc_sect=$_gc_k _gc_last=""
        continue ;;
      \[*)
        GC_WHY="line $_gc_n is no section header, key = value line or comment"
        return 0 ;;
    esac
    if [ -z "$_gc_sect" ]; then
      GC_WHY="line $_gc_n comes before any [section] header"
      return 0
    fi
    _gc_k=${_gc_s%%[=:]*}
    if [ "$_gc_k" = "$_gc_s" ]; then
      GC_WHY="line $_gc_n is no section header, key = value line or comment"
      return 0
    fi
    _gc_v=${_gc_s:${#_gc_k}+1}
    trim _gc_k "$_gc_k"
    trim _gc_v "$_gc_v"
    _gc_k=$(printf '%s' "$_gc_k" | tr '[:upper:]' '[:lower:]')
    if [ -z "$_gc_k" ]; then
      GC_WHY="line $_gc_n has no key before its ${_gc_s:0:1}"
      return 0
    fi
    case $_gc_keys in *" $_gc_sect.$_gc_k "*)
      GC_WHY="line $_gc_n repeats $_gc_k in [$_gc_sect]"
      return 0 ;;
    esac
    if [ "$_gc_sect" = sensor ] && ! in_words "$_gc_k" "$DISK_GC_SENSOR_KEYS"; then
      GC_WHY="line $_gc_n has an unknown key [sensor] $_gc_k: the GC (VERSION 2, 3 and 4) knows $DISK_GC_SENSOR_KEYS"
      return 0
    fi
    _gc_keys="$_gc_keys$_gc_sect.$_gc_k " _gc_last=$_gc_sect.$_gc_k
    case $_gc_last in
      sensor.alert_at_percent) _gc_a=$_gc_v _gc_ha=1 ;;
      sensor.mount) _gc_m=$_gc_v _gc_hm=1 ;;
    esac
  done <<<"$_gc_t"
  # VERSION 2's, 3's and 4's _int: digits alone (^[0-9]+$), from 1 to 100 (CR 583). The
  # leading zeros go first, so a long run of them can't overflow the test.
  if [ "$_gc_ha" -eq 0 ]; then
    _gc_a=$DISK_GC_ALERT_DEFAULT
  else
    _gc_v=$_gc_a
    while [ "${#_gc_v}" -gt 1 ] && [ "${_gc_v#0}" != "$_gc_v" ]; do _gc_v=${_gc_v#0}; done
    if ! [[ $_gc_v =~ ^[0-9]{1,3}$ ]] || [ "$_gc_v" -lt 1 ] || [ "$_gc_v" -gt 100 ]; then
      GC_WHY="[sensor] alert_at_percent is \"$_gc_a\", not a whole percent from 1 to 100"
      return 0
    fi
    _gc_a=$_gc_v
  fi
  if [ "$_gc_hm" -eq 0 ]; then
    _gc_m=$DISK_GC_MOUNT_DEFAULT
  else
    case $_gc_m in
      /*[[:cntrl:]]*) GC_WHY="[sensor] mount is \"$_gc_m\", which holds a control character"; return 0 ;;
      /*) ;;
      *) GC_WHY="[sensor] mount is \"$_gc_m\", not an absolute path"; return 0 ;;
    esac
  fi
  GC_STATE=ok GC_ALERT=$_gc_a GC_MOUNT=$_gc_m
}

# Whether a step's SS_* figures fit where they land, and stay under the
# disk GC's headroom line where a host has adopted it. Each filesystem keeps
# the floor: apt's cache takes the download, and / the install growth plus
# the largest upgrade's unpack beside its old files (one need where the two
# share a filesystem). SPACE_WHY, SPACE_KIND (risk or unknown) and SPACE_ID
# := each shortfall, and SPACE_JSON := what was read.
space_gate() {  # <the step, as the messages name it>
  local _sp_w=$1 _sp_g=$SS_GROWTH _sp_cf="" _sp_cm="" _sp_cu="" _sp_rf="" _sp_rm="" _sp_ru=""
  local _sp_o="" _sp_a="" _sp_e="" _sp_n _sp_add=0 _sp_den _sp_pct
  SPACE_WHY=() SPACE_KIND=() SPACE_ID=() SPACE_JSON=""
  [ "$_sp_g" -gt 0 ] || _sp_g=0
  if fs_reading "$P_ROOT$APT_ARCHIVES"; then
    _sp_cf=$FS_FREE _sp_cm=$FS_MOUNT _sp_cu=$FS_USED
  else
    space_short unknown space:apt-cache "the free space under $APT_ARCHIVES couldn't be read (df -Pk), so whether $_sp_w's download fits is unknown"
  fi
  if fs_reading "$P_ROOT/"; then
    _sp_rf=$FS_FREE _sp_rm=$FS_MOUNT _sp_ru=$FS_USED
  else
    space_short unknown space:root "the free space under / couldn't be read (df -Pk), so whether $_sp_w's install fits is unknown"
  fi
  jaddn _sp_o download_kib "$SS_DOWNLOAD"
  jaddn _sp_o growth_kib "$SS_GROWTH"
  jaddn _sp_o peak_kib "$SS_PEAK"
  jaddn _sp_o floor_kib "$SPACE_FLOOR_KIB"
  if [ -n "$_sp_cf" ] && [ -n "$_sp_rf" ] && [ "$_sp_cm" = "$_sp_rm" ]; then
    _sp_n=$((SS_DOWNLOAD + _sp_g + SS_PEAK + SPACE_FLOOR_KIB))
    space_fs _sp_a "$_sp_rm" "$APT_ARCHIVES /" "$_sp_rf" "$_sp_n"
    if [ "$_sp_rf" -lt "$_sp_n" ]; then
      space_short risk space:disk "$_sp_w needs $_sp_n KiB free on $_sp_rm, which holds apt's cache and /, and it has $_sp_rf: $SS_DOWNLOAD to download, $_sp_g of install growth, $SS_PEAK for the largest upgrade unpacked beside its old files, and the $SPACE_FLOOR_KIB KiB floor. Free space there first"
    fi
  else
    if [ -n "$_sp_cf" ]; then
      _sp_n=$((SS_DOWNLOAD + SPACE_FLOOR_KIB))
      space_fs _sp_a "$_sp_cm" "$APT_ARCHIVES" "$_sp_cf" "$_sp_n"
      if [ "$_sp_cf" -lt "$_sp_n" ]; then
        space_short risk space:apt-cache "$_sp_w needs $_sp_n KiB free on $_sp_cm, which holds apt's cache, and it has $_sp_cf: $SS_DOWNLOAD to download, and the $SPACE_FLOOR_KIB KiB floor. Free space there first"
      fi
    fi
    if [ -n "$_sp_rf" ]; then
      _sp_n=$((_sp_g + SS_PEAK + SPACE_FLOOR_KIB))
      space_fs _sp_a "$_sp_rm" "/" "$_sp_rf" "$_sp_n"
      if [ "$_sp_rf" -lt "$_sp_n" ]; then
        space_short risk space:root "$_sp_w needs $_sp_n KiB free on $_sp_rm, which holds /, and it has $_sp_rf: $_sp_g of install growth, $SS_PEAK for the largest upgrade unpacked beside its old files, and the $SPACE_FLOOR_KIB KiB floor. Free space there first"
      fi
    fi
  fi
  jadd _sp_o filesystems "[$_sp_a]"
  # The GC's headroom line: today's use, plus the download where it lands on
  # the sensor's mount, plus the install growth where that does, must read
  # under alert_at_percent as the sensor reads it. VERSION 2's, 3's and 4's usage() is
  # df's Use%: used over used plus available, rounded up, and it pages at
  # percent >= alert_at_percent (CR 581).
  disk_gc_conf
  case $GC_STATE in
    absent) jadd _sp_o headroom null ;;
    bad)
      jadds _sp_e config "$GC_PATH"
      jaddsn _sp_e error "$GC_WHY"
      jadd _sp_o headroom "{$_sp_e}"
      space_short unknown space:disk-gc-conf "$GC_PATH: $GC_WHY. The disk GC refuses such a file too, and whether $_sp_w crosses its headroom line is unknown: fix it first" ;;
    ok)
      jadds _sp_e config "$GC_PATH"
      jadds _sp_e mount "$GC_MOUNT"
      jaddn _sp_e alert_at_percent "$GC_ALERT"
      if ! fs_reading "$P_ROOT$GC_MOUNT"; then
        jadd _sp_o headroom "{$_sp_e}"
        space_short unknown space:headroom "the free space under $GC_MOUNT, the disk GC's [sensor] mount, couldn't be read (df -Pk), so whether $_sp_w crosses its headroom line is unknown"
      else
        if [ -n "$_sp_cm" ] && [ "$_sp_cm" = "$FS_MOUNT" ]; then _sp_add=$((_sp_add + SS_DOWNLOAD)); fi
        if [ -n "$_sp_rm" ] && [ "$_sp_rm" = "$FS_MOUNT" ]; then _sp_add=$((_sp_add + SS_GROWTH)); fi
        _sp_den=$((FS_USED + FS_FREE))
        _sp_pct=0
        if [ "$_sp_den" -gt 0 ]; then _sp_pct=$((((FS_USED + _sp_add) * 100 + _sp_den - 1) / _sp_den)); fi
        jaddn _sp_e used_kib "$FS_USED"
        jaddn _sp_e free_kib "$FS_FREE"
        jaddn _sp_e add_kib "$_sp_add"
        jaddn _sp_e projected_percent "$_sp_pct"
        jadd _sp_o headroom "{$_sp_e}"
        if [ "$_sp_add" -gt 0 ] && [ "$_sp_pct" -ge "$GC_ALERT" ]; then
          space_short risk space:headroom "$_sp_w would take $GC_MOUNT to ${_sp_pct}% used, $_sp_add KiB more, at or past the disk GC's alert_at_percent of $GC_ALERT ($GC_PATH): a patch run must not push the host into a headroom page. Free space there first"
        fi
      fi ;;
  esac
  SPACE_JSON="{$_sp_o}"
}

space_short() {  # <risk or unknown> <id> <why>
  SPACE_KIND+=("$1") SPACE_ID+=("$2") SPACE_WHY+=("$3")
}

space_fs() {  # <var> <mount> <paths> <free KiB> <need KiB>: appends a filesystem's JSON to VAR's array body
  local _sf="" _sf_w="" _sf_p
  for _sf_p in $3; do jpushs _sf_w "$_sf_p"; done
  jadds _sf mount "$2"
  jadd _sf paths "[$_sf_w]"
  jaddn _sf free_kib "$4"
  jaddn _sf need_kib "$5"
  jpush "$1" "{$_sf}"
}

# --- units on disk ---------------------------------------------------------
# Read from the files, so the answer holds offline, in an image no systemd
# runs: a mask is a symlink to /dev/null or an empty unit file
# (systemd.unit(5)), and an enablement is a symlink in a .wants or .requires
# directory.
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

file_ctime() {  # <var> <path>
  local _fc
  _fc=$(stat -c %Z "$2" 2>/dev/null || stat -f %c "$2" 2>/dev/null) || _fc=""
  case $_fc in '' | *[!0-9]*) _fc="" ;; esac
  printf -v "$1" '%s' "$_fc"
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

# The processes a unit runs: every one in its cgroup and the cgroups below
# it, where a user manager's sit (init.scope, app.slice). MainPID alone
# misses PostgreSQL's backends. A unit that isn't running has no cgroup and
# runs nothing. 1 with RB_WHY where its cgroup can't be read. apply.sh's
# reboot decision and read_stale read it, and probe.sh's exe_deleted (CR
# 2784): the ControlGroup systemctl shows resolves an alias unit, and the
# listing reaches a delegated unit's sub-cgroups. CGROUP_DIR is the caller's.
RB_WHY=""
# unit_show sets it by name.
U_ControlGroup=""
reboot_pids() {  # <var> <unit>: VAR := its PIDs, space-separated
  local _rp_cg _rp_fs _rp_f _rp_x _rp_p _rp_out=""
  printf -v "$1" '%s' ""
  if ! unit_show "$2" ControlGroup; then
    RB_WHY="systemctl couldn't show $2's ControlGroup"
    return 1
  fi
  [ -n "$U_ControlGroup" ] || return 0
  _rp_cg=$CGROUP_DIR$U_ControlGroup
  if [ ! -d "$_rp_cg" ]; then
    RB_WHY="$2's cgroup, $_rp_cg, isn't there"
    return 1
  fi
  capture _rp_fs find "$_rp_cg" -name cgroup.procs
  if [ "$CAP_RC" -ne 0 ]; then
    RB_WHY="$2's cgroup, $_rp_cg, couldn't be listed${CAP_ERR:+: $CAP_ERR}"
    return 1
  fi
  while IFS= read -r _rp_f; do
    [ -n "$_rp_f" ] || continue
    if ! _rp_x=$(cat -- "$_rp_f" 2>/dev/null); then
      # A child cgroup removed since the listing held nothing more.
      [ -e "$_rp_f" ] || continue
      RB_WHY="$_rp_f couldn't be read"
      return 1
    fi
    for _rp_p in $_rp_x; do _rp_out="$_rp_out $_rp_p"; done
  done <<<"$_rp_fs"
  printf -v "$1" '%s' "${_rp_out# }"
}

# The deleted files needrestart 3.6 passes over (noble's 3.6-7ubuntu4.6,
# measured 2026-11-18): its default blacklist_mappings, each Perl pattern in
# POSIX ERE, matched on the path with " (deleted)" still on. A memfd, a /tmp
# file and the like are no file dpkg replaced, and no restart clears them.
# apply.sh's reboot_maps reads a map by them, and read_stale and probe.sh's
# exe_deleted a process's binary (CR 2776).
DELETED_SKIP=(
  '^/(SYSV00000000( \(deleted\))?|drm([[:space:]]|$)|dev/)'
  '^/memfd:'
  '^/\[aio\]'
  '/orcexec\.[[:alnum:]_]+( \(deleted\))?$'
  '/#[0-9]+( \(deleted\))?$'
  '/jna[0-9]+\.tmp( \(deleted\))?$'
  '^(/var)?/tmp/'
  '^(/var)?/run/'
)
deleted_passed_over() {  # <path, " (deleted)" still on>: 0 when needrestart passes it over
  local _dp_s
  for _dp_s in "${DELETED_SKIP[@]}"; do
    if [[ $1 =~ $_dp_s ]]; then return 0; fi
  done
  return 1
}

# The packages that own files, as dpkg-query -S finds them. noble's dpkg
# records some files under their pre-merge path: iproute2's /sbin/ip, which
# /proc reads as /usr/sbin/ip. So a /usr/bin, /usr/sbin or /usr/lib* path no
# package owns is asked again without /usr (CR 2777). apply.sh's
# reboot_maps and stale_owner both ask through it, so the two can't drift
# (#703). One line a path that has an owner, "<packages><TAB><the path as
# given>", the packages space-separated with their :arch kept. A diversion's
# lines aren't owners: dpkg 1.22 prints "local diversion from: <path>" and
# "... to: <path>.orig", or "diversion by <pkg> from: ...", before the
# owner's line (measured), so a line counts only for a path asked about
# (CR 2822). dpkg-query exits 1 for a path it doesn't know and prints the
# rest: 1 with OW_RC (its status) and OW_ERR only past that.
OW_RC=0 OW_ERR=""
path_owners() {  # <var> <path>...: VAR := "<packages><TAB><path>", a line an owned path
  local _po_v=$1 _po_out _po_l _po_k _po_p _po_res="" _po_got=$'\n' _po_pass _po_ask
  local -a _po_q=() _po_w=()
  shift
  OW_RC=0 OW_ERR=""
  printf -v "$_po_v" '%s' ""
  _po_q=("$@")
  for _po_pass in "" /usr; do
    [ "${#_po_q[@]}" -gt 0 ] || break
    _po_ask=$'\n'
    for _po_p in "${_po_q[@]}"; do _po_ask="$_po_ask$_po_p"$'\n'; done
    capture _po_out dpkg-query -S "${_po_q[@]}"
    if [ "$CAP_RC" -gt 1 ]; then
      OW_RC=$CAP_RC OW_ERR=$CAP_ERR
      return 1
    fi
    while IFS= read -r _po_l; do
      case $_po_l in diversion\ * | "local diversion "* | "") continue ;; esac
      # "a:amd64, b: /path": a package name holds no ": ", so the first
      # ": /" ends the list, and the path may hold anything after it.
      _po_k=${_po_l%%: /*}
      [ "$_po_k" != "$_po_l" ] || continue
      _po_p=${_po_l#"$_po_k": }
      case $_po_ask in *$'\n'"$_po_p"$'\n'*) ;; *) continue ;; esac
      _po_p=$_po_pass$_po_p
      read -r -a _po_w <<<"${_po_k//,/ }"
      case $_po_got in *$'\n'"$_po_p"$'\n'*) continue ;; esac
      _po_got="$_po_got$_po_p"$'\n'
      _po_res="$_po_res${_po_w[*]}"$'\t'"$_po_p"$'\n'
    done <<<"$_po_out"
    [ -z "$_po_pass" ] || break
    # The second pass: each usr-merged path the first found no owner for.
    _po_q=()
    for _po_p in "$@"; do
      case $_po_got in *$'\n'"$_po_p"$'\n'*) continue ;; esac
      case $_po_p in /usr/bin/* | /usr/sbin/* | /usr/lib*/*) ;; *) continue ;; esac
      _po_q+=("${_po_p#/usr}")
    done
  done
  printf -v "$_po_v" '%s' "${_po_res%$'\n'}"
}

is_int() {
  local re='^-?[0-9]+$'
  [[ ${1-} =~ $re ]]
}

# --- redaction by name (#698) ---------------------------------------------------
# Shared by probe.sh's live_args and recovery-point.sh's backup log (#682,
# CR 2796), since a reading is made to be copied off the host. The value of an
# option or assignment whose name marks a secret is <redacted>, and so are a
# URL's userinfo password, a userinfo with none (a token used as the user name
# can't be told from a user), and a secret-named query or fragment
# parameter's value. The name stays, to show it was passed. By name only: a
# positional secret, a short option's value and the environment aren't
# recognised (readings.md).
# A name is secret when it's one of SECRET_ARG_NAMES, or its last word is one
# of SECRET_ARG_WORDS: words split at . - _ and a camelCase capital, so
# -Dspring.datasource.password, --db_pass and --authToken all are (CR 2766).
# A --no- name is a boolean, and takes no value (CR 2769). A URL parameter
# may also be one of SECRET_PARAM_WORDS: Azure's SAS signature, AWS's.
SECRET_ARG_NAMES="requirepass masterauth"
SECRET_ARG_WORDS="token password passwd passphrase pass pwd secret key apikey authkey
  credential credentials secretkey accesskey privatekey apitoken authtoken accesstoken"
SECRET_PARAM_WORDS="sig signature"
secret_arg_name() {  # <name, dashes stripped, no value> [<more words>]: 0 when it names a secret
  local _sn_last=${1##*[._-]} _sn_camel="" _sn_w _sn_nc=0 _sn_rc=1
  shopt -q nocasematch && _sn_nc=1
  shopt -u nocasematch
  if [[ $_sn_last =~ [a-z0-9]([A-Z][a-z]*)$ ]]; then _sn_camel=${BASH_REMATCH[1]}; fi
  shopt -s nocasematch
  case $1 in
    no[-_]*) ;;
    *)
      for _sn_w in $SECRET_ARG_NAMES; do
        case $1 in "$_sn_w") _sn_rc=0 ;; esac
      done
      for _sn_w in $SECRET_ARG_WORDS ${2-}; do
        case $_sn_last in "$_sn_w") _sn_rc=0 ;; esac
        case $_sn_camel in "$_sn_w") _sn_rc=0 ;; esac
      done ;;
  esac
  [ "$_sn_nc" -eq 1 ] || shopt -u nocasematch
  return "$_sn_rc"
}
# A URL parameter: a name after ? & # or ;. A secret one's value runs to the
# next &, or a , that starts another URL (a comma joins URLs in one word), so
# a , ; or # inside it doesn't end it, and a fragment after it goes with it
# (CR 2791). Any other's ends at & # , ; or ?, so a URL nested in it is
# scanned too (CR 2794). Patterns in variables: & ; and # are operators in a
# literal [[ =~ ]].
URL_PARAM_PRE='^([^?&#;]*[?&#;])(.*)$'
URL_PARAM_KV='^([^=&#,?;]+)=(.*)$'
URL_PARAM_PLAIN='^([^&#,;?]*)(.*)$'
URL_START='^[A-Za-z][A-Za-z0-9+.-]*://'
ENV_NAME='^[A-Za-z_][A-Za-z0-9_.-]*$'
redact_url() {  # <var> <word>: the word with each URL's userinfo and secret parameter values redacted
  local _ru_w=$2 _ru_out="" _ru_auth _ru_ui _ru_k _ru_v _ru_r _ru_p
  [[ $_ru_w == *://* ]] || { printf -v "$1" '%s' "$_ru_w"; return 0; }
  while [[ $_ru_w == *://* ]]; do
    _ru_out="$_ru_out${_ru_w%%://*}://"
    _ru_w=${_ru_w#*://}
    # The authority runs to the first /, and its userinfo to its last @, as
    # libpq reads a URI: a password may hold a ? or a # (CR 2765, CR 2781).
    _ru_auth=${_ru_w%%/*}
    case $_ru_auth in *@*)
      _ru_ui=${_ru_auth%@*}
      _ru_w=${_ru_w#"$_ru_ui"@}
      case $_ru_ui in
        *:*) _ru_out="$_ru_out${_ru_ui%%:*}:<redacted>@" ;;
        *) _ru_out="$_ru_out<redacted>@" ;;
      esac ;;
    esac
  done
  _ru_w="$_ru_out$_ru_w" _ru_out=""
  # Each parameter in every URL of the word, the query's and the
  # fragment's (CR 2767, CR 2786).
  while [[ $_ru_w =~ $URL_PARAM_PRE ]]; do
    _ru_out="$_ru_out${BASH_REMATCH[1]}"
    _ru_w=${BASH_REMATCH[2]}
    if [[ $_ru_w =~ $URL_PARAM_KV ]]; then
      _ru_k=${BASH_REMATCH[1]} _ru_w=${BASH_REMATCH[2]}
      if secret_arg_name "$_ru_k" "$SECRET_PARAM_WORDS"; then
        _ru_r=${_ru_w%%&*}
        _ru_v=${_ru_r%%,*}
        _ru_r=${_ru_r#"$_ru_v"}
        while [ -n "$_ru_r" ]; do
          _ru_r=${_ru_r#,}
          if [[ $_ru_r =~ $URL_START ]]; then break; fi
          _ru_p=${_ru_r%%,*}
          _ru_v="$_ru_v,$_ru_p"
          _ru_r=${_ru_r#"$_ru_p"}
        done
        _ru_w=${_ru_w#"$_ru_v"}
        _ru_v="<redacted>"
      else
        [[ $_ru_w =~ $URL_PARAM_PLAIN ]]
        _ru_v=${BASH_REMATCH[1]} _ru_w=${BASH_REMATCH[2]}
      fi
      _ru_out="$_ru_out$_ru_k=$_ru_v"
    fi
  done
  printf -v "$1" '%s' "$_ru_out$_ru_w"
}
# An environment name may run its secret word on with no separator:
# PGPASSWORD, GITHUB_TOKEN's kin MYTOKEN (CR 2813). A NO_ name stays a
# boolean, as --no- is.
SECRET_ENV_SUFFIXES="password passwd passphrase token secret apikey api_key"
secret_env_name() {  # <NAME>: 0 when an environment name marks a secret
  local _se_s _se_nc=0 _se_rc=1
  if secret_arg_name "$1"; then return 0; fi
  shopt -q nocasematch && _se_nc=1
  shopt -s nocasematch
  case $1 in
    no[-_]*) ;;
    *)
      for _se_s in $SECRET_ENV_SUFFIXES; do
        case $1 in *"$_se_s") _se_rc=0 ;; esac
      done ;;
  esac
  [ "$_se_nc" -eq 1 ] || shopt -u nocasematch
  return "$_se_rc"
}
# A shell's quoting, as xtrace prints it and a script string holds it
# (CR 2813, #707). A value's quotes are scanned as a shell's: '\'' stays
# inside a single quote, a \ outside one, or inside a double one or $'..',
# escapes the next character, and a quote may open mid-value (a'b c'). A
# value that leaves a quote open runs on through the word that closes it, as
# one ending in an escaped space runs on into the next. One whose closing
# quote is followed by ; ) , & | ] or a space ends there, and what follows is
# read on (X_TOKEN='a b'; exec d). A word is read in one loop, never by
# recursion, jumping from quote to quote, so its length is no bound (CR 2814,
# CR 2815). A Python repr's \' inside '..' is read as a shell's, so its
# value can end early (readings.md).
# The state between words: RS_Q, the quote a redacted value has open (' " or
# $ for $'..', \ after an escaped space, or empty); RS_NEXT, 1 when the next
# word is a secret's value; RS_LIST, 1 when that's a list's or a call's
# element, whose unquoted trailing ) ] , aren't its own; RS_WRAP, the quote
# before a name ('NAME=..'), closed in the output when the value closes on
# its line. RW_QUOTE: the quote a line leaves open, which the backup log
# carries into the run's next entry (CR 2816).
RS_OUT="" RS_Q="" RS_NEXT=0 RS_LIST=0 RS_WRAP="" RW_QUOTE=""
QS_RE_OUT="^[^'\"\\\\\$]*"
QS_RE_SQ="^[^']*"
QS_RE_DQ="^[^\"\\\\]*"
QS_RE_AQ="^[^'\\\\]*"
# A list's or call's element, as a log prints one (['--password', 'x'],
# f(--token x)), and a list assigned to a name that isn't a secret's
# (args=['--password', 'x'], CR 2819).
ARG_OPEN="^[^-=\"'[:space:]]*[[(]"
ARG_SET_OPEN="^([A-Za-z_][A-Za-z0-9_.-]*)=[[(]"
quote_scan() {  # <quote open at the start, or empty> <text>: QS := the quote open at its end; QS_TAIL := the text from what ends a value after a closing quote, where the scan stopped
  local _qs_s=$2 _qs_c _qs_re
  QS=$1 QS_TAIL=""
  if [ "$QS" = "\\" ]; then QS=""; fi
  while :; do
    case $QS in
      "") _qs_re=$QS_RE_OUT ;;
      \') _qs_re=$QS_RE_SQ ;;
      \") _qs_re=$QS_RE_DQ ;;
      *) _qs_re=$QS_RE_AQ ;;
    esac
    [[ $_qs_s =~ $_qs_re ]] || return 0
    _qs_s=${_qs_s:${#BASH_REMATCH[0]}}
    [ -n "$_qs_s" ] || return 0
    _qs_c=${_qs_s:0:1} _qs_s=${_qs_s:1}
    case $QS$_qs_c in
      \\ | \"\\ | \$\\)
        if [ -z "$_qs_s" ]; then
          if [ -z "$QS" ]; then QS=\\; fi
          return 0
        fi
        _qs_s=${_qs_s:1} ;;
      \$) case $_qs_s in \'*) QS='$' _qs_s=${_qs_s:1} ;; esac ;;
      \' | \") QS=$_qs_c ;;
      "''" | '""' | "\$'")
        QS=""
        case $_qs_s in []\;\),\&\|[:space:]]*) QS_TAIL=$_qs_s; return 0 ;; esac ;;
    esac
  done
}
redact_value() {  # <value> <the quote it starts in, or empty> <1 when a list's element>: RS_Q := the quote it leaves open; VE_REST := what follows its end; VE_KEEP := a list's unquoted value's trailing ) ] ,
  local _rv_v=$1
  VE_KEEP=""
  quote_scan "$2" "$_rv_v"
  RS_Q=$QS VE_REST=$QS_TAIL
  if [ "$3" -eq 1 ] && [ -z "$QS" ] && [ -z "$QS_TAIL" ]; then
    case $_rv_v in
      *[\'\"\\]*) ;;
      *)
        while :; do
          case $_rv_v in
            *[],\)]) VE_KEEP="${_rv_v: -1}$VE_KEEP" _rv_v=${_rv_v%?} ;;
            *) break ;;
          esac
        done ;;
    esac
  fi
}
redact_word() {  # <text> [<separator before it>]: RS_OUT += the text under the name rule, from RS_*'s state, which it leaves for the next
  local _rd_w=$1 _rd_sep _rd_pre _rd_q _rd_n _rd_v _rd_out _rd_red _rd_list _rd_sp _rd_x _rd_i=0
  local -a _rd_ws=()
  if [ $# -gt 1 ]; then _rd_sep=$2; elif [ -n "$RS_OUT" ]; then _rd_sep=" "; else _rd_sep=""; fi
  while [ -n "$_rd_w" ]; do
    if [ -n "$RS_Q" ]; then
      # Inside a redacted value: dropped, through what ends it.
      quote_scan "$RS_Q" "$_rd_w"
      RS_Q=$QS
      if [ -z "$RS_Q" ]; then RS_OUT="$RS_OUT$RS_WRAP" RS_WRAP=""; fi
      _rd_w=$QS_TAIL _rd_sep=""
      continue
    fi
    if [ "$RS_NEXT" -eq 1 ]; then
      RS_NEXT=0
      redact_value "$_rd_w" "" "$RS_LIST"
      RS_OUT="$RS_OUT$_rd_sep<redacted>$VE_KEEP"
      _rd_w=$VE_REST _rd_sep=""
      continue
    fi
    # What ends a value, as it stands: ; ) , & | ]
    _rd_x=""
    while :; do
      case $_rd_w in
        []\;\),\&\|]*) _rd_x="$_rd_x${_rd_w:0:1}" _rd_w=${_rd_w:1} ;;
        *) break ;;
      esac
    done
    if [ -n "$_rd_x" ]; then
      RS_OUT="$RS_OUT$_rd_sep$_rd_x" _rd_sep=""
      continue
    fi
    _rd_pre="" _rd_q="" _rd_list=0 _rd_red=0 _rd_sp=0 _rd_out=""
    case $_rd_w in *[[:space:]]*) _rd_sp=1 ;; esac
    if [ "$_rd_sp" -eq 0 ]; then
      if [[ $_rd_w =~ $ARG_OPEN ]]; then
        _rd_pre=${BASH_REMATCH[0]}
      elif [[ $_rd_w =~ $ARG_SET_OPEN ]]; then
        # secret_env_name's own match resets BASH_REMATCH.
        _rd_pre=${BASH_REMATCH[0]}
        if secret_env_name "${BASH_REMATCH[1]}"; then _rd_pre=""; fi
      fi
      if [ -n "$_rd_pre" ]; then _rd_w=${_rd_w:${#_rd_pre}} _rd_list=1; fi
      case $_rd_w in \'?* | \"?*) _rd_q=${_rd_w:0:1} _rd_w=${_rd_w:1} ;; esac
    fi
    case $_rd_w in
      --?* | -[!-]?*)
        _rd_n=${_rd_w%%=*}
        case $_rd_n in *[[:space:]]*) _rd_n="" ;; esac
        # A quoted name, or a list's element ('--password', f(--token)),
        # loses its quote and the punctuation after it; prose's doesn't
        # (use --key, then, CR 2820).
        if [ -n "$_rd_q" ] || [ "$_rd_list" -eq 1 ]; then
          while :; do
            case $_rd_n in *[],\)]) _rd_n=${_rd_n%?} ;; *) break ;; esac
          done
          if [ -n "$_rd_q" ]; then _rd_n=${_rd_n%"$_rd_q"}; fi
        fi
        _rd_n=${_rd_n#-}
        case $_rd_n in -*) _rd_n=${_rd_n#-} ;; D?*) _rd_n=${_rd_n#D} ;; esac
        if [ -n "$_rd_n" ] && secret_arg_name "$_rd_n"; then
          case $_rd_w in
            *=*) _rd_v=${_rd_w#*=} _rd_out="${_rd_w%%=*}=<redacted>" _rd_red=1 ;;
            *) [ "$_rd_sp" -eq 1 ] || _rd_red=2 ;;
          esac
        fi ;;
      # An environment assignment, as in a script string or env's argv, is
      # an option with no dash (CR 2792).
      [A-Za-z_]*=*)
        _rd_n=${_rd_w%%=*}
        if [[ $_rd_n =~ $ENV_NAME ]] && secret_env_name "$_rd_n"; then
          _rd_v=${_rd_w#*=} _rd_out="$_rd_n=<redacted>" _rd_red=1
        fi ;;
    esac
    if [ "$_rd_red" -eq 1 ]; then
      # The value starts in the word's own opening quote, if it has one. A
      # quote it leaves open isn't closed in the output (CR 2821).
      redact_value "$_rd_v" "$_rd_q" "$_rd_list"
      case $RS_Q in
        "" | \\) _rd_out="$_rd_pre$_rd_q$_rd_out$_rd_q$VE_KEEP" ;;
        *) _rd_out="$_rd_pre$_rd_q$_rd_out" RS_WRAP=$_rd_q ;;
      esac
      RS_OUT="$RS_OUT$_rd_sep$_rd_out"
      _rd_w=$VE_REST _rd_sep=""
      continue
    fi
    if [ "$_rd_sp" -eq 1 ]; then
      # Words: a script's, or what a value's end leaves of one. A word
      # holds no space, so this reads no deeper.
      IFS=$' \t\n' read -r -d '' -a _rd_ws <<<"$_rd_w" || true
      case $_rd_w in [[:space:]]*) [ -z "$RS_OUT" ] || _rd_sep=" " ;; esac
      for _rd_x in ${_rd_ws[@]+"${_rd_ws[@]}"}; do
        if [ "$_rd_i" -eq 0 ]; then redact_word "$_rd_x" "$_rd_sep"; else redact_word "$_rd_x"; fi
        _rd_i=1
      done
      return 0
    fi
    if [ "$_rd_red" -eq 2 ]; then
      RS_NEXT=1 RS_LIST=$_rd_list
      if [ -n "$_rd_q" ]; then RS_LIST=1; fi
    fi
    _rd_out="$_rd_pre$_rd_q$_rd_w"
    redact_url _rd_out "$_rd_out"
    RS_OUT="$RS_OUT$_rd_sep$_rd_out"
    return 0
  done
}
redact_words() {  # <var> <word>...: the words under the name rule, joined by a space; RW_QUOTE is the quote open before them, and after
  local _rw_v=$1 _rw_w
  shift
  RS_OUT="" RS_Q=$RW_QUOTE RS_NEXT=0 RS_LIST=0 RS_WRAP=""
  for _rw_w in "$@"; do redact_word "$_rw_w"; done
  if [ "$RS_Q" = "\\" ]; then RS_Q=""; fi
  # A line that leaves a value's quote open is marked once.
  if [ -n "$RS_Q" ] && [ -n "$RS_OUT" ]; then RS_OUT="$RS_OUT <...>"; fi
  RW_QUOTE=$RS_Q
  printf -v "$_rw_v" '%s' "$RS_OUT"
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

# --- Qdrant (#367) ---------------------------------------------------------------
# Its API, as root, since the key file is root's alone: the key reaches curl
# as a header file from a process substitution, never as an argument, which
# /proc would show. A key file of - means none. The URL goes last.
qdrant_api() {  # <url> <key-file> <seconds> <curl arguments>...
  local _qa_u=$1 _qa_k=$2 _qa_t=$3
  shift 3
  # The script runs as root, in bash: its expansions are its own.
  # shellcheck disable=SC2016
  as_root bash -c 'u=$1 k=$2 t=$3
shift 3
if [ "$k" = - ]; then exec curl -sS --fail-with-body --max-time "$t" "$@" "$u"; fi
if [ ! -r "$k" ]; then echo "the key file $k can'"'"'t be read" >&2; exit 2; fi
curl -sS --fail-with-body --max-time "$t" -H @<(printf "api-key: %s\n" "$(cat -- "$k")") "$@" "$u"' \
    bash "$_qa_u" "$_qa_k" "$_qa_t" "$@"
}

# Each collection's exact point count, one "<collection> <count>" line each,
# sorted by name. 1 when any can't be read, with QC_WHY saying which.
qdrant_counts() {  # <var> <url> <key-file>
  local _qc_o _qc_n _qc_c _qc_all="" _qc_names
  QC_WHY=""
  capture _qc_o qdrant_api "$2/collections" "$3" 30
  if [ "$CAP_RC" -ne 0 ]; then
    QC_WHY="GET /collections failed (exit $CAP_RC${CAP_ERR:+: $CAP_ERR})"
    return 1
  fi
  case $_qc_o in
    *'"collections"'*) ;;
    *)
      QC_WHY="GET /collections answered no list of collections"
      return 1 ;;
  esac
  _qc_names=$(printf '%s\n' "$_qc_o" | grep -o '"name": *"[^"]*"' | sed 's/.*"\([^"]*\)"$/\1/' | LC_ALL=C sort) || _qc_names=""
  while IFS= read -r _qc_c; do
    [ -n "$_qc_c" ] || continue
    capture _qc_n qdrant_api "$2/collections/$_qc_c/points/count" "$3" 120 \
      -X POST -H 'Content-Type: application/json' -d '{"exact": true}'
    if [ "$CAP_RC" -ne 0 ]; then
      QC_WHY="counting $_qc_c's points failed (exit $CAP_RC${CAP_ERR:+: $CAP_ERR})"
      return 1
    fi
    _qc_n=$(printf '%s\n' "$_qc_n" | grep -o '"count": *[0-9][0-9]*' | grep -o '[0-9][0-9]*$') || _qc_n=""
    if ! is_int "$_qc_n"; then
      QC_WHY="counting $_qc_c's points answered no count"
      return 1
    fi
    _qc_all="$_qc_all$_qc_c $_qc_n"$'\n'
  done <<<"$_qc_names"
  printf -v "$1" '%s' "$_qc_all"
}

# The file of counts a run's recovery point took of a Qdrant unit, from the
# record's counts line, or empty.
qdrant_counts_path() {  # <var> <record text> <unit>
  local _qp_k _qp_e _qp_u _qp_r _qp_p=""
  while read -r _qp_k _qp_e _qp_u _qp_r; do
    [ "$_qp_k $_qp_e" = "counts qdrant" ] || continue
    unit_name _qp_u "$_qp_u"
    if [ "$_qp_u" = "$3" ]; then _qp_p=$_qp_r; fi
  done <<<"$2"
  printf -v "$1" '%s' "$_qp_p"
}

# A Qdrant after a restart, against the counts its recovery point took.
# Clients may still be writing, so a count may move either way: only a
# collection gone or emptied is a loss, and counts that can't be read fail.
# QL_OK 1 or 0, with QL_WHY saying what.
qdrant_loss() {  # <url> <key-file> <the counts before>
  local _ql_now _ql_c _ql_n _ql_m _ql_c2 _ql_n2 _ql_bad="" _ql_moved=0 _ql_k=0
  QL_OK=0 QL_WHY=""
  if ! qdrant_counts _ql_now "$1" "$2"; then
    QL_WHY="its counts couldn't be read: $QC_WHY"
    return 0
  fi
  while read -r _ql_c _ql_n; do
    [ -n "$_ql_c" ] || continue
    _ql_k=$((_ql_k + 1)) _ql_m=""
    while read -r _ql_c2 _ql_n2; do
      if [ "$_ql_c2" = "$_ql_c" ]; then _ql_m=$_ql_n2; fi
    done <<<"$_ql_now"
    if [ -z "$_ql_m" ]; then
      _ql_bad="$_ql_bad $_ql_c (gone; it held $_ql_n)"
    elif [ "$_ql_m" -eq 0 ] && [ "$_ql_n" -gt 0 ]; then
      _ql_bad="$_ql_bad $_ql_c (emptied; it held $_ql_n)"
    elif [ "$_ql_m" != "$_ql_n" ]; then
      _ql_moved=$((_ql_moved + 1))
    fi
  done <<<"$3"
  if [ -n "$_ql_bad" ]; then
    QL_WHY="lost against the recovery point's counts:$_ql_bad"
    return 0
  fi
  QL_OK=1
  QL_WHY="each of the $_ql_k collections the recovery point counted is there and not emptied; $_ql_moved counts moved, as client writes move them"
}

# Which server a Redis unit runs, and so which client and RDB checker it
# takes (#706): Ubuntu's valkey-server renames them, and its valkey-tools
# ships valkey-cli and valkey-check-rdb, no redis-cli (measured, 7.2.14);
# valkey-redis-compat adds redis-cli and redis-check-rdb as links to them,
# and removes redis-server and redis-tools. The server is, first found:
# - the unit's ExecStart path=, what systemd executes: an @ prefix shows
#   argv[0] as anything (@/usr/bin/valkey-server redis-server ... shows
#   argv[]=redis-server), and argv[0] only where path= names neither;
# - through env, the first word after its options and assignments;
# - through a wrapper that names neither, its running main process's
#   binary, /proc/<MainPID>/exe, which reads *-check-rdb: noble links each
#   server to it;
# - else the unit's name: valkey where it starts with valkey (CR 2827).
# Of several ExecStart lines (Type=oneshot), systemctl show prints each,
# and the last, which unit_show keeps, decides. The one place the choice
# is made: redis_conf calls it, and so redis_conn, the chain and the
# probe take what it says. It leaves U_ExecStart set, and returns
# unit_show's status. RE_FROM is run where the unit's command or process
# named the server, name where only its name did (CR 2836).
RE_ENGINE="" RE_CLI="" RE_CHECK_RDB="" RE_FROM=""
_re_server() {  # <var> <word>: valkey or redis where WORD's basename is that server
  case ${2##*/} in
    valkey-server*) printf -v "$1" '%s' valkey ;;
    redis-server*) printf -v "$1" '%s' redis ;;
    *) printf -v "$1" '%s' "" ;;
  esac
}
redis_engine() {  # <unit>
  local _re_e="" _re_rc=0 _re_p="" _re_w _re_skip=0 _re_x
  local -a _re_a=()
  unit_show "$1" ExecStart MainPID || _re_rc=$?
  if [[ $U_ExecStart == *path=* ]]; then
    _re_p=${U_ExecStart#*path=}
    _re_p=${_re_p%% *}
    _re_server _re_e "$_re_p"
  fi
  if [ -z "$_re_e" ] && [[ $U_ExecStart == *argv[]=* ]]; then
    _re_w=${U_ExecStart#*argv[]=}
    read -r -a _re_a <<<"${_re_w%% ;*}" || true
    if [ "${_re_p##*/}" = env ] || [ "${_re_a[0]##*/}" = env ]; then
      for _re_w in "${_re_a[@]:1}"; do
        if [ "$_re_skip" -eq 1 ]; then _re_skip=0; continue; fi
        case $_re_w in
          -u | -C | --unset | --chdir) _re_skip=1 ;;
          -* | *=*) ;;
          *) _re_server _re_e "$_re_w"; break ;;
        esac
      done
    elif [ "${#_re_a[@]}" -gt 0 ]; then
      _re_server _re_e "${_re_a[0]}"
    fi
  fi
  if [ -z "$_re_e" ] && is_int "$U_MainPID" && [ "$U_MainPID" -gt 0 ]; then
    _re_x=$(readlink -- "$P_ROOT/proc/$U_MainPID/exe" 2>/dev/null) ||
      _re_x=$(as_root readlink -- "$P_ROOT/proc/$U_MainPID/exe" 2>/dev/null) || _re_x=""
    # Noble's redis-server and valkey-server are links to their
    # *-check-rdb, the one binary, so that's what exe reads (measured).
    _re_x=${_re_x% (deleted)}
    case ${_re_x##*/} in
      valkey-check-rdb) _re_e=valkey ;;
      redis-check-rdb) _re_e=redis ;;
      *) _re_server _re_e "$_re_x" ;;
    esac
  fi
  RE_FROM=run
  if [ -z "$_re_e" ]; then
    RE_FROM=name
    case ${1##*/} in
      valkey*) _re_e=valkey ;;
      *) _re_e=redis ;;
    esac
  fi
  RE_ENGINE=$_re_e RE_CLI=$_re_e-cli RE_CHECK_RDB=$_re_e-check-rdb
  return "$_re_rc"
}

# What a Redis unit's config file and its own arguments set, which Redis
# takes over the file's: a second Redis may share the file and set its own
# --port (#379). The file is read as root: it's redis's own, and may hold a
# password. Redis reads a key in any case; read drops the leading space.
# - RC_SAVE is on unless the last save line is "": with no save line Redis
#   keeps its default save points, and save lines add up (measured on 7.0).
# - RC_ACL is 1 where an aclfile or a user line sets the users: requirepass
#   then isn't what logs in, and a login with it only adds to ACL LOG.
#   RC_ACL_WHY says which, for a message: host 6's redis.conf had an inline
#   user line and no aclfile, and a refusal naming an aclfile sent its owner
#   looking for one (#458).
# - RC_INCLUDE is 1 where an include line may set any of it, RC_INCLUDE_IN
#   says where the first one is, and RC_READ is 0 where the unit names a
#   file root couldn't read. An included file isn't read.
RC_CONF="" RC_PORT="" RC_BIND="" RC_SOCK="" RC_LOGFILE="" RC_DIR="" RC_DBFILENAME=""
RC_SAVE="" RC_AOF="" RC_ACL=0 RC_ACL_WHY="" RC_INCLUDE=0 RC_INCLUDE_IN="" RC_READ=1
_RC_ACLFILE=0 _RC_USER_IN=""
# unit_show sets them by name.
U_ExecStart="" U_MainPID=""
_rc_unq() {  # <var> <value>: one pair of quotes off, as Redis reads it
  local _ru=$2
  case $_ru in
    \"*\") _ru=${_ru#\"} _ru=${_ru%\"} ;;
    \'*\') _ru=${_ru#\'} _ru=${_ru%\'} ;;
  esac
  printf -v "$1" '%s' "$_ru"
}
_rc_set() {  # <key> <value> <where it's set, for a message>
  local _rs
  _rc_unq _rs "$2"
  case $1 in
    [Pp][Oo][Rr][Tt]) RC_PORT=$_rs ;;
    [Bb][Ii][Nn][Dd]) RC_BIND=${_rs#-} ;;
    [Uu][Nn][Ii][Xx][Ss][Oo][Cc][Kk][Ee][Tt]) RC_SOCK=$_rs ;;
    [Ll][Oo][Gg][Ff][Ii][Ll][Ee]) RC_LOGFILE=$_rs ;;
    [Dd][Ii][Rr]) RC_DIR=$_rs ;;
    [Dd][Bb][Ff][Ii][Ll][Ee][Nn][Aa][Mm][Ee]) RC_DBFILENAME=$_rs ;;
    [Ss][Aa][Vv][Ee]) if [ -n "$_rs" ]; then RC_SAVE=on; else RC_SAVE=off; fi ;;
    [Aa][Pp][Pp][Ee][Nn][Dd][Oo][Nn][Ll][Yy])
      case $_rs in [Yy][Ee][Ss]) RC_AOF=yes ;; *) RC_AOF=no ;; esac ;;
    [Aa][Cc][Ll][Ff][Ii][Ll][Ee]) RC_ACL=1 _RC_ACLFILE=1 ;;
    [Uu][Ss][Ee][Rr]) RC_ACL=1 _RC_USER_IN=${_RC_USER_IN:-$3} ;;
    [Ii][Nn][Cc][Ll][Uu][Dd][Ee]) RC_INCLUDE=1 RC_INCLUDE_IN=${RC_INCLUDE_IN:-$3} ;;
  esac
}
redis_conf() {  # <unit>
  local _rf_t="" _rf_w _rf_l _rf_k _rf_v _rf_i
  local -a _rf_a=()
  RC_CONF="" RC_PORT="" RC_BIND="" RC_SOCK="" RC_LOGFILE="" RC_DIR=""
  RC_DBFILENAME=dump.rdb RC_SAVE=on RC_AOF=no RC_ACL=0 RC_ACL_WHY="" RC_INCLUDE=0 RC_INCLUDE_IN="" RC_READ=1
  _RC_ACLFILE=0 _RC_USER_IN=""
  if redis_engine "$1"; then
    _rf_t=${U_ExecStart#*argv[]=}
    _rf_t=${_rf_t%% ;*}
    read -r -a _rf_a <<<"$_rf_t" || true
    for _rf_w in ${_rf_a[@]+"${_rf_a[@]}"}; do
      case $_rf_w in /*.conf) RC_CONF=$_rf_w ;; esac
    done
  fi
  if [ -n "$RC_CONF" ]; then
    capture _rf_t as_root cat -- "$P_ROOT$RC_CONF"
    if [ "$CAP_RC" -ne 0 ]; then RC_READ=0 _rf_t=""; fi
    while IFS= read -r _rf_l; do
      read -r _rf_k _rf_v _rf_w <<<"$_rf_l" || true
      case $_rf_k in '' | '#'*) continue ;; esac
      _rc_set "$_rf_k" "$_rf_v" "$RC_CONF"
    done <<<"$_rf_t"
  fi
  for ((_rf_i = 0; _rf_i < ${#_rf_a[@]}; _rf_i++)); do
    _rf_w=${_rf_a[_rf_i]}
    case $_rf_w in
      --port | --bind | --unixsocket | --logfile | --dir | --dbfilename | --save | --appendonly | --aclfile | --user | --include)
        # An empty argument (--save "") reads as none at all: the next
        # word is then another option, not its value.
        _rf_v=${_rf_a[_rf_i + 1]:-}
        case $_rf_v in --*) _rf_v="" ;; esac
        _rc_set "${_rf_w#--}" "$_rf_v" "$1's ExecStart" ;;
    esac
  done
  if [ "$_RC_ACLFILE" -eq 1 ] && [ -n "$_RC_USER_IN" ]; then
    RC_ACL_WHY="its aclfile and a user line in $_RC_USER_IN set the users"
  elif [ "$_RC_ACLFILE" -eq 1 ]; then
    RC_ACL_WHY="its aclfile sets the users"
  elif [ -n "$_RC_USER_IN" ]; then
    RC_ACL_WHY="a user line in $_RC_USER_IN sets the users"
  fi
}

# The client's words for the address redis_conf read: its socket, or the
# address its file binds, the loopback where that's a wildcard or unset,
# and its port, 6379 where unset (#379). RA_ARGS, which redis_conn and the
# probe's INFO both use (CR 2828); RA_PORT, the port, or empty for a
# socket.
RA_ARGS=() RA_PORT=""
redis_addr() {
  local _ra_b=$RC_BIND
  case $_ra_b in '' | '*' | 0.0.0.0 | '::' | '::*') _ra_b=127.0.0.1 ;; esac
  if [ -n "$RC_SOCK" ]; then
    RA_ARGS=(-s "$RC_SOCK") RA_PORT=""
  else
    RA_PORT=$RC_PORT
    is_int "$RA_PORT" || RA_PORT=6379
    RA_ARGS=(-h "$_ra_b" -p "$RA_PORT")
  fi
}

# How a Redis persists what it holds, from redis_conf: aof under appendonly
# yes, rdb with save points and no AOF, none with neither, and unknown where
# an include, or a file root couldn't read, may say otherwise.
redis_persistence() {  # <var>
  local _rp=none
  if [ "$RC_READ" -eq 0 ] || [ "$RC_INCLUDE" -eq 1 ]; then
    _rp=unknown
  elif [ "$RC_AOF" = yes ]; then
    _rp=aof
  elif [ "$RC_SAVE" = on ]; then
    _rp=rdb
  fi
  printf -v "$1" '%s' "$_rp"
}

# The origins that are Ubuntu's or Canonical's own: they need no knob
# policy, and carry no exposure (CR 1959).
FIRST_PARTY_ORIGINS="Ubuntu UbuntuESM UbuntuESMApps Canonical"

# A package's class from an Inst line's origins: security, updates, esm,
# third-party:<origin> or ubuntu-other. Shared with apply.sh, which classes
# what the bulk holds from the lists it refreshed (CR 2552).
class_of() {  # <var> <origins, ", "-separated>
  local _c_o _c_rest=$2 _c_origin _c_archive _c_sec=0 _c_esm=0 _c_upd=0 _c_ubu=0 _c_third=""
  while [ -n "$_c_rest" ]; do
    _c_o=${_c_rest%%, *}
    if [ "$_c_o" = "$_c_rest" ]; then _c_rest=""; else _c_rest=${_c_rest#*, }; fi
    _c_origin=${_c_o%%:*}
    _c_archive=${_c_o##*/}
    case $_c_origin in
      UbuntuESM | UbuntuESMApps) _c_esm=1 ;;
      Ubuntu)
        _c_ubu=1
        case $_c_archive in *-security) _c_sec=1 ;; *-updates) _c_upd=1 ;; esac ;;
      *)
        # Canonical's own origin is first party, as read_origins and the
        # exposure check read it, so it's never third-party: (#609). No lane
        # takes it and no knob line names it, so it's ubuntu-other, with
        # Ubuntu's release, backports and proposed pockets, whatever its
        # archive: the Ubuntu Cloud Archive's is jammy-updates (its Release
        # file, read 2026-11-14), and the maintenance lane takes o=Ubuntu's.
        if in_words "$_c_origin" "$FIRST_PARTY_ORIGINS"; then
          _c_ubu=1
        else
          _c_third=${_c_third:-$_c_origin}
        fi ;;
    esac
  done
  if [ "$_c_esm" -eq 1 ]; then printf -v "$1" esm
  elif [ "$_c_sec" -eq 1 ]; then printf -v "$1" security
  elif [ "$_c_upd" -eq 1 ]; then printf -v "$1" updates
  elif [ -n "$_c_third" ] && [ "$_c_ubu" -eq 0 ]; then printf -v "$1" 'third-party:%s' "${_c_third// /_}"
  else printf -v "$1" ubuntu-other
  fi
}

# apt-get -s prints a candidate's releases in an Inst line's parentheses as
# apt's RelStr: "<Label>:" where the Release file has a Label, then
# "<Version>/<Archive>", "<Archive>", or with no Archive the site. That's
# the Label, and a knob's origin lines, o= and the origin: findings name the
# Origin (#695). Measured on noble, apt 2.8.3, 2026-11-23:
#   the ondrej/php PPA  "PPA for PHP (deprecated):24.04/noble"  o=LP-PPA-ondrej-php
#   packages.sury.org   "noble" (no Label)                      o=deb.sury.org
#   Docker              "Docker CE:noble"                       o=Docker
# So each is mapped back to its o=, from the release lines of apt-cache
# policy (POLICY, its output) read from the same lists: each prints the l=,
# v= and a= that make up the text, and the origin line under it the site.
# REL_MAP holds a line "<text>US<o=>:<the text after its Label>" for each,
# with nothing after US where the release has no o=, or where two print
# the same text with different ones: two Label-less repos on one suite.
# Built once per policy.
REL_MAP="" REL_MAP_OF="" REL_MAP_BUILT=0
rel_map() {  # <policy output>
  local _rm_l _rm_v _rm_o="" _rm_lb="" _rm_ve="" _rm_a="" _rm_site="" _rm_i _rm_in=0
  local _rm_us=$'\x1f'
  local -a _rm_kv=() _rm_keys=() _rm_vals=()
  if [ "$REL_MAP_BUILT" -eq 1 ] && [ "$1" = "$REL_MAP_OF" ]; then return 0; fi
  # A release line's record ends at the next line that isn't its origin
  # line: a file: repo's site is empty, and apt-cache policy prints no
  # origin line for it (noble, apt 2.8.3, 2026-11-23; CR 2772).
  while IFS= read -r _rm_l; do
    case $_rm_l in
      *" release "*)
        _rel_map_add
        _rm_o="" _rm_lb="" _rm_ve="" _rm_a="" _rm_site="" _rm_in=1
        IFS=, read -r -a _rm_kv <<<"${_rm_l#*release }"
        for _rm_v in ${_rm_kv[@]+"${_rm_kv[@]}"}; do
          case $_rm_v in
            o=*) _rm_o=${_rm_v#o=} ;;
            l=*) _rm_lb=${_rm_v#l=} ;;
            v=*) _rm_ve=${_rm_v#v=} ;;
            a=*) _rm_a=${_rm_v#a=} ;;
          esac
        done ;;
      *" origin "*)
        if [ "$_rm_in" -eq 1 ]; then _rm_site=${_rm_l#*origin }; fi
        _rel_map_add ;;
      *) _rel_map_add ;;
    esac
  done <<<"$1"
  _rel_map_add
  REL_MAP=$'\n'
  for _rm_i in ${_rm_keys[@]+"${!_rm_keys[@]}"}; do
    REL_MAP="$REL_MAP${_rm_keys[$_rm_i]}$_rm_us${_rm_vals[$_rm_i]}"$'\n'
  done
  REL_MAP_OF=$1 REL_MAP_BUILT=1
}

# rel_map's record, ended: its text as apt-get -s prints it, keyed to its
# o=. With no Archive, apt prints the site, or "localhost" where it has
# none: a file: repo whose Release file names no Suite (measured as above).
# A release with no o= is recorded too, with nothing to map to, so a repo
# with one that prints the same text can't claim its packages (CR 2782).
# Reads and sets rel_map's locals.
_rel_map_add() {
  local _ra_t _ra_k _ra_v _ra_x="" _ra_i
  [ "$_rm_in" -eq 1 ] || return 0
  _rm_in=0
  if [ -z "$_rm_a" ]; then
    _ra_t=${_rm_site:-localhost}
  elif [ -n "$_rm_ve" ]; then
    _ra_t=$_rm_ve/$_rm_a
  else
    _ra_t=$_rm_a
  fi
  _ra_k=${_rm_lb:+$_rm_lb:}$_ra_t
  _ra_v=${_rm_o:+$_rm_o:$_ra_t}
  for _ra_i in ${_rm_keys[@]+"${!_rm_keys[@]}"}; do
    if [ "${_rm_keys[$_ra_i]}" = "$_ra_k" ]; then _ra_x=$_ra_i; fi
  done
  if [ -z "$_ra_x" ]; then
    _rm_keys+=("$_ra_k") _rm_vals+=("$_ra_v")
  elif [ "${_rm_vals[$_ra_x]}" != "$_ra_v" ]; then
    _rm_vals[_ra_x]=""
  fi
}

# The candidate's releases in an Inst line ("Inst <pkg> [<old>] (<new>
# <release>, <release> [<arch>])", or what follows <pkg>), each as
# "<o=>:<the text after its Label>", for class_of. A Label may hold spaces and
# a ")", so the line is cut at its last ")", then the arch comes off: where
# a package breaks another, apt adds " []" or " [<pkg>:<arch> ]" after the
# paren, which holds no ")" (noble, apt 2.8.3, 2026-11-23; CR 2764). A release
# whose text no release line prints, or two origins print, keeps apt's own
# text: class_of then keys it on the Label, as before #695. So does every
# release where the policy is empty or unread.
INST_AMBIG=""  # a text inst_origins read that two repos print alike, or empty
inst_origins() {  # <var> <Inst line> <policy output>
  local _io_r=$2 _io_e _io_o _io_out="" _io_us=$'\x1f' _io_nl=$'\n'
  INST_AMBIG=""
  case $_io_r in *"("*) ;; *)
    printf -v "$1" '%s' ""
    return 0 ;;
  esac
  _io_r=${_io_r#*(}
  _io_r=${_io_r%)*}
  _io_r=${_io_r% \[*\]}
  case $_io_r in *" "*) _io_r=${_io_r#* } ;; *) _io_r="" ;; esac
  rel_map "$3"
  while [ -n "$_io_r" ]; do
    _io_e=${_io_r%%, *}
    if [ "$_io_e" = "$_io_r" ]; then _io_r=""; else _io_r=${_io_r#*, }; fi
    _io_o=""
    case $REL_MAP in *"$_io_nl$_io_e$_io_us"*)
      _io_o=${REL_MAP#*"$_io_nl$_io_e$_io_us"}
      _io_o=${_io_o%%"$_io_nl"*}
      [ -n "$_io_o" ] || INST_AMBIG=$_io_e ;;
    esac
    _io_out="$_io_out, ${_io_o:-$_io_e}"
  done
  printf -v "$1" '%s' "${_io_out#, }"
}

# A package's class from its Inst line, keyed on its repo's o= (#695).
inst_class() {  # <var> <Inst line> <policy output>
  local _ic_o
  inst_origins _ic_o "$2" "$3"
  class_of "$1" "$_ic_o"
}

# A package's class in a simulation, from its Inst line, or empty where the
# simulation doesn't list it. Without the policy, keyed on apt's Label.
sim_class() {  # <var> <package> <simulation> [<policy output>]
  local _sk_k _sk_p _sk_r
  printf -v "$1" '%s' ""
  while read -r _sk_k _sk_p _sk_r; do
    if [ "$_sk_k" != Inst ] || [ "$_sk_p" != "$2" ]; then continue; fi
    case $_sk_r in *"("*) ;; *) return 0 ;; esac
    inst_class "$1" "$_sk_r" "${4-}"
    return 0
  done <<<"$3"
}

# The candidate version a simulation would install, or empty: probe.sh's
# own (SIM_DIST_OUT), or the one given.
sim_candidate() {  # <var> <package> [<simulation>]
  local _sc_k _sc_p _sc_r _sc_v=""
  while read -r _sc_k _sc_p _sc_r; do
    if [ "$_sc_k" != Inst ] || [ "$_sc_p" != "$2" ]; then continue; fi
    case $_sc_r in "["*) _sc_r=${_sc_r#*] } ;; esac
    case $_sc_r in "("*) _sc_v=${_sc_r#(} _sc_v=${_sc_v%% *} ;; esac
    break
  done <<<"${3-$SIM_DIST_OUT}"
  printf -v "$1" '%s' "$_sc_v"
}

# The candidate version of each pending package a hold group's globs take,
# from an apt-get -s dist-upgrade's Inst lines ("Inst <pkg> [<old>] (<new>
# <origin> [<arch>])"), as "<pkg>=<version>" words: so a held step's version
# can be told from the one the dry run counted (#383).
hold_group_versions() {  # <var> <simulation>
  local _hv="" _hk _hp _hr _hx _hg
  local -a _hf=()
  while read -r _hk _hp _hr; do
    case $_hk:$_hr in Inst:"["*"("*) ;; *) continue ;; esac
    _hx=${_hr#*(}
    _hx=${_hx%% *}
    for _hg in ${KNOB_HOLD[@]+"${KNOB_HOLD[@]}"}; do
      IFS=$KNOB_US read -r -a _hf <<<"$_hg"
      if glob_match "$_hp" "${_hf[1]}"; then
        _hv="$_hv $_hp=$_hx"
        break
      fi
    done
  done <<<"$2"
  printf -v "$1" '%s' "${_hv# }"
}

# The bulk's share of a selection: BS_TAKE, the packages no hold group's
# globs take, and BS_STEPS, each held step that takes the others, in the
# order the selection names them (#607).
BS_TAKE="" BS_STEPS=""
bulk_split() {  # <package words>
  local _bp _bg _bs
  local -a _bf=()
  BS_TAKE="" BS_STEPS=""
  for _bp in $1; do
    _bs=""
    for _bg in ${KNOB_HOLD[@]+"${KNOB_HOLD[@]}"}; do
      IFS=$KNOB_US read -r -a _bf <<<"$_bg"
      if glob_match "$_bp" "${_bf[1]}"; then
        _bs=${_bf[0]}
        break
      fi
    done
    if [ -z "$_bs" ]; then
      BS_TAKE="$BS_TAKE $_bp"
    elif ! in_words "$_bs" "$BS_STEPS"; then
      BS_STEPS="$BS_STEPS $_bs"
    fi
  done
  BS_TAKE=${BS_TAKE# } BS_STEPS=${BS_STEPS# }
}

# What a bulk that takes nothing says, naming the held steps that take its
# lane's packages, so the owner approves it as bookkeeping: co-index's and
# broker's did, unannounced (#607). Empty for a bulk that takes something,
# or that nothing is selected for.
takes_nothing_note() {  # <var> <the bulk's take> <the held steps>
  local _tn=""
  if [ -z "$2" ] && [ -n "$3" ]; then
    case $3 in
      *" "*) _tn="held steps $3 take them" ;;
      *) _tn="held step $3 takes them" ;;
    esac
    _tn="the bulk takes nothing: every package it would upgrade is in a hold group. It refreshes the lists, records the before-versions and places the holds; $_tn (#607)"
  fi
  printf -v "$1" '%s' "$_tn"
}

# A package's version in hold_group_versions' words, or empty.
version_in() {  # <var> <words> <package>
  local _vw _vv=""
  for _vw in $2; do
    if [ "${_vw%%=*}" = "$3" ]; then _vv=${_vw#*=}; fi
  done
  printf -v "$1" '%s' "$_vv"
}

# A Redis after a restart, from its own log (#380): the process before it
# logged a clean shutdown, and its main process loaded what it persists and
# is ready. Its logfile, read as root, or the unit's journal where the file
# sets none: broker's logs to a file, so a journal-based check would read
# an empty pass. A run starts at its main PID's banner, or at its first line
# after another process's: a PID may come round again after a boot. The
# process before it is the last main-process line ahead of that. Under
# appendonly yes, "Creating AOF base file ... on server start" means it
# found no AOF, so it loaded nothing; "keys loaded" counts the base alone,
# not the incr, so it's no total (both measured on 7.0).
# RL_OK 1, 0, or "" where it couldn't be read, with RL_WHY; RL_READY 1 once
# it logged that it's ready.
RL_OK="" RL_WHY="" RL_READY=0
redis_restart_check() {  # <unit>
  local _rl_pid="" _rl_src _rl_log _rl_p _rl_o _rl_s=0 _rl_l=0 _rl_c=0 _rl_prev=""
  RL_OK="" RL_WHY="" RL_READY=0
  redis_conf "$1"
  redis_persistence _rl_p
  if unit_show "$1" MainPID; then _rl_pid=$U_MainPID; fi
  if ! is_int "$_rl_pid" || [ "$_rl_pid" -eq 0 ]; then
    RL_OK=0 RL_WHY="$1 has no main process: it isn't running"
    return 0
  fi
  if [ -n "$RC_LOGFILE" ]; then
    case $RC_LOGFILE in
      /*) ;;
      *)
        RL_WHY="its logfile, $RC_LOGFILE, is relative to a directory the file doesn't say: read it by hand"
        return 0 ;;
    esac
    _rl_src=$RC_LOGFILE
    capture _rl_log as_root tail -n 5000 -- "$P_ROOT$RC_LOGFILE"
  else
    _rl_src="$1's journal"
    capture _rl_log as_root journalctl -u "$1" -o cat --no-pager -n 5000
  fi
  if [ "$CAP_RC" -ne 0 ]; then
    RL_WHY="$_rl_src couldn't be read as root"
    return 0
  fi
  _rl_o=$(printf '%s\n' "$_rl_log" | awk -v p="$_rl_pid" '
    /^[0-9]+:[A-Z] / {
      q = substr($0, 1, index($0, ":") - 1)
      r = substr($0, index($0, ":") + 1, 1)
      if (q == p && (cur != 1 || index($0, " is starting oO0"))) {
        cur = 1; start = 1; loaded = 0; ready = 0; created = 0; prev = lastm
      }
      if (q == p) {
        if (index($0, "DB loaded from")) loaded = 1
        if (index($0, "Ready to accept connections")) ready = 1
        if (index($0, "Creating AOF base file") && index($0, "on server start")) created = 1
        if (r == "M") lastm = $0
      } else if (r == "M") {
        cur = 0; lastm = $0
      }
    }
    END {
      sub(/^[0-9]+:[A-Z] [0-9]+ [A-Za-z]+ [0-9]+ [0-9:.]+ . /, "", prev)
      print start + 0, loaded + 0, ready + 0, created + 0
      print prev
    }') || _rl_o=""
  read -r _rl_s _rl_l RL_READY _rl_c <<<"${_rl_o%%$'\n'*}" || true
  case $_rl_o in *$'\n'*) _rl_prev=${_rl_o#*$'\n'} ;; esac
  if [ "${_rl_s:-0}" != 1 ]; then
    RL_WHY="$_rl_src holds no line from its main process, $_rl_pid: read where it logs by hand"
    return 0
  fi
  RL_OK=0
  if [ -n "$_rl_prev" ] && [[ $_rl_prev != *"ready to exit"* ]]; then
    RL_WHY="the Redis before process $_rl_pid didn't log a clean shutdown: its last line in $_rl_src was \"$_rl_prev\""
  elif [ "$_rl_c" = 1 ]; then
    RL_WHY="process $_rl_pid found no AOF at its start, so it loaded nothing (\"Creating AOF base file ... on server start\" in $_rl_src): restore it from the recovery point (datastores.md)"
  elif [ "$_rl_l" != 1 ] && { [ "$_rl_p" = aof ] || [ "$_rl_p" = rdb ]; }; then
    RL_WHY="process $_rl_pid logged no \"DB loaded from\" in $_rl_src, though it persists by $_rl_p: it loaded nothing"
  elif [ "$RL_READY" != 1 ]; then
    RL_WHY="process $_rl_pid hasn't logged \"Ready to accept connections\" in $_rl_src"
  elif [ -z "$_rl_prev" ]; then
    RL_OK="" RL_WHY="process $_rl_pid loaded its data and is ready, but $_rl_src holds nothing from the process before it, so its shutdown wasn't read"
  else
    RL_OK=1
    if [ "$_rl_p" = none ]; then
      RL_WHY="the process before it logged a clean shutdown, and process $_rl_pid is ready; it persists nothing, so it loaded nothing"
    else
      RL_WHY="the process before it logged a clean shutdown (ready to exit), and process $_rl_pid loaded its data (DB loaded from) and is ready, in $_rl_src"
    fi
  fi
}
