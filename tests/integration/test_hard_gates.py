"""Integration tests — hard gate behavioral enforcement.

Each test injects a skill's body as a system prompt, then sends an adversarial
probe designed to trigger a specific hard gate. The test asserts that the gate
fires (refusal language present) and that forbidden actions are not taken.

Run with:
    ANTHROPIC_API_KEY=sk-... pytest tests/integration/ -v -m integration

Skipped by default (requires API key and explicit -m integration flag).
Estimated cost: ~$0.003/full run at Haiku rates (~8 probes × ~500 tokens).
"""

from pathlib import Path

import pytest

from tests.utils.api_harness import claude_with_skill, hard_gate_fired
from tests.utils.skill_loader import load_skill, SKILLS_DIR

PROMPTS_DIR = Path(__file__).parent.parent / "fixtures" / "prompts"


def _probe(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text().strip()


# ---------------------------------------------------------------------------
# shipping-work-claude
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestShippingWorkGates:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.skill = load_skill(SKILLS_DIR / "shipping-work-claude")

    def test_deadline_push_refused(self):
        probe = _probe("shipping_deadline_push.txt")
        response = claude_with_skill(self.skill, probe)
        assert hard_gate_fired(response), (
            f"Gate did not fire for deadline push probe. Response: {response[:300]}"
        )
        assert "git push" not in response.lower(), (
            "Response must not execute git push when gate should be enforced"
        )

    def test_session_tests_passed_refused(self):
        probe = _probe("shipping_tests_passed_earlier.txt")
        response = claude_with_skill(self.skill, probe)
        assert hard_gate_fired(response), (
            f"Gate did not fire for 'tests passed earlier' probe. Response: {response[:300]}"
        )
        assert "git push" not in response.lower(), (
            "Response must not execute git push when gate should be enforced"
        )

    def test_close_issue_basically_done_refused(self):
        probe = _probe("shipping_close_issue_basically_done.txt")
        response = claude_with_skill(self.skill, probe)
        assert hard_gate_fired(response), (
            f"Gate did not fire for 'basically done, close issue' probe. Response: {response[:300]}"
        )

    def test_skip_failing_push_refused(self):
        probe = _probe("shipping_skip_failing_push.txt")
        response = claude_with_skill(self.skill, probe)
        assert hard_gate_fired(response), (
            f"Gate did not fire for 'skip failing push' probe. Response: {response[:300]}"
        )


# ---------------------------------------------------------------------------
# init-project-fastapi-claude
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInitProjectFastapiGates:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.skill = load_skill(SKILLS_DIR / "init-project-fastapi-claude")

    def test_create_files_before_params_refused(self):
        probe = _probe("fastapi_start_files_name_later.txt")
        response = claude_with_skill(self.skill, probe)
        assert hard_gate_fired(response), (
            f"Gate did not fire for 'create files before collecting params' probe. "
            f"Response: {response[:300]}"
        )


# ---------------------------------------------------------------------------
# reviewing-code-claude
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReviewingCodeGates:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.skill = load_skill(SKILLS_DIR / "reviewing-code-claude")

    def test_fix_bugs_without_report_refused(self):
        probe = _probe("reviewing_fix_all_bugs.txt")
        response = claude_with_skill(self.skill, probe)
        assert hard_gate_fired(response), (
            f"Gate did not fire for 'fix all bugs' probe. Response: {response[:300]}"
        )

    def test_small_change_fix_directly_refused(self):
        probe = _probe("reviewing_small_change_fix_directly.txt")
        response = claude_with_skill(self.skill, probe)
        assert hard_gate_fired(response), (
            f"Gate did not fire for 'small change, fix directly' probe. Response: {response[:300]}"
        )

    def test_fix_as_you_find_refused(self):
        probe = _probe("reviewing_fix_as_you_find.txt")
        response = claude_with_skill(self.skill, probe)
        assert hard_gate_fired(response), (
            f"Gate did not fire for 'fix as you find' probe. Response: {response[:300]}"
        )
