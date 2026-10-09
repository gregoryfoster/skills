#!/usr/bin/env bash
# probe.sh — read a host's update state, read-only, and print it as JSON.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash probe.sh [--config FILE] [--host NAME] [--root DIR] [--repo DIR]
                     [--refresh-into DIR] [--dry-run-into DIR]
                     [--lane security|maintenance|origin:<origin>]
                     [--post-boot [--run DIR]] [--session-pid PID]
                     [--today YYYY-MM-DD]

Reads the host and prints one JSON object on stdout: its environment, what
updates it, the pending set by class, what an apply would touch, dormant
components, and every finding against the posture its knob declares. It
installs, removes, holds, restarts and configures nothing. The readings, and
the mistake each one prevents: references/readings.md.

Options:
  --config FILE       the knob (default: .skills/patching-hosts at the root of
                      the repo around the current directory, or in the
                      current directory outside a repo; never --repo's)
  --host NAME         whose knob sections apply (default: `hostname`; under
                      --root, DIR/etc/hostname's first word, and without one,
                      pass --host)
  --root DIR          read DIR's files instead of /'s: an image tree, or a
                      fixture. What only a running system can answer
                      (systemctl, journalctl, docker, psql, needrestart, ss,
                      redis-cli, tailscale, /proc, knob commands, among
                      others) is read only when DIR/run/systemd/system
                      exists, and then from the machine the probe runs on
  --repo DIR          the repo whose deploy/ units and docs may name an engine
                      (default: the repo around the current directory)
  --refresh-into DIR  refresh apt's lists into DIR/lists first, never into
                      /var/lib/apt/lists, and count against them (the ESM
                      count, from pro, still reads the host's own lists).
                      It also audits each service's uv.lock against OSV
                      (pending.language), which nothing else asks for
  --dry-run-into DIR  count the selection with unattended-upgrade --dry-run,
                      as root, with apt's cache in DIR/archives. It downloads
                      the whole set (290 MB and 9 minutes on one host) and
                      leaves it there for you to remove. The count is the
                      security set exactly only while pending.dry_run's
                      security_only is true; wider origins, or another lane,
                      put other packages on the same line. DIR/summary holds
                      when it began, its exit, count, wall time, lane and
                      security_only, and in the one-origin lane what it
                      would leave, which apply.sh --dry-run reads; its
                      download size,
                      memory and free disk are in the JSON. An earlier
                      summary is removed first. A dry run that doesn't run
                      (no root, a lane the knob doesn't resolve, an
                      unsimulated set, an origin's site unread) still exits
                      0: it's a finding with id dry-run, and leaves no
                      summary
  --lane LANE         the dry run's selection, as apply.sh --lane takes it:
                      security (the default), what the host's
                      unattended-upgrades origins take; maintenance, which
                      adds Ubuntu's -updates and each origin the knob
                      follows; or origin:<origin>, one followed origin and
                      nothing else. With --dry-run-into only
  --post-boot         the checks after a reboot (run.md section 6), not the
                      readings before a run. Takes neither --refresh-into nor
                      --dry-run-into
  --run DIR           with --post-boot: the run whose reboot chain copied a
                      volatile journal into DIR/journal (default: the newest
                      /var/backups/patching-hosts-<UTC>). A persistent
                      journal isn't copied: the previous boot's own last
                      lines are read instead
  --session-pid PID   where the session's chain to PID 1 starts (default: the
                      probe itself)
  --today YYYY-MM-DD  the date exceptions expire against (default: today, UTC)
  -h, --help          show this help

--refresh-into and --dry-run-into need a running system: without
DIR/run/systemd/system, the probe exits 2 and reads nothing.

Top-level keys: probe, knob, environment, then updates, pending, impact and
dormant (or post_boot), then findings, excepted and not_read. A finding's
kind is one of: deviation, from the posture; leftover, from provisioning;
risk, which a run must plan around; unknown, a reading the posture depends
on that couldn't be taken or isn't set anywhere; dormant, a component
nothing uses; post-boot, a failed check after a reboot; knob, a problem with
the knob. A finding that names an exception_what, and that an unexpired
exception covers, is listed under excepted instead; one with none takes no
exception. A dormant component the owner keeps (keep:, or a prune stage) is
no finding at all: its dormant entry's verdict is kept. A reading the probe
couldn't take is null, never its default, and not_read says why.

environment.profile names the environment profile the host matches
(references/environments/) and its image generation, read from the
profile's markers. Its name is null when none matches: read SKILL.md's
"Hosts no profile matches".

Exit codes:
  0  read; act on findings. A dry run asked for may not have run: look for
     a finding with id dry-run
  2  usage error (a host name that isn't one included), an unreadable knob,
     or a library missing: nothing on stdout
  *  any other code: the probe failed; don't trust stdout
USAGE
}

config="" host="" root=/ repo="" refresh="" dryrun="" postboot=0 session_pid="" today="" lane="" run=""
repo_set=0
while [ "$#" -gt 0 ]; do
  case $1 in
    --config | --host | --root | --repo | --refresh-into | --dry-run-into | --lane | --session-pid | --today | --run)
      [ "$#" -ge 2 ] || { echo "ERROR $1 needs a value" >&2; exit 2; }
      case $1 in
        --config) config=$2 ;;
        --host) host=$2 ;;
        --root) root=$2 ;;
        --repo) repo=$2 repo_set=1 ;;
        --refresh-into) refresh=$2 ;;
        --dry-run-into) dryrun=$2 ;;
        --lane) lane=$2 ;;
        --session-pid) session_pid=$2 ;;
        --today) today=$2 ;;
        --run) run=$2 ;;
      esac
      shift 2 ;;
    --post-boot) postboot=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1 (see --help)" >&2; exit 2 ;;
  esac
done

# --- shared libraries ---------------------------------------------------------
# Resolved through a symlink chain first, as read-knob.sh does: the skill is
# usually reached through a symlinked vendor tree.
_self="${BASH_SOURCE[0]}"
_n=0
while [ -L "$_self" ] && [ "$_n" -lt 10 ]; do
  _t="$(readlink "$_self" 2>/dev/null)" || break
  case "$_t" in
    /*) _self="$_t" ;;
    *) _self="$(dirname "$_self")/$_t" ;;
  esac
  _n=$((_n + 1))
done
_libdir="$(cd "$(dirname "$_self")" 2>/dev/null && pwd -P)" || _libdir=""
for _lib in _knob-lib.sh _probe-lib.sh read-knob.sh; do
  if [ -z "$_libdir" ] || [ ! -f "$_libdir/$_lib" ]; then
    echo "ERROR $_lib not found next to $_self" >&2
    exit 2
  fi
done
# shellcheck source=_knob-lib.sh
. "$_libdir/_knob-lib.sh"
# shellcheck source=_probe-lib.sh
. "$_libdir/_probe-lib.sh"

# Every parse below reads C-locale output, and the JSON builder's '?' for a
# byte that isn't printable ASCII depends on it too.
export LC_ALL=C
# The apt timers run with no APT_CONFIG, so the probe reads what they read.
unset APT_CONFIG

for _v in "$config" "$root" "$repo" "$refresh" "$dryrun"; do
  case $_v in *[[:cntrl:]]*)
    echo "ERROR a path holds a control character" >&2
    exit 2 ;;
  esac
done
if [ ! -d "$root" ]; then
  echo "ERROR --root $root is not a directory" >&2
  exit 2
fi
root=$(cd "$root" && pwd -P)
if [ -n "$session_pid" ] && ! is_int "$session_pid"; then
  echo "ERROR --session-pid takes a process id" >&2
  exit 2
fi
case $lane in
  "" | security | maintenance | origin:?*) ;;
  *) echo "ERROR --lane takes security, maintenance or origin:<an origin the knob follows>" >&2; exit 2 ;;
esac
if [ -n "$lane" ] && [ -z "$dryrun" ]; then
  echo "ERROR --lane names the dry run's selection: it goes with --dry-run-into" >&2
  exit 2
fi
lane=${lane:-security}
if [ -n "$refresh$dryrun" ] && [ "$postboot" -eq 1 ]; then
  echo "ERROR --post-boot takes neither --refresh-into nor --dry-run-into" >&2
  exit 2
fi
if [ -n "$run" ] && [ "$postboot" -ne 1 ]; then
  echo "ERROR --run names the run whose reboot --post-boot checks: it goes with --post-boot" >&2
  exit 2
fi
case $run in "" | /*) ;; *) echo "ERROR --run takes an absolute path" >&2; exit 2 ;; esac
# Under --root, the tree's own name: never the probing machine's, whose
# knob sections aren't the tree's. A CR or blank a file ends with isn't part
# of the name.
if [ -z "$host" ]; then
  if [ "$root" = / ]; then
    host=$(hostname)
  else
    if [ -r "$root/etc/hostname" ]; then IFS= read -r host <"$root/etc/hostname" || true; fi
    host=${host#"${host%%[![:space:]]*}"}
    host=${host%%[[:space:]]*}
    if [ -z "$host" ]; then
      echo "ERROR --root $root has no readable etc/hostname naming the host: pass --host" >&2
      exit 2
    fi
  fi
fi
if [ -z "$config" ]; then
  config="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.skills/patching-hosts"
fi
if [ "$repo_set" -eq 0 ]; then
  repo=$(git rev-parse --show-toplevel 2>/dev/null) || repo=""
fi
[ -n "$today" ] || today=$(date -u +%Y-%m-%d)

# Called plainly, never in a condition: bash turns errexit off for everything
# a condition runs (read-knob.sh's note). A return of 2 exits 2 here.
knob_load "$config" "$host" "$today"
knob_json=$(bash "$_libdir/read-knob.sh" --config "$config" --host "$host" --today "$today")

probe_init "$root"
trap 'rm -rf "$P_TMP"' EXIT
SESSION_PID=${session_pid:-$$}
if [ -n "$refresh$dryrun" ] && [ "$P_LIVE" -ne 1 ]; then
  echo "ERROR --refresh-into and --dry-run-into need a running system, and ${P_ROOT:-}/run/systemd/system is absent" >&2
  exit 2
fi
# Made only now, so a refused run leaves nothing behind.
if [ -n "$refresh" ]; then
  mkdir -p "$refresh"
  refresh=$(cd "$refresh" && pwd -P)
fi
if [ -n "$dryrun" ]; then
  mkdir -p "$dryrun"
  dryrun=$(cd "$dryrun" && pwd -P)
fi

# --- helpers ------------------------------------------------------------------
# No function here ends on a bare `[ … ] && …`: a function that returns
# non-zero stops the script under errexit, wherever it is called plainly.

# dpkg-query's format fields, not shell expansions.
# shellcheck disable=SC2016
DPKG_STATUS='${db:Status-Abbrev}' DPKG_VERSION='${Version}' DPKG_PKG_STATUS='${Package} ${db:Status-Abbrev}\n' DPKG_CONFFILES='${Conffiles}\n'
# unit_show sets these by name.
U_LoadState="" U_ConditionResult="" U_Result="" U_ActiveState="" U_MainPID="" U_After=""
U_RequiredBy="" U_BoundBy="" U_NRestarts="" U_ExecMainExitTimestamp="" U_InactiveEnterTimestamp=""
U_NextElapseUSecRealtime="" U_NextElapseUSecMonotonic="" U_ActiveEnterTimestamp="" U_InactiveExitTimestamp=""

capture2() {  # <var> <cmd>...: as capture, with stderr in VAR too
  local _cv=$1 _co
  shift
  CAP_RC=0 CAP_ERR=""
  _co=$("$@" 2>&1) || CAP_RC=$?
  printf -v "$_cv" '%s' "$_co"
}

nlines() {  # <var> <text>: its count of non-empty lines
  local _nl_n=0 _nl_l
  while IFS= read -r _nl_l; do
    if [ -n "$_nl_l" ]; then _nl_n=$((_nl_n + 1)); fi
  done <<<"$2"
  printf -v "$1" '%s' "$_nl_n"
}

json_list() {  # <var> <space-separated words>: VAR := a JSON array of them
  local _jl_a="" _jl
  local -a _jl_w=()
  read -r -a _jl_w <<<"$2" || true
  for _jl in ${_jl_w[@]+"${_jl_w[@]}"}; do jpushs _jl_a "$_jl"; done
  printf -v "$1" '[%s]' "$_jl_a"
}

apt_env() {  # an apt command, reading ROOT's configuration and state
  if [ -n "$P_ROOT" ]; then APT_CONFIG=$P_TMP/apt-root.conf "$@"; else "$@"; fi
}

dpkgq() {
  if [ -n "$P_ROOT" ]; then dpkg-query --admindir="$P_ROOT/var/lib/dpkg" "$@"; else dpkg-query "$@"; fi
}

installed() {  # <package>: dpkg calls it installed
  local s
  have dpkg-query || return 1
  s=$(dpkgq -W -f "$DPKG_STATUS" "$1" 2>/dev/null) || return 1
  case $s in ii*) return 0 ;; esac
  return 1
}

jctl() {  # journalctl, as root when it can: a user reads only their own journal
  if [ "$P_PRIV" != none ]; then as_root journalctl "$@"; else journalctl "$@"; fi
}

# Whether Docker can be asked without changing the host: docker.socket starts
# dockerd on its first client, so a docker call to an idle Docker starts it,
# and restarts the idle clock a dormant verdict reads. exeuntu ships
# docker.service disabled and docker.socket enabled (read in the image,
# 2026-10-01).
docker_running() {
  live_cmd docker || return 1
  unit_show docker.service ActiveState || return 1
  [ "$U_ActiveState" = active ]
}

docker_socket_listens() {  # whether docker.socket would start dockerd on a docker call
  unit_show docker.socket ActiveState || return 1
  [ "$U_ActiveState" = active ]
}

# What Docker holds, read from its data root as root, with no daemon to ask:
# each container's restart policy from hostconfig.json, whether it was
# stopped by hand, and each named volume. The data root is daemon.json's, or
# /var/lib/docker.
DISK_CONTAINERS="" DISK_RESTARTING="" DISK_VOLUMES=""
docker_on_disk() {
  local root=/var/lib/docker r out kind pol manual
  DISK_CONTAINERS="" DISK_RESTARTING="" DISK_VOLUMES=""
  if [ -r "$P_ROOT/etc/docker/daemon.json" ]; then
    r=$(grep -o '"data-root": *"[^"]*"' "$P_ROOT/etc/docker/daemon.json" 2>/dev/null | head -n 1) || r=""
    r=${r%\"}
    r=${r##*\"}
    if [ -n "$r" ]; then root=$r; fi
  fi
  [ "$P_PRIV" != none ] || return 0
  # The script runs as root, in sh: its expansions are its own.
  # shellcheck disable=SC2016
  capture out as_root sh -c '
    cd "$1" 2>/dev/null || exit 3
    for d in containers/*/; do
      [ -f "${d}hostconfig.json" ] || continue
      p=$(grep -o "\"RestartPolicy\": *{ *\"Name\": *\"[a-z-]*\"" "${d}hostconfig.json" | head -n 1)
      p=${p%\"}
      p=${p##*\"}
      m=no
      if grep -q "\"HasBeenManuallyStopped\":true" "${d}config.v2.json" 2>/dev/null; then m=yes; fi
      echo "container ${p:-no} $m"
    done
    for v in volumes/*/; do
      if [ -d "$v" ]; then echo volume; fi
    done' sh "$P_ROOT$root"
  case $CAP_RC in
    0) ;;
    3) DISK_CONTAINERS=0 DISK_RESTARTING=0 DISK_VOLUMES=0; return 0 ;;
    *) return 0 ;;
  esac
  DISK_CONTAINERS=0 DISK_RESTARTING=0 DISK_VOLUMES=0
  while read -r kind pol manual; do
    case $kind in
      container)
        DISK_CONTAINERS=$((DISK_CONTAINERS + 1))
        # What dockerd starts again when it comes up: always, and
        # unless-stopped unless it was stopped by hand.
        case $pol/$manual in
          always/* | unless-stopped/no) DISK_RESTARTING=$((DISK_RESTARTING + 1)) ;;
        esac ;;
      volume) DISK_VOLUMES=$((DISK_VOLUMES + 1)) ;;
    esac
  done <<<"$out"
}

docker_cmd() {  # docker, then docker as root when the user isn't in its group
  if docker "$@" 2>/dev/null; then return 0; fi
  if [ "$P_PRIV" = none ]; then return 1; fi
  as_root docker "$@"
}

live_cmd() {  # <cmd>: whether a reading from the running system can be taken with it
  [ "$P_LIVE" -eq 1 ] && have "$1"
}

F_KIND=() F_ID=() F_WHAT=() F_MSG=()
finding() {  # <kind> <id> <what an exception names, or empty> <message>
  F_KIND+=("$1")
  F_ID+=("$2")
  F_WHAT+=("$3")
  F_MSG+=("$4")
}

NOT_READ=""
not_read() { jpushs NOT_READ "$1"; }

exception_for() {  # <what>: sets EX_*; returns 1 when the knob declares none
  local _r
  local -a _f=()
  EX_LINE="" EX_REVIEW="" EX_REASON="" EX_EXPIRED=""
  for _r in ${KNOB_EXCEPTION[@]+"${KNOB_EXCEPTION[@]}"}; do
    IFS=$KNOB_US read -r -a _f <<<"$_r"
    if [ "${_f[0]}" = "$1" ]; then
      EX_REVIEW=${_f[1]} EX_REASON=${_f[2]} EX_EXPIRED=${_f[3]} EX_LINE=${_f[4]}
      return 0
    fi
  done
  return 1
}

knob_units() {  # <var> <list-directive records>...: VAR := their units, space-separated
  local _ku_v=$1 _ku_r _ku_u _ku_all=""
  local -a _ku_f=()
  shift
  for _ku_r in "$@"; do
    IFS=$KNOB_US read -r -a _ku_f <<<"$_ku_r"
    unit_name _ku_u "${_ku_f[0]}"
    _ku_all="$_ku_all $_ku_u"
  done
  printf -v "$_ku_v" '%s' "${_ku_all# }"
}

if [ -n "$P_ROOT" ]; then
  printf 'Dir "%s/";\n' "$P_ROOT" >"$P_TMP/apt-root.conf"
fi
# apt never writes its binary cache here: a non-root probe can't, and the
# host's may be stale against refreshed lists.
APT_OPTS=(-o Dir::Cache::pkgcache= -o Dir::Cache::srcpkgcache=)
LISTS_DIR=$P_ROOT/var/lib/apt/lists
REFRESHED=0
LISTS_OPT=()

if [ "$P_LIVE" -ne 1 ]; then
  not_read "readings from a running system (systemctl, journalctl, docker, psql, needrestart, knob commands): ${P_ROOT:-}/run/systemd/system is absent, so nothing runs this tree"
fi
if [ "$P_PRIV" = none ]; then
  not_read "root-only readings (other users' /proc maps, needrestart, the Postgres catalogs, the whole journal): not root, and sudo -n needs a password"
fi

# --- environment ------------------------------------------------------------
BTIME="" UPTIME_DAYS="" MANAGER_DAYS=""
read_boot() {
  local o="" line at out
  if [ -r "$P_ROOT/proc/stat" ]; then
    while IFS= read -r line; do
      case $line in "btime "*) BTIME=${line#btime } ;; esac
    done <"$P_ROOT/proc/stat"
  fi
  is_int "$BTIME" || BTIME=""
  if [ -n "$BTIME" ]; then UPTIME_DAYS=$(((P_NOW - BTIME) / 86400)); fi
  iso_utc at "$BTIME"
  jaddn o btime "$BTIME"
  jaddsn o at "$at"
  # When systemd itself started: a unit never active since then has been idle
  # that long. It's later than the kernel's boot in a container, or after a
  # soft reboot.
  if live_cmd systemctl; then
    capture out systemctl show --timestamp=unix -p UserspaceTimestamp
    case $out in UserspaceTimestamp=@[0-9]*)
      out=${out#UserspaceTimestamp=@}
      out=${out%%[!0-9]*}
      MANAGER_DAYS=$(((P_NOW - out) / 86400)) ;;
    esac
  fi
  jaddn o uptime_days "$UPTIME_DAYS"
  jaddn o systemd_started_days "$MANAGER_DAYS"
  jadds o source "/proc/stat btime; who -b was wrong on three hosts"
  R_BOOT=$o
}

journal_first_line() { { jctl -q -o short-unix --no-pager 2>/dev/null || true; } | head -n 1; }

read_journal() {
  local o="" f line n storage="" ssrc="" flush flush_live="" out pc="" vc="" verdict=unknown oldest="" reach="" at
  for f in "$P_ROOT/etc/systemd/journald.conf" "$P_ROOT"/usr/lib/systemd/journald.conf.d/*.conf "$P_ROOT"/etc/systemd/journald.conf.d/*.conf; do
    [ -f "$f" ] || continue
    n=0
    while IFS= read -r line || [ -n "$line" ]; do
      n=$((n + 1))
      case $line in
        Storage=*)
          storage=${line#Storage=}
          storage=${storage%%[[:space:]]*}
          ssrc="${f#"$P_ROOT"}:$n" ;;
      esac
    done <"$f"
  done
  unit_disk_state flush systemd-journal-flush.service
  if live_cmd systemctl; then
    capture flush_live systemctl is-enabled systemd-journal-flush.service
    flush_live=${flush_live%%$'\n'*}
  fi
  for f in var/log/journal run/log/journal; do
    n=""
    if [ -d "$P_ROOT/$f" ]; then
      if [ "$P_PRIV" != none ]; then
        capture out as_root find "$P_ROOT/$f" -name '*.journal'
      else
        capture out find "$P_ROOT/$f" -name '*.journal'
      fi
      if [ "$CAP_RC" -eq 0 ]; then nlines n "$out"; fi
    elif [ "$f" = var/log/journal ]; then
      n=0
    fi
    if [ "$f" = var/log/journal ]; then pc=$n; else vc=$n; fi
  done
  # Persistent only when files are actually there: Storage=persistent with the
  # flush masked leaves /var/log/journal empty, and a reboot erases the lot
  # (address-validator's 51 days).
  if is_int "$pc" && [ "$pc" -gt 0 ]; then
    verdict=persistent
  elif [ "$storage" = volatile ] || [ "$storage" = none ]; then
    verdict=$storage
  elif [ "$flush" = masked ] || [ "$flush_live" = masked ]; then
    verdict=volatile
  elif [ "$pc" = 0 ] && is_int "$vc" && [ "$vc" -gt 0 ]; then
    verdict=volatile
  fi
  if live_cmd journalctl; then
    capture line journal_first_line
    oldest=${line%%[. ]*}
    is_int "$oldest" || oldest=""
    if [ -n "$oldest" ]; then reach=$(((P_NOW - oldest) / 86400)); fi
  fi
  iso_utc at "$oldest"
  JOURNAL_VERDICT=$verdict
  jaddsn o storage "$storage"
  jaddsn o storage_set_in "$ssrc"
  jadds o flush "$flush"
  jaddsn o flush_live "$flush_live"
  jaddn o persistent_files "$pc"
  jaddn o volatile_files "$vc"
  jadds o verdict "$verdict"
  jaddsn o oldest_entry "$at"
  jaddn o reach_days "$reach"
  R_JOURNAL=$o
  if [ "$verdict" = volatile ]; then
    finding risk journal:volatile journal:volatile "The journal is volatile (Storage=${storage:-unset}, systemd-journal-flush ${flush_live:-$flush}, ${pc:-an unknown number of} files under /var/log/journal): a reboot erases everything before it. Copy it as the reboot chain's last step (run.md section 5)."
  fi
}

# The session's own processes end below the platform's agent: exe.dev's
# exe-init stays at -1000 and, since its fix, starts each session's
# processes at 0 (CannObserv/replicator#125, #353). On the older layouts the
# session runs under exe.dev's sshd instead, at -1000 on every build, while
# sshd-session and the session read 0 on a fixed one (#346, 13 hosts,
# 2026-10-01). Stock OpenSSH does the same: noble's sshd puts its listener
# at -1000 and each connection's sshd and session at 0 (measured with
# CAP_SYS_RESOURCE, 2026-10-06; without it the listener can't lower itself
# and reads 0). So stopping at the first sshd keeps a stock host's session
# from reading as -1000 (CR 201, CR 206).
# The agent's adj is reported apart, so the finding names the session's
# own -1000 only.
PLATFORM_AGENTS="exe-init sshd"
read_session() {
  local o="" chain="" e pid=$SESSION_PID n=0 ppid adj comm line min="" complete=0 last="" agent="" below=1
  while [ -n "$pid" ] && [ "$n" -lt 64 ]; do
    n=$((n + 1))
    adj="" comm="" ppid=""
    if [ -r "$P_ROOT/proc/$pid/oom_score_adj" ]; then IFS= read -r adj <"$P_ROOT/proc/$pid/oom_score_adj" || true; fi
    if [ -r "$P_ROOT/proc/$pid/comm" ]; then IFS= read -r comm <"$P_ROOT/proc/$pid/comm" || true; fi
    if [ -r "$P_ROOT/proc/$pid/status" ]; then
      while IFS= read -r line; do
        case $line in PPid:*) ppid=${line#PPid:} ppid=${ppid//[[:space:]]/} ;; esac
      done <"$P_ROOT/proc/$pid/status"
    fi
    is_int "$adj" || adj=""
    e=""
    jaddn e pid "$pid"
    jaddsn e comm "$comm"
    jaddn e adj "$adj"
    jpush chain "{$e}"
    if [ "$below" -eq 1 ] && [ "$pid" != "$SESSION_PID" ] && in_words "$comm" "$PLATFORM_AGENTS"; then
      below=0
      jaddn agent pid "$pid"
      jaddsn agent comm "$comm"
      jaddn agent adj "$adj"
    fi
    if [ "$below" -eq 1 ] && [ -n "$adj" ] && { [ -z "$min" ] || [ "$adj" -lt "$min" ]; }; then min=$adj; fi
    last=$pid
    if [ "$pid" = 1 ]; then
      complete=1
      break
    fi
    if [ -z "$adj" ] || ! is_int "$ppid" || [ "$ppid" -eq 0 ]; then break; fi
    pid=$ppid
  done
  jaddn o start_pid "$SESSION_PID"
  jadd o chain "[$chain]"
  jaddb o reaches_pid1 "$complete"
  jaddn o min_adj "$min"
  if [ -n "$agent" ]; then jadd o platform_agent "{$agent}"; else jadd o platform_agent null; fi
  jadds o source "each process's /proc/<pid>/oom_score_adj, read directly up the chain; min_adj stops below the platform's agent"
  R_SESSION=$o
  R_SESSION_MIN=$min
  if [ -n "$min" ] && [ "$min" -le -1000 ]; then
    finding risk session:adj session:adj "A process in this session's chain runs at oom_score_adj $min, so under memory pressure a production service is killed first. Run the apply and the dry run under choom -n 0 (run.md section 3)."
  fi
  if [ "$complete" -ne 1 ]; then
    if [ "$ppid" = 0 ]; then
      finding unknown session:chain "" "The session's chain from pid $SESSION_PID leaves this PID namespace at pid $last, as under docker exec: an adj beyond it can't be read."
    else
      finding unknown session:chain "" "The session's chain from pid $SESSION_PID stopped at pid $last before PID 1: an adj beyond it wasn't read."
    fi
  fi
}

# Secret patterns, reported by name and line, never by value.
SP_NAME=(tailscale-auth-key tailscale-key github-token github-pat anthropic-key openai-key aws-access-key-id slack-token private-key credential-assignment)
SP_FLAG=("" "" "" "" "" "" "" "" "" i)
SP_RE=(
  'tskey-auth-[A-Za-z0-9]'
  'tskey-(api|client|scim|webhook)-[A-Za-z0-9]'
  'gh[pousr]_[A-Za-z0-9]{20,}'
  'github_pat_[A-Za-z0-9_]{20,}'
  'sk-ant-[A-Za-z0-9_-]{10,}'
  'sk-(proj-)?[A-Za-z0-9]{20,}'
  'AKIA[0-9A-Z]{16}'
  'xox[abprs]-[A-Za-z0-9-]{10,}'
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'
  '(password|passwd|secret|token|api_?key|auth_?key)[a-z_]*[[:space:]]*[=:][[:space:]]*[^[:space:]]'
)

# Line numbers only: grep's matching lines go straight into cut, so a
# secret's value never reaches a variable, stdout or stderr.
_secret_lines() {  # <as-root 0|1> <flags> <ere> <file>
  if [ "$1" -eq 1 ]; then
    as_root grep -n"$2" -E -e "$3" -- "$4" 2>/dev/null
  else
    grep -n"$2" -E -e "$3" -- "$4" 2>/dev/null
  fi
  echo "rc=$?"
}

scan_secrets() {  # <file>: SECRETS (JSON array body), SECRET_SUMMARY, SCAN_OK
  local i out l rc sudo=0
  SECRETS="" SECRET_SUMMARY="" SCAN_OK=1
  if [ ! -r "$1" ]; then
    if [ "$P_PRIV" = none ]; then
      SCAN_OK=0
      return 0
    fi
    sudo=1
  fi
  for i in "${!SP_NAME[@]}"; do
    out=$(_secret_lines "$sudo" "${SP_FLAG[$i]}" "${SP_RE[$i]}" "$1" | cut -d: -f1)
    rc=${out##*rc=}
    if [ "$rc" != 0 ] && [ "$rc" != 1 ]; then
      SCAN_OK=0
      continue
    fi
    while IFS= read -r l; do
      is_int "$l" || continue
      jpush SECRETS "{\"pattern\": \"${SP_NAME[$i]}\", \"line\": $l}"
      SECRET_SUMMARY="$SECRET_SUMMARY, ${SP_NAME[$i]} at line $l"
    done <<<"$out"
  done
  SECRET_SUMMARY=${SECRET_SUMMARY#, }
}

read_setup() {
  local o="" u="" fo="" f="$P_ROOT/exe.dev/setup" disk present=0 mode="" readable="" owner="" contained=0 bootlist line id bo="" boots="" nb=0 nyes=0 nno=0 cond res verdict=unknown msg lines
  unit_disk_state disk exe-setup.service
  unit_show exe-setup.service LoadState ConditionResult Result ActiveState || true
  jadds u disk "$disk"
  jaddsn u load_state "$U_LoadState"
  jaddsn u condition_result "$U_ConditionResult"
  jaddsn u result "$U_Result"
  jaddsn u active_state "$U_ActiveState"
  SECRETS="" SECRET_SUMMARY="" SCAN_OK=1
  if [ -e "$f" ] || [ -L "$f" ]; then
    present=1
    file_mode mode "$f"
    case $mode in ???[4567]) readable=1 ;; ????) readable=0 ;; esac
    file_owner owner "$f"
    # Contained in place: root's alone, and the unit that runs it as exedev
    # off. The platform leaves a 0600 file be, and delivers a shredded one
    # again at 0755 (CannObserv/notifier#99, across an in-guest reboot,
    # 2026-10-02).
    case $owner:$mode:$disk in 0:??00:disabled | 0:??00:masked | 0:??00:masked-runtime) contained=1 ;; esac
    scan_secrets "$f"
  fi
  jaddb fo present "$present"
  jaddsn fo mode "$mode"
  jaddn fo owner_uid "$owner"
  jaddb fo readable_by_all "$readable"
  jadd fo secrets "[$SECRETS]"
  if [ "$present" -eq 1 ]; then jaddb fo scanned "$SCAN_OK"; fi
  # Each retained boot: did the unit run? Its lines are only classified, and
  # none is printed: the script's own output is among them. PID 1 logs to the
  # console on exeuntu, so a boot with no line at all stays unknown.
  if live_cmd journalctl && [ "$disk" != not-found ]; then
    capture bootlist jctl --list-boots --no-pager -q
    while IFS= read -r line; do
      read -r _ id _ <<<"$line"
      case $id in *[!0-9a-f]* | '') continue ;; esac
      [ "${#id}" -eq 32 ] || continue
      capture lines jctl -b "$id" -u exe-setup.service -o cat --no-pager -q
      cond=unknown res=""
      if [ -n "$lines" ]; then
        case $lines in
          *"unmet condition"*) cond=no ;;
          *) cond=yes res=unknown ;;
        esac
        if [ "$cond" = yes ]; then
          case $lines in
            *"Failed with result"* | *"Failed to start"*) res=failed ;;
            *"Finished "* | *"Deactivated successfully"*) res=success ;;
          esac
        fi
      fi
      nb=$((nb + 1))
      if [ "$cond" = yes ]; then
        nyes=$((nyes + 1))
      elif [ "$cond" = no ]; then
        nno=$((nno + 1))
      fi
      bo=""
      jadds bo boot "$id"
      jadds bo ran "$cond"
      jaddsn bo result "$res"
      jpush boots "{$bo}"
    done <<<"$bootlist"
  fi
  if [ "$contained" -eq 1 ]; then
    verdict=contained
  elif [ "$present" -eq 1 ]; then
    verdict=present
  elif [ "$disk" = not-found ] && [ -z "$U_LoadState" ]; then
    verdict="no-consumer"
  elif [ "$nb" -gt 0 ] && [ "$nyes" -eq "$nb" ]; then
    verdict=redelivered
  elif [ "$nb" -gt 0 ] && [ "$nno" -eq "$nb" ]; then
    verdict=none-delivered
  fi
  jadd o unit "{$u}"
  jadd o file "{$fo}"
  jadd o boots "[$boots]"
  jadds o verdict "$verdict"
  R_SETUP=$o
  case $verdict in
    present)
      msg="/exe.dev/setup is on disk (mode ${mode:-unknown}"
      if [ "$readable" = 1 ]; then msg="$msg, readable by every user"; fi
      msg="$msg; exe-setup.service result ${U_Result:-unknown})."
      if [ -n "$SECRET_SUMMARY" ]; then
        msg="$msg It holds $SECRET_SUMMARY. Revoke each key first: the platform delivers the script again at the next boot (the profile)."
      elif [ "$SCAN_OK" -ne 1 ]; then
        msg="$msg It couldn't be read to check for secrets."
      fi
      msg="$msg Then contain it in place: sudo systemctl disable exe-setup.service, and sudo chmod 600 /exe.dev/setup, root's alone. Don't shred it: the platform delivers it again at the next boot, at 0755 (the profile)."
      finding leftover setup-script:present "" "$msg" ;;
    redelivered)
      # Revoking the key changes nothing the probe can read, so the owner
      # declares it: an exception, with a review-by date (#352).
      finding leftover setup-script:redelivered setup-script:redelivered "exe-setup.service ran on each of the $nb retained boots read, though /exe.dev/setup is absent now: the platform delivers the script again every boot, so an absent file isn't cleanup. Revoke any key the script carries, then declare it: exception setup-script:redelivered <review-by> <reason> (policy.md). Once it's back on disk, contain it in place: disable exe-setup.service and chmod 600 /exe.dev/setup (the profile)." ;;
  esac
}

read_tmp() {
  local o="" staged="" name count=0
  tmp_rule
  if [ -d "$P_ROOT/tmp" ]; then
    for name in "$P_ROOT"/tmp/* "$P_ROOT"/tmp/.[!.]*; do
      if [ ! -e "$name" ] && [ ! -L "$name" ]; then continue; fi
      [ "$name" != "$P_TMP" ] || continue
      name=${name##*/}
      case $name in systemd-private-* | snap-private-tmp | .X11-unix | .ICE-unix | .XIM-unix | .font-unix | .Test-unix) continue ;; esac
      count=$((count + 1))
      if [ "$count" -le 50 ]; then jpushs staged "$name"; fi
    done
  fi
  jaddsn o rule "$TMP_RULE"
  jaddsn o rule_file "$TMP_RULE_FILE"
  jaddb o cleared_at_boot "$TMP_CLEARED"
  jaddn o staged_count "$count"
  jadd o staged "[$staged]"
  R_TMP=$o
}

