"""Content invariant tests for SKILL.md files.

Verify that safety-critical text (hard gates, phase ordering, references) is
verbatim present in each skill. These tests catch accidental deletion of
behavioral contracts during edits.

No API calls required.
"""

import pytest

from tests.utils.skill_loader import load_skill, SKILLS_DIR


def skill(name: str):
    return load_skill(SKILLS_DIR / name)


# ---------------------------------------------------------------------------
# shipping-work-claude
# ---------------------------------------------------------------------------


class TestShippingWorkClaude:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("shipping-work-claude")

    def test_iron_law_no_push_without_tests(self):
        assert "NO PUSH WITHOUT PASSING TESTS" in self.s.body, (
            "Iron Law text 'NO PUSH WITHOUT PASSING TESTS' must be present verbatim"
        )

    def test_iron_law_no_closure_without_implementation(self):
        assert "NO ISSUE CLOSURE WITHOUT FULL IMPLEMENTATION" in self.s.body, (
            "Iron Law text 'NO ISSUE CLOSURE WITHOUT FULL IMPLEMENTATION' must be present verbatim"
        )

    def test_hard_gate_xml_block_present(self):
        assert "<HARD-GATE>" in self.s.body, (
            "<HARD-GATE> XML block must be present in shipping-work-claude"
        )

    def test_step_ordering_tests_before_push(self):
        body = self.s.body
        step1_pos = body.find("Step 1 — Run tests")
        step4_pos = body.find("Step 4 — Push")
        assert step1_pos != -1, "Step 1 — Run tests not found"
        assert step4_pos != -1, "Step 4 — Push not found"
        assert step1_pos < step4_pos, (
            "Step 1 (Run tests) must appear before Step 4 (Push) in the procedure"
        )

    def test_no_continuation_if_tests_fail(self):
        assert "NO CONTINUATION IF TESTS FAIL" in self.s.body, (
            "'NO CONTINUATION IF TESTS FAIL' block must be present"
        )

    def test_rationalization_table_present(self):
        assert "Rationalization prevention" in self.s.body, (
            "Rationalization prevention table must be present"
        )


# ---------------------------------------------------------------------------
# init-project-fastapi
# ---------------------------------------------------------------------------


class TestInitProjectFastapi:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("init-project-fastapi-claude")

    def test_hard_gate_xml_block_present(self):
        assert "<HARD-GATE>" in self.s.body, (
            "<HARD-GATE> XML block must be present in init-project-fastapi-claude"
        )

    def test_hard_gate_collect_params_first(self):
        assert "Do NOT create files or run commands until" in self.s.body, (
            "Hard gate text 'Do NOT create files or run commands until' must be present verbatim"
        )

    def test_all_required_parameters_listed(self):
        required_params = [
            "PROJECT_NAME",
            "PROJECT_DESCRIPTION",
            "GITHUB_ORG",
            "API_PORT",
            "DEPLOY_KEY_LABEL",
            "GIT_USER_NAME",
            "GIT_USER_EMAIL",
        ]
        for param in required_params:
            assert param in self.s.body, f"Required parameter '{param}' must be documented"

    def test_confirm_all_before_proceeding(self):
        assert "Confirm all" in self.s.body, (
            "Skill must state that all parameters must be confirmed before proceeding"
        )

    def test_phase_ordering_verify_before_commit(self):
        body = self.s.body
        verify_pos = body.find("Phase 12 — Verify")
        commit_pos = body.find("Phase 13 — Commit")
        push_pos = body.find("Phase 14 — Push")
        assert verify_pos != -1, "Phase 12 — Verify not found"
        assert commit_pos != -1, "Phase 13 — Commit not found"
        assert push_pos != -1, "Phase 14 — Push not found"
        assert verify_pos < commit_pos < push_pos, (
            "Phase ordering must be: Verify (12) → Commit (13) → Push (14)"
        )


# ---------------------------------------------------------------------------
# reviewing-code-claude
# ---------------------------------------------------------------------------


