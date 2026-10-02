#!/usr/bin/env bash
# recovery-point.sh — take a run's recovery point as root, and write the
# record apply.sh's bulk reads.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash recovery-point.sh --retain-until YYYY-MM-DD [--approve] [--run DIR]
                              [--personal-data NAME]... [--dump]
                              [--redis-within SECONDS]
                              [--config FILE] [--host NAME] [--today YYYY-MM-DD]

Takes the recovery point in references/run.md section 2 for each datastore
the knob declares, and writes its record, recovery-point, into the run's
directory. Until every check passes it changes nothing, and prints why.

  The host's own backup regime first: a backup unit the knob declares whose
  last run succeeded is started, and must succeed again. It writes off the
  node itself, so it stands in for every dump. --dump takes dumps instead.

  Otherwise a dump of each declared Postgres database (pg_dump -Fc) and of
  each Redis (BGSAVE, then a copy of its RDB file), written as root at mode
  600. A dump counts only when pg_dump exited 0, pg_restore --list reads it,
  a full read (pg_restore -f /dev/null) does too, and its mode is 600:
  --list alone passes a dump cut off after its table of contents. An RDB
  copy counts when BGSAVE succeeded, the copy exited 0, redis-check-rdb
  reads it where it's installed, and its mode is 600.

  Each cluster's roles (pg_dumpall --globals-only) stay on the node at mode
  600: they hold password hashes, so they're never copied off it or attested.

Each dump's sha256 is printed for the owner, who copies the dump off the node
and checks their copy against it before the apply. Nothing here restarts a
data store. A recovery point takes minutes: start it where nothing cuts it
off, in the background, and read its JSON when it ends.

Options:
  --retain-until DATE      when the owner deletes these files (required: every
                           recovery-point file has a stated retention)
  --approve                the owner's approval, given in the host's own
                           session
  --run DIR                the run's directory, an absolute path (default:
                           /var/backups/patching-hosts-<UTC>). Pass the same
                           one to apply.sh
  --personal-data NAME     a database, or a Redis unit, whose dump holds
                           personal data; the record flags it. Repeatable
  --dump                   dump, even where a backup regime would stand in
  --redis-within SECONDS   how long a BGSAVE may take (default 300)
  --config FILE            the knob (default: .skills/patching-hosts at the
                           repo root, or in the current directory)
  --host NAME              whose knob sections apply (default: `hostname`)
  --today DATE             the date exceptions expire against (default:
                           today, UTC)
  -h, --help               show this help

It refuses (exit 3) without --approve; on a report-only host; without root;
when the knob declares no datastore; once the run's bulk has started; when a
cluster or a database can't be found, or a Redis can't be reached; and when
the run's filesystem has less free space than the data it would dump.

The record, one line each (run.md section 2):
  began <epoch seconds>    retain <date>
  dump postgres <unit> <database> <sha256> <path>
  dump redis <unit> <sha256> <path>
  backup <unit>            local <path>            personal <path>

Output: one JSON object on stdout. Keys: recovery_point, refused, gate, then
what it did: backup, dumps, local, verdict and next.

Exit codes:
  0  the recovery point is taken and recorded
  1  a dump or the backup failed: nothing was recorded
  2  usage error, an unreadable knob, or a library missing
  3  refused: nothing was changed
USAGE
}

approve=0 run="" retain="" config="" host="" today="" force_dump=0 redis_within=300
personal=()
while [ "$#" -gt 0 ]; do
  case $1 in
    --run | --retain-until | --personal-data | --redis-within | --config | --host | --today)
      [ "$#" -ge 2 ] || { echo "ERROR $1 needs a value" >&2; exit 2; }
      case $1 in
        --run) run=$2 ;;
        --retain-until) retain=$2 ;;
        --personal-data) personal+=("$2") ;;
        --redis-within) redis_within=$2 ;;
        --config) config=$2 ;;
        --host) host=$2 ;;
        --today) today=$2 ;;
      esac
      shift 2 ;;
    --approve) approve=1; shift ;;
    --dump) force_dump=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1 (see --help)" >&2; exit 2 ;;
  esac
done

date_re='^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$'
if [ -z "$retain" ]; then
  echo "ERROR --retain-until is required: every recovery-point file has a stated retention (run.md section 2)" >&2
  exit 2
