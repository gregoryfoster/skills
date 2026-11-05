#!/usr/bin/env bash
# Once-per-day skills-vendor/ submodule refresh. Auto-commits only on main.
# Designed for invocation as a Claude Code SessionStart hook — exits 0 on
# every non-fatal condition so a failure here never blocks a session.
#
# The WHOLE script is one `{ … }` block, closed on the last line (#306). It is
# normally run through a symlink into the very submodule its own `git
# submodule update` rewrites, and bash does not read a script once: it reads
# it in pieces as it goes, resuming by byte offset. Were the bytes under it to
# change mid-run, everything after the update would resume at an old offset
# into new content — mid-statement, in a different file — on the path that
# commits and pushes. A brace group is parsed to its closing brace before any
# of it runs, and the `exit` that ends it means bash never reads past that
# brace. So: nothing may follow the closing brace, and the block ends in exit.
#
# Git itself is not the writer that breaks this today. Measured on git 2.39.3,
# checkout unlinks a file and creates a new one rather than rewriting it in
# place, so the running hook keeps the inode it opened and reads the old
# bytes to the end — tests/structural/test_hook_self_replacement.py pins
# that. The braces make it not matter: they cover any writer that DOES write
# in place (cp onto an existing file, a shell redirect) and a git that ever
# starts to. `install` is not one: BSD's and GNU's alike give the path a new
# inode (measured, coreutils 9.1).
# Braces rather than a main() function because they change nothing else — no
# function scope for anything below to acquire, and "$@" is still the
# script's own.
{
set -euo pipefail
# The phase timing (#572) reads SECONDS, and bash takes its starting value
# from the environment: `env SECONDS=5000 bash -c 'echo $SECONDS'` prints
# 5000. Zeroed, so a stray export cannot skew the times or the warning
# (CR 1818).
SECONDS=0

# Backstop: an unhandled error in a TOP-LEVEL statement exits 0 (SessionStart
# hooks must not block a session), with a one-line breadcrumb to LOG when LOG
# is already defined, so unexpected failures remain debuggable.
#
# Top-level statements only. Without `set -E` an ERR trap is not inherited by
# functions, and `set -e` exits inside one with the failing command's own
# status: measured on bash 3.2.57, a bare `false` in a function exits 1 with
# no breadcrumb. So every function here (_reconcile_unpushed, _install_doctor
# and the rest) must guard its own commands; this does not cover them.
# `set -E` is NOT the fix: it carries the trap into command substitutions too,
# where it fires and exits 0 in the subshell — measured, the checked
# `$(git status …) || STATUS_RC=$?` below then reads rc 0, and a failed status
# becomes "nothing to commit".
#
# A panic once the refresh has begun spends the day, as any run that ends does
# (#555): the lock used to be stamped before the refresh, so an error there was
# already damped, and a deterministic one must not re-run at every session.
# Called by the ERR trap below; shellcheck does not count a trap as a call.
# shellcheck disable=SC2329
_hook_panic() {
  local rc=$?
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] unexpected hook error (rc=$rc)" \
    >> "${LOG:-/dev/null}" 2>/dev/null || true
  if [ "${REFRESH_BEGUN:-0}" = "1" ]; then
    _stamp_lock || true
  fi
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
  - Runs at most once per UTC day (.git/skills-update.lock). The day is
    spent when a run ends, not when it starts: a run killed part way
    leaves it for the next session, which first undoes any staging the
    killed run left behind (.git/skills-update.staging marks a refresh in
    progress).
  - Runs only on the main branch.
  - Scopes the submodule update to skills-vendor/ — never touches other
    submodules.
  - Initializes an unregistered skills-vendor/ submodule (--init) rather
    than skipping it. A refresh that still moved nothing is reported, not
    logged as a bare success.
  - Honours per-submodule pins, so one vendored repo can be held at a
    commit while the rest keep refreshing (see Pin file below).
  - Installs or refreshes .skills/doctor.sh every session, on any branch,
    from the first vendored install-doctor.sh that succeeds — and again
    after a refresh, so a pointer bump commits the doctor it ships. Every
    installer failing is reported on stderr, once, when the run's last
    install is the one that failed. A checkout whose
    skills-vendor/ submodules are not populated (a fresh worktree) has no
    installer to run.
  - Stages and commits exactly two kinds of path: the skills-vendor/
    submodules it just refreshed and, when it exists, .skills/doctor.sh.
    Never .skills/ wholesale, which would absorb operator config
    (plans_dir, worktree_root, skills-pin).
  - Commit message names what changed: 'chore: update skills submodules',
    'chore: refresh .skills/doctor.sh', or both.
  - Pushes the commits it makes, and retries at every session start for any
    it left unpushed earlier. A commit that lands locally and is never
    pushed is invisible to CI, to every other clone and to every fresh
    worktree; where a service reads the checkout it can refuse to start.
    If the push fails the commit is rolled back so the checkout matches the
    remote — the pointer, the vendored content and .skills/doctor.sh
    alike — and the next session retries. A run that cannot push does not
    refresh either. Never pulls, never force-pushes main, and never touches
    a commit this hook did not write.
  - With .skills/merge_mode 'pr' (read from the primary checkout, #560),
    never pushes to main: the bump is proposed as ONE pull request from
    skills/submodule-refresh, which later sessions update, and the
    checkout's content stays on the pointer its index records. Needs gh
    and a token for it (#576): GH_TOKEN in the hook's environment, else
    GH_TOKEN in the repo's .env (read as data, handed to gh alone), else
    gh's stored login; with none, no refresh. A refusal is reported once
    and not retried. A knob that is present but unusable is never read as
    'direct': no refresh until it is fixed.
  - With .skills/refresh-skip-hooks (committed, #572), adds the pre-commit
    hook ids it lists to SKIP for this hook's own commit and pushes, so a
    suite longer than the 120 s timeout is not run on a pointer bump. A
    commit made by hand still runs every hook. A knob that is present but
    unusable skips nothing, and says so on stderr.
  - Logs each phase's elapsed time, and warns on stderr when a refresh
    passes 90 s of its 120 s timeout.
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
# A refresh in progress (#555): written before the update, removed once the
# commit block ends with nothing of the hook's left staged. Its first line
# names the run that owns it, `pid <PID> <epoch seconds>`; then one path per
# line — the ones that run may stage — so a later session can tell what the
# hook staged from what a human did; a heal that has said a killed run's
# staging on stderr appends `noted`. See _heal_staged and _marker_owner_live.
STAGING="$gitdir/skills-update.staging"
# How long a marker's owner can be believed alive (CR 1789): the hook's 120 s
# ceiling plus margin. Past it, a live PID is a reused one — an unrelated
# process, or one in another PID namespace — and the marker is stale.
#
# A known limit (CR 1799): the 120 s is install-refresh.sh's default, and
# install-hook.sh keeps a consumer's own larger `timeout` on a re-run. A run
# allowed past 300 s that takes that long has its live marker read as stale,
# so a session starting then can heal under it — the race CR 1789 closed. Not
# derived: the harness does not hand a hook its timeout, and reading it from
# .claude/settings.json means a JSON parser on a path that must finish inside
# the extension's ~2 s. A timeout above 300 s needs this raised with it.
MARKER_MAX_AGE=300
# merge_mode pr (#560): the private index the pull request's commit is built
# in, so the checkout's own index is never written; and the one branch the
# hook proposes from.
PR_INDEX="$gitdir/skills-update.pr-index"
PR_BRANCH="skills/submodule-refresh"

# Nothing to refresh if the project doesn't use the skills-vendor/ pattern.
[ -d skills-vendor ] || exit 0

# One timestamped line to $LOG. $LOG is this hook's only diagnostic surface,
# so every write to it is timestamped — an unattributed fragment there is hard
# to pin to a session.
#
# Defined here rather than below the gates, where it used to live: the
# reconcile step deliberately runs ahead of both of them (#293) and needs it.
_log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >>"$LOG" 2>/dev/null || true
}

# _phase <name> — how far into the hook's timeout a phase ended (#572; see
# TIMING_WARN_AT below). Up here because the reconcile's push, which times
# itself, runs ahead of the refresh too.
_phase() {
  _log "timing: $1 done at ${SECONDS}s"
}

# _marker_owner_live — true when $STAGING names a run that is still going
# (CR 1789), and sets MARKER_OWNER to its PID for the log.
#
# The day's lock used to be stamped ahead of the refresh, and that made it the
# hook's mutual exclusion as well: a session starting mid-refresh exited at
# the once-per-day guard. #555 moved the stamp to the end, so the marker
# carries that job now. Without it, two sessions starting together in one
# checkout — agent sessions sharing it, or two VS Code windows reconnecting —
# both ran the whole refresh, and the second's heal took the first's LIVE
# marker for a killed run's: it unstaged and restored the content under a run
# between `git add` and `git commit`, whose commit then recorded nothing.
#
# Alive means `kill -0` reaches the PID and the marker is younger than
# MARKER_MAX_AGE. A SIGKILL or SIGTERM leaves the marker behind with its owner
# gone, which is exactly the leftover the heal exists for. A marker naming
# this run's own PID (reused) is not live.
#
# Nor, once it is a few seconds old, is one this run cannot parse. Younger, it
# is a claim still being written (CR 1808): noclobber's open creates the file
# before its first byte lands, and a second session reading it in between
# found no `pid` line, took it for dead, and both refreshed. The claim now
# writes it with no fork inside the redirect, so that window is microseconds;
# _marker_being_written covers what is left of it, and is reached only for an
# unparseable marker, so its `stat` costs a normal run nothing. Both ways
# bounded: an mtime more than 2 s ahead (a clock set back) is not believed.
MARKER_OWNER=""
_marker_being_written() {
  local now mtime
  now="$(date +%s 2>/dev/null)" || return 1
  # GNU and busybox take -c; BSD's (macOS) refuses it with nothing on stdout.
  mtime="$(stat -c %Y "$STAGING" 2>/dev/null || stat -f %m "$STAGING" 2>/dev/null)" || return 1
  case "$mtime" in '' | *[!0-9]*) return 1 ;; esac
  [ $((now - mtime)) -le 2 ] && [ $((mtime - now)) -le 2 ]
}
_marker_owner_live() {
  local head tag pid started now
  MARKER_OWNER=""
  [ -f "$STAGING" ] || return 1
  head="$(head -n 1 "$STAGING" 2>/dev/null)" || return 1
  read -r tag pid started <<<"$head" || true
  case "$pid" in '' | *[!0-9]*) tag="" ;; esac
  case "$started" in '' | *[!0-9]*) tag="" ;; esac
  if [ "$tag" != "pid" ]; then
    _marker_being_written || return 1
    MARKER_OWNER="unknown: its marker is still being written"
    return 0
  fi
  [ "$pid" != "$$" ] || return 1
  now="$(date +%s 2>/dev/null)" || return 1
  [ $((now - started)) -le "$MARKER_MAX_AGE" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  MARKER_OWNER="$pid"
  return 0
}

# _unstage <after> <path>... — unstage the paths, then read the index back
# rather than trust the reset (#311). <after> names the failure being undone,
# for the messages: "a failed commit", "a rolled-back push".
#
# Both of this hook's failure paths end by handing the index back as they
# found it, and each did it with a `git reset` whose exit status was
# discarded, git's stderr in $LOG its only trace. A reset that fails leaves
# the paths staged with nothing said where a session looks — the state
# CannObserv/power-map was found in on 2026-09-18, both paths staged beneath
# this hook's own "unstaging" line. The cause is not proven. #306's in-place
# rewrite was measured and ruled out; an index.lock held by another git
# process would produce it (measured: the reset exits 128); and so might a
# kill that lands inside this very reset — #555 found the VS Code extension
# killing session-start hooks about 2 s in. A kill earlier, between `git add`
# and the end of `git commit`, leaves the same two paths staged but WITHOUT
# the "unstaging" line power-map's log carried; _heal_staged undoes that one
# at the next session. So this checks the outcome, not a cause: whatever is
# still staged under the paths is named on stderr, with the command that
# clears it.
#
# It sees the index as the reset left it. Something that re-stages later — a
# hook running `git add`, a framework restoring its stash — is past it.
_unstage() {
  local after="$1" left rc=0
  shift
  git reset -q -- "$@" 2>>"$LOG" || _log "unstage after $after: git reset exited $? (git's words above)"
  left="$(git diff --cached --name-only -- "$@" 2>>"$LOG")" || rc=$?
  if [ "$rc" -ne 0 ]; then
    _log "unstage after $after: could not read the index back (git diff exited $rc) — $* may still be staged"
    echo "skills update: could not check the index after $after — run git status for $* (see $LOG)" >&2 || true
  elif [ -n "$left" ]; then
    left="${left//$'\n'/ }"
    _log "unstage after $after incomplete — still staged: $left"
    echo "skills update: $left still staged after $after — unstage by hand: git reset -q -- $left (see $LOG)" >&2 || true
  fi
  return 0
}

# Resolved here, gated further down. The reconcile step is main-only for the
# same reason the commit is, but it runs before the lock, so it cannot wait
# for the `exit 0` gate to have computed this.
BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || true)"

