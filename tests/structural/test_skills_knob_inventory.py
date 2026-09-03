"""docs/KNOBS.md inventories every `.skills/` path, and stays complete.

Background ([#264](https://github.com/gregoryfoster/skills/issues/264)):
twenty-two paths are read or written under a consuming repo's `.skills/`
directory, and six were documented anywhere a project would look. The rest
lived only in the SKILL.md or `references/` file of the skill that read them,
so a project learned a knob existed when an agent happened to run the skill
that read it.

That is not a documentation nicety. It is how
[#261](https://github.com/gregoryfoster/skills/issues/261) was found: a repo
tailored `.skills/doc-sensitive-paths`, had no way to discover the companion
that tailors the advice, and shipped with instructions written for a stack it
does not run. A knob nobody can enumerate is a knob nobody can use.

Two directions are pinned, and both matter:

- **Every referenced path has a row.** A new knob cannot ship undocumented.
  This is the forcing function; the inventory reached sixteen paths out of date
  precisely because nothing paired the row with the reader.
- **Every row is still referenced.** A knob that was removed leaves a row
  promising a project something it will silently not get, which is worse than
  the gap it replaced.

There is deliberately **no ignore-list**. The first version needed one, and it
held only artifacts of its own scope: fixture paths from `tests/`, and a stem
left behind when a `.skills/context-token-*` glob or a wrapped line was parsed
as a name. Excluding what does not ship knobs, and rejecting a captured name
that ends in a hyphen, removes both classes structurally. An ignore-list is
somewhere a real knob can hide, and the guard against that can only check the
name still appears — not that it is still not a knob.

No API calls. Pure text analysis of the repo.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY = REPO_ROOT / "docs" / "KNOBS.md"

# Everything git tracks is in scope, minus three prefixes. A directory-and-
# suffix allowlist was the first attempt and it had holes exactly where knobs
# ship: `.install` hook installers and `.mjs` drivers under skills/*/scripts/
# are production files with no listed suffix, and .github/workflows/,
# .pre-commit-config.yaml and .gitattributes all read knobs from outside any
# listed directory. A knob introduced only there would have shipped
# undocumented with this test green, which is the failure it exists to prevent.
EXCLUDED_PREFIXES = (
    # Dated records of what was decided, not current guidance. A knob named
    # only in a plan is one that was discussed, not shipped.
    "docs/plans/",
    # Fixtures deliberately construct paths that look like knobs and are not
    # (`skills-pin.override` demonstrating a redirected env var, `.skills/x` in
    # quoted help text). Knobs ship from skills/, scripts/, hooks and repo
    # config; nothing ships from here, so scanning it only forced an
    # ignore-list — and an ignore-list is somewhere a real knob can hide.
    "tests/",
    # This repo's own committed knob FILES. Their contents are data — acked
    # sentences quoting other files, a cohort roster — not references.
    ".skills/",
)

# Capture the whole run of name characters, then judge it. A trailing `-` means
# the source had `.skills/context-token-*` (a glob) or wrapped the name across a
# line; either way it is a stem, not a name. A trailing `.` is sentence
# punctuation after a real name (`.skills/doctor.sh.`).
KNOB_RE = re.compile(r"\.skills/([A-Za-z0-9_.-]+)")


def _knob_names(text: str):
    for m in KNOB_RE.finditer(text):
        name = m.group(1)
        if name.endswith("-"):
            continue
        name = name.rstrip(".")
        if name:
            yield name


def _scan_files() -> list[Path]:
    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")
    return [
        REPO_ROOT / rel
        for rel in tracked
        if rel
        and not rel.startswith(EXCLUDED_PREFIXES)
        and (REPO_ROOT / rel).is_file()
    ]


def referenced_knobs() -> dict[str, list[str]]:
    """Every `.skills/<name>` literal in scope, mapped to where it appears."""
    found: dict[str, list[str]] = {}
    for f in _scan_files():
        try:
            text = f.read_text()
        except (OSError, UnicodeDecodeError):
            continue  # binary asset; no knob reference to find
        rel = f.relative_to(REPO_ROOT).as_posix()
        for name in _knob_names(text):
            found.setdefault(name, []).append(rel)
    return found


def _row_name(line: str) -> str | None:
    """The backticked name in a table row's first cell, if it has one.

    Header rows (`| Path |`) and separator rows (`|---|`) carry no backticks
    and yield None, which is how they are skipped. A trailing `/` marks a
    directory (`experiments/`) and is stripped to match the literal in the tree.
    """
    cells = line.split("|")
    if len(cells) < 2:
        return None
    m = re.fullmatch(r"`([^`]+)`", cells[1].strip())
    return m.group(1).rstrip("/") if m else None


def inventoried_knobs() -> set[str]:
    """Every name in the leftmost column of any table in docs/KNOBS.md."""
    return {
        name
        for line in INVENTORY.read_text().splitlines()
        if line.startswith("|") and (name := _row_name(line))
    }


@pytest.fixture(scope="module")
def referenced() -> dict[str, list[str]]:
    return referenced_knobs()


@pytest.fixture(scope="module")
def inventoried() -> set[str]:
    return inventoried_knobs()


def test_every_table_in_the_inventory_yields_rows():
    """A table whose rows stop parsing would pass every check below by
    vacuously matching nothing — the failure mode this whole file exists to
    prevent, one level down.

    Asserted per SECTION rather than as a total: a bare row count is the kind
    of number this repo makes authors justify, and it would drift on every knob
    added or retired. Three sections each yielding rows is the structural
    property actually wanted, and it localises a parser break to the table it
    broke on."""
    section = None
    per_section: dict[str, int] = {}
    for line in INVENTORY.read_text().splitlines():
        if line.startswith("#"):
            section = line.lstrip("#").strip()
            per_section.setdefault(section, 0)
        elif line.startswith("|") and section and _row_name(line):
            per_section[section] += 1
    populated = {s: n for s, n in per_section.items() if n}
    assert len(populated) >= 3, (
        f"docs/KNOBS.md yielded rows in {len(populated)} section(s) "
        f"({populated}). Every table must parse: configuration a project "
        "commits, the acknowledgement files, and state a skill writes. A "
        "section at zero means its row format changed and the parser above no "
        "longer reads it."
    )


def test_every_referenced_knob_is_inventoried(
    referenced: dict[str, list[str]], inventoried: set[str]
):
    """The forcing function: a new `.skills/` path cannot ship undocumented."""
    missing = {
        name: sorted(set(where))[:3]
        for name, where in referenced.items()
        if name not in inventoried
    }
    assert not missing, (
        "these .skills/ paths are read or written but have no row in "
        "docs/KNOBS.md:\n"
        + "\n".join(f"  .skills/{n} — e.g. {', '.join(w)}" for n, w in sorted(missing.items()))
        + "\n\nAdd the row in the same change that adds the reader, saying what "
        "the file is for, whether it replaces or extends a default, and what "
        "its absence means. If it is genuinely not a knob, the honest fix is "
        "almost always the extractor or the scope above, not an exception."
    )


def test_every_inventoried_knob_is_still_referenced(
    referenced: dict[str, list[str]], inventoried: set[str]
):
    """A row for a knob nothing reads promises a project something it will
    silently not get."""
    stale = sorted(inventoried - set(referenced))
    assert not stale, (
        f"docs/KNOBS.md has rows for {stale}, which no tracked file outside "
        f"{', '.join(EXCLUDED_PREFIXES)} references any more. Remove the row, "
        "or fix the name if it was renamed."
    )


def test_the_inventory_is_linked_from_agents_md():
    """An inventory nobody can find repeats the problem it was written to fix."""
    agents = (REPO_ROOT / "AGENTS.md").read_text()
    assert "docs/KNOBS.md" in agents, (
        "AGENTS.md must link docs/KNOBS.md — #264 is about discoverability, so "
        "an unlinked inventory fixes nothing"
    )


def test_the_two_load_bearing_columns_are_present():
    """`Replaces or extends` and `Absent means` are the two a reader cannot
    derive from the filename, and are the reason this table is hand-written
    rather than generated."""
    text = INVENTORY.read_text()
    for column in ("Replaces or extends", "Absent means"):
        assert column in text, (
            f"docs/KNOBS.md must keep the {column!r} column: it is what a "
            "generated list could not carry, per #264"
        )
