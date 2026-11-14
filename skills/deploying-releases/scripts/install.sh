#!/usr/bin/env bash
# install.sh — install the deploying-releases core into a consuming repo.
#
# Copies this skill's assets/deploy.sh to <repo>/scripts/deploy.sh, and the hooks
# template to <repo>/scripts/deploy_hooks.sh when the repo has none. The core is
# a copy, never a symlink and never run from skills-vendor/: production runs
# what the consumer reviewed and committed, so an upgrade shows up as a diff in
# its own tree, not a submodule bump (#372).
#
# Refuses to overwrite a scripts/deploy.sh that is not a core (a repo's own
# deploy) unless --replace says that is the point: adopting the core in a repo
# that has its own copy. Never overwrites deploy_hooks.sh.
#
# Usage: bash install.sh [--check] [--replace] [--repo <dir>] [--help]
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash <skill>/scripts/install.sh [--check] [--replace] [--repo <dir>]

Installs the deploying-releases core as <repo>/scripts/deploy.sh, and the hooks
template as <repo>/scripts/deploy_hooks.sh when there is none.

  --check        change nothing; report the installed core against this skill's
  --replace      overwrite a scripts/deploy.sh that is the repo's own deploy
  --repo <dir>   the consuming repo (default: the git top level of the cwd)
  --help         this text

Prints one TSV line on stdout: <state> <installed version> <vendored version>.
States: installed, updated, current, drift, edited (the installed copy no
longer matches its own sha256 marker: a hand edit), missing, foreign (not a core).

Exit codes:
  0  installed, updated or current
  1  --check found drift, a hand edit or no core
  2  refused (a foreign deploy.sh without --replace, an edited core), or a usage
     or tooling error
EOF
}

CHECK=0
REPLACE=0
REPO=""
while (($#)); do
  case "$1" in
    --check) CHECK=1 ;;
    --replace) REPLACE=1 ;;
    --repo)
      (($# > 1)) || {
        echo "install.sh: --repo needs a directory" >&2
        exit 2
      }
      REPO="$2"
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "install.sh: unknown argument $1 (see --help)" >&2
      exit 2
      ;;
  esac
  shift
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE="$HERE/../assets/deploy.sh"
TEMPLATE="$HERE/../assets/deploy_hooks.sh.tmpl"
[[ -f "$CORE" && -f "$TEMPLATE" ]] || {
  echo "install.sh: the skill's assets are missing ($CORE, $TEMPLATE)" >&2
  exit 2
}

if [[ -z "$REPO" ]]; then
  REPO="$(git rev-parse --show-toplevel)" || {
    echo "install.sh: not in a git repo; pass --repo <dir>" >&2
    exit 2
  }
fi
[[ -d "$REPO" ]] || {
  echo "install.sh: $REPO is not a directory" >&2
  exit 2
}
DEST="$REPO/scripts/deploy.sh"
HOOKS="$REPO/scripts/deploy_hooks.sh"

MARK_VERSION='# deploying-releases-core: version '
MARK_SHA='# deploying-releases-core-sha256: '
ZEROS=0000000000000000000000000000000000000000000000000000000000000000

sha256() { # stdin -> hex digest
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | cut -d' ' -f1
  else
    shasum -a 256 | cut -d' ' -f1
  fi
}

version_of() { # <file>: the core's version, or nothing for a file that is not a core
  sed -n "2s/^${MARK_VERSION}//p" "$1" 2>/dev/null
}

# The digest a core records of itself: the file with its own digest zeroed.
body_sha() { # <file>
  sed "s/^\(${MARK_SHA}\).*$/\1${ZEROS}/" "$1" | sha256
}
recorded_sha() { # <file>
  sed -n "s/^${MARK_SHA}//p" "$1" | head -n 1
}

vendored="$(version_of "$CORE")"
[[ -n "$vendored" && "$(body_sha "$CORE")" == "$(recorded_sha "$CORE")" ]] || {
  echo "install.sh: this skill's own core fails its sha256 marker; refusing to install it" >&2
  exit 2
}

report() { printf '%s\t%s\t%s\n' "$1" "${2:--}" "$vendored"; }

# The template, once: never over a repo's own hooks. On every path that
# leaves a core in place, so a repo with the core and no hooks gets one.
ensure_hooks() {
  [[ ! -e "$HOOKS" ]] || return 0
  if cp "$TEMPLATE" "$HOOKS"; then
    echo "install.sh: wrote $HOOKS from the template; fill in PROJECT and GITHUB_REPO" >&2
  else
    echo "install.sh: could not write $HOOKS" >&2
    exit 2
  fi
}

installed=""
state=""
if [[ ! -e "$DEST" ]]; then
  state=missing
else
  installed="$(version_of "$DEST")"
  if [[ -z "$installed" ]]; then
    state=foreign
  elif [[ "$(body_sha "$DEST")" != "$(recorded_sha "$DEST")" ]]; then
    state=edited
  elif cmp -s "$CORE" "$DEST"; then
    state=current
  else
    state=drift
  fi
fi

if ((CHECK)); then
  report "$state" "$installed"
  case "$state" in
    current) exit 0 ;;
    edited) echo "install.sh: $DEST was edited by hand; configure deploy_hooks.sh instead" >&2 ;;
    foreign) echo "install.sh: $DEST is this repo's own deploy, not the core" >&2 ;;
    missing) echo "install.sh: no core at $DEST" >&2 ;;
    drift) echo "install.sh: $DEST is core version $installed; this skill ships $vendored" >&2 ;;
  esac
  exit 1
fi

case "$state" in
  current)
    report current "$installed"
    ensure_hooks
    exit 0
    ;;
  edited)
    echo "install.sh: $DEST was edited by hand, so an upgrade would discard that edit." \
      "Move the change into deploy_hooks.sh (or raise it upstream), restore the file, then install" >&2
    report edited "$installed"
    exit 2
    ;;
  foreign)
    if ((!REPLACE)); then
      echo "install.sh: $DEST is this repo's own deploy. Adopting the core replaces it:" \
        "pass --replace once its behaviour is in deploy_hooks.sh" >&2
      report foreign ""
      exit 2
    fi
    ;;
esac

mkdir -p "$REPO/scripts" || {
  echo "install.sh: cannot make $REPO/scripts" >&2
  exit 2
}
# Through a temp file and a rename, so an interrupted copy never leaves half a core.
tmp="$(mktemp "$REPO/scripts/.deploy.sh.XXXXXX")" || {
  echo "install.sh: cannot make a temp file in $REPO/scripts" >&2
  exit 2
}
if ! { cp "$CORE" "$tmp" && chmod 755 "$tmp" && mv -f "$tmp" "$DEST"; }; then
  rm -f "$tmp" || :
  echo "install.sh: could not write $DEST" >&2
  exit 2
fi
if [[ "$state" == missing || "$state" == foreign ]]; then
  report installed ""
else
  report updated "$installed"
fi
ensure_hooks
