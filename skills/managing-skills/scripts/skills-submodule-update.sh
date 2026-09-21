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
# in place (cp, GNU install, a shell redirect) and a git that ever starts to.
# Braces rather than a main() function because they change nothing else — no
# function scope for anything below to acquire, and "$@" is still the
# script's own.
{
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
  - Initializes an unregistered skills-vendor/ submodule (--init) rather
    than skipping it. A refresh that still moved nothing is reported, not
    logged as a bare success.
  - Honours per-submodule pins, so one vendored repo can be held at a
    commit while the rest keep refreshing (see Pin file below).
  - Installs or refreshes .skills/doctor.sh every session, on any branch,
    from the first vendored install-doctor.sh that succeeds — and again
    after a refresh, so a pointer bump commits the doctor it ships. Every
    installer failing is reported on stderr. A checkout whose
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
    remote, and the next session retries. Never pulls, never force-pushes,
    and never touches a commit this hook did not write.
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

# One timestamped line to $LOG. $LOG is this hook's only diagnostic surface,
# so every write to it is timestamped — an unattributed fragment there is hard
# to pin to a session.
#
# Defined here rather than below the gates, where it used to live: the
# reconcile step deliberately runs ahead of both of them (#293) and needs it.
_log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >>"$LOG" 2>/dev/null || true
}

# Resolved here, gated further down. The reconcile step is main-only for the
# same reason the commit is, but it runs before the lock, so it cannot wait
# for the `exit 0` gate to have computed this.
BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || true)"

# The commit subjects this hook authors. Named once because two places read
# them: the commit step at the bottom, and the reconcile step's authorship
# guard. Let those drift and the guard either stops recognising this hook's
# own commits (it silently stops rolling them back) or recognises too much
# (it rolls back an operator's) — so they are constants, not literals.
MSG_SUB='chore: update skills submodules'
MSG_DOC='chore: refresh .skills/doctor.sh'
MSG_BOTH='chore: update skills submodules and refresh .skills/doctor.sh'

# Set when a push fails, and read for the rest of the run. A rollback leaves
# the refreshed submodule content in the working tree, so the very next thing
# this script would otherwise do is re-stage it, re-commit it, and re-attempt
# the push it has just been refused — two network waits inside a hook with a
# 120s ceiling, and the same warning twice. One refusal is enough information
# for one run.
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
#   - the lock is stamped BEFORE the work, deliberately, so a push that
#     failed on the commit path would wait a whole UTC day to retry;
#   - the harness can kill this hook between commit and push — a timeout
#     SIGKILL, which the ERR trap cannot catch — leaving exactly the state
#     this exists to prevent. A separate pass heals it at the next session;
#   - consumers are stranded today. This reaches them with nobody visiting
#     the machine.
#
# Deliberately NEVER pulls. Landing a bump on a checkout that is behind would
# mean advancing local main, and on a deployed VM main IS the running code:
# a SessionStart hook updating deployed application code is a far larger
# authority than moving a submodule pointer. A stale consumer gets no bump,
# loudly, until a human syncs — and that is an acceptable trade because the
# rollback is the fix here and the push is the optimization. The service was
# stranded by `ahead 1`, not by a stale skills pin, and a rollback leaves the
# refreshed submodule *content* in the working tree (only the recorded
# pointer reverts), so the skills themselves keep working either way.
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

  local paths
  if {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] push $ahead unpushed commit(s) to $upstream_name:"
    # Explicit refspec, never a bare `git push`: under push.default=matching
    # that pushes every matching branch, which is not an authority an
    # unattended SessionStart hook should be exercising. Never --force, in
    # any spelling — a rejected push is information, not an obstacle.
    git push "$remote" "HEAD:$merge" 2>&1
  } >>"$LOG"; then
    _log "unpushed: pushed $ahead commit(s) to $upstream_name"
    return 0
  fi

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
    if [ "${#paths[@]}" -gt 0 ]; then
      # Same move as the commit step's failure path: leave the index as we
      # found it. A .skills/doctor.sh that was untracked before the commit
      # goes back to untracked rather than sitting staged in an index the
      # operator never touched.
      git reset -q -- "${paths[@]}" 2>>"$LOG" || true
    fi
    _log "unpushed: push failed — rolled $ahead commit(s) back; the refreshed content stays in the working tree and the next session retries"
    echo "skills update: could not push to $remote — rolled $ahead commit(s) back so this checkout matches $upstream_name (see $LOG)" >&2
  else
    _log "unpushed: push failed AND rollback failed — $BRANCH is still $ahead commit(s) ahead of $upstream_name"
    echo "skills update: $BRANCH is $ahead unpushed commit(s) ahead of $upstream_name and could be neither pushed nor rolled back — fix by hand (see $LOG)" >&2
  fi
  return 0
}

