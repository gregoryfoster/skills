#!/usr/bin/env bash
# reboot-chain.sh — write a run's reboot chain as a root script, and launch
# it detached, so the operator's disconnect can't cut it off.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash reboot-chain.sh --run DIR [--approve] [--delay SECONDS]
                            [--expect SECONDS] [--config FILE] [--host NAME]
                            [--today YYYY-MM-DD]

Writes the reboot chain in references/run.md section 5 into the run's
directory, as a 0700 root script, and launches it detached:
  systemd-run --on-active=DELAY --timer-property=AccuracySec=1s
By default the transient timer fired 41 s late. Without --approve it changes
nothing, and prints the chain: every command it would run, the knob's
inflight commands verbatim, so the owner approves exactly what runs
(approval 3(b)).

The chain, logged to the run's reboot-chain.log, root's only:
  1. the gate again: no package manager running, and every inflight command
     prints 0, run as the user recorded here, never as root. Otherwise it
     stops nothing and ends;
  2. stop each restarter, then each service;
  3. a checkpoint, then stop each data store (Postgres: CHECKPOINT; Redis:
     SAVE first when it has no save points);
  4. journalctl --sync;
  5. copy the volatile journal into the run, last, so it holds every stop
     line, and read it back: it's the only record of the shutdown. A
     persistent journal survives the boot, so it isn't copied: a copy would
     land on the disk the data stores boot from;
  6. sync, then systemctl reboot. In-guest only: a platform restart is a
     hard reset.
After a stop, nothing aborts it: the host comes back with what it stopped.

Options:
  --run DIR          the run's directory, an absolute path (required)
  --approve          the owner's approval of the reboot, 3(b), given in the
                     host's own session
  --delay SECONDS    the seconds from reboot-chain.sh's start to the chain's
                     (default 120). The gate's own time comes out of it, so
                     the chain starts where its span was gated from
  --expect SECONDS   how long the boot and the post-boot checks take
                     (default 600). The span is the delay plus this
  --config FILE      the knob (default: .skills/patching-hosts at the repo
                     root, or in the current directory)
  --host NAME        whose knob sections apply (default: `hostname`)
  --today DATE       the date exceptions expire against (default: today, UTC)
  -h, --help         show this help

It refuses (exit 3) without --approve; on a report-only host; without root;
when the run aborted at a step; while the run's chain is scheduled or
running, or once one ran and didn't end in ABORT (an aborted one stopped
nothing, and may go again); when the span isn't wholly inside one window or
meets a quiet range; while a package manager runs or an inflight command
prints anything but 0; and when a datastore's cluster can't be found, or a
running Redis's address reaches another process.

Output: one JSON object on stdout. Keys: reboot_chain, refused, gate, chain
(its lines), launched, tmp_staged (what the boot will empty), next.

Exit codes:
  0  the chain is launched
  1  systemd-run failed, or the gate took the whole delay: nothing is
     scheduled
  2  usage error, an unreadable knob, or a library missing
  3  refused: nothing was changed
USAGE
}

approve=0 run="" config="" host="" today="" delay=120 expect=600
while [ "$#" -gt 0 ]; do
  case $1 in
    --run | --delay | --expect | --config | --host | --today)
      [ "$#" -ge 2 ] || { echo "ERROR $1 needs a value" >&2; exit 2; }
      case $1 in
        --run) run=$2 ;;
        --delay) delay=$2 ;;
        --expect) expect=$2 ;;
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

if [ -z "$run" ]; then
  echo "ERROR --run DIR is required: the chain, its log and the journal copy go in the run's directory" >&2
  exit 2
