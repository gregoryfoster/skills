#!/usr/bin/env bash
# prune-plan.sh — what pruning one dormant component would take, read from
# the host. Read-only: --out writes the plan prune.sh acts on, and nothing
# else is written.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash prune-plan.sh --component NAME [--out FILE] [--config FILE]
                          [--host NAME] [--today YYYY-MM-DD]

For one component the probe knows, prints what pruning it would take
(references/pruning.md), and changes nothing:
  - the units, sockets and timers its packages ship, with each one's state
    now: what the disable stage stops, disables and masks;
  - the packages apt-get -s remove and apt-get -s purge would take, with
    what each drags along, and any held;
  - what a later autoremove would take that it doesn't take now;
  - what else installed depends on them;
  - the lines in their purge scripts that delete files, and their debconf
    answers;
  - its config and data paths, with their sizes, and its packages'
    conffiles outside its config, which a purge deletes too;
  - its group, and the group's members;
  - its residue: its packages removed with their config left (rc);
  - the stage the knob declares, and the next one.

--out FILE writes the plan prune.sh acts on: the exact packages, units and
members. A stage refuses when the host no longer matches it, so an approval
binds to exactly what it names.

Options:
  --component NAME   docker, postgres, redis, nginx, ollama or qdrant
  --out FILE         write the plan here (a new file, mode 600)
  --config FILE      the knob (default: .skills/patching-hosts at the repo
                     root, or in the current directory)
  --host NAME        whose knob sections apply (default: `hostname`)
  --today DATE       the date exceptions expire against (default: today, UTC)
  -h, --help         show this help

Output: one JSON object on stdout. Keys: prune_plan, units, packages,
reverse_depends, autoremove_would_take, purge_scripts, debconf, paths,
conffiles, group, residue, stage, plan_file, not_read.

Exit codes:
  0  the plan is printed, and written with --out
  1  apt or dpkg couldn't be read, or --out couldn't be written
  2  usage error, an unreadable knob, or a library missing
USAGE
}

component="" out="" config="" host="" today=""
while [ "$#" -gt 0 ]; do
  case $1 in
    --component | --out | --config | --host | --today)
      [ "$#" -ge 2 ] || { echo "ERROR $1 needs a value" >&2; exit 2; }
      case $1 in
        --component) component=$2 ;;
        --out) out=$2 ;;
        --config) config=$2 ;;
        --host) host=$2 ;;
        --today) today=$2 ;;
      esac
      shift 2 ;;
    -h | --help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1 (see --help)" >&2; exit 2 ;;
  esac
done

if [ -z "$component" ]; then
  echo "ERROR --component is required: docker, postgres, redis, nginx, ollama or qdrant" >&2
  exit 2
fi
case $out$config in *[[:cntrl:]]*)
  echo "ERROR an argument holds a control character" >&2
  exit 2 ;;
esac
if [ -n "$out" ] && [ -e "$out" ]; then
  echo "ERROR --out $out exists: a plan is written to a new file" >&2
  exit 2
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
ME=prune-plan
# shellcheck source=_gate-lib.sh
. "$_libdir/_gate-lib.sh"
# shellcheck source=_prune-lib.sh
. "$_libdir/_prune-lib.sh"

if ! prune_component "$component"; then
  echo "ERROR --component takes one the probe knows: $PRUNE_COMPONENTS" >&2
  exit 2
fi

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
# It reads the running system, never a tree.
P_LIVE=1
# unit_show sets these by name.
U_ActiveState="" U_UnitFileState="" U_FragmentPath=""

NOT_READ=""
not_read() { jpushs NOT_READ "$1"; }

_rc=0
derive "$component" || _rc=$?
if [ "$_rc" -ne 0 ]; then
  echo "prune-plan: $D_WHY" >&2
  printf '{"prune_plan": {"component": "%s", "host": "%s"}, "error": ' "$component" "$host"
  _e=""
  jpushs _e "$D_WHY"
  printf '[%s]}\n' "$_e"
  exit 1
fi

