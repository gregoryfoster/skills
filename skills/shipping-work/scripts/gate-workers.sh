#!/usr/bin/env bash
# gate-workers.sh
# Decides how many pytest-xdist workers a gate may use, and prints the number.
# 0 means "run serially". The suite's verdict never depends on this answer —
# only its wall clock does — so a gate that cannot use the number (no xdist in
# the venv) runs serially and says so; it never skips a test (#537).
#
# RESOLUTION — first match wins (#537, decision D2)
#
#   1. PYTEST_XDIST_AUTO_NUM_WORKERS — pytest-xdist's own variable, the one
#      `-n auto` reads. A coordinator running N agents on one host is the only
#      party that knows N, so it sets this in each worker's brief: cores / N.
#   2. .skills/test-workers — the project's standing choice: `off`, `auto`, or
#      a number. `off` is for a suite whose tests share a database or a port.
#   3. auto:
#      - 2 cores or fewer -> 0. Every exe.dev VM shares two vCPUs, and a
#        worker pool there competes with the agent driving it.
#      - otherwise min(8, cores / (active gates + 1)), where active gates are
#        the live slot files under <git-common-dir>/gate-slots/. That spreads
#        the cores across concurrent worktrees of one repo when no coordinator
#        is counting. 8 is measured, not guessed: on a 14-core Mac this repo's
#        suite ran 3:10 at -n 6, 2:30 at -n 8 and 2:40 at -n 12.
#      A result under 2 is 0: one xdist worker is serial plus its overhead.
#
# SLOTS
#
#   `--slot-dir` prints (and creates) the slot directory. A caller that is
#   about to run a suite writes its own PID there and removes the file when it
#   finishes; a slot whose PID is gone is stale and is removed when counted.
#
# Usage: bash "<gate-workers.sh>" [--explain | --slot-dir | --help]
set -euo pipefail

MAX_WORKERS=8

usage() {
  echo "Usage: bash \"$0\" [--explain | --slot-dir | --help]"
  echo ""
  echo "Prints how many pytest-xdist workers a gate may use (0 = serial)."
  echo ""
  echo "Resolution, first match wins:"
  echo "  1. PYTEST_XDIST_AUTO_NUM_WORKERS   set by a coordinator, per agent"
  echo "  2. .skills/test-workers            off | auto | <number>"
  echo "  3. auto: 0 on 2 cores or fewer; else min($MAX_WORKERS, cores / (active gates + 1))"
  echo ""
  echo "Options:"
  echo "  --explain   also print the reason for the answer on stderr"
  echo "  --slot-dir  print the slot directory (created if absent) and exit"
  echo ""
  echo "Exit codes:"
  echo "  0  a number was printed"
  echo "  2  a configured value is not a number, off or auto; nothing printed"
}

EXPLAIN=0
SLOT_DIR_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --help) usage; exit 0 ;;
    --explain) EXPLAIN=1 ;;
    --slot-dir) SLOT_DIR_ONLY=1 ;;
    *) echo "ERROR: unknown argument '$arg'" >&2; usage >&2; exit 2 ;;
  esac
done

say() {
  if [[ "$EXPLAIN" -eq 1 ]]; then
    echo "gate-workers: $*" >&2
  fi
}

answer() {
  say "$2"
  echo "$1"
  exit 0
}

is_count() {
  [[ "$1" =~ ^[0-9]+$ ]]
}

slot_dir() {
  local common
  common=$(git rev-parse --git-common-dir 2>/dev/null) || return 1
  mkdir -p "$common/gate-slots"
  (cd "$common/gate-slots" && pwd -P)
}

if [[ "$SLOT_DIR_ONLY" -eq 1 ]]; then
  slot_dir || { echo "ERROR: not inside a git repository — no slot directory" >&2; exit 2; }
  exit 0
fi

# 1. The coordinator's per-agent figure.
if [[ -n "${PYTEST_XDIST_AUTO_NUM_WORKERS:-}" ]]; then
  if ! is_count "$PYTEST_XDIST_AUTO_NUM_WORKERS"; then
    echo "ERROR: PYTEST_XDIST_AUTO_NUM_WORKERS='$PYTEST_XDIST_AUTO_NUM_WORKERS' is not a number" >&2
    exit 2
  fi
  answer "$PYTEST_XDIST_AUTO_NUM_WORKERS" \
    "PYTEST_XDIST_AUTO_NUM_WORKERS=$PYTEST_XDIST_AUTO_NUM_WORKERS (set by the caller)"
fi

# 2. The project's knob. First non-comment, non-blank line.
ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
KNOB="$ROOT/.skills/test-workers"
SETTING=auto
if [[ -f "$KNOB" ]]; then
  SETTING=$(sed -e 's/#.*//' -e 's/[[:space:]]//g' "$KNOB" | grep -m1 . || true)
  SETTING=${SETTING:-auto}
  case "$SETTING" in
    off) answer 0 ".skills/test-workers says off" ;;
    auto) ;;
    *)
      if ! is_count "$SETTING"; then
        echo "ERROR: .skills/test-workers says '$SETTING' — expected off, auto or a number" >&2
        exit 2
      fi
      answer "$SETTING" ".skills/test-workers says $SETTING"
      ;;
  esac
fi

# 3. auto.
CORES=$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1)
is_count "$CORES" || CORES=1
if [[ "$CORES" -le 2 ]]; then
  answer 0 "auto: $CORES core(s), so serial"
fi

ACTIVE=0
if DIR=$(slot_dir); then
  for slot in "$DIR"/*; do
    [[ -e "$slot" ]] || continue
    pid=${slot##*/}
    if is_count "$pid" && kill -0 "$pid" 2>/dev/null; then
      ACTIVE=$((ACTIVE + 1))
    else
      rm -f "$slot"
    fi
  done
fi

N=$((CORES / (ACTIVE + 1)))
if [[ "$N" -gt "$MAX_WORKERS" ]]; then
  N=$MAX_WORKERS
fi
if [[ "$N" -lt 2 ]]; then
  N=0
fi
answer "$N" "auto: $CORES cores, $ACTIVE other gate(s) running, so $N"
