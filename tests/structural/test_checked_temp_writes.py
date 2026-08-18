r"""#181 — a write through a temp file must be checked.

    cmd … >"$FILE.tmp" && mv -f "$FILE.tmp" "$FILE"
    log "wrote the thing"          # runs even when cmd failed

Under `set -e` the failure of the FIRST element of an `&&` list is exempt from
the errexit check. So `cmd` fails, the script does not abort, `mv` never runs,
the temp file is orphaned, and the success line prints anyway. Every script in
this tree carries `set -euo pipefail`, which is exactly what makes the idiom
worth a gate: it reads as covered and is not.

Why a grep rule and not shellcheck
----------------------------------
Shellcheck has no check for this. SC2015 ("A && B || C is not if-then-else")
is the nearest neighbour and needs the `|| C` this shape does not have. The
gate in test_scripts.py runs at severity `style` — the floor is already as low
as it goes — and it passed the defect this file was written for.

Why THIS rule and not the obvious one
-------------------------------------
The obvious formulation — "a write followed by an unconditional success
message" — was measured against this tree before it was rejected. It produced
37 candidates and 0 true positives: `>` inside help text (`.skills/x > y`,
`feature/foo -> foo`), comparison arrows in prose, and a long tail of simple
`printf … >>FILE` writes whose failure errexit already catches because they
are not part of an `&&` list. A gate with a 100% false-positive rate is worse
than the convention in AGENTS.md, because it gets suppressed.

The rule below is narrower and matches the mechanism rather than the symptom:
a file redirect that is a NON-FINAL element of an `&&` list, which is the one
position errexit does not cover. Measured on the same tree it finds the #181
defect and nothing else.

The second spelling (#193)
--------------------------
    date -u +%Y%m%d > "$LOCK" || true

The same family, and the one this file originally declined to gate. Its failure
presents as the *absence* of a state change rather than as a false success
message, so there is no `&&` list to find. It has now escaped two sweeps
written for the `&&` shape — #187 in `socraticode-health.sh`, then #193 in
`skills-submodule-update.sh`, whose file matched #181's `grep -rln '\.tmp'`
enumeration on a genuinely-correct `.tmp` site and was filed READ-ONLY without
ever being re-read for this spelling. Two escapes is the evidence that the
convention alone does not hold.

The widening this docstring previously rejected was "any write with `|| true`".
That rejection was correct and still is: re-measured on this tree with #193's
defect still in place, it reports 16 sites, 1 of them real. Three exclusions,
each naming a mechanism rather than a symptom, take it to 16 → 1 with no false
positive left:

- **`>>` is not a write, it is an append.** Every one of them here is an audit
  line to `$LOG`, where a lost line costs a breadcrumb and nothing else. Only a
  truncating `>` replaces state something later reads back.
- **A pipeline's exit status belongs to its last command, which may be entitled
  to fail.** `grep … | sort -u >"$TMP/units" || true` swallows an empty grep,
  not a failed write; `cmd >/dev/null || true` discards output rather than
  storing it. Neither is a state write.
- **A heredoc body is data this script emits, not code it runs.** The `|| true`
  in `install-cadence.sh`'s emitted workflow belongs to a GitHub Actions step
  whose tool exits 3 on a finding. If emitted text lands in a `.sh` in this
  tree, this gate reaches it there, in the file that runs it.

What remains is a truncating redirect, outside a pipeline and outside a
heredoc, whose failure is discarded — which is the mechanism exactly. As with
the `&&` rule, a deliberate one is not forbidden, only required to say so:
`# unchecked-write-ok: <reason>`.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Search path: every shell script a consumer repo can end up running.
SEARCH_DIRS = (
    sorted(REPO_ROOT.glob("skills/*/scripts"))
    + [REPO_ROOT / "scripts", REPO_ROOT / ".claude" / "hooks"]
)

# A file redirect (not `>&2`, not a `->` arrow, not `>=`) followed on the same
# logical line by `&&`. `[^&|;]*` keeps the match inside a single list element.
REDIRECT_THEN_AND = re.compile(r'(?<![0-9&\-=])>>?\s*"?\$?[A-Za-z_./{][^&|;]*&&')

# The escape hatch, and the reason it is not `|| true`.
#
# `if … && …; then` and `… || <handler>` are STRUCTURAL evidence that the
# outcome was considered: the branch or the handler is where the success
# message goes. `|| true` is not — it is the #187 shape, a write whose failure
# is discarded, and accepting it as an exemption would teach the fix that makes
# the bug worse. So a deliberate `|| true` on a temp-file write must say so on
# the line, the way a shellcheck directive does.
# The marker may sit on the statement or in the contiguous comment block
# directly above it, which is where the rationale usually already is.
EXEMPT_MARKER = "unchecked-write-ok:"
CONDITION_HEAD = re.compile(r"^(if|while|until|elif)\b")


def _logical_lines(path: Path):
    """Yield (lineno, joined_text, head_text, preamble) with backslash
    continuations joined, since the `&&` of a wrapped list sits on a later
    physical line. `preamble` is the contiguous comment block immediately
    above, so the marker can be written where the rationale already lives
    rather than crammed onto the end of the statement."""
    lines = path.read_text().splitlines()
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        start = i
        while start > 0 and lines[start - 1].rstrip().endswith("\\"):
            start -= 1
        if start != i:
            # Only judge each logical line once, from its first physical line.
            continue
        joined = stripped
        j = i
        while lines[j].rstrip().endswith("\\") and j + 1 < len(lines):
            j += 1
            joined += " " + lines[j].strip()
        k = start - 1
        preamble = []
        while k >= 0 and lines[k].strip().startswith("#"):
            preamble.append(lines[k].strip())
            k -= 1
        yield i + 1, joined, stripped, "\n".join(preamble)


def _offenders(path: Path):
    out = []
    for lineno, joined, head, preamble in _logical_lines(path):
        m = REDIRECT_THEN_AND.search(joined)
        if not m:
            continue
        if CONDITION_HEAD.match(head):
            continue          # the list's status governs a branch
        if EXEMPT_MARKER in joined or EXEMPT_MARKER in preamble:
            continue          # named, at the line, with a reason
        # A handler belongs to THIS list only if it FOLLOWS the `&&`. Testing the
        # whole logical line instead let a `||` anywhere on it — inside an
        # earlier command substitution, most plausibly — exempt an unchecked
        # write further along, in the one rule that is supposed to be
        # mechanism-shaped rather than symptom-shaped (CR finding 26).
        tail = joined[m.end():]
        if re.search(r"\|\|\s*true\b", tail):
            out.append((lineno, joined))   # #187's shape; needs the marker
            continue
        if "||" in tail:
            continue          # a real handler runs on failure
        if re.search(r";\s*then\b", joined) or joined.rstrip().endswith("then"):
            continue
        out.append((lineno, joined))
    return out


# ------------------------------------------------------------------ #193
# The second spelling: a truncating write whose failure is discarded.

# A truncating redirect to a file: `>` but not `>>`, not `>&2`, not `2>`, not
# a `->` arrow or `>=`. The target must start like a path or a variable.
TRUNCATING_REDIRECT = re.compile(r'(?<![0-9&\->=])>(?!>)\s*"?\$?[A-Za-z_./{]')

# The swallow. `:` is `true` spelled shorter and hides the same failure, but
# only as the WHOLE handler — `|| : >"$TMP/code"` truncates the file on
# failure, which is a real handler and the opposite of a discard. Anchoring on
# the end of the list is what tells the two apart (verify-facts.sh:184).
SWALLOWED = re.compile(r"\|\|\s*(?:true|:)\s*(?:;|#|$)")

# A pipeline — `|` that is not part of `||`. The list's exit status is the last
# command's, and that command may be entitled to fail (an empty `grep`).
SINGLE_PIPE = re.compile(r"(?<!\|)\|(?!\|)")

# Output thrown away rather than stored. Not state, so not this rule's business.
DISCARD = re.compile(r'>\s*"?/dev/null')

# `<<WORD` / `<<-WORD` / `<<'WORD'`, but never the `<<<` here-string.
HEREDOC_OPEN = re.compile(r"""(?<!<)<<(?!<)-?\s*['"]?([A-Za-z_][A-Za-z0-9_]*)['"]?""")


