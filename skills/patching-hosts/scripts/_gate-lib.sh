#!/usr/bin/env bash
# _gate-lib.sh — what apply.sh, recovery-point.sh and reboot-chain.sh share:
# refusals and failures, root-only records, a step's span against the
# knob's windows and quiet ranges, the inflight gate, and how to reach a
# data store. Sourced after _knob-lib.sh and _probe-lib.sh.
# The REFUSED, FAILED, SPAN_*, PG_* and REDIS_* variables are its output.
# shellcheck disable=SC2034
set -euo pipefail

gate_lib_usage() {
  cat <<'USAGE'
Usage: . _gate-lib.sh    (sourced by apply.sh, recovery-point.sh,
                         reboot-chain.sh, prune-plan.sh and prune.sh;
                         running it does nothing)

The gate_* functions add their readings to the caller's J_GATE.

  refuse WHY / fail WHY     add to REFUSED / FAILED; fail also tells stderr,
                            after the caller's ME
  root_write PATH           stdin into PATH as root, mode 600 from creation
  root_append PATH          the same, appended
  root_logged LOG CMD...    CMD as root, its output in LOG, mode 600
  root_has PATH             whether PATH exists, asked as root
  root_read VAR PATH        VAR := PATH's contents, read as root
  root_mode VAR PATH        PATH's permission bits as root sees them
  default_run VAR           /var/backups/patching-hosts-<UTC>, from P_NOW
  words_of VAR TEXT         TEXT's words, one space apart
  json_words VAR WORDS      a JSON array of space-separated WORDS
  says VAR RC               what a knob command's exit status means
  sq VAR TEXT               TEXT quoted for sh
  gate_span SECONDS         refuses a span, now to now plus SECONDS, that
                            isn't inside one window or meets a quiet range;
                            sets SPAN_S and SPAN_E. Not a number: unknown,
                            and SPAN_S and SPAN_E are left as they were
  gate_inflight             refuses unless every inflight command prints 0
                            and exits 0, and when there's no invoking user
                            to run the knob's inflight, health or recovery commands as
  chain_active UNIT         whether a run's reboot chain is scheduled or
                            running; CHAIN_STATE says which unit, and how
  package_manager VAR       which package manager runs now, or empty
  pg_port VAR UNIT          the port of the cluster a postgresql unit runs,
                            or 1 with PG_WHY
  redis_conn UNIT [USER KEY-FILE]
                            REDIS_ARGS := redis-cli's connection words,
                            REDIS_CONF := the file the unit starts from, and
                            REDIS_LOGIN := key (the knob's USER), conf
                            (default, with requirepass) or none (an aclfile
                            and no USER); RC_* as redis_conf sets them
  redis_cli CMD...          redis-cli at REDIS_ARGS, as root, logged in as
                            REDIS_LOGIN says, with the password root's own sh
                            reads from KEY-FILE or REDIS_CONF
  redis_owned UNIT          whether the unit's own process listens at
                            REDIS_ARGS, as ss reads it as root, with no
                            login: 1 for another or none, 2 when the unit
                            isn't running, each with REDIS_WHY
  redis_refused UNIT CMD OUT
                            whether OUT, with CAP_ERR, is Redis refusing the
                            login or CMD, with REDIS_WHY saying which
  redis_key_ok              whether a key login's file is readable as root
  PKG_RE                    the pgrep pattern unattended-upgrade is matched
                            by, at its path
  REDIS_PW_SED              the sed program that reads a Redis file's
                            password as Redis does
USAGE
}

case "${0##*/}" in
  _gate-lib.sh) case "${1-}" in -h | --help) gate_lib_usage; exit 0 ;; esac ;;
esac

# No function here ends on a bare `[ … ] && …`: a function that returns
# non-zero stops the caller under errexit, wherever it is called plainly.

ME=${ME:-gate}
REFUSED=() FAILED=()
refuse() { REFUSED+=("$1"); }
fail() {
  FAILED+=("$1")
  echo "$ME: $1" >&2
}

