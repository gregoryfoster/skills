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
# `(assets/<path>)`. `[^)]+` captures everything up to the closing paren,
# which may include a `#fragment` or `?query` suffix — callers must strip
# those before resolving against the filesystem.
_LINK_RE = re.compile(r"\((references|assets)/([^)]+)\)")


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