# Which environment profile (references/environments/) the host matches. The
# guest can't see its image digest, so the profile's markers decide, each
# read on its own: usa-wa's image had exe-setup.service but no exeuntu. The
# platform's (/exe.dev/, exe-init as init=) exist only on an exe.dev VM: the
# image doesn't carry /exe.dev/. The image's are in any tree of it, which is
# all an offline read sees, and only they can date it.
PROFILE="" GENERATION=""
read_profile() {
  local o="" m="" cmdline="" init="" dir=0 account=0 wrapper=0 exeuntu=0 setup out p kimg="" kernel=""
  local platform=0 image=0
  if [ -r "$P_ROOT/proc/cmdline" ]; then
    IFS= read -r cmdline <"$P_ROOT/proc/cmdline" || true
    init=0
    case " $cmdline " in *" init=/exe.dev/bin/exe-init "*) init=1 ;; esac
  fi
  if [ -d "$P_ROOT/exe.dev" ]; then dir=1; fi
  # The image's since its import (boldsoftware/exeuntu 6f88f30, 2026-01-22):
  # the ubuntu account renamed exedev, "exe.dev user", and /usr/local/bin/init,
  # the init wrapper, which names the image.
  if [ -r "$P_ROOT/etc/passwd" ] &&
    grep -q '^exedev:[^:]*:[^:]*:[^:]*:exe\.dev user[,:]' "$P_ROOT/etc/passwd"; then
    account=1
  fi
  if [ -r "$P_ROOT/usr/local/bin/init" ] &&
    grep -q 'boldsoftware/exeuntu' "$P_ROOT/usr/local/bin/init"; then
    wrapper=1
  fi
  if [ -e "$P_ROOT/usr/local/bin/exeuntu" ]; then exeuntu=1; fi
  unit_disk_state setup exe-setup.service
  # No linux-image package: the platform supplies the kernel.
  if have dpkg-query; then
    capture out dpkgq -W -f "$DPKG_PKG_STATUS" 'linux-image-*'
    if [ "$CAP_RC" -eq 0 ]; then
      kimg=0
      while IFS= read -r p; do
        case $p in *" ii"*) kimg=$((kimg + 1)) ;; esac
      done <<<"$out"
    else
      case $CAP_ERR in *"no packages found"*) kimg=0 ;; esac
    fi
  fi
  if [ -r "$P_ROOT/proc/sys/kernel/osrelease" ]; then
    IFS= read -r kernel <"$P_ROOT/proc/sys/kernel/osrelease" || true
  fi
  if [ "$dir" -eq 1 ] || [ "$init" = 1 ]; then platform=1; fi
  if [ "$account" -eq 1 ] || [ "$wrapper" -eq 1 ]; then image=1; fi
  if [ "$platform" -eq 1 ] || [ "$image" -eq 1 ]; then
    PROFILE=exe-dev-exeuntu
    # Only the image's markers date it: on the platform alone, the image
    # could be another. The generations differ by these two (the profile's
    # table).
    GENERATION=unknown
    if [ "$image" -eq 1 ]; then
      if [ "$setup" = not-found ] && [ "$exeuntu" -eq 0 ]; then
        GENERATION=feb-2026
      elif [ "$setup" != not-found ] && [ "$exeuntu" -eq 0 ]; then
        GENERATION=may-2026
      elif [ "$setup" != not-found ]; then
        GENERATION=newer
      fi
    fi
  fi
  jaddb m exe_init_cmdline "$init"
  jaddb m exe_dev_dir "$dir"
  jaddb m exedev_account "$account"
  jaddb m init_wrapper "$wrapper"
  jaddb m exeuntu "$exeuntu"
  jadds m exe_setup_unit "$setup"
  jaddn m linux_image_packages "$kimg"
  jaddsn m kernel "$kernel"
  jaddsn o name "$PROFILE"
  if [ -n "$PROFILE" ]; then
    jadds o reference "references/environments/$PROFILE.md"
  else
    jadd o reference null
  fi
  jaddsn o generation "$GENERATION"
  jaddb o platform "$platform"
  jaddb o image "$image"
  jadd o markers "{$m}"
  if [ -z "$PROFILE" ]; then
    jadds o fallback "no profile matches: read SKILL.md's \"Hosts no profile matches\""
  fi
  R_PROFILE=$o
}

read_environment() {
  local o="" lt=""
  read_profile
  read_boot
  read_journal
  if live_cmd systemd-analyze; then
    capture lt systemd-analyze get-log-target
    lt=${lt%%$'\n'*}
  fi
  read_session
  read_setup
  read_tmp
  jadd o profile "{$R_PROFILE}"
  jadd o boot "{$R_BOOT}"
  jadd o journal "{$R_JOURNAL}"
  jaddsn o pid1_log_target "$lt"
  jadd o session "{$R_SESSION}"
  jadd o setup_script "{$R_SETUP}"
  jadd o tmp "{$R_TMP}"
  R_ENV=$o
}

# --- what updates this host -------------------------------------------------
APT_UNITS="apt-daily.timer apt-daily-upgrade.timer unattended-upgrades.service update-notifier-download.timer update-notifier-motd.timer"
UNIT_STATE=""  # " unit=state ..." pairs: the live state when there is one, else the disk's
PERIODIC_E="" PERIODIC_U="" PERIODIC_UU="" UU_REBOOT="" UU_WIDE="" UU_ORIGINS_N=0 APT_CONFIG_OK=0
NR_RESTART="" NR_PROOF=unknown NR_INSTALLED=0 UU_INSTALLED=0 NR_SVC="" NR_KSTA="" NR_READ=0