fi
case $run in
  /*) ;;
  *) echo "ERROR --run takes an absolute path" >&2; exit 2 ;;
esac
case $run$config in *[[:cntrl:]]*)
  echo "ERROR an argument holds a control character" >&2
  exit 2 ;;
esac
for _v in "$delay" "$expect"; do
  case $_v in
    '' | *[!0-9]* | 0) echo "ERROR --delay and --expect take a number of seconds, 1 or more" >&2; exit 2 ;;
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
ME=reboot-chain
# shellcheck source=_gate-lib.sh
. "$_libdir/_gate-lib.sh"

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

stamp=""
iso_utc stamp "$P_NOW"
stamp=${stamp//[-:]/}
unit=patching-hosts-reboot-$stamp
script=$run/reboot-chain.sh
log=$run/reboot-chain.log

# --- the gate -------------------------------------------------------------------
# No function here ends on a bare `[ … ] && …`: a function that returns
# non-zero stops the script under errexit, wherever it is called plainly.
J_GATE="" J_LAUNCHED=null
NEXT=()

gate_host() {
  local why t
  [ "$approve" -eq 1 ] ||
    refuse "no --approve: the owner approves the reboot, 3(b), in the host's own session. The chain is below, every command it would run"
  for why in ${KNOB_REPORT_ONLY_WHY[@]+"${KNOB_REPORT_ONLY_WHY[@]}"}; do
    refuse "report-only: $why"
  done
  if [ "$P_PRIV" = none ]; then
    refuse "no root: run reboot-chain.sh as root, or as a user sudo -n lets through"
  fi
  for t in systemd-run systemctl journalctl pgrep runuser; do
    have "$t" || refuse "$t isn't on PATH"
  done
}

gate_run() {
  local mode out s r rest failed="" u l last="" e=""
  [ "$P_PRIV" != none ] || return 0
  if ! root_has "$run"; then
    refuse "$run doesn't exist: the chain belongs to a run, after its last step"
    return 0
  fi
  file_mode mode "$run"
  [ "$mode" = 0700 ] || refuse "$run is mode ${mode:-unknown}, not 0700: a run's records are root-only"
  if root_read out "$run/steps"; then
    while read -r s r rest; do
      [ -n "$s" ] || continue
      [ "$r" = ok ] || failed=$s
    done <<<"$out"
  fi
  if [ -n "$failed" ]; then
    refuse "the run aborted at $failed: no reboot until the owner decides (run.md, Abort branch)"
  fi
  # A chain launched before goes again only where it stopped nothing: its
  # log ends in ABORT, or it never started, since a boot drops a timer that
  # hasn't fired.
  if root_read out "$run/reboot-chain.unit"; then
    u=${out%% *}
    if root_read l "$log"; then last=${l##*$'\n'}; fi
    jadds e unit "$u"
    jaddsn e last_line "$last"
    jadd J_GATE earlier_chain "{$e}"
    if chain_active "$u"; then
      refuse "this run's chain, ${CHAIN_STATE% *}, is ${CHAIN_STATE##* }: it's scheduled or running. Read $log"
    elif [ -n "$last" ] && [[ $last != *" ABORT: "* ]]; then
      refuse "this run's chain, $u, ran and didn't end in ABORT, so it stopped what it stops (its log ends: $last). Read $log"
    fi
  fi
}

gate_packages() {
  local who=""
  package_manager who
  if [ -n "$who" ]; then
    refuse "$who is running: a reboot now could cut it off mid-dpkg. Wait for it to end"
  fi
  jaddsn J_GATE package_manager_running "$who"
}

# Each data store's checkpoint and stop: a Postgres cluster's port, and for
# Redis its address and the file that holds any password.
DS_LINES=()
gate_datastores() {
  local r u port a="" e seen="" rc
  local -a f=()
  for r in ${KNOB_DATASTORE[@]+"${KNOB_DATASTORE[@]}"}; do
    IFS=$KNOB_US read -r -a f <<<"$r"
    unit_name u "${f[1]}"
    in_words "$u" "$seen" && continue
    seen="$seen $u"
    e=""
    jadds e unit "$u"
    if [ "${f[0]}" = postgres ]; then
      port=""
      if ! pg_port port "$u"; then
        refuse "datastore postgres $u: $PG_WHY"
        continue
      fi
      jaddn e port "$port"
      DS_LINES+=("postgres $u $port")
    else
      redis_conn "$u"
      # The chain would check and save another Redis. One that isn't running
      # has nothing to save.
      rc=0
      redis_owned "$u" || rc=$?
      if [ "$rc" -eq 1 ]; then
        refuse "datastore redis $u: $REDIS_WHY"
        continue
      fi
      jadds e address "${REDIS_ARGS[*]}"
      DS_LINES+=("redis $u ${REDIS_CONF:--} ${REDIS_ARGS[*]}")
    fi
    jpush a "{$e}"
  done
  jadd J_GATE datastores "[$a]"
}

emit() {
  local o="" a="" r
  jadds a run "$run"
  jadds a script "$script"
  jadds a log "$log"
  jadds a unit "$unit"
  jaddn a delay_seconds "$delay"
  jaddb a approved "$approve"
  jadds a host "$host"
  jadds a knob "$config"
  jadd o reboot_chain "{$a}"
  a=""
  for r in ${REFUSED[@]+"${REFUSED[@]}"}; do jpushs a "$r"; done
  jadd o refused "[$a]"
  jadd o gate "{$J_GATE}"
  a=""
  while IFS= read -r r; do jpushs a "$r"; done <<<"${CHAIN%$'\n'}"
  jadd o chain "[$a]"
  jadd o launched "$J_LAUNCHED"
  jadd o tmp_staged "$J_TMP"
  a=""
  for r in ${NEXT[@]+"${NEXT[@]}"}; do jpushs a "$r"; done
  jadd o next "[$a]"
  printf '{%s}\n' "$o"
}

# --- the chain ------------------------------------------------------------------
# Written as sh, every value quoted, so the text the owner approves is the
# text that runs. It runs as root, under systemd-run.
CHAIN=""
c() { CHAIN="$CHAIN$*"$'\n'; }

# Single quotes, the log's words too: a unit's name is the knob's, and a
# $( ) in it would run as root.
stop_line() {  # <unit>
  local q m x
  sq q "$1"
  sq m "stop $1"
  sq x "stop $1 failed"
  c "say $m; systemctl stop -- $q || say $x"
}

# The chain is sh text, written literally: its expansions are its own.
# shellcheck disable=SC2016
write_chain() {
  local r q u kind conf rest l cmd user t m x ra pw
  local -a f=() w=()
  sq q "$log"
  c '#!/bin/sh'
  c "# The reboot chain for $host, run $run: approval 3(b)."
  c "# Written by reboot-chain.sh. Every command it runs is below."
  c 'set -u'
  c 'set -f'
  c '# Its log holds journal lines, and a journal can hold secrets.'
  c 'umask 077'
  c "LOG=$q"
  sq q "$run/journal"
  c "JOURNAL=$q"
  c "JOURNAL_DIRS='/run/log/journal'"
  c 'exec >>"$LOG" 2>&1'
  c "say() { printf '%s %s\\n' \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"\$*\"; }"
  c 'abort() { say "ABORT: $*. Nothing was stopped."; exit 1; }'
  c 'say start'
  c ''
  c '# 1. The gate again. No package manager running:'
  sq q "$PKG_RE"
  c "if pgrep -x 'dpkg|apt|apt-get' >/dev/null || pgrep -f $q >/dev/null; then abort 'a package manager is running'; fi"
  user=$P_KNOB_USER
  if [ "${#KNOB_INFLIGHT[@]}" -gt 0 ]; then
    sq u "$user"
    t=""
    if have timeout; then t="timeout -k $KNOB_CMD_KILL_AFTER $KNOB_CMD_TIMEOUT "; fi
    c "# Every inflight command prints 0, run as $user, never as root:"
    for r in "${KNOB_INFLIGHT[@]}"; do
      IFS=$KNOB_US read -r -a f <<<"$r"
      cmd=${f[0]} l=${f[1]}
      sq q "$cmd"
      c "# knob line $l: $cmd"
      c "out=\$(runuser -u $u -- ${t}sh -c $q 2>/dev/null); rc=\$?"
      c 'set -- $out'
      c "if [ \"\$rc\" -ne 0 ] || [ \"\$#\" -ne 1 ] || [ \"\$1\" != 0 ]; then abort \"inflight (knob line $l) exited \$rc and printed: \$*\"; fi"
    done
  fi
  c 'say "gate passed"'
  c ''
  c '# 2. Each restarter, then each service.'
  for r in ${KNOB_RESTARTER[@]+"${KNOB_RESTARTER[@]}"} ${KNOB_SERVICE[@]+"${KNOB_SERVICE[@]}"}; do
    IFS=$KNOB_US read -r -a f <<<"$r"
    unit_name u "${f[0]}"
    stop_line "$u"
  done
  c ''
  c '# 3. A checkpoint, then each data store.'
  for r in ${DS_LINES[@]+"${DS_LINES[@]}"}; do
    # "postgres <unit> <port>", or "redis <unit> <conf or -> <redis-cli words>".
    read -r kind u conf rest <<<"$r"
    if [ "$kind" = postgres ]; then
      # pg_port's port is a number.
      sq m "checkpoint $u"
      c "say $m; runuser -u postgres -- psql -XAtq -p $conf -d postgres -c CHECKPOINT || say \"CHECKPOINT failed: the stop checkpoints anyway\""
    else
      # The address and the socket come from redis.conf, which the redis
      # user can write: each one quoted.
      read -r -a w <<<"$rest"
      ra=""
      for x in ${w[@]+"${w[@]}"}; do
        case $x in -h | -p | -s) ;; *) sq x "$x" ;; esac
        ra="$ra $x"
      done
      if [ "$conf" != - ]; then
        # Read as redis_cli reads it, and as Redis does.
        sq l "$conf"
        sq pw "$REDIS_PW_SED"
        c "REDISCLI_AUTH=\$(sed $pw $l 2>/dev/null | tail -n 1)"
        c '[ -n "$REDISCLI_AUTH" ] && export REDISCLI_AUTH || unset REDISCLI_AUTH'
      else
        # No file to read one from, and the last Redis's isn't this one's.
        c 'unset REDISCLI_AUTH'
      fi
      c "# Its stop saves the RDB file only where save points are set."
      # redis-cli exits 0 on an error reply, and prints it on stdout; an
      # AUTH warning goes to stderr, which is the log (measured on 7.0). So
      # stdout alone says whether the SAVE took.
      sq m "SAVE $u"
      c "if [ -z \"\$(redis-cli$ra CONFIG GET save | sed -n 2p)\" ]; then say $m; reply=\$(redis-cli$ra SAVE); [ \"\$reply\" = OK ] || say \"SAVE failed: \$reply\"; fi"
    fi
    stop_line "$u"
  done
  c ''
  c '# 4.'
  c 'journalctl --sync'
  c ''
  c '# 5. The volatile journal, last, so it holds every stop line, readable by'
  c '# root only. A persistent one, in /var/log/journal, survives the boot, and'
  c '# a copy of it would land on the disk the data stores boot from.'
  c 'install -d -m 700 "$JOURNAL"'
  c 'for d in $JOURNAL_DIRS; do'
  c '  if [ -z "$(ls -A "$d" 2>/dev/null)" ]; then say "$d holds no journal: a persistent one survives the boot"; continue; fi'
  c '  t=$JOURNAL/$(printf %s "$d" | tr / _)'
  c '  if install -d -m 700 "$t" && cp -a "$d/." "$t/" && chmod -R go-rwx "$t" && journalctl -D "$t" -n 5 --no-pager; then'
  c '    say "journal $d copied to $t, and read back"'
  c '  else'
  c '    say "the copy of $d failed: the shutdown has no record of its own"'
  c '  fi'
  c 'done'
  c ''
  c '# 6. In-guest only: a platform restart is a hard reset.'
  c 'sync'
  c 'say reboot'
  c 'systemctl reboot'
}

gate_host
gate_run
gate_span "$((delay + expect))"
gate_packages
gate_datastores
# Last, so its reading is the freshest.
gate_inflight
write_chain

# What the boot will empty: anything staged under /tmp, but this script's
# own scratch directory, which goes when it exits.
J_TMP="" _a=""
while IFS= read -r _f; do
  [ -n "$_f" ] || continue
  [ "$_f" != "$P_TMP" ] || continue
  case ${_f##*/} in systemd-private-* | .*-unix | snap-private-tmp) continue ;; esac
  jpushs _a "$_f"
