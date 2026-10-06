#!/usr/bin/env bash
# apply.sh — run one step of a patch run, gated, and record it as root.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash apply.sh --step bulk|<held step> [--approve] [--run DIR]
                     [--lane security|maintenance|origin:<origin>]
                     [--dry-run DIR] [--offnode-sha256 HEX]...
                     [--offnode-object NAME]... [--health-within SECONDS]
                     [--config FILE] [--host NAME] [--today YYYY-MM-DD]

Runs one step of the apply in references/run.md section 3, under the gate before
it, and records it as root in the run's directory. Until every check
passes it changes nothing, and prints why.

Steps:
  bulk         refreshes apt's lists, records the before-versions, holds the
               pending packages of every hold group, runs unattended-upgrade
               on the rest, and polls the health checks. Approval 2.
  <held step>  one hold group: postgres, redis, docker, or a step the knob's
               hold lines name. Stops each restarter that was active, then
               releases what the bulk held for it, runs the same command,
               polls the health checks every second, and starts the
               restarters again: on a green step, or one that failed before
               the upgrade. After a failed upgrade they stay stopped, for
               the owner. Approval 3(a): each group is its own invocation.

Lanes (references/policy.md):
  security     what the host's own unattended-upgrades origins take, which
               must be no wider than -security and the release pocket
               unless exception uu:origins covers more
  maintenance  those, plus Ubuntu's -updates and each origin the knob
               follows, from an APT_CONFIG file in the run's directory. Never
               a pinned or held origin
  origin:<origin>  one origin the knob follows, and nothing else: a
               security bulletin's out-of-cycle window. Its file adds that
               origin, and skips every other pending package
               (Package-Blacklist)
The bulk names the lane; its held steps run the same one.

Every step runs `NEEDRESTART_MODE=l choom -n 0 -- unattended-upgrade -v` as
root, with no memory cap, then runs probe.sh into the run's directory. It
never reboots, unmasks or enables anything, and never holds or releases a
package the owner held. It runs no apt-get remove or purge; the packages
unattended-upgrade auto-removes itself are reported, under
upgrade.auto_removed. A step takes minutes: start it where
nothing cuts it off, in the background, and read its JSON when it ends.

Options:
  --step STEP              bulk, or a held step (required)
  --approve                the owner's approval of this step, given in the
                           host's own session
  --lane LANE              the bulk only: security (the default),
                           maintenance or origin:<origin>
  --run DIR                the run's directory, an absolute path. A held step
                           needs it. On a host that declares a datastore,
                           pass the bulk the directory recovery-point.sh
                           wrote: without --run, the bulk makes
                           /var/backups/patching-hosts-<UTC>, which holds no
                           recovery point
  --dry-run DIR            the bulk only, and required there: the directory
                           probe.sh --dry-run-into wrote, within 24 hours,
                           for the same lane. Its wall time is the floor of
                           each step's expected duration
  --offnode-sha256 HEX     the bulk only: a dump's sha256, typed after the
                           owner checks their own copy off the node. One per
                           dump the recovery point recorded
  --offnode-object NAME    the bulk only: the object a backup unit wrote off
                           the node, typed after the owner confirms it
                           exists. One per backup unit
  --health-within SECONDS  how long the health checks may take to pass twice
                           in a row after a step (default 300)
  --config FILE            the knob (default: .skills/patching-hosts at the
                           root of the repo around the current directory, or
                           in the current directory outside a repo)
  --host NAME              whose knob sections apply (default: `hostname`)
  --today YYYY-MM-DD       the date exceptions expire against (default:
                           today, UTC)
  -h, --help               show this help

It refuses (exit 3) for each reason under refused, among them: without
--approve; on a report-only host (no knob, no posture line, class
ephemeral, a malformed line, a tie); without root, or as root with no
invoking user while the knob has inflight or health commands, which never
run as root (run it through sudo from your own account); when a command it
needs isn't on PATH (choom among them); when unattended-upgrade would
reboot by itself (Automatic-Reboot), or would take more than -security
without an unexpired exception uu:origins; in another lane, when the
host's own origins could take an origin the knob holds or pins, or apt
doesn't read the lane's file, or a held step's knob follows other origins
than its bulk did, or origin:<origin> names one the knob doesn't follow;
for the bulk, without --dry-run, or when its summary is missing, failed, is
more than 24 hours old, or counted another lane, or in the one-origin lane,
nothing or not all of the origin's upgrades; when dpkg --audit isn't
clean; when the step's span, from now to now plus its expected duration,
isn't wholly inside one window or overlaps a quiet range; while an
automatic apt run is in progress, or apt-daily-upgrade.timer could start
one inside the span (apt-daily.timer isn't read: on noble its 12-hour
random delay, twice a day, spans the whole day); while the run's reboot
chain is scheduled or
running; when an inflight command prints anything but 0, or exits
non-zero; and for a held step, when the run aborted at an earlier step,
its bulk isn't green, the step already ran, or the run holds nothing for
it. On a host that declares a datastore, the bulk also refuses until the
recovery point began within 24 hours, covers every datastore, and has left
the node: each dump attested by its sha256, and each backup unit, one the
knob declares, run successfully since the recovery point began, with its
object named. A backup unit stands in only for the datastores the record
says it covered, which its knob line must name too: each other datastore
needs its own dump.

The run's directory is root-only: 0700, and each file 0600.
  recovery-point   written before the bulk (run.md section 2 has its lines)
  lane.conf        another lane's APT_CONFIG, which each step reads
  dry-run          the dry run's summary, for the held steps' gate
  before-versions, before-showhold, before-showauto
  holds            "<step> <package>": each hold the run placed
  steps            one tab-separated line per step that began its upgrade:
                   <step>, ok or failed, when apply.sh started (epoch), and
                   the upgrade's wall seconds and max RSS in KiB, either
                   empty when it wasn't measured
  apt-get-update.log, <step>.log, <step>.max-rss-kib, <step>-health.log,
  probe-after-<step>.json and .err

Output: one JSON object on stdout, for exits 0, 1 and 3. Keys: apply,
refused, gate, then what the step did: holds, upgrade, health, restarters,
verdict, abort, next and reprobe.

Exit codes:
  0  the step ran, and its verdict is green
  1  the step failed. Before its upgrade (a refresh, a record, a release
     or a stop that failed), abort.instructions says so: nothing was
     upgraded and the step isn't recorded, so fix what failed and run it
     again. After it: stop. Its abort says what to do, and lists the holds
     the run left and any restarters still stopped. With nothing on
     stdout, it failed before the gate: read stderr
  2  usage error, an unreadable knob, or a library missing: nothing on
     stdout
  3  refused: nothing was changed
  *  any other code: apply.sh failed unexpectedly; read the run's
     directory, if it has one
USAGE
}

step="" approve=0 run="" dryrun="" config="" host="" today="" health_within=300 lane=""
attest=() objects=()
while [ "$#" -gt 0 ]; do
  case $1 in
    --step | --run | --lane | --dry-run | --offnode-sha256 | --offnode-object | --health-within | --config | --host | --today)
      [ "$#" -ge 2 ] || { echo "ERROR $1 needs a value" >&2; exit 2; }
      case $1 in
        --step) step=$2 ;;
        --run) run=$2 ;;
        --lane) lane=$2 ;;
        --dry-run) dryrun=$2 ;;
        --offnode-sha256) attest+=("$2") ;;
        --offnode-object) objects+=("$2") ;;
        --health-within) health_within=$2 ;;
        --config) config=$2 ;;
        --host) host=$2 ;;
        --today) today=$2 ;;
      esac
      shift 2 ;;
    --approve) approve=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1 (see --help)" >&2; exit 2 ;;
  esac
done

step_re='^[a-z0-9][a-z0-9-]*$'
sha_re='^[0-9a-f]{64}$'
date_re='^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$'
if [ -z "$step" ]; then
  echo "ERROR --step is required: bulk, or a held step (see --help)" >&2
  exit 2
fi
if ! [[ $step =~ $step_re ]]; then
  echo "ERROR --step takes bulk or a held step's name: lowercase letters, digits and hyphens" >&2
  exit 2
fi
for _v in "$run" "$dryrun" "$config" ${objects[@]+"${objects[@]}"}; do
  case $_v in *[[:cntrl:]]*)
    echo "ERROR an argument holds a control character" >&2
    exit 2 ;;
  esac
done
for _v in ${objects[@]+"${objects[@]}"}; do
  if [ -z "$_v" ]; then
    echo "ERROR --offnode-object takes the object's name" >&2
    exit 2
  fi