# ------------------------------------------------------ merge_mode (#342, #560)
# How this project lands work on its default branch: `direct` (absent means
# direct) or `pr`. In `pr` mode the hook never pushes to main; it proposes its
# bump as one pull request (_pr_refresh, below).
#
# Inline, not a call to shipping-work's merge-mode.sh: this file is read by
# bash while `git submodule update` rewrites the vendored tree (see the brace
# note at the top), it can be installed as a copy rather than a symlink
# (install-hook.sh), and a consumer need not vendor shipping-work at all.
# tests/structural/test_refresh_hook_pr_mode.py holds it to merge-mode.sh's
# answers on the same inputs test_cadence_merge_mode.py uses.
#
# Read from the primary checkout (the first `git worktree list` entry), as
# merge-mode.sh does: an untracked knob does not exist in a linked worktree.
# Present but unusable is `unusable`, never `direct` — the run then neither
# pushes nor refreshes, and says why.
MERGE_MODE="direct"
MERGE_MODE_ERR=""
_read_merge_mode() {
  local wt primary knob remedy line word="" count=0 words
  MERGE_MODE="unusable"
  MERGE_MODE_ERR=""
  remedy="write one word, 'pr' or 'direct', or delete the file for the default ('direct')"
  wt="$(git worktree list --porcelain 2>/dev/null)" || {
    MERGE_MODE_ERR="git worktree list failed, so .skills/merge_mode could not be read"
    return 0
  }
  primary=${wt%%$'\n'*}
  primary=${primary#worktree }
  if [ ! -d "$primary" ]; then
    MERGE_MODE_ERR="could not resolve the primary checkout (got '$primary') to read .skills/merge_mode"
    return 0
  fi
  knob="$primary/.skills/merge_mode"
  if [ ! -e "$knob" ] && [ ! -L "$knob" ]; then
    MERGE_MODE="direct"
    return 0
  fi
  if ! { [ -f "$knob" ] && [ -r "$knob" ]; }; then
    MERGE_MODE_ERR="$knob is present but not a readable file: $remedy"
    return 0
  fi
  if ! exec 3<"$knob"; then
    MERGE_MODE_ERR="could not open $knob: $remedy"
    return 0
  fi
  while IFS= read -r line <&3 || [ -n "$line" ]; do
    line=${line%$'\r'}
    read -r -a words <<<"$line" || true
    [ "${#words[@]}" -gt 0 ] || continue
    case ${words[0]} in \#*) continue ;; esac
    count=$((count + ${#words[@]}))
    word=${words[0]}
  done
  exec 3<&-
  if [ "$count" -eq 0 ]; then
    MERGE_MODE_ERR="$knob names no mode: $remedy"
  elif [ "$count" -ne 1 ]; then
    MERGE_MODE_ERR="$knob has $count words; it takes one: $remedy"
  else
    case $word in
      pr | direct) MERGE_MODE="$word" ;;
      *) MERGE_MODE_ERR="$knob says '$word', which is not a merge mode: $remedy" ;;
    esac
  fi
  return 0
}
# Read on main only: every path that acts on it is main-only, so a session on
# any other branch runs exactly as before the knob.
if [ "$BRANCH" = "main" ]; then
  _read_merge_mode
fi

# ------------------------------------------------ refresh-skip-hooks (#572)
# The consumer's pre-commit hook ids this hook's own commit and pushes skip,
# through pre-commit's SKIP. The harness kills this hook at 120 s, and
# MARKER_MAX_AGE caps any raise at 300, so a consumer whose pre-commit suite
# runs longer had every refresh commit killed — and since #555, killed again
# at every session start. A gate inside the consumer's pre-commit that guessed
# this hook's commit from its staged paths (CannObserv/power-map#752) copied
# COMMIT_PATHS and would drift with it; marking the commit here does not. Only
# this hook's commits and pushes carry it, so a bump made by hand still runs
# every hook.
#
# The pushes too: a consumer whose pre-push runs the same suite meets the same
# kill there, and pre-commit applies SKIP to an id in every stage. "This
# hook's" is the reconcile's reading (CR 1823): it pushes only when every
# unpushed subject is one of MSG_SUB/MSG_DOC/MSG_BOTH, so a commit made by hand
# under one of those exact subjects is pushed with the knob's SKIP too. Its
# pre-commit ran when it was made; only its pre-push is skipped.
#
# Read from this checkout, not the primary: it is committed config that lands
# with the pin bump that needs it, and this checkout is the one committing.
# Absent: nothing skipped. Present but unusable: nothing skipped either, so
# the commit runs every hook, the safe direction — and _skip_hooks_note says
# so on stderr.
SKIP_HOOKS=""
SKIP_HOOKS_ERR=""
SKIP_HOOKS_KNOB=.skills/refresh-skip-hooks
_read_skip_hooks() {
  local line word words ids="" remedy
  SKIP_HOOKS=""
  SKIP_HOOKS_ERR=""
  remedy="write pre-commit hook ids separated by spaces or newlines, or delete the file to run every hook"
  if [ ! -e "$SKIP_HOOKS_KNOB" ] && [ ! -L "$SKIP_HOOKS_KNOB" ]; then
    return 0
  fi
  if ! { [ -f "$SKIP_HOOKS_KNOB" ] && [ -r "$SKIP_HOOKS_KNOB" ]; }; then
    SKIP_HOOKS_ERR="$SKIP_HOOKS_KNOB is present but not a readable file: $remedy"
    return 0
  fi
  if ! exec 3<"$SKIP_HOOKS_KNOB"; then
    SKIP_HOOKS_ERR="could not open $SKIP_HOOKS_KNOB: $remedy"
    return 0
  fi
  while IFS= read -r line <&3 || [ -n "$line" ]; do
    line=${line%$'\r'}
    read -r -a words <<<"$line" || true
    [ "${#words[@]}" -gt 0 ] || continue
    case ${words[0]} in \#*) continue ;; esac
    for word in "${words[@]}"; do
      # pre-commit splits SKIP on commas, so an id holding one would skip
      # two hooks; a `#` past the first word is a comment pre-commit never
      # sees, taken here for ids.
      case $word in
        *,* | \#*)
          [ -n "$SKIP_HOOKS_ERR" ] ||
            SKIP_HOOKS_ERR="$SKIP_HOOKS_KNOB has '$word', which is not a hook id (no commas; a comment takes its own line): $remedy"
          ;;
        *) ids="${ids:+$ids,}$word" ;;
      esac
    done
  done
  exec 3<&-
  if [ -z "$SKIP_HOOKS_ERR" ] && [ -z "$ids" ]; then
    SKIP_HOOKS_ERR="$SKIP_HOOKS_KNOB names no hook id: $remedy"
  fi
  [ -n "$SKIP_HOOKS_ERR" ] || SKIP_HOOKS="$ids"
  return 0
}
# Main only, as merge_mode: nothing off main commits or pushes.
if [ "$BRANCH" = "main" ]; then
  _read_skip_hooks
fi

# _skip_hooks_note — an unusable knob, said once per run, ahead of the first
# commit or push it would have shaped. Its own call, not inside _hook_git:
# every caller folds that command's stderr into $LOG or a variable, where an
# operator would never read it.
SKIP_HOOKS_SAID=0
_skip_hooks_note() {
  [ -n "$SKIP_HOOKS_ERR" ] && [ "$SKIP_HOOKS_SAID" = "0" ] || return 0
  SKIP_HOOKS_SAID=1
  _log "$SKIP_HOOKS_ERR — this run's commit and push run every pre-commit hook"
  echo "skills update: $SKIP_HOOKS_ERR. Until then this hook's commit and push run every pre-commit hook, and a run that outlasts its 120 s timeout is killed (see $LOG)" >&2 || true
  return 0
}

# _hook_git <git args> — git with the knob's ids added to SKIP, for this one
# command. Only this hook's own commit and pushes go through it. An SKIP the
# session already carries is kept, not replaced.
_hook_git() {
  if [ -n "$SKIP_HOOKS" ]; then
    _log "git $1: skipping pre-commit hook(s) $SKIP_HOOKS ($SKIP_HOOKS_KNOB)"
    SKIP="${SKIP:+$SKIP,}$SKIP_HOOKS" git "$@"
  else
    git "$@"
  fi
}

# The commit subjects this hook authors. Named once because two places read
# them: the commit step at the bottom, and the reconcile step's authorship
# guard. Let those drift and the guard either stops recognising this hook's
# own commits (it silently stops rolling them back) or recognises too much
# (it rolls back an operator's) — so they are constants, not literals.
MSG_SUB='chore: update skills submodules'
MSG_DOC='chore: refresh .skills/doctor.sh'
MSG_BOTH='chore: update skills submodules and refresh .skills/doctor.sh'

# Set when a push fails or is refused, and read for the rest of the run: it
# stops the refresh itself, not only the commit (#550). Without it the very
# next thing this script would do after a rollback is fetch the content
# forward again, re-stage it, re-commit it and re-attempt the push it has just
# been refused — two network waits inside a hook with a 120s ceiling, the
# same warning twice, and a checkout left with content ahead of its pointer.
# One refusal is enough information for one run.
PUSH_BLOCKED=0

# ------------------------------------------------- unpushed reconcile (#293)
# A commit that lands locally and is never pushed is functionally untracked
# for every consumer but the machine that wrote it: CI, fresh worktrees and
# every other clone see nothing. CannObserv/replicator's systemd unit refuses
# to start a checkout carrying unpushed commits — main is the deployed code,
# so unpushed is unshared — and a one-line pointer bump from this hook
# stranded that service twice in two weeks (13h on 2026-09-03, 56min on
# 2026-09-16), each time unrecoverable without an operator.
#
# This is #86's defect one level up. #86 committed the doctor this hook had
# written, so it stopped being untracked; this pushes the commit, so it stops
# being unshared. Committing to main was never the problem — a sibling
# workflow commits `chore: weekly context measurement` to main and pushes it,
# and it surfaces as a routine rebase.
#
# Runs on EVERY session, ahead of the once-per-day lock, rather than as a
# `git push` bolted onto the commit below. Three things that shape buys:
#   - the lock is spent by any run that ends, success or failure, so a push
#     that failed on the commit path would wait a whole UTC day to retry;
#   - the hook can be killed at any point, by a signal no trap here can
#     answer: the harness's timeout, or — every window (re)connect, about
#     2 s in — the VS Code extension's config-cache process shutting down
#     (#555). A kill between commit and push leaves exactly the state this
#     exists to prevent, and this pass heals it at the next session. A kill
#     before the commit ends is _heal_staged's, just below;
#   - consumers are stranded today. This reaches them with nobody visiting
#     the machine.
#
# Deliberately NEVER pulls. Landing a bump on a checkout that is behind would
# mean advancing local main, and on a deployed VM main IS the running code:
# a SessionStart hook updating deployed application code is a far larger
# authority than moving a submodule pointer. A stale consumer gets no bump,
# loudly, until a human syncs — and that is an acceptable trade because the
# rollback is the fix here and the push is the optimization. The service was
# stranded by `ahead 1`, not by a stale skills pin.
#
# A rollback undoes the WHOLE bump: the recorded pointer, the vendored content
# and the doctor (_restore_bump). It used to revert only the pointer, leaving
# the refreshed content checked out "so the skills keep working either way".
# That holds only while an update is backward-compatible with the consumer's
# repo-side config, and #550 measured where it is not: wslcb's rollback on
# 2026-10-29 left content carrying #480, which refuses a knob grammar that
# repo's committed config still used, so its vendored patching-hosts refused
# the repo's own knob until a human synced. A stale consumer keeps the older
# skills, content and pointer together, until a session can share the bump.
_reconcile_unpushed() {
  [ "$BRANCH" = "main" ] || return 0
  # Already refused once this run. Asking again costs a second network wait
  # and tells the operator nothing the first message did not.
  [ "$PUSH_BLOCKED" = "0" ] || return 0

  local remote merge upstream_name ahead merges subject unknown seen rpath
  # Read from config rather than parsed out of `@{u}`: this yields the remote
  # name and the remote ref separately, which is exactly what an explicit push
  # refspec needs, and it stays unambiguous when a remote name contains a
  # slash or the local branch tracks a differently-named remote branch.
  remote="$(git config --get "branch.$BRANCH.remote" 2>/dev/null || true)"
  merge="$(git config --get "branch.$BRANCH.merge" 2>/dev/null || true)"
  # No upstream at all is a configuration (a remote-less checkout), not a
  # fault. There is nothing to be ahead OF, so there is nothing to say.
  if [ -z "$remote" ] || [ -z "$merge" ]; then
    return 0
  fi
  upstream_name="$remote/${merge#refs/heads/}"

  # @{u} is the remote-tracking ref — the last fetch, not the live remote.
  # That is the right comparison anyway: it is this checkout's own record of
  # what has been shared, and a push settles the question authoritatively.
  ahead="$(git rev-list --count '@{u}..HEAD' 2>/dev/null || true)"
  case "$ahead" in ''|*[!0-9]*) return 0 ;; esac
  [ "$ahead" -gt 0 ] || return 0

  # Roll back only what this hook wrote. An operator's own unpushed commit is
  # never this hook's to undo — and THIS guard, not the choice of reset mode,
  # is what makes the rollback below safe in general.
  unknown=0
  seen=0
  while IFS= read -r subject; do
    seen=$((seen + 1))
    case "$subject" in
      "$MSG_SUB"|"$MSG_DOC"|"$MSG_BOTH") : ;;
      *) unknown=$((unknown + 1)) ;;
    esac
  done < <(git log --no-show-signature --format=%s '@{u}..HEAD' 2>/dev/null || true)

  # Not `direct`: this hook pushes nothing to $BRANCH (#560). Its guards and
  # its messages differ, so it has its own pass.
  if [ "$MERGE_MODE" != "direct" ]; then
    _reconcile_pr "$ahead" "$seen" "$unknown" "$upstream_name"
    return 0
  fi

  # `--no-show-signature` above, because this count is compared against
  # rev-list's: with `log.showSignature = true` — an ordinary setting where
  # signing is mandated — git prepends verification lines to each SIGNED
  # commit, `seen` overshoots `ahead`, and the check below then refuses every
  # session, forever, with one $LOG line as the only trace. Failing closed
  # makes that safe rather than dangerous, but a guard that a formatting knob
  # can switch off is not a guard.
  #
  # The guard has to fail CLOSED, and without this it fails open. The `|| true`
  # above turns a git that failed into empty output, and empty output through
  # that loop leaves unknown=0 — the guard concluding "every one of them is
  # mine" on no evidence at all, in the one direction that publishes an
  # operator's unshared work. Every commit rev-list counted must be accounted
  # for here. Same standard as the merge refusal below: a range this hook
  # cannot fully read is a range it does not touch.
  if [ "$seen" -ne "$ahead" ]; then
    # Blocked, not merely skipped. Every refusal in this function has to stop
    # the commit step too: a run that has concluded it cannot share a commit
    # and then makes one has manufactured the stranding this whole step exists
    # to prevent, and call site 2 will only refuse it again.
    PUSH_BLOCKED=1
    _log "unpushed: refusing to push — read $seen subject(s) for the $ahead commit(s) ahead of $upstream_name, so they cannot be confirmed as this hook's"
    return 0
  fi

  if [ "$unknown" -gt 0 ]; then
    # This run will not push, whatever the mix. A push from here is a push of
    # the WHOLE branch, so it would carry commits the operator has not chosen
    # to share — publishing someone's work for them is a larger overreach
    # than the stranding this step exists to prevent. Blocking also stops the
    # commit step adding another commit to a pile nothing here can share.
    PUSH_BLOCKED=1
    if [ "$unknown" -lt "$ahead" ]; then
      # Mixed. One of ours is stranded behind commits we must not touch, and
      # nothing here can fix it — so say so where someone will see it.
      _log "unpushed: $BRANCH is $ahead commit(s) ahead of $upstream_name and $unknown are not this hook's — leaving every one of them alone"
      echo "skills update: this hook's pointer bump is unpushed behind $unknown commit(s) it did not write — push $BRANCH yourself (see $LOG)" >&2
    else
      # Purely the operator's own commits: logged, never warned. Working
      # unpushed on a local main is normal in plenty of repos, and a stderr
      # line at every session start there would train the reader to ignore
      # this channel — the one channel the stranding case depends on.
      _log "unpushed: $BRANCH is $ahead commit(s) ahead of $upstream_name, none of them this hook's — committing nothing this run rather than push work that was not shared"
    fi
    return 0
  fi

  # Merges refused, because the rollback below counts first-parent steps. With
  # every subject in the range one of this hook's three, a merge commit is
  # already close to impossible — but "close to" is not what the arithmetic
  # needs, and an empty count from a failed git reads as non-zero here.
  merges="$(git rev-list --count --merges '@{u}..HEAD' 2>/dev/null || true)"
  if [ "$merges" != "0" ]; then
    # Same reasoning as the count mismatch above: refusing to push means
    # refusing to commit, or the run strands what it makes.
    PUSH_BLOCKED=1
    _log "unpushed: refusing to roll back — $merges merge commit(s) in @{u}..HEAD, so HEAD~$ahead is not this hook's own history"
    return 0
  fi

  local paths log_before=0
  # Where this push's output starts in $LOG, so a refusal can be read back
  # from it (#560). A read only: what is written, and when, is unchanged.
  if [ -f "$LOG" ]; then
    log_before="$(wc -c <"$LOG" 2>/dev/null | tr -d ' ')" || log_before=0
  fi
  case "$log_before" in '' | *[!0-9]*) log_before=0 ;; esac
  _skip_hooks_note
  if {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] push $ahead unpushed commit(s) to $upstream_name:"
    # Explicit refspec, never a bare `git push`: under push.default=matching
    # that pushes every matching branch, which is not an authority an
    # unattended SessionStart hook should be exercising. Never --force, in
    # any spelling — a rejected push is information, not an obstacle.
    _hook_git push "$remote" "HEAD:$merge" 2>&1
  } >>"$LOG"; then
    _phase "push"
    _log "unpushed: pushed $ahead commit(s) to $upstream_name"
    return 0
  fi
  _phase "push"

  # --soft, and to HEAD~N rather than to @{u}. Both halves are load-bearing.
  #
  # --soft because --hard is whole-tree: it is NOT bounded by this hook's add
  # scope, and it discards any uncommitted edit anywhere in the checkout.
  # Measured on a repo with one unrelated dirty file, staged by nobody: the
  # file was reverted. The add-scope discipline this script is careful about
  # is a property of `git add`, and constrains `git reset --hard` not at all.
  #
  # HEAD~N rather than @{u} because a *diverged* main — ours ahead, origin
  # also ahead — would move HEAD onto origin's tree while the working tree
  # stayed on ours, so every file origin had added would then read as
  # deleted-by-us. HEAD~N stays on this checkout's own history. The
  # authorship and merge guards above are what make that arithmetic sound.
  PUSH_BLOCKED=1

  # Captured here: before the RESET, which is what destroys the range — not
  # before the push, which changes nothing when it fails. Deriving it from the
  # commits themselves rather than re-deriving COMMIT_PATHS means the unstage
  # covers exactly what the reset re-staged and nothing else, including a path
  # some older version of this hook staged.
  paths=()
  while IFS= read -r -d '' rpath; do
    paths+=("$rpath")
  done < <(git diff --name-only -z "HEAD~$ahead" HEAD 2>/dev/null || true)

  if git reset -q --soft "HEAD~$ahead" 2>>"$LOG"; then
    _log "unpushed: push failed — rolled $ahead commit(s) back, vendored content with them; the next session retries"
    # A repository rule or branch protection (GH013, GH006) is not an outage
    # the next session's retry outlives: say which rule, and the knob that
    # answers it (#560). Every other failure keeps the line it always had.
    if _rule_refusal "$(tail -c +$((log_before + 1)) "$LOG" 2>/dev/null || true)"; then
      echo "skills update: could not push to $remote — a repository rule refused it ($RULE_TEXT), so $BRANCH takes changes by pull request here: write pr to .skills/merge_mode and this hook proposes its bump as one pull request instead; rolled $ahead commit(s) back so this checkout matches $upstream_name (see $LOG)" >&2
    else
      echo "skills update: could not push to $remote — rolled $ahead commit(s) back so this checkout matches $upstream_name (see $LOG)" >&2
    fi
    if [ "${#paths[@]}" -gt 0 ]; then
      # Same move as the commit step's failure path: leave the index as we
      # found it. A .skills/doctor.sh that was untracked before the commit
      # goes back to untracked rather than sitting staged in an index the
      # operator never touched. Then the content goes back to the pointer
      # the reset restored (#550), bounded to these paths. After the report
      # above, so a warning that either fell short follows the rollback it
      # belongs to.
      _restore_bump "a rolled-back push" "${paths[@]}"
    fi
  else
    _log "unpushed: push failed AND rollback failed — $BRANCH is still $ahead commit(s) ahead of $upstream_name"
    echo "skills update: $BRANCH is $ahead unpushed commit(s) ahead of $upstream_name and could be neither pushed nor rolled back — fix by hand (see $LOG)" >&2
  fi
  return 0
}

