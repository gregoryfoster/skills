#!/usr/bin/env bash
# >>> usage
# preflight.sh — host readiness gates for SocratiCode indexing.
#
# Detect-and-instruct only: every failing gate prints the exact fix command and
# exits non-zero. This script NEVER installs or mutates the host toolchain
# (no auto brew/apt/nvm, no docker pulls, and no `claude update` or
# `exeuntu update claude`, neither of which has a check-only mode — the version
# and install age of the Claude Code running this session are reported
# instead, and PATH's beside it where the two differ) — that is the operator's
# call.
#
# Usage:
#   bash preflight.sh            # run all gates; exit 0 only if every gate passes
#   bash preflight.sh --check    # alias for the above; the fast, safe smoke test
#                                # (no mutation happens in either mode)
#   bash preflight.sh --help     # show usage
#
# Two stores (#287). `managed`, the default, runs Qdrant in a local Docker
# container. `external` reaches a shared Qdrant by URL and needs no Docker
# unless the embedder does. The mode, and each value below, is read the way the
# server will see it: this process's environment first, then the env block of
# .claude/settings.local.json, then .claude/settings.json, then the user's
# settings.json (under CLAUDE_CONFIG_DIR, default ~/.claude). On a first
# install, before the skill has written those files, pass them in the
# environment:
#
#   QDRANT_MODE=external QDRANT_URL=https://<full host name>:6333 \
#     OLLAMA_MODE=external OLLAMA_URL=http://<host>:11434 bash preflight.sh
#
# Docker is gated only when something will run in it: a managed Qdrant, or an
# Ollama embedder in `docker` mode (or `auto` mode with no native Ollama on
# localhost:11434, which falls back to a container). On a socket-activated host
# whose daemon is down, no docker command runs at all — any of them would
# start the daemon.
#
# Two launches can install at start — the driver's and the plugin session's —
# and each is pinned separately: a pre-install under SOCRATICODE_PIN_DIR, and
# SOCRATICODE_SPEC (read like the store values above) on a plugin build that
# reads it. Both pins are reported, with a warning where the driver is pinned
# and the session is not, where they disagree, or where the installed plugin
# ignores the variable (#327). Inside a session the session's pin is read off
# the process table (ps: the server its claude launched), never inferred from
# this script's own environment, and one that cannot be read is reported as
# not observed; a pinned spec no npx cache tree holds is named too, since its
# first launch installs (#332).
#
# Network reads, all bounded to a few seconds and none a write:
#   - Node 26+ only, and only while the session's launch floats: `npm view
#     socraticode version`, to learn whether the build that will launch carries
#     the Node 26 Qdrant transport bridge. Degraded to a warning when it does
#     not answer, so an air-gapped host is slowed rather than blocked.
#   - external store: GET <QDRANT_URL>/collections, without the key and then
#     with it, so a store that answers 401 is told apart from one that does not
#     answer, and a rejected key from a missing one. The key goes to curl on
#     stdin, never on its command line.
#   - Ollama in `external` mode: GET <OLLAMA_URL>/api/tags; in `auto` mode with
#     an external store, the same probe of localhost:11434 that the server
#     makes to choose between a native Ollama and a container.
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

# ── Configuration: the values the server will see ───────────────────────────
# Environment first: inside a Claude Code session it already carries the
# settings `env` block, so this is the server's own view. The settings files
# next, for a run from a plain shell: the project's two, then the user's.
#
# A pattern match, not a JSON parse: this script has to run where node is
# missing (#281 sends exactly that host here). The values it reads — a mode, a
# URL, a key — are plain strings in practice, and one that is not is refused
# rather than misread (from_settings).
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PROJECT_SETTINGS=("$ROOT/.claude/settings.local.json" "$ROOT/.claude/settings.json")
# User settings rank last, for values only (#287 CR 7): the reference offers
# them as the home of a host-wide key, and ignoring them told such a host its
# key was not set. The trust gate's declared block stays the project's alone.
USER_SETTINGS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"
ESCAPED=""

# from_settings KEY [project] [quiet] — the first settings file declaring KEY
# as a string: the project's two, then (without `project`) the user's. Sets
# S_VAL and S_SRC (relative to the repo root where it can be); both empty if
# none. S_ESC is set when the value was refused.
#
# The pattern spans JSON escapes so a value is never cut short at an escaped
# quote — `"se\"c\\ret"` used to read as `se\`, probed as a 3-character key
# and reported rejected — but an escape is not decoded, so a value holding one
# is refused, and said so once, rather than guessed at. `quiet` is for a
# caller that reads a file only to compare it with what the environment
# already supplied: warning there "not used" contradicted the ✓ that used it
# (#287 round 2, CR 43).
from_settings() {
  local key="$1" f m
  local -a files=("${PROJECT_SETTINGS[@]}")
  [ "${2:-}" = project ] || files+=("$USER_SETTINGS")
  S_VAL="" S_SRC="" S_ESC=""
  for f in "${files[@]}"; do
    [ -f "$f" ] || continue
    m="$(grep -oE "\"$key\""'[[:space:]]*:[[:space:]]*"([^"\\]|\\.)*"' "$f" 2>/dev/null | head -n 1 || true)"
    [ -n "$m" ] || continue
    S_SRC="${f#"$ROOT"/}"
    S_VAL="$(printf '%s' "$m" | sed -E 's/^"[^"]*"[[:space:]]*:[[:space:]]*"//; s/"$//')"
    case "$S_VAL" in
      *\\*)
        S_ESC=1
        case " $ESCAPED " in
          *" $key "*) ;;
          *)
            if [ "${3:-}" != quiet ]; then
              ESCAPED="$ESCAPED $key"
              warn "$key in $S_SRC holds a JSON escape this check does not decode, so this run treats it as unset — a Claude Code session started here carries it decoded"
            fi
            ;;
        esac
        S_VAL=""
        ;;
    esac
    return 0
  done
}

# resolve KEY — the environment's value, else the settings files'. Sets R_VAL,
# and R_SRC to where it came from.
resolve() {
  R_VAL="${!1:-}" R_SRC="the environment"
  if [ -z "$R_VAL" ]; then
    from_settings "$1"
    R_VAL="$S_VAL" R_SRC="$S_SRC"
  fi
}

resolve QDRANT_MODE;        STORE_MODE="$R_VAL" STORE_SRC="$R_SRC"
resolve QDRANT_URL;         Q_URL="${R_VAL%/}"
resolve QDRANT_HOST;        Q_HOST="$R_VAL"
resolve QDRANT_PORT;        Q_PORT="$R_VAL"
resolve QDRANT_API_KEY;     Q_KEY="$R_VAL"
resolve EMBEDDING_PROVIDER; E_PROVIDER="${R_VAL:-ollama}"
resolve OLLAMA_MODE;        O_MODE="${R_VAL:-auto}"
resolve OLLAMA_URL;         O_URL="${R_VAL:-http://localhost:11434}"
O_URL="${O_URL%/}"
# Declared in a FILE, whatever the environment says — the trust gate compares
# the two.
from_settings QDRANT_MODE project; DECL_MODE="$S_VAL" DECL_SRC="$S_SRC"

# Values upstream refuses (#287 CR 9). loadEmbeddingConfig (1.13.3) throws on
# an EMBEDDING_PROVIDER or OLLAMA_MODE outside these exact, case-sensitive sets
# — OLLAMA_MODE whatever the provider — and runs lazily, on the first call that
# needs the embedder, never at startup (#287 round 2, CR 42). So a typo is a
# server that connects, shows Connected, and fails every index, search and
# health call — which the gates below would otherwise read as a choice:
# `Ollama` as a cloud embedder needing no Docker, `extern` as auto. QDRANT_MODE
# is never refused, only read as managed, so a typo there is said aloud instead.
case "$E_PROVIDER" in
  ollama | openai | google | lmstudio | litellm) ;;
  *) fail "EMBEDDING_PROVIDER=$E_PROVIDER is not one upstream accepts (ollama, openai, google, lmstudio, litellm) — the server connects, then fails every index, search and health call" ;;
esac
case "$O_MODE" in
  auto | docker | external) ;;
  *) fail "OLLAMA_MODE=$O_MODE is not one upstream accepts (auto, docker, external) — the server connects, then fails every index, search and health call" ;;
esac
case "$STORE_MODE" in
  '' | external | managed) ;;
  *) warn "QDRANT_MODE=$STORE_MODE is not \"external\", so upstream runs a managed store — a local Qdrant in Docker" ;;
esac

# Upstream's own rule: anything but "external" is managed.
if [ "$STORE_MODE" = external ]; then
  echo "Store: external (QDRANT_MODE from $STORE_SRC)"
else
  STORE_MODE=managed
  echo "Store: managed — a local Qdrant in Docker"
fi

# http_status URL [KEY] — prints the HTTP status of a GET; returns curl's exit
# status, so 0 means some HTTP answer arrived. `-q` first, in every curl call
# here: it must lead to stop ~/.curlrc being read, and a `--fail` in one turned
# a 401 into exit 22, "no answer" in place of "requires an API key" (#287 CR 8).
# `--noproxy '*'` in every one too (#287 round 2, CR 32): the server's fetch
# and its Qdrant client ignore http(s)_proxy, so a probe sent through a proxy
# answers for a route the server never takes. The key rides in on stdin as a
# curl config line, never on the command line, where every process on the host
# can read it for the life of the call.
http_status() {
  local key="${2:-}" esc
  if [ -n "$key" ]; then
    esc="${key//\\/\\\\}"
    esc="${esc//\"/\\\"}"
    printf 'header = "api-key: %s"\n' "$esc" \
      | curl -q --noproxy '*' -s -o /dev/null -w '%{http_code}' --max-time 5 -K - "$1" 2>/dev/null
  else
    curl -q --noproxy '*' -s -o /dev/null -w '%{http_code}' --max-time 5 "$1" 2>/dev/null
  fi
}

# url_host URL — the host alone: no scheme, userinfo, port or path.
url_host() {
  local rest="${1#*://}"
  rest="${rest%%/*}"
  rest="${rest##*@}"
  case "$rest" in
    \[*) printf '%s' "${rest%%]*}]" ;;
    *) printf '%s' "${rest%%:*}" ;;
  esac
}

# The hosts upstream lets carry a key over plain http, and no others.
is_loopback() {
  case "$1" in
    localhost | 127.0.0.1 | \[::1\]) return 0 ;;
    *) return 1 ;;
  esac
}

