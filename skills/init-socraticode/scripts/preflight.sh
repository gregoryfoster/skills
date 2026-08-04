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
hint() { printf '      → %s\n' "$1"; }

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

# ── Gate 2: Node present and in the supported range >=18 <26 ─────────────────
# Node 26+ is a HARD REFUSAL: qdrant-js pins undici v6, which is incompatible
# with Node 26's bundled undici — the SocratiCode server process.exit(1)s on
# start. 18 / 20 / 22 / 24 are fine.
if ! command -v node >/dev/null 2>&1; then
  fail "Node not installed"
  hint "Install Node 18–24 (nvm: 'nvm install 22', or https://nodejs.org). Do NOT install Node 26+."
else
  NODE_RAW="$(node --version)"            # e.g. v22.11.0
  NODE_MAJOR="${NODE_RAW#v}"; NODE_MAJOR="${NODE_MAJOR%%.*}"
  if [ "$NODE_MAJOR" -ge 26 ]; then
    fail "Node $NODE_RAW is too new — 26+ is hard-refused (undici v6 incompatibility, server exits on start)"
    hint "Install and select Node 18–24: 'nvm install 22 && nvm use 22'"
  elif [ "$NODE_MAJOR" -lt 18 ]; then
    fail "Node $NODE_RAW is too old — need >=18"
    hint "Upgrade: 'nvm install 22 && nvm use 22'"
  else
    pass "Node $NODE_RAW in range (>=18 <26)"
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