fi
if ! [[ $retain =~ $date_re ]]; then
  echo "ERROR --retain-until takes a date, YYYY-MM-DD" >&2
  exit 2
fi
for _v in "$run" "$config" ${personal[@]+"${personal[@]}"}; do
  case $_v in *[[:cntrl:]]* | *[[:space:]]*)
    echo "ERROR an argument holds a space or a control character" >&2
    exit 2 ;;
  esac
done
case $run in
  "" | /*) ;;
  *) echo "ERROR --run takes an absolute path" >&2; exit 2 ;;
esac
case $redis_within in
  '' | *[!0-9]* | 0) echo "ERROR --redis-within takes a number of seconds, 1 or more" >&2; exit 2 ;;
esac

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
for _lib in _knob-lib.sh _probe-lib.sh _gate-lib.sh; do
  if [ -z "$_libdir" ] || [ ! -f "$_libdir/$_lib" ]; then
    echo "ERROR $_lib not found next to $_self" >&2
    exit 2
  fi
done
# shellcheck source=_knob-lib.sh
. "$_libdir/_knob-lib.sh"
# shellcheck source=_probe-lib.sh
. "$_libdir/_probe-lib.sh"
ME=recovery-point
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
# unit_show sets these by name.
U_Result="" U_ExecMainStartTimestamp="" U_ExecMainExitTimestamp="" U_LoadState="" U_Triggers=""

[ -n "$run" ] || default_run run
stamp=""
iso_utc stamp "$P_NOW"
stamp=${stamp//[-:]/}

# --- the gate -------------------------------------------------------------------
# No function here ends on a bare `[ … ] && …`: a function that returns
# non-zero stops the script under errexit, wherever it is called plainly.
J_GATE="" J_BACKUP=null J_DUMPS=null J_LOCAL=null J_VERDICT=null
NEXT=()

# The datastores, one entry each: "postgres <unit> <port> <database>" per
# database, "redis <unit>" per Redis. Sizes in bytes, in the same order.
DS=() DS_BYTES=() PG_UNITS="" PG_UNIT_PORT=() BACKUP_SVC=""

gate_host() {
  local why t r db
  local -a f=() dbs=()
  [ "$approve" -eq 1 ] ||
    refuse "no --approve: the owner approves the recovery point in the host's own session (run.md, Approvals)"
  for why in ${KNOB_REPORT_ONLY_WHY[@]+"${KNOB_REPORT_ONLY_WHY[@]}"}; do
    refuse "report-only: $why"
  done
  if [ "$P_PRIV" = none ]; then
    refuse "no root: run recovery-point.sh as root, or as a user sudo -n lets through"
  fi
  if [ "${#KNOB_DATASTORE[@]}" -eq 0 ]; then
    refuse "the knob declares no datastore, so there's nothing to dump: a host with none needs only its before-versions, which apply.sh records"
  fi
  for t in sha256sum systemctl; do
    have "$t" || refuse "$t isn't on PATH"
  done
  for r in ${KNOB_DATASTORE[@]+"${KNOB_DATASTORE[@]}"}; do
    IFS=$KNOB_US read -r -a f <<<"$r"
    if [ "${f[0]}" = postgres ]; then
      for t in pg_lsclusters pg_dump pg_dumpall pg_restore runuser; do
        have "$t" || refuse "$t isn't on PATH, and the knob declares a Postgres datastore"
      done
    else
      have redis-cli || refuse "redis-cli isn't on PATH, and the knob declares a Redis datastore"
    fi
  done
  for t in ${personal[@]+"${personal[@]}"}; do
    r=0
    for why in ${KNOB_DATASTORE[@]+"${KNOB_DATASTORE[@]}"}; do
      IFS=$KNOB_US read -r -a f <<<"$why"
      read -r -a dbs <<<"${f[2]:-}" || true
      unit_name db "${f[1]}"
      if [ "$t" = "${f[1]}" ] || [ "$t" = "$db" ] || in_words "$t" "${dbs[*]-}"; then r=1; fi
    done
    [ "$r" -eq 1 ] || refuse "--personal-data $t names no database or Redis unit the knob declares"
  done
}

gate_run() {
  local mode
  [ "$P_PRIV" != none ] || return 0
  root_has "$run" || return 0
  file_mode mode "$run"
  [ "$mode" = 0700 ] || refuse "$run is mode ${mode:-unknown}, not 0700: a run's records are root-only"
  if root_has "$run/holds"; then
    refuse "$run's bulk already started: a recovery point comes before it. Take one for a new run"
  fi
}

# The host's own backup regime, where the knob declares one whose last run
# succeeded: a unit, or the service a declared timer starts.
gate_backup() {
  local r u svc o="" why=""
  local -a f=()
  for r in ${KNOB_BACKUP[@]+"${KNOB_BACKUP[@]}"}; do
    IFS=$KNOB_US read -r -a f <<<"$r"
    unit_name u "${f[0]}"
    svc=$u
    case $u in
      *.timer)
        svc=""
        if unit_show "$u" Triggers; then svc=${U_Triggers%% *}; fi ;;
    esac
    if [ -z "$svc" ]; then
      why="$u starts no unit that could be read"
    elif ! unit_show "$svc" LoadState Result ExecMainExitTimestamp; then
      why="$svc couldn't be read"
    elif [ "$U_LoadState" != loaded ]; then
      why="$svc is ${U_LoadState:-unknown}, not loaded"
    elif [ "$U_Result" != success ] || [ -z "${U_ExecMainExitTimestamp#@}" ]; then
      why="$svc's last run ended in ${U_Result:-nothing}, so it isn't one to rely on"
    else
      BACKUP_SVC=$svc
      break
    fi
  done
  if [ "$force_dump" -eq 1 ]; then BACKUP_SVC=""; fi
  jaddsn o unit "$BACKUP_SVC"
  if [ "${#KNOB_BACKUP[@]}" -eq 0 ]; then
    why="the knob declares no backup unit"
  elif [ "$force_dump" -eq 1 ]; then
    why="--dump"
  fi
  if [ -n "$BACKUP_SVC" ]; then why=""; fi
  jaddsn o not_used "$why"
  jadd J_GATE backup_regime "{$o}"
}

# A database's size, as postgres. psql substitutes a variable only in what
# it reads, never in -c's string (measured on 16), so the query comes in on
# stdin, with the name quoted by psql itself.
pg_size() {  # <port> <database>
  printf '%s\n' "select pg_database_size(datname) from pg_database where datname = :'db';" |
    as_user postgres psql -XAtq -p "$1" -d postgres -v "db=$2"
}

# What each dump would hold, and whether the run's filesystem has room for
# it: a full disk mid-dump can stop the data store it shares the disk with.
gate_datastores() {
  local r u port db out sz e a="" need=0 avail="" dir
  local -a f=() dbs=()
  for r in ${KNOB_DATASTORE[@]+"${KNOB_DATASTORE[@]}"}; do
    IFS=$KNOB_US read -r -a f <<<"$r"
    unit_name u "${f[1]}"
    if [ "${f[0]}" = postgres ]; then
      port=""
      if ! pg_port port "$u"; then
        refuse "datastore postgres $u: $PG_WHY"
        continue
      fi
      PG_UNITS="$PG_UNITS $u" PG_UNIT_PORT+=("$port")
      # A backup regime stands in for the dumps: only the roles' ports count.
      [ -z "$BACKUP_SVC" ] || continue
      read -r -a dbs <<<"${f[2]}"
      for db in "${dbs[@]}"; do
        capture out pg_size "$port" "$db"
        sz=""
        if [ "$CAP_RC" -eq 0 ] && is_int "$out"; then sz=$out; fi
        e=""
        jadds e datastore "postgres $u $db"
        jaddn e bytes "$sz"
        jpush a "{$e}"
        if [ -z "$sz" ]; then
          refuse "datastore postgres $u: database $db isn't in the cluster, or its size couldn't be read${CAP_ERR:+ ($CAP_ERR)}"
          continue
        fi
        DS+=("postgres $u $port $db") DS_BYTES+=("$sz")
        need=$((need + sz))
      done
    elif [ -z "$BACKUP_SVC" ]; then
      # Raw replies, since stdout isn't a terminal: the key, then its value.
      redis_conn "$u"
      dir="" sz=""
      capture out redis_cli CONFIG GET dir
      [ "$CAP_RC" -ne 0 ] || dir=$(printf '%s\n' "$out" | sed -n '2p')
      capture out redis_cli CONFIG GET dbfilename
      [ "$CAP_RC" -ne 0 ] || dir="$dir/$(printf '%s\n' "$out" | sed -n '2p')"
      case $dir in
        /*/*.rdb)
          # The script runs as root, in sh: its expansion is its own.
          # shellcheck disable=SC2016
          capture out as_root sh -c 'wc -c <"$1"' sh "$dir"
          words_of sz "$out"
          is_int "$sz" || sz=0 ;;
        *) dir="" ;;
      esac
      e=""
      jadds e datastore "redis $u"
      jaddsn e rdb "$dir"
      jaddn e bytes "$sz"
      jpush a "{$e}"
      if [ -z "$dir" ]; then
        refuse "datastore redis $u: redis-cli ${REDIS_ARGS[*]} couldn't say where its RDB file is (CONFIG GET dir and dbfilename)"
        continue
      fi
      DS+=("redis $u $dir") DS_BYTES+=("$sz")
      need=$((need + sz))
    fi
  done
  jadd J_GATE datastores "[$a]"
  if [ -n "$BACKUP_SVC" ]; then return 0; fi
  dir=$run
  while [ ! -d "$dir" ] && [ "$dir" != / ]; do dir=$(dirname "$dir"); done
  out=$(df -Pk -- "$dir" 2>/dev/null | awk 'NR == 2 { print $4 }') || out=""
  is_int "$out" && avail=$out
  e=""
  jaddn e need_kib "$(((need + 1023) / 1024))"
  jaddn e free_kib "$avail"
  jadds e on "$dir"
  jadd J_GATE space "{$e}"
  if [ -z "$avail" ]; then
    refuse "the free space under $dir couldn't be read"
  elif [ "$avail" -lt $(((need + 1023) / 1024)) ]; then
    refuse "$dir has $avail KiB free, and the data would take up to $(((need + 1023) / 1024)) KiB: a full disk mid-dump can stop a data store on it"
  fi
}

