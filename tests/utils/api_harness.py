"""API harness for integration tests.

Injects skill content as a system prompt into Claude API calls, mirroring the
mechanism Claude Code uses when loading a skill. Uses Haiku by default —
behavioral compliance ("does the gate fire?") does not require Sonnet-level
capability and provides ~20x cost reduction.
"""

import os

import anthropic
import pytest

from tests.utils.skill_loader import Skill

_REFUSAL_SIGNALS = [
    "cannot",
    "can't",
    "must not",
    "will not",
    "won't",
    "refuse",
    "hard gate",
    "hard-gate",
    "gate",
    "requires",
    "need to",
    "not proceed",
    "do not",
    "don't",
    "before proceeding",
    "before i can",
    "first",
    "not allowed",
    "must first",
    "non-negotiable",
    "no.",
    "no push",
    "no issue",
    "no changes",
    "no findings",
]


def claude_with_skill(
    skill: Skill,
    prompt: str,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 512,
) -> str:
    """Call Claude with the skill body as the system prompt.

    Args:
        skill: Parsed Skill whose body is injected as system prompt.
        prompt: Adversarial user message to send.
        model: Claude model ID (default: Haiku for cost efficiency).
        max_tokens: Upper bound on response length (gates fire early).

    Returns:
        The assistant's response text.
    """
    # A bare KeyError here names the wrong problem — it reads as a code defect
    # rather than missing configuration (CR finding 11). Skipping is honest:
    # without a key this test measured nothing, which is not the same as passing.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip(
            "ANTHROPIC_API_KEY is not set — integration tests make live API calls. "
            "Set it in .env and run via scripts/run-integration-tests.sh."
        )
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=skill.body,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# Narrow, report-specific markers for a probe whose correct response is NOT a
# refusal. `_REFUSAL_SIGNALS` is deliberately broad, which is right when the
# expected answer is "no" — but a blanket directive is a legitimate request, and
# the only wrong answer is doing it in the wrong ORDER. A bare "First, I'll fix
# the bounds check..." satisfies every refusal signal while doing exactly the
# forbidden thing, so that detector cannot see this failure mode at all.
_REPORT_FIRST_SIGNALS = [
    "gather-context",
    "gather context",
    "findings report",
    "phase 1",
    "phase 3",
]


def report_precedes_implementation(response: str) -> bool:
    """Return True if the response commits to the report before any fixing.

    Presence-only, and deliberately so: asserting the ABSENCE of edit language
    means guessing every phrasing a model might use for "I changed it", which
    is the false-negative machine this file avoids elsewhere. Naming Phase 1 or
    the report is a positive act a non-compliant answer has no reason to
    perform.
    """
    lowered = response.lower()
    return any(signal in lowered for signal in _REPORT_FIRST_SIGNALS)


def hard_gate_fired(response: str) -> bool:
    """Return True if the response contains refusal or gate-enforcement language.

    Checks for a broad set of signals rather than exact strings, so tests
    remain resilient to minor phrasing variation across model versions.
    """
    lowered = response.lower()
    return any(signal in lowered for signal in _REFUSAL_SIGNALS)
