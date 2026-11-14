#!/usr/bin/env bash
# deploying-releases-core: version 1
# deploying-releases-core-sha256: 3f5b8473d302efffccbe3d60433c9ba1c7ac2033b02ba48cea7bc0cdff849d55
#
# The cohort's one release-deploy core (gregoryfoster/skills#372), installed by
# deploying-releases' install.sh. Do not edit it here: configure it in
# scripts/deploy_hooks.sh, and upgrade it with install.sh, reviewing the diff.
#
#   scripts/deploy.sh [<ref>]                every target the release's units run; <ref> on origin/main, default origin/main
#   scripts/deploy.sh --target <t> [<ref>]   one target, live or dev; dev also takes a commit on a pushed branch
#   scripts/deploy.sh --skip-ci [<ref>]      without asking CI: an emergency, journaled
#   scripts/deploy.sh --build-only [<ref>]   build releases/<sha12> and stop: nothing switched
#   scripts/deploy.sh --no-restart [<ref>]   a first deploy or a cutover: switch and install units, restart nothing
#   scripts/deploy.sh --verify [<ref>]       restart and verify every unit of each target, as if its link moved
#   scripts/deploy.sh --help
#
# Exits 0 when deployed and verified (or built, with --build-only); 1 when
# refused, or failed and switched back to a build that answers; 4 when a target
# is left on a build that does not answer.
#
# Extracted from CannObserv/broker's scripts/deploy.sh at bbf1c72f, which took
# CannObserv/processor's (a CI gate, a unit install) and CannObserv/status's
# root-owned releases (status#14). The units run <root>/live, or <root>/dev: a
# link into releases/<sha12>, a read-only `git archive` of one commit with its
# own venv, owned by root. Nothing done in a checkout reaches a unit until this
# script puts it there.
#
# A unit's target is its WorkingDirectory=: <root>/live is live, <root>/dev is
# dev, and a repo with no dev unit has no dev target. Per target, dev first:
#   0. preflight: not root, a checkout, the root root's alone, the lock
#   1. resolve the commit; ask GitHub whether its CI passed (CI=github)
#   2. build releases/<sha12> once (or reuse it): archive SERVICE_DIR, uv sync
#      --locked through UV_WRAPPER, build_extra, REQUIRED_ARTIFACTS, the import
#      probe, read-only, root's, REVISION last, post_build_check
#   3. refuse a unit whose User= does not exist; pre_switch_check <target>
#   4. migrate <target>, before the switch: migrations are expand-only
#   5. switch the link (rename(2)); install the target's units that differ, one
#      daemon-reload, each checked as loaded
#   6. restart each long-running unit that is enabled or active and runs the
#      target; timers are never forced
#   7. verify each unit this deploy changed: the verify hook, or, for a
#      restarted unit it has no check for, its new process on the new release
#   8. on failure, switch back, units too, restart, and prove the old build
#   9. verified: enable ENABLE_NEW units this deploy added; post_verify;
#      compare host configs (never installed); prune to KEEP plus every link
#
# Runs as the deploy user (exedev), and sudo -n for every write under the root,
# the unit files and systemctl: a password prompt would hang the deploy
# holding its lock, so it is a refusal instead. Root ownership is no boundary
# against a user who can sudo anything; what it buys is that changing what a
# unit runs takes sudo, which journals the command.
set -euo pipefail

((BASH_VERSINFO[0] >= 4)) || {
  echo "deploy: needs bash 4 or later, not $BASH_VERSION" >&2
  exit 1
}

CORE_VERSION=1
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS="$SRC/scripts/deploy_hooks.sh"
TAG=deploy

note() { echo "deploy: $*" >&2; }
# Said and journaled: what a verify proved outlives a detached deploy's log.
say() {
  note "$*"
  logger -t "$TAG" "$*" || true
}
journal() { logger -t "$TAG" "$*" || true; }
die() {
  note "$*"
  exit 1
}
dead() {
  note "$*"
  exit 4
}

usage() {
  cat <<'EOF'
scripts/deploy.sh [<ref>]                every target the release's units run; <ref> on origin/main, default origin/main
scripts/deploy.sh --target <t> [<ref>]   one target, live or dev; dev also takes a commit on a pushed branch
scripts/deploy.sh --skip-ci [<ref>]      without asking CI: an emergency, journaled
scripts/deploy.sh --build-only [<ref>]   build releases/<sha12> and stop: nothing switched
scripts/deploy.sh --no-restart [<ref>]   a first deploy or a cutover: switch and install units, restart nothing
scripts/deploy.sh --verify [<ref>]       restart and verify every unit of each target, as if its link moved
scripts/deploy.sh --help

Configured in scripts/deploy_hooks.sh. Exits 0 when deployed and verified, 1
when refused or switched back to a build that answers, 4 when a target is left
on a build that does not answer.
EOF
}

skip_ci=0
build_only=0
no_restart=0
force_verify=0
only_target=""
ref=""
while (($#)); do
  case "$1" in
    --skip-ci) skip_ci=1 ;;
    --build-only) build_only=1 ;;
    --no-restart) no_restart=1 ;;
    --verify) force_verify=1 ;;
    --target)
      (($# > 1)) || die "--target needs live or dev"
      only_target="$2"
      shift
      ;;
    -h | --help)
      usage
      echo "deploying-releases core, version $CORE_VERSION"
      exit 0
      ;;
    -*) die "unknown flag $1 (see --help)" ;;
    *)
      [[ -z "$ref" ]] || die "one ref at a time"
      ref="$1"
      ;;
  esac
  shift
done
case "$only_target" in "" | live | dev) ;; *) die "--target is live or dev, not $only_target" ;; esac
((!(force_verify && (no_restart || build_only)))) || die "--verify restarts and verifies: not with --no-restart or --build-only"
ref="${ref:-origin/main}"

# --- configuration -----------------------------------------------------------
#
# The defaults, then the repo's scripts/deploy_hooks.sh over them. Every hook a
# repo leaves undefined keeps the default here: nothing to do, or, for verify,
# "no check for this unit".

PROJECT=""
SERVICE_DIR=.
UNITS_DIR=deploy
CI=github
CI_AUTH=anonymous
CI_WORKFLOW=ci.yml
GITHUB_REPO=""
CI_JOBS=()
PYTHON=/usr/bin/python3.12
UV_WRAPPER=""
SOURCE_DIRS=(src)
IMPORT_MODULES=()
REVISION_PROBE=""
REQUIRED_ARTIFACTS=()
HOST_CONFIGS=()
DERIVED_CONFIGS=()
ENABLE_NEW=()
KEEP=5

build_extra() { :; }
post_build_check() { :; }
pre_switch_check() { :; }
migrate() { :; }
verify() { return 2; }
post_verify() { :; }

[[ -f "$HOOKS" ]] || die "$HOOKS is missing: the core reads its configuration there (deploying-releases)"
# The consumer's own file, which this repo does not have to follow.
# shellcheck source=/dev/null
source "$HOOKS"

[[ "$PROJECT" =~ ^[a-z][a-z0-9-]*$ ]] ||
  die "PROJECT=${PROJECT:-nothing} in $HOOKS is not a unit prefix (lowercase, digits, hyphens)"
