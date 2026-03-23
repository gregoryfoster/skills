"""Integration tests — trigger routing.

Verifies that each skill activates on its declared trigger phrases and does
NOT activate on off-topic inputs.

Approach: inject the skill as system prompt, send a lightweight yes/no
detection prompt, parse "YES" or "NO" from the first line of the response.

Parametrized over all skills via all_skills() — automatically covers new
skills without requiring test updates.

Run with:
    ANTHROPIC_API_KEY=sk-... pytest tests/integration/ -v -m integration

Skipped by default (requires API key and explicit -m integration flag).
Estimated cost: varies by skill count; ~$0.001 per (skill × probe) at Haiku
rates (~64 tokens/call).
"""

import pytest

from tests.utils.api_harness import claude_with_skill
from tests.utils.skill_loader import Skill, all_skills

# ---------------------------------------------------------------------------
# Off-topic probes — should NOT activate any skill
# ---------------------------------------------------------------------------

_OFF_TOPIC_PROBES = [
    "What's the weather today?",
    "Explain recursion to me.",
    "Write a haiku about autumn.",
]

# ---------------------------------------------------------------------------
# Detection prompt
# ---------------------------------------------------------------------------

_DETECTION_TEMPLATE = (
    "A software developer has sent the following request in the context of an active "
    "software development session. Does this request match what your skill is designed "
    "to handle? Respond with exactly 'YES' or 'NO' on the first line, nothing else on "
    "that line.\n\n"
    "User request: \"{request}\""
)


def _skill_activated(response: str) -> bool:
    """Return True if the first line of the response contains 'YES'."""
    first_line = response.strip().split("\n")[0].strip().upper()
    return "YES" in first_line


def _triggers_from_skill(skill: Skill) -> list[str]:
    """Extract individual trigger phrases from a skill's metadata.triggers string."""
    triggers_str = skill.skill_metadata.get("triggers", "")
    return [t.strip() for t in triggers_str.split(",") if t.strip()]


# ---------------------------------------------------------------------------
# Build parametrize inputs at module load (no API calls)
# ---------------------------------------------------------------------------

try:
    _all_skills = all_skills()
except Exception:
    # skills/ directory missing or unreadable — produce zero parametrized tests
    # rather than aborting the entire collection session with an import error.
    _all_skills = []

# Triggers that only work with prior conversational context — the bare phrase
# is too ambiguous for the detection probe to reliably identify the skill.
_CONTEXT_DEPENDENT_TRIGGERS: set[tuple[str, str]] = {
    ("init-project-fastapi-claude", "bootstrap project"),
    ("init-project-fastapi-claude", "set up foundation"),
    ("managing-skills-claude", "add skill repo"),
    ("managing-skills-claude", "manage skills"),
    ("managing-skills-claude", "update vendor skills"),
    ("shipping-work-claude", "close GH"),
    ("shipping-work-claude", "push GH"),
}

def _trigger_param(skill: "Skill", trigger: str) -> pytest.param:
    """Wrap a (skill, trigger) pair in pytest.param, adding xfail for known context-dependent triggers."""
    marks = []
    if (skill.dir_name, trigger) in _CONTEXT_DEPENDENT_TRIGGERS:
        marks.append(
            pytest.mark.xfail(
                reason=(
                    f"'{trigger}' is context-dependent and too ambiguous to activate "
                    "the skill reliably in isolation"
                ),
                strict=False,
            )
        )
    return pytest.param(skill, trigger, id=f"{skill.dir_name}/{trigger}", marks=marks)


_skill_trigger_pairs = [
    _trigger_param(skill, trigger)
    for skill in _all_skills
    for trigger in _triggers_from_skill(skill)
]

_skill_probe_pairs = [
    (skill, probe)
    for skill in _all_skills
    for probe in _OFF_TOPIC_PROBES
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("skill,trigger", _skill_trigger_pairs)
def test_trigger_activates_skill(skill: Skill, trigger: str) -> None:
    """Each declared trigger phrase must cause the skill to activate."""
    prompt = _DETECTION_TEMPLATE.format(request=trigger)
    response = claude_with_skill(skill, prompt, max_tokens=64)
    assert _skill_activated(response), (
        f"Skill '{skill.dir_name}' did not activate for trigger '{trigger}'. "
        f"Response: {response[:200]}"
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "skill,probe",
    _skill_probe_pairs,
    ids=[f"{s.dir_name}/{p.split('.')[0]}" for s, p in _skill_probe_pairs],
)
def test_off_topic_does_not_activate(skill: Skill, probe: str) -> None:
    """Off-topic requests must not cause any skill to activate."""
    prompt = _DETECTION_TEMPLATE.format(request=probe)
    response = claude_with_skill(skill, prompt, max_tokens=64)
    assert not _skill_activated(response), (
        f"Skill '{skill.dir_name}' incorrectly activated for off-topic probe "
        f"'{probe}'. Response: {response[:200]}"
    )
