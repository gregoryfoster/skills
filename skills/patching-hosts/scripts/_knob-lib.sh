#!/usr/bin/env bash
# _knob-lib.sh — reads .skills/patching-hosts for one host. Sourced, not run.
#
# read-knob.sh prints what this resolves as JSON. The probe and apply.sh (later
# steps of the plan) source it directly, so a knob means the same thing to every
# script that reads it. The grammar is references/knob.md.
#
# Written for bash 3.2, the macOS default the suite runs under: indexed arrays
# only, and every expansion of an array that may be empty is guarded as
# ${a[@]+"${a[@]}"}, because 3.2 calls a bare empty "${a[@]}" unbound under -u.

# The KNOB_* variables are this library's output; its callers read them.
# shellcheck disable=SC2034
set -euo pipefail

# Fields inside one record are joined by US (\037). No knob line can hold one:
# a line carrying any control character but a tab is malformed.
KNOB_US=$'\037'

# Precedence ranks: the global lines, then each matching glob section at 2 plus
# its specificity (its characters that aren't * or ?), then an exact section. A
# record that doesn't apply to this host has no rank (-1). A default hold has
# none either: it applies only when no line names its step.
KNOB_RANK_GLOBAL=1
KNOB_RANK_GLOB=2
KNOB_RANK_EXACT=100000

knob_lib_usage() {
  cat <<'USAGE'
_knob-lib.sh: the .skills/patching-hosts reader patching-hosts' scripts share

This file is a library. Source it; do not run it:

  . "<dir>/_knob-lib.sh"
  knob_load <path> <host> <today YYYY-MM-DD>
      returns 2 if <path> exists but can't be read, or the host or date
      isn't one; a <path> that doesn't exist returns 0, KNOB_PRESENT=0

Call knob_load plainly, never inside if, && or ||: bash turns errexit off for
everything a condition runs, and a failure in the library would go unseen.

Then read the KNOB_* variables knob_load sets. Records join their fields with
$KNOB_US; the field order of each array is documented at knob_reset.
USAGE
}

# Only honour --help when executed directly. When sourced, $0 and $1 belong to
# the caller, whose own --help would otherwise exit here with the wrong text.
case "${0##*/}" in
  _knob-lib.sh)
    case "${1-}" in
      -h | --help) knob_lib_usage; exit 0 ;;
    esac
    ;;
esac

# Every result variable, reset.
#
# Scalars: KNOB_PATH, KNOB_HOST, KNOB_TODAY, KNOB_PRESENT (0|1), KNOB_CLASS,
# KNOB_POSTURE, KNOB_IMAGE_OWNER and KNOB_RECORDS, each value with a *_LINE
# (empty for a default), and KNOB_REPORT_ONLY (0|1).
# Lists of plain strings: KNOB_SECTIONS (applied, least specific first) and
# KNOB_REPORT_ONLY_WHY.
#
# Field order per record:
#   KNOB_WINDOW     weekday start end wraps line
#   KNOB_QUIET      weekday-or-empty start end wraps line
#   KNOB_INFLIGHT, KNOB_HEALTH                  command line
#   KNOB_RESTARTER, KNOB_SERVICE                unit line
#   KNOB_BACKUP     unit datastore-units line (the units space-separated)
#   KNOB_CALLER     repo line
#   KNOB_DATASTORE  engine unit databases(space-separated) line; for
#                   qdrant, the third field is "container url key-file"
#                   (key-file - for none)
#   KNOB_HOLD       step globs(space-separated) line-or-empty(default)
#   KNOB_OWNER      component repo line
#   KNOB_ORIGIN     origin policy value line
#   KNOB_EXCEPTION  what review-by reason expired(0|1) line
#   KNOB_FINDING    line-or-empty kind message
knob_reset() {
  KNOB_PATH="" KNOB_HOST="" KNOB_TODAY="" KNOB_PRESENT=0
  KNOB_CLASS="production" KNOB_CLASS_LINE=""
  KNOB_POSTURE="automatic" KNOB_POSTURE_LINE=""
  KNOB_IMAGE_OWNER="" KNOB_IMAGE_OWNER_LINE=""
  KNOB_RECORDS="" KNOB_RECORDS_LINE=""
  KNOB_SECTIONS=()
  KNOB_WINDOW=() KNOB_QUIET=() KNOB_INFLIGHT=() KNOB_HEALTH=()
  KNOB_RESTARTER=() KNOB_SERVICE=() KNOB_BACKUP=() KNOB_CALLER=()
  KNOB_DATASTORE=() KNOB_HOLD=() KNOB_OWNER=() KNOB_ORIGIN=()
  KNOB_EXCEPTION=() KNOB_FINDING=()
  KNOB_REPORT_ONLY=0 KNOB_REPORT_ONLY_WHY=()
  # Parsed records: one entry per valid directive line, in file order.
  _KP_LINE=() _KP_SEC=() _KP_DIR=() _KP_KEY=() _KP_VAL=()
  # Sections: header glob, header line, exact (no * or ?), and rank for this host.
  _KS_GLOB=() _KS_LINE=() _KS_EXACT=() _KS_RANK=()
  _KNOB_MALFORMED=0 _KNOB_AMBIGUOUS=0
}