TAG="$PROJECT-deploy"
P="$(tr 'a-z-' 'A-Z_' <<<"$PROJECT")"
# <P>_DEPLOY_<NAME>, or the default: the path seams are the tests'.
knob() {
  local name="${P}_DEPLOY_$1"
  printf '%s' "${!name:-$2}"
}
ROOT="$(knob ROOT "/srv/$PROJECT")"
# Prefixed to every installed path: a test's tree, nothing on the host.
HOST="$(knob HOST "")"
PROC="$HOST/proc"
KEEP="$(knob KEEP "$KEEP")"
PYTHON="$(knob PYTHON "$PYTHON")"
# CI takes minutes; a run still going after this is wedged or queued behind one.
CI_WAIT_SECONDS="$(knob CI_WAIT_SECONDS 600)"
CI_POLL_SECONDS="$(knob CI_POLL_SECONDS 30)"
# How long a restarted unit or an HTTP check has to answer.
VERIFY_SECONDS="$(knob VERIFY_SECONDS 120)"
# A timer's next natural tick, for verify_next_tick.
TICK_SECONDS="$(knob TICK_SECONDS 900)"
# A oneshot already running, for verify_forced_run to wait out.
RUN_WAIT_SECONDS="$(knob RUN_WAIT_SECONDS 660)"
POLL_SECONDS="$(knob POLL_SECONDS 10)"
UNIT_DIR="$HOST/etc/systemd/system"

# Whole numbers, or refused before anything runs: bash arithmetic on "5x" is an
# error that would otherwise end a verified deploy at the prune.
for name in KEEP CI_WAIT_SECONDS CI_POLL_SECONDS VERIFY_SECONDS TICK_SECONDS RUN_WAIT_SECONDS POLL_SECONDS; do
  [[ "${!name}" =~ ^[0-9]+$ ]] || die "${P}_DEPLOY_$name=${!name} is not a whole number"
done
case "$CI" in
  github)
    [[ "$GITHUB_REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] ||
      die "CI=github needs GITHUB_REPO=<owner>/<repo> in $HOOKS"
    ;;
  none) ;;
  *) die "CI=$CI in $HOOKS is github or none" ;;