state_of() {  # <var> <unit>: the state read_updates recorded
  local _so=${UNIT_STATE#* "$2"=}
  if [ "$_so" = "$UNIT_STATE" ]; then _so=""; fi
  printf -v "$1" '%s' "${_so%% *}"
}

set_in() {  # <var> <ere>: VAR := the apt.conf files, with line numbers, whose lines match; SET_IN_PLAIN the same as text
  local _si_out="" _si_f _si_l _si_n
  SET_IN_PLAIN=""
  for _si_f in "$P_ROOT/etc/apt/apt.conf" "$P_ROOT"/etc/apt/apt.conf.d/*; do
    [ -f "$_si_f" ] || continue
    _si_n=0
    while IFS= read -r _si_l || [ -n "$_si_l" ]; do
      _si_n=$((_si_n + 1))
      case $_si_l in [[:space:]]*'//'* | '//'* | '#'*) continue ;; esac
      if [[ $_si_l =~ $2 ]]; then
        jpushs _si_out "${_si_f#"$P_ROOT"}:$_si_n"
        SET_IN_PLAIN="$SET_IN_PLAIN, ${_si_f#"$P_ROOT"}:$_si_n"
      fi
    done <"$_si_f"
  done
  SET_IN_PLAIN=${SET_IN_PLAIN#, }
  printf -v "$1" '[%s]' "$_si_out"
}

refresh_lists() {
  local out
  [ -n "$refresh" ] || return 0
  mkdir -p "$refresh/lists/partial" "$refresh/archives/partial"
  capture2 out apt_env apt-get update -o "Dir::State::Lists=$refresh/lists/" -o "Dir::Cache::archives=$refresh/archives/" "${APT_OPTS[@]}"
  if [ "$CAP_RC" -eq 0 ]; then
    LISTS_DIR=$refresh/lists REFRESHED=1
    LISTS_OPT=(-o "Dir::State::Lists=$refresh/lists/")
  else
    finding unknown lists:refresh "" "apt-get update into $refresh/lists failed (exit $CAP_RC), so every count is against the host's own lists."
  fi
}

read_units() {
  local u disk live e
  R_UNITS=""
  for u in $APT_UNITS; do
    unit_disk_state disk "$u"
    live=""
    if live_cmd systemctl; then
      capture live systemctl is-enabled "$u"
      live=${live%%$'\n'*}
    fi
    UNIT_STATE="$UNIT_STATE $u=${live:-$disk}"
    e=""
    jadds e unit "$u"
    jadds e disk "$disk"
    jaddsn e live "$live"
    jpush R_UNITS "{$e}"
  done
}

# The effective values, through apt-config: a file named after Docker sets
# Enable to 0 on the base image, whatever 20auto-upgrades says.
read_periodic() {
  local out line name val files e v
  R_PERIODIC="" R_UU=""
  if have apt-config; then
    capture out apt_env apt-config shell PE APT::Periodic::Enable PU APT::Periodic::Update-Package-Lists PUU APT::Periodic::Unattended-Upgrade UR Unattended-Upgrade::Automatic-Reboot
    if [ "$CAP_RC" -eq 0 ]; then
      APT_CONFIG_OK=1
      while IFS= read -r line; do
        name=${line%%=*} val=${line#*=}
        val=${val#\'} val=${val%\'}
        case $name in
          PE) PERIODIC_E=$val ;;
          PU) PERIODIC_U=$val ;;
          PUU) PERIODIC_UU=$val ;;
          UR) UU_REBOOT=$val ;;
        esac
      done <<<"$out"
    fi
  fi
  for name in Enable Update-Package-Lists Unattended-Upgrade; do
    case $name in
      Enable) val=$PERIODIC_E ;;
      Update-Package-Lists) val=$PERIODIC_U ;;
      *) val=$PERIODIC_UU ;;
    esac
    set_in files "Periodic::${name}[[:space:]]"
    e=""
    jaddsn e value "$val"
    jadd e set_in "$files"
    jadd R_PERIODIC "$name" "{$e}"
  done
  if installed unattended-upgrades; then UU_INSTALLED=1; fi
  local origins=""
  if [ "$APT_CONFIG_OK" -eq 1 ]; then
    capture out apt_env apt-config dump
    while IFS= read -r line; do
      case $line in
        "Unattended-Upgrade::Allowed-Origins:: "* | "Unattended-Upgrade::Origins-Pattern:: "*)
          v=${line#*:: \"}
          v=${v%\";}
          UU_ORIGINS_N=$((UU_ORIGINS_N + 1))
          jpushs origins "$v"
          if widens "$v"; then UU_WIDE="$UU_WIDE, $v"; fi ;;
      esac
    done <<<"$out"
    UU_WIDE=${UU_WIDE#, }
  fi
  jaddb R_UU installed "$UU_INSTALLED"
  if [ "$APT_CONFIG_OK" -eq 1 ]; then jadd R_UU origins "[$origins]"; else jadd R_UU origins null; fi
  jaddsn R_UU automatic_reboot "$UU_REBOOT"
}

# needrestart: the file that sets the key, then the proof that it loads.
read_needrestart() {
  local f line n re src="" ver="" out
  R_NR=""
  if installed needrestart; then
    NR_INSTALLED=1
    ver=$(dpkgq -W -f "$DPKG_VERSION" needrestart 2>/dev/null) || ver=""
  fi
  re="^[[:space:]]*\\\$nrconf\\{restart\\}[[:space:]]*=[[:space:]]*['\"]([a-z])['\"]"
  for f in "$P_ROOT/etc/needrestart/needrestart.conf" "$P_ROOT"/etc/needrestart/conf.d/*.conf; do
    [ -f "$f" ] || continue
    n=0
    while IFS= read -r line || [ -n "$line" ]; do
      n=$((n + 1))
      if [[ $line =~ $re ]]; then
        NR_RESTART=${BASH_REMATCH[1]}
        src="${f#"$P_ROOT"}:$n"
      fi
    done <"$f"
  done
  if [ "$NR_INSTALLED" -eq 1 ] && live_cmd needrestart && [ "$P_PRIV" != none ]; then
    capture2 out as_root needrestart -m u -b -r l
    case $out in
      *"Disabling Ubuntu mode, explicit restart mode configured"*) NR_PROOF=explicit ;;
      *NEEDRESTART-VER*) NR_PROOF=ubuntu-mode ;;
    esac
    # Its batch output names what it found, an empty list included.
    case $out in *NEEDRESTART-VER*) NR_READ=1 ;; esac
    while IFS= read -r line; do
      case $line in
        NEEDRESTART-SVC:*) NR_SVC="$NR_SVC ${line#NEEDRESTART-SVC:}" ;;
        NEEDRESTART-KSTA:*) NR_KSTA=${line#NEEDRESTART-KSTA:} ;;
      esac
    done <<<"$out"
  fi
  jaddb R_NR installed "$NR_INSTALLED"
  jaddsn R_NR version "$ver"
  jaddsn R_NR restart "$NR_RESTART"
  jaddsn R_NR restart_set_in "$src"
  jadds R_NR proof "$NR_PROOF"
  jadds R_NR proof_command "sudo needrestart -m u -b -r l"
}

read_sources() {
  local f line uris v s i
  local -a w=()
  R_SOURCES=""
  for f in "$P_ROOT/etc/apt/sources.list" "$P_ROOT"/etc/apt/sources.list.d/*.list "$P_ROOT"/etc/apt/sources.list.d/*.sources; do
    [ -f "$f" ] || continue
    uris=""
    while IFS= read -r line || [ -n "$line" ]; do
      case $line in
        "deb "* | "deb-src "*)
          read -r -a w <<<"$line"
          i=1
          if [ "${w[1]:0:1}" = "[" ]; then
            while [ "$i" -lt "${#w[@]}" ] && [[ ${w[$i]} != *"]" ]]; do i=$((i + 1)); done
            i=$((i + 1))
          fi
          if [ "$i" -lt "${#w[@]}" ]; then jpushs uris "${w[$i]}"; fi ;;
        URIs:*)
          read -r -a w <<<"${line#URIs:}"
          for v in ${w[@]+"${w[@]}"}; do jpushs uris "$v"; done ;;
      esac
    done <"$f"
    s=""
    jadds s file "${f#"$P_ROOT"}"
    jadd s uris "[$uris]"
    jpush R_SOURCES "{$s}"
  done
}

# "origin|site" entries. A repository names its own origin, so the names stay
# in arrays: split unquoted, a '*' in one would expand against the current
# directory.
THIRD_PARTY=()
read_origins() {
  local out line v os="" oa="" osite third po seen="" third_seen=""
  local -a kv=()
  R_ORIGINS=""
  POLICY_WHY="apt-cache isn't installed"
  have apt-cache || return 0
  capture out apt_env apt-cache "${APT_OPTS[@]}" ${LISTS_OPT[@]+"${LISTS_OPT[@]}"} policy
  # The one-origin lane's dry run maps a site to its o= names from it.
  POLICY_OUT=$out
  if [ "$CAP_RC" -eq 0 ]; then POLICY_WHY=""; else POLICY_WHY="apt-cache policy exited $CAP_RC${CAP_ERR:+: $CAP_ERR}"; fi
  while IFS= read -r line; do
    case $line in
      *" release "*)
        os="" oa=""
        IFS=, read -r -a kv <<<"${line#*release }"
        for v in ${kv[@]+"${kv[@]}"}; do
          case $v in o=*) os=${v#o=} ;; a=*) oa=${v#a=} ;; esac
        done ;;
      *" origin "*)
        osite=${line#*origin }
        if [ -n "$os$oa" ] && [ "$oa" != now ] && ! in_words "${os// /_}|$oa|$osite" "$seen"; then
          seen="$seen ${os// /_}|$oa|$osite"
          third=1
          case $os in Ubuntu | UbuntuESM | UbuntuESMApps | Canonical) third=0 ;; esac
          po=""
          jaddsn po origin "$os"
          jaddsn po archive "$oa"
          jadds po site "$osite"
          jaddb po third_party "$third"
          jpush R_ORIGINS "{$po}"
          if [ "$third" -eq 1 ] && ! in_words "${os// /_}|$osite" "$third_seen"; then
            third_seen="$third_seen ${os// /_}|$osite"
            THIRD_PARTY+=("${os// /_}|$osite")
          fi
        fi
        os="" oa="" ;;
    esac
  done <<<"$out"
}

# A followed origin is scoped to what it was added for (policy.md). A
# "Package: *" pin for its site shows as the priority on its release lines,
# and a package pin is listed under "Pinned packages:", by name, for each
# version it matches. Measured on noble with NodeSource (apt 2.8.3,
# 2026-10-05): unpinned at 500, its nodejs replaced Ubuntu's; at 100 or 499,
# Ubuntu's stayed. But an installed NodeSource nodejs was still upgraded at
# 100, and kept only at 99: only a package pin says which ones it serves.
# A package pin sets the installed version's priority too, so one at 99
# didn't keep it. A pin on its installed version kept it at 501; at 500
# with no catch-all, and at 100 under one, it tied the newer one, which won.
SCOPE_KEY=() SCOPE_SITES=() SCOPE_PRIO=() SCOPE_UNPINNED=()
SCOPE_READ=""  # 1 when every installed package's candidate was read
POLICY_WHY="not read"  # why apt-cache policy's own output isn't a reading, or empty
R_SCOPE=""
read_scope() {
  local r line v o="" prio="" key sites max pins="" follow="" out pkg="" cand="" incand=0 host i e why=""
  local -a f=() kv=() rp=() ro=() rs=() scope_pkgs=()
  R_SCOPE=""
  # Each release's priority, o= and site, and the package pins.
  while IFS= read -r line; do
    if [ "$line" = "Pinned packages:" ]; then pins=" "; continue; fi
    if [ -n "$pins" ]; then
      case $line in *" -> "*)
        v=${line%% -> *}
        v=${v##* }
        v=${v%%:*}
        if ! in_words "$v" "$pins"; then pins="$pins$v "; fi ;;
      esac
      continue
    fi
    case $line in
      *" release "*)
        o=""
        IFS=, read -r -a kv <<<"${line#*release }"
        for v in ${kv[@]+"${kv[@]}"}; do
          case $v in o=*) o=${v#o=} ;; esac
        done ;;
      *" origin "*)
        if [ -n "$prio" ]; then rp+=("$prio") ro+=("$o") rs+=("${line#*origin }"); fi
        o="" prio="" ;;
      *)
        if [[ $line =~ ^\ *(-?[0-9]+)\  ]]; then prio=${BASH_REMATCH[1]}; fi ;;
    esac
  done <<<"$POLICY_OUT"
  # Each followed origin's sites, as origin_names reads its key, and its
  # highest priority among them.
  for r in ${KNOB_ORIGIN[@]+"${KNOB_ORIGIN[@]}"}; do
    IFS=$KNOB_US read -r -a f <<<"$r"
    [ "${f[1]}" = follow ] || continue
    key=${f[0]} sites=" " max=""
    for i in ${rs[@]+"${!rs[@]}"}; do
      case $key in
        *.*) [ "${rs[$i]}" = "$key" ] || continue ;;
        *) [ "${ro[$i]}" = "${key//_/ }" ] || continue ;;
      esac
      if ! in_words "${rs[$i]}" "$sites"; then sites="$sites${rs[$i]} "; fi
      if [ -z "$max" ] || [ "${rp[$i]}" -gt "$max" ]; then max=${rp[$i]}; fi
    done
    SCOPE_KEY+=("$key") SCOPE_SITES+=("$sites") SCOPE_PRIO+=("$max") SCOPE_UNPINNED+=(" ")
    follow="$follow$sites"
  done
  # Each installed package whose candidate one of those sites serves, from
  # one apt-cache policy over every installed package: a version's sources
  # are indented under it, a URL's host being the site. A version line has
  # 5 columns before it; a source line right-aligns its priority after 7 or
  # more, so 1001 has 7.
  # Without the policy, no origin's sites or priority are known: each is
  # unread, never an origin apt doesn't list.
  if [ -n "$POLICY_WHY" ] && [ "${#SCOPE_KEY[@]}" -gt 0 ]; then
    not_read "each followed origin's scope: $POLICY_WHY"
  fi
  if [ -z "$POLICY_WHY" ] && [ -n "${follow// /}" ]; then
    SCOPE_READ=0
    if ! have dpkg-query; then
      why="dpkg-query isn't installed"
    else
      capture out dpkgq -W -f "$DPKG_PKG_STATUS"
      if [ "$CAP_RC" -ne 0 ]; then
        why="dpkg-query -W exited $CAP_RC${CAP_ERR:+: $CAP_ERR}"
      else
        while read -r pkg v; do
          if [ "${v:1:1}" = i ]; then scope_pkgs+=("$pkg"); fi
        done <<<"$out"
        if [ "${#scope_pkgs[@]}" -eq 0 ]; then
          why="dpkg-query -W listed no installed package"
        else
          capture out apt_env apt-cache "${APT_OPTS[@]}" ${LISTS_OPT[@]+"${LISTS_OPT[@]}"} policy "${scope_pkgs[@]}"
          if [ "$CAP_RC" -ne 0 ]; then
            why="apt-cache policy over the installed packages exited $CAP_RC${CAP_ERR:+: $CAP_ERR}"
          fi
        fi
      fi
    fi
    if [ -z "$why" ]; then SCOPE_READ=1; fi
    if [ "$SCOPE_READ" -eq 1 ]; then
      pkg=""
      while IFS= read -r line; do
        case $line in
          [!\ ]*:)
            pkg=${line%:}
            pkg=${pkg%%:*}
            cand="" incand=0 ;;
          "  Candidate: "*) cand=${line#  Candidate: } ;;
          " *** "* | "     "[!\ ]*)
            v=${line:5}
            incand=0
            if [ "${v%% *}" = "$cand" ]; then incand=1; fi ;;
          "       "*)
            if [ "$incand" -eq 0 ] || [ -z "$pkg" ]; then continue; fi
            in_words "$pkg" "$pins" && continue
            v=${line#"${line%%[![:space:]]*}"}
            v=${v#* }
            case $v in *://*) ;; *) continue ;; esac
            host=${v#*://}
            host=${host%%/*}
            host=${host##*@}
            host=${host%%:*}
            for i in ${SCOPE_KEY[@]+"${!SCOPE_KEY[@]}"}; do
              if in_words "$host" "${SCOPE_SITES[$i]}" && ! in_words "$pkg" "${SCOPE_UNPINNED[$i]}"; then
                SCOPE_UNPINNED[i]="${SCOPE_UNPINNED[$i]}$pkg "
              fi
            done ;;
        esac
      done <<<"$out"
    else
      not_read "which installed packages a followed origin serves: $why"
    fi
  fi
  for i in ${SCOPE_KEY[@]+"${!SCOPE_KEY[@]}"}; do
    e=""
    jadds e origin "${SCOPE_KEY[$i]}"
    if [ -n "$POLICY_WHY" ]; then
      jadd e sites null
      jadd e priority null
      jadd e unpinned null
      jpush R_SCOPE "{$e}"
      continue
    fi
    json_list v "${SCOPE_SITES[$i]}"
    jadd e sites "$v"
    jaddn e priority "${SCOPE_PRIO[$i]}"
    if [ "$SCOPE_READ" = 1 ]; then
      json_list v "${SCOPE_UNPINNED[$i]}"
      jadd e unpinned "$v"
    elif [ -n "${SCOPE_SITES[$i]// /}" ]; then
      jadd e unpinned null
    else
      jadd e unpinned "[]"
    fi
    jpush R_SCOPE "{$e}"
  done
}

# Outside apt: binaries under /usr/local/bin and ~/.local/bin, with any owner
# the knob names, and container images with their age.
read_outside_apt() {
  local list="" r path age mt owner oline e c=0 out line img ci=""
  local -a of=()
  for path in "$P_ROOT"/usr/local/bin/* "$P_ROOT"/home/*/.local/bin/* "$P_ROOT"/root/.local/bin/*; do
    [ -f "$path" ] || continue
    c=$((c + 1))
    [ "$c" -le 100 ] || continue
    file_mtime mt "$path"
    age=""
    if [ -n "$mt" ]; then age=$(((P_NOW - mt) / 86400)); fi
    owner="" oline=""
    for r in ${KNOB_OWNER[@]+"${KNOB_OWNER[@]}"}; do
      IFS=$KNOB_US read -r -a of <<<"$r"
      if glob_match "${path#"$P_ROOT"}" "${of[0]} */${of[0]}"; then owner=${of[1]} oline=${of[2]}; fi
    done
    e=""
    jadds e path "${path#"$P_ROOT"}"
    jaddn e age_days "$age"
    jaddsn e owner "$owner"
    jaddn e owner_line "$oline"
    jpush list "{$e}"
  done
  if docker_running; then
    capture out docker_cmd images --format '{{.Repository}}:{{.Tag}}|{{.CreatedSince}}'
    if [ "$CAP_RC" -eq 0 ]; then
      while IFS= read -r line; do
        [ -n "$line" ] || continue
        img=""
        jadds img image "${line%%|*}"
        jadds img created "${line#*|}"
        jpush ci "{$img}"
      done <<<"$out"
      ci="[$ci]"
    fi
  elif live_cmd docker; then
    if docker_socket_listens; then
      not_read "container images: docker.service isn't running, and asking would start it through docker.socket"
    else
      not_read "container images: docker.service isn't running"
    fi
  fi
  R_OUTSIDE=""
  jadd R_OUTSIDE binaries "[$list]"
  jaddn R_OUTSIDE binaries_count "$c"
  jadd R_OUTSIDE container_images "${ci:-null}"
}

# Tailscale updates itself when its own auto-update is on (tailscale set
# --auto-update): outside any window, an upgrade drops the host's tailnet
# path, and anything that reaches the host over it. tailscale debug prefs
# reads it, no root needed (the socket is 0666): AutoUpdate.Apply is true,
# false, or null when nothing ever set it on the node, as on a daemon that
# never logged in (noble, 2026-10-03). The node's own false doesn't hold:
# on co-replicator, tailscaled logged "using tailnet default auto-update
# setting: true" at a later boot and set Apply true again (2026-10-06,
# #357). So --post-boot reads it again.
TS_APPLY=""
read_tailscale() {
  local out re v=""
  R_TAILSCALE=null TS_APPLY=""
  installed tailscale || return 0
  R_TAILSCALE=""
  if [ "$P_LIVE" -ne 1 ] || ! have tailscale; then
    not_read "Tailscale's auto-update: tailscale debug prefs needs a running system with the CLI"
    jadd R_TAILSCALE auto_update null
    R_TAILSCALE="{$R_TAILSCALE}"
    return 0
  fi
  capture out tailscale version
  jaddsn R_TAILSCALE version "${out%%$'\n'*}"
  # That's the CLI's. The daemon keeps running the old binary until it
  # restarts, and only --daemon reads it: plain tailscale version printed
  # 1.102.4 over a 1.102.2 tailscaled (noble, 2026-10-04). daemonLong is
  # <major.minor.patch>-t<commit>-g<commit>; without a daemon it exits 1.
  v=""
  capture out tailscale version --daemon --json
  re='"daemonLong": *"([0-9][^"-]*)'
  if [ "$CAP_RC" -eq 0 ] && [[ $out =~ $re ]]; then v=${BASH_REMATCH[1]}; fi
  jaddsn R_TAILSCALE daemon_version "$v"
  v=""
  capture out tailscale debug prefs
  re='"AutoUpdate": *\{[^}]*"Apply": *(true|false|null)'
  if [ "$CAP_RC" -eq 0 ] && [[ $out =~ $re ]]; then
    v=${BASH_REMATCH[1]}
    TS_APPLY=$v
    jadd R_TAILSCALE auto_update "$v"
  else
    not_read "Tailscale's auto-update: tailscale debug prefs couldn't be read (${CAP_ERR:-exit $CAP_RC}); is tailscaled running?"
    jadd R_TAILSCALE auto_update null
  fi
  R_TAILSCALE="{$R_TAILSCALE}"
}

read_updates() {
  local o=""
  read_units
  read_periodic
  read_needrestart
  read_sources
  read_origins
  read_scope
  read_outside_apt
  read_tailscale
  jadd o units "[$R_UNITS]"
  jadd o periodic "{$R_PERIODIC}"
  jaddb o apt_config_read "$APT_CONFIG_OK"
  jadd o unattended_upgrades "{$R_UU}"
  jadd o needrestart "{$R_NR}"
  jadd o sources "[$R_SOURCES]"
  # Unread, the origins are unknown, never none: a third-party one would
  # go without its policy finding.
  if [ -n "$POLICY_WHY" ]; then
    jadd o origins null
    not_read "apt's origins, and whether each third-party one has a policy: $POLICY_WHY"
  else
    jadd o origins "[$R_ORIGINS]"
  fi
  jadd o origin_scope "[$R_SCOPE]"
  jadd o outside_apt "{$R_OUTSIDE}"
  jadd o tailscale "$R_TAILSCALE"
  R_UPD=$o
}

evaluate_posture() {
  local u st p=$KNOB_POSTURE key val files t os site r found i pk
  local -a of=()
  for u in apt-daily.timer apt-daily-upgrade.timer; do
    state_of st "$u"
    if [ "$p" = automatic ]; then
      case $st in
        enabled | enabled-runtime) ;;
        *) finding deviation "timer:$u" "timer:$u" "$u is $st; the automatic posture needs it enabled (policy.md)." ;;
      esac
    else
      case $st in
        masked | masked-runtime | not-found) ;;
        *) finding deviation "timer:$u" "timer:$u" "$u is $st; the scheduled posture keeps it masked, so nothing patches the host outside its window (policy.md)." ;;
      esac
    fi
  done
  if [ "$p" = automatic ]; then
    if [ "$APT_CONFIG_OK" -ne 1 ]; then
      finding unknown periodic:unread periodic:unread "apt-config couldn't be run, so the effective APT::Periodic values are unknown."
    else
      for key in Enable Update-Package-Lists Unattended-Upgrade; do
        case $key in
          Enable) val=$PERIODIC_E ;;
          Update-Package-Lists) val=$PERIODIC_U ;;
          *) val=$PERIODIC_UU ;;
        esac
        set_in files "Periodic::${key}[[:space:]]"
        if [ -z "$val" ]; then
          finding unknown "periodic:$key" "periodic:$key" "APT::Periodic::$key is set nowhere. apt.systemd.daily has a default, but the probe reports only what's set: declare it."
        elif [ "$key" = Enable ] && [ "$val" != 1 ]; then
          finding deviation "periodic:$key" "periodic:$key" "APT::Periodic::Enable is \"$val\" (${SET_IN_PLAIN:-set in no file the probe could read}), which makes the timers no-ops. Set \"1\" in a file sorting after it (policy.md)."
        elif [ "$key" != Enable ] && { ! is_int "$val" || [ "$val" -lt 1 ]; }; then
          finding deviation "periodic:$key" "periodic:$key" "APT::Periodic::$key is \"$val\" (${SET_IN_PLAIN:-set in no file the probe could read}); the automatic posture needs 1 or more."
        fi
      done
      if [ "$UU_INSTALLED" -ne 1 ]; then
        finding deviation package:unattended-upgrades package:unattended-upgrades "unattended-upgrades isn't installed; the automatic posture runs it daily."
      elif [ "$UU_ORIGINS_N" -eq 0 ]; then
        finding unknown uu:origins uu:origins "No Unattended-Upgrade::Allowed-Origins or Origins-Pattern entry is set, so what the daily run would take is unknown."
      elif [ -n "$UU_WIDE" ]; then
        finding deviation uu:origins uu:origins "unattended-upgrades takes more than -security: $UU_WIDE. The automatic posture is security-only; the rest belongs to the maintenance lane (policy.md)."
      fi
      if [ -z "$UU_REBOOT" ]; then
        finding unknown uu:automatic-reboot uu:automatic-reboot "Unattended-Upgrade::Automatic-Reboot is set nowhere. Its built-in default is false, but the probe reports only what's set: declare \"false\"."
      elif [ "$UU_REBOOT" = true ] || [ "$UU_REBOOT" = 1 ]; then
        finding deviation uu:automatic-reboot uu:automatic-reboot "Unattended-Upgrade::Automatic-Reboot is \"$UU_REBOOT\"; the posture never reboots automatically."
      fi
    fi
  fi
  # The drop-in belongs to both postures: every run relies on the hook
  # restarting nothing.
  if [ "$NR_INSTALLED" -eq 1 ]; then
    if [ -z "$NR_RESTART" ]; then
      finding deviation needrestart:restart needrestart:restart "No file sets \$nrconf{restart}, so needrestart's apt hook runs in Ubuntu mode and restarts services itself. Install the drop-in (run.md section 1)."
    elif [ "$NR_RESTART" != l ]; then
      finding deviation needrestart:restart needrestart:restart "\$nrconf{restart} is '$NR_RESTART'; both postures need 'l', so the hook lists restarts rather than performing them (run.md section 1)."
    elif [ "$NR_PROOF" = ubuntu-mode ]; then
      finding deviation needrestart:restart needrestart:restart "A file sets \$nrconf{restart} to 'l', but needrestart ran without \"Disabling Ubuntu mode\": the file doesn't load (run.md section 1)."
    fi
  fi
  # Each third-party origin needs a policy for the maintenance lane.
  for t in ${THIRD_PARTY[@]+"${THIRD_PARTY[@]}"}; do
    os=${t%%|*} site=${t#*|}
    found=0
    for r in ${KNOB_ORIGIN[@]+"${KNOB_ORIGIN[@]}"}; do
      IFS=$KNOB_US read -r -a of <<<"$r"
      if [ "${of[0]}" = "$os" ] || [ "${of[0]}" = "$site" ]; then found=1; fi
    done
    if [ "$found" -eq 0 ]; then
      finding knob "origin:${os//_/ }" "" "The third-party origin ${os//_/ } ($site) has no policy: add origin $os follow, pin <version> or hold <reason> (knob.md). The maintenance lane takes nothing from it until then."
    fi
  done
  # Each followed origin is scoped to the packages it was added for.
  for i in ${SCOPE_KEY[@]+"${!SCOPE_KEY[@]}"}; do
    key=${SCOPE_KEY[$i]}
    if is_int "${SCOPE_PRIO[$i]}" && [ "${SCOPE_PRIO[$i]}" -ge 500 ]; then
      finding deviation "unscoped:$key" "unscoped:$key" "The followed origin $key is at apt priority ${SCOPE_PRIO[$i]}, at least Ubuntu's 500, so a package it serves under a name this host already has, at a higher version, replaces Ubuntu's in the maintenance lane and in a one-origin run (--lane origin:$key), not only what it was added for. Scope it: a Package: * pin for its site below 500, and a package pin above 500 for each package it was added for (policy.md)."
    fi
    for pk in ${SCOPE_UNPINNED[$i]}; do
      finding deviation "unpinned:$pk" "unpinned:$pk" "$pk is installed, and its candidate comes from the followed origin $key, but no package pin names it: the maintenance lane and a one-origin run (--lane origin:$key) take its upgrades, though nothing declares the origin was added for it, and a Package: * pin stops that only below 100. Pin it above 500 if the origin was added for it. To keep it where it is, pin its installed version above 500: a lower pin can tie the newer version, which then wins, and a package pin below 100 lowers the installed version too (policy.md)."
    done
  done
  # Either posture: Tailscale belongs in the maintenance lane, or in an
  # expedited window (policy.md), never in an update of its own choosing.
  case $TS_APPLY in
    true) finding deviation tailscale:auto-update tailscale:auto-update "Tailscale updates itself (AutoUpdate.Apply is true): outside any window, an upgrade drops this host's tailnet path, and anything that reaches it over the tailnet. Turn it off for the tailnet (the admin console's auto-updates) as well as with tailscale set --auto-update=false: the tailnet's default re-applied over the node's setting at a boot. Take its updates in the maintenance lane (policy.md)." ;;
    null) finding unknown tailscale:auto-update tailscale:auto-update "Tailscale's auto-update was never set on this node (AutoUpdate.Apply is null), so nothing on record says whether it updates itself, and the tailnet's default can set it at a boot. Turn it off for the tailnet, and on the node: tailscale set --auto-update=false (policy.md)." ;;
  esac
}

