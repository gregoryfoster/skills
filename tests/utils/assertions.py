"""Reusable regex-based format checkers for skill output assertions.

These assertions check structural compliance only — no semantic judgment.
They can be imported by Phase 4 benchmarks to validate judge inputs.
"""

import re
from typing import Optional

__all__ = [
    "assert_title_format",
    "assert_severity_ordering",
    "assert_sequential_numbering",
    "assert_finding_subfields",
    "assert_summary_section",
    "assert_full_format_compliance",
]

# Severity emoji markers
_SEVERITY_RED = "🔴"
_SEVERITY_YELLOW = "🟡"
_SEVERITY_BLUE = "💭"

# Pattern for top-level numbered findings: lines starting with a digit and period
_FINDING_PATTERN = re.compile(r"^\s*(\d+)\.", re.MULTILINE)

# Title patterns
_CODE_REVIEW_TITLE = re.compile(r"^## Code & Documentation Review — .+", re.MULTILINE)
_ARCH_REVIEW_TITLE = re.compile(r"^## Architectural Review — .+", re.MULTILINE)
_ANY_REVIEW_TITLE = re.compile(
    r"^## (Code & Documentation|Architectural) Review — .+", re.MULTILINE
)

# Summary section — matches "### Summary" or "### Architecture Summary" etc.
_SUMMARY_PATTERN = re.compile(r"^### (\w+ )?Summary", re.MULTILINE)


def _findings_body(text: str) -> str:
    """Return the slice of text between the first severity marker and ### Summary.

    Scoping numbered-item checks to this region avoids false matches from
    ordered lists in the "What's solid" section, procedure descriptions, or
    other non-finding content in the response.
    """
    severity_positions = [
        text.find(e)
        for e in (_SEVERITY_RED, _SEVERITY_YELLOW, _SEVERITY_BLUE)
        if text.find(e) != -1
    ]
    start = min(severity_positions) if severity_positions else 0
    end_match = _SUMMARY_PATTERN.search(text)
    end = end_match.start() if end_match else len(text)
    return text[start:end]


def assert_title_format(text: str, review_type: Optional[str] = None) -> None:
    """Assert the response contains a properly formatted review title.

    Args:
        text: Response text to check.
        review_type: Optional "code" or "architecture" to narrow the check.

    Raises:
        AssertionError: If no matching title is found.
    """
    if review_type == "code":
        assert _CODE_REVIEW_TITLE.search(text), (
            "Response must contain a title matching "
            "'## Code & Documentation Review — [scope]'. "
            f"Response starts with: {text[:300]}"
        )
    elif review_type == "architecture":
        assert _ARCH_REVIEW_TITLE.search(text), (
            "Response must contain a title matching "
            "'## Architectural Review — [scope]'. "
            f"Response starts with: {text[:300]}"
        )
    else:
        assert _ANY_REVIEW_TITLE.search(text), (
            "Response must contain a review title matching the expected format. "
            f"Response starts with: {text[:300]}"
        )


def assert_severity_ordering(text: str) -> None:
    """Assert severity sections appear in order: 🔴 before 🟡 before 💭.

    Only checks ordering when two or more severity sections are present.

    Raises:
        AssertionError: If present sections are out of order.
    """
    red_pos = text.find(_SEVERITY_RED)
    yellow_pos = text.find(_SEVERITY_YELLOW)
    blue_pos = text.find(_SEVERITY_BLUE)

    present = [
        (pos, emoji)
        for pos, emoji in [
            (red_pos, _SEVERITY_RED),
            (yellow_pos, _SEVERITY_YELLOW),
            (blue_pos, _SEVERITY_BLUE),
        ]
        if pos != -1
    ]

    if len(present) < 2:
        return  # Cannot check ordering with 0 or 1 sections

    positions = [pos for pos, _ in present]
    assert positions == sorted(positions), (
        f"Severity sections must appear in order: 🔴 → 🟡 → 💭. "
        f"Found order: {[emoji for _, emoji in present]}"
    )


