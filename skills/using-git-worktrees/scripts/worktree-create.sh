#!/usr/bin/env bash
# worktree-create.sh
# Creates a git worktree for <branch> under the resolved worktree root.
# Refuses if <branch> is already checked out in another worktree (Iron Law).
#
# Usage: bash "<worktree-create.sh>" [--new] <branch> [--help]
# Flags are position-independent: `--new <branch>` and `<branch> --new` are equivalent.
set -euo pipefail

usage() {
  echo "Usage: bash \"$0\" [--new] <branch>"
  echo ""
  echo "Creates a worktree at <root>/<branch-slug>, where <branch-slug> is"
  echo "<branch> with '/' replaced by '-' (e.g., feature/foo -> feature-foo)."
  echo "The root is resolved via resolve-worktree-root.sh (env var → .skills/worktree_root → <repo>/.worktrees/)."
  echo ""
  echo "The main checkout's .venv is symlinked into the new worktree when one"
  echo "exists. Write 'none' into .skills/worktree_venv (read from the PRIMARY"
  echo "checkout; 'link' is the default) to skip that — the right setting when"
  echo "the main checkout is also a running service's WorkingDirectory=, where"
  echo "the service's own 'uv run' / 'uv sync' rewrite the shared venv under a"
  echo "worktree's test run."
  echo ""
  echo "Options:"
  echo "  --new   Create the branch (passes -b to git worktree add). Default: branch must already exist."
  echo ""
  echo "Flags may appear before or after <branch>; both orders are equivalent."
  echo ""
  echo "Iron Law: refuses if <branch> is already checked out in another worktree."
  echo ""
  echo "Refuses a root git would commit (#567): one inside the primary checkout"
  echo "or the current one that git does not ignore there. A worktree inside a"
  echo "tracked directory is one 'git add -A' away from being committed as an"
  echo "embedded repository. Add the root to that checkout's .gitignore (the"
  echo "default root wants '.worktrees/') and commit it, or move the root out of"
  echo "the repo. A root outside every work tree needs no rule and passes. Paths"
  echo "are compared after resolving symlinks and '..', so an alias of the repo"
  echo "is inside it. git is asked about the new worktree's own directory, so a"
  echo "'.worktrees/*' rule passes too. A relative WORKTREE_ROOT is taken from"
  echo "the current checkout's top level (a relative .skills/worktree_root, from"
  echo "the primary checkout's), so the printed path is always absolute."
  echo ""
  echo "Exit codes:"
  echo "  0  Worktree created; absolute path printed on stdout"
  echo "  1  Iron Law violation (branch already checked out elsewhere)"
  echo "  2  Tooling/infra failure (not a git repo, missing arg, the root could"
  echo "     not be created, git worktree add failed), or the root is inside a"
  echo "     work tree that does not ignore it (git check-ignore) or in a"
  echo "     submodule that is not checked out, which creates nothing"
}

# One line, not the whole block. An argument error used to print the full usage
# dump to stderr underneath the ERROR line — 23 lines here, 69 in the destroy
# script — so the one line carrying the actual diagnosis scrolled off the top,
# and a `| tail` on the output showed nothing but boilerplate (#262). `--help`
# still prints everything; a mistake gets a pointer to it.
usage_hint() {
  echo "Usage: bash \"$0\" [--new] <branch>   (run with --help for the full description)"
}

# Scan every argument for --help before anything runs, then parse flags in any
# position. Both properties are the convention worktree-list.sh already states
# in its own preamble; create and destroy were the two scripts in this
# directory that had drifted from it, in OPPOSITE directions (#262).
#
# The drift was not cosmetic. `--new` was recognised only as $1, so trailing it
# was dropped in silence and the failure surfaced as git's `fatal: invalid
# reference: <branch>` — the script blaming git for its own omission. And
# `--help` trailing an EXISTING branch fell through to provisioning: a request
# for documentation that created a worktree and printed its path.
for arg in "$@"; do
  if [[ "$arg" == "--help" ]]; then
    usage
    exit 0
  fi
