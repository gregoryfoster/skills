"""Content invariant tests for SKILL.md files.

Verify that safety-critical text (hard gates, phase ordering, references) is
verbatim present in each skill. These tests catch accidental deletion of
behavioral contracts during edits.

Cross-cutting invariants are parameterized across the baseline and every stack
variant so drift is mechanically impossible. Stack-specific invariants live in
their own variant-only classes.

No API calls required.
"""

import pytest

from tests.utils.skill_loader import load_skill, SKILLS_DIR


def skill(name: str):
    return load_skill(SKILLS_DIR / name)


# ---------------------------------------------------------------------------
# shipping-work (baseline + variants)
# ---------------------------------------------------------------------------


@pytest.fixture(params=["shipping-work", "shipping-work-php", "shipping-work-python-fastapi", "shipping-work-python-click"])
def shipping_work_skill(request):
    return skill(request.param)


class TestShippingWork:
    """Cross-cutting invariants — must hold for the baseline and every variant."""

    def test_iron_law_no_closure_without_implementation(self, shipping_work_skill):
        assert "NO ISSUE CLOSURE WITHOUT FULL IMPLEMENTATION" in shipping_work_skill.body, (
            "Iron Law text 'NO ISSUE CLOSURE WITHOUT FULL IMPLEMENTATION' must be present verbatim"
        )

    def test_hard_gate_xml_block_present(self, shipping_work_skill):
        assert "<HARD-GATE>" in shipping_work_skill.body, (
            "<HARD-GATE> XML block must be present"
        )

    def test_step_ordering_step1_before_push(self, shipping_work_skill):
        body = shipping_work_skill.body
        # Step 1 name differs across variants; locate by leading marker only.
        step1_pos = body.find("### Step 1 —")
        step4_pos = body.find("Step 4 — Push")
        assert step1_pos != -1, "Step 1 header not found"
        assert step4_pos != -1, "Step 4 — Push not found"
        assert step1_pos < step4_pos, (
            "Step 1 must appear before Step 4 (Push) in the procedure"
        )

    def test_rationalization_table_present(self, shipping_work_skill):
        assert "Rationalization prevention" in shipping_work_skill.body, (
            "Rationalization prevention table must be present"
        )


class TestShippingWorkBaseline:
    """Baseline-only invariants — Iron Law first line + 'Run tests' wording."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("shipping-work")

    def test_iron_law_no_push_without_tests(self):
        assert "NO PUSH WITHOUT PASSING TESTS" in self.s.body, (
            "Baseline Iron Law text 'NO PUSH WITHOUT PASSING TESTS' must be present verbatim"
        )

    def test_step1_run_tests(self):
        assert "Step 1 — Run tests" in self.s.body, (
            "Baseline Step 1 heading must be 'Run tests'"
        )

    def test_no_continuation_if_tests_fail(self):
        assert "NO CONTINUATION IF TESTS FAIL" in self.s.body, (
            "'NO CONTINUATION IF TESTS FAIL' block must be present in baseline"
        )


class TestShippingWorkPhp:
    """PHP variant-only invariants."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("shipping-work-php")

    def test_iron_law_no_push_without_pre_ship_checks(self):
        assert "NO PUSH WITHOUT PASSING PRE-SHIP CHECKS" in self.s.body, (
            "PHP Iron Law text 'NO PUSH WITHOUT PASSING PRE-SHIP CHECKS' must be present verbatim"
        )

    def test_step1_run_pre_ship_checks(self):
        assert "Step 1 — Run pre-ship checks" in self.s.body, (
            "PHP variant Step 1 heading must be 'Run pre-ship checks'"
        )

    def test_no_continuation_if_checks_fail(self):
        assert "NO CONTINUATION IF CHECKS FAIL" in self.s.body, (
            "'NO CONTINUATION IF CHECKS FAIL' block must be present in PHP variant"
        )

    def test_h1_includes_php_suffix(self):
        assert "# Shipping Work — PHP" in self.s.body, (
            "PHP variant H1 must be '# Shipping Work — PHP'"
        )

    def test_wp_next_steps_categories_present(self):
        body = self.s.body
        for category in ("ACF JSON sync", "Asset build", "WP-CLI cache", "Composer deps"):
            assert category in body, f"WP next-steps category '{category}' must be present"


