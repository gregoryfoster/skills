#!/usr/bin/env bash
# socraticode-prefetch
#
# SessionStart hook: re-emits the ToolSearch prefetch instruction that loads
# SocratiCode's DEFERRED `codebase_*` MCP schemas. Claude Code injects
# SessionStart stdout as session context, so the single `echo` at the bottom of
# this file IS the hook's product — keep it on one line and keep it verbatim.
#
# Vendored source of truth (#186). Consumers symlink this file into
# `.claude/hooks/socraticode-reminder.sh` so an upstream edit to the prefetch
# query arrives on the normal submodule refresh — the shape #179 established for
# the sibling `socraticode-health.sh`, which lands in the same `.claude/hooks/`
# of the same consumer and must not be installed by the opposite mechanism.
#
# Before #186 this hook had no source file at all: it was rendered from prose in
# `references/code-exploration-policy.md`, so every consumer's copy was whatever
# the installing agent typed that day. A copy at least starts as a byte-for-byte
# snapshot of a known version; a prose-rendered hook does not even have that.
#
# The `# socraticode-prefetch` marker on line 2 is the same token the
# settings.json dedupe scans for. It is deliberately duplicated in the hook's
# command string, so the merge check can recognize the entry by reading
# settings.json alone without opening this file.
set -euo pipefail
# -E on its own line rather than a folded `set -Eeuo`: the structural suite pins
# the literal `set -euo pipefail` as the house convention, and a superset
# spelling passes shellcheck while failing that gate. Without -E the ERR trap
# below is not inherited by functions, subshells or command substitutions.
set -E

# Backstop: any unhandled error must exit 0. A SessionStart hook that fails
# closed takes the session with it, and this hook's whole job is one line of
# advice. The realistic failure is a closed or full stdout, so the degrade is a
# noisier report on stderr — never a lost session. `|| true` because the stderr
# write can fail for the same reason the stdout one did, and the ERR trap must
# still reach its `exit 0`.
_hook_panic() {
  local rc=$?
  echo "socraticode-reminder: could not print the prefetch reminder (rc=$rc); run the ToolSearch query in docs/SOCRATICODE.md by hand" >&2 || true
  exit 0
}
trap _hook_panic ERR

for arg in "$@"; do
  if [ "$arg" = "--help" ]; then
    cat <<'EOF'
Usage: bash .claude/hooks/socraticode-reminder.sh [--help]

SessionStart hook. Prints one line telling the agent to run the ToolSearch
prefetch that loads SocratiCode's deferred `codebase_*` MCP tool schemas.
Those schemas are not in the session until the prefetch loads them, and
calling one of the tools before that fails validation.

Behaviour:
  - Takes no arguments beyond --help and reads no configuration. It carries no
    per-project state, which is the argument FOR installing it as a symlink
    into skills-vendor/ rather than copying it (#186, following #179): a file
    with no per-project state is exactly the one that should track upstream
    automatically.
  - Prints to stdout, which Claude Code injects as session context.
  - Exits 0 on every path, so a failure here never blocks a session.

The prefetch query it prints must stay identical to the one in the skill's
references/socraticode-doc.md — the template a consumer's `docs/SOCRATICODE.md`
is generated from, for an operator running the query by hand. A structural test
pins this script and that template together; nothing pins a consumer's generated
copy, so a stale one is caught on the next install rather than by the suite.

Options:
  --help    Show this help and exit.

Exit codes:
  0  Always (this hook never blocks a session).
EOF
    exit 0
  fi
done

echo 'socraticode-prefetch: SocratiCode codebase_* tools are deferred. Before broad code exploration, run ToolSearch "select:mcp__plugin_socraticode_socraticode__codebase_search,mcp__plugin_socraticode_socraticode__codebase_symbol,mcp__plugin_socraticode_socraticode__codebase_symbols,mcp__plugin_socraticode_socraticode__codebase_flow,mcp__plugin_socraticode_socraticode__codebase_impact,mcp__plugin_socraticode_socraticode__codebase_graph_query,mcp__plugin_socraticode_socraticode__codebase_status,mcp__plugin_socraticode_socraticode__codebase_context,mcp__plugin_socraticode_socraticode__codebase_context_search" to load their schemas. Prefer codebase_search over grep for semantic questions.'
