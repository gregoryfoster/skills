"""The one declaration of which skills are variants of which baseline.

Two independent mechanisms used to encode this relation and could drift apart
(CR finding 3): `test_content_invariants.VARIANT_FAMILY_PAIRS` hand-listed the
pairs, while `test_trigger_routing._skill_family` inferred them from directory
names. Each was individually correct, so a divergence would have been invisible
— adding `reviewing-code-go` would have inherited the trigger xfails
automatically while silently gaining no drift assertions.

Both now read `VARIANT_FAMILIES` below.

## Why an explicit declaration rather than pure name inference

Inference from `<baseline>-<stack>` is what #243 shipped, and it carries a
hazard the inference itself cannot see (CR finding 6): a future skill named
`shipping-work-orders` — a genuinely different skill, not a variant — matches
the prefix and would silently inherit the family's xfails, turning a real
routing regression into a quiet pass. A name is a guess about intent; this
list states it.

## Why that does not reintroduce the staleness it replaced

The objection to a hand-kept list is real and was #243's own lesson: a list
you must remember to update is a list that goes stale, and the staleness is
silent. So the inference is kept — demoted from authority to **detector**.
`undeclared_variant_candidates()` finds any skill directory that *looks* like
a variant but is not declared here, and `test_naming.py` fails on it. Adding
`reviewing-code-go` without declaring it is therefore a loud error naming the
fix, not a silent gap.

Authority is explicit; detection is inferred. Neither alone is sufficient.
"""

from tests.utils.skill_loader import all_skills

# (baseline, variant, stack keyword asserted in the variant's `compatibility`).
# The stack keyword belongs here rather than beside the drift assertions
# because it is a property of the family relation, not of any one test.
VARIANT_FAMILIES: list[tuple[str, str, str]] = [
    ("reviewing-code", "reviewing-code-php", "PHP"),
    ("reviewing-code", "reviewing-code-python-fastapi", "FastAPI"),
    ("reviewing-code", "reviewing-code-python-click", "Click"),
    ("shipping-work", "shipping-work-php", "PHP"),
    ("shipping-work", "shipping-work-python-fastapi", "FastAPI"),
    ("shipping-work", "shipping-work-python-click", "Click"),
]

# Skill directories that look like `<baseline>-<suffix>` but are deliberately
# NOT variants. Empty today; an entry here is a decision with a reason, which
# is the point — the detector forces the question to be answered rather than
# defaulted.
NOT_VARIANTS: dict[str, str] = {}

_VARIANT_TO_BASELINE = {variant: base for base, variant, _ in VARIANT_FAMILIES}

BASELINES = sorted({base for base, _, _ in VARIANT_FAMILIES})


def skill_family(dir_name: str) -> str:
    """Return the baseline whose family `dir_name` belongs to.

    A baseline, and any skill that is not a declared variant, is its own
    family. Declared-only: a name that merely *looks* like a variant does not
    join a family (see module docstring).
    """
    return _VARIANT_TO_BASELINE.get(dir_name, dir_name)


def family_members(family: str) -> list[str]:
    """The baseline plus every skill declared as its variant."""
    return [family] + sorted(
        variant for variant, base in _VARIANT_TO_BASELINE.items() if base == family
    )


def infer_variant_candidates(
    names: list[str],
    baselines: list[str] | None = None,
    declared: dict[str, str] | None = None,
    excluded: dict[str, str] | None = None,
) -> list[tuple[str, str]]:
    """Pure core of the detector — no disk access, so it is directly testable.

    Returns `(name, inferred_baseline)` for each name shaped like
    `<baseline>-<suffix>` that is neither declared nor excluded. The `-`
    boundary is required, so `shipping-workflow` is not a candidate for
    `shipping-work`; the longest match wins, so a nested baseline beats a
    shorter prefix of it.
    """
    baselines = BASELINES if baselines is None else baselines
    declared = _VARIANT_TO_BASELINE if declared is None else declared
    excluded = NOT_VARIANTS if excluded is None else excluded

    candidates = []
    for name in sorted(names):
        if name in declared or name in excluded:
            continue
        matches = [b for b in baselines if name != b and name.startswith(b + "-")]
        if matches:
            candidates.append((name, max(matches, key=len)))
    return candidates


def undeclared_variant_candidates() -> list[tuple[str, str]]:
    """Skill dirs on disk that look like variants but are undeclared.

    The detector half of this module — see the module docstring for why
    inference survives here after losing its authority over resolution.
    """
    return infer_variant_candidates([skill.dir_name for skill in all_skills()])
