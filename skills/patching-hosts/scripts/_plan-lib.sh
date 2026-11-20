#!/usr/bin/env bash
# _plan-lib.sh — read a fleet executor's plan file (references/executor.md).
#
# Sourced by apply.sh, recovery-point.sh and reboot-chain.sh, after
# _knob-lib.sh, _probe-lib.sh and _gate-lib.sh, whose trim, day arithmetic,
# capture and refuse it uses. A plan is an owner's approval given off the
# host: the skill can't verify that, so it reads what the file states,
# hashes the file itself, and holds each step to it. Nothing here guesses: a
# line that doesn't parse makes the whole plan malformed (#673).
# The PLAN_* variables are its output.
# shellcheck disable=SC2034
set -euo pipefail

plan_lib_usage() {
  cat <<'USAGE'
Usage: . _plan-lib.sh    (sourced by apply.sh, recovery-point.sh and
                         reboot-chain.sh; running it does nothing)

The grammar is the knob's: one directive a line, '#' a comment at the start
of a line or after whitespace, and [host <name>] sections, each an exact
name.

  plan <id>                                 once, before any section
  approved <YYYY-MM-DDTHH:MM:SSZ> <by...>   once, before any section
  not-after <YYYY-MM-DDTHH:MM:SSZ>          once, before any section
  [host <name>]
  lane security|maintenance|origin:<origin> once a section
  reboot yes|no                             once a section
  package <name> <version> <class>          class: security, updates, esm,
                                            ubuntu-other or
                                            third-party:<origin>
  held <step>                               each held step it approves

  plan_load FILE HOST       read FILE for HOST: 1 with PLAN_WHY when it
                            can't be read or doesn't parse
  plan_gate APPROVE FILE HOST  plan_load, then the host and its not-after;
                            refuses only under --approve
  plan_gate_record APPROVE FILE HOST REBOOT  gate.plan for recovery-point.sh
                            and reboot-chain.sh
  plan_approval VAR APPROVE FILE STANDING  the step's approval record
  approval_args VAR FILE STANDING  the --plan or --standing a next command
                            carries
  standing_for LANE         the knob's standing line for LANE into ST_*: 1
                            with ST_WHY when none approves
  standing_any              the same, for any lane: the security lane's first
  run_lane VAR RUN          the lane the run's bulk ran in, from its dry-run
                            record: 1 when it can't be read
  standing_gate_record APPROVE STANDING RUN-OR-EMPTY REBOOT  gate.standing
                            for recovery-point.sh and reboot-chain.sh
USAGE
}

case "${0##*/}" in
  _plan-lib.sh) case "${1-}" in -h | --help) plan_lib_usage; exit 0 ;; esac ;;
esac

PLAN_ID="" PLAN_APPROVED_AT="" PLAN_APPROVED_BY="" PLAN_NOT_AFTER="" PLAN_NOT_AFTER_S=""
PLAN_SHA="" PLAN_WHY="" PLAN_COVERS=0
PLAN_LANE="" PLAN_REBOOT="" PLAN_HELD="" PLAN_ORIGINS=""
PLAN_PKG_NAME=() PLAN_PKG_VERSION=() PLAN_PKG_CLASS=()