class TestShippingWorkPythonFastapi:
    """Python/FastAPI variant-only invariants."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("shipping-work-python-fastapi")

    def test_iron_law_no_push_without_pre_ship_checks(self):
        assert "NO PUSH WITHOUT PASSING PRE-SHIP CHECKS" in self.s.body, (
            "Python/FastAPI Iron Law text 'NO PUSH WITHOUT PASSING PRE-SHIP CHECKS' must be present verbatim"
        )

    def test_step1_run_pre_ship_checks(self):
        assert "Step 1 — Run pre-ship checks" in self.s.body, (
            "Python/FastAPI variant Step 1 heading must be 'Run pre-ship checks'"
        )

    def test_no_continuation_if_checks_fail(self):
        assert "NO CONTINUATION IF CHECKS FAIL" in self.s.body, (
            "'NO CONTINUATION IF CHECKS FAIL' block must be present in Python/FastAPI variant"
        )

    def test_h1_includes_python_fastapi_suffix(self):
        assert "# Shipping Work — Python/FastAPI" in self.s.body, (
            "Python/FastAPI variant H1 must be '# Shipping Work — Python/FastAPI'"
        )

    def test_fastapi_next_steps_categories_present(self):
        body = self.s.body
        for category in ("DB migration", "Service restart", "Integration tests", "Env var", "Dev-server cleanup"):
            assert category in body, f"FastAPI next-steps category '{category}' must be present"

    def test_auto_derived_stamp_prefix_documented(self):
        assert "auto-derives" in self.s.body or "auto-derived" in self.s.body, (
            "Variant must document that the per-SHA stamp prefix is auto-derived "
            "(eliminates the project-name substitution copy-paste bug class)"
        )


class TestShippingWorkPythonClick:
    """Python/Click variant-only invariants."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("shipping-work-python-click")

    def test_iron_law_no_push_without_pre_ship_checks(self):
        assert "NO PUSH WITHOUT PASSING PRE-SHIP CHECKS" in self.s.body, (
            "Python/Click Iron Law text 'NO PUSH WITHOUT PASSING PRE-SHIP CHECKS' must be present verbatim"
        )

    def test_step1_run_pre_ship_checks(self):
        assert "Step 1 — Run pre-ship checks" in self.s.body, (
            "Python/Click variant Step 1 heading must be 'Run pre-ship checks'"
        )

    def test_no_continuation_if_checks_fail(self):
        assert "NO CONTINUATION IF CHECKS FAIL" in self.s.body, (
            "'NO CONTINUATION IF CHECKS FAIL' block must be present in Python/Click variant"
        )

    def test_h1_includes_python_click_suffix(self):
        assert "# Shipping Work — Python/Click" in self.s.body, (
            "Python/Click variant H1 must be '# Shipping Work — Python/Click'"
        )

    def test_click_next_steps_categories_present(self):
        body = self.s.body
        for category in ("Dep update", "Cross-package consumer", "Pydantic pin", "New command"):
            assert category in body, f"Click next-steps category '{category}' must be present"

    def test_auto_detected_import_target_documented(self):
        body = self.s.body
        assert "auto-detected" in body, (
            "Variant must document that the import-check target is auto-detected from pyproject.toml"
        )
        assert ".skills/import-targets" in body, (
            "Variant must document the .skills/import-targets override path for multi-package projects"
        )

    def test_no_substitution_markers(self):
        body = self.s.body
        assert "<PROJECT_PACKAGE>" not in body, (
            "Variant must not carry <PROJECT_PACKAGE> substitution markers — "
            "import target is auto-detected from pyproject.toml"
        )


# ---------------------------------------------------------------------------
# init-project-fastapi
# ---------------------------------------------------------------------------