def _heredoc_body_lines(path: Path) -> set[int]:
    """1-based line numbers sitting inside a heredoc body.

    Terminators are matched after stripping, which covers `<<-` as well as
    plain `<<`. Deliberately shallow — a heredoc opened inside another
    heredoc's body is not tracked, because the body is skipped wholesale
    either way."""
    inside: set[int] = set()
    terminator = None
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        if terminator is not None:
            if raw.strip() == terminator:
                terminator = None
            else:
                inside.add(lineno)
            continue
        m = HEREDOC_OPEN.search(raw)
        if m:
            terminator = m.group(1)
    return inside


def _swallowed_state_writes(path: Path):
    """Truncating writes, outside a pipeline and outside a heredoc, whose
    failure is discarded by `|| true`.

    EVERY redirect on the line is judged, not just the first. Deciding on the
    first let an earlier discard speak for a later write:

        cmd >/dev/null 2>&1 && printf x >"$STATE" || true

    matched at `>/dev/null`, the discard rule fired, and the real state write
    was never reached. One line's worth of `>` is not one verdict — a line is
    clean only when none of its redirects is an unchecked state write.
    """
    heredoc = _heredoc_body_lines(path)
    out = []
    for lineno, joined, _head, preamble in _logical_lines(path):
        if not TRUNCATING_REDIRECT.search(joined):
            continue
        if EXEMPT_MARKER in joined or EXEMPT_MARKER in preamble:
            continue          # named, at the line, with a reason
        if SINGLE_PIPE.search(joined):
            continue          # the status is the last command's, not the write's
        if lineno in heredoc:
            continue          # emitted text, not code this script runs
        for m in TRUNCATING_REDIRECT.finditer(joined):
            redirect_on = joined[m.start():]
            if DISCARD.match(redirect_on):
                continue      # this one discards output; keep looking
            if not SWALLOWED.search(redirect_on):
                continue      # nothing swallows this one's failure
            out.append((lineno, joined))
            break
    return out


