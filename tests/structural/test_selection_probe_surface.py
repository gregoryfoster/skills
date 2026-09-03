"""The free half of the competitive-selection probe (#242).

`tests/integration/test_competitive_selection.py` spends real money asking a
live model to pick one skill from the full listing. Everything *around* that
question — the listing is complete, every declared variant gets a scenario, the
uncovered-stack case is genuinely uncovered, the parser scores a hedge as a
hedge — needs no API call at all, and so belongs here, where it runs on every
commit.

This is #243's lesson applied forward. That bug survived because its only guard
lived in a suite `pyproject.toml` deselects by default; the same asymmetry would
let this probe silently stop covering a family. The specific rot this file
prevents: someone adds `reviewing-code-go` to `VARIANT_FAMILIES` and the billed
suite quietly keeps testing three stacks instead of four, with nothing red
anywhere. `test_every_declared_variant_has_a_scenario` makes that a loud failure
on the next commit, naming the fix.

What this file cannot do is verify that selection *works*. That is the billed
suite's job and it is not substitutable — the whole point of #97 was that a
structurally well-formed surface can still shadow.
"""

import pytest

from tests.utils.selection_probe import (
    LABEL_NAMING_CONTEXTS,
    NONE_CHOICE,
    UNCOVERED_STACK,
    parse_choice,
    scenarios,
    selection_prompt,
    skill_listing,
)
from tests.utils.skill_families import BASELINES, VARIANT_FAMILIES
from tests.utils.skill_loader import all_skills

_SKILLS = all_skills()
_SCENARIOS = scenarios(_SKILLS)
_LISTING = skill_listing(_SKILLS)
_VARIANTS = sorted({variant for _, variant, _ in VARIANT_FAMILIES})


class TestTheListingIsTheWholeSurface:
    """The probe's premise is that the model sees everything the runtime shows it.

    A listing missing even one skill measures a different library than the one
    that ships, and would understate competition in exactly the direction that
    hides shadowing.
    """

    @pytest.mark.parametrize("skill", _SKILLS, ids=lambda s: s.dir_name)
    def test_every_skill_contributes_name_and_description(self, skill):
        assert skill.name, f"{skill.dir_name} has no frontmatter name to list"
        assert skill.description, f"{skill.dir_name} has no description to list"
        assert f"- name: {skill.name}\n" in _LISTING, (
            f"{skill.dir_name} is missing from the selection listing"
        )
        assert skill.description in _LISTING, (
            f"{skill.dir_name}'s description is missing from the selection listing"
        )

    def test_the_listing_has_one_entry_per_skill(self):
        assert _LISTING.count("- name: ") == len(_SKILLS)

    def test_no_two_skills_share_a_description(self):
        """Identical descriptions are unresolvable by any selection layer.

        `test_content_invariants` already forbids a variant copying its
        baseline's description verbatim; this states the same requirement as a
        property of the surface itself, across all skills rather than within a
        family.
        """
        seen: dict[str, str] = {}
        for skill in _SKILLS:
            clash = seen.get(skill.description)
            assert clash is None, (
                f"{skill.dir_name} and {clash} have byte-identical descriptions — "
                "the selection surface cannot distinguish them at all."
            )
            seen[skill.description] = skill.dir_name