# unreachable WHAT URL RC — the ✗ for a probe that got no HTTP answer, named by
# curl's exit status, because each has a different fix.
unreachable() {
  local what="$1" url="$2" rc="$3" host
  host="$(url_host "$url")"
  case "$rc" in
    1 | 3)
      # Unsupported protocol, malformed URL (#287 round 2, CR 41): a typo, not
      # a network fault. QDRANT_URL's shape is refused before any probe; this
      # is OLLAMA_URL's.
      fail "$what: $url is not a URL curl can fetch (curl exit $rc)"
      ;;
    6)
      fail "$what: cannot resolve $host"
      hint "Check the host name. On a tailnet, a peer the ACL does not admit is invisible — it fails as DNS, not as a denial"
      ;;
    7) fail "$what: cannot connect to $url (refused, or no route to it)" ;;
    28) fail "$what: no answer from $url within 5s" ;;
    35)
      # The handshake itself failed, which a certificate never causes: most
      # often the port answers plain http.
      fail "$what: TLS handshake failed at $url (curl exit 35)"
      hint "Does that port serve TLS? An http:// endpoint behind an https:// URL fails exactly this way"
      ;;
    51 | 60)
      # The certificate did not verify — and a name missing from its SAN is
      # the usual reason on a tailnet. 51 is how curl before 7.62 said it.
      fail "$what: the certificate at $url did not verify (curl exit $rc)"
      case "$host" in
        *.* | \[*) ;;
        *) hint "A certificate names the full host name, and $host is a short one — use the FQDN (on a tailnet, the full MagicDNS name <host>.<tailnet>.ts.net)" ;;
      esac
      ;;
    98)
      fail "$what: $url requires a client certificate (curl exit 98)"
      hint "The server presents none either — an endpoint behind mutual TLS is out of its reach"
      ;;
    53 | 54 | 58 | 59 | 64 | 66 | 77 | 80 | 82 | 83 | 90 | 91)
      fail "$what: TLS failed at $url (curl exit $rc)"
      ;;
    *) fail "$what: no answer from $url (curl exit $rc)" ;;
  esac
}

# The pinned pre-install, if this host has one. Read once: Gate 2 judges it as
# a build that will launch, and the driver prefers it over the plugin's command
# (#295). Absent, every consumer below behaves exactly as it did before.
SC_PIN_DIR="${SOCRATICODE_PIN_DIR:-$HOME/.socraticode/pin}"
SC_PIN_VER=""
if [ -r "$SC_PIN_DIR/node_modules/socraticode/package.json" ]; then
  # node, not jq: jq is not a dependency of this skill and node is already a
  # hard gate in Gate 2 below. Failure leaves SC_PIN_VER empty, which every
  # reader treats as "no pin" rather than as an error — a pin whose version
  # cannot be read is not a pin anyone can reason about.
  SC_PIN_VER="$(node -e 'try{const v=require(process.argv[1]).version;if(typeof v==="string")process.stdout.write(v.trim())}catch{}' \
    "$SC_PIN_DIR/node_modules/socraticode/package.json" 2>/dev/null || true)"
fi