class TestInitProjectFastapi:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("init-project-fastapi")

    def test_hard_gate_xml_block_present(self):
        assert "<HARD-GATE>" in self.s.body, (
            "<HARD-GATE> XML block must be present in init-project-fastapi"
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
# reviewing-code (baseline + variants)
# ---------------------------------------------------------------------------


@pytest.fixture(params=["reviewing-code", "reviewing-code-php", "reviewing-code-python-fastapi", "reviewing-code-python-click"])
def reviewing_code_skill(request):
    return skill(request.param)


class TestReviewingCode:
    """Cross-cutting invariants — must hold for the baseline and every variant."""

    def test_iron_law_no_changes_without_report(self, reviewing_code_skill):
        assert "NO CHANGES WITHOUT A FINDINGS REPORT AND EXPLICIT USER DIRECTIVES" in reviewing_code_skill.body, (
            "Iron Law text 'NO CHANGES WITHOUT A FINDINGS REPORT AND EXPLICIT USER DIRECTIVES' "
            "must be present verbatim"
        )

    def test_iron_law_no_report_without_gather_context(self, reviewing_code_skill):
        assert "NO FINDINGS REPORT WITHOUT RUNNING GATHER-CONTEXT FIRST" in reviewing_code_skill.body, (
            "Iron Law text 'NO FINDINGS REPORT WITHOUT RUNNING GATHER-CONTEXT FIRST' "
            "must be present verbatim"
        )

    def test_phase4_wait_for_feedback_present(self, reviewing_code_skill):
        assert "Phase 4 — Wait for feedback" in reviewing_code_skill.body, (
            "Phase 4 — Wait for feedback must be present"
        )

    def test_phase4_stop_instruction(self, reviewing_code_skill):
        assert "Stop. Do not make changes until the user responds." in reviewing_code_skill.body, (
            "'Stop. Do not make changes until the user responds.' must appear in Phase 4"
        )

    def test_findings_format_inline(self, reviewing_code_skill):
        body = reviewing_code_skill.body
        assert "What:" in body, "'What:' label must appear in findings format"
        assert "Why it matters:" in body, "'Why it matters:' label must appear in findings format"
        assert "Suggested fix:" in body, "'Suggested fix:' label must appear in findings format"

    def test_directives_table_inline(self, reviewing_code_skill):
        body = reviewing_code_skill.body
        assert "`1: fix`" in body, "Directives table must list '1: fix' verbatim"
        assert "`3: stet`" in body, "Directives table must list '3: stet' verbatim"
        assert "`10: GH`" in body, "Directives table must list '10: GH' verbatim"

    def test_rationalization_table_present(self, reviewing_code_skill):
        assert "Rationalization prevention" in reviewing_code_skill.body, (
            "Rationalization prevention table must be present"
        )

    def test_phase_ordering_gather_before_present(self, reviewing_code_skill):
        body = reviewing_code_skill.body
        phase1_pos = body.find("Phase 1 — Gather context")
        phase3_pos = body.find("Phase 3 — Present findings")
        phase4_pos = body.find("Phase 4 — Wait for feedback")
        assert phase1_pos != -1, "Phase 1 — Gather context not found"
        assert phase3_pos != -1, "Phase 3 — Present findings not found"
        assert phase4_pos != -1, "Phase 4 — Wait for feedback not found"
        assert phase1_pos < phase3_pos < phase4_pos, (
            "Phase ordering must be: Gather (1) → Present (3) → Wait (4)"
        )


class TestReviewingCodePhp:
    """PHP variant-only invariants."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("reviewing-code-php")

    def test_h1_includes_php_suffix(self):
        assert "# Code & Documentation Review — PHP" in self.s.body, (
            "PHP variant H1 must be '# Code & Documentation Review — PHP'"
        )

    def test_bedrock_dimension_present(self):
        assert "Bedrock conventions" in self.s.body, (
            "Bedrock conventions dimension must be present in Phase 2"
        )

    def test_sage_dimension_present(self):
        assert "Sage 11 patterns" in self.s.body, (
            "Sage 11 patterns dimension must be present in Phase 2"
        )

    def test_sql_safety_dimension_present(self):
        assert "$wpdb->prepare()" in self.s.body, (
            "SQL safety dimension must mention $wpdb->prepare()"
        )

    def test_pint_lint_gate_present(self):
        assert "pint --test" in self.s.body, (
            "Phase 3.5 must mention 'pint --test' for PHP lint/format gate"
        )


class TestReviewingCodePythonFastapi:
    """Python/FastAPI variant-only invariants."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("reviewing-code-python-fastapi")

    def test_h1_includes_python_fastapi_suffix(self):
        assert "# Code & Documentation Review — Python/FastAPI" in self.s.body, (
            "Python/FastAPI variant H1 must be '# Code & Documentation Review — Python/FastAPI'"
        )

    def test_tdd_dimension_present(self):
        assert "TDD discipline" in self.s.body, (
            "TDD discipline dimension must be present in Phase 2"
        )

    def test_api_contract_dimension_present(self):
        assert "API contract" in self.s.body, (
            "API contract dimension must be present in Phase 2"
        )

    def test_logging_convention_dimension_present(self):
        body = self.s.body
        assert "Logging convention" in body, (
            "Logging convention dimension must be present in Phase 2"
        )
        assert "get_logger(__name__)" in body, (
            "Logging convention must reference get_logger(__name__)"
        )

    def test_datetime_convention_dimension_present(self):
        assert "Datetime convention" in self.s.body, (
            "Datetime convention dimension must be present in Phase 2"
        )

    def test_pydantic_idioms_dimension_present(self):
        assert "Pydantic v2 idioms" in self.s.body, (
            "Pydantic v2 idioms dimension must be present in Phase 2"
        )

    def test_ruff_lint_gate_present(self):
        body = self.s.body
        assert "uv run ruff check" in body, (
            "Phase 3.5 must mention 'uv run ruff check' for Python lint gate"
        )
        assert "uv run ruff format --check" in body, (
            "Phase 3.5 must mention 'uv run ruff format --check' for Python format gate"
        )

    def test_pytest_excluded_from_review(self):
        assert "Do not run pytest during a review" in self.s.body, (
            "Variant must instruct reviewers not to run the full pytest suite "
            "during review (full-suite runs belong in pre-ship.sh)"
        )


class TestReviewingCodePythonClick:
    """Python/Click variant-only invariants."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("reviewing-code-python-click")

    def test_h1_includes_python_click_suffix(self):
        assert "# Code & Documentation Review — Python/Click" in self.s.body, (
            "Python/Click variant H1 must be '# Code & Documentation Review — Python/Click'"
        )

    def test_click_command_correctness_dimension_present(self):
        assert "Click command correctness" in self.s.body, (
            "Click command correctness dimension must be present in Phase 2"
        )

    def test_paramtype_testability_dimension_present(self):
        body = self.s.body
        assert "ParamType testability" in body, (
            "ParamType testability dimension must be present in Phase 2"
        )
        assert "ParamType.callback()" in body, (
            "ParamType testability must reference callback() vs convert()"
        )

    def test_command_registration_dimension_present(self):
        assert "Command registration" in self.s.body, (
            "Command registration dimension must be present in Phase 2"
        )

    def test_pydantic_idioms_dimension_present(self):
        assert "Pydantic v2 idioms" in self.s.body, (
            "Pydantic v2 idioms dimension must be present in Phase 2"
        )

    def test_cross_package_boundary_dimension_present(self):
        assert "Cross-package boundary" in self.s.body, (
            "Cross-package boundary dimension must be present in Phase 2"
        )

    def test_ruff_lint_gate_present(self):
        body = self.s.body
        assert "uv run ruff check" in body, (
            "Phase 3.5 must mention 'uv run ruff check' for Python lint gate"
        )
        assert "uv run ruff format --check" in body, (
            "Phase 3.5 must mention 'uv run ruff format --check' for Python format gate"
        )

    def test_auto_detected_import_target_documented(self):
        body = self.s.body
        assert "auto-detected from `pyproject.toml`" in body or "auto-detected from pyproject.toml" in body, (
            "Variant must document that the import target is auto-detected from pyproject.toml"
        )
        assert ".skills/import-targets" in body, (
            "Variant must document the .skills/import-targets override path"
        )

    def test_no_substitution_markers(self):
        body = self.s.body
        assert "<PROJECT_PACKAGE>" not in body, (
            "Variant must not carry <PROJECT_PACKAGE> substitution markers — "
            "import target is auto-detected from pyproject.toml"
        )


# ---------------------------------------------------------------------------
# reviewing-architecture
# ---------------------------------------------------------------------------


class TestReviewingArchitecture:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("reviewing-architecture")

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
# managing-skills
# ---------------------------------------------------------------------------


class TestManagingSkills:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("managing-skills")

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