# --- the pending set --------------------------------------------------------
PEND=""        # " name ... ": everything apt-get -s would install or upgrade
SIM_DIST_OUT="" SIM_OK=0 POLICY_OUT=""  # apt-get -s dist-upgrade's and apt-cache policy's output
SEC_EXACT=""   # the dry run's selection, when it ran
R_PHASED=null  # {package: percent} for each phased candidate in the set
DRY_SECURITY_ONLY=0  # 1 when that selection is security alone
PK_NAME=() PK_CLASS=()
R_PASSED_OVER=null  # {by_class key: n} the dry run passes over (#361)

pk_class_key() {  # <var> <package>: by_class's key for it, or empty
  local _pk_i _pk_k=""
  for _pk_i in ${PK_NAME[@]+"${!PK_NAME[@]}"}; do
    if [ "${PK_NAME[$_pk_i]}" = "$2" ]; then
      case ${PK_CLASS[$_pk_i]} in
        security) _pk_k=security_lower_bound ;;
        updates) _pk_k=updates ;;
        esm) _pk_k=esm_visible ;;
        third-party:*) _pk_k=third_party ;;
        *) _pk_k=ubuntu_other ;;
      esac
      break
    fi
  done
  printf -v "$1" '%s' "$_pk_k"
}

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
      *) _c_third=${_c_third:-$_c_origin} ;;
    esac
  done
  if [ "$_c_esm" -eq 1 ]; then printf -v "$1" esm
  elif [ "$_c_sec" -eq 1 ]; then printf -v "$1" security
  elif [ "$_c_upd" -eq 1 ]; then printf -v "$1" updates
  elif [ -n "$_c_third" ] && [ "$_c_ubu" -eq 0 ]; then printf -v "$1" 'third-party:%s' "${_c_third// /_}"
  else printf -v "$1" ubuntu-other
  fi
}

read_lists_age() {
  local f mt newest="" age=""
  R_LISTS=""
  for f in "$LISTS_DIR"/*-security_InRelease "$LISTS_DIR"/*-security_Release; do
    [ -f "$f" ] || continue
    file_mtime mt "$f"
    if [ -n "$mt" ] && { [ -z "$newest" ] || [ "$mt" -gt "$newest" ]; }; then newest=$mt; fi
  done
  if [ -n "$newest" ]; then age=$(((P_NOW - newest) / 3600)); fi
  jadds R_LISTS dir "${LISTS_DIR#"$P_ROOT"}"
  jaddb R_LISTS refreshed "$REFRESHED"
  jaddn R_LISTS security_age_hours "$age"
  jadds R_LISTS source "the security InRelease's mtime, which apt sets from the archive's Last-Modified"
  if [ -z "$age" ]; then
    finding unknown lists:age "" "No security InRelease under ${LISTS_DIR#"$P_ROOT"}, so the counts have no security list behind them."
  elif [ "$age" -gt 24 ] && [ "$REFRESHED" -eq 0 ]; then
    finding risk lists:stale "" "The security list is $age hours old, so the counts measure the lists, not the host. Re-run with --refresh-into DIR."
  fi
}

# A lower bound for security: where -updates carries a newer version, apt
# shows only that one, and unattended-upgrade still takes the security one
# (usa-wa: 178 against 185). --dry-run-into gives the exact count.
read_simulation() {
  local out line rest name paren origins cls rem="" w t n c tpo="" pk="" seen
  local sec=0 upd=0 esm=0 other=0 ns="" nu="" ne="" nt="" no=""
  local -a thirds=() tp=()
  R_BYCLASS=null R_PACKAGES=null R_REMOVALS=null
  if ! have apt-get; then
    finding unknown pending:simulate "" "apt-get isn't on PATH, so the pending set is unknown."
    return 0
  fi
  capture out apt_env apt-get -s -o Debug::NoLocking=1 "${APT_SIM_PHASED[@]}" "${APT_OPTS[@]}" ${LISTS_OPT[@]+"${LISTS_OPT[@]}"} dist-upgrade
  if [ "$CAP_RC" -ne 0 ]; then
    finding unknown pending:simulate "" "apt-get -s dist-upgrade failed (exit $CAP_RC${CAP_ERR:+: $CAP_ERR}), so the pending set is unknown."
    return 0
  fi
  # The one-origin lane's dry run splits it by origin.
  SIM_DIST_OUT=$out SIM_OK=1
  while IFS= read -r line; do
    case $line in
      "Inst "*)
        rest=${line#Inst }
        name=${rest%% *}
        paren=${rest#*(}
        paren=${paren%%)*}
        origins=${paren#* }
        origins=${origins% \[*}
        class_of cls "$origins"
        PK_NAME+=("$name")
        PK_CLASS+=("$cls")
        PEND="$PEND $name"
        case $cls in
          security) sec=$((sec + 1)) ns="$ns $name" ;;
          updates) upd=$((upd + 1)) nu="$nu $name" ;;
          esm) esm=$((esm + 1)) ne="$ne $name" ;;
          third-party:*)
            nt="$nt $name"
            thirds+=("${cls#third-party:}") ;;
          *) other=$((other + 1)) no="$no $name" ;;
        esac ;;
      "Remv "*)
        rest=${line#Remv }
        jpushs rem "${rest%% *}" ;;
    esac
  done <<<"$out"
  PEND="$PEND "
  # Arrays, not split strings: the origin is the vendor's name (above).
  for t in ${thirds[@]+"${thirds[@]}"}; do
    seen=0
    for c in ${tp[@]+"${tp[@]}"}; do
      if [ "$c" = "$t" ]; then seen=1; fi
    done
    if [ "$seen" -eq 0 ]; then tp+=("$t"); fi
  done
  for t in ${tp[@]+"${tp[@]}"}; do
    n=0
    for c in ${thirds[@]+"${thirds[@]}"}; do
      if [ "$c" = "$t" ]; then n=$((n + 1)); fi
    done
    jaddn tpo "${t//_/ }" "$n"
  done
  R_BYCLASS=""
  jaddn R_BYCLASS security_lower_bound "$sec"
  jaddn R_BYCLASS updates "$upd"
  jaddn R_BYCLASS esm_visible "$esm"
  jaddn R_BYCLASS ubuntu_other "$other"
  jadd R_BYCLASS third_party "{$tpo}"
  R_BYCLASS="{$R_BYCLASS}"
  json_list w "$ns"
  jadd pk security "$w"
  json_list w "$nu"
  jadd pk updates "$w"
  json_list w "$ne"
  jadd pk esm "$w"
  json_list w "$nt"
  jadd pk third_party "$w"
  json_list w "$no"
  jadd pk ubuntu_other "$w"
  R_PACKAGES="{$pk}"
  R_REMOVALS="[$rem]"
  read_phased
}

# Which pending candidates are phased, with their percentage: apt-cache
# policy marks the version "(phased N%)". The simulation shows them all,
# since unattended-upgrade takes them all (#354), so this only flags them.
read_phased() {
  local out line name="" cand="" v pct o=""
  local -a pend_pkgs=()
  R_PHASED=null
  read -r -a pend_pkgs <<<"$PEND" || true
  if [ "${#pend_pkgs[@]}" -eq 0 ]; then
    R_PHASED="{}"
    return 0
  fi
  if ! have apt-cache; then
    not_read "which pending updates are phased: apt-cache isn't installed"
    return 0
  fi
  capture out apt_env apt-cache "${APT_OPTS[@]}" ${LISTS_OPT[@]+"${LISTS_OPT[@]}"} policy "${pend_pkgs[@]}"
  if [ "$CAP_RC" -ne 0 ]; then
    not_read "which pending updates are phased: apt-cache policy exited $CAP_RC${CAP_ERR:+: $CAP_ERR}"
    return 0
  fi
  while IFS= read -r line; do
    case $line in
      [!\ ]*:) name=${line%:} cand="" ;;
      "  Candidate: "*) cand=${line#  Candidate: } ;;
      *"(phased "*"%)")
        read -r v _ <<<"${line# \*\*\* }"
        if [ -n "$name" ] && [ "$v" = "$cand" ] && in_words "$name" "$PEND"; then
          pct=${line##*(phased }
          pct=${pct%\%)}
          jaddn o "$name" "$pct"
        fi ;;
    esac
  done <<<"$out"
  R_PHASED="{$o}"
}

# Ubuntu Pro / ESM: noble-security doesn't patch universe.
read_esm() {
  local pro re k po=""
  R_ESM=null
  # pro takes no root: it reads the machine it runs on, which an offline
  # tree under --root isn't. Inside the image itself, / is that tree.
  if [ -n "$P_ROOT" ] && [ "$P_LIVE" -ne 1 ]; then
    not_read "Ubuntu Pro / ESM: pro security-status reads only the machine it runs on, not a tree under --root, and \"0 security pending\" never covers universe"
    return 0
  fi
  if have pro; then
    capture pro pro security-status --format json
    if [ "$CAP_RC" -eq 0 ]; then
      for k in num_esm_apps_updates num_esm_infra_updates num_universe_packages num_installed_packages; do
        re="\"$k\": *([0-9]+)"
        if [[ $pro =~ $re ]]; then jaddn po "$k" "${BASH_REMATCH[1]}"; else jadd po "$k" null; fi
      done
      re='"attached": *(true|false)'
      if [[ $pro =~ $re ]]; then jadd po attached "${BASH_REMATCH[1]}"; fi
      # pro reads apt's own lists: --refresh-into can't reach it, so these
      # counts can be staler than the ones beside them.
      jadds po lists "the host's own, even under --refresh-into"
      R_ESM="{$po}"
    fi
  fi
  if [ "$R_ESM" = null ]; then
    not_read "Ubuntu Pro / ESM: pro security-status couldn't be read, and \"0 security pending\" never covers universe"
  fi
}

# Language dependencies (#366): the tree a service runs from, which apt never
# sees. A wheel bundles its own native libraries (cryptography's OpenSSL), so
# "0 security pending" never covers it. v1 audits uv.lock only; any other
# lockfile is reported as found, not audited, so it never reads as clean.
LANG_OTHER_LOCKS="package-lock.json poetry.lock Pipfile.lock pnpm-lock.yaml yarn.lock"

passwd_entry() {  # <uid>: PW_NAME and PW_HOME from the tree's /etc/passwd, or both empty
  local _pl _pf
  local -a _pw=()
  PW_NAME="" PW_HOME=""
  [ -r "$P_ROOT/etc/passwd" ] || return 0
  while IFS= read -r _pl || [ -n "$_pl" ]; do
    IFS=: read -r -a _pw <<<"$_pl" || true
    _pf=${_pw[2]:-}
    if [ "$_pf" = "$1" ]; then
      PW_NAME=${_pw[0]} PW_HOME=${_pw[5]:-}
      return 0
    fi
  done <"$P_ROOT/etc/passwd"
}

passwd_home() {  # <var> <user>: that user's home from the tree's /etc/passwd, or empty
  local _ph="" _pl
  local -a _pw=()
  if [ -r "$P_ROOT/etc/passwd" ]; then
    while IFS= read -r _pl || [ -n "$_pl" ]; do
      IFS=: read -r -a _pw <<<"$_pl" || true
      if [ "${_pw[0]:-}" = "$2" ]; then _ph=${_pw[5]:-}; fi
    done <"$P_ROOT/etc/passwd"
  fi
  printf -v "$1" '%s' "$_ph"
}

# The checkout's origin as owner/name, from .git/config read as a file. Only
# a GitHub remote is named, and only by owner/name: a URL can carry a token.
git_origin() {  # <var> <dir>
  local _go="" _gl _gin=0 _gc re='github\.com[:/]+([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$'
  capture _gc as_reader cat -- "$P_ROOT$2/.git/config"
  if [ "$CAP_RC" -eq 0 ]; then
    while IFS= read -r _gl || [ -n "$_gl" ]; do
      _gl=${_gl#"${_gl%%[![:space:]]*}"}
      case $_gl in
        '[remote "origin"]') _gin=1 ;;
        '['*) _gin=0 ;;
        url*=*)
          if [ "$_gin" -eq 1 ]; then
            _gl=${_gl#*=}
            _gl=${_gl#"${_gl%%[![:space:]]*}"}
            _gl=${_gl%/}
            _gl=${_gl%.git}
            if [[ $_gl =~ $re ]]; then _go="${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"; fi
          fi
          ;;
      esac
    done <<<"$_gc"
  fi
  printf -v "$1" '%s' "$_go"
}

# A tree's uv.lock, audited in a copy as the lockfile's owner: never in the
# tree, and never as root, since the uv found may be ~/.local/bin's, which
# its user can rewrite. uv 0.11.8 exits 0 clean, 1 with advisories and 2 on
# an error; its output is text only. Sets LA_AUDITED, LA_N, LA_PKGS (a JSON
# array body) and LA_WHY.
lang_audit() {  # <dir> <user> <home>
  local d=$1 u=$2 home=$3 uvb="" out err="" line re rc n=0 sum="" p
  LA_AUDITED=0 LA_N="" LA_PKGS="" LA_WHY=""
  if [ "$u" = root ]; then
    LA_WHY="its uv.lock is root's, and uv never runs as root here"
    return 0
  fi
  if [ ! -e "$P_ROOT$d/pyproject.toml" ] && ! as_root test -e "$P_ROOT$d/pyproject.toml" 2>/dev/null; then
    LA_WHY="no pyproject.toml beside its uv.lock, which uv audit needs"
    return 0
  fi
  uvb=$(command -v uv 2>/dev/null) || uvb=""
  if [ -z "$uvb" ] && [ -n "$home" ] && [ -x "$P_ROOT$home/.local/bin/uv" ]; then uvb=$P_ROOT$home/.local/bin/uv; fi
  if [ -z "$uvb" ]; then
    LA_WHY="no uv on PATH or in $u's ~/.local/bin"
    return 0
  fi
  # The script's $1..$3 are expanded by the inner sh, from its arguments.
  # shellcheck disable=SC2016
  capture out as_user "$u" env HOME="${home:-/}" sh -c '
    t=$(mktemp -d) || exit 2
    if cp -- "$1" "$2" "$t"/ && cd "$t"; then
      timeout -k 10 60 "$3" audit --frozen --no-cache --no-python-downloads --no-config
      r=$?
    else
      r=2
    fi
    cd / && rm -rf "$t"
    exit $r' sh "$P_ROOT$d/pyproject.toml" "$P_ROOT$d/uv.lock" "$uvb"
  rc=$CAP_RC
  err=$(cat "$P_TMP/stderr" 2>/dev/null) || err=""
  re='^([^ ]+) ([^ ]+) has ([0-9]+) known vulnerabilit(y|ies):$'
  while IFS= read -r line; do
    if [[ $line =~ $re ]]; then
      p=""
      jadds p name "${BASH_REMATCH[1]}"
      jadds p version "${BASH_REMATCH[2]}"
      jaddn p advisories "${BASH_REMATCH[3]}"
      jpush LA_PKGS "{$p}"
      n=$((n + BASH_REMATCH[3]))
    fi
  done <<<"$out"
  re='Found ([0-9]+) known vulnerabilit'
  if [[ $err =~ $re ]]; then sum=${BASH_REMATCH[1]}; fi
  if [ "$rc" -eq 0 ]; then
    LA_AUDITED=1 LA_N=0 LA_PKGS=""
  elif [ "$rc" -eq 1 ] && [ -n "$LA_PKGS" ]; then
    LA_AUDITED=1 LA_N=${sum:-$n}
  else
    # The first error line, else the last line: the experimental warning
    # comes first, and says nothing about this tree.
    LA_WHY=""
    while IFS= read -r line; do
      case $line in error:*) [ -n "$LA_WHY" ] || LA_WHY=$line ;; esac
    done <<<"$err"
    if [ -z "$LA_WHY" ]; then
      while IFS= read -r line; do [ -z "$line" ] || LA_WHY=$line; done <<<"$err"
    fi
    if [ "$rc" -eq 1 ]; then
      LA_WHY="uv audit exited 1, and no advisory in its output could be read${LA_WHY:+: $LA_WHY}"
    else
      LA_WHY="uv audit exited $rc${LA_WHY:+: $LA_WHY}"
    fi
    LA_PKGS=""
  fi
}

read_language() {
  local f u dir user line trees="" complete=1 i e r o owner oline uid lf k
  local -a dirs=() units=() of=()
  R_LANG=null
  if [ "$P_LIVE" -ne 1 ]; then
    not_read "language dependencies: uv audit runs only on the machine it audits, not a tree under --root"
    return 0
  fi
  # An audit asks OSV, and takes up to a minute a tree. Like the lists'
  # refresh, it's taken only when asked: apply.sh's probe after each step
  # never asks, and an apt step can't change a lockfile (CR 231).
  if [ -z "$refresh" ]; then
    not_read "language dependencies: audited only with --refresh-into, which takes the probe's network readings"
    return 0
  fi
  # Every unit file the host's admin installed, and each knob service.
  local files="" d
  for f in "$P_ROOT"/etc/systemd/system/*.service; do
    [ -f "$f" ] && files="$files"$'\n'"$f"
  done
  for u in $KNOB_SERVICES; do
    for d in etc/systemd/system run/systemd/system usr/local/lib/systemd/system usr/lib/systemd/system lib/systemd/system; do
      if [ -f "$P_ROOT/$d/$u" ]; then
        case $files in *$'\n'"$P_ROOT/$d/$u"*) ;; *) files="$files"$'\n'"$P_ROOT/$d/$u" ;; esac
        break
      fi
    done
  done
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    capture o as_reader cat -- "$f"
    [ "$CAP_RC" -eq 0 ] || continue
    dir="" user=""
    while IFS= read -r line || [ -n "$line" ]; do
      case $line in
        WorkingDirectory=*) dir=${line#WorkingDirectory=} ;;
        User=*) user=${line#User=} ;;
      esac
    done <<<"$o"
    dir=${dir#-}
    case $dir in
      '' | *%*) continue ;;
      '~')
        passwd_home dir "${user:-root}"
        [ -n "$dir" ] || continue
        ;;
      /*) ;;
      *) continue ;;
    esac
    dir=${dir%/}
    [ -n "$dir" ] || dir=/
    k=-1
    for i in ${dirs[@]+"${!dirs[@]}"}; do
      if [ "${dirs[$i]}" = "$dir" ]; then k=$i; fi
    done
    if [ "$k" -ge 0 ]; then
      units[k]="${units[$k]} ${f##*/}"
    else
      dirs+=("$dir") units+=("${f##*/}")
    fi
  done <<<"$files"

  for i in ${dirs[@]+"${!dirs[@]}"}; do
    dir=${dirs[$i]}
    owner="" oline=""
    for r in ${KNOB_OWNER[@]+"${KNOB_OWNER[@]}"}; do
      IFS=$KNOB_US read -r -a of <<<"$r"
      if glob_match "$dir" "${of[0]}"; then owner=${of[1]} oline=${of[2]}; fi
    done
    if [ -z "$owner" ]; then git_origin owner "$dir"; fi
    for lf in uv.lock $LANG_OTHER_LOCKS; do
      if [ ! -e "$P_ROOT$dir/$lf" ] && ! as_root test -e "$P_ROOT$dir/$lf" 2>/dev/null; then continue; fi
      e=""
      jadds e dir "$dir"
      jadds e lockfile "$lf"
      o=""
      for u in ${units[$i]}; do jpushs o "$u"; done
      jadd e units "[$o]"
      jadds e owner "${owner:-unknown}"
      jaddn e owner_line "$oline"
      if [ "$lf" = uv.lock ]; then
        file_owner uid "$P_ROOT$dir/$lf"
        passwd_entry "$uid"
        if [ -z "$PW_NAME" ]; then
          LA_AUDITED=0 LA_N="" LA_PKGS="" LA_WHY="its uv.lock's owner, uid ${uid:-unknown}, isn't in /etc/passwd"
        else
          lang_audit "$dir" "$PW_NAME" "$PW_HOME"
        fi
      else
        LA_AUDITED=0 LA_N="" LA_PKGS="" LA_WHY="$lf: v1 audits uv.lock only"
      fi
      jaddb e audited "$LA_AUDITED"
      jaddn e advisories "$LA_N"
      if [ "$LA_AUDITED" -eq 1 ]; then jadd e packages "[$LA_PKGS]"; else jadd e packages null; fi
      jaddsn e why "$LA_WHY"
      [ "$LA_AUDITED" -eq 1 ] || complete=0
      jpush trees "{$e}"
    done
  done
  o=""
  jadd o trees "[$trees]"
  jaddb o complete "$complete"
  R_LANG="{$o}"
}

# A changed conffile's state on disk, for each conffile a package lists that
# isn't obsolete: missing, modified, or unread. unattended-upgrade passes a
# package over at a conffile prompt even where dpkg wouldn't ask, as for a
# conffile the image deleted (wslcb's fwupd, #361). 1 when dpkg can't say.
conffile_states() {  # <var> <package>: VAR := a JSON array body
  local _cs_out _cs_p _cs_m _cs_o _cs_cur _cs_st _cs_e _cs_a=""
  capture _cs_out dpkgq -W -f "$DPKG_CONFFILES" "$2"
  [ "$CAP_RC" -eq 0 ] || return 1
  while read -r _cs_p _cs_m _cs_o; do
    [ -n "$_cs_p" ] || continue
    if [ "$_cs_o" = obsolete ] || [ "$_cs_m" = newconffile ]; then continue; fi
    if [ ! -e "$P_ROOT$_cs_p" ] && [ ! -L "$P_ROOT$_cs_p" ]; then
      _cs_st=missing
    else
      capture _cs_cur as_reader md5sum -- "$P_ROOT$_cs_p"
      _cs_cur=${_cs_cur%% *}
      if [ "$CAP_RC" -ne 0 ] || [ -z "$_cs_cur" ]; then
        _cs_st=unread
      elif [ "$_cs_cur" != "$_cs_m" ]; then
        _cs_st=modified
      else
        continue
      fi
    fi
    _cs_e=""
    jadds _cs_e path "$_cs_p"
    jadds _cs_e state "$_cs_st"
    jpush _cs_a "{$_cs_e}"
  done <<<"$_cs_out"
  printf -v "$1" '%s' "$_cs_a"
}

