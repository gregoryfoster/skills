#!/usr/bin/env bash
# >>> usage
# preflight.sh — host readiness gates for SocratiCode indexing.
#
# Detect-and-instruct only: every failing gate prints the exact fix command and
# exits non-zero. This script NEVER installs or mutates the host toolchain
# (no auto brew/apt/nvm, no docker pulls) — that is the operator's call.
#
# Usage:
#   bash preflight.sh            # run all gates; exit 0 only if every gate passes
#   bash preflight.sh --check    # alias for the above; the fast, safe smoke test
#                                # (no mutation happens in either mode)
#   bash preflight.sh --help     # show usage
#
# One network read, and only on Node 26+: `npm view socraticode version`, to
# learn whether the build that will launch carries the Node 26 Qdrant transport
# bridge. Bounded to a few seconds and degraded to a warning when it does not
# answer, so an air-gapped host is slowed rather than blocked. Nothing else here
# touches the network, and nothing here mutates anything in either mode.
#
# Exit codes: 0 = all gates green; 1 = at least one gate failed (see messages).
# <<< usage

# -e is safe here: every gate's commands live inside `if`/`&&`/`||` conditions
# (which -e ignores), so a failing probe records FAIL and moves on rather than
# aborting. It never masks the accumulate-all-gates behavior.
set -euo pipefail

case "${1:-}" in
  --help | -h)
    # Print the sentinel-delimited usage block (robust to header edits).
    sed -n '/^# >>> usage$/,/^# <<< usage$/p' "$0" | sed '1d;$d;s/^# \{0,1\}//'
    exit 0
    ;;
  --check | '')
    : # run all gates (default); --check is an explicit alias, no mutation either way
    ;;
  *)
    echo "unknown argument: $1 (try --help)" >&2
    exit 2
    ;;
esac

FAIL=0
pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=1; }
warn() { printf '  \033[33m•\033[0m %s\n' "$1"; }
hint() { printf '      → %s\n' "$1"; }

# True when $1 >= $2, comparing dotted numeric versions field by field.
#
# Field-by-field rather than a string compare, which puts 1.9.0 above 1.13.0 —
# the exact pair this script has to get right. `sort -V` would do it on GNU
# coreutils but is not dependable on a stock macOS host, which is half the
# target platform.
#
# A prerelease tag is truncated, so 1.13.0-rc.1 counts as 1.13.0. Deliberate and
# stated: the only comparison here asks whether a build carries a fix, and an rc
# of the release that carries it does.
version_ge() {
  local a="${1%%-*}" b="${2%%-*}" ai bi i
  local -a A B
  IFS=. read -r -a A <<<"$a"
  IFS=. read -r -a B <<<"$b"
  for i in 0 1 2; do
    ai="${A[i]:-0}"; ai="${ai//[!0-9]/}"; ai="${ai:-0}"
    bi="${B[i]:-0}"; bi="${bi//[!0-9]/}"; bi="${bi:-0}"
    [ "$((10#$ai))" -gt "$((10#$bi))" ] && return 0
    [ "$((10#$ai))" -lt "$((10#$bi))" ] && return 1
  done
  return 0
}

echo "SocratiCode preflight — host readiness"
echo

# ── Gate 1: Docker installed and the daemon running ─────────────────────────
# Qdrant (vector store) and the default Ollama embedder both run as containers.
if ! command -v docker >/dev/null 2>&1; then
  fail "Docker not installed"
  hint "macOS: brew install --cask docker   Linux: https://docs.docker.com/engine/install/"
elif ! docker info >/dev/null 2>&1; then
  fail "Docker installed but the daemon is not running"
  hint "Start Docker Desktop (macOS) or: sudo systemctl start docker (Linux)"
