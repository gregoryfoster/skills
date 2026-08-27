"""`measure-context.sh --gate` turns the budget from a reading into a contract (#88).

`test_policy_surface_budget.py` already holds THIS repo's `AGENTS.md` to its
budget through pytest — but that gate is this repo's, not the cohort's. Eleven
cohort members vendor `curating-context` and have no structural suite to bolt a
budget test onto; what they have is a check surface (pre-commit, composer
scripts, a CI job). `--gate` is the piece enforcing-architecture can wire into
any of those: the same measurement, the same budget-resolution chain
(flag → `CONTEXT_BUDGET` → `.skills/context-budget` → 6,000), and a non-zero
exit when `policy.over_budget` is true.

Contract pinned here:

1. `--gate` exits 4 — its own code, distinct from 1 (usage), 2 (infrastructure)
   and 3 (`--check-credential`) — when the policy file is over budget, and
   names the overage on stderr. The JSON still prints: a failing gate that
   discards the measurement leaves the committer diagnosing blind.
2. `--gate` exits 0 when the file is under budget.
3. WITHOUT `--gate`, an over-budget file still exits 0. The default is a
   measurement, not a gate — record-telemetry.sh and the cadence workflow pipe
   from it and must never mistake a budget verdict for a broken run.
4. The gate resolves its budget through `.skills/context-budget`, the knob
   `install-guard.sh --budget` writes — a gate that ignored the knob would
   enforce 6,000 in repos configured otherwise, which is #126's bug reborn as
   a red check.
5. It works OFFLINE (the calibrated estimate). A pre-commit hook has no API
   key, so a gate that needed one would silently never fire.
6. This repo wires it into its own detected check surface: pre-commit — the
   only surface here that runs on commit/merge (both workflows are
   schedule + workflow_dispatch), per enforcing-architecture's detection rule.

No API calls: every run scrubs ANTHROPIC_API_KEY so the offline path is the
one under test.
"""

import json
import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MEASURE = (
    REPO_ROOT / "skills" / "curating-context" / "scripts" / "measure-context.sh"
)
PLAYBOOK = (
    REPO_ROOT / "skills" / "enforcing-architecture" / "references"
    / "fitness-functions.md"
)
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"

GATE_EXIT = 4


def _env() -> dict:
    """What a pre-commit hook sees: no GIT_* leakage, no credential, no knobs.

    GIT_* is scrubbed because pre-commit exports GIT_DIR/GIT_INDEX_FILE to the
    hook process and they outrank cwd (docs/STYLE.md). The credential is
    dropped so the offline path is the one exercised; the budget knobs so an
    operator's environment cannot move the ceiling under test.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("ANTHROPIC_API_KEY", "CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET",
              "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    return env


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(MEASURE), "--no-write", *args],
        capture_output=True, text=True, cwd=str(cwd), env=_env(), timeout=120,
    )


def _over_budget_tree(tmp_path: Path) -> Path:
    """A policy file comfortably over the 6,000 default, in a throwaway tree.

    Same construction as test_policy_surface_budget.py's failure proof —
    never by mutating the real AGENTS.md.
    """
    (tmp_path / "AGENTS.md").write_text(
        "# Policy\n\n" + ("filler " * 20_000) + "\n"
    )
    (tmp_path / "docs").mkdir()
    return tmp_path


class TestTheGateFlagFailsAnOverBudgetPolicyFile:
    def test_gate_exits_4_on_an_over_budget_file(self, tmp_path: Path):
        result = _run(_over_budget_tree(tmp_path), "--gate")
        assert result.returncode == GATE_EXIT, (
            f"--gate should exit {GATE_EXIT} on an over-budget policy file; "
            f"got {result.returncode}.\nstderr:\n{result.stderr}"
        )

    def test_gate_still_emits_the_measurement(self, tmp_path: Path):
        """A red gate must hand the committer the numbers, not just a verdict."""
        result = _run(_over_budget_tree(tmp_path), "--gate")
        policy = json.loads(result.stdout)["policy"]
        assert policy["over_budget"] is True, policy

    def test_gate_names_the_overage_on_stderr(self, tmp_path: Path):
        result = _run(_over_budget_tree(tmp_path), "--gate")
        assert "over budget" in result.stderr, (
            "the gate's stderr should say WHAT failed — pre-commit shows "
            f"stderr, and stdout is a JSON blob. Got:\n{result.stderr}"
        )
        assert "6000" in result.stderr.replace(",", ""), (
            "the stderr verdict should name the budget it enforced:\n"
            + result.stderr
        )

    def test_gate_exits_0_under_budget(self, tmp_path: Path):
        (tmp_path / "AGENTS.md").write_text("# Policy\n\nShort and under.\n")
        (tmp_path / "docs").mkdir()
        result = _run(tmp_path, "--gate")
        assert result.returncode == 0, result.stderr


class TestTheDefaultStaysAMeasurement:
    def test_without_gate_an_over_budget_file_still_exits_0(
        self, tmp_path: Path
    ):
        """The contract every existing consumer was built on (issue #88: 'exits
        0 even when over budget (by design — it is a measurement, not a
        gate)')."""
        result = _run(_over_budget_tree(tmp_path))
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["policy"]["over_budget"] is True


class TestTheGateHonoursTheBudgetChain:
    def test_gate_reads_the_knob_file(self, tmp_path: Path):
        """#126's fix, load-bearing for the gate: `.skills/context-budget` is
        what `install-guard.sh --budget` writes, so a gate that ignored it
        would enforce 6,000 regardless of what the repo configured."""
        (tmp_path / "AGENTS.md").write_text(
            "# Policy\n\n" + ("filler " * 300) + "\n"
        )
        (tmp_path / "docs").mkdir()
        (tmp_path / ".skills").mkdir()
        (tmp_path / ".skills" / "context-budget").write_text("100\n")
        result = _run(tmp_path, "--gate")
        assert result.returncode == GATE_EXIT, (
            "a ~300-token file against the knob file's budget of 100 should "
            f"fail the gate; got exit {result.returncode}:\n{result.stderr}"
        )
        assert json.loads(result.stdout)["policy"]["budget"] == 100

    def test_gate_flag_override_wins(self, tmp_path: Path):
        (tmp_path / "AGENTS.md").write_text(
            "# Policy\n\n" + ("filler " * 300) + "\n"
        )
        (tmp_path / "docs").mkdir()
        result = _run(tmp_path, "--gate", "--budget", "50")
        assert result.returncode == GATE_EXIT, result.stderr


class TestTheGateIsWiredIntoThisReposCheckSurface:
    """Enforcing-architecture's rule: wire into every surface the project
    already runs on merge/commit. Here that is pre-commit alone — both
    workflows under .github/workflows/ are schedule + workflow_dispatch."""

    def test_pre_commit_runs_the_gate(self):
        config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text())
        hooks = [h for r in config["repos"] for h in r.get("hooks", [])]
        gates = [
            h for h in hooks
            if "measure-context.sh" in h.get("entry", "")
            and "--gate" in h.get("entry", "")
        ]
        assert gates, (
            "no pre-commit hook runs `measure-context.sh --gate`; the context "
            "budget is back to being a convention on this surface (#88)"
        )

    def test_the_playbook_documents_the_gate(self):
        """The fitness-function row enforcing-architecture fills in for a
        cohort repo — without it the skill improvises the wiring from memory,
        which its own Iron Law forbids."""
        text = PLAYBOOK.read_text()
        assert "--gate" in text and "measure-context.sh" in text, (
            f"{PLAYBOOK} has no context-budget row (#88)"
        )
