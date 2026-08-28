"""Structural pin on how test_trigger_routing keys its context-dependent xfails.

`tests/integration/test_trigger_routing.py` attaches a non-strict xfail to
trigger phrases too context-dependent to activate a skill in isolation. The
integration suite that consumes those marks is opt-in — it needs a live API
key and costs money — so nothing in the free, always-on gate noticed when the
keying went wrong (#243): the set was keyed on the exact skill directory name,
so `shipping-work/close GH` was excused while the three `shipping-work-*`
variants, which are *required* to declare byte-identical triggers
(TestVariantFamilyConsistency::test_triggers_match_baseline), were not. Six
parametrized cases failed for a reason that had already been accepted as
not-a-defect.

These tests inspect the collected marks without calling the API, so the
keying contract is checked on every commit. Two failure modes are pinned, and
they pull in opposite directions:

- under-application: a variant does not inherit its baseline's xfail;
- over-application: an unrelated skill inherits an xfail it never earned,
  which is what keying on the bare trigger phrase would have produced —
  it would silently excuse a future skill declaring a trigger like "AR".
"""

import importlib.util
from pathlib import Path

import pytest

from tests.utils.skill_families import (
    infer_variant_candidates,
    skill_family,
    undeclared_variant_candidates,
)


def _candidates_for(names, baselines=None, declared=None):
    """Run the detector's pure core over hypothetical names.

    `declared` defaults to empty rather than to the real declaration: these
    cases ask what the *inference* does with a name, so a name that happens to
    be declared today (`reviewing-code-python-click`) must not be skipped.
    """
    return infer_variant_candidates(
        names, baselines=baselines, declared={} if declared is None else declared
    )

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ROUTING_PATH = _REPO_ROOT / "tests" / "integration" / "test_trigger_routing.py"