def _shell_scripts():
    for d in SEARCH_DIRS:
        if d.is_dir():
            for f in sorted(d.rglob("*.sh")):
                if f.is_symlink():
                    continue      # linked into .claude/hooks/; linted at source
                yield f


def test_no_unchecked_temp_file_write():
    found = []
    for f in _shell_scripts():
        for lineno, text in _offenders(f):
            rel = f.relative_to(REPO_ROOT)
            found.append(f"{rel}:{lineno}\n      {text[:120]}")
    assert not found, (
        "a write whose failure errexit does not catch. Put the `&&` list in an "
        "`if`, so the success message lives in the branch that succeeded — see "
        "install-refresh.sh's settings_rewrite(). If the swallow is deliberate, "
        f"mark the line `# {EXEMPT_MARKER} <reason>`.\n\n  "
        + "\n  ".join(found)
    )


def test_no_swallowed_state_write():
    found = []
    for f in _shell_scripts():
        for lineno, text in _swallowed_state_writes(f):
            rel = f.relative_to(REPO_ROOT)
            found.append(f"{rel}:{lineno}\n      {text[:120]}")
    assert not found, (
        "a truncating write whose failure is discarded. Its failure shows up as "
        "state that never changed, not as an error — check it with `if ! cmd > "
        '"$F" 2>/dev/null; then …`, the shape socraticode-health.sh uses to '
        "stamp its lock. If the swallow is deliberate, mark the line "
        f"`# {EXEMPT_MARKER} <reason>`.\n\n  " + "\n  ".join(found)
    )


