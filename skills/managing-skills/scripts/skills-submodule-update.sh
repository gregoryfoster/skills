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
  - Honours per-submodule pins, so one vendored repo can be held at a
    commit while the rest keep refreshing (see Pin file below).
  - Stages and commits exactly two kinds of path: the skills-vendor/
    submodules it just refreshed and, when it exists, .skills/doctor.sh.
    Never .skills/ wholesale, which would absorb operator config
    (plans_dir, worktree_root, skills-pin).
  - Commit message names what changed: 'chore: update skills submodules',
    'chore: refresh .skills/doctor.sh', or both.
  - Logs to .git/skills-update.log (bounded to ~64 KiB / 200 lines).
  - Exits 0 on every non-fatal condition.

Pin file:
  Resolved in three steps, like this repo's other knobs:
    1. \$SKILLS_PIN_FILE     (env var; one-off override)
    2. .skills/skills-pin   (committed; the project's persistent default)
    3. no pins              (refresh everything — prior behaviour)

  Format: one '<submodule-path> <commit-ish>' per line; blank lines and
  '#' comments ignored. Example:

    skills-vendor/gregoryfoster-skills 3fc7b71

  A pinned path is excluded from both the update and the auto-commit, and
  each honoured pin is logged by name so a stale hold is visible rather
  than silent. A pin naming an unregistered submodule, or a line that is
  not '<path> <commit-ish>', refuses the whole refresh for that run —
  moving nothing beats silently ending a hold the operator still believes
  in. A pin whose recorded gitlink is not the pinned commit is reported
  as drift: the hook holds the pointer still but cannot move it back.

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

# One timestamped line to $LOG. $LOG is this hook's only diagnostic surface,
# so every write to it is timestamped — an unattributed fragment there is hard
# to pin to a session.
_log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >>"$LOG" 2>/dev/null || true
}

# --------------------------------------------------------------- pins (#100)
# A consumer may hold one skills-vendor/ submodule at a commit while the rest
# keep refreshing — an experiment control arm, a known-good vendored version.
# Without this, the only remedy was deleting the hook's SessionStart entry,
# which also stops the sibling refreshes and the .skills/doctor.sh self-heal.
#
# NOT solved by `submodule.<name>.update = none` in .gitmodules, which looks
# like the cheaper fix: `--merge` overrides it. Verified — with `--merge` the
# pinned submodule is updated anyway; without it, git skips it. Dropping
# `--merge` would change update semantics for every other submodule, so the
# pinned paths are removed from the pathspec instead.
#
# The pin must survive the *commit* step too: `git add -- skills-vendor/`
# would stage a pinned submodule whose checkout had already drifted, so the
# staged set is narrowed to the same paths the update was.
#
# Three-step resolution, matching .skills/plans_dir and .skills/worktree_root:
# env var, then committed file, then a default of "no pins".
PIN_FILE="${SKILLS_PIN_FILE:-.skills/skills-pin}"

# Submodules git actually knows about, restricted to this hook's scope. Pins
# are validated against this rather than against the filesystem — a directory
# under skills-vendor/ that isn't a registered submodule can't be pinned
# because it can't be updated either.
REGISTERED="$(git config -f .gitmodules --get-regexp '^submodule\..*\.path$' 2>/dev/null |
  awk '$2 ~ /^skills-vendor\// {print $2}' || true)"

PINNED=""      # space-fenced membership set: " path1  path2 "
PIN_COUNT=0    # entry lines seen, valid or not
PIN_REFUSE=0   # an entry this hook cannot honour ⇒ move nothing this run

if [ -f "$PIN_FILE" ]; then
  while IFS= read -r PIN_RAW || [ -n "$PIN_RAW" ]; do
    PIN_LINE="${PIN_RAW%%#*}"
    [ -n "$(printf '%s' "$PIN_LINE" | tr -d '[:space:]')" ] || continue
    PIN_COUNT=$((PIN_COUNT + 1))

    # Refuse rather than guess at a line that isn't '<path> <commit-ish>'.
    # Skipping the entry instead would leave the operator believing in a hold
    # they do not have — the failure this whole mechanism exists to prevent.
    if [ "$(printf '%s\n' "$PIN_LINE" | wc -w | tr -d ' ')" != "2" ]; then
      PIN_REFUSE=1
      _log "pin malformed: '$PIN_RAW' — expected '<submodule-path> <commit-ish>'"
      echo "skills pin: malformed line in $PIN_FILE: $PIN_RAW" >&2
      continue
    fi
    PIN_PATH="$(printf '%s\n' "$PIN_LINE" | awk '{print $1}')"
    PIN_ISH="$(printf '%s\n' "$PIN_LINE" | awk '{print $2}')"

    case "
$REGISTERED
" in
      *"
