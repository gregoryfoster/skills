#!/usr/bin/env bash
# >>> usage
# loopback-containers.sh — create SocratiCode's local containers on loopback,
# or check the ones that exist (#494).
#
# SocratiCode creates its managed stack with `docker run -p <port>:6333 …`
# and no host IP, so an unauthenticated Qdrant — which holds every indexed
# chunk's source text — and its Ollama listen on every interface. Docker's
# publishes bypass the host firewall. Qdrant's anonymous telemetry is on too.
# SocratiCode starts an existing container by name and never recreates it, so
# one created here first, on 127.0.0.1, is the one it uses from then on.
#
# Usage:
#   bash loopback-containers.sh [options] <target>...
#   bash loopback-containers.sh --check <target>...
#   bash loopback-containers.sh --help
#
# Targets: `qdrant` (socraticode-qdrant), `ollama` (socraticode-ollama). Name
# only what runs locally: preflight.sh prints the command with the right ones.
#
# Default mode: creates each target that is MISSING, on 127.0.0.1, with the
# names, volumes, container ports and restart policy SocratiCode's own
# `docker run` uses, plus QDRANT__TELEMETRY_DISABLED=true on Qdrant. An
# existing container is only checked. This script never removes, stops,
# renames or recreates one: moving a wide container to loopback is the manual
# procedure in references/loopback-containers.md, because it swaps the
# container under a live index.
#
# --check: read-only. Inspects each target and changes nothing.
#
# Options:
#   --check               inspect only; create nothing
#   --qdrant-image IMAGE  default qdrant/qdrant:v1.17.0
#   --ollama-image IMAGE  default ollama/ollama:latest
#                         Both defaults are SocratiCode's own tags (1.13.1 to
#                         1.16.1). It looks for those exact tags and pulls one
#                         that is missing, so another tag costs a second pull.
#   --help                show this help
#
# Env (SocratiCode's own, read the same way it reads them):
#   QDRANT_PORT       host port for Qdrant's HTTP API   (default 16333)
#   QDRANT_GRPC_PORT  host port for Qdrant's gRPC API   (default 16334)
#   OLLAMA_PORT       host port for the Ollama API      (default 11435)
#
# Output: one tab-separated line per target on stdout,
#   <target> <container> <verdict> <detail>
# where <verdict> is one of:
#   ok         exists, every publish on loopback, telemetry off (Qdrant)
#   created    was missing; created on loopback by this run
#   missing    does not exist (--check only)
#   wide       publishes a port beyond loopback
#   decoy      another container's name contains this one's; SocratiCode's
#              substring match may take it for this one
#   telemetry  on loopback, but Qdrant's telemetry is not disabled
#   unknown    could not be read, publishes no port, has never started, or
#              could not be created
# Docker's own messages, and a pull's progress, go to stderr.
#
# Exit codes: 0 = every target ok or created; 1 = at least one target is not;
# 2 = usage error, or docker is not installed.
# <<< usage
set -euo pipefail

usage() { sed -n '/^# >>> usage$/,/^# <<< usage$/p' "$0" | sed '1d;$d;s/^# \{0,1\}//'; }

CHECK=""
QDRANT_IMAGE="qdrant/qdrant:v1.17.0"
OLLAMA_IMAGE="ollama/ollama:latest"
TARGETS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --help | -h) usage; exit 0 ;;
    --check) CHECK=1; shift ;;
    --qdrant-image | --ollama-image)
      [ $# -ge 2 ] && [ -n "$2" ] || { echo "$1 needs a value (try --help)" >&2; exit 2; }
      if [ "$1" = --qdrant-image ]; then QDRANT_IMAGE="$2"; else OLLAMA_IMAGE="$2"; fi
      shift 2 ;;
    qdrant | ollama) TARGETS+=("$1"); shift ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
done
[ "${#TARGETS[@]}" -gt 0 ] || { echo "name at least one target: qdrant, ollama (try --help)" >&2; exit 2; }

QP="${QDRANT_PORT:-16333}" QG="${QDRANT_GRPC_PORT:-16334}" OP="${OLLAMA_PORT:-11435}"
for _p in "$QP" "$QG" "$OP"; do
  case "$_p" in
    '' | *[!0-9]*) echo "a port is not a number: QDRANT_PORT=$QP QDRANT_GRPC_PORT=$QG OLLAMA_PORT=$OP" >&2; exit 2 ;;
  esac
done

command -v docker >/dev/null 2>&1 || { echo "docker is not installed" >&2; exit 2; }

# True for an address only this host can reach. Docker writes HostIp "" for a
# publish with no host IP, which is every interface.
is_loopback() {
  case "$1" in
    127.* | ::1 | '[::1]' | ::ffff:127.*) return 0 ;;
    *) return 1 ;;
  esac
}