# --- what it prints -----------------------------------------------------------
J="" _x="" _y="" _n=0
_o=""
jadds _o component "$component"
jadds _o host "$host"
jadds _o knob "$config"
jaddb _o installed "$D_PRESENT"
jaddb _o from_apt "$((1 - D_UNPACKAGED))"
if [ "$D_UNPACKAGED" -eq 1 ]; then
  jadds _o binary "$C_BINARY"
  not_read "$component comes from outside apt: prune.sh disables it, and removing it is by hand (pruning.md)"
fi
if [ -n "$D_INST" ]; then
  jadds _o warning "apt would install $D_INST to take it away: no stage runs a removal that installs"
fi
jadd J prune_plan "{$_o}"

# Each unit and its state now: what the disable stage stops, disables and
# masks, and what undoing it starts again.
_a=""
for _u in ${D_UNITS[@]+"${D_UNITS[@]}"}; do
  _e=""
  unit_show "$_u" ActiveState UnitFileState FragmentPath || true
  jadds _e unit "$_u"
  jaddsn _e active "$U_ActiveState"
  jaddsn _e enabled "$U_UnitFileState"
  jaddsn _e file "$U_FragmentPath"
  jpush _a "{$_e}"
done
jadd J units "[$_a]"

pkg_list() {  # <var> <"package version">...: a JSON array of {package, version}
  local _pl_v=$1 _pl_a="" _pl_e _pl_x
  shift
  for _pl_x in "$@"; do
    _pl_e=""
    jadds _pl_e package "${_pl_x%% *}"
    jadds _pl_e version "${_pl_x#* }"
    jpush _pl_a "{$_pl_e}"
  done
  printf -v "$_pl_v" '[%s]' "$_pl_a"
}
_o=""
json_words _x "$D_ROOTS"
jadd _o roots "$_x"
pkg_list _x ${D_REMOVE[@]+"${D_REMOVE[@]}"}
jadd _o remove "$_x"
pkg_list _x ${D_PURGE[@]+"${D_PURGE[@]}"}
jadd _o purge "$_x"
_drag=""
for _p in ${D_PURGE[@]+"${D_PURGE[@]}"}; do
  in_words "${_p%% *}" "$D_ROOTS $D_RESIDUE" || _drag="$_drag ${_p%% *}"
done
json_words _x "$_drag"
jadd _o dragged_along "$_x"
json_words _x "$D_HELD"
jadd _o held "$_x"
jadd J packages "{$_o}"

# What else installed depends on them and stays: apt drags along what must
# go, and lists here what only recommends or suggests them.
_a=""
_names=""
for _p in ${D_PURGE[@]+"${D_PURGE[@]}"}; do _names="$_names ${_p%% *}"; done
for _p in $D_ROOTS; do
  capture _x apt-cache rdepends --installed "$_p"
  [ "$CAP_RC" -eq 0 ] || continue
  while read -r _l; do
    case $_l in '' | "$_p" | 'Reverse Depends:') continue ;; esac
    _l=${_l#|}
    in_words "$_l" "$_names" && continue
    _e=""
    jadds _e package "$_l"
    jadds _e depends_on "$_p"
    case " $_a " in *"{$_e}"*) ;; *) jpush _a "{$_e}" ;; esac
  done <<<"$_x"
done
jadd J reverse_depends "[$_a]"

# What a later autoremove would take that it doesn't take now: what apt
# installed for these packages alone. No stage autoremoves, but anyone's apt
# autoremove does, as does unattended-upgrades' Remove-Unused-Dependencies.
# apt's "no longer required" list holds what autoremove takes already, so
# that's taken off.
capture _x apt-get -s autoremove
if [ "$CAP_RC" -eq 0 ]; then
  _now=""
  while read -r _l _p _y; do
    if [ "$_l" = Remv ]; then _now="$_now $_p"; fi
  done <<<"$_x"
  _y=""
  for _p in $D_ORPHANS; do in_words "$_p" "$_now" || _y="$_y $_p"; done
  json_words _x "$_y"
  jadd J autoremove_would_take "$_x"
else
  not_read "what a later autoremove would take: apt-get -s autoremove failed (${CAP_ERR:-exit $CAP_RC})"
  jadd J autoremove_would_take null
fi