# The plugin session's launch, as the driver reads it (#327). Two launches can
# install at start, and pinning one does not pin the other: the driver's pin
# above covers the health hook, index, status and verify; the session's server
# is the plugin's own. Since upstream 0c33776 (2026-09-20) that plugin reads
# its package spec from SOCRATICODE_SPEC, so the variable in Claude Code's
# environment when it starts pins it (a settings env block alone can miss the
# launch, below) — but that commit landed after the 1.14.0 release without a
# version bump, so an installed "1.14.0" may predate it and ignore the
# variable.
#
# Read through the driver's own resolver rather than re-implemented here: it
# follows plugin.json's `mcpServers` to the file Claude Code actually loads —
# the repo ships three launch manifests and two of them hardcode @latest — and
# expands `${VAR:-default}` the way Claude Code does (#309). The value is the
# one a session here carries: this process's, else the settings files'.
#
# SC_PLUGIN_FIXED is the exact version the plugin's definition launches, or
# SC_PLUGIN_FLOATS the spec it resolves at launch — both empty when no
# definition applies here; SC_SPEC_VAR names the variable the spec is read
# from, empty when the installed build hardcodes it.
#
# Those say what a launch carrying the variable runs, not what this session's
# did (#332): a settings env block reaches every child of a session — this
# script included — whether or not it reached the plugin's launch, and on
# three hosts it did not. So the launch is also read off the process table,
# through the driver: SC_SEEN_SPEC is the spec the session's claude launched
# its server with (several, comma-separated, if it launched several) and
# SC_SEEN_PIDS their pids, or SC_SEEN_WHY says why nothing was seen.
# SC_SEEN_FIXED is SC_SEEN_SPEC's exact version, when it is one.
# Parameter expansion, not dirname: the suite runs this script on a PATH
# holding only its stubs.
case "${BASH_SOURCE[0]}" in
  */*) SC_DRIVER_PATH="${BASH_SOURCE[0]%/*}/mcp-driver.mjs" ;;
  *) SC_DRIVER_PATH="./mcp-driver.mjs" ;;
esac
# >>> plugin-launch
SC_PLUGIN_FIXED="" SC_PLUGIN_FLOATS="" SC_SPEC_VAR=""
SC_SEEN_SPEC="" SC_SEEN_PIDS="" SC_SEEN_WHY="" SC_SEEN_FIXED=""
resolve SOCRATICODE_SPEC; SC_SPEC="$R_VAL" SC_SPEC_SRC="$R_SRC"
if command -v node >/dev/null 2>&1; then
  # Exported only when non-empty: Claude Code expands a variable set to the
  # empty string to an empty argument, not to the default, and so does the
  # driver — an empty export here would describe a launch nobody runs. The
  # driver path goes in the environment, not argv: the driver runs its CLI
  # when argv[1] is its own path, which `node -e … <driver>` would make it.
  # (No comments inside the substitution: bash 3.2 misparses a quote there.)
  SC_PLUGIN="$(
    env ${SC_SPEC:+"SOCRATICODE_SPEC=$SC_SPEC"} \
      SC_DRIVER="$SC_DRIVER_PATH" node --input-type=module -e '
      const { pathToFileURL } = await import("node:url");
      const d = await import(pathToFileURL(process.env.SC_DRIVER).href);
      const p = d.launchFromPluginConfig({ project: process.argv[1] });
      const s = p ? d.observeSessionLaunch() : null;
      const seen = s && s.observed
        ? [[...new Set(s.servers.map((x) => x.spec))].join(", "), s.servers.map((x) => x.pid).join(" "), ""]
        : ["", "", s ? s.reason : ""];
      if (p) process.stdout.write([d.pluginLaunchVersion(p) ?? "",
        d.pluginSpecFloats(p) ?? "", p.specVariable ?? "", ...seen].join("|"));
    ' "$ROOT" 2>/dev/null || true
  )"
  IFS='|' read -r SC_PLUGIN_FIXED SC_PLUGIN_FLOATS SC_SPEC_VAR SC_SEEN_SPEC SC_SEEN_PIDS SC_SEEN_WHY <<EOF
$SC_PLUGIN
EOF
fi
case "$SC_SEEN_SPEC" in
  socraticode@*)
    SC_SEEN_FIXED="${SC_SEEN_SPEC#socraticode@}"
    case "$SC_SEEN_FIXED" in '' | *[!0-9.]*) SC_SEEN_FIXED="" ;; esac
    ;;
esac
# <<< plugin-launch

# ── Host capacity: the install is the peak, not the index ───────────────────
# Advisory, never fatal. A small host CAN index — broker's 2 GB node did, under
# a cap — so this reports the headroom and names the cap rather than refusing.
#
# What it is sized against is the measured launch, not the indexing run. On
# CannObserv/broker (8 GB, SocratiCode 1.14.0) a cold `npx -y --prefer-online
# socraticode@latest` reached 1.2 G at the cgroup — ~610 MB of process plus
# ~519 MB of npm page cache — and every one of the 126 MemoryHigh throttle
# events landed in that install. The same workload from a pre-installed, pinned
# entry peaked at 75 MB, and a graph build plus a context index at 86 MB. The
# install is two orders of magnitude above the server it installs (#295).
#
# That is why the warning fires on total RAM rather than on repo size, and why
# the hint is a capped install rather than a smaller index: the index is not
# what was measured to hurt.
MEM_KB=""
SWAP_KB=""
if [ -r /proc/meminfo ]; then
  # Field 2 of each line, in kB — the only place Linux states both.
  MEM_KB="$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || true)"
  SWAP_KB="$(awk '/^SwapTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || true)"
elif [ "$(uname -s 2>/dev/null || true)" = "Darwin" ]; then
  MEM_B="$(sysctl -n hw.memsize 2>/dev/null || true)"
  case "$MEM_B" in [0-9]*) MEM_KB="$((MEM_B / 1024))" ;; esac
  # Deliberately left empty on macOS: swap is dynamic and grown on demand, so
  # "0 configured" carries none of the meaning it carries on Linux, where it
  # means there is no cushion at all. Reporting it would invite the same
  # warning on a host that is not in that trouble.
fi

# >>> host-capacity
case "$MEM_KB" in
  [0-9]*)
    MEM_GIB_X10="$((MEM_KB * 10 / 1048576))"   # tenths of a GiB, integer math
    MEM_HUMAN="$((MEM_GIB_X10 / 10)).$((MEM_GIB_X10 % 10)) GiB"
    if [ "$MEM_KB" -lt 4194304 ]; then         # < 4 GiB
      warn "Host memory $MEM_HUMAN — a cold server install peaks near 1.2 G, which is the largest thing this setup does"
      # Under choom, composed as row U's capped scope is: a session at -1000
      # passes that score to the install, and at -1000 the cap stalls it
      # rather than killing it. choom's `--` is not optional — it permutes its
      # options, so `--prefix` would be read as one of its own.
      hint "Pre-install once under a cap instead of installing at every launch: systemd-run --user --scope -p MemoryMax=1536M choom -n 500 -- npm install --prefix $SC_PIN_DIR socraticode@<version>"
      hint "mcp-driver.mjs prefers that pin over the plugin's 'npx ... @latest', so no driver launch installs anything (references/host-memory.md)"
      # The unattended launch is covered without a step here (#330): the
      # health hook opens this scope itself wherever the host can, so a
      # wrapper a repo hand-rolled around it is redundant, and the next
      # install-hook.sh run removes it anyway.
      hint "The daily health hook caps its own check the same way wherever user systemd allows (#330) — a hand-rolled systemd-run wrapper around it in .claude/settings.json can go"
      # The shared-host case, named only here. A cap on a session process
      # protects the host solely when the host's own service holds the
      # reservation, and this gate cannot tell a dev box from a production node
      # that is also ssh'd into — broker's VM was both. Saying it on every host
      # would be a warning that always fires, which is the cry-wolf shape the
      # health hook is tuned against; under 4 GiB it is the case that bites.
      #
      # Whether a cap on a session STALLS it depends on the host (#303): on
      # broker's VM session processes inherited oom_score_adj -1000, so the
      # killer could not pick them; on notifier's they sat at 0, where a cap
      # kills instead. The service's half is the same either way, so it is
      # given either way. It is not the whole answer at -1000: no killer takes
      # a -1000 process, earlyoom included, so nothing on the service's side
      # can put a session behind it, and the lever there is the session's own
      # score (#307 CR 1) — named with the check that tells the hosts apart.
      hint "If this host also runs a production service, give that service the reservation first — MemoryLow=, granted on every slice above it, and OOMScoreAdjust= — on any host (references/host-memory.md)"
      hint "Where session processes sit at oom_score_adj -1000 (cat /proc/<pid>/oom_score_adj), no killer can take one and a cgroup cap STALLS it rather than killing it — launch it under choom -n 500 -- <cmd> (raising is unprivileged), as the capped install above does"
    else
      pass "Host memory $MEM_HUMAN"
    fi
    ;;
  *)
    warn "Could not read this host's total memory — the install peak (~1.2 G) is unbudgeted here"
    ;;
esac
# <<< host-capacity

case "$SWAP_KB" in
  0)
    warn "No swap configured — past the memory ceiling the kernel fails atomic allocations in unrelated processes rather than OOM-killing one"
    hint "That is how broker's 2026-09-16 outage presented: nothing was killed, tailscaled and ksoftirqd failed allocations, and the bus was down 57m (#295)"
    ;;
esac

# >>> memory-protection
# ── Memory protection: does a unit's MemoryLow= take effect here? (#307) ────
# Advisory, never fatal, and read-only: files under /proc and the cgroup mount,
# no systemctl call, nothing written.
#
# A production unit's MemoryLow= reserves memory only up to what EVERY ancestor
# cgroup grants: the kernel scales a child's protection by its parent's
# effective protection (effective_protection() in mm/page_counter.c), and
# system.slice ships memory.low 0. On CannObserv/wslcb-licensing-tracker a unit
# at MemoryLow=256M was protected by nothing, while `systemctl show`, the
# unit's own memory.low, a clean daemon-reload and a healthy service all said
# it worked (#307). A templated unit sits one slice deeper, in an implicit
# system-<name>.slice that grants nothing either, so a system.slice grant is
# necessary and not sufficient — measured on CannObserv/address-validator,
# where postgres stayed unprotected under a working system.slice grant.
#
# So this reads the chain, not the slice alone: every unit under system.slice
# that CLAIMS protection, through nested slices however deep they go (to a
# stated bound), against the least its slices grant. It warns only on a claim
# that is clamped. A stock host, where nothing claims any, gets the reading and
# its consequence rather than a warning that fires everywhere — the cry-wolf
# shape the hint above is careful about.
#
# memory_recursiveprot is reported beside it because #307 read that mount
# option as an escape hatch. It is not one: it shares a parent's UNCLAIMED
# protection among children that claim less, in proportion to their usage, and
# a parent at 0 has none to share (systemd.resource-control(5): "it is
# generally required to set a corresponding allocation on all ancestors"). It
# does add to the reading below a granting slice, though. A slice that grants
# less than what reaches it still reserves only its own grant, and passes down
# a usage-dependent share on top, at most the grant above less its siblings'
# claims. So a unit it clamps is told what it reserves and what it may keep
# besides, not "at most 0" (#307 CR 43), and a unit its grant covers is
# reserved either way (#307 CR 66). The templated-slice clamp above was
# measured on a bare `rw` mount, without the option.
#
# The mountinfo path is the one argument, and the cgroup mount point is read
# out of it rather than assumed, so the whole reading follows from one file.
# `claims`, `flagged` and `deep` are this function's locals, which
# protection_walk and protection_line (called only from here) append to — bash
# scopes a local to its callees.
memory_protection() {
  local mountinfo="$1" found mnt opts rp slice low f i
  local claims="" flagged=0 deep="" recursive=""
  if [ ! -r "$mountinfo" ]; then
    warn "Memory protection not measured — no $mountinfo here (not Linux, or no /proc), and MemoryLow= is a Linux cgroup v2 setting"
    return 0
  fi
  # Field 5 is the mount point; after the lone '-' come the fs type, the
  # source and the superblock options, which is where memory_recursiveprot is.
  # Read with builtins, so no missing tool can turn "not measured" into a false
  # "cgroup2 is not mounted".
  found=""
  while read -r -a f; do
    for ((i = 6; i < ${#f[@]}; i++)); do
      if [ "${f[i]}" = - ]; then
        [ "${f[i + 1]:-}" = cgroup2 ] && found="${f[4]} ${f[i + 3]:-}"
        break
      fi
    done
    [ -z "$found" ] || break
  done <"$mountinfo"
  if [ -z "$found" ]; then
    warn "Memory protection not measured — cgroup2 is not mounted, so there is no memory.low for a MemoryLow= to set"
    return 0
  fi
  mnt="${found%% *}" opts="${found#* }"
  # mountinfo escapes a space in a path as \040.
  mnt="${mnt//\\040/ }"
  case ",$opts," in
    *,memory_recursiveprot,*)
      rp="with memory_recursiveprot, which shares a slice's grant but never lifts a child above it"
      recursive=1
      ;;
    *) rp="without memory_recursiveprot" ;;
  esac
  slice="$mnt/system.slice"
  low="$(cat "$slice/memory.low" 2>/dev/null || true)"
  case "$low" in
    max | [0-9]*) ;;
    *)
      warn "Memory protection not measured — no readable memory.low for system.slice under $mnt (no systemd, a container's own cgroup, or the memory controller is off there)"
      return 0
      ;;
  esac

  protection_walk "$slice" "" "$low" system.slice 1
  if [ -n "$deep" ]; then
    warn "Memory protection not measured past $PROTECTION_DEPTH levels of slice — a MemoryLow= claimed under $deep is not checked"
  fi

  if [ "$flagged" -ne 0 ]; then
    hint "Give system.slice — and every slice between it and the unit, such as a templated unit's system-<name>.slice — a MemoryLow= at least the sum of its children's, daemon-reload, then check the unit's EFFECTIVE value, not its own (references/host-memory.md). cgroup2 is mounted $rp"
  elif [ -n "$claims" ]; then
    pass "Memory protection: $claims — each within every slice's grant above it, alone and summed with its siblings (cgroup2 mounted $rp)"
  elif [ -z "$deep" ]; then
    # "Nothing under it claims" is said only of a tree read to the bottom.
    if [ "$low" = 0 ]; then
      pass "Memory protection: nothing under system.slice claims MemoryLow=, and system.slice grants none (cgroup2 mounted $rp)"
      hint "A MemoryLow= given to a production unit here would be inert until every slice above it grants one (references/host-memory.md)"
    else
      pass "Memory protection: system.slice grants $(low_human "$low"), and nothing under it claims MemoryLow= (cgroup2 mounted $rp)"
    fi
  fi
}

# low_min A B — the smaller of two memory.low readings, where `max` is no limit.
low_min() {
  if [ "$1" = max ]; then
    printf '%s' "$2"
  elif [ "$2" = max ] || [ "$1" -le "$2" ]; then
    printf '%s' "$1"
  else
    printf '%s' "$2"
  fi
}

# low_human BYTES — a memory.low reading in MiB, the unit systemd's own
# settings are usually written in.
low_human() {
  if [ "$1" = max ]; then
    printf 'max'
  elif [ "$1" -gt 0 ] && [ "$1" -lt 1048576 ]; then
    printf '%s bytes' "$1"
  else
    printf '%s MiB' "$(($1 / 1048576))"
  fi
}

# How many slices deep the walk follows, system.slice being the first. A
# template instance sits one below it, and systemd nests a dashed slice name one
# level per dash (system-a-b.slice lives in system-a.slice), so real trees stay
# shallow; the bound keeps a pathological one finite, and where it stops is
# named rather than dropped.
PROTECTION_DEPTH=6

# protection_walk DIR PREFIX GRANT GRANTER DEPTH [SOFT SHARED] — every child of
# the slice at DIR that claims MemoryLow=, against GRANT: the least any slice
# from system.slice down to this one grants, GRANTER being the slice that set it
# (the higher one on a tie). PREFIX is DIR's path below system.slice, so a unit
# is named where a reader of the cgroup tree finds it; DEPTH is DIR's own.
#
# Recursion rather than a fixed number of globbed levels: at two levels a unit
# in a slice inside a slice went unread, and under a slice granting 0 that read
# as "nothing under it claims MemoryLow=". Locals, globs and arithmetic only,
# so it runs on bash 3.2.
#
# Then the children's claims TOGETHER, against the same grant. Each within it
# is not enough: when the claims the siblings use add up past what their slice
# can pass down, effective_protection() gives each a share of that grant in
# proportion to its usage (mm/page_counter.c, "distribute shares in proportion
# to utilization"), so two 384M units under a 512M grant are not each sure of
# 384M. Read statically, as every claim in full use — the case a reservation
# exists for. Only for two claimants or more: one alone over its grant is
# already the clamp warning above, and at a grant of 0 every claimant is.
#
# GRANT is the same reading with memory_recursiveprot as without it, because
# the option only ADDS: its branch of effective_protection() hands a child
# that claims less than its parent affords a share of the parent's unclaimed
# protection, in proportion to its unprotected usage, on top of what it claims
# — never in place of it. So below a slice granting less than what reaches it,
# a unit still reserves what the chain of grants gives it, and may keep a
# usage-dependent share above that. SOFT is the static bound on what can reach
# DIR so — what reached the slice above, less its siblings' claims — and SHARED
# the clause naming where it comes from; both are empty without the option, or
# where no share reaches past GRANT. CR 43 walked SOFT in GRANT's place, and a
# chain granted in full, host-memory.md's own remedy, read as "not a
# reservation" on every host mounted with the option (#307 CR 66). The claims
# are summed before any slice is descended, since the bound needs them.
protection_walk() {
  local dir="$1" prefix="$2" grant="$3" granter="$4" depth="$5" soft="${6:-}" shared="${7:-}" d name low
  local sum=0 n=0 unbounded="" who="" here what reach up others cap hard hardby s c
  here="${prefix%/}" here="${here##*/}" here="${here:-system.slice}"
  if [ "$grant" = max ]; then
    what="$granter's unlimited grant"
  else
    what="the $(low_human "$grant") $granter grants"
  fi
  reach="$what" up="$grant"
  if [ -n "$soft" ]; then
    reach="the up to $(low_human "$soft") that reaches $here" up="$soft"
  fi
  for d in "$dir"/*/; do
    [ -d "$d" ] || continue
    d="${d%/}" name="${d##*/}"
    low="$(cat "$d/memory.low" 2>/dev/null || true)"
    case "$low" in
      max) unbounded=1 n=$((n + 1)) who="${who:+$who, }$name max" ;;
      [1-9]*) sum=$((sum + low)) n=$((n + 1)) who="${who:+$who, }$name $(low_human "$low")" ;;
      *) continue ;;
    esac
    case "$name" in
      *.slice) ;;
      *)
        protection_line "$prefix$name" "$low" "$(low_min "$grant" "$low")" "$grant" "$granter" \
          "$(low_min "$up" "$low")" "$shared"
        ;;
    esac
  done

  for d in "$dir"/*.slice/; do
    [ -d "$d" ] || continue
    d="${d%/}" name="${d##*/}"
    low="$(cat "$d/memory.low" 2>/dev/null || true)"
    case "$low" in max | [0-9]*) ;; *) continue ;; esac
    if [ "$depth" -ge "$PROTECTION_DEPTH" ]; then
      deep="${deep:+$deep, }$prefix$name"
      continue
    fi
    if [ "$(low_min "$grant" "$low")" = "$grant" ]; then
      hard="$grant" hardby="$granter"
    else
      hard="$low" hardby="$name"
    fi
    # What the option passes it besides: all that reaches DIR where it grants
    # at least that, else a share, its siblings' claims taken first. It grants
    # less than a number or max there, so it is a number; a sibling at max
    # claims everything, read in full use; the sum holds its own claim.
    s="" c=""
    if [ -n "$recursive" ]; then
      if [ "$(low_min "$up" "$low")" = "$up" ]; then
        s="$soft" c="$shared"
      else
        others=$((sum - low)) cap=0
        if [ -n "$unbounded" ]; then
          :
        elif [ "$up" = max ]; then
          cap=max
        elif [ "$up" -gt "$others" ]; then
          cap=$((up - others))
        fi
        if [ "$cap" = max ] || [ "$cap" -gt "$low" ]; then
          if [ "$others" -gt 0 ]; then others=" less the $(low_human "$others") its siblings claim"; else others=""; fi
          s="$cap" c="with memory_recursiveprot, $name passes down a share of $reach$others, in proportion to its usage"
        elif [ -n "$soft" ]; then
          # Nothing unclaimed left to share here: its own grant bounds it.
          s="$low" c="$shared, then $name grants $(low_human "$low")"
        fi
      fi
      # Named only where it reaches past the chain of grants.
      if [ -n "$s" ] && [ "$(low_min "$s" "$hard")" = "$s" ]; then s="" c=""; fi
    fi
    protection_walk "$d" "$prefix$name/" "$hard" "$hardby" "$((depth + 1))" "$s" "$c"
  done

  case "$grant" in max | 0) return 0 ;; esac
  [ "$n" -ge 2 ] || return 0
  if [ -n "$unbounded" ] || [ "$sum" -gt "$grant" ]; then
    if [ -n "$unbounded" ]; then sum=max; fi
    flagged=1
    warn "Memory protection: under $here, $n children claim $(low_human "$sum") together ($who), more than $what — once they use their claims, each keeps a share of it in proportion to its usage, not what it claims${soft:+; memory_recursiveprot may pass down more, up to $(low_human "$soft") in all, but by usage, not by reservation}"
  fi
}