class TestReviewingCodeClaude:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("reviewing-code-claude")

    def test_iron_law_no_changes_without_report(self):
        assert "NO CHANGES WITHOUT A FINDINGS REPORT AND EXPLICIT USER DIRECTIVES" in self.s.body, (
            "Iron Law text 'NO CHANGES WITHOUT A FINDINGS REPORT AND EXPLICIT USER DIRECTIVES' "
            "must be present verbatim"
        )

    def test_iron_law_no_report_without_tests(self):
        assert "NO FINDINGS REPORT WITHOUT RUNNING THE TEST SUITE FIRST" in self.s.body, (
            "Iron Law text 'NO FINDINGS REPORT WITHOUT RUNNING THE TEST SUITE FIRST' "
            "must be present verbatim"
        )

    def test_phase4_wait_for_feedback_present(self):
        assert "Phase 4 — Wait for feedback" in self.s.body, (
            "Phase 4 — Wait for feedback must be present"
        )

    def test_phase4_stop_instruction(self):
        assert "Stop. Do not make changes until the user responds." in self.s.body, (
            "'Stop. Do not make changes until the user responds.' must appear in Phase 4"
        )

    def test_findings_format_reference(self):
        assert "references/findings-format.md" in self.s.body, (
            "references/findings-format.md must be referenced in the skill body"
        )

    def test_rationalization_table_present(self):
        assert "Rationalization prevention" in self.s.body, (
            "Rationalization prevention table must be present"
        )

    def test_phase_ordering_gather_before_present(self):
        body = self.s.body
        phase1_pos = body.find("Phase 1 — Gather context")
        phase3_pos = body.find("Phase 3 — Present findings")
        phase4_pos = body.find("Phase 4 — Wait for feedback")
        assert phase1_pos != -1, "Phase 1 — Gather context not found"
        assert phase3_pos != -1, "Phase 3 — Present findings not found"
        assert phase4_pos != -1, "Phase 4 — Wait for feedback not found"
        assert phase1_pos < phase3_pos < phase4_pos, (
            "Phase ordering must be: Gather (1) → Present (3) → Wait (4)"
        )


# ---------------------------------------------------------------------------
# reviewing-architecture-claude
# ---------------------------------------------------------------------------


class TestReviewingArchitectureClaude:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("reviewing-architecture-claude")

    def test_phase4_wait_for_feedback_present(self):
        assert "Phase 4 — Wait for feedback" in self.s.body, (
            "Phase 4 — Wait for feedback must be present"
        )

    def test_phase4_stop_instruction(self):
        assert "Stop. Do not make changes until the user responds." in self.s.body, (
            "'Stop. Do not make changes until the user responds.' must appear in Phase 4"
        )

    def test_findings_format_reference(self):
        assert "references/findings-format.md" in self.s.body, (
            "references/findings-format.md must be referenced in the skill body"
        )

    def test_phase_ordering_gather_before_present(self):
        body = self.s.body
        phase1_pos = body.find("Phase 1 — Gather context")
        phase3_pos = body.find("Phase 3 — Present findings")
        phase4_pos = body.find("Phase 4 — Wait for feedback")
        assert phase1_pos != -1, "Phase 1 — Gather context not found"
        assert phase3_pos != -1, "Phase 3 — Present findings not found"
        assert phase4_pos != -1, "Phase 4 — Wait for feedback not found"
        assert phase1_pos < phase3_pos < phase4_pos, (
            "Phase ordering must be: Gather (1) → Present (3) → Wait (4)"
        )

    def test_eleven_dimensions_referenced(self):
        assert "references/dimensions.md" in self.s.body, (
            "references/dimensions.md must be referenced in the skill body"
        )


# ---------------------------------------------------------------------------
# managing-skills-claude
# ---------------------------------------------------------------------------


class TestManagingSkillsClaude:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("managing-skills-claude")

    def test_relative_symlink_paths_documented(self):
        assert "../skills-vendor/" in self.s.body, (
            "Relative symlink path '../skills-vendor/' must be documented (symlinks must be relative)"
        )

    def test_two_level_chain_documented(self):
        assert "../../skills/" in self.s.body, (
            "Two-level chain '../../skills/' must be documented for .claude/skills/ wiring"
        )

    def test_submodule_pattern_documented(self):
        assert "git submodule add" in self.s.body, (
            "Submodule add command must be documented"
        )