read_dry_run() {
  local o="" conf t0 t1 out rc line names="" n="" dlk="" free="" rss="" w sel=0 lnames="" lkeep="" lskip=""
  local oleft="" left_read=0 kw p rest unlisted="" prompts="" cfp="" cfs="" i k keys="" po=""
  local -a words=() cf_states=() cf_keys=()
  R_DRY=null R_PASSED_OVER=null
  if [ -z "$dryrun" ]; then
    not_read "the exact security count and the dry run's cost: only with --dry-run-into DIR, which downloads the whole set as root"
    return 0
  fi
  # apply.sh counts with DIR/summary: an earlier one goes first, so a dry
  # run that doesn't run, or fails, never leaves another's behind.
  rm -f -- "$dryrun/summary" 2>/dev/null || true
  if [ -e "$dryrun/summary" ]; then
    finding unknown dry-run "" "the dry run didn't run: an earlier $dryrun/summary couldn't be removed, and apply.sh would count with it. Remove it, then count again."
    return 0
  fi
  if [ "$P_PRIV" = none ]; then
    finding unknown dry-run "" "--dry-run-into needs root, and sudo -n needs a password: the dry run didn't run."
    return 0
  fi
  conf=$dryrun/apt.conf
  # apt fetches into archives/partial, and the dry run's fetcher never makes
  # it: without it, every download failed (noble, 2026-10-01).
  mkdir -p "$dryrun/archives/partial"
  # Another lane counts what apply.sh takes in it: the host's own origins,
  # plus the lane's, and for one origin, every other pending package skipped.
  if [ "$lane" != security ] && ! lane_patterns "$lane"; then
    finding unknown dry-run "" "the $lane lane's dry run didn't run: $LANE_WHY."
    return 0
  fi
  case $lane in
    origin:*)
      if [ "$SIM_OK" -ne 1 ]; then
        finding unknown dry-run "" "the $lane lane's dry run didn't run: the pending set couldn't be simulated, so what it would skip is unknown."
        return 0
      fi
      # A site maps to its o= names through apt-cache policy: unread, or
      # listing no origin there, nothing would be told from the rest, and
      # the dry run would skip everything and count nothing.
      case ${lane#origin:} in *.*)
        if [ -n "$POLICY_WHY" ]; then
          finding unknown dry-run "" "the $lane lane's dry run didn't run: $POLICY_WHY, so which pending packages come from ${lane#origin:} is unknown."
          return 0
        fi ;;
      esac
      origin_names lnames "${lane#origin:}" "$POLICY_OUT"
      if [ "$lnames" = "|" ]; then
        finding unknown dry-run "" "the $lane lane's dry run didn't run: apt-cache policy lists no origin at ${lane#origin:}, so nothing from it is pending: is its source configured?"
        return 0
      fi
      origin_split lkeep lskip "$lnames" "$SIM_DIST_OUT" ;;
  esac
  {
    if [ -n "$P_ROOT" ]; then printf 'Dir "%s/";\n' "$P_ROOT"; fi
    printf 'Dir::Cache::archives "%s/archives/";\n' "$dryrun"
    if [ "$REFRESHED" -eq 1 ]; then printf 'Dir::State::Lists "%s/";\n' "$LISTS_DIR"; fi
    if [ "$lane" != security ]; then lane_conf "${LANE_PATTERNS[@]}"; fi
    # Word lists, each a package name.
    # shellcheck disable=SC2086
    case $lane in origin:*) lane_skip_conf $lskip ;; esac
  } >"$conf"
  if [ -n "$lkeep$lskip" ]; then
    json_list w "$lkeep"
    jadd o origin_pending "$w"
  fi
  rss_timer "$dryrun/max-rss-kib"
  t0=$(date +%s)
  rc=0
  # At adj 0: the session may run at -1000, and the dry run would inherit it.
  if have choom; then
    as_root env "APT_CONFIG=$conf" choom -n 0 -- ${TIMER[@]+"${TIMER[@]}"} unattended-upgrade --dry-run -d >"$dryrun/dry-run.log" 2>&1 || rc=$?
  else
    as_root env "APT_CONFIG=$conf" ${TIMER[@]+"${TIMER[@]}"} unattended-upgrade --dry-run -d >"$dryrun/dry-run.log" 2>&1 || rc=$?
  fi
  t1=$(date +%s)
  # The selection line can be empty: with nothing to upgrade but auto-removals
  # pending, unattended-upgrade still logs it (2.9.1's run()). Seen, it's the
  # count, 0 included, whether or not a space follows the colon.
  while IFS= read -r line; do
    case $line in
      *"Packages that will be upgraded:"*) names=${line#*Packages that will be upgraded:} sel=1 ;;
      *"No packages found that can be upgraded unattended"*) n=0 ;;
      # unattended-upgrade 2.9.1 prints it, and logs it as a warning.
      *"Package "*" has conffile prompt and needs to be upgraded manually"*)
        p=${line##*Package }
        p=${p%% has conffile prompt*}
        in_words "$p" "$prompts" || prompts="$prompts $p" ;;
    esac
  done <"$dryrun/dry-run.log"
  if [ "$sel" -eq 1 ]; then
    read -r -a words <<<"$names" || true
    n=${#words[@]}
    SEC_EXACT=" ${words[*]-} "
    # What it selects and the class lists don't name would reach the host
    # unseen in the proposal: replicator's phased package did (#354).
    if [ "$SIM_OK" -eq 1 ]; then
      for p in ${words[@]+"${words[@]}"}; do
        in_words "$p" "$PEND" || unlisted="$unlisted $p"
      done
    fi
  fi
  # The origin's upgrades the selection leaves out: unattended-upgrade would
  # pass them over, so apply.sh refuses the window before it changes
  # anything. Only upgrades count: a new package an upgrade needs comes with
  # it, and is never named in the selection.
  case $lane in
    origin:*)
      if [ -n "$n" ]; then
        left_read=1
        while read -r kw p rest; do
          case $kw:$rest in
            Inst:"["*) if in_words "$p" "$lkeep" && ! in_words "$p" "${words[*]-}"; then oleft="$oleft $p"; fi ;;
          esac
        done <<<"$SIM_DIST_OUT"
      fi ;;
  esac
  out=$(cat "$dryrun/max-rss-kib" 2>/dev/null) || out=""
  rss_of rss "$out"
  out=$(du -sk "$dryrun/archives" 2>/dev/null) || out=""
  dlk=${out%%[[:space:]]*}
  out=$(df -Pk "$P_ROOT/var/cache/apt/archives" 2>/dev/null) || out=""
  free=$(printf '%s\n' "$out" | awk 'NR == 2 { print $4 }')
  jaddn o exit "$rc"
  jaddn o count "$n"
  json_list w "$names"
  jadd o packages "$w"
  jaddn o wall_seconds "$((t1 - t0))"
  jaddn o max_rss_kib "$rss"
  jaddn o download_kib "$dlk"
  jaddn o free_kib_apt_cache "$free"
  jadds o log "$dryrun/dry-run.log"
  jadds o cache "$dryrun/archives, root-owned: remove it when done"
  # The selection is whatever the host's unattended-upgrades origins take:
  # security alone only when apt-config was read, an origin is set, and none
  # widens them (read_periodic). Otherwise it holds -updates or third-party
  # packages too, and isn't a security count.
  # No other lane's is: maintenance adds -updates and the followed origins,
  # and origin:<key> takes one origin alone.
  if [ "$lane" = security ] && [ "$APT_CONFIG_OK" -eq 1 ] && [ "$UU_ORIGINS_N" -gt 0 ] && [ -z "$UU_WIDE" ]; then
    DRY_SECURITY_ONLY=1
  fi
  jadds o lane "$lane"
  jaddb o security_only "$DRY_SECURITY_ONLY"
  if [ "$SIM_OK" -eq 1 ] && [ "$sel" -eq 1 ]; then
    json_list w "$unlisted"
    jadd o unlisted "$w"
  else
    jadd o unlisted null
  fi
  # Each package it passed over at a conffile prompt: its class still counts
  # it, though the lane won't install it, so by_class.passed_over marks it
  # (#361). Read once each: the record and the finding say the same thing
  # (CR 213).
  for p in $prompts; do
    w=""
    jadds w package "$p"
    pk_class_key k "$p"
    cf_keys+=("$k")
    if [ -n "$k" ]; then
      jadds w class "$k"
      keys="$keys $k"
    else
      jadd w class null
    fi
    if conffile_states cfs "$p"; then
      jadd w conffiles "[$cfs]"
      cf_states+=("$cfs")
    else
      jadd w conffiles null
      cf_states+=("?")
    fi
    jpush cfp "{$w}"
  done
  jadd o conffile_prompts "[$cfp]"
  for k in security_lower_bound updates esm_visible ubuntu_other third_party; do
    i=0
    for w in $keys; do
      if [ "$w" = "$k" ]; then i=$((i + 1)); fi
    done
    if [ "$i" -gt 0 ]; then jaddn po "$k" "$i"; fi
  done
  R_PASSED_OVER="{$po}"
  case $lane in
    origin:*)
      w=null
      if [ "$left_read" -eq 1 ]; then json_list w "$oleft"; fi
      jadd o origin_left "$w" ;;
  esac
  # apply.sh reads it: the dry run's wall time is the floor of each step's
  # expected duration, and in the one-origin lane, what it would leave.
  {
    printf 'began=%s\nexit=%s\ncount=%s\nwall_seconds=%s\nsecurity_only=%s\nlane=%s\n' \
      "$t0" "$rc" "$n" "$((t1 - t0))" "$DRY_SECURITY_ONLY" "$lane"
    if [ "$left_read" -eq 1 ]; then printf 'origin_left=%s\n' "${oleft# }"; fi
  } >"$dryrun/summary"
  jadds o summary "$dryrun/summary"
  R_DRY="{$o}"
  i=0
  for p in $prompts; do
    cfs=${cf_states[$i]}
    k=${cf_keys[$i]}
    i=$((i + 1))
    if [ "$cfs" != "?" ]; then
      cfs=$(printf '%s' "$cfs" | sed -e 's/{"path": "\([^"]*\)", "state": "\([^"]*\)"}/\1 (\2)/g')
      cfs=${cfs:-none it could read as changed}
    else
      cfs="unknown: dpkg-query couldn't list them"
    fi
    finding risk "dry-run:conffile:$p" "" "unattended-upgrade passes over $p at a conffile prompt, so the lane won't install it${k:+, though by_class.$k counts it (by_class.passed_over marks it)} (the dry run exited $rc). Its conffiles on disk: $cfs. Choose a remedy: hold it, declared as exception held:$p <review-by> <reason>; reinstall it with -o Dpkg::Options::=--force-confmiss (a deleted conffile) or settle the change by hand; or prune it (policy.md)."
  done
  if [ -n "$unlisted" ]; then
    finding risk dry-run:unlisted "" "The dry run selects${unlisted}, which the pending set's class lists don't name: the proposal's counts leave them out, and the apply would take them. Read each in apt-cache policy before proposing."
  fi
  if [ "$rc" -ne 0 ]; then
    w=""
    if [ -n "$prompts" ]; then w=" It passed over${prompts} at a conffile prompt: see each dry-run:conffile finding."; fi
    finding unknown dry-run "" "unattended-upgrade --dry-run exited $rc: read $dryrun/dry-run.log. The security count stays a lower bound.$w"
  elif [ -z "$n" ]; then
    finding unknown dry-run "" "unattended-upgrade --dry-run exited 0, but its log has neither a \"Packages that will be upgraded\" line nor \"No packages found\": read $dryrun/dry-run.log. The security count stays a lower bound."
  fi
}

read_holds() {
  local r name m hm e hl flag
  local -a hf=() all=()
  R_HOLDGROUPS="" R_OWNERHOLDS=null
  read -r -a all <<<"$PEND $SEC_EXACT" || true
  # Held groups: which of each hold step's globs are in the set.
  for r in ${KNOB_HOLD[@]+"${KNOB_HOLD[@]}"}; do
    IFS=$KNOB_US read -r -a hf <<<"$r"
    m=""
    for name in ${all[@]+"${all[@]}"}; do
      if ! in_words "$name" "$m" && glob_match "$name" "${hf[1]}"; then m="$m $name"; fi
    done
    json_list hm "$m"
    # Which of its globs are pending is unknown while the set is.
    if [ "$SIM_OK" -ne 1 ]; then hm=null; fi
    e=""
    jadds e step "${hf[0]}"
    jadd e pending "$hm"
    jaddn e line "${hf[2]-}"
    jpush R_HOLDGROUPS "{$e}"
  done
  # The owner's own holds. apt-get -s keeps a held package back, so it never
  # reaches the set above: each hold's installed and candidate versions come
  # from apt-cache policy instead. One with an update waiting defers the fix
  # indefinitely unless an exception declares it (policy.md).
  have apt-mark || return 0
  capture hl apt_env apt-mark showhold
  [ "$CAP_RC" -eq 0 ] || return 0
  R_OWNERHOLDS=""
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    held_versions "$name"
    flag=""
    # A hold on a package that isn't installed defers nothing.
    if [ -n "$HV_INSTALLED" ] && [ -n "$HV_CANDIDATE" ]; then
      flag=0
      if [ "$HV_INSTALLED" != "(none)" ] && [ "$HV_CANDIDATE" != "$HV_INSTALLED" ] &&
        [ "$HV_CANDIDATE" != "(none)" ]; then flag=1; fi
    fi
    if [ "$flag" = 1 ]; then
      if [ "$HV_SECURITY" -eq 1 ]; then e="a security update"; else e="an update"; fi
      finding deviation "held:$name" "held:$name" "$name is held (apt-mark showhold) with $e waiting ($HV_INSTALLED to $HV_CANDIDATE), so every run and the daily timer skip it. Declare exception held:$name <review-by> <reason>, or release the hold (policy.md)."
    fi
    e=""
    jadds e package "$name"
    jaddsn e installed "$HV_INSTALLED"
    jaddsn e candidate "$HV_CANDIDATE"
    jaddb e pending "$flag"
    if [ "$flag" = 1 ]; then jaddb e security "$HV_SECURITY"; fi
    jpush R_OWNERHOLDS "{$e}"
  done <<<"$hl"
  R_OWNERHOLDS="[$R_OWNERHOLDS]"
}

held_versions() {  # <package>: HV_INSTALLED, HV_CANDIDATE, and HV_SECURITY 1 when a newer version is in a -security suite
  local out line newer=1
  HV_INSTALLED="" HV_CANDIDATE="" HV_SECURITY=0
  have apt-cache || return 0
  capture out apt_env apt-cache "${APT_OPTS[@]}" ${LISTS_OPT[@]+"${LISTS_OPT[@]}"} policy "$1"
  [ "$CAP_RC" -eq 0 ] || return 0
  while IFS= read -r line; do
    case $line in
      *"Installed: "*) HV_INSTALLED=${line#*Installed: } ;;
      *"Candidate: "*) HV_CANDIDATE=${line#*Candidate: } ;;
      " *** "*) newer=0 ;;
      *-security/*) if [ "$newer" -eq 1 ]; then HV_SECURITY=1; fi ;;
    esac
  done <<<"$out"
}

read_pending() {
  local o=""
  read_lists_age
  read_simulation
  read_esm
  read_language
  read_dry_run
  read_holds
  jadd o lists "{$R_LISTS}"
  if [ "$R_BYCLASS" != null ]; then
    R_BYCLASS=${R_BYCLASS#\{}
    R_BYCLASS=${R_BYCLASS%\}}
    jadd R_BYCLASS passed_over "$R_PASSED_OVER"
    R_BYCLASS="{$R_BYCLASS}"
  fi
  jadd o by_class "$R_BYCLASS"
  jadd o packages "$R_PACKAGES"
  jadd o removals "$R_REMOVALS"
  jadd o phased "$R_PHASED"
  jadd o esm "$R_ESM"
  jadd o language "$R_LANG"
  jadd o dry_run "$R_DRY"
  jadd o hold_groups "[$R_HOLDGROUPS]"
  jadd o owner_holds "$R_OWNERHOLDS"
  R_PEND=$o
}

# --- impact -----------------------------------------------------------------
DS_UNITS="" KNOB_SERVICES="" KNOB_RESTARTERS="" KNOB_BACKUPS=""

unit_of_pid() {  # <var> <pid>: the systemd unit its cgroup names, or empty
  local _up_l _up_u=""
  if [ -r "$P_ROOT/proc/$2/cgroup" ]; then
    while IFS= read -r _up_l; do
      case $_up_l in 0::*) _up_u=${_up_l##*/} ;; esac
    done <"$P_ROOT/proc/$2/cgroup"
    case $_up_u in *.service | *.scope) ;; *) _up_u="" ;; esac
  fi
  printf -v "$1" '%s' "$_up_u"
}

# Which processes map a shared object from a pending package: Postgres needs
# a restart when its backends map libc6 or libxml2, even with its own
# package out of the set.
read_maps() {
  local p f out line pid pkg u e w pairs="" ulist="" pk pids np
  local -a maps=()
  R_MAPS=null
  # An unsimulated set isn't an empty one: what maps it is unknown.
  if [ "$SIM_OK" -ne 1 ]; then
    not_read "which processes map a library in the set: the pending set couldn't be simulated"
    return 0
  fi
  if [ -z "${PEND// /}" ]; then
    R_MAPS='{"units": [], "note": "nothing pending"}'
    return 0
  fi
  if [ "$P_LIVE" -ne 1 ] || [ "$P_PRIV" = none ] || ! have dpkg-query; then
    not_read "which processes map a library in the set: needs root and a running system"
    return 0
  fi
  : >"$P_TMP/libs.tsv"
  : >"$P_TMP/libs.pat"
  for p in $PEND; do
    capture out dpkgq -L "$p"
    while IFS= read -r f; do
      case $f in
        *.so | *.so.[0-9]*)
          printf '%s\t%s\n' "$p" "${f#/usr}" >>"$P_TMP/libs.tsv"
          printf '%s\n' "${f#/usr}" >>"$P_TMP/libs.pat" ;;
      esac
    done <<<"$out"
  done
  if [ ! -s "$P_TMP/libs.pat" ]; then
    R_MAPS='{"units": [], "note": "no shared object in the pending set"}'
    return 0
  fi
  for f in "$P_ROOT"/proc/[0-9]*/maps; do
    if [ -e "$f" ]; then maps+=("$f"); fi
  done
  if [ "${#maps[@]}" -eq 0 ]; then return 0; fi
  capture out as_root grep -H -o -F -f "$P_TMP/libs.pat" -- "${maps[@]}"
  if [ "$CAP_RC" -gt 1 ] && [ -z "$out" ]; then
    not_read "which processes map a library in the set: grep over /proc/*/maps failed as root"
    return 0
  fi
  # "<pid> <package>" once per pair; a /usr-less pattern matches either path.
  printf '%s\n' "$out" >"$P_TMP/maps.out"
  out=$(awk 'NR == FNR { split($0, a, "\t"); pkg[a[2]] = a[1]; next }
    { i = index($0, ":"); path = substr($0, 1, i - 1); lib = substr($0, i + 1)
      if (!(lib in pkg)) next
      n = split(path, parts, "/"); k = parts[n - 1] " " pkg[lib]
      if (!(k in seen)) { seen[k] = 1; print k } }' "$P_TMP/libs.tsv" "$P_TMP/maps.out")
  while read -r pid pkg; do
    [ -n "$pid" ] || continue
    unit_of_pid u "$pid"
    pairs="$pairs ${u:-unknown}|$pkg|$pid"
    in_words "${u:-unknown}" "$ulist" || ulist="$ulist ${u:-unknown}"
  done <<<"$out"
  local byunit=""
  for u in $ulist; do
    pk="" pids="" np=0
    for e in $pairs; do
      case $e in "$u|"*)
        p=${e#*|}
        pid=${p#*|}
        p=${p%%|*}
        in_words "$p" "$pk" || pk="$pk $p"
        if ! in_words "$pid" "$pids"; then
          pids="$pids $pid"
          np=$((np + 1))
        fi ;;
      esac
    done
    e=""
    jadds e unit "$u"
    jaddn e processes "$np"
    json_list w "$pk"
    jadd e packages "$w"
    if in_words "$u" "$DS_UNITS"; then jaddb e datastore 1; else jaddb e datastore 0; fi
    jpush byunit "{$e}"
  done
  R_MAPS="{\"units\": [$byunit], \"source\": \"/proc/*/maps, read as root, against each pending package's shared objects\"}"
}

PG_CLUSTERS=""  # " ver/name/port/status/logfile ..."
# One record per database, its fields split on the unit separator: a name
# may hold a space, a '*' or a '|', so it's never split on IFS or globbed.
PG_ROWS=()     # ver/name db writes stats_reset own_tables created started sessions
PG_READ=""      # " ver/name ...": clusters whose catalogs were read
read_pg_clusters() {
  local out line ver name port status owner dir log
  PG_CLUSTERS=""
  live_cmd pg_lsclusters || return 1
  capture out pg_lsclusters -h
  [ "$CAP_RC" -eq 0 ] || return 1
  while IFS= read -r line; do
    read -r ver name port status owner dir log <<<"$line"
    [ -n "$ver" ] || continue
    PG_CLUSTERS="$PG_CLUSTERS $ver/$name/$port/${status%%,*}/$log"
  done <<<"$out"
  return 0
}

# The creation dates need pg_stat_file, which a role that isn't a superuser
# may not run, and Postgres checks that before the query runs, so a CASE
# around it doesn't help (measured on 16). Refused, pg_databases asks again
# without it: only the dates are lost.
PG_Q_HEAD="select d.datname, pg_database_size(d.oid), coalesce(s.tup_inserted + s.tup_updated + s.tup_deleted, 0), coalesce(extract(epoch from s.stats_reset)::bigint::text, ''), d.datcollate, coalesce(to_jsonb(d) ->> 'datlocprovider', 'c'), coalesce(to_jsonb(d) ->> 'datcollversion', ''), coalesce(case when d.datname = current_database() then (select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace where c.relkind in ('r', 'p', 'm') and n.nspname <> 'information_schema' and n.nspname !~ '^pg_')::text end, '')"
PG_Q_TAIL="extract(epoch from pg_postmaster_start_time())::bigint, coalesce(to_jsonb(s) ->> 'sessions', '') from pg_database d left join pg_stat_database s on s.datid = d.oid where not d.datistemplate order by 1"
PG_Q="$PG_Q_HEAD, coalesce(extract(epoch from (pg_stat_file('base/' || d.oid || '/PG_VERSION', true)).modification)::bigint::text, ''), $PG_Q_TAIL"
PG_Q_PLAIN="$PG_Q_HEAD, '', $PG_Q_TAIL"

# Fields split on the unit separator, not a tab: a tab is IFS whitespace, so
# an empty stats_reset would vanish and shift every field after it. In order:
# name, size, writes, stats_reset, collate, provider, collversion; then
# own_tables, the connected database's own tables, so only postgres's row has
# it (the default database, where an app may keep its tables); created,
# PG_VERSION's mtime (empty outside the default tablespace); the server's
# start; and the sessions since the statistics were reset (Postgres 14 on).
# datlocprovider and datcollversion came with Postgres 15: read through
# to_jsonb, they're null on 14 (jammy's), where naming them fails the whole
# query. Before 15 every database's provider was libc, so a missing one
# reads c.
pg_databases() {  # <port>: rows of PG_Q, as the postgres user; of PG_Q_PLAIN when pg_stat_file is refused
  local _pd_rc=0
  as_user postgres psql -XAtq -F "$KNOB_US" -p "$1" -d postgres -c "$PG_Q" 2>"$P_TMP/pg_q.err" || _pd_rc=$?
  if [ "$_pd_rc" -ne 0 ] && grep -q pg_stat_file "$P_TMP/pg_q.err"; then
    as_user postgres psql -XAtq -F "$KNOB_US" -p "$1" -d postgres -c "$PG_Q_PLAIN"
    return
  fi
  cat "$P_TMP/pg_q.err" >&2
  return "$_pd_rc"
}

# Each cluster's databases, with collation and activity, and any database no
# datastore line names: the recovery point wouldn't cover it.
read_datastores() {
  local r e c out db size writes reset coll prov cver own created started sess dbs d declared="" cls="" ver name port status what
  local -a df=()
  R_DS=""
  for r in ${KNOB_DATASTORE[@]+"${KNOB_DATASTORE[@]}"}; do
    IFS=$KNOB_US read -r -a df <<<"$r"
    if [ "${df[0]}" = postgres ]; then declared="$declared ${df[2]}"; fi
  done
  if ! read_pg_clusters; then
    jadd R_DS postgres null
    return 0
  fi
  for c in $PG_CLUSTERS; do
    IFS=/ read -r ver name port status _ <<<"$c"
    e="" dbs=""
    jadds e cluster "$ver/$name"
    jaddn e port "$port"
    jadds e status "$status"
    if [ "$status" = online ]; then
      capture out pg_databases "$port"
      if [ "$CAP_RC" -eq 0 ]; then
        PG_READ="$PG_READ $ver/$name"
        while IFS=$KNOB_US read -r db size writes reset coll prov cver own created started sess; do
          [ -n "$db" ] || continue
          d=""
          jadds d name "$db"
          jaddn d size_bytes "$size"
          jaddn d writes_since_stats_reset "$writes"
          jaddn d stats_reset "$reset"
          jaddsn d collate "$coll"
          jaddsn d provider "$prov"
          jaddsn d collversion "$cver"
          if [ -n "$own" ]; then jaddn d own_tables "$own"; fi
          jaddn d created "$created"
          jaddn d sessions_since_stats_reset "$sess"
          jpush dbs "{$d}"
          PG_ROWS+=("$ver/$name$KNOB_US$db$KNOB_US${writes:-0}$KNOB_US${reset:-}$KNOB_US${own:-}$KNOB_US${created:-}$KNOB_US${started:-}$KNOB_US${sess:-}")
          case $db in template0 | template1) continue ;; esac
          what="$db,"
          if [ "$db" = postgres ]; then
            if ! is_int "$own" || [ "$own" -eq 0 ]; then continue; fi
            what="its postgres database, with $own tables of its own,"
          fi
          if ! in_words "$db" "$declared"; then
            finding knob "database:$db" "database:$db" "The $ver/$name cluster holds $what which no datastore line names, so the recovery point wouldn't cover it. Name it in a datastore postgres line (knob.md)."
          fi
        done <<<"$out"
        jadd e databases "[$dbs]"
      else
        jadd e databases null
        jadds e unread "${CAP_ERR:-psql as postgres failed}"
      fi
    fi
    jpush cls "{$e}"
  done
  jadd R_DS postgres "[$cls]"
}

