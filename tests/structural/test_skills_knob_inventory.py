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

`NOT_A_KNOB` carries the deliberate exclusions, each with a reason, and is
itself held minimal: an entry that stops appearing in the tree is a failure,
so the list cannot quietly grow into a place to hide a real knob.

No API calls. Pure text analysis of the repo.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY = REPO_ROOT / "docs" / "KNOBS.md"

# Where a `.skills/<name>` literal counts as a live reference. `docs/plans/` is
# excluded: plans are dated records of what was decided, not current guidance,
# and a knob named only in one is a knob that was discussed, not shipped.
SCAN_DIRS = ("skills", "scripts", ".claude/hooks", "docs")
SCAN_FILES = ("AGENTS.md", "README.md")
SCAN_SUFFIXES = {".sh", ".md", ".py", ".yml", ".yaml", ".json"}
EXCLUDE_PARTS = ("docs/plans/",)

# A path component that cannot end in `.` or `-`, so `.skills/doctor.sh.` at the
# end of a sentence yields `doctor.sh`, and a `.skills/context-token-*` glob
# wrapped across a line does not yield a phantom `context-token`.
KNOB_RE = re.compile(r"\.skills/([A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9_])?)")

# Literals that look like knobs and are not. Each must still appear somewhere,
# enforced by test_every_exclusion_is_still_real.
NOT_A_KNOB = {
    "skills-pin.override": (
        "an env-var value in test_skills_update_hook.py, demonstrating that "
        "SKILLS_PIN_FILE can point somewhere other than the default"
    ),
    "x": (
        "an illustrative path inside quoted help text, cited in "
        "test_checked_temp_writes.py's docstring as a false-positive it excludes"
    ),
}


def _scan_files() -> list[Path]:
    files: list[Path] = []
    for d in SCAN_DIRS:
        root = REPO_ROOT / d
        if not root.exists():
            continue
        files += [
            f
            for f in root.rglob("*")
            if f.is_file() and f.suffix in SCAN_SUFFIXES
        ]
    files += [REPO_ROOT / f for f in SCAN_FILES]
    return [
        f
        for f in files
        if f.exists()
        and not any(p in f.relative_to(REPO_ROOT).as_posix() for p in EXCLUDE_PARTS)
    ]


def referenced_knobs() -> dict[str, list[str]]:
    """Every `.skills/<name>` literal in scope, mapped to where it appears."""
    found: dict[str, list[str]] = {}
    for f in _scan_files():
        try:
            text = f.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        rel = f.relative_to(REPO_ROOT).as_posix()
        for m in KNOB_RE.finditer(text):
            found.setdefault(m.group(1), []).append(rel)
    return found


def inventoried_knobs() -> set[str]:
    """Names in the leftmost column of any table in docs/KNOBS.md.

    Rows are read as `| \\`name\\` | …`, and a trailing `/` marks a directory
    (`experiments/`), which is stripped so it matches the literal in the tree.
    """
    names: set[str] = set()
    for line in INVENTORY.read_text().splitlines():
        if not line.startswith("|"):
            continue
        first = line.split("|")[1].strip()
        m = re.fullmatch(r"`([^`]+)`", first)
        if m:
            names.add(m.group(1).rstrip("/"))
    return names


@pytest.fixture(scope="module")
def referenced() -> dict[str, list[str]]:
    return referenced_knobs()


@pytest.fixture(scope="module")
def inventoried() -> set[str]:
    return inventoried_knobs()


def test_the_inventory_parses(inventoried: set[str]):
    """A table whose rows stop parsing would pass every check below by
    vacuously matching nothing, which is the failure mode this whole file
    exists to prevent one level down."""
    assert len(inventoried) >= 20, (
        f"docs/KNOBS.md yielded only {len(inventoried)} rows "
        f"({sorted(inventoried)}). Either the table shrank drastically or its "
        "row format changed and the parser above no longer reads it."
    )


def test_every_referenced_knob_is_inventoried(
    referenced: dict[str, list[str]], inventoried: set[str]
):
    """The forcing function: a new `.skills/` path cannot ship undocumented."""
    missing = {
        name: sorted(set(where))[:3]
        for name, where in referenced.items()
        if name not in inventoried and name not in NOT_A_KNOB
    }
    assert not missing, (
        "these .skills/ paths are read or written but have no row in "
        "docs/KNOBS.md:\n"
        + "\n".join(f"  .skills/{n} — e.g. {', '.join(w)}" for n, w in sorted(missing.items()))
        + "\n\nAdd the row in the same change that adds the reader, saying what "
        "the file is for, whether it replaces or extends a default, and what "
        "its absence means. If it is not a knob, add it to NOT_A_KNOB with the "
        "reason."
    )


def test_every_inventoried_knob_is_still_referenced(
    referenced: dict[str, list[str]], inventoried: set[str]
):
    """A row for a knob nothing reads promises a project something it will
    silently not get."""
    stale = sorted(inventoried - set(referenced))
    assert not stale, (
        f"docs/KNOBS.md has rows for {stale}, which no file under "
        f"{', '.join(SCAN_DIRS)} references any more. Remove the row, or fix "
        "the name if it was renamed."
    )


def test_every_exclusion_is_still_real(referenced: dict[str, list[str]]):
    """NOT_A_KNOB must not become a place to park a real knob. Every entry has
    to still appear somewhere in the repo, or it is dead weight that would
    silently swallow a future path of the same name."""
    for name in NOT_A_KNOB:
        hits = list(REPO_ROOT.glob("tests/**/*.py"))
        assert any(
            f".skills/{name}" in f.read_text() for f in hits if f.is_file()
        ), (
            f"NOT_A_KNOB names {name!r}, but no `.skills/{name}` literal exists "
            "under tests/ any more. Drop the entry: a stale exclusion silently "
            "excuses a future knob that happens to share the name."
        )


def test_every_exclusion_has_a_reason():
    for name, reason in NOT_A_KNOB.items():
        assert len(reason.split()) >= 5, (
            f"NOT_A_KNOB[{name!r}] needs a reason a reader can check, not "
            f"{reason!r}"
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