# Root-only records. A `>` from this shell can't write under /var/backups,
# and `sudo tee` would create the file at 644: each one is written by root's
# own sh, mode 600 from creation (run.md §2).
# The script runs as root, in sh: its expansion is its own.
# shellcheck disable=SC2016
root_write() { as_root sh -c 'umask 077; cat >"$1"' sh "$1"; }
# The script runs as root, in sh: its expansion is its own.
# shellcheck disable=SC2016
root_append() { as_root sh -c 'umask 077; cat >>"$1"' sh "$1"; }
# Runs CMD as root, with its output in LOG, a root-only file.
# The script runs as root, in sh: its expansions are its own.
# shellcheck disable=SC2016
root_logged() {  # <log> <cmd>...
  local _rl=$1
  shift
  as_root sh -c 'umask 077; l=$1; shift; "$@" >"$l" 2>&1' sh "$_rl" "$@"
}
root_has() { as_root test -e "$1"; }
root_read() {  # <var> <path>: VAR := its contents; returns 1 when it can't be read
  capture "$1" as_root cat -- "$2"
  [ "$CAP_RC" -eq 0 ]
}
# A file inside a 0700 root directory can't be stat'ed from outside it.
root_mode() {  # <var> <path>
  local _rm=""
  capture _rm as_root stat -c %a -- "$2"
  if [ "$CAP_RC" -ne 0 ]; then capture _rm as_root stat -f %Lp -- "$2"; fi
  case $_rm in
    '' | *[!0-7]*) printf -v "$1" '%s' "" ;;
    *) printf -v "$1" '%04d' "$((10#$_rm))" ;;
  esac
}

default_run() {  # <var>
  local _dr=""
  iso_utc _dr "$P_NOW"
  printf -v "$1" '%s' "/var/backups/patching-hosts-${_dr//[-:]/}"
}

words_of() {  # <var> <text>: VAR := its words, one space apart
  local -a _wo=()
  read -r -d '' -a _wo <<<"$2" || true
  printf -v "$1" '%s' "${_wo[*]-}"
}

json_words() {  # <var> <space-separated words>: VAR := a JSON array of them
  local _jw_a="" _jw
  local -a _jw_w=()
  read -r -a _jw_w <<<"$2" || true
  for _jw in ${_jw_w[@]+"${_jw_w[@]}"}; do jpushs _jw_a "$_jw"; done
  printf -v "$1" '[%s]' "$_jw_a"
}

says() {  # <var> <rc>: what a knob command's exit status means
  case $2 in
    124) printf -v "$1" '%s' "timed out after $KNOB_CMD_TIMEOUT s" ;;
    137) printf -v "$1" '%s' "was killed (exit 137): it ignored the time limit's TERM" ;;
    *) printf -v "$1" '%s' "exited $2" ;;
  esac
}