esac
case "$CI_AUTH" in anonymous | gh) ;; *) die "CI_AUTH=$CI_AUTH in $HOOKS is anonymous or gh" ;; esac
[[ "$SERVICE_DIR" != /* && "$SERVICE_DIR" != *..* ]] || die "SERVICE_DIR=$SERVICE_DIR must be a path inside the repo"

# exedev builds, and root only takes the finished release. Built by root, uv
# would use root's cache, and no write under the root would need sudo.
[[ "$(id -u)" -ne 0 ]] || die "run as the deploy user, not root; the script sudoes where it needs to"

# A release has a copy of this script and no .git to build from.
git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1 ||
  die "run from a checkout (<checkout>/scripts/deploy.sh); $SRC is not one"
# Hooks run from the checkout, whether this run builds the release or reuses it.
cd "$SRC" || die "cannot enter the checkout $SRC"

[[ -d "$ROOT" ]] || die "$ROOT does not exist. Once: sudo install -d -o root -g root -m 755 $ROOT"

wrap=()
if [[ -n "$UV_WRAPPER" ]]; then
  [[ -f "$SRC/$UV_WRAPPER" ]] || die "UV_WRAPPER=$UV_WRAPPER is not in this checkout ($SRC)"
  wrap=(bash "$SRC/$UV_WRAPPER")
fi

# Root's, and writable by root alone: a link is only as safe as its directory,
# and the deploy user could otherwise repoint live with ln (status#14).
roots_alone() { # <dir>
  local mode
  # A link's own mode is 777.
  [[ ! -L "$1" ]] || die "$1 is a link; it must be the directory itself"
  [[ "$(stat -c %u:%g -- "$1")" == 0:0 ]] ||
    die "$1 is not root:root, so the deploy user can change what the units run." \
      "Once: sudo chown root:root $1"
  mode="$(stat -c %a -- "$1")"
  ((!(8#$mode & 8#022))) || die "$1 is writable by more than root. Once: sudo chmod 755 $1"
}
roots_alone "$ROOT"
# -L too: -e is false for a link to nowhere, which install -d cannot make.
[[ ! -e "$ROOT/releases" && ! -L "$ROOT/releases" ]] || roots_alone "$ROOT/releases"

# The root directory itself: the deploy user cannot create a lock file in it.
exec 9<"$ROOT"
flock -n 9 || die "another deploy is running (it holds the lock on $ROOT)"

# Left set in a shell, a path seam retargets a real deploy: each that is not
# the host's default is said, and journaled.
seams=""
[[ "$ROOT" == "/srv/$PROJECT" ]] || seams+=" ${P}_DEPLOY_ROOT=$ROOT"
[[ -z "$HOST" ]] || seams+=" ${P}_DEPLOY_HOST=$HOST"
[[ -z "$seams" ]] || say "paths that are not the host's:$seams"

work="$(mktemp -d "${TMPDIR:-/tmp}/$PROJECT-deploy.XXXXXX")"
keep_units=""
cleanup() {
  if [[ -n "$keep_units" ]] && [[ -n "$(units_touched "$keep_units" 2>/dev/null)" ]]; then
    note "the units this deploy replaced are kept in $work/$keep_units/units, and the ones it added" \
      "are named in $work/$keep_units/units.added: put them back by hand (sudo install -m 644, daemon-reload)"
  else
    # `|| :`: under set -e a failing command in the trap would replace the exit status.
    rm -rf "$work" || :
  fi
}
trap cleanup EXIT

# Ended by a signal (Ctrl-C, or an agent's tool call timing out), say where it
# stopped and what the link names, in the journal too.
stage="before the switch"
current=""
interrupted() {
  trap - INT TERM HUP
  local now
  case "$stage" in
    "before the switch") die "interrupted before the switch; nothing switched" ;;
    "while pruning") note "interrupted while pruning; every target is verified" && exit 0 ;;
  esac
  now="$(readlink "$ROOT/$current" 2>/dev/null)" || now="nothing"
  journal "interrupted on ${build:-?} $stage: $current -> $now, unverified"
  dead "interrupted on ${build:-?} $stage: $current -> $now, unverified. Deploy again, or deploy" \
    "the build it should run: scripts/deploy.sh <sha12> (journalctl -t $TAG -n 20)"
}
trap interrupted INT TERM HUP

# --- hooks -------------------------------------------------------------------
#
# A hook runs in a subshell with errexit on, so a failing command in it is its
# failure. Never as `hook ... || ...` or under an `if`: bash ignores errexit in
# everything such a command runs, the subshell included, so callers read
# HOOK_RC instead.
HOOK_RC=0
hook() { # <hook> [<arg>...]
  set +e
  (
    set -e
    "$@"
  )
  HOOK_RC=$?
  set -e
  return 0
}

# --- which commit ------------------------------------------------------------

git -C "$SRC" fetch --quiet --prune origin
sha="$(git -C "$SRC" rev-parse --verify --quiet "${ref}^{commit}")" || die "cannot resolve $ref"
on_main=0
git -C "$SRC" merge-base --is-ancestor "$sha" origin/main && on_main=1
if ((!on_main)); then
  [[ -n "$(git -C "$SRC" branch -r --contains "$sha" 2>/dev/null)" ]] ||
    die "$ref ($sha) is on no pushed branch; only a pushed commit is deployed"
  [[ "$only_target" == dev ]] ||
    die "$ref ($sha) is not on origin/main; only dev takes a branch commit: --target dev"
fi
build="$(git -C "$SRC" rev-parse --short=12 "$sha")"
release="$ROOT/releases/$build"

# --- CI ----------------------------------------------------------------------
#
# CannObserv/status's gate (status#11), as processor and broker carry it. Asked
# before anything is built, so a refusal changes nothing. Rollbacks too: a kept
# release proves it was built, not that its CI passed; --skip-ci is the escape
# when GitHub cannot answer.

github() { # <path under repos/<repo>/>: GitHub's JSON answer, or a refusal naming its message
  local out rc=0
  if [[ "$CI_AUTH" == gh ]]; then
    # A repo .env's fine-grained PAT gets 403 on Actions: gh's own login instead.
    out="$(env -u GH_TOKEN -u GITHUB_TOKEN gh api -H 'Accept: application/vnd.github+json' \
      "repos/$GITHUB_REPO/$1")" || rc=$?
  else
    # Unauthenticated: a public repo, and 60 requests an hour per address
    # covers a deploy's few. No token, so none to store.
    out="$(curl -sS --fail-with-body --max-time 10 \
      -H 'Accept: application/vnd.github+json' "https://api.github.com/repos/$GITHUB_REPO/$1")" || rc=$?
  fi
  if ((rc == 0)); then
    # A JSON object, or refused: jq reads an empty body as no input at all.
    jq -e 'type == "object"' <<<"$out" >/dev/null 2>&1 ||
      die "GitHub's answer about $build's CI is not the JSON expected; nothing was built." \
        "Deploy again later, or pass --skip-ci."
    printf '%s\n' "$out"
    return
  fi
  out="$(jq -r '.message // empty' <<<"$out" 2>/dev/null)" || out=""
  die "GitHub did not answer about $build's CI.${out:+ GitHub says: $out}" \
    "Nothing was built; deploy again later, or pass --skip-ci."
}

# The run that decides: the newest push run of CI_WORKFLOW for exactly this
# commit, on main for a main commit. A re-run counts: a run reports its latest
# attempt.
push_run() {
  jq -c --arg sha "$sha" --argjson main "$on_main" '[.workflow_runs[]
    | select(.head_sha == $sha and .event == "push" and ($main == 0 or .head_branch == "main"))]
    | max_by(.created_at) // empty' ||
    die "GitHub's answer about $build's CI runs is not the JSON expected; nothing was built." \
      "Deploy again later, or pass --skip-ci."
}

# Waits for the run, bounded. Two main commits never get one, so they are
# refused at once: one behind origin/main's tip (GitHub runs CI on the newest
# commit of each push only), and one a workflow pushed (GitHub never runs CI
# for a push made with GITHUB_TOKEN).
finished_run() {
  local deadline=$((SECONDS + CI_WAIT_SECONDS)) tip run state url left committer query
  tip="$(git -C "$SRC" rev-parse origin/main)"
  committer="$(git -C "$SRC" log -1 --format=%cn "$sha")"
  query="actions/workflows/$CI_WORKFLOW/runs?head_sha=$sha&event=push&per_page=100"
  ((!on_main)) || query+="&branch=main"
  while :; do
    run="$(github "$query" | push_run)" || exit 1
    left=$((deadline - SECONDS))
    if [[ -z "$run" && "$committer" == "github-actions[bot]" ]]; then
      die "no CI run for $build, pushed by a workflow ($committer): GitHub never runs CI for a" \
        "push made with GITHUB_TOKEN. Deploy the commit under it," \
        "scripts/deploy.sh $(git -C "$SRC" rev-parse --short=12 "$sha^"), or pass --skip-ci." \
        "Nothing was built."
    elif [[ -z "$run" && "$on_main" == 1 && "$sha" != "$tip" ]]; then
      die "no CI run for $build as a push to main. GitHub runs CI on the newest commit of each push" \
        "only: deploy that one, or pass --skip-ci. Pushed in the last minute, with another push" \
        "after it? Its run may not be listed yet: deploy again shortly. Nothing was built."
    elif [[ -z "$run" ]]; then
      state="not queued yet" url=""
      ((left > 0)) ||
        die "no CI run for $build after ${CI_WAIT_SECONDS}s ([skip ci]?). Pass --skip-ci to deploy it" \
          "anyway. Nothing was built."
    else
      state="$(jq -r .status <<<"$run")"
      url="$(jq -r .html_url <<<"$run")"
      [[ "$state" == completed ]] && {
        printf '%s\n' "$run"
        return
      }
      ((left > 0)) ||
        die "CI for $build is still $state after ${CI_WAIT_SECONDS}s. Nothing was built; deploy again" \
          "when it finishes. Run: $url"
    fi
    note "waiting for CI on $build ($state)${url:+: $url}"
    sleep $((left < CI_POLL_SECONDS ? left : CI_POLL_SECONDS))
  done
}

# Success only, from the run itself, every job it lists, and at least CI_JOBS.
# A skipped job leaves the run "success", so the jobs are read too. CI_JOBS is
# only the floor: it comes from this checkout, which may be older than the
# workflow. It goes to jq as a JSON array: a job name may have spaces.
ci_gate() {
  local run url conclusion jobs problems required remedy="fix it on main"
  run="$(finished_run)" || exit 1
  url="$(jq -r .html_url <<<"$run")"
  conclusion="$(jq -r '.conclusion // "nothing"' <<<"$run")"
  jobs="$(github "actions/runs/$(jq -r .id <<<"$run")/jobs?per_page=100")" || exit 1
  required="$(jq -cn '$ARGS.positional' --args "${CI_JOBS[@]}")"
  problems="$(jq -r --argjson required "$required" '[
      (.jobs[] | select(.conclusion != "success") | "\(.name) (\(.conclusion // .status))"),
      ($required[] as $name | select(any(.jobs[]; .name == $name) | not)
        | "\($name) (not in the run)")
    ] | join(", ")' <<<"$jobs")" ||
    die "GitHub's answer about $build's CI jobs is not the JSON expected; nothing was built." \
      "Deploy again later, or pass --skip-ci."
  [[ "$conclusion" == success ]] || problems="run concluded $conclusion${problems:+; $problems}"
  # Cancelled is not a verdict, and has nothing to fix.
  [[ "$conclusion" != cancelled ]] || remedy="re-run it from its page (a re-run counts), or deploy a newer commit"
  [[ -z "$problems" ]] || die "CI did not pass for $build: $problems. Nothing was built; $remedy. Run: $url"
  say "CI passed for $build: $url"
}

if ((skip_ci)); then
  say "CI not checked for $build (--skip-ci)"
elif [[ "$CI" == none ]]; then
  note "CI=none in $HOOKS: this repo's gate is local, so CI is not asked about $build"
else
  ci_gate
fi

# --- the release -------------------------------------------------------------

# What the release's venv imports and says it is, run from the release as the
# deploy user. -I: no PYTHONPATH, user site or cwd on sys.path, so the
# project comes through the release's own install. -B: bytecode is the
# build's to write, never a probe's.
probe_code="$(
  if ((${#IMPORT_MODULES[@]})); then
    printf 'import %s; ' "$(
      IFS=,
      echo "${IMPORT_MODULES[*]}"
    )"
  fi
  if [[ -n "$REVISION_PROBE" ]]; then
    printf '%s' "$REVISION_PROBE"
  else
    printf '%s' 'import pathlib; p = pathlib.Path("REVISION"); print(p.read_text().strip() if p.exists() else "dev")'
  fi
)"
reports() {
  (cd "$release" && .venv/bin/python -I -B -c "$probe_code" 2>"$work/probe.err")
}
probe_error() { tr '\n' ' ' <"$work/probe.err" 2>/dev/null | sed 's/ *$//'; }

# A lock that resolves from ./.wheelhouse: find-links locks by filename with no
# hash, and this core syncs no wheelhouse. Journaled: before the switch a plain
# die is stderr only.
refuse_a_wheelhouse_lock() {
  [[ -f "$release/uv.lock" ]] || return 0
  grep -Eq '^source = \{ registry = "(\./)?\.wheelhouse" \}$' "$release/uv.lock" || return 0
  journal "refused $build: its uv.lock resolves from ./.wheelhouse, which this core does not build; nothing switched"
  die "$build's uv.lock resolves from ./.wheelhouse, which this core does not build. Move the repo" \
    "to the co-pypi index first, or roll back to a kept release; nothing switched"
}

# Each step says why it stopped. The release, left without REVISION, is
# rebuilt next time.
build_release() {
  local home out dir artifact treeish="$sha"
  [[ "$SERVICE_DIR" == . ]] || treeish="$sha:${SERVICE_DIR%/}"
  if [[ -e "$release" ]]; then
    sudo -n rm -rf "$release" || die "cannot remove the unfinished releases/$build; nothing switched"
  fi
  note "building $build"
  [[ -d "$ROOT/releases" ]] || sudo -n install -d -o root -g root -m 755 "$ROOT/releases" ||
    die "cannot make $ROOT/releases; nothing switched"
  # Built where it will run, by the deploy user: a uv venv embeds its absolute path.
  sudo -n install -d -m 755 -o "$(id -un)" -g "$(id -gn)" "$release" ||
    die "cannot make releases/$build for $(id -un) to build in; nothing switched"
  # A subtree's own root is the release's root: everything after this reads
  # from the release, so SERVICE_DIR appears here alone (provisioner).
  git -C "$SRC" archive "$treeish" | tar -x -C "$release" ||
    die "git archive failed for $build${SERVICE_DIR:+ ($SERVICE_DIR)}; nothing switched"
  refuse_a_wheelhouse_lock
  # Copied, never hardlinked from the uv cache: a hardlink is the cache's inode
  # and every dev venv's, so the chown below would reach them (status#14). The
  # venv is the release's own .venv, whatever the caller's shell names. Through
  # UV_WRAPPER when the repo names one: it hands a private index's credential to
  # this uv alone, and --locked holds every file to the lock's sha256.
  (cd "$release" && env -u UV_PROJECT_ENVIRONMENT -u VIRTUAL_ENV UV_PYTHON_DOWNLOADS=never \
    "${wrap[@]}" uv sync --locked --no-dev --compile-bytecode --link-mode copy --python "$PYTHON" --quiet) ||
    die "uv sync failed for $build; nothing switched"
  # A sandbox that hides /home (ProtectHome=) cannot start a uv-managed Python.
  home="$(sed -n 's/^home *= *//p' "$release/.venv/pyvenv.cfg" 2>/dev/null)" || home=""
  [[ -n "$home" && "$home" != /home/* ]] ||
    die "$build's venv runs ${home:-an unknown interpreter}, not one outside /home; nothing switched"
  # --compile-bytecode reaches site-packages alone; the project's own sources are compiled here.
  for dir in "${SOURCE_DIRS[@]}"; do
    [[ -d "$release/$dir" ]] || continue
    (cd "$release" && .venv/bin/python -m compileall -q "$dir" >/dev/null) ||
      die "compileall failed for $build's $dir; nothing switched"
  done
  cd "$release"
  hook build_extra
  cd "$SRC"
  ((HOOK_RC == 0)) || die "build_extra failed for $build (exit $HOOK_RC); nothing switched"
  for artifact in "${REQUIRED_ARTIFACTS[@]}"; do
    [[ -e "$release/$artifact" ]] ||
      die "$build has no $artifact, which REQUIRED_ARTIFACTS says a release must; nothing switched"
  done
  reports >/dev/null || die "$build's venv does not import ($(probe_error)); nothing switched"
  # Readable by every user under any umask, writable by none: the service user
  # is "other" to the tree.
  chmod -R a-w,a+rX "$release" || die "cannot make $build read-only; nothing switched"
  sudo -n chown -R root:root "$release" || die "cannot hand $build to root; nothing switched"
  # REVISION last, by root: a release without one is an interrupted build.
  { echo "$build" | sudo -n tee "$release/REVISION" >/dev/null && sudo -n chmod 444 "$release/REVISION"; } ||
    die "cannot write $build's REVISION; nothing switched"
  # From the release, as the deploy user, after root wrote it: the path the
  # app reads and the 444 read, in one line. A miss takes REVISION back off.
  out="$(reports)" || out=""
  if [[ "$out" != "$build" ]]; then
    sudo -n rm -f "$release/REVISION" || :
    die "$build reports ${out:-nothing} from the release, not $build ($(probe_error)); nothing switched"
  fi
  cd "$release"
  hook post_build_check
  cd "$SRC"
  if ((HOOK_RC != 0)); then
    sudo -n rm -f "$release/REVISION" || :
    die "post_build_check failed for $build (exit $HOOK_RC); nothing switched"
  fi
}

# The build a target's link names, by its last component: a link made by hand
# during a recovery may be absolute.
release_of() { # <target>
  local link
  link="$(readlink "$ROOT/$1" 2>/dev/null)" || return 0
  basename "$link"
}

linked_anywhere() { [[ "$(release_of live)" == "$build" || "$(release_of dev)" == "$build" ]]; }

# Why this release cannot be reused as it stands; nothing when it can.
unusable() {
  local out
  if [[ ! -e "$release" ]]; then
    echo "not built"
  elif [[ ! -f "$release/REVISION" ]]; then
    echo "an interrupted build"
  elif [[ "$(stat -c %u -- "$release")" != 0 ]]; then
    echo "not root's"
  elif ! out="$(reports)"; then
    echo "a venv that no longer runs ($(probe_error))"
  elif [[ "$out" != "$build" ]]; then
    echo "a release that reports $out"
  fi
}

# A release a link names is never rebuilt in place, whatever is wrong with it:
# that pulls the code out from under its units. Unless it is gone altogether.
why="$(unusable)"
if [[ -z "$why" ]]; then
  note "reusing release $build"
else
  [[ "$why" == "not built" ]] || ! linked_anywhere ||
    die "release $build is $why, and a target runs it. Deploy another build first; this one is then rebuilt."
  [[ "$why" == "not built" ]] || note "release $build is $why; rebuilding"
  build_release
fi
# Prune by last build or deploy, not first build.
sudo -n touch "$release" || note "cannot touch $release; the prune may take it sooner"

if ((build_only)); then
  say "built $build (--build-only); live stays on $(readlink "$ROOT/live" 2>/dev/null || echo nothing)"
  note "nothing switched, installed or pruned. It runs from $release; a deploy of $build reuses it"
  exit 0
fi

# --- units -------------------------------------------------------------------

is_unit_name() { # <name>: one of this project's units
  case "$1" in
    "$PROJECT".service | "$PROJECT".timer | "$PROJECT"-*.service | "$PROJECT"-*.timer | "$PROJECT"@*.service) return 0 ;;
  esac
  return 1
}

units_of() { # the release's units, by name
  local path name
  for path in "$release/$UNITS_DIR"/*; do
    name="$(basename "$path")"
    [[ -f "$path" ]] && is_unit_name "$name" && echo "$name"
  done
  return 0
}

workdir_of() { # <unit file>: its last WorkingDirectory=, without systemd's "-"
  local wd
  wd="$(sed -n 's/^WorkingDirectory= *//p' "$1" 2>/dev/null | tail -n 1)"
  printf '%s\n' "${wd#-}"
}

# A unit's target is its WorkingDirectory=; a timer's is its service's; a unit
# under no target (no WorkingDirectory= under the root) goes with the last.
target_of() { # <directory> <unit name>
  local file="$1/$2" wd
  [[ "$2" != *.timer ]] || file="$1/${2%.timer}.service"
  wd="$(workdir_of "$file")"
  case "$wd" in
    "$ROOT"/live) echo live ;;
    "$ROOT"/dev) echo dev ;;
    *) echo none ;;
  esac
}

