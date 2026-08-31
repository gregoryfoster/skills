#!/usr/bin/env bash
# Once-per-day SocratiCode infrastructure health check. Reports; never repairs.
# Designed for invocation as a Claude Code SessionStart hook — exits 0 on every
# condition so a failure here never blocks a session.
#
# Sibling of managing-skills' skills-submodule-update.sh, which established this
# cadence pattern (UTC day-stamped lock in .git/, bounded log, always exit 0).
# Deliberately a separate hook rather than an extension of that one: this one
# needs a running MCP server and Docker, and the submodule refresh must not
# start depending on either.
set -euo pipefail
# -E on its own line, not folded into `set -Eeuo` above: the structural suite
# pins the literal `set -euo pipefail` as the house convention, and a superset
# spelling passes shellcheck while failing that gate. Without -E the ERR trap
# below is not inherited by functions, subshells or command substitutions, so
# the backstop would cover only top-level commands — which is not what "any
# unhandled error must exit 0" claims.
set -E

# Backstop: any unhandled error must exit 0. A SessionStart hook that fails
# closed takes the session with it.
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
Usage: bash .claude/hooks/socraticode-health.sh [--help]

Once-per-day SocratiCode infrastructure health check. Designed for invocation
as a Claude Code SessionStart hook — never blocks a session.

What it reports (to stdout, which Claude Code injects as session context):
  - codebase_health problems: a stopped container, a missing embedding model.
  - codebase_status: a FAILED last operation, or an index marked INCOMPLETE.
    #107 found an 'Incremental update — FAILED (fetch failed)' sitting
    unreported for ~21h behind three green lights.
  - codebase_graph_status measured by EDGE YIELD, not by status. READY is
    reachable with 3 edges across 374 files; the policy this skill writes then
    sends every agent to codebase_graph_query first, where an empty answer
    reads as 'no dependents' rather than 'the tool failed'.

It reports. It never re-indexes, never starts Docker, never edits a file — a
session-start hook is the wrong place to spend an hour of CPU or to change the
repo under an agent that has already begun work.

