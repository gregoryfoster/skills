"""Content invariant tests for SKILL.md files.

Verify that safety-critical text (hard gates, phase ordering, references) is
verbatim present in each skill. These tests catch accidental deletion of
behavioral contracts during edits.

Cross-cutting invariants are parameterized across the baseline and every stack
variant so drift is mechanically impossible. Stack-specific invariants live in
their own variant-only classes.

No API calls required.
"""

import re

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

    def test_parameterized_invocation_section_present(self, shipping_work_skill):
        assert "## Parameterized invocation" in shipping_work_skill.body, (
            "Parameterized invocation section must be present (formalizes inline scope "
            "in trigger phrases, e.g., `wrap up #19 #20`)"
        )


class TestShippingWorkBaseline:
    """Baseline-only invariants — Iron Law first line + 'Run tests' wording."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("shipping-work")

    def test_iron_law_no_push_without_pre_ship_checks(self):
        assert "NO PUSH WITHOUT PASSING PRE-SHIP CHECKS" in self.s.body, (
            "Baseline Iron Law text 'NO PUSH WITHOUT PASSING PRE-SHIP CHECKS' must be present verbatim"
        )

    def test_step1_run_pre_ship_checks(self):
        assert "Step 1 — Run pre-ship checks" in self.s.body, (
            "Baseline Step 1 heading must be 'Run pre-ship checks'"
        )

    def test_no_continuation_if_checks_fail(self):
        assert "NO CONTINUATION IF CHECKS FAIL" in self.s.body, (
            "'NO CONTINUATION IF CHECKS FAIL' block must be present in baseline"
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

    def test_worktree_aware_merge_step_present(self):
        body = self.s.body
        assert "Step 2.5 — Worktree-aware merge" in body, (
            "Step 2.5 (worktree-aware merge) must be present in the FastAPI variant — "
            "it closes the loop opened in #10 (deferred until using-git-worktrees landed)"
        )
        assert "using-git-worktrees" in body, (
            "Step 2.5 must reference the using-git-worktrees skill by name (hard cross-reference) "
            "so the agent can discover and invoke the worktree workflow when it applies"
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

    def test_writing_plans_cross_reference_present(self):
        body = self.s.body
        assert "writing-plans" in body, (
            "init-project-fastapi must reference the writing-plans skill by name — "
            "the bootstrap creates `docs/plans/` and the skill governs what goes in it"
        )


# ---------------------------------------------------------------------------
# using-git-worktrees
# ---------------------------------------------------------------------------


class TestUsingGitWorktrees:
    """Invariants for the using-git-worktrees workflow skill.

    This is a workflow skill (not a review skill), so it does not carry a
    findings-format or directives table — but it does carry an Iron Law,
    Rationalization-prevention table, Parameterized invocation block, and
    a six-phase procedure (1, 2, 3, 3.5, 4, 5). Phase 3.5 is the worktree-
    health verification gate; the test below asserts it explicitly so it
    cannot be silently deleted.
    """

    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("using-git-worktrees")

    def test_h1_present(self):
        assert "# Using Git Worktrees" in self.s.body, (
            "H1 must be '# Using Git Worktrees'"
        )

    def test_iron_law_no_destroy_without_merge(self):
        assert "NO WORKTREE DESTROY WITHOUT VERIFIED MERGE OR EXPLICIT DESCOPE" in self.s.body, (
            "Iron Law line 1 must be present verbatim"
        )

    def test_iron_law_no_double_checkout(self):
        assert "NO BRANCH CHECKED OUT IN TWO WORKTREES SIMULTANEOUSLY" in self.s.body, (
            "Iron Law line 2 must be present verbatim"
        )

    def test_rationalization_table_present(self):
        assert "Rationalization prevention" in self.s.body, (
            "Rationalization prevention table must be present"
        )

    def test_parameterized_invocation_section_present(self):
        assert "## Parameterized invocation" in self.s.body, (
            "Parameterized invocation section must be present (formalizes inline branch "
            "in trigger phrases, e.g., `create worktree feature/foo`)"
        )

    def test_resolution_order_documented(self):
        body = self.s.body
        for token in ("WORKTREE_ROOT", ".skills/worktree_root", ".worktrees/"):
            assert token in body, (
                f"Worktree-root resolution order must mention '{token}' "
                "(env var → .skills/worktree_root → <repo>/.worktrees/)"
            )

    def test_all_phases_present(self):
        body = self.s.body
        for phase in (
            "Phase 1 — Decide",
            "Phase 2 — Create",
            "Phase 3 — Work",
            "Phase 3.5 — Verify",
            "Phase 4 — Merge",
            "Phase 5 — Destroy",
        ):
            assert phase in body, f"'{phase}' header must be present"

    def test_phase_ordering(self):
        body = self.s.body
        positions = [body.find(p) for p in (
            "Phase 1 — Decide",
            "Phase 2 — Create",
            "Phase 3 — Work",
            "Phase 3.5 — Verify",
            "Phase 4 — Merge",
            "Phase 5 — Destroy",
        )]
        assert all(p != -1 for p in positions), "All phases must be discoverable"
        assert positions == sorted(positions), (
            "Phases must appear in numeric order in the body "
            "(Phase 3.5 between Phase 3 and Phase 4)"
        )

    def test_scripts_referenced_in_body(self):
        body = self.s.body
        for script in ("worktree-create.sh", "worktree-destroy.sh", "worktree-list.sh", "resolve-worktree-root.sh"):
            assert script in body, (
                f"Script '{script}' must be referenced in SKILL.md body"
            )

    def test_descoped_flag_documented(self):
        body = self.s.body
        assert "--descoped" in body, (
            "Iron Law escape hatch '--descoped <reason>' must be documented "
            "(used by worktree-destroy.sh to acknowledge an intentional descope)"
        )


# ---------------------------------------------------------------------------
# writing-plans
# ---------------------------------------------------------------------------


class TestWritingPlans:
    """Invariants for the writing-plans discipline skill.

    Lighter than using-git-worktrees — no multi-phase stateful workflow — but
    carries an Iron Law, Rationalization-prevention table, Parameterized
    invocation block, plans-directory resolution order, and the prescribed
    plan structure (problem / approach / tradeoffs / steps / open questions).
    """

    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("writing-plans")

    def test_h1_present(self):
        assert "# Writing Plans" in self.s.body, (
            "H1 must be '# Writing Plans'"
        )

    def test_iron_law_no_implementation_without_plan(self):
        assert "NO NON-TRIVIAL IMPLEMENTATION WITHOUT A WRITTEN, REVIEWED PLAN" in self.s.body, (
            "Iron Law text 'NO NON-TRIVIAL IMPLEMENTATION WITHOUT A WRITTEN, REVIEWED PLAN' "
            "must be present verbatim"
        )

    def test_rationalization_table_present(self):
        assert "Rationalization prevention" in self.s.body, (
            "Rationalization prevention table must be present"
        )

    def test_parameterized_invocation_section_present(self):
        assert "## Parameterized invocation" in self.s.body, (
            "Parameterized invocation section must be present (formalizes inline topic "
            "in trigger phrases, e.g., `write a plan for auth rotation`)"
        )

    def test_resolution_order_documented(self):
        body = self.s.body
        for token in ("PLANS_DIR", ".skills/plans_dir", "docs/plans/"):
            assert token in body, (
                f"Plans-directory resolution order must mention '{token}' "
                "(env var → .skills/plans_dir → <repo>/docs/plans/)"
            )

    def test_plan_structure_sections_documented(self):
        body = self.s.body
        for section in ("Problem", "Approach", "Tradeoffs", "Steps", "Open questions"):
            assert section in body, (
                f"Prescribed plan section '{section}' must be documented in the body"
            )

    def test_script_referenced_in_body(self):
        assert "resolve-plans-dir.sh" in self.s.body, (
            "Script 'resolve-plans-dir.sh' must be referenced in SKILL.md body"
        )

    def test_template_referenced_in_body(self):
        assert "assets/plan-template.md" in self.s.body, (
            "Plan template 'assets/plan-template.md' must be referenced in SKILL.md body"
        )

    def test_all_phases_present(self):
        body = self.s.body
        for phase in (
            "Phase 1 — Decide",
            "Phase 2 — Draft",
            "Phase 3 — Request review",
            "Phase 4 — Execute",
        ):
            assert phase in body, f"'{phase}' header must be present"

    def test_phase_ordering(self):
        body = self.s.body
        positions = [body.find(p) for p in (
            "Phase 1 — Decide",
            "Phase 2 — Draft",
            "Phase 3 — Request review",
            "Phase 4 — Execute",
        )]
        assert all(p != -1 for p in positions), "All phases must be discoverable"
        assert positions == sorted(positions), (
            "Phases must appear in numeric order in the body"
        )

    def test_supersedes_chain_documented(self):
        assert "Supersedes" in self.s.body, (
            "Plan-supersession convention ('Supersedes: <old-plan-path>') must be documented "
            "so pivots produce a discoverable chain"
        )


# ---------------------------------------------------------------------------
# orchestrating-issue-backlog
# ---------------------------------------------------------------------------


class TestOrchestratingIssueBacklog:
    """Cross-reference invariant — orchestrating-issue-backlog writes design
    docs into the plans directory, so it must hard-reference writing-plans
    by name. Keeps the dependency graph visible and structural."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("orchestrating-issue-backlog")

    def test_writing_plans_cross_reference_present(self):
        assert "writing-plans" in self.s.body, (
            "orchestrating-issue-backlog must reference the writing-plans skill by name — "
            "design docs land in the plans directory governed by that skill"
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

    def test_parameterized_invocation_section_present(self, reviewing_code_skill):
        assert "## Parameterized invocation" in reviewing_code_skill.body, (
            "Parameterized invocation section must be present (formalizes inline scope "
            "in trigger phrases, e.g., `CR #14`)"
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
# Python/Click cross-script integration
# ---------------------------------------------------------------------------


class TestPythonClickHelperIntegration:
    """Both review and ship must resolve import targets via the same helper —
    a regression here would let the two skills disagree about which package
    to import-check."""

    @pytest.fixture(
        params=[
            "reviewing-code-python-click/scripts/gather-context.sh",
            "shipping-work-python-click/scripts/pre-ship.sh",
        ],
        ids=lambda p: p.split("/")[0] + "/" + p.split("/")[-1],
    )
    def script_path(self, request):
        return SKILLS_DIR / request.param

    def test_invokes_detect_import_targets_helper(self, script_path):
        content = script_path.read_text()
        assert "detect-import-targets.sh" in content, (
            f"{script_path.parent.parent.name}/{script_path.name} must invoke "
            "detect-import-targets.sh — review and ship must agree on the "
            "import target via one canonical resolver"
        )

    def test_invokes_detect_test_dirs_helper(self, script_path):
        content = script_path.read_text()
        assert "detect-test-dirs.sh" in content, (
            f"{script_path.parent.parent.name}/{script_path.name} must invoke "
            "detect-test-dirs.sh — review and ship must agree on test "
            "directory discovery via one canonical resolver"
        )


class TestPythonClickHelperByteEquality:
    """Each helper exists as an independent copy in both reviewing-code-python-click/scripts/
    and shipping-work-python-click/scripts/ so each variant is self-contained per the
    Agent Skills spec (no cross-skill symlinks). The two copies must stay byte-equal
    until intentionally diverged — if you genuinely need them to differ, delete this
    test class and document the divergence in both scripts' headers.
    """

    @pytest.fixture(
        params=["detect-import-targets.sh", "detect-test-dirs.sh"],
        ids=lambda n: n,
    )
    def helper_name(self, request):
        return request.param

    def test_review_and_ship_copies_byte_equal(self, helper_name):
        review = SKILLS_DIR / "reviewing-code-python-click" / "scripts" / helper_name
        ship = SKILLS_DIR / "shipping-work-python-click" / "scripts" / helper_name
        assert review.exists(), f"missing helper copy in reviewing-code-python-click: {helper_name}"
        assert ship.exists(), f"missing helper copy in shipping-work-python-click: {helper_name}"
        assert not review.is_symlink(), (
            f"reviewing-code-python-click/scripts/{helper_name} is a symlink — variants must be "
            "self-contained per the Agent Skills spec; replace with a real copy"
        )
        assert not ship.is_symlink(), (
            f"shipping-work-python-click/scripts/{helper_name} is a symlink — variants must be "
            "self-contained per the Agent Skills spec; replace with a real copy"
        )
        assert review.read_bytes() == ship.read_bytes(), (
            f"{helper_name} differs between reviewing-code-python-click and "
            f"shipping-work-python-click copies. Either re-sync them or delete this "
            f"assertion and document the intended divergence."
        )


# ---------------------------------------------------------------------------
# Pre-ship gate-script hardening (cross-variant)
# ---------------------------------------------------------------------------


_PROCESS_SUBSTITUTION_DONE = re.compile(r"\bdone\s*<\s*<\(")
_UNHARDENED_ESCAPE = re.compile(r"#\s*unhardened\s*:", re.IGNORECASE)
_GATE_HARDENING_LOOKBACK = 10


def _unhardened_process_substitution_sites(content: str) -> list[tuple[int, str]]:
    """Locate `done < <(...)` lines lacking an `# unhardened: <reason>` escape
    on the same line or within the prior 10 lines. Pure-comment lines (first
    non-whitespace char is `#`) are skipped so explanatory prose citing the
    anti-pattern doesn't trip the gate. Returns [(1-indexed lineno, line), ...]."""
    lines = content.splitlines()
    violations = []
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        if not _PROCESS_SUBSTITUTION_DONE.search(line):
            continue
        window = lines[max(0, i - _GATE_HARDENING_LOOKBACK) : i + 1]
        if any(_UNHARDENED_ESCAPE.search(w) for w in window):
            continue
        violations.append((i + 1, line.rstrip()))
    return violations


class TestPreShipGateHardening:
    """Enforce the gate-script discipline codified in AGENTS.md.

    Pre-ship scripts must not use `done < <(producer ...)` for control-flow
    inputs: process-substitution exit codes aren't visible in the parent shell,
    so a producer failure (git, find, helper script) silently empties the loop
    and the gate falsely passes. The canonical hardened pattern captures
    producer output to a tempfile and its exit code into a scalar — see
    `LS_RC` in skills/shipping-work-php/scripts/pre-ship.sh and the
    "Gate-script discipline" subsection in AGENTS.md.

    Scope is intentionally pre-ship only. Review/gather-context scripts are
    reporting-only producers (degraded output is acceptable), so they are
    exempt — extending this assertion to them would force the existing
    legitimate process-substitution sites in those scripts to be rewritten
    unnecessarily.

    Escape hatch: tag the loop with `# unhardened: <reason>` either on the
    `done` line itself or anywhere within the prior 10 lines, if a
    process-substitution input is genuinely required.
    """

    _PRE_SHIP_PATHS = sorted(
        p.relative_to(SKILLS_DIR).as_posix()
        for p in SKILLS_DIR.glob("shipping-work*/scripts/pre-ship.sh")
    )

    @pytest.fixture(
        params=_PRE_SHIP_PATHS,
        ids=lambda p: p.split("/")[0],
    )
    def script_path(self, request):
        return SKILLS_DIR / request.param

    def test_pre_ship_scripts_discovered(self):
        # Sanity guard: if the glob ever returns nothing, the parameterized
        # test would silently skip and the gate would vanish unnoticed.
        assert len(self._PRE_SHIP_PATHS) >= 1, (
            "Glob `shipping-work*/scripts/pre-ship.sh` matched zero files — "
            "the hardening gate has silently disabled itself. Check whether "
            "the skills/ directory layout or naming convention changed."
        )

    def test_no_unhardened_process_substitution(self, script_path):
        violations = _unhardened_process_substitution_sites(script_path.read_text())
        assert not violations, (
            f"{script_path.relative_to(SKILLS_DIR)} contains unhardened "
            f"`done < <(...)` site(s):\n"
            + "\n".join(f"  line {ln}: {txt}" for ln, txt in violations)
            + "\n\nGate-script inputs must capture the producer's exit code. "
            "Replace with the tempfile + `*_RC=$?` pattern (see `LS_RC` in "
            "skills/shipping-work-php/scripts/pre-ship.sh and the "
            '"Gate-script discipline" subsection of AGENTS.md). '
            "If process substitution is genuinely required, tag the loop "
            "with `# unhardened: <reason>` on the `done` line itself or "
            "anywhere within the prior 10 lines."
        )


class TestProcessSubstitutionDetector:
    """Unit-test the gate-script detector function directly. The integration
    test above exercises it only against current scripts (which have zero
    violations); these synthetic cases lock in the behavioral guarantees
    so a future refactor of the regex or lookback can't silently weaken
    detection."""

    def test_inline_one_liner_regression_detected(self):
        # The most common bash form: `while ...; do ...; done < <(producer)`.
        src = 'while IFS= read -r f; do TRACKED+=("$f"); done < <(git ls-files)'
        v = _unhardened_process_substitution_sites(src)
        assert len(v) == 1, f"inline one-liner regression must trip, got {v}"

    def test_multiline_loop_regression_detected(self):
        src = "while read x; do\n  echo \"$x\"\ndone < <(producer)\n"
        v = _unhardened_process_substitution_sites(src)
        assert len(v) == 1, f"multiline `done < <(...)` must trip, got {v}"

    def test_hardened_tempfile_form_clean(self):
        src = (
            "LS_RC=0\n"
            'git ls-files >"$LS_OUT" || LS_RC=$?\n'
            'while read x; do :; done < "$LS_OUT"\n'
        )
        assert _unhardened_process_substitution_sites(src) == []

    def test_escape_hatch_prior_line_bypasses(self):
        src = (
            "# unhardened: producer is a constant printf, no failure mode\n"
            'while read x; do :; done < <(printf "a\\nb\\n")\n'
        )
        assert _unhardened_process_substitution_sites(src) == []

    def test_escape_hatch_inline_same_line_bypasses(self):
        # Finding 2: a `# unhardened:` comment on the `done` line itself
        # must also be honored — inline suppression is ergonomic and common.
        src = 'while read x; do :; done < <(producer)  # unhardened: deliberate'
        assert _unhardened_process_substitution_sites(src) == []

    def test_stale_escape_hatch_beyond_lookback_rejected(self):
        # An `# unhardened:` comment more than 10 lines above the offending
        # `done` must NOT greenlight it — otherwise stale comments could
        # silently authorize unrelated regressions further down the file.
        src = "# unhardened: legitimate older site\n" + "\n" * 12 + "while read x; do :; done < <(producer)\n"
        v = _unhardened_process_substitution_sites(src)
        assert len(v) == 1, f"stale whitelist >10 lines away must not bypass, got {v}"

    def test_pure_comment_line_not_flagged(self):
        # Finding 1: explanatory prose citing the anti-pattern (common in
        # AGENTS.md-style comments) must not trip the gate.
        src = "# Never write `done < <(producer)` in a gate context — see AGENTS.md.\n"
        assert _unhardened_process_substitution_sites(src) == []

    def test_indented_comment_line_not_flagged(self):
        src = "    # example: done < <(producer)  # for illustration only"
        assert _unhardened_process_substitution_sites(src) == []


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

    def test_iron_law_no_report_without_gather_context(self):
        assert "NO FINDINGS REPORT WITHOUT RUNNING GATHER-CONTEXT FIRST" in self.s.body, (
            "Iron Law text 'NO FINDINGS REPORT WITHOUT RUNNING GATHER-CONTEXT FIRST' must be present verbatim"
        )

    def test_iron_law_no_changes_without_report(self):
        assert "NO CHANGES WITHOUT A FINDINGS REPORT AND EXPLICIT USER DIRECTIVES" in self.s.body, (
            "Iron Law text 'NO CHANGES WITHOUT A FINDINGS REPORT AND EXPLICIT USER DIRECTIVES' must be present verbatim"
        )

    def test_rationalization_table_present(self):
        assert "Rationalization prevention" in self.s.body, (
            "Rationalization prevention table must be present"
        )

    def test_findings_format_inline(self):
        body = self.s.body
        assert "What:" in body, "'What:' label must appear in findings format"
        assert "Why it matters:" in body, "'Why it matters:' label must appear in findings format"
        assert "Suggested approach:" in body, "'Suggested approach:' label must appear in findings format"

    def test_directives_table_inline(self):
        body = self.s.body
        assert "`1: fix`" in body, "Directives table must list '1: fix' verbatim"
        assert "`3: stet`" in body, "Directives table must list '3: stet' verbatim"
        assert "`10: GH`" in body, "Directives table must list '10: GH' verbatim"

    def test_phase35_verify_before_reporting(self):
        assert "Phase 3.5 — Verify before reporting" in self.s.body, (
            "Phase 3.5 verification gate must be present"
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

    def test_parameterized_invocation_section_present(self):
        assert "## Parameterized invocation" in self.s.body, (
            "Parameterized invocation section must be present (formalizes inline scope "
            "in trigger phrases, e.g., `AR services/`)"
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


# ---------------------------------------------------------------------------
# reviewing-code gather-context.sh shared-baseline (drift assertion)
# ---------------------------------------------------------------------------


REVIEWING_CODE_GATHER_CONTEXT_PATHS = sorted(
    p.relative_to(SKILLS_DIR).as_posix()
    for p in SKILLS_DIR.glob("reviewing-code*/scripts/gather-context.sh")
)

# Each variant's gather-context.sh must invoke these commands. Captures the
# shared boilerplate that's duplicated across variants; if one variant drops
# (or renames) a required command, this test catches it before that variant
# loses parity with the baseline.
GATHER_CONTEXT_REQUIRED_COMMANDS = [
    "git rev-parse --show-toplevel",
    "git status --short",
    "git diff --staged",
    "git diff --stat",
    "git log --oneline",
    "git diff --name-only HEAD",
]


class TestReviewingCodeGatherContextSharedBaseline:
    """The reviewing-code* gather-context.sh files share a boilerplate baseline
    (project-root resolution + git status/diffs/log/changed-files). Stack
    variants extend it with stack-specific commands (composer validate, ruff,
    etc.) but must not drop the shared baseline — otherwise the variant's
    Phase 1 returns less context than the user expects from a "code review."
    """

    @pytest.fixture(
        params=REVIEWING_CODE_GATHER_CONTEXT_PATHS,
        ids=lambda p: p.split("/")[0],
    )
    def script(self, request):
        return (SKILLS_DIR / request.param).read_text()

    def test_shebang(self, script):
        assert script.startswith("#!/usr/bin/env bash\n"), (
            "gather-context.sh must start with `#!/usr/bin/env bash`"
        )

    def test_set_euo_pipefail(self, script):
        assert "set -euo pipefail" in script, (
            "gather-context.sh must declare `set -euo pipefail`"
        )

    def test_help_flag_handler(self, script):
        assert '"${1:-}" == "--help"' in script, (
            "gather-context.sh must handle a --help flag"
        )

    @pytest.mark.parametrize("cmd", GATHER_CONTEXT_REQUIRED_COMMANDS)
    def test_required_command_present(self, script, cmd):
        assert cmd in script, (
            f"gather-context.sh must invoke `{cmd}` — shared baseline across the "
            "reviewing-code* family. If this variant intentionally drops the command, "
            "remove it from GATHER_CONTEXT_REQUIRED_COMMANDS and document the divergence."
        )


# ---------------------------------------------------------------------------
# Cross-family variant consistency (drift assertions)
# ---------------------------------------------------------------------------


# (base, variant, stack-keyword-required-in-compatibility)
VARIANT_FAMILY_PAIRS = [
    ("reviewing-code", "reviewing-code-php", "PHP"),
    ("reviewing-code", "reviewing-code-python-fastapi", "FastAPI"),
    ("reviewing-code", "reviewing-code-python-click", "Click"),
    ("shipping-work", "shipping-work-php", "PHP"),
    ("shipping-work", "shipping-work-python-fastapi", "FastAPI"),
    ("shipping-work", "shipping-work-python-click", "Click"),
]


def _iron_law_first_line(body: str) -> str:
    """Extract the first line inside the Iron Law code fence."""
    m = re.search(r"## The Iron Law\s*\n+```\s*\n(.+?)\n", body)
    return m.group(1) if m else ""


class TestVariantFamilyConsistency:
    """Drift assertions across each baseline + variant family.

    Catches the class of drift surfaced in the post-#11 review: identical
    descriptions across variants, missing stack keyword in compatibility,
    trigger drift between baseline and variant, and Iron Law text drift
    between baseline and variants (the kind that left shipping-work baseline
    on `NO PUSH WITHOUT PASSING TESTS` while all three variants used
    `NO PUSH WITHOUT PASSING PRE-SHIP CHECKS` until #c3316b0 generalized it).
    """

    @pytest.fixture(
        params=VARIANT_FAMILY_PAIRS,
        ids=lambda p: f"{p[1]}_vs_{p[0]}",
    )
    def pair(self, request):
        base_name, variant_name, stack_keyword = request.param
        return skill(base_name), skill(variant_name), stack_keyword

    def test_triggers_match_baseline(self, pair):
        base, variant, _ = pair
        base_triggers = (base.skill_metadata.get("triggers") or "").strip()
        variant_triggers = (variant.skill_metadata.get("triggers") or "").strip()
        assert base_triggers, f"{base.name}: missing metadata.triggers"
        assert variant_triggers, f"{variant.name}: missing metadata.triggers"
        assert variant_triggers == base_triggers, (
            f"{variant.name} triggers ({variant_triggers!r}) must match baseline "
            f"{base.name} triggers ({base_triggers!r}) — the runtime selects on triggers, "
            "so divergence breaks variant discovery"
        )

    def test_description_differs_from_baseline(self, pair):
        base, variant, _ = pair
        assert variant.description != base.description, (
            f"{variant.name} description must differ from baseline {base.name} — "
            "identical descriptions give the runtime no signal to prefer the right variant. "
            "Prepend a stack identifier (e.g., 'For PHP/WordPress projects:')"
        )

    def test_compatibility_mentions_stack(self, pair):
        base, variant, stack_keyword = pair
        assert stack_keyword.lower() in variant.compatibility.lower(), (
            f"{variant.name} compatibility must mention {stack_keyword!r} so consumers "
            f"can tell what stack this variant targets. Got: {variant.compatibility!r}"
        )

    def test_iron_law_first_line_matches_baseline(self, pair):
        base, variant, _ = pair
        base_first = _iron_law_first_line(base.body)
        variant_first = _iron_law_first_line(variant.body)
        assert base_first, f"{base.name}: could not locate Iron Law first line"
        assert variant_first, f"{variant.name}: could not locate Iron Law first line"
        assert variant_first == base_first, (
            f"{variant.name} Iron Law first line ({variant_first!r}) must match "
            f"baseline {base.name} ({base_first!r}). The Iron Law states what must be "
            "true, not which tool — variant-specific tooling lives in gather-context.sh "
            "and pre-ship.sh, not the law."
        )
