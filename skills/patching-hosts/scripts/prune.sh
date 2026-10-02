#!/usr/bin/env bash
# prune.sh — run one stage of a component's prune, on exactly what its plan
# names: disable, savepoint, remove or purge.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash prune.sh --stage disable|savepoint|remove|purge --plan FILE
                     [--approve] [--savepoint DIR] [--purge-data PATH]...
                     [--run DIR] [--config FILE] [--host NAME]
                     [--today YYYY-MM-DD]

Runs one stage of a prune (references/pruning.md) on exactly what the plan
names. Without --approve it changes nothing, and prints every command the
stage would run. A plan is good for the host it was taken on, for 24 hours,
and only while the host still matches it: a stage refuses when a fresh read
gives other packages, units or members, so an approval binds to exactly
what the plan names.

The stages, each after the last one's soak (its review-by date, policy.md):
  disable    stop, disable and mask the units its packages ship, each in one
             systemctl call, so systemd orders the stops
  savepoint  a tarball of its config and its packages' other conffiles, and
             its packages' versions, as root at mode 600 in the run's
             directory. Its data stays with you: dump it off the node
             yourself, with a stated retention
  remove     apt-get remove of exactly the plan's packages, never an
             autoremove, then its group's members dropped from the group
  purge      apt-get purge of exactly the plan's packages, the members
             dropped and the group deleted, then each --purge-data path.
             Each package's own purge script runs too: the plan lists what
             each one deletes, and where one deletes a data path, the purge
             refuses until --purge-data names it
With a savepoint, the purge may follow the disable's soak, and the remove
stage is skipped: that leaves no config, and no rc package, behind.

Options:
  --stage STAGE        disable, savepoint, remove or purge
  --plan FILE          the plan prune-plan.sh --out wrote, within 24 hours
  --approve            the owner's approval of this stage, given in the
                       host's own session
  --savepoint DIR      (purge) the component's savepoint: the purge may then
                       follow the disable's soak
  --purge-data PATH    (purge) delete this config or data path, one the plan
                       names. Repeatable. Without it, its data stays
  --run DIR            where the logs and the savepoint go, an absolute path
                       (default: /var/backups/patching-hosts-prune-<component>)
  --config FILE        the knob (default: .skills/patching-hosts at the repo
                       root, or in the current directory)
  --host NAME          whose knob sections apply (default: `hostname`)
  --today DATE         the date exceptions expire against (default: today,
                       UTC)
  -h, --help           show this help

It refuses (exit 3) without --approve; on a report-only host; without root;
for a plan it can't read, another host's, one more than 24 hours old, or one
naming anything outside the component; for a stage the knob's calendar
hasn't reached; when the host no longer matches the plan, or apt would
install anything; for remove or purge while a package manager runs,
dpkg --audit isn't clean or one of its packages is held, or of a component
from outside apt; for a --purge-data path the plan doesn't name; and for a
purge whose packages' own scripts delete a data path --purge-data doesn't
name.

Output: one JSON object on stdout. Keys: prune, refused, gate, actions
(each command, in order), done (each one's exit), verdict and next.

Exit codes:
  0  the stage ran
  1  a command failed: done says which, and the run's <stage>.log has its
     output
  2  usage error, an unreadable knob, or a library missing
  3  refused: nothing was changed
USAGE
}

approve=0 stage="" plan="" savepoint="" run="" config="" host="" today=""
purge_data=()
while [ "$#" -gt 0 ]; do
  case $1 in
    --stage | --plan | --savepoint | --purge-data | --run | --config | --host | --today)
      [ "$#" -ge 2 ] || { echo "ERROR $1 needs a value" >&2; exit 2; }
      case $1 in
        --stage) stage=$2 ;;
        --plan) plan=$2 ;;
        --savepoint) savepoint=$2 ;;
        --purge-data) purge_data+=("$2") ;;
        --run) run=$2 ;;
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

case $stage in
  disable | savepoint | remove | purge) ;;
  *) echo "ERROR --stage takes disable, savepoint, remove or purge" >&2; exit 2 ;;