Behaviour:
  - Measures the MAIN CHECKOUT, not the session's cwd (#180). SocratiCode
    indexes by absolute project path, so from a git worktree the old literal
    '.' asked about a project that was never indexed and reported a healthy
    index as broken. The path is the parent of --git-common-dir, and it is
    skipped unless the manifest is found there.
  - Runs at most once per UTC day, per PROJECT — the lock lives in the common
    git dir, so N worktrees of one repo produce one report a day, not N.
  - Silent when there is nothing to report, and on every infrastructure
    condition it cannot judge (no node, no driver, no manifest).
  - Says FAILED TO RUN when the driver exits non-zero without printing any
    findings (#254). A crashed check and a check that found defects both exit
    1, and the crash must not be rendered in the shape that means "measured,
    and here is the list" — a broken check would then read as a healthy one.
  - Bounded: HEALTH_TIMEOUT_MS caps the driver run. This hook exports 60000,
    tightening mcp-driver.mjs's own 120000 default, because a session start
    must not wait two minutes on a server that will never answer.
  - Logs to <common .git>/socraticode-health.log (~64 KiB / 200 lines).
  - Exits 0 on every condition.

Resolution of the driver, first hit wins. Paths below are relative to the main
checkout, and the vendor path is preferred over the two symlink dirs, which
point at it anyway (#177):
  1. \$SOCRATICODE_DRIVER               (env var; one-off override)
  2. skills-vendor/*/skills/init-socraticode/scripts/mcp-driver.mjs
  3. skills/init-socraticode/scripts/mcp-driver.mjs
  4. .claude/skills/init-socraticode/scripts/mcp-driver.mjs
  5. \$HOME/.claude/skills/init-socraticode/scripts/mcp-driver.mjs

Env:
  SOCRATICODE_DRIVER      explicit path to mcp-driver.mjs
  SOCRATICODE_PROBE_FILE  a file with known first-party imports; on a LOW yield
                          verdict the driver runs one codebase_graph_query
                          against it as a confirmatory probe
  HEALTH_TIMEOUT_MS       driver ceiling in ms. This hook exports 60000; the
                          driver's own default, for a direct run, is 120000.
                          Set it yourself for a slower, more patient check.
  SOCRATICODE_HEALTH_FORCE=1
                          ignore the once-per-day lock (for testing)

Options:
  --help    Show this help and exit.

Exit codes:
  0  Always (this hook never blocks a session).
EOF
    exit 0
  fi
done

git rev-parse --git-dir >/dev/null 2>&1 || exit 0

# The COMMON git dir, not this checkout's private one. `git rev-parse --git-dir`
# in a worktree yields .git/worktrees/<name>; --git-common-dir yields the shared
# .git for both a worktree and the primary checkout, and its parent is the
# directory SocratiCode indexed (#180).
#
# Two things hang off that, and they are the same question asked twice:
#
#   PROJECT — SocratiCode indexes by ABSOLUTE project path, so from a worktree
#     the old literal `.` asked about a project that was never indexed and
#     reported `graph is not READY` against a perfectly healthy index. Repos
#     that deploy from their main checkout are told to do feature work in
#     worktrees, so that false report was the common case, not the exception —
#     and a once-per-day reporter that cries wolf on most sessions gets tuned
#     out, taking the one true finding with it.
#
#   LOCK/LOG — one project now yields one report per day rather than one per
#     checkout of it. Leaving these in the private dir would answer #180's false
#     positive with N identical true ones.
#
# --path-format=absolute needs git >= 2.31; without it --git-common-dir is
# relative to cwd in the primary checkout (plain `.git`) and absolute in a
# worktree, so the fallback resolves it against the current directory.
commondir="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" \
  || commondir=""
if [ -z "$commondir" ]; then
  commondir="$(git rev-parse --git-common-dir 2>/dev/null)" || exit 0
  case "$commondir" in /*) ;; *) commondir="$PWD/$commondir" ;; esac
fi
gitdir="$commondir"
LOCK="$gitdir/socraticode-health.lock"
LOG="$gitdir/socraticode-health.log"

PROJECT="$(dirname "$commondir")"

# mcp-driver.mjs resolves a RELATIVE argument the same way now (#226), so this
# hook could in principle hand it a `.`. It must not, and this block does not
# shrink: $PROJECT is load-bearing for three things the driver knows nothing
# about — the manifest guard below, the driver search path, and (via $gitdir)
# the shared lock and log. Passing the resolved path also keeps the hook's
# report independent of the driver's resolution, so the two can be tested apart.

# Nothing to check if this repo was never indexed. The manifest is the cheapest
# reliable marker that init-socraticode ran here, and it costs no process.
#
# Probed at $PROJECT, the path that is about to be measured — not at `.`. In a
# worktree those differ, and asking about the wrong one is the bug above in
# miniature. It also verifies the resolution: a layout where dirname(commondir)
# is not the checkout (a bare repo's worktree, a --separate-git-dir clone) has
# no manifest there, so the hook stays silent rather than measuring a path it
# guessed. That is the issue's option 2 — resolve, then verify — settled
# locally, at no round trip.
[ -f "$PROJECT/.socraticodecontextartifacts.json" ] || exit 0

if [ "${SOCRATICODE_HEALTH_FORCE:-0}" != "1" ] \
  && [ -f "$LOCK" ] \
  && [ "$(cat "$LOCK" 2>/dev/null || true)" = "$(date -u +%Y%m%d)" ]; then
  exit 0
fi

# Bound the log: keep the last 200 lines once it crosses 64 KiB.
if [ -f "$LOG" ] && [ "$(wc -c <"$LOG")" -gt 65536 ]; then
  if tail -n 200 "$LOG" > "$LOG.tmp" 2>/dev/null; then
    mv -f "$LOG.tmp" "$LOG" 2>/dev/null || rm -f "$LOG.tmp"
  fi
fi

_log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >>"$LOG" 2>/dev/null || true
}

# Stamp the lock BEFORE the check, like the submodule hook: a transient failure
# (Docker mid-restart) must not re-run and re-log on every same-day session.
#
# Checked, not `|| true`. The lock is the hook's only state, and it now lives in
# the COMMON git dir — so a write that fails silently no longer re-reports in one
# checkout, it re-reports in EVERY checkout of the repo, every session. That is
# the tuned-out reporter #180 exists to prevent, reached by a different route.
# Reported, never fatal: this is a session hook that must not block, so a failed
# stamp degrades to noisier reporting rather than to no session.
if ! date -u +%Y%m%d > "$LOCK" 2>/dev/null; then
  _log "could not stamp $LOCK — the once-per-day guard is off until this is fixed"
  echo "socraticode-health: cannot write $LOCK; this check will repeat every session (see $LOG)" >&2
fi

command -v node >/dev/null 2>&1 || { _log "node not on PATH — skipped"; exit 0; }

DRIVER=""
# skills-vendor/*/ BEFORE the two symlink dirs, which are symlinks into it and
# so resolve to the same file. Preferring the real path costs nothing on a
# current install, and keeps this hook working against a vendored driver that
# predates the #177 fix — where reaching mcp-driver.mjs through the symlink made
# it exit 0 having printed nothing, which a silent-when-clean hook reports as a
# healthy install.
#
# Anchored at $PROJECT rather than cwd, for the same reason the measurement is
# (#180): from a worktree with uninitialized submodules — which is the state
# managing-skills' doctor exists to repair — the vendor tree is absent here but
# present in the checkout being measured.
for candidate in \
  "${SOCRATICODE_DRIVER:-}" \
  "$PROJECT"/skills-vendor/*/skills/init-socraticode/scripts/mcp-driver.mjs \
  "$PROJECT/skills/init-socraticode/scripts/mcp-driver.mjs" \
  "$PROJECT/.claude/skills/init-socraticode/scripts/mcp-driver.mjs" \
  "$HOME/.claude/skills/init-socraticode/scripts/mcp-driver.mjs"; do
  if [ -n "$candidate" ] && [ -f "$candidate" ]; then
    DRIVER="$candidate"
    break
  fi
done
[ -n "$DRIVER" ] || { _log "mcp-driver.mjs not found — skipped"; exit 0; }

PROBE_ARGS=()
if [ -n "${SOCRATICODE_PROBE_FILE:-}" ]; then
  PROBE_ARGS=(--probe "$SOCRATICODE_PROBE_FILE")
fi

# Tighter than the driver's own 2-minute default: this runs at session start,
# where a bounded wait is the whole contract. An operator who wants the slower,
# more patient check sets the variable themselves.
#
# The disagreement is deliberate (#187) — 60s is a session hook's budget, 120s
# is a direct health check's — so the number a reader sees must depend on which
# entry point they read. Both usage blocks name both numbers, and
# tests/structural/test_health_timeout_contract.py keeps them doing so.
export HEALTH_TIMEOUT_MS="${HEALTH_TIMEOUT_MS:-60000}"

# Findings land on the driver's stderr, one per line; the JSON verdict is on
# stdout and goes to the log, not to the session — a session-context injection
# should be the sentence, not the payload.
#
# Per-PID, and removed on every exit path. $gitdir is the COMMON git dir now
# (#180), so this file is shared by every checkout of the repo: two sessions
# starting in the same second both clear the lock before either stamps it, and
# a single fixed name would let one truncate the other's findings mid-report.
# The lock makes that rare, not impossible, and the failure would be a garbled
# report — which is the one thing a reporter must not produce.
#
# Sweeping first is what keeps per-PID from trading one stale file for many.
# bash runs an EXIT trap on an untrapped SIGTERM (verified), so ordinary
# termination is covered and only SIGKILL can strand one — but a strand is now
# unbounded where the old fixed name self-limited to a single file, and it
# accumulates in state shared by every checkout.
#
# Only files whose PID is gone. A blanket `rm -f …findings.*` would delete a
# concurrent session's file mid-write, which is precisely the garbled report the
# per-PID name exists to prevent — the sweep must not reintroduce the race it is
# cleaning up after.
for _stale in "$gitdir"/socraticode-health.findings.*; do
  [ -f "$_stale" ] || continue          # unmatched glob stays literal
  _pid="${_stale##*.}"
  case "$_pid" in
    ''|*[!0-9]*) continue ;;            # not a PID suffix — leave it alone
  esac
  kill -0 "$_pid" 2>/dev/null || rm -f "$_stale"
done
FINDINGS_FILE="$gitdir/socraticode-health.findings.$$"
trap 'rm -f "${FINDINGS_FILE:-}"' EXIT
RC=0
# `${A[@]+"${A[@]}"}`, not `"${A[@]}"`: under `set -u`, bash 3.2 — which is what
# macOS ships — treats an empty array expansion as an unbound variable and kills
# the hook before it can report anything.
node "$DRIVER" health-check ${PROBE_ARGS[@]+"${PROBE_ARGS[@]}"} "$PROJECT" \
  >>"$LOG" 2>"$FINDINGS_FILE" \
  || RC=$?

# A non-zero RC has TWO meanings and they are opposites (#254): the driver
# exits 1 for "defects found" (#220), and node also exits 1 for an error thrown
# out of the dispatch — `server process exited (code N) with requests in
# flight`, say, which is what an interpreter change under the plugin's mcp.json
# produced in the field. So the findings themselves, not the exit code, decide
# which sentence the operator gets.
#
# Captured into a scalar first, then branched on. Printing the header before
# the grep is what made a crash render as a clean-but-listed result: the header
# and footer were unconditional, `grep` matched nothing, and the `|| true` —
# correctly there, so a findings-free grep cannot kill this `set -e` hook —
# swallowed the last chance to notice. Same shape the gate scripts use for the
# same reason (docs/STYLE.md, "Gate-script discipline").
#
# The guard is RC alone, no longer `RC != 0 && -s findings`: a driver that dies
# with an empty stderr (SIGKILL, an OOM) also measured nothing, and the
# invariant behind #177/#214/#225/#254 is that for a reporter that is silent
# when clean, EVERY failure mode must be louder than silence, never quieter.
if [ "$RC" -ne 0 ]; then
  # `  - ` lines are the driver's findings; the rest is launch chatter.
  # POSIX bracket class, not `\s`: BSD grep -E does not know the escape.
  _found="$(grep -E '^[[:space:]]+- ' "$FINDINGS_FILE" || true)"
  if [ -n "$_found" ]; then
    echo "socraticode-health: findings from today's once-per-day check (see $LOG):"
    printf '%s\n' "$_found"
    echo "socraticode-health: this hook reports only. Re-index with codebase_index, or re-run init-socraticode, to act on it."
  else
    echo "socraticode-health: the check FAILED TO RUN (driver exited $RC with no findings) — see $LOG."
    echo "socraticode-health: this is not a clean result. Nothing was measured today."
  fi
fi

_log "health-check exited $RC"
cat "$FINDINGS_FILE" >>"$LOG" 2>/dev/null || true
# Removal is the EXIT trap's job — it also covers the _hook_panic path, which
# used to leave the file behind in the git dir.

exit 0