sq() {  # <var> <text>: VAR := TEXT in single quotes, each ' as '\''
  local _sq=${2//\'/\'\\\'\'}
  printf -v "$1" "'%s'" "$_sq"
}

hm_sec() {  # <var> <HH:MM>
  printf -v "$1" '%s' "$((10#${2%%:*} * 3600 + 10#${2##*:} * 60))"
}

dow_of() {  # <var> <Mon..Sun>: 0 for Monday
  local _d _i=0
  for _d in Mon Tue Wed Thu Fri Sat Sun; do
    if [ "$_d" = "$2" ]; then
      printf -v "$1" '%s' "$_i"
      return 0
    fi
    _i=$((_i + 1))
  done
  return 1
}

# The span, from now to now plus its expected duration, inside one window
# and clear of every quiet range. Checking only the start lets a 9-minute
# apply begun 5 minutes before a quiet range run into it.
SPAN_S="" SPAN_E=""
# SPAN_WHAT names the span in a refusal, where it's more than the step's.
SPAN_WHAT=""
gate_span() {  # <expected seconds, or empty when unknown>
  local S E o="" a="" r d ws we len wk os oe day q dq hit="" s_iso e_iso what=$SPAN_WHAT
  [ -n "$what" ] || what="the step's span"
  local -a f=()
  if ! is_int "$1"; then
    jadd J_GATE span null
    return 0
  fi
  S=$P_NOW
  E=$((S + $1))
  SPAN_S=$S SPAN_E=$E
  iso_utc s_iso "$S"
  iso_utc e_iso "$E"
  jadds o start "$s_iso"
  jadds o end "$e_iso"
  jaddn o expected_seconds "$((E - S))"
  # Monday 00:00 UTC of the week holding S: 1970-01-01 was a Thursday.
  wk=$((S - ((S / 86400 + 3) % 7) * 86400 - S % 86400))
  for r in ${KNOB_WINDOW[@]+"${KNOB_WINDOW[@]}"}; do
    IFS=$KNOB_US read -r -a f <<<"$r"
    dow_of d "${f[0]}"
    hm_sec ws "${f[1]}"
    hm_sec we "${f[2]}"
    len=$((we - ws))
    [ "${f[3]}" -eq 0 ] || len=$((len + 86400))
    # Last week's occurrence too: one that wraps past Sunday midnight.
    for os in $((wk - 7 * 86400 + d * 86400 + ws)) $((wk + d * 86400 + ws)); do
      oe=$((os + len))
      if [ -z "$hit" ] && [ "$os" -le "$S" ] && [ "$E" -le "$oe" ]; then
        hit="{\"weekday\": \"${f[0]}\", \"start\": \"${f[1]}\", \"end\": \"${f[2]}\", \"line\": ${f[4]}}"
      fi
    done
  done
  if [ "${#KNOB_WINDOW[@]}" -eq 0 ]; then
    refuse "no window is declared for this host, so no step's span can be inside one (knob.md)"
  elif [ -z "$hit" ]; then
    refuse "$what, $s_iso to $e_iso ($((E - S)) s expected), isn't wholly inside one window: start it where the whole span fits"
  fi
  jadd o window "${hit:-null}"
  for r in ${KNOB_QUIET[@]+"${KNOB_QUIET[@]}"}; do
    IFS=$KNOB_US read -r -a f <<<"$r"
    hm_sec ws "${f[1]}"
    hm_sec we "${f[2]}"
    len=$((we - ws))
    [ "${f[3]}" -eq 0 ] || len=$((len + 86400))
    dq=""
    if [ -n "${f[0]}" ]; then dow_of dq "${f[0]}"; fi
    for ((day = S / 86400 - 1; day <= E / 86400; day++)); do
      if [ -n "$dq" ] && [ $(((day + 3) % 7)) -ne "$dq" ]; then continue; fi
      os=$((day * 86400 + ws))
      oe=$((os + len))
      if [ "$os" -lt "$E" ] && [ "$S" -lt "$oe" ]; then
        q=""
        jaddsn q weekday "${f[0]}"
        jadds q start "${f[1]}"
        jadds q end "${f[2]}"
        jaddn q line "${f[4]}"
        jpush a "{$q}"
        refuse "$what runs into the quiet range ${f[1]}-${f[2]}${f[0]:+ ${f[0]}} (line ${f[4]})"
        break
      fi
    done
  done
  jadd o quiet_overlaps "[$a]"
  jadd J_GATE span "{$o}"
}

# Knob commands never run as root (knob.md). Every inflight one must print 0,
# read right before the step, not at the window's start.
gate_inflight() {
  local r c l out rc e="" a="" why
  local -a f=()
  if [ -z "$P_KNOB_USER" ] && [ $((${#KNOB_INFLIGHT[@]} + ${#KNOB_HEALTH[@]} + ${#KNOB_RECOVERY[@]})) -gt 0 ]; then
    refuse "the knob's inflight, health and recovery commands never run as root, and there's no invoking user to run them as: run $ME.sh through sudo from your own account"
    jadd J_GATE inflight null
    return 0
  fi
  for r in ${KNOB_INFLIGHT[@]+"${KNOB_INFLIGHT[@]}"}; do
    IFS=$KNOB_US read -r -a f <<<"$r"
    c=${f[0]} l=${f[1]}
    rc=0
    out=$(knob_cmd "$c" 2>/dev/null) || rc=$?
    # The whole output, not its first line: a check that prints a count per
    # queue prints 0 only when every queue is empty.
    words_of out "$out"
    e=""
    jadds e command "$c"
    jaddn e line "$l"
    jaddn e exit "$rc"
    jadds e printed "$out"
    if [ "$rc" -eq 0 ] && [ "$out" = 0 ]; then
      jaddb e ok 1
    else
      jaddb e ok 0
      if [ "$rc" -ne 0 ]; then
        says why "$rc"
        refuse "inflight (line $l) $why, so whether work is in flight is unknown"
      else
        refuse "inflight (line $l) printed \"$out\", not 0: let the work drain, then gate again"
      fi
    fi
    jpush a "{$e}"
  done
  jadd J_GATE inflight "[$a]"
}

# Whether the reboot chain a run launched is scheduled or running: its
# timer or its service active, or on its way up or down.
CHAIN_STATE=""
chain_active() {  # <unit>: CHAIN_STATE := "<its timer or service> <state>"
  local _ca_x _ca_s
  CHAIN_STATE=""
  for _ca_x in "$1.timer" "$1.service"; do
    _ca_s=$(systemctl is-active -- "$_ca_x" 2>/dev/null) || true
    case $_ca_s in
      active | activating | deactivating | reloading)
        CHAIN_STATE="$_ca_x $_ca_s"
        return 0 ;;
    esac
  done
  return 1
}

# Whether a package manager runs now. unattended-upgrade-shutdown runs all
# the time where unattended-upgrades is installed, and its name is cut to
# the same 15 characters, so unattended-upgrade is matched by its path.
PKG_RE='/usr/bin/unattended-upgrade( |$)'
package_manager() {  # <var>
  local _pm=""
  if pgrep -x 'dpkg|apt|apt-get' >/dev/null 2>&1; then _pm="dpkg or apt"; fi
  if pgrep -f "$PKG_RE" >/dev/null 2>&1; then _pm="${_pm:+$_pm and }unattended-upgrade"; fi
  printf -v "$1" '%s' "$_pm"
}

# --- data stores ---------------------------------------------------------------
# A knob's postgresql unit is a cluster: postgresql@16-main is 16/main.
# postgresql.service is Ubuntu's umbrella, which names a cluster only on a
# host that has one. pg_lsclusters gives each one's port and status.
PG_WHY=""
pg_port() {  # <var> <unit>
  local _pu=${2%.service} _po _pl _pv _pn _pp _ps _pr _want="" _n=0 _hit=""
  PG_WHY=""
  case $_pu in
    postgresql@*-*) _want=${_pu#postgresql@} _want="${_want%%-*}/${_want#*-}" ;;
    postgresql) ;;
    *)
      PG_WHY="$2 isn't a postgresql unit"
      return 1 ;;
  esac
  capture _po pg_lsclusters -h
  if [ "$CAP_RC" -ne 0 ]; then
    PG_WHY="pg_lsclusters couldn't be read (${CAP_ERR:-exit $CAP_RC})"
    return 1
  fi
  while IFS= read -r _pl; do
    read -r _pv _pn _pp _ps _pr <<<"$_pl"
    [ -n "$_pv" ] || continue
    _n=$((_n + 1))
    if [ -z "$_want" ] || [ "$_want" = "$_pv/$_pn" ]; then _hit="$_pv/$_pn $_pp ${_ps%%,*}"; fi
  done <<<"$_po"
  if [ -z "$_want" ] && [ "$_n" -ne 1 ]; then
    PG_WHY="$2 names no cluster, and the host has $_n: name it as postgresql@<version>-<cluster>"
    return 1
  fi
  if [ -z "$_hit" ]; then
    PG_WHY="the host has no cluster $_want"
    return 1
  fi
  read -r _pn _pp _ps <<<"$_hit"
  if [ "$_ps" != online ]; then
    PG_WHY="cluster $_pn is $_ps, not online"
    return 1
  fi
  # pg_lsclusters reads it from postgresql.conf, which postgres can write,
  # and the reboot chain runs it as root.
  if ! is_int "$_pp"; then
    PG_WHY="cluster $_pn's port, $_pp, isn't a number"
    return 1
  fi
  printf -v "$1" '%s' "$_pp"
}

# redis-cli reaches the server the unit starts, through the address its own
# config file binds: a host may bind only its tailnet address. A command
# that needs a login logs in as the knob's user, with its key file, or else
# as default with the file's requirepass, except under an aclfile, which
# makes requirepass nobody's (#379). A password never leaves its file:
# redis_cli, and the chain when it runs, read it into REDISCLI_AUTH as
# root, so it reaches no argv and no output.
REDIS_ARGS=() REDIS_CONF="" REDIS_LOGIN="" REDIS_USER="" REDIS_KEY=""
# Where systemd keeps encrypted credentials: a key file under it is one,
# which systemd-creds decrypts as root, by the name of its file.
REDIS_CREDSTORE=/etc/credstore.encrypted/
# The password a file's last requirepass sets, as Redis reads it: the key
# in any case, after any leading space, and the value without trailing
# space or one pair of quotes, double or single (measured on 7.0).
# redis_cli and the chain run this one script, so the two read the same
# password.
_RPW='[[:space:]]*[Rr][Ee][Qq][Uu][Ii][Rr][Ee][Pp][Aa][Ss][Ss][[:space:]]'
REDIS_PW_SED="/^$_RPW/!d;s/^$_RPW*//;"'s/[[:space:]]*$//;s/^"\(.*\)"$/\1/;s/^'\''\(.*\)'\''$/\1/'
# unit_show sets it by name.
U_MainPID=""
redis_conn() {  # <unit> [<user> <key-file>]
  local _rc_bind
  REDIS_ARGS=() REDIS_USER=${2:-} REDIS_KEY=${3:-}
  redis_conf "$1"
  REDIS_CONF=$RC_CONF
  _rc_bind=$RC_BIND
  case $_rc_bind in '' | '*' | 0.0.0.0 | '::' | '::*') _rc_bind=127.0.0.1 ;; esac
  if [ -n "$RC_SOCK" ]; then
    REDIS_ARGS=(-s "$RC_SOCK")
  else
    is_int "$RC_PORT" || RC_PORT=6379
    REDIS_ARGS=(-h "$_rc_bind" -p "$RC_PORT")
  fi
  # key: the knob's user; conf: default, with requirepass where the file
  # sets one; none: no login at all, so nothing reaches ACL LOG.
  if [ -n "$REDIS_USER" ]; then
    REDIS_LOGIN=key
  elif [ "$RC_ACL" -eq 1 ]; then
    REDIS_LOGIN=none
  else
    REDIS_LOGIN=conf
  fi
}

# Whom redis_cli logs in as, for a message.
redis_as() {  # <var>
  case $REDIS_LOGIN in
    key) printf -v "$1" '%s' "$REDIS_USER" ;;
    none) printf -v "$1" '%s' "no user: its aclfile sets the users, so its requirepass isn't one to log in with" ;;
    *) printf -v "$1" '%s' "default, with its file's requirepass" ;;
  esac
}

