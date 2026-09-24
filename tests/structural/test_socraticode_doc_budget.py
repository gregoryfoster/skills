"""The generated `docs/SOCRATICODE.md` is a fixed cost, so it has a ratchet (#329).

Everything between the template's markers is rewritten on every
`init-socraticode` re-run, and only what follows `END` is curatable — the
repo-specific notes the template itself tells a consumer to write there. So the
template's size is subtracted from every consumer's 10,000-token per-doc budget
before they write a line, and no curation run can win it back.

Measured on CannObserv/watcher when #329 was filed, the generated part was
5,687 exact tokens (5,729 on this repo's template, which carries no adapted
rows): 57% of the budget, with **Graph health** alone half of it. The audit
re-run there rescued the repo's pre-marker notes below `END`, the file came to
11,444 tokens, and getting under meant cutting that repo's own measured notes
from 5,117 to ~4.2k. The skill's fixed cost was displacing the part it asks
for.

#329 moved what the rules were learned from — the PSR-4 and stale-graph
stories, the `builderCheck`/`checkServer`/`sessionServer` walk, both verbatim
wordings of the `unresolvedPct` note — to `references/graph-health.md`, and
this file stops the template regrowing. The ratchet follows
`test_skill_self_budget.py`'s rules, because it is the same kind of number: it
binds the offline estimate on every commit and `count_tokens` when
`SKILL_BUDGET_EXACT=1`, it sits at the larger reading rounded up to the next
50, and it only comes down. The reference names the figure in prose, so the
gate and a reader quote the same number.

What is measured is the template as a consumer receives it — the ````markdown
fence's contents, markers included — not `references/socraticode-doc.md`,
whose own prose above the fence never reaches a consumer and is held by the
per-doc budget like every other reference.
"""

import json
import subprocess
from pathlib import Path

import pytest

from .test_skill_self_budget import (
    EXACT_ENV,
    MEASURE,
    REPO_ROOT,
    _env,
    _exact_requested,
    _has_credential,
    ratio_estimates,
)
from .test_socraticode_policy_split import DOC_REF, _template

# 2,547 estimated, 2,593 exact after #329 — the larger, rounded up to the next
# 50. Lower it when a later trim finds more; never raise it. A rule a consumer
# acts on may displace a sentence here, but an addition that needs headroom
# belongs in references/graph-health.md or another reference, which cost a
# consumer nothing.
GENERATED_DOC_RATCHET = 2_600

RATCHET_PHRASE = f"{GENERATED_DOC_RATCHET:,}-token ratchet (estimate and exact)"


def _generated() -> str:
    return _template(DOC_REF.read_text())


def _measure_exact(path: Path) -> dict:
    """count_tokens over one file, by the skill's own script.

    Run from the repo root so the script finds the repo's `.env` itself, as
    `test_skill_self_budget.py`'s exact pass does; `--file` takes the absolute
    path of the extracted template, and `--docs-dir` an empty directory so
    nothing else is measured.
    """
    docs = path.parent / "no-docs"
    docs.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            "bash",
            str(MEASURE),
            "--exact",
            "--no-write",
            "--file",
            str(path),
            "--docs-dir",
            str(docs),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=_env(exact=True),
        timeout=120,
    )
    assert result.returncode == 0, f"measure-context.sh failed:\n{result.stderr}"
    return json.loads(result.stdout)["policy"]


class TestTheGeneratedDocStaysSmall:
    def test_the_estimate_is_within_the_ratchet(self) -> None:
        body = _generated().encode()
        (estimate,) = ratio_estimates([len(body)])
        assert estimate <= GENERATED_DOC_RATCHET, (
            f"the generated docs/SOCRATICODE.md is ~{estimate} estimated tokens "
            f"against its {GENERATED_DOC_RATCHET:,} ratchet. Every consumer "
            "pays it on every re-run, out of the per-doc budget their own "
            "notes need (#329): move the addition's rationale to "
            "references/graph-health.md, or another reference, and keep only "
            "the rule here."
        )

    def test_the_reference_names_its_own_ratchet(self) -> None:
        prose = " ".join(DOC_REF.read_text().split()).replace("**", "")
        assert RATCHET_PHRASE in prose, (
            f"references/{DOC_REF.name} must name the figure this file "
            f"enforces — {RATCHET_PHRASE!r} — so a reader editing the template "
            "sees the budget before the gate does"
        )

    def test_the_graph_health_long_form_is_named_not_linked(self) -> None:
        """The rationale moved; a consumer must still be able to find it.

        Named as a path in the vendored skill rather than linked: the template
        is written into `docs/`, where a relative link into this skill's
        `references/` would resolve here and 404 in every consumer — and the
        fenced-block skip in test_relative_links would never notice.
        """
        body = _generated()
        assert "`skills/init-socraticode/references/graph-health.md`" in body, (
            "the generated doc's Graph health section must name where its "
            "rules' rationale and each finding's full wording now live (#329)"
        )
        assert "](graph-health.md" not in body and "](references/" not in body, (
            "the generated doc links into the skill's references/, which does "
            "not exist beside a consumer's docs/SOCRATICODE.md"
        )


class TestTheContractMeasuredExactly:
    def test_the_exact_count_is_within_the_ratchet(self, tmp_path: Path) -> None:
        if not _exact_requested():
            pytest.skip(
                f"exact verification is opt-in: set {EXACT_ENV}=1 to run it, "
                "as test_skill_self_budget.py's exact pass is"
            )
        if not _has_credential():
            pytest.skip(f"{EXACT_ENV} set but no usable count_tokens credential")
        path = tmp_path / "SOCRATICODE.md"
        path.write_text(_generated())
        measured = _measure_exact(path)
        if not measured["tokens_exact"]:
            pytest.skip("count_tokens was not reached; the estimate test ran")
        assert measured["tokens"] <= GENERATED_DOC_RATCHET, (
            f"the generated docs/SOCRATICODE.md is {measured['tokens']} exact "
            f"tokens against its {GENERATED_DOC_RATCHET:,} ratchet (#329)"
        )
