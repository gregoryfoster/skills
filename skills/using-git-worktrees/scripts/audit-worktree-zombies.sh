#!/usr/bin/env bash
# audit-worktree-zombies.sh — list processes referencing destroyed worktrees.
# Exits non-zero if zombies are found, so it can be wired into pre-flight checks.
set -euo pipefail

usage() {
  echo "Usage: bash \"$0\" [--quiet]"
  echo ""
  echo "Lists processes whose cmdline references a path under the resolved"
  echo "worktree root that no longer exists on disk. Detection-only — does"
  echo "not kill anything. The root matches as given, as resolved through"
  echo "symlinks, and as the caller's directory spells it; only the first"
  echo "worktree path in a cmdline is checked."
  echo ""
  echo "Searches for zombies under the resolved worktree root (env WORKTREE_ROOT"
  echo "→ .skills/worktree_root → <repo>/.worktrees/, in that order)."
  echo ""
  echo "Exit codes:"
  echo "  0  No zombies found"
  echo "  1  Zombies found (printed to stdout)"
  echo "  2  Tooling/infra failure (not a git repo, unknown flag, ps failed)"
}

# Argument errors print one line, not the whole usage block — the rule the rest
# of this directory adopted in #262, so a diagnosis is not buried under
# boilerplate that a `| tail` would show instead.
usage_hint() {
  echo "Usage: bash \"$0\" [--quiet]   (run with --help for the full description)"
}

# Scan every argument for --help before the loop runs. Handling it inside the
# loop covered `--quiet --help` but not `stray --help`, where the bare word hit
# the error arm first — so a help request could still be answered with an
# error. This is the convention worktree-list.sh states in its own preamble
# and the one create/destroy adopted in #262.
for arg in "$@"; do
  if [[ "$arg" == "--help" ]]; then
    usage
    exit 0
  fi
done

# This script takes no positional arguments, so a bare word is an unexpected
# argument, not an "unknown flag" — the same misdiagnosis #262 removed from
# worktree-destroy.sh, where the branch name was reported as a flag.
QUIET=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quiet) QUIET=1; shift ;;
    -*)
      echo "ERROR: unknown flag '$1'" >&2
      usage_hint >&2
      exit 2
      ;;
    *)
      echo "ERROR: unexpected argument '$1' (this script takes no positional arguments)" >&2
      usage_hint >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKTREE_ROOT=$(bash "$SCRIPT_DIR/resolve-worktree-root.sh") || {
  echo "ERROR: failed to resolve worktree root" >&2
  exit 2
}
# resolve-worktree-root.sh already verifies we're inside a git repo (exits 2
# otherwise), so no separate `git rev-parse --show-toplevel` sentinel is needed.

# Trim any trailing slash so the match doesn't look for `//` when
# WORKTREE_ROOT is set via env with a conventional trailing slash. Without
# this, `WORKTREE_ROOT=/custom/wt/` looks for `/custom/wt//`, which won't
# match real cmdlines — silent false negatives.
WORKTREE_ROOT="${WORKTREE_ROOT%/}"