emit() {
  local o="" a="" r
  jadds a run "$run"
  jadds a record "$run/recovery-point"
  jaddb a approved "$approve"
  jadds a retain_until "$retain"
  jadds a host "$host"
  jadds a knob "$config"
  jadd o recovery_point "{$a}"
  a=""
  for r in ${REFUSED[@]+"${REFUSED[@]}"}; do jpushs a "$r"; done
  jadd o refused "[$a]"
  jadd o gate "{$J_GATE}"
  jadd o backup "$J_BACKUP"
  jadd o dumps "$J_DUMPS"
  jadd o local "$J_LOCAL"
  jadd o verdict "$J_VERDICT"
  a=""
  for r in ${NEXT[@]+"${NEXT[@]}"}; do jpushs a "$r"; done
  jadd o next "[$a]"
  printf '{%s}\n' "$o"
}

gate_host
gate_run
gate_backup
gate_datastores

if [ "${#REFUSED[@]}" -gt 0 ]; then
  for _r in "${REFUSED[@]}"; do echo "recovery-point: refused: $_r" >&2; done
  emit
  exit 3
fi

# --- the recovery point -----------------------------------------------------------
# From here on files are written. A failure is recorded, and no record is
# written, so apply.sh's bulk refuses until a whole one is.

REC_LINES="began $P_NOW"$'\n'"retain $retain"$'\n'
PERSONAL_PATHS=""

