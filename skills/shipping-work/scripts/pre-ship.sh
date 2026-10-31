#!/usr/bin/env bash
# pre-ship.sh
# The ship gate. It asks detect-stack.sh what the repo has and runs every check
# each toolchain owns — one implementation per check, the same in every repo,
# instead of one forked gate per named stack that drifted apart (#537). The
# decision behind each check is a row in references/gate-topology.md.
#
#   uv        ruff check, ruff format --check, an import check, then pytest
#             with integration tests deselected, --no-cov when pytest-cov is
#             installed, and xdist when the project's environment has it
#   composer  composer validate at each composer.json, php -l on every tracked
#             PHP file, and composer test when the project defines it
#   npm       whichever of lint:js, format:js:check and test:js it declares
#
# Every check runs even after one fails, and the gate then exits 1 naming each
# failure, so one run shows everything there is to fix. A tooling failure
# stops it at once with exit 2. A pass is recorded against the exact tree
# (gate-stamp.sh), and a later run on the same tree reuses it.
#
# Nothing detected, or nothing to run, is exit 1: a gate that verified nothing
# must not read as green. A project with another toolchain supplies its own
# gate as scripts/pre-ship.sh at its repo root, which SKILL.md Step 1
# resolves ahead of this one (#301).
#
# Usage: bash "<pre-ship.sh>" [--help]
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

usage() {
  echo "Usage: bash \"$0\" [--help]"
  echo ""
  echo "Runs the checks for every toolchain detect-stack.sh finds:"
  echo "  uv        uv run ruff check . ; uv run ruff format --check . ; an import"
  echo "            check (.skills/import-targets, else the [project] name) ;"
  echo "            uv run pytest, integration-marked tests deselected on top of"
  echo "            the project's own marker expression, --no-cov when pytest-cov"
  echo "            is installed, -n N --dist loadfile when xdist is"
  echo "  composer  composer validate ; php -l on tracked PHP files ; composer test"
  echo "  npm       npm run lint:js / format:js:check / test:js, when declared"
  echo ""
  echo "Every check runs; the gate then exits 1 naming each one that failed."
  echo "Nothing detected exits 1: supply scripts/pre-ship.sh at your repo root."
  echo ""
  echo "Knobs:"
  echo "  .skills/pre-ship-uv-args   arguments inserted after 'uv run' in every"
  echo "                             uv call (e.g. --group seed); whitespace-"
  echo "                             separated, '#'-comment lines ignored"
  echo "  .skills/import-targets     packages the import check imports"
  echo "  .skills/test-workers       off | auto | N  (or PYTEST_XDIST_AUTO_NUM_WORKERS)"
  echo "  PRE_SHIP_PHP_LINT_JOBS     parallel php -l jobs (default: the worker count)"
  echo "  PRE_SHIP_ENV_NAMES         names a wrapper's env files set; they join the"
  echo "                             stamp key, and an empty list writes no stamp"
  echo "  GATE_STAMP=off             always run; never reuse or record a pass"
  echo ""
  echo "Exit codes:"
  echo "  0  every check passed (or this exact tree already passed)"
  echo "  1  a check failed, or nothing was detected to run"
  echo "  2  tooling/infra failure (a detected toolchain's tool missing, a helper"
  echo "     failed, mktemp failed, .skills/pre-ship-uv-args present but unreadable)"
}

for arg in "$@"; do
  case "$arg" in
    --help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument '$arg'" >&2; usage >&2; exit 2 ;;
  esac
done

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}
cd "$PROJECT_ROOT"