$PIN_PATH
"*) : ;;
      *)
        PIN_REFUSE=1
        _log "pin unknown: '$PIN_PATH' is not a registered skills-vendor/ submodule"
        echo "skills pin: $PIN_FILE names '$PIN_PATH', which is not a registered skills-vendor/ submodule" >&2
        continue
        ;;
    esac

    PINNED="$PINNED $PIN_PATH "
    _log "pin honoured: $PIN_PATH held at $PIN_ISH — excluded from this refresh"

    # A pin only holds what the superproject already records. If the recorded
    # pointer is elsewhere, the hold is not in effect and no amount of *not*
    # updating will restore it — only an operator can. Say so out loud.
    #
    # None of these report-only cases refuses the refresh, unlike the two
    # above: the path is excluded from the pathspec either way, so the hold
    # on movement is applied. An unresolvable target is the normal state of a
    # freshly cloned, not-yet-fetched submodule, and refusing there would
    # strand every sibling on exactly the checkout that needs the refresh.
    PIN_RECORDED="$(git rev-parse --verify --quiet "HEAD:$PIN_PATH" 2>/dev/null || true)"
    PIN_RESOLVED="$(git -C "$PIN_PATH" rev-parse --verify --quiet "${PIN_ISH}^{commit}" 2>/dev/null || true)"
    if [ -z "$PIN_RECORDED" ]; then
      _log "pin unrecorded: $PIN_PATH has no gitlink in HEAD — there is no pointer to hold"
      echo "skills pin: $PIN_PATH has no committed gitlink — there is no pointer to hold" >&2
    elif [ -z "$PIN_RESOLVED" ]; then
      _log "pin unverified: '$PIN_ISH' does not resolve inside $PIN_PATH — the hold is applied but its target could not be confirmed"
      echo "skills pin: cannot resolve '$PIN_ISH' inside $PIN_PATH — hold applied, target unverified" >&2
    elif [ "$PIN_RESOLVED" != "$PIN_RECORDED" ]; then
      _log "pin drift: $PIN_PATH is recorded at $PIN_RECORDED but pinned at $PIN_ISH ($PIN_RESOLVED) — the hold is not in effect"
      echo "skills pin: $PIN_PATH is recorded at ${PIN_RECORDED:0:7}, not the pinned $PIN_ISH — the hold is not in effect (see $LOG)" >&2
    fi
  done < "$PIN_FILE"
fi

# Paths to refresh. Empty is NOT the same as absent: `git submodule update
# --remote --merge --` with no pathspec updates *every* submodule, so an empty
# set has to skip the command outright.
UPDATE_PATHS=()
if [ "$PIN_COUNT" -eq 0 ]; then
  # No pins: the pre-#100 pathspec, which also covers a submodule added
  # since the last run.
  UPDATE_PATHS=(skills-vendor/)
elif [ "$PIN_REFUSE" -eq 1 ]; then
  _log "submodule refresh refused — $PIN_FILE has entries this hook cannot honour; no pointer moved"
  echo "skills pin: refusing to refresh skills-vendor/ until $PIN_FILE is fixed (see $LOG)" >&2
else
  while IFS= read -r REG_PATH; do
    [ -n "$REG_PATH" ] || continue
    case "$PINNED" in *" $REG_PATH "*) continue ;; esac
    UPDATE_PATHS+=("$REG_PATH")
  done <<REGISTERED_EOF
$REGISTERED
REGISTERED_EOF
fi

# Stamp the lock BEFORE the update so a transient failure (e.g. network
# blip) doesn't cause the hook to retry-and-relog on every same-day session.
# A failure today defers recovery to tomorrow's UTC day; the trade-off
# preserves the once-per-day invariant for both success and failure.
date -u +%Y%m%d > "$LOCK" || true

# Scope the update to the unpinned skills-vendor/ paths — never touch other
# submodules, and never a pinned one.
if [ "${#UPDATE_PATHS[@]}" -eq 0 ]; then
  _log "submodule update skipped — no unpinned skills-vendor/ submodules to refresh"
elif ! {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] submodule update (${UPDATE_PATHS[*]}):"
  git submodule update --remote --merge -- "${UPDATE_PATHS[@]}" 2>&1
} >>"$LOG"; then
  echo "skills update failed (see $LOG)" >&2
  exit 0
fi

# Paths this hook is allowed to stage. Enumerated explicitly, and NEVER
# `.skills/` wholesale: that directory also holds operator config (plans_dir,
# worktree_root) this hook has no business committing. Matching diff scope to
# add scope is what keeps unrelated dirty work out and empty commits from
# being created; extending one without the other breaks it.
#
# .skills/doctor.sh is here because the install above writes it and nothing
# else ever commits it — the drift that left four of twelve audited consumers
# with no doctor in CI at all (#86).
#
# The submodule half is exactly what the update was scoped to, never
# `skills-vendor/` wholesale once pins are in play: a pinned submodule whose
# checkout has already drifted would otherwise be staged and committed here,
# ending the hold the update step had just honoured (#100).
COMMIT_PATHS=()
if [ "${#UPDATE_PATHS[@]}" -gt 0 ]; then
  COMMIT_PATHS=("${UPDATE_PATHS[@]}")
fi
# Guarded on existence — `git add` errors on a path that isn't there, and
# consumers that don't use the doctor must stay unaffected.
if [ -f .skills/doctor.sh ]; then
  COMMIT_PATHS+=(.skills/doctor.sh)
fi
# Nothing this hook is allowed to stage. An empty pathspec would widen every
# git call below to the whole repo, so stop here instead.
if [ "${#COMMIT_PATHS[@]}" -eq 0 ]; then
  exit 0
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
#
# stderr goes to a scratch file rather than straight to $LOG so it can be
# emitted *under* a timestamped header. Every other write to $LOG is
# timestamped, and $LOG is this hook's only diagnostic surface — an
# unattributed fragment there is hard to pin to a session.
STATUS_ERR="$gitdir/skills-status.err"
STATUS_RC=0
STATUS_OUT="$(git status --porcelain -- "${COMMIT_PATHS[@]}" 2>"$STATUS_ERR")" || STATUS_RC=$?
if [ "$STATUS_RC" -ne 0 ]; then
  {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] git status failed (rc=$STATUS_RC) — skipping commit this run"
    cat "$STATUS_ERR"
  } >>"$LOG" 2>/dev/null || true
fi
rm -f "$STATUS_ERR"

if [ "$STATUS_RC" -eq 0 ] && [ -n "$STATUS_OUT" ]; then
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
