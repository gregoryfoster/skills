#!/usr/bin/env bash
# install.sh — install the deploying-releases core, or its co-pypi wrapper, into
# a consuming repo.
#
# The core: this skill's assets/deploy.sh to <repo>/scripts/deploy.sh, and the
# hooks template to <repo>/scripts/deploy_hooks.sh when the repo has none.
# --co-pypi: assets/co-pypi/co-pypi.sh and co_pypi_token.py to <repo>/scripts/
# (#632), and their test to <repo>/tests/test_co_pypi.py when the repo has none.
# Each is a copy, never a symlink and never run from skills-vendor/: production
# runs what the consumer reviewed and committed, so an upgrade shows up as a
# diff in its own tree, not a submodule bump (#372).
#
# Refuses to overwrite a file that is not ours (the repo's own deploy or
# wrapper) unless --replace says that is the point: adopting it in a repo that
# has its own copy. Never overwrites deploy_hooks.sh or the test.
#
# Usage: bash install.sh [--co-pypi] [--check] [--replace] [--repo <dir>] [--help]
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash <skill>/scripts/install.sh [--co-pypi] [--check] [--replace] [--repo <dir>]

Installs the deploying-releases core as <repo>/scripts/deploy.sh, and the hooks
template as <repo>/scripts/deploy_hooks.sh when there is none. With --co-pypi,
installs the co-pypi wrapper instead: scripts/co-pypi.sh and
scripts/co_pypi_token.py, and tests/test_co_pypi.py when there is none.

  --co-pypi      the co-pypi wrapper, not the core (run both for a repo with both)
  --check        change nothing; report the installed copy against this skill's
  --replace      overwrite the repo's own deploy.sh (or co-pypi wrapper)
  --repo <dir>   the consuming repo (default: the git top level of the cwd)
  --help         this text

Prints one TSV line on stdout: <state> <installed version> <vendored version>.
States: installed, updated, current, drift, edited (an installed file no longer
matches its own sha256 marker: a hand edit), missing, foreign (not ours).
For --co-pypi the state is the pair's: foreign or edited if either file is,
missing if both are, current if both are, otherwise drift.

Exit codes:
  0  installed, updated or current
  1  --check found drift, a hand edit or no copy
  2  refused (a foreign file without --replace, an edited copy), or a usage
     or tooling error
EOF
}

CHECK=0
REPLACE=0
CO_PYPI=0
REPO=""
while (($#)); do
  case "$1" in
    --check) CHECK=1 ;;
    --replace) REPLACE=1 ;;
    --co-pypi) CO_PYPI=1 ;;
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
ASSETS="$HERE/../assets"
# Each copy: <asset> <path in the repo> <mode>. The once-only file (the hooks
# template, the test) is written when absent and never overwritten.
if ((CO_PYPI)); then
  NAME="co-pypi wrapper"
  MARK='deploying-releases-co-pypi'
  SRCS=("$ASSETS/co-pypi/co-pypi.sh" "$ASSETS/co-pypi/co_pypi_token.py")
  DESTS=(scripts/co-pypi.sh scripts/co_pypi_token.py)
  MODES=(755 644)
  ONCE_SRC="$ASSETS/co-pypi/test_co_pypi.py"
  ONCE_DEST=tests/test_co_pypi.py
  ONCE_NOTE="the co-pypi index's invariants"
  EDIT_ADVICE="raise the change upstream, restore the file, then install"
else
  NAME="core"
  MARK='deploying-releases-core'
  SRCS=("$ASSETS/deploy.sh")
  DESTS=(scripts/deploy.sh)
  MODES=(755)
  ONCE_SRC="$ASSETS/deploy_hooks.sh.tmpl"
  ONCE_DEST=scripts/deploy_hooks.sh
  ONCE_NOTE="fill in PROJECT and GITHUB_REPO"
  EDIT_ADVICE="Move the change into deploy_hooks.sh (or raise it upstream), restore the file, then install"
fi
for f in "${SRCS[@]}" "$ONCE_SRC"; do
  [[ -f "$f" ]] || {
    echo "install.sh: the skill's assets are missing ($f)" >&2
    exit 2
  }
done

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

MARK_VERSION="# $MARK: version "
MARK_SHA="# $MARK-sha256: "
ZEROS=0000000000000000000000000000000000000000000000000000000000000000

sha256() { # stdin -> hex digest
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | cut -d' ' -f1
  else
    shasum -a 256 | cut -d' ' -f1
  fi
}

version_of() { # <file>: its version, or nothing for a file that is not ours
  sed -n "2s/^${MARK_VERSION}//p" "$1" 2>/dev/null
}

# The digest a copy records of itself: the file with its own digest zeroed.
body_sha() { # <file>
  sed "s/^\(${MARK_SHA}\).*$/\1${ZEROS}/" "$1" | sha256
}
recorded_sha() { # <file>
  sed -n "s/^${MARK_SHA}//p" "$1" | head -n 1
}

vendored="$(version_of "${SRCS[0]}")"
for src in "${SRCS[@]}"; do
  [[ -n "$vendored" && "$(version_of "$src")" == "$vendored" &&
    "$(body_sha "$src")" == "$(recorded_sha "$src")" ]] || {
    echo "install.sh: this skill's own $src fails its sha256 marker; refusing to install it" >&2
    exit 2
  }