cmdline_of() {  # <var> <pid>
  local _ca
  _ca=$(tr '\0' ' ' <"$P_ROOT/proc/$2/cmdline" 2>/dev/null) || _ca=""
  printf -v "$1" '%s' "${_ca% }"
}

# Live arguments come from /proc/<pid>/cmdline, never the journal, which keeps
# every start's arguments (wslcb quoted earlyoom's boot-time block).
read_cmdlines() {
  local f pid comm args svc e
  R_ARGS=""
  for f in "$P_ROOT"/proc/[0-9]*/comm; do
    [ -r "$f" ] || continue
    IFS= read -r comm <"$f" || true
    [ "$comm" = earlyoom ] || continue
    pid=${f%/comm}
    pid=${pid##*/}
    cmdline_of args "$pid"
    e=""
    jadds e process earlyoom
    jaddn e pid "$pid"
    jadds e args "$args"
    jadds e source "/proc/$pid/cmdline"
    jpush R_ARGS "{$e}"
  done
  for svc in $KNOB_SERVICES; do
    unit_show "$svc" MainPID || continue
    pid=$U_MainPID
    if is_int "$pid" && [ "$pid" -gt 0 ] && [ -r "$P_ROOT/proc/$pid/cmdline" ]; then
      cmdline_of args "$pid"
      e=""
      jadds e process "$svc"
      jaddn e pid "$pid"
      jadds e args "$args"
      jadds e source "/proc/$pid/cmdline"
      jpush R_ARGS "{$e}"
    fi
  done
}

ordering_ok() {  # <datastore unit> <After= list>
  case " $2 " in *" $1 "*) return 0 ;; esac
  case $1 in postgresql@*) case " $2 " in *" postgresql.service "*) return 0 ;; esac ;; esac
  return 1
}

# Each runbook service: its ordering on every data store, and what Requires= it.
read_services() {
  local svc e ds bad w
  R_SVC=""
  for svc in $KNOB_SERVICES; do
    e=""
    jadds e unit "$svc"
    if unit_show "$svc" After RequiredBy BoundBy Result NRestarts ActiveState; then
      jadds e active_state "$U_ActiveState"
      jaddsn e result "$U_Result"
      jaddn e restarts "$U_NRestarts"
      bad=""
      for ds in $DS_UNITS; do
        # A service that is itself the data store, as co-index's Qdrant is.
        [ "$ds" != "$svc" ] || continue
        ordering_ok "$ds" "$U_After" || bad="$bad $ds"
      done
      json_list w "$bad"
      jadd e missing_after "$w"
      json_list w "$U_RequiredBy $U_BoundBy"
      jadd e required_by "$w"
      if [ -n "$bad" ]; then
        finding risk "ordering:$svc" "ordering:$svc" "$svc has no After= on${bad}: its first start after a boot succeeds only by luck, whatever its last start did (CannObserv/address-validator#239). Add After=, not Wants=."
      fi
    else
      jadd e active_state null
    fi
    jpush R_SVC "{$e}"
  done
}

# What runs a unit's Exec lines can restart: a systemctl start or restart on
# the line, or in a script it runs. Comment lines don't count: replicator's
# notifier mentions `systemctl status` in one.
RESTART_RE='systemctl[^#]*(start|restart|try-restart|reload-or-restart)'

# Programs that start no unit, whatever their arguments, and the shell
# builtins an inline command may use.
INERT_PROGS="curl wget logger systemd-cat true echo printf"
SHELL_BUILTINS=": [ test exit"

# Whether an inline command (sh -c '...') restarts anything, read as simple
# commands: 0 when it can, 1 when each command word was read and can't, 2
# when one couldn't be, with IV_WHY saying which (CR 205). A path runs a
# script, read like any other; a bare name must start nothing.
inline_verdict() {  # <command>
  local cmd=$1 seg w i rc=1 v
  local -a ws=()
  IV_WHY=""
  cmd=${cmd//[\'\"]/ }
  cmd=${cmd//&&/$'\n'}
  cmd=${cmd//||/$'\n'}
  cmd=${cmd//[;&|()]/$'\n'}
  while IFS= read -r seg; do
    read -r -a ws <<<"$seg" || true
    i=0
    while [ "$i" -lt "${#ws[@]}" ] && case ${ws[$i]} in *=* | exec | command | nohup) true ;; *) false ;; esac; do i=$((i + 1)); done
    [ "$i" -lt "${#ws[@]}" ] || continue
    w=${ws[$i]}
    case $w in
      /*)
        v=0
        script_verdict "$w" || v=$?
        case $v in
          0) return 0 ;;
          2) IV_WHY=$SV_WHY rc=2 ;;
        esac ;;
      *)
        if ! in_words "$w" "$INERT_PROGS $SHELL_BUILTINS"; then
          IV_WHY="$w, a command it can't read"
          rc=2
        fi ;;
    esac
  done <<<"$cmd"
  return $rc
}

# Whether a script restarts anything: 0 when it can, 1 when it's read and
# can't, 2 when it can't be read, with SV_WHY saying why. One level deep: a
# script it calls in turn isn't followed, so a restart two scripts down is
# missed (CR 208).
script_verdict() {  # <path>
  SV_WHY=""
  case $1 in
    *%*) SV_WHY="$1, a path with a specifier" && return 2 ;;
    /*) ;;
    *) SV_WHY="$1, a path relative to its working directory" && return 2 ;;
  esac
  local rc=0
  # grep -I reads a binary as no match (1), and exits 2 on an error.
  as_reader grep -qI '' "$P_ROOT$1" 2>/dev/null || rc=$?
  case $rc in
    0) ;;
    1) SV_WHY="$1, a binary" && return 2 ;;
    *) SV_WHY="$1, which couldn't be read" && return 2 ;;
  esac
  if as_reader grep -v '^[[:space:]]*#' "$P_ROOT$1" 2>/dev/null | grep -qE "$RESTART_RE"; then return 0; fi
  return 1
}

# Whether an OnFailure= target starts or restarts anything (#351). A unit
# that isn't a service can't be read from Exec lines, and stays a restarter
# (CR 199). 0 when it can restart, 1 when it can't, 2 when that couldn't be
# read, with OF_WHY saying what.
onfailure_restarts() {  # <target unit>
  local rc=0
  OF_WHY=""
  case $1 in
    *.service) ;;
    *)
      OF_WHY="its OnFailure= target $1 isn't a service, so what it does can't be read from Exec lines"
      return 2 ;;
  esac
  unit_restarts "$1" "its OnFailure= target $1" || rc=$?
  OF_WHY=$UR_WHY
  return $rc
}

# Whether what a service runs starts or restarts anything: its unit file,
# its template's, their drop-ins, and what each Exec line runs. It's cleared
# only when everything it runs was read, one script deep: an interpreter's
# script (through env), a program that starts nothing, and each command of
# an inline one. A binary or an unreadable script can't be (CR 205). 0 when
# it can restart, 1 when it can't, 2 when that couldn't be read, with UR_WHY
# saying what, after WHO.
unit_restarts() {  # <service> <who>
  local t=$1 who=$2 tmpl="" d f files="" line raw prog base script rc=1 w i v text
  local -a tok=()
  UR_WHY=""
  case $t in *@*.*) tmpl=${t%%@*}@.${t##*.} ;; esac
  for d in etc/systemd/system run/systemd/system usr/local/lib/systemd/system usr/lib/systemd/system lib/systemd/system; do
    for f in "$P_ROOT/$d/$t" ${tmpl:+"$P_ROOT/$d/$tmpl"}; do
      if [ -f "$f" ] && [ -z "$files" ]; then files=$f; fi
    done
  done
  if [ -z "$files" ]; then
    UR_WHY="$who has no unit file to read"
    return 2
  fi
  for d in etc/systemd/system run/systemd/system usr/local/lib/systemd/system usr/lib/systemd/system lib/systemd/system; do
    for f in "$P_ROOT/$d/$t.d"/*.conf ${tmpl:+"$P_ROOT/$d/$tmpl.d"/*.conf}; do
      [ -f "$f" ] && files="$files"$'\n'"$f"
    done
  done
  while IFS= read -r f; do
    capture text as_reader cat -- "$f"
    if [ "$CAP_RC" -ne 0 ]; then
      UR_WHY="$who: ${f#"$P_ROOT"} couldn't be read"
      rc=2
      continue
    fi
    while IFS= read -r line || [ -n "$line" ]; do
      case $line in [[:space:]]*Exec*=* | Exec*=*) ;; *) continue ;; esac
      if [[ $line =~ $RESTART_RE ]]; then return 0; fi
      # Quotes and shell punctuation off, so a path inside sh -c '...' is a
      # word of its own.
      line=${line#*=}
      raw=$line
      line=${line//[\'\";()&|]/ }
      read -r -a tok <<<"$line" || true
      [ "${#tok[@]}" -gt 0 ] || continue
      prog=${tok[0]}
      while case $prog in [-@+!:]*) true ;; *) false ;; esac; do prog=${prog#?}; done
      i=1
      # env runs the program after its own options and assignments.
      while [ "${prog##*/}" = env ]; do
        while [ "$i" -lt "${#tok[@]}" ] && case ${tok[$i]} in -* | *=*) true ;; *) false ;; esac; do i=$((i + 1)); done
        prog=${tok[$i]:-}
        i=$((i + 1))
      done
      base=${prog##*/}
      script=""
      case $base in
        "") continue ;;
        sh | bash | dash | zsh | python | python[0-9]* | perl | perl[0-9]* | ruby | node)
          # Its script is its first argument that isn't an option. With -c,
          # the command follows, and each simple command in it is read.
          for w in "${tok[@]:$i}"; do
            case $w in
              -c)
                v=0
                inline_verdict "${raw#* -c }" || v=$?
                case $v in
                  0) return 0 ;;
                  2) UR_WHY="$who runs $IV_WHY" rc=2 ;;
                esac
                break ;;
              -*) ;;
              *) script=$w && break ;;
            esac
          done ;;
        *) in_words "$base" "$INERT_PROGS" || script=$prog ;;
      esac
      if [ -n "$script" ]; then
        v=0
        script_verdict "$script" || v=$?
        case $v in
          0) return 0 ;;
          2) UR_WHY="$who runs $SV_WHY" rc=2 ;;
        esac
      fi
      # Any other script the line names, read where it can be.
      for w in "${tok[@]:1}"; do
        case $w in /*) [ "$w" != "$script" ] || continue ;; *) continue ;; esac
        if [ -f "$P_ROOT$w" ] && script_verdict "$w"; then return 0; fi
      done
    done <<<"$text"
  done <<<"$files"
  return $rc
}

# In-host restarters: a unit whose Exec line runs systemctl restart, or one
# whose OnFailure= target starts or restarts a service. One that only
# notifies isn't a restarter: declaring it would stop the service it watches
# around every held step (#351). One the knob doesn't name isn't stopped
# around a data-store step.
read_restarters() {
  local f u base found="" stem declared e how line t rc why text unread="" svc opaque="" open=0 runs="" listed=""
  local -a tok=()
  R_RESTARTERS="" R_RESTARTERS_READ=""
  OF_WHYS=""
  for f in "$P_ROOT"/etc/systemd/system/*.service "$P_ROOT"/etc/systemd/system/*.service.d/*.conf; do
    [ -f "$f" ] || continue
    case $f in
      *.service.d/*)
        base=${f%/*}
        base=${base##*/}
        base=${base%.d} ;;
      *) base=${f##*/} ;;
    esac
    # Read as root where the user can't: a file left unread would leave its
    # restarter out of a list that then reads as clean (#360).
    capture text as_reader cat -- "$f"
    if [ "$CAP_RC" -ne 0 ]; then
      unread="$unread ${f#"$P_ROOT"}"
      continue
    fi
    if grep -qE '^[[:space:]]*Exec[A-Za-z]*=.*systemctl[^#]*(restart|try-restart|reload-or-restart)' <<<"$text"; then
      in_words "$base:restart" "$found" || found="$found $base:restart"
    fi
    while IFS= read -r line; do
      read -r -a tok <<<"${line#*=}" || true
      for t in ${tok[@]+"${tok[@]}"}; do
        rc=0
        onfailure_restarts "$t" || rc=$?
        if [ "$rc" -ne 1 ]; then
          in_words "$base:on-failure" "$found" || found="$found $base:on-failure"
          if [ "$rc" -eq 2 ]; then OF_WHYS="$OF_WHYS"$'\n'"$base:$OF_WHY"; fi
        fi
      done
    done < <(grep -E '^[[:space:]]*OnFailure=' <<<"$text" || true)
  done
  # A timer's service is read through what it runs, one script deep, as an
  # OnFailure= target is: a restart "only if the cert changed" lives in a
  # script (#368). One it can't follow leaves the list incomplete until it's
  # declared, either way: a restarter, or not-restarter:<service>.
  for f in "$P_ROOT"/etc/systemd/system/*.timer; do
    [ -f "$f" ] || continue
    base=${f##*/}
    capture text as_reader cat -- "$f"
    if [ "$CAP_RC" -ne 0 ]; then
      unread="$unread ${f#"$P_ROOT"}"
      continue
    fi
    svc=${base%.timer}.service
    while IFS= read -r line; do
      read -r svc <<<"${line#*=}" || true
    done < <(grep -E '^[[:space:]]*Unit=' <<<"$text" || true)
    # Which timer runs it: Unit= may name a service of another stem.
    runs="$runs $svc=$base"
    if in_words "$svc:restart" "$found"; then continue; fi
    rc=0
    unit_restarts "$svc" "$svc" || rc=$?
    case $rc in
      0) in_words "$svc:script" "$found" || found="$found $svc:script" ;;
      2)
        if in_words "$svc" "$KNOB_RESTARTERS" || in_words "$base" "$KNOB_RESTARTERS"; then continue; fi
        if ! { exception_for "not-restarter:$svc" && [ "$EX_EXPIRED" = 0 ]; }; then open=1; fi
        if ! in_words "$svc" "$opaque"; then
          opaque="$opaque $svc"
          finding unknown "restarters:unread:$svc" "not-restarter:$svc" "$base runs $svc, and the restarter scan can't follow it: $UR_WHY. If it can start or restart a service, declare restarter $base; if it can't, declare exception not-restarter:$svc <review-by> <reason> (knob.md)."
        fi ;;
    esac
  done
  for f in $found; do
    u=${f%%:*}
    # One entry, and one finding, a unit: the first way it was found
    # names it (CR 224).
    if in_words "$u" "$listed"; then continue; fi
    listed="$listed $u"
    stem=${u%.service}
    declared=0
    if in_words "$u" "$KNOB_RESTARTERS" || in_words "$stem.timer" "$KNOB_RESTARTERS"; then declared=1; fi
    for t in $runs; do
      if [ "${t%%=*}" = "$u" ] && in_words "${t#*=}" "$KNOB_RESTARTERS"; then declared=1; fi
    done
    e=""
    jadds e unit "$u"
    jadds e how "${f#*:}"
    jaddb e declared "$declared"
    jpush R_RESTARTERS "{$e}"
    if [ "$declared" -eq 0 ]; then
      how="an Exec line runs systemctl restart"
      if [ "${f#*:}" = script ]; then how="what its timer runs starts or restarts one"; fi
      if [ "${f#*:}" = on-failure ]; then
        how="its OnFailure= target starts or restarts one"
        why=""
        while IFS= read -r line; do
          if [ -z "$why" ] && [ "${line%%:*}" = "$u" ]; then why=${line#*:}; fi
        done <<<"$OF_WHYS"
        if [ -n "$why" ]; then how="it may: $why"; fi
      fi
      finding knob "restarter:$u" "" "$u can restart a service ($how), and no restarter line names it or its timer, so a data-store step wouldn't stop it. Declare it (knob.md)."
    fi
  done
  # What was found is still listed; the list just isn't the whole answer.
  R_RESTARTERS_READ=1
  if [ "$open" -eq 1 ]; then
    R_RESTARTERS_READ=0
    not_read "in-host restarters: a timer's service the scan can't follow, so whether it restarts one is unknown (each restarters:unread finding)"
  fi
  if [ -n "$unread" ]; then
    R_RESTARTERS_READ=0
    not_read "in-host restarters: ${unread# } couldn't be read, even as root, so a restarter among them is unknown"
    finding unknown restarters:unread "" "The restarter scan couldn't read${unread}, even as root: a restarter there would go unstopped through a data-store step. Read it as root, and declare any restarter it holds (knob.md)."
  fi
}