done
case $run in
  "" | /*) ;;
  *) echo "ERROR --run takes an absolute path" >&2; exit 2 ;;
esac
case $health_within in
  '' | *[!0-9]* | 0) echo "ERROR --health-within takes a number of seconds, 1 or more" >&2; exit 2 ;;
esac
sums=()
for _v in ${attest[@]+"${attest[@]}"}; do
  _v=$(printf '%s' "$_v" | tr 'A-F' 'a-f')
  if ! [[ $_v =~ $sha_re ]]; then
    echo "ERROR --offnode-sha256 takes a sha256: 64 hex digits" >&2
    exit 2
  fi
  sums+=("$_v")
done
case $lane in
  "" | security | maintenance | origin:?*) ;;
  *) echo "ERROR --lane takes security, maintenance or origin:<an origin the knob follows>" >&2; exit 2 ;;
esac
if [ "$step" != bulk ]; then
  if [ -n "$dryrun$lane" ] || [ "${#sums[@]}" -gt 0 ] || [ "${#objects[@]}" -gt 0 ]; then
    echo "ERROR --lane, --dry-run, --offnode-sha256 and --offnode-object belong to the bulk step: a held step runs its bulk's lane" >&2
    exit 2
  fi
  if [ -z "$run" ]; then
    echo "ERROR a held step needs --run DIR, the run its bulk made" >&2
    exit 2
  fi
fi

# --- shared libraries ---------------------------------------------------------
# Resolved through a symlink chain first, as probe.sh does: the skill is
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
for _lib in _knob-lib.sh _probe-lib.sh _gate-lib.sh probe.sh; do
  if [ -z "$_libdir" ] || [ ! -f "$_libdir/$_lib" ]; then
    echo "ERROR $_lib not found next to $_self" >&2
    exit 2
  fi
done
# shellcheck source=_knob-lib.sh
. "$_libdir/_knob-lib.sh"
# shellcheck source=_probe-lib.sh
. "$_libdir/_probe-lib.sh"
ME=apply
# shellcheck source=_gate-lib.sh
. "$_libdir/_gate-lib.sh"

# Every line parsed below is C-locale output, and so is the JSON builder's
# '?' for a byte that isn't printable ASCII.
export LC_ALL=C
# unattended-upgrade reads the host's own configuration, never a caller's.
unset APT_CONFIG

[ -n "$host" ] || host=$(hostname)
if [ -z "$config" ]; then
  config="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.skills/patching-hosts"
fi
[ -n "$today" ] || today=$(date -u +%Y-%m-%d)

# Called plainly, never in a condition: bash turns errexit off for everything
# a condition runs (read-knob.sh's note). A return of 2 exits 2 here.
knob_load "$config" "$host" "$today"
probe_init /
trap 'rm -rf "$P_TMP"' EXIT
# apply.sh acts on the running system, never on a tree, so every reading it
# takes asks that system: the probe's test for an offline tree doesn't apply.
P_LIVE=1
# unit_show sets these by name.
U_Result="" U_ExecMainStartTimestamp="" U_ExecMainExitTimestamp="" U_LoadState=""

[ -n "$run" ] || default_run run

# The lane: the bulk names it, and each held step runs its bulk's, as the
# dry run that bulk recorded says.
LANE=${lane:-security} _o=""
if [ "$step" != bulk ] && [ "$P_PRIV" != none ] && root_read _o "$run/dry-run"; then
  while IFS= read -r _l; do
    case $_l in lane=*) LANE=${_l#lane=} ;; esac
  done <<<"$_o"
fi
case $LANE in security | maintenance | origin:?*) ;; *) LANE=unknown ;; esac

# --- the gate -------------------------------------------------------------------
# _gate-lib.sh holds refuse and fail, the root-only records, the span and the
# inflight gate. No function here ends on a bare `[ … ] && …`: a function that
# returns non-zero stops the script under errexit, wherever it is called
# plainly.
NEXT=()
J_GATE="" J_HOLDS=null J_UPGRADE=null J_HEALTH=null J_RESTARTERS=null
J_VERDICT=null J_ABORT=null J_REPROBE=null

HOLD_STEPS=""
for _r in ${KNOB_HOLD[@]+"${KNOB_HOLD[@]}"}; do HOLD_STEPS="$HOLD_STEPS ${_r%%"$KNOB_US"*}"; done
HOLD_STEPS=${HOLD_STEPS# }

gate_host() {
  local why t
  [ "$approve" -eq 1 ] ||
    refuse "no --approve: the owner approves each step in the host's own session (run.md, Approvals)"
  for why in ${KNOB_REPORT_ONLY_WHY[@]+"${KNOB_REPORT_ONLY_WHY[@]}"}; do
    refuse "report-only: $why"
  done
  if [ "$P_PRIV" = none ]; then
    refuse "no root: run apply.sh as root, or as a user sudo -n lets through"
  fi
  for t in apt-get apt-mark dpkg dpkg-query unattended-upgrade systemctl; do
    have "$t" || refuse "$t isn't on PATH"
  done
  have choom ||
    refuse "choom isn't on PATH: the step would inherit this session's OOM adj, which may be -1000, so the kernel would kill a production service first (run.md section 3)"
  if in_words bulk "$HOLD_STEPS"; then
    refuse "the knob names a hold step bulk, the bulk step's own name: rename it"
  fi
  if [ "$step" != bulk ] && ! in_words "$step" "$HOLD_STEPS"; then
    refuse "no hold step $step for this host: its held steps are $HOLD_STEPS"
  fi
}

# unattended-upgrade reboots the host itself once reboot-required appears
# when Automatic-Reboot is true (2.9.1's reboot_if_requested_and_needed). It
# takes no -o, and APT_CONFIG is read before apt.conf.d, so nothing passed
# to it could override the host's setting: the step refuses instead.
HOST_PATTERNS=()
gate_uu() {
  local out line ur="" v n=0 wide="" wide_json="" origins="" o="" excepted=0 r
  local -a f=()
  if ! have apt-config; then
    refuse "apt-config isn't on PATH, so whether unattended-upgrade would reboot, and what it takes, is unknown"
    jadd J_GATE unattended_upgrade null
    return 0
  fi
  capture out apt-config shell UR Unattended-Upgrade::Automatic-Reboot
  if [ "$CAP_RC" -ne 0 ]; then
    refuse "apt-config couldn't be read, so whether unattended-upgrade would reboot, and what it takes, is unknown"
    jadd J_GATE unattended_upgrade null
    return 0
  fi
  while IFS= read -r line; do
    case $line in UR=*) ur=${line#UR=} ur=${ur#\'} ur=${ur%\'} ;; esac
  done <<<"$out"
  # apt's own false values; anything else, apt may read as true.
  case $(printf '%s' "$ur" | tr '[:upper:]' '[:lower:]') in
    '' | 0 | false | no | off | without | disable) ;;
    *) refuse "Unattended-Upgrade::Automatic-Reboot is \"$ur\": unattended-upgrade would reboot the host itself once reboot-required appears, and a step never reboots. Set it to false first: the owner's change" ;;
  esac
  capture out apt-config dump
  if [ "$CAP_RC" -ne 0 ]; then
    refuse "apt-config dump couldn't be read, so what unattended-upgrade takes is unknown"
  fi
  while IFS= read -r line; do
    case $line in
      "Unattended-Upgrade::Allowed-Origins:: "* | "Unattended-Upgrade::Origins-Pattern:: "*)
        v=${line#*:: \"}
        v=${v%\";}
        n=$((n + 1))
        HOST_PATTERNS+=("$v")
        jpushs origins "$v"
        if widens "$v"; then
          wide="$wide, $v"
          jpushs wide_json "$v"
        fi ;;
    esac
  done <<<"$out"
  wide=${wide#, }
  if [ "$CAP_RC" -eq 0 ] && [ "$n" -eq 0 ]; then
    refuse "unattended-upgrades takes no origin, so the step would upgrade nothing"
  fi
  if [ -n "$wide" ]; then
    for r in ${KNOB_EXCEPTION[@]+"${KNOB_EXCEPTION[@]}"}; do
      IFS=$KNOB_US read -r -a f <<<"$r"
      if [ "${f[0]}" = uu:origins ] && [ "${f[3]}" = 0 ]; then excepted=1; fi
    done
    [ "$excepted" -eq 1 ] ||
      refuse "unattended-upgrades takes more than -security: $wide. The security lane would apply them too: narrow its origins, or declare exception uu:origins (policy.md)"
  fi
  jaddsn o automatic_reboot "$ur"
  jadd o origins "[$origins]"
  jadd o wider "[$wide_json]"
  jaddb o wider_excepted "$excepted"
  jadd J_GATE unattended_upgrade "{$o}"
}

# The origins and sites an unattended-upgrades entry names, each as the knob
# names it (_ for a space): an Origins-Pattern's o=, origin= and site=
# fields, or an Allowed-Origins entry's part before the colon.
pattern_names() {  # <var> <entry>
  local _pn_e=$2 _pn_f _pn_n="" _pn_v
  local -a _pn_fs=()
  case $_pn_e in
    *=*)
      IFS=, read -r -a _pn_fs <<<"$_pn_e"
      for _pn_f in ${_pn_fs[@]+"${_pn_fs[@]}"}; do
        case $_pn_f in
          o=* | origin=* | site=*) _pn_v=${_pn_f#*=} _pn_n="$_pn_n ${_pn_v// /_}" ;;
        esac
      done ;;
    *:*)
      _pn_v=${_pn_e%%:*}
      _pn_v=${_pn_v//"$UU_DISTRO_ID"/Ubuntu}
      _pn_n=" ${_pn_v// /_}" ;;
  esac
  printf -v "$1" '%s' "${_pn_n# }"
}

# Another lane than security. The host's own origins, which it adds to,
# can't take an origin the knob holds or pins, and apt must read the lane's
# file. A held step runs its bulk's lane: the knob must follow the same
# origins now. The one-origin lane's skip list is the bulk's (do_bulk).
LANE_CONF=""
gate_lane() {
  local o="" a="" p r v n names stops="" out got="" missing="" l
  local -a f=()
  if [ "$LANE" = unknown ]; then
    refuse "$run/dry-run names a lane this apply.sh doesn't know: start a new run"
    return 0
  fi
  jadds o name "$LANE"
  if [ "$LANE" = security ]; then
    jadd o patterns "[]"
    jadd J_GATE lane "{$o}"
    return 0
  fi
  if ! lane_patterns "$LANE"; then
    refuse "$LANE_WHY"
    jadd J_GATE lane "{$o}"
    return 0
  fi
  LANE_CONF=$(lane_conf "${LANE_PATTERNS[@]}")
  for r in ${KNOB_ORIGIN[@]+"${KNOB_ORIGIN[@]}"}; do
    IFS=$KNOB_US read -r -a f <<<"$r"
    [ "${f[1]}" = follow ] || stops="$stops ${f[0]}"
  done
  # The security entries name Ubuntu's own pockets: only a wider one, which
  # exception uu:origins let through, could reach a third party.
  if [ -n "$stops" ]; then
    for p in ${HOST_PATTERNS[@]+"${HOST_PATTERNS[@]}"}; do
      widens "$p" || continue
      pattern_names names "$p"
      if [ -z "$names" ]; then
        refuse "the host's own unattended-upgrades origins take \"$p\", which names no origin or site, so the $LANE lane couldn't tell it from an origin the knob holds or pins:$stops. Narrow it first"
        continue
      fi
      for n in $names; do
        case $n in
          *[*?[]*) refuse "the host's own unattended-upgrades origins take \"$p\", whose $n is a pattern, so the $LANE lane couldn't tell it from an origin the knob holds or pins:$stops. Narrow it first" ;;
          *) in_words "$n" "$stops" && refuse "the host's own unattended-upgrades origins take \"$p\", which names ${n//_/ }, an origin the knob holds or pins: the $LANE lane would take it. Narrow the host's origins first" ;;
        esac
      done
    done
  fi
  # apt reads the lane's file, and adds its patterns to the host's.
  printf '%s\n' "$LANE_CONF" >"$P_TMP/lane.conf"
  capture out env APT_CONFIG="$P_TMP/lane.conf" apt-config dump
  while IFS= read -r l; do
    case $l in
      "Unattended-Upgrade::Origins-Pattern:: "*)
        v=${l#*:: \"}
        got="$got|${v%\";}" ;;
    esac
  done <<<"$out"
  for p in "${LANE_PATTERNS[@]}"; do
    case "$got|" in *"|$p|"*) ;; *) missing="$missing \"$p\"" ;; esac
    jpushs a "$p"
  done
  if [ "$CAP_RC" -ne 0 ] || [ -n "$missing" ]; then
    refuse "apt-config didn't read the $LANE lane's patterns (${missing# }) from APT_CONFIG${CAP_ERR:+: $CAP_ERR}, so unattended-upgrade wouldn't either"
  fi
  if [ "$step" != bulk ]; then
    if ! root_read l "$run/lane.conf"; then
      refuse "$run/lane.conf couldn't be read, so the lane its bulk ran is unknown"
    elif [ "${l:0:${#LANE_CONF}}" != "$LANE_CONF" ]; then
      refuse "the knob follows other origins than it did at the bulk, so this step would take another selection: restore its origin lines, or start a new run"
    fi
  fi
  jadd o patterns "[$a]"
  jadd J_GATE lane "{$o}"
}

gate_dpkg() {
  local out first
  [ "$P_PRIV" != none ] || return 0
  capture out as_root dpkg --audit
  if [ "$CAP_RC" -ne 0 ] || [ -n "$out" ]; then
    first=${out%%$'\n'*}
    [ -n "$first" ] || first=${CAP_ERR:-exit $CAP_RC}
    refuse "dpkg --audit isn't clean ($first): fix dpkg first, or a failure in this step couldn't be told from what was broken already"
  fi
}

# The run's state, read before a step: which steps ran, the holds the bulk
# placed, the owner's holds before it, and the dry run's cost.
RUN_STEPS="" RUN_FAILED="" BEFORE_HOLDS="" EXPECT="" RELEASED=""
RUN_HOLD_STEP=() RUN_HOLD_PKG=()
read_run_holds() {
  local out s p
  RUN_HOLD_STEP=() RUN_HOLD_PKG=()
  root_read out "$run/holds" || return 1
  while read -r s p; do
    if [ -n "$s" ] && [ -n "$p" ]; then RUN_HOLD_STEP+=("$s") RUN_HOLD_PKG+=("$p"); fi
  done <<<"$out"
}

gate_run() {
  local mode out s r rest line i n=0
  [ "$P_PRIV" != none ] || return 0
  if [ "$step" = bulk ]; then
    root_has "$run" || return 0
    file_mode mode "$run"
    [ "$mode" = 0700 ] || refuse "$run is mode ${mode:-unknown}, not 0700: a run's records are root-only"
    if root_has "$run/holds"; then
      refuse "$run's bulk already started: continue it with a held step, or start a new run"
    fi
    return 0
  fi
  if ! root_has "$run/steps"; then
    refuse "$run holds no bulk step: a held step continues a run whose bulk went green"
    return 0
  fi
  root_read out "$run/steps" || { refuse "$run/steps couldn't be read"; return 0; }
  while read -r s r rest; do
    [ -n "$s" ] || continue
    case $r in
      ok) RUN_STEPS="$RUN_STEPS $s" ;;
      *) RUN_FAILED=$s ;;
    esac
    [ "$s" = bulk ] || RELEASED="$RELEASED $s"
  done <<<"$out"
  if [ -n "$RUN_FAILED" ]; then
    refuse "the run aborted at $RUN_FAILED: no further held step, and no reboot, until the owner decides (run.md, Abort branch)"
  fi
  in_words bulk "$RUN_STEPS" || refuse "the run's bulk isn't green: a held step comes after it"
  if in_words "$step" "$RELEASED"; then refuse "step $step already ran in this run"; fi
  if read_run_holds; then
    for i in ${RUN_HOLD_STEP[@]+"${!RUN_HOLD_STEP[@]}"}; do
      [ "${RUN_HOLD_STEP[$i]}" != "$step" ] || n=$((n + 1))
    done
    [ "$n" -gt 0 ] ||
      refuse "the run holds nothing for $step: none of its packages was pending at the bulk, so there's no step to run"
  else
    refuse "$run/holds couldn't be read"
  fi
  if root_read out "$run/before-showhold"; then
    words_of BEFORE_HOLDS "$out"
  else
    refuse "$run/before-showhold couldn't be read, so the owner's holds are unknown"
  fi
  if root_read out "$run/dry-run"; then
    while IFS= read -r line; do
      case $line in wall_seconds=*) EXPECT=${line#wall_seconds=} ;; esac
    done <<<"$out"
  fi
  is_int "$EXPECT" || refuse "$run/dry-run holds no wall time, so the step's span is unknown"
}

# A step never runs into the reboot its run scheduled: the chain stops at a
# package manager running when it starts, but not at one that starts after.
gate_reboot() {
  local out
  [ "$P_PRIV" != none ] || return 0
  root_read out "$run/reboot-chain.unit" || return 0
  if chain_active "${out%% *}"; then
    refuse "the run's reboot chain, ${CHAIN_STATE% *}, is ${CHAIN_STATE##* }: no step until the host is back. Read $run/reboot-chain.log"
  fi
}

# A dry run counts the set pending that day: a month-old one counted
# another, so its wall time isn't this run's floor.
DRY_SUMMARY="" DRY_MAX_AGE=86400
gate_dry() {
  local line rc="" count="" began="" iso dlane=security dleft="" dleft_seen=0
  [ "$step" = bulk ] || return 0
  if [ -z "$dryrun" ]; then
    refuse "no --dry-run DIR: count first with probe.sh --dry-run-into DIR (run.md section 3). Its wall time is the floor of the step's expected duration"
    return 0
  fi
  if [ ! -r "$dryrun/summary" ]; then
    refuse "$dryrun/summary is missing: run probe.sh --dry-run-into $dryrun first"
    return 0
  fi
  DRY_SUMMARY=$(cat "$dryrun/summary")
  while IFS= read -r line; do
    case $line in
      began=*) began=${line#began=} ;;
      exit=*) rc=${line#exit=} ;;
      count=*) count=${line#count=} ;;
      wall_seconds=*) EXPECT=${line#wall_seconds=} ;;
      lane=*) dlane=${line#lane=} ;;
      origin_left=*) dleft=${line#origin_left=} dleft_seen=1 ;;
    esac
  done <<<"$DRY_SUMMARY"
  # Its wall time is this step's floor only for the selection it counted.
  if [ "$dlane" != "$LANE" ]; then
    refuse "the dry run counted the $dlane lane, and this bulk runs the $LANE lane: count again with probe.sh --lane $LANE --dry-run-into DIR"
  fi
  if [ "$rc" != 0 ]; then
    refuse "the dry run exited ${rc:-unknown}: read $dryrun/dry-run.log, and count again"
  elif ! is_int "$count"; then
    # Exit 0 with nothing counted: Update-Days, InstallOnShutdown or a lock
    # made unattended-upgrade skip the run, and the step would skip it the
    # same way, after holding every group.
    refuse "the dry run exited 0 but counted nothing: read $dryrun/dry-run.log, and count again"
  elif [ "$dlane" = "$LANE" ] && [[ $LANE == origin:* ]]; then
    # It counts that origin's packages alone, and names the ones it would
    # leave: a window that can't take them all fails after changing the
    # host, so it doesn't start.
    if [ "$dleft_seen" -eq 0 ]; then
      refuse "$dryrun/summary doesn't say which of the ${LANE#origin:} origin's packages the dry run would leave: count again with this skill's probe.sh"
    elif [ -n "$dleft" ]; then
      refuse "the dry run would leave $dleft from the ${LANE#origin:} origin pending: unattended-upgrade passes over an upgrade that needs a package from another origin, which this lane skips, or one the host's own Package-Blacklist names. Read $dryrun/dry-run.log; one whose dependency is another origin's needs a lane that takes both, such as maintenance"
    elif [ "$count" -eq 0 ]; then
      refuse "the dry run counted nothing from the ${LANE#origin:} origin, so this window would take nothing: its packages are current, its source isn't configured, or the owner holds them. Read $dryrun/dry-run.log"
    fi
  fi
  is_int "$EXPECT" || refuse "$dryrun/summary holds no wall time"
  if ! is_int "$began"; then
    refuse "$dryrun/summary doesn't say when the dry run began: count again with this skill's probe.sh"
  elif [ $((P_NOW - began)) -gt "$DRY_MAX_AGE" ]; then
    iso_utc iso "$began"
    refuse "the dry run began $iso, more than 24 hours ago: count again"
  fi
}

# The step's span: the dry run's wall time, plus the time the health checks
# may take.
gate_step_span() {
  local x=""
  if is_int "$EXPECT"; then
    x=$EXPECT
    if [ "${#KNOB_HEALTH[@]}" -gt 0 ]; then x=$((x + health_within)); fi
  fi
  gate_span "$x"
}

# Where the apt timers run, their unattended-upgrade takes the lock a step
# needs: one running now, or one that starts inside the span, fails the step
# with nothing upgraded ("Lock file is already taken", 2.9.1), after a held
# step has released its group and stopped its restarters. The timer's next
# run is no guide: systemd draws its random delay again at every
# daemon-reload, and a step's maintainer scripts reload it. So the span must
# miss the whole range the run can start in, each calendar time plus the
# delay, read from busctl in microseconds (FixedRandomDelay=no; systemd 255,
# measured 2026-10-01). A stopped timer still reports its calendar times.
APT_TIMER=/org/freedesktop/systemd1/unit/apt_2ddaily_2dupgrade_2etimer
gate_apt() {
  local u st out d=0 base end s_iso e_iso o="" a="" w="" e re='" ([0-9]+)(.*)$'
  for u in apt-daily.service apt-daily-upgrade.service; do
    st=$(systemctl is-active -- "$u" 2>/dev/null) || true
    case $st in
      active | activating | deactivating | reloading)
        jpushs a "$u"
        refuse "$u is $st: an automatic apt run is in progress. Wait for it to end, then gate again" ;;
    esac
  done
  jadd o running "[$a]"
  st=$(systemctl is-active -- apt-daily-upgrade.timer 2>/dev/null) || true
  if [ -n "$SPAN_S" ] && [ "$st" = active ]; then
    capture out busctl get-property org.freedesktop.systemd1 "$APT_TIMER" org.freedesktop.systemd1.Timer RandomizedDelayUSec
    case $out in "t "*) d=${out#t } ;; esac
    is_int "$d" || d=0
    capture out busctl get-property org.freedesktop.systemd1 "$APT_TIMER" org.freedesktop.systemd1.Timer TimersCalendar
    while [[ $out =~ $re ]]; do
      out=${BASH_REMATCH[2]}
      base=$((10#${BASH_REMATCH[1]} / 1000000))
      [ "$base" -gt 0 ] || continue
      end=$((base + d / 1000000))
      iso_utc s_iso "$base"
      iso_utc e_iso "$end"
      e=""
      jadds e from "$s_iso"
      jadds e to "$e_iso"
      jpush w "{$e}"
      if [ "$base" -le "$SPAN_E" ] && [ "$SPAN_S" -le "$end" ]; then
        refuse "apt-daily-upgrade.timer can start unattended-upgrade from $s_iso to $e_iso, which the step's span meets: start the step where its span misses that range"
      fi
    done
  fi
  jadd o upgrade_timer "[$w]"
  jadd J_GATE apt "{$o}"
}

# A dump can't be seen leaving the node from on it, so the bulk binds to the
# owner's attestation: each dump's sha256, typed after they check their own
# copy, and for a backup unit, which writes off the node itself, a run that
# started after the recovery point began and succeeded, plus the object's
# name. A recovery point from another day isn't one for this run.
RP_MAX_AGE=86400
gate_recovery() {
  local rec line kind engine unit rest db sha path key n=0 i r s x began="" retain="" o="" a="" e iso="" ok u k declared d kc w
  local -a f=() dbs=() need=() dkeys=() dsums=() dpaths=() backups=() bcovers=() kcovers=()
  [ "$step" = bulk ] || return 0
  if [ "${#KNOB_DATASTORE[@]}" -eq 0 ]; then
    if [ "${#sums[@]}" -gt 0 ] || [ "${#objects[@]}" -gt 0 ]; then
      refuse "the knob declares no datastore, so there's nothing to attest off the node: if this host holds one, declare it first"
    fi
    jadd J_GATE recovery_point null
    return 0
  fi
  # Units compare with their suffix, whichever way each side spells them.
  for r in "${KNOB_DATASTORE[@]}"; do
    IFS=$KNOB_US read -r -a f <<<"$r"
    unit_name u "${f[1]}"
    if [ "${f[0]}" = postgres ]; then
      read -r -a dbs <<<"${f[2]}"
      for db in "${dbs[@]}"; do need+=("postgres $u $db"); done
    else
      need+=("redis $u")
    fi
  done
  jadds o path "$run/recovery-point"
  if [ "$P_PRIV" = none ] || ! root_read rec "$run/recovery-point"; then
    refuse "the host declares a datastore, and $run holds no recovery point that could be read: take one first, and pass its directory with --run (run.md section 2)"
    jadd J_GATE recovery_point "{$o}"
    return 0
  fi
  while IFS= read -r line; do
    n=$((n + 1))
    [ -n "$line" ] || continue
    kind="" engine="" unit="" rest="" db="" sha="" path=""
    read -r kind engine unit rest <<<"$line"
    if [ -n "$unit" ]; then unit_name unit "$unit"; fi
    case $kind:$engine in
      began:*) began=$engine ;;
      dump:postgres) read -r db sha path <<<"$rest"; key="postgres $unit $db" ;;
      dump:redis) read -r sha path <<<"$rest"; key="redis $unit" ;;
      # A backup line names its unit and each datastore unit it covered.
      backup:*)
        if [ -n "$engine" ] && [ -n "$unit" ]; then
          w=""
          for d in $unit $rest; do unit_name d "$d"; w="$w $d"; done
          backups+=("$engine") bcovers+=("${w# }")
        else
          kind=bad
        fi ;;
      local:* | personal:*) [ -n "$engine" ] || kind=bad ;;
      retain:*) if [[ $engine =~ $date_re ]]; then retain=$engine; else kind=bad; fi ;;
      *) kind=bad ;;
    esac
    if [ "$kind" = dump ]; then
      if [[ $sha =~ $sha_re ]] && [ -n "$path" ]; then
        dkeys+=("$key") dsums+=("$sha") dpaths+=("$path")
      else
        kind=bad
      fi
    fi
    [ "$kind" != bad ] || refuse "the recovery point's line $n isn't one apply.sh reads (run.md section 2)"
  done <<<"$rec"
  if ! is_int "$began"; then
    refuse "the recovery point has no began line, so whether it's this run's is unknown"
  elif [ $((P_NOW - began)) -gt "$RP_MAX_AGE" ]; then
    iso_utc iso "$began"
    refuse "the recovery point began $iso, more than 24 hours ago: take one for this run"
  fi
  iso_utc iso "$began"
  jaddsn o began "$iso"
  jaddsn o retain_until "$retain"
  # Each datastore needs a dump, or a backup unit that covered its unit: a
  # backup stands in only for what its line names (CR 194).
  for key in ${need[@]+"${need[@]}"}; do
    s=0
    for i in ${dkeys[@]+"${!dkeys[@]}"}; do [ "${dkeys[$i]}" != "$key" ] || s=1; done
    u=${key#* } u=${u%% *}
    for i in ${bcovers[@]+"${!bcovers[@]}"}; do in_words "$u" "${bcovers[$i]}" && s=1; done
    [ "$s" -eq 1 ] || refuse "the recovery point holds no dump of $key, and no backup unit covered $u"
  done
  for i in ${dkeys[@]+"${!dkeys[@]}"}; do
    s=0
    for sha in ${sums[@]+"${sums[@]}"}; do [ "$sha" != "${dsums[$i]}" ] || s=1; done
    e=""
    jadds e datastore "${dkeys[$i]}"
    jadds e path "${dpaths[$i]}"
    jaddb e attested "$s"
    jpush a "{$e}"
    [ "$s" -eq 1 ] ||
      refuse "the dump ${dpaths[$i]} (${dkeys[$i]}) isn't attested off the node: once the owner's own copy checks out, pass its sha256 with --offnode-sha256"
  done
  jadd o dumps "[$a]"
  for sha in ${sums[@]+"${sums[@]}"}; do
    s=0
    for i in ${dsums[@]+"${!dsums[@]}"}; do [ "${dsums[$i]}" != "$sha" ] || s=1; done
    [ "$s" -eq 1 ] ||
      refuse "--offnode-sha256 $sha matches no dump the recovery point recorded: check which copy it came from"
  done
  a=""
  for i in ${backups[@]+"${!backups[@]}"}; do
    unit=${backups[$i]}
    unit_name unit "$unit"
    e="" ok=0 declared=0 kc=""
    jadds e unit "$unit"
    json_words w "${bcovers[$i]}"
    jadd e datastores "$w"
    # Only the host's own regime stands in for a dump: a unit a backup line
    # names, or the service a declared timer starts, and only for the
    # datastores that line names.
    for r in ${KNOB_BACKUP[@]+"${KNOB_BACKUP[@]}"}; do
      IFS=$KNOB_US read -r -a f <<<"$r"
      unit_name k "${f[0]}"
      if [ "$k" = "$unit" ] || [ "$k" = "${unit%.service}.timer" ]; then
        declared=1
        read -r -a kcovers <<<"${f[1]}"
        for d in ${kcovers[@]+"${kcovers[@]}"}; do unit_name d "$d"; kc="$kc $d"; done
      fi
    done
    jaddb e declared "$declared"
    w=""
    for d in ${bcovers[$i]}; do in_words "$d" "$kc" || w="$w $d"; done
    if [ "$declared" -eq 0 ]; then
      refuse "backup unit $unit isn't one the knob declares: only the host's own backup regime, named by a backup line (knob.md), stands in for a dump"
    elif [ -n "$w" ]; then
      refuse "backup unit $unit is recorded as covering$w, which its backup line doesn't name: take the recovery point again"
    elif ! unit_show "$unit" Result ExecMainStartTimestamp ExecMainExitTimestamp; then
      refuse "backup unit $unit's last run couldn't be read"
    else
      s=${U_ExecMainStartTimestamp#@} x=${U_ExecMainExitTimestamp#@}
      jaddsn e result "$U_Result"
      iso_utc iso "$s"
      jaddsn e started "$iso"
      # Its start, not its exit: a run begun before the recovery point read
      # the data as it stood then, whenever it finished.
      if ! is_int "$s" || ! is_int "$began" || [ "$s" -lt "$began" ]; then
        refuse "backup unit $unit hasn't started since the recovery point began: its last run started ${iso:-never}. Start it, and wait for it to succeed"
      elif ! is_int "$x" || [ "$x" -lt "$s" ]; then
        refuse "backup unit $unit hasn't finished the run it started at $iso"
      elif [ "$U_Result" != success ]; then
        refuse "backup unit $unit's last run ended in ${U_Result:-an unknown result}, not success"
      else
        ok=1
      fi
    fi
    jaddb e ok "$ok"
    jpush a "{$e}"
  done
  jadd o backups "[$a]"
  if [ "${#objects[@]}" -ne "${#backups[@]}" ]; then
    refuse "${#backups[@]} backup units wrote off the node, and ${#objects[@]} --offnode-object names were given: name each one's object, once the owner confirms it exists"
  fi
  a=""
  for s in ${objects[@]+"${objects[@]}"}; do jpushs a "$s"; done
  jadd o objects "[$a]"
  jadd J_GATE recovery_point "{$o}"
}

# Each restarter's state, read and recorded before the step. A held step
# stops the active ones around its restart.
R_UNIT=() R_BEFORE=()
gate_restarters() {
  local r u st a="" e
  local -a f=()
  for r in ${KNOB_RESTARTER[@]+"${KNOB_RESTARTER[@]}"}; do
    IFS=$KNOB_US read -r -a f <<<"$r"
    unit_name u "${f[0]}"
    # is-active reads a unit that doesn't exist as inactive (exit 4, systemd
    # 255), so a misspelled restarter would never be stopped.
    if ! unit_show "$u" LoadState; then
      refuse "restarter $u (line ${f[1]}): whether it's a unit on this host couldn't be read"
    elif [ "$U_LoadState" = not-found ]; then
      refuse "restarter $u (line ${f[1]}) isn't a unit on this host: a misspelled one leaves the real restarter running through the restart"
    fi
    st=$(systemctl is-active -- "$u" 2>/dev/null) || true
    R_UNIT+=("$u") R_BEFORE+=("${st:-unknown}")
    e=""
    jadds e unit "$u"
    jadds e state "${st:-unknown}"
    jpush a "{$e}"
  done
  jadd J_GATE restarters "[$a]"
}

emit() {
  local o="" a="" r
  jadds a step "$step"
  jadds a lane "$LANE"
  jadds a run "$run"
  jaddb a approved "$approve"
  jadds a host "$host"
  jadds a knob "$config"
  jadd o apply "{$a}"
  a=""
  for r in ${REFUSED[@]+"${REFUSED[@]}"}; do jpushs a "$r"; done
  jadd o refused "[$a]"
  jadd o gate "{$J_GATE}"
  jadd o holds "$J_HOLDS"
  jadd o upgrade "$J_UPGRADE"
  jadd o health "$J_HEALTH"
  jadd o restarters "$J_RESTARTERS"
  jadd o verdict "$J_VERDICT"
  jadd o abort "$J_ABORT"
  a=""
  for r in ${NEXT[@]+"${NEXT[@]}"}; do jpushs a "$r"; done
  jadd o next "[$a]"
  jadd o reprobe "$J_REPROBE"
  printf '{%s}\n' "$o"
}

gate_host
gate_uu
gate_lane
gate_dpkg
gate_run
gate_reboot
gate_dry
gate_step_span
gate_apt
gate_recovery
gate_restarters
# Last, so its reading is the freshest.
gate_inflight

if [ "${#REFUSED[@]}" -gt 0 ]; then
  for _r in "${REFUSED[@]}"; do echo "apply: refused: $_r" >&2; done
  emit
  exit 3
fi

# --- the step -------------------------------------------------------------------
# From here on the host changes. Each failure is recorded, and stops what
# would follow it.

# The holds apt-mark should show now: the owner's, plus the run's own for
# every held step that hasn't released them.
expected_holds() {  # <var>
  local _eh=$BEFORE_HOLDS _i
  for _i in ${RUN_HOLD_PKG[@]+"${!RUN_HOLD_PKG[@]}"}; do
    in_words "${RUN_HOLD_STEP[$_i]}" "$RELEASED" || _eh="$_eh ${RUN_HOLD_PKG[$_i]}"
  done
  words_of "$1" "$_eh"
}

check_holds() {
  local want got p missing="" extra=""
  local -a w=()
  expected_holds want
  capture got apt-mark showhold
  if [ "$CAP_RC" -ne 0 ]; then
    fail "apt-mark showhold couldn't be read after the step, so the holds are unproven"
    return 0
  fi
  words_of got "$got"
  read -r -a w <<<"$want" || true
  for p in ${w[@]+"${w[@]}"}; do in_words "$p" "$got" || missing="$missing $p"; done
  read -r -a w <<<"$got" || true
  for p in ${w[@]+"${w[@]}"}; do in_words "$p" "$want" || extra="$extra $p"; done
  if [ -n "$missing$extra" ]; then
    fail "apt-mark showhold isn't the owner's holds plus the run's unreleased ones:${missing:+ not held:$missing}${extra:+;}${extra:+ held besides:$extra}"
  fi
}

# The one-origin lane is there to take its origin's fix, and
# unattended-upgrade passes a package over without failing. It logs why, in
# a "Package <name> is ..." line: "kept back because a related package is
# kept back" for one whose upgrade needs a package the lane skips, "is
# blacklisted" for one the host's own Package-Blacklist names. With nothing
# else to take, it logs "No packages found" and exits 0 (2.9.1's
# find_kept_packages, read 2026-10-03; the blacklist's, seen live on noble the
# same day). So what the step took is read from apt afterwards: each of
# LANE_TAKE, the origin's packages this step is to take, must no longer be
# pending.
LANE_TAKE="" ORIGIN_LEFT="" ORIGIN_READ=0 ORIGIN_ERR=""
read_origin_left() {
  local out kw p rest
  capture out as_root apt-get -s "${APT_SIM_PHASED[@]}" dist-upgrade
  if [ "$CAP_RC" -ne 0 ]; then
    ORIGIN_ERR=${CAP_ERR:-exit $CAP_RC}
    return 0
  fi
  ORIGIN_READ=1
  while read -r kw p rest; do
    if [ "$kw" = Inst ] && in_words "$p" "$LANE_TAKE"; then ORIGIN_LEFT="$ORIGIN_LEFT $p"; fi
  done <<<"$out"
}

UU_RC="" UU_WALL="" UU_RSS="" UU_INSTALLED=0 UU_NOTHING=0 UU_UPGRADED="" UU_REMOVED=""
run_uu() {
  local log=$run/$step.log rss=$run/$step.max-rss-kib t0 out line o="" w
  local -a lenv=()
  # Another lane adds its origins to the host's own through APT_CONFIG,
  # read before apt.conf.d.
  if [ "$LANE" != security ]; then lenv=("APT_CONFIG=$run/lane.conf"); fi
  rss_timer "$rss"
  echo "apply: running unattended-upgrade for $step; its log is $log" >&2
  t0=$SECONDS
  UU_RC=0
  # NEEDRESTART_MODE backs up the drop-in: in apt's hook there's no -r, so
  # the variable wins. choom puts the step at adj 0, so the kernel doesn't
  # sacrifice a production service to protect a -1000 session. No memory
  # cap: a kill mid-dpkg leaves packages half-configured.
  root_logged "$log" env ${lenv[@]+"${lenv[@]}"} NEEDRESTART_MODE=l choom -n 0 -- ${TIMER[@]+"${TIMER[@]}"} unattended-upgrade -v || UU_RC=$?
  UU_WALL=$((SECONDS - t0))
  if [ "${#TIMER[@]}" -gt 0 ] && root_read out "$rss"; then rss_of UU_RSS "$out"; fi
  root_read out "$log" || out=""
  while IFS= read -r line; do
    case $line in
      *"All upgrades installed"*) UU_INSTALLED=1 ;;
      *"No packages found that can be upgraded unattended"*) UU_NOTHING=1 ;;
      *"Packages that will be upgraded:"*) UU_UPGRADED=${line#*Packages that will be upgraded:} ;;
      *"Packages that were successfully auto-removed:"*) UU_REMOVED=${line#*auto-removed:} ;;
    esac
  done <<<"$out"
  case $LANE in
    origin:*)
      if [ -z "$LANE_TAKE" ]; then
        ORIGIN_READ=1
      elif [ "$UU_RC" -eq 0 ]; then
        read_origin_left
      fi ;;
  esac
  jaddn o exit "$UU_RC"
  # The one-origin lane's: what the step was to take from the origin, and
  # what apt still has pending of it, or null when that wasn't read.
  case $LANE in
    origin:*)
      json_words w "$LANE_TAKE"
      jadd o origin_pending "$w"
      w=null
      if [ "$ORIGIN_READ" -eq 1 ]; then json_words w "$ORIGIN_LEFT"; fi
      jadd o origin_left "$w" ;;
  esac
  jaddn o wall_seconds "$UU_WALL"
  jaddn o max_rss_kib "$UU_RSS"
  jaddb o all_installed "$UU_INSTALLED"
  jaddb o nothing_to_do "$UU_NOTHING"
  json_words w "$UU_UPGRADED"
  jadd o upgraded "$w"
  json_words w "$UU_REMOVED"
  jadd o auto_removed "$w"
  jadds o log "$log"
  J_UPGRADE="{$o}"
  # The verdict: the exit code, the line, and dpkg's own audit. Never a
  # count of "Failed" or "error" lines: a clean apply logged about 100.
  if [ "$UU_RC" -ne 0 ]; then
    fail "unattended-upgrade exited $UU_RC: read $log"
  elif [ "$UU_INSTALLED" -eq 0 ] && [ "$UU_NOTHING" -eq 0 ]; then
    fail "unattended-upgrade exited 0, but logged neither \"All upgrades installed\" nor \"No packages found\": read $log. Update-Days or InstallOnShutdown can make it skip the run"
  elif [ -n "$ORIGIN_ERR" ]; then
    fail "apt-get -s dist-upgrade failed after the upgrade ($ORIGIN_ERR), so whether it took$LANE_TAKE from the ${LANE#origin:} origin is unknown"
  elif [ -n "$ORIGIN_LEFT" ]; then
    fail "unattended-upgrade exited 0 but left$ORIGIN_LEFT from the ${LANE#origin:} origin pending: $log says why, in a \"Package <name> is ...\" line for each. One kept back by a related package from another origin, which this lane skips, needs a lane that takes both, such as maintenance"
  fi
  capture out as_root dpkg --audit
  if [ "$CAP_RC" -ne 0 ] || [ -n "$out" ]; then
    line=${out%%$'\n'*}
    fail "dpkg --audit isn't clean after the step: ${line:-${CAP_ERR:-exit $CAP_RC}}"
  fi
}

# Every health command, every second, each result logged with its time,
# until all of them pass twice in a row or the time runs out.
HEALTH_OK=""
poll_health() {
  local r c l rc all streak=0 polls=0 t0=$SECONDS log=$run/$step-health.log lines="" ts o=""
  local -a f=()
  if [ "${#KNOB_HEALTH[@]}" -eq 0 ]; then
    jaddn o declared 0
    jadd o passed null
    J_HEALTH="{$o}"
    return 0
  fi
  while :; do
    polls=$((polls + 1))
    all=1
    for r in "${KNOB_HEALTH[@]}"; do
      IFS=$KNOB_US read -r -a f <<<"$r"
      c=${f[0]} l=${f[1]}
      rc=0
      knob_cmd "$c" >/dev/null 2>&1 || rc=$?
      iso_utc ts "$(date +%s)"
      lines="$lines$ts line $l exit $rc"$'\n'
      echo "apply: health $ts line $l exit $rc" >&2
      [ "$rc" -eq 0 ] || all=0
    done
    if [ "$all" -eq 1 ]; then streak=$((streak + 1)); else streak=0; fi
    if [ "$streak" -ge 2 ]; then
      HEALTH_OK=1
      break
    fi
    if [ $((SECONDS - t0)) -ge "$health_within" ]; then
      HEALTH_OK=0
      break
    fi
    sleep 1
  done
  printf '%s' "$lines" | root_write "$log" || fail "the health log $log couldn't be written"
  jaddn o declared "${#KNOB_HEALTH[@]}"
  jaddn o polls "$polls"
  jaddb o passed "$HEALTH_OK"
  jaddn o within_seconds "$health_within"
  jadds o log "$log"
  J_HEALTH="{$o}"
  [ "$HEALTH_OK" -eq 1 ] ||
    fail "the health checks didn't pass twice in a row within $health_within s: read $log"
}

# The holds this run still has on, for the abort and the record: each one
# apt-mark still shows, whatever its step, since a release can fail part-way
# and a hold can fail to take. Only when showhold can't be read, those of the
# steps that haven't released theirs.
holds_left() {  # <var>: JSON array
  local _hl="" _i _e _now="" _read=1
  capture _now apt-mark showhold
  if [ "$CAP_RC" -ne 0 ]; then _read=0 _now=""; fi
  words_of _now "$_now"
  for _i in ${RUN_HOLD_PKG[@]+"${!RUN_HOLD_PKG[@]}"}; do
    if [ "$_read" -eq 1 ]; then
      in_words "${RUN_HOLD_PKG[$_i]}" "$_now" || continue
    else
      in_words "${RUN_HOLD_STEP[$_i]}" "$RELEASED" && continue
    fi
    _e=""
    jadds _e step "${RUN_HOLD_STEP[$_i]}"
    jadds _e package "${RUN_HOLD_PKG[$_i]}"
    jpush _hl "{$_e}"
  done
  printf -v "$1" '[%s]' "$_hl"
}

STOPPED=""
finish() {
  local o="" a="" r rc=0 out result=ok ok=1 left u i err=""
  if [ "${#FAILED[@]}" -gt 0 ]; then result=failed; fi
  if [ "$STARTED" -eq 1 ]; then
    printf '%s\t%s\t%s\t%s\t%s\n' "$step" "$result" "$P_NOW" "${UU_WALL:-}" "${UU_RSS:-}" | root_append "$run/steps" ||
      { fail "$run/steps couldn't be written: the run's state is unrecorded"; result=failed; }
  fi
  # After the record, so a record that couldn't be written fails the verdict.
  for r in ${FAILED[@]+"${FAILED[@]}"}; do jpushs a "$r"; done
  if [ "$result" = failed ]; then ok=0; fi
  jaddb o ok "$ok"
  jadd o why "[$a]"
  J_VERDICT="{$o}"
  if [ "$result" = failed ] && [ "$STARTED" -eq 0 ]; then
    o="" a="" left="[]"
    if [ "$step" = bulk ]; then
      jpushs a "Nothing was held or upgraded: fix what failed, then run this step again."
    else
      holds_left left
      jpushs a "Nothing was upgraded, and the step isn't recorded: fix what failed, then run it again."
    fi
    if [ -n "$STOPPED" ]; then
      jpushs a "These restarters are still stopped:$STOPPED. Start each when the owner decides."
    fi
    jadd o instructions "[$a]"
    jadd o holds_left "$left"
    json_words a "$STOPPED"
    jadd o restarters_stopped "$a"
    J_ABORT="{$o}"
  elif [ "$result" = failed ]; then
    holds_left left
    o="" a=""
    jpushs a "Stop: no further held step, and no reboot, until the owner decides (run.md, Abort branch)."
    jpushs a "If dpkg --audit lists anything, consider sudo dpkg --configure -a, after recording the state."
    jpushs a "A rollback reinstalls the version recorded in $run/before-versions. Where apt's cache is emptied after each run (docker-clean), fetch it from snapshot.ubuntu.com."
    if [ "$left" != "[]" ]; then
      jpushs a "Each hold this run left is still on: release it with sudo apt-mark unhold <package>, or declare it as exception held:<package> <review-by> <reason>. An undeclared hold skips that package in every later run."
    fi
    if [ -n "$STOPPED" ]; then
      jpushs a "These restarters are still stopped:$STOPPED. Start each when the owner decides."
    fi
    jadd o instructions "[$a]"
    jadd o holds_left "$left"
    json_words a "$STOPPED"
    jadd o restarters_stopped "$a"
    J_ABORT="{$o}"
  else
    # In the knob's order, not apt's, by this script's own path: from the
    # project root, a bare apply.sh resolves to nothing (#63).
    for u in $HOLD_STEPS; do
      in_words "$u" "$RELEASED" && continue
      for i in ${RUN_HOLD_STEP[@]+"${!RUN_HOLD_STEP[@]}"}; do
        [ "${RUN_HOLD_STEP[$i]}" = "$u" ] || continue
        NEXT+=("bash \"$_libdir/apply.sh\" --approve --step $u --run \"$run\": approval 3(a), a restart")
        break
      done
    done
    NEXT+=("the reboot decision: run.md section 4")
  fi
  # The probe again, into the run, for the record: never part of the verdict.
  out=$(bash "$_libdir/probe.sh" --config "$config" --host "$host" --today "$today" 2>"$P_TMP/reprobe.err") || rc=$?
  o=""
  jaddn o exit "$rc"
  if printf '%s\n' "$out" | root_write "$run/probe-after-$step.json"; then
    jadds o path "$run/probe-after-$step.json"
  else
    jadd o path null
  fi
  # Its diagnostics too, which the scratch directory would lose at exit, and
  # on a failure their last line, where the probe says why.
  if root_write "$run/probe-after-$step.err" <"$P_TMP/reprobe.err"; then
    jadds o stderr "$run/probe-after-$step.err"
  else
    jadd o stderr null
  fi
  if [ "$rc" -ne 0 ]; then err=$(tail -n 1 "$P_TMP/reprobe.err" 2>/dev/null) || err=""; fi
  jaddsn o error "$err"
  J_REPROBE="{$o}"
  emit
  if [ "$result" = ok ]; then exit 0; fi
  exit 1
}

STARTED=0

LANE_KEEP=""
do_bulk() {
  local out pend="" p i r s g o="" a="" names="" e kw rest pol onames oskip
  local -a f=() w=()
  if ! root_has "$run" && ! as_root mkdir -p -m 700 -- "$run"; then
    fail "$run couldn't be made"
    return 0
  fi
  # The host's own lists: the probe's dry run counted against a scratch copy,
  # and on a host whose timers are masked, these may be months old.
  if ! root_logged "$run/apt-get-update.log" apt-get update; then
    fail "apt-get update failed: read $run/apt-get-update.log. Nothing was held or upgraded"
    return 0
  fi
  printf '%s\n' "$DRY_SUMMARY" | root_write "$run/dry-run" || { fail "$run/dry-run couldn't be written"; return 0; }
  # The lane's selection, which the bulk and each held step read.
  if [ "$LANE" = maintenance ] && ! printf '%s\n' "$LANE_CONF" | root_write "$run/lane.conf"; then
    fail "$run/lane.conf couldn't be written: nothing was held or upgraded"
    return 0
  fi
  capture out dpkg-query -W
  if [ "$CAP_RC" -ne 0 ] || ! printf '%s\n' "$out" | root_write "$run/before-versions"; then
    fail "the before-versions couldn't be recorded: nothing was held or upgraded"
    return 0
  fi
  capture out apt-mark showauto
  if [ "$CAP_RC" -ne 0 ] || ! printf '%s\n' "$out" | root_write "$run/before-showauto"; then
    fail "apt-mark showauto couldn't be recorded: nothing was held or upgraded"
    return 0
  fi
  capture out apt-mark showhold
  if [ "$CAP_RC" -ne 0 ] || ! printf '%s\n' "$out" | root_write "$run/before-showhold"; then
    fail "the owner's holds couldn't be recorded: nothing was held or upgraded"
    return 0
  fi
  words_of BEFORE_HOLDS "$out"
  # What's pending now, against the refreshed lists: every upgrade, from any
  # origin, so a group is held whichever origin its update comes from, and
  # whatever its phase: unattended-upgrade ignores phasing (_probe-lib.sh).
  capture out as_root apt-get -s "${APT_SIM_PHASED[@]}" dist-upgrade
  if [ "$CAP_RC" -ne 0 ]; then
    fail "apt-get -s dist-upgrade failed (${CAP_ERR:-exit $CAP_RC}): nothing was held or upgraded"
    return 0
  fi
  while read -r kw p rest; do
    case $kw:$rest in Inst:"["*) pend="$pend $p" ;; esac
  done <<<"$out"
  # The one-origin lane takes that origin's packages alone: every other
  # pending package goes in its file's Package-Blacklist, and only its own
  # are candidates for a hold group. The split reads the lists just
  # refreshed, so it's what unattended-upgrade sees.
  case $LANE in
    origin:*)
      capture pol apt-cache policy
      if [ "$CAP_RC" -ne 0 ]; then
        fail "apt-cache policy failed (${CAP_ERR:-exit $CAP_RC}), so the ${LANE#origin:} origin's packages are unknown: nothing was held or upgraded"
        return 0
      fi
      origin_names onames "${LANE#origin:}" "$pol"
      origin_split LANE_KEEP oskip "$onames" "$out"
      # A window with nothing from the origin in it fails here, before any
      # hold: unattended-upgrade would log "No packages found" and exit 0.
      if [ "$onames" = "|" ]; then
        fail "apt-cache policy lists no origin at ${LANE#origin:}, so nothing from it is pending: is its source configured? Nothing was held or upgraded"
        return 0
      elif [ -z "$LANE_KEEP" ]; then
        fail "nothing from the ${LANE#origin:} origin is pending against the refreshed lists: its packages are current, its source isn't configured, or the owner holds them (apt-mark showhold: ${BEFORE_HOLDS:-none}). Nothing was held or upgraded"
        return 0
      fi
      pend=""
      for p in $LANE_KEEP; do pend="$pend $p"; done
      # A word list, each a package name.
      # shellcheck disable=SC2086
      if ! { printf '%s\n' "$LANE_CONF"; lane_skip_conf $oskip; } | root_write "$run/lane.conf"; then
        fail "$run/lane.conf couldn't be written: nothing was held or upgraded"
        return 0
      fi ;;
  esac
  # Each pending package matching a hold group's globs, in the knob's order,
  # unless the owner already holds it: the run never holds or releases those.
  read -r -a w <<<"$pend" || true
  for p in ${w[@]+"${w[@]}"}; do
    in_words "$p" "$BEFORE_HOLDS" && continue
    for r in ${KNOB_HOLD[@]+"${KNOB_HOLD[@]}"}; do
      IFS=$KNOB_US read -r -a f <<<"$r"
      if glob_match "$p" "${f[1]}"; then
        RUN_HOLD_STEP+=("${f[0]}") RUN_HOLD_PKG+=("$p")
        break
      fi
    done
  done
  out=""
  for i in ${RUN_HOLD_PKG[@]+"${!RUN_HOLD_PKG[@]}"}; do
    out="$out${RUN_HOLD_STEP[$i]} ${RUN_HOLD_PKG[$i]}"$'\n'
    names="$names ${RUN_HOLD_PKG[$i]}"
  done
  # The bulk takes the origin's packages no group holds; each held step, its
  # own (do_held).
  for p in $LANE_KEEP; do in_words "$p" "$names" || LANE_TAKE="$LANE_TAKE $p"; done
  # Written before the hold, so a hold that half-works is still on record.
  if ! printf '%s' "$out" | root_write "$run/holds"; then
    fail "$run/holds couldn't be written: nothing was held or upgraded"
    return 0
  fi
  STARTED=1
  for s in $HOLD_STEPS; do
    g=""
    for i in ${RUN_HOLD_PKG[@]+"${!RUN_HOLD_PKG[@]}"}; do
      [ "${RUN_HOLD_STEP[$i]}" != "$s" ] || g="$g ${RUN_HOLD_PKG[$i]}"
    done
    if [ -n "$g" ]; then
      json_words e "$g"
      jadd a "$s" "$e"
    fi
  done
  jadd o placed "{$a}"
  json_words e "$BEFORE_HOLDS"
  jadd o owner "$e"
  J_HOLDS="{$o}"
  read -r -a w <<<"$names" || true
  if [ "${#w[@]}" -gt 0 ] && ! as_root apt-mark hold "${w[@]}" >/dev/null; then
    fail "apt-mark hold failed: the bulk didn't run"
    return 0
  fi
  check_holds
  [ "${#FAILED[@]}" -eq 0 ] || return 0
  run_uu
  check_holds
  poll_health
}

do_held() {
  local i out o="" a="" e names="" rel="" u st left x
  local -a w=()
  read_run_holds || true
  for i in ${RUN_HOLD_PKG[@]+"${!RUN_HOLD_PKG[@]}"}; do
    [ "${RUN_HOLD_STEP[$i]}" != "$step" ] || names="$names ${RUN_HOLD_PKG[$i]}"
  done
  read -r -a w <<<"$names" || true
  # Stopped around the restart, so a health timer doesn't restart the app
  # into a database that's down. Stopped before the release, too: a stop
  # that fails then leaves the group held, rather than open to the next
  # automatic upgrade with the step unable to run again.
  for i in ${R_UNIT[@]+"${!R_UNIT[@]}"}; do
    [ "${R_BEFORE[$i]}" = active ] || continue
    if ! as_root systemctl stop -- "${R_UNIT[$i]}"; then
      fail "systemctl stop ${R_UNIT[$i]} failed: nothing was released or upgraded"
      break
    fi
    STOPPED="$STOPPED ${R_UNIT[$i]}"
  done
  if [ "${#FAILED[@]}" -eq 0 ] && [ "${#w[@]}" -gt 0 ] &&
    ! as_root apt-mark unhold "${w[@]}" >/dev/null; then
    fail "apt-mark unhold failed: nothing was upgraded"
  fi
  # Released once the unhold ran and exited 0. Whether showhold agrees is
  # read after the upgrade.
  if [ "${#FAILED[@]}" -eq 0 ]; then rel=$names; fi
  json_words e "$rel"
  jadd o released "$e"
  json_words e "$BEFORE_HOLDS"
  jadd o owner "$e"
  J_HOLDS="{$o}"
  # The step starts with the upgrade: until then nothing it changed needs
  # the owner, and it isn't recorded, so it can run again.
  if [ "${#FAILED[@]}" -eq 0 ]; then
    STARTED=1
    RELEASED="$RELEASED $step"
    # In the one-origin lane, a group holds only the origin's packages.
    case $LANE in origin:*) LANE_TAKE=$rel ;; esac
    run_uu
    check_holds
    poll_health
  fi
  # Started again on a green step, and on one that failed before the
  # upgrade, which restarted nothing. After a failed upgrade, the owner
  # decides.
  if [ "${#FAILED[@]}" -eq 0 ] || [ "$STARTED" -eq 0 ]; then
    for i in ${R_UNIT[@]+"${!R_UNIT[@]}"}; do
      u=${R_UNIT[$i]}
      in_words "$u" "$STOPPED" || continue
      if ! as_root systemctl start -- "$u"; then
        fail "systemctl start $u failed"
        continue
      fi
      st=$(systemctl is-active -- "$u" 2>/dev/null) || true
      if [ "$st" = active ]; then
        left=""
        for x in $STOPPED; do [ "$x" = "$u" ] || left="$left $x"; done
        STOPPED=$left
      else
        fail "restarter $u is ${st:-unknown} after its start, not active"
      fi
    done
  fi
  for i in ${R_UNIT[@]+"${!R_UNIT[@]}"}; do
    e=""
    jadds e unit "${R_UNIT[$i]}"
    jadds e before "${R_BEFORE[$i]}"
    x=0
    if in_words "${R_UNIT[$i]}" "$STOPPED"; then x=1; fi
    jaddb e left_stopped "$x"
    jpush a "{$e}"
  done
  J_RESTARTERS="[$a]"
}

if [ "$step" = bulk ]; then do_bulk; else do_held; fi
finish
