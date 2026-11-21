#!/usr/bin/env bash
# _attest-gate.sh — the local-gate attestation (#688). Sourced by push.sh;
# running it does nothing, so there is no command-line path to the write.
#
# In a private, duration-shaped repo whose PRs come from people, the gate a
# developer just ran locally runs again on a billed runner (#602). With
# .skills/attest-local-gate committed as `on`, push.sh says so on the commit:
# the status `gate/local` = `success` on the SHA it pushed, which CI may read
# to skip its heavy tier. references/attestation.md has the CI side.
#
# THE ORDER: verify, push, write.
#   attest_verify  before the push. The knob, then a clean tree, then the gate
#                  on it. Verifying first means a tree the gate fails is never
#                  pushed, and the write follows the push by seconds instead
#                  of by a gate run, so a runner that push starts can find it.
#   (push.sh pushes)
#   attest_post    the write, then a read-back through the combined status,
#                  the endpoint CI reads.
#
# THE KNOB is read from the commit being shipped (HEAD), never the work tree:
# only a committed knob turns writes on, so one developer's untracked file
# decides nothing for the repo, and the opt-in travels with the commit that
# carries it. One word, `on` or `off`; blank lines and whole-line `#`
# comments are ignored. `off` is the same as absent. Anything else is exit 2
# before the push, never `on` and never silently `off`.
#
# THE GATE is the one Step 1 resolved: the project's scripts/pre-ship.sh,
# else the pre-ship.sh beside the path push.sh was run through, else the one
# beside its target. It is asked, not re-implemented, and its exit code is
# the whole answer. So a pass it reuses from a stamp attests: the stamp is
# keyed to this exact tree and its tools and written only for a clean tree
# (gate-stamp.sh), which is the evidence a fresh run would give. GATE_STAMP
# reaches the gate as the caller set it; nothing here forces a run.
#
# NEVER `success` FOR A TREE THE GATE DIDN'T PASS. The write is reached only
# after the gate exited 0 on a clean tree, HEAD and the tree were checked
# again after it, and HEAD is still that commit after the push.
#
# A REFUSED WRITE DOESN'T FAIL THE SHIP. By then the push has landed, and a
# missing status fails safe: CI runs its full tier. It is said on stderr with
# gh's own message, under ATTESTATION NOT POSTED, and on stdout in one line.
#
# The caller sets ATTEST_LINK_DIR and ATTEST_SCRIPT_DIR, and runs from the
# project root. ATTEST_READBACK_PAUSE is the seconds between read-backs
# (default 2).
#
# ATTEST_SHA and ATTEST_TREE are read by push.sh, which shellcheck can't see.
# shellcheck disable=SC2034
set -euo pipefail

ATTEST_KNOB=.skills/attest-local-gate
# A contract: CI snippets key on this name, so it is fixed, not configurable.
ATTEST_CONTEXT=gate/local
ATTEST_SHA=""
ATTEST_TREE=""

attest_usage() {
  cat <<'USAGE'
Usage: . _attest-gate.sh    (sourced by push.sh; running it does nothing)

The local-gate attestation, on when the commit being shipped carries
.skills/attest-local-gate with the one word `on`.

  attest_verify   before the push: the knob, a clean tree, then the gate on
                  it (scripts/pre-ship.sh, else the skill's)
                    0  the gate passed on HEAD's tree
                    1  not passed: uncommitted changes, a failing gate, or a
                       tree the gate changed
                    2  could not tell: an unusable knob, no gate, a gate that
                       did not run, git failing
                    3  the knob says `off`
  attest_post     after the push: posts the commit status gate/local =
                  success on that SHA to origin's repository, then reads it
                  back through the combined status
                    0  posted and read back
                    1  not posted, or not confirmed; said on both streams

The write needs gh, logged in with push access to the repository: a classic
token's `repo` scope, or a fine-grained token's "Commit statuses: write".
USAGE
}

case "${0##*/}" in
  _attest-gate.sh) case "${1-}" in -h | --help) attest_usage; exit 0 ;; esac ;;
esac