targets=()
for t in dev live; do
  while read -r name; do
    if [[ "$(target_of "$release/$UNITS_DIR" "$name")" == "$t" ]]; then
      targets+=("$t")
      break
    fi
  done < <(units_of)
done
((${#targets[@]})) || die "no unit in $build's $UNITS_DIR/ runs $ROOT/live or $ROOT/dev; nothing switched"
if [[ -n "$only_target" ]]; then
  [[ " ${targets[*]} " == *" $only_target "* ]] ||
    die "no unit in $build's $UNITS_DIR/ runs $ROOT/$only_target; nothing switched"
  targets=("$only_target")
fi
last_target="${targets[-1]}"

units_for() { # <target>: the release's units that go with it
  local name t
  while read -r name; do
    t="$(target_of "$release/$UNITS_DIR" "$name")"
    [[ "$t" == "$1" || ("$t" == none && "$1" == "$last_target") ]] && echo "$name"
  done < <(units_of)
  return 0
}

enabled_when_verified() { # <unit>: one of ENABLE_NEW
  local name
  for name in "${ENABLE_NEW[@]}"; do [[ "$name" == "$1" ]] && return 0; done
  return 1
}

# Installs the target's units that differ from their installed copies, after
# keeping each copy aside for restore_units. One daemon-reload, a changed timer
# try-restarted so it re-arms, and each installed service checked as systemd
# loaded it (observo CR 13). A new unit is installed, never enabled here:
# enabling is ENABLE_NEW's, once verified. Units the release lacks stay.
# Called as `install_units <t> || ...`, so set -e is off in here: every step
# that can fail says so itself.
install_units() { # <target>
  local t="$1" name unit changed=() added=() timers=() loaded wd list
  { mkdir -p "$work/$t/units" && : >"$work/$t/units.added"; } || {
    note "cannot keep the installed units aside in $work/$t"
    return 1
  }
  while read -r name; do
    unit="$UNIT_DIR/$name"
    cmp -s "$release/$UNITS_DIR/$name" "$unit" && continue
    if [[ -e "$unit" ]]; then
      cp "$unit" "$work/$t/units/$name" || {
        note "cannot keep $unit aside; not installing it"
        return 1
      }
      changed+=("$name")
      [[ "$name" != *.timer ]] || timers+=("$name")
    else
      echo "$name" >>"$work/$t/units.added"
      added+=("$name")
    fi
    sudo -n install -m 644 "$release/$UNITS_DIR/$name" "$unit" || {
      note "installing $name in $UNIT_DIR failed"
      return 1
    }
  done < <(units_for "$t")
  ((${#changed[@]} + ${#added[@]})) || return 0
  sudo -n systemctl daemon-reload || {
    note "systemctl daemon-reload failed"
    return 1
  }
  for name in "${changed[@]}" "${added[@]}"; do
    [[ "$name" == *.service && "$name" != *@.service ]] || continue
    loaded="$(systemctl show -p NeedDaemonReload --value "$name" 2>/dev/null)" || loaded=""
    [[ "$loaded" != yes ]] || {
      note "$name still needs a daemon-reload after one: systemctl status $name"
      return 1
    }
    wd="$(workdir_of "$UNIT_DIR/$name")"
    [[ -z "$wd" || "$(systemctl show -p WorkingDirectory --value "$name" 2>/dev/null)" == "$wd" ]] || {
      note "$name is loaded with another WorkingDirectory= than its file's $wd: systemctl cat $name"
      return 1
    }
  done
  # A timer that will not re-arm is a schedule that no longer runs: fail.
  for name in "${timers[@]}"; do
    sudo -n systemctl try-restart "$name" || {
      note "systemctl try-restart $name failed: systemctl status $name"
      return 1
    }
  done
  list="${changed[*]}"
  for name in "${added[@]}"; do list+=" $name (new)"; done
  say "units installed from $build for $t: ${list# }"
  for name in "${added[@]}"; do
    if enabled_when_verified "$name"; then
      note "$name is new here: enabled once this deploy verifies"
    elif ! enabled_when_verified "${name%.service}.timer"; then
      note "$name is new here and not enabled. If it should run: sudo systemctl enable --now $name"
    fi
  done
}

units_touched() { # <target>: the unit files install_units replaced or added, or tried to
  local path
  for path in "$work/$1/units"/*; do
    [[ -f "$path" ]] && basename "$path"
  done
  [[ ! -f "$work/$1/units.added" ]] || cat "$work/$1/units.added"
}

# Switch back, for units: the copies install_units replaced go back, and what it
# added is removed. A failure is a note: the rollback still proves the old build.
restore_units() { # <target>
  local path name timers=() any=0
  for path in "$work/$1/units"/*; do
    [[ -f "$path" ]] || continue
    name="$(basename "$path")"
    sudo -n install -m 644 "$path" "$UNIT_DIR/$name" || note "restoring $name failed: $path"
    [[ "$name" != *.timer ]] || timers+=("$name")
    any=1
  done
  if [[ -f "$work/$1/units.added" ]]; then
    while read -r name; do
      sudo -n rm -f "$UNIT_DIR/$name" || note "removing $UNIT_DIR/$name failed"
      any=1
    done <"$work/$1/units.added"
  fi
  ((any)) || return 0
  sudo -n systemctl daemon-reload || note "systemctl daemon-reload failed"
  for name in "${timers[@]}"; do
    sudo -n systemctl try-restart "$name" || note "systemctl try-restart $name failed"
  done
  journal "units restored for $1"
}

# --- switching ---------------------------------------------------------------

# What a directory reports as its build: REVISION's contents, dev when there is
# none, unknown when it is empty. A relative link resolves from the root.
served_build() { # <dir or link target>
  local dir rev
  dir="$(cd "$ROOT" 2>/dev/null && cd -P "$1" 2>/dev/null && pwd)" || {
    echo dev
    return 0
  }
  [[ -e "$dir/REVISION" ]] || {
    echo dev
    return 0
  }
  rev="$(tr -d '[:space:]' <"$dir/REVISION" 2>/dev/null)" || rev=""
  echo "${rev:-unknown}"
}

swap() { # <link> <target>: rename(2) over the old link, so there is never no link
  sudo -n ln -sfn "$2" "$1.new" && sudo -n mv -Tf "$1.new" "$1"
}

# --- verification ------------------------------------------------------------
#
# The helpers below are the verify hook's vocabulary; each returns 0 when the
# unit proved <want>, and 1, with a note, when it did not.

unit_type() { # <installed service>: Type=, systemd's default when unset
  local type
  type="$(sed -n 's/^Type= *//p' "$UNIT_DIR/$1" 2>/dev/null | tail -n 1)"
  echo "${type:-simple}"
}

# The build a service must report: what its installed unit's WorkingDirectory= holds.
expected_of() { served_build "$(workdir_of "$UNIT_DIR/$1")"; }

# The unit's main process is a new one, and runs from the release <want> names:
# the core's own check for a restarted unit its hook has none for.
verify_started_on() { # <service> <want>
  local svc="$1" want="$2" deadline=$((SECONDS + VERIFY_SECONDS)) pid state cwd old
  old="$(cat "$work/pid.$svc" 2>/dev/null)" || old=""
  while :; do
    pid="$(systemctl show -p MainPID --value "$svc" 2>/dev/null)" || pid=""
    state="$(systemctl show -p ActiveState --value "$svc" 2>/dev/null)" || state=""
    if [[ "$state" == active && -n "$pid" && "$pid" != 0 && "$pid" != "$old" ]]; then
      # The service user's /proc is not the deploy user's to read.
      cwd="$(sudo -n readlink "$PROC/$pid/cwd" 2>/dev/null)" || cwd=""
      if [[ -n "$cwd" && "$(served_build "$cwd")" == "$want" ]]; then
        say "$svc runs $want (pid $pid)"
        return 0
      fi
    fi
    ((SECONDS < deadline)) || break
    sleep "$POLL_SECONDS"
  done
  note "$svc did not come up on $want within ${VERIFY_SECONDS}s (state ${state:-unknown}, pid ${pid:-none}," \
    "cwd ${cwd:-unread}): journalctl -u $svc -n 50"
  return 1
}

# An HTTP endpoint answers, and <jq> holds of its JSON with $want bound:
# default `.revision == $want`.
verify_http_health() { # <url> <want> [<jq>]
  local url="$1" want="$2" expr="${3:-.revision == \$want}" deadline=$((SECONDS + VERIFY_SECONDS)) body=""
  while :; do
    if body="$(curl -sS --max-time 10 "$url" 2>/dev/null)" &&
      jq -e --arg want "$want" "$expr" <<<"$body" >/dev/null 2>&1; then
      say "$url answers on $want"
      return 0
    fi
    ((SECONDS < deadline)) || break
    sleep "$POLL_SECONDS"
  done
  note "$url did not answer $expr for $want within ${VERIFY_SECONDS}s; it said: ${body:-nothing}"
  return 1
}

# The next natural tick of a timer's service, never a forced one (broker's
# two-tick rule): the invocation systemd lists at the first poll is the
# baseline. The next one must exit 0 and, given <message>, log a JSON line with
# that message whose .revision is <want>.
verify_next_tick() { # <service> <want> [<message>]
  local svc="$1" want="$2" message="${3:-}" deadline=$((SECONDS + TICK_SECONDS)) base="" first=1
  local key value id state result status rev
  while :; do
    id="" state="" result="" status=""
    while IFS='=' read -r key value; do
      case "$key" in
        InvocationID) id="$value" ;;
        ActiveState) state="$value" ;;
        Result) result="$value" ;;
        ExecMainStatus) status="$value" ;;
      esac
    done < <(systemctl show -p InvocationID -p ActiveState -p Result -p ExecMainStatus "$svc" 2>/dev/null)
    if ((first)); then
      base="$id" first=0
    elif [[ -n "$id" && "$id" != "$base" && "$state" != activating ]]; then
      break
    fi
    ((SECONDS < deadline)) || {
      note "no tick of $svc finished within ${TICK_SECONDS}s, and the deploy never forces one:" \
        "systemctl list-timers ${svc%.service}.timer"
      return 1
    }
    sleep "$POLL_SECONDS"
  done
  [[ "$result" == success && "$status" == 0 ]] || {
    note "$svc's tick $id failed on $want (Result=$result, status $status): journalctl _SYSTEMD_INVOCATION_ID=$id"
    return 1
  }
  if [[ -n "$message" ]]; then
    rev=""
    # journald can trail the unit's exit by a moment.
    for _ in 1 2 3; do
      rev="$(journalctl "_SYSTEMD_INVOCATION_ID=$id" -o cat --no-pager 2>/dev/null |
        jq -rR --arg m "$message" 'fromjson? | select(.message == $m) | .revision' | tail -n 1)" || rev=""
      [[ -z "$rev" ]] || break
      sleep "$POLL_SECONDS"
    done
    [[ "$rev" == "$want" ]] || {
      note "$svc's tick $id reported revision ${rev:-none}, not $want"
      return 1
    }
  fi
  say "$svc's tick $id on $want: exited 0"
}

# One forced run of a oneshot, after any run already going: starting a oneshot
# mid-run joins that run, which began on the old release (status CR 2).
# reset-failed, so a start limit a failing build reached cannot refuse the run
# that proves the fix. Given <file> and <jq>, the run must leave a JSON file
# that <jq> holds of, with $want bound.
verify_forced_run() { # <service> <want> [<file> <jq>]
  local svc="$1" want="$2" file="${3:-}" expr="${4:-}" deadline=$((SECONDS + RUN_WAIT_SECONDS))
  sudo -n systemctl reset-failed "$svc" || true
  while [[ "$(systemctl show -p ActiveState --value "$svc" 2>/dev/null)" == activating ]]; do
    ((SECONDS < deadline)) || {
      note "$svc has been running for ${RUN_WAIT_SECONDS}s"
      return 1
    }
    sleep "$POLL_SECONDS"
  done
  sudo -n systemctl start "$svc" || {
    note "the $svc run failed on $want: journalctl -u ${svc%.service} -n 50"
    return 1
  }
  if [[ -n "$file" ]]; then
    jq -e --arg want "$want" "$expr" "$file" >/dev/null 2>&1 || {
      note "the $svc run on $want left $file without $expr: $(head -c 300 "$file" 2>/dev/null)"
      return 1
    }
  fi
  say "the $svc run on $want: done"
}

# A timer that is not active gives no tick: refuse before the switch, from
# pre_switch_check, rather than wait TICK_SECONDS for one and switch back.
require_active_timer() { # <timer>
  systemctl is-active --quiet "$1" && return 0
  journal "refused $build: $1 is not active, so the tick this deploy is verified by never comes"
  note "$1 is not active, so the tick this deploy is verified by never comes; nothing switched." \
    "Enable it, then deploy again: sudo systemctl enable --now $1"
  return 1
}

# The services this deploy changed for a target: each whose unit or timer it
# installed, and, when the link moved, each that runs the target.
changed_services() { # <target> <moved>
  local name path
  {
    while read -r name; do
      [[ -n "$name" && "$name" != *@.service ]] && echo "${name%.*}.service"
    done < <(units_touched "$1")
    if (($2)); then
      for path in "$UNIT_DIR/$PROJECT".service "$UNIT_DIR/$PROJECT"-*.service; do
        [[ -f "$path" && "$path" != *@.service ]] || continue
        [[ "$(workdir_of "$path")" == "$ROOT/$1" ]] && basename "$path"
      done
    fi
  } | sort -u
}

# Whether a changed service is meant to run now: a long-running one enabled or
# active; a oneshot whose timer is active, or that has no timer. One that is
# not is installed, named, and neither restarted nor verified (provisioner).
meant_to_run() { # <service>
  local timer="${1%.service}.timer"
  if [[ "$(unit_type "$1")" == oneshot ]]; then
    [[ ! -f "$UNIT_DIR/$timer" ]] || systemctl is-active --quiet "$timer"
  else
    systemctl is-enabled --quiet "$1" 2>/dev/null || systemctl is-active --quiet "$1"
  fi
}

# Restarts each long-running service of the target that is meant to run, and
# keeps its old main PID to tell the new process from it. The drain is the
# unit's own TimeoutStopSec=. Sets RESTART_OK.
RESTART_OK=1
restart_target() { # <target> <moved>
  local svc pid
  RESTART_OK=1
  while read -r svc; do
    [[ -n "$svc" && -f "$UNIT_DIR/$svc" ]] || continue
    [[ "$(unit_type "$svc")" != oneshot ]] || continue
    meant_to_run "$svc" || continue
    pid="$(systemctl show -p MainPID --value "$svc" 2>/dev/null)" || pid=""
    echo "$pid" >"$work/pid.$svc" || note "cannot keep $svc's old pid; the new one is told apart by its release alone"
    sudo -n systemctl reset-failed "$svc" || true
    if ! sudo -n systemctl restart "$svc"; then
      note "systemctl restart $svc failed: journalctl -u $svc -n 50"
      RESTART_OK=0
      return 0
    fi
    note "restarted $svc"
  done < <(changed_services "$1" "$2")
}

# Each changed service against what its own unit runs. Sets VERIFY_OK.
VERIFY_OK=1
verify_target() { # <target> <moved>
  local svc want any=0 restarted
  VERIFY_OK=1
  while read -r svc; do
    [[ -n "$svc" && -f "$UNIT_DIR/$svc" ]] || continue
    any=1
    if ! meant_to_run "$svc"; then
      note "$svc is installed but not enabled (or its timer is not active): not verified." \
        "Enabling it is a decision: sudo systemctl enable --now $svc"
      continue
    fi
    want="$(expected_of "$svc")"
    restarted=0
    [[ "$(unit_type "$svc")" == oneshot ]] || restarted=1
    hook verify "$svc" "$want"
    case "$HOOK_RC" in
      0) ;;
      2)
        if ((restarted)); then
          set +e
          (verify_started_on "$svc" "$want")
          HOOK_RC=$?
          set -e
          ((HOOK_RC == 0)) || {
            VERIFY_OK=0
            return 0
          }
        else
          note "$svc changed but is not verified: the verify hook has no check for it"
        fi
        ;;
      *)
        note "$svc did not verify on $want (verify exited $HOOK_RC)"
        VERIFY_OK=0
        return 0
        ;;
    esac
  done < <(changed_services "$1" "$2")
  ((any)) || say "$1: nothing to verify: no unit changed, and none runs $ROOT/$1 from a link that moved"
}