done < <(find /tmp -mindepth 1 -maxdepth 1 2>/dev/null | sort)
J_TMP="[$_a]"

NEXT+=("After the boot: bash \"$_libdir/probe.sh\" --post-boot --config \"$config\" --host $host (run.md section 6).")
NEXT+=("If $log ends in ABORT, the chain stopped nothing: read why, then run reboot-chain.sh again once the gate would pass.")
NEXT+=("The journal copy in $run/journal is a recovery-point file: delete it with the others, on their retention.")

if [ "${#REFUSED[@]}" -gt 0 ]; then
  for _r in "${REFUSED[@]}"; do echo "reboot-chain: refused: $_r" >&2; done
  emit
  exit 3
fi

# --- the launch ------------------------------------------------------------------
_o="" _rc=0 _fire=$((P_NOW + delay)) _iso="" _now="" _left=""
# An absolute path, so no --: BSD chmod reads it as a file.
if ! printf '%s' "$CHAIN" | root_write "$script" || ! as_root chmod 700 "$script"; then
  fail "$script couldn't be written"
else
  # The span was gated from P_NOW, and every inflight command has run
  # since: the timer gets what's left of the delay, so the chain starts at
  # the time its span was gated from.
  _now=$(date +%s) || _now=""
  is_int "$_now" || _now=$P_NOW
  _left=$((_fire - _now))
  if [ "$_left" -lt 1 ]; then
    fail "the gate took $((_now - P_NOW)) s, the whole --delay of $delay s: nothing is scheduled. Run reboot-chain.sh again"
  else
    as_root systemd-run --unit="$unit" --on-active="$_left" --timer-property=AccuracySec=1s "$script" >&2 || _rc=$?
    [ "$_rc" -eq 0 ] || fail "systemd-run exited $_rc: nothing is scheduled"
  fi
fi
iso_utc _iso "$_fire"
jaddn _o exit "$_rc"
jadds _o unit "$unit"
jaddn _o on_active_seconds "$_left"
if [ "${#FAILED[@]}" -eq 0 ]; then
  jadds _o fires_at "$_iso"
  printf '%s %s\n' "$unit" "$_iso" | root_write "$run/reboot-chain.unit" ||
    fail "$run/reboot-chain.unit couldn't be written: the chain is launched, unrecorded"
else
  jadd _o fires_at null
fi
_a=""
for _r in ${FAILED[@]+"${FAILED[@]}"}; do jpushs _a "$_r"; done
jadd _o why "[$_a]"
J_LAUNCHED="{$_o}"
emit
[ "${#FAILED[@]}" -eq 0 ] || exit 1
exit 0