# The lines in their purge scripts that delete: nginx-common's takes
# /etc/nginx and /var/log/nginx with it, docker.io's leaves /var/lib/docker,
# and postgresql-16's drops every cluster. A purge refuses until
# --purge-data names each data path one of them deletes.
_a=""
# A word list, each a package name.
# shellcheck disable=SC2086
purge_deletes $_names
for _i in ${PD_PKG[@]+"${!PD_PKG[@]}"}; do
  _e=""
  jadds _e package "${PD_PKG[$_i]}"
  jaddn _e line "${PD_LINE[$_i]}"
  jadds _e text "${PD_TEXT[$_i]}"
  jpush _a "{$_e}"
done
jadd J purge_scripts "[$_a]"

# debconf's answers, which a purge forgets.
_a=""
if [ "$P_PRIV" = none ]; then
  not_read "debconf's answers: debconf-show needs root"
elif [ -n "$_names" ]; then
  # A word list, each a package name.
  # shellcheck disable=SC2086
  capture _x as_root debconf-show $_names
  while IFS= read -r _l; do
    [ -n "$_l" ] || continue
    words_of _y "${_l#\*}"
    jpushs _a "$_y"
  done <<<"$_x"
fi
jadd J debconf "[$_a]"

# Each path that exists, and its size.
_a=""
[ "$P_PRIV" != none ] || not_read "the sizes of its paths: du needs root"
while read -r _p _k; do
  [ -n "$_p" ] || continue
  _e=""
  if in_words "$_p" "$D_CONFIG"; then
    jadds _e kind config
  elif in_words "$_p" "$D_DATA"; then
    jadds _e kind data
  else
    jadds _e kind binary
  fi
  jadds _e path "$_p"
  jaddn _e kib "$_k"
  jpush _a "{$_e}"
done <<<"$D_SIZES"
jadd J paths "[$_a]"

# Its packages' conffiles outside its config: a purge deletes them too, and
# the savepoint keeps them.
json_words _x "$D_CONFFILES"
jadd J conffiles "$_x"
for _p in ${D_UNSAVED[@]+"${D_UNSAVED[@]}"}; do
  not_read "the conffile $_p: a path with whitespace can't be one word of the savepoint's tar, so save it by hand"
done

_o=""
jaddsn _o name "$C_GROUP"
jaddb _o exists "$D_GROUP_EXISTS"
json_words _x "$D_MEMBERS"
jadd _o members "$_x"
jadd J group "{$_o}"
json_words _x "$D_RESIDUE"
jadd J residue "$_x"

# The stage the knob declares, and what comes next (policy.md).
calendar "$component"
_o=""
jadds _o declared "$CAL_STAGE"
jaddsn _o review_by "$CAL_REVIEW"
jaddn _o knob_line "$CAL_LINE"
case $CAL_STAGE:$CAL_PASSED in
  none:*) _next=disable _why="nothing is declared: disable comes first" ;;
  keep:*) _next="" _why="the owner keeps it until $CAL_REVIEW" ;;
  disabled:0) _next=savepoint _why="disabled, soaking until $CAL_REVIEW: a savepoint now lets the purge skip the remove stage" ;;
  disabled:1) _next="remove, or savepoint then purge" _why="disabled, and its soak ended $CAL_REVIEW" ;;
  removed:0) _next="" _why="removed, soaking until $CAL_REVIEW" ;;
  removed:1) _next=purge _why="removed, and its soak ended $CAL_REVIEW" ;;
  purged:*) _next="" _why="purged: the line stays until the base image stops shipping it" ;;
esac
if [ "$D_PRESENT" -eq 0 ] && [ "$CAL_STAGE" != purged ]; then _next="" _why="it isn't installed"; fi
jaddsn _o next "$_next"
jadds _o why "$_why"
jadd J stage "{$_o}"

if [ -n "$out" ]; then
  # Mode 600 from creation, in the operator's own directory.
  if ( umask 077 && write_plan "$host" "$component" >"$out" ); then
    jadds J plan_file "$out"
  else
    echo "prune-plan: $out couldn't be written" >&2
    jadd J plan_file null
    jadd J not_read "[$NOT_READ]"
    printf '{%s}\n' "$J"
    exit 1
  fi
else
  jadd J plan_file null
fi
jadd J not_read "[$NOT_READ]"
printf '{%s}\n' "$J"