# protection_line UNIT CLAIM EFFECTIVE GRANT GRANTER [SHARE SHARED] — one
# claiming unit: tallied when every slice above grants its claim, a warning
# naming the slice that clamps it when one does not, and saying what it may
# keep above that where SHARED says memory_recursiveprot passes a share down,
# of up to SHARE (see protection_walk). "Reserves up to", not "keeps": what it
# keeps also depends on its siblings' claims, which protection_walk sums.
protection_line() {
  local unit="$1" claim="$2" eff="$3" grant="$4" granter="$5" share="${6:-}" shared="${7:-}" who kept
  if [ "$eff" = "$claim" ]; then
    claims="${claims:+$claims, }$unit reserves up to $(low_human "$claim")"
    return 0
  fi
  flagged=1
  claims="${claims:+$claims, }$unit"
  if [ "$granter" = system.slice ]; then
    who="system.slice grants $(low_human "$grant")"
  else
    who="its $granter grants $(low_human "$grant")"
  fi
  if [ -n "$shared" ]; then
    kept="reserves only $(low_human "$eff")"
    [ "$eff" != 0 ] || kept="reserves none of it"
    warn "Memory protection: $unit claims MemoryLow=$(low_human "$claim") but $kept — $who — and above that keeps a usage-dependent share of up to $(low_human "$share"): $shared. A share, not a reservation"
    return 0
  fi
  warn "Memory protection: $unit claims MemoryLow=$(low_human "$claim") but keeps at most $(low_human "$eff") — $who, and a unit keeps no more than every slice above it grants"
}

memory_protection /proc/self/mountinfo
# <<< memory-protection

# ── Gate 1: Docker — only when something will run in it ─────────────────────
# A managed Qdrant is a container. So is an Ollama embedder in `docker` mode,
# and one in `auto` mode (upstream's default) unless a native Ollama answers on
# localhost:11434 — the server makes that same probe, with a 2s budget, to
# choose. An external store with an external (or cloud) embedder starts no
# container, and demanding Docker there reported a ✗ that was not a defect
# (#287).
# DOCKER_FOR says why, for the gate's own line; DOCKER_WHAT names what runs,
# for the boot-persistence lines, which used to say "Qdrant never starts" on a
# host where only an Ollama container needed Docker (#287 CR 22).
DOCKER_FOR="" DOCKER_WHAT=""
if [ "$STORE_MODE" = managed ]; then
  DOCKER_FOR="the managed Qdrant" DOCKER_WHAT="the Qdrant container"
fi
if [ "$E_PROVIDER" = ollama ]; then
  case "$O_MODE" in
    external) ;;
    docker)
      DOCKER_FOR="${DOCKER_FOR:+$DOCKER_FOR and }the Ollama embedder (OLLAMA_MODE=docker)"
      DOCKER_WHAT="${DOCKER_WHAT:+$DOCKER_WHAT and }the Ollama container"
      ;;
    *)
      # Probed only where the answer changes the verdict: next to a managed
      # Qdrant, Docker is needed either way.
      if [ "$STORE_MODE" = external ]; then
        if command -v curl >/dev/null 2>&1; then
          NATIVE="$(curl -q --noproxy '*' -s -o /dev/null -w '%{http_code}' --max-time 2 http://localhost:11434/api/tags 2>/dev/null || true)"
        else
          # Said, not assumed: the gate below treats it as the fallback case.
          NATIVE=""
          warn "curl not found — localhost:11434 was not probed for a native Ollama, so Docker is gated as if none answers"
        fi
        if [ "$NATIVE" != 200 ]; then
          DOCKER_FOR="the Ollama embedder (OLLAMA_MODE=$O_MODE falls back to a container when no native Ollama answers on localhost:11434)"
          DOCKER_WHAT="the Ollama container"
        fi
      fi
      ;;
  esac
fi

# True on a systemd host whose Docker socket is listening while the daemon is
# down. Every docker command — `docker info` included — connects to that socket,
# and connecting STARTS the daemon: on broker's 2 GB, no-swap node a read-only
# `docker ps` brought up dockerd and containerd, ~120 MB, beside the cohort's
# production Redis (#287). `systemctl is-active` asks systemd instead, and
# touches nothing.
#
# Only where the docker CLI would reach that socket (#287 round 2, CR 39). A
# DOCKER_HOST over tcp or ssh, or a context other than `default`, points every
# docker call — the server's too — at another daemon, which says nothing about
# the local socket's state and which `docker info` can probe without touching
# it. The CLI's own order decides: DOCKER_HOST, then DOCKER_CONTEXT, then the
# config's currentContext.
docker_socket_idle() {
  local ctx
  command -v systemctl >/dev/null 2>&1 || return 1
  if [ -n "${DOCKER_HOST:-}" ]; then
    case "$DOCKER_HOST" in unix://*) ;; *) return 1 ;; esac
  else
    ctx="${DOCKER_CONTEXT:-}"
    if [ -z "$ctx" ]; then
      ctx="$(grep -oE '"currentContext"[[:space:]]*:[[:space:]]*"[^"]*"' \
        "${DOCKER_CONFIG:-${HOME:-}/.docker}/config.json" 2>/dev/null \
        | head -n 1 | sed -E 's/.*"([^"]*)"$/\1/' || true)"
    fi
    case "${ctx:-default}" in default) ;; *) return 1 ;; esac
  fi
  systemctl is-active --quiet docker.socket 2>/dev/null || return 1
  ! systemctl is-active --quiet docker.service 2>/dev/null
}

if [ -z "$DOCKER_FOR" ]; then
  pass "Docker not needed — the store is external and the embedder is not a container, so nothing here starts one"
elif ! command -v docker >/dev/null 2>&1; then
  fail "Docker not installed (needed for $DOCKER_FOR)"
  hint "macOS: brew install --cask docker   Linux: https://docs.docker.com/engine/install/"