# 0 on, 3 off, 2 unusable (said on stderr).
attest_read_knob() {
  local entry mode text line count=0 word="" rc=0
  local remedy="write one word, 'on' or 'off', or delete the file"
  local -a words
  entry=$(git ls-tree HEAD -- "$ATTEST_KNOB") || rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "ERROR: git ls-tree HEAD failed (exit $rc), so $ATTEST_KNOB could not" >&2
    echo "       be read from the commit. Nothing was pushed." >&2
    return 2
  fi
  if [[ -z "$entry" ]]; then
    echo "ERROR: $ATTEST_KNOB is in the work tree but not in the commit being" >&2
    echo "       shipped. The knob is read from the commit, so only a committed" >&2
    echo "       one attests: commit it, or delete it. Nothing was pushed." >&2
    return 2
  fi
  mode=${entry%% *}
  case $mode in
    100644 | 100755) ;;
    *)
      echo "ERROR: $ATTEST_KNOB is not a regular file in the commit being" >&2
      echo "       shipped (mode $mode): $remedy. Nothing was pushed." >&2
      return 2
      ;;
  esac
  text=$(git cat-file blob "HEAD:$ATTEST_KNOB") || rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "ERROR: git cat-file failed (exit $rc) reading $ATTEST_KNOB from the" >&2
    echo "       commit. Nothing was pushed." >&2
    return 2
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    line=${line%$'\r'}
    read -r -a words <<<"$line"
    [[ ${#words[@]} -gt 0 ]] || continue
    case ${words[0]} in \#*) continue ;; esac
    count=$((count + ${#words[@]}))
    word=${words[0]}
  done <<<"$text"
  if [[ $count -eq 1 && "$word" == on ]]; then
    return 0
  fi
  if [[ $count -eq 1 && "$word" == off ]]; then
    return 3
  fi
  if [[ $count -eq 0 ]]; then
    echo "ERROR: $ATTEST_KNOB, in the commit being shipped, names no setting:" >&2
  elif [[ $count -gt 1 ]]; then
    echo "ERROR: $ATTEST_KNOB, in the commit being shipped, has $count words; it takes one:" >&2
  else
    echo "ERROR: $ATTEST_KNOB, in the commit being shipped, says '$word':" >&2
  fi
  echo "       $remedy. Nothing was pushed." >&2
  return 2
}

# 0 clean, 1 not (the first paths are listed), 2 unknown. git's own stderr is
# shown: a failing status is not a clean tree (#257).
#
# git's defaults are not trusted (CR 2664). A repo's config can hide what
# makes the files differ from the commit, and a gate that passes only because
# of what is hidden would be attested for a commit that fails it:
#   status.showUntrackedFiles=no     hides every untracked file
#   submodule.<name>.ignore=dirty    hides an edit inside a submodule, which
#                                    is where a consumer vendors this gate
#   skip-worktree, assume-unchanged  tell git not to look at a path at all,
#                                    so no status can vouch for it
_attest_tree_state() {
  local out hidden rc=0
  out=$(git status --porcelain --untracked-files=all --ignore-submodules=none) || rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "ERROR: git status failed (exit $rc): the tree state is unknown," >&2
    echo "       which is not clean. Nothing was pushed." >&2
    return 2
  fi
  if [[ -n "$out" ]]; then
    printf '%s\n' "$out" | sed -n '1,5s/^/         /p' >&2
    return 1
  fi
  # `git ls-files -v` tags a skip-worktree path S and lowercases the tag of
  # an assume-unchanged one.
  hidden=$(git ls-files -v) || rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "ERROR: git ls-files failed (exit $rc): the tree state is unknown," >&2
    echo "       which is not clean. Nothing was pushed." >&2
    return 2
  fi
  hidden=$(grep '^[a-zS] ' <<<"$hidden" || true)
  if [[ -n "$hidden" ]]; then
    printf '%s\n' "$hidden" | sed -n '1,5s/^/         /p' >&2
    echo "       git was told not to watch these paths (skip-worktree or" >&2
    echo "       assume-unchanged), so it can't say they are the commit's." >&2
    return 1
  fi
  return 0
}

attest_verify() {
  local rc=0 sha tree now gate="" candidate
  attest_read_knob || rc=$?
  [[ $rc -eq 0 ]] || return "$rc"

  sha=$(git rev-parse HEAD) || rc=$?
  if [[ $rc -eq 0 ]]; then
    tree=$(git rev-parse 'HEAD^{tree}') || rc=$?
  fi
  if [[ $rc -ne 0 ]]; then
    echo "ERROR: git could not name HEAD or its tree (exit $rc). Nothing was pushed." >&2
    return 2
  fi

  _attest_tree_state || rc=$?
  case $rc in
    0) ;;
    1)
      echo "ERROR: uncommitted changes (above). The gate would run on files" >&2
      echo "       that aren't the commit, so it can't speak for it. Commit" >&2
      echo "       them (Step 2), then push. Nothing was pushed." >&2
      return 1
      ;;
    *) return 2 ;;
  esac

  for candidate in scripts "${ATTEST_LINK_DIR:-}" "${ATTEST_SCRIPT_DIR:-}"; do
    if [[ -n "$candidate" && -f "$candidate/pre-ship.sh" ]]; then
      gate="$candidate/pre-ship.sh"
      break
    fi
  done
  if [[ -z "$gate" ]]; then
    echo "ERROR: $ATTEST_KNOB is on, but there is no pre-ship.sh to ask: not" >&2
    echo "       in scripts/, nor beside push.sh (${ATTEST_LINK_DIR:-?})," >&2
    echo "       nor beside its target (${ATTEST_SCRIPT_DIR:-?}). Nothing was pushed." >&2
    return 2
  fi

  echo "Attestation: $ATTEST_KNOB is on. Asking the gate about $sha"
  echo "  before the push: $gate"
  bash "$gate" || rc=$?
  case $rc in
    0) ;;
    1)
      echo "" >&2
      echo "ERROR: the gate failed on this tree (exit 1). Nothing was pushed," >&2
      echo "       and nothing is attested. Fix what it names, commit, and push." >&2
      return 1
      ;;
    *)
      echo "" >&2
      echo "ERROR: the gate did not run (exit $rc), which is never a pass." >&2
      echo "       Nothing was pushed, and nothing is attested." >&2
      return 2
      ;;
  esac

  # The gate passed on something. Is it still what is here?
  now=$(git rev-parse HEAD) || rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "ERROR: git could not name HEAD after the gate (exit $rc). Nothing was pushed." >&2
    return 2
  fi
  if [[ "$now" != "$sha" ]]; then
    echo "ERROR: the tree changed under the gate: HEAD moved from $sha" >&2
    echo "       to $now. Nothing was pushed. Push again to ask the gate about it." >&2
    return 1
  fi
  _attest_tree_state || rc=$?
  case $rc in
    0) ;;
    1)
      echo "ERROR: the tree changed under the gate (above): what it passed is" >&2
      echo "       no longer what is here. Nothing was pushed. Commit or" >&2
      echo "       discard the changes, then push." >&2
      return 1
      ;;
    *) return 2 ;;
  esac

  ATTEST_SHA=$sha
  ATTEST_TREE=$tree
  return 0
}