# <var> <YYYY-MM-DDTHH:MM:SSZ>: VAR := its seconds since 1970, or empty.
plan_epoch() {
  local _pe_d _pe_day _pe_h _pe_m _pe_s
  local _pe_re='^([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z$'
  printf -v "$1" '%s' ""
  [[ $2 =~ $_pe_re ]] || return 0
  # Taken before _knob_is_day, whose own match replaces BASH_REMATCH.
  _pe_day=${BASH_REMATCH[1]} _pe_h=$((10#${BASH_REMATCH[2]}))
  _pe_m=$((10#${BASH_REMATCH[3]})) _pe_s=$((10#${BASH_REMATCH[4]}))
  _knob_is_day "$_pe_day" || return 0
  if [ "$_pe_h" -gt 23 ] || [ "$_pe_m" -gt 59 ] || [ "$_pe_s" -gt 59 ]; then return 0; fi
  knob_epoch_day _pe_d "$_pe_day"
  printf -v "$1" '%s' $((_pe_d * 86400 + _pe_h * 3600 + _pe_m * 60 + _pe_s))
}

# A plan an executor wrote may be root's alone: read it as the caller, then
# as root.
plan_read() {  # <var> <cmd>...
  local _pr_v=$1
  shift
  capture "$_pr_v" "$@"
  if [ "$CAP_RC" -ne 0 ] && [ "$P_PRIV" != none ]; then capture "$_pr_v" as_root "$@"; fi
}

# The file's SHA-256: the skill's own, whatever the plan or its executor says.
plan_sha() {  # <var> <file>
  local _ps_o=""
  printf -v "$1" '%s' ""
  if have sha256sum; then
    plan_read _ps_o sha256sum -- "$2"
  elif have shasum; then
    plan_read _ps_o shasum -a 256 -- "$2"
  else
    return 0
  fi
  [ "$CAP_RC" -eq 0 ] || return 0
  _ps_o=${_ps_o%% *}
  [[ $_ps_o =~ ^[0-9a-f]{64}$ ]] || return 0
  printf -v "$1" '%s' "$_ps_o"
}

# Reads FILE for HOST. 0 with the plan read, PLAN_COVERS 1 when it has a
# section for HOST; 1 with PLAN_WHY when it can't be read, or doesn't parse.
plan_load() {  # <file> <host>
  local f=$1 h=$2 text line s n=0 sec="" seen_secs=" " d nt mine=0 hre copy
  local mine_lane="" mine_reboot="" seen_lane="" seen_reboot="" seen_pkgs=" "
  local id_re='^[A-Za-z0-9][A-Za-z0-9._:-]*$' step_re='^[a-z0-9][a-z0-9-]*$'
  local class_re='^(security|updates|esm|ubuntu-other|third-party:[^[:space:]]+)$'
  local -a tok=()
  hre='^\[host[[:space:]]+([^][:space:]]+)[[:space:]]*\]$'
  PLAN_ID="" PLAN_APPROVED_AT="" PLAN_APPROVED_BY="" PLAN_NOT_AFTER="" PLAN_NOT_AFTER_S=""
  PLAN_SHA="" PLAN_WHY="" PLAN_COVERS=0
  PLAN_LANE="" PLAN_REBOOT="" PLAN_HELD="" PLAN_ORIGINS=""
  PLAN_PKG_NAME=() PLAN_PKG_VERSION=() PLAN_PKG_CLASS=()
  # Read once (CR 2529): a regular file, copied whole into P_TMP, and that
  # copy is what's parsed and hashed. A pipe, /dev/stdin or a file rewritten
  # between two reads would otherwise hash one plan and run another; a NUL,
  # which bash drops from what it reads, would do the same.
  copy=$P_TMP/plan
  plan_read text test -f "$f"
  if [ "$CAP_RC" -ne 0 ]; then
    PLAN_WHY="$f isn't a regular file, or can't be read: a plan is read once, from a file"
    return 1
  fi
  if ! cat -- "$f" >"$copy" 2>/dev/null; then
    if [ "$P_PRIV" = none ] || ! as_root cat -- "$f" >"$copy" 2>/dev/null; then
      PLAN_WHY="$f couldn't be read"
      return 1
    fi
  fi
  if [ "$(wc -c <"$copy")" -ne "$(tr -d '\000' <"$copy" | wc -c)" ]; then
    PLAN_WHY="$f holds a NUL byte"
    return 1
  fi
  plan_sha PLAN_SHA "$copy"
  if [ -z "$PLAN_SHA" ]; then
    PLAN_WHY="$f couldn't be hashed: neither sha256sum nor shasum read it"
    return 1
  fi
  while IFS= read -r line || [ -n "$line" ]; do
    n=$((n + 1))
    case $line in *[[:cntrl:]]*)
      PLAN_WHY="line $n holds a control character"
      return 1 ;;
    esac
    s=" $line"
    s=${s%%[[:space:]]#*}
    _knob_trim "$s"
    s=$_KR
    [ -n "$s" ] || continue
    if [[ $s == "["* ]]; then
      if ! [[ $s =~ $hre ]] || [[ ${BASH_REMATCH[1]} == *[*?]* ]]; then
        PLAN_WHY="line $n: a section is [host <name>], an exact name"
        return 1
      fi
      sec=${BASH_REMATCH[1]}
      case $seen_secs in *" $sec "*)
        PLAN_WHY="line $n: [host $sec] appears twice"
        return 1 ;;
      esac
      seen_secs="$seen_secs$sec "
      seen_lane="" seen_reboot="" seen_pkgs=" "
      mine=0
      if [ "$sec" = "$h" ]; then mine=1 PLAN_COVERS=1; fi
      continue
    fi
    read -r -a tok <<<"$s"
    d=${tok[0]}
    nt=$((${#tok[@]} - 1))
    case $d in
      plan | approved | not-after)
        if [ -n "$sec" ]; then
          PLAN_WHY="line $n: $d belongs before any section"
          return 1
        fi ;;
      lane | reboot | package | held)
        if [ -z "$sec" ]; then
          PLAN_WHY="line $n: $d belongs in a [host <name>] section"
          return 1
        fi ;;
      *)
        PLAN_WHY="line $n: $d isn't a plan directive (plan, approved, not-after, lane, reboot, package, held)"
        return 1 ;;
    esac
    case $d in
      plan)
        if [ "$nt" -ne 1 ] || ! [[ ${tok[1]} =~ $id_re ]]; then
          PLAN_WHY="line $n: plan takes one id: letters, digits, '.', '_', ':' and '-'"
          return 1
        fi
        if [ -n "$PLAN_ID" ]; then PLAN_WHY="line $n: plan appears twice"; return 1; fi
        PLAN_ID=${tok[1]} ;;
      approved)
        if [ "$nt" -lt 2 ]; then
          PLAN_WHY="line $n: approved takes <YYYY-MM-DDTHH:MM:SSZ> <by>"
          return 1
        fi
        plan_epoch d "${tok[1]}"
        if [ -z "$d" ]; then
          PLAN_WHY="line $n: approved takes a UTC time, YYYY-MM-DDTHH:MM:SSZ"
          return 1
        fi
        if [ -n "$PLAN_APPROVED_AT" ]; then PLAN_WHY="line $n: approved appears twice"; return 1; fi
        PLAN_APPROVED_AT=${tok[1]} PLAN_APPROVED_BY=${tok[*]:2} ;;
      not-after)
        if [ "$nt" -ne 1 ]; then
          PLAN_WHY="line $n: not-after takes one UTC time, YYYY-MM-DDTHH:MM:SSZ"
          return 1
        fi
        plan_epoch d "${tok[1]}"
        if [ -z "$d" ]; then
          PLAN_WHY="line $n: not-after takes a UTC time, YYYY-MM-DDTHH:MM:SSZ"
          return 1
        fi
        if [ -n "$PLAN_NOT_AFTER" ]; then PLAN_WHY="line $n: not-after appears twice"; return 1; fi
        PLAN_NOT_AFTER=${tok[1]} PLAN_NOT_AFTER_S=$d ;;
      lane)
        if [ "$nt" -ne 1 ] || ! [[ ${tok[1]} =~ ^(security|maintenance|origin:[^[:space:]]+)$ ]]; then
          PLAN_WHY="line $n: lane takes security, maintenance or origin:<origin>"
          return 1
        fi
        if [ -n "$seen_lane" ]; then PLAN_WHY="line $n: [host $sec] names its lane twice"; return 1; fi
        seen_lane=${tok[1]}
        if [ "$mine" -eq 1 ]; then mine_lane=${tok[1]}; fi ;;
      reboot)
        if [ "$nt" -ne 1 ] || ! [[ ${tok[1]} =~ ^(yes|no)$ ]]; then
          PLAN_WHY="line $n: reboot takes yes or no"
          return 1
        fi
        if [ -n "$seen_reboot" ]; then PLAN_WHY="line $n: [host $sec] names its reboot twice"; return 1; fi
        seen_reboot=${tok[1]}
        if [ "$mine" -eq 1 ]; then mine_reboot=${tok[1]}; fi ;;
      package)
        if [ "$nt" -ne 3 ] || ! [[ ${tok[3]} =~ $class_re ]]; then
          PLAN_WHY="line $n: package takes <name> <version> <class>, the class one of security, updates, esm, ubuntu-other or third-party:<origin>"
          return 1
        fi
        # One line a package (CR 2536): a second, at any version, would
        # stand beside the first.
        case $seen_pkgs in *" ${tok[1]} "*)
          PLAN_WHY="line $n: package ${tok[1]} appears twice in [host $sec]"
          return 1 ;;
        esac
        seen_pkgs="$seen_pkgs${tok[1]} "
        if [ "$mine" -eq 1 ]; then
          PLAN_PKG_NAME+=("${tok[1]}") PLAN_PKG_VERSION+=("${tok[2]}") PLAN_PKG_CLASS+=("${tok[3]}")
          case ${tok[3]} in third-party:*)
            in_words "${tok[3]#third-party:}" "$PLAN_ORIGINS" || PLAN_ORIGINS="$PLAN_ORIGINS ${tok[3]#third-party:}" ;;
          esac
        fi ;;
      held)
        if [ "$nt" -ne 1 ] || ! [[ ${tok[1]} =~ $step_re ]]; then
          PLAN_WHY="line $n: held takes one step's name"
          return 1
        fi
        if [ "$mine" -eq 1 ]; then PLAN_HELD="$PLAN_HELD ${tok[1]}"; fi ;;
    esac
    # A section's lane and reboot are checked once the next one starts, or
    # the file ends: below.
    if [ "$mine" -eq 1 ]; then PLAN_LANE=$mine_lane PLAN_REBOOT=$mine_reboot; fi
  done <"$copy"
  if [ -z "$PLAN_ID" ] || [ -z "$PLAN_APPROVED_AT" ] || [ -z "$PLAN_NOT_AFTER" ]; then
    PLAN_WHY="a plan needs its plan, approved and not-after lines, before any section"
    return 1
  fi
  if [ "$PLAN_COVERS" -eq 1 ] && { [ -z "$PLAN_LANE" ] || [ -z "$PLAN_REBOOT" ]; }; then
    PLAN_WHY="[host $h] needs a lane line and a reboot line"
    return 1
  fi
  PLAN_HELD=${PLAN_HELD# } PLAN_ORIGINS=${PLAN_ORIGINS# }
  return 0
}

