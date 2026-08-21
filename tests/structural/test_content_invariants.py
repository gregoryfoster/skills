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
        expected = (
            "Do NOT create files in the bootstrapped project's working tree "
            "or run project-mutating commands until"
        )
        assert expected in self.s.body, (
            f"Hard gate text {expected!r} must be present verbatim"
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
# vendoring-openapi-client
# ---------------------------------------------------------------------------


class TestVendoringOpenapiClient:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.s = skill("vendoring-openapi-client")

    def test_hard_gate_xml_block_present(self):
        assert "<HARD-GATE>" in self.s.body, (
            "<HARD-GATE> XML block must be present in vendoring-openapi-client"
        )

    def test_hard_gate_collect_params_first(self):
        expected = "Do NOT create or modify files in the consumer repo until you have collected"
        assert expected in self.s.body, (
            f"Hard gate text {expected!r} must be present verbatim"
        )

    def test_branch_point_parameters_listed(self):
        for param in ["OUTPUT_LAYOUT", "FILTER_SPEC", "DRIFT_GUARD"]:
            assert param in self.s.body, f"Branch-point parameter '{param}' must be documented"

    def test_contract_of_record_invariant(self):
        assert "contract-of-record" in self.s.body, (
            "The snapshot-is-contract-of-record invariant must be stated — it is the "
            "load-bearing rule (generate from the snapshot, never from the live producer)"
        )

    def test_hermetic_gate_limitation_stated(self):
        assert "cannot detect snapshot-vs-live staleness" in self.s.body, (
            "The skill must state the hermetic CI gate's blind spot verbatim — "
            "removing it invites claiming coverage the gate doesn't provide"
        )

    def test_live_drift_never_merge_blocker(self):
        assert "never merge" in self.s.body, (
            "Live-drift guards must be documented as never being merge blockers"
        )

    def test_refresh_mode_present(self):
        assert "## Refresh mode" in self.s.body, (
            "Refresh mode (update path for an existing vendored client) must be present — "
            "it is a first-class flow, not an afterthought (#66 review point 3)"
        )

    def test_asset_scripts_exist_and_referenced(self):
        for asset in ["filter_openapi_spec.py", "check_client_drift.py"]:
            assert (self.s.directory / "assets" / asset).exists(), (
                f"assets/{asset} must ship with the skill"
            )
            assert asset in self.s.body, (
                f"assets/{asset} must be referenced from SKILL.md"
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

    def test_base_flag_documented(self):
        body = self.s.body
        assert "--base" in body, (
            "Base-ref override '--base <ref>' must be documented "
            "(used by worktree-destroy.sh to verify merge into a non-default "
            "integration branch such as 'batch/<x>' in multi-agent orchestrations)"
        )

    def test_venv_remedy_documented(self):
        """#156: a linked worktree inherits no virtualenv.

        worktree-create.sh links the parent's, but a harness-provisioned
        worktree never runs that script — so the manual one-liner has to be
        readable here too, or the next agent rediscovers it the way three of
        four did in #155 Batch C: as a rejected commit after a green suite.
        """
        body = self.s.body
        assert "ln -s" in body and ".venv" in body, (
            "SKILL.md must state the `ln -s <main-checkout>/.venv .venv` remedy "
            "for a linked worktree that has no virtualenv (#156)"
        )
        assert "isolation" in body or "harness" in body, (
            "SKILL.md must say the remedy is still needed by hand in "
            "harness-provisioned worktrees, which do not run worktree-create.sh"
        )

    def test_venv_opt_out_knob_documented(self):
        """#201: linking is right by default and wrong for one shape.

        The remedy asserted above tells a reader to link. The knob is the
        opt-out, so it has to be readable in the same file or the two halves
        contradict each other: an operator who was told to `ln -s` has no way
        to learn that this project told the script not to.
        """
        body = self.s.body
        assert ".skills/worktree_venv" in body, (
            "SKILL.md must document the `.skills/worktree_venv` knob (#201)"
        )
        assert "`none`" in body and "`link`" in body, (
            "both accepted values must be named, and which one is the default"
        )

    def test_service_working_directory_hazard_documented(self):
        """Name the mechanisms, not just the rule.

        A reader who has only "do not link when the checkout is a service's
        working directory" cannot tell whether their project is that case. The
        two uv behaviours are the recognisable symptoms: a version assertion
        that fails in a full run and passes in isolation, and a suite that
        quietly reports skips where it used to report passes.
        """
        body = self.s.body
        assert "WorkingDirectory" in body, (
            "SKILL.md must name the shape — the main checkout is also a "
            "running service's `WorkingDirectory=` (#201)"
        )
        for token in ("uv run", "uv sync"):
            assert token in body, (
                f"SKILL.md must name `{token}` as one of the two mechanisms "
                "that rewrite the shared venv under a worktree's test run"
            )

    def test_knob_tracking_is_addressed(self):
        """#202: an untracked `.skills/` file does not exist in a linked worktree.

        `.skills/worktree_root` survives that because it is resolved against
        the primary checkout, and this knob has to say it does the same — a
        reader who assumes otherwise will commit the file to make it work, and
        push a machine-local setting to every clone.
        """
        body = self.s.body
        assert "primary checkout" in body, (
            "SKILL.md must say the knob is read from the primary checkout, so "
            "it works untracked from inside a worktree too (#201, #202)"
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

    # -- worktree base (#150) ------------------------------------------------
    #
    # The harness cuts every agent worktree from `origin/main`, regardless of
    # what the orchestrator has checked out. Sub-wave 1 hides it (the batch
    # branch still equals main); by sub-wave 2 the batch branch carries merged
    # work the agent's tree does not have. In #144 Batch A two of four agents
    # in one sub-wave caught it; the other two would have measured and edited
    # a tree missing eight merged issues. The three assertions below pin the
    # statement, the remediation, and the detector respectively — the skill
    # previously described this as variance ("some agents branch from
    # origin/main, others from the orchestrator's current local HEAD"), which
    # is unfalsifiable advice and produced no action.

    def test_worktree_base_stated_as_fact_not_variance(self):
        body = self.s.body
        assert "independent of the orchestrator's checked-out branch" in body, (
            "Rule 3 must state the worktree base as fact: worktrees are created "
            "from `origin/main`, independent of the orchestrator's checked-out "
            "branch. `git checkout -b batch/<X>` sets the merge TARGET, not the "
            "base — a reader who believes otherwise skips the remediation."
        )
        assert "Branch base also varies" not in body, (
            "Rule 3 must not describe the worktree base as varying. It does not "
            "vary; describing it as variance is what left the remediation "
            "optional (#150)."
        )

    def test_worker_protocol_merges_batch_branch_after_isolation_check(self):
        body = self.s.body
        isolation = body.find('[ -f "$(git rev-parse --show-toplevel)/.git" ]')
        merge = body.find("git merge batch/<X>")
        implement = body.find("**Implement with TDD**")
        assert -1 not in (isolation, merge, implement), (
            "The worker protocol must carry all three of: the isolation "
            "pre-flight, a `git merge batch/<X>` step, and the TDD step. "
            f"Found offsets isolation={isolation} merge={merge} "
            f"implement={implement} (-1 means absent)."
        )
        # Order is the contract, not merely presence. The merge WRITES FILES,
        # so it must not run before isolation is proven — #150 proposed it as
        # step 1, ahead of the pre-flight, which would have a fallen-through
        # worker mutate the main checkout, the exact outcome the pre-flight's
        # abort clause exists to prevent.
        assert isolation < merge < implement, (
            "Worker protocol ordering must be: verify isolation → merge "
            "`batch/<X>` → implement. Merging before the isolation check would "
            "write files into the main checkout on a provisioning "
            "fall-through; merging after implementation is too late to fix the "
            "base the work was measured against."
        )

    def test_worker_step_cross_references_point_at_the_right_step(self):
        """Every "Worker step(s) N" citation must land on the step it means.

        Inserting #150's two new steps renumbered the protocol and silently
        invalidated two citations elsewhere in the file: the Q5 answer cited
        "Worker steps 5-7" for the run-tests/lint/self-review trio (now 7-9),
        and the adopted-improvements list cited "Worker step 3" for the
        issue-body rule (now 5). Both are prose an orchestrator follows
        literally.

        Checking that a cited number is merely IN RANGE does not catch this —
        3, 5 and 7 all still exist, they just mean other things now. So each
        citation is resolved against the cited step's TITLE.
        """
        body = self.s.body
        protocol = body[body.index("### Worker agents"):body.index("## Key Principles")]
        steps = {
            int(n): title
            for n, title in re.findall(r"(?m)^(\d+)\. \*\*(.+?)\*\*", protocol)
        }
        assert steps and set(steps) == set(range(1, len(steps) + 1)), (
            f"Worker protocol steps must be contiguous from 1; found {sorted(steps)}."
        )

        def step_titled(fragment: str) -> int:
            matches = [n for n, t in steps.items() if fragment.lower() in t.lower()]
            assert len(matches) == 1, (
                f"Expected exactly one worker step titled like {fragment!r}; "
                f"found {matches} in {steps}."
            )
            return matches[0]

        cited_body = re.search(r"Worker step (\d+) \"issue body is a proposal", body)
        assert cited_body, (
            "The adopted-improvements list must still cite the issue-body rule "
            'as `Worker step N "issue body is a proposal, not a specification"`.'
        )
        expected = step_titled("issue body as a proposal")
        assert int(cited_body.group(1)) == expected, (
            f"Adopted improvements cites 'Worker step {cited_body.group(1)}' for "
            f"the issue-body rule, which is now step {expected}."
        )

        cited_verify = re.search(
            r"Worker steps (\d+)[-–](\d+) run before the completion signal", body
        )
        assert cited_verify, (
            "The Q5 answer must still cite the pre-signal verification steps as "
            "`Worker steps N-M run before the completion signal`."
        )
        want = (step_titled("Run full test suite"), step_titled("Self-review diff"))
        assert tuple(int(g) for g in cited_verify.groups()) == want, (
            f"Q5 cites 'Worker steps {cited_verify.group(1)}-"
            f"{cited_verify.group(2)}' for the run-tests → self-review trio, "
            f"which is now steps {want[0]}-{want[1]}."
        )

    def test_worker_prompts_must_carry_a_falsifiable_baseline(self):
        body = self.s.body
        assert "expected test count on `batch/<X>`" in body, (
            "Every worker prompt must carry the expected test count on the "
            "batch branch with a stop-if-it-does-not-match instruction. That "
            "is the only detector that has actually caught a stale worktree "
            "base (#144 Batch A) — a merge step alone fails silently when the "
            "brief itself was written against the wrong tree."
        )

    # -- execution-phase addendum (#161) -------------------------------------
    #
    # Four promotions, and what unites the first two is that each defeats a
    # detector the skill already prescribes rather than merely evading it: a
    # vacuous assertion keeps the suite GREEN, and a corrupted `.git/config`
    # keeps Rule 6 answering "clean". A rule whose own check reports success
    # under the failure is worth pinning, because nothing else will notice it
    # going missing.

    def test_test_surface_grep_covers_vacuous_assertions(self):
        """Step 5's test-surface grep must hunt green failures, not only red.

        The existing bullet finds assertions a fix *invalidates* — they go red
        and the gate says so. An assertion the fix makes vacuous
        (`None == None`, after the state moved to another column) stays green
        while verifying nothing, and no keyword sweep reaches it: it names
        neither the literal the fix removes nor the one it adds.
        """
        body = self.s.body
        section = body[
            body.index("### Step 5–6: Conflict zone analysis"):
            body.index("### Step 7: Batch design")
        ]
        assert "vacuous" in section, (
            "Step 5's conflict-zone analysis must tell the orchestrator to grep "
            "for the assertions a change makes VACUOUS, not only the ones it "
            "breaks. The invalidated half is caught by the suite; the vacuous "
            "half is exactly what the suite cannot report."
        )

    def test_rule_6_reads_the_exit_code_not_only_stdout(self):
        """Rule 6's check must not be satisfiable by a failed `git status`.

        A linked worktree shares `.git/config` with the main checkout, so a
        worker's stray `git config` can set `core.bare = true` there. That makes
        `git status` FAIL with empty stdout — indistinguishable from "clean" to
        a caller reading output alone. The corruption disables the detector
        instead of tripping it (#189, twice in one four-agent batch).
        """
        body = self.s.body
        rule6 = body[
            body.index("### Rule 6 — Detect worktree fall-through at runtime"):
            body.index("## Recovery")
        ]
        assert "exit" in rule6, (
            "Rule 6 must instruct the orchestrator to read the exit code of "
            "`git status --porcelain`, not only its stdout — an empty stdout "
            "from a FAILED status reads as 'clean' (#189)."
        )
        assert "core.bare" in rule6, (
            "Rule 6 must name the corruption it now guards against "
            "(`core.bare = true` written through a linked worktree's shared "
            "`.git/config`), or the exit-code clause reads as pedantry and gets "
            "dropped by the next editor."
        )
        assert "--is-inside-work-tree" in rule6, (
            "Rule 6 must carry the positive canary as well as the exit-code "
            "check: `git rev-parse --is-inside-work-tree` on the main checkout "
            "catches the whole class rather than this one flag (#189)."
        )

    def test_orchestrator_reconciliation_covers_a_failed_signal(self):
        """`failed` and `completed` reach the same reconciliation.

        A subagent killed mid-run (weekly limit, timeout) signals `failed`, and
        the instinct is to relaunch from scratch — which discards a coherent,
        committed phase. From outside the worktree "died" and "fell through"
        are indistinguishable, so Rule 6 plus reconciliation is the correct
        first move for either signal.
        """
        body = self.s.body
        orchestrator = body[
            body.index("### Orchestrator agent"):body.index("### Worker agents")
        ]
        assert "failed" in orchestrator, (
            "Orchestrator step 5 must state that a `failed` worker signal takes "
            "the same reconcile-then-merge path as a `completed` one. Naming "
            "only 'completion signal' is what makes relaunching-from-scratch "
            "look correct."
        )

    def test_report_back_slot_requires_a_collected_count(self):
        """A verdict cannot be reconciled across workers; a count can.

        `2252 + 4 + 6 + 15 + 17 = 2294` is what let one batch gate confirm that
        four green claims were green on the same tree — and it is how three of
        four workers diagnosed a stale briefed baseline instead of silently
        reconciling to it (#182 Batch A, sourced from #156).
        """
        protocol = self.s.body[self.s.body.index("### Worker agents"):]
        assert "N passed, M skipped" in protocol, (
            "The worker protocol's required report-back slot must demand the "
            "suite's COLLECTED COUNT (`N passed, M skipped`), not a bare "
            "'green'. Verdicts from N workers cannot be reconciled against each "
            "other; counts can."
        )

    def test_red_phase_commit_advice_is_conditional_on_what_the_hook_runs(self):
        """The promoted candidate's own claim about pre-commit was wrong.

        #161's Candidate B asserted "the pre-commit hook runs ruff, not pytest,
        so a red commit lands cleanly" — true of the repository it was observed
        in, false of this one, whose single hook runs the whole structural
        suite and therefore REJECTS a red commit. The claim was copied into
        four worker briefs unchecked and caught independently by three agents.
        Promoting it unqualified would carry the error upstream into the skill,
        where every consumer inherits it.
        """
        body = self.s.body
        assert not re.search(r"hook runs ruff|runs ruff, not pytest", body), (
            "The skill must not assert that the pre-commit hook runs a linter "
            "rather than the test suite. That is true of the repo the finding "
            "was observed in and false of others — including this one (#161)."
        )
        assert "--no-verify" in body, (
            "The red-phase-commit rule must name `--no-verify`, since a hook "
            "that runs the suite rejects the red commit outright."
        )
        paragraph = next(
            p for p in body.split("\n") if "--no-verify" in p
        )
        assert re.search(r"\bonly where\b|\bcheck\b", paragraph), (
            "The red commit lands cleanly ONLY where the pre-commit hook does "
            "not run the suite, and checking which is the worker's job. State "
            "the condition in the same breath as the advice, or the reader "
            "inherits the wrong repo's fact:\n  " + paragraph
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
        # Click's ParamType has no `callback`: `convert()` is the only
        # conversion hook (verified against click 8.3.2 — #208). Naming
        # `ParamType.callback` at all, in any call or attribute form, is the
        # regression this pins, because the dimension told reviewers to prefer
        # it over `convert()` and so flagged conforming tests as wrong.
        assert "ParamType.callback" not in body, (
            "ParamType has no `callback` attribute — `convert()` is its only "
            "conversion hook; `callback` belongs to Parameter/Option and to "
            "Command"
        )
        assert "`convert()` is a ParamType's only conversion hook" in body, (
            "ParamType testability must name convert() as the sole conversion "
            "hook rather than steering reviewers away from it"
        )
        assert "command.callback(" in body, (
            "ParamType testability must keep the separate, real advice: a "
            "COMMAND's callback is what bypasses option parsing"
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


# ---------------------------------------------------------------------------
# Phase 1 doctor preflight (drift assertion)
# ---------------------------------------------------------------------------


# Each tuple is (skill-name, phase-1-script-name). Reviewing-* skills use
# gather-context.sh; shipping-* skills use pre-ship.sh.
SKILLS_REQUIRING_DOCTOR_PREFLIGHT = [
    ("reviewing-code", "gather-context.sh"),
    ("reviewing-code-php", "gather-context.sh"),
    ("reviewing-code-python-click", "gather-context.sh"),
    ("reviewing-code-python-fastapi", "gather-context.sh"),
    ("reviewing-architecture", "gather-context.sh"),
    ("shipping-work", "pre-ship.sh"),
    ("shipping-work-php", "pre-ship.sh"),
    ("shipping-work-python-click", "pre-ship.sh"),
    ("shipping-work-python-fastapi", "pre-ship.sh"),
]


class TestPhase1DoctorPreflight:
    """Every reviewing-*/shipping-* SKILL.md must invoke `.skills/doctor.sh`
    as a guarded preflight before the gather/pre-ship script, chained with
    `&&` so the original "No such file or directory" noise from a dangling
    vendor symlink chain doesn't drown out the doctor's actionable error.
    The chain is followed by a paragraph explaining the semantics so a
    future reader doesn't have to reverse-engineer the dense one-liner.

    A future SKILL.md refactor could drop the chain or the paragraph from
    one variant and the inconsistency would only surface in a broken-symlink
    scenario (fresh `git worktree add`, shallow CI clone). These tests pin
    both so the inconsistency surfaces during review instead.
    """

    @pytest.fixture(
        params=SKILLS_REQUIRING_DOCTOR_PREFLIGHT,
        ids=lambda p: p[0],
    )
    def skill_and_script(self, request):
        skill_name, script_name = request.param
        return skill(skill_name).body, skill_name, script_name

    def test_doctor_preflight_chain_present(self, skill_and_script):
        body, skill_name, script_name = skill_and_script
        # Doctor-specific property: the preflight sits between the header and
        # the resolution loop. Ordering is the load-bearing part — the loop
        # must come *after* the doctor so a freshly healed symlink chain is
        # visible to the probe (issue #63).
        #
        # The shape of the loop itself belongs to TestScriptResolutionBlock,
        # which covers all 11 skills rather than only the 9 with a doctor.
        # The overlap here is deliberate: this pins ordering, that pins form.
        expected = (
            f"N={skill_name} S={script_name} SD=\n"
            "{ [ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh; } || exit 1\n"
            'for d in scripts ".claude/skills/$N/scripts" '
            '"$HOME/.claude/skills/$N/scripts"; do\n'
        )
        assert expected in body, (
            f"SKILL.md Phase 1 must open with:\n  {expected}\n"
            "See skills/managing-skills/scripts/doctor.sh, "
            "https://github.com/gregoryfoster/skills/issues/46 and "
            "https://github.com/gregoryfoster/skills/issues/63."
        )

    def test_doctor_preflight_invokes_script(self, skill_and_script):
        body, _skill_name, _script_name = skill_and_script
        # The head assertion above stops at `done`, so on its own it would
        # still pass if the line that actually RUNS the script were deleted —
        # leaving the Iron Law gating on a script that never executes, which
        # is the #63 failure class. Pin the invocation separately.
        #
        # One canonical shape across both families. shipping-* additionally
        # publish SKILL_SCRIPTS beforehand (so later steps can substitute it),
        # but the invocation itself guards at the call site rather than
        # relying on that earlier line having aborted first — so an `any()`
        # over per-family variants is no longer needed here.
        invocation = (
            'bash "${SD:?not found in scripts/, .claude/skills/$N/scripts/, '
            'or ~/.claude/skills/$N/scripts/}/$S"'
        )
        assert invocation in body, (
            "SKILL.md Phase 1 resolves the script but never invokes it "
            f"(or invokes it unguarded). Expected:\n  {invocation}"
        )

    def test_doctor_preflight_guards_unresolved_path(self, skill_and_script):
        body, _skill_name, _script_name = skill_and_script
        # `${SD:?…}` is what turns "resolved nothing" into a loud failure
        # naming the searched paths, rather than a silent no-op loop.
        guard = (
            "${SD:?not found in scripts/, .claude/skills/$N/scripts/, "
            "or ~/.claude/skills/$N/scripts/}"
        )
        assert guard in body, (
            "SKILL.md Phase 1 must fail loudly when no candidate resolves. "
            f"Expected the guard:\n  {guard}"
        )

    def test_doctor_preflight_paragraph_present(self, skill_and_script):
        body, _skill_name, script_name = skill_and_script
        # Pin the explanatory paragraph that follows the block — same wording
        # across the family with only the phase-1 script name varying.
        expected = (
            "The first line is a preflight: when `.skills/doctor.sh` is present, "
            "it heals any dangling vendor symlinks (or reports an actionable "
            "error); when absent, the group is a no-op. `|| exit 1` skips "
            f"`{script_name}` if the doctor reports unrecoverable state so the "
            'original "No such file or directory" noise doesn\'t drown out the '
            "doctor's message. The loop then resolves the script against the "
            "skill directory rather than the cwd"
        )
        assert expected in body, (
            "SKILL.md Phase 1 must include the explanatory paragraph below "
            "the doctor preflight block so future readers don't have to "
            "reverse-engineer the dense snippet. Expected to start with:\n\n  "
            + expected
        )


# ---------------------------------------------------------------------------
# Skill-relative script paths (regression guard)
# ---------------------------------------------------------------------------


class TestNoBareScriptPaths:
    """No SKILL.md may invoke a helper via a bare `bash scripts/X.sh`.

    Scripts ship inside the skill directory, but a bare `scripts/` path
    resolves relative to the agent's cwd — the *project* root — where the
    script does not exist. Every invocation therefore failed with
    "No such file or directory" unless the consuming project happened to
    have its own scripts/ copy (issue #63).

    The replacement is the `<SKILL_SCRIPTS>` placeholder: a resolution block
    prints the resolved directory once, and later steps substitute the
    literal path. This test pins the absence of the old form so a future
    edit can't quietly reintroduce it — the failure mode is invisible in
    any project that does have a root scripts/ directory.

    references/ files are scanned alongside SKILL.md: they are loaded into
    context and can carry invocations just as SKILL.md does. Recursively, since
    #152: a reference in `references/<subdir>/` is loaded exactly as one at the
    top level is, and a non-recursive glob would have let the whole
    `process-log/` journal out of this check without failing anything.
    """

    @pytest.fixture(
        params=sorted(
            list(SKILLS_DIR.glob("*/SKILL.md"))
            + list(SKILLS_DIR.glob("*/references/**/*.md"))
        ),
        ids=lambda p: str(p.relative_to(SKILLS_DIR)),
    )
    def skill_md(self, request):
        return request.param

    def test_no_bare_scripts_path(self, skill_md):
        offenders = [
            line.strip()
            for line in skill_md.read_text().splitlines()
            if re.search(r"bash\s+scripts/\S+\.sh", line)
        ]
        assert not offenders, (
            f"{skill_md.relative_to(SKILLS_DIR)} invokes a script via a bare "
            "cwd-relative path:\n  "
            + "\n  ".join(offenders)
            + '\n\nUse the resolved placeholder form instead: bash "<SKILL_SCRIPTS>/X.sh"'
            "\nSee https://github.com/gregoryfoster/skills/issues/63."
        )


# ---------------------------------------------------------------------------
# Script resolution block (all skills that carry one)
# ---------------------------------------------------------------------------


RESOLUTION_LOOP = (
    'for d in scripts ".claude/skills/$N/scripts" '
    '"$HOME/.claude/skills/$N/scripts"; do'
)

RESOLUTION_GUARD = (
    "${SD:?not found in scripts/, .claude/skills/$N/scripts/, "
    "or ~/.claude/skills/$N/scripts/}"
)


def _skills_with_resolution_block():
    return sorted(
        p for p in SKILLS_DIR.glob("*/SKILL.md") if RESOLUTION_LOOP in p.read_text()
    )


# Skills that ship a scripts/ directory but deliberately carry no resolution
# block. Each resolves script paths another way, so the cwd-relative bug #63
# fixed does not apply:
#   - init-*: Phase 0 clones the skill repo and captures <SKILL_DIR>, so paths
#     are absolute from the start (see init-project-fastapi / init-socraticode).
#   - managing-skills: runs during bootstrap, before the .claude/skills symlinks
#     it installs exist, so it uses full vendor paths.
# test_resolution_block_roster pins this set so a NEW skill that ships scripts/
# and forgets a block fails loudly instead of silently escaping coverage.
SKILLS_EXEMPT_FROM_RESOLUTION_BLOCK = {
    "init-project-fastapi",
    "init-socraticode",
    "managing-skills",
}


def test_resolution_block_roster():
    """Every skill that ships scripts/ either carries a resolution block or is
    a documented exemption — nothing escapes coverage silently.

    TestScriptResolutionBlock discovers its subjects by matching the loop
    line, so a corrupted loop line (or a new skill missing a block entirely)
    would drop out of the parameter list with no visible failure. This roster
    check is the backstop: it keys on the scripts/ directory, not on the block
    text the other class asserts.
    """
    ships_scripts = {
        p.parent.name
        for p in SKILLS_DIR.glob("*/SKILL.md")
        if (p.parent / "scripts").is_dir()
    }
    has_block = {p.parent.name for p in _skills_with_resolution_block()}
    missing = ships_scripts - has_block - SKILLS_EXEMPT_FROM_RESOLUTION_BLOCK
    assert not missing, (
        "These skills ship a scripts/ directory but carry neither a resolution "
        f"block nor an entry in SKILLS_EXEMPT_FROM_RESOLUTION_BLOCK: {sorted(missing)}.\n"
        "Add the block (see AGENTS.md 'Invoking a skill's own scripts'), or — if "
        "the skill resolves paths another way — document why in the exemption set."
    )
    # Keep the exemption set honest: a skill that gained a block, or dropped
    # its scripts/ dir, should be removed rather than lingering as dead config.
    stale = {
        name
        for name in SKILLS_EXEMPT_FROM_RESOLUTION_BLOCK
        if name in has_block or name not in ships_scripts
    }
    assert not stale, (
        "SKILLS_EXEMPT_FROM_RESOLUTION_BLOCK lists skills that no longer need an "
        f"exemption (they gained a block or dropped scripts/): {sorted(stale)}."
    )


class TestScriptResolutionBlock:
    """Every skill that resolves its own scripts/ must do so identically.

    TestPhase1DoctorPreflight covers only the 9 skills with a doctor
    preflight, which left using-git-worktrees and writing-plans — 9 of the 30
    <SKILL_SCRIPTS> substitution sites — with no coverage of their block at
    all. They also hold the only copies of the sentinel-probe correction
    (`[ -f "$d/$S" ]` rather than `[ -d "$d" ]`), making the least-tested
    files the most-recently-changed ones.

    Each assertion below pins a line whose deletion fails as #63's symptom —
    "No such file or directory" — rather than as anything self-explanatory.
    """

    @pytest.fixture(
        params=_skills_with_resolution_block(), ids=lambda p: p.parent.name
    )
    def skill_md(self, request):
        return request.param

    def test_header_clears_sd(self, skill_md):
        # Without `SD=`, a value inherited from the environment or left by an
        # earlier block in the same shell survives the loop and defeats the
        # guard, silently building a path from the stale value.
        name = skill_md.parent.name
        pattern = rf"^N={re.escape(name)} S=\S+\.sh SD=$"
        assert re.search(pattern, skill_md.read_text(), re.M), (
            f"{name}/SKILL.md resolution block must open with "
            f"`N={name} S=<sentinel>.sh SD=` — the trailing `SD=` is what "
            "makes the ${SD:?…} guard reachable."
        )

    def test_probes_sentinel_file_not_directory(self, skill_md):
        # `[ -d "$d" ]` would falsely match any project with an unrelated
        # root scripts/ directory — this repo has one.
        expected = '  [ -f "$d/$S" ] && { SD="$d"; break; }\ndone\n'
        assert expected in skill_md.read_text(), (
            f"{skill_md.parent.name}/SKILL.md must probe for the sentinel "
            f"script file, not the directory:\n  {expected}"
        )

    def test_guard_present(self, skill_md):
        assert RESOLUTION_GUARD in skill_md.read_text(), (
            f"{skill_md.parent.name}/SKILL.md must fail loudly when no "
            f"candidate resolves. Expected the guard:\n  {RESOLUTION_GUARD}"
        )

    def test_placeholder_uses_have_a_publisher(self, skill_md):
        # Every `bash "<SKILL_SCRIPTS>/X.sh"` is meaningless unless some
        # earlier step printed the path the reader substitutes. Six skills
        # carry 30 such sites between them; deleting the single publishing
        # line would strand all of them.
        #
        # references/**/*.md is scanned alongside SKILL.md (matching the surface
        # TestNoBareScriptPaths already covers): a reference file may carry a
        # substitution site, but only SKILL.md's block publishes the path.
        skill_dir = skill_md.parent
        docs = [skill_md, *sorted(skill_dir.glob("references/**/*.md"))]
        uses = sum(p.read_text().count('bash "<SKILL_SCRIPTS>/') for p in docs)
        if not uses:
            pytest.skip("skill has no <SKILL_SCRIPTS> substitution sites")
        assert 'echo "SKILL_SCRIPTS=' in skill_md.read_text(), (
            f"{skill_dir.name} has {uses} `bash \"<SKILL_SCRIPTS>/…\"` site(s) "
            "(SKILL.md + references/) but SKILL.md never prints the path to "
            'substitute. The resolution block must publish it:\n  echo '
            f'"SKILL_SCRIPTS={RESOLUTION_GUARD}"'
        )