# Opportunistically install/update .skills/doctor.sh — the backport path
# for consumers added before doctor.sh existed. install-doctor.sh is a no-op
# when content matches, so the cost is one file compare per call.
#
# Called from two places. Call site 1, just below, runs on every session (not
# gated by the once-per-day lock) so accidental deletions self-heal at the
# next session start. Call site 2 runs after a successful submodule update,
# because call site 1 ran the PRE-bump installer against the PRE-bump doctor
# (#299): without it, the session that advances the pointer commits the old
# doctor beside the new pointer, and the refreshed one waits for the next
# session that reaches call site 1.
#
# Neither fires in a checkout whose skills-vendor/* are empty gitlinks — every
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
# channel every other failure here uses — once per run although this is called
# twice: the second call's failure would only repeat the first's news.
DOCTOR_INSTALL_WARNED=0
_install_doctor() {
  local installer tried=0
  for installer in skills-vendor/*/skills/managing-skills/scripts/install-doctor.sh; do
    [ -x "$installer" ] || continue
    tried=$((tried + 1))
    if bash "$installer" --quiet >>"$LOG" 2>&1; then
      return 0
    fi
    _log "doctor install failed via $installer (see lines above) — trying the next vendor, if any"
  done
  [ "$tried" -gt 0 ] || return 0
  _log "doctor install failed: all $tried vendored installer(s) failed — .skills/doctor.sh left as it was"
  if [ "$DOCTOR_INSTALL_WARNED" = "0" ]; then
    DOCTOR_INSTALL_WARNED=1
    echo "skills update: could not install .skills/doctor.sh — every vendored installer failed, so it was left as it was (see $LOG)" >&2
  fi
  return 0
}

# _install_doctor, call site 1 of 2: every session, ahead of both gates. This
# is the working-tree repair, and it should happen on every branch and every
# session. Committing the result is a separate concern and stays behind
# both gates, further down (#86).
_install_doctor

# Call site 1 of 2: every session, ahead of both gates. This is the pass that
# heals a checkout some earlier run left stranded — a push killed by the
# harness timeout, a push that failed while the remote was unreachable, or a
# commit made by a version of this hook that had no push step at all. Behind
# the once-per-day lock it would retry at most once a day; behind the branch
# gate it would never run at all on the sessions that matter.
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
#
# Checked, not `|| true` (#193). This one write IS the once-per-day contract:
# the guard at the top reads nothing else. A read-only or root-owned .git, or
# a full disk, and the stamp never lands, the guard falls through next session,
# and the whole refresh runs again — every session, forever, with nothing said.
# That is the same defect #187 fixed in socraticode-health.sh, the script this
# file's own pin comment names as its twin; the shape below is copied from it.
# Reported, never fatal: a SessionStart hook must not block, so a failed stamp
# degrades to noisier reporting rather than to no session.
if ! date -u +%Y%m%d > "$LOCK" 2>/dev/null; then
  _log "could not stamp $LOCK — the once-per-day guard is off until this is fixed"
  echo "skills update: cannot write $LOCK; this refresh will repeat every session (see $LOG)" >&2
fi

# Scope the update to the unpinned skills-vendor/ paths — never touch other
# submodules, and never a pinned one.
#
# `--init` is what makes this hook work on a half-healed checkout: content
# present under skills-vendor/, nothing registered in .git/config. Without it
# git skips every such submodule and exits **0** — so the guard below passes,
# no pointer moves, and the lock (stamped above, deliberately) is spent. A
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

  # _install_doctor, call site 2 of 2 (#299): the update may just have
  # replaced the vendored install-doctor.sh and doctor.sh, so run the
  # POST-bump installer. Here, before COMMIT_PATHS is built, so the doctor
  # staged and committed below is the one that ships with the pointer this run
  # records — and so the -f guard there sees a doctor this call has only just
  # created.
  _install_doctor
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

# This run has already established it cannot share a commit — the remote
# refused a push, or `main` carries commits this hook did not write and must
# not publish on the operator's behalf. Committing anyway would manufacture
# exactly the unpushed commit the reconcile step exists to prevent (#293).
# Nothing is lost by waiting: the refreshed submodule content is already in
# the working tree, so the skills themselves work today, and the pointer gets
# recorded by the first session that can actually share it.
if [ "$PUSH_BLOCKED" = "1" ]; then
  _log "commit skipped — this run cannot share what it would commit; the pointer bump waits for a session that can"
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
        # On failure, unstage what we staged. `git add` above may have staged
        # a previously *untracked* .skills/doctor.sh, and leaving a file the
        # operator never touched sitting in their index is worse than leaving
        # the commit undone — the next run retries cleanly either way.
        git commit -m "$MSG" -- "${STAGED_PATHS[@]}" 2>&1 || {
          echo "commit failed — unstaging to leave the index as we found it"
          git reset -q -- "${COMMIT_PATHS[@]}" 2>&1 || true
        }
      fi
    fi
  } >>"$LOG" || true
fi

# Call site 2 of 2: push what this run just committed. Cheap when call site 1
# already found nothing — it re-reads a count and returns. Separate from the
# commit block above so a push failure is never reported into that block's
# `>>"$LOG"` redirect, where the operator would never see it (the failure the
# log-a-warning alternative was rejected for).
_reconcile_unpushed

exit 0
}