else
  # A masked unit first, and on every path (#287 round 2, CR 31): nothing
  # starts it — not socket activation, not boot, not `systemctl start` — so a
  # stopped one is a single ✗, followed by neither the probe's "start it" hint
  # nor the boot line's ✓, which `masked` + an enabled socket used to earn.
  # `masked-runtime` is the same state, set for this boot only.
  DOCKER_MASKED=""
  if command -v systemctl >/dev/null 2>&1; then
    case "$(systemctl is-enabled docker.service 2>/dev/null || true)" in
      masked | masked-runtime) DOCKER_MASKED=1 ;;
    esac
  fi
  if [ -n "$DOCKER_MASKED" ] && ! systemctl is-active --quiet docker.service 2>/dev/null; then
    fail "docker.service is masked — neither socket activation, boot, nor systemctl start can bring the daemon up (needed for $DOCKER_FOR)"
    hint "sudo systemctl unmask docker.service"
  elif docker_socket_idle; then
    # Not probed — but not assumed either (#287 CR 10). A failed service is
    # retried by the first docker call and may fail again, and a socket this
    # user cannot write to refuses every call. Each read below asks systemd or
    # the filesystem; none connects to the socket.
    DOCKER_SOCK="${DOCKER_HOST:-unix:///var/run/docker.sock}"
    case "$DOCKER_SOCK" in
      unix://*) DOCKER_SOCK="${DOCKER_SOCK#unix://}" ;;
      *) DOCKER_SOCK="" ;;
    esac
    if systemctl is-failed --quiet docker.service 2>/dev/null; then
      fail "docker.socket is listening, but docker.service is failed — the first docker call retries it and may fail the same way (needed for $DOCKER_FOR)"
      hint "journalctl -u docker.service, then: sudo systemctl reset-failed docker.service"
    elif [ -n "$DOCKER_SOCK" ] && [ -e "$DOCKER_SOCK" ] && [ ! -w "$DOCKER_SOCK" ]; then
      fail "Docker's socket $DOCKER_SOCK is not writable by ${USER:-this user} — every docker call the server makes is refused (needed for $DOCKER_FOR)"
      hint "sudo usermod -aG docker ${USER:-<user>}, then log in again"
    else
      # The socket is how this host runs Docker, and the server's first docker
      # call brings the daemon up.
      pass "Docker is socket-activated and its daemon is down — not probed, since any docker command would start it; the server starts it on first use (needed for $DOCKER_FOR)"
    fi
  elif ! docker info >/dev/null 2>&1; then
    fail "Docker installed but the daemon is not running (needed for $DOCKER_FOR)"
    hint "Start Docker Desktop (macOS) or: sudo systemctl start docker (Linux)"
  else
    pass "Docker installed and daemon reachable (needed for $DOCKER_FOR)"
  fi

  # Boot persistence (advisory; systemd hosts only). SocratiCode creates both
  # containers with `--restart unless-stopped`, so they come back on their own
  # once the daemon is up — the only thing that doesn't survive a reboot is a
  # daemon that was never enabled at boot. Symptom if missed: search silently
  # returns nothing after a restart (troubleshooting gotcha L). `is-enabled`
  # reads unit files; like `is-active`, it never starts the daemon.
  if [ -n "$DOCKER_MASKED" ]; then
    # Stopped, the ✗ above has said it. Running — masked after it started —
    # it serves now and nothing brings it back after a reboot.
    if systemctl is-active --quiet docker.service 2>/dev/null; then
      warn "docker.service is masked — the daemon runs now, but nothing starts it after a reboot, and $DOCKER_WHAT stays down with it"
      hint "sudo systemctl unmask docker.service && sudo systemctl enable docker"
    fi
  elif command -v systemctl >/dev/null 2>&1; then
    DOCKER_BOOT="$(systemctl is-enabled docker 2>/dev/null || true)"
    DOCKER_SOCKET_BOOT="$(systemctl is-enabled docker.socket 2>/dev/null || true)"
    case "${DOCKER_BOOT}${DOCKER_SOCKET_BOOT}" in
      '')
        : # no systemd docker unit (Docker Desktop, rootless, snap) — nothing to assert
        ;;
      *enabled* | *static* | *indirect*)
        # Matches enabled / enabled-runtime on either unit; socket activation
        # counts, and "disabled" contains no "enabled" substring.
        pass "Docker starts at boot ($DOCKER_WHAT survives a reboot)"
        ;;
      *)
        warn "Docker is not enabled at boot — after a reboot the daemon stays down and $DOCKER_WHAT with it, so codebase_search fails or returns nothing"
        hint "sudo systemctl enable docker"
        ;;
    esac
  fi
fi

# An external-store client still embedding through an Ollama container is
# Docker-bound for that alone. Said whether or not Docker is here: the host
# that has it is the one that never heard it before (#287 CR 22).
if [ "$STORE_MODE" = external ] && [ -n "$DOCKER_FOR" ]; then
  warn "This external-store client still embeds through an Ollama container — OLLAMA_MODE=external with the store's OLLAMA_URL keeps it Docker-free"
fi