_knob_finding() {  # <line-or-empty> <kind> <message>
  KNOB_FINDING+=("$1$KNOB_US$2$KNOB_US$3")
}

_knob_malformed() {  # <line> <message>
  _KNOB_MALFORMED=1
  _knob_finding "$1" malformed "$2"
}

_knob_trim() {  # <text> -> _KR
  local re='^[[:space:]]*(.*[^[:space:]])[[:space:]]*$'
  if [[ $1 =~ $re ]]; then _KR=${BASH_REMATCH[1]}; else _KR=""; fi
}

_knob_is_time_range() {  # <HH:MM-HH:MM> -> _KT_START _KT_END _KT_WRAPS; 1 if not one
  local re='^(([01][0-9]|2[0-3]):[0-5][0-9])-(([01][0-9]|2[0-3]):[0-5][0-9])$'
  [[ $1 =~ $re ]] || return 1
  _KT_START=${BASH_REMATCH[1]} _KT_END=${BASH_REMATCH[3]}
  # A range ending where it starts is either empty or a whole day. Neither
  # reading is safe to guess, so it's malformed rather than silently one.
  [ "$_KT_START" != "$_KT_END" ] || return 1
  if [[ $_KT_END < $_KT_START ]]; then _KT_WRAPS=1; else _KT_WRAPS=0; fi
}

_knob_is_weekday() {
  case $1 in Mon | Tue | Wed | Thu | Fri | Sat | Sun) return 0 ;; esac
  return 1
}

_knob_is_repo() {
  local re='^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'
  [[ $1 =~ $re ]]
}

_knob_is_host() {
  local re='^[A-Za-z0-9][A-Za-z0-9._-]*$'
  [[ $1 =~ $re ]]
}

_knob_is_date() {
  local re='^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$'
  [[ $1 =~ $re ]]
}

_knob_record() {  # <line> <sec> <dir> <key> <val>
  _KP_LINE+=("$1") _KP_SEC+=("$2") _KP_DIR+=("$3") _KP_KEY+=("$4") _KP_VAL+=("$5")
}