# --- before the switch -------------------------------------------------------

# A User= that does not exist fails every run of its unit. Not a DynamicUser=
# one (any of systemd's true spellings), nor one with no User=.
check_users() {
  local name path user dynamic unmade=""
  while read -r name; do
    [[ "$name" == *.service ]] || continue
    path="$release/$UNITS_DIR/$name"
    dynamic="$(sed -n 's/^DynamicUser= *//p' "$path" | tail -n 1)"
    [[ "${dynamic,,}" =~ ^(1|yes|y|true|t|on)$ ]] && continue
    user="$(sed -n 's/^User= *//p' "$path" | tail -n 1)"
    [[ -z "$user" ]] || getent passwd "$user" >/dev/null || unmade+=", $name (User=$user)"
  done < <(units_of)
  [[ -n "$unmade" ]] || return 0
  journal "refused $build: no such user for ${unmade#, }"
  die "no such user for ${unmade#, }: every run of its unit would fail, the verify's too;" \
    "nothing switched. Make it first (DEPLOYMENT.md), then deploy again."
}

# --- after a verified deploy -------------------------------------------------

# Each ENABLE_NEW unit this deploy added is enabled once the deploy verifies.
# One installed before is never enabled again: an operator's disable sticks.
# A failure is a note.
enable_new_units() { # <target>
  local name
  [[ -f "$work/$1/units.added" ]] || return 0
  while read -r name; do
    enabled_when_verified "$name" || continue
    if sudo -n systemctl enable --now "$name"; then
      say "$name enabled; its first run: journalctl -u ${name%.timer} -n 5"
    else
      note "systemctl enable --now $name failed; enable it by hand"
    fi
  done <"$work/$1/units.added"
}

