"""Frontmatter schema validation for all SKILL.md files.

These tests verify that every skill has the required fields, correct types,
and meets length/format constraints. No API calls required.
"""

import re

import pytest

from tests.utils.skill_loader import Skill, all_skills

SEMVER_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")


@pytest.fixture(params=all_skills(), ids=lambda s: s.dir_name)
def skill(request) -> Skill:
    return request.param


class TestRequiredTopLevelFields:
    def test_name_present(self, skill):
        assert "name" in skill.frontmatter, "Missing required field: name"

    def test_name_is_string(self, skill):
        assert isinstance(skill.name, str) and skill.name, "name must be a non-empty string"

    def test_description_present(self, skill):
        assert "description" in skill.frontmatter, "Missing required field: description"

    def test_description_is_string(self, skill):
        assert isinstance(skill.description, str) and skill.description, (
            "description must be a non-empty string"
        )

    def test_description_max_length(self, skill):
        assert len(skill.description) <= 1024, (
            f"description exceeds 1024 chars (got {len(skill.description)})"
        )

    def test_compatibility_present(self, skill):
        assert "compatibility" in skill.frontmatter, "Missing required field: compatibility"

    def test_compatibility_is_string(self, skill):
        assert isinstance(skill.compatibility, str) and skill.compatibility, (
            "compatibility must be a non-empty string"
        )


class TestMetadataBlock:
    def test_metadata_block_present(self, skill):
        assert "metadata" in skill.frontmatter, "Missing required block: metadata"

    def test_metadata_is_dict(self, skill):
        assert isinstance(skill.skill_metadata, dict), "metadata must be a mapping"

    def test_author_present(self, skill):
        assert skill.skill_metadata.get("author"), "metadata.author must be present and non-empty"

    def test_version_present(self, skill):
        assert skill.skill_metadata.get("version") is not None, (
            "metadata.version must be present"
        )

    def test_version_is_semver(self, skill):
        version = str(skill.skill_metadata.get("version", ""))
        assert SEMVER_RE.match(version), (
            f"metadata.version '{version}' does not match semver (e.g. '1.0' or '1.2.3')"
        )

    def test_triggers_present(self, skill):
        assert skill.skill_metadata.get("triggers"), (
            "metadata.triggers must be present and non-empty"
        )

    def test_triggers_is_string(self, skill):
        assert isinstance(skill.skill_metadata.get("triggers"), str), (
            "metadata.triggers must be a string of comma-separated phrases"
        )


class TestOverridesConsistency:
    def test_override_reason_required_when_overrides_set(self, skill):
        if skill.skill_metadata.get("overrides"):
            assert skill.skill_metadata.get("override-reason"), (
                "metadata.override-reason is required when metadata.overrides is set"
            )


class TestBody:
    def test_body_not_empty(self, skill):
        assert skill.body and skill.body.strip(), "SKILL.md body must not be empty"

    def test_body_length_guideline(self, skill):
        line_count = len(skill.body.splitlines())
        assert line_count <= 500, (
            f"SKILL.md body is {line_count} lines; consider moving detail to references/"
            " (spec guideline: <= 500 lines)"
        )
