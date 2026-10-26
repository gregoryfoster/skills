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
  origin_split KEEP SKIP NAMES SIM  the pending packages from those origins,
                            and every other one
  rss_timer FILE            TIMER := GNU time's words to record a command's
                            max RSS in FILE, or none where there's no GNU time
  rss_of VAR TEXT           VAR := the max RSS a TIMER file's TEXT holds
  APT_SIM_PHASED            the apt-get option that shows phased updates in a
                            simulation: unattended-upgrade takes them all
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
  redis_conf UNIT           RC_* := what a Redis unit's file, read as root,
                            and its own arguments set: port, bind, socket,
                            logfile, dir, dbfilename, save, appendonly, and
                            whether an aclfile or an include is there
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

# apt's resolver defers a phased update on a machine outside its phase, so
# apt-get -s leaves it out. unattended-upgrade 2.9.1 takes it whatever the
# phase: of 40 machine ids on noble, apt-get -s took a 10%-phased -updates
# package for 3, and unattended-upgrade for all 40 (2026-10-06, #354). So a
# simulation that stands for what a lane takes shows them all.
APT_SIM_PHASED=(-o APT::Get::Always-Include-Phased-Updates=true)

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
# the GC's own default in VERSION 2 (load_config): 85 and /.
DISK_GC_CONF=/etc/cannobserv/disk-gc/disk-gc.conf
DISK_GC_ALERT_DEFAULT=85
DISK_GC_MOUNT_DEFAULT=/
# The commands step_space reads apt and dpkg with: a caller may prefix them
# (as_root, apt_env) or add options (a scratch copy of the lists).
SS_APT_GET=(apt-get -s)
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
# unreadable file, or one whose syntax or headroom keys it would reject, is
# never read as absent. INI as Python's configparser parses it by default:
# [section] headers, each once; "key = value" or "key: value" lines, keys
# case-folded, each once per section; # and ; comments on their own line;
# an indented line continuing the value above; a [DEFAULT] key standing in
# for one a section leaves out. Other sections' keys aren't judged here:
# their values are the GC's to refuse.
disk_gc_conf() {  # GC_STATE := absent, ok or bad; GC_ALERT and GC_MOUNT when ok; GC_WHY when bad
  local _gc_t _gc_l _gc_s _gc_n=0 _gc_k _gc_v _gc_sect="" _gc_last="" _gc_sects=" " _gc_keys=" "
  local _gc_a="" _gc_ha=0 _gc_m="" _gc_hm=0 _gc_da="" _gc_hda=0 _gc_dm="" _gc_hdm=0
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
            sensor.alert_at_percent | sensor.mount | DEFAULT.alert_at_percent | DEFAULT.mount)
              GC_WHY="line $_gc_n continues [${_gc_last%%.*}] ${_gc_last#*.} onto a second line"
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
    _gc_keys="$_gc_keys$_gc_sect.$_gc_k " _gc_last=$_gc_sect.$_gc_k
    case $_gc_last in
      sensor.alert_at_percent) _gc_a=$_gc_v _gc_ha=1 ;;
      sensor.mount) _gc_m=$_gc_v _gc_hm=1 ;;
      DEFAULT.alert_at_percent) _gc_da=$_gc_v _gc_hda=1 ;;
      DEFAULT.mount) _gc_dm=$_gc_v _gc_hdm=1 ;;
    esac
  done <<<"$_gc_t"
  if [ "$_gc_ha" -eq 0 ] && [ "$_gc_hda" -eq 1 ]; then _gc_a=$_gc_da _gc_ha=1; fi
  if [ "$_gc_hm" -eq 0 ] && [ "$_gc_hdm" -eq 1 ]; then _gc_m=$_gc_dm _gc_hm=1; fi
  if [ "$_gc_ha" -eq 0 ]; then
    _gc_a=$DISK_GC_ALERT_DEFAULT
  elif ! [[ $_gc_a =~ ^[0-9]{1,3}$ ]] || [ $((10#$_gc_a)) -gt 100 ]; then
    GC_WHY="[sensor] alert_at_percent is \"$_gc_a\", not a whole percent from 0 to 100"
    return 0
  fi
  if [ "$_gc_hm" -eq 0 ]; then
    _gc_m=$DISK_GC_MOUNT_DEFAULT
  else
    case $_gc_m in
      /*[[:cntrl:]%]* | /*%*) GC_WHY="[sensor] mount is \"$_gc_m\", which the GC can't read as a path"; return 0 ;;
      /*) ;;
      *) GC_WHY="[sensor] mount is \"$_gc_m\", not an absolute path"; return 0 ;;
    esac
  fi
  GC_STATE=ok GC_ALERT=$((10#$_gc_a)) GC_MOUNT=$_gc_m
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
  # the sensor's mount, plus the install growth where that does, must stay
  # under alert_at_percent, as df reckons use: Used over Used + Available.
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
        if [ "$_sp_add" -gt 0 ] && [ $(((FS_USED + _sp_add) * 100)) -ge $((GC_ALERT * _sp_den)) ]; then
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

# What a Redis unit's config file and its own arguments set, which Redis
# takes over the file's: a second Redis may share the file and set its own
# --port (#379). The file is read as root: it's redis's own, and may hold a
# password. Redis reads a key in any case; read drops the leading space.
# - RC_SAVE is on unless the last save line is "": with no save line Redis
#   keeps its default save points, and save lines add up (measured on 7.0).
# - RC_ACL is 1 where an aclfile or a user line sets the users: requirepass
#   then isn't what logs in, and a login with it only adds to ACL LOG.
# - RC_INCLUDE is 1 where an include line may set any of it, and RC_READ is
#   0 where the unit names a file root couldn't read.
RC_CONF="" RC_PORT="" RC_BIND="" RC_SOCK="" RC_LOGFILE="" RC_DIR="" RC_DBFILENAME=""
RC_SAVE="" RC_AOF="" RC_ACL=0 RC_INCLUDE=0 RC_READ=1
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
_rc_set() {  # <key> <value>
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
    [Aa][Cc][Ll][Ff][Ii][Ll][Ee] | [Uu][Ss][Ee][Rr]) RC_ACL=1 ;;
    [Ii][Nn][Cc][Ll][Uu][Dd][Ee]) RC_INCLUDE=1 ;;
  esac
}
redis_conf() {  # <unit>
  local _rf_t="" _rf_w _rf_l _rf_k _rf_v _rf_i
  local -a _rf_a=()
  RC_CONF="" RC_PORT="" RC_BIND="" RC_SOCK="" RC_LOGFILE="" RC_DIR=""
  RC_DBFILENAME=dump.rdb RC_SAVE=on RC_AOF=no RC_ACL=0 RC_INCLUDE=0 RC_READ=1
  if unit_show "$1" ExecStart; then
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
      _rc_set "$_rf_k" "$_rf_v"
    done <<<"$_rf_t"
  fi
  for ((_rf_i = 0; _rf_i < ${#_rf_a[@]}; _rf_i++)); do
    _rf_w=${_rf_a[_rf_i]}
    case $_rf_w in
      --port | --bind | --unixsocket | --logfile | --dir | --dbfilename | --save | --appendonly | --aclfile | --include)
        # An empty argument (--save "") reads as none at all: the next
        # word is then another option, not its value.
        _rf_v=${_rf_a[_rf_i + 1]:-}
        case $_rf_v in --*) _rf_v="" ;; esac
        _rc_set "${_rf_w#--}" "$_rf_v" ;;
    esac
  done
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
      if (q == p && (cur != 1 || index($0, "Redis is starting"))) {
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