is_personal() {  # <unit> <database, or empty for Redis>
  local _p _u
  for _p in ${personal[@]+"${personal[@]}"}; do
    unit_name _u "$_p"
    if [ -n "$2" ]; then
      if [ "$_p" = "$2" ]; then return 0; fi
    elif [ "$_u" = "$1" ]; then
      return 0
    fi
  done
  return 1
}

file_sha() {  # <var> <path>
  local _fs=""
  capture _fs as_root sha256sum -- "$2"
  _fs=${_fs%% *}
  [[ $_fs =~ $sha_re ]] || _fs=""
  printf -v "$1" '%s' "$_fs"
}
sha_re='^[0-9a-f]{64}$'

take_backup() {
  local o="" s x iso ok=0
  echo "recovery-point: starting $BACKUP_SVC, the host's own backup regime" >&2
  if ! as_root systemctl start -- "$BACKUP_SVC"; then
    fail "systemctl start $BACKUP_SVC failed: read its journal. Run again with --dump to take dumps instead"
  fi
  s="" x=""
  if unit_show "$BACKUP_SVC" Result ExecMainStartTimestamp ExecMainExitTimestamp; then
    s=${U_ExecMainStartTimestamp#@} x=${U_ExecMainExitTimestamp#@}
  fi
  jadds o unit "$BACKUP_SVC"
  jaddsn o result "$U_Result"
  iso_utc iso "$s"
  jaddsn o started "$iso"
  iso_utc iso "$x"
  jaddsn o finished "$iso"
  if [ "${#FAILED[@]}" -gt 0 ]; then
    :
  elif ! is_int "$s" || [ "$s" -lt "$P_NOW" ]; then
    fail "$BACKUP_SVC didn't start a run now: its last run started ${iso:-never}"
  elif ! is_int "$x" || [ "$x" -lt "$s" ]; then
    fail "$BACKUP_SVC hasn't finished the run it started: a backup unit whose start returns early isn't one apply.sh can wait on. Run again with --dump"
  elif [ "$U_Result" != success ]; then
    fail "$BACKUP_SVC's run ended in ${U_Result:-an unknown result}: read its journal. Run again with --dump to take dumps instead"
  else
    ok=1
  fi
  jaddb o ok "$ok"
  J_BACKUP="{$o}"
  [ "$ok" -eq 0 ] || REC_LINES="${REC_LINES}backup $BACKUP_SVC"$'\n'
}

# pg_dump runs as postgres, its output opened by root's own sh at mode 600:
# one stage, so its exit status is the pipeline's.
# The script runs as root, in sh: its expansions are its own.
# shellcheck disable=SC2016
pg_dump_to() {  # <port> <database> <path>
  as_root sh -c 'umask 077; cd / && exec runuser -u postgres -- pg_dump -Fc -p "$1" -d "$2" >"$3"' sh "$@"
}
# The script runs as root, in sh: its expansions are its own.
# shellcheck disable=SC2016
pg_globals_to() {  # <port> <path>
  as_root sh -c 'umask 077; cd / && exec runuser -u postgres -- pg_dumpall --globals-only -p "$1" >"$2"' sh "$@"
}

DUMPS_A="" LOCAL_A=""
dump_postgres() {  # <unit> <port> <database>
  local u=$1 port=$2 db=$3 path rc lrc frc mode sha="" e="" ok=0 t0 safe
  safe=${db//[!A-Za-z0-9._-]/_}
  path=$run/${u%.service}-$safe-$stamp.dump
  echo "recovery-point: dumping $db from $u into $path" >&2
  t0=$SECONDS
  rc=0
  pg_dump_to "$port" "$db" "$path" || rc=$?
  lrc="" frc=""
  if [ "$rc" -eq 0 ]; then
    lrc=0
    as_root pg_restore --list -- "$path" >/dev/null 2>&1 || lrc=$?
  fi
  # --list reads only the table of contents, which a custom-format dump
  # written to a pipe puts first: a dump cut off mid-data still lists.
  if [ "$lrc" = 0 ]; then
    frc=0
    as_root pg_restore -f /dev/null -- "$path" >/dev/null 2>&1 || frc=$?
  fi
  root_mode mode "$path"
  if [ "$frc" = 0 ] && [ "$mode" = 0600 ]; then file_sha sha "$path"; fi
  jadds e datastore "postgres $u $db"
  jadds e path "$path"
  jaddn e pg_dump_exit "$rc"
  jaddn e list_exit "$lrc"
  jaddn e full_read_exit "$frc"
  jaddsn e mode "$mode"
  jaddsn e sha256 "$sha"
  jaddn e seconds "$((SECONDS - t0))"
  if [ "$rc" -ne 0 ]; then
    fail "pg_dump of $db ($u) exited $rc"
  elif [ "$lrc" != 0 ]; then
    fail "pg_restore --list can't read the dump of $db ($u): exit $lrc"
  elif [ "$frc" != 0 ]; then
    fail "the dump of $db ($u) lists, but a full read fails (exit $frc): it's cut off after its table of contents"
  elif [ "$mode" != 0600 ]; then
    fail "the dump of $db ($u) is mode ${mode:-unknown}, not 0600"
  elif [ -z "$sha" ]; then
    fail "the dump of $db ($u) couldn't be hashed"
  else
    ok=1
    REC_LINES="${REC_LINES}dump postgres $u $db $sha $path"$'\n'
    if is_personal "$u" "$db"; then PERSONAL_PATHS="$PERSONAL_PATHS $path"; fi
  fi
  jaddb e ok "$ok"
  if is_personal "$u" "$db"; then jaddb e personal_data 1; else jaddb e personal_data 0; fi
  jpush DUMPS_A "{$e}"
}

dump_globals() {  # <unit> <port>
  local u=$1 port=$2 path rc=0 mode e="" ok=0
  path=$run/${u%.service}-globals-$stamp.sql
  pg_globals_to "$port" "$path" || rc=$?
  root_mode mode "$path"
  jadds e path "$path"
  jadds e holds "the roles of $u, with their password hashes: it stays on the node"
  jaddn e exit "$rc"
  jaddsn e mode "$mode"
  if [ "$rc" -ne 0 ]; then
    fail "pg_dumpall --globals-only for $u exited $rc"
  elif [ "$mode" != 0600 ]; then
    fail "the roles of $u went to a file of mode ${mode:-unknown}, not 0600"
  else
    ok=1
    REC_LINES="${REC_LINES}local $path"$'\n'
  fi
  jaddb e ok "$ok"
  jpush LOCAL_A "{$e}"
}

# BGSAVE, then a copy of the file it wrote, once LASTSAVE moves past the
# time it was asked and the save reports ok.
# The script runs as root, in sh: its expansions are its own.
# shellcheck disable=SC2016
copy_root() { as_root sh -c 'umask 077; cat -- "$1" >"$2"' sh "$1" "$2"; }

dump_redis() {  # <unit> <rdb>
  local u=$1 rdb=$2 path t0 now="" out line st="" busy="" crc="" rrc="" mode sha="" e="" ok=0 w0 n=0
  path=$run/${u%.service}-$stamp.rdb
  redis_conn "$u"
  echo "recovery-point: BGSAVE on $u, then a copy into $path" >&2
  w0=$SECONDS
  capture out redis_cli LASTSAVE
  t0=$out
  is_int "$t0" || t0=""
  line=${out:-${CAP_ERR:-no reply}}
  capture out redis_cli BGSAVE
  case $out in
    *"Background saving started"* | *"already in progress"* | *scheduled*) ;;
    *) out="BGSAVE: ${out:-${CAP_ERR:-no reply}}" ;;
  esac
  while [ -n "$t0" ]; do
    capture out redis_cli INFO persistence
    busy="" st="" now=""
    while IFS= read -r line; do
      line=${line%$'\r'}
      case $line in
        rdb_bgsave_in_progress:*) busy=${line#*:} ;;
        rdb_last_bgsave_status:*) st=${line#*:} ;;
        rdb_last_save_time:*) now=${line#*:} ;;
      esac
    done <<<"$out"
    if [ "$busy" = 0 ] && is_int "$now" && [ "$now" -gt "$t0" ]; then break; fi
    if [ $((SECONDS - w0)) -ge "$redis_within" ]; then st=timeout; break; fi
    n=$((n + 1))
    sleep 1
  done
  if [ "$st" = ok ]; then
    crc=0
    copy_root "$rdb" "$path" || crc=$?
  fi
  if [ "$crc" = 0 ] && have redis-check-rdb; then
    rrc=0
    as_root redis-check-rdb "$path" >/dev/null 2>&1 || rrc=$?
  fi
  root_mode mode "$path"
  if [ "$crc" = 0 ] && [ "${rrc:-0}" = 0 ] && [ "$mode" = 0600 ]; then file_sha sha "$path"; fi
  jadds e datastore "redis $u"
  jadds e path "$path"
  jaddsn e bgsave "${st:-unknown}"
  jaddn e copy_exit "$crc"
  jaddn e check_exit "$rrc"
  jaddsn e mode "$mode"
  jaddsn e sha256 "$sha"
  jaddn e seconds "$((SECONDS - w0))"
  if [ -z "$t0" ]; then
    fail "redis-cli ${REDIS_ARGS[*]} LASTSAVE answered \"$line\", not a time, so a BGSAVE couldn't be told from an old save"
  elif [ "$st" != ok ]; then
    fail "the BGSAVE on $u didn't end ok (${st:-unknown}) within $redis_within s"
  elif [ "$crc" != 0 ]; then
    fail "the copy of $rdb exited $crc"
  elif [ -n "$rrc" ] && [ "$rrc" != 0 ]; then
    fail "redis-check-rdb can't read the copy of $u's RDB file: exit $rrc"
  elif [ "$mode" != 0600 ]; then
    fail "the copy of $u's RDB file is mode ${mode:-unknown}, not 0600"
  elif [ -z "$sha" ]; then
    fail "the copy of $u's RDB file couldn't be hashed"
  else
    ok=1
    REC_LINES="${REC_LINES}dump redis $u $sha $path"$'\n'
    if is_personal "$u" ""; then PERSONAL_PATHS="$PERSONAL_PATHS $path"; fi
  fi
  jaddb e ok "$ok"
  if is_personal "$u" ""; then jaddb e personal_data 1; else jaddb e personal_data 0; fi
  jpush DUMPS_A "{$e}"
}

