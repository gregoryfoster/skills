"""The attestation's documents say what the step does, and the CI snippet
keeps its rules (#688).

`gate/local` is a contract: a workflow in another repository keys on the
name, and it is copied from `shipping-work`'s reference, not from the script.
So the name in the script, the name in the snippet and the name in the knob
inventory are held to one spelling here.

The snippet is what an adopter pastes, and each of its rules is one a wrong
copy gets silently wrong:

- the **combined** status (`commits/{sha}/status`), never `/statuses`, which
  lists every status ever posted, so a later failure would still count;
- a **whole page**, since the combined status is paged at 30 contexts;
- **`pull_request.head.sha`**, since `github.sha` is the merge commit there;
- **never for a bot's PR or a fork's**, tested only on `pull_request` events:
  on a push the PR fields are empty, and an unguarded fork test would be true
  for every push, so nothing would ever be skipped;
- **`statuses: read`**, since a workflow that sets any permission gets `none`
  for each one it leaves out.

No API calls. Text analysis, and a YAML parse of the snippet.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

from tests.utils.skill_loader import SKILLS_DIR

REPO = SKILLS_DIR.parent
SKILL = SKILLS_DIR / "shipping-work"
REFERENCE = SKILL / "references" / "attestation.md"
LIB = SKILL / "scripts" / "_attest-gate.sh"
PUSH = SKILL / "scripts" / "push.sh"
NON_LEVERS = SKILLS_DIR / "auditing-ci-cost" / "references" / "non-levers.md"
KNOBS = REPO / "docs" / "KNOBS.md"
KNOB = ".skills/attest-local-gate"


def _flat(path: Path) -> str:
    return " ".join(path.read_text().split())


def _context() -> str:
    (name,) = re.findall(r"^ATTEST_CONTEXT=(\S+)$", LIB.read_text(), re.M)
    return name


def _snippet() -> dict:
    (block,) = re.findall(r"```yaml\n(.*?)```", REFERENCE.read_text(), re.S)
    return yaml.safe_load(block)


def _steps() -> list[dict]:
    (job,) = _snippet()["jobs"].values()
    return job["steps"]


class TestOneNameForTheContext:
    def test_the_script_names_it_once(self):
        assert _context() == "gate/local"

    def test_the_snippet_keys_on_the_scripts_name(self):
        (attest,) = [s for s in _steps() if s.get("id") == "attest"]
        assert f'.context == "{_context()}"' in attest["run"]
        assert '.state == "success"' in attest["run"]

    def test_every_document_spells_it_the_same(self):
        for doc in (REFERENCE, NON_LEVERS, KNOBS):
            assert f"`{_context()}`" in doc.read_text(), doc


class TestTheSnippetKeepsItsRules:
    def test_it_reads_the_combined_status_a_whole_page_never_the_list(self):
        (attest,) = [s for s in _steps() if s.get("id") == "attest"]
        assert "/commits/$HEAD/status?per_page=100" in attest["run"]
        assert not re.search(r"/statuses\b[^:]", attest["run"].split("#")[0])

    def test_it_reads_the_prs_head_and_falls_to_the_pushed_commit(self):
        (attest,) = [s for s in _steps() if s.get("id") == "attest"]
        head = attest["env"]["HEAD"]
        assert head.index("github.event.pull_request.head.sha") < head.index(
            "github.sha"
        )
        assert "||" in head

    def test_a_bots_pr_and_a_forks_always_run_the_heavy_tier(self):
        (heavy,) = [s for s in _steps() if "if" in s]
        cond = " ".join(heavy["if"].split())
        assert "steps.attest.outputs.attested != 'yes'" in cond
        assert "github.event.pull_request.user.type == 'Bot'" in cond
        assert (
            "github.event.pull_request.head.repo.full_name != github.repository" in cond
        )

    def test_the_pr_tests_apply_to_pull_requests_only(self):
        """On a push both PR fields are empty, so the fork test alone would
        be true and a direct ship would never skip anything."""
        (heavy,) = [s for s in _steps() if "if" in s]
        cond = " ".join(heavy["if"].split())
        guarded = re.search(
            r"\(github\.event_name == 'pull_request' && \((.*)\)\)", cond
        )
        assert guarded, cond
        assert "'Bot'" in guarded.group(1) and "full_name" in guarded.group(1)

    def test_only_a_push_or_a_pull_request_may_skip(self):
        """CR 2665: a schedule, a manual run and pull_request_target read
        github.sha too. Skipping there would leave a directly shipped commit
        with no clean-runner run at all, and pull_request_target would trust
        a status on a bot's or a fork's branch."""
        (heavy,) = [s for s in _steps() if "if" in s]
        cond = " ".join(heavy["if"].split())
        assert (
            "|| (github.event_name != 'push' && github.event_name != 'pull_request')"
            in cond
        )
        assert "pull_request_target" not in cond
        assert "Keep a scheduled run" in _flat(REFERENCE)

    def test_the_job_may_read_statuses(self):
        assert _snippet()["permissions"] == {"contents": "read", "statuses": "read"}


class TestTheReferenceSaysWhatTheStepIs:
    def test_the_knob_its_grammar_and_where_it_is_read(self):
        text = _flat(REFERENCE)
        assert f"`{KNOB}`" in text
        assert "`on` or `off`" in text
        assert "the commit being shipped" in text
        assert "exit 2 before the push" in text

    def test_it_is_trust_not_proof_and_never_required_alone(self):
        text = _flat(REFERENCE)
        assert "Trust, not proof" in text
        assert "Never make it a required status by itself" in text

    def test_the_decisions_carry_their_reasons(self):
        text = _flat(REFERENCE)
        for claim in (
            "A reused pass attests",
            "A refused write doesn't fail the ship",
            "`gate/local` is fixed",
            "whose own `scripts/pre-ship.sh` is the gate",
            "Never post the status by hand",
        ):
            assert claim in text, claim

    def test_the_token_is_the_operators_not_a_workflows(self):
        text = _flat(REFERENCE)
        assert "Commit statuses: Read and write" in text
        assert "`repo` scope" in text

    def test_every_exit_code_push_help_names_is_in_the_table(self):
        """CR 2666, CR 2671: read from --help itself. Each code it lists has
        a row, and the rows that end before the push say how to tell them
        from git's own failure after it."""
        out = subprocess.run(
            ["bash", str(PUSH), "--help"], capture_output=True, text=True, timeout=30
        ).stdout
        codes = re.findall(r"^  (\d|\*)  ", out[out.index("Exit codes:") :], re.M)
        assert codes == ["0", "1", "2", "*"], out
        rows = [
            line.split("|")[1].strip()
            for line in REFERENCE.read_text().splitlines()
            if line.startswith("| ") and not line.startswith("| Exit")
        ]
        firsts = [row.split(",")[0] for row in rows]
        assert firsts == ["0", "0", "1", "2", "any other"], rows
        for row in rows[2:4]:
            assert "`Nothing was pushed`" in row, row
        assert "after `Pushing <branch> to origin...`" in rows[4]
        assert "ATTESTATION NOT POSTED" in rows[1]
        for text in (out, LIB.read_text()):
            assert "ATTESTATION NOT POSTED" in text

    def test_skill_md_points_at_it_from_the_push_step(self):
        skill = (SKILL / "SKILL.md").read_text()
        step = skill[skill.index("### Step 4") : skill.index("### Step 5")]
        assert f"`{KNOB}`" in step
        assert "references/attestation.md" in step
        assert "`Attestation:`" in step, "the line the agent reports in Step 7"


class TestAuditingCiCostPointsAtWhatShipped:
    def test_the_sketch_is_gone_and_the_step_is_linked(self):
        text = _flat(NON_LEVERS)
        assert "A sketch, not shipped" not in text
        assert "SKETCH" not in text
        assert "../../shipping-work/references/attestation.md" in text
        assert f"`{KNOB}`" in text

    def test_it_still_names_the_three_rules(self):
        text = _flat(NON_LEVERS)
        assert "the combined status, never `/statuses`" in text
        assert "`pull_request.head.sha`, never `github.sha`" in text
        assert "never trust the status for a bot's PR or a fork's" in text


class TestThisRepoDoesNotOptIn:
    def test_no_knob_is_committed_here(self):
        """Public, and no workflow runs on a push or a pull request, so
        nothing would read the status. The step is for consuming repos."""
        assert not (REPO / KNOB).exists()
        for workflow in (REPO / ".github" / "workflows").glob("*.y*ml"):
            triggers = yaml.safe_load(workflow.read_text()).get(True, {})
            assert not {"push", "pull_request"} & set(triggers), workflow.name
