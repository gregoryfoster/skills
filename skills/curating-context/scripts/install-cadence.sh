#!/usr/bin/env bash
# install-cadence.sh — wire the weekly context measurement into a repo as a
# scheduled GitHub Actions workflow.
#
# The thing on the clock is a MEASUREMENT, not a curation. It records one
# `baseline` telemetry row so regrowth, budget adherence and seam accrual
# accumulate as a per-repo series; curation needs judgement and stays
# agent-triggered, prompted by what these rows show. Rationale, and the template
# this renders with its annotations: references/cadence.md (#118).
#
# Idempotent: a re-run rewrites the workflow in place and reports whether
# anything changed. It never commits — but it does set TWO repo-local git
# config values, `merge.ours.driver` and `merge.context-counts.driver`,
# because config is the only place a merge driver can live: neither is a git
# built-in, config is not versioned, and an attribute naming an undefined
# driver is inert (#192, #237).
set -euo pipefail

usage() {
  cat <<'USAGE'
install-cadence.sh — install the weekly context-measurement workflow

Usage:
  install-cadence.sh [options]

Options:
  --cron EXPR      Five-field cron for the schedule. Default: a weekly slot
                   derived from the repo name, so a twelve-repo cohort spreads
                   across the window instead of firing at once.
  --file PATH      Workflow path. Default: .github/workflows/context-cadence.yml
  --ledger PATH    Ledger the cadence records into, relative to the repo root.
                   Default: .skills/context-metrics.jsonl. Threaded through all
                   three places that must agree — the union-merge attribute,
                   the workflow's `git add`, and its error message — because a
                   cadence that measures correctly and stages the wrong path
                   records nothing.
  --check          Report what is installed; change nothing. Six guarantees
                   are reported independently — the workflow, the driver setup
                   inside it, the ledger's union merge, the calibration files'
                   merge attributes, the `ours` driver the ratio attribute
                   needs to exist at all, and the newest-wins driver behind the
                   counts attribute — because each is its own way to lose a
                   row, and one combined "ok" would have read green through
                   all of #173, #192 and #237.
                   Exit 0 all present, 3 any missing.
  --uninstall      Remove the workflow file AND every merge attribute it
                   installed, leaving .gitattributes as it found it (the file
                   itself goes only if nothing else was in it). The recorded
                   rows stay — they are the series — and so do both merge
                   drivers: a defined driver with no attribute pointing at it
                   never runs, and other merge rules may depend on them.
  --print          Write the rendered workflow to stdout and exit; touch
                   nothing. Still needs to be inside a git repo: the default
                   schedule is derived from the repo identity.
  -h, --help       Show this help and exit 0.

What it does:
  Ensures .gitattributes carries `<ledger> merge=union`.
  The ledger is append-only, so a scheduled append racing a human commit lands
  on the same last line and cannot auto-merge; without the union driver the
  push is rejected, the retry's rebase conflicts, and the week's row is lost.
  It must be committed BEFORE the first concurrent run — git resolves using the
  attributes in the tree being replayed onto.

  Sets two merge drivers in this clone's git config. The ratio file carries
  `merge=ours` (`merge.ours.driver true` — regenerate on collision, never
  reconcile), and the counts file carries `merge=context-counts`
  (`merge.context-counts.driver` running merge-token-counts.sh — per row,
  newest wins: on a collision each path keeps the row whose bytes match the
  file in the tree, so the cadence's fresh measurement survives whichever
  side of the merge it lands on, #237). Neither driver is a git built-in, so
  the attributes alone are inert. Config is not versioned, so this is per
  clone and does not travel with the commit — run this (or the two config
  one-liners) once in every checkout, and use --check to confirm.

  Renders .github/workflows/context-cadence.yml, which weekly:
    1. checks out with submodules (the skill is reached through a symlink into
       skills-vendor/, which dangles without them),
    2. preflights the credential FIRST,
    3. sweeps seams, measures once with --exact, records a `baseline` row,
    4. commits that one JSONL line to the default branch,
    5. emits ::warning:: when the surface is over budget or seams accrued.

  It never runs on pull_request and never blocks a merge. Turning the budget
  into a merge gate is a different job (#88), with its own sequencing rule.

REQUIRED, or the job records nothing at all:
  ANTHROPIC_API_KEY must exist as a repository secret. Without it --exact
  degrades to an offline estimate and record-telemetry.sh REFUSES the append
  (exit 4) against a ledger of exact rows. The failure is silence, not a bad
  number, which is why the workflow preflights the credential in its first step.

    gh secret set ANTHROPIC_API_KEY --repo <owner>/<repo>

It does not commit. Review the diff and commit with your normal gate.

Exit codes:
  0  installed, uninstalled, unchanged, or printed
  1  usage error, or not in a git repo
  2  could not rewrite .gitattributes — nothing was changed
  3  --check only: a workflow, merge attribute or merge driver is missing
  4  could not set a merge driver — its calibration attribute is inert
USAGE
}

CRON=""
WF_PATH=".github/workflows/context-cadence.yml"
LEDGER=".skills/context-metrics.jsonl"
LEDGER_SET=0
MODE="install"

while [ $# -gt 0 ]; do
  case "$1" in
    --cron) CRON="${2:?--cron needs a cron expression}"; shift 2 ;;
    --file) WF_PATH="${2:?--file needs a path}"; shift 2 ;;
    --ledger) LEDGER="${2:?--ledger needs a path}"; LEDGER_SET=1; shift 2 ;;
    --check) MODE="check"; shift ;;
    --uninstall) MODE="uninstall"; shift ;;
    --print) MODE="print"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