# Whether the Redis reached is the unit's own: its main PID listens at the
# address, as root reads it from the socket (#379). No login, so a Redis
# whose default user is off is read the same, and nothing reaches ACL LOG.
# A port redis_conn can't read, such as --port ${VAR}, which systemd
# expands only at exec, or one an included file sets, would otherwise
# reach another Redis. A save's child closes the listening sockets
# (measured on 7.0), but a second process on one doesn't matter: the main
# PID must be among them.
REDIS_WHY=""
redis_owned() {  # <unit>
  local _ro_pid="" _ro_out _ro_l _ro_at _ro_w _ro_p _ro_pids="" _ro_h _ro_n
  REDIS_WHY=""
  if unit_show "$1" MainPID; then _ro_pid=$U_MainPID; fi
  if ! is_int "$_ro_pid" || [ "$_ro_pid" -eq 0 ]; then
    REDIS_WHY="$1 has no main process: it isn't running"
    return 2
  fi
  if [ "${REDIS_ARGS[0]}" = -s ]; then
    _ro_at=${REDIS_ARGS[1]}
    capture _ro_out as_root ss -Hlxp src "$_ro_at"
  else
    _ro_h=${REDIS_ARGS[1]} _ro_n=${REDIS_ARGS[3]}
    case $_ro_h in *:*) _ro_at="[$_ro_h]:$_ro_n" ;; *) _ro_at="$_ro_h:$_ro_n" ;; esac
    capture _ro_out as_root ss -Hltnp "sport = :$_ro_n"
  fi
  if [ "$CAP_RC" -ne 0 ]; then
    REDIS_WHY="ss couldn't list what listens at $_ro_at (exit $CAP_RC${CAP_ERR:+: $CAP_ERR}), so whether it's $1's own Redis is unknown"
    return 1
  fi
  while IFS= read -r _ro_l; do
    [ -n "$_ro_l" ] || continue
    if [ "${REDIS_ARGS[0]}" != -s ]; then
      # Its local address, the fourth column, or the wildcard of its family:
      # Redis listens on IPv6 alone (measured on 7.0).
      read -r _ _ _ _ro_w _ <<<"$_ro_l" || true
      case $_ro_at:$_ro_w in
        "$_ro_at:$_ro_at" | "[$_ro_h]:$_ro_n:[::]:$_ro_n" | "$_ro_h:$_ro_n:0.0.0.0:$_ro_n" | *":*:$_ro_n") ;;
        *) continue ;;
      esac
    fi
    _ro_w=$_ro_l
    while [[ $_ro_w == *pid=* ]]; do
      _ro_w=${_ro_w#*pid=}
      _ro_p=${_ro_w%%[!0-9]*}
      in_words "$_ro_p" "$_ro_pids" || _ro_pids="$_ro_pids $_ro_p"
    done
  done <<<"$_ro_out"
  if in_words "$_ro_pid" "$_ro_pids"; then return 0; fi
  if [ -n "$_ro_pids" ]; then
    REDIS_WHY="$_ro_at is process$_ro_pids's (ss), and $1's main process is $_ro_pid: give its address in its file or its unit's own arguments"
  else
    REDIS_WHY="nothing listens at $_ro_at (ss), and $1's main process is $_ro_pid: give its address in its file or its unit's own arguments"
  fi
  return 1
}