def _load_routing_module():
    """Import the integration module by path.

    `tests/integration/` is not a package (no `__init__.py`), so a normal
    `import tests.integration...` does not resolve. Loading by file path keeps
    that layout untouched — adding an `__init__.py` purely to satisfy this
    test would change how pytest collects the integration suite.
    """
    spec = importlib.util.spec_from_file_location(
        "_trigger_routing_under_test", _ROUTING_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def routing():
    return _load_routing_module()


@pytest.fixture(scope="module")
def marked_pairs(routing):
    """The set of (dir_name, trigger) pairs carrying an xfail mark."""
    pairs = set()
    for param in routing._skill_trigger_pairs:
        skill, trigger = param.values
        if any(m.name == "xfail" for m in param.marks):
            pairs.add((skill.dir_name, trigger))
    return pairs


@pytest.fixture(scope="module")
def declared(routing):
    """Every (dir_name, trigger) pair the skills tree actually declares."""
    return {
        (skill.dir_name, trigger)
        for skill in routing._all_skills
        for trigger in routing._triggers_from_skill(skill)
    }


def _family_members(routing, family: str) -> list[str]:
    """Skill dirs belonging to `family`: the baseline plus its `-<stack>` variants."""
    return [
        skill.dir_name
        for skill in routing._all_skills
        if skill.dir_name == family or skill.dir_name.startswith(family + "-")
    ]


class TestSkillFamilyResolution:
    """`skill_family` maps a directory name onto its baseline skill.

    Resolution is **declared-only** — it reads VARIANT_FAMILIES rather than
    inferring from the `<baseline>-<stack>` name shape (CR finding 6). The
    inference that used to do this job still exists, demoted to a detector in
    `undeclared_variant_candidates`; see TestTheDetectorCatchesStaleness.
    """

    def test_a_baseline_resolves_to_itself(self):
        assert skill_family("shipping-work") == "shipping-work"

    @pytest.mark.parametrize(
        "variant",
        ["shipping-work-php", "shipping-work-python-click", "shipping-work-python-fastapi"],
    )
    def test_a_variant_resolves_to_its_baseline(self, variant):
        assert skill_family(variant) == "shipping-work"

    def test_an_unrecognized_name_resolves_to_itself(self):
        assert skill_family("no-such-skill") == "no-such-skill"

    def test_a_lookalike_name_does_not_join_the_family(self):
        """`shipping-work-orders` is not a variant just because it reads like one.

        This is the whole point of declaring membership. Under the previous
        name-inference resolver this returned `shipping-work`, silently
        granting the family's xfails to a skill that never earned them and
        turning any real routing regression in it into a quiet pass.
        """
        assert skill_family("shipping-work-orders") == "shipping-work-orders"

    def test_the_routing_module_uses_the_shared_resolver(self, routing):
        """The integration module must not carry its own copy of this logic."""
        assert routing.skill_family is skill_family, (
            "test_trigger_routing should import skill_family from "
            "tests.utils.skill_families, not define its own — two encodings of "
            "one relation is what CR finding 3 removed."
        )


class TestTheDetectorCatchesStaleness:
    """Declaring membership is safe; forgetting to declare it must be loud.

    An explicit list alone would reintroduce exactly the staleness #243 was
    about. `undeclared_variant_candidates` keeps the name inference as a
    detector so an undeclared lookalike fails `test_naming.py` by name.
    """

    def test_the_tree_is_currently_fully_declared(self):
        assert undeclared_variant_candidates() == []

    def test_a_hyphen_boundary_is_required(self):
        """`shipping-workflow` must not be reported as an undeclared variant.

        Without the boundary a plain `startswith` flags any skill whose name
        merely begins with a baseline's.
        """
        assert not [
            name
            for name, _ in _candidates_for(["shipping-workflow"])
        ], "a hyphen boundary is required before a name counts as a candidate"

    def test_a_lookalike_is_reported_as_undeclared(self):
        assert _candidates_for(["shipping-work-orders"]) == [
            ("shipping-work-orders", "shipping-work")
        ]

    def test_the_longest_matching_baseline_wins(self):
        """With nested baselines the more specific family is the right one."""
        assert _candidates_for(
            ["reviewing-code-python-click"], baselines=["reviewing-code", "reviewing-code-python"]
        ) == [("reviewing-code-python-click", "reviewing-code-python")]


class TestContextDependentTriggerKeying:
    def test_the_set_is_keyed_on_a_family_not_a_directory(self, routing):
        """Every entry names a real baseline skill declaring that trigger.

        A stale entry — a renamed skill, a trigger phrase that has since been
        reworded — is an xfail nobody will ever collect, and it hides the fact
        that the real pair is now failing unexcused.
        """
        declared_by = {
            skill.dir_name: set(routing._triggers_from_skill(skill))
            for skill in routing._all_skills
        }
        for family, trigger in routing._CONTEXT_DEPENDENT_TRIGGERS:
            assert family in declared_by, (
                f"_CONTEXT_DEPENDENT_TRIGGERS names skill family {family!r}, "
                "which is not a skill directory"
            )
            assert trigger in declared_by[family], (
                f"{family} no longer declares the trigger {trigger!r} — "
                "remove or update the _CONTEXT_DEPENDENT_TRIGGERS entry"
            )

    def test_every_family_member_inherits_the_xfail(
        self, routing, marked_pairs, declared
    ):
        """The #243 regression: variants must inherit their baseline's xfail.

        Variant triggers are required to equal the baseline's byte for byte,
        so a trigger that is too ambiguous for the baseline is exactly as
        ambiguous for every variant.
        """
        missing = set()
        for family, trigger in routing._CONTEXT_DEPENDENT_TRIGGERS:
            for member in _family_members(routing, family):
                if (member, trigger) in declared and (
                    member,
                    trigger,
                ) not in marked_pairs:
                    missing.add((member, trigger))
        assert not missing, (
            "these family members declare a context-dependent trigger but did "
            f"not inherit its xfail: {sorted(missing)}"
        )

    def test_no_skill_outside_a_flagged_family_is_marked(self, routing, marked_pairs):
        """Over-application guard — the reason not to key on the bare phrase.

        Keying on the trigger string alone is simpler and produces the same
        marks today, but it would silently excuse any future skill that
        happens to declare `AR` or `close GH`, turning a real routing
        regression into a quiet non-failure.
        """
        allowed = {
            (member, trigger)
            for family, trigger in routing._CONTEXT_DEPENDENT_TRIGGERS
            for member in _family_members(routing, family)
        }
        assert marked_pairs <= allowed, (
            "xfail leaked onto pairs outside the declared families: "
            f"{sorted(marked_pairs - allowed)}"
        )

    def test_other_triggers_of_a_flagged_family_stay_unmarked(self, marked_pairs):
        """The key keeps its trigger dimension.

        `shipping-work` is flagged for `close GH` and `push GH` only; its
        unambiguous triggers must still be able to fail.
        """
        for member in (
            "shipping-work",
            "shipping-work-php",
            "shipping-work-python-click",
            "shipping-work-python-fastapi",
        ):
            for trigger in ("ship it", "wrap up"):
                assert (member, trigger) not in marked_pairs

    def test_the_reviewing_code_family_is_not_flagged_at_all(self, marked_pairs):
        """A sibling variant family with no context-dependent entry stays clean."""
        leaked = {p for p in marked_pairs if p[0].startswith("reviewing-code")}
        assert not leaked, f"unexpected xfail on the reviewing-code family: {leaked}"