# _rule_refusal <push output> — true when a repository rule or branch
# protection refused the push, and sets RULE_TEXT to its code and the rule it
# named: GitHub prints `GH013: Repository rule violations found` with each rule
# as a `remote: - <rule>` line, and legacy protection prints `GH006: Protected
# branch update failed` with the rule as a second `remote: error:` line.
RULE_TEXT=""
_rule_refusal() {
  local text="$1" code rule
  RULE_TEXT=""
  case "$text" in
    *GH013*) code="GH013" ;;
    *GH006*) code="GH006" ;;
    *"rotected branch"*) code="protected branch" ;;
    *) return 1 ;;
  esac
  rule="$(awk '/^remote: - / { sub(/^remote: - /, ""); sub(/[ \r]+$/, ""); print; exit }' <<<"$text" 2>/dev/null || true)"
  if [ -z "$rule" ]; then
    rule="$(awk '/^remote: error: / && !/GH0[0-9][0-9]/ { sub(/^remote: error: /, ""); sub(/[ \r]+$/, ""); print; exit }' <<<"$text" 2>/dev/null || true)"
  fi
  RULE_TEXT="$code${rule:+: $rule}"
  return 0
}

# _reconcile_pr <ahead> <seen> <unknown> <upstream> — the unpushed pass when
# merge_mode is not `direct` (#560). Nothing is ever pushed to $BRANCH here.
#
# `pr`: commits this hook wrote and never pushed — left by a run from before
# the repo set `pr` — are rolled back with their content (#550), and the pull
# request path redoes the bump from the default branch's tip. Moving them onto
# the PR branch instead would publish a bump an older run verified, on a parent
# that may not be the default branch's. Anything not wholly this hook's is left
# alone: the PR is built on @{u}, so an operator's unpushed work is never in
# it, and _pr_refresh refuses where main and @{u} disagree on the hook's paths.
#
# HEAD moves by compare-and-swap (`update-ref <new> <old>`), not `reset --soft
# HEAD~N`: two sessions starting together both reach this pass ahead of the
# in-progress marker, and a relative reset run twice would roll back a commit
# that is not this hook's. The second swap fails instead, and is logged.
#
# `unusable`: neither pushed nor rolled back. The refresh, which runs once a
# day, is where that is reported.
_reconcile_pr() {
  local ahead="$1" seen="$2" unknown="$3" upstream_name="$4" merges head target rpath paths=()
  if [ "$MERGE_MODE" != "pr" ]; then
    _log "unpushed: $BRANCH is $ahead commit(s) ahead of $upstream_name, and .skills/merge_mode is unusable — neither pushing nor rolling back until it reads pr or direct"
    return 0
  fi
  if [ "$seen" -ne "$ahead" ] || [ "$unknown" -gt 0 ]; then
    _log "unpushed: $BRANCH is $ahead commit(s) ahead of $upstream_name, not all confirmed as this hook's — merge_mode is pr, so nothing is pushed or rolled back"
    return 0
  fi
  merges="$(git rev-list --count --merges '@{u}..HEAD' 2>/dev/null || true)"
  if [ "$merges" != "0" ]; then
    _log "unpushed: merge_mode is pr, and @{u}..HEAD holds merge commit(s) — not rolling back"
    return 0
  fi
  head="$(git rev-parse --verify -q HEAD 2>/dev/null)" || return 0
  target="$(git rev-parse --verify -q "HEAD~$ahead" 2>/dev/null)" || return 0
  while IFS= read -r -d '' rpath; do
    paths+=("$rpath")
  done < <(git diff --name-only -z "$target" "$head" 2>/dev/null || true)
  if git update-ref -m "skills update: merge_mode pr, roll back $ahead unpushed hook commit(s)" HEAD "$target" "$head" 2>>"$LOG"; then
    _log "unpushed: merge_mode is pr — rolled back $ahead commit(s) this hook made on $BRANCH; a pull request proposes the bump instead"
    echo "skills update: merge_mode is pr — rolled back $ahead unpushed commit(s) this hook made on $BRANCH; it proposes the bump as a pull request instead (see $LOG)" >&2
    if [ "${#paths[@]}" -gt 0 ]; then
      _restore_bump "a pr-mode rollback" "${paths[@]}"
    fi
  else
    _log "unpushed: merge_mode is pr, and rolling back $ahead commit(s) this hook made on $BRANCH failed (HEAD moved, or git refused)"
  fi
  return 0
}

