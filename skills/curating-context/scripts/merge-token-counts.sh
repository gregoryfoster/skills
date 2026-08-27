#!/usr/bin/env bash
# merge-token-counts.sh — per-row newest-wins merge driver for the per-file
# token calibration, .skills/context-token-counts (#237).
#
# Git invokes this through `merge.context-counts.driver` when both sides of a
# merge or rebase changed the counts file. install-cadence.sh wires all three
# legs: the `merge=context-counts` attribute in .gitattributes, this command in
# the clone's config, and the same definition inside the cadence workflow's
# commit step (config is not versioned, so each clone and each runner needs
# its own — #192).
set -euo pipefail

usage() {
  cat <<'USAGE'
merge-token-counts.sh — per-row newest-wins merge driver for
.skills/context-token-counts (#237)

Usage (as git invokes it, per the config install-cadence.sh writes):
  merge-token-counts.sh <ancestor> <current> <other> [<path>]

  <ancestor>/<current>/<other> are the temp files git substitutes for
  %O/%A/%B; the merged result is left in <current> and exit 0 reports a
  successful merge, exactly the contract of gitattributes(5). <path> (%P) is
  only for diagnostics.

Why not merge=ours:
  The file is keyed rows — `<bytes> <tokens> <path>` — and `ours` keeps the
  side of whoever RUNS the merge, which is unrelated to which side measured
  more recently. The weekly cadence only ever pushes to the default branch,
  so it was structurally always the side that lost: merging origin/main back
  onto a branch silently reverted the week's fresh measurement, and nothing
  went red because the file is a cache (#237).

What it does instead, per row:
  - changed on one side only: that side wins, deletions included — ordinary
    three-way, no arbitration needed;
  - changed on both sides: keep the row whose <bytes> matches the file as it
    stands in the tree. The row describing the file that exists is a
    measurement; the other describes a file nobody has;
  - matching neither (the file moved on since both measurements, or is
    gone): keep the current side's row — exactly what `merge=ours` did — and
    the estimators' drift fallback plus the next --exact run absorb it.

  The header comes from the current side and rows are re-sorted by path
  under LC_ALL=C, the shape measure-context.sh writes, so a merged file and
  a regenerated one diff clean.

Exit codes:
  0  merged; the result replaced <current>
  1  usage error, or the merge could not be written — git records a
     conflict, which is loud, never a silent revert
USAGE
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
esac

if [ "$#" -lt 3 ]; then
  echo "ERROR expected <ancestor> <current> <other>, got $#" >&2
  usage >&2
  exit 1
fi

ANCESTOR="$1"
CURRENT="$2"
OTHER="$3"
MERGED_PATH="${4:-.skills/context-token-counts}"

for f in "$ANCESTOR" "$CURRENT" "$OTHER"; do
  [ -f "$f" ] || { echo "ERROR $MERGED_PATH: no such merge input: $f" >&2; exit 1; }
done

# Row paths are repo-root-relative, and git runs merge drivers from the top of
# the working tree — but resolve the top explicitly rather than trusting the
# cwd, the same defensiveness every git-adjacent script here carries (#189).
TOP="$(git rev-parse --show-toplevel 2>/dev/null)" || TOP="$PWD"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Every path either side names, with the byte size of the file as it stands in
# the tree; -1 when it does not exist. Computed here in shell so the awk below
# never shells out — quoting a path into a `cmd | getline` is the embedded
# escaping #171 exists to warn about.
awk '/^[[:space:]]*#/ || NF < 3 { next }
     { p = $3; for (i = 4; i <= NF; i++) p = p " " $i; print p }' \
  "$CURRENT" "$OTHER" | LC_ALL=C sort -u |
while IFS= read -r p; do
  case "$p" in
    /*|../*|*/../*) continue ;;   # a row must never point outside the tree
  esac
  if [ -f "$TOP/$p" ]; then
    sz="$(wc -c <"$TOP/$p")"
    sz="${sz//[^0-9]/}"           # BSD wc pads with spaces
  else
    sz="-1"
  fi
  printf '%s %s\n' "${sz:--1}" "$p"
done >"$TMP/sizes"

{
  # The header travels with the current side; a merge must not invent one.
  grep '^[[:space:]]*#' "$CURRENT" \
    || grep '^[[:space:]]*#' "$OTHER" \
    || true
  awk -v anc="$ANCESTOR" -v cur="$CURRENT" -v oth="$OTHER" \
      -v sizes="$TMP/sizes" '
    function trim(s) {
      sub(/^[ \t]+/, "", s); sub(/[ \t\r]+$/, "", s); return s
    }
    # The path is fields 3..NF, not field 3: a markdown file may legitimately
    # have a space in its name, the same rule the writer in measure-context.sh
    # applies when it merges scopes.
    function keyof(line,   n, f, p, i) {
      n = split(line, f, /[ \t]+/)
      if (n < 3) return ""
      p = f[3]
      for (i = 4; i <= n; i++) p = p " " f[i]
      return p
    }
    function bytesof(line,   f) {
      split(line, f, /[ \t]+/)
      return f[1] + 0
    }
    function load(file, row, order,   line, k, n) {
      n = 0
      while ((getline line < file) > 0) {
        line = trim(line)
        if (line == "" || line ~ /^#/) continue
        k = keyof(line)
        if (k == "") continue
        if (!(k in row)) order[++n] = k
        row[k] = line
      }
      close(file)
      return n
    }
    function disksize(p) {
      return (p in dsz) ? dsz[p] : -1
    }
    function emit(k,   a, b, o, d) {
      a = (k in A) ? A[k] : ""
      b = (k in B) ? B[k] : ""
      o = (k in O) ? O[k] : ""
      # Ordinary three-way first: a row only one side touched needs no
      # arbitration, and a deletion is a change like any other.
      if (a == b) { if (a != "") print a; return }
      if (b == o) { if (a != "") print a; return }
      if (a == o) { if (b != "") print b; return }
      # A genuine collision: both sides re-measured. The tree is the arbiter
      # — the row whose bytes match the file that exists IS the measurement.
      d = disksize(k)
      if (a != "" && bytesof(a) == d) { print a; return }
      if (b != "" && bytesof(b) == d) { print b; return }
      # Matching neither: keep the current side, which is what merge=ours
      # did. The estimators detect the drift and fall back to the ratio, and
      # the next --exact run recomputes the row.
      if (a != "") print a
    }
    BEGIN {
      while ((getline line < sizes) > 0) {
        sz = line; sub(/ .*/, "", sz)
        p = line;  sub(/^[^ ]+ /, "", p)
        dsz[p] = sz + 0
      }
      close(sizes)
      na = load(cur, A, AO)
      nb = load(oth, B, BO)
      load(anc, O, OO)
      for (i = 1; i <= na; i++) { k = AO[i]; seen[k] = 1; emit(k) }
      for (i = 1; i <= nb; i++) {
        k = BO[i]
        if (!(k in seen)) { seen[k] = 1; emit(k) }
      }
      # A row both sides deleted needs no visit, and an ancestor-only key
      # would emit nothing — so the ancestor list is never walked.
    }
  ' </dev/null | LC_ALL=C sort -k3
} >"$TMP/merged"

mv -f "$TMP/merged" "$CURRENT"
