#!/usr/bin/env bash
# pre-ship.sh
# Stub: runs the project's test suite before shipping.
#
# This script must be overridden by the consuming project's local skill override.
# The global shipping-work skill cannot know the project's test runner.
#
# Usage: bash <SKILL_SCRIPTS>/pre-ship.sh [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \"$0\""
  echo ""
  echo "Runs the project test suite. Must be overridden in the consuming project."
  echo "The global skill provides this stub only — replace with your test runner."
  echo ""
  echo "Scaffolding (worktree zombie audit + JS toolchain auto-detection) is"
  echo "included below the stub exit. Overrides that remove the exit block"
  echo "inherit the scaffolding verbatim, matching the FastAPI/Click/PHP siblings."
  exit 0
fi

# === STUB EARLY EXIT =========================================================
# The bare skill's pre-ship.sh exits HERE. Everything below is scaffolding
# downstream overrides inherit when they delete this exit block and replace
# it with a real test-runner invocation. Until then, the stub does no work
# (no audit, no npm gates) so its "you must override" message is the first
# and only thing the operator sees.
echo "ERROR: pre-ship.sh is a stub. The consuming project must override this script." >&2
echo "       Copy shipping-work/ into your project's skills/ directory and" >&2
echo "       replace this file with your test runner (e.g., uv run pytest)." >&2
exit 1
# ============================================================================

# --- SCAFFOLDING BELOW (not executed by the stub) ----------------------------
# When an override removes the stub exit above, this block runs. Mirrors the
# FastAPI/Click/PHP siblings so overrides have a working template out of the
# box. Overrides should keep PROJECT_ROOT resolution + cd at the top so the
# AUDIT_SCRIPT and `package.json` paths resolve from the repo root regardless
# of where the script was invoked from.

PROJECT_ROOT=$(git rev-parse --show-toplevel)
cd "$PROJECT_ROOT"

# --- Project-local env loading (optional override point) ---------------------
# Upstream ships without env loading — most projects don't need it. If yours
# does (test fixtures reading live secrets, a bootstrap that hard-fails on a
# missing DSN), load it here, at the top of your override:
#
#   load_env() {                                  # parse, never source
#     [ -r "$1" ] || return 0
#     while IFS= read -r line || [ -n "$line" ]; do
#       line=${line#"${line%%[![:space:]]*}"}       # drop leading blanks
#       case $line in ''|\#*) continue ;; esac       # blank or comment
#       line=${line#export }                        # tolerate `export K=v`
#       case $line in *=*) ;; *) continue ;; esac
#       key=${line%%=*} val=${line#*=}
#       key=${key%"${key##*[![:space:]]}"}
#       case $key in ''|*[!A-Za-z0-9_]*) continue ;; esac
#       case $val in                                # strip matched quotes
#         \"*\") val=${val#\"} val=${val%\"} ;;
#         \'*\') val=${val#\'} val=${val%\'} ;;
#       esac
#       export "$key=$val"
#     done < "$1"
#   }
#   load_env /etc/<project>/.env
#   load_env "$PROJECT_ROOT/.env"
#
# Note how this differs from the language variants (-php, -python-click,
# -python-fastapi). Those ship a real gate, so their advice is a project-local
# WRAPPER that loads env and `exec`s the vendored script — one copy of the
# logic, upstream fixes land automatically. This script is a stub that exits 1
# above, so there is nothing to delegate to: your project-local copy IS the
# gate, and the env loading belongs inside it.
#
# Parse the file line by line; never `set -a; . file`, and never
# `export $(cat ... | xargs)`. That one-liner shipped here until #144 and had
# three defects: with both files absent it degenerated to a bare `export`,
# dumping every exported variable — secrets included — into the ship-gate
# transcript; a `#` comment line reached `export` as `'#': not a valid
# identifier`, so `set -e` killed the caller BEFORE the gate ran; and `xargs`
# word-split `PW=two words` into a wrong value with exit 0. Quoting
# `export "$key=$val"` is what makes spaces, globs and quoted values survive,
# so there is no `set -f` dance and no shellcheck suppressions. A key that is
# not a plain identifier is skipped rather than aborting: a malformed line in
# a secrets file must not decide whether the gate runs.

# Pre-flight: warn (do not fail) if zombie processes from previously-destroyed
# worktrees are still around. Helps surface drift the destroy script can't see
# (operators using raw `git worktree remove`, post-destroy spawn races, etc.).
# Silent skip when vendored at a non-canonical path (warning, not a gate).
AUDIT_SCRIPT="skills/using-git-worktrees/scripts/audit-worktree-zombies.sh"
if [[ -x "$AUDIT_SCRIPT" ]]; then
  if ! "$AUDIT_SCRIPT" --quiet; then
    echo "WARN: worktree zombies detected — see 'bash $AUDIT_SCRIPT'" >&2
  fi
fi

# --- Optional JS toolchain (auto-detected) -----------------------------------
# Projects with a frontend ship a package.json. Pure-backend projects skip
# this block entirely without per-project override.

if [[ -f "package.json" ]]; then
  # Probing package.json requires node. Fail loudly if it's absent rather than
  # silently treating every script as missing (gate-script discipline: the
  # output of `has_script` decides whether each JS gate runs, so its stderr
  # must not be swallowed).
  if ! command -v node >/dev/null 2>&1; then
    echo "ERROR: node is required to probe package.json scripts (no JS gates would run)" >&2
    exit 2
  fi

  # Validate package.json parses cleanly up front. Without this, `has_script`
  # would return non-zero on a JSON parse error and the JS gates would silently
  # skip — conflating "script missing" with "package.json broken." Gate-script
  # discipline: a broken package.json is an ERROR (exit 2), not a skip.
  # require("./package.json") uses node's built-in JSON loader; a parse error
  # throws and node exits non-zero with the parse error on stderr.
  if ! node -e 'require("./package.json")' >/dev/null; then
    echo "ERROR: package.json failed to parse" >&2
    exit 2
  fi

  # has_script <name>: exits 0 if package.json has the named npm script, else 1.
  # Script name is passed via env so colons (`lint:js`) or any future special
  # character can't break out of the node -e JS literal. With package.json
  # pre-validated above, non-zero from has_script means only "script not present".
  has_script() {
    SCRIPT="$1" node -e 'const s=require("./package.json").scripts; process.exit(s&&s[process.env.SCRIPT]?0:1)'
  }

  if has_script lint:js; then
    echo ""
    echo "=== Lint (ESLint) ==="
    npm run lint:js
  fi

  if has_script format:js:check; then
    echo ""
    echo "=== Format check (Prettier) ==="
    npm run format:js:check
  fi

  if has_script test:js; then
    echo ""
    echo "=== Tests (JS) ==="
    npm run test:js
  fi
fi