# The approval a step records: the plan's, as it states it, the knob's
# standing line, or the session's. null without --approve.
plan_approval() {  # <var> <approve 0|1> <plan file, or empty> <standing 0|1>
  local _pa=""
  if [ "$2" -ne 1 ]; then
    printf -v "$1" '%s' null
    return 0
  fi
  if [ "${4:-0}" -eq 1 ]; then
    jadds _pa by standing
    jaddsn _pa lane "$ST_LANE"
    jaddsn _pa review_by "$ST_REVIEW"
    jaddsn _pa reason "$ST_REASON"
    jaddn _pa line "$ST_LINE"
  elif [ -z "$3" ]; then
    jadds _pa by session
  else
    jadds _pa by plan
    jaddsn _pa plan "$PLAN_ID"
    jaddsn _pa sha256 "$PLAN_SHA"
    jaddsn _pa approved_at "$PLAN_APPROVED_AT"
    jaddsn _pa approved_by "$PLAN_APPROVED_BY"
  fi
  printf -v "$1" '{%s}' "$_pa"
}

# What every script checks of a plan: that it parses, covers HOST, and
# hasn't passed its not-after. Refusals go through refuse only under
# --approve: without it, the step is refused anyway, and gate.plan says
# what the plan would decide. Returns 1 when the plan doesn't stand.
plan_gate() {  # <approve 0|1> <file> <host>
  local why=""
  if ! plan_load "$2" "$3"; then
    why="the plan is malformed: $PLAN_WHY"
  elif [ "$PLAN_COVERS" -ne 1 ]; then
    why="the plan $PLAN_ID has no [host $3] section, so it doesn't cover this host"
  elif ! is_int "${P_NOW:-}"; then
    # Fail closed (CR 2539): a clock that can't be read can't say the plan
    # still stands.
    why="the host's clock can't be read, so whether the plan $PLAN_ID passed its not-after is unknown"
  elif [ "$P_NOW" -gt "$PLAN_NOT_AFTER_S" ]; then
    why="the plan $PLAN_ID passed its not-after, $PLAN_NOT_AFTER"
  fi
  PLAN_WHY=$why
  [ -n "$why" ] || return 0
  if [ "$1" -eq 1 ]; then refuse "$why"; fi
  return 1
}