# _attest_repo_of <remote url>: `host/owner/repo`, or nothing for a URL that
# names no host's repository. managing-skills' _gh_repo_of, ported (#576): an
# SSH URL's host is an ssh_config name, so `ssh -G` names the HostName behind
# a deploy-key alias, and SSH-over-443's ssh.github.com is github.com to gh.
_attest_repo_of() {
  local url=$1 rest host path ssh="" alias
  case $url in
    ssh://* | git+ssh://* | ssh+git://*) ssh=1 ;;
  esac
  case $url in
    *://*)
      rest=${url#*://}
      host=${rest%%/*}
      path=${rest#*/}
      host=${host##*@}
      host=${host%%:*}
      ;;
    *:*)
      # scp-like, [user@]host:path: git's rule is no slash before the colon.
      rest=${url%%:*}
      case $rest in */*) return 0 ;; esac
      host=${rest##*@}
      path=${url#*:}
      ssh=1
      ;;
    *) return 0 ;;
  esac
  path=${path%/}
  path=${path%.git}
  case $host in '' | -*) return 0 ;; esac
  case $path in
    '' | /* | */*/*) return 0 ;;
    */*) ;;
    *) return 0 ;;
  esac
  if [[ -n "$ssh" ]]; then
    alias=$host
    host=$(ssh -G -- "$alias" </dev/null 2>/dev/null | awk '$1 == "hostname" { print $2; exit }' || true)
    [[ "$host" != ssh.github.com ]] || host=github.com
    case $host in '' | -*) return 0 ;; esac
  fi
  printf '%s/%s\n' "$host" "$path"
}

