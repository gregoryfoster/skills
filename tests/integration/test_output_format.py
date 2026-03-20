"""Integration tests — structured output format compliance.

Verifies that reviewing-code-claude and reviewing-architecture-claude produce
responses that match the findings format spec in references/findings-format.md.

Uses controlled code snippets with unambiguous issues spanning all three
severity tiers (🔴 🟡 💭) to ensure deterministic findings structure.

One API call per class (class-scoped fixture) — all assertions share the
same response to avoid unnecessary cost and response drift.

Run with:
    ANTHROPIC_API_KEY=sk-... pytest tests/integration/ -v -m integration

Skipped by default (requires API key and explicit -m integration flag).
Estimated cost: ~$0.002/full run at Haiku rates (~2 calls × ~1500 tokens).
"""

import pytest

from tests.utils.api_harness import claude_with_skill
from tests.utils.assertions import (
    assert_finding_subfields,
    assert_sequential_numbering,
    assert_severity_ordering,
    assert_summary_section,
    assert_title_format,
)
from tests.utils.skill_loader import SKILLS_DIR, load_skill

# ---------------------------------------------------------------------------
# Controlled code snippet — deliberate issues across all three severity tiers
#
# 🔴 Bug:    SQL injection via f-string interpolation in delete_user()
# 🟡 Issue:  Hardcoded password at module level
# 💭 Minor:  Accumulator loop that could use a list comprehension
# ---------------------------------------------------------------------------

_CODE_SNIPPET = """\
```python
# user_service.py
import os

PASSWORD = "hunter2"  # hardcoded credential


def get_users(db):
    results = []
    for row in db.execute("SELECT * FROM users"):
        results.append(row)
    return results


def delete_user(db, user_id):
    db.execute(f"DELETE FROM users WHERE id = {user_id}")
    db.commit()
```
"""

_CODE_REVIEW_PROMPT = (
    "Please perform a code review of the following snippet. "
    "Use the exact findings format specified in your instructions: "
    "start with an h2 title (##) matching '## Code & Documentation Review — [scope]', "
    "followed by severity sections (🔴 🟡 💭), "
    "sequential numbering across all sections, per-finding subfields "
    "(What:, Why it matters:, Suggested fix:), "
    "and end with a '### Summary' section.\n\n"
    + _CODE_SNIPPET
)

# ---------------------------------------------------------------------------
# Controlled architecture description — deliberate issues across all tiers
#
# 🔴 Structural: 500-line god module mixing routing, logic, and DB queries
# 🟡 Design:     Hardcoded DB URL in config.py (no env var support)
# 💭 Observation: Minimal test coverage (10 lines for the whole app)
# ---------------------------------------------------------------------------

_ARCH_DESCRIPTION = """\
Project structure:

app/
  main.py       (500 lines — routing, business logic, and DB queries all in one file)
  models.py     (30 lines)
  utils.py      (200 lines — unrelated helpers mixed together)
tests/
  test_main.py  (10 lines — minimal coverage, no fixtures)
config.py       (hardcoded DB URL: "postgresql://localhost/mydb", no env var support)
"""

_ARCH_REVIEW_PROMPT = (
    "Please perform an architectural review of the following project structure. "
    "Use the exact findings format specified in your instructions: "
    "start with an h2 title (##) matching '## Architectural Review — [scope]', "
    "followed by severity sections (🔴 🟡 💭), "
    "sequential numbering across all sections, per-finding subfields "
    "(What:, Why it matters:, Suggested fix:), "
    "and end with a '### Summary' section.\n\n"
    + _ARCH_DESCRIPTION
)


# ---------------------------------------------------------------------------
# reviewing-code-claude
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def code_review_response():
    """Single API call shared across all TestCodeReviewOutputFormat methods."""
    skill = load_skill(SKILLS_DIR / "reviewing-code-claude")
    return claude_with_skill(skill, _CODE_REVIEW_PROMPT, max_tokens=1500)


@pytest.mark.integration
@pytest.mark.usefixtures("code_review_response")
class TestCodeReviewOutputFormat:
    def test_title_format(self, code_review_response):
        assert_title_format(code_review_response, review_type="code")

    def test_severity_ordering(self, code_review_response):
        assert_severity_ordering(code_review_response)

    def test_sequential_numbering(self, code_review_response):
        assert_sequential_numbering(code_review_response)

    def test_finding_subfields(self, code_review_response):
        assert_finding_subfields(code_review_response)

    def test_summary_section(self, code_review_response):
        assert_summary_section(code_review_response)


# ---------------------------------------------------------------------------
# reviewing-architecture-claude
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def arch_review_response():
    """Single API call shared across all TestArchReviewOutputFormat methods."""
    skill = load_skill(SKILLS_DIR / "reviewing-architecture-claude")
    return claude_with_skill(skill, _ARCH_REVIEW_PROMPT, max_tokens=2500)


@pytest.mark.integration
@pytest.mark.usefixtures("arch_review_response")
class TestArchReviewOutputFormat:
    def test_title_format(self, arch_review_response):
        assert_title_format(arch_review_response, review_type="architecture")

    def test_severity_ordering(self, arch_review_response):
        assert_severity_ordering(arch_review_response)

    def test_sequential_numbering(self, arch_review_response):
        assert_sequential_numbering(arch_review_response)

    def test_finding_subfields(self, arch_review_response):
        assert_finding_subfields(arch_review_response)

    def test_summary_section(self, arch_review_response):
        assert_summary_section(arch_review_response)