# --- Project-local env loading (optional override point) ---------------------
# Upstream ships without env loading — most projects don't need it. If yours
# does (test fixtures reading live secrets, a conftest that hard-fails on a
# missing DSN), do NOT fork this script: a fork copies every gate below to add
# a handful of lines, then stops receiving upstream fixes without saying so.
# The skill's resolution loop (SKILL.md Step 1) probes `scripts/` first, so a
# project-local WRAPPER wins and delegates back here:
#
#   #!/usr/bin/env bash
#   set -euo pipefail
#   PROJECT_ROOT=$(git rev-parse --show-toplevel); cd "$PROJECT_ROOT"
#   DELEGATE="skills/shipping-work/scripts/pre-ship.sh"
#   [[ -f "$DELEGATE" ]] || {
#     echo "ERROR: vendored gate missing at $DELEGATE" >&2
#     echo "       fix: git submodule update --init --recursive" >&2
#     exit 2
#   }
#   load_env() {                                  # parse, never source
#     local line key val                          # safe to lift into a shell
#     [ -r "$1" ] || return 0
#     while IFS= read -r line || [ -n "$line" ]; do
#       line=${line#"${line%%[![:space:]]*}"}       # drop leading blanks
#       case $line in ''|\#*) continue ;; esac       # blank or comment
#       line=${line#export }                        # tolerate `export K=v`
#       case $line in *=*) ;; *) continue ;; esac
#       key=${line%%=*} val=${line#*=}
#       key=${key%"${key##*[![:space:]]}"}
#       case $key in ''|[0-9]*|*[!A-Za-z0-9_]*) continue ;; esac
#       case $val in                                # strip matched quotes
#         \"*\") val=${val#\"} val=${val%\"} ;;
#         \'*\') val=${val#\'} val=${val%\'} ;;
#       esac
#       export "$key=$val"
#       PRE_SHIP_ENV_NAMES="${PRE_SHIP_ENV_NAMES:+$PRE_SHIP_ENV_NAMES }$key"
#     done < "$1"
#   }
#   export PRE_SHIP_ENV_NAMES=""                  # names only: the stamp's key
#   ETC_ENV="/etc/<project>/.env" LOCAL_ENV="$PROJECT_ROOT/.env"
#   ENV_FILE=$LOCAL_ENV                           # a linked worktree has none,
#   [ -r "$ENV_FILE" ] ||                         # so use the primary checkout's
#     ENV_FILE="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")/.env"
#   [ -r "$ETC_ENV" ] || [ -r "$ENV_FILE" ] || {  # neither: say so, loudly
#     [ "$ENV_FILE" = "$LOCAL_ENV" ] || LOCAL_ENV="$LOCAL_ENV or $ENV_FILE"
#     echo "WARN: no env file at $ETC_ENV or $LOCAL_ENV;" >&2
#     echo "      tests that need one will skip, and no stamp is written" >&2
#   }
#   for f in "$ETC_ENV" "$ENV_FILE"; do load_env "$f"; done  # paths fixed first
#   exec bash "$DELEGATE" "$@"
#
# Every line there is a trap someone has already hit:
#   - Delegate through the SYMLINK path (skills/...), never skills-vendor/... —
#     the symlink is the stable interface, the vendor layout is not.
#   - `exec`, so the exit code the Iron Law gates on propagates unchanged.
#   - "$@", so `--help` still reaches this script.
#   - The missing-delegate guard exits 2, matching this script's own
#     tooling/infra code so operators read one exit-code table rather than
#     two. Without the guard an unpopulated submodule (a clone without
#     --recurse-submodules, a fresh `git worktree add`) fails as bash's
#     generic "No such file or directory".
#   - Parse the file line by line; never `set -a; . file`, and never
#     `export $(cat ... | xargs)`. That one-liner shipped here until #144
#     and had three defects: with both files absent it degenerated to a bare
#     `export`, dumping every exported variable — secrets included — into the
#     ship-gate transcript; a `#` comment line reached `export` as `'#': not a
#     valid identifier`, so `set -e` killed the wrapper BEFORE the gate ran;
#     and `xargs` word-split `PW=two words` into a wrong value with exit 0.
#   - Quoting `export "$key=$val"` is what makes spaces, globs and quoted
#     values survive, so no `set -f` dance and no shellcheck suppressions.
#   - Skipping a key that is not a plain identifier, rather than aborting.
#     A malformed line in a secrets file must not decide whether the gate
#     runs — that is precisely the environmental-vs-real judgement call a
#     gate should never put in front of an operator.
#   - Fall back to the primary checkout's .env, and WARN when neither file
#     exists. A gitignored .env lives only in the primary checkout, so in a
#     linked worktree "$PROJECT_ROOT/.env" is missing, and load_env returns 0
#     on a missing file by design: the tests that needed it skipped and the
#     gate passed, saying nothing (#497). --git-common-dir names the
#     primary's .git from any worktree. Every path is fixed before either
#     file loads, since /etc's may set PROJECT_ROOT; the WARN fires only when
#     neither file is readable, and prints paths, never a value.
#   - Export PRE_SHIP_ENV_NAMES, the names (never the values) the env files
#     set. This gate folds them into its stamp key, and writes no stamp when
#     the list is empty, so a run that loaded no env cannot bless the tree
#     for the run that does (#497). A wrapper that does not export it keeps
#     a key without env names.

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

