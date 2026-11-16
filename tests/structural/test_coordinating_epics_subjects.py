"""coordinating-epics: a line's subject, and --account's ticked lines (#662).

`epic-edit.sh --account` passed when every open issue was mentioned anywhere
in the body, so a ticked line could carry an issue still open. Power-map's
2026-11-14 journal, finding A1: a line naming two issues was ticked when the
first closed, the second never did, and --account passed for three weeks.

The operator's decision (2026-11-15): a line's subject is the run of refs it
leads with, joined by "+", ",", "&" or "and"; --account warns about a ticked
line whose subject is still open (`ticked_open`), never refuses. A subject in
another repo isn't in the open set --account fetches, so it is listed
unchecked (`ticked_unchecked`) with one NOTE, and no read is spent on it. A
new or changed checkbox line with two or more subjects gets a WARNING
suggesting a line each (`multi_subject`). A fake gh stands in for GitHub.
"""

from __future__ import annotations

import importlib.util

import pytest

from tests.structural.coordinating_epics_rig import SCRIPTS, Rig, summary

REPO = "acme/widgets"
EPIC = 10

BODY = """\
# Burn-down

- **Last check-in:** 2026-10-01T09:00Z
- **Last issue seen:** #48

## Tier 1

- [x] #46 + #47 the pair, ticked when the first closed
- [ ] #45 still open · blocked by acme/gadgets#3

## Log

- 2026-10-01: created.
"""


def _load():
    spec = importlib.util.spec_from_file_location(
        "_epic_edit", SCRIPTS / "_epic_edit.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ee = _load()
H = REPO.lower()


def k(n: int, repo: str = H) -> str:
    return f"{repo}#{n}"


@pytest.mark.parametrize(
    "line, kind, subjects",
    [
        ("- [ ] #45 <title> · blocked by owner/repo#3", "item", [k(45)]),
        ("- [x] **#301** title", "item", [k(301)]),
        ("- [x] #46 + #47 title", "item", [k(46), k(47)]),
        ("- [x] #46+#47 title", "item", [k(46), k(47)]),
        ("- [x] **#46** + **#47** title", "item", [k(46), k(47)]),
        ("- [x] **#46 + #47** title", "item", [k(46), k(47)]),
        ("- [x] #46, #47 and #48 title", "item", [k(46), k(47), k(48)]),
        ("- [x] #46 & acme/gadgets#3 title", "item", [k(46), k(3, "acme/gadgets")]),
        ("- [x] ~~#46~~ + #47 title", "item", [k(46), k(47)]),
        ("- [x] 12. #46 + #47 title", "item", [k(46), k(47)]),
        ("1. [x] #46 and #47", "item", [k(46), k(47)]),
        (
            "- [x] [#46](https://github.com/acme/widgets/issues/46) +"
            " [#47](https://github.com/acme/widgets/issues/47) title",
            "item",
            [k(46), k(47)],
        ),
        (
            "- [x] **#586** title · [verified]"
            "(https://github.com/acme/widgets/issues/586#issuecomment-1)",
            "item",
            [k(586)],
        ),
        ("- [x] #46, title naming #47", "item", [k(46)]),
        ("- [x] #46: see #47", "item", [k(46)]),
        ("- [x] #46 andrew #47", "item", [k(46)]),
        ("- [x] #46 + `#47`", "item", [k(46)]),
        ("- [x] #45 &#183; verified", "item", [k(45)]),
        ("- [x] #45 &#xB7; verified", "item", [k(45)]),
        ("- [x] #46 &amp; #47 pair", "item", [k(46), k(47)]),
        ("- #46 + #47 · out of epic", "bullet", [k(46), k(47)]),
        ("| #46, #47 | when the SDK ships |", "row", [k(46), k(47)]),
    ],
    ids=[
        "issue-example-blocked-by",
        "bold",
        "plus",
        "plus-unspaced",
        "bold-each",
        "bold-run",
        "comma-and",
        "amp-cross-repo",
        "struck",
        "ordinal",
        "ordered-marker",
        "linked",
        "compaction-form",
        "comma-then-text",
        "colon",
        "and-is-a-word",
        "second-in-code",
        "decimal-entity",
        "hex-entity",
        "amp-entity",
        "bullet",
        "row",
    ],
)
def test_662_a_lines_subject_is_the_run_of_refs_it_leads_with(line, kind, subjects):
    """#662's Shape, each example verbatim, and compaction's own line form:
    refs later in the line are mentions, not subjects."""
    assert ee.line_subjects(line, REPO) == (kind, subjects)
    # The first subject is always the lead every other op finds the line by.
    assert ee.line_ref(line, REPO) == (kind, subjects[0])


@pytest.mark.parametrize(
    "line",
    [
        "- [x] `#46` + #47 title",
        "- [x] Ordered from acme/widgets#394, the backlog epic",
        "- [x] see #46",
        "plain #46 + #47",
    ],
    ids=["code-led", "pointer-line", "text-led", "not-a-line"],
)
def test_662_a_line_led_by_anything_but_a_ref_has_no_subject(line):
    """A pointer line names the other epic, not the child (#660's question 1)."""
    assert ee.line_subjects(line, REPO) is None


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path)
    r.issue(REPO, EPIC, body=BODY)
    r.issue(REPO, 45)
    r.issue(REPO, 46, state="closed")
    r.issue(REPO, 47)
    r.issue(REPO, 48, state="closed")
    res = r.edit(REPO, EPIC, [], "--adopt-live")
    assert res.returncode == 0, res.stderr
    return r