else
  pass "Docker installed and daemon reachable"

  # Boot persistence (advisory; systemd hosts only). SocratiCode creates both
  # containers with `--restart unless-stopped`, so they come back on their own
  # once the daemon is up — the only thing that doesn't survive a reboot is a
  # daemon that was never enabled at boot. Symptom if missed: search silently
  # returns nothing after a restart (troubleshooting gotcha L).
  if command -v systemctl >/dev/null 2>&1; then
    DOCKER_BOOT="$(systemctl is-enabled docker 2>/dev/null || true)"
    DOCKER_SOCKET_BOOT="$(systemctl is-enabled docker.socket 2>/dev/null || true)"
    case "${DOCKER_BOOT}${DOCKER_SOCKET_BOOT}" in
      '')
        : # no systemd docker unit (Docker Desktop, rootless, snap) — nothing to assert
        ;;
      *enabled* | *static* | *indirect*)
        # Matches enabled / enabled-runtime on either unit; socket activation
        # counts, and "disabled" contains no "enabled" substring.
        pass "Docker starts at boot (index survives a reboot)"
        ;;
      *)
        printf '  \033[33m•\033[0m %s\n' "Docker is not enabled at boot — after a reboot the daemon stays down, Qdrant never starts, and codebase_search returns nothing"
        hint "sudo systemctl enable docker"
        ;;
    esac
  fi
fi

# ── Gate 2: Node present and supported by the server that will run ──────────
# The floor is upstream's own `engines` (>=18.17.0), not a bare major: 18.0–18.16
# satisfy ">=18" and fail the package's constraint.
#
# The ceiling is NOT a Node version. Node 26 shipped undici 8 as its built-in
# fetch, and @qdrant/js-client-rest < 1.19 hands its undici-6 Agent to that
# fetch, which used to kill the server on start. SocratiCode 1.13.0 fixed it on
# purpose — `src/services/qdrant-client-compat.ts` pairs the client's Agent with
# a matching undici — so the question is which BUILD will launch, not which Node
# is installed (#269). The plugin's mcp.json runs `npx -y --prefer-online
# socraticode@latest`, so that is what gets resolved here.
NODE_MIN=18.17.0          # upstream package.json `engines.node`
NODE26_SERVER_MIN=1.13.0  # release carrying the Node 26 transport bridge
if ! command -v node >/dev/null 2>&1; then
  fail "Node not installed"
  hint "Install Node >=$NODE_MIN (nvm: 'nvm install 22', or https://nodejs.org)"
else
  NODE_RAW="$(node --version)"            # e.g. v22.11.0
  NODE_VER="${NODE_RAW#v}"
  NODE_MAJOR="${NODE_VER%%.*}"
  if ! version_ge "$NODE_VER" "$NODE_MIN"; then
    fail "Node $NODE_RAW is too old — SocratiCode's engines require >=$NODE_MIN"
    hint "Upgrade: 'nvm install 22 && nvm use 22'"
  elif [ "$NODE_MAJOR" -lt 26 ]; then
    pass "Node $NODE_RAW (>=$NODE_MIN)"
  elif [ -n "${SOCRATICODE_ENTRY:-}" ]; then
    # The registry is not the authority here. `resolveServerLaunch` in
    # mcp-driver.mjs takes SOCRATICODE_ENTRY ahead of the plugin's recorded
    # command, so on such a host the published version describes a build that
    # will never launch — and reporting it would be a confident answer about the
    # wrong artifact, on the one gate whose job is predicting a startup failure.
    warn "Node $NODE_RAW with SOCRATICODE_ENTRY set — that build is what launches, so the published version says nothing about it"
    hint "It must be socraticode >=$NODE26_SERVER_MIN to run on Node 26+; otherwise use Node 22"
  else
    # Node 26+: resolve the build that will actually launch. Network read, never
    # a mutation, and its failure is not this gate's business to escalate.
    # Bounded: an offline host must reach the warn branch in seconds, not sit on
    # npm's default retry ladder. `timeout(1)` is not on a stock macOS, so the
    # budget is handed to npm itself.
    SC_LATEST="$(npm view socraticode version --silent \
      --fetch-timeout=5000 --fetch-retries=1 2>/dev/null || true)"
    # Last line, not `tr -d` over the whole reply: deleting newlines CONCATENATES
    # a multi-line answer, so `1.13.1\n1.13.2` would become `1.13.11.13.2` and
    # parse as a plausible 1.13.11. Every other reader in this skill degrades to
    # a stated unknown rather than to a wrong number.
    SC_LATEST="$(printf '%s' "$SC_LATEST" | tail -n 1 | tr -d '[:space:]')"
    case "$SC_LATEST" in
      [0-9]*.[0-9]*.[0-9]*)
        if version_ge "$SC_LATEST" "$NODE26_SERVER_MIN"; then
          pass "Node $NODE_RAW with socraticode $SC_LATEST (>=$NODE26_SERVER_MIN carries the Node 26 Qdrant transport bridge)"
        else
          fail "Node $NODE_RAW needs socraticode >=$NODE26_SERVER_MIN, but $SC_LATEST is what resolves — the server exits on start (undici 6 vs Node 26's undici 8)"
          hint "Use Node 22 instead: 'nvm install 22 && nvm use 22'"
        fi
        ;;
      *)
        # Undeterminable, so unprovable either way. A warning, not a refusal:
        # every published build since 1.13.0 supports Node 26, and the residual
        # failure is loud at startup rather than silent — refusing here would
        # block a working host because a registry lookup did not answer.
        warn "Node $NODE_RAW: could not resolve the socraticode version from npm, so Node 26 support is unconfirmed"
        hint "Needs socraticode >=$NODE26_SERVER_MIN; if the server exits on start, use Node 22: 'nvm install 22 && nvm use 22'"
        ;;
    esac
  fi