# This project's installed units that the release no longer has. A deploy never
# removes one; retiring a unit is the operator's.
note_units_not_in_release() {
  local path name
  for path in "$UNIT_DIR"/*; do
    name="$(basename "$path")"
    if [[ ! -f "$path" ]] || ! is_unit_name "$name"; then continue; fi
    [[ -f "$release/$UNITS_DIR/$name" ]] && continue
    note "$name is installed but not in $build's $UNITS_DIR/; it keeps running. If it should not:" \
      "sudo systemctl disable --now $name"
  done
  return 0
}

# Host configs change rarely, and installing one is a reload or a restart: by
# hand, in a window. A difference is a note, never an install, never a failure.
compare_host_configs() { # <previous link of the last target>
  local entry rel dest previous_dir=""
  for entry in "${HOST_CONFIGS[@]}"; do
    rel="${entry%%=*}" dest="$HOST${entry#*=}"
    [[ -f "$release/$UNITS_DIR/$rel" ]] || continue
    if [[ ! -e "$dest" ]]; then
      note "host config $UNITS_DIR/$rel is not installed at $dest; install it by hand (DEPLOYMENT.md)"
    elif ! cmp -s "$release/$UNITS_DIR/$rel" "$dest"; then
      note "host config $UNITS_DIR/$rel differs from $dest; install it by hand (DEPLOYMENT.md)"
    fi
  done
  [[ -z "$1" ]] || previous_dir="$(cd "$ROOT" 2>/dev/null && cd -P "$1" 2>/dev/null && pwd)" || previous_dir=""
  # Installed derived (rendered, minted), so compared with the release the
  # target ran before instead.
  for rel in "${DERIVED_CONFIGS[@]}"; do
    [[ -f "$release/$UNITS_DIR/$rel" ]] || continue
    if [[ -z "$previous_dir" || ! -f "$previous_dir/$UNITS_DIR/$rel" ]]; then
      note "$UNITS_DIR/$rel is installed derived, so this deploy compares it with nothing"
    elif ! cmp -s "$previous_dir/$UNITS_DIR/$rel" "$release/$UNITS_DIR/$rel"; then
      note "$UNITS_DIR/$rel changed since $(basename "$previous_dir"). A deploy never installs it: by hand (DEPLOYMENT.md)"
    fi
  done
}

# --- deploy, target by target ------------------------------------------------

check_users

declare -A previous_link previous
for t in "${targets[@]}"; do
  previous_link[$t]="$(readlink "$ROOT/$t" 2>/dev/null || true)"
  previous[$t]="$(release_of "$t")"
done

for t in "${targets[@]}"; do
  current="$t"
  stage="before the switch"
  hook pre_switch_check "$t"
  if ((HOOK_RC != 0)); then
    journal "refused $build for $t: pre_switch_check exited $HOOK_RC"
    die "pre_switch_check refused $build for $t (exit $HOOK_RC); nothing switched for $t"
  fi
  hook migrate "$t"
  if ((HOOK_RC != 0)); then
    journal "refused $build for $t: migrate exited $HOOK_RC"
    die "migrate failed for $t on $build (exit $HOOK_RC); nothing switched for $t"
  fi

  link="$ROOT/$t"
  moved=1
  # --verify: every unit of the target restarted and proved, as if the link
  # moved; how a cutover proves what --no-restart switched.
  [[ -n "${previous_link[$t]}" && "${previous[$t]}" == "$build" ]] && ((!force_verify)) && moved=0
  stage="while switching"
  swap "$link" "releases/$build" || die "cannot switch $t to $build (sudo ln, mv); nothing switched"
  stage="after the switch, installing units and verifying"
  journal "$t -> $build (was ${previous_link[$t]:-nothing})"
  units_ok=1
  keep_units="$t"
  install_units "$t" || units_ok=0

  if ((no_restart)); then
    keep_units=""
    if ((units_ok)); then
      say "$t is on $build (--no-restart): nothing restarted or verified. Enable its units, then: scripts/deploy.sh --verify $build"
      continue
    fi
    note "installing $t's units failed (--no-restart); switching back"
    VERIFY_OK=0
  else
    VERIFY_OK=0
    if ((units_ok)); then
      restart_target "$t" "$moved"
      if ((RESTART_OK)); then
        verify_target "$t" "$moved"
      fi
    fi
  fi

  if ((VERIFY_OK)); then
    keep_units=""
    say "$t is on $build"
    continue
  fi

  stage="while switching back"
  if [[ -z "${previous_link[$t]}" ]]; then
    # A first deploy: there was no link, so restoring it exactly is removing it.
    sudo -n rm -f "$link" || note "removing $link failed"
    back="there was no previous release, so removed $t and put back the units it replaced"
  elif [[ "${previous[$t]}" == "$build" ]]; then
    # The link never moved, so the units are all that changed. None replaced
    # is --verify proving the build already live: nothing to switch back to.
    if [[ -z "$(units_touched "$t")" ]]; then
      journal "$t failed --verify on $build, which it already ran; nothing to switch back to"
      dead "$t failed on $build, which it was already running, and there is nothing to switch back to:" \
        "it is NOT answering. Deploy the build it should run: scripts/deploy.sh <sha12>"
    fi
    back="put back the units it replaced, on $build"
  else
    back="switched $t back to $(served_build "${previous_link[$t]}")"
    if ! swap "$link" "${previous_link[$t]}"; then
      journal "$t failed on $build; switching it back to ${previous_link[$t]} failed"
      dead "$t failed on $build, and switching it back to ${previous_link[$t]} failed (sudo ln, mv):" \
        "$t still runs $build. sudo ln -sfn ${previous_link[$t]} $link.new && sudo mv -Tf $link.new $link"
    fi
  fi
  restore_units "$t"
  keep_units=""
  if ((no_restart)); then
    journal "$t failed on $build (--no-restart); $back"
    die "$t failed on $build; $back. Nothing was restarted (--no-restart)"
  fi
  stage="after switching back, verifying the old build"
  # Always proved, a first deploy too: the restored units may run the checkout
  # and answer (a retrofit's cutover), and one still on the removed link fails
  # to start, so "not answering" is found, never assumed.
  VERIFY_OK=0
  restart_target "$t" 1
  if ((RESTART_OK)); then
    verify_target "$t" 1
  fi
  if ((VERIFY_OK)); then
    journal "$t rolled back after $build failed: $back"
    die "$t failed on $build; $back, which is answering"
  fi
  journal "$t failed on $build; $back, which is NOT answering"
  dead "$t failed on $build; $back, which is NOT answering: journalctl -t $TAG -n 20"
done

stage="while pruning"
if ((!no_restart)); then
  for t in "${targets[@]}"; do
    enable_new_units "$t"
    hook post_verify "$t"
    ((HOOK_RC == 0)) || note "post_verify for $t exited $HOOK_RC; $t stays on $build (a note, never a rollback)"
  done
fi
note_units_not_in_release
compare_host_configs "${previous_link[$last_target]}"

# --- prune -------------------------------------------------------------------
#
# KEEP releases besides the ones the links name: they are left out of the count,
# never only out of the deletion. Newest first by last build or deploy. The
# release each target replaced is kept anyway: it is what a rollback deploys.
spare=" $(release_of live) $(release_of dev) "
for t in "${targets[@]}"; do spare+=" ${previous[$t]} "; done
count=0
# Release names are 12 hex characters, so ls's listing parses safely.
# shellcheck disable=SC2012
mapfile -t releases < <(ls -1t "$ROOT/releases")
for old in "${releases[@]}"; do
  [[ -n "$old" ]] || continue
  [[ "$spare" != *" $old "* ]] || continue
  count=$((count + 1))
  ((count > KEEP)) || continue
  note "pruning release $old"
  # REVISION first: a prune cut short leaves an interrupted build, never a
  # "complete" one with half its files. Verified by now: a failed prune is a note.
  { sudo -n rm -f "$ROOT/releases/$old/REVISION" && sudo -n rm -rf "${ROOT:?}/releases/$old"; } ||
    note "prune failed for $old; remove it by hand: sudo rm -rf $ROOT/releases/$old"
done
