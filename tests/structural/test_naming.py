"""Naming convention tests for skill directories.

Validates that skill directories follow the conventions documented in AGENTS.md:
- Lowercase, hyphens only, no consecutive hyphens, max 64 chars
- Directory name matches the 'name' field in frontmatter exactly

No API calls required.
"""

import re

import pytest

from tests.utils.skill_loader import Skill, all_skills

# Pattern: lowercase letters, digits, hyphens; no consecutive hyphens; max 64 chars
VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


@pytest.fixture(params=all_skills(), ids=lambda s: s.dir_name)
def skill(request) -> Skill:
    return request.param


class TestDirectoryNameFormat:
    def test_lowercase_hyphens_only(self, skill):
        assert VALID_NAME_RE.match(skill.dir_name), (
            f"Directory name '{skill.dir_name}' must be lowercase with hyphens only, "
            "no consecutive hyphens, starting with a letter"
        )

    def test_max_64_chars(self, skill):
        assert len(skill.dir_name) <= 64, (
            f"Directory name '{skill.dir_name}' exceeds 64 character limit "
            f"(got {len(skill.dir_name)})"
        )

    def test_no_uppercase(self, skill):
        assert skill.dir_name == skill.dir_name.lower(), (
            f"Directory name '{skill.dir_name}' must be all lowercase"
        )


class TestNameFieldConsistency:
    def test_name_matches_directory(self, skill):
        assert skill.name == skill.dir_name, (
            f"'name' field in frontmatter ('{skill.name}') must match "
            f"directory name ('{skill.dir_name}') exactly"
        )
