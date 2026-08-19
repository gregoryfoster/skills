"""This repo's own `AGENTS.md` and `docs/` are held to the budgets it enforces.

`curating-context` refuses to let a cohort repo's policy file exceed 6,000
tokens and its reference docs 10,000, and `test_skill_self_budget.py` holds
every `skills/*/SKILL.md` to a ratchet. Between them the *policy file of this
repo* — the file the whole skill is about — was gated by nothing.

That is not a theoretical gap. It was measured in the batch/c review (#199): a
copy of `AGENTS.md` with ~12,000 tokens appended to it passed
`test_skill_self_budget.py` at `81 passed, 85 skipped`, because `_measure()`
passes `--file skills/{skill}/SKILL.md` and the policy file is never the
measured file. `docs/*.md` was unreachable for the same reason — the per-doc
budget is applied to `--docs-dir skills/{skill}/references`, so the tree under
`docs/` that `AGENTS.md`'s own "Detail Docs" section points at was never priced.

Three surfaces had to fail before anyone noticed:

  1. The write guard is a `PostToolUse` hook — advisory, and it never fires for
     a change that arrives by `git merge`.
  2. `context-delta.sh` defaulted to `--base HEAD`, so a committed branch
     diffed empty and the review-time block printed nothing (fixed alongside
     this file).
  3. Neither structural gate looked at the file.

So this is the always-on one. Offline by default, exact under
`SKILL_BUDGET_EXACT=1`, mirroring `test_skill_self_budget.py` so a reading can
never be loosened by choosing a measurement.

No API calls unless the exact pass is asked for.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MEASURE = (
    REPO_ROOT / "skills" / "curating-context" / "scripts" / "measure-context.sh"
)

# The two numbers this repo enforces on the cohort, applied to itself. They are
# the skill's own defaults, restated rather than imported because a change to
# the default should have to be made deliberately here too.
POLICY_BUDGET = 6_000
DOC_BUDGET = 10_000

EXACT_ENV = "SKILL_BUDGET_EXACT"


def _exact_requested() -> bool:
    return os.environ.get(EXACT_ENV, "") not in ("", "0")


def _env(*, exact: bool) -> dict:
    """What pre-commit sees, plus a credential only when asked.

    `GIT_*` is scrubbed for the reason docs/STYLE.md gives — git exports
    `GIT_DIR` to every hook process, and it outranks both `-C` and cwd. The
    budget knobs are dropped so an operator's environment cannot quietly move
    the ceiling this file exists to pin.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    if not exact:
        env.pop("ANTHROPIC_API_KEY", None)
    return env


def _measure(*, exact: bool) -> dict:
    """This repo's own surface: AGENTS.md plus the docs/ tree it indexes.

    `--no-write` is not optional. Without it an `--exact` run rewrites
    `.skills/context-token-ratio`, recalibrating every offline estimate in the
    library — which during batch/c pushed an untouched skill 31 tokens over its
    ratchet from a verification run that was supposed to be read-only.
    """
    cmd = [
        "bash", str(MEASURE),
        "--no-write",
        "--budget", str(POLICY_BUDGET),
        "--doc-budget", str(DOC_BUDGET),
    ]
    if exact:
        cmd.insert(3, "--exact")
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(REPO_ROOT),
        env=_env(exact=exact), timeout=300,
    )
    assert result.returncode == 0, (
        f"measure-context.sh failed on this repo's own surface:\n{result.stderr}"
    )
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def surface() -> dict:
    return _measure(exact=False)


@pytest.fixture(scope="module")
def exact_surface() -> dict:
    if not _exact_requested():
        pytest.skip(
            f"exact verification is opt-in: set {EXACT_ENV}=1 to run it. The "
            "offline gate ran and is the always-on contract."
        )
    measured = _measure(exact=True)
    # `policy.tokens_exact`, which is what test_skill_self_budget.py's own
    # fixture reads. There is no top-level `method` key — the first draft of
    # this file checked for one, so the exact pass skipped on every run while
    # reporting green, which is the "verified nothing" failure this file's
    # sibling gate was caught doing in the same review. Asserted below rather
    # than only skipped, so a *docs* row degrading to an estimate cannot pass
    # as an exact verdict either.
    if not measured["policy"]["tokens_exact"]:
        pytest.skip(
            f"{EXACT_ENV} was set but count_tokens was unreachable, so the "
            "exact contract WAS NOT VERIFIED — only the offline estimate ran. "
            "A green run here is not evidence; check the skip count. Verify "
            "the credential with `measure-context.sh --check-credential`."
        )
    stale = [d["path"] for d in measured["docs"] if not d["tokens_exact"]]
    assert not stale, (
        "these docs fell back to the offline estimate while the policy file "
        "was counted exactly, so a mixed reading would be reported as an "
        f"exact verdict: {', '.join(stale)}"
    )
    return measured


