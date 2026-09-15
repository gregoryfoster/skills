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
# Network reads, all bounded to a few seconds and none a write:
#   - Node 26+ only: `npm view socraticode version`, to learn whether the build
#     that will launch carries the Node 26 Qdrant transport bridge. Degraded to
#     a warning when it does not answer, so an air-gapped host is slowed rather
#     than blocked.
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

# from_settings KEY [project] — the first settings file declaring KEY as a
# string: the project's two, then (without `project`) the user's. Sets S_VAL
# and S_SRC (relative to the repo root where it can be); both empty if none.
#
# The pattern spans JSON escapes so a value is never cut short at an escaped
# quote — `"se\"c\\ret"` used to read as `se\`, probed as a 3-character key
# and reported rejected — but an escape is not decoded, so a value holding one
# is refused, and said so, rather than guessed at.
from_settings() {
  local key="$1" f m
  local -a files=("${PROJECT_SETTINGS[@]}")
  [ "${2:-}" = project ] || files+=("$USER_SETTINGS")
  S_VAL="" S_SRC=""
  for f in "${files[@]}"; do
    [ -f "$f" ] || continue
    m="$(grep -oE "\"$key\""'[[:space:]]*:[[:space:]]*"([^"\\]|\\.)*"' "$f" 2>/dev/null | head -n 1 || true)"
    [ -n "$m" ] || continue
    S_SRC="${f#"$ROOT"/}"
    S_VAL="$(printf '%s' "$m" | sed -E 's/^"[^"]*"[[:space:]]*:[[:space:]]*"//; s/"$//')"
    case "$S_VAL" in
      *\\*)
        case " $ESCAPED " in
          *" $key "*) ;;
          *)
            ESCAPED="$ESCAPED $key"
            warn "$key in $S_SRC holds a JSON escape this check does not decode — not used; export it for this run instead"
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
# — OLLAMA_MODE whatever the provider — so a typo is a server that will not
# start, which the gates below would otherwise read as a choice: `Ollama` as a
# cloud embedder needing no Docker, `extern` as auto. QDRANT_MODE is never
# refused, only read as managed, so a typo there is said aloud instead.
case "$E_PROVIDER" in
  ollama | openai | google | lmstudio | litellm) ;;
  *) fail "EMBEDDING_PROVIDER=$E_PROVIDER is not one upstream accepts (ollama, openai, google, lmstudio, litellm) — the server throws at startup" ;;
esac
case "$O_MODE" in
  auto | docker | external) ;;
  *) fail "OLLAMA_MODE=$O_MODE is not one upstream accepts (auto, docker, external) — the server throws at startup" ;;
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
# a 401 into exit 22, "no answer" in place of "requires an API key" (#287 CR 8). The key rides in on stdin as a
# curl config line, never on the command line, where every process on the host
# can read it for the life of the call.
http_status() {
  local key="${2:-}" esc
  if [ -n "$key" ]; then
    esc="${key//\\/\\\\}"
    esc="${esc//\"/\\\"}"
    printf 'header = "api-key: %s"\n' "$esc" \
      | curl -q -s -o /dev/null -w '%{http_code}' --max-time 5 -K - "$1" 2>/dev/null
  else
    curl -q -s -o /dev/null -w '%{http_code}' --max-time 5 "$1" 2>/dev/null
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
      # the usual reason on a tailnet.
      fail "$what: the certificate at $url did not verify (curl exit $rc)"
      case "$host" in
        *.* | \[*) ;;
        *) hint "A certificate names the full host name, and $host is a short one — use the FQDN (on a tailnet, the full MagicDNS name <host>.<tailnet>.ts.net)" ;;
      esac
      ;;
    53 | 54 | 58 | 59 | 64 | 66 | 77 | 80 | 82 | 83 | 90 | 91)
      fail "$what: TLS failed at $url (curl exit $rc)"
      ;;
    *) fail "$what: no answer from $url (curl exit $rc)" ;;
  esac
}

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
        NATIVE="$(curl -q -s -o /dev/null -w '%{http_code}' --max-time 2 http://localhost:11434/api/tags 2>/dev/null || true)"
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
docker_socket_idle() {
  command -v systemctl >/dev/null 2>&1 || return 1
  systemctl is-active --quiet docker.socket 2>/dev/null || return 1
  ! systemctl is-active --quiet docker.service 2>/dev/null
}

