#!/usr/bin/env bash
# Once-per-day skills-vendor/ submodule refresh. Auto-commits only on main.
# Designed for invocation as a Claude Code SessionStart hook — exits 0 on
# every non-fatal condition so a failure here never blocks a session.
set -euo pipefail

# Backstop: any unhandled error must exit 0 (SessionStart hooks must not
# block a session). Logs a one-line breadcrumb to LOG when LOG is already
# defined, so unexpected failures remain debuggable.
_hook_panic() {
  local rc=$?
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] unexpected hook error (rc=$rc)" \
    >> "${LOG:-/dev/null}" 2>/dev/null || true
  exit 0
}
trap _hook_panic ERR

for arg in "$@"; do
  if [[ "$arg" == "--help" ]]; then
    cat <<EOF
Usage: bash .claude/hooks/skills-submodule-update.sh [--help]

Once-per-day refresh of skills-vendor/ git submodules. Designed for
invocation as a Claude Code SessionStart hook — never blocks a session.

Behaviour:
  - Runs at most once per UTC day (.git/skills-update.lock).
  - Runs only on the main branch.
  - Scopes update + diff + add to skills-vendor/ — never touches other
    submodules.
  - Auto-commits pointer bumps as 'chore: update skills submodules'.
  - Logs to .git/skills-update.log (bounded to ~64 KiB / 200 lines).
  - Exits 0 on every non-fatal condition.

Options:
  --help    Show this help and exit.

Exit codes:
  0  Always (this hook never blocks a session).
EOF
    exit 0
  fi
done

gitdir="$(git rev-parse --git-dir 2>/dev/null)" || exit 0
LOCK="$gitdir/skills-update.lock"
LOG="$gitdir/skills-update.log"

# Nothing to refresh if the project doesn't use the skills-vendor/ pattern.
[ -d skills-vendor ] || exit 0

# Lock check: once per UTC day. UTC matches the log timestamp timezone so
# "today" never disagrees between lock and log at the day boundary.
if [ -f "$LOCK" ] && [ "$(cat "$LOCK" 2>/dev/null || true)" = "$(date -u +%Y%m%d)" ]; then
  exit 0
fi

BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || true)"
[ "$BRANCH" = "main" ] || exit 0

# Bound the log: keep the last 200 lines once it crosses 64 KiB.
if [ -f "$LOG" ] && [ "$(wc -c <"$LOG")" -gt 65536 ]; then
  if tail -n 200 "$LOG" > "$LOG.tmp" 2>/dev/null; then
    mv -f "$LOG.tmp" "$LOG" 2>/dev/null || rm -f "$LOG.tmp"
  fi
fi

# Stamp the lock BEFORE the update so a transient failure (e.g. network
# blip) doesn't cause the hook to retry-and-relog on every same-day session.
# A failure today defers recovery to tomorrow's UTC day; the trade-off
# preserves the once-per-day invariant for both success and failure.
date -u +%Y%m%d > "$LOCK" || true

# Scope the update to skills-vendor/ — never touch other submodules.
if ! {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] submodule update (skills-vendor/):"
  git submodule update --remote --merge -- skills-vendor/ 2>&1
} >>"$LOG"; then
  echo "skills update failed (see $LOG)" >&2
  exit 0
fi

# Commit only if skills-vendor/ specifically changed. Match the diff scope
# to the add scope so unrelated dirty work cannot be absorbed and empty
# commits cannot be created.
if ! git diff --quiet HEAD -- skills-vendor/ 2>/dev/null; then
  {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] commit submodule bump:"
    git add skills-vendor/ 2>&1 || true
    if ! git diff --cached --quiet -- skills-vendor/ 2>/dev/null; then
      git commit -m 'chore: update skills submodules' 2>&1 || true
    fi
  } >>"$LOG" || true
fi

exit 0