# ── External store: the URL, its TLS, and an answer ─────────────────────────
# Follows upstream's ensureExternalQdrantReady (1.13.3) — no key over plain http
# except to loopback — and adds the two checks it leaves to the first index:
# whether the store answers at all, and whether it takes the key.
#
# Stricter than upstream in one place, by this skill's choice (#287 CR 11): it
# requires QDRANT_URL. Upstream accepts a non-localhost QDRANT_HOST alone and
# builds http://<host>:<QDRANT_PORT> from it — plain http, which cannot carry a
# key, on a port whose default is 16333 rather than Qdrant's 6333, so the
# mistake reads as a network fault (CannObserv/broker#17, trap 3).
#
# And the URL is read the way the server's two readers of it read it, since
# curl reads more than either (#287 round 2, CR 27). @qdrant/js-client-rest
# 1.18 throws on a URL not starting with a literal `http://` or `https://` —
# case-sensitive, so `HTTPS://` too — ignores its path, and puts an http URL
# with no port on 6333; ensureExternalQdrantReady's readiness GET keeps the
# path and uses 80. curl would have guessed a scheme, followed the path, and
# probed port 80, passing each of these while the server failed every call.
if [ "$STORE_MODE" = external ]; then
  Q_SCHEME="${Q_URL%%://*}"
  case "$Q_URL" in http://* | https://*) Q_SCHEME_OK=1 ;; *) Q_SCHEME_OK="" ;; esac
  # The host compares lowercased, as upstream's URL parser returns it.
  Q_URL_HOST="$(url_host "$Q_URL" | tr '[:upper:]' '[:lower:]')"
  Q_AUTHORITY="${Q_URL#*://}" Q_PATH=""
  case "$Q_AUTHORITY" in
    */*) Q_PATH="/${Q_AUTHORITY#*/}" Q_AUTHORITY="${Q_AUTHORITY%%/*}" ;;
  esac
  Q_AUTHORITY="${Q_AUTHORITY##*@}"
  case "$Q_AUTHORITY" in
    \[*\]:*) Q_URL_PORT="${Q_AUTHORITY##*\]:}" ;;
    \[*) Q_URL_PORT="" ;;
    *:*) Q_URL_PORT="${Q_AUTHORITY##*:}" ;;
    *) Q_URL_PORT="" ;;
  esac
  if [ -z "$Q_URL" ]; then
    if [ -n "$Q_PORT" ]; then
      PORT_NOTE="port $Q_PORT"
    else
      PORT_NOTE="port 16333, QDRANT_PORT's default rather than Qdrant's 6333"
    fi
    fail "QDRANT_MODE=external but QDRANT_URL is not set${Q_HOST:+ — QDRANT_HOST=$Q_HOST alone is not enough for this skill}"
    hint "Set QDRANT_URL=https://<full host name>:6333. A URL built from QDRANT_HOST is plain http on $PORT_NOTE, and plain http cannot carry a key"
  elif [ -z "$Q_SCHEME_OK" ]; then
    fail "QDRANT_URL=$Q_URL does not start with http:// or https:// — the server's Qdrant client refuses any other form, uppercase included"
    hint "Use https://<full host name>:6333"
  elif [ -n "$Q_PATH" ]; then
    fail "QDRANT_URL=$Q_URL has a path ($Q_PATH) — the server's Qdrant client drops it and calls $Q_SCHEME://$Q_AUTHORITY at the root"
    hint "Serve the store at the root of its host and port; the client takes no path from the URL"
  elif [ "$Q_SCHEME" = http ] && [ -z "$Q_URL_PORT" ]; then
    fail "QDRANT_URL=$Q_URL names no port — the server's readiness check then reaches port 80 and its Qdrant client 6333"
    hint "Write the port: http://<host>:6333"
  elif [ -n "$Q_KEY" ] && [ "$Q_SCHEME" != https ] && ! is_loopback "$Q_URL_HOST"; then
    # Upstream refuses before it connects, so there is nothing to probe.
    fail "QDRANT_API_KEY is set but $Q_URL is not https — the server refuses to send the key over plain http"
    hint "Serve the store over TLS and use https://<full host name>:6333"
  elif ! command -v curl >/dev/null 2>&1; then
    warn "curl not found — the store at $Q_URL was not probed"
  else
    Q_RC=0
    Q_CODE="$(http_status "$Q_URL/collections")" || Q_RC=$?
    if [ "$Q_RC" -ne 0 ]; then
      unreachable "Qdrant store" "$Q_URL" "$Q_RC"
    else
      case "$Q_CODE" in
        200) pass "Qdrant store answers at $Q_URL (no key required)" ;;
        401 | 403)
          if [ -z "$Q_KEY" ]; then
            from_settings QDRANT_API_KEY "" quiet
            if [ -n "$S_ESC" ]; then
              # Set, where the operator put it — only undecodable here, so
              # "not set, put it in settings.local.json" sent them in a circle.
              fail "Qdrant store at $Q_URL requires an API key (HTTP $Q_CODE without one), and the QDRANT_API_KEY in $S_SRC was not used — it holds a JSON escape this check does not decode"
              hint "Run this check from a Claude Code session started here, whose environment carries the key decoded"
            else
              fail "Qdrant store at $Q_URL requires an API key (HTTP $Q_CODE without one), and QDRANT_API_KEY is not set"
              hint "Put it in the env block of .claude/settings.local.json — git-ignored — never in the tracked settings.json"
            fi
          else
            K_RC=0
            K_CODE="$(http_status "$Q_URL/collections" "$Q_KEY")" || K_RC=$?
            if [ "$K_RC" -ne 0 ]; then
              unreachable "Qdrant store" "$Q_URL" "$K_RC"
            elif [ "$K_CODE" = 200 ]; then
              pass "Qdrant store answers at $Q_URL and accepts QDRANT_API_KEY"
            else
              fail "Qdrant store at $Q_URL rejects QDRANT_API_KEY (HTTP $K_CODE; the key is ${#Q_KEY} characters)"
              hint "A truncated key is refused exactly like a wrong one — compare its length with the store's"
            fi
          fi
          ;;
        *) fail "Qdrant store at $Q_URL answered HTTP $Q_CODE to /collections — is it a Qdrant endpoint?" ;;
      esac
    fi
  fi
fi

# ── External embedder: an Ollama the server will not start ──────────────────
# Upstream checks it at the first index and names OLLAMA_URL when it fails; the
# model itself it pulls on demand, so only the answer is gated here.
if [ "$E_PROVIDER" = ollama ] && [ "$O_MODE" = external ]; then
  if ! command -v curl >/dev/null 2>&1; then
    warn "curl not found — Ollama at $O_URL was not probed"
  else
    O_RC=0
    O_CODE="$(http_status "$O_URL/api/tags")" || O_RC=$?
    if [ "$O_RC" -ne 0 ]; then
      unreachable "Ollama" "$O_URL" "$O_RC"
    elif [ "$O_CODE" = 200 ]; then
      pass "Ollama answers at $O_URL"
    else
      fail "Ollama at $O_URL answered HTTP $O_CODE to /api/tags"
    fi
  fi
fi

# ── Trust: the settings env block reaches this session ──────────────────────
# Claude Code applies a project's `env` block only in a trusted folder, and only
# to sessions started after it was written. Without it QDRANT_MODE reverts to
# managed and OLLAMA_MODE to auto, and the server does not report missing
# configuration — it starts a local Docker stack, through the socket if the
# host has one (CannObserv/broker#17, trap 6). Trust cannot be read reliably
# from outside (it is inherited from a parent folder, and IDE and SDK sessions
# skip the prompt), so this checks its effect: CLAUDECODE marks a process a
# session started, and that process either carries the block or does not.
#
# Every store variable the block declares, not QDRANT_MODE alone (#287 CR 2).
# The gates above read an absent value from the files, so a session that got
# QDRANT_MODE from somewhere else — user settings, a shell export — but not
# OLLAMA_MODE was reported trusted and Docker-free, while its server ran Ollama
# in auto mode and started a container. Names only: a value may be the key.
#
# Keyed on the mode the project DECLARES, where the driver's check also runs on
# the mode this process resolves (#287 round 2, CR 40). The difference is the
# first install: its Phase 1 passes the store's values inline while the
# project holds only the key, which that session started too early to carry,
# so keying on the resolved mode would fail the documented flow. The driver
# never runs before Phase 3 has written the block.
if [ "$DECL_MODE" = external ]; then
  if [ -n "${CLAUDECODE:-}" ]; then
    UNCARRIED="" DIFFERENT=""
    # The collection prefix and id override too (#287 round 2, CR 28): left
    # behind, either points every write at another collection set.
    for key in QDRANT_MODE QDRANT_URL QDRANT_HOST QDRANT_PORT QDRANT_API_KEY \
      QDRANT_COLLECTION_PREFIX SOCRATICODE_PROJECT_ID \
      OLLAMA_MODE OLLAMA_URL EMBEDDING_PROVIDER EMBEDDING_MODEL EMBEDDING_DIMENSIONS; do
      from_settings "$key" project quiet
      if [ -n "$S_ESC" ]; then
        # Declared but undecodable: presence is all there is to compare.
        [ -n "${!key:-}" ] || UNCARRIED="${UNCARRIED:+$UNCARRIED, }$key"
        continue
      fi
      [ -n "$S_VAL" ] || continue
      if [ -z "${!key:-}" ]; then
        UNCARRIED="${UNCARRIED:+$UNCARRIED, }$key"
      elif [ "${!key}" != "$S_VAL" ]; then
        DIFFERENT="${DIFFERENT:+$DIFFERENT, }$key"
      fi
    done
    # Two failures, told apart (#287 round 2, CR 29). A value the session
    # lacks is the dropped block of an untrusted folder, or one written after
    # the session began; a value it carries differently is a session that
    # started before the file changed, in a folder already trusted, where no
    # prompt will appear. And what the server runs without them is named for
    # what is missing: the mode moves the store, OLLAMA_MODE only the embedder.
    case ", $UNCARRIED, " in
      *", QDRANT_MODE, "*)
        WITHOUT="runs a managed store — a local Qdrant in Docker — instead of reaching the external one"
        ;;
      *", OLLAMA_MODE, "*)
        if [ "${EMBEDDING_PROVIDER:-ollama}" = ollama ]; then
          WITHOUT="embeds through Ollama in auto mode — a container, unless a native Ollama answers on localhost:11434 — not through the store's"
        else
          WITHOUT="runs without them"
        fi
        ;;
      *) WITHOUT="runs without them" ;;
    esac
    if [ -z "$UNCARRIED$DIFFERENT" ]; then
      pass "This session carries $DECL_SRC's env block — every store variable it declares — so the folder is trusted"
    fi
    if [ -n "$UNCARRIED" ]; then
      fail "The project settings declare store variables this session does not carry ($UNCARRIED) — its SocratiCode server $WITHOUT"
      hint "Restart Claude Code in this folder, trusting it if asked, then re-run this check from the new session"
    fi
    if [ -n "$DIFFERENT" ]; then
      fail "This session carries other values than the project settings declare ($DIFFERENT) — most likely it started before they changed, and its SocratiCode server runs the old ones"
      hint "Restart Claude Code in this folder, then re-run this check from the new session"
    fi
  else
    warn "Outside a Claude Code session, so whether $DECL_SRC's env block reaches the server is unconfirmed — an untrusted folder drops it"
    hint "Re-run this check from a Claude Code session started in this folder"
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
elif ! NODE_RAW="$(node --version 2>/dev/null)" || [ "${NODE_RAW#v[0-9]}" = "$NODE_RAW" ]; then
  # A condition, like every other probe here (#287 round 2, CR 46). Outside
  # one, a node that fails — a version-manager shim pointing at a version that
  # is not installed — ended the script under set -e: no ✗, no later gate, no
  # summary line.
  fail "Node is on PATH ($(command -v node)) but 'node --version' reported no version — a broken install, or a shim pointing at nothing"
  hint "Reinstall Node >=$NODE_MIN, or point the shim at an installed version: 'nvm install 22 && nvm use 22'"
else
  NODE_VER="${NODE_RAW#v}"                # NODE_RAW e.g. v22.11.0
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
    # Node 26+: judge every build that will actually launch — which, since #295,
    # can be TWO. A pinned pre-install is what mcp-driver.mjs runs (the health
    # hook, index and verify runs); the plugin's own session server launches
    # what its definition resolves to — `socraticode@latest` unless
    # SOCRATICODE_SPEC pins it (#327). Judging only one of them would pass a
    # host whose other server exits on start.
    if [ -n "$SC_PIN_VER" ]; then
      if version_ge "$SC_PIN_VER" "$NODE26_SERVER_MIN"; then
        pass "Node $NODE_RAW with pinned socraticode $SC_PIN_VER (>=$NODE26_SERVER_MIN carries the Node 26 Qdrant transport bridge)"
      else
        fail "Node $NODE_RAW with pinned socraticode $SC_PIN_VER — the driver's server exits on start (undici 6 vs Node 26's undici 8)"
        hint "Re-pin above $NODE26_SERVER_MIN: 'npm install --prefix $SC_PIN_DIR socraticode@latest', or use Node 22"
      fi
    fi
    # Network read, never a mutation, and its failure is not this gate's
    # business to escalate. Bounded: an offline host must reach the warn branch
    # in seconds, not sit on npm's default retry ladder. `timeout(1)` is not on
    # a stock macOS, so the budget is handed to npm itself.
    #
    # A session pinned by SOCRATICODE_SPEC launches that version, not the
    # registry's, so there is nothing to look up (#327). Which version that is
    # comes from the launch where it was seen: the variable this script
    # carries can have missed it, and then the session floats (#332).
    # >>> session-version
    if [ -n "$SC_SEEN_FIXED" ]; then
      SC_LATEST="$SC_SEEN_FIXED"
    elif [ -z "$SC_SEEN_SPEC" ] && [ -n "$SC_PLUGIN_FIXED" ]; then
      SC_LATEST="$SC_PLUGIN_FIXED"
    else
      SC_LATEST="$(npm view socraticode version --silent \
        --fetch-timeout=5000 --fetch-retries=1 2>/dev/null || true)"
    fi
    # <<< session-version
    # Last line, not `tr -d` over the whole reply: deleting newlines CONCATENATES
    # a multi-line answer, so `1.13.1\n1.13.2` would become `1.13.11.13.2` and
    # parse as a plausible 1.13.11. Every other reader in this skill degrades to
    # a stated unknown rather than to a wrong number.
    SC_LATEST="$(printf '%s' "$SC_LATEST" | tail -n 1 | tr -d '[:space:]')"
    # Named for whose server it is, so two lines on a pinned host cannot be read
    # as one answer given twice.
    SC_WHOSE="socraticode"
    [ -n "$SC_PIN_VER" ] && SC_WHOSE="the plugin session's socraticode"
    case "$SC_LATEST" in
      [0-9]*.[0-9]*.[0-9]*)
        if version_ge "$SC_LATEST" "$NODE26_SERVER_MIN"; then
          pass "Node $NODE_RAW with $SC_WHOSE $SC_LATEST (>=$NODE26_SERVER_MIN carries the Node 26 Qdrant transport bridge)"
        else
          fail "Node $NODE_RAW needs socraticode >=$NODE26_SERVER_MIN, but $SC_LATEST is what $SC_WHOSE resolves to — the server exits on start (undici 6 vs Node 26's undici 8)"
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

# ── Launch pins: the driver's and the plugin session's (#327) ───────────────
# Reported together because they are separate exposures: a pinned driver beside
# a floating session reads as done, and the session still installs at every
# start. Silent where nothing is pinned on a host with headroom — that is the
# default working as shipped, and a line that always fires is the cry-wolf
# shape the health hook is tuned against.
# >>> launch-pins
SPEC_NAME="${SC_SPEC_VAR:-SOCRATICODE_SPEC}"
# Where the variable has to be for the launch to see it (#332). A settings env
# block reaches every child of a session, and on watcher, notifier and
# address-validator not the plugin's launch: its args were expanded before
# the block was merged.
SPEC_WHERE="in Claude Code's environment when it starts — claudeCode.environmentVariables in VS Code (a machine setting), or an export in the shell that launches claude; the repo's settings env block alone can miss the launch (references/host-memory.md)"
SPEC_HINT="Pin the session: $SPEC_NAME=socraticode@${SC_PIN_VER:-<version>} $SPEC_WHERE"
if [ -n "$SC_SPEC" ] && [ -z "${SOCRATICODE_SPEC:-}" ] && [ -n "${CLAUDECODE:-}" ]; then
  # Read from the files, so the lines below describe the NEXT session; this
  # one started without it and its server launched from the default.
  warn "SOCRATICODE_SPEC is declared in $SC_SPEC_SRC, but this session does not carry it — its server launched from the plugin's default"
  hint "Restart Claude Code in this folder, trusting it if asked; if the restarted session's server still launches the default, set it $SPEC_WHERE"
fi
if [ -n "$SC_PLUGIN_FIXED" ]; then
  # The definition fixes a version once the variable is expanded into it, in
  # THIS process. Whether the session's launch saw it is the process table's
  # answer, and a pin nobody observed is never a pass (#332).
  # Two spellings, because bash 3.2 has no case conversion: one opens a line,
  # the other sits inside one.
  if [ -n "$SC_SPEC_VAR" ]; then
    SC_PINNED_BY="A session carrying $SC_SPEC_VAR" SC_PINNED_IN="a session carrying $SC_SPEC_VAR"
  else
    SC_PINNED_BY="The plugin's definition" SC_PINNED_IN="the plugin's definition"
  fi
  # The observed launch first. When it is not the fixed version, every line
  # comparing pins would describe a session that is not running — including
  # the disagreement below, whose remedy would re-pin the driver to a version
  # nothing launched (CR 1). A pinned server beside another is not that: the
  # pin reached a launch, the other is a second server, and setting the
  # variable again changes nothing (CR 9).
  SC_SEEN_BESIDE=""
  case ", $SC_SEEN_SPEC, " in
    *", socraticode@$SC_PLUGIN_FIXED, "*)
      [ "$SC_SEEN_SPEC" = "socraticode@$SC_PLUGIN_FIXED" ] || SC_SEEN_BESIDE=1 ;;
  esac
  if [ -n "$SC_SEEN_BESIDE" ]; then
    warn "The session's claude launched a second socraticode server beside the pinned socraticode@$SC_PLUGIN_FIXED ('$SC_SEEN_SPEC', pids $SC_SEEN_PIDS) — two builds writing one store"
    hint "A standalone MCP entry beside the plugin's is the usual source: claude mcp remove socraticode, then restart the session"
  elif [ -n "$SC_SEEN_SPEC" ] && [ "$SC_SEEN_SPEC" != "socraticode@$SC_PLUGIN_FIXED" ]; then
    if [ -n "${SOCRATICODE_SPEC:-}" ]; then
      warn "The session's server was launched as '$SC_SEEN_SPEC' (pid $SC_SEEN_PIDS), not socraticode@$SC_PLUGIN_FIXED — $SPEC_NAME reached this shell but not the launch"
    else
      warn "The session's server was launched as '$SC_SEEN_SPEC' (pid $SC_SEEN_PIDS), not socraticode@$SC_PLUGIN_FIXED"
    fi
    hint "Set $SPEC_NAME=socraticode@${SC_PIN_VER:-$SC_PLUGIN_FIXED} $SPEC_WHERE"
    hint "Then restart the session: its server reads the variable only when it launches"
  elif [ -n "$SC_PIN_VER" ] && [ "$SC_PIN_VER" != "$SC_PLUGIN_FIXED" ]; then
    if [ -n "$SC_SEEN_SPEC" ]; then
      SC_SESSION_SIDE="the plugin session launched $SC_PLUGIN_FIXED (observed)"
    else
      SC_SESSION_SIDE="$SC_PINNED_IN launches $SC_PLUGIN_FIXED (not observed: ${SC_SEEN_WHY:-the process table was not read})"
    fi
    warn "Launch pins disagree: the driver's pin is socraticode $SC_PIN_VER, $SC_SESSION_SIDE — two builds writing one store"
    hint "Pin both to one version: $SPEC_NAME=socraticode@$SC_PIN_VER, or re-pin the driver with 'npm install --prefix $SC_PIN_DIR socraticode@$SC_PLUGIN_FIXED'"
  elif [ -n "$SC_SEEN_SPEC" ]; then
    pass "Plugin session launched socraticode $SC_PLUGIN_FIXED — observed: its server (pid $SC_SEEN_PIDS) was launched as socraticode@$SC_PLUGIN_FIXED${SC_PIN_VER:+, matching the driver pin} — no launch installs"
  else
    warn "$SC_PINNED_BY launches socraticode $SC_PLUGIN_FIXED — not observed: ${SC_SEEN_WHY:-the process table was not read}"
  fi
  # npx keys its cache on the spec string, so a warm `socraticode@latest` tree
  # does not serve `socraticode@1.14.0`: the first launch of a newly pinned
  # spec is a full install, at session start, unattended — #295's peak once
  # (#332, address-validator). The tree's directory IS that key — the first 16
  # hex digits of the spec's sha512, as libnpmexec names it, unchanged from
  # 7.0.0 (npm 10) through 10.1 (npm 11). Its package.json is no witness: only
  # libnpmexec 10.1+ (npm 11.3+) records the spec there, and an npm 10 tree for
  # `@1.14.0` reads `"socraticode": "^1.14.0"`, as an `@latest` tree that
  # resolved to it does (CR 10).
  SC_NPX_DIR="${npm_config_cache:-$HOME/.npm}/_npx"
  SC_NPX_KEY="$(node -e 'process.stdout.write(require("crypto").createHash("sha512").update(process.argv[1]).digest("hex").slice(0, 16))' \
    "socraticode@$SC_PLUGIN_FIXED" 2>/dev/null || true)"
  if [ -n "$SC_NPX_KEY" ] && [ ! -f "$SC_NPX_DIR/$SC_NPX_KEY/node_modules/socraticode/package.json" ]; then
    warn "No npx cache tree under $SC_NPX_DIR holds socraticode@$SC_PLUGIN_FIXED, so the first session to launch it installs it — the install peak, once, at an unattended start"
    hint "Warm it now, capped where user systemd allows: systemd-run --user --scope -p MemoryHigh=1200M -p MemoryMax=1536M choom -n 500 -- npm exec --yes --prefer-online --package=socraticode@$SC_PLUGIN_FIXED -- true (elsewhere, the npm exec alone)"
  fi
elif [ -n "$SC_PLUGIN_FLOATS" ]; then
  if [ -z "$SC_SPEC_VAR" ] && [ -n "$SC_SPEC" ]; then
    warn "SOCRATICODE_SPEC is set ($SC_SPEC_SRC), but the installed plugin's launch never reads it — it hardcodes '$SC_PLUGIN_FLOATS'"
    hint "The variable reached the plugin after the 1.14.0 release with no version bump, so a '1.14.0' install can predate it — and 'claude plugin update' can report success while keeping that directory: move it aside and update again, then read the launch off the process table (references/host-memory.md)"
  elif [ -n "$SC_PIN_VER" ]; then
    warn "The driver is pinned at socraticode $SC_PIN_VER, but the plugin session launches '$SC_PLUGIN_FLOATS' — it still installs at every session start"
    if [ -n "$SC_SPEC_VAR" ]; then
      hint "$SPEC_HINT"
    else
      hint "This plugin build hardcodes its spec; update the plugin to one that reads SOCRATICODE_SPEC (references/host-memory.md)"
    fi
  elif [ -n "$SC_SPEC_VAR" ] && [ -n "$MEM_KB" ] && [ "$MEM_KB" -lt 4194304 ]; then
    warn "The plugin session launches '$SC_PLUGIN_FLOATS', installing at every session start on a host under 4 GiB"
    hint "$SPEC_HINT"
  fi
fi
# <<< launch-pins

# ── Claude Code: the binary running this session, its version and age ───────
# Advisory (#310, #316). Everything else this skill depends on has its version
# reported — Node against upstream's engines, the build that launches, the
# store, the plugin's registration — except the host running all of it. A
# CannObserv workstation sat on Claude Code 2.1.71 from March to September
# while 2.1.278 was current, preflight green on every run, and #309 then
# reasoned from current documentation about a six-month-old binary: two
# confidently wrong conclusions reached shipped comments and one an upstream
# issue. The version being invisible is what made the mistake invisible.
#
# WHICH binary. `claude --version` answers for PATH, and an IDE session does
# not run PATH's claude: it runs the extension's own native binary. Measured on
# two exeuntu VMs, PATH said 2.1.258 while the agent ran 2.1.266, and 2.1.251
# while it ran 2.1.273 — and after `sudo exeuntu update claude` the first read
# 2.1.278 on PATH with the agent unchanged, so the documented remedy made the
# reported number MORE wrong (#316). So inside a session (CLAUDECODE set) this
# walks up its own process ancestry to the first Claude Code executable and
# measures that; the gap between it and PATH's is reported first, and no
# verdict is ever computed from PATH's when the running one is known. Outside a
# session, or when the walk finds nothing, PATH's claude is measured and the
# line says so.
#
# Age, not a version comparison, because nothing may ask what is current:
# `claude update` has no check-only mode — it installs — and this script never
# mutates the host or makes a network call for this. The age is the mtime of
# the resolved file, whatever its layout: the native installer's
# versions/<v>, an extension's native-binary/claude, an image's root-owned
# /usr/local/bin/claude. #310 read it only where .claude.json said
# installMethod "native", and an exeuntu image records no installMethod at all
# — its binary is baked in at build time — so the age never fired on the hosts
# it was filed for. Nothing here reads .claude.json: autoUpdates is absent on
# the same image while `claude doctor` reports "Auto-updates: enabled" for a
# binary the user cannot write, so an unset key is unknown, never "enabled".
# "Installed 195 days ago" reads on its own, where a bare version needs the
# current one beside it. Releases ran at about one a day (207 across 195 days),
# so 30 days is roughly 30 releases behind.
#
# Every path it cannot measure says so; none is skipped silently.
CLAUDE_AGE_WARN_DAYS=30

# Parent of process $1. `ps` first because both platforms have it, so one path
# runs everywhere; /proc/<pid>/status covers a Linux image without procps.
claude_ppid() {
  local out="" line
  out="$(ps -o ppid= -p "$1" 2>/dev/null || true)"
  out="${out//[!0-9]/}"
  if [ -z "$out" ] && [ -r "/proc/$1/status" ]; then
    while IFS= read -r line; do
      case "$line" in PPid:*) out="${line//[!0-9]/}"; break ;; esac
    done <"/proc/$1/status" || true
  fi
  printf '%s' "$out"
}

# Executable of process $1 as an absolute path, or nothing. /proc first: Linux's
# `ps -o comm=` gives a 15-character name, while macOS's gives the path.
claude_exe() {
  local out=""
  out="$(readlink "/proc/$1/exe" 2>/dev/null || true)"
  [ -n "$out" ] || out="$(ps -o comm= -p "$1" 2>/dev/null || true)"
  out="${out#"${out%%[![:space:]]*}"}"
  out="${out%"${out##*[![:space:]]}"}"
  case "$out" in /*) printf '%s' "$out" ;; esac
}

# The nearest ancestor that is a Claude Code executable: named claude (an
# image's, an extension's) or a native installer's versions/<v> file. A binary
# replaced since it started reads "<path> (deleted)" in /proc, kept as is.
claude_running_binary() {
  local pid="$PPID" exe hops=0
  while [ "$hops" -lt 16 ]; do
    case "$pid" in '' | *[!0-9]*) return 0 ;; esac
    [ "$pid" -gt 1 ] || return 0
    exe="$(claude_exe "$pid")"
    case "$exe" in
      */claude | */claude\ \(deleted\) | */claude/versions/*)
        printf '%s' "$exe"
        return 0
        ;;
    esac
    pid="$(claude_ppid "$pid")"
    hops=$((hops + 1))
  done
}

# What `$1 --version` answers: "2.1.278 (Claude Code)", the first word of the
# first line when it is a release number, else nothing. Parameter expansion
# rather than awk: an advisory reading must not be able to end the run, and
# under `set -e` a missing tool inside an assignment's command substitution
# does exactly that.
claude_reported_version() {
  local v
  v="$("$1" --version 2>/dev/null || true)"
  v="${v%%$'\n'*}"
  v="${v%% *}"
  case "$v" in [0-9]*.[0-9]*.[0-9]*) printf '%s' "$v" ;; esac
}

# The release the file $1 names by its path — an extension directory or a
# native installer's versions/<v> — else what it answers to --version.
claude_version_of() {
  local v=""
  case "$1" in
    */anthropic.claude-code-*/*) v="${1##*/anthropic.claude-code-}"; v="${v%%/*}"; v="${v%%-*}" ;;
    */claude/versions/*) v="${1##*/claude/versions/}"; v="${v%%/*}" ;;
  esac
  case "$v" in
    [0-9]*.[0-9]*.[0-9]*) printf '%s' "$v" ;;
    *) [ ! -x "$1" ] || claude_reported_version "$1" ;;
  esac
}

# The remedy for a stale binary depends on which channel installed it; naming
# the wrong one is how a host gets a second binary that PATH picks between.
# The native installer's versions/<v> is the user's own copy whatever the host,
# so exeuntu — which updates the image's binary — never answers for it.
claude_remedy() {
  case "$1" in
    */anthropic.claude-code-*/*)
      hint "Update the Claude Code extension in the IDE, then reload its window — updating the claude on PATH does not change what this session runs"
      return 0
      ;;
    */claude/versions/*)
      hint "claude update — run it yourself: it installs, and has no check-only mode, so this check never calls it"
      return 0
      ;;
  esac
  if command -v exeuntu >/dev/null 2>&1; then
    hint "sudo exeuntu update claude — the image's own channel; run it yourself. Not 'claude update', which installs a second copy beside the root-owned image binary rather than replacing it (CannObserv/broker#36)"
  else
    hint "claude update — run it yourself: it installs, and has no check-only mode, so this check never calls it"
    [ -w "$1" ] || hint "$1 is not writable by you, so 'claude update' would install a second copy beside it rather than replace it — check which one PATH runs afterwards"
  fi
}

# One ✓ or • line for the file $1: "$2 installed N days ago — $3", with the
# remedy past the mark. The verdict leads and which binary it is follows.
claude_age_line() {
  local mtime now days reason=""
  # GNU stat first, then BSD: `stat -c` is an illegal option on macOS, and on
  # Linux `stat -f` means the filesystem rather than the file. -L on both, so a
  # link is measured by what it points at.
  mtime="$(stat -L -c %Y "$1" 2>/dev/null || stat -L -f %m "$1" 2>/dev/null || true)"
  case "$mtime" in '' | *[!0-9]*) reason="the modification time of $1 could not be read" ;; esac
  now="$(date +%s 2>/dev/null || true)"
  case "$now" in '' | *[!0-9]*) [ -n "$reason" ] || reason="the clock could not be read" ;; esac
  if [ -n "$reason" ]; then
    warn "$2, install age not determined ($reason) — $3"
    return 0
  fi
  days=$(((now - mtime) / 86400))
  [ "$days" -ge 0 ] || days=0
  if [ "$days" -gt "$CLAUDE_AGE_WARN_DAYS" ]; then
    warn "$2 installed $days days ago, past the $CLAUDE_AGE_WARN_DAYS-day mark (releases have run at about one a day) — $3"
    claude_remedy "$1"
  else
    pass "$2 installed $days day(s) ago — $3"
  fi
}

# An IDE stages a new extension beside the running one and switches only when
# its window reloads, so a host can be behind its own completed update — the
# case where the newest directory's age says current while the agent runs an
# older release (#316 §5). Named when a newer, complete sibling exists.
claude_staged_extension() {
  local run="$1" ver="$2" root inner d v newest=""
  root="${run%/anthropic.claude-code-*}"
  inner="${run#"$root"/anthropic.claude-code-}"
  inner="${inner#*/}"
  for d in "$root"/anthropic.claude-code-*/; do
    [ -e "$d$inner" ] || continue
    v="${d%/}"
    v="${v##*/anthropic.claude-code-}"
    v="${v%%-*}"
    case "$v" in [0-9]*.[0-9]*.[0-9]*) ;; *) continue ;; esac
    version_ge "$ver" "$v" && continue
    if [ -z "$newest" ] || ! version_ge "$newest" "$v"; then newest="$v"; fi
  done
  if [ -n "$newest" ]; then
    warn "Claude Code $newest is installed beside it in $root and has not started — the IDE switches to it only when its window reloads"
    hint "Reload the IDE window; until then this session runs $ver"
  fi
}

