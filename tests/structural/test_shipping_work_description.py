"""`shipping-work`'s description says what it is now: one skill for every stack.

Until #537's release 2 it was the baseline of a variant family, and its
description said so — "the fallback of last resort … for any stack with no
dedicated shipping-work-* variant" (#240). Release 2 deleted the variants, so
that clause told the selection surface two false things: that a better match
exists for FastAPI, Click and PHP repos, and that this skill is for whatever
is left over. A model reading it could pass over the only ship skill there is.

`test_baseline_fallback_clause.py` holds the clause on the baselines and off
their variants; `shipping-work` is neither now, so this pins its own wording.

No API calls. Whether the description routes is `test_trigger_routing`'s job.
"""

from tests.utils.skill_families import BASELINES
from tests.utils.skill_loader import SKILLS_DIR, load_skill

DESCRIPTION = load_skill(SKILLS_DIR / "shipping-work").description


def test_it_is_no_longer_a_baseline():
    assert "shipping-work" not in BASELINES


def test_it_claims_no_fallback_role():
    lowered = DESCRIPTION.lower()
    for marker in ("last resort", "no dedicated", "fallback"):
        assert marker not in lowered, (
            f"shipping-work's description still claims a fallback role "
            f"({marker!r}); there is no variant for it to fall back from:\n"
            f"  {DESCRIPTION!r}"
        )


def test_it_names_no_variant():
    assert "shipping-work-" not in DESCRIPTION, (
        f"shipping-work's description names a variant family that no longer "
        f"exists:\n  {DESCRIPTION!r}"
    )


def test_it_says_it_detects_the_stack():
    lowered = DESCRIPTION.lower()
    assert "detects" in lowered, DESCRIPTION
    for stack in ("fastapi", "click", "php"):
        assert stack in lowered, (
            f"the description should name the stacks it detects, so a model "
            f"choosing for a {stack} repo sees it is covered; missing {stack!r}:"
            f"\n  {DESCRIPTION!r}"
        )
