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
  - Runs at most once per UTC day (.git/socraticode-health.lock).
  - Silent when there is nothing to report, and on every infrastructure
    condition it cannot judge (no node, no driver, no manifest).
  - Bounded: HEALTH_TIMEOUT_MS caps the driver run (default 60000).
  - Logs to .git/socraticode-health.log (bounded to ~64 KiB / 200 lines).
  - Exits 0 on every condition.

Resolution of the driver, first hit wins. The vendor path is preferred over the
two symlink dirs, which point at it anyway (#177):
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
  HEALTH_TIMEOUT_MS       driver ceiling in ms (default 60000)
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

gitdir="$(git rev-parse --git-dir 2>/dev/null)" || exit 0
LOCK="$gitdir/socraticode-health.lock"
LOG="$gitdir/socraticode-health.log"

# Nothing to check if this repo was never indexed. The manifest is the cheapest
# reliable marker that init-socraticode ran here, and it costs no process.
[ -f .socraticodecontextartifacts.json ] || exit 0

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
date -u +%Y%m%d > "$LOCK" || true

command -v node >/dev/null 2>&1 || { _log "node not on PATH — skipped"; exit 0; }

DRIVER=""
# skills-vendor/*/ BEFORE the two symlink dirs, which are symlinks into it and
# so resolve to the same file. Preferring the real path costs nothing on a
# current install, and keeps this hook working against a vendored driver that
# predates the #177 fix — where reaching mcp-driver.mjs through the symlink made
# it exit 0 having printed nothing, which a silent-when-clean hook reports as a
# healthy install.
for candidate in \
  "${SOCRATICODE_DRIVER:-}" \
  skills-vendor/*/skills/init-socraticode/scripts/mcp-driver.mjs \
  "skills/init-socraticode/scripts/mcp-driver.mjs" \
  ".claude/skills/init-socraticode/scripts/mcp-driver.mjs" \
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
export HEALTH_TIMEOUT_MS="${HEALTH_TIMEOUT_MS:-60000}"

# Findings land on the driver's stderr, one per line; the JSON verdict is on
# stdout and goes to the log, not to the session — a session-context injection
# should be the sentence, not the payload.
FINDINGS_FILE="$gitdir/socraticode-health.findings"
RC=0
# `${A[@]+"${A[@]}"}`, not `"${A[@]}"`: under `set -u`, bash 3.2 — which is what
# macOS ships — treats an empty array expansion as an unbound variable and kills
# the hook before it can report anything.
node "$DRIVER" health-check ${PROBE_ARGS[@]+"${PROBE_ARGS[@]}"} . \
  >>"$LOG" 2>"$FINDINGS_FILE" \
  || RC=$?

if [ "$RC" -ne 0 ] && [ -s "$FINDINGS_FILE" ]; then
  echo "socraticode-health: findings from today's once-per-day check (see $LOG):"
  # `  - ` lines are the driver's findings; the rest is launch chatter.
  # POSIX bracket class, not `\s`: BSD grep -E does not know the escape.
  grep -E '^[[:space:]]+- ' "$FINDINGS_FILE" || true
  echo "socraticode-health: this hook reports only. Re-index with codebase_index, or re-run init-socraticode, to act on it."
fi

_log "health-check exited $RC"
cat "$FINDINGS_FILE" >>"$LOG" 2>/dev/null || true
rm -f "$FINDINGS_FILE"

exit 0