def assert_sequential_numbering(text: str) -> None:
    """Assert all top-level numbered findings form a sequential list (1, 2, 3…).

    Numbers must not reset between severity groups. Only numbered items within
    the findings body (between the first severity marker and ### Summary) are
    checked, to avoid false matches from other numbered lists in the response.

    Raises:
        AssertionError: If numbering is not sequential starting from 1.
    """
    body = _findings_body(text)
    numbers = [int(m.group(1)) for m in _FINDING_PATTERN.finditer(body)]
    if not numbers:
        return  # No findings present — not an error

    expected = list(range(1, len(numbers) + 1))
    assert numbers == expected, (
        f"Findings numbering must be sequential (1, 2, 3…) without resets. "
        f"Got: {numbers}"
    )


# The two skills do NOT share a finding envelope, and asserting one against the
# other is how the drift below went unnoticed for four versions: this helper
# pinned `Suggested fix:` while reviewing-architecture has said
# `Suggested approach:` since 547f615 (v1.1), and the prompts in
# test_output_format.py asked the model for the stale wording — so the check
# passed by MASKING the divergence rather than by detecting it. #142 then added
# `Evidence:` and widened the gap. Keep these tables next to the SKILL.md that
# owns each envelope; test_finding_evidence.py guards the architecture one.
_ENVELOPES = {
    "code": ("What:", "Why it matters:", "Suggested fix:"),
    "architecture": (
        "What:",
        "Evidence:",
        "Why it matters:",
        "Suggested approach:",
        "Effort/Blast radius:",
    ),
}


def assert_finding_subfields(text: str, review_type: str = "code") -> None:
    """Assert each numbered finding carries its review type's required subfields.

    Only numbered items within the findings body (between the first severity
    marker and ### Summary) are checked.

    Args:
        text: The review output.
        review_type: "code" (What/Why it matters/Suggested fix) or
            "architecture" (adds Evidence and Effort/Blast radius, and uses
            Suggested approach). Defaults to "code".

    Raises:
        AssertionError: If any numbered finding is missing a required subfield.
        KeyError: If review_type is not a known envelope.
    """
    labels = _ENVELOPES[review_type]
    body = _findings_body(text)
    finding_matches = list(_FINDING_PATTERN.finditer(body))
    if not finding_matches:
        return

    for i, match in enumerate(finding_matches):
        start = match.start()
        end = finding_matches[i + 1].start() if i + 1 < len(finding_matches) else len(body)
        finding_text = body[start:end]
        finding_num = match.group(1)

        for label in labels:
            assert re.search(rf"\b{re.escape(label)}", finding_text, re.MULTILINE), (
                f"{review_type} finding {finding_num} is missing the "
                f"'{label}' subfield"
            )


def assert_summary_section(text: str) -> None:
    """Assert the response contains a ### Summary section.

    Raises:
        AssertionError: If no Summary section is found.
    """
    assert _SUMMARY_PATTERN.search(text), (
        "Response must contain a '### Summary' section. "
        f"Response ends with: ...{text[-300:]}"
    )


def assert_full_format_compliance(text: str, review_type: Optional[str] = None) -> None:
    """Run all five format assertions on a review response.

    Convenience composite for Phase 4 benchmarks that validate judge inputs.

    Args:
        text: The complete review response text.
        review_type: Optional "code" or "architecture". Narrows the title check
            AND selects the finding envelope — passing "architecture" here is
            what makes the composite check `Evidence:` and
            `Suggested approach:` rather than the code skill's labels. Left
            unset, the envelope check defaults to "code", so an architecture
            response must name its type to be checked correctly.
    """
    assert_title_format(text, review_type)
    assert_severity_ordering(text)
    assert_sequential_numbering(text)
    assert_finding_subfields(text, review_type or "code")
    assert_summary_section(text)