done

NEW_BRANCH=0
BRANCH=""
BRANCH_SET=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --new)
      NEW_BRANCH=1
      shift
      ;;
    -*)
      echo "ERROR: unknown flag '$1'" >&2
      usage_hint >&2
      exit 2
      ;;
    *)
      # First non-flag argument is <branch>. A second one is an ERROR, not a
      # silent drop: `create foo bar` previously ignored 'bar' entirely, which
      # is the same failure mode as the dropped trailing flag.
      if [[ $BRANCH_SET -eq 1 ]]; then
        echo "ERROR: unexpected argument '$1' (<branch> is already '$BRANCH')" >&2
        usage_hint >&2
        exit 2
      fi
      BRANCH="$1"
      BRANCH_SET=1
      shift
      ;;
  esac
done

if [[ -z "$BRANCH" ]]; then
  echo "ERROR: <branch> argument required" >&2
  usage_hint >&2
  exit 2
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}
cd "$PROJECT_ROOT"

# here_git <args>: git for asking about another checkout, the primary above
# all, without an inherited GIT_DIR or GIT_WORK_TREE (#605, set R's CR 1895,
# 1903). Git exports GIT_DIR to every hook, and it beats -C: asked about a
# submodule's primary, git answered for this checkout or for the entry
# itself, so the primary's ignore check was skipped. merge-mode.sh holds the
# same rule. Each call answers for the checkout it names (docs/STYLE.md, #189).
here_git() {
  env -u GIT_DIR -u GIT_WORK_TREE git "$@"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT=$(bash "$SCRIPT_DIR/resolve-worktree-root.sh") || {
  echo "ERROR: failed to resolve worktree root" >&2
  exit 2
}

# The physical absolute path of $1, which need not exist yet: its deepest
# existing ancestor is resolved by `cd -P`/`pwd -P`, and the rest is applied
# lexically. That is exact, since a component that does not exist cannot be a
# symlink, and it is what `mkdir -p` will create. A raw string compare is not
# enough: macOS spells /var as /private/var, and an alias or a `..` reaches
# into the repo under a prefix that does not match it.
#
# The existing part is spelled as it is on disk (CR 1859). bash's builtin
# `pwd -P` keeps the spelling `cd` was given, so on a case-insensitive
# volume `Vendor/Sub/src` was asked of the superproject as written: not
# "in submodule" `vendor/sub` there, so the superproject decided, and the
# remedy it printed let through a root the submodule tracks. The external
# pwd calls getcwd(3), which returns the on-disk case on macOS; where it is
# missing, the builtin is the fallback. Components that do not exist yet
# keep the spelling given, which is what `mkdir -p` will create.
physical_pwd() {
  if [[ -x /bin/pwd ]]; then /bin/pwd -P; else pwd -P; fi
}

canonical_path() {
  local p=$1 rest="" head comp
  case $p in /*) ;; *) p="$PWD/$p" ;; esac
  # Every step is checked (#586). Past PATH_MAX, macOS's dirname fails ("File
  # name too long"): unchecked, `p` emptied, the walk ended at `.`, and the
  # root became `$PWD/<last component>`, so a root outside the repo was
  # refused as inside it. A failure here is the caller's exit 2.
  while [[ ! -d "$p" ]]; do
    if ! comp=$(basename -- "$p") || [[ -z "$comp" ]]; then return 1; fi
    rest="$comp${rest:+/$rest}"
    if ! p=$(dirname -- "$p") || [[ -z "$p" ]]; then return 1; fi
  done
  head=$(cd -P -- "$p" && physical_pwd) || return 1
  while [[ -n "$rest" ]]; do
    comp=${rest%%/*}
    if [[ "$rest" == */* ]]; then rest=${rest#*/}; else rest=""; fi
    case $comp in
      "" | .) ;;
      ..) head=$(dirname -- "$head") || return 1 ;;
      *) head="${head%/}/$comp" ;;
    esac
  done
  printf '%s\n' "$head"
}

