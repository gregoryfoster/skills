#!/usr/bin/env bash
# Once-per-day SocratiCode infrastructure health check. Reports; never repairs.
# Designed for invocation as a Claude Code SessionStart hook — exits 0 on every
# condition so a failure here never blocks a session.
#
# Sibling of managing-skills' skills-submodule-update.sh, which established this
# cadence pattern (UTC day-stamped lock in .git/, bounded log, always exit 0).
# Deliberately a separate hook rather than an extension of that one: this one
# needs a running MCP server and the store behind it — Docker for a managed
# store, a reachable URL for an external one (#287) — and the submodule refresh
# must not start depending on either.
#
# Where the host can cap, the check runs inside a transient systemd scope with
# troubleshooting.md row U's properties (#330) — see "The memory cap" below.
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
  - codebase_graph_status measured by YIELD, not by status. READY is
    reachable with 3 edges across 374 files; the policy this skill writes then
    sends every agent to codebase_graph_query first, where an empty answer
    reads as 'no dependents' rather than 'the tool failed'. Since 1.13.0 the
    server states the resolution itself and that ruling is preferred; the
    edges/file floor is the fallback where it is silent (#207).
  - WHICH BUILD CUT THE GRAPH, against the running server's own version
    (#297). A stored graph reports READY forever, whatever built it, so a
    resolver fix shipped since is invisible from the status alone: in
    CannObserv/cannabis.observer-wordpress a graph cut by v1.10.0 sent three
    rounds of diagnosis to the conclusion that a PSR-4 composer.json
    declaration 'would not help' — PSR-4 resolution having shipped in v1.11.0,
    a version the graph predated. A stale or unstamped builder is reported
    here as its own defect, naming both versions and codebase_graph_build, so
    the hazard no longer has to live as a hand-written working rule in each
    repo's AGENTS.md. The graph is judged against the server answering the
    session's queries where the plugin's definition fixes its version (#305):
    a graph that matches it but trails the driver's own server is a note, not
    reported here, because a rebuild through the session re-stamps the same
    version — update the plugin, restart Claude Code, then rebuild.
  - A configured repo missing its toolchain on this machine (#281): no node,
    so the codebase_* tools cannot start, or no driver, so nothing was
    measured. Only past the manifest gate — see Behaviour.
  - Linked projects configured in .socraticode.json or
    SOCRATICODE_LINKED_PROJECTS whose paths do not resolve (#281). The server
    drops each without a word, so codebase_search with includeLinked: true
    searches fewer repos than the configuration names.
  - A store the server must not be launched against (#287): an external store
    with no projectId, or with the checkout's own path hash as one; a
    projectId outside [a-zA-Z0-9_-], or one a linked project shares; a store
    variable the project settings declare that the session does not carry, or
    carries with another value — or, in a worktree, a key only the main
    checkout's settings.local.json holds; a project settings file that does
    not parse. The driver then skips its server checks, since the launch is
    itself a write, and says that nothing past the configuration was measured.
  - Linked projects that break includeLinked search without blocking the
    check: one whose projectId is invalid, or two that share one.
  - A check its own memory cap stopped (#330): said as such, since nothing
    was measured, and never re-run uncapped.

It reports. It runs no docker command of its own, never re-indexes and never
edits a file — a session-start hook is the wrong place to spend an hour of CPU
or to change the repo under an agent that has already begun work. The server
it launches runs with upstream's auto-resume off and its watcher on manual, so
it writes no index content either. Upstream's own readiness paths are another
matter: on a managed store, codebase_status starts a stopped Qdrant container,
and its Docker probe wakes a socket-activated daemon; codebase_graph_status
creates a project's empty symbol-graph metadata collection when a graph lacks
one. An external store with an external embedder touches no Docker at all.

Behaviour:
  - Measures the MAIN CHECKOUT, not the session's cwd (#180). SocratiCode
    indexes by absolute project path, so from a git worktree the old literal
    '.' asked about a project that was never indexed and reported a healthy
    index as broken. The path is the parent of --git-common-dir, and it is
    skipped unless the manifest is found there.
  - Runs at most once per UTC day, per PROJECT — the lock lives in the common
    git dir, so N worktrees of one repo produce one report a day, not N.
  - Silent when there is nothing to report, and in a repo never configured
    for SocratiCode (no manifest). Past that gate a missing toolchain is a
    FINDING, not a skip (#281): no node means the codebase_* tools cannot run
    while the policy still sends agents to them, and no driver means nothing
    was measured. Each is reported once a day like any other finding. The
    manifest is tracked, so that includes a clone on a machine that never
    installed SocratiCode, whose policy block misleads it just the same.
  - Says FAILED TO RUN when the driver exits non-zero without printing any
    findings (#254). A crashed check and a check that found defects both exit
    1, and the crash must not be rendered in the shape that means "measured,
    and here is the list" — a broken check would then read as a healthy one.
  - Bounded: HEALTH_TIMEOUT_MS caps the driver run. This hook exports 60000,
    tightening mcp-driver.mjs's own 120000 default, because a session start
    must not wait two minutes on a server that will never answer.
  - Capped where the host can cap (#330). The driver and the server it
    launches run in one transient scope — systemd-run --user --scope with
    MemoryHigh=1200M MemoryMax=1536M CPUQuota=100%, under choom -n 500 so a
    session at oom_score_adj -1000 is killed by the cap rather than stalled —
    after a probe that runs the identical command and asks systemd, from
    inside its scope, whether it accounts that scope's memory — without a
    memory controller, MemoryMax= is accepted and never enforced. Where the
    host cannot cap (no systemd-run, as on macOS; no user systemd; or no
    memory controller for it — cgroup v1, or none delegated) the check runs
    uncapped, as before, and says nothing about it; a failed probe leaves one
    log line. With a pinned server the launch peaks near 75 MB and the
    cap never binds: it is for a host that never pinned, a pin that broke, or
    an index that grew.
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
  SOCRATICODE_HEALTH_CAP  the scope's systemd properties, space-separated;
                          default 'MemoryHigh=1200M MemoryMax=1536M
                          CPUQuota=100%'. 'off' runs the check uncapped, and
                          so does a value the probe rejects — the log says
                          why. A ceiling belongs to the host: set it in
                          .claude/settings.local.json, not settings.json.
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

# Past the manifest gate, a missing toolchain is reported, not skipped (#281).
# Silence is right for a repo that never adopted SocratiCode — nagging it would
# be the tuned-out reporter #180 exists to prevent — and the manifest gate above
# has already ruled that repo out. What reaches here is a project CONFIGURED for
# SocratiCode whose toolchain is missing on this machine, and that is the very
# state a once-per-day reporter exists for. CannObserv/notifier lost node, the
# plugin, the Qdrant image and its volume; this line logged "node not on PATH —
# skipped" five times over nine days, reached no session, and every agent in
# them was told by AGENTS.md to prefer codebase_search over grep.
#
# Configured is a property of the REPO; the toolchain belongs to the MACHINE.
# The manifest and this hook's registration in .claude/settings.json are both
# tracked, so a fresh clone on a machine that never installed SocratiCode lands
# here too, and hears this line once a day. That is still the right line: the
# tracked policy block sends that session's agent to codebase_search just the
# same, and the grep fallback is what it needs.
#
# The loud path is stdout, the quiet one the log, the same split every other
# finding here uses, and the lock above keeps it to one report a day. Exit 0
# still: this is advice, not a gate.
#
# The docs pointer is conditional because an install that predates the detail
# doc would be sent to a file it does not have.
_see=""
[ -f "$PROJECT/docs/SOCRATICODE.md" ] && _see=" (see docs/SOCRATICODE.md)"

if ! command -v node >/dev/null 2>&1; then
  _log "node not on PATH — reported"
  # "Will fail", not "may": the plugin starts its server as `npx` with no env
  # of its own, so the server inherits the PATH this hook was given.
  echo "socraticode-health: node is not on PATH, but this project is configured for SocratiCode (.socraticodecontextartifacts.json is present). The plugin starts its server with npx on this same PATH, so semantic search is unavailable and the codebase_* tools will fail — answer code questions with grep/rg this session."
  echo "socraticode-health: restoring node is an install fix, not a session one: init-socraticode's preflight.sh --check names what is missing${_see}."
  exit 0
fi

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
# The same argument one step on (#281). A repo carrying the manifest vendors
# this skill, so a driver found nowhere is a broken install, not an absent one,
# and the check it would have run did not happen. Said in the words the
# FAILED TO RUN branch below uses for the same fact: nothing was measured, and
# silence would read as a clean day. The tools themselves may be fine — the
# driver is only this hook's instrument — so, unlike the node case, this does
# not tell a session to stop using them.
if [ -z "$DRIVER" ]; then
  _log "mcp-driver.mjs not found — reported"
  echo "socraticode-health: this project is configured for SocratiCode (.socraticodecontextartifacts.json is present), but mcp-driver.mjs was not found, so today's check could not run. Nothing was measured — this is not a clean result."
  echo "socraticode-health: restore the vendored init-socraticode skill, or point SOCRATICODE_DRIVER at mcp-driver.mjs; --help lists where this hook looks${_see}."
  exit 0
fi

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

# ── The memory cap (#330) ────────────────────────────────────────────────────
# The one SocratiCode launch nobody watches: SessionStart, once a day, before
# any agent has context. On co-replicator (3.82 GiB, no swap, a production
# co-tenant) CannObserv/replicator#99 measured it as the only uncapped launcher
# on the host — the #295 shape, where the launch is the peak and a production
# service is what goes down. So where the host can cap, the driver runs in row U's scope, and
# the server it launches, as its child, runs there with it.
#
# Here, not in settings.json and not as an installer flag. install-hook.sh
# rebuilds this hook's command from its constants on every run, keeping only
# the timeout (#259), so a wrapper in settings.json — replicator's fix — is
# erased by the next init-socraticode re-run, silently. This file is a symlink
# into the vendored skill, so what is written here survives every re-run.
#
# Defence in depth, not the fix. Pinned (#295, #327), this launch installs
# nothing and peaks near 75 MB. The cap is for a host that never pinned, a pin
# that broke, and an index that grew.
#
# It adds no timeout of its own. HEALTH_TIMEOUT_MS still fires first and the
# 120s registration after it; the scope holds nothing the driver does not, so
# when the driver exits, on its own timer or killed, its server's stdin
# closes, the server exits, and the empty scope goes with it.
CAP_DEFAULT="MemoryHigh=1200M MemoryMax=1536M CPUQuota=100%"
CAP_PROPS=()
CAP_UNIT=""
_cap_words=()
if [ "${SOCRATICODE_HEALTH_CAP:-}" = "off" ]; then
  _log "memory cap off (SOCRATICODE_HEALTH_CAP=off) — running uncapped"
elif command -v systemd-run >/dev/null 2>&1; then
  read -r -a _cap_words <<<"${SOCRATICODE_HEALTH_CAP:-$CAP_DEFAULT}" || true
  for _w in ${_cap_words[@]+"${_cap_words[@]}"}; do
    CAP_PROPS+=(-p "$_w")
  done
fi

# The probe and the payload share this one prefix, so they cannot disagree
# (#330 trap 2). A bare `systemd-run --user --scope -q true` succeeds where the
# properties are unsupported; the real call then exits 1 with the uncapped
# branch already behind it, and a hook written never to fail closed does
# (#177) — replicator's first wrapper had exactly that bug. Unit name and
# payload aside, the probe IS the call.
#
# And a cap systemd accepts is not a cap it enforces. Where the user manager
# has no memory controller — cgroup v1, or v2 with memory neither delegated
# nor accounted — `-p MemoryMax=` is taken, exit 0, and never applied:
# measured on systemd 255 with the manager at `pids` only, the probe passed
# and a 320 MB payload outlived MemoryMax=64M. systemd knows, though. The
# scope's MemoryCurrent reads "[not set]" there and a byte count wherever it
# accounts the scope's memory, so a cap with a Memory property sends the probe
# to ask, from inside its own scope. A cap without one asks nothing (`true`):
# it is not refused over a controller it never uses.
#
# Single-quoted on purpose: the probe's `sh -c` expands it, not this shell.
# shellcheck disable=SC2016
_CAP_MEMORY_CHECK='m="$(systemctl --user show -p MemoryCurrent --value "$1")" || exit 1
case "$m" in
  "" | *[!0-9]*)
    echo "systemd accounts no memory for $1 (MemoryCurrent=${m:-empty}), so its Memory cap would not be enforced" >&2
    exit 1 ;;
esac'
#
# choom because at oom_score_adj -1000 — broker's and address-validator's
# sessions — a MemoryMax= cap stalls a process instead of killing it (#303,
# #307). Raising a score is unprivileged.
_capped() {
  local unit="$1"
  shift
  systemd-run --user --scope -q --unit="$unit" \
    ${CAP_PROPS[@]+"${CAP_PROPS[@]}"} choom -n 500 -- "$@"
}

if [ "${#CAP_PROPS[@]}" -gt 0 ]; then
  _unit="socraticode-health-$$-$(date -u +%s)"
  # Silent where it fails — every host without user systemd, linger or a
  # memory controller for it; macOS never reaches the probe at all. Only the log
  # says so. A line in every session on those hosts would be a finding that
  # always fires, the tuned-out reporter #180 exists to prevent (trap 5).
  #
  # With the first line of the probe's stderr, which is what tells a host that
  # cannot cap ("Failed to connect to bus") from a property systemd refused —
  # trap 2's host, or a mistyped SOCRATICODE_HEALTH_CAP an operator would
  # otherwise believe was in force — and from a cap it would not enforce.
  #
  # `trap - ERR` first, inside the substitution only. set -E hands the ERR
  # trap to the subshell, where the `if` no longer shields a failure from it
  # (measured on bash 3.2): _hook_panic would run there and `exit 0`, and a
  # probe that failed would read as one that passed — a capped launch on a
  # host that cannot cap, and FAILED TO RUN every day.
  _probe=(true)
  case " ${_cap_words[*]}" in
    *" Memory"*) _probe=(sh -c "$_CAP_MEMORY_CHECK" sh "$_unit-probe.scope") ;;
  esac
  if _probe_err="$(trap - ERR; _capped "$_unit-probe" "${_probe[@]}" 2>&1 >/dev/null)"; then
    CAP_UNIT="$_unit"
  else
    _probe_err="${_probe_err%%$'\n'*}"
    _log "memory cap unavailable: the probe (systemd-run --user --scope ${CAP_PROPS[*]} choom -n 500) failed (${_probe_err:-no message}) — running uncapped"
  fi
fi

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
#
# Braced, so the redirection holds this shell's stderr too: a payload killed by
# a signal — the cap's SIGKILL above all — makes bash print a "Killed" job
# notice, and it belongs in the log with the rest, not on the hook's stderr.
_driver=(node "$DRIVER" health-check ${PROBE_ARGS[@]+"${PROBE_ARGS[@]}"} "$PROJECT")
if [ -n "$CAP_UNIT" ]; then
  { _capped "$CAP_UNIT" "${_driver[@]}"; } >>"$LOG" 2>"$FINDINGS_FILE" || RC=$?
else
  { "${_driver[@]}"; } >>"$LOG" 2>"$FINDINGS_FILE" || RC=$?
fi

# Did the cap stop it? (#330) A killed payload and a crashed one both arrive as
# a non-zero RC with no findings, and they call for opposite responses, so ask
# the scope: systemd records an OOM kill as its Result. Asked only after a
# failure, and only of our own unit. The kill is recorded asynchronously, so a
# scope still winding down gets a moment — at most ~5s, well inside the 120s.
#
# A systemd that records no kill on the scope (OOMPolicy=continue) leaves the
# report at FAILED TO RUN: wrong about the cause, still louder than silence.
#
# Never re-run uncapped, whatever the answer (trap 3). `capped || uncapped`
# would re-launch, without its cap, the process the cap just stopped, on the
# host the cap was protecting.
CAP_KILLED=0
if [ -n "$CAP_UNIT" ] && [ "$RC" -ne 0 ]; then
  _result=""
  _tries=0
  while :; do
    _result="$(systemctl --user show -p Result --value "$CAP_UNIT.scope" 2>/dev/null || true)"
    [ "$_result" != "oom-kill" ] || break
    _tries=$((_tries + 1))
    [ "$_tries" -lt 25 ] || break
    case "$(systemctl --user show -p ActiveState --value "$CAP_UNIT.scope" 2>/dev/null || true)" in
      active | activating | deactivating | reloading) sleep 0.2 ;;
      *) break ;;
    esac
  done
  if [ "$_result" = "oom-kill" ]; then
    CAP_KILLED=1
    # Our own unit, and the one piece of state the cap leaves: a failed scope
    # stays listed until it is reset.
    systemctl --user reset-failed "$CAP_UNIT.scope" >/dev/null 2>&1 || true
  fi
fi

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
if [ "$CAP_KILLED" = 1 ]; then
  _limit=""
  for _w in "${_cap_words[@]}"; do
    case "$_w" in MemoryMax=*) _limit="$_w" ;; esac
  done
  _limit="${_limit:-${_cap_words[*]}}"
  _log "health-check stopped by its memory cap ($_limit) — not re-run uncapped"
  echo "socraticode-health: the check was stopped by its memory cap ($_limit) before it finished — see $LOG."
  echo "socraticode-health: this is not a clean result. Nothing was measured today, and it was not re-run uncapped: the cap keeps this host's other services up. A launch that needs that much usually installed the server — pin it (init-socraticode's references/host-memory.md); if the index has outgrown the cap, raise it with SOCRATICODE_HEALTH_CAP where the host has room."
elif [ "$RC" -ne 0 ]; then
  # `  - ` lines are the driver's findings; the rest is launch chatter.
  # POSIX bracket class, not `\s`: BSD grep -E does not know the escape.
  _found="$(grep -E '^[[:space:]]+- ' "$FINDINGS_FILE" || true)"
  if [ -n "$_found" ]; then
    echo "socraticode-health: findings from today's once-per-day check (see $LOG):"
    printf '%s\n' "$_found"
    # A finding's own fix comes first (#281). A linked project that does not
    # resolve is repaired by a checkout or by dropping the entry, and an hour
    # of re-indexing does nothing for it; a LOW yield names its own policy
    # swap. The rest name no fix, and for them the index is the lever.
    echo "socraticode-health: this hook reports only. Where a finding names its own fix, apply that; otherwise re-index with codebase_index, or re-run init-socraticode, to act on it."
  else
    echo "socraticode-health: the check FAILED TO RUN (driver exited $RC with no findings) — see $LOG."
    echo "socraticode-health: this is not a clean result. Nothing was measured today."
  fi
fi

_log "health-check exited $RC${CAP_UNIT:+ (capped: scope $CAP_UNIT.scope)}"
cat "$FINDINGS_FILE" >>"$LOG" 2>/dev/null || true
# Removal is the EXIT trap's job — it also covers the _hook_panic path, which
# used to leave the file behind in the git dir.

exit 0
