"""coordinating-epics: three places epic-edit.sh wrote or said the wrong thing.

Each is a script suggestion from CannObserv/processor#84's journal (#670), a
23-day burn-down that hit it by hand:

- F8: the `log` op wrote "- - text" when the text itself began with "- ".
- F9: set-line refused a line with "doesn't lead with #N" when the line did
  start with #N and only its list marker was missing.
- F10: add-line's "section" needed the whole heading, and the refusal didn't
  say which headings there were.

New behaviour is additive: an ops file that worked keeps working, and no
refusal is new. A fake gh stands in for GitHub.
"""

from __future__ import annotations

import pytest

from tests.structural.coordinating_epics_rig import Rig, summary

REPO = "acme/widgets"
EPIC = 10

BODY = """\
# Burn-down

- **Last check-in:** 2026-10-01T09:00Z
- **Last issue seen:** #14

## Tier 1 — bugs

- [ ] #11 first thing
- [ ] #12 second thing

## Tier 10 — later

- [ ] #13 third thing

## Logistics

Who runs what.

## Log

- 2026-10-01: created.
"""


@pytest.fixture
def adopted(tmp_path):
    r = Rig(tmp_path)
    r.issue(REPO, EPIC, body=BODY)
    for n in (11, 12, 13, 14):
        r.issue(REPO, n)
    res = r.edit(REPO, EPIC, [], "--adopt-live")
    assert res.returncode == 0, res.stderr
    return r


# ---------------------------------------------------------------- F8: log


@pytest.mark.parametrize(
    "text",
    [
        "- 2026-10-02: #11 closed.",
        "2026-10-02: #11 closed.",
        "  -   2026-10-02: #11 closed.",
    ],
    ids=["its-own-bullet", "no-bullet", "bullet-and-spaces"],
)
def test_670_f8_a_log_text_with_its_own_bullet_gets_one(adopted, text):
    res = adopted.edit(REPO, EPIC, [{"op": "log", "text": text}])
    assert res.returncode == 0, res.stderr
    body = adopted.body(REPO, EPIC)
    assert "\n- 2026-10-02: #11 closed.\n" in body + "\n"
    assert "- - " not in body


def test_670_f8_the_same_entry_with_and_without_its_bullet_is_logged_once(adopted):
    for text in ("2026-10-02: #11 closed.", "- 2026-10-02: #11 closed."):
        res = adopted.edit(REPO, EPIC, [{"op": "log", "text": text}])
        assert res.returncode == 0, res.stderr
    assert adopted.body(REPO, EPIC).count("2026-10-02: #11 closed.") == 1
    assert any("log entry already present" in n for n in summary(res)["notes"])


def test_670_f8_only_one_bullet_is_taken(adopted):
    """A text that is itself a doubled bullet keeps its second: the op takes
    the one it would have added, and guesses no further."""
    res = adopted.edit(REPO, EPIC, [{"op": "log", "text": "- - 2026-10-02: x."}])
    assert res.returncode == 0, res.stderr
    assert "\n- - 2026-10-02: x.\n" in adopted.body(REPO, EPIC) + "\n"