read_backups() {
  local u e age f base stem cands=""
  R_BACKUPS=""
  for u in $KNOB_BACKUPS; do
    e=""
    jadds e unit "$u"
    if unit_show "$u" Result ExecMainExitTimestamp ActiveState; then
      jaddsn e result "$U_Result"
      age=""
      case $U_ExecMainExitTimestamp in @[0-9]*) age=$(((P_NOW - ${U_ExecMainExitTimestamp#@}) / 3600)) ;; esac
      jaddn e last_exit_hours_ago "$age"
    fi
    jpush R_BACKUPS "{$e}"
  done
  for f in "$P_ROOT"/etc/systemd/system/*backup*.service "$P_ROOT"/etc/systemd/system/*dump*.service "$P_ROOT"/etc/systemd/system/*backup*.timer "$P_ROOT"/etc/systemd/system/*dump*.timer; do
    [ -f "$f" ] || continue
    base=${f##*/}
    stem=${base%.*}
    in_words "$stem" "$cands" && continue
    cands="$cands $stem"
    if ! in_words "$stem.service" "$KNOB_BACKUPS" && ! in_words "$stem.timer" "$KNOB_BACKUPS"; then
      finding knob "backup:$stem" "" "$base looks like a backup regime, and no backup line names it: declare it with each datastore unit it copies, backup $stem <datastore unit>..., so the recovery point can prefer a fresh success of it for those (knob.md, run.md section 2)."
    fi
  done
}

health_says() {  # <var> <exit status>: how a knob check ended, in words
  if [ "$2" = 124 ]; then
    printf -v "$1" 'times out after %s s' "$KNOB_CMD_TIMEOUT"
  elif [ "$2" = 137 ]; then
    printf -v "$1" 'is killed (exit 137): it outlived the %s s limit and its TERM, or something else killed it' "$KNOB_CMD_TIMEOUT"
  else
    printf -v "$1" 'exits %s' "$2"
  fi
}

HEALTH_RC=() HEALTH_LINE=()  # parallel to KNOB_HEALTH: each check's exit status, or empty, and its knob line
FAILED_UNITS=""
read_health() {  # <pre-run|post-boot>
  local r e rc failed="" out line w kind=risk said
  local -a hf=()
  R_HEALTH="" HEALTH_RC=() HEALTH_LINE=()
  if [ "$1" = post-boot ]; then kind=post-boot; fi
  for r in ${KNOB_HEALTH[@]+"${KNOB_HEALTH[@]}"}; do
    IFS=$KNOB_US read -r -a hf <<<"$r"
    rc=""
    if [ "$P_LIVE" -eq 1 ] && [ -n "$P_KNOB_USER" ]; then
      rc=0
      knob_cmd "${hf[0]}" >/dev/null 2>&1 </dev/null || rc=$?
      if [ "$rc" -ne 0 ] && [ "$kind" = risk ]; then
        health_says said "$rc"
        finding risk "health:${hf[1]}" "" "The health check on knob line ${hf[1]} $said before any change, so a run has no green baseline to compare against."
      fi
    fi
    HEALTH_RC+=("$rc")
    HEALTH_LINE+=("${hf[1]}")
    e=""
    jadds e command "${hf[0]}"
    jaddn e line "${hf[1]}"
    jaddn e exit "$rc"
    jpush R_HEALTH "{$e}"
  done
  if [ "$P_LIVE" -eq 1 ] && [ -z "$P_KNOB_USER" ] && [ -n "$R_HEALTH" ]; then
    not_read "the knob's health checks: running as root with no SUDO_USER, and a knob command never runs as root (knob.md)"
  fi
  R_FAILED=null
  if live_cmd systemctl; then
    capture out systemctl list-units --failed --plain --no-legend --no-pager
    if [ "$CAP_RC" -eq 0 ]; then
      while IFS= read -r line; do
        read -r w _ <<<"$line"
        if [ -n "$w" ]; then failed="$failed $w"; fi
      done <<<"$out"
      json_list R_FAILED "$failed"
      FAILED_UNITS=${failed# }
      if [ -n "$failed" ] && [ "$kind" = risk ]; then
        finding risk failed-units "" "Units have failed before any change:${failed}. Record them as the baseline, or fix them first."
      fi
    fi
  fi
}

REBOOT_REQ=0 REBOOT_DEL=""
read_reboot() {  # <pre-run|post-boot>
  local f pk="" line out w
  REBOOT_REQ=0 REBOOT_DEL=""
  for f in "$P_ROOT/run/reboot-required" "$P_ROOT/var/run/reboot-required"; do
    [ -e "$f" ] || continue
    REBOOT_REQ=1
    if [ -r "$f.pkgs" ]; then
      while IFS= read -r line || [ -n "$line" ]; do
        if [ -n "$line" ]; then jpushs pk "$line"; fi
      done <"$f.pkgs"
    fi
    break
  done
  if [ -e "$P_ROOT/proc/1/maps" ] && [ "$P_PRIV" != none ]; then
    capture out as_root grep -c '(deleted)' "$P_ROOT/proc/1/maps"
    if [ "$CAP_RC" -le 1 ] && is_int "$out"; then REBOOT_DEL=$out; fi
  fi
  R_REBOOT=""
  jaddb R_REBOOT required "$REBOOT_REQ"
  jadd R_REBOOT packages "[$pk]"
  jaddn R_REBOOT pid1_deleted_maps "$REBOOT_DEL"
  json_list w "$NR_SVC"
  if [ "$NR_READ" -ne 1 ]; then w=null; fi
  jadd R_REBOOT needrestart_services "$w"
  jaddsn R_REBOOT needrestart_kernel_status "$NR_KSTA"
  # exe.dev has no guest kernel, so needrestart's kernel lines mean nothing
  # there (the profile's update channels).
  if [ "$PROFILE" = exe-dev-exeuntu ]; then
    jadds R_REBOOT kernel_status_note "the platform's kernel: never decide a reboot from it"
  fi
  if [ "$REBOOT_REQ" -eq 1 ] && [ "$1" = pre-run ]; then
    finding risk reboot:pending "" "A reboot is already pending from an earlier upgrade (/run/reboot-required${pk:+, packages listed under impact.reboot}). Plan it into this run's window."
  fi
}

# Each running Qdrant container, and whether a datastore qdrant line names
# it (#367): one no line names is the analogue of database:<name>, a store
# no recovery point covers. null when Docker couldn't be read.
read_qdrant_containers() {
  local r out name image base declared="" e a="" d
  local -a f=()
  for r in ${KNOB_DATASTORE[@]+"${KNOB_DATASTORE[@]}"}; do
    IFS=$KNOB_US read -r -a f <<<"$r"
    if [ "${f[0]}" = qdrant ]; then declared="$declared ${f[2]%% *}"; fi
  done
  if ! docker_running; then
    jadd R_DS qdrant null
    return 0
  fi
  capture out docker_cmd ps --format '{{.Names}} {{.Image}}'
  if [ "$CAP_RC" -ne 0 ]; then
    jadd R_DS qdrant null
    return 0
  fi
  while read -r name image; do
    [ -n "$name" ] || continue
    # Its repository, without a tag or a digest, from any registry.
    base=${image%%@*}
    case ${base##*/} in *:*) base=${base%:*} ;; esac
    case $base in qdrant/qdrant | */qdrant/qdrant) ;; *) continue ;; esac
    d=0
    if in_words "$name" "$declared"; then d=1; fi
    e=""
    jadds e container "$name"
    jadds e image "$image"
    jaddb e declared "$d"
    jpush a "{$e}"
    if [ "$d" -eq 0 ]; then
      finding knob "datastore:$name" "datastore:$name" "The container $name runs $image, and no datastore line names it, so no recovery point covers it, and the reboot chain doesn't stop it as a data store. Name it: datastore qdrant <unit> $name <url> <key-file>. A store the owner chooses to rebuild instead takes exception datastore:$name <review-by> <reason> (knob.md)."
    fi
  done <<<"$out"
  jadd R_DS qdrant "[$a]"
}

read_impact() {
  local o=""
  read_maps
  read_datastores
  read_qdrant_containers
  read_cmdlines
  read_services
  read_restarters
  read_backups
  read_health pre-run
  read_reboot pre-run
  jadd o maps "$R_MAPS"
  jadd o datastores "{$R_DS}"
  jadd o live_args "[$R_ARGS]"
  jadd o services "[$R_SVC]"
  jadd o restarters "[$R_RESTARTERS]"
  jaddb o restarters_complete "$R_RESTARTERS_READ"
  jadd o backups "[$R_BACKUPS]"
  jadd o health "[$R_HEALTH]"
  jadd o failed_units "$R_FAILED"
  jadd o reboot "{$R_REBOOT}"
  R_IMPACT=$o
  not_read "callers and traffic: the service's own access or audit log, by UTC hour"
  not_read "what reads 200 while a dependency is down: the code path, read in the repo"
  not_read "the test suite's pass and skip counts, for the health baseline"
}

# --- dormant components -----------------------------------------------------
# One entry per engine the probe knows. The verdict is in-use, dormant, kept
# or unknown (policy.md): never dormant on evidence it couldn't read, or on
# fewer than 30 days of it.
DORMANT=""
SS_LOCAL=()

idle_days() {  # <unit>: IDLE := the days it has been inactive, or empty
  IDLE=""
  unit_show "$1" ActiveState InactiveEnterTimestamp || return 0
  case $U_ActiveState in
    inactive | failed)
      case $U_InactiveEnterTimestamp in
        @[0-9]*) IDLE=$(((P_NOW - ${U_InactiveEnterTimestamp#@}) / 86400)) ;;
        *) IDLE=${MANAGER_DAYS:-$UPTIME_DAYS} ;;
      esac ;;
  esac
}

active_days() {  # <unit>: ACTIVE := the days it has been active, else since systemd or the kernel started
  ACTIVE=${MANAGER_DAYS:-$UPTIME_DAYS}
  unit_show "$1" ActiveEnterTimestamp || return 0
  case $U_ActiveEnterTimestamp in
    @[0-9]*) ACTIVE=$(((P_NOW - ${U_ActiveEnterTimestamp#@}) / 86400)) ;;
  esac
}

named_by() {  # <ere>: NAMED (JSON array body); NAMED_DEPLOY 1 when deploy/ names it
  local out f hit
  NAMED="" NAMED_DEPLOY=0
  if [ -n "$repo" ] && [ -d "$repo" ]; then
    for f in deploy docs AGENTS.md README.md; do
      [ -e "$repo/$f" ] || continue
      capture out grep -rliE -- "$1" "$repo/$f"
      while IFS= read -r hit; do
        [ -n "$hit" ] || continue
        jpushs NAMED "${hit#"$repo"/}"
        case ${hit#"$repo"/} in deploy/*) NAMED_DEPLOY=1 ;; esac
      done <<<"$out"
    done
  fi
  if [ -r "$config" ] && grep -qiE -- "$1" "$config" 2>/dev/null; then jpushs NAMED "the knob"; fi
}

# The security set only: what a dormant component costs is the security fixes
# it takes for nothing (nginx was in the set on six hosts). The simulation's
# security class counts, and so does the dry run's selection when its
# origins are security alone.
pending_in() {  # <var> <globs>: VAR := the pending security packages they match
  local _pi_i _pi_n _pi_m=""
  local -a _pi_all=()
  if [ "$DRY_SECURITY_ONLY" -eq 1 ]; then read -r -a _pi_all <<<"$SEC_EXACT" || true; fi
  for _pi_i in ${PK_NAME[@]+"${!PK_NAME[@]}"}; do
    if [ "${PK_CLASS[$_pi_i]}" = security ]; then _pi_all+=("${PK_NAME[$_pi_i]}"); fi
  done
  for _pi_n in ${_pi_all[@]+"${_pi_all[@]}"}; do
    if [ -n "$2" ] && glob_match "$_pi_n" "$2" && ! in_words "$_pi_n" "$_pi_m"; then _pi_m="$_pi_m $_pi_n"; fi
  done
  printf -v "$1" '%s' "${_pi_m# }"
}

listeners_for() {  # <var> <ports>: VAR := the listening addresses on them
  local _lf_a _lf_p _lf_m=""
  for _lf_a in ${SS_LOCAL[@]+"${SS_LOCAL[@]}"}; do
    for _lf_p in $2; do
      case $_lf_a in *":$_lf_p") _lf_m="$_lf_m $_lf_a" ;; esac
    done
  done
  printf -v "$1" '%s' "${_lf_m# }"
}

read_listeners() {
  local out line a
  live_cmd ss || return 0
  capture out ss -Hltn
  [ "$CAP_RC" -eq 0 ] || return 0
  while IFS= read -r line; do
    read -r _ _ _ a _ <<<"$line"
    if [ -n "$a" ]; then SS_LOCAL+=("$a"); fi
  done <<<"$out"
}

window_ok() {  # <days>: 30 days of evidence or more
  is_int "${1-}" && [ "$1" -ge 30 ]
}

# <name> <installed 0|1> <unit> <ports> <ere> <package globs> <workload json>
# <in-use evidence> <dormant evidence> <why unknown>
engine() {
  local name=$1 inst=$2 unit=$3 ports=$4 ere=$5 pkgs=$6 wl=$7 inuse=$8 dorm=$9 unk=${10}
  local e="" disk verdict=unknown why stage="" w x
  [ "$inst" -eq 1 ] || return 0
  unit_disk_state disk "$unit"
  unit_show "$unit" ActiveState || true
  named_by "$ere"
  if [ -z "$inuse" ] && [ "$NAMED_DEPLOY" -eq 1 ]; then inuse="the repo's deploy/ names it"; fi
  for x in keep disabled removed purged; do
    if exception_for "$x:$name" && [ "$EX_EXPIRED" = 0 ]; then
      stage=$x
      break
    fi
  done
  why=$unk
  if [ -n "$inuse" ]; then
    verdict=in-use why=$inuse
  elif [ -n "$stage" ]; then
    verdict=kept why="exception $stage:$name on knob line $EX_LINE, review by $EX_REVIEW"
  elif [ -n "$dorm" ]; then
    verdict=dormant why=$dorm
  fi
  jadds e name "$name"
  jadds e unit "$unit"
  jadds e disk "$disk"
  jaddsn e active_state "$U_ActiveState"
  listeners_for w "$ports"
  json_list x "$w"
  jadd e listeners "$x"
  jadd e workload "${wl:-null}"
  jadd e named_by "[$NAMED]"
  pending_in w "$pkgs"
  json_list x "$w"
  jadd e pending_security "$x"
  jadds e verdict "$verdict"
  jaddsn e evidence "$why"
  if [ -n "$stage" ]; then jadds e exception "$stage:$name"; fi
  jpush DORMANT "{$e}"
  if [ "$verdict" = dormant ]; then
    finding dormant "dormant:$name" "keep:$name" "$name is installed and nothing uses it ($why). It's patch surface and attack surface for no benefit: propose a prune (policy.md), or declare exception keep:$name <review-by> <reason>."
  fi
}

idle_verdict() {  # <unit> <state>: sets DORM or UNK from how long the unit has been idle
  idle_days "$1"
  if window_ok "$IDLE"; then
    DORM="$2 for $IDLE days"
  else
    UNK="$2 for ${IDLE:-an unknown number of} days: fewer than 30"
  fi
}

read_docker() {
  local inst=0 out c im vol state
  WL="" INUSE="" DORM="" UNK=""
  if installed docker.io || installed docker-ce || [ -x "$P_ROOT/usr/bin/dockerd" ]; then inst=1; fi
  if [ "$inst" -eq 1 ]; then
    unit_show docker.service ActiveState || true
    if [ "$U_ActiveState" = active ] && live_cmd docker; then
      capture out docker_cmd ps -aq
      if [ "$CAP_RC" -eq 0 ]; then
        nlines c "$out"
        capture out docker_cmd images -q
        nlines im "$out"
        capture out docker_cmd volume ls -q
        nlines vol "$out"
        WL="{\"containers\": $c, \"images\": $im, \"volumes\": $vol}"
        active_days docker.service
        if [ "$c" -gt 0 ]; then
          INUSE="$c containers"
        elif window_ok "$ACTIVE"; then
          DORM="active for $ACTIVE days with no container in any state"
        else
          UNK="no container in any state, but active for only ${ACTIVE:-an unknown number of} days: fewer than 30"
        fi
      else
        UNK="docker couldn't be read, as the user or as root"
      fi
    elif [ "$U_ActiveState" = active ]; then
      UNK="active, but the docker CLI isn't on PATH, so its containers weren't read"
    elif [ -n "$U_ActiveState" ]; then
      # Idle isn't empty: what's on disk would go with a prune.
      state=$U_ActiveState
      docker_on_disk
      if [ -z "$DISK_CONTAINERS" ]; then
        UNK="$state, and what it holds on disk couldn't be read as root"
      else
        WL="{\"containers\": $DISK_CONTAINERS, \"volumes\": $DISK_VOLUMES, \"read_from\": \"disk\"}"
        if [ "$DISK_CONTAINERS" -gt 0 ] || [ "$DISK_VOLUMES" -gt 0 ]; then
          UNK="$state, but $DISK_CONTAINERS containers and $DISK_VOLUMES volumes are on disk, and a prune would take them"
        else
          idle_verdict docker.service "$state"
        fi
      fi
    else
      UNK="its state couldn't be read"
    fi
  fi
  engine docker "$inst" docker.service "" 'docker|containerd' 'docker.io docker-ce* containerd* runc' "$WL" "$INUSE" "$DORM" "$UNK"
}

read_postgres() {
  local inst=0 out p r c online=0 nusr=0 wr=0 window="" reset d db writes own created started sess ses=0 ses_why="" ver name status up="" pg_own="" span_unknown=0 gap="" down=""
  local -a df=()
  WL="" INUSE="" DORM="" UNK=""
  if have dpkg-query; then
    capture out dpkgq -W -f "$DPKG_PKG_STATUS" 'postgresql-[0-9]*'
    while IFS= read -r p; do
      case $p in *" ii"*) inst=1 ;; esac
    done <<<"$out"
  fi
  if [ "$inst" -eq 1 ]; then
    for r in ${KNOB_DATASTORE[@]+"${KNOB_DATASTORE[@]}"}; do
      IFS=$KNOB_US read -r -a df <<<"$r"
      if [ "${df[0]}" = postgres ]; then INUSE="a datastore line declares it"; fi
    done
    if [ -z "$PG_CLUSTERS" ] && ! read_pg_clusters; then
      UNK="pg_lsclusters couldn't be read"
    elif [ -z "$PG_CLUSTERS" ]; then
      UNK="no cluster"
    else
      # Every cluster counts: an online one once its catalogs were read, a
      # down one by its own unit's idle time. postgresql.service can't speak
      # for them: on Debian it's an umbrella that stays active (exited) with
      # every cluster down.
      for c in $PG_CLUSTERS; do
        IFS=/ read -r ver name _ status _ <<<"$c"
        if [ "$status" = online ]; then
          online=1
          if ! in_words "$ver/$name" "$PG_READ"; then gap="$gap $ver/$name (unread)"; fi
        else
          idle_days "postgresql@$ver-$name.service"
          if ! window_ok "$IDLE"; then
            gap="$gap $ver/$name (down ${IDLE:-an unknown number of} days)"
          elif [ -z "$down" ] || [ "$IDLE" -lt "$down" ]; then
            down=$IDLE
          fi
        fi
      done
      if [ "$online" -eq 0 ] && [ -z "$gap" ]; then
        DORM="every cluster down, the latest for $down days"
      elif [ "$online" -eq 0 ]; then
        UNK="every cluster down, but not each for 30 days:$gap"
      elif [ -z "${PG_READ// /}" ]; then
        UNK="its activity needs a login as postgres, and that failed"
      elif [ -n "$gap" ]; then
        UNK="not every cluster could be judged:$gap"
      else
        for r in ${PG_ROWS[@]+"${PG_ROWS[@]}"}; do
          IFS=$KNOB_US read -r _ db writes reset own created started sess <<<"$r"
          case $db in template0 | template1) continue ;; esac
          # postgres counts as a database of its own only with tables in it.
          if [ "$db" = postgres ]; then
            if ! is_int "$own"; then pg_own=unknown; continue; fi
            if [ "$own" -eq 0 ]; then continue; fi
          fi
          nusr=$((nusr + 1))
          if is_int "$writes"; then wr=$((wr + writes)); fi
          # No row written isn't idleness: an app may only read. sessions
          # counts client connections alone (a read moves it, autovacuum
          # doesn't: measured on 16), so a database with none had no client.
          # postgres's own include the probe's, and before 14 there's none.
          if [ "$db" = postgres ]; then
            ses_why="the postgres database's sessions include the probe's own"
          elif is_int "$sess"; then
            ses=$((ses + sess))
          else
            ses_why="the server counts no sessions (before Postgres 14)"
          fi
          # What its counters cover: since a reset, or else since the later of
          # its creation and the server's start. Never reset, they outlive a
          # clean restart but not a crash, and they begin with the database,
          # so the server's start alone overstates one created after it
          # (measured on 16).
          d=""
          if is_int "$reset"; then
            d=$(((P_NOW - reset) / 86400))
          elif is_int "$created" && is_int "$started"; then
            if [ "$created" -gt "$started" ]; then started=$created; fi
            d=$(((P_NOW - started) / 86400))
          fi
          if [ -z "$d" ]; then
            span_unknown=1
          elif [ -z "$window" ] || [ "$d" -lt "$window" ]; then
            window=$d
          fi
        done
        if [ "$span_unknown" -eq 1 ]; then window=""; fi
        # With no database to read, the servers' own uptime bounds the
        # evidence: in a container, or after a soft reboot, the kernel booted
        # long before them.
        for c in $PG_CLUSTERS; do
          case $c in */online/*)
            IFS=/ read -r ver name _ <<<"$c"
            active_days "postgresql@$ver-$name.service"
            if is_int "$ACTIVE" && { [ -z "$up" ] || [ "$ACTIVE" -lt "$up" ]; }; then up=$ACTIVE; fi ;;
          esac
        done
        WL="{\"databases\": $nusr, \"writes_since_stats_reset\": $wr, \"sessions_since_stats_reset\": $ses}"
        if [ -n "$ses_why" ]; then WL="{\"databases\": $nusr, \"writes_since_stats_reset\": $wr, \"sessions_since_stats_reset\": null}"; fi
        if [ "$nusr" -eq 0 ] && [ -n "$pg_own" ]; then
          UNK="no database but postgres and the templates, but whether postgres holds tables of its own wasn't read"
        elif [ "$nusr" -eq 0 ]; then
          if window_ok "$up"; then
            DORM="no database but postgres and the templates, up $up days"
          else
            UNK="no database but postgres and the templates, but up only ${up:-an unknown number of} days: fewer than 30"
          fi
        elif [ "$wr" -gt 0 ]; then
          INUSE=${INUSE:-"$wr rows written since the statistics were reset"}
        elif [ -n "$ses_why" ]; then
          UNK="no row written, but whether anything read it isn't known: $ses_why"
        elif [ "$ses" -gt 0 ]; then
          UNK="no row written, but $ses sessions since the statistics were reset: a read and a backup look alike"
        elif window_ok "$window"; then
          DORM="$nusr databases, and no row written and no session in the $window days their statistics cover"
        elif [ -n "$window" ]; then
          UNK="no row written, but the statistics cover only $window days: fewer than 30"
        else
          UNK="no row written, but how many days the statistics cover couldn't be read"
        fi
      fi
    fi
  fi
  engine postgres "$inst" postgresql.service 5432 'postgres|psql|pg_dump' 'postgresql-* libpq5' "$WL" "$INUSE" "$DORM" "$UNK"
}

read_redis() {
  local inst=0 out r keys=0 up="" v look=0 exp=0 subs=0 clients="" seen=0
  local -a df=()
  WL="" INUSE="" DORM="" UNK=""
  if installed redis-server; then inst=1; fi
  if [ "$inst" -eq 1 ]; then
    for r in ${KNOB_DATASTORE[@]+"${KNOB_DATASTORE[@]}"}; do
      IFS=$KNOB_US read -r -a df <<<"$r"
      if [ "${df[0]}" = redis ]; then INUSE="a datastore line declares it"; fi
    done
    unit_show redis-server.service ActiveState || true
    if [ "$U_ActiveState" = active ] && live_cmd redis-cli; then
      capture out redis-cli INFO
      out=${out//$'\r'/}
      if [ "$CAP_RC" -eq 0 ] && [[ $out == *uptime_in_days:* ]]; then
        while IFS= read -r r; do
          case $r in
            uptime_in_days:*) up=${r#uptime_in_days:} ;;
            db[0-9]*:keys=*)
              r=${r#*keys=}
              r=${r%%,*}
              if is_int "$r"; then keys=$((keys + r)); fi ;;
            # No key isn't idleness: a cache whose keys expired, or a bus,
            # holds none. A fresh server reads 0 for each of these, and 1
            # client, the probe's own (measured on 7).
            keyspace_hits:* | keyspace_misses:* | expired_keys:* | pubsub_channels:* | pubsub_patterns:* | connected_clients:*)
              v=${r#*:}
              if is_int "$v"; then
                seen=$((seen + 1))
                case $r in
                  keyspace_*) look=$((look + v)) ;;
                  expired_keys:*) exp=$v ;;
                  pubsub_*) subs=$((subs + v)) ;;
                  *) clients=$v ;;
                esac
              fi ;;
          esac
        done <<<"$out"
        WL="{\"keys\": $keys, \"uptime_days\": ${up:-null}, \"key_lookups\": $look, \"expired_keys\": $exp, \"subscriptions\": $subs, \"clients\": ${clients:-null}}"
        if [ "$keys" -gt 0 ]; then
          INUSE=${INUSE:-"$keys keys"}
        elif [ "$look" -gt 0 ]; then
          INUSE=${INUSE:-"no key now, but $look key lookups since it started"}
        elif [ "$exp" -gt 0 ]; then
          INUSE=${INUSE:-"no key now, but $exp keys expired since it started"}
        elif [ "$subs" -gt 0 ]; then
          INUSE=${INUSE:-"no key, but $subs pub/sub subscriptions"}
        elif is_int "$clients" && [ "$clients" -gt 1 ]; then
          INUSE=${INUSE:-"no key, but $((clients - 1)) clients besides the probe"}
        elif [ "$seen" -lt 6 ]; then
          UNK="no key, but INFO lacked the lookup, expiry, subscription or client counts"
        elif window_ok "$up"; then
          DORM="no key, and no lookup, expiry, subscription or client but the probe in the $up days it's been up"
        else
          UNK="no key, but up only ${up:-an unknown number of} days: fewer than 30"
        fi
      else
        UNK="redis-cli INFO couldn't be read (a password?)"
      fi
    elif [ "$U_ActiveState" = active ]; then
      UNK="active, but redis-cli isn't on PATH, so its keys weren't read"
    elif [ -n "$U_ActiveState" ]; then
      idle_verdict redis-server.service "$U_ActiveState"
    else
      UNK="its state couldn't be read"
    fi
  fi
  engine redis "$inst" redis-server.service 6379 'redis' 'redis-server redis-tools redis' "$WL" "$INUSE" "$DORM" "$UNK"
}

read_nginx() {
  local inst=0 sites=0 other=0 s
  WL="" INUSE="" DORM="" UNK=""
  if installed nginx || installed nginx-core || installed nginx-full || installed nginx-light; then inst=1; fi
  if [ "$inst" -eq 1 ]; then
    for s in "$P_ROOT"/etc/nginx/sites-enabled/*; do
      if [ ! -e "$s" ] && [ ! -L "$s" ]; then continue; fi
      sites=$((sites + 1))
      if [ "${s##*/}" != default ]; then other=$((other + 1)); fi
    done
    WL="{\"sites_enabled\": $sites}"
    unit_show nginx.service ActiveState || true
    if [ "$U_ActiveState" = active ]; then
      if [ "$other" -gt 0 ]; then
        INUSE="active, with $other sites besides default"
      else
        UNK="active with only the default site: whether anything calls it isn't read"
      fi
    elif [ -n "$U_ActiveState" ]; then
      idle_verdict nginx.service "$U_ActiveState"
    else
      UNK="its state couldn't be read"
    fi
  fi
  engine nginx "$inst" nginx.service '80 443' 'nginx' 'nginx nginx-* libnginx-*' "$WL" "$INUSE" "$DORM" "$UNK"
}

# Ollama and Qdrant come from outside apt, and are found by their unit or
# binary.
read_unpackaged() {  # <name> <unit> <binary> <store> <ports>
  local inst=0 ud out n=""
  WL="" INUSE="" DORM="" UNK=""
  unit_disk_state ud "$2"
  if [ -x "$P_ROOT$3" ] || [ "$ud" != not-found ]; then inst=1; fi
  if [ "$inst" -eq 1 ]; then
    if [ -d "$P_ROOT$4" ]; then
      if [ "$P_PRIV" != none ]; then
        capture out as_root find "$P_ROOT$4" -mindepth 1 -maxdepth 4 -type f
      else
        capture out find "$P_ROOT$4" -mindepth 1 -maxdepth 4 -type f
      fi
      if [ "$CAP_RC" -eq 0 ]; then nlines n "$out"; fi
    fi
    WL="{\"stored_files\": ${n:-null}}"
    unit_show "$2" ActiveState || true
    if is_int "$n" && [ "$n" -gt 0 ]; then
      INUSE="$n files under $4"
    elif [ -n "$U_ActiveState" ] && [ "$U_ActiveState" != active ]; then
      idle_verdict "$2" "$U_ActiveState"
    elif [ "$n" = 0 ] && [ "$U_ActiveState" = active ]; then
      active_days "$2"
      if window_ok "$ACTIVE"; then
        DORM="active for $ACTIVE days with nothing stored under $4"
      else
        UNK="nothing stored under $4, but active for only ${ACTIVE:-an unknown number of} days: fewer than 30"
      fi
    else
      UNK="whether anything calls it isn't read"
    fi
  fi
  engine "$1" "$inst" "$2" "$5" "$1" "" "$WL" "$INUSE" "$DORM" "$UNK"
}

read_dormant() {
  read_listeners
  read_docker
  read_postgres
  read_redis
  read_nginx
  read_unpackaged ollama ollama.service /usr/local/bin/ollama /usr/share/ollama/.ollama/models/manifests 11434
  read_unpackaged qdrant qdrant.service /usr/local/bin/qdrant /var/lib/qdrant/storage/collections '6333 6334'
  not_read "whether each component came with the image or was installed later: that needs the image's build date, and the guest sees neither its image's digest nor its date (the profile's Detection)"
}

# --- after the boot (run.md §6) ---------------------------------------------
POST=""
check() {  # <name> <ok 1|0|""> <evidence>
  local e=""
  jadds e check "$1"
  jaddb e ok "$2"
  jaddsn e evidence "$3"
  jpush POST "{$e}"
  if [ "$2" = 0 ]; then finding post-boot "post-boot:$1" "" "$1: $3"; fi
}

# The boot is when the tailnet's default re-applied over the node's own
# setting (#357), so it's read again after one.
check_tailscale_auto_update() {
  read_tailscale
  installed tailscale || return 0
  case $TS_APPLY in
    false) check tailscale:auto-update 1 "AutoUpdate.Apply is false" ;;
    true)
      if exception_for tailscale:auto-update && [ "$EX_EXPIRED" = 0 ]; then
        check tailscale:auto-update 1 "AutoUpdate.Apply is true, excepted by knob line $EX_LINE"
      else
        check tailscale:auto-update 0 "AutoUpdate.Apply is true after the boot: the tailnet's default re-applies over the node's setting, so turn it off for the tailnet too (policy.md)"
      fi ;;
    null) check tailscale:auto-update "" "AutoUpdate.Apply is null: nothing set it on the node" ;;
    *) check tailscale:auto-update "" "tailscale debug prefs couldn't be read" ;;
  esac
}