class TestTheMatrixCoversTheDeclaredFamilies:
    """Scenario coverage is derived from `VARIANT_FAMILIES`, and pinned here."""

    @pytest.mark.parametrize("variant", _VARIANTS)
    def test_every_declared_variant_has_a_scenario(self, variant):
        """The growth ratchet — see the module docstring.

        A variant with no `_STACK_CONTEXTS` entry for its stack keyword is
        silently skipped by `scenarios()`. That silence is the failure mode this
        catches.
        """
        matching = [s for s in _SCENARIOS if s.expected == variant]
        assert matching, (
            f"No competitive-selection scenario expects {variant}. Add its stack "
            "keyword (the third element of its VARIANT_FAMILIES row) to "
            "`_STACK_CONTEXTS` in tests/utils/selection_probe.py, with a sentence "
            "describing the evidence a real session would see for that stack."
        )
        assert len(matching) == 1, (
            f"{variant} is expected by {len(matching)} scenarios; one is intended"
        )

    @pytest.mark.parametrize("baseline", BASELINES)
    def test_every_baseline_gets_a_no_context_scenario(self, baseline):
        """The bare trigger with no stack evidence must resolve to the baseline."""
        matching = [s for s in _SCENARIOS if s.family == baseline and s.stack == "none"]
        assert len(matching) == 1
        assert matching[0].expected == baseline
        assert matching[0].context == ""

    @pytest.mark.parametrize("baseline", BASELINES)
    def test_every_baseline_gets_an_uncovered_stack_scenario(self, baseline):
        """#240's assertion: an uncovered stack falls back to the baseline."""
        matching = [
            s for s in _SCENARIOS if s.family == baseline and s.stack == UNCOVERED_STACK
        ]
        assert len(matching) == 1, (
            f"{baseline} has no uncovered-stack scenario — the case #240 exists for"
        )
        assert matching[0].expected == baseline
        assert matching[0].context, "the uncovered-stack scenario needs stack evidence"

    def test_the_uncovered_stack_is_actually_uncovered(self):
        """If a `-go` variant ever lands, this scenario stops testing fallback.

        It would then assert that a covered stack routes to the *baseline*,
        which is the opposite of the contract — a false green rather than a gap.
        """
        declared = {stack for _, _, stack in VARIANT_FAMILIES}
        assert UNCOVERED_STACK not in declared, (
            f"A variant now declares the stack keyword {UNCOVERED_STACK!r}, so the "
            "fallback scenarios are no longer probing an uncovered stack. Pick a "
            "still-uncovered stack for `UNCOVERED_STACK`."
        )

    @pytest.mark.parametrize("scenario", _SCENARIOS, ids=lambda s: s.id)
    def test_each_scenario_expects_a_skill_that_exists(self, scenario):
        assert scenario.expected in {s.dir_name for s in _SKILLS}

    @pytest.mark.parametrize("scenario", _SCENARIOS, ids=lambda s: s.id)
    def test_each_scenario_uses_a_declared_trigger(self, scenario):
        """The probe must fire the family's real trigger, not a paraphrase."""
        baseline = next(s for s in _SKILLS if s.dir_name == scenario.family)
        declared = [
            t.strip()
            for t in baseline.skill_metadata.get("triggers", "").split(",")
            if t.strip()
        ]
        assert scenario.trigger in declared, (
            f"{scenario.id} fires {scenario.trigger!r}, which {scenario.family} does "
            f"not declare. Declared: {declared}"
        )

    def test_scenario_ids_are_unique(self):
        ids = [s.id for s in _SCENARIOS]
        assert len(ids) == len(set(ids)), f"duplicate scenario ids in {ids}"


class TestTheContextsDoNotGiveTheAnswerAway:
    """A context that names its own answer measures string matching, not selection."""

    @pytest.mark.parametrize(
        "scenario", [s for s in _SCENARIOS if s.context], ids=lambda s: s.id
    )
    def test_context_never_names_the_expected_skill(self, scenario):
        assert scenario.expected not in scenario.context, (
            f"{scenario.id}'s stack context names {scenario.expected} outright. "
            "Describe the repository's artifacts and let the model infer."
        )

    @pytest.mark.parametrize(
        "scenario",
        [s for s in _SCENARIOS if s.context and s.stack != UNCOVERED_STACK],
        ids=lambda s: s.id,
    )
    def test_context_does_not_name_its_own_stack_undeclared(self, scenario):
        """Naming the stack turns inference into token matching.

        A context that says "this is a Click project" would be passed by a
        library where every description had been replaced with its stack tag —
        which is exactly the shadowing this suite exists to detect. Allowed,
        but only as a declared exception carrying its reason.
        """
        if scenario.stack.lower() in scenario.context.lower():
            assert scenario.stack in LABEL_NAMING_CONTEXTS, (
                f"{scenario.id}'s context contains its own stack keyword "
                f"{scenario.stack!r}, weakening the scenario to a token match. "
                "Rewrite it to describe the repository's artifacts, or — if the "
                "stack genuinely cannot be described without naming it — add an "
                "entry to `LABEL_NAMING_CONTEXTS` in tests/utils/selection_probe.py "
                "stating why."
            )

    @pytest.mark.parametrize("stack", sorted(LABEL_NAMING_CONTEXTS))
    def test_declared_label_naming_exceptions_are_still_needed(self, stack):
        """A stale exception silently re-permits what it was granted for.

        If the context is reworded to stop naming its stack, the entry should
        go with it — otherwise the next contributor inherits a standing licence
        nobody re-examined.
        """
        matching = [s for s in _SCENARIOS if s.stack == stack]
        assert matching, (
            f"{stack!r} is declared in LABEL_NAMING_CONTEXTS but has no scenario"
        )
        assert any(stack.lower() in s.context.lower() for s in matching), (
            f"{stack!r} no longer names itself in its context, so its "
            "LABEL_NAMING_CONTEXTS exception is stale — remove it."
        )

    @pytest.mark.parametrize(
        "scenario",
        [s for s in _SCENARIOS if s.stack == UNCOVERED_STACK],
        ids=lambda s: s.id,
    )
    def test_the_uncovered_context_names_no_covered_stack(self, scenario):
        """Any covered-stack keyword leaking in would hand the model a variant."""
        lowered = scenario.context.lower()
        leaked = [stack for _, _, stack in VARIANT_FAMILIES if stack.lower() in lowered]
        assert not leaked, (
            f"{scenario.id}'s uncovered-stack context mentions {leaked}, which a "
            "variant covers — the scenario would no longer be testing fallback."
        )


