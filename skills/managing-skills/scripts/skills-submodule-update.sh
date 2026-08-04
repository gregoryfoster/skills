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
  - Scopes the submodule update to skills-vendor/ — never touches other
    submodules.
  - Stages and commits exactly two paths: skills-vendor/ and, when it
    exists, .skills/doctor.sh. Never .skills/ wholesale, which would
    absorb operator config (plans_dir, worktree_root).
  - Commit message names what changed: 'chore: update skills submodules',
    'chore: refresh .skills/doctor.sh', or both.
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

# Opportunistically install/update .skills/doctor.sh — the backport path
# for consumers added before doctor.sh existed. Runs on every session
# (not gated by the once-per-day lock) so accidental deletions self-heal
# at the next session start. install-doctor.sh is a no-op when content
# matches, so the cost is one file compare per session.
#
# Deliberately ahead of the lock and main-branch gates: this is the
# working-tree repair, and it should happen on every branch and every
# session. Committing the result is a separate concern and stays behind
# both gates, further down (#86).
for installer in skills-vendor/*/skills/managing-skills/scripts/install-doctor.sh; do
  [ -x "$installer" ] || continue
  if ! bash "$installer" --quiet >>"$LOG" 2>&1; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] doctor install failed (see lines above)" >>"$LOG"
  fi
  break
done

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

# Paths this hook is allowed to stage. Enumerated explicitly, and NEVER
# `.skills/` wholesale: that directory also holds operator config
# (.skills/plans_dir, .skills/worktree_root) which this hook has no business
# committing. Matching the diff scope to the add scope is what keeps
# unrelated dirty work from being absorbed and empty commits from being
# created — extending one without the other breaks that invariant.
#
# .skills/doctor.sh is here because the opportunistic install above writes it
# into the working tree and nothing else ever commits it, leaving it untracked
# in perpetuity. Four of twelve audited consumers had a doctor that had been
# reinstalled on every session for weeks and never once committed, so their
# fresh worktrees and CI clones had no doctor at all and the Phase 1 preflight
# silently short-circuited (#86; same symptom as #65).
COMMIT_PATHS=(skills-vendor/)
# Guarded on existence — `git add` errors on a path that isn't there, and
# consumers that don't use the doctor must stay unaffected.
if [ -f .skills/doctor.sh ]; then
  COMMIT_PATHS+=(.skills/doctor.sh)
fi

# `git status --porcelain`, not `git diff HEAD`: a diff against HEAD does not
# report an *untracked* file, which is exactly the state this is here to fix.
#
# Exit code captured rather than swallowed. This drives the commit branch, so
# a git that fails for an unexpected reason would otherwise be indistinguish-
# able from "nothing to commit" and the hook would silently stop committing
# forever. The remedy is log-and-skip, not the exit-2 of AGENTS.md's gate
# discipline: a SessionStart hook must never block a session, so the failure
# is made diagnosable instead of fatal. RC pre-init is required under `set -u`
# — a success path never fires `|| RC=$?`.
STATUS_RC=0
STATUS_OUT="$(git status --porcelain -- "${COMMIT_PATHS[@]}" 2>>"$LOG")" || STATUS_RC=$?
if [ "$STATUS_RC" -ne 0 ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] git status failed (rc=$STATUS_RC) — skipping commit this run" >>"$LOG"
elif [ -n "$STATUS_OUT" ]; then
  {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] commit skills update:"
    # `|| true` is load-bearing in two distinct cases, not just the obvious
    # one. (a) A path that isn't there — already excluded by the -f guard
    # above. (b) A consumer who gitignores `.skills/`: git then exits 1 for
    # the ignored path but still stages everything else, so submodule bumps
    # keep getting committed there. Tightening this into a hard failure
    # would silently strand those consumers.
    git add -- "${COMMIT_PATHS[@]}" 2>&1 || true
    if ! git diff --cached --quiet -- "${COMMIT_PATHS[@]}" 2>/dev/null; then
      # Name what actually changed. A doctor-only refresh recorded as
      # "update skills submodules" is wrong in both the log and git history.
      STAGED_SUB=0
      STAGED_DOC=0
      git diff --cached --quiet -- skills-vendor/ 2>/dev/null || STAGED_SUB=1
      git diff --cached --quiet -- .skills/doctor.sh 2>/dev/null || STAGED_DOC=1
      if [ "$STAGED_SUB" = "1" ] && [ "$STAGED_DOC" = "1" ]; then
        MSG='chore: update skills submodules and refresh .skills/doctor.sh'
      elif [ "$STAGED_DOC" = "1" ]; then
        MSG='chore: refresh .skills/doctor.sh'
      else
        MSG='chore: update skills submodules'
      fi
      # On failure, unstage what we staged. `git add` above may have staged a
      # previously *untracked* .skills/doctor.sh, and leaving a file the
      # operator never touched sitting in their index is worse than leaving
      # the commit undone — the next run retries cleanly either way.
      git commit -m "$MSG" 2>&1 || {
        echo "commit failed — unstaging to leave the index as we found it"
        git reset -q -- "${COMMIT_PATHS[@]}" 2>&1 || true
      }
    fi
  } >>"$LOG" || true
fi

exit 0