# inspect NAME — sets V (verdict) and DETAIL. Read-only.
#
# One template, two parts: state and publishes on the first line, then the
# environment one variable per line. Bash builtins parse it, so the script runs
# on preflight's stubbed PATH, which carries no awk and no mktemp.
INSPECT_FORMAT='{{.State.Status}}{{"\t"}}{{range .HostConfig.PortBindings}}{{range .}}{{.HostIp}}|{{.HostPort}} {{end}}{{end}}{{"\n"}}{{range .Config.Env}}{{.}}{{"\n"}}{{end}}'
inspect() {
  local name="$1" out err line state env b ip wide="" seen="" telemetry="" other=""
  local -a binds=()
  V="" DETAIL=""
  if ! out="$(docker inspect --type container --format "$INSPECT_FORMAT" "$name" 2>/dev/null)"; then
    # Asked again for its message: stdout is the report, and holding both
    # streams apart in one call needs a temp file this PATH may not offer.
    err="$(docker inspect --type container "$name" 2>&1 >/dev/null || true)"
    err="${err%%$'\n'*}"
    case "$err" in
      *"No such"*) V=missing DETAIL="no container named $name" ;;
      *) V=unknown DETAIL="docker inspect failed: ${err:-no message}" ;;
    esac
    return 0
  fi
  line="${out%%$'\n'*}"
  env="${out#*$'\n'}"
  [ "$env" != "$out" ] || env=""
  state="${line%%$'\t'*}"
  if [ -z "$state" ]; then
    V=unknown DETAIL="docker inspect printed nothing for $name"
    return 0
  fi
  if [ "${line#*$'\t'}" != "$line" ]; then
    read -r -a binds <<<"${line#*$'\t'}" || true
  fi
  for b in ${binds[@]+"${binds[@]}"}; do
    ip="${b%%|*}"
    seen=1
    is_loopback "$ip" || wide="${wide:+$wide, }${ip:-0.0.0.0}:${b#*|}"
  done
  case $'\n'"$env" in
    *$'\nQDRANT__TELEMETRY_DISABLED=true'$'\n'* | *$'\nQDRANT__TELEMETRY_DISABLED=true') telemetry=off ;;
  esac
  # SocratiCode's existence check is `docker ps -a --filter name=<name>` and
  # then a substring `.includes(name)`, so `socraticode-qdrant-old` counts.
  other="$(docker ps -a --filter "name=$name" --format '{{.Names}}' 2>/dev/null | grep -vx -- "$name" | tr '\n' ' ' || true)"
  other="${other% }"
  if [ -z "$seen" ]; then
    V=unknown DETAIL="$name ($state) publishes no port, so SocratiCode cannot reach it"
  elif [ -n "$wide" ]; then
    V=wide DETAIL="$name ($state) publishes beyond loopback: $wide"
    if [ "$name" = socraticode-qdrant ] && [ -z "$telemetry" ]; then
      DETAIL="$DETAIL; telemetry not disabled"
    fi
  elif [ "$state" = created ]; then
    # Never started (CR 790). A `docker run` that cannot bind its port leaves
    # one behind, loopback publishes and all; SocratiCode's start of
    # it fails the same way until whatever holds the port lets go.
    V=unknown DETAIL="$name has never started (state created): a docker run that could not bind leaves one behind, so find what holds its port before starting it"
  elif [ -n "$other" ]; then
    V=decoy DETAIL="$name ($state) is on loopback, but SocratiCode's substring match also counts: $other"
  elif [ "$name" = socraticode-qdrant ] && [ -z "$telemetry" ]; then
    V=telemetry DETAIL="$name ($state) is on loopback, but QDRANT__TELEMETRY_DISABLED=true is not set"
  else
    V=ok DETAIL="$name ($state) is on loopback${telemetry:+, telemetry off}"
  fi
  if [ "$V" = ok ] || [ "$V" = telemetry ]; then
    [ -z "$other" ] || DETAIL="$DETAIL; SocratiCode's substring match also counts: $other"
  fi
}

# create TARGET NAME — `docker run`, matching SocratiCode's own except for the
# host IP and the telemetry variable [traced: socraticode 1.13.1 and 1.16.1,
# dist/services/docker.js startQdrant / startOllama]. Docker's container ID and
# its messages go to stderr; stdout is this script's report.
create() {
  local target="$1" name="$2"
  local -a args=(run -d --name "$name")
  if [ "$target" = qdrant ]; then
    args+=(-p "127.0.0.1:$QP:6333" -p "127.0.0.1:$QG:6334"
      -v socraticode_qdrant_data:/qdrant/storage
      --restart unless-stopped
      -e QDRANT__TELEMETRY_DISABLED=true
      "$QDRANT_IMAGE")
  else
    args+=(-p "127.0.0.1:$OP:11434"
      -v socraticode_ollama_data:/root/.ollama
      --restart unless-stopped
      "$OLLAMA_IMAGE")
  fi
  docker "${args[@]}" >&2
}

RC=0
for target in "${TARGETS[@]}"; do
  name="socraticode-$target"
  inspect "$name"
  if [ "$V" = missing ] && [ -z "$CHECK" ]; then
    if create "$target" "$name"; then
      inspect "$name"
      [ "$V" != ok ] || V=created
    else
      inspect "$name"
      if [ "$V" = missing ]; then
        V=unknown DETAIL="docker run failed for $name (its message is above, on stderr)"
      else
        V=unknown DETAIL="docker run failed for $name (its message is above, on stderr) and left it behind: $DETAIL"
      fi
    fi
  fi
  case "$V" in ok | created) ;; *) RC=1 ;; esac
  printf '%s\t%s\t%s\t%s\n' "$target" "$name" "$V" "$DETAIL"
done
exit "$RC"