TMP=$(mktemp -d) || { echo "ERROR: mktemp failed" >&2; exit 2; }
SLOT=""
trap 'rm -rf "$TMP"; [[ -z "$SLOT" ]] || rm -f "$SLOT"' EXIT

# --- What this repo has ------------------------------------------------------
DETECT="$SCRIPT_DIR/detect-stack.sh"
if [[ ! -f "$DETECT" ]]; then
  echo "ERROR: detect-stack.sh is missing beside this script ($SCRIPT_DIR)." >&2
  echo "       The gate cannot tell which checks this repo needs." >&2
  exit 2
fi
DETECT_RC=0
bash "$DETECT" >"$TMP/stack" || DETECT_RC=$?
if [[ $DETECT_RC -ne 0 ]]; then
  echo "ERROR: detect-stack.sh failed (exit $DETECT_RC)" >&2
  exit 2
fi
has() { grep -qx "toolchain	$1" "$TMP/stack"; }
UV=0 COMPOSER=0 NPM=0
if has uv; then UV=1; fi
if has composer; then COMPOSER=1; fi
if has npm; then NPM=1; fi

no_gate() {
  echo "ERROR: $1" >&2
  echo "       This gate runs the checks of the toolchains it can detect: uv" >&2
  echo "       (pyproject.toml with uv.lock or [tool.uv]), composer" >&2
  echo "       (composer.json) and npm (package.json scripts lint:js," >&2
  echo "       format:js:check, test:js). For anything else, write" >&2
  echo "       scripts/pre-ship.sh at your repo root with your test runner in" >&2
  echo "       it; SKILL.md Step 1 resolves it ahead of this script (#301)." >&2
  echo "       Do not copy shipping-work/ into your own skills/ directory: a" >&2
  echo "       copy of the whole skill drifts on every update." >&2
  exit 1
}

if [[ $UV -eq 0 && $COMPOSER -eq 0 && $NPM -eq 0 ]]; then
  no_gate "no toolchain detected, so there is nothing for this gate to run."
fi
# SKILL.md reads this line: each `framework <name>` names the
# references/stack-<name>.md that holds that framework's next steps.
echo "Detected: $(awk -F'\t' '{printf "%s%s %s", (NR > 1 ? ", " : ""), $1, $2}' "$TMP/stack")"

# A detected toolchain whose tool is missing is a tooling failure, not a pass.
need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: $1 is not installed, but this repo $2." >&2
    exit 2
  fi
}
if [[ $UV -eq 1 ]]; then need uv "is a uv project"; fi
if [[ $COMPOSER -eq 1 ]]; then need composer "has a composer.json"; fi
if [[ $NPM -eq 1 ]]; then need node "has a package.json (node reads its scripts)"; fi

