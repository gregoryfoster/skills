#!/usr/bin/env bash
# detect-stack.sh
# Says what a repo has, so one ship gate serves every repo instead of one
# variant per stack (#537, plan Step 5 rows 1 and 1b).
#
# Two kinds of answer, kept apart on purpose:
#
#   toolchain   decides which CHECKS pre-ship.sh runs. Every one found runs.
#     uv        pyproject.toml plus a uv.lock or a [tool.uv] table. A Poetry
#               or pip project is not one: the gate would `uv run` against a
#               project uv does not manage, so it gets the remedy instead.
#     composer  composer.json at the root, or one level under themes/ or
#               plugins/ (the layout the PHP gate validates).
#     npm       package.json, with composer's reach: at the root, or one level
#               under themes/ or plugins/, where a Sage-style monorepo
#               with themes/ and plugins/ at the root keeps them (#561); a
#               Bedrock repo's web/app/themes/ is not searched. A nested
#               one counts only when git tracks it. pre-ship.sh runs each
#               one's scripts in its own directory.
#
#   framework   decides only which DOCS apply: doc-check.sh's default watch
#               list and which references/stack-*.md to load. Never a check.
#     fastapi   fastapi is a declared dependency.
#     click     click or typer is, and fastapi is not: a service that pulls
#               in click for a management command is still a service.
#     php       any composer toolchain.
#
#   undetermined framework
#               printed instead of a Python framework line when a uv
#               workspace's members could not all be read and none that was
#               declares fastapi. The kind is `undetermined`, not
#               `framework`, so nothing reads it as a stack-<name>.md to load.
#
# The dependency match is a quoted requirement whose name is exactly the
# framework's, case-insensitive — "fastapi>=0.110", "FastAPI[standard]" — so
# "clickhouse-driver" is not click. It reads pyproject.toml as text rather
# than parsing TOML: this runs before any interpreter is known to exist, and a
# miss only costs a doc default, never a check.
#
# A uv workspace (#552): when the root pyproject.toml has a
# [tool.uv.workspace] table, the root and every member's pyproject.toml are
# read together, with the precedence above across all of them, since a
# virtual root declares its members rather than a framework. Members are the
# table's `members` globs resolved from the root, less what its `exclude`
# globs match. Each array is read as text: strings in either quote, on one
# line or across several. Any other spelling, a `**` (bash 3.2 has no
# globstar), a pattern matching no member pyproject.toml, or a member file it
# cannot read makes the framework undetermined, with the reason on stderr.
# No `members` key is a root-only workspace. A `workspace` key under
# [tool.uv] (inline `{…}` or dotted) is not parsed and is undetermined too.
#
# Output: one `kind<TAB>name` line per finding. Nothing found is exit 0 with
# no output.
#
# Usage: bash "<detect-stack.sh>" [--help]
set -euo pipefail

usage() {
  echo "Usage: bash \"$0\" [--help]"
  echo ""
  echo "Prints what this repo has, one tab-separated line per finding:"
  echo "  toolchain uv|composer|npm      which checks the ship gate runs"
  echo "  framework fastapi|click|php    which docs apply (never a check)"
  echo "  undetermined framework         a uv workspace whose members could"
  echo "                                 not all be read; the reason is on stderr"
  echo ""
  echo "Exit codes:"
  echo "  0  done (no output means nothing was detected)"
  echo "  2  not inside a git repository, an unreadable pyproject.toml, a"
  echo "     failing grep, or a bad argument"
}

for arg in "$@"; do
  case "$arg" in
    --help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument '$arg'" >&2; usage >&2; exit 2 ;;
  esac
done

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}
cd "$ROOT"

# Whether any of the files after $1 has a quoted requirement named exactly
# $1: the name, then a version operator, an extras bracket, a marker, a space
# or the closing quote. A grep that fails is a tooling failure, never "no".
declares() {
  local name=$1 rc=0
  shift
  grep -qiE "[\"'][[:space:]]*${name}[[:space:]]*([][<>=!~;,[:space:]\"']|\$)" "$@" || rc=$?
  if [[ $rc -gt 1 ]]; then
    echo "ERROR: grep failed (exit $rc) reading $*" >&2
    exit 2
  fi
  return "$rc"
}