def test_the_second_rule_catches_the_defect_it_was_written_for(tmp_path: Path):
    """#193's exact pre-fix text, so a later loosening is caught here."""
    s = tmp_path / "lock.sh"
    s.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'date -u +%Y%m%d > "$LOCK" || true\n'
    )
    assert [n for n, _ in _swallowed_state_writes(s)] == [3]


def test_the_second_rule_accepts_the_checked_form(tmp_path: Path):
    s = tmp_path / "fixed.sh"
    s.write_text(
        "#!/usr/bin/env bash\n"
        'if ! date -u +%Y%m%d > "$LOCK" 2>/dev/null; then\n'
        '  _log "could not stamp $LOCK"\n'
        "fi\n"
    )
    assert _swallowed_state_writes(s) == []


def test_the_second_rule_takes_the_same_marker(tmp_path: Path):
    s = tmp_path / "marked.sh"
    s.write_text(
        "# unchecked-write-ok: best-effort scratch file in a hook that must not block\n"
        'date -u +%Y%m%d > "$LOCK" || true\n'
    )
    assert _swallowed_state_writes(s) == []


def test_an_append_is_not_a_state_write(tmp_path: Path):
    """`>>` adds an audit line; a lost one costs a breadcrumb, not state.
    Reporting them is what made the naive widening unusable."""
    s = tmp_path / "log.sh"
    s.write_text('echo "[$(date -u)] $*" >>"$LOG" 2>/dev/null || true\n')
    assert _swallowed_state_writes(s) == []


def test_a_pipeline_is_not_a_state_write(tmp_path: Path):
    """The status belongs to the last command, and an empty `grep` is normal."""
    s = tmp_path / "pipe.sh"
    s.write_text('grep -oE "#[0-9]+" "$f" | sort -u >"$TMP/issues" || true\n')
    assert _swallowed_state_writes(s) == []


def test_a_colon_with_a_redirect_is_a_real_handler(tmp_path: Path):
    """verify-facts.sh:184. `|| :` alone discards the failure; `|| : >"$F"`
    empties the file on failure, which is the handler, not the absence of one.
    Only the bare form is the swallow."""
    s = tmp_path / "colon.sh"
    s.write_text('grep -E "$re" "$f" >"$TMP/code" 2>/dev/null || : >"$TMP/code"\n')
    assert _swallowed_state_writes(s) == []
    s.write_text('printf x >"$TMP/code" || :\n')
    assert [n for n, _ in _swallowed_state_writes(s)] == [1]


def test_a_discard_is_not_a_state_write(tmp_path: Path):
    s = tmp_path / "quiet.sh"
    s.write_text('command -v node >/dev/null || true\n')
    assert _swallowed_state_writes(s) == []


def test_a_discard_does_not_speak_for_a_later_write_on_the_same_line(
        tmp_path: Path):
    """The rule judged only the FIRST redirect, so `>/dev/null` earlier on the
    line answered for a real state write later on it. `command -v x >/dev/null`
    is common enough to sit next to one."""
    s = tmp_path / "shadow.sh"
    s.write_text('cmd >/dev/null 2>&1 && printf x >"$STATE" || true\n')
    assert [n for n, _ in _swallowed_state_writes(s)] == [1]
    # …and a line whose only redirect is the discard stays clean.
    s.write_text('cmd >/dev/null 2>&1 || true\n')
    assert _swallowed_state_writes(s) == []


def test_a_heredoc_body_is_emitted_text_not_code(tmp_path: Path):
    """install-cadence.sh's emitted workflow, reduced. The `|| true` there
    belongs to a CI step whose tool exits 3 on a finding."""
    s = tmp_path / "emit.sh"
    s.write_text(
        "cat <<YAML > .github/workflows/x.yml\n"
        "        run: |\n"
        "          bash check-seams.sh >/tmp/seams.txt 2>&1 || true\n"
        '          date -u +%Y%m%d > "$LOCK" || true\n'
        "YAML\n"
    )
    assert _swallowed_state_writes(s) == []
    # …and the tracker closes again, so a later write is still judged.
    s.write_text(
        "cat <<YAML\n"
        "hello\n"
        "YAML\n"
        'date -u +%Y%m%d > "$LOCK" || true\n'
    )
    assert [n for n, _ in _swallowed_state_writes(s)] == [4]


