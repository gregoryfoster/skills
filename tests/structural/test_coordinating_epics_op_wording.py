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


# ---------------------------------------------------------------- F9: set-line


@pytest.mark.parametrize(
    "line, says",
    [
        (
            "#12 second thing, reworded",
            "it starts with #12, but isn't a checklist item",
        ),
        ("[ ] #12 second thing", "it starts with #12, but isn't a checklist item"),
        ("- [ ] #11 oops", "it leads with #11"),
        ("- [ ] acme/gadgets#12 oops", "it leads with acme/gadgets#12"),
        ("- [ ] see #12 for the rest", "its first token isn't a ref"),
        ("- [ ] `#12` in code", "its first token isn't a ref"),
        ("- [ ] no ref at all", "its first token isn't a ref"),
        ("#11 another ref, and no marker", "it starts with #11, but isn't"),
    ],
    ids=[
        "no-marker",
        "a-box-and-no-marker",
        "another-ref",
        "another-repos-ref",
        "text-before-the-ref",
        "the-ref-in-code",
        "no-ref",
        "another-ref-and-no-marker",
    ],
)
def test_670_f9_set_lines_refusal_says_what_is_missing(adopted, line, says):
    """The refusal was "the new line doesn't lead with #12" for a line that
    began with #12. Its first words stay, for anything that matches on them."""
    res = adopted.edit(REPO, EPIC, [{"op": "set-line", "ref": "#12", "line": line}])
    assert res.returncode == 3, res.stderr
    assert "the new line doesn't lead with #12: " in res.stderr
    assert says in res.stderr, res.stderr


def test_670_f9_a_ref_no_line_holds_is_answered_with_the_forms_that_lead(adopted):
    """Not only a box: a bullet and a table row lead too."""
    ops = [{"op": "set-line", "ref": "#12", "line": "#12 second thing"}]
    res = adopted.edit(REPO, EPIC, ops)
    for form in ('"- [ ] #12"', '"- #12"', '"| #12"'):
        assert form in res.stderr, res.stderr


@pytest.mark.parametrize(
    "line",
    ["- [x] #12 second thing, done", "- #12 second thing, a bullet now"],
    ids=["item", "bullet"],
)
def test_670_f9_a_line_that_leads_is_still_set(adopted, line):
    res = adopted.edit(REPO, EPIC, [{"op": "set-line", "ref": "#12", "line": line}])
    assert res.returncode == 0, res.stderr
    assert line in adopted.body(REPO, EPIC)


# ---------------------------------------------------------------- F9: add-line


def test_670_f9_add_line_notes_a_ref_no_line_holds_and_still_adds_it(adopted):
    """add-line never refused this, and doesn't now: the line goes in as the
    text it is. The summary says no op will find it by its ref."""
    ops = [{"op": "add-line", "section": "Tier 1 — bugs", "line": "#14 a follow-up"}]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 0, res.stderr
    assert "\n#14 a follow-up\n" in adopted.body(REPO, EPIC)
    notes = [n for n in summary(res)["notes"] if "added as text" in n]
    assert len(notes) == 1 and "starts with #14" in notes[0], summary(res)["notes"]


@pytest.mark.parametrize(
    "line",
    ["- [ ] #14 a follow-up", "a plain note", "see #14 for the rest"],
    ids=["a-ref-led-item", "plain-text", "a-ref-later-in-the-text"],
)
def test_670_f9_add_line_notes_nothing_for_any_other_line(adopted, line):
    ops = [{"op": "add-line", "section": "Tier 1 — bugs", "line": line}]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 0, res.stderr
    assert not [n for n in summary(res)["notes"] if "added as text" in n]