# Five whitespace-separated fields. Deliberately shallow — the point is to catch
# a prose string or a six-field spec, not to reimplement cron.
if [ -n "$CRON" ]; then
  # `set -f` is load-bearing, not decoration. Word splitting is what counts the
  # fields, but the same unquoted expansion also globs — and a cron expression
  # is mostly `*`. Run from any directory with visible files, `0 15 * * 1`
  # expanded to one field per file and every valid schedule was refused with a
  # nonsense count. Found by the shellcheck gate's SC2086 (#90).
  set -f
  # Deliberate word split; globbing is off for exactly these two lines.
  # shellcheck disable=SC2086
  set -- $CRON
  set +f
  [ "$#" -eq 5 ] || {
    echo "ERROR --cron needs five fields (got $#): '$CRON'" >&2
    echo "      e.g. --cron '0 15 * * 1'" >&2
    exit 1; }
fi

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "ERROR not inside a git repository" >&2; exit 1; }
WF="$ROOT/$WF_PATH"

# What the INSTALLED workflow measures, which is not necessarily what this
# invocation was told. Deriving the ledger from the flag alone meant every mode
# silently assumed the caller repeated --ledger: --check on a repo installed with
# a custom ledger reported the attribute MISSING and said to re-run, and doing so
# appended a SECOND attribute for the default path and rewrote the workflow back
# to the default. Following the tool's own advice broke a correct install.
INSTALLED_LEDGER=""
if [ -f "$WF" ]; then
  INSTALLED_LEDGER="$(sed -n 's/^ *git add -- "\(.*\)"$/\1/p' "$WF" | head -1)"
fi
# An explicit --ledger always wins — that is how you deliberately change it.
# Otherwise describe the repo rather than the invocation.
if [ "$LEDGER_SET" -eq 0 ] && [ -n "$INSTALLED_LEDGER" ]; then
  LEDGER="$INSTALLED_LEDGER"
fi

# ONE definition, above the mode dispatch, because --check reads this and
# ensure_attr writes it. They lived forty lines apart with the string typed
# twice, so the reader and the writer could drift — and a --check reporting
# "yes" against a line the installer no longer writes is worse than no check.
ATTR_FILE="$ROOT/.gitattributes"
ATTR_LINE="$LEDGER merge=union"

# The two calibration files the same --exact run rewrites (#145). The workflow
# stages all THREE paths, so protecting only the ledger left the other two to
# conflict on exactly the race the ledger was protected against (#173).
#
# Union is the wrong answer for both: it produces two values for one key, and
# the estimators would silently read whichever they hit first — worse than a
# conflict, because nothing reports it. Beyond that the two files part ways:
#
# The RATIO is one repo-wide scalar, a pure function of the tree at
# measurement time with nothing for a per-row merge to key on, so on a
# collision the right answer is always "recompute", never "reconcile" —
# merge=ours keeps whatever is already on the branch and the next --exact run
# recomputes it. A week of stale ratio is self-correcting and shallow: it only
# prices files never counted exactly.
#
# The COUNTS file is keyed rows (<bytes> <tokens> <path>), and merge=ours was
# the wrong shape there (#237): `ours` keeps the side of whoever RUNS the
# merge, which is unrelated to which side measured more recently, and the
# cadence bot only ever pushes to the default branch — so it was structurally
# always the side that lost, and its fresh measurement was silently reverted.
# The context-counts driver merges per row instead: one-sided edits merge
# three-way, and a genuine collision keeps the row whose bytes match the file
# in the tree.
RATIO_PATH=".skills/context-token-ratio"
COUNTS_PATH=".skills/context-token-counts"
ATTR_RATIO="$RATIO_PATH merge=ours"
COUNTS_DRIVER_NAME="context-counts"
ATTR_COUNTS="$COUNTS_PATH merge=$COUNTS_DRIVER_NAME"
# What pre-#237 installs carry; ensure_attr migrates it and --check names it.
ATTR_COUNTS_STALE="$COUNTS_PATH merge=ours"

# The attributes above name drivers; these are the drivers. `union` and
# `binary` are built in, `ours` and `context-counts` are NOT — an entry naming
# a driver with no definition in config makes git fall back to the 3-way merge
# and conflict exactly as if the attribute were absent, markers and all. #173
# set the ours driver correctly but INSIDE the workflow job, on a throwaway
# runner; git config is not versioned, so every developer clone was
# unprotected while --check reported the guarantee as satisfied off the
# .gitattributes grep alone (#192).
#
# Independent things, so independent reports and independent repairs: the
# attributes live in the tree and travel with a clone, the drivers live in
# config and never do.
#
# `true` is the whole ours driver. It succeeds without writing, which leaves
# the copy already on the branch in place and drops the replayed one — exactly
# the regenerate-on-collision semantics the ratio wants.
DRIVER_KEY="merge.ours.driver"
DRIVER_VALUE="true"
DRIVER_FIX="git config $DRIVER_KEY $DRIVER_VALUE"