# A root reached through a symlink has more than one spelling, and a process
# started under one the audit was not given went unlisted, with "No worktree
# zombies." to say so (#533). So the root is matched as configured, as resolved
# through symlinks, and as the caller spells it. Only an absolute root that
# exists has the other two: `cd` fails on a missing one, and a relative one
# would resolve against wherever the audit happened to run.
RESOLVED_ROOT=""
if [[ "$WORKTREE_ROOT" == /* ]]; then
  RESOLVED_ROOT=$(cd -- "$WORKTREE_ROOT" 2>/dev/null && pwd -P) || RESOLVED_ROOT=""
fi

# The caller's spelling of a resolved path, or nothing. The default root is
# built with `pwd -P`, so it is always the resolved spelling, and a repo reached
# through a symlink (macOS's /tmp is /private/tmp) left a process under the
# caller's `/tmp/<repo>/.worktrees/<gone>` unlisted (CR 1738). The caller's
# `pwd -L` and `pwd -P` name the link: stripping their common trailing
# components leaves one mapping, physical prefix to logical prefix. It works
# from a linked worktree too, where the caller's toplevel is not the primary
# checkout the default root lives under, since only the prefix is used. The
# strip can overreach (`L/proj` linked to `R/proj` maps `R` to `L`, which is no
# spelling of `R`), so a derived spelling counts only if it resolves to the
# root. A caller under no link learns nothing: a process under some other
# symlink to the root is still missed.
caller_spelling() {
  local resolved=$1 logical physical candidate
  logical=$(pwd -L 2>/dev/null) && physical=$(pwd -P 2>/dev/null) || return 0
  [[ "$logical" == /* && "$physical" == /* && "$logical" != "$physical" ]] || return 0
  while [[ -n "$logical" && -n "$physical" && "${logical##*/}" == "${physical##*/}" ]]; do
    logical=${logical%/*}
    physical=${physical%/*}
  done
  case "$resolved" in
    "$physical" | "$physical"/*) candidate="$logical${resolved#"$physical"}" ;;
    *) return 0 ;;
  esac
  [[ "$(cd -- "$candidate" 2>/dev/null && pwd -P)" == "$resolved" ]] || return 0
  printf '%s\n' "$candidate"
}

CALLER_ROOT=""
if [[ -n "$RESOLVED_ROOT" ]]; then
  CALLER_ROOT=$(caller_spelling "$RESOLVED_ROOT")
fi

# Enumerate with `ps`, not `pgrep -af` (#335). On macOS and the BSDs `pgrep -a`
# means "include ancestors in the match", not "print the command line", so each
# line was a bare PID, no worktree path could be read from it, and the audit
# said "No worktree zombies." — fail-open, and quietly. `ps -A -o` prints
# `<pid> <ppid> <args>` on procps and BSD alike. `-ww` because procps cuts args
# at $COLUMNS without it, which can cut the worktree path off and fail open the
# same way. Captured rather than piped, so a ps that fails is a tooling failure
# (exit 2) with its own stderr shown, never a clean bill.
PS_TABLE=$(ps -A -ww -o pid= -o ppid= -o args=) || {
  echo "ERROR: ps failed, so no process was checked" >&2
  exit 2
}

# Scope all matching to the project's RESOLVED worktree root, which may be the
# default <repo>/.worktrees/ or a custom location set via WORKTREE_ROOT env var
# or .skills/worktree_root file. Without this scoping, processes referencing
# other projects' worktree paths on the same machine would be falsely flagged
# as zombies of this project.
#
# The root is matched as a literal string, passed through the environment: a
# `grep` filter would carry the pattern in its own argv and could match itself,
# and awk's `-v` would rewrite any backslash in the path. Each candidate is
# printed as `<pid> TAB <root>/<name> TAB <args>`, where <name> is the first
# path component after the root — the worktree the process belongs to. Of the
# root's spellings, whichever comes first in the text is used, so a process is
# still checked by the first worktree name it names, not by any. <name>
# also ends at shell punctuation (`;&|<>()'"` and backtick) and at `:`, since a
# shell's command text writes `cd <root>/<name>; …` or `PATH=<root>/<name>:…`.
# Keeping the `;` named a worktree that never existed, so a live session's shell
# was listed as a zombie of it (#335). \047 is a single quote: the program sits
# inside one.
#
# The audit's own ancestors are never candidates. The shell that ran it may
# name a vanished worktree in its own command text, and so may a wrapper further
# up: under worktree-create.sh's preamble the wrapper is the audit's
# grandparent. Listing either would make the `Kill all:` recipe kill the caller.
CANDIDATES=$(AUDIT_ROOT="$WORKTREE_ROOT/" \
  AUDIT_ROOT_RESOLVED="${RESOLVED_ROOT:+$RESOLVED_ROOT/}" \
  AUDIT_ROOT_CALLER="${CALLER_ROOT:+$CALLER_ROOT/}" AUDIT_SELF=$$ awk '
  BEGIN {
    roots[1] = ENVIRON["AUDIT_ROOT"]; nroots = 1
    split("AUDIT_ROOT_RESOLVED AUDIT_ROOT_CALLER", more, " ")
    for (k = 1; k <= 2; k++) {
      r = ENVIRON[more[k]]
      for (j = 1; j <= nroots; j++) if (roots[j] == r) r = ""
      if (r != "") roots[++nroots] = r
    }
  }
  {
    ppid[$1] = $2
    args = $0
    sub("^[ \t]*[0-9]+[ \t]+[0-9]+[ \t]", "", args)
    s = args
    while (1) {
      # The earliest spelling in the text; at a tie, the longer one.
      at = 0
      for (j = 1; j <= nroots; j++) {
        i = index(s, roots[j])
        if (i > 0 && (at == 0 || i < at || (i == at && length(roots[j]) > length(root)))) {
          at = i; root = roots[j]
        }
      }
      if (at == 0) break
      s = substr(s, at + length(root))
      if (match(s, "^[^/ \t;&|<>()\047\"`:]+")) {
        n++; pid[n] = $1; wt[n] = root substr(s, 1, RLENGTH); cmd[n] = args
        break
      }
    }
  }
  END {
    p = ENVIRON["AUDIT_SELF"]
    while (!(p in ancestor)) {
      ancestor[p] = 1
      if (!(p in ppid)) break
      p = ppid[p]
    }
    for (k = 1; k <= n; k++)
      if (!(pid[k] in ancestor)) print pid[k] "\t" wt[k] "\t" cmd[k]
  }
' <<<"$PS_TABLE") || {
  echo "ERROR: awk failed to read the process table" >&2
  exit 2
}

ZOMBIES=()
while IFS=$'\t' read -r PID WT_PATH CMD; do
  [[ -n "$PID" ]] || continue
  [[ -d "$WT_PATH" ]] && continue
  ZOMBIES+=("$PID $CMD")
done <<<"$CANDIDATES"

if (( ${#ZOMBIES[@]} > 0 )); then
  if (( QUIET == 0 )); then
    printf 'Worktree zombie processes detected (%d):\n' "${#ZOMBIES[@]}"
    printf '  %s\n' "${ZOMBIES[@]}"
    echo ""
    # $0, not a hardcoded path: under vendoring the script lives at
    # skills-vendor/<owner>-<repo>/skills/using-git-worktrees/scripts/, where a
    # hardcoded prefix names a file that does not exist. $0 is whatever the
    # caller actually invoked, so the recipe is copy-pasteable as printed.
    echo "Kill all: bash \"$0\" | awk '/^  [0-9]/ {print \$1}' | xargs kill"
  fi
  exit 1
fi

(( QUIET == 1 )) || echo "No worktree zombies."