# Opportunistically install/update .skills/doctor.sh — the backport path
# for consumers added before doctor.sh existed. install-doctor.sh is a no-op
# when content matches, so the cost is one file compare per call.
#
# Called from three places. Call site 1, just below, runs on every session
# (not gated by the once-per-day lock) so accidental deletions self-heal at
# the next session start. Call site 2 runs after a successful submodule
# update, because call site 1 ran the PRE-bump installer against the PRE-bump
# doctor (#299): without it, the session that advances the pointer commits
# the old doctor beside the new pointer, and the refreshed one waits for the
# next session that reaches call site 1. The third is _restore_content, after
# it puts the content back on its pointer (#550): the heal, a rolled-back
# push, a failed commit or update, and every pr-mode refresh, where it is
# always the run's last call (CR 1794).
#
# None fires in a checkout whose skills-vendor/* are empty gitlinks — every
# fresh linked worktree, until something initializes them. The glob matches no
# installer there, and there is no vendored doctor to install from anyway, so
# "every session" means every session in a checkout with its submodules
# populated (#299).
#
# The first installer that SUCCEEDS wins, in glob order — not the first that
# exists (#300). The glob spans every vendored repo, so a second one shipping
# managing-skills is the fallback when the first fails; the loop used to break
# after the first attempt either way, leaving a stale doctor with one $LOG line
# as its only trace. When every installer fails, that reaches stderr — the
# channel every other failure here uses — once per run although a run can call
# this several times (three call sites, the third once per restore), and only
# when the run's LAST call failed (#300 CR 14, CR 1809).
# Warning from call site 1 on the spot was false whenever call site 2 then
# succeeded: a broken pre-bump installer that the bump replaces with a working
# one leaves a freshly installed and committed doctor, which "left as it was"
# denies. So each call records its outcome and the EXIT trap below reports the
# last one — every way out of this block, the ERR backstop's exit included,
# passes it.
#
# A restore passes what it restores after, and its failure is worded apart
# (CR 1794). By then call site 2 — this run's, or a killed run's being healed
# — may already have replaced the doctor from the bump's installer, which the
# restored pointer's installer then could not put back, so "left as it was"
# would deny a change the run made. What holds is that the doctor may not be
# the one the restored pointer ships.
DOCTOR_INSTALL_FAILED=0
DOCTOR_FAILED_AFTER=""
_install_doctor() {
  local installer tried=0 restoring="${1:-}"
  for installer in skills-vendor/*/skills/managing-skills/scripts/install-doctor.sh; do
    [ -x "$installer" ] || continue
    tried=$((tried + 1))
    if bash "$installer" --quiet >>"$LOG" 2>&1; then
      DOCTOR_INSTALL_FAILED=0
      DOCTOR_FAILED_AFTER=""
      return 0
    fi
    _log "doctor install failed via $installer (see lines above) — trying the next vendor, if any"
  done
  # No installer this time leaves the last verdict standing: a call that
  # installed nothing has not repaired an earlier failure.
  [ "$tried" -gt 0 ] || return 0
  _log "doctor install failed: all $tried vendored installer(s) failed — .skills/doctor.sh left as it was${restoring:+, not reinstalled after $restoring}"
  DOCTOR_INSTALL_FAILED=1
  DOCTOR_FAILED_AFTER="$restoring"
  return 0
}
# Called by the EXIT trap below; shellcheck does not count a trap as a call.
# shellcheck disable=SC2329
_report_doctor_install() {
  [ "$DOCTOR_INSTALL_FAILED" = "1" ] || return 0
  if [ -n "$DOCTOR_FAILED_AFTER" ]; then
    echo "skills update: could not reinstall .skills/doctor.sh when the content went back on its pointer after $DOCTOR_FAILED_AFTER — every vendored installer failed, so it may not be the version the restored pointer ships (see $LOG)" >&2 || true
    return 0
  fi
  echo "skills update: could not install .skills/doctor.sh — every vendored installer failed, so it was left as it was (see $LOG)" >&2 || true
}
trap _report_doctor_install EXIT

# Another session's refresh is in flight (CR 1789): leave the checkout to it,
# the way the old up-front lock did. Ahead of everything that writes — the
# doctor install, the heal, the reconcile, the refresh — and without spending
# the day, since that run will.
if _marker_owner_live; then
  _log "another refresh is in flight (pid $MARKER_OWNER) — leaving this checkout to it"
  exit 0
fi

# _install_doctor, call site 1 of 3: every session, ahead of both gates. This
# is the working-tree repair, and it should happen on every branch and every
# session. Committing the result is a separate concern and stays behind
# both gates, further down (#86).
_install_doctor

# Submodules git actually knows about, restricted to this hook's scope. Pins
# are validated against this rather than against the filesystem — a directory
# under skills-vendor/ that isn't a registered submodule can't be pinned
# because it can't be updated either. Resolved up here, ahead of the gates,
# because _heal_staged reads it too (#555).
REGISTERED="$(git config -f .gitmodules --get-regexp '^submodule\..*\.path$' 2>/dev/null |
  awk '$2 ~ /^skills-vendor\// {print $2}' || true)"

# _listed <path> <newline-separated list> — true when the list holds the path
# as a whole line.
_listed() {
  case "
$2
" in
    *"
$1
"*) return 0 ;;
  esac
  return 1
}

# _restore_bump <after> <path>... — undo a pointer bump this hook made but
# cannot keep (#550): a rolled-back push, or a killed refresh's leftovers. A
# failed commit and a failed update (CR 1792) do the same in two calls,
# unstage and restore, because their pathspecs differ.
# Unstages the paths, then puts each registered skills-vendor/ submodule among
# them back on the commit the index now records, then reinstalls the doctor
# from the restored vendored installer — so content, pointer and doctor go
# back together. Called only once REGISTERED is resolved.
#
# The doctor is reinstalled rather than checked out, so each case lands where
# it was: one tracked before the bump matches its committed copy again, and
# one untracked before it — unstaged back to untracked just above — is
# rewritten in place to the version the restored pointer ships, which is what
# _install_doctor's call site 1 writes at every session anyway.
#
# `--checkout`, because a plain `git submodule update -- <path>` honours a
# configured `submodule.<name>.update`: with merge, rebase or none it exits 0
# and leaves the newer content checked out (measured, git 2.54 — the older
# recorded commit is already contained in the newer one). `--no-fetch`,
# because the recorded commit was checked out here before the bump, and this
# runs inside a session start. Neither `--remote` nor `--merge`, and never
# `-f`: a checkout carries a local edit across where it can and refuses where
# it cannot, and a refusal is said on stderr — the content is then still
# ahead of its pointer, and the session needs to know.
#
# _restore_content is the second half alone, for merge_mode pr (#560): that
# path never stages anything in the checkout's index, so nothing staged under
# these paths is the hook's to unstage. The checkout is to the commit the
# index records, so an operator's own staged bump is kept, content and all.
_restore_bump() {
  local after="$1"
  shift
  _unstage "$after" "$@"
  _restore_content "$after" "$@"
}
#
# The log names the commit each path went back to, and whose it is (CR 1791):
# `git submodule update` checks out the pointer the INDEX records, which is
# HEAD's unless something is staged there — an unstage that failed, or a bump
# staged with no marker, which may be a human's and is never the hook's to
# unstage. "Restored to the recorded pointer" said nothing of which.
_restore_content() {
  local after="$1" p idx head gitlinks=()
  shift
  for p in "$@"; do
    if _listed "$p" "$REGISTERED"; then
      gitlinks+=("$p")
    fi
  done
  [ "${#gitlinks[@]}" -gt 0 ] || return 0
  if {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] restore ${gitlinks[*]} to the pointer the index records, after $after:"
    git submodule update --checkout --no-fetch -- "${gitlinks[@]}" 2>&1
  } >>"$LOG"; then
    for p in "${gitlinks[@]}"; do
      idx="$(git ls-files -s -- "$p" 2>/dev/null | awk '$1 == "160000" { print $2 }')" || idx=""
      head="$(git rev-parse -q --verify "HEAD:$p" 2>/dev/null)" || head=""
      idx="${idx:0:7}"
      head="${head:0:7}"
      if [ "$idx" = "$head" ]; then
        _log "restored $p after $after: ${idx:-nothing}, the pointer HEAD and the index both record"
      else
        _log "restored $p after $after: ${idx:-nothing}, the pointer the index records — HEAD records ${head:-nothing}; the staged bump between them is left as it is"
      fi
    done
  else
    _log "could not restore ${gitlinks[*]} after $after — content is ahead of the recorded pointer"
    echo "skills update: ${gitlinks[*]} is ahead of the recorded pointer after $after — repo-side config may not match it until synced: git submodule update --checkout -- ${gitlinks[*]} (see $LOG)" >&2 || true
  fi
  _install_doctor "$after"
  return 0
}

# The day's lock, written by every run that ENDS — success or failure — and by
# no run that is killed part way (#555). Checked, not `|| true` (#193): this
# one write IS the once-per-day contract, and the guard reads nothing else. A
# read-only or root-owned .git, or a full disk, and the stamp never lands, the
# guard falls through next session, and the whole refresh runs again — every
# session, forever, with nothing said. That is the defect #187 fixed in
# socraticode-health.sh, the script this file's pin comment names as its twin;
# the shape is copied from it. Reported, never fatal: a SessionStart hook must
# not block, so a failed stamp degrades to noisier reporting.
_stamp_lock() {
  if ! date -u +%Y%m%d > "$LOCK" 2>/dev/null; then
    _log "could not stamp $LOCK — the once-per-day guard is off until this is fixed"
    echo "skills update: cannot write $LOCK; this refresh will repeat every session (see $LOG)" >&2 || true
  fi
  return 0
}

# ------------------------------------------- a killed refresh's staging (#555)
# The VS Code extension starts a short-lived "config cache" CLI process at
# every window (re)connect. It runs the SessionStart hooks and shuts down about
# 2-3 s later, killing what is still running; the real session starts its own
# run about a second after. A refresh fetching a hundred upstream commits, then
# committing through a consumer's pre-commit framework (about 1 s even with
# every hook skipped), does not fit. Killed between `git add` and the end of
# `git commit`, it leaves this hook's paths STAGED: the state
# CannObserv/address-validator was found in on 2026-11-01, and the next bare
# `git commit` anyone makes there absorbs the bump under their own message.
#
# Undone here, every session on main, ahead of the lock — the session after a
# kill is usually the real one, a second later. Unstaged rather than
# committed: the lock is now spent only when a run ends, so this same session
# redoes the bump, and nothing is committed that this run has not verified.
#
# Only what the hook staged is touched, and the marker is how it knows. A
# human's own `git add skills-vendor/<v>` — a manual bump — stages exactly the
# hook's paths, so "every staged path is one this hook would commit" cannot
# tell the two apart. With no marker, the index is left alone and the state is
# logged: a checkout left staged by a hook from before #555 is not undone
# here. In `direct` mode the first refresh this version completes on main
# commits it through its own pathspec; `pr` mode never commits in this
# checkout, so its refresh says so on stderr instead, with the reset that
# clears it (_pr_note_staged, CR 1791). With a marker, the heal unstages only
# when every staged path is one the marker names; anything else staged beside
# them is someone's work, so the whole index is left alone — the content still
# goes back on the pointer the index records (CR 1801) — and the marker is
# kept while the hook's own paths stay staged.
_heal_staged() {
  [ "$BRANCH" = "main" ] || return 0

  local listed="" marked=0 staged_now rc=0 spath own=() others=0 hook_paths
  if [ -f "$STAGING" ]; then
    # A live owner's marker is never the heal's (CR 1789). The guard ahead of
    # the doctor install already exits on one; this keeps the heal honest on
    # its own.
    if _marker_owner_live; then
      _log "heal: $STAGING belongs to a refresh still in flight (pid $MARKER_OWNER) — leaving the index alone"
      return 0
    fi
    marked=1
    # The paths, without the owner line, a pr-mode run's `mode pr`, or the
    # `noted` an earlier heal appended (CR 1801).
    listed="$(grep -v -e '^pid ' -e '^mode ' -e '^noted$' "$STAGING" 2>>"$LOG")" || rc=$?
    if [ "$rc" -gt 1 ]; then
      _log "heal: could not read $STAGING (grep exited $rc) — leaving the index alone"
      return 0
    fi
    rc=0
    # A pr-mode run (#560) never stages in this index, so whatever is staged
    # is not its own: only its content goes back, and its private index goes.
    if grep -qx 'mode pr' "$STAGING" 2>/dev/null; then
      _heal_pr "$listed"
      return 0
    fi
  fi

  # --ignore-submodules=none: a diff.ignoreSubmodules or .gitmodules `ignore`
  # setting would otherwise hide the very gitlink this looks for.
  staged_now="$(git diff --cached --name-only --ignore-submodules=none 2>>"$LOG")" || rc=$?
  if [ "$rc" -ne 0 ]; then
    _log "heal: could not read the index (git diff exited $rc) — leaving it alone"
    return 0
  fi

  if [ "$marked" = "1" ]; then
    hook_paths="$listed"
  else
    hook_paths="$REGISTERED
.skills/doctor.sh"
  fi
  while IFS= read -r spath; do
    [ -n "$spath" ] || continue
    if _listed "$spath" "$hook_paths"; then
      own+=("$spath")
    else
      others=$((others + 1))
    fi
  done <<STAGED_EOF
$staged_now
STAGED_EOF

  if [ "$marked" = "0" ]; then
    if [ "${#own[@]}" -gt 0 ]; then
      _log "heal: ${own[*]} staged with no in-progress marker — a manual bump, or a hook from before #555; not this hook's to undo, leaving the index alone"
    fi
    return 0
  fi

  # The whole bump goes back, not only its staging (#550): a kill after the
  # update leaves the content ahead of the pointer whether or not it got as
  # far as `git add`, and a session that cannot redo the bump (main carrying
  # an operator's unpushed commit, a pin refusal) would otherwise keep it so.
  # When this session can redo it, it does, from a checkout that agrees.
  # Every path the marker names, staged or not: an unstage of a path with
  # nothing staged is a no-op, and a submodule already on its pointer is too.
  local marked_paths=() gitlinks=() p
  while IFS= read -r spath; do
    [ -n "$spath" ] || continue
    marked_paths+=("$spath")
  done <<LISTED_EOF
$listed
LISTED_EOF

  # Someone else's work staged beside the hook's keeps the index as it is,
  # but not the content (CR 1801): `git submodule update --checkout` writes
  # no index, so the content still goes back — onto the pointer the index
  # records, which for a gitlink the killed run staged is that run's bump;
  # _restore_content's log says which. The hook's staging left in place is
  # said on stderr once per killed run, not at every session while the
  # human's work stays staged: the marker gets a `noted` line, and the
  # refresh that redoes the bump writes a fresh marker. `own` is empty when
  # the kill fell before `git add`, and an empty array's expansion is an
  # unbound variable under bash 3.2's `set -u` (CR 1800).
  if [ "$others" -gt 0 ]; then
    if [ "${#own[@]}" -gt 0 ]; then
      _log "heal: a killed refresh left ${own[*]} staged beside $others path(s) it did not stage — leaving the index alone; the content goes back on the pointer the index records"
      if ! grep -qx 'noted' "$STAGING" 2>/dev/null; then
        for p in "${own[@]}"; do
          if _listed "$p" "$REGISTERED"; then
            gitlinks+=("$p")
          fi
        done
        echo "skills update: a refresh killed part way left ${own[*]} staged beside $others staged path(s) it did not stage, so the index is left as it is; the next refresh to complete commits them through its own pathspec. To drop them instead: git reset -q -- ${own[*]}${gitlinks[0]:+ && git submodule update --checkout -- ${gitlinks[*]}} (see $LOG)" >&2 || true
        printf 'noted\n' >>"$STAGING" 2>/dev/null || true
      fi
    else
      _log "heal: a killed refresh staged nothing, and $others path(s) it did not stage are staged — leaving the index alone; the content goes back on its pointer"
    fi
    if [ "${#marked_paths[@]}" -gt 0 ]; then
      _restore_content "a killed refresh" "${marked_paths[@]}"
    fi
  elif [ "${#marked_paths[@]}" -gt 0 ]; then
    if [ "${#own[@]}" -gt 0 ]; then
      _log "heal: a killed refresh left ${own[*]} staged — undoing its bump"
    fi
    _restore_bump "a killed refresh" "${marked_paths[@]}"
  fi
  # Kept while anything of the hook's is still staged, so the next session
  # tries again; _unstage has already said so on stderr.
  if [ "${#own[@]}" -eq 0 ] ||
    git diff --cached --quiet --ignore-submodules=none -- "${own[@]}" 2>/dev/null; then
    rm -f "$STAGING" 2>/dev/null || true
  fi
  return 0
}

# _heal_pr <marked paths> — a killed pr-mode refresh's leftovers (#560): the
# vendored content it moved, the doctor it reinstalled, and its private index
# (with git's lock on it — its owner is dead, which is how this was reached).
# The marker goes too: a restore git refuses is said on stderr, and the next
# refresh runs the same restore again.
_heal_pr() {
  local spath marked_paths=()
  while IFS= read -r spath; do
    [ -n "$spath" ] || continue
    marked_paths+=("$spath")
  done <<LISTED_EOF
$1
LISTED_EOF
  _log "heal: a killed pr-mode refresh left $STAGING — putting the content back on the recorded pointer"
  if [ "${#marked_paths[@]}" -gt 0 ]; then
    _restore_content "a killed refresh" "${marked_paths[@]}"
  fi
  rm -f "$PR_INDEX" "$PR_INDEX.lock" "$STAGING" 2>/dev/null || true
  return 0
}

# Ahead of _reconcile_unpushed: a failed push's rollback re-stages its range
# with `reset --soft`, and the paths it then unstages are derived from that
# range alone. Healed first, the index it starts from holds nothing a killed
# run left there.
_heal_staged

# Call site 1 of 2: every session, ahead of both gates. This is the pass that
# heals a checkout some earlier run left stranded — a push killed by the
# harness timeout or the extension's shutdown (#555), a push that failed while
# the remote was unreachable, or a commit made by a version of this hook that
# had no push step at all. Behind the once-per-day lock it would retry at most
# once a day; behind the branch gate it would never run at all on the
# sessions that matter.
_reconcile_unpushed

# Lock check: once per UTC day. UTC matches the log timestamp timezone so
# "today" never disagrees between lock and log at the day boundary.
if [ -f "$LOCK" ] && [ "$(cat "$LOCK" 2>/dev/null || true)" = "$(date -u +%Y%m%d)" ]; then
  exit 0
fi

[ "$BRANCH" = "main" ] || exit 0

# Bound the log: keep the last 200 lines once it crosses 64 KiB.
if [ -f "$LOG" ] && [ "$(wc -c <"$LOG")" -gt 65536 ]; then
  if tail -n 200 "$LOG" > "$LOG.tmp" 2>/dev/null; then
    mv -f "$LOG.tmp" "$LOG" 2>/dev/null || rm -f "$LOG.tmp"
  fi
fi

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

# Pins are validated against REGISTERED, resolved above the gates.
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

# This run has already established it cannot share a commit — the remote
# refused a push, or `main` carries commits this hook did not write and must
# not publish on the operator's behalf. Committing anyway would manufacture
# exactly the unpushed commit the reconcile step exists to prevent (#293).
#
# And it does not refresh either (#550). It used to, skipping only the
# commit, on the premise that refreshed content in the working tree keeps the
# skills working while the pointer waits. That premise is what #550
# disproved: content ahead of its pointer can refuse the repo's own config.
# So the checkout stays on its recorded pointer — the one a rollback this run
# has just restored, or the one main has carried all along — until a session
# that can share the bump makes it. After the pin parse, so a malformed pin
# is still reported; a completed run, so the day is spent.
if [ "$PUSH_BLOCKED" = "1" ]; then
  _log "refresh skipped — this run cannot share what it would commit, and a refresh it cannot commit would leave the content ahead of the pointer; the bump waits for a session that can"
  _stamp_lock
  exit 0
fi

# merge_mode (#560). Present but unusable is never `direct`: no refresh, said
# once — here, behind the day's lock — not at every session start.
if [ "$MERGE_MODE" = "unusable" ]; then
  _log "refresh skipped — $MERGE_MODE_ERR"
  echo "skills update: no refresh — .skills/merge_mode is unusable, and is never read as direct: $MERGE_MODE_ERR (see $LOG)" >&2
  _stamp_lock
  exit 0
fi

# `pr`: what the pull request needs that is local and cheap, checked before
# the refresh moves anything — gh on PATH, and an upstream for main. Each
# refusal is said once and spends the day, as any run that ends does.
PR_REMOTE=""
PR_MERGE=""
PR_BASE_BRANCH=""
PR_UPSTREAM=""
PR_GH_REPO=""
PR_GH_TOKEN=""
PR_TOKEN_FROM=""
PR_GIT_CRED=""
# _gh_repo_of <remote url> — `host/owner/repo` for gh's --repo, or nothing:
# for a URL that is not a host's (a local path), and for an SSH host `ssh -G`
# cannot name. gh then resolves the repo from the checkout's remotes, which
# works where there is one.
#
# An SSH URL's host is an ssh_config name, not necessarily a hostname. A
# deploy-key alias (`git@github-processor:o/r.git` under `Host
# github-processor` / `HostName github.com`) went to gh as an Enterprise host,
# and every run was refused at `gh pr list` (#576). `ssh -G` prints the
# HostName the name resolves to (the name itself when no Host block matches),
# and SSH-over-443's ssh.github.com is github.com to gh. --repo is kept rather
# than left to gh: it pins the PR's base to main's own upstream remote, where
# gh's choice among remotes could take an `upstream` fork parent instead.
_gh_repo_of() {
  local url="$1" rest host path ssh=""
  case "$url" in
    ssh://* | git+ssh://* | ssh+git://*) ssh=1 ;;
  esac
  case "$url" in
    *://*)
      rest=${url#*://}
      host=${rest%%/*}
      path=${rest#*/}
      host=${host##*@}
      host=${host%%:*}
      ;;
    *:*)
      # scp-like, [user@]host:path: git's rule is no slash before the colon.
      rest=${url%%:*}
      case "$rest" in */*) return 0 ;; esac
      host=${rest##*@}
      path=${url#*:}
      ssh=1
      ;;
    *) return 0 ;;
  esac
  path=${path%/}
  path=${path%.git}
  case "$host" in '' | -*) return 0 ;; esac
  case "$path" in
    '' | /* | */*/*) return 0 ;;
    */*) : ;;
    *) return 0 ;;
  esac
  if [ -n "$ssh" ]; then
    rest=$host
    host="$(ssh -G -- "$rest" </dev/null 2>/dev/null | awk '$1 == "hostname" { print $2; exit }' || true)"
    [ "$host" != "ssh.github.com" ] || host=github.com
    if [ -z "$host" ] || [ "${host#-}" != "$host" ]; then
      _log "pr: ssh -G could not name the host behind '$rest' — gh resolves the repo from the checkout's remotes instead"
      return 0
    fi
  fi
  printf '%s/%s\n' "$host" "$path"
  return 0
}