done

report() { printf '%s\t%s\t%s\n' "$1" "${2:--}" "$vendored"; }

# The once-only file: never over a repo's own. On every path that leaves the
# copy in place, so a repo with the copy and no hooks (or test) gets one.
ensure_once() {
  local dest="$REPO/$ONCE_DEST"
  [[ ! -e "$dest" ]] || return 0
  if mkdir -p "$(dirname "$dest")" && cp "$ONCE_SRC" "$dest"; then
    echo "install.sh: wrote $dest; $ONCE_NOTE" >&2
  else
    echo "install.sh: could not write $dest" >&2
    exit 2
  fi
}

# What the installed wrapper needs from pyproject.toml, named on every path that
# leaves the pair in place, so a re-run that changes nothing still says it.
warn_setup() {
  ((CO_PYPI)) || return 0
  if ! grep -Eq '^co-pypi *=' "$REPO/pyproject.toml" 2>/dev/null; then
    echo "install.sh: the wrapper runs pyproject.toml's co-pypi dependency group, which is missing:" \
      "add co-pypi = [\"google-auth[requests]>=2,<3\"] under [dependency-groups], then uv lock" >&2
  fi
  if grep -q '^\[tool\.ruff\]' "$REPO/pyproject.toml" 2>/dev/null &&
    ! grep -q 'scripts/co_pypi_token\.py' "$REPO/pyproject.toml"; then
    echo "install.sh: a ruff --fix or format pass would edit the installed minter:" \
      "add \"scripts/co_pypi_token.py\" to [tool.ruff] extend-exclude" >&2
  fi
}

# Each file's state, then the set's: foreign and edited win, then missing (all
# of them), current (all of them), and anything else is drift.
installed=""
states=()
for i in "${!SRCS[@]}"; do
  dest="$REPO/${DESTS[$i]}"
  if [[ ! -e "$dest" ]]; then
    states+=(missing)
    continue
  fi
  v="$(version_of "$dest")"
  if [[ -z "$v" ]]; then
    states+=(foreign)
  elif [[ "$(body_sha "$dest")" != "$(recorded_sha "$dest")" ]]; then
    states+=(edited)
  elif cmp -s "${SRCS[$i]}" "$dest"; then
    states+=(current)
  else
    states+=(drift)
  fi
  if [[ -n "$v" && -z "$installed" ]]; then installed="$v"; fi
done
any() { # <state>: one file is in it
  local s
  for s in "${states[@]}"; do [[ "$s" != "$1" ]] || return 0; done
  return 1
}
every() { # <state>: every file is in it
  local s
  for s in "${states[@]}"; do [[ "$s" == "$1" ]] || return 1; done
}
named() { # <state>: the repo paths of the files in it, so a message names the right one
  local i out=()
  for i in "${!states[@]}"; do [[ "${states[$i]}" != "$1" ]] || out+=("${DESTS[$i]}"); done
  echo "${out[*]}"
}
if any foreign; then
  state=foreign
elif any edited; then
  state=edited
elif every missing; then
  state=missing
elif every current; then
  state=current
else
  state=drift
fi

DEST="$REPO/${DESTS[0]}"
if ((CHECK)); then
  report "$state" "$installed"
  case "$state" in
    current) exit 0 ;;
    edited) echo "install.sh: $(named edited) in $REPO was edited by hand; $EDIT_ADVICE" >&2 ;;
    foreign) echo "install.sh: $(named foreign) in $REPO is this repo's own, not the $NAME" >&2 ;;
    missing) echo "install.sh: no $NAME at $DEST" >&2 ;;
    drift) echo "install.sh: the $NAME in $REPO/scripts is version ${installed:-?} or partial; this skill ships $vendored" >&2 ;;
  esac
  exit 1
fi

case "$state" in
  current)
    report current "$installed"
    ensure_once
    warn_setup
    exit 0
    ;;
  edited)
    echo "install.sh: $(named edited) in $REPO was edited by hand, so an upgrade would discard that edit." \
      "$EDIT_ADVICE" >&2
    report edited "$installed"
    exit 2
    ;;
  foreign)
    if ((!REPLACE)); then
      echo "install.sh: $REPO holds this repo's own $(named foreign). Adopting the $NAME replaces it:" \
        "pass --replace once its behaviour is covered" >&2
      report foreign ""
      exit 2
    fi
    ;;
esac

mkdir -p "$REPO/scripts" || {
  echo "install.sh: cannot make $REPO/scripts" >&2
  exit 2
}
for i in "${!SRCS[@]}"; do
  dest="$REPO/${DESTS[$i]}"
  # Through a temp file and a rename, so an interrupted copy never leaves half a file.
  tmp="$(mktemp "$REPO/scripts/.install.XXXXXX")" || {
    echo "install.sh: cannot make a temp file in $REPO/scripts" >&2
    exit 2
  }
  if ! { cp "${SRCS[$i]}" "$tmp" && chmod "${MODES[$i]}" "$tmp" && mv -f "$tmp" "$dest"; }; then
    rm -f "$tmp" || :
    echo "install.sh: could not write $dest" >&2
    exit 2
  fi
done
if [[ "$state" == missing || "$state" == foreign ]]; then
  report installed ""
else
  report updated "$installed"
fi
ensure_once
warn_setup
