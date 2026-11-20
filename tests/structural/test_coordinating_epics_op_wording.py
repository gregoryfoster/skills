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


@pytest.mark.parametrize(
    "texts, kept",
    [
        (
            ["- #11 closed.", "- #11 reopened."],
            ["- - #11 closed.", "- - #11 reopened."],
        ),
        (["- [ ] #14 a follow-up"], ["- - [ ] #14 a follow-up"]),
        (["- [x] done by hand"], ["- - [x] done by hand"]),
        (["- **#12** verified."], ["- - **#12** verified."]),
    ],
    ids=["a-ref-twice", "a-box-and-a-ref", "a-box", "a-bold-ref"],
)
def test_cr2415_a_bullet_before_a_ref_or_a_box_is_kept_as_it_was(adopted, texts, kept):
    """CR 2415: without its own "- " such a text is a line led by a ref, or a
    checkbox, and the editor's other guards refuse it: two bullets led by one
    ref, a box the counts don't expect. Written doubled, as before F8, each
    was accepted, so each still is, and the summary says why."""
    ops = [{"op": "log", "text": text} for text in texts]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 0, res.stderr
    body = adopted.body(REPO, EPIC)
    for line in kept:
        assert f"\n{line}\n" in body + "\n", body
    notes = [n for n in summary(res)["notes"] if 'own "- "' in n]
    assert len(notes) == len(texts), summary(res)["notes"]


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


# ---------------------------------------------------------------- F10: sections


def test_670_f10_add_line_takes_the_one_heading_its_section_starts(adopted):
    """--help's own example is "section": "Tier 2", and the template's heading
    is "## Tier 2 — <name>". "Tier 1" is "Tier 1 — bugs", never "Tier 10"."""
    ops = [{"op": "add-line", "section": "Tier 1", "line": "- [ ] #14 a follow-up"}]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 0, res.stderr
    body = adopted.body(REPO, EPIC)
    assert "- [ ] #12 second thing\n- [ ] #14 a follow-up\n\n## Tier 10" in body
    notes = [n for n in summary(res)["notes"] if "Tier 1 — bugs" in n]
    assert len(notes) == 1 and "'Tier 1'" in notes[0], summary(res)["notes"]


def test_670_f10_a_heading_given_in_full_is_taken_with_no_note(adopted):
    ops = [
        {"op": "add-line", "section": "Tier 1 — bugs", "line": "- [ ] #14 follow-up"}
    ]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 0, res.stderr
    assert not [n for n in summary(res)["notes"] if "heading" in n]


def test_670_f10_the_heading_itself_outranks_one_it_starts(adopted):
    """ "Log" is the Log section, though "Logistics" starts with it."""
    ops = [{"op": "add-line", "section": "Log", "line": "- 2026-10-02: by hand."}]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 0, res.stderr
    assert adopted.body(REPO, EPIC).rstrip().endswith("- 2026-10-02: by hand.")


@pytest.mark.parametrize(
    "section, named, unnamed",
    [
        ("Tier", ["'Tier 1 — bugs'", "'Tier 10 — later'"], ["'Logistics'"]),
        ("Logi", ["'Logistics'"], ["'Tier 1 — bugs'"]),
        ("Parked", ["'Tier 1 — bugs'", "'Logistics'", "'Log'"], []),
    ],
    ids=["two-start-with-it", "one-starts-with-it-mid-word", "none-starts-with-it"],
)
def test_670_f10_a_section_refusal_names_the_headings(adopted, section, named, unnamed):
    """Two candidates, or one that only shares a word's first letters, is a
    guess the op doesn't make. The refusal lists what there is to choose."""
    ops = [{"op": "add-line", "section": section, "line": "- [ ] #14 a follow-up"}]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 3, res.stderr
    assert f"no section headed {section!r}" in res.stderr
    for heading in named:
        assert heading in res.stderr, res.stderr
    for heading in unnamed:
        assert heading not in res.stderr, res.stderr
    assert "#14" not in adopted.body(REPO, EPIC).split("## Tier 1")[1]


@pytest.mark.parametrize(
    "op",
    [
        {"op": "replace-section", "heading": "Tier 1", "text": "- [ ] #11 only"},
        {"op": "rename-section", "heading": "Tier 1", "to": "Tier 1 — now"},
        {"op": "add-section", "heading": "New", "text": "x", "before": "Tier 1"},
    ],
    ids=["replace-section", "rename-section", "add-section-before"],
)
def test_670_f10_only_add_lines_section_takes_a_prefix(adopted, op):
    """A prefix in section_span itself would let replace-section replace a
    section the op didn't name. Every other op wants the heading in full, and
    its refusal now names the one meant."""
    before = adopted.body(REPO, EPIC)
    res = adopted.edit(REPO, EPIC, [op])
    assert res.returncode == 3, res.stderr
    assert "no section headed 'Tier 1'" in res.stderr
    assert "'Tier 1 — bugs'" in res.stderr
    assert adopted.body(REPO, EPIC) == before


def test_670_f10_the_log_op_never_writes_into_a_section_log_only_starts(tmp_path):
    r = Rig(tmp_path)
    no_log = BODY.replace("\n## Log\n\n- 2026-10-01: created.\n", "")
    assert "## Log\n" not in no_log and "## Logistics\n" in no_log
    r.issue(REPO, EPIC, body=no_log)
    assert r.edit(REPO, EPIC, [], "--adopt-live").returncode == 0
    res = r.edit(REPO, EPIC, [{"op": "log", "text": "2026-10-02: a check-in."}])
    assert res.returncode == 3, res.stderr
    assert "no section headed 'Log'" in res.stderr and "'Logistics'" in res.stderr
    assert "a check-in" not in r.body(REPO, EPIC)