# _env_value <file> <name> — <name>'s value in a .env file, parsed as data and
# never sourced: load_env's grammar from shipping-work's pre-ship.sh header,
# for one name, the last assignment winning as it does there. Nothing when the
# file is absent or unreadable, or does not set it.
_env_value() {
  local file="$1" want="$2" line key val found=""
  if ! { [ -f "$file" ] && [ -r "$file" ]; }; then
    return 0
  fi
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line#"${line%%[![:space:]]*}"}
    case $line in '' | \#*) continue ;; esac
    line=${line#export }
    case $line in *=*) ;; *) continue ;; esac
    key=${line%%=*} val=${line#*=}
    key=${key%"${key##*[![:space:]]}"}
    [ "$key" = "$want" ] || continue
    case $val in
      \"*\") val=${val#\"} val=${val%\"} ;;
      \'*\') val=${val#\'} val=${val%\'} ;;
    esac
    found=$val
  done <"$file" 2>/dev/null || true
  printf '%s' "$found"
}

# _pr_token — where gh's token comes from (#576), into PR_TOKEN_FROM; false
# when there is none. Cohort hosts keep GH_TOKEN only in the git-ignored repo
# .env, which agents load per command; a SessionStart hook runs beside the
# others, not after them, so no other hook's export ever reaches this one.
# In order:
#   1. GH_TOKEN or GITHUB_TOKEN already in this hook's environment;
#   2. GH_TOKEN in the checkout's .env, or from a linked worktree the primary
#      checkout's — read as data, held in PR_GH_TOKEN, and handed to gh (and
#      to git's network calls for an https remote) per call. Never exported:
#      the refresh runs the new pointer's own install-doctor.sh before any
#      human has reviewed the bump, and the token must not reach it;
#   3. gh's own stored login (`gh auth token`, which reads it offline).
# The .env outranks the stored login: a stale hosts.yml fails as a 401 that
# reads like a bad token (#334's power-map case), while the .env is what the
# cohort keeps current.
_pr_token() {
  local env_file=".env" wt primary host
  PR_GH_TOKEN=""
  PR_TOKEN_FROM=""
  if [ -n "${GH_TOKEN:-}" ] || [ -n "${GITHUB_TOKEN:-}" ]; then
    PR_TOKEN_FROM="this hook's environment"
    return 0
  fi
  if [ ! -r "$env_file" ]; then
    wt="$(git worktree list --porcelain 2>/dev/null || true)"
    primary=${wt%%$'\n'*}
    primary=${primary#worktree }
    [ -z "$primary" ] || env_file="$primary/.env"
  fi
  PR_GH_TOKEN="$(_env_value "$env_file" GH_TOKEN)"
  if [ -n "$PR_GH_TOKEN" ]; then
    PR_TOKEN_FROM="$env_file"
    return 0
  fi
  host=""
  [ -z "$PR_GH_REPO" ] || host=${PR_GH_REPO%%/*}
  if GH_PROMPT_DISABLED=1 GH_NO_UPDATE_NOTIFIER=1 gh auth token ${host:+--hostname "$host"} >/dev/null 2>&1; then
    PR_TOKEN_FROM="gh's stored login${host:+ for $host}"
    return 0
  fi
  PR_TOKEN_FROM="$env_file"
  return 1
}
_pr_preflight() {
  local url
  if ! command -v gh >/dev/null 2>&1; then
    _log "pr: gh not found on PATH — merge_mode is pr, and the pull request is opened with gh; no refresh this run"
    echo "skills update: .skills/merge_mode is pr, but gh is not on this hook's PATH, so no pull request can be opened — no refresh this run; install gh and run gh auth login (see $LOG)" >&2
    return 1
  fi
  PR_REMOTE="$(git config --get "branch.$BRANCH.remote" 2>/dev/null || true)"
  PR_MERGE="$(git config --get "branch.$BRANCH.merge" 2>/dev/null || true)"
  if [ -z "$PR_REMOTE" ] || [ -z "$PR_MERGE" ]; then
    _log "pr: $BRANCH has no upstream — merge_mode is pr, and the pull request needs a base; no refresh this run"
    echo "skills update: .skills/merge_mode is pr, but $BRANCH has no upstream to propose a pull request against — no refresh this run (see $LOG)" >&2
    return 1
  fi
  PR_BASE_BRANCH="${PR_MERGE#refs/heads/}"
  PR_UPSTREAM="$PR_REMOTE/$PR_BASE_BRANCH"
  # The configured URL, not `git remote get-url`, which expands insteadOf.
  url="$(git config --get "remote.$PR_REMOTE.url" 2>/dev/null || true)"
  PR_GH_REPO="$(_gh_repo_of "$url")"
  # No token is refused here, before the refresh moves anything: it used to
  # be found at `gh pr list`, after a whole refresh and its restore (#576).
  if ! _pr_token; then
    _log "pr: gh has no token — none in this hook's environment, no GH_TOKEN in $PR_TOKEN_FROM, and no stored gh login; no refresh this run"
    echo "skills update: .skills/merge_mode is pr, but gh has no token here — GH_TOKEN is not in this hook's environment or in $PR_TOKEN_FROM, and gh has no stored login (gh auth login) — so no pull request can be opened; no refresh this run (see $LOG)" >&2
    return 1
  fi
  _log "pr: gh's token comes from $PR_TOKEN_FROM${PR_GH_REPO:+; --repo $PR_GH_REPO}"
  # An https remote needs a credential for the branch push too, and a host
  # whose token lives only in the .env, or only in gh's login, may have no
  # git credential helper at all. Such a run's network git calls get gh's
  # (`gh auth git-credential`, which answers from the same token) for that
  # host, added through GIT_CONFIG_COUNT (git >= 2.31; older git ignores
  # it) after the consumer's own helpers, which still answer first. Not when
  # the caller set GIT_CONFIG_COUNT: adding to it would renumber theirs.
  case "$url" in
    https://*)
      if [ -n "${GIT_CONFIG_COUNT:-}" ]; then
        _log "pr: GIT_CONFIG_COUNT is already set, so gh is not added as $PR_REMOTE's credential helper — the push uses git's own, if any"
      elif [ -n "$PR_GH_REPO" ]; then
        PR_GIT_CRED="credential.https://${PR_GH_REPO%%/*}.helper"
      fi
      ;;
  esac
  return 0
}
if [ "$MERGE_MODE" = "pr" ] && ! _pr_preflight; then
  _stamp_lock
  exit 0
fi

# The refresh begins. The day's lock is NOT stamped here; it used to be, so
# that a transient failure (a network blip) would not retry and re-log at every
# same-day session — and that damping is kept for every run that ends, failure
# included: each way out of the update-and-commit block below goes through
# _finish_refresh. What changed is a run killed part way (#555). Stamped up
# here, it spent the day before doing the work, and the real session that
# starts a second after the extension's config-cache process exited at the
# once-per-day guard; recovery waited a UTC day, and the next day's run landed
# in the same 2 s window. Unstamped, the next session redoes it.
#
# The marker goes down first, naming this run as its owner and every path it
# may stage — the unpinned registered submodules and the doctor — so a kill
# anywhere from here to the end of the commit leaves _heal_staged the evidence
# it needs, and a session starting meanwhile leaves this one alone. Checked: a
# marker that never lands costs only the heal, so it is logged, not fatal.
REFRESH_PATHS=()
if [ "$PIN_COUNT" -eq 0 ]; then
  while IFS= read -r REG_PATH; do
    [ -n "$REG_PATH" ] || continue
    REFRESH_PATHS+=("$REG_PATH")
  done <<REGISTERED_EOF
$REGISTERED
REGISTERED_EOF
elif [ "${#UPDATE_PATHS[@]}" -gt 0 ]; then
  REFRESH_PATHS=("${UPDATE_PATHS[@]}")
fi
REFRESH_PATHS+=(.skills/doctor.sh)

# Claimed, not just written (CR 1789): `noclobber` makes the write fail when a
# marker is already there, so of two runs that reach this line together
# exactly one owns the refresh. One already there is checked: a live owner's
# means another session got here since this one passed the guard at the top,
# so this run leaves; a dead owner's — kept by a heal whose unstage failed —
# is replaced. In a subshell, so noclobber stays out of the rest of the run
# (and `$$` there is still this run's PID).
#
# The whole content is built first, `date` and all, and written by one
# builtin `printf` (CR 1808): with the fork inside the redirect, the file sat
# empty for as long as `date` took, and a second session reading it then saw
# no owner. _marker_owner_live believes an unparseable marker for its first
# 2 s, which covers the open-to-write gap that remains.
_claim_marker() {
  local body p
  body="pid $$ $(date +%s 2>/dev/null || true)"
  # A pr-mode run says so: its heal restores content and unstages nothing.
  if [ "$MERGE_MODE" = "pr" ]; then
    body="$body"$'\n'"mode pr"
  fi
  for p in "${REFRESH_PATHS[@]}"; do
    body="$body"$'\n'"$p"
  done
  (
    set -o noclobber
    printf '%s\n' "$body" > "$STAGING"
  ) 2>/dev/null
}
if ! _claim_marker; then
  if _marker_owner_live; then
    _log "another refresh is in flight (pid $MARKER_OWNER) — leaving this checkout to it"
    exit 0
  fi
  rm -f "$STAGING" 2>/dev/null || true
  if ! _claim_marker; then
    if [ -f "$STAGING" ]; then
      _log "another refresh claimed $STAGING first — leaving this checkout to it"
      exit 0
    fi
    _log "could not write $STAGING — a run killed before its commit ends will not have its staging undone"
  fi
fi
REFRESH_BEGUN=1
HOOK_ADDED=0

# Phase timing (#572): how much of the harness's timeout each part of a
# refresh used, in $LOG (_phase, above; a push is timed where it is made, at
# either reconcile call, so a run that pushes nothing logs no push — CR 1817), and one stderr line once a run passes
# TIMING_WARN_AT. The kill at 120 s says nothing of its own, and a consumer
# whose suite keeps growing crosses it between one day and the next
# (CannObserv/cli was at 112 s). SECONDS counts from the hook's start, so the
# heal and the reconcile ahead of the refresh are in it. On EXIT, so every way
# out of a refresh is covered; a SIGKILL runs no trap, and the log then ends at
# the last phase that finished. Added to the doctor report's EXIT trap, not in
# place of it: a shell holds one trap per signal.
#
# A known limit (CR 1820), MARKER_MAX_AGE's again: the harness does not hand
# the hook its timeout, so the line is fixed. A consumer that raised its entry
# toward 300 s is warned on every run past 90 s, though none is at risk.
TIMING_WARN_AT=90
# Called by the EXIT trap below; shellcheck does not count a trap as a call.
# shellcheck disable=SC2329
_warn_if_slow() {
  [ "$SECONDS" -ge "$TIMING_WARN_AT" ] || return 0
  _log "timing: this run took ${SECONDS}s, past the ${TIMING_WARN_AT}s warning line"
  echo "skills update: this refresh took ${SECONDS} s of the hook's 120 s default timeout, and a run past its timeout is killed. Each phase's time is in $LOG; a slow pre-commit hook can be skipped on this hook's own commit with .skills/refresh-skip-hooks" >&2 || true
}
trap '_report_doctor_install; _warn_if_slow' EXIT

# merge_mode pr and a bump staged with no marker (CR 1791). _heal_staged
# leaves it alone, since a human's own `git add skills-vendor/<v>` looks the
# same as a hook from before #555. In `direct` mode this run's commit takes it
# through its own pathspec; `pr` mode never commits in this checkout, so it
# stays staged for the next `git commit` on main to absorb, and the content
# stays on the pointer the index records. So it is said, once a run — this is
# behind the day's lock — by the run that owns the refresh, with the commands
# that clear it.
_pr_note_staged() {
  local p hook_paths=() left gitlinks=() rc=0
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    hook_paths+=("$p")
  done <<NOTE_EOF
$REGISTERED
.skills/doctor.sh
NOTE_EOF
  left="$(git diff --cached --name-only --ignore-submodules=none -- "${hook_paths[@]}" 2>>"$LOG")" || rc=$?
  if [ "$rc" -ne 0 ] || [ -z "$left" ]; then
    return 0
  fi
  while IFS= read -r p; do
    if _listed "$p" "$REGISTERED"; then
      gitlinks+=("$p")
    fi
  done <<LEFT_EOF
$left
LEFT_EOF
  left="${left//$'\n'/ }"
  _log "pr: $left staged with no in-progress marker — left staged; merge_mode pr never commits here"
  echo "skills update: $left is staged with no in-progress marker — a hook from before #555, or a bump of your own. merge_mode pr never commits in this checkout, so it stays staged for the next git commit on main, and the content stays on the pointer the index records. If it is not yours: git reset -q -- $left${gitlinks[0]:+ && git submodule update --checkout -- ${gitlinks[*]}} (see $LOG)" >&2 || true
  return 0
}
if [ "$MERGE_MODE" = "pr" ]; then
  _pr_note_staged
fi

# Every way out of the refresh from here on. The marker goes unless this run's
# own `git add` left something of the hook's still staged — a commit that
# failed and could not be unstaged — in which case the next session's
# _heal_staged tries the unstage again. Then the day is spent.
_finish_refresh() {
  if [ "$HOOK_ADDED" = "0" ] ||
    git diff --cached --quiet --ignore-submodules=none -- "${REFRESH_PATHS[@]}" 2>/dev/null; then
    rm -f "$STAGING" 2>/dev/null || true
  fi
  _stamp_lock
}

# Scope the update to the unpinned skills-vendor/ paths — never touch other
# submodules, and never a pinned one.
#
# `--init` is what makes this hook work on a half-healed checkout: content
# present under skills-vendor/, nothing registered in .git/config. Without it
# git skips every such submodule and exits **0** — so the guard below passes,
# no pointer moves, and the day's lock is spent on a run that did nothing. A
# consumer sat in that state for days reporting success (#176).
#
# How loudly git skips depends on the pathspec, which is worth knowing because
# both halves show up in this tree's notes. Verified on git 2.39.3: named
# explicitly — as they are here — each path draws "Submodule path '<p>' not
# initialized / Maybe you want to use 'update --init'?" on **stderr**; with no
# pathspec at all git is completely silent. Neither is any use to an operator
# here, because the `2>&1` below folds that stderr into $LOG, a file nobody
# reads until something has already gone wrong. Hence `--init` plus the
# post-condition below, rather than trusting git's own report.
#
# `--init` is idempotent on an already-registered submodule,
# and it stays behind the pin filter because a pinned path was already removed
# from UPDATE_PATHS — a held submodule is neither initialized nor refreshed.
#
# .skills/doctor.sh does not cover this: its own `--init --recursive` runs
# only when a skills/* symlink dangles, and in this state they all resolve.
if [ "${#UPDATE_PATHS[@]}" -eq 0 ]; then
  _log "submodule update skipped — no unpinned skills-vendor/ submodules to refresh"
elif [ -z "$(printf '%s' "$REGISTERED" | tr -d '[:space:]')" ]; then
  # skills-vendor/ exists but .gitmodules records nothing under it, so the
  # pathspec matches no submodule and git exits 0 having done nothing. That is
  # a permanent no-op, not a quiet success — name it (#176).
  _log "submodule update did nothing — no registered skills-vendor/ submodules in .gitmodules; this hook cannot advance a pointer here"
  echo "skills update: no submodules registered under skills-vendor/ — nothing to refresh (see $LOG)" >&2
elif ! {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] submodule update (${UPDATE_PATHS[*]}):"
  git submodule update --init --remote --merge -- "${UPDATE_PATHS[@]}" 2>&1
} >>"$LOG"; then
  echo "skills update failed (see $LOG)" >&2
  # A part-way update must not stay checked out, in either mode (#560 for
  # pr, CR 1792 for direct): nothing is committed after it, so whatever it
  # moved would sit ahead of its pointer until the next day's refresh. The
  # hook has staged nothing yet, so only the content goes back.
  _restore_content "a failed update" "${REFRESH_PATHS[@]}"
  # A failure that ran to completion: it spends the day (see above).
  _finish_refresh
  exit 0
else
  # Post-condition, because the failure mode of #176 was a *silent* one: git
  # can decline to touch a submodule and still exit 0. `git submodule status`
  # prefixes an uninitialized path with '-'. Reported, never fatal — this hook
  # must not block a session, and the next run retries.
  UNINIT="$(git submodule status -- "${UPDATE_PATHS[@]}" 2>/dev/null |
    awk '/^-/ {printf "%s ", $2}' || true)"
  if [ -n "$UNINIT" ]; then
    _log "submodule refresh incomplete — still uninitialized after --init: ${UNINIT% }"
    echo "skills update: still uninitialized after refresh: ${UNINIT% } (see $LOG)" >&2
  fi

  # _install_doctor, call site 2 of 3 (#299): the update may just have
  # replaced the vendored install-doctor.sh and doctor.sh, so run the
  # POST-bump installer. Here, before COMMIT_PATHS is built, so the doctor
  # staged and committed below is the one that ships with the pointer this run
  # records — and so the -f guard there sees a doctor this call has only just
  # created.
  _install_doctor
fi

_phase "refresh"

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
  _finish_refresh
  exit 0
fi

# ------------------------------------------------------ merge_mode pr (#560)
# The refresh above ran in place, as it always has: the same update, the same
# post-bump doctor install (#299), the same pins. From here a `pr` run records
# the bump in a commit built in a private index, never in the checkout's own,
# puts the content back on the pointer the index records (#550) — main's,
# unless a bump is staged with no marker (_pr_note_staged) — and only THEN
# touches the network: pushes that commit to skills/submodule-refresh and opens
# a pull request for it if none is open. Local main never moves; the content
# always agrees with the index, except between the update and the restore,
# which the marker covers (_heal_pr). Annotated in
# references/auto-refresh-hook/pr-mode.md.
#
# Why in place rather than fetching inside each submodule and writing the new
# gitlinks without checking them out: `--remote --merge --init` and the pins
# would have to be re-implemented, and the doctor that rides the commit must be
# the one the new pointer's own installer writes, which needs that installer
# checked out.

# Every path this hook may write, as a list and as an array: the registered
# skills-vendor/ submodules and the doctor.
PR_HOOK_LIST="$REGISTERED
.skills/doctor.sh"
PR_HOOK_PATHS=()
while IFS= read -r REG_PATH; do
  [ -n "$REG_PATH" ] || continue
  PR_HOOK_PATHS+=("$REG_PATH")
done <<PRHOOK_EOF
$PR_HOOK_LIST
PRHOOK_EOF

# gh, with the token _pr_token found in the .env (if that is where it came
# from) in its environment alone, never the hook's (#576).
_gh() {
  if [ -n "$PR_GH_REPO" ]; then
    set -- "$@" --repo "$PR_GH_REPO"
  fi
  if [ -n "$PR_GH_TOKEN" ]; then
    GH_TOKEN="$PR_GH_TOKEN" GH_PROMPT_DISABLED=1 GH_NO_UPDATE_NOTIFIER=1 gh "$@"
  else
    GH_PROMPT_DISABLED=1 GH_NO_UPDATE_NOTIFIER=1 gh "$@"
  fi
}

# _pr_net <command>... — one of the pr path's network git calls (a git or a
# _hook_git), with gh as the https remote's credential helper when
# _pr_preflight chose one, the token in that call's environment only.
_pr_net() {
  if [ -z "$PR_GIT_CRED" ]; then
    "$@"
    return
  fi
  if [ -n "$PR_GH_TOKEN" ]; then
    GH_TOKEN="$PR_GH_TOKEN" GH_PROMPT_DISABLED=1 GIT_CONFIG_COUNT=1 \
      GIT_CONFIG_KEY_0="$PR_GIT_CRED" GIT_CONFIG_VALUE_0='!gh auth git-credential' "$@"
  else
    GH_PROMPT_DISABLED=1 GIT_CONFIG_COUNT=1 \
      GIT_CONFIG_KEY_0="$PR_GIT_CRED" GIT_CONFIG_VALUE_0='!gh auth git-credential' "$@"
  fi
}

# _pr_restore — the content back on the pointer the index records (main's,
# unless a bump is staged with no marker), the doctor with it.
_pr_restore() {
  _restore_content "a pr-mode refresh" "${REFRESH_PATHS[@]}"
}

# _pr_tree <commit> <path>... — a tree: <commit>'s, with each path as the
# working tree has it. The add is the commit step's own (`|| true` for the same
# gitignored-.skills/ reason), in the private index.
_pr_tree() {
  local base="$1" tree
  shift
  rm -f "$PR_INDEX" "$PR_INDEX.lock" 2>/dev/null || true
  GIT_INDEX_FILE="$PR_INDEX" git read-tree "$base" 2>>"$LOG" || return 1
  GIT_INDEX_FILE="$PR_INDEX" git add -- "$@" >>"$LOG" 2>&1 || true
  tree="$(GIT_INDEX_FILE="$PR_INDEX" git write-tree 2>>"$LOG")" || return 1
  rm -f "$PR_INDEX" 2>/dev/null || true
  printf '%s\n' "$tree"
}

# _pr_graft <commit> <tree> <path>... — a tree: <commit>'s, with each path as
# <tree> has it.
_pr_graft() {
  local base="$1" from="$2" entries tree
  shift 2
  rm -f "$PR_INDEX" "$PR_INDEX.lock" 2>/dev/null || true
  GIT_INDEX_FILE="$PR_INDEX" git read-tree "$base" 2>>"$LOG" || return 1
  entries="$(git ls-tree -r "$from" -- "$@" 2>>"$LOG")" || return 1
  if [ -n "$entries" ]; then
    GIT_INDEX_FILE="$PR_INDEX" git update-index --index-info <<<"$entries" 2>>"$LOG" || return 1
  fi
  tree="$(GIT_INDEX_FILE="$PR_INDEX" git write-tree 2>>"$LOG")" || return 1
  rm -f "$PR_INDEX" 2>/dev/null || true
  printf '%s\n' "$tree"
}

# _pr_same_bump <a> <b> — true when two commits make the same change to the
# hook's paths: from the same pointers and doctor, to the same. False when
# either is not here to read.
_pr_same_bump() {
  if [ -z "$1" ] || [ -z "$2" ]; then
    return 1
  fi
  git diff --quiet --ignore-submodules=none "$1" "$2" -- "${PR_HOOK_PATHS[@]}" </dev/null 2>/dev/null || return 1
  git diff --quiet --ignore-submodules=none "$1^" "$2^" -- "${PR_HOOK_PATHS[@]}" </dev/null 2>/dev/null || return 1
  return 0
}

# _pr_hook_commit <commit> — true when it is a commit this hook writes: one
# parent, one of the three subjects, and nothing changed outside the hook's
# paths. A human's fix on the PR fails it, and is never replaced.
_pr_hook_commit() {
  local parents subject changed p
  parents="$(git rev-list --parents -n 1 "$1" 2>/dev/null)" || return 1
  case "$parents" in
    *" "*" "*) return 1 ;;
    *" "*) : ;;
    *) return 1 ;;
  esac
  subject="$(git log -1 --no-show-signature --format=%s "$1" 2>/dev/null)" || return 1
  case "$subject" in
    "$MSG_SUB" | "$MSG_DOC" | "$MSG_BOTH") : ;;
    *) return 1 ;;
  esac
  changed="$(git diff --name-only --ignore-submodules=none "$1^" "$1" 2>/dev/null)" || return 1
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    _listed "$p" "$PR_HOOK_LIST" || return 1
  done <<CHANGED_EOF
$changed
CHANGED_EOF
  return 0
}

# _pr_refused <what> <output> — a push or gh call that failed, said once on
# stderr. Never retried: a rule, a credential or a concurrent push is not
# answered by asking again, and the run ends after it.
_pr_refused() {
  local what="$1" out="$2" first
  first="$(awk 'NF { sub(/[ \r]+$/, ""); print; exit }' <<<"$out" 2>/dev/null || true)"
  if _rule_refusal "$out"; then
    _log "pr: $what refused by a rule ($RULE_TEXT)"
    echo "skills update: a repository rule refused $what ($RULE_TEXT) — merge_mode pr needs $PR_BRANCH pushable, so exempt that branch from the rule; not retried (see $LOG)" >&2
  else
    _log "pr: $what failed: $first"
    echo "skills update: $what failed${first:+: $first} — not retried this run (see $LOG)" >&2
  fi
}

# _pr_publish <commit> <subject> — the commit onto $PR_BRANCH, and ONE pull
# request for it.
_pr_publish() {
  local c="$1" msg="$2" prs rc=0 tip_line tip n s oid open="" declined="" out
  local unread=() refspecs=() pr missing
  # Every PR from the branch, any state. gh failing is not "none".
  prs="$(_gh pr list --head "$PR_BRANCH" --base "$PR_BASE_BRANCH" --state all \
    --json number,state,headRefOid --jq '.[] | "\(.number) \(.state) \(.headRefOid)"' 2>&1)" || rc=$?
  if [ "$rc" -ne 0 ]; then
    { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] gh pr list exited $rc:"; printf '%s\n' "$prs"; } >>"$LOG" 2>/dev/null || true
    # The preflight found a token, so this is GitHub refusing that one. Name
    # where it came from: a stale .env token is invisible to `gh auth status`
    # in the operator's shell, which checks that shell's own (CR 1828).
    _pr_refused "gh pr list, with the token from $PR_TOKEN_FROM (is it still valid?)" "$prs"
    return 0
  fi
  tip_line="$(_pr_net git ls-remote "$PR_REMOTE" "refs/heads/$PR_BRANCH" 2>>"$LOG")" || rc=$?
  if [ "$rc" -ne 0 ]; then
    _pr_refused "reading $PR_BRANCH from $PR_REMOTE" "git ls-remote exited $rc"
    return 0
  fi
  tip=${tip_line%%[[:space:]]*}
  while read -r n s oid; do
    case "$n" in '' | *[!0-9]*) continue ;; esac
    if [ "$s" = "OPEN" ]; then
      open=${open:-$n}
    elif [ "$s" = "CLOSED" ] && [ -z "$declined" ] && [ -n "$oid" ]; then
      if ! git cat-file -e "$oid^{commit}" 2>/dev/null; then
        unread+=("$n $oid")
      elif _pr_same_bump "$oid" "$c"; then
        declined=$n
      fi
    fi
  done <<PRS_EOF
$prs
PRS_EOF

  # A closed PR's head this clone never had — another clone proposed it, or
  # gc pruned it once the branch was deleted — compared as "not the same" and
  # a declined bump was proposed again (CR 1802). GitHub keeps every PR's head
  # at refs/pull/<n>/head on the base repo, so it is fetched from there, all
  # in one fetch, and only when nothing else has settled the answer. Unable to
  # fetch, the run proposes nothing: a PR a human may already have closed is
  # a visible write, and waiting costs a day — the next day's run checks again.
  if [ -z "$open" ] && [ -z "$declined" ] && [ "${#unread[@]}" -gt 0 ]; then
    refspecs=()
    for pr in "${unread[@]}"; do
      refspecs+=("refs/pull/${pr%% *}/head")
    done
    rc=0
    { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] fetch ${refspecs[*]} to read closed PRs' heads:"; _pr_net git fetch -q --no-tags "$PR_REMOTE" "${refspecs[@]}" 2>&1; } >>"$LOG" || rc=$?
    missing=""
    for pr in "${unread[@]}"; do
      n=${pr%% *}
      oid=${pr#* }
      if [ "$rc" -ne 0 ] || ! git cat-file -e "$oid^{commit}" 2>/dev/null; then
        missing=${missing:-$n}
      elif _pr_same_bump "$oid" "$c"; then
        declined=$n
        break
      fi
    done
    if [ -z "$declined" ] && [ -n "$missing" ]; then
      _log "pr: could not fetch closed PR #$missing's head from $PR_REMOTE — whether it declined this bump is unknown, so nothing is proposed this run"
      echo "skills update: could not fetch closed PR #$missing's head from $PR_REMOTE to check whether it declined this bump, so nothing is proposed this run; the next day's refresh checks again (see $LOG)" >&2
      return 0
    fi
  fi

  # An open PR's branch is replaced only while it is still the hook's own.
  if [ -n "$open" ] && [ -n "$tip" ]; then
    if ! git cat-file -e "$tip^{commit}" 2>/dev/null; then
      if ! { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] fetch $PR_BRANCH to read PR #$open's tip:"; _pr_net git fetch -q --no-tags "$PR_REMOTE" "refs/heads/$PR_BRANCH" 2>&1; } >>"$LOG"; then
        _pr_refused "fetching $PR_BRANCH" "git fetch failed"
        return 0
      fi
    fi
    if ! _pr_hook_commit "$tip"; then
      _log "pr: PR #$open's branch $PR_BRANCH carries a commit this hook did not write — leaving it"
      echo "skills update: PR #$open's branch $PR_BRANCH carries a commit this hook did not write, so it is left as it is — merge or close it, and a later session proposes any newer bump (see $LOG)" >&2
      return 0
    fi
  fi
  # Closed unmerged, the same change: a human's no. The next upstream change
  # is proposed again; .skills/skills-pin is how to hold one for good.
  if [ -z "$open" ] && [ -n "$declined" ]; then
    _log "pr: PR #$declined proposed this same bump and was closed unmerged — not proposing it again"
    return 0
  fi

  if [ -n "$tip" ] && _pr_same_bump "$tip" "$c"; then
    _log "pr: $PR_BRANCH already proposes this bump — nothing to push"
  else
    # The lease is the tip just read; empty means "must not exist". Never a
    # plain --force: a push landing between the read and here is refused.
    rc=0
    _skip_hooks_note
    out="$(_pr_net _hook_git push --force-with-lease="refs/heads/$PR_BRANCH:$tip" "$PR_REMOTE" "$c:refs/heads/$PR_BRANCH" 2>&1)" || rc=$?
    { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] push the bump to $PR_BRANCH:"; [ -z "$out" ] || printf '%s\n' "$out"; } >>"$LOG" 2>/dev/null || true
    if [ "$rc" -ne 0 ]; then
      _pr_refused "the push to $PR_BRANCH" "$out"
      return 0
    fi
  fi
  if [ -n "$open" ]; then
    _log "pr: PR #$open proposes the bump"
    return 0
  fi
  rc=0
  out="$(_gh pr create --head "$PR_BRANCH" --base "$PR_BASE_BRANCH" --title "$msg" --body "$PR_BODY" 2>&1)" || rc=$?
  { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] gh pr create exited $rc:"; [ -z "$out" ] || printf '%s\n' "$out"; } >>"$LOG" 2>/dev/null || true
  if [ "$rc" -eq 0 ]; then
    _log "pr: opened $out"
  else
    case "$out" in
      *"already exists"*) _log "pr: a pull request from $PR_BRANCH already exists — another session opened it" ;;
      *) _pr_refused "gh pr create (the bump is on $PR_BRANCH; a later session retries)" "$out" ;;
    esac
  fi
  return 0
}

PR_BODY='Proposed by the skills auto-refresh hook (managing-skills), because .skills/merge_mode is pr here: the hook never pushes to the default branch.

Later sessions update this branch in place, at most once a day, while this pull request is open and its branch holds only the hook'"'"'s commit. Closing it unmerged declines this bump; the next upstream change is proposed again. To hold one submodule at a commit, use .skills/skills-pin.'

# _pr_refresh — the whole pr path, from the refreshed working tree.
_pr_refresh() {
  local bumped head_tree base base_tree tree rc=0 msg moves c
  # 1. The bump, read off the working tree onto HEAD.
  bumped="$(_pr_tree HEAD "${COMMIT_PATHS[@]}")" || rc=$?
  # 2. The content goes back before anything else, success or not.
  _pr_restore
  if [ "$rc" -ne 0 ] || [ -z "$bumped" ]; then
    _log "pr: could not record the bump in $PR_INDEX — nothing proposed"
    rm -f "$PR_INDEX" "$PR_INDEX.lock" 2>/dev/null || true
    return 0
  fi
  head_tree="$(git rev-parse --verify -q 'HEAD^{tree}' 2>/dev/null || true)"
  if [ "$bumped" = "$head_tree" ]; then
    _log "pr: nothing to propose — $BRANCH already records the refreshed pointers and doctor"
    return 0
  fi
  # 3. The base: the default branch as the remote has it now. A fetch, never
  # a pull — local main does not move.
  if ! { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] fetch $PR_UPSTREAM to base the pull request on:"; _pr_net git fetch -q --no-tags "$PR_REMOTE" "$PR_MERGE" 2>&1; } >>"$LOG"; then
    _pr_refused "fetching $PR_UPSTREAM" "git fetch failed"
    return 0
  fi
  base="$(git rev-parse --verify -q '@{u}^{commit}' 2>/dev/null)" || {
    _log "pr: @{u} does not resolve after the fetch — nothing proposed"
    return 0
  }
  # 4. A checkout behind on the hook's paths gets no bump: the bump was made
  # from HEAD's pointers, and the base records others (a merged refresh PR
  # not yet pulled, a pin changed upstream).
  rc=0
  git diff --quiet --ignore-submodules=none "$base" HEAD -- "${PR_HOOK_PATHS[@]}" .skills/skills-pin 2>>"$LOG" || rc=$?
  if [ "$rc" -eq 1 ]; then
    _log "pr: $BRANCH and $PR_UPSTREAM record different skills-vendor/ pointers, doctor or pin — no bump until $BRANCH is pulled"
    echo "skills update: $BRANCH and $PR_UPSTREAM record different skills-vendor/ pointers, doctor or pin, so no bump is proposed — pull $BRANCH (or drop an unpushed bump on it), and a later session proposes any newer one (see $LOG)" >&2
    return 0
  elif [ "$rc" -ne 0 ]; then
    _log "pr: could not compare $BRANCH with $PR_UPSTREAM (git diff exited $rc) — nothing proposed"
    return 0
  fi
  # 5. The pull request's commit: the base, with the bump.
  tree="$(_pr_graft "$base" "$bumped" "${COMMIT_PATHS[@]}")" || {
    _log "pr: could not build the pull request's tree — nothing proposed"
    rm -f "$PR_INDEX" "$PR_INDEX.lock" 2>/dev/null || true
    return 0
  }
  base_tree="$(git rev-parse --verify -q "$base^{tree}" 2>/dev/null || true)"
  if [ "$tree" = "$base_tree" ]; then
    _log "pr: nothing to propose — $PR_UPSTREAM already records this refresh"
    return 0
  fi
  if ! git diff --quiet --ignore-submodules=none "$base" "$tree" -- skills-vendor/ 2>/dev/null; then
    if ! git diff --quiet "$base" "$tree" -- .skills/doctor.sh 2>/dev/null; then
      msg="$MSG_BOTH"
    else
      msg="$MSG_SUB"
    fi
  else
    msg="$MSG_DOC"
  fi
  moves="$(git diff --raw --ignore-submodules=none "$base" "$tree" -- skills-vendor/ 2>/dev/null |
    awk -F '\t' '{ split($1, f, " "); printf "%s: %s -> %s\n", $2, f[3], f[4] }' || true)"
  # The subject is exactly one of the three, so _pr_hook_commit knows it again.
  [ -n "$moves" ] || moves="(the doctor only)"
  c="$(git commit-tree "$tree" -p "$base" -m "$msg" -m "$moves" 2>>"$LOG")" || {
    _log "pr: git commit-tree failed — nothing proposed"
    return 0
  }
  _log "pr: proposing $c on $PR_UPSTREAM ($msg)"
  # 6. The network, with the checkout already back on its pointer.
  _pr_publish "$c" "$msg"
  return 0
}

if [ "$MERGE_MODE" = "pr" ]; then
  _pr_refresh
  _phase "pull request"
  _finish_refresh
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
  _skip_hooks_note
  {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] commit skills update:"
    # `|| true` is load-bearing in two distinct cases, not just the obvious
    # one. (a) A path that isn't there — already excluded by the -f guard
    # above. (b) A consumer who gitignores `.skills/`: git then exits 1 for
    # the ignored path but still stages everything else, so submodule bumps
    # keep getting committed there. Tightening this into a hard failure
    # would silently strand those consumers.
    #
    # From this add to the end of the commit is the window the 11-01 kill
    # landed in (#555): the marker written above is what lets the next
    # session undo it.
    HOOK_ADDED=1
    git add -- "${COMMIT_PATHS[@]}" 2>&1 || true
    if ! git diff --cached --quiet -- "${COMMIT_PATHS[@]}" 2>/dev/null; then
      # Name what actually changed. A doctor-only refresh recorded as
      # "update skills submodules" is wrong in both the log and git history.
      STAGED_SUB=0
      STAGED_DOC=0
      git diff --cached --quiet -- skills-vendor/ 2>/dev/null || STAGED_SUB=1
      git diff --cached --quiet -- .skills/doctor.sh 2>/dev/null || STAGED_DOC=1
      if [ "$STAGED_SUB" = "1" ] && [ "$STAGED_DOC" = "1" ]; then
        MSG="$MSG_BOTH"
      elif [ "$STAGED_DOC" = "1" ]; then
        MSG="$MSG_DOC"
      else
        MSG="$MSG_SUB"
      fi
      # The commit is scoped to a pathspec, not left to sweep the index. A
      # bare `git commit` commits everything staged, so work the operator had
      # staged before this session started was absorbed into the hook's commit
      # — a local wart while the hook only committed, and a published one now
      # that it pushes (#293). Measured: a staged file reached the remote
      # under the hook's own commit message.
      #
      # The pathspec is what is actually STAGED under COMMIT_PATHS, not
      # COMMIT_PATHS itself. `git commit -- <path>` fails outright on a path
      # git does not know, and .skills/doctor.sh is exactly that for a
      # consumer who gitignores `.skills/` — the `git add` above leaves it
      # unstaged there by design. Passing COMMIT_PATHS verbatim made the whole
      # commit fail for those consumers, stranding the submodule bump too,
      # which is the hard failure the `|| true` on the add exists to avoid.
      STAGED_PATHS=()
      while IFS= read -r -d '' spath; do
        STAGED_PATHS+=("$spath")
      done < <(git diff --cached --name-only -z -- "${COMMIT_PATHS[@]}" 2>/dev/null || true)
      # Non-empty by construction — this branch runs only when the same
      # pathspec reported a staged change — but an empty array under `set -u`
      # would expand to nothing and widen the commit back to the whole index,
      # which is the defect this block is closing.
      if [ "${#STAGED_PATHS[@]}" -eq 0 ]; then
        # Reported and fallen through, never `exit`. This is inside the
        # `{ … } >>"$LOG"` group, which is not a subshell, so an exit here
        # ends the whole run — skipping _reconcile_unpushed's second call
        # site, the one that pushes what this run committed. The branch is
        # unreachable by construction, which is exactly why a wrong
        # construction here would go unnoticed.
        echo "nothing staged under this hook's paths after all — no commit"
      else
        # On failure — a consumer's pre-commit hook refusing, most often —
        # the bump is undone whole, as a refused push's is (#550, CR 1792).
        # Unstaged first: `git add` above may have staged a previously
        # *untracked* .skills/doctor.sh, and leaving a file the operator never
        # touched sitting in their index is worse than leaving the commit
        # undone. The unstage is checked, not assumed: see _unstage (#311).
        # It takes COMMIT_PATHS, the add's own pathspec; the restore takes
        # REFRESH_PATHS, because COMMIT_PATHS holds `skills-vendor/` itself
        # when nothing is pinned, and that names no registered submodule.
        # Then the content goes back to its pointer and the doctor with it:
        # unstaging alone left both ahead, with stderr silent and the day
        # spent.
        _hook_git commit -m "$MSG" -- "${STAGED_PATHS[@]}" 2>&1 || {
          echo "commit failed — undoing the bump: unstaging, then the content and the doctor back on the recorded pointer"
          echo "skills update: the commit failed (git's words in $LOG), so this run undoes its bump — the staging, the vendored content and the doctor; anything it cannot put back is said separately. The next day's refresh tries again" >&2 || true
          _unstage "a failed commit" "${COMMIT_PATHS[@]}"
          _restore_content "a failed commit" "${REFRESH_PATHS[@]}"
        }
      fi
    fi
  } >>"$LOG" || true
  _phase "commit"
fi

# The update-and-commit block has ended: the day is spent here, and not
# before, so a run killed anywhere above leaves it for the next session
# (#555). Ahead of the push, which _reconcile_unpushed retries at every
# session regardless of the lock.
_finish_refresh

# Call site 2 of 2: push what this run just committed. Cheap when call site 1
# already found nothing — it re-reads a count and returns. Separate from the
# commit block above so a push failure is never reported into that block's
# `>>"$LOG"` redirect, where the operator would never see it (the failure the
# log-a-warning alternative was rejected for).
_reconcile_unpushed

exit 0
}