# gate.plan's opening keys, shared by the three scripts.
plan_json_head() {  # <var> <file>
  local _pj=""
  jadds _pj file "$2"
  jaddsn _pj id "$PLAN_ID"
  jaddsn _pj sha256 "$PLAN_SHA"
  jaddsn _pj not_after "$PLAN_NOT_AFTER"
  jaddsn _pj lane "$PLAN_LANE"
  jaddsn _pj reboot "$PLAN_REBOOT"
  printf -v "$1" '%s' "$_pj"
}

# A step after the bulk, under a plan, runs only under the plan its bulk
# ran under (CR 2530): the run's approval record names it by its sha256.
plan_run_approval() {  # <run dir>: 1 with PLAN_WHY when it doesn't
  local _ra=""
  if ! root_read _ra "$1/approval"; then
    PLAN_WHY="$1/approval can't be read, so which approval the run's bulk ran under is unknown"
    return 1
  fi
  _ra=${_ra%%$'\n'*}
  case $_ra in
    "plan $PLAN_SHA "* | "plan $PLAN_SHA") return 0 ;;
  esac
  PLAN_WHY="the run's bulk ran under ${_ra:-nothing it recorded}, which isn't this plan ($PLAN_ID, sha256 $PLAN_SHA)"
  return 1
}