# Whether a reply is Redis refusing the login, or the command to the user
# it logged in as, with REDIS_WHY saying which. redis-cli exits 0 on each:
# NOAUTH, WRONGPASS or NOPERM on stdout, and a failed AUTH on stderr, which
# CAP_ERR holds (measured on 7.0).
redis_refused() {  # <unit> <command> <its stdout>
  local _rr=${3%%$'\n'*} _ra
  _rr=${_rr%$'\r'}
  case $CAP_ERR in "AUTH failed"*) _rr=$CAP_ERR ;; esac
  case $_rr in
    NOPERM*)
      redis_as _ra
      REDIS_WHY="$1 refused $2 to $_ra ($_rr): give that user the command in Redis's ACL, or name one that has it" ;;
    NOAUTH* | WRONGPASS* | "AUTH failed"*)
      case $REDIS_LOGIN in
        key) REDIS_WHY="$1 refused $2 to the login as $REDIS_USER ($_rr): check its key file, $REDIS_KEY" ;;
        none) REDIS_WHY="$1 refused $2 without a login ($_rr), and its aclfile sets the users, so its requirepass isn't one to try: give its datastore line a user and key file (datastore redis <unit> <user> <key-file>), or cover it with a backup line" ;;
        *) REDIS_WHY="$1 refused $2 to the login as default, with its file's requirepass ($_rr): give its datastore line a user and key file (datastore redis <unit> <user> <key-file>), or cover it with a backup line" ;;
      esac ;;
    *) return 1 ;;
  esac
}