if [ -z "$DOCKER_FOR" ]; then
  pass "Docker not needed — the store is external and the embedder is not a container, so nothing here starts one"
elif ! command -v docker >/dev/null 2>&1; then
  fail "Docker not installed (needed for $DOCKER_FOR)"
  hint "macOS: brew install --cask docker   Linux: https://docs.docker.com/engine/install/"
else
  if docker_socket_idle; then
    # Not probed — but not assumed either (#287 CR 10). Socket activation
    # cannot start a masked service, a failed one is retried by the first
    # docker call and may fail again, and a socket this user cannot write to
    # refuses every call. Each read below asks systemd or the filesystem; none
    # connects to the socket.
    DOCKER_SOCK="${DOCKER_HOST:-unix:///var/run/docker.sock}"
    case "$DOCKER_SOCK" in
      unix://*) DOCKER_SOCK="${DOCKER_SOCK#unix://}" ;;
      *) DOCKER_SOCK="" ;;
    esac
    if [ "$(systemctl is-enabled docker.service 2>/dev/null || true)" = masked ]; then
      fail "docker.socket is listening, but docker.service is masked — socket activation cannot start it (needed for $DOCKER_FOR)"
      hint "sudo systemctl unmask docker.service"
    elif systemctl is-failed --quiet docker.service 2>/dev/null; then
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
            fail "Qdrant store at $Q_URL requires an API key (HTTP $Q_CODE without one), and QDRANT_API_KEY is not set"
            hint "Put it in the env block of .claude/settings.local.json — git-ignored — never in the tracked settings.json"
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
if [ "$DECL_MODE" = external ]; then
  if [ -n "${CLAUDECODE:-}" ]; then
    UNCARRIED=""
    # The collection prefix and id override too (#287 round 2, CR 28): left
    # behind, either points every write at another collection set.
    for key in QDRANT_MODE QDRANT_URL QDRANT_HOST QDRANT_PORT QDRANT_API_KEY \
      QDRANT_COLLECTION_PREFIX SOCRATICODE_PROJECT_ID \
      OLLAMA_MODE OLLAMA_URL EMBEDDING_PROVIDER EMBEDDING_MODEL EMBEDDING_DIMENSIONS; do
      from_settings "$key" project
      if [ -n "$S_VAL" ] && [ "${!key:-}" != "$S_VAL" ]; then
        UNCARRIED="${UNCARRIED:+$UNCARRIED, }$key"
      fi
    done
    case "$UNCARRIED" in
      '')
        pass "This session carries $DECL_SRC's env block — every store variable it declares — so the folder is trusted"
        ;;
      *QDRANT_MODE* | *OLLAMA_MODE*)
        fail "The project settings declare store variables this session does not carry ($UNCARRIED) — its SocratiCode server falls back to a local Docker stack instead of reaching the store"
        hint "Restart Claude Code in this folder and accept the trust prompt, then re-run this check from the new session"
        ;;
      *)
        fail "The project settings declare store variables this session does not carry ($UNCARRIED) — its SocratiCode server runs without them"
        hint "Restart Claude Code in this folder and accept the trust prompt, then re-run this check from the new session"
        ;;
    esac
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

  # `claude mcp list` STARTS each server to test it, and SocratiCode's startup
  # auto-resume then runs an incremental update of the project at its cwd and,
  # in managed mode, probes Docker: a write to the index and, on a
  # socket-activated host, a daemon start — from a check that promises neither.
  # Before a projectId exists that write lands in collections named by this
  # checkout's path hash (#287). Upstream reads SOCRATICODE_AUTO_RESUME=off
  # before any Docker or Qdrant access, so the probe stays a probe.
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