class TestThePromptIsWellFormed:
    @pytest.mark.parametrize("scenario", _SCENARIOS, ids=lambda s: s.id)
    def test_prompt_carries_listing_request_and_none_option(self, scenario):
        prompt = selection_prompt(scenario, _LISTING)
        assert _LISTING in prompt
        assert f'User request: "{scenario.trigger}"' in prompt
        assert NONE_CHOICE in prompt, (
            "the prompt must offer NONE, or a model with no good answer is forced "
            "to guess and the probe cannot see the #97 failure mode at all"
        )

    @pytest.mark.parametrize(
        "scenario", [s for s in _SCENARIOS if s.context], ids=lambda s: s.id
    )
    def test_prompt_carries_the_stack_context(self, scenario):
        assert scenario.context in selection_prompt(scenario, _LISTING)

    @pytest.mark.parametrize(
        "scenario", [s for s in _SCENARIOS if not s.context], ids=lambda s: s.id
    )
    def test_no_context_prompt_carries_no_stack_evidence(self, scenario):
        """The no-context arm's whole value is that it states nothing about the stack."""
        prompt = selection_prompt(scenario, _LISTING)
        listing_free = prompt.replace(_LISTING, "")
        for other in _SCENARIOS:
            if other.context:
                assert other.context not in listing_free


class TestParseChoice:
    """Strict on purpose — a lenient parser scores hedging as a clean pick."""

    @pytest.mark.parametrize(
        "response,expected",
        [
            ("reviewing-code", "reviewing-code"),
            ("reviewing-code\n", "reviewing-code"),
            ("`reviewing-code-php`", "reviewing-code-php"),
            ('"shipping-work"', "shipping-work"),
            ("**shipping-work-python-click**", "shipping-work-python-click"),
            ("reviewing-code.", "reviewing-code"),
            ("shipping-work\nBecause the project is a Go service.", "shipping-work"),
            ("NONE", NONE_CHOICE),
            ("none", NONE_CHOICE),
            ("`NONE`", NONE_CHOICE),
        ],
    )
    def test_decoration_is_stripped(self, response, expected):
        assert parse_choice(response) == expected

    @pytest.mark.parametrize(
        "response",
        [
            "Either reviewing-code or reviewing-code-php would work.",
            "I would choose reviewing-code.",
            "reviewing-code, reviewing-code-php",
        ],
    )
    def test_hedged_answers_do_not_normalise_to_a_name(self, response):
        """A sentence containing a name is not a selection.

        Scoring these as correct would let a model that cannot disambiguate
        pass by listing candidates — precisely the behaviour under test.
        """
        valid = {s.dir_name for s in _SKILLS} | {NONE_CHOICE}
        assert parse_choice(response) not in valid