# The strings of a TOML array of strings, into PARSED. Returns 1, leaving
# PARSED empty, for anything else.
PARSED=()
array_strings() {
  local rest=$1
  local array_re="^[[:space:]]*[[][[:space:]]*((\"[^\"]*\"|'[^']*')[[:space:]]*,[[:space:]]*)*((\"[^\"]*\"|'[^']*')[[:space:]]*)?[]][[:space:]]*$"
  local item_re="^[^\"']*(\"([^\"]*)\"|'([^']*)')(.*)$"
  PARSED=()
  [[ $rest =~ $array_re ]] || return 1
  while [[ $rest =~ $item_re ]]; do
    PARSED+=("${BASH_REMATCH[2]}${BASH_REMATCH[3]}")
    rest=${BASH_REMATCH[4]}
  done
}

# The directories one glob names from the root, into HITS: no splitting, no
# match is no hit, and `./` and a trailing `/` are dropped so the members and
# the exclusions compare as the same spelling. The matches are walked by index:
# bash 3.2 joins ${words[@]+"${words[@]}"} into one word under an empty IFS.
HITS=()
glob_dirs() {
  local IFS='' hit i words
  HITS=()
  shopt -s nullglob
  # The pattern is a glob on purpose, and the empty IFS keeps it one word.
  # shellcheck disable=SC2206
  words=($1)
  shopt -u nullglob
  for ((i = 0; i < ${#words[@]}; i++)); do
    hit=${words[i]}
    while [[ $hit == ./* ]]; do hit=${hit#./}; done
    HITS+=("${hit%/}")
  done
}

# The root's [tool.uv.workspace] table: whether there is one, and its
# `members` and `exclude` values, each joined onto one line. `#` starts a
# comment wherever it falls, so a glob that contains one reads as unparseable.
# A `workspace` key in [tool.uv] is the same table spelled inline or dotted,
# which this read does not parse, so it is flagged rather than passed over.
WORKSPACE=0 INLINE=0 MEMBERS_SET=0 MEMBERS_RAW="" EXCLUDE_SET=0 EXCLUDE_RAW=""
store() {
  if [[ $1 == members ]]; then
    MEMBERS_SET=1 MEMBERS_RAW=$2
  else
    EXCLUDE_SET=1 EXCLUDE_RAW=$2
  fi
}
read_workspace_table() {
  local line in_table=0 in_uv=0 key="" value=""
  local header_re='^[[:space:]]*[[]'
  local table_re='^[[:space:]]*[[][[:space:]]*tool[[:space:]]*[.][[:space:]]*uv[[:space:]]*[.][[:space:]]*workspace[[:space:]]*[]][[:space:]]*$'
  local uv_re='^[[:space:]]*[[][[:space:]]*tool[[:space:]]*[.][[:space:]]*uv[[:space:]]*[]][[:space:]]*$'
  local inline_re="^[[:space:]]*[\"']?workspace[\"']?[[:space:]]*[.=]"
  local key_re="^[[:space:]]*[\"']?(members|exclude)[\"']?[[:space:]]*=(.*)$"
  while IFS= read -r line || [[ -n $line ]]; do
    line=${line%%#*}
    if [[ -n $key ]]; then
      value="$value $line"
    elif [[ $line =~ $header_re ]]; then
      in_table=0 in_uv=0
      if [[ $line =~ $table_re ]]; then in_table=1 WORKSPACE=1; fi
      if [[ $line =~ $uv_re ]]; then in_uv=1; fi
      continue
    elif [[ $in_uv -eq 1 && $line =~ $inline_re ]]; then
      WORKSPACE=1 INLINE=1
      continue
    elif [[ $in_table -eq 1 && $line =~ $key_re ]]; then
      key=${BASH_REMATCH[1]} value=${BASH_REMATCH[2]}
    else
      continue
    fi
    if [[ $value == *"]"* ]]; then
      store "$key" "$value"
      key=""
    fi
  done <pyproject.toml
  # Still open at the end of the file: stored unclosed, which no array is.
  if [[ -n $key ]]; then store "$key" "$value"; fi
}

if [[ -f pyproject.toml ]]; then
  if [[ ! -r pyproject.toml ]]; then
    echo "ERROR: pyproject.toml is not readable, so neither the toolchain nor the framework can be read." >&2
    exit 2
  fi
  if [[ -f uv.lock ]] || grep -qE '^[[:space:]]*\[tool\.uv[].]' pyproject.toml; then
    printf 'toolchain\tuv\n'
  fi

  FILES=(pyproject.toml)
  UNDETERMINED=""
  read_workspace_table
  if [[ $INLINE -eq 1 ]]; then
    UNDETERMINED="[tool.uv] spells its workspace as a key, which this text read does not parse"
  fi
  EXCLUDED=()
  if [[ $WORKSPACE -eq 1 && $EXCLUDE_SET -eq 1 && -z $UNDETERMINED ]]; then
    if array_strings "$EXCLUDE_RAW"; then
      for pat in ${PARSED[@]+"${PARSED[@]}"}; do
        glob_dirs "$pat"
        EXCLUDED+=(${HITS[@]+"${HITS[@]}"})
      done
    else
      UNDETERMINED="[tool.uv.workspace] exclude is not an array of strings this text read can parse"
    fi
  fi
  if [[ $WORKSPACE -eq 1 && $MEMBERS_SET -eq 1 && -z $UNDETERMINED ]]; then
    if ! array_strings "$MEMBERS_RAW"; then
      UNDETERMINED="[tool.uv.workspace] members is not an array of strings this text read can parse"
    fi
    for pat in ${PARSED[@]+"${PARSED[@]}"}; do
      if [[ $pat == *"**"* ]]; then
        UNDETERMINED="member pattern '$pat' uses **, which this read does not expand"
        continue
      fi
      glob_dirs "$pat"
      matched=0
      for dir in ${HITS[@]+"${HITS[@]}"}; do
        [[ -f "$dir/pyproject.toml" ]] || continue
        matched=1
        for x in ${EXCLUDED[@]+"${EXCLUDED[@]}"}; do
          if [[ $x == "$dir" ]]; then continue 2; fi
        done
        if [[ -r "$dir/pyproject.toml" ]]; then
          FILES+=("$dir/pyproject.toml")
        else
          UNDETERMINED="$dir/pyproject.toml is not readable"
        fi
      done
      if [[ $matched -eq 0 ]]; then
        UNDETERMINED="member pattern '$pat' matches no pyproject.toml"
      fi
    done
  fi

  # fastapi anywhere decides it, whatever went unread; click needs them all.
  if declares fastapi "${FILES[@]}"; then
    printf 'framework\tfastapi\n'
  elif [[ -n $UNDETERMINED ]]; then
    echo "NOTE: the Python framework is undetermined: $UNDETERMINED." >&2
    printf 'undetermined\tframework\n'
  elif declares click "${FILES[@]}" || declares typer "${FILES[@]}"; then
    printf 'framework\tclick\n'
  fi
fi

# Whether manifest $1 is at the root or one level under themes/ or plugins/:
# the reach of composer and npm alike, so neither misses the other's layout.
present() {
  local f
  if [[ -f "$1" ]]; then return 0; fi
  for f in themes/*/"$1" plugins/*/"$1"; do
    if [[ -f "$f" ]]; then return 0; fi
  done
  return 1
}

# The package.json files one level under themes/ or plugins/ that git tracks
# and the tree has, into NESTED_NPM, themes first. Read from git, not the
# filesystem: a plugin composer installs is gitignored, and its scripts are
# not this repo's to run. pre-ship.sh lists them the same way, so the two
# agree. A failing ls-files is a tooling failure, never "none".
#
# No temp file, so nothing to leak on a signal or a set -e exit (CR 1868):
# git writes straight into the loop, its stderr straight to ours, and its
# exit status follows as one last NUL-terminated `status N` record, since
# bash 3.2 can neither hold NULs in a variable nor wait on a process
# substitution. No listed path can read as that record: each one ends in
# /package.json. A missing record (the lister died first) is a failure too.
NESTED_NPM=()
nested_npm() {
  local parent f status
  for parent in themes plugins; do
    status=""
    # unhardened: only in form; the lister's exit status arrives as the last record and is checked below
    while IFS= read -r -d '' f; do
      case $f in
        "status "*) status=${f#status } ;;
        *) if [[ -f $f ]]; then NESTED_NPM+=("$f"); fi ;;
      esac
    done < <(
      rc=0
      git ls-files -z -- ":(glob)$parent/*/package.json" || rc=$?
      printf 'status %s\0' "$rc"
    )
    if [[ $status != 0 ]]; then
      echo "ERROR: git ls-files failed (exit ${status:-unknown}) listing $parent/*/package.json." >&2
      exit 2
    fi
  done
}

if present composer.json; then
  printf 'toolchain\tcomposer\n'
  printf 'framework\tphp\n'
fi

nested_npm
if [[ -f package.json || ${#NESTED_NPM[@]} -gt 0 ]]; then
  printf 'toolchain\tnpm\n'
fi