esac
if [ -z "$plan" ]; then
  echo "ERROR --plan FILE is required: the plan prune-plan.sh --out wrote" >&2
  exit 2
fi
if [ "$stage" != purge ] && [ -n "$savepoint${purge_data[*]-}" ]; then
  echo "ERROR --savepoint and --purge-data belong to --stage purge" >&2
  exit 2
fi
for _v in "$plan" "$savepoint" "$run" "$config" ${purge_data[@]+"${purge_data[@]}"}; do
  case $_v in *[[:cntrl:]]*)
    echo "ERROR an argument holds a control character" >&2
    exit 2 ;;
  esac
done
for _v in "$savepoint" "$run" ${purge_data[@]+"${purge_data[@]}"}; do
  case $_v in
    "" | /*) ;;
    *) echo "ERROR --savepoint, --run and --purge-data take absolute paths" >&2; exit 2 ;;
  esac
done

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
for _lib in _knob-lib.sh _probe-lib.sh _gate-lib.sh _prune-lib.sh; do
  if [ -z "$_libdir" ] || [ ! -f "$_libdir/$_lib" ]; then
    echo "ERROR $_lib not found next to $_self" >&2
    exit 2
  fi
done
# shellcheck source=_knob-lib.sh
. "$_libdir/_knob-lib.sh"
# shellcheck source=_probe-lib.sh
. "$_libdir/_probe-lib.sh"
ME=prune
# shellcheck source=_gate-lib.sh
. "$_libdir/_gate-lib.sh"
# shellcheck source=_prune-lib.sh
. "$_libdir/_prune-lib.sh"

# Every line parsed below is C-locale output, and so is the JSON builder's
# '?' for a byte that isn't printable ASCII.
export LC_ALL=C

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
# It acts on the running system, never on a tree.
P_LIVE=1
# unit_show sets it by name.
U_FragmentPath=""

component=""
if read_plan "$plan"; then component=$PLAN_COMPONENT; fi
prune_component "$component" || true
[ -n "$run" ] || run=/var/backups/patching-hosts-prune-${component:-unknown}

# --- the gate -------------------------------------------------------------------
# No function here ends on a bare `[ … ] && …`: a function that returns
# non-zero stops the script under errexit, wherever it is called plainly.
J_GATE="" J_DONE=null J_VERDICT=null
NEXT=()
PLAN_OK=0

gate_host() {
  local why t
  [ "$approve" -eq 1 ] ||
    refuse "no --approve: the owner approves each prune stage in the host's own session. The commands it would run are under actions"
  for why in ${KNOB_REPORT_ONLY_WHY[@]+"${KNOB_REPORT_ONLY_WHY[@]}"}; do
    refuse "report-only: $why"
  done
  if [ "$P_PRIV" = none ]; then
    refuse "no root: run prune.sh as root, or as a user sudo -n lets through"
  fi
  for t in systemctl dpkg-query; do
    have "$t" || refuse "$t isn't on PATH"
  done
  case $stage in
    remove | purge) for t in apt-get dpkg; do have "$t" || refuse "$t isn't on PATH"; done ;;
    savepoint) for t in tar sha256sum; do have "$t" || refuse "$t isn't on PATH"; done ;;
  esac
}

# The plan is this host's, fresh, and names only what the component is.
gate_plan() {
  local o="" p before=${#REFUSED[@]}
  if [ -z "$component" ]; then
    refuse "$plan couldn't be read, or isn't a plan prune-plan.sh wrote"
    jadd J_GATE plan null
    return 0
  fi
  jadds o component "$component"
  jadds o host "$PLAN_HOST"
  if is_int "$PLAN_TAKEN"; then iso_utc p "$PLAN_TAKEN"; jadds o taken "$p"; else jadd o taken null; fi
  jadd J_GATE plan "{$o}"
  if ! prune_component "$component"; then
    refuse "the plan names $component, a component the probe doesn't know"
    return 0
  fi
  [ -z "$PLAN_BAD" ] || refuse "the plan holds lines prune-plan.sh doesn't write ($PLAN_BAD): take a fresh one"
  [ "$PLAN_HOST" = "$host" ] || refuse "the plan was taken on ${PLAN_HOST:-no host}, and this is $host"
  if ! is_int "$PLAN_TAKEN"; then
    refuse "the plan doesn't say when it was taken: take a fresh one"
  elif [ $((P_NOW - PLAN_TAKEN)) -gt 86400 ] || [ $((PLAN_TAKEN - P_NOW)) -gt 300 ]; then
    refuse "the plan was taken more than 24 hours ago: take a fresh one for this stage, and approve that"
  fi
  # A path or a group the component doesn't have is no plan of its.
  for p in $PLAN_CONFIG; do in_words "$p" "$C_CONFIG" || refuse "the plan names $p, which isn't $component's config"; done
  for p in $PLAN_DATA; do in_words "$p" "$C_DATA" || refuse "the plan names $p, which isn't $component's data"; done
  if [ -n "$PLAN_GROUP" ] && [ "$PLAN_GROUP" != "$C_GROUP" ]; then
    refuse "the plan names the group $PLAN_GROUP, which isn't $component's"
  fi
  if [ -n "$C_UNIT" ]; then
    case $stage in
      remove | purge) refuse "$component comes from outside apt: remove its unit, binary and data by hand (pruning.md)" ;;
    esac
  fi
  for p in ${purge_data[@]+"${purge_data[@]}"}; do
    in_words "$p" "$PLAN_CONFIG $PLAN_DATA" || refuse "--purge-data $p isn't a path the plan names"
  done
  # Its own refusals only: a run without --approve still prints the plan's
  # commands.
  [ "${#REFUSED[@]}" -gt "$before" ] || PLAN_OK=1
}

# The calendar: each stage waits for the last one's review-by date, declared
# in the knob (policy.md). A savepoint lets the purge follow the disable.
# The record is written last, and only once its tarball's sha256 was read,
# so a tarball that doesn't match it is no savepoint.
SP_OK=0 SP_WHY=""
gate_savepoint() {  # <dir>: whether it holds this component's savepoint; SP_WHY when not
  local rec l k v c="" h="" sha="" now=""
  SP_WHY=""
  if ! root_read rec "$1/savepoint"; then
    SP_WHY="$1 holds no savepoint record"
    return 1
  fi
  while read -r k v l; do
    case $k in
      component) c=$v ;;
      host) h=$v ;;
      config.tar) sha=$v ;;
    esac
  done <<<"$rec"
  if [ "$c" != "$component" ] || [ "$h" != "$host" ]; then
    SP_WHY="$1 holds ${c:-no component}'s savepoint on ${h:-no host}, not $component's on $host"
    return 1
  fi
  if ! root_has "$1/versions"; then
    SP_WHY="$1/versions is missing"
    return 1
  fi
  capture now as_root sha256sum "$1/config.tar"
  now=${now%% *}
  if [ "$CAP_RC" -ne 0 ] || [ -z "$sha" ] || [ "$now" != "$sha" ]; then
    SP_WHY="$1/config.tar isn't the tarball its record names: its sha256 is ${now:-unreadable}, and the record's ${sha:-empty}"
    return 1
  fi
}

gate_calendar() {
  local o="" d
  [ "$PLAN_OK" -eq 1 ] || return 0
  calendar "$component"
  d=$CAL_STAGE
  jadds o declared "$d"
  jaddsn o review_by "$CAL_REVIEW"
  jaddb o soak_over "$CAL_PASSED"
  if [ "$stage" = purge ] && [ -n "$savepoint" ] && gate_savepoint "$savepoint"; then SP_OK=1; fi
  jaddb o savepoint "$SP_OK"
  jadd J_GATE calendar "{$o}"
  case $stage:$d in
    disable:keep | savepoint:keep | remove:keep | purge:keep)
      refuse "the knob keeps $component until $CAL_REVIEW (exception keep:$component, line $CAL_LINE)" ;;
    disable:none | disable:disabled) ;;
    disable:*) refuse "$component is already $d: nothing to disable" ;;
    savepoint:disabled | savepoint:removed) ;;
    savepoint:*) refuse "disable $component first, and declare exception disabled:$component <review-by> <reason>" ;;
    remove:disabled)
      [ "$CAL_PASSED" = 1 ] ||
        refuse "$component is soaking until $CAL_REVIEW: the remove waits for it. An earlier review-by date shortens the soak" ;;
    remove:none) refuse "disable $component first: the remove follows the disable's soak" ;;
    remove:*) refuse "$component is already $d" ;;
    purge:removed)
      [ "$CAL_PASSED" = 1 ] ||
        refuse "$component is soaking until $CAL_REVIEW: the purge waits for it. An earlier review-by date shortens the soak" ;;
    purge:disabled)
      if [ "$CAL_PASSED" != 1 ]; then
        refuse "$component is soaking until $CAL_REVIEW: the purge waits for it. An earlier review-by date shortens the soak"
      elif [ "$SP_OK" -ne 1 ]; then
        refuse "the remove comes next, or a savepoint lets the purge skip it: --stage savepoint, then --savepoint DIR${SP_WHY:+ ($SP_WHY)}"
      fi ;;
    purge:none) refuse "disable $component first: the purge comes last" ;;
    purge:purged) refuse "$component is already purged" ;;
  esac
}

# No apt run under another, and a dpkg that's clean before it starts, so a
# failure can be told from what was broken already.
gate_packages() {
  local who out first
  case $stage in remove | purge) ;; *) return 0 ;; esac
  package_manager who
  [ -z "$who" ] || refuse "$who is running: wait for it to end"
  jaddsn J_GATE package_manager_running "$who"
  [ "$P_PRIV" != none ] || return 0
  capture out as_root dpkg --audit
  if [ "$CAP_RC" -ne 0 ] || [ -n "$out" ]; then
    first=${out%%$'\n'*}
    refuse "dpkg --audit isn't clean (${first:-${CAP_ERR:-exit $CAP_RC}}): fix dpkg first"
  fi
}

# The host as it stands now, against the plan: the approval binds to it.
SIG_NOW=""
gate_drift() {
  local rc=0 now want o="" l a=""
  [ "$PLAN_OK" -eq 1 ] || return 0
  derive "$component" || rc=$?
  if [ "$rc" -ne 0 ]; then
    refuse "the host couldn't be read again: $D_WHY"
    return 0
  fi
  signature SIG_NOW
  now=$(printf '%s' "$SIG_NOW" | sort)
  want=$(printf '%s' "$PLAN_SIG" | sort)
  if [ "$now" != "$want" ]; then
    while IFS= read -r l; do
      [ -n "$l" ] || continue
      jpushs a "$l"
    done < <(diff <(printf '%s\n' "$want") <(printf '%s\n' "$now") | sed -n 's/^\([<>]\) /\1 /p')
    jadd o differs "[$a]"
    refuse "the host no longer matches the plan (< the plan, > the host now): take a fresh plan, and approve that"
  fi
  case $stage in
    remove | purge)
      [ -z "$D_INST" ] || refuse "apt would install $D_INST to take $component away: no stage runs a removal that installs"
      [ -z "$D_HELD" ] || refuse "apt-mark holds $D_HELD, and apt-get -y won't remove a held package. A hold is its owner's: release it with apt-mark unhold $D_HELD first, if that's the owner's call" ;;
  esac
  jaddb o matches "$([ "$now" = "$want" ] && echo 1 || echo 0)"
  jadd J_GATE drift "{$o}"
}

# A purge deletes data only where the owner names it. A package's own purge
# script runs too, so where one deletes a data path, --purge-data must name
# that path: postgresql-16's drops every cluster whatever debconf says
# (_prune-lib.sh), and nginx-common's takes /var/log/nginx.
gate_purge_scripts() {
  local l i p n="" seen=""
  if [ "$stage" != purge ] || [ "$PLAN_OK" -ne 1 ]; then return 0; fi
  for l in ${D_PURGE[@]+"${D_PURGE[@]}"}; do n="$n ${l%% *}"; done
  # A word list, each a package name.
  # shellcheck disable=SC2086
  purge_deletes $n
  for i in ${PD_PKG[@]+"${!PD_PKG[@]}"}; do
    for p in $D_DATA; do
      case ${PD_TEXT[$i]} in *"$p"*) ;; *) continue ;; esac
      in_words "$p" "${purge_data[*]-}" && continue
      in_words "${PD_PKG[$i]}:$p" "$seen" && continue
      seen="$seen ${PD_PKG[$i]}:$p"
      refuse "${PD_PKG[$i]}'s purge script deletes $p (postrm line ${PD_LINE[$i]}: ${PD_TEXT[$i]}): pass --purge-data $p to approve that, or leave $component removed rather than purged"
    done
  done
}

emit() {
  local o="" a="" r
  jadds a component "$component"
  jadds a stage "$stage"
  jadds a plan "$plan"
  jadds a run "$run"
  jaddb a approved "$approve"
  jadds a host "$host"
  jadds a knob "$config"
  jadd o prune "{$a}"
  a=""
  for r in ${REFUSED[@]+"${REFUSED[@]}"}; do jpushs a "$r"; done
  jadd o refused "[$a]"
  jadd o gate "{$J_GATE}"
  a=""
  for r in ${ACT[@]+"${ACT[@]}"}; do jpushs a "$r"; done
  jadd o actions "[$a]"
  jadd o "done" "$J_DONE"
  jadd o verdict "$J_VERDICT"
  a=""
  for r in ${NEXT[@]+"${NEXT[@]}"}; do jpushs a "$r"; done
  jadd o next "[$a]"
  printf '{%s}\n' "$o"
}

gate_host
gate_plan
gate_calendar
gate_packages
gate_drift
gate_purge_scripts

# --- the actions ------------------------------------------------------------------
# Each one a command line, printed before anything runs: the text the owner
# approves is the text that runs, and nothing outside it does.
ACT=()
APT_ENV="env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l"
APT_OPT="-y -o APT::Get::AutomaticRemove=false"
names_of() {  # <var> <sig kind>: the plan's packages of that kind, space-separated
  local _no_l _no_k _no_n _no_s=""
  while read -r _no_k _no_n; do
    [ "$_no_k" = "$2" ] && _no_s="$_no_s $_no_n"
  done <<<"$PLAN_SIG"
  printf -v "$1" '%s' "${_no_s# }"
}
MASKS_SKIPPED="" _units="" _pk="" TAR_ACT=""
if [ "$PLAN_OK" -eq 1 ]; then
  _members=""
  while read -r _k _g _m; do
    if [ "$_k" = member ]; then _members="$_members $_m"; fi
  done <<<"$PLAN_SIG"
  case $stage in
    disable)
      # One systemctl call each, so systemd orders the stops itself: dockerd
      # before the containerd it runs on, whatever order apt lists them in.
      names_of _units unit
      _masks=""
      for _u in $_units; do
        # A unit file under /etc can't be masked: the mask is that very path.
        unit_show "$_u" FragmentPath || true
        case $U_FragmentPath in
          /etc/systemd/system/*) MASKS_SKIPPED="$MASKS_SKIPPED $_u" ;;
          *) _masks="$_masks $_u" ;;
        esac
      done
      if [ -n "$_units" ]; then
        ACT+=("systemctl stop -- $_units" "systemctl disable -- $_units")
        [ -z "$_masks" ] || ACT+=("systemctl mask --${_masks}")
      fi ;;
    savepoint)
      # An earlier attempt's record goes first: a tar that fails now must
      # leave no record vouching for its tarball.
      ACT+=("mkdir -p -m 700 $run" "rm -f -- $run/savepoint")
      _files="$PLAN_CONFIG $PLAN_CONFFILES"
      _files=${_files# }
      _files=${_files% }
      TAR_ACT="tar -cf $run/config.tar ${_files:---files-from /dev/null}"
      ACT+=("$TAR_ACT")
      ACT+=("write $run/versions")
      ACT+=("write $run/savepoint") ;;
    remove)
      names_of _pk remove
      [ -z "$_pk" ] || ACT+=("$APT_ENV apt-get remove $APT_OPT $_pk")
      for _m in $_members; do ACT+=("gpasswd -d $_m $PLAN_GROUP"); done ;;
    purge)
      names_of _pk purge
      [ -z "$_pk" ] || ACT+=("$APT_ENV apt-get purge $APT_OPT $_pk")
      for _m in $_members; do ACT+=("gpasswd -d $_m $PLAN_GROUP"); done
      [ -z "$PLAN_GROUP" ] || ACT+=("groupdel $PLAN_GROUP")
      for _p in ${purge_data[@]+"${purge_data[@]}"}; do ACT+=("rm -rf $_p"); done ;;
  esac
fi

if [ "${#REFUSED[@]}" -gt 0 ]; then
  for _r in "${REFUSED[@]}"; do echo "prune: refused: $_r" >&2; done
  emit
  exit 3
fi

# --- the stage --------------------------------------------------------------------
# From here on the host changes. Each command's output goes to the run's
# <stage>.log, root's only.
log=$run/$stage.log
if ! root_has "$run" && ! as_root mkdir -p -m 700 -- "$run"; then
  fail "$run couldn't be made"
fi
BEFORE_INSTALLED=""
for _i in ${PKG_NAME[@]+"${!PKG_NAME[@]}"}; do
  case ${PKG_STATE[$_i]} in ii | hi) BEFORE_INSTALLED="$BEFORE_INSTALLED ${PKG_NAME[$_i]}" ;; esac
done

# The script runs as root, in sh: its expansions are its own.
# shellcheck disable=SC2016
run_act() {  # <action>: runs it as root, its output to the log; sets RC
  local _ra=$1 _ra_o=$P_TMP/act.out
  local -a _ra_w=()
  read -r -a _ra_w <<<"$_ra"
  RC=0
  # Each one's output, stdout and stderr in the order written, goes to the
  # log under its command line: a failure points there.
  case $_ra in
    'mkdir '*) return 0 ;;
    'tar -cf '*)
      as_root sh -c 'umask 077; f=$1; shift; exec tar -cf "$f" "$@"' sh "${_ra_w[2]}" "${_ra_w[@]:3}" >"$_ra_o" 2>&1 || RC=$? ;;
    "write $run/versions")
      printf '%s' "$PLAN_VERSIONS" | root_write "$run/versions" >"$_ra_o" 2>&1 || RC=$? ;;
    "write $run/savepoint")
      printf 'component %s\nhost %s\ntaken %s\nconfig.tar %s\n' "$component" "$host" "$P_NOW" "$SP_SHA" |
        root_write "$run/savepoint" >"$_ra_o" 2>&1 || RC=$? ;;
    *) as_root "${_ra_w[@]}" >"$_ra_o" 2>&1 || RC=$? ;;
  esac
  { printf '$ %s\n' "$_ra"; cat "$_ra_o"; } | root_append "$log" || true
}

SP_SHA="" _done="" RC=0
for _act in ${ACT[@]+"${ACT[@]}"}; do
  [ "${#FAILED[@]}" -eq 0 ] || [ "$stage" = disable ] || break
  RC=0
  run_act "$_act"
  if [ "$_act" = "$TAR_ACT" ] && [ "$RC" -eq 0 ]; then
    capture SP_SHA as_root sha256sum "$run/config.tar"
    SP_SHA=${SP_SHA%% *}
    # No record vouches for a tarball whose sha256 couldn't be read.
    if [ "$CAP_RC" -ne 0 ] || [[ ! $SP_SHA =~ ^[0-9a-f]{64}$ ]]; then
      fail "sha256sum couldn't read $run/config.tar (${CAP_ERR:-exit $CAP_RC}), so no savepoint record is written"
    fi
  fi
  _e=""
  jadds _e action "$_act"
  jaddn _e exit "$RC"
  jpush _done "{$_e}"
  [ "$RC" -eq 0 ] || fail "$_act exited $RC: its output is in $log"
done
J_DONE="[$_done]"

# What the stage left, read again.
_o=""
case $stage in
  disable)
    for _u in ${D_UNITS[@]+"${D_UNITS[@]}"}; do
      _st=$(systemctl is-enabled -- "$_u" 2>/dev/null) || true
      _ac=$(systemctl is-active -- "$_u" 2>/dev/null) || true
      if [ "$_ac" = active ] || [ "$_ac" = activating ]; then fail "$_u is still $_ac"; fi
      if ! in_words "$_u" "$MASKS_SKIPPED" && [ "$_st" != masked ]; then fail "$_u is $_st, not masked"; fi
    done ;;
  remove | purge)
    if read_packages; then
      names_of _pk "$stage"
      _now=""
      for _i in ${PKG_NAME[@]+"${!PKG_NAME[@]}"}; do
        _n=${PKG_NAME[$_i]} _s=${PKG_STATE[$_i]}
        case $_s in ii | hi) _now="$_now $_n" ;; esac
        if in_words "$_n" "$_pk"; then
          case $stage:$_s in
            remove:ii | remove:hi | purge:ii | purge:hi | purge:rc) fail "$_n is still $_s after the $stage" ;;
          esac
        fi
      done
      # Every package installed before that the plan doesn't name, still
      # installed: one apt took entirely is gone from the list, not changed.
      for _n in $BEFORE_INSTALLED; do
        in_words "$_n" "$_pk" && continue
        in_words "$_n" "$_now" || fail "apt took $_n, which the plan doesn't name"
      done
    else
      fail "dpkg-query couldn't be read after the $stage"
    fi ;;
esac

_a=""
for _r in ${FAILED[@]+"${FAILED[@]}"}; do jpushs _a "$_r"; done
if [ "${#FAILED[@]}" -eq 0 ]; then jaddb _o ok 1; else jaddb _o ok 0; fi
jadd _o why "[$_a]"
J_VERDICT="{$_o}"

day_after() {  # <var> <days>: the date that many days from now
  local _da=""
  iso_utc _da "$((P_NOW + $2 * 86400))"
  printf -v "$1" '%s' "${_da%%T*}"
}
if [ "${#FAILED[@]}" -gt 0 ]; then
  NEXT+=("The stage didn't finish: read $log and the failures above before anything else. A disable is undone with systemctl unmask, then enable --now.")
else
  case $stage in
    disable)
      day_after _d 30
      NEXT+=("Declare it in the knob: exception disabled:$component $_d <reason>. The remove waits for that date, as does a purge after a savepoint.")
      [ -z "$MASKS_SKIPPED" ] || NEXT+=("Not masked, since its unit file is under /etc/systemd/system:$MASKS_SKIPPED. It's stopped and disabled.")
      NEXT+=("To undo it: systemctl unmask, then systemctl enable --now, for each unit under actions.") ;;
    savepoint)
      [ -z "$PLAN_DATA" ] || NEXT+=("The savepoint holds no data: dump $PLAN_DATA off the node yourself, with a stated retention, before the purge.")
      for _p in ${D_UNSAVED[@]+"${D_UNSAVED[@]}"}; do NEXT+=("The conffile $_p isn't in it: a path with whitespace can't be one word of the tar, so save it by hand."); done
      NEXT+=("The purge may follow the disable's soak: bash \"$_libdir/prune.sh\" --stage purge --savepoint $run --plan <a fresh plan>.") ;;
    remove)
      day_after _d 30
      NEXT+=("Replace the knob's disabled:$component line with: exception removed:$component $_d <reason>. The purge waits for that date.") ;;
    purge)
      day_after _d 90
      NEXT+=("Replace the knob's line with: exception purged:$component $_d <reason>. It stays until the base image stops shipping $component.")
      for _p in $PLAN_DATA $PLAN_CONFIG; do
        in_words "$_p" "${purge_data[*]-}" && continue
        path_kib _k "$_p"
        [ -z "$_k" ] || NEXT+=("$_p is still there ($_k KiB): delete it with --purge-data $_p, or keep it.")
      done ;;
  esac
fi
emit
[ "${#FAILED[@]}" -eq 0 ] || exit 1
exit 0
