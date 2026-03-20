"""API harness for integration tests.

Injects skill content as a system prompt into Claude API calls, mirroring the
mechanism Claude Code uses when loading a skill. Uses Haiku by default —
behavioral compliance ("does the gate fire?") does not require Sonnet-level
capability and provides ~20x cost reduction.
"""

import os

import anthropic

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
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=skill.body,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def hard_gate_fired(response: str) -> bool:
    """Return True if the response contains refusal or gate-enforcement language.

    Checks for a broad set of signals rather than exact strings, so tests
    remain resilient to minor phrasing variation across model versions.
    """
    lowered = response.lower()
    return any(signal in lowered for signal in _REFUSAL_SIGNALS)