if ! root_has "$run" && ! as_root mkdir -p -m 700 -- "$run"; then
  fail "$run couldn't be made"
fi
if [ "${#FAILED[@]}" -eq 0 ]; then
  if [ -n "$BACKUP_SVC" ]; then
    take_backup
  else
    for _i in ${DS[@]+"${!DS[@]}"}; do
      read -r _k _u _p _d <<<"${DS[$_i]}"
      if [ "$_k" = postgres ]; then dump_postgres "$_u" "$_p" "$_d"; else dump_redis "$_u" "$_p"; fi
    done
    J_DUMPS="[$DUMPS_A]"
  fi
  # The roles, on the node, whichever way the data left it.
  for _i in ${PG_UNIT_PORT[@]+"${!PG_UNIT_PORT[@]}"}; do
    read -r -a _units <<<"$PG_UNITS"
    dump_globals "${_units[$_i]}" "${PG_UNIT_PORT[$_i]}"
  done
  J_LOCAL="[$LOCAL_A]"
fi

for _p in $PERSONAL_PATHS; do REC_LINES="${REC_LINES}personal $_p"$'\n'; done
if [ "${#FAILED[@]}" -eq 0 ]; then
  printf '%s' "$REC_LINES" | root_write "$run/recovery-point" ||
    fail "$run/recovery-point couldn't be written"