_attest_goes_on() {
  echo "  The push landed and the ship goes on. $1" >&2
  echo "  Say so in the Step 7 report, and never post the status by hand." >&2
  echo "  Once the cause is fixed, running push.sh again retries it." >&2
}

_attest_not_posted() {
  echo "" >&2
  echo "ATTESTATION NOT POSTED: $1." >&2
  _attest_goes_on "CI finds no $ATTEST_CONTEXT status on $ATTEST_SHA and runs its full tier."
  echo "Attestation: $ATTEST_CONTEXT NOT posted on $ATTEST_SHA (the reason is on stderr)."
}

_attest_not_confirmed() {
  echo "" >&2
  echo "ATTESTATION NOT CONFIRMED: the write was accepted, but $1." >&2
  _attest_goes_on "CI reads that same combined status, so it may run its full tier."
  echo "Attestation: $ATTEST_CONTEXT NOT confirmed on $ATTEST_SHA (the reason is on stderr)."
}

attest_post() {
  local sha=$ATTEST_SHA head url repo host path rc=0 state="" try
  local pause=${ATTEST_READBACK_PAUSE:-2}
  # This context's latest state, or "none". Built outside the $(...) below:
  # bash 3.2 misreads escaped quotes inside a command substitution.
  local jq='[.statuses[] | select(.context == "CONTEXT")][0].state // "none"'
  jq=${jq/CONTEXT/$ATTEST_CONTEXT}

  head=$(git rev-parse HEAD) || head=""
  if [[ "$head" != "$sha" ]]; then
    _attest_not_posted "HEAD moved during the push, from the commit the gate passed to ${head:-an unknown commit}"
    return 1
  fi
  # The configured URL, not `git remote get-url`, which expands insteadOf.
  url=$(git config --get remote.origin.url) || url=""
  repo=$(_attest_repo_of "$url")
  if [[ -z "$repo" ]]; then
    _attest_not_posted "origin's URL (${url:-none}) names no repository on a GitHub host"
    return 1
  fi
  host=${repo%%/*}
  path=${repo#*/}
  if ! command -v gh >/dev/null 2>&1; then
    _attest_not_posted "gh is not on PATH (install it, then run gh auth login)"
    return 1
  fi

  # gh's stderr is not redirected: its refusal is the operator's to read.
  gh api --hostname "$host" --method POST "repos/$path/statuses/$sha" \
    -f state=success -f "context=$ATTEST_CONTEXT" \
    -f "description=shipping-work: the local gate passed on tree $ATTEST_TREE" \
    >/dev/null || rc=$?
  if [[ $rc -ne 0 ]]; then
    _attest_not_posted "gh refused the write to $repo (exit $rc; its own message is above)"
    return 1
  fi

  # Read it back as CI reads it. The combined status keeps each context's
  # latest state, a page of 30 by default, so a whole page is asked for.
  for try in 1 2 3; do
    rc=0
    state=$(gh api --hostname "$host" "repos/$path/commits/$sha/status?per_page=100" --jq "$jq") || rc=$?
    if [[ $rc -eq 0 && "$state" == success ]]; then
      echo "Attestation: $ATTEST_CONTEXT = success posted on $sha ($repo),"
      echo "  and read back through the combined status."
      return 0
    fi
    [[ $try -eq 3 ]] || sleep "$pause"
  done
  if [[ $rc -ne 0 ]]; then
    _attest_not_confirmed "the combined status of $sha could not be read (gh exit $rc; its own message is above)"
  else
    _attest_not_confirmed "the combined status of $sha shows $ATTEST_CONTEXT = ${state:-nothing}"
  fi
  return 1
}
