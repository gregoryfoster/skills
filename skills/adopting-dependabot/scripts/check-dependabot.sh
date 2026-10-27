#!/usr/bin/env bash
# check-dependabot.sh — read whether a repo's Dependabot is working, not just
# configured: the verify step of adopting-dependabot (#376). Read-only.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash check-dependabot.sh --repo OWNER/REPO [--runs N]

Reads, through gh api, whether Dependabot is proposing anything in a repo,
and whether its security path is on. It changes nothing. Each check is
pass, fail, unread (this token can't read it) or info:

  config            .github/dependabot.yml on the default branch parses,
                    is version 2, and every block names an ecosystem, a
                    directory and schedule.interval
  limit:<eco>       open Dependabot PRs against open-pull-requests-limit
                    (default 5). Full means no more version updates open,
                    and nothing says so. Security updates have their own
                    fixed limit of 10, but their PRs can't be told apart by
                    branch, so the count may include them
  update-runs       the latest "Dependabot Updates" run per ecosystem and
                    directory didn't fail; none at all fails too
  last-pr           the newest Dependabot PR and its age (info)
  graph             every committed lockfile (uv.lock, package-lock.json,
                    composer.lock, ...) is a dependency-graph manifest.
                    0 manifests means the graph is off, or the token can't
                    see it: no alert can match, so no security update opens
  alerts            Dependabot alerts are on
  security-updates  Dependabot security updates are on and not paused

graph needs only metadata read. alerts needs Dependabot alerts: read (or
Administration: read), and security-updates Administration: read; without
them each reads unread, never pass.

Output (stdout, JSON): {repo, default_branch, checks: [{name, status,
detail, ...}], summary: {status: count}}. gh's own errors go to stderr.

Options:
  --repo OWNER/REPO   the repo to read
  --runs N            dynamic runs to read for update-runs (default 100)
  -h, --help          show this help

Needs gh (authenticated), and python3 3.11+ with PyYAML, or uv.

Exit codes:
  0  no check failed
  1  a check failed: the JSON says which
  2  usage, a needed tool missing, or the repo unreadable
USAGE
}

ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --repo | --runs)
      [ $# -ge 2 ] || { echo "check-dependabot: $1 needs a value" >&2; exit 2; }
      ARGS+=("$1" "$2")
      shift 2
      ;;
    -h | --help) usage; exit 0 ;;
    *) echo "check-dependabot: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
case " ${ARGS[*]-} " in
  *" --repo "*) ;;
  *) echo "check-dependabot: --repo OWNER/REPO is required" >&2; exit 2 ;;
esac

command -v gh >/dev/null || { echo "check-dependabot: needs gh on PATH" >&2; exit 2; }
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=_python.sh
. "$HERE/_python.sh"
pick_python check-dependabot || exit 2
exec "${PY[@]}" "$HERE/_check.py" "${ARGS[@]}"
