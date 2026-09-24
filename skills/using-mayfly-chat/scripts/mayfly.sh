#!/usr/bin/env bash
# mayfly.sh — the using-mayfly-chat skill's entry point to its vendored Mayfly client.
#
# Every command the skill runs goes through here. It finds client.mjs beside
# itself, checks for Node 18+, refuses a channel URL on the command line before
# it can reach any process's argv, checks MAYFLY_URL_FILE is set, and execs the
# client with the arguments as given. The client reads the channel URL from the
# mode-600 file MAYFLY_URL_FILE names, so /proc/<pid>/cmdline — mode 444,
# world-readable for the life of every call — holds only that file's path
# (gregoryfoster/skills#302, findings 16 and 19).
#
# Usage: MAYFLY_URL_FILE=<path> bash "<mayfly.sh>" COMMAND [options]
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: MAYFLY_URL_FILE=<path> bash "<mayfly.sh>" COMMAND [options]

Commands (each prints one JSON object; every option: node <this directory>/client.mjs --help):
  create ORIGIN                                   mint a channel; writes its URL into MAYFLY_URL_FILE (mode 600, must not exist)
  read   --last N [--wait S]                      one page; re-read with the returned last while "more" is true
  post   --from NAME --last N --body PATH [--wait S]
  listen --last N --me NAME [--slot S] [--max S]  short-poll loop; returns on the first message not from NAME
  delete                                          destroy the channel: the post-leak remedy, no undo

The channel URL is never an argument. MAYFLY_URL_FILE names a mode-600 file
that holds it; create writes that file, every other command reads it.

Exit codes:
  0  success (stdout, JSON)
  1  conflict (stdout, posted:false) or client error (stderr, JSON)
  2  usage error, or a channel URL was passed as an argument
  3  listen reached --max seconds with no peer message (stdout, JSON)
  4  node is missing or older than 18, or client.mjs is not beside this script
  5  MAYFLY_URL_FILE is unset
EOF
}

# --help anywhere prints usage and never runs the client. Anything shaped like
# a channel URL — an origin followed by a /c/ path, or by a #fragment — is
# refused here, because the point of this wrapper is that such a string never
# becomes an argument to node.
for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
  esac
  if [[ "$arg" == *://*/c/* ]] || { [[ "$arg" == *://* ]] && [[ "$arg" == *#* ]]; }; then
    echo "ERROR: refusing a channel URL on the command line." >&2
    echo "  Write it to a mode-600 file with the file-write tool and set MAYFLY_URL_FILE to that path." >&2
    exit 2
  fi
done
if [[ $# -eq 0 ]]; then
  usage >&2
  exit 2
fi

# Resolved before anything else, from the path as invoked: the client ships
# beside this script and a project that copies one must copy both.
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
CLIENT="${SCRIPT_DIR}/client.mjs"
if [[ ! -f "$CLIENT" ]]; then
  echo "ERROR: ${CLIENT} is missing; a project that copies mayfly.sh copies the whole scripts/ directory." >&2
  exit 4
fi

if ! command -v node >/dev/null 2>&1; then
  echo "ERROR: node is not on PATH; the client needs Node.js 18 or newer and no packages." >&2
  exit 4
fi
# Not a bare assignment: a node that cannot run would otherwise abort here
# under set -e with no message, on the one path that must explain itself.
NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null) || NODE_MAJOR=
if [[ ! "$NODE_MAJOR" =~ ^[0-9]+$ ]] || [[ "$NODE_MAJOR" -lt 18 ]]; then
  echo "ERROR: node reports major version '${NODE_MAJOR}'; 18 or newer is required." >&2
  exit 4
fi

if [[ -z "${MAYFLY_URL_FILE:-}" ]]; then
  echo "ERROR: MAYFLY_URL_FILE is unset. It must name a mode-600 file holding the channel URL" >&2
  echo "  (for create: the path to write it to). Set it on this command, for example" >&2
  echo "  MAYFLY_URL_FILE=\$HOME/.mayfly/<topic>.url bash \"<mayfly.sh>\" $1 ..." >&2
  exit 5
fi

exec node "$CLIENT" "$@"
