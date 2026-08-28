"""The baseline skills must state their fallback role on the selection surface.

#240: in #97's 72-trial competitive-selection probe, a Go project — no variant
exists for it — got NO skill chosen 8/8 times at Haiku tier. The baselines
*are* the intended answer there, but their fallback role was documented only
in an AGENTS.md tree-listing comment, which the runtime's selection surface
(name + description) never sees. Sonnet-tier models recovered; smaller ones
did not.

The fix added a fallback clause to both baseline descriptions. This pins it.

## Why this file exists at all (CR finding 2)

The suite that can actually *measure* the fix — `tests/integration/`, which
asks a live model to choose among the real descriptions — is opt-in: it needs
`ANTHROPIC_API_KEY`, costs money per call, and `pyproject.toml` deselects it
by default via `addopts = "-m 'not integration and not benchmark'"`. That is
precisely the asymmetry that let #243's keying bug survive: a contract whose
only guard is a suite nobody runs by default is a contract that rots quietly.

So this asserts the cheap, structural half — the clause is *present*, on the
baselines and only on the baselines. It cannot verify the clause *works*; that
is #242's job. A silent revert, though, now fails on every commit.
"""

import pytest

from tests.utils.skill_families import BASELINES, VARIANT_FAMILIES
from tests.utils.skill_loader import load_skill, SKILLS_DIR

# Substrings that constitute stating the fallback role. Matching on meaning-
# bearing phrases rather than one exact sentence lets the wording be reworded
# without a test edit, while still failing if the idea is dropped entirely.
_FALLBACK_MARKERS = ("last resort", "no dedicated")

_VARIANTS = sorted({variant for _, variant, _ in VARIANT_FAMILIES})


def _description(dir_name: str) -> str:
    return load_skill(SKILLS_DIR / dir_name).description


@pytest.mark.parametrize("baseline", BASELINES)
class TestBaselinesStateTheirFallbackRole:
    def test_description_states_the_fallback_role(self, baseline):
        description = _description(baseline)
        assert any(m in description.lower() for m in _FALLBACK_MARKERS), (
            f"{baseline}'s description must state that it is the fallback for stacks "
            f"with no dedicated variant (#240). Expected one of {_FALLBACK_MARKERS} in:\n"
            f"  {description!r}\n"
            "Without it the selection surface gives a model no reason to prefer the "
            "baseline on an uncovered stack, and smaller models pick nothing at all."
        )

    def test_the_clause_names_the_variant_family(self, baseline):
        """The clause should say which family it is the fallback *for*.

        `reviewing-code` and `shipping-work` are both baselines; a bare "use me
        when nothing else matches" in each gives a model no way to tell which
        of the two an uncovered stack should get.
        """
        description = _description(baseline)
        assert f"{baseline}-" in description, (
            f"{baseline}'s fallback clause should name its own variant family "
            f"(e.g. '{baseline}-*') so the clause distinguishes it from the other "
            f"baseline. Got:\n  {description!r}"
        )


@pytest.mark.parametrize("variant", _VARIANTS)
def test_variants_do_not_claim_the_fallback_role(variant):
    """Only the baselines are the fallback — a variant claiming it is a defect.

    This is the failure mode AGENTS.md's "Adding a variant" procedure can
    produce: the procedure starts with `cp -r` of the baseline, so a variant
    that inherits the description wholesale inherits a claim that is false for
    it. `test_description_differs_from_baseline` catches only a byte-identical
    copy, not a lightly-edited one that keeps the clause.
    """
    description = _description(variant).lower()
    matched = [m for m in _FALLBACK_MARKERS if m in description]
    assert not matched, (
        f"{variant} is a stack-specific variant but its description claims the "
        f"baseline's fallback role (matched {matched}). Remove that clause — it was "
        "almost certainly inherited by copying the baseline. Only the baselines "
        "answer for stacks with no dedicated variant."
    )
