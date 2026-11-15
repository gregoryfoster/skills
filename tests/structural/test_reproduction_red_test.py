"""A brief asks for the child's own reproduction, verbatim, as the first red test (#571).

A brief asks for tests of the *decided mechanism*, and a build can pass them
all and still miss the issue's own headline case. Three Wave 8 runs under
#516 saw it (orchestrating-issue-backlog's process log):

- **Set S, #533** (2026-11-02): the decision was "match the root as
  configured or resolved". The default root is already resolved, so the
  issue's own `/tmp` example still missed. Review caught it (CR 1738).
- **Set B, #550** (2026-11-03): the brief asked for the issue's own
  reproduction as a red test, and that test caught a decided restore that
  missed the headline case.
- **Set R, #566** (2026-11-06): the verbatim case was right, but not the whole
  race; review found a rollback of a commit already on origin (CR 1896). So
  the reproduction is the *first* red test, not the only one, and the review
  still looks for the rest of its class.

Both skills that brief an implementer carry the rule:
`coordinating-epics` in hand-off.md's "What the brief holds", and
`orchestrating-issue-backlog` in execution.md's Worker step 6. Each test
reads only the section that owns the line, so the rule cannot drift into
some other paragraph and still pass.
"""

import re

import pytest

from tests.utils.skill_loader import SKILLS_DIR

HAND_OFF = SKILLS_DIR / "coordinating-epics" / "references" / "hand-off.md"
EXECUTION = SKILLS_DIR / "orchestrating-issue-backlog" / "references" / "execution.md"


def _brief_holds() -> str:
    """hand-off.md's "What the brief holds" section, up to the next heading."""
    text = HAND_OFF.read_text()
    start = text.index("## What the brief holds")
    end = re.compile(r"\n## ").search(text, start + 1)
    return text[start : end.start() if end else len(text)]


def _worker_step_6() -> str:
    """execution.md's Worker step 6, up to step 7."""
    text = EXECUTION.read_text()
    start = text.index("6. **Implement with TDD**")
    end = re.compile(r"(?m)^7\. ").search(text, start)
    assert end, "Worker step 7 must follow step 6"
    return text[start : end.start()]


SECTIONS = {
    "coordinating-epics hand-off.md, What the brief holds": _brief_holds,
    "orchestrating-issue-backlog execution.md, Worker step 6": _worker_step_6,
}


@pytest.fixture(params=sorted(SECTIONS))
def section(request):
    return request.param, SECTIONS[request.param]()


def test_the_brief_asks_for_the_issues_own_reproduction_verbatim(section):
    """#571's own case: both skills ask for the verbatim reproduction test."""
    where, text = section
    flat = " ".join(text.split()).lower()
    assert "own reproduction, verbatim" in flat, (
        f"{where} must ask for the child's own reproduction, verbatim, as a "
        "red test (#571): a build passed the decided mechanism's tests and "
        "missed the issue's headline case (set S #533)."
    )
    assert "decided mechanism" in flat, (
        f"{where} must put the reproduction beside the tests of the decided "
        "mechanism, not in place of them (#571)."
    )


def test_the_reproduction_is_the_first_red_test_not_the_only_one(section):
    """The third sighting (set R #566): right, and not the whole class."""
    where, text = section
    flat = " ".join(text.split()).lower()
    assert "first red test" in flat, (
        f"{where} must make the reproduction the *first* red test (#571)."
    )
    assert "not the only one" in flat and "rest of its class" in flat, (
        f"{where} must say the reproduction is not the only red test, and "
        "that the review still looks for the rest of its class: #566's "
        "verbatim case was correct but not the whole race (CR 1896)."
    )


def test_the_rule_cites_its_sightings(section):
    """Each line cites its runs, as its neighbours do."""
    where, text = section
    missing = [n for n in ("#533", "#550", "#566") if n not in text]
    assert not missing, (
        f"{where} must cite the sightings the rule came from (set S #533, "
        f"set B #550, set R #566); missing {missing}."
    )