# The project's declared npm scripts, read once. node parses package.json; a
# file it cannot parse is a tooling failure, never "no scripts".
NPM_SCRIPTS=()
if [[ $NPM -eq 1 ]]; then
  if ! node -e 'require("./package.json")' >/dev/null; then
    echo "ERROR: package.json failed to parse" >&2
    exit 2
  fi
  for s in lint:js format:js:check test:js; do
    if SCRIPT="$s" node -e 'const s=require("./package.json").scripts; process.exit(s&&s[process.env.SCRIPT]?0:1)'; then
      NPM_SCRIPTS+=("$s")
    fi
  done
  if [[ ${#NPM_SCRIPTS[@]} -gt 0 ]]; then need npm "declares npm scripts"; fi
fi

# Tracked PHP files, captured with git's own status so a failing ls-files can
# never read as "no PHP to lint".
TRACKED_PHP=()
if [[ $COMPOSER -eq 1 ]]; then
  LS_RC=0
  git ls-files -z '*.php' >"$TMP/php" 2>"$TMP/php.err" || LS_RC=$?
  if [[ $LS_RC -ne 0 ]]; then
    echo "ERROR: git ls-files failed (exit $LS_RC):" >&2
    cat "$TMP/php.err" >&2
    exit 2
  fi
  while IFS= read -r -d '' f; do TRACKED_PHP+=("$f"); done <"$TMP/php"
  if [[ ${#TRACKED_PHP[@]} -gt 0 ]]; then need php "has tracked PHP files"; fi
fi

if [[ $UV -eq 0 && $COMPOSER -eq 0 && ${#NPM_SCRIPTS[@]} -eq 0 ]]; then
  no_gate "package.json declares none of lint:js, format:js:check or test:js, so there is nothing for this gate to run."
fi

# --- .skills/pre-ship-uv-args ------------------------------------------------
# Arguments inserted after `uv run` in every uv call (e.g. `--group seed`, so
# the gate runs the suite the project's own hook runs). Whitespace-separated,
# never glob-expanded; a file that exists but cannot be read is exit 2, not an
# empty list.
UV_ARGS=()
UV_ARGS_FILE=.skills/pre-ship-uv-args
if [[ -e "$UV_ARGS_FILE" || -L "$UV_ARGS_FILE" ]]; then
  if [[ ! -f "$UV_ARGS_FILE" ]] || ! exec 3<"$UV_ARGS_FILE"; then
    echo "ERROR: $UV_ARGS_FILE exists but cannot be read as a file of uv" >&2
    echo "       arguments. Fix or remove it." >&2
    exit 2
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    line=${line%$'\r'}
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    read -r -a words <<<"$line"
    [[ ${#words[@]} -eq 0 ]] || UV_ARGS+=("${words[@]}")
  done <&3
  exec 3<&-
fi
uv_run() { uv run ${UV_ARGS[@]+"${UV_ARGS[@]}"} "$@"; }

# --- Workers -----------------------------------------------------------------
# gate-workers.sh: PYTEST_XDIST_AUTO_NUM_WORKERS, then .skills/test-workers,
# then the cores shared across the gates running now. It only sets how fast
# the checks run, so a copy without it runs them serially.
WORKERS="$SCRIPT_DIR/gate-workers.sh"
N=0
if [[ -f "$WORKERS" ]]; then
  N=$(bash "$WORKERS" --explain) || exit 2
fi

# --- Reuse a pass recorded for this exact tree --------------------------------
# The key: the tree, the OS, PYTEST_ADDOPTS and PYTHONPATH, the detected
# stacks and their tools' versions, PATH without git's exec-path (git puts it
# first in every hook), the env names a wrapper loaded, and gate-stamp.sh's
# untracked inputs. Under a pre-commit hook it keys the tree being committed.
STAMP="$SCRIPT_DIR/gate-stamp.sh"
STAMP_OK=1
if [[ ! -f "$STAMP" ]]; then
  STAMP_OK=0
fi
ENV_NAMES_LINE="env-names unset"
if [[ -n "${PRE_SHIP_ENV_NAMES+set}" ]]; then
  read -r -a ENV_NAMES <<<"$PRE_SHIP_ENV_NAMES"
  if [[ ${#ENV_NAMES[@]} -eq 0 ]]; then
    echo "WARN: PRE_SHIP_ENV_NAMES is empty (the wrapper's env files set nothing);" >&2
    echo "      every check runs, and no pass is recorded." >&2
    STAMP_OK=0
  else
    ENV_NAMES_LINE="env-names $(printf '%s\n' "${ENV_NAMES[@]}" | LC_ALL=C sort -u | tr '\n' ' ')"
  fi
fi

key_path() {
  local exec_path entry out=""
  exec_path=$(git --exec-path) || return 1
  local IFS=:
  for entry in $PATH; do
    if [[ "$entry" != "$exec_path" ]]; then
      out=${out:+$out:}$entry
    fi
  done
  echo "$out"
}

# `sed -n 1p`, not `head -1`: head exits early, and under pipefail the
# writer's SIGPIPE would fail the pipe.
tool_versions() {
  local t v out="tools"
  for t in uv composer php node npm; do
    if command -v "$t" >/dev/null 2>&1; then
      v=$("$t" --version 2>&1 | sed -n 1p) || return 1
      out="$out $t=[$v]"
    fi
  done
  echo "$out"
}

stamp_key() {
  local kpath tools args=()
  kpath=$(key_path) || return 2
  tools=$(tool_versions) || return 2
  if [[ "${PRE_COMMIT:-}" == "1" ]]; then args+=(--index); fi
  if [[ "${GATE_STAMP_EXPLAIN:-}" == "1" ]]; then args+=(--explain); fi
  bash "$STAMP" key ${args[@]+"${args[@]}"} \
    --env PYTEST_ADDOPTS --env PYTHONPATH \
    --extra "stacks $(tr '\n' ' ' <"$TMP/stack")" \
    --extra "PATH=$kpath" --extra "$tools" --extra "$ENV_NAMES_LINE"
}

KEY=""
if [[ $STAMP_OK -eq 1 ]]; then
  RC=0
  KEY=$(stamp_key) || RC=$?
  case "$RC" in
    0) ;;
    3) KEY="" ;;  # not stampable; gate-stamp.sh said why
    *) echo "NOTE: no stamp key (exit $RC) — running without reuse" >&2; KEY="" ;;
  esac
  if [[ -n "$KEY" ]]; then
    RC=0
    RECORD=$(bash "$STAMP" check "$KEY") || RC=$?
    case "$RC" in
      0)
        echo "Pre-ship: this exact tree already passed — not re-running."
        echo "  recorded: $RECORD"
        echo "  (GATE_STAMP=off forces a run)"
        exit 0
        ;;
      1) ;;
      *) echo "NOTE: stamp check failed (exit $RC) — running" >&2 ;;
    esac
  fi
fi

# --- The checks ----------------------------------------------------------------
START=$SECONDS
FAILED=()
check() {
  local label=$1 rc=0
  shift
  echo ""
  echo "=== $label ==="
  "$@" || rc=$?
  if [[ $rc -ne 0 ]]; then
    FAILED+=("$label (exit $rc)")
  fi
}

if [[ $UV -eq 1 ]]; then
  check "Lint (ruff)" uv_run ruff check .
  check "Format check (ruff)" uv_run ruff format --check .

  # The resolver is shared, byte for byte, with reviewing-code-python-click,
  # so review and ship import the same packages.
  IMPORTS="$SCRIPT_DIR/detect-import-targets.sh"
  if [[ ! -f "$IMPORTS" ]]; then
    echo "ERROR: detect-import-targets.sh is missing beside this script." >&2
    exit 2
  fi
  IMPORT_RC=0
  bash "$IMPORTS" >"$TMP/imports" || IMPORT_RC=$?
  if [[ $IMPORT_RC -ne 0 ]]; then
    echo "ERROR: detect-import-targets.sh failed (exit $IMPORT_RC)" >&2
    exit 2
  fi
  # A target the project named in .skills/import-targets always runs. One
  # guessed from the [project] name runs only when the tree has it, as
  # `<name>/` or `src/<name>/`: most services package their code as `src`
  # (hatch `packages = ["src"]`), and importing a name that is nowhere in the
  # repo tests the guess, not the packaging.
  IMPORT_TARGETS=()
  GUESSED_AWAY=()
  while IFS= read -r pkg; do
    [[ -n "$pkg" ]] || continue
    if [[ -e .skills/import-targets || -d "$pkg" || -d "src/$pkg" ]]; then
      IMPORT_TARGETS+=("$pkg")
    else
      GUESSED_AWAY+=("$pkg")
    fi
  done <"$TMP/imports"
  if [[ ${#IMPORT_TARGETS[@]} -eq 0 ]]; then
    echo ""
    echo "=== Import check ==="
    if [[ ${#GUESSED_AWAY[@]} -gt 0 ]]; then
      echo "No package named ${GUESSED_AWAY[*]} (from the [project] name) at the root or under src/."
      echo "Skipping. List what to import in .skills/import-targets (e.g. src) to check it."
    else
      echo "No import target (no .skills/import-targets and no [project] name). Skipping."
    fi
  else
    for pkg in "${IMPORT_TARGETS[@]}"; do
      check "Import $pkg" uv_run python -c "import $pkg"
    done
  fi

  # Integration tests are excluded by a plugin, never by `-m`. A command-line
  # `-m` REPLACES the marker expression in the project's addopts rather than
  # intersecting with it: `-m "not integration"` once silently dropped
  # power-map's `not browser` and ran a Playwright tier its config excludes
  # (#304). The plugin deselects integration-marked items AFTER pytest has
  # applied the project's own expression. It is written per run, not shipped
  # beside this script: a consumer vendoring by per-file symlinks carries only
  # the files it linked, and `-p` fails loudly on a module that is not there.
  mkdir "$TMP/plugin"
  if ! cat >"$TMP/plugin/pre_ship_not_integration.py" <<'PY'
import pytest


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    keep, drop = [], []
    for item in items:
        (drop if item.get_closest_marker("integration") else keep).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep
PY
  then
    echo "ERROR: could not write the pytest plugin under $TMP/plugin" >&2
    exit 2
  fi
  PYTEST_ARGS=(-p pre_ship_not_integration)
  # --no-cov only when pytest-cov is there to accept it: a coverage threshold
  # belongs in CI, and the flag is a usage error without the plugin.
  if uv_run python -c "import pytest_cov" >/dev/null 2>&1; then
    PYTEST_ARGS+=(--no-cov)
  fi
  if [[ "$N" -ge 2 ]]; then
    if uv_run python -c "import xdist" >/dev/null 2>&1; then
      PYTEST_ARGS+=(-n "$N" --dist loadfile)
      if SLOTS=$(bash "$WORKERS" --slot-dir); then
        SLOT="$SLOTS/$$"
        : >"$SLOT" || {
          echo "NOTE: could not take a gate slot — running without one" >&2
          SLOT=""
        }
      fi
    else
      echo "NOTE: $N workers allowed, but pytest-xdist is not in the project's" >&2
      echo "      environment — running serially. Add it as a dev dependency" >&2
      echo "      to run the suite in parallel." >&2
    fi
  fi
  echo ""
  echo "=== Tests (pytest) ==="
  PYTEST_RC=0
  PYTHONPATH="$TMP/plugin${PYTHONPATH:+:$PYTHONPATH}" \
    uv_run pytest "${PYTEST_ARGS[@]}" || PYTEST_RC=$?
  case $PYTEST_RC in
    0) ;;
    5) echo "NOTE: pytest collected no tests (exit 5) — counted as a pass." ;;
    *) FAILED+=("Tests (pytest) (exit $PYTEST_RC)") ;;
  esac
fi

if [[ $COMPOSER -eq 1 ]]; then
  COMPOSER_DIRS=()
  [[ -f composer.json ]] && COMPOSER_DIRS+=(".")
  for f in themes/*/composer.json plugins/*/composer.json; do
    [[ -f "$f" ]] && COMPOSER_DIRS+=("$(dirname "$f")")
  done
  for dir in "${COMPOSER_DIRS[@]}"; do
    check "composer validate ($dir)" composer --working-dir="$dir" validate --no-check-publish
  done

  if [[ ${#TRACKED_PHP[@]} -gt 0 ]]; then
    JOBS="${PRE_SHIP_PHP_LINT_JOBS:-}"
    if [[ -z "$JOBS" ]]; then
      JOBS=$N
      [[ "$JOBS" -ge 1 ]] || JOBS=1
    elif ! [[ "$JOBS" =~ ^[1-9][0-9]*$ ]]; then
      echo "WARN: PRE_SHIP_PHP_LINT_JOBS='$JOBS' is not a positive integer; using 1." >&2
      JOBS=1
    fi
    # php -l's stderr (multi-line syntax errors) flows through to the user.
    # $1 is expanded by the inner bash -c, once per file, which is the point.
    # shellcheck disable=SC2016
    php_lint() {
      printf '%s\0' "${TRACKED_PHP[@]}" | xargs -0 -P "$JOBS" -I {} \
        bash -c '[[ -f "$1" ]] || exit 0; php -l "$1" >/dev/null || { echo "FAIL: php -l $1" >&2; exit 1; }' _ {}
    }
    check "php -l (${#TRACKED_PHP[@]} tracked files, $JOBS jobs)" php_lint
  fi

  if [[ -f composer.json ]]; then
    # The probe's stderr is kept: a failing list must say why, and must fail,
    # rather than read as "no test script" and skip the suite.
    LIST_RC=0
    composer run-script --list >"$TMP/scripts" 2>"$TMP/scripts.err" || LIST_RC=$?
    if [[ $LIST_RC -ne 0 ]]; then
      echo ""
      echo "=== composer test ==="
      cat "$TMP/scripts.err" >&2
      FAILED+=("composer test (could not list scripts, exit $LIST_RC)")
    elif grep -qE '^[[:space:]]*test[[:space:]]' "$TMP/scripts"; then
      check "composer test" composer test
    fi
  fi
fi

for s in ${NPM_SCRIPTS[@]+"${NPM_SCRIPTS[@]}"}; do
  check "npm run $s" npm run "$s"
done

echo ""
if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo "Pre-ship checks FAILED:" >&2
  printf '  - %s\n' "${FAILED[@]}" >&2
  exit 1
fi

# Record the pass only if nothing moved under the run: the key is computed
# again and must still match.
if [[ -n "$KEY" ]]; then
  AFTER=$(stamp_key) || AFTER=""
  if [[ "$AFTER" == "$KEY" ]]; then
    bash "$STAMP" write "$KEY" --label "pre-ship, $N workers" \
      --seconds "$((SECONDS - START))" \
      || echo "NOTE: the pass was not recorded; the next run will repeat it" >&2
  else
    echo "NOTE: files changed during the run — the pass is not recorded" >&2
  fi
fi
echo "Pre-ship checks passed."