# A relative root (a relative WORKTREE_ROOT; a relative .skills/worktree_root
# is already the primary checkout's) means the current checkout's top level,
# where this script now stands. Absolutized here, because stdout promises an
# absolute path: `wt/feature-x` printed to a caller in a subdirectory names a
# directory that does not exist.
case $ROOT in /*) ;; *) ROOT="$PWD/${ROOT#./}" ;; esac
SLUG="${BRANCH//\//-}"
WORKTREE_PATH="$ROOT/$SLUG"

# Refuse a root git would commit (#567). A worktree inside a directory git
# does not ignore is one `git add -A` away from being committed: git adds the
# nested checkout as an embedded repository (a gitlink), with only a warning.
# The default `<repo>/.worktrees/` is no exception: it is safe only where the
# repo ignores it.
#
# Two checkouts can commit it: the primary (the first `git worktree list`
# entry, merge-mode.sh's idiom), where the root normally lives, and the
# current one, which is a different tree when this runs from a linked
# worktree. Each that contains the root must ignore the new worktree's
# directory, by its own rules. The directory, not the root: `.worktrees/*`
# ignores every worktree in the root and not the root itself. A root inside
# a submodule of either is the submodule checkout's to decide (CR 1849).
#
# Three traps:
#   * Inside-ness first. `git check-ignore` exits non-zero for ANY path it does
#     not match, one outside the repo included (exit 128), so a root outside
#     every work tree passes without asking it.
#   * The trailing slash. A dir-only pattern matches only a path git knows is
#     a directory, and on the first create nothing there exists yet. A rule
#     on a parent (`.worktrees/`) matches `.worktrees/x` either way, since a
#     parent is a directory by construction; a rule on the worktree's own
#     level (`.worktrees/*/`) matches `.worktrees/x` only when asked with the
#     slash.
#   * Canonical paths on both sides (canonical_path, above), and containment by
#     inode, not by string (rel_in, below).
# check-ignore failing (exit 128) is a refusal too: an unanswered question is
# not "ignored". A root that IS the work tree is refused without asking.
ROOT_CANON=$(canonical_path "$ROOT") || {
  echo "ERROR: could not resolve the worktree root '$ROOT' (the reason is above)" >&2
  exit 2
}

# Succeeds when the root is the directory $1 or below it, setting REL to the
# root's path relative to $1 ("" for $1 itself). Walks up from the root and
# compares each ancestor by inode (`-ef`), not by string (CR 1842): the
# tree's path is spelled by git and the root's by canonical_path, and on a
# case-insensitive volume only the inode says two spellings are one
# directory. The existing part of REL is spelled as on disk (CR 1859), so
# git sees the submodule a case-flipped root leads into; a component that
# does not exist yet matches nothing and is carried into REL as given.
rel_in() {
  local anc=$ROOT_CANON rel=""
  while :; do
    if [[ "$anc" -ef "$1" ]]; then
      REL=$rel
      return 0
    fi
    [[ "$anc" != / ]] || return 1
    rel="${anc##*/}${rel:+/$rel}"
    anc=${anc%/*}
    anc=${anc:-/}
  done
}

# Prints the first leading part of $2 (a path in the work tree $1) that is a
# submodule (a mode-160000 gitlink) in $1's index; fails when none is.
gitlink_prefix() {
  local rest=$2 p="" comp
  while [[ -n "$rest" ]]; do
    comp=${rest%%/*}
    if [[ "$rest" == */* ]]; then rest=${rest#*/}; else rest=""; fi
    p=${p:+$p/}$comp
    if here_git -C "$1" -c core.quotePath=false ls-files --stage -- ":(literal)$p" |
      awk -F '\t' -v p="$p" '$2 == p && $1 ~ /^160000 / { f = 1 } END { exit !f }'; then
      printf '%s\n' "$p"
      return 0
    fi
  done
  return 1
}

tree_unknown() {
  echo "ERROR: could not resolve the work tree of '$1' (the reason is above), so whether it ignores the worktree root '$ROOT' is unknown${2:-}" >&2
  exit 2
}

WT_LIST=$(here_git worktree list --porcelain) || {
  echo "ERROR: failed to enumerate worktrees (git worktree list --porcelain)" >&2
  exit 2
}
# The primary is the first porcelain block, up to the first blank line. A
# block with a `bare` line is `repo.git`, which has no work tree and so
# cannot commit anything: it is not queued (CR 1840).
PRIMARY_BLOCK=${WT_LIST%%$'\n\n'*}
PRIMARY_ENTRY=${PRIMARY_BLOCK%%$'\n'*}
PRIMARY_ENTRY=${PRIMARY_ENTRY#worktree }
PRIMARY=$PRIMARY_ENTRY
# A queue, not a fixed pair: a root inside a submodule adds that submodule's
# checkout (CR 1849).
#
# One entry needs more than the loop's ask (#605, set R's CR 1892): a primary
# whose .git is a pointer file (`git init --separate-git-dir`) lists its
# store, which names no work tree. From that primary itself, the work tree is
# this one: its git dir is the common dir. From a linked worktree git knows no
# path to it, so whether it ignores the root is unknown: exit 2, saying so.
case $'\n'"$PRIMARY_BLOCK"$'\n' in
  *$'\n'bare$'\n'*) TREES=("$PROJECT_ROOT") ;;
  *)
    if ! here_git -C "$PRIMARY_ENTRY" rev-parse --show-toplevel >/dev/null 2>&1; then
      DIRS=$(here_git rev-parse --path-format=absolute --git-dir --git-common-dir 2>/dev/null) || DIRS=""
      if [[ -z "$DIRS" || "${DIRS%%$'\n'*}" != "${DIRS#*$'\n'}" ]] ||
        ! PRIMARY=$(here_git rev-parse --show-toplevel 2>/dev/null); then
        # Asked again for git's reason, which goes to stderr.
        here_git -C "$PRIMARY_ENTRY" rev-parse --show-toplevel >/dev/null || true
        HINT=""
        if [[ "$(here_git -C "$PRIMARY_ENTRY" rev-parse --is-inside-git-dir 2>/dev/null)" == true ]]; then
          HINT="; it is a git dir with no work tree, as a primary whose .git is a file makes it (git init --separate-git-dir), and only that primary knows its work tree, so run this from the primary checkout"
        fi
        tree_unknown "$PRIMARY_ENTRY" "$HINT"
      fi
    fi
    TREES=("$PRIMARY" "$PROJECT_ROOT")
    ;;
esac
CHECKED=()
i=0
while [[ $i -lt ${#TREES[@]} ]]; do
  TREE=${TREES[$i]}
  i=$((i + 1))
  # Each entry becomes its work tree the same way (CR 1840). In a submodule
  # (git 2.54) the primary's is `<super>/.git/modules/<name>`, whose work
  # tree git names via core.worktree. A tree git cannot answer for is exit
  # 2 with git's reason (CR 1858): skipping it skipped the one check that
  # could refuse the root, so "dubious ownership" let any root through.
  TOP=$(here_git -C "$TREE" rev-parse --show-toplevel) || tree_unknown "$TREE"
  TREE=$(cd -P -- "$TOP" && pwd -P) || tree_unknown "$TREE"
  SEEN=0
  for C in ${CHECKED[@]+"${CHECKED[@]}"}; do
    if [[ "$TREE" -ef "$C" ]]; then SEEN=1; fi
  done
  [[ $SEEN -eq 0 ]] || continue
  CHECKED+=("$TREE")
  rel_in "$TREE" || continue
  IGNORE_RC=1
  IGNORE_ERR=""
  if [[ -n "$REL" ]]; then
    IGNORE_RC=0
    IGNORE_ERR=$(here_git -C "$TREE" check-ignore -q -- "$REL/$SLUG/" 2>&1) || IGNORE_RC=$?
  fi
  [[ $IGNORE_RC -ne 0 ]] || continue
  # A root inside a submodule of this tree (CR 1849): git cannot answer for
  # this tree ("Pathspec ... is in submodule", exit 128), and no rule here
  # could change that. This tree commits only the gitlink; the submodule's
  # checkout is what would commit a worktree, so its rules decide. One that
  # is not checked out (no `.git` in it) is refused (CR 1870): there are no
  # rules to read, and a worktree there would block its init.
  if [[ $IGNORE_RC -eq 128 ]] && SUB=$(gitlink_prefix "$TREE" "$REL"); then
    if [[ ! -e "$TREE/$SUB/.git" ]]; then
      echo "ERROR: the worktree root '$ROOT' is inside the submodule at $TREE/$SUB, which is not checked out: its rules can't be read, and a worktree there would block 'git submodule update --init'" >&2
      echo "Set WORKTREE_ROOT or .skills/worktree_root to a path outside it." >&2
      exit 2
    fi
    TREES+=("$TREE/$SUB")
    continue
  fi
  [[ -z "$IGNORE_ERR" ]] || printf '%s\n' "$IGNORE_ERR" >&2
  if [[ -z "$REL" ]]; then
    echo "ERROR: the worktree root '$ROOT' is the work tree $TREE itself: every worktree would sit in the repo" >&2
    echo "Set WORKTREE_ROOT or .skills/worktree_root to a directory git ignores, or to a path outside the repo. Unset, the root is '.worktrees/', which .gitignore must carry." >&2
  else
    if [[ $IGNORE_RC -eq 1 ]]; then
      echo "ERROR: the worktree root '$ROOT' is inside $TREE, and git does not ignore it there: a worktree in it is one 'git add -A' away from being committed" >&2
      echo "Add '$REL/' to $TREE/.gitignore and commit it, or set WORKTREE_ROOT or .skills/worktree_root to a path outside the repo." >&2
    else
      # No .gitignore line answers a question git could not ask (CR 1849).
      echo "ERROR: git check-ignore failed (exit $IGNORE_RC; git's reason is above), so whether $TREE ignores the worktree root '$ROOT' is unknown" >&2
      echo "Set WORKTREE_ROOT or .skills/worktree_root to a path outside the repo." >&2
    fi
  fi
  exit 2
done


# Iron Law check: refuse if the branch is already checked out elsewhere.
# `git worktree list --porcelain` emits a `branch refs/heads/<name>` line per worktree.
EXISTING=$(git worktree list --porcelain | awk -v b="refs/heads/$BRANCH" '$1=="branch" && $2==b {print "match"; exit}')
if [[ "$EXISTING" == "match" ]]; then
  echo "ERROR: branch '$BRANCH' is already checked out in another worktree (Iron Law: no double checkout)" >&2
  echo "Run 'bash \"$SCRIPT_DIR/worktree-list.sh\"' to see existing worktrees." >&2
  exit 1
fi

if [[ -e "$WORKTREE_PATH" ]]; then
  echo "ERROR: path '$WORKTREE_PATH' already exists" >&2
  exit 2
fi

# Pre-flight zombie audit: warn (do not fail) if processes from previously-
# destroyed worktrees are still around. Fresh worktree creation is a good
# moment to surface stale state — non-zero from the audit becomes a WARN,
# never a gate. The audit script is detection-only and lives in the same
# scripts/ directory.
# Runs AFTER the Iron Law + existing-path checks so we don't pay the audit
# cost when we're about to abort anyway.
#
# `>/dev/null` as well as `--quiet`: this script's stdout contract is exactly
# the worktree path, and routing it through a child's flag makes the contract
# depend on that flag still working. Neutering QUIET in the audit script failed
# nine tests in test_worktree_venv_knob.py — a file about the venv knob, which
# is where the breakage would have been diagnosed. The redirect makes the
# coupling structural instead of behavioural; --quiet stays so the audit is not
# doing work whose output is thrown away.
#
# Exit 1 is zombies found; anything else non-zero is an audit that could not
# run (exit 2: no process table, no root), which is not a finding (#335).
if [[ -x "$SCRIPT_DIR/audit-worktree-zombies.sh" ]]; then
  AUDIT_RC=0
  "$SCRIPT_DIR/audit-worktree-zombies.sh" --quiet >/dev/null || AUDIT_RC=$?
  if [[ $AUDIT_RC -eq 1 ]]; then
    echo "WARN: worktree zombies detected — run 'bash $SCRIPT_DIR/audit-worktree-zombies.sh' for details" >&2
  elif [[ $AUDIT_RC -ne 0 ]]; then
    echo "WARN: the worktree zombie audit could not run (exit $AUDIT_RC) — run 'bash $SCRIPT_DIR/audit-worktree-zombies.sh' to see why" >&2
  fi
fi

# Exit 2, not set -e's 1: exit 1 is the Iron Law's code alone (CR 1850).
mkdir -p "$ROOT" || {
  echo "ERROR: could not create the worktree root '$ROOT'" >&2
  exit 2
}

# `git worktree add` splits its own chatter across both streams: "Preparing
# worktree ..." goes to stderr, but the checkout notice "HEAD is now at <sha>
# <subject>" goes to STDOUT, where it lands ahead of the path this script
# promises. Redirect, do not silence: `-q` empties stdout too, but it also
# drops the stderr line, leaving no record of what was checked out.
if [[ $NEW_BRANCH -eq 1 ]]; then
  git worktree add -b "$BRANCH" "$WORKTREE_PATH" >&2 || exit 2
else
  git worktree add "$WORKTREE_PATH" "$BRANCH" >&2 || exit 2
fi

# The link below is right by default and wrong for exactly one shape: a main
# checkout that is ALSO a running service's `WorkingDirectory=`. There the link
# hands every worktree one shared *mutable* environment while isolating it in
# every other respect, and the service's own tooling rewrites that environment
# underneath a worktree's test run (#201). Two mechanisms, both confirmed on uv
# 0.10.4:
#   * `uv run` reinstalls the current project, restamping
#     `importlib.metadata.version(...)` to the MAIN checkout's version mid-run.
#     A worktree suite on a bumped version then fails in a full run and passes
#     in isolation — a flake whose direction depends on which checkout ran uv
#     last.
#   * `uv sync` prunes every dependency group it was not asked for. An opt-in
#     group whose test modules `pytest.importorskip` at module scope does not
#     error when it vanishes; it turns a few hundred passes into skips against
#     a suite that still reports green.
#
# `.skills/worktree_venv` is the opt-out: `none`, or `link` (the default, so
# nothing changes for existing users).
#
# Read from the PRIMARY checkout, not from `git rev-parse --show-toplevel`.
# `.skills/` knobs are machine-local and untracked, and an untracked file does
# not exist in a linked worktree at all — so a knob read from the current
# checkout would be invisible whenever this script runs from inside a worktree,
# silently restoring the link in the one deployment the knob exists to protect.
# This is the derivation `resolve-worktree-root.sh` uses for the same reason,
# including its submodule guard: the parent of `<super>/.git/modules/<name>` is
# not a work tree, so the candidate is accepted only if it is a checkout
# sharing this common dir. The #203 gap is inherited with it — in a linked
# worktree OF a submodule the candidate is rejected and the knob is read from
# the current checkout, where an untracked file is absent.
worktree_venv_mode() {
  local common_dir candidate candidate_common knob_root knob configured
  knob_root="$PROJECT_ROOT"
  common_dir=$(here_git rev-parse --git-common-dir 2>/dev/null || true)
  if [[ -n "$common_dir" ]] && common_dir=$(cd "$common_dir" 2>/dev/null && pwd -P); then
    candidate=$(dirname "$common_dir")
    # `git -C "$candidate"` answers relative to candidate, not to our $PWD.
    candidate_common=$(here_git -C "$candidate" rev-parse --git-common-dir 2>/dev/null || true)
    if [[ -n "$candidate_common" ]] &&
       candidate_common=$(cd "$candidate" && cd "$candidate_common" 2>/dev/null && pwd -P) &&
       [[ "$candidate_common" == "$common_dir" ]]; then
      knob_root="$candidate"
    fi
  fi

  knob="$knob_root/.skills/worktree_venv"
  [[ -f "$knob" ]] || { echo link; return 0; }

  # First non-blank, non-comment line, trimmed — the same read
  # `resolve-worktree-root.sh` gives `.skills/worktree_root`, so one knob
  # syntax covers the directory. `|| true` keeps pipefail from aborting on a
  # file that is empty or all comments: that must default, not crash.
  configured=$(grep -v '^[[:space:]]*#' "$knob" | grep -v '^[[:space:]]*$' | head -n1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
  case "$configured" in
    none) echo none ;;
    link | "") echo link ;;
    # A malformed knob file degrades to the default AND says so. Silence is
    # what lets a typo ('off', 'false', 'no') read as a working opt-out, and
    # the symptom it would leave — a venv that keeps being rewritten — is the
    # one this whole block exists to make legible.
    *)
      echo "WARN: $knob: unrecognised value '$configured' (expected 'link' or 'none') — linking as usual" >&2
      echo link
      ;;
  esac
}

# A worktree inherits no virtualenv, so the first `.venv/bin/python -m pytest`
# in it dies before any test runs (#156). Link the parent's when there is one:
# a symlink is by construction the same interpreter and the same installed
# packages, where a freshly resolved venv is a different environment that can
# collect fewer tests and still report green.
#
# Opportunistic, never a gate — this script is vendored into repos that have no
# venv at all, and a worktree without one is not a failed worktree. Notes go to
# stderr; stdout stays the worktree path, which is this script's contract.
#
# Does NOT reach harness-provisioned worktrees (the Agent tool's
# `isolation: "worktree"`), which call `git worktree add` directly and never
# run this script. Those rely on the consuming repo's own hook, plus the
# by-hand `ln -s` in SKILL.md Phase 3.
#
# Every failure path here is swallowed. The worktree already exists by this
# point, so a `set -e` abort would return non-zero for a creation that
# succeeded — and leave the caller without the path on stdout.
# `! -e && ! -L`, matching scripts/structural-tests.sh: a BROKEN symlink at
# .venv is `-e` false and `-L` true, so testing -e alone would fall through to
# an `ln -s` that fails on the existing name. It lands in the WARN branch either
# way, but the two linkers must read identically or a later edit fixes one.
if [[ -e "$PROJECT_ROOT/.venv/bin/activate" && ! -e "$WORKTREE_PATH/.venv" && ! -L "$WORKTREE_PATH/.venv" ]]; then
  # Resolved here rather than up front so a repo with no venv pays none of it,
  # and so a malformed knob warns only where it would have changed something.
  if [[ "$(worktree_venv_mode)" == "none" ]]; then
    # Announced, never silent. An absent .venv is also the signature of the
    # #156 bug this linker fixes, so the operator standing in a fresh worktree
    # has to be told which of the two they are looking at.
    echo "NOTE: .skills/worktree_venv=none — no .venv linked into $WORKTREE_PATH; provision one there" >&2
  else
    # `pwd -P` resolves through a .venv that is itself a symlink (a worktree
    # provisioning a worktree), so we never build a link to a link.
    VENV_TARGET=$(cd "$PROJECT_ROOT/.venv" 2>/dev/null && pwd -P) || VENV_TARGET=""
    if [[ -z "$VENV_TARGET" ]]; then
      echo "WARN: could not resolve $PROJECT_ROOT/.venv — no venv linked into $WORKTREE_PATH" >&2
    elif ln -s "$VENV_TARGET" "$WORKTREE_PATH/.venv" 2>/dev/null; then
      echo "NOTE: linked .venv -> $VENV_TARGET" >&2
    else
      echo "WARN: could not link .venv into $WORKTREE_PATH — run 'ln -s $VENV_TARGET .venv' there" >&2
    fi
  fi
fi

echo "$WORKTREE_PATH"