fi

# ── Gate 3: npx reachable (the plugin MCP server launches as `npx -y socraticode`)
if ! command -v npx >/dev/null 2>&1; then
  fail "npx not on PATH (ships with npm/Node)"
  hint "Reinstall Node so npm/npx are present, or add npm's bin dir to PATH"
else
  pass "npx reachable"
fi

# ── Gate 4 (advisory): plugin MCP server registered and Connected ───────────
# Not fatal — the bundled mcp-driver.mjs fallback works without the plugin being
# wired into the session (gotcha A). Reported so the operator knows which path
# they are on. `claude` may be absent when preflight runs outside Claude Code.
if command -v claude >/dev/null 2>&1; then
  # Marketplace first: `socraticode@socraticode` is plugin@marketplace, so the
  # install in Phase 2 cannot resolve until the marketplace is registered.
  # Reported separately from the connection check so a fresh host doesn't read
  # its missing marketplace as "just needs a restart".
  if claude plugin marketplace list 2>/dev/null | grep -q 'socraticode'; then
    pass "Marketplace 'socraticode' registered"
  else
    printf '  \033[33m•\033[0m %s\n' "Marketplace 'socraticode' not registered — 'claude plugin install socraticode@socraticode' will fail"
    hint "claude plugin marketplace add giancarloerra/socraticode"
  fi

  MCP_LIST="$(claude mcp list 2>/dev/null || true)"
  if printf '%s\n' "$MCP_LIST" | grep -q 'plugin:socraticode:socraticode.*Connected'; then
    pass "Plugin MCP server connected (plugin:socraticode:socraticode)"
  else
    printf '  \033[33m•\033[0m %s\n' "Plugin MCP server not confirmed connected (native path may need a restart)"
    hint "Install/enable: claude plugin marketplace add giancarloerra/socraticode && claude plugin install socraticode@socraticode"
    hint "Fallback works regardless: scripts/mcp-driver.mjs drives the server directly"
  fi
  # Duplicate-config trap: a standalone 'socraticode' server (its list entry
  # starts the line) coexisting with the plugin entry.
  if printf '%s\n' "$MCP_LIST" | grep -q 'plugin:socraticode' \
     && printf '%s\n' "$MCP_LIST" | grep -q '^socraticode'; then
    printf '  \033[33m•\033[0m %s\n' "Duplicate config: a standalone 'socraticode' server coexists with the plugin"
    hint "Remove the standalone: claude mcp remove socraticode"
  fi
else
  printf '  \033[33m•\033[0m %s\n' "claude CLI not found — skipping plugin-connection check"
fi

echo
if [ "$FAIL" -eq 0 ]; then
  echo "Preflight PASSED — host is ready to index."
  exit 0
else
  echo "Preflight FAILED — resolve the ✗ gates above, then re-run."
  exit 1
fi