fi

_o="" _a=""
for _r in ${FAILED[@]+"${FAILED[@]}"}; do jpushs _a "$_r"; done
if [ "${#FAILED[@]}" -eq 0 ]; then jaddb _o ok 1; else jaddb _o ok 0; fi
jadd _o why "[$_a]"
J_VERDICT="{$_o}"
if [ "${#FAILED[@]}" -gt 0 ]; then
  NEXT+=("Nothing was recorded, so apply.sh's bulk refuses: fix what failed, then take the recovery point again. The files written so far are under dumps and local: delete them, or keep them to $retain.")
elif [ -n "$BACKUP_SVC" ]; then
  NEXT+=("Confirm the object $BACKUP_SVC wrote off the node, then name it to the bulk: --offnode-object <its name>.")
else
  NEXT+=("Copy each dump off the node with your own scp, and check your copy's sha256 against the one here before the apply.")
  NEXT+=("Then name each copy that checks out to the bulk: --offnode-sha256 <your copy's sha256>, once per dump.")
fi
if [ "${#FAILED[@]}" -eq 0 ]; then
  NEXT+=("bash \"$_libdir/apply.sh\" --approve --step bulk --run \"$run\" --dry-run <DIR>: approval 2")
  NEXT+=("Delete every file in $run on $retain, the retention stated here.")
fi
emit
[ "${#FAILED[@]}" -eq 0 ] || exit 1
exit 0
