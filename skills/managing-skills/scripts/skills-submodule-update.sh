#!/usr/bin/env bash
# Once-per-day skills-vendor/ submodule refresh. Auto-commits only on main.
# Designed for invocation as a Claude Code SessionStart hook — exits 0 on
# every non-fatal condition so a failure here never blocks a session.
set -euo pipefail

# Backstop: any unhandled error must exit 0 (SessionStart hooks must not
# block a session). Explicit guards below log known failure paths first.
trap 'exit 0' ERR

for arg in "$@"; do
  if [[ "$arg" == "--help" ]]; then
    cat <<EOF
Usage: bash scripts/skills-submodule-update.sh

Once-per-day refresh of skills-vendor/ git submodules. Designed for
invocation as a Claude Code SessionStart hook — never blocks a session.

Behaviour:
  - Runs at most once per calendar day (.git/skills-update.lock).
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

# Lock check first — cheap and gates everything else.
if [ -f "$LOCK" ] && [ "$(cat "$LOCK" 2>/dev/null || true)" = "$(date +%Y%m%d)" ]; then
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

# Scope the update to skills-vendor/ — never touch other submodules.
if ! {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] submodule update (skills-vendor/):"
  git submodule update --remote --merge -- skills-vendor/ 2>&1
} >>"$LOG"; then
  echo "skills update failed (see $LOG)" >&2
  exit 0
fi

date +%Y%m%d > "$LOCK" || true

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