# recovery-point.sh's and reboot-chain.sh's gate.plan: the plan covers the
# host and hasn't passed its not-after, and for the reboot, 3(b), it says
# reboot yes, and is the plan the run's bulk ran under. The envelope is the
# bulk's: apply.sh reads it.
plan_gate_record() {  # <approve 0|1> <file, or empty> <host> <reboot 0|1> [<run dir>]
  local _po="" _pw=""
  if [ -z "$2" ]; then
    jadd J_GATE plan null
    return 0
  fi
  if ! plan_gate "$1" "$2" "$3"; then
    _pw=$PLAN_WHY
  elif [ "$4" -eq 1 ] && [ "$PLAN_REBOOT" != yes ]; then
    _pw="the plan $PLAN_ID says reboot no for this host: the reboot needs the owner's own approval"
    if [ "$1" -eq 1 ]; then refuse "$_pw"; fi
  elif [ "$4" -eq 1 ] && ! plan_run_approval "${5:-}"; then
    _pw=$PLAN_WHY
    if [ "$1" -eq 1 ]; then refuse "$_pw"; fi
  fi
  plan_json_head _po "$2"
  if [ -n "$_pw" ]; then
    jaddb _po covers 0
    jadds _po why "$_pw"
  else
    jaddb _po covers 1
    jadd _po why null
  fi
  jadd J_GATE plan "{$_po}"
}

# --- standing approval (#673 item 4) -------------------------------------------
# The owner's declaration in a committed knob: `standing <lane> [no-reboot]
# [no-datastore] [no-held] <review-by> <reason>` (knob.md). It approves only
# a step of its lane within its limits; past its review-by date, or naming an
# origin the knob doesn't follow, it approves nothing.
ST_LANE="" ST_NO_REBOOT=0 ST_NO_DS=0 ST_NO_HELD=0 ST_REVIEW="" ST_REASON="" ST_LINE="" ST_WHY=""

standing_for() {  # <lane>
  local _sf_r _sf_k _sf_o _sf_ok _sf_d
  local -a _sf_f=()
  ST_LANE="" ST_NO_REBOOT=0 ST_NO_DS=0 ST_NO_HELD=0 ST_REVIEW="" ST_REASON="" ST_LINE="" ST_WHY=""
  for _sf_r in ${KNOB_STANDING[@]+"${KNOB_STANDING[@]}"}; do
    IFS=$KNOB_US read -r -a _sf_f <<<"$_sf_r"
    [ "${_sf_f[0]}" = "$1" ] || continue
    ST_LANE=${_sf_f[0]} ST_NO_REBOOT=${_sf_f[1]} ST_NO_DS=${_sf_f[2]} ST_NO_HELD=${_sf_f[3]}
    ST_REVIEW=${_sf_f[4]} ST_REASON=${_sf_f[5]} ST_LINE=${_sf_f[7]}
    # Against the host's own clock, never --today, which is the caller's
    # (CR 2528). A clock that can't be read approves nothing.
    if ! is_int "${P_NOW:-}"; then
      ST_WHY="the host's clock can't be read, so whether standing $1 (knob line $ST_LINE) has passed its review-by date is unknown: it approves nothing"
      return 1
    fi
    knob_epoch_day _sf_d "$ST_REVIEW"
    if [ "${_sf_f[6]}" = 1 ] || [ $((P_NOW / 86400)) -gt "$_sf_d" ]; then
      ST_WHY="standing $1 (knob line $ST_LINE) passed its review-by date, $ST_REVIEW: it approves nothing until it's renewed"
      return 1
    fi
    case $1 in origin:*)
      _sf_o=${1#origin:} _sf_ok=0
      for _sf_k in ${KNOB_ORIGIN[@]+"${KNOB_ORIGIN[@]}"}; do
        case $_sf_k in "$_sf_o${KNOB_US}follow$KNOB_US"*) _sf_ok=1 ;; esac
      done
      if [ "$_sf_ok" -ne 1 ]; then
        ST_WHY="standing $1 (knob line $ST_LINE) names an origin the knob doesn't follow: it approves nothing"
        return 1
      fi ;;
    esac
    return 0
  done
  ST_WHY="the knob has no standing line for the $1 lane"
  return 1
}