JOURNAL_VERDICT=unknown
check_shutdown() {
  local c ver name port status log out line ok ev
  if read_pg_clusters; then
    for c in $PG_CLUSTERS; do
      IFS=/ read -r ver name port status log <<<"$c"
      ok="" ev="its log couldn't be read as root"
      if [ -n "$log" ] && [ "$P_PRIV" != none ]; then
        capture out as_root tail -n 400 "$P_ROOT$log"
        if [ "$CAP_RC" -eq 0 ]; then
          ev="no shutdown line in the log's last 400 lines"
          while IFS= read -r line; do
            case $line in
              *"database system was shut down at"*) ok=1 ev="database system was shut down, and no redo followed" ;;
              *"database system was interrupted"*) ok=0 ev="database system was interrupted" ;;
              *"redo starts"*) ok=0 ev="redo starts: it recovered from a crash" ;;
            esac
          done <<<"$out"
        fi
      fi
      check "shutdown:postgres:$ver/$name" "$ok" "$ev"
    done
  fi
  if live_cmd journalctl; then
    capture out jctl -k -b 0 -q --no-pager
    if [ "$CAP_RC" -eq 0 ]; then
      case $out in
        *orphan*) check shutdown:ext4-orphans 0 "the kernel ran orphan recovery at this boot: the last shutdown wasn't clean" ;;
        *) check shutdown:ext4-orphans 1 "no orphan recovery in this boot's kernel log" ;;
      esac
    fi
  fi
  check_journal_record
}

# The shutdown's own record (#356). A persistent journal survives the boot,
# so the previous boot's last lines are read: journald's "Journal stopped"
# is its last, written only when the shutdown reached it. A volatile one is
# gone, and the chain's copy in <run>/journal is the record: reboot-chain.sh
# writes it there, one directory per journal it copied.
# The run a post-boot probe reads: --run, or the newest one under
# /var/backups, or empty.
post_run_dir() {  # <var>
  local _pr_r=$run _pr_t
  if [ -z "$_pr_r" ]; then
    for _pr_t in "$P_ROOT"/var/backups/patching-hosts-2*; do
      if [ -d "$_pr_t" ]; then _pr_r=${_pr_t#"$P_ROOT"}; fi
    done
  fi
  printf -v "$1" '%s' "$_pr_r"
}

# Each Qdrant against the counts the run's recovery point took (#367).
check_qdrant() {
  local r u qurl qkey rd="" rec cpath before
  local -a f=()
  for r in ${KNOB_DATASTORE[@]+"${KNOB_DATASTORE[@]}"}; do
    IFS=$KNOB_US read -r -a f <<<"$r"
    [ "${f[0]}" = qdrant ] || continue
    unit_name u "${f[1]}"
    read -r _ qurl qkey <<<"${f[2]}"
    if [ "$P_LIVE" -ne 1 ] || [ "$P_PRIV" = none ]; then
      check "qdrant:$u" "" "its counts need a running system, read as root"
      continue
    fi
    [ -n "$rd" ] || post_run_dir rd
    if [ -z "$rd" ]; then
      check "qdrant:$u" "" "no run directory under /var/backups/patching-hosts-<UTC>: pass --run, the run whose recovery point counted it"
      continue
    fi
    capture rec as_root cat "$P_ROOT$rd/recovery-point"
    if [ "$CAP_RC" -ne 0 ]; then
      check "qdrant:$u" "" "$rd/recovery-point couldn't be read as root"
      continue
    fi
    qdrant_counts_path cpath "$rec" "$u"
    if [ -z "$cpath" ]; then
      check "qdrant:$u" "" "$rd/recovery-point holds no counts of it: its recovery point was a backup unit's, or older than #367"
      continue
    fi
    capture before as_root cat "$P_ROOT$cpath"
    if [ "$CAP_RC" -ne 0 ]; then
      check "qdrant:$u" "" "$cpath couldn't be read as root"
      continue
    fi
    qdrant_loss "$qurl" "$qkey" "$before"
    check "qdrant:$u" "$QL_OK" "$QL_WHY"
  done
}

check_journal_record() {
  local out r
  if [ "$JOURNAL_VERDICT" = persistent ]; then
    if ! live_cmd journalctl; then
      check shutdown:journal-stopped "" "the previous boot's journal needs a running system to read"
      return 0
    fi
    capture out jctl -b -1 -n 20 -q --no-pager -o cat
    if [ "$CAP_RC" -ne 0 ]; then
      check shutdown:journal-stopped "" "the previous boot's journal couldn't be read (${CAP_ERR:-exit $CAP_RC})"
    else
      case $out in
        *"Journal stopped"*) check shutdown:journal-stopped 1 "the persistent journal's previous boot ends with Journal stopped" ;;
        *) check shutdown:journal-stopped 0 "the previous boot's last 20 journal lines have no Journal stopped: the shutdown never reached journald's stop" ;;
      esac
    fi
    return 0
  fi
  post_run_dir r
  if [ -z "$r" ]; then
    check shutdown:journal-copy "" "no run directory under /var/backups/patching-hosts-<UTC>: pass --run, the run whose chain copied the journal"
    return 0
  fi
  # The chain's own log says what step 5 did: a directory can hold a copy
  # that failed partway (CR 200). The run is root's, at 0700.
  capture out as_root cat "$P_ROOT$r/reboot-chain.log"
  if [ "$CAP_RC" -ne 0 ]; then
    if [ "$P_PRIV" = none ]; then
      check shutdown:journal-copy "" "$r/reboot-chain.log needs root to read"
    else
      check shutdown:journal-copy "" "no reboot chain log in $r (${CAP_ERR:-exit $CAP_RC}): pass --run, the run whose chain rebooted the host"
    fi
    return 0
  fi
  case $out in
    *"the copy of "*" failed"*) check shutdown:journal-copy 0 "the chain's copy of the volatile journal failed ($r/reboot-chain.log): the shutdown has no record" ;;
    *" copied to "*", and read back"*) check shutdown:journal-copy 1 "the chain copied the volatile journal into $r/journal, and read it back" ;;
    *"holds no journal"*) check shutdown:journal-copy 0 "the chain found no volatile journal to copy, and the journal isn't persistent (verdict $JOURNAL_VERDICT): the shutdown has no record" ;;
    *) check shutdown:journal-copy "" "$r/reboot-chain.log has no journal step: the chain ended before it" ;;
  esac
}

# Whether the first start held. NRestarts can't say: it counts only
# Restart='s own restarts, so a first start that failed and was then started
# by hand reads 0 (CannObserv/address-validator#239). systemd sets
# InactiveEnterTimestamp only when a unit stops or fails, so one that started
# (InactiveExitTimestamp) with it still unset has run since, whatever the
# journal kept: measured on systemd 255. One that did stop needs PID 1's
# lines in this boot's journal to tell a failure from a stop by hand, and PID
# 1 logs to the console on exeuntu.
first_start() {  # <unit>, after unit_show read its Inactive*Timestamps: FIRST_START := held, failed, stopped, or empty when nothing tells
  local out
  FIRST_START=""
  if [ -n "$U_InactiveExitTimestamp" ] && [ -z "$U_InactiveEnterTimestamp" ]; then
    FIRST_START=held
    return 0
  fi
  live_cmd journalctl || return 0
  capture out jctl -b 0 -u "$1" -o cat --no-pager -q
  [ "$CAP_RC" -eq 0 ] || return 0
  case $out in
    *"$1: Failed with result"* | *"Failed to start $1"*) FIRST_START=failed ;;
    *"Started $1"*) FIRST_START=stopped ;;
  esac
}

read_post_boot() {
  local svc ds t out line down="" i said
  check_shutdown
  for svc in $KNOB_SERVICES; do
    if unit_show "$svc" ActiveState Result NRestarts After InactiveExitTimestamp InactiveEnterTimestamp; then
      if [ "$U_ActiveState" != active ] || [ "${U_NRestarts:-0}" != 0 ]; then
        check "service:$svc" 0 "$U_ActiveState, ${U_NRestarts:-unknown} automatic restarts, result ${U_Result:-unknown}: the first start didn't hold"
      else
        first_start "$svc"
        case $FIRST_START in
          held) check "service:$svc" 1 "active, 0 automatic restarts, and never stopped or failed since it started" ;;
          failed) check "service:$svc" 0 "active now, but this boot's journal shows it failing: a start by hand doesn't count in NRestarts" ;;
          stopped) check "service:$svc" 1 "active, 0 automatic restarts: it stopped since it started, and this boot's journal shows no failure" ;;
          *) check "service:$svc" "" "active with 0 automatic restarts, but it stopped or failed since it started, and this boot's journal has none of PID 1's lines to say which" ;;
        esac
      fi
      for ds in $DS_UNITS; do
        [ "$ds" != "$svc" ] || continue
        if ordering_ok "$ds" "$U_After"; then
          check "ordering:$svc" 1 "After= $ds"
        else
          check "ordering:$svc" 0 "no After= $ds: its start at this boot succeeded by luck"
        fi
      done
    else
      check "service:$svc" "" "systemctl couldn't be read"
    fi
  done
  for t in $KNOB_RESTARTERS; do
    if unit_show "$t" ActiveState NextElapseUSecRealtime NextElapseUSecMonotonic; then
      if [ "$U_ActiveState" = active ]; then check "restarter:$t" 1 active; else check "restarter:$t" 0 "$U_ActiveState"; fi
      # A monotonic timer (OnBootSec=, OnUnitActiveSec=) has no realtime
      # elapse: systemd leaves NextElapseUSecRealtime empty for it (#363).
      # A stopped one reads NextElapseUSecMonotonic=infinity, and a calendar
      # one 0 (systemd 255, measured 2026-10-07; CR 211).
      case $t in
        *.timer)
          if [ -n "$U_NextElapseUSecRealtime" ] && [ "$U_NextElapseUSecRealtime" != 0 ]; then
            check "timer:$t" 1 "scheduled, realtime"
          elif [ -n "$U_NextElapseUSecMonotonic" ] && [ "$U_NextElapseUSecMonotonic" != 0 ] && [ "$U_NextElapseUSecMonotonic" != infinity ]; then
            check "timer:$t" 1 "scheduled, monotonic: $U_NextElapseUSecMonotonic"
          else
            check "timer:$t" 0 "not scheduled"
          fi ;;
      esac
    else
      check "restarter:$t" "" "systemctl couldn't be read"
    fi
  done
  NR_SVC=""
  if installed needrestart && live_cmd needrestart && [ "$P_PRIV" != none ]; then
    capture2 out as_root needrestart -b -r l
    while IFS= read -r line; do
      case $line in NEEDRESTART-SVC:*) NR_SVC="$NR_SVC ${line#NEEDRESTART-SVC:}" ;; esac
    done <<<"$out"
    if [ -z "${NR_SVC// /}" ]; then check needrestart 1 "no service left to restart"; else check needrestart 0 "still to restart:$NR_SVC"; fi
  else
    check needrestart "" "needrestart couldn't be run as root"
  fi
  check_qdrant
  read_reboot post-boot
  check_tailscale_auto_update
  if is_int "$REBOOT_DEL"; then
    if [ "$REBOOT_DEL" -eq 0 ]; then check pid1-deleted-maps 1 "PID 1 maps no deleted file"; else check pid1-deleted-maps 0 "PID 1 maps $REBOOT_DEL deleted files"; fi
  else
    check pid1-deleted-maps "" "/proc/1/maps couldn't be read as root"
  fi
  if [ "$REBOOT_REQ" -eq 1 ]; then check reboot-required 0 "/run/reboot-required is still there"; else check reboot-required 1 absent; fi
  if [ -n "$R_SESSION_MIN" ] && [ "$R_SESSION_MIN" -le -1000 ]; then
    check session-adj 0 "the session's chain still runs at $R_SESSION_MIN"
  elif [ -n "$R_SESSION_MIN" ]; then
    check session-adj 1 "lowest adj in the session's chain, below the platform's agent: $R_SESSION_MIN"
  fi
  if docker_running; then
    capture out docker_cmd ps -a --format '{{.Names}} {{.State}}'
    if [ "$CAP_RC" -eq 0 ]; then
      while IFS= read -r line; do
        [ -n "$line" ] || continue
        case $line in *" running") ;; *) down="$down ${line%% *}" ;; esac
      done <<<"$out"
      if [ -z "$down" ]; then check containers 1 "every container is running"; else check containers 0 "not running:$down"; fi
    fi
  elif live_cmd docker; then
    # Read from disk instead: with docker.service down, nothing brings a
    # container back at boot, whatever its restart policy.
    docker_on_disk
    if [ -z "$DISK_CONTAINERS" ]; then
      check containers "" "docker.service isn't running, and its containers on disk couldn't be read as root"
    elif [ "$DISK_RESTARTING" -gt 0 ]; then
      if docker_socket_listens; then
        check containers 0 "docker.service isn't running, so $DISK_RESTARTING containers with a restart policy aren't back: only docker.socket listens, and it starts dockerd on the first docker call"
      else
        check containers 0 "docker.service isn't running, so $DISK_RESTARTING containers with a restart policy aren't back"
      fi
    else
      check containers 1 "docker.service isn't running, and none of the $DISK_CONTAINERS containers on disk has a restart policy that would bring it back"
    fi
  fi
  read_health post-boot
  for i in ${HEALTH_RC[@]+"${!HEALTH_RC[@]}"}; do
    if [ -z "${HEALTH_RC[$i]}" ]; then
      check "health:${HEALTH_LINE[$i]}" "" "not run"
    elif [ "${HEALTH_RC[$i]}" -eq 0 ]; then
      check "health:${HEALTH_LINE[$i]}" 1 "exit 0"
    else
      health_says said "${HEALTH_RC[$i]}"
      check "health:${HEALTH_LINE[$i]}" 0 "the check on knob line ${HEALTH_LINE[$i]} $said"
    fi
  done
  case $R_FAILED in
    null) check failed-units "" "systemctl couldn't be read" ;;
    '[]') check failed-units 1 none ;;
    *) check failed-units 0 "$FAILED_UNITS" ;;
  esac
  not_read "the downtime: from the stop line or the last request to the first good response"
}

# --- run -----------------------------------------------------------------------
knob_units KNOB_SERVICES ${KNOB_SERVICE[@]+"${KNOB_SERVICE[@]}"}
knob_units KNOB_RESTARTERS ${KNOB_RESTARTER[@]+"${KNOB_RESTARTER[@]}"}
knob_units KNOB_BACKUPS ${KNOB_BACKUP[@]+"${KNOB_BACKUP[@]}"}
_u=""
for _r in ${KNOB_DATASTORE[@]+"${KNOB_DATASTORE[@]}"}; do
  IFS=$KNOB_US read -r -a _f <<<"$_r"
  unit_name _u "${_f[1]}"
  in_words "$_u" "$DS_UNITS" || DS_UNITS="$DS_UNITS $_u"
done

read_environment
if [ "$postboot" -eq 1 ]; then
  read_post_boot
else
  refresh_lists
  read_updates
  evaluate_posture
  read_pending
  read_impact
  read_dormant
fi

# The knob's own findings join the probe's. An exception covers a finding
# only when the finding names a <what>, and only until its review-by date.
for _r in ${KNOB_FINDING[@]+"${KNOB_FINDING[@]}"}; do
  IFS=$KNOB_US read -r -a _f <<<"$_r"
  finding knob "knob:${_f[1]}" "" "knob line ${_f[0]:-(none)}: ${_f[2]}"
done
FINDINGS="" EXCEPTED=""
for _i in ${F_ID[@]+"${!F_ID[@]}"}; do
  _e=""
  jadds _e kind "${F_KIND[$_i]}"
  jadds _e id "${F_ID[$_i]}"
  jaddsn _e exception_what "${F_WHAT[$_i]}"
  jadds _e message "${F_MSG[$_i]}"
  if [ -n "${F_WHAT[$_i]}" ] && exception_for "${F_WHAT[$_i]}" && [ "$EX_EXPIRED" = 0 ]; then
    jaddn _e exception_line "$EX_LINE"
    jadds _e review_by "$EX_REVIEW"
    jadds _e reason "$EX_REASON"
    EXCEPTED="${EXCEPTED:+$EXCEPTED,
}    {$_e}"
  else
    FINDINGS="${FINDINGS:+$FINDINGS,
}    {$_e}"
  fi
done

_p=""
jaddn _p version 1
if [ "$postboot" -eq 1 ]; then jadds _p mode post-boot; else jadds _p mode pre-run; fi
jadds _p root "${P_ROOT:-/}"
jaddb _p live "$P_LIVE"
jadds _p privilege "$P_PRIV"
jadds _p today "$today"
jaddsn _p repo "$repo"
jaddsn _p refreshed_into "$refresh"
jaddsn _p dry_run_into "$dryrun"

printf '{\n'
printf '  "probe": {%s},\n' "$_p"
printf '  "knob": %s,\n' "$knob_json"
printf '  "environment": {%s},\n' "$R_ENV"
if [ "$postboot" -eq 1 ]; then
  printf '  "post_boot": [%s],\n' "$POST"
else
  printf '  "updates": {%s},\n' "$R_UPD"
  printf '  "pending": {%s},\n' "$R_PEND"
  printf '  "impact": {%s},\n' "$R_IMPACT"
  printf '  "dormant": [%s],\n' "$DORMANT"
fi
if [ -n "$FINDINGS" ]; then printf '  "findings": [\n%s\n  ],\n' "$FINDINGS"; else printf '  "findings": [],\n'; fi
if [ -n "$EXCEPTED" ]; then printf '  "excepted": [\n%s\n  ],\n' "$EXCEPTED"; else printf '  "excepted": [],\n'; fi
printf '  "not_read": [%s]\n' "$NOT_READ"
printf '}\n'