claude_version_age() {
  local on_path="" path_file="" path_ver="" run="" run_ver="" label
  if command -v claude >/dev/null 2>&1; then
    on_path="$(command -v claude)"
    path_file="$(readlink -f "$on_path" 2>/dev/null || true)"
    [ -n "$path_file" ] || path_file="$on_path"
    path_ver="$(claude_reported_version "$on_path")"
  fi
  [ -z "${CLAUDECODE:-}" ] || run="$(claude_running_binary)"

  if [ -n "$run" ]; then
    case "$run" in
      *' (deleted)')
        warn "Claude Code: this session runs ${run% (deleted)}, which has been replaced on disk since it started, so its version and install age were not determined"
        hint "Restart the session to run what is installed there now"
        return 0
        ;;
    esac
    if [ ! -e "$run" ]; then
      warn "Claude Code: this session runs $run, which is no longer on disk, so its version and install age were not determined"
      hint "Restart the session to run what is installed now"
      return 0
    fi
    # macOS's ps reports the path the binary was started by, link or not.
    run="$(readlink -f "$run" 2>/dev/null || printf '%s' "$run")"
    run_ver="$(claude_version_of "$run")"
    [ -n "$run_ver" ] || [ "$run" != "$path_file" ] || run_ver="$path_ver"
    label="the binary running this session, $run"
    if [ "$run" = "$path_file" ]; then
      label="the binary running this session and PATH's claude, $run"
    elif [ -z "$on_path" ]; then
      label="$label (no claude on PATH)"
    elif [ -n "$run_ver" ] && [ "$run_ver" = "$path_ver" ]; then
      label="$label (PATH's claude, $path_file, is the same release)"
    else
      # The gap first; the verdict after it is the running binary's alone.
      warn "Claude Code: this session runs ${run_ver:-$run}, but PATH's claude is ${path_ver:-a binary that reported no version} ($path_file) — two programs, and updating PATH's does not change this session's"
    fi
    claude_age_line "$run" "Claude Code ${run_ver:-(release unread)}" "$label"
    case "$run" in
      */anthropic.claude-code-*/*) [ -z "$run_ver" ] || claude_staged_extension "$run" "$run_ver" ;;
    esac
    return 0
  fi

  local unfound=""
  [ -z "${CLAUDECODE:-}" ] || unfound="the binary running this session was not found among this check's parent processes"
  if [ -z "$on_path" ]; then
    warn "Claude Code: no claude on PATH${unfound:+, and $unfound}, so its version and install age were not determined"
    return 0
  fi
  if [ -z "$path_ver" ]; then
    warn "Claude Code: 'claude --version' ($on_path) reported no version, so its version and install age were not determined"
    return 0
  fi
  [ -z "$unfound" ] || warn "Claude Code: $unfound, so the reading below is PATH's claude — an IDE session runs a binary of its own"
  claude_age_line "$path_file" "Claude Code $path_ver" "PATH's claude, $path_file"
}

claude_version_age

# ── Gate 4 (advisory): plugin MCP server registered and Connected ───────────
# Not fatal — the bundled mcp-driver.mjs fallback works without the plugin being
# wired into the session (gotcha A). Reported so the operator knows which path
# they are on. `claude` may be absent when preflight runs outside Claude Code.
if command -v claude >/dev/null 2>&1; then
  # The marketplace first: `socraticode@socraticode` is plugin@marketplace, so the
  # install in Phase 2 cannot resolve until the marketplace is registered.
  # Reported separately from the connection check so a fresh host doesn't read
  # its missing marketplace as "just needs a restart".
  if claude plugin marketplace list 2>/dev/null | grep -q 'socraticode'; then
    pass "Marketplace 'socraticode' registered"
  else
    printf '  \033[33m•\033[0m %s\n' "Marketplace 'socraticode' not registered — 'claude plugin install socraticode@socraticode' will fail"
    hint "claude plugin marketplace add giancarloerra/socraticode"
  fi

  # `claude mcp list` STARTS each server to test it, and SocratiCode's startup
  # auto-resume then runs an incremental update of the project at its cwd and,
  # in managed mode, probes Docker: a write to the index and, on a
  # socket-activated host, a daemon start — from a check that promises neither.
  # Before a projectId exists that write lands in collections named by this
  # checkout's path hash (#287). Upstream reads SOCRATICODE_AUTO_RESUME=off
  # before any Docker or Qdrant access, so the probe stays a probe.
  #
  # It is NOT version-bounded, and #295's finding 5 was wrong to suspect it was
  # (#309). The docs put configuration-only statuses at 2.1.238, and a 2.1.251
  # host did not start a project stdio server — but that server was pending
  # approval, which is the likelier reason. Measured on 2.1.278 with a
  # throwaway plugin whose MCP server recorded its own argv: `claude mcp list`
  # STARTED it. A plugin-provided server is already trusted by virtue of the
  # plugin being installed, so the approval gate that stops a project server
  # does not apply to it.
  #
  # So this guard is load-bearing on current Claude Code, not a legacy
  # precaution for old hosts, and the behaviour it prevents is a write to a
  # shared store.
  #
  # How the variable gets there is inferred, not observed (#287 CR 24): it
  # rides claude's own environment into the server it starts, the route a
  # settings `env` block takes to reach a plugin server — which the cohort's
  # external stores demonstrate daily. Testing it directly means writing
  # ~/.claude.json under a live session, which this suite does not do. If
  # claude ever stopped passing its environment through, the probe would
  # regress to the auto-resume it had before, no worse.
  MCP_LIST="$(SOCRATICODE_AUTO_RESUME=off claude mcp list 2>/dev/null || true)"
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
  printf '  \033[33m•\033[0m %s\n' "claude CLI not found — the plugin-connection check is skipped"
fi

echo
if [ "$FAIL" -eq 0 ]; then
  echo "Preflight PASSED — host is ready to index."
  exit 0
else
  echo "Preflight FAILED — resolve the ✗ gates above, then re-run."
  exit 1
fi