# A step with no lane of its own, the recovery point: any lane's line will
# do, the security lane's first, since it changes no package.
standing_any() {
  local _sa_r
  local -a _sa_f=()
  if [ "${#KNOB_STANDING[@]}" -eq 0 ]; then
    standing_for security || true
    ST_WHY="the knob has no standing line"
    return 1
  fi
  if standing_for security; then return 0; fi
  for _sa_r in "${KNOB_STANDING[@]}"; do
    IFS=$KNOB_US read -r -a _sa_f <<<"$_sa_r"
    [ "${_sa_f[0]}" != security ] || continue
    if standing_for "${_sa_f[0]}"; then return 0; fi
  done
  ST_WHY="no standing line approves: $ST_WHY"
  return 1
}

# The lane the run's bulk ran in, from the dry-run record it wrote.
run_lane() {  # <var> <run dir>
  local _rl_o _rl_l _rl_v=""
  printf -v "$1" '%s' ""
  [ -n "$2" ] && [ "$P_PRIV" != none ] || return 1
  root_read _rl_o "$2/dry-run" || return 1
  while IFS= read -r _rl_l; do
    case $_rl_l in lane=*) _rl_v=${_rl_l#lane=} ;; esac
  done <<<"$_rl_o"
  case $_rl_v in security | maintenance | origin:?*) ;; *) return 1 ;; esac
  printf -v "$1" '%s' "$_rl_v"
}

standing_json_head() {  # <var>
  local _sj=""
  jaddsn _sj lane "$ST_LANE"
  jaddn _sj line "$ST_LINE"
  jaddsn _sj review_by "$ST_REVIEW"
  jaddb _sj no_reboot "$ST_NO_REBOOT"
  jaddb _sj no_datastore "$ST_NO_DS"
  jaddb _sj no_held "$ST_NO_HELD"
  printf -v "$1" '%s' "$_sj"
}

# recovery-point.sh's and reboot-chain.sh's gate.standing. The recovery
# point takes any lane's line; the reboot, 3(b), its run's lane's, and none
# that says no-reboot. Refusals only under --approve, as for a plan.
standing_gate_record() {  # <approve 0|1> <standing 0|1> <run dir, or empty for the recovery point> <reboot 0|1>
  local _sg="" _sw="" _sl
  if [ "$2" -ne 1 ]; then
    jadd J_GATE standing null
    return 0
  fi
  if [ "$4" -eq 1 ]; then
    if ! run_lane _sl "$3"; then
      _sw="the lane the run's bulk ran in can't be read from $3/dry-run, so which standing line applies is unknown"
    elif ! standing_for "$_sl"; then
      _sw=$ST_WHY
    elif [ "$ST_NO_REBOOT" = 1 ]; then
      _sw="the standing approval for the $_sl lane (knob line $ST_LINE) says no-reboot: the reboot needs the owner's own approval"
    fi
  elif ! standing_any; then
    _sw=$ST_WHY
  fi
  standing_json_head _sg
  if [ -n "$_sw" ]; then
    if [ "$1" -eq 1 ]; then refuse "$_sw"; fi
    jaddb _sg covers 0
    jadds _sg why "$_sw"
  else
    jaddb _sg covers 1
    jadd _sg why null
  fi
  jadd J_GATE standing "{$_sg}"
}

# The approval a suggested next command carries, as given here (CR 2535).
approval_args() {  # <var> <plan file, or empty> <standing 0|1>
  local _apa_s=""
  if [ -n "$2" ]; then _apa_s=" --plan \"$2\""; fi
  if [ "$3" -eq 1 ]; then _apa_s=" --standing"; fi
  printf -v "$1" '%s' "$_apa_s"
}