# Validates one directive line and records it, or reports it malformed.
_knob_directive() {  # <line> <sec> <text>
  local n=$1 sec=$2 s=$3 dir rest u=$KNOB_US
  local -a tok=()
  dir=${s%%[[:space:]]*}
  _knob_trim "${s#"$dir"}"
  rest=$_KR
  [ -z "$rest" ] || read -r -a tok <<<"$rest"
  local nt=${#tok[@]}
  case $dir in
    class)
      case "$nt:${tok[0]:-}" in
        1:production | 1:staging | 1:dev | 1:ephemeral)
          _knob_record "$n" "$sec" class "" "${tok[0]}" ;;
        *) _knob_malformed "$n" "class takes one of production, staging, dev, ephemeral" ;;
      esac ;;
    posture)
      case "$nt:${tok[0]:-}" in
        1:automatic | 1:scheduled) _knob_record "$n" "$sec" posture "" "${tok[0]}" ;;
        *) _knob_malformed "$n" "posture takes automatic or scheduled" ;;
      esac ;;
    window)
      if [ "$nt" -eq 2 ] && _knob_is_weekday "${tok[0]}" && _knob_is_time_range "${tok[1]}"; then
        _knob_record "$n" "$sec" window "" "${tok[0]}$u$_KT_START$u$_KT_END$u$_KT_WRAPS"
      else
        _knob_malformed "$n" "window takes <weekday> <HH:MM-HH:MM>, with a weekday Mon to Sun and an end that differs from the start"
      fi ;;
    quiet)
      if { [ "$nt" -eq 1 ] || { [ "$nt" -eq 2 ] && _knob_is_weekday "${tok[1]}"; }; } &&
        _knob_is_time_range "${tok[0]}"; then
        _knob_record "$n" "$sec" quiet "" "${tok[1]:-}$u$_KT_START$u$_KT_END$u$_KT_WRAPS"
      else
        _knob_malformed "$n" "quiet takes <HH:MM-HH:MM> [<weekday>], with an end that differs from the start"
      fi ;;
    inflight | health)
      if [ -n "$rest" ]; then
        _knob_record "$n" "$sec" "$dir" "" "$rest"
      else
        _knob_malformed "$n" "$dir takes a command"
      fi ;;
    restarter | service)
      if [ "$nt" -eq 1 ]; then
        _knob_record "$n" "$sec" "$dir" "" "${tok[0]}"
      else
        _knob_malformed "$n" "$dir takes one unit"
      fi ;;
    # A backup regime names what it covers: unbound, it would stand in for
    # every datastore's dump, one it never copies included (CR 194).
    backup)
      if [ "$nt" -ge 2 ]; then
        _knob_record "$n" "$sec" backup "" "${tok[0]}$u${tok[*]:1}"
      else
        _knob_malformed "$n" "backup takes <unit> and each datastore unit it covers, as datastore lines name them"
      fi ;;
    caller)
      if [ "$nt" -eq 1 ] && _knob_is_repo "${tok[0]}"; then
        _knob_record "$n" "$sec" caller "" "${tok[0]}"
      else
        _knob_malformed "$n" "caller takes one repo, as owner/name"
      fi ;;
    datastore)
      if [ "$nt" -ge 3 ] && [ "${tok[0]}" = postgres ]; then
        # One record per database, keyed by unit and database, so two lines
        # naming the same cluster add up instead of one replacing the other.
        local db
        for db in "${tok[@]:2}"; do
          _knob_record "$n" "$sec" datastore "${tok[1]} $db" "postgres$u${tok[1]}$u$db"
        done
      elif [ "$nt" -eq 2 ] && [ "${tok[0]}" = redis ]; then
        _knob_record "$n" "$sec" datastore "${tok[1]}" "redis$u${tok[1]}$u"
      elif [ "$nt" -eq 5 ] && [ "${tok[0]}" = qdrant ] \
        && [[ ${tok[2]} =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] \
        && [[ ${tok[3]} =~ ^https?://[^/]+ ]] \
        && case ${tok[4]} in - | /*) true ;; *) false ;; esac; then
        # #367: the container its snapshot is copied out of, the API's base
        # as its certificate names it, and a root-only key file, or - .
        # A key goes over plain http only to this host, as SocratiCode's
        # own rule has it (CR 217).
        local qhost=${tok[3]#*://}
        qhost=${qhost%%/*}
        case $qhost in
          \[*) qhost=${qhost%%]*}] ;;
          *) qhost=${qhost%:*} ;;
        esac
        if [ "${tok[4]}" != - ] && [[ ${tok[3]} == http://* ]] &&
          ! case $qhost in localhost | 127.* | '[::1]') true ;; *) false ;; esac; then
          _knob_malformed "$n" "datastore qdrant would send its API key over plain http to another host: use https://, as its certificate names it, or this host's own address (127.0.0.1, localhost, [::1])"
        else
          _knob_record "$n" "$sec" datastore "${tok[1]}" "qdrant$u${tok[1]}$u${tok[2]} ${tok[3]} ${tok[4]}"
        fi
      else
        _knob_malformed "$n" "datastore takes postgres <unit> <database>..., redis <unit>, or qdrant <unit> <container> <http(s)://url> <key-file, an absolute path, or ->"
      fi ;;
    hold)
      # No tok[-1]: bash 3.2 rejects a negative subscript.
      local step="" sre='^[a-z0-9][a-z0-9-]*$'
      [ "$nt" -lt 2 ] || step=${tok[$((nt - 1))]}
      if [ -n "$step" ] && [[ $step =~ $sre ]]; then
        local globs=("${tok[@]:0:$((nt - 1))}")
        _knob_record "$n" "$sec" hold "$step" "$step$u${globs[*]}"
      else
        _knob_malformed "$n" "hold takes <package-glob>... <step>, with a step name of lowercase letters, digits and hyphens"
      fi ;;
    owner)
      if [ "$nt" -eq 2 ] && { _knob_is_repo "${tok[1]}" || [ "${tok[1]}" = self ] || [ "${tok[1]}" = image ]; }; then
        _knob_record "$n" "$sec" owner "${tok[0]}" "${tok[0]}$u${tok[1]}"
      else
        _knob_malformed "$n" "owner takes <component-glob> <repo>, the repo as owner/name, self or image"
      fi ;;
    image-owner)
      if [ "$nt" -eq 1 ] && _knob_is_repo "${tok[0]}"; then
        _knob_record "$n" "$sec" image-owner "" "${tok[0]}"
      else
        _knob_malformed "$n" "image-owner takes one repo, as owner/name"
      fi ;;
    origin)
      local o=${tok[0]:-} pol=${tok[1]:-}
      if [ "$nt" -eq 2 ] && [ "$pol" = follow ]; then
        _knob_record "$n" "$sec" origin "$o" "$o${u}follow$u"
      elif [ "$nt" -eq 3 ] && [ "$pol" = pin ]; then
        _knob_record "$n" "$sec" origin "$o" "$o${u}pin$u${tok[2]}"
      elif [ "$nt" -ge 3 ] && [ "$pol" = hold ]; then
        _knob_record "$n" "$sec" origin "$o" "$o${u}hold$u${tok[*]:2}"
      else
        _knob_malformed "$n" "origin takes <origin> follow, <origin> pin <version>, or <origin> hold <reason>"
      fi ;;
    exception)
      if [ "$nt" -ge 3 ] && _knob_is_date "${tok[1]}"; then
        _knob_record "$n" "$sec" exception "${tok[0]}" "${tok[0]}$u${tok[1]}$u${tok[*]:2}"
      else
        _knob_malformed "$n" "exception takes <what> <review-by YYYY-MM-DD> <reason>"
      fi ;;
    records)
      if [ "$nt" -eq 1 ]; then
        _knob_record "$n" "$sec" records "" "${tok[0]}"
      else
        _knob_malformed "$n" "records takes one path or repo"
      fi ;;
    *) _knob_malformed "$n" "unknown directive" ;;
  esac
}

_knob_parse_file() {
  local n=0 sec=-1 line s t j glob hre
  hre='^\[host[[:space:]]+([^][:space:]]+)[[:space:]]*\]$'
  while IFS= read -r line || [ -n "$line" ]; do
    n=$((n + 1))
    line=${line%$'\r'}
    # Checked on the raw line, before the comment is cut: a control character
    # in a comment is as unrepresentable in a record as one anywhere else.
    t=${line//$'\t'/ }
    case $t in *[[:cntrl:]]*)
      _knob_malformed "$n" "the line holds a control character"
      continue ;;
    esac
    # '#' opens a comment only at the start of a line or after whitespace, so
    # a command can hold a URL fragment. %% cuts from the first such '#'.
    s=" $line"
    s=${s%%[[:space:]]#*}
    _knob_trim "$s"
    s=$_KR
    [ -n "$s" ] || continue
    case $s in
      "["*)
        if [[ $s =~ $hre ]] && [[ ${BASH_REMATCH[1]} != *"["* ]]; then
          glob=${BASH_REMATCH[1]}
          sec=-1
          for j in ${_KS_GLOB[@]+"${!_KS_GLOB[@]}"}; do
            if [ "${_KS_GLOB[$j]}" = "$glob" ]; then
              sec=$j
              _knob_finding "$n" duplicate-section \
                "[host $glob] also opens at line ${_KS_LINE[$j]}; their lines are read as one section"
              break
            fi
          done
          if [ "$sec" -eq -1 ]; then
            sec=${#_KS_GLOB[@]}
            _KS_GLOB+=("$glob") _KS_LINE+=("$n") _KS_RANK+=(-1)
            case $glob in *[*?]*) _KS_EXACT+=(0) ;; *) _KS_EXACT+=(1) ;; esac
          fi
        else
          # The lines that follow can't be placed, so they're dropped with it
          # rather than read as global.
          _knob_malformed "$n" "a section header is [host <glob>], the glob using only * and ?"
          sec=-2
        fi ;;
      *)
        if [ "$sec" -eq -2 ]; then
          _knob_malformed "$n" "under a malformed section header, so it applies to no host"
        else
          _knob_directive "$n" "$sec" "$s"
        fi ;;
    esac
  done <"$KNOB_PATH"
}

# Which sections apply to this host, and at what rank. Globs apply from the
# least specific to the most, so [host co-worker-*] refines [host co-*]. Two
# matching globs equally specific are a tie: neither applies, and the host is
# report-only.
_knob_match_sections() {
  local j k spec lines tied
  local -a matched=() specs=()
  for j in ${_KS_GLOB[@]+"${!_KS_GLOB[@]}"}; do
    if [ "${_KS_EXACT[$j]}" -eq 1 ]; then
      [ "${_KS_GLOB[$j]}" != "$KNOB_HOST" ] || _KS_RANK[$j]=$KNOB_RANK_EXACT
    else
      # Unquoted on purpose: the header is a glob, matched as a pattern.
      # shellcheck disable=SC2053
      if [[ $KNOB_HOST == ${_KS_GLOB[$j]} ]]; then
        spec=${_KS_GLOB[$j]//[*?]/}
        _KS_RANK[$j]=$((KNOB_RANK_GLOB + ${#spec}))
        matched+=("$j") specs+=("${#spec}")
      fi
    fi
  done
  for j in ${matched[@]+"${!matched[@]}"}; do
    tied=0 lines=""
    for k in "${!matched[@]}"; do
      [ "${specs[$k]}" = "${specs[$j]}" ] || continue
      lines="$lines, [host ${_KS_GLOB[${matched[$k]}]}] (line ${_KS_LINE[${matched[$k]}]})"
      [ "$k" -eq "$j" ] || tied=1
    done
    [ "$tied" -eq 1 ] || continue
    _KNOB_AMBIGUOUS=1
    _KS_RANK[${matched[$j]}]=-1
    # Reported once, by the first section of the tie.
    for k in "${!matched[@]}"; do
      [ "${specs[$k]}" = "${specs[$j]}" ] || continue
      [ "$k" -lt "$j" ] && continue 2
      break
    done
    _knob_finding "" ambiguous-sections \
      "$KNOB_HOST matches glob sections that are equally specific: ${lines#, }. None of them applies until one is narrowed or an exact section is added"
  done
  # Applied sections, least specific first, as they layer. Ordered in bash: a
  # sort inside a for word list can fail, and no errexit would see it.
  local best
  local -a left=()
  for j in ${_KS_GLOB[@]+"${!_KS_GLOB[@]}"}; do
    [ "${_KS_RANK[$j]}" -le 0 ] || left+=("$j")
  done
  while [ "${#left[@]}" -gt 0 ]; do
    best=0
    for k in "${!left[@]}"; do
      [ "${_KS_RANK[${left[$k]}]}" -ge "${_KS_RANK[${left[$best]}]}" ] || best=$k
    done
    KNOB_SECTIONS+=("${_KS_GLOB[${left[$best]}]}")
    unset "left[$best]"
    left=(${left[@]+"${left[@]}"})
  done
}

_knob_rank_of() {  # <record index> -> _KR (-1 when it doesn't apply to this host)
  local sec=${_KP_SEC[$1]}
  if [ "$sec" -eq -1 ]; then _KR=$KNOB_RANK_GLOBAL; else _KR=${_KS_RANK[$sec]}; fi
}

# The records of one directive that win for this host, in file order -> _KSEL.
#   keyed: per key, the highest rank wins; a repeat at that rank is a finding,
#          and the later line wins.
#   list:  the highest rank that declares the directive replaces the others.
_knob_select() {  # <directive> <keyed|list>
  local dir=$1 mode=$2 i k ri rk top=-1 beaten by
  _KSEL=()
  for i in ${_KP_DIR[@]+"${!_KP_DIR[@]}"}; do
    [ "${_KP_DIR[$i]}" = "$dir" ] || continue
    _knob_rank_of "$i"; ri=$_KR
    [ "$ri" -gt 0 ] || continue
    if [ "$mode" = list ]; then
      [ "$ri" -le "$top" ] || top=$ri
      continue
    fi
    beaten=0 by=""
    for k in "${!_KP_DIR[@]}"; do
      if [ "$k" = "$i" ] || [ "${_KP_DIR[$k]}" != "$dir" ] || [ "${_KP_KEY[$k]}" != "${_KP_KEY[$i]}" ]; then
        continue
      fi
      _knob_rank_of "$k"; rk=$_KR
      [ "$rk" -gt 0 ] || continue
      if [ "$rk" -gt "$ri" ]; then beaten=1; by=""; break; fi
      if [ "$rk" -eq "$ri" ] && [ "$k" -gt "$i" ]; then beaten=1; by=${_KP_LINE[$k]}; fi
    done
    if [ "$beaten" -eq 0 ]; then
      _KSEL+=("$i")
    elif [ -n "$by" ]; then
      _knob_finding "${_KP_LINE[$i]}" repeated \
        "$dir${_KP_KEY[$i]:+ ${_KP_KEY[$i]}} is set again at the same precedence; line $by wins"
    fi
  done
  if [ "$mode" = list ] && [ "$top" -gt 0 ]; then
    for i in "${!_KP_DIR[@]}"; do
      [ "${_KP_DIR[$i]}" = "$dir" ] || continue
      _knob_rank_of "$i"
      [ "$_KR" -ne "$top" ] || _KSEL+=("$i")
    done
  fi
}

_knob_resolve() {
  local i d u=$KNOB_US step val
  local -a f=()

  _knob_select class keyed
  for i in ${_KSEL[@]+"${_KSEL[@]}"}; do KNOB_CLASS=${_KP_VAL[$i]} KNOB_CLASS_LINE=${_KP_LINE[$i]}; done
  _knob_select posture keyed
  for i in ${_KSEL[@]+"${_KSEL[@]}"}; do KNOB_POSTURE=${_KP_VAL[$i]} KNOB_POSTURE_LINE=${_KP_LINE[$i]}; done
  _knob_select image-owner keyed
  for i in ${_KSEL[@]+"${_KSEL[@]}"}; do KNOB_IMAGE_OWNER=${_KP_VAL[$i]} KNOB_IMAGE_OWNER_LINE=${_KP_LINE[$i]}; done
  _knob_select records keyed
  for i in ${_KSEL[@]+"${_KSEL[@]}"}; do KNOB_RECORDS=${_KP_VAL[$i]} KNOB_RECORDS_LINE=${_KP_LINE[$i]}; done

  for d in window quiet inflight health restarter service backup caller; do
    _knob_select "$d" list
    for i in ${_KSEL[@]+"${_KSEL[@]}"}; do
      val="${_KP_VAL[$i]}$u${_KP_LINE[$i]}"
      case $d in
        window) KNOB_WINDOW+=("$val") ;;
        quiet) KNOB_QUIET+=("$val") ;;
        inflight) KNOB_INFLIGHT+=("$val") ;;
        health) KNOB_HEALTH+=("$val") ;;
        restarter) KNOB_RESTARTER+=("$val") ;;
        service) KNOB_SERVICE+=("$val") ;;
        backup) KNOB_BACKUP+=("$val") ;;
        caller) KNOB_CALLER+=("$val") ;;
      esac
    done
  done

  # Datastores: the winning records are one per unit and database, grouped
  # back into one entry per unit, with the line that first names it.
  local -a du=() de=() dd=() dl=()
  local k found
  _knob_select datastore keyed
  for i in ${_KSEL[@]+"${_KSEL[@]}"}; do
    IFS=$u read -r -a f <<<"${_KP_VAL[$i]}"
    found=-1
    for k in ${du[@]+"${!du[@]}"}; do
      if [ "${du[$k]}" = "${f[1]}" ]; then found=$k; break; fi
    done
    if [ "$found" -eq -1 ]; then
      du+=("${f[1]}") de+=("${f[0]}") dd+=("${f[2]:-}") dl+=("${_KP_LINE[$i]}")
    elif [ -n "${f[2]:-}" ]; then
      dd[$found]="${dd[$found]:+${dd[$found]} }${f[2]}"
    fi
  done
  for k in ${du[@]+"${!du[@]}"}; do
    KNOB_DATASTORE+=("${de[$k]}$u${du[$k]}$u${dd[$k]}$u${dl[$k]}")
  done

  for d in owner origin exception; do
    _knob_select "$d" keyed
    for i in ${_KSEL[@]+"${_KSEL[@]}"}; do
      val="${_KP_VAL[$i]}"
      case $d in
        owner) KNOB_OWNER+=("$val$u${_KP_LINE[$i]}") ;;
        origin) KNOB_ORIGIN+=("$val$u${_KP_LINE[$i]}") ;;
        exception)
          IFS=$u read -r -a f <<<"$val"
          # A passed review-by date expires it: the day itself still counts.
          if [[ $KNOB_TODAY > ${f[1]} ]]; then
            KNOB_EXCEPTION+=("$val${u}1$u${_KP_LINE[$i]}")
            _knob_finding "${_KP_LINE[$i]}" expired-exception \
              "exception ${f[0]} passed its review-by date, ${f[1]}; the deviation it covered is a finding again"
          else
            KNOB_EXCEPTION+=("$val${u}0$u${_KP_LINE[$i]}")
          fi ;;
      esac
    done
  done

  # Holds: the defaults, each replaced by a knob line naming its step, plus
  # any step only the knob names.
  _knob_select hold keyed
  local defaults=("postgres${u}postgresql-* libpq5" "redis${u}redis-server redis-tools" "docker${u}docker.io containerd")
  for val in "${defaults[@]}"; do
    step=${val%%"$u"*}
    for i in ${_KSEL[@]+"${_KSEL[@]}"}; do
      [ "${_KP_KEY[$i]}" != "$step" ] || continue 2
    done
    KNOB_HOLD+=("$val$u")
  done
  for i in ${_KSEL[@]+"${_KSEL[@]}"}; do KNOB_HOLD+=("${_KP_VAL[$i]}$u${_KP_LINE[$i]}"); done
}

_knob_report_only() {
  if [ "$KNOB_PRESENT" -eq 0 ]; then
    KNOB_REPORT_ONLY_WHY+=("no knob: the host is compared against the reference automatic posture, and nothing is applied")
  elif [ -z "$KNOB_POSTURE_LINE" ]; then
    KNOB_REPORT_ONLY_WHY+=("no posture line for this host: compared against automatic, and nothing is applied")
  fi
  [ "$KNOB_CLASS" != ephemeral ] ||
    KNOB_REPORT_ONLY_WHY+=("class ephemeral: the host is patched by rebuilding its image")
  [ "$_KNOB_MALFORMED" -eq 0 ] ||
    KNOB_REPORT_ONLY_WHY+=("a malformed line: the knob isn't trusted for an apply until every line parses")
  [ "$_KNOB_AMBIGUOUS" -eq 0 ] ||
    KNOB_REPORT_ONLY_WHY+=("glob sections that are equally specific match this host")
  [ "${#KNOB_REPORT_ONLY_WHY[@]}" -eq 0 ] || KNOB_REPORT_ONLY=1
}

knob_load() {  # <path> <host> <today YYYY-MM-DD>
  # Words split and join on the default separators, whatever the caller set:
  # under a strict IFS=$'\n\t', a line would read as one word, and a joined
  # list would carry a newline.
  local IFS=$' \t\n'
  knob_reset
  # Checked here, not left to each caller: an empty date sorts before every
  # review-by date, so no exception would ever expire, and a host holding a
  # control character would reach the output unescaped.
  if ! _knob_is_date "$3"; then
    echo "ERROR knob_load takes the date as YYYY-MM-DD" >&2
    return 2
  fi
  if ! _knob_is_host "$2"; then
    echo "ERROR knob_load takes a host name of letters, digits, '.', '-' and '_'" >&2
    return 2
  fi
  KNOB_PATH=$1 KNOB_HOST=$2 KNOB_TODAY=$3
  if [ -e "$KNOB_PATH" ]; then
    if [ -d "$KNOB_PATH" ] || [ ! -r "$KNOB_PATH" ]; then
      echo "ERROR the knob at $KNOB_PATH exists but can't be read" >&2
      return 2
    fi
    KNOB_PRESENT=1
    local LC_ALL=C
    _knob_parse_file
    _knob_match_sections
  fi
  _knob_resolve
  _knob_report_only
}