def _overage(policy: dict) -> str:
    return (
        f"{policy['tokens']:,} tokens against a {policy['budget']:,} budget "
        f"— {policy['tokens'] - policy['budget']:,} over.\n\n"
        "The fix is a DEMOTION, not a rewrite: move the section into a "
        "docs/ reference doc and leave one pointer behind, per "
        "curating-context Phase 3 class B. Shortening prose to fit is how a "
        "policy file loses the reasons behind its rules."
    )


class TestThePolicyFileIsWithinItsOwnBudget:
    """The gap measured in #199's batch/c review, closed."""

    def test_offline(self, surface: dict):
        policy = surface["policy"]
        assert policy["budget"] == POLICY_BUDGET, policy
        assert not policy["over_budget"], _overage(policy)

    def test_exact(self, exact_surface: dict):
        """Both readings, so no choice of measurement loosens the ceiling.

        The offline estimate has run below the exact count on this file, so a
        green offline pass is not sufficient evidence on its own.
        """
        policy = exact_surface["policy"]
        assert not policy["over_budget"], _overage(policy)


class TestEveryLiveDocIsWithinThePerDocBudget:
    """`AGENTS.md`'s Detail Docs section is a promise that each of these is
    worth loading. A doc over budget is one an agent pays for and should not
    have been sent to."""

    def test_offline(self, surface: dict):
        over = [
            f"  {d['path']}: {d['tokens']:,} / {d['budget']:,}"
            for d in surface["docs"] if d["over_budget"]
        ]
        assert not over, (
            "reference doc(s) over the per-doc budget:\n" + "\n".join(over)
            + "\n\nSplit the doc, or demote the part that is not pulling its "
              "weight. Phase 5's rule applies: split BEFORE anything points "
              "into what moves."
        )

    def test_exact(self, exact_surface: dict):
        over = [
            f"  {d['path']}: {d['tokens']:,} / {d['budget']:,}"
            for d in exact_surface["docs"] if d["over_budget"]
        ]
        assert not over, (
            "reference doc(s) over the per-doc budget when counted exactly:\n"
            + "\n".join(over)
        )


class TestTheGateCanActuallyFail:
    """A gate that cannot fail is not a gate — and this one could not, silently,
    for as long as the repo has had a budget. Pinned against the real files, so
    the proof does not drift from what ships."""

    def test_an_oversized_policy_file_is_reported_over(self, tmp_path: Path):
        """The exact probe from the batch/c review, as a test.

        Built in a throwaway tree rather than by mutating the real AGENTS.md:
        the review's first attempt did mutate it, and a timeout killed the
        restore, leaving the repo's policy file 12,000 tokens heavy until it
        was recovered from git.
        """
        (tmp_path / "AGENTS.md").write_text(
            "# Policy\n\n" + ("filler " * 20_000) + "\n"
        )
        (tmp_path / "docs").mkdir()
        result = subprocess.run(
            ["bash", str(MEASURE), "--no-write",
             "--budget", str(POLICY_BUDGET), "--doc-budget", str(DOC_BUDGET)],
            capture_output=True, text=True, cwd=str(tmp_path),
            env=_env(exact=False), timeout=120,
        )
        assert result.returncode == 0, result.stderr
        policy = json.loads(result.stdout)["policy"]
        assert policy["over_budget"] is True, policy
        assert policy["tokens"] > POLICY_BUDGET, policy

    def test_an_oversized_reference_doc_is_reported_over(self, tmp_path: Path):
        (tmp_path / "AGENTS.md").write_text(
            "# Policy\n\n## Detail Docs\n\n- [docs/BIG.md](docs/BIG.md) — big\n"
        )
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "BIG.md").write_text(
            "# Big\n\n" + ("filler " * 30_000) + "\n"
        )
        result = subprocess.run(
            ["bash", str(MEASURE), "--no-write",
             "--budget", str(POLICY_BUDGET), "--doc-budget", str(DOC_BUDGET)],
            capture_output=True, text=True, cwd=str(tmp_path),
            env=_env(exact=False), timeout=120,
        )
        assert result.returncode == 0, result.stderr
        docs = json.loads(result.stdout)["docs"]
        big = next(d for d in docs if d["path"].endswith("BIG.md"))
        assert big["over_budget"] is True, big