# The newest-wins driver is a script, resolved relative to this installer so
# it lands wherever the vendored skill's scripts/ sits in the consumer repo.
# Stored repo-relative when it is inside the repo — git runs merge drivers
# from the top of the working tree, and a relative path survives the checkout
# moving — absolute otherwise (a test fixture pointing at the source tree).
MERGE_SCRIPT_NAME="merge-token-counts.sh"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MERGE_SCRIPT="$SCRIPT_DIR/$MERGE_SCRIPT_NAME"
case "$MERGE_SCRIPT" in
  "$ROOT"/*) MERGE_SCRIPT_CFG="${MERGE_SCRIPT#"$ROOT"/}" ;;
  *)         MERGE_SCRIPT_CFG="$MERGE_SCRIPT" ;;
esac
COUNTS_DRIVER_KEY="merge.$COUNTS_DRIVER_NAME.driver"
COUNTS_DRIVER_VALUE="bash '$MERGE_SCRIPT_CFG' %O %A %B %P"
COUNTS_DRIVER_FIX="git config $COUNTS_DRIVER_KEY \"$COUNTS_DRIVER_VALUE\""

ATTR_NOTE_1="# Append-only telemetry: concurrent appends must union-merge, or a"
ATTR_NOTE_2="# scheduled measurement racing a human commit conflicts and is lost."
ATTR_NOTE_3="# Calibration is regenerated, never reconciled: on a collision keep"
ATTR_NOTE_4="# the branch's copy and let the next --exact run recompute it."
ATTR_NOTE_5="# The per-file calibration merges per row (#237): on a collision each"
ATTR_NOTE_6="# path keeps the row whose bytes match the file in the tree."

# strip_attr's failure path removes this itself; the trap covers the signal case
# it cannot, so a killed run never strands a temp file beside .gitattributes for
# `git add -A` to collect (CR finding 16).
trap 'rm -f "$ATTR_FILE.tmp"' EXIT

# Every comment line this installer has ever written, newline-joined so the
# strip below matches all generations of the block in one pass.
ATTR_NOTES_ALL="$ATTR_NOTE_1
$ATTR_NOTE_2
$ATTR_NOTE_3
$ATTR_NOTE_4
$ATTR_NOTE_5
$ATTR_NOTE_6"

# Remove only the attribute LINE for a given prefix, comments untouched. The
# migration path needs exactly this: swapping the counts attribute must not
# take the heading that still introduces the ratio line beside it (#237).
strip_line() {
  [ -f "$ATTR_FILE" ] || return 0
  awk -v want="$1" '
    { line = $0; sub(/^[ \t]+/, "", line) }
    line !~ /^#/ && index(line, want) == 1 { next }
    { print }
  ' "$ATTR_FILE" >"$ATTR_FILE.tmp" || {
    # `awk … >tmp && mv` with an unconditional "removed …" after it is the shape
    # that let install-refresh.sh report a change it had not made: under set -e
    # the failure of the FIRST element of an && list is exempt, so the log ran
    # anyway and the temp file was orphaned (CR findings 11, 13). Far less
    # likely to fire here than a jq parse error on operator-edited JSON, but it
    # is the same idiom and would tell the same lie.
    rm -f "$ATTR_FILE.tmp"
    echo "ERROR could not rewrite .gitattributes — nothing was changed" >&2
    exit 2; }
  mv -f "$ATTR_FILE.tmp" "$ATTR_FILE"
}

# Remove OUR block for a given attribute: the line itself plus every comment
# line this installer writes. Factored rather than inlined twice — a
# superseded ledger and an uninstall want the same operation, and hand-rolling
# this awk a second time is the duplication the last three rounds kept finding.
strip_attr() {
  [ -f "$ATTR_FILE" ] || return 0
  # Through the environment, not -v: BSD awk rejects a -v value containing a
  # literal newline ("newline in string"), and the note list is one per line.
  ATTR_NOTES_ALL="$ATTR_NOTES_ALL" awk '
    BEGIN {
      n = split(ENVIRON["ATTR_NOTES_ALL"], N, "\n")
      for (i = 1; i <= n; i++) drop[N[i]] = 1
    }
    { line = $0; sub(/^[ \t]+/, "", line) }
    line in drop { next }
    { print }
  ' "$ATTR_FILE" >"$ATTR_FILE.tmp" || {
    rm -f "$ATTR_FILE.tmp"
    echo "ERROR could not rewrite .gitattributes — nothing was changed" >&2
    exit 2; }
  mv -f "$ATTR_FILE.tmp" "$ATTR_FILE"
  strip_line "$1"
  # If nothing but blank lines is left, the file was ours to begin with.
  if [ ! -s "$ATTR_FILE" ] || ! grep -q '[^[:space:]]' "$ATTR_FILE"; then
    rm -f "$ATTR_FILE"
  fi
}

# Anchored, and comment lines are skipped. A substring grep reported a
# COMMENTED-OUT attribute as present — and commenting it out is exactly how
# somebody disables it, so the check asserted a guarantee that was switched off
# and the failure landed later as a row lost to a race.
has_attr() {
  [ -f "$ATTR_FILE" ] || return 1
  awk -v want="$1" '
    { line = $0; sub(/^[ \t]+/, "", line) }
    line ~ /^#/ { next }
    index(line, want) == 1 { found = 1; exit }
    END { exit !found }
  ' "$ATTR_FILE"
}

# `env -u GIT_DIR -u GIT_WORK_TREE` is load-bearing, and it is the only reason
# this is a function rather than two inline `git config` calls.
#
# This is the first thing in this script that WRITES anything outside the
# working tree, so it is the first that can escape the repo it was pointed at.
# An inherited GIT_DIR beats -C: git resolves the config file from GIT_DIR and
# ignores the directory entirely. Git exports GIT_DIR to every hook process, and
# from a LINKED WORKTREE it is absolute — so a run under a pre-commit hook, or
# any test harness that forgets to scrub the environment, reads and writes the
# SHARED .git/config of the main checkout while `--check` reports on some other
# directory's .gitattributes. Observed doing exactly that: the structural suite
# set merge.ours.driver in this repo's real config from a temp-directory
# fixture. Stripping both vars makes -C authoritative, and a directory that is
# not a repo then fails loudly instead of writing somewhere else (#189, #192).
git_config() {
  env -u GIT_DIR -u GIT_WORK_TREE git -C "$ROOT" config "$@"
}

# Whatever the named driver currently resolves to in this repo, empty if
# nothing does.
#
# `--get` searches system, global and local, and any of the three protects the
# repo — a cohort that sets a driver in ~/.gitconfig is correct, and telling
# it to re-run would be a false alarm to match the false assurance #192 is
# about. Empty is treated as missing: `git config merge.ours.driver ""` exits 0
# and defines a key with no command, which git then fails the merge on.
driver_value() {
  git_config --get "$1" 2>/dev/null || true
}

# The script the configured newest-wins command names, resolved the way git
# will resolve it: relative paths against the worktree top. Empty when the
# value does not carry a recognisable quoted path — a deliberately customised
# driver is not this script's to second-guess.
counts_driver_script() {
  local value="$1" path
  case "$value" in
    *"'"*"'"*) ;;
    *) return 0 ;;
  esac
  path="${value#*\'}"
  path="${path%%\'*}"
  case "$path" in
    /*) printf '%s' "$path" ;;
    ?*) printf '%s' "$ROOT/$path" ;;
  esac
}

# Every path the rendered workflow stages, paired with the attribute that keeps
# a concurrent commit from destroying it. Iterated rather than checked one by
# one, so adding a staged path to the template and forgetting its attribute is
# a diff in ONE list instead of a silent gap between two places — which is
# exactly how the calibration files went unprotected for #145's whole life.
ATTR_ALL="$ATTR_LINE
$ATTR_RATIO
$ATTR_COUNTS"

has_all_attrs() {
  local line
  while IFS= read -r line; do
    has_attr "$line" || return 1
  done <<EOF
$ATTR_ALL
EOF
  return 0
}

if [ "$MODE" = "check" ]; then
  # Reported independently. The two are separate failure modes — a workflow with
  # no merge attribute loses a row to the first race, and an attribute with no
  # workflow measures nothing — and gating the second report on the first hid
  # whichever one you were not looking for.
  rc=0
  if [ -f "$WF" ]; then
    echo "workflow:           $WF_PATH"
    sed -n 's/^ *- cron: *\(.*\)$/  schedule:         \1/p' "$WF"
    # The workflow is the THIRD place the drivers must exist — the runner is
    # a fresh clone, so nothing set here or in any developer checkout reaches
    # it. A workflow rendered before #237 rebases without the newest-wins
    # driver and conflicts on the counts file.
    if grep -qF "$COUNTS_DRIVER_KEY" "$WF"; then
      echo "workflow drivers:   yes (defined inside the commit step)"
    else
      echo "workflow drivers:   STALE — the installed workflow predates the"
      echo "                    per-row counts merge (#237); its rebase would"
      echo "                    conflict on $COUNTS_PATH."
      echo "                    Re-run install-cadence.sh to re-render it."
      rc=3
    fi
  else
    echo "workflow:           MISSING ($WF_PATH)"
    rc=3
  fi
  if has_attr "$ATTR_LINE"; then
    echo "ledger union merge: yes ($ATTR_LINE)"
  else
    echo "ledger union merge: MISSING — concurrent appends will conflict and the"
    echo "                    row is lost. Re-run install-cadence.sh to add it."
    rc=3
  fi
  # Reported as its own line, not folded into the one above. The workflow
  # stages three paths and each is a separate way to lose the row; a single
  # "attributes: ok" would have read green through the whole of #173.
  if has_attr "$ATTR_RATIO" && has_attr "$ATTR_COUNTS"; then
    echo "calibration merge:  yes (ratio regenerates, counts merge per row)"
  else
    echo "calibration merge:  MISSING — the workflow also stages"
    echo "                    $RATIO_PATH and $COUNTS_PATH,"
    echo "                    which conflict on the same race the ledger is"
    echo "                    protected against. Re-run install-cadence.sh."
    if has_attr "$ATTR_COUNTS_STALE"; then
      echo "                    ($COUNTS_PATH still carries the pre-#237"
      echo "                    \`merge=ours\` line, which silently reverts the"
      echo "                    cadence's measurements; re-running migrates it.)"
    fi
    rc=3
  fi
  # The mechanism behind the attribute above, checked separately BECAUSE it is
  # a separate thing to lose. The attribute is committed and travels with a
  # clone; the driver is config and never does, so a fresh clone of a correctly
  # installed repo has one and not the other — and reporting them together is
  # what told the second cadence pilot the collision case was handled when it
  # was not (#192).
  driver="$(driver_value "$DRIVER_KEY")"
  if [ -n "$driver" ]; then
    echo "ours merge driver:  yes ($DRIVER_KEY=$driver)"
  else
    echo "ours merge driver:  MISSING — \`ours\` is not a driver git defines"
    echo "                    for you, so the ratio attribute above is inert"
    echo "                    and conflicts as if absent. Config is not"
    echo "                    versioned: fix per clone."
    # Don't send a worktree run at the installer — ensure_driver refuses there
    # by design, so "re-run install-cadence.sh" would be a loop (#199 CR round
    # 2, finding 11). Name the checkout that can actually take the write.
    if [ -f "$ROOT/.git" ]; then
      echo "                    This is a linked worktree, whose --local writes"
      echo "                    the main checkout's shared config — set it THERE,"
      echo "                    not here, and not by re-running this installer:"
    else
      echo "                    Here, or by re-running install-cadence.sh:"
    fi
    echo "                      $DRIVER_FIX"
    rc=3
  fi
  # The counts driver, on its own line for the same reason: it is a separate
  # key protecting a separate file, and it has one failure mode the ours
  # driver cannot have — a defined command whose script is not there (a
  # vendored skill behind an uninitialised submodule), which git treats
  # exactly like no driver at all.
  counts_driver="$(driver_value "$COUNTS_DRIVER_KEY")"
  if [ -z "$counts_driver" ]; then
    echo "newest-wins driver: MISSING — the counts attribute above names the"
    echo "                    \`$COUNTS_DRIVER_NAME\` driver, which git does not"
    echo "                    define, so it is inert and conflicts as if"
    echo "                    absent. Config is not versioned: fix per clone."
    if [ -f "$ROOT/.git" ]; then
      echo "                    Set it in the MAIN checkout, not this worktree:"
    else
      echo "                    Here, or by re-running install-cadence.sh:"
    fi
    echo "                      $COUNTS_DRIVER_FIX"
    rc=3
  else
    counts_script="$(counts_driver_script "$counts_driver")"
    if [ -n "$counts_script" ] && [ ! -f "$counts_script" ]; then
      echo "newest-wins driver: BROKEN — $COUNTS_DRIVER_KEY is set, but the"
      echo "                    script it names does not exist:"
      echo "                      $counts_script"
      echo "                    (dangling vendored symlink? run \`git submodule"
      echo "                    update --init --recursive\`, or point the driver"
      echo "                    at the real script:)"
      echo "                      $COUNTS_DRIVER_FIX"
      rc=3
    else
      echo "newest-wins driver: yes ($COUNTS_DRIVER_KEY=$counts_driver)"
    fi
  fi
  exit "$rc"
fi

if [ "$MODE" = "uninstall" ]; then
  if [ -f "$WF" ]; then
    rm -f "$WF"
    echo "uninstalled: removed $WF_PATH"
  else
    echo "nothing to remove: no $WF_PATH"
  fi
  # Every attribute this installer EVER wrote, not just the current set — an
  # uninstall that leaves the pre-#237 counts line behind is the same
  # half-state --check exists to catch.
  while IFS= read -r attr; do
    if has_attr "$attr"; then
      strip_attr "$attr"
      echo "removed the .gitattributes entry: $attr"
    fi
  done <<EOF
$ATTR_ALL
$ATTR_COUNTS_STALE
EOF
  # The attributes come out; the drivers deliberately do not. `ours` is
  # generic — any other `merge=ours` rule in the repo depends on it, and
  # unsetting it here would break attributes this script never wrote. The
  # newest-wins driver is this skill's own, but with nothing pointing at it a
  # defined driver simply never runs, and unsetting config is one more
  # worktree-shaped write (#189) this script has no need to make. Said out
  # loud rather than left silent: the installer changed config, so the
  # uninstall has to account for it either way.
  if [ -n "$(driver_value "$DRIVER_KEY")" ]; then
    echo "note: left $DRIVER_KEY set — it is generic, and other merge=ours"
    echo "      rules in this repo may depend on it. Unset it by hand if not."
  fi
  if [ -n "$(driver_value "$COUNTS_DRIVER_KEY")" ]; then
    echo "note: left $COUNTS_DRIVER_KEY set — with no attribute naming it, a"
    echo "      defined driver never runs. Unset it by hand if you want it gone."
  fi
  echo "note: the recorded rows were left in place — they are the series."
  exit 0
fi

# Stagger the cohort. Twelve repos on one cron produce twelve simultaneous
# count_tokens bursts and twelve commits in the same minute; worse, they all
# land in GitHub's most contended slot (the top of the hour), where scheduled
# runs are delayed most. Derive an offset from the repo name so the spread needs
# no per-repo decision and is stable across re-runs of this installer.
if [ -z "$CRON" ]; then
  # The ORIGIN basename, not the checkout directory. #102 fixed this same latent
  # bug in record-telemetry.sh, where a worktree path recorded
  # `feat-161-curating-context` as the repo; here it would only make two repos
  # draw the same slot, but the precedence should not differ between scripts.
  ORIGIN="$(git remote get-url origin 2>/dev/null)" || ORIGIN=""
  if [ -n "$ORIGIN" ]; then
    NAME="${ORIGIN%/}"; NAME="${NAME##*[/:]}"; NAME="${NAME%.git}"
  else
    NAME="$(basename "$ROOT")"
  fi
  # cksum is POSIX and stable across platforms, unlike $RANDOM or md5/md5sum.
  H="$(printf '%s' "$NAME" | cksum | cut -d' ' -f1)"
  MIN=$(( H % 60 ))
  HOUR=$(( 13 + (H / 60) % 6 ))   # 13:00-18:00 UTC — inside a working day
  DOW=$(( 1 + (H / 360) % 5 ))    # Mon-Fri; weekends delay hardest
  CRON="$MIN $HOUR * * $DOW"
fi

# The ledger is append-only, so two appends land on the SAME last line and git
# cannot auto-merge them: a human commit during the measurement makes the push a
# non-fast-forward, and the retry's rebase then halts on a conflict, leaving
# markers in the ledger and the week's row lost. Verified against a real remote.
#
# `merge=union` is the fix, and it must be COMMITTED BEFORE the first concurrent
# run — git resolves the merge using the attributes in the tree being replayed
# onto, so an attribute added after the fact does not rescue the conflict that
# motivated it.

# One attribute plus the two comment lines that introduce it, appended only
# when absent. The heading is guarded on its own first line rather than on the
# attribute: emitting it whenever the attribute was missing left a second copy
# above a lone repaired line, on exactly the partial-repair path this exists
# for (CR finding 4).
append_attr() {
  local attr="$1" note_a="$2" note_b="$3"
  has_attr "$attr" && return 0
  if [ ! -f "$ATTR_FILE" ] || ! grep -qF "$note_a" "$ATTR_FILE"; then
    printf '\n%s\n%s\n' "$note_a" "$note_b" >>"$ATTR_FILE"
  fi
  printf '%s\n' "$attr" >>"$ATTR_FILE"
  echo "wrote .gitattributes: $attr"
}

ensure_attr() {
  # A deliberate ledger change supersedes the old attribute. Leaving it makes
  # .gitattributes accumulate one dead line per reconfiguration and makes
  # --check's output ambiguous about which one is live.
  if [ -n "$INSTALLED_LEDGER" ] && [ "$INSTALLED_LEDGER" != "$LEDGER" ]; then
    stale="$INSTALLED_LEDGER merge=union"
    if [ -f "$ATTR_FILE" ] && grep -qF "$stale" "$ATTR_FILE"; then
      strip_attr "$stale"
      echo "removed superseded .gitattributes line: $stale"
    fi
  fi
  # The pre-#237 counts attribute is superseded the same way — merge=ours on a
  # keyed-row file silently reverts the cadence's fresh measurements. Only the
  # LINE comes out: the heading beside it still introduces the ratio entry.
  # That population is every repo installed between #173 and #237, including
  # the ones whose --check read green.
  if has_attr "$ATTR_COUNTS_STALE"; then
    strip_line "$ATTR_COUNTS_STALE"
    echo "removed superseded .gitattributes line: $ATTR_COUNTS_STALE (#237)"
  fi
  if has_all_attrs; then
    echo "unchanged: .gitattributes already protects all three staged paths"
    return 0
  fi
  # Append rather than overwrite: the file routinely carries linguist and
  # line-ending rules that are none of this script's business.
  if [ -s "$ATTR_FILE" ] && [ "$(tail -c 1 "$ATTR_FILE" | wc -l)" -eq 0 ]; then
    printf '\n' >>"$ATTR_FILE"
  fi
  # Each block appended only if absent, so a repo that installed before the
  # calibration attributes existed (#173) — or before the counts file left
  # merge=ours (#237) — gains exactly what it is missing rather than a
  # duplicated ledger line beside it.
  append_attr "$ATTR_LINE"   "$ATTR_NOTE_1" "$ATTR_NOTE_2"
  append_attr "$ATTR_RATIO"  "$ATTR_NOTE_3" "$ATTR_NOTE_4"
  append_attr "$ATTR_COUNTS" "$ATTR_NOTE_5" "$ATTR_NOTE_6"
}

# The second half of the calibration guarantee, and the half that cannot be
# committed. ensure_attr puts `merge=ours` in the tree; without this the entry
# is a name for a driver that does not exist and git conflicts as if it were
# absent. #173 set it inside the workflow job, which protected the runner and
# nobody else (#192).
#
# --local, and only when nothing already answers. A repo that resolves `ours`
# through ~/.gitconfig is protected, and writing a local override of somebody's
# deliberate global would be this script exceeding its brief.
# DRIVER_STATE is what ensure_driver DID, and the closing NEXT block reads it
# rather than assuming. Every early return below is a path on which nothing was
# written, and a closing paragraph that says "the setting above" on those paths
# is a tool claiming a change it did not make — the failure this whole backlog
# exists to remove (#199 CR round 2, finding 8).
DRIVER_STATE="unset"

ensure_driver() {
  local ours counts
  ours="$(driver_value "$DRIVER_KEY")"
  counts="$(driver_value "$COUNTS_DRIVER_KEY")"
  if [ -n "$ours" ] && [ -n "$counts" ]; then
    echo "unchanged: $DRIVER_KEY and $COUNTS_DRIVER_KEY are already set"
    DRIVER_STATE="already"
    return 0
  fi
  # Scrubbing GIT_DIR made -C authoritative about WHICH repo. It says nothing
  # about which checkout of that repo, and `--local` from a LINKED WORKTREE
  # writes the shared .git/config of the main checkout — that is what `--local`
  # means without extensions.worktreeConfig, which is unset here and in every
  # consumer that has not deliberately turned it on.
  #
  # So the one remaining way for this write to surprise someone is an agent
  # running the installer inside its own worktree and silently editing the
  # orchestrator's config. That is #189's class exactly, and it cost a batch
  # salvage in #199 — the same batch this guard was written in. Refuse rather
  # than warn: the value is repo-wide, so the operator loses nothing by setting
  # it from the checkout that owns the config, and a warning printed into an
  # agent's scrollback is not read by anyone.
  #
  # A linked worktree has .git as a FILE pointing at the real git dir; the main
  # checkout has it as a directory. Cheapest reliable discriminator there is.
  if [ -f "$ROOT/.git" ]; then
    echo "note: $ROOT is a linked worktree, whose \`git config --local\` writes" >&2
    echo "      the SHARED config of the main checkout. Refusing to set the" >&2
    echo "      merge drivers from here (#189). The attributes are installed;" >&2
    echo "      run these once in the main checkout:" >&2
    echo "        $DRIVER_FIX" >&2
    echo "        $COUNTS_DRIVER_FIX" >&2
    DRIVER_STATE="worktree"
    return 0
  fi
  # Loud, not tolerant. A config write failing (unwritable .git/config, a repo
  # opened read-only) leaves exactly the state this issue is about — attributes
  # present, driver absent, everything looking installed — and swallowing it
  # would rebuild the false assurance one layer down.
  if [ -z "$ours" ]; then
    git_config --local "$DRIVER_KEY" "$DRIVER_VALUE" || {
      echo "ERROR could not set $DRIVER_KEY in $ROOT — the ratio attribute" >&2
      echo "      this installer just wrote is INERT until it is set:" >&2
      echo "        $DRIVER_FIX" >&2
      exit 4; }
    echo "set git config: $DRIVER_KEY=$DRIVER_VALUE (this clone only)"
  fi
  if [ -z "$counts" ]; then
    git_config --local "$COUNTS_DRIVER_KEY" "$COUNTS_DRIVER_VALUE" || {
      echo "ERROR could not set $COUNTS_DRIVER_KEY in $ROOT — the counts" >&2
      echo "      attribute this installer just wrote is INERT until it is" >&2
      echo "      set:" >&2
      echo "        $COUNTS_DRIVER_FIX" >&2
      exit 4; }
    echo "set git config: $COUNTS_DRIVER_KEY=$COUNTS_DRIVER_VALUE (this clone only)"
  fi
  DRIVER_STATE="set"
}

render() {
  cat <<YAML
name: context-cadence

# Weekly measurement of the agent-context surface (#118). Records one \`baseline\`
# telemetry row so regrowth, budget adherence and seam accrual accumulate as a
# per-repo series.
#
# It does NOT curate. Curation needs judgement — classify each section, verify
# each claim, decide what relocates where — and that stays agent-triggered,
# prompted by what these rows show. Rationale and the annotated template:
# curating-context/references/cadence.md
#
# Generated by install-cadence.sh. Re-run it rather than editing by hand.
#
# REQUIRES the ANTHROPIC_API_KEY repository secret. Without it --exact degrades
# to an offline estimate and record-telemetry.sh refuses the append, so the job
# records NOTHING, silently, every week. The credential is preflighted first.

on:
  schedule:
    - cron: '$CRON'
  workflow_dispatch:

# contents: write because the job appends one JSONL line and pushes it. That is
# append-only telemetry, not code.
permissions:
  contents: write

concurrency:
  group: context-cadence
  cancel-in-progress: false

jobs:
  measure:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    # NOT continue-on-error. A red run here means "this repo is not measuring",
    # which is true and worth seeing — the credential preflight exists to make
    # that failure loud, and continue-on-error would restore the silence at the
    # one level a human actually looks at. Drift is reported as ::warning::
    # below and never fails the job, so red always means the mechanism broke,
    # never that the surface grew.
    steps:
      # submodules: recursive is load-bearing — the skill is vendored under
      # skills-vendor/ and reached through a symlink, which dangles without it.
      # fetch-depth: 0 because the push path rebases when a human commit lands
      # during the measurement, and rebasing on a depth-1 clone lacks the history
      # to replay onto.
      # @v5, not @v4: v4 targets Node 20, which runners now force onto Node 24
      # with a deprecation warning on every run. Twelve repos are about to adopt
      # this template, and sweeping twelve for a warning we could have not
      # written is the avoidable version of the problem (#163).
      - uses: actions/checkout@v5
        with:
          submodules: recursive
          fetch-depth: 0

      - name: Heal vendored symlinks
        run: '[ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh'

      - name: Resolve the skill scripts
        run: |
          N=curating-context S=measure-context.sh SD=
          for d in scripts ".claude/skills/\$N/scripts" "skills/\$N/scripts"; do
            [ -f "\$d/\$S" ] && { SD="\$d"; break; }
          done
          echo "SKILL_SCRIPTS=\${SD:?curating-context scripts not found}" >>"\$GITHUB_ENV"

      # FIRST, not last: without a credential every later step does its work and
      # the append is refused at the end.
      - name: Preflight the credential
        env:
          ANTHROPIC_API_KEY: \${{ secrets.ANTHROPIC_API_KEY }}
        run: bash "\$SKILL_SCRIPTS/measure-context.sh" --check-credential

      # Exits 3 when there are new seams, which is a finding rather than a
      # failure here — the count goes on the row either way.
      #
      # --base-ledger, NOT --base HEAD. On a clean checkout the policy file at
      # HEAD and the one in the working tree are the same content, so the diff
      # is empty and the one class that needs a base — moved-title — was zero
      # in every scheduled run, in every repo, forever (#169). The ledger's
      # newest repo_commit is the previous measurement, so the sweep spans the
      # interval since it. With no such row the report SAYS the interval is
      # empty rather than presenting a standing count as a week's accrual.
      - name: Sweep the seams
        run: |
          bash "\$SKILL_SCRIPTS/check-seams.sh" --base-ledger "$LEDGER" >/tmp/seams.txt 2>&1 || true
          tail -20 /tmp/seams.txt
          echo "SEAMS=\$(sed -n 's/^seams: \([0-9]*\)\$/\1/p' /tmp/seams.txt | tail -1)" >>"\$GITHUB_ENV"
          echo "SEAMS_ACKED=\$(sed -n 's/^seams_acked: \([0-9]*\)\$/\1/p' /tmp/seams.txt | tail -1)" >>"\$GITHUB_ENV"

      # Measured ONCE — the drift report below reads this file rather than
      # re-running --exact, which would disagree with the row just recorded.
      - name: Measure and record
        env:
          ANTHROPIC_API_KEY: \${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          bash "\$SKILL_SCRIPTS/measure-context.sh" --exact >/tmp/ctx.json
          bash "\$SKILL_SCRIPTS/record-telemetry.sh" --baseline=scheduled \\
              --ledger "$LEDGER" \\
              \${SEAMS:+--seams "\$SEAMS"} \${SEAMS_ACKED:+--seams-acked "\$SEAMS_ACKED"} \\
              --print-trend </tmp/ctx.json

      - name: Commit the row
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          # Neither merge driver is a git built-in and the runner is a fresh
          # clone, so without these two lines the .gitattributes entries are
          # inert and the calibration files conflict as if unprotected (#192).
          # \`true\` keeps the branch's ratio; the next --exact recomputes (#173).
          git config merge.ours.driver true
          # The counts file merges per row (#237): a collision keeps, per path,
          # the row whose bytes match the file in the tree.
          git config $COUNTS_DRIVER_KEY "bash \\"\$SKILL_SCRIPTS/$MERGE_SCRIPT_NAME\\" %O %A %B %P"
          # Staged separately, and the row is NOT tolerant of failure. One
          # \`git add\` over both paths stages NOTHING when either is missing —
          # it exits 128 on the unmatched pathspec — so \`|| true\` turned a
          # missing ratio file into "no new row" and discarded the measurement
          # silently, which is the failure this whole job exists to prevent.
          git add -- "$LEDGER"
          if [ -f .skills/context-token-ratio ]; then
            git add -- .skills/context-token-ratio
          fi
          # The per-file calibration the same --exact run refreshes (#145).
          # Unstaged it would be recomputed and discarded every week, and the
          # estimators between runs would stay on the repo-wide ratio forever —
          # a feature that writes a file nobody ever commits is a feature that
          # does not exist.
          if [ -f .skills/context-token-counts ]; then
            git add -- .skills/context-token-counts
          fi
          if git diff --cached --quiet; then
            echo "no new row — nothing to commit"
            exit 0
          fi
          git commit -m "chore: weekly context measurement"
          # A human push landing during the measurement makes this a
          # non-fast-forward. The ledger is append-only JSONL, so rebasing is
          # safe by construction; without it the week's row is simply lost.
          # GITHUB_REF_NAME is authoritative; git branch --show-current is
          # empty on a detached HEAD and \`git push origin ""\` fails opaquely.
          BRANCH="\${GITHUB_REF_NAME:-\$(git branch --show-current)}"
          # --- push ---
          for attempt in 1 2 3; do
            git push origin "HEAD:\$BRANCH" && exit 0
            echo "push rejected (attempt \$attempt) — rebasing onto origin/\$BRANCH"
            # A failing rebase is fatal and must SAY so. As a bare command under
            # bash -e it killed the step before this loop could retry or reach
            # the error line below, making "3 attempts" really one.
            git pull --rebase --autostash origin "\$BRANCH" || {
              echo "::error::rebase onto origin/\$BRANCH failed — the row was not pushed."
              # Name the file that actually conflicted rather than asserting it
              # was the ledger. Blaming a ledger attribute that is present and
              # correct sent the reader to the one file that was protected,
              # while the calibration files were the unprotected ones (#173).
              #
              # \\\\\` — escaped for BOTH layers. A single \\\` renders a live
              # backtick into the workflow, where bash runs the attribute line
              # as a command and the substitution eats the very filename this
              # message exists to name (#171). The seams ::warning:: below has
              # always had this right; this line did not.
              git diff --name-only --diff-filter=U | sed 's/^/::error::  conflicted: /'
              echo "::error::Re-run install-cadence.sh, then confirm with --check that"
              echo "::error::every staged path carries a merge attribute:"
              echo "::error::  \\\`$ATTR_LINE\\\`"
              echo "::error::  \\\`$ATTR_RATIO\\\`"
              echo "::error::  \\\`$ATTR_COUNTS\\\`"
              exit 1
            }
          done
          echo "::error::could not push the measurement row after 3 attempts"
          exit 1

      # always(), so a failed push does not swallow the warnings. Those are the
      # only output a human reads, and losing them on exactly the runs that went
      # wrong inverts the intent.
      - name: Report drift
        if: always()
        run: |
          # always() makes this reachable when the measurement never ran — the
          # missing-credential case, which is exactly the failure this design
          # exists to make legible. A FileNotFoundError stacked on top of the
          # real preflight error helps nobody.
          if [ ! -f /tmp/ctx.json ]; then
            echo "no measurement was taken — see the failing step above"
            exit 0
          fi
          python3 - /tmp/ctx.json <<'PY'
          import json, sys
          p = json.load(open(sys.argv[1]))["policy"]
          if p["over_budget"]:
              print(f"::warning::{p['path']} is {p['tokens']} tokens against a "
                    f"{p['budget']} budget. Run \`curate context\` in this repo.")
          PY
          if [ "\${SEAMS:-0}" -gt 0 ]; then
            echo "::warning::\$SEAMS unacknowledged cross-reference seam(s). Run \\\`curate context\\\`."
          fi
YAML
}

if [ "$MODE" = "print" ]; then
  render
  exit 0
fi

mkdir -p "$(dirname "$WF")"
if [ -f "$WF" ] && render | cmp -s - "$WF"; then
  echo "unchanged: $WF_PATH is already current (schedule: $CRON)"
else
  EXISTED=no
  [ -f "$WF" ] && EXISTED=yes
  render >"$WF"
  if [ "$EXISTED" = yes ]; then
    echo "updated: $WF_PATH (schedule: $CRON)"
  else
    echo "installed: $WF_PATH (schedule: $CRON)"
  fi
fi
# NOT inside the else. The installer's contract is two artifacts, and an early
# exit on "the workflow is current" skipped this entirely — so every repo that
# adopted before the merge attribute existed re-ran the installer, was told
# "unchanged", and stayed one race away from losing a row. That is exactly the
# population --check tells to re-run.
ensure_attr
# Also NOT inside the else, for the same reason and one more: this is the only
# artifact of the three that a `git pull` can never deliver, so every clone of
# an already-installed repo arrives needing it.
ensure_driver

# The closing text describes what happened, not what usually happens. Written
# unconditionally it told a worktree run that the setting "above" was made and
# is clone-local, on the one path where ensure_driver deliberately wrote
# nothing (#199 CR round 2, finding 8).
case "$DRIVER_STATE" in
  set|already)
    DRIVER_NOTE="The merge drivers above CANNOT be committed — git config is not
versioned. They are set in this clone only, so every other checkout of this
repo needs them once, or the calibration attributes are inert:
  $DRIVER_FIX
  $COUNTS_DRIVER_FIX" ;;
  worktree)
    DRIVER_NOTE="The merge drivers were NOT set — this is a linked worktree, and
its \`git config --local\` writes the main checkout's shared config. Until they
are set there, the calibration attributes this installer wrote are inert:
  (in the main checkout)  $DRIVER_FIX
  (in the main checkout)  $COUNTS_DRIVER_FIX" ;;
  *)
    DRIVER_NOTE="The merge drivers were NOT set, so the calibration attributes
this installer wrote are inert until they are:
  $DRIVER_FIX
  $COUNTS_DRIVER_FIX" ;;
esac

cat <<NEXT

The secret is REQUIRED — without it this job records nothing, silently:
  gh secret set ANTHROPIC_API_KEY

Not committed — review and commit with your normal gate. BOTH files: the
.gitattributes union merge has to be in history before the first concurrent
run, or the race it prevents is already lost when it lands.
  git add $WF_PATH .gitattributes
  git commit -m "chore: schedule the weekly context measurement"

$DRIVER_NOTE

Then run it once by hand before trusting the schedule:
  gh workflow run context-cadence.yml
NEXT
