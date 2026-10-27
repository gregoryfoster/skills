#!/usr/bin/env bash
# inventory.sh — read a repo's Dependabot surface, phases 1 and 2 of
# adopting-dependabot (#376). Read-only.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash inventory.sh [--repo-root DIR] [--upstream] [--timeout SECONDS]

Reads what Dependabot would see in a repo, and what its CI needs, from the
committed files only (git ls-files). It changes nothing.

Output (stdout, JSON):
  dependabot_config   the config's path, or null
  ecosystems          [{ecosystem, directory, evidence}]: every manifest
                      found, in Dependabot's directory form ("/", "/sub").
                      A row is a manifest found, not an ecosystem known to
                      be configurable as named: check Dependabot's own list
                      before writing a block for it
  workflows           per workflow: triggers, gates_pull_request,
                      scheduled_only (a bump there runs in no PR's CI), the
                      generated-file marker if any, and per job: needs
                      (nothing | secret | oidc | unknown), calls (the
                      reusable workflow it calls: a local one lends its
                      jobs' needs, another repo's reads unknown), secrets,
                      vars,
                      write_permissions (a Dependabot run's token is
                      read-only), private_index_steps, runs_on
  actions             distinct owner/repo actions, their count (the
                      github-actions PR-limit floor), and every uses: ref
                      with its pin form: major | minor | exact | sha |
                      branch | local | docker | unpinned
  runner_labels       each runs-on label; floating when it ends -latest
  private_indexes     uv/pip index-url, extra-index-url, find-links,
                      [[tool.uv.index]], requirements -f/-i, pip.conf,
                      .npmrc; local=true for a path, not a URL
  pinned_sources      [tool.uv.sources] git/path/url/index entries and
                      git+ requirements: pins the bot does not move
  exact_pins          == specifiers, by table
  tables              per pyproject.toml: runtime count, extras, groups
  upstream            null, or with --upstream, per action: newest
                      vX.Y.Z, the floating vN tags; and each ref gains
                      status: current | behind | frozen | missing |
                      mismatch | branch | unpinned | unknown | unread,
                      with why

Options:
  --repo-root DIR   the repo to read (default: .)
  --upstream        also read each action's tags with git ls-remote
                    (network; anonymous). frozen means a major-form pin
                    whose upstream stopped floating vN tags: Dependabot
                    proposes refs in the pin's own form, so it stops there
  --timeout N       seconds per git ls-remote (default 20)
  -h, --help        show this help

Needs git, and python3 3.11+ with PyYAML, or uv (which supplies it, pinned).

Exit codes:
  0  read
  2  usage, or a needed tool missing
USAGE
}

ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --repo-root | --timeout)
      [ $# -ge 2 ] || { echo "inventory: $1 needs a value" >&2; exit 2; }
      ARGS+=("$1" "$2")
      shift 2
      ;;
    --upstream) ARGS+=("$1"); shift ;;
    -h | --help) usage; exit 0 ;;
    *) echo "inventory: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

command -v git >/dev/null || { echo "inventory: needs git on PATH" >&2; exit 2; }
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=_python.sh
. "$HERE/_python.sh"
pick_python inventory || exit 2
exec "${PY[@]}" "$HERE/_inventory.py" ${ARGS[@]+"${ARGS[@]}"}