# Whether redis_cli can log in as the knob's user: its key file is
# readable as root. 0 where the login is another kind.
redis_key_ok() {
  [ "$REDIS_LOGIN" = key ] || return 0
  if ! as_root test -r "$REDIS_KEY"; then
    REDIS_WHY="its key file $REDIS_KEY can't be read as root"
    return 1
  fi
}

# As root, so a socket only redis and root can open, as unixsocketperm 700
# makes it, is reached too. The password goes from its file into
# REDISCLI_AUTH inside root's own sh, never through a process of the
# invoking user's: the key file's, decrypted by systemd-creds where it's an
# encrypted credential, or requirepass's.
# The script runs as root, in sh: its expansions are its own.
# shellcheck disable=SC2016
redis_cli() {  # <command>...
  local -a _ru=()
  if [ "$REDIS_LOGIN" = key ]; then _ru=(--user "$REDIS_USER"); fi
  as_root sh -c 'c=$1 s=$2 m=$3 k=$4 d=$5
shift 5
p=""
case $m in
  key)
    case $k in
      "$d"*) p=$(systemd-creds decrypt "$k" - 2>/dev/null) ;;
      *) p=$(cat -- "$k" 2>/dev/null) ;;
    esac ;;
  conf)
    if [ -n "$c" ]; then
      # An absolute path, so no --: BSD sed reads it as a file.
      p=$(sed "$s" "$c" 2>/dev/null | tail -n 1)
    fi ;;
esac
if [ -n "$p" ]; then
  REDISCLI_AUTH=$p
  export REDISCLI_AUTH
fi
exec redis-cli "$@"' sh "$REDIS_CONF" "$REDIS_PW_SED" "$REDIS_LOGIN" "$REDIS_KEY" "$REDIS_CREDSTORE" ${_ru[@]+"${_ru[@]}"} ${REDIS_ARGS[@]+"${REDIS_ARGS[@]}"} "$@"
}
