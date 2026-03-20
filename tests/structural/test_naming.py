"""Naming convention tests for skill directories.

Validates that skill directories follow the conventions documented in AGENTS.md:
- Lowercase, hyphens only, no consecutive hyphens, max 64 chars
- Directory name matches the 'name' field in frontmatter exactly
- Gerund + agent suffix pattern (or 'All agents' compatibility)
- overrides/override-reason consistency

No API calls required.
"""

import re

import pytest

from tests.utils.skill_loader import Skill, all_skills

KNOWN_SUFFIXES = {"-claude", "-cursor", "-copilot", "-gemini"}
ALL_AGENTS_COMPATIBILITY = "All agents"

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


class TestAgentSuffixConvention:
    def test_has_agent_suffix_or_all_agents_compatibility(self, skill):
        has_suffix = any(skill.dir_name.endswith(suffix) for suffix in KNOWN_SUFFIXES)
        is_all_agents = ALL_AGENTS_COMPATIBILITY.lower() in skill.compatibility.lower()
        assert has_suffix or is_all_agents, (
            f"Skill '{skill.dir_name}' must either end with an agent suffix "
            f"({', '.join(KNOWN_SUFFIXES)}) or declare "
            f"'compatibility: {ALL_AGENTS_COMPATIBILITY}'"
        )