def test_a_here_string_does_not_open_a_heredoc(tmp_path: Path):
    """`<<<` shares a prefix with `<<`. Treating it as an opener would swallow
    the rest of the file into a body that never terminates."""
    s = tmp_path / "herestring.sh"
    s.write_text(
        'read -r x <<<"EOF"\n'
        'date -u +%Y%m%d > "$LOCK" || true\n'
    )
    assert [n for n, _ in _swallowed_state_writes(s)] == [2]


def test_the_rule_still_catches_the_defect_it_was_written_for(tmp_path: Path):
    """A gate that cannot fail is not a gate. This pins the rule against the
    exact pre-fix text of install-guard.sh's merge_settings, so a later
    loosening of the regex is caught here rather than in the next incident."""
    sample = tmp_path / "sample.sh"
    sample.write_text(
        '#!/usr/bin/env bash\n'
        'set -euo pipefail\n'
        'merge_settings() {\n'
        '  jq --arg cmd "$COMMAND" --arg marker "$MARKER" \\\n'
        '    "$expr" "$SETTINGS" >"$SETTINGS.tmp" \\\n'
        '    && mv -f "$SETTINGS.tmp" "$SETTINGS"\n'
        '}\n'
    )
    assert _offenders(sample), "the rule no longer detects #181's own defect"


def test_the_rule_accepts_the_checked_form(tmp_path: Path):
    """And a gate that fails on the fix is a gate nobody keeps."""
    sample = tmp_path / "fixed.sh"
    sample.write_text(
        '#!/usr/bin/env bash\n'
        'set -euo pipefail\n'
        'if jq "$@" "$S" >"$S.tmp" && mv -f "$S.tmp" "$S"; then\n'
        '  log "wrote it"\n'
        'else\n'
        '  rm -f "$S.tmp"; exit 1\n'
        'fi\n'
    )
    assert not _offenders(sample)


def test_a_bare_or_true_is_not_an_exemption(tmp_path: Path):
    """`|| true` is #187's shape, not a checked write. It must be named."""
    sample = tmp_path / "swallowed.sh"
    sample.write_text(
        'tail -n 200 "$LOG" >"$LOG.tmp" && mv -f "$LOG.tmp" "$LOG" || true\n'
    )
    assert _offenders(sample)
    sample.write_text(
        'tail -n 200 "$LOG" >"$LOG.tmp" && mv -f "$LOG.tmp" "$LOG" || true '
        '# unchecked-write-ok: best-effort log trim in a hook that must not block\n'
    )
    assert not _offenders(sample)


def test_an_unrelated_handler_earlier_on_the_line_is_not_an_exemption(tmp_path: Path):
    """The gap CR finding 26 closed. `||` belongs to this list only if it
    follows the `&&`; one inside an earlier command substitution says nothing
    about whether the write was checked, and used to exempt it."""
    s = tmp_path / "x.sh"
    s.write_text(
        '#!/usr/bin/env bash\n'
        'v="$(get_it || echo default)"; jq . "$F" >"$F.tmp" && mv -f "$F.tmp" "$F"\n'
    )
    assert [n for n, _ in _offenders(s)] == [2]


def test_a_handler_after_the_and_still_exempts(tmp_path: Path):
    """The other half: scoping the test must not start reporting the checked
    form. A handler that really does run on this list's failure is evidence."""
    s = tmp_path / "x.sh"
    s.write_text(
        '#!/usr/bin/env bash\n'
        'jq . "$F" >"$F.tmp" && mv -f "$F.tmp" "$F" || die "rewrite failed"\n'
    )
    assert _offenders(s) == []