def test_662_a_ticked_lines_open_second_subject_is_named(rig):
    """#662's red test, power-map's case in miniature: #46 closed, #47 open, the
    pair ticked, --account set below both. It passed in silence; now it warns."""
    res = rig.edit(REPO, EPIC, [], "--account", "45")
    assert res.returncode == 0, res.stderr
    s = summary(res)
    assert s["unlisted"] == []
    assert s["ticked_open"] == [
        {
            "line": "- [x] #46 + #47 the pair, ticked when the first closed",
            "open": ["#47"],
        }
    ]
    assert "WARNING" in res.stderr and "#47" in res.stderr


def test_662_it_is_a_warning_and_the_write_goes_through(rig):
    ops = [{"op": "log", "text": "{today}: checked."}]
    res = rig.edit(REPO, EPIC, ops, "--account")
    assert res.returncode == 0, res.stderr
    assert "{today}: checked." not in rig.body(REPO, EPIC)
    assert "checked." in rig.body(REPO, EPIC)
    assert summary(res)["ticked_open"][0]["open"] == ["#47"]


def test_662_every_open_subject_counts_not_only_those_from_n_up(rig):
    """The open set --account fetches is the whole repo's (E:2886): N scopes
    'unlisted', not this check."""
    res = rig.edit(REPO, EPIC, [], "--account", "48")
    assert res.returncode == 0, res.stderr
    assert summary(res)["ticked_open"][0]["open"] == ["#47"]


def test_662_a_ticked_line_whose_subjects_are_closed_is_quiet(rig):
    rig.issue(REPO, 47, state="closed")
    res = rig.edit(REPO, EPIC, [], "--account")
    assert res.returncode == 0, res.stderr
    assert summary(res)["ticked_open"] == []
    assert "WARNING" not in res.stderr


def test_662_an_open_line_and_a_mention_on_a_ticked_line_are_not_subjects(rig):
    """The rejected shape: a ticked line's later refs are follow-ups, parks and
    blockers that are open on purpose."""
    rig.issue(REPO, 47, state="closed")
    ops = [
        {
            "op": "set-line",
            "ref": "#46",
            "line": "- [x] #46 + #47 the pair · follow-up #45, still open",
        }
    ]
    res = rig.edit(REPO, EPIC, ops, "--account")
    assert res.returncode == 0, res.stderr
    assert summary(res)["ticked_open"] == []


def test_662_a_ticked_line_in_a_fence_is_not_read(tmp_path):
    body = BODY.replace(
        "## Log", "```\n- [x] #45 an example, not a line\n```\n\n## Log"
    )
    r = Rig(tmp_path)
    r.issue(REPO, EPIC, body=body)
    for n, st in ((45, "open"), (46, "closed"), (47, "closed"), (48, "closed")):
        r.issue(REPO, n, state=st)
    assert r.edit(REPO, EPIC, [], "--adopt-live").returncode == 0
    res = r.edit(REPO, EPIC, [], "--account")
    assert res.returncode == 0, res.stderr
    assert summary(res)["ticked_open"] == []


def test_662_a_subject_in_another_repo_is_listed_unchecked(rig):
    """Question 1, as recommended: no read per foreign ref, and said so."""
    rig.issue(REPO, 47, state="closed")
    rig.issue(REPO, 45, state="closed")
    ops = [{"op": "tick", "ref": "#45"}]
    res = rig.edit(REPO, EPIC, ops, "--account")
    assert res.returncode == 0, res.stderr
    # A foreign ref later in the line is a mention, not a subject.
    assert summary(res)["ticked_unchecked"] == []
    calls_before = len(rig.load()["calls"])
    ops = [
        {
            "op": "add-line",
            "section": "Tier 1",
            "line": "- [x] acme/gadgets#3 upstream fix",
        }
    ]
    res = rig.edit(REPO, EPIC, ops, "--account")
    assert res.returncode == 0, res.stderr
    s = summary(res)
    assert s["ticked_unchecked"] == ["acme/gadgets#3"]
    assert s["ticked_open"] == []
    assert res.stderr.count("NOTE") == 1 and "acme/gadgets#3" in res.stderr
    calls = rig.load()["calls"][calls_before:]
    assert calls and not [c for c in calls if "acme/gadgets" in " ".join(c)]


def test_662_no_account_no_check(rig):
    res = rig.edit(REPO, EPIC, [], "--dry-run")
    assert res.returncode == 0, res.stderr
    assert "ticked_open" not in summary(res)


def test_662_a_new_line_with_two_subjects_is_nudged_toward_one_each(rig):
    ops = [
        {"op": "add-line", "section": "Tier 1", "line": "- [ ] #48 + #45 another pair"}
    ]
    res = rig.edit(REPO, EPIC, ops)
    assert res.returncode == 0, res.stderr
    assert summary(res)["multi_subject"] == ["- [ ] #48 + #45 another pair"]
    assert "WARNING" in res.stderr and "A line each" in res.stderr


def test_662_an_unchanged_pair_isnt_nudged_again(rig):
    """Existing bodies stay valid: only a new or changed line is read."""
    res = rig.edit(REPO, EPIC, [{"op": "tick", "ref": "#45"}])
    assert res.returncode == 0, res.stderr
    assert "multi_subject" not in summary(res)
    assert "A line each" not in res.stderr


def test_662_lint_all_names_every_pair(rig):
    res = rig.edit(REPO, EPIC, [], "--lint-all", "--dry-run")
    assert res.returncode == 0, res.stderr
    assert summary(res)["multi_subject"] == [
        "- [x] #46 + #47 the pair, ticked when the first closed"
    ]
