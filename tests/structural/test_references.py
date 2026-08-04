"""Structural assertions for references/ and assets/ directories.

These tests enforce two cheap invariants that catch the kind of drift surfaced
during #29 round-1 review (broken asset path, parameter-row pointing at a
nonexistent Phase header):

1. Every `references/...` or `assets/...` link in a SKILL.md body resolves to
   a real file under the skill directory.
2. Every file under a skill's references/ directory is linked from its sibling
   SKILL.md (by filename appearing in the body).

Out of scope per #30: length cap on references, frontmatter-on-references
check, parameter-row -> Phase-header check.

No API calls required.
"""

import re

import pytest

from tests.utils.skill_loader import Skill, all_skills

# Match Markdown link targets of the form `(references/<path>)` or
# `(assets/<path>)`. `[^) ]+` captures everything up to the closing paren OR
# the first whitespace — which excludes a CommonMark link title such as
# `[label](references/foo.md "Title")`. The captured path may still include
# a `#fragment` or `?query` suffix; callers must strip those before
# resolving against the filesystem.
_LINK_RE = re.compile(r"\((references|assets)/([^) ]+)")


# Conditional-block markers in reference templates. A block opens with
# `> Include when <COND>:` and closes with `> end include`; the renderer drops
# the whole block when the condition is false, so an unterminated open has no
# boundary and silently swallows whatever follows (skills#82/#83 CR round 1).
_INCLUDE_OPEN = "> Include when"
_INCLUDE_CLOSE = "> end include"


@pytest.fixture(params=all_skills(), ids=lambda s: s.dir_name)
def skill(request) -> Skill:
    return request.param


class TestReferences:
    """Linked-file-exists and no-orphan assertions for references/ and assets/."""

    def test_referenced_files_exist(self, skill: Skill) -> None:
        """Every (references|assets)/<path> link in SKILL.md must resolve."""
        for kind, raw in _LINK_RE.findall(skill.body):
            # Strip `#fragment` and `?query` suffixes so links like
            # `references/foo.md#L42` resolve against `references/foo.md`.
            name = raw.split("#", 1)[0].split("?", 1)[0]
            target = skill.directory / kind / name
            assert target.exists(), (
                f"{skill.dir_name}: {kind}/{name} linked from SKILL.md but missing"
            )

    def test_no_orphan_references(self, skill: Skill) -> None:
        """Every *.md file under references/ must be linked from sibling SKILL.md.

        Enforces the AGENTS.md "References convention" rule that references files
        must appear as a markdown link `[label](references/<name>.md)`, not merely
        as a backtick mention or comment. Uses the same regex as the linked-file
        check so the two assertions stay in lockstep.
        """
        ref_dir = skill.directory / "references"
        if not ref_dir.is_dir():
            pytest.skip("no references/ directory")
        linked_names = {
            raw.split("#", 1)[0].split("?", 1)[0]
            for kind, raw in _LINK_RE.findall(skill.body)
            if kind == "references"
        }
        for ref in sorted(ref_dir.glob("*.md")):
            assert ref.name in linked_names, (
                f"{skill.dir_name}: references/{ref.name} exists but is not linked "
                f"as a markdown link `[label](references/{ref.name})` from SKILL.md"
            )


class TestConditionalBlockMarkers:
    """Every `> Include when …:` block in a reference must be terminated.

    These markers gate branch-point content that an agent renders mechanically.
    An unterminated open leaves the block's extent undefined, so dropping it on
    a false condition takes an arbitrary amount of following prose with it —
    a silent deletion, with nothing failing to report it. That is exactly how
    an unterminated `PRIVATE_WHEELHOUSE` block reached main (skills#82/#83).
    """

    def test_include_markers_are_balanced(self, skill: Skill) -> None:
        ref_dir = skill.directory / "references"
        if not ref_dir.is_dir():
            pytest.skip("no references/ directory")
        for ref in sorted(ref_dir.glob("*.md")):
            open_line = None
            for lineno, raw in enumerate(ref.read_text().splitlines(), 1):
                line = raw.strip()
                # startswith, not `in`: prose documenting the convention quotes
                # the marker mid-sentence and must not count as an occurrence.
                if line.startswith(_INCLUDE_OPEN):
                    assert open_line is None, (
                        f"{skill.dir_name}: references/{ref.name} line {lineno} opens a "
                        f"'{_INCLUDE_OPEN}' block while line {open_line} is still open — "
                        f"add '{_INCLUDE_CLOSE}' to close the earlier one"
                    )
                    open_line = lineno
                elif line == _INCLUDE_CLOSE:
                    assert open_line is not None, (
                        f"{skill.dir_name}: references/{ref.name} line {lineno} has a stray "
                        f"'{_INCLUDE_CLOSE}' with no matching '{_INCLUDE_OPEN}'"
                    )
                    open_line = None
            assert open_line is None, (
                f"{skill.dir_name}: references/{ref.name} line {open_line} opens a "
                f"'{_INCLUDE_OPEN}' block that is never closed with '{_INCLUDE_CLOSE}' — "
                f"the renderer has no boundary for what to drop when the condition is false"
            )
