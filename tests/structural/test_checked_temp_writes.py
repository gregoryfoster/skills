"""#181 — a write through a temp file must be checked.

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

What this rule does NOT reach
-----------------------------
The second spelling of the same family — `date -u +%Y%m%d > "$LOCK" || true`,
a write the script's contract depends on whose failure is swallowed outright
(#187). Its failure presents as the absence of a state change, not as a false
success message, so there is no `&&` list to find. Widening to "any write with
`|| true`" was also measured: it sweeps up every `>>"$LOG" … || true` audit
line and every `grep … >"$TMP/x" || true` where an empty result is normal, and
lands back above 20 false positives. That one stays a review lesson and the
AGENTS.md convention, not a test.
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
        if not REDIRECT_THEN_AND.search(joined):
            continue
        if CONDITION_HEAD.match(head):
            continue          # the list's status governs a branch
        if EXEMPT_MARKER in joined or EXEMPT_MARKER in preamble:
            continue          # named, at the line, with a reason
        if re.search(r"\|\|\s*true\b", joined):
            out.append((lineno, joined))   # #187's shape; needs the marker
            continue
        if "||" in joined:
            continue          # a real handler runs on failure
        if re.search(r";\s*then\b", joined) or joined.rstrip().endswith("then"):
            continue
        out.append((lineno, joined))
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
