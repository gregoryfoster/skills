"""coordinating-epics: epic-edit.sh refuses every write that once damaged an epic.

Each test is one failure a coordinator thread hit by hand (gregoryfoster/skills#348):
the body blanked by an empty file (archiver#300 finding 2), a failed assert that
still re-posted (third run 34, processor#24 F101), a foreign edit overwritten
(address-validator#272 47), a tick made elsewhere breaking the anchor (broker#80
147), counts typed by hand (seventh run 92), a wrong cross-repo link (watcher#348
F61), a fabricated comment id (processor#24 F134), and a write the exit code
called good (address-validator#272 48). A fake gh stands in for GitHub.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re

import pytest

from tests.structural.coordinating_epics_rig import SCRIPTS, Rig, summary

REPO = "acme/widgets"
EPIC = 10

BODY = """\
# Burn-down

- **Last check-in:** 2026-10-01T09:00Z
- **Last issue seen:** #14
- **Next:** #12

## Tier 1

- [ ] #11 first thing
- [ ] #12 second thing
- [ ] acme/gadgets#3 upstream fix

## Parked

| Issue | Trigger |
|---|---|
| #13 | when the SDK ships |

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


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path)
    r.issue(REPO, EPIC, body=BODY)
    for n in (11, 12, 13, 14):
        r.issue(REPO, n)
    return r


@pytest.fixture
def adopted(rig):
    res = rig.edit(REPO, EPIC, [], "--adopt-live")
    assert res.returncode == 0, res.stderr
    return rig


# ---------------------------------------------------------------- baseline


def test_no_baseline_is_refused_with_the_way_forward(rig):
    res = rig.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 3
    assert "--adopt-live" in res.stderr
    assert rig.body(REPO, EPIC) == BODY


def test_adopting_saves_the_baseline_and_writes_nothing(adopted):
    assert (adopted.state_dir / "acme" / "widgets" / "10" / "last-written.md").is_file()
    assert "patches" not in adopted.load()


def test_lint_all_checks_a_created_body_an_empty_edit_never_touches(rig):
    """CR 291: the creation chain adopts with no ops, so only --lint-all reads the body."""
    bad = BODY.replace(
        "- [ ] #12 second thing", "- [ ] #12 after SUB2, see watcher#348"
    )
    rig.issue(REPO, EPIC, body=bad)
    res = rig.edit(REPO, EPIC, [], "--adopt-live", "--lint-all")
    assert res.returncode == 3, res.stderr
    assert "SUB2" in res.stderr and "watcher#348" in res.stderr
    assert not (rig.state_dir / "acme" / "widgets" / "10" / "last-written.md").exists()
    fix = [{"op": "set-line", "ref": "#12", "line": "- [ ] #12 after #13"}]
    res = rig.edit(REPO, EPIC, fix, "--adopt-live", "--lint-all")
    assert res.returncode == 0, res.stderr
    assert "- [ ] #12 after #13" in rig.body(REPO, EPIC)


def test_the_baseline_is_found_whatever_the_repos_casing(adopted):
    """CR 299: GitHub names are case-insensitive; a casing slip isn't "no baseline"."""
    res = adopted.edit("Acme/Widgets", EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 0, res.stderr


def test_repos_that_flatten_alike_keep_separate_baselines(rig):
    """CR 299: "a-b/c" and "a/b-c" were one directory."""
    for repo in ("a-b/c", "a/b-c"):
        rig.issue(repo, 1, body=f"- [ ] #2 in {repo}")
    assert rig.edit("a-b/c", 1, [], "--adopt-live").returncode == 0
    res = rig.edit("a/b-c", 1, [])
    assert res.returncode == 3 and "no baseline" in res.stderr


def test_an_empty_live_body_is_refused(rig):
    rig.issue(REPO, EPIC, body="")
    res = rig.edit(REPO, EPIC, [], "--adopt-live")
    assert res.returncode == 3
    assert "the live body is empty" in res.stderr


# ---------------------------------------------------------------- ticks


def test_tick_writes_reads_back_and_moves_the_baseline(adopted):
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 0, res.stderr
    s = summary(res)
    assert s["written"] and s["readback"] == "matches"
    assert s["counts_before"] == {"open": 3, "done": 0}
    assert s["counts_after"] == {"open": 2, "done": 1}
    assert "- [x] #11 first thing" in adopted.body(REPO, EPIC)
    base = (
        adopted.state_dir / "acme" / "widgets" / "10" / "last-written.md"
    ).read_text()
    assert "- [x] #11" in base


def test_tick_is_idempotent(adopted):
    adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 0
    s = summary(res)
    assert s.get("unchanged") and not s["written"]
    assert len(adopted.load()["patches"]) == 1


def test_a_cross_repo_ref_is_its_own_line(adopted):
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "acme/gadgets#3"}])
    assert res.returncode == 0, res.stderr
    assert "- [x] acme/gadgets#3" in adopted.body(REPO, EPIC)
    assert "- [ ] #11" in adopted.body(REPO, EPIC)


def test_a_missing_anchor_writes_nothing(adopted):
    res = adopted.edit(
        REPO, EPIC, [{"op": "tick", "ref": "#11"}, {"op": "tick", "ref": "#99"}]
    )
    assert res.returncode == 3
    assert "#99" in res.stderr or "acme/widgets#99" in res.stderr
    assert "patches" not in adopted.load()


def test_tick_wants_a_checklist_item_not_a_table_row(adopted):
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#13"}])
    assert res.returncode == 3
    assert "checklist item" in res.stderr


# ---------------------------------------------------------------- foreign edits


def test_a_foreign_tick_is_a_claim_until_accepted(adopted):
    adopted.issue(REPO, EPIC, body=BODY.replace("- [ ] #12", "- [x] #12"))
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 3
    assert "acme/widgets#12" in res.stderr and "--accept-ticks" in res.stderr
    res = adopted.edit(
        REPO, EPIC, [{"op": "tick", "ref": "#11"}], "--accept-ticks", "#12"
    )
    assert res.returncode == 0, res.stderr
    assert summary(res)["foreign_ticks"] == ["acme/widgets#12"]
    body = adopted.body(REPO, EPIC)
    assert "- [x] #11" in body and "- [x] #12" in body


def test_an_uppercase_foreign_tick_is_still_a_tick(adopted):
    """CR 254: GitHub's own UI writes [x], but [X] is a tick too."""
    adopted.issue(REPO, EPIC, body=BODY.replace("- [ ] #12", "- [X] #12"))
    res = adopted.edit(
        REPO, EPIC, [{"op": "tick", "ref": "#11"}], "--accept-ticks", "#12"
    )
    assert res.returncode == 0, res.stderr
    assert summary(res)["foreign_ticks"] == ["acme/widgets#12"]


def test_accepting_a_tick_with_nothing_to_write_still_moves_the_baseline(adopted):
    """CR 295: or the same tick is a foreign claim again on every later run."""
    adopted.issue(REPO, EPIC, body=BODY.replace("- [ ] #12", "- [x] #12"))
    res = adopted.edit(REPO, EPIC, [], "--accept-ticks", "#12")
    assert res.returncode == 0 and summary(res).get("unchanged"), res.stderr
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 0, res.stderr


def test_a_foreign_tick_with_a_reworded_line_is_an_edit_not_a_tick(adopted):
    """CR 295 (for 254): only a flip on an otherwise unchanged line is a tick."""
    adopted.issue(
        REPO, EPIC, body=BODY.replace("- [ ] #12 second thing", "- [x] #12 reworded")
    )
    res = adopted.edit(
        REPO, EPIC, [{"op": "tick", "ref": "#11"}], "--accept-ticks", "#12"
    )
    assert res.returncode == 3 and "beyond box ticks" in res.stderr
    assert "+ - [x] #12 reworded" in res.stderr


def test_a_foreign_edit_beyond_ticks_is_refused_with_the_diff(adopted):
    adopted.issue(
        REPO, EPIC, body=BODY.replace("second thing", "second thing, rescoped")
    )
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 3
    assert "+ - [ ] #12 second thing, rescoped" in res.stderr
    assert "patches" not in adopted.load()


def test_a_hard_line_break_survives_a_write(rig):
    """CR 244: the write is the live body with the ops applied, not a normalized copy."""
    rig.issue(
        REPO,
        EPIC,
        body=BODY.replace("# Burn-down\n", "# Burn-down\n\nIntro  \nsecond line\n"),
    )
    assert rig.edit(REPO, EPIC, [], "--adopt-live").returncode == 0
    res = rig.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 0, res.stderr
    body = rig.body(REPO, EPIC)
    assert "Intro  \nsecond line" in body and "- [x] #11" in body


def test_trailing_whitespace_and_crlf_are_not_foreign_edits(adopted):
    adopted.issue(REPO, EPIC, body=BODY.rstrip("\n").replace("\n", "  \r\n"))
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 0, res.stderr


# ---------------------------------------------------------------- operations


def test_header_injects_now(adopted):
    res = adopted.edit(
        REPO, EPIC, [{"op": "header", "field": "Last check-in", "value": "{now}"}]
    )
    assert res.returncode == 0, res.stderr
    assert re.search(
        r"- \*\*Last check-in:\*\* \d{4}-\d\d-\d\dT\d\d:\d\dZ$",
        adopted.body(REPO, EPIC),
        re.M,
    )


def test_the_header_takes_the_scans_time_and_watermark(adopted):
    """CR 248: Last check-in is when the scan looked, not when the write happened."""
    report = adopted.tmp / "scan.json"
    report.write_text(
        json.dumps(
            {
                "repo": REPO,
                "epic": EPIC,
                "now": "2026-10-14T18:03:27Z",
                "max_number": 13,
                "new_numbers": [],
                "updated_since": [],
            }
        )
    )
    ops = [
        {"op": "header", "field": "Last check-in", "value": "{checked}"},
        {"op": "header", "field": "Last issue seen", "value": "{last_seen}"},
    ]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 1 and "needs --scan" in res.stderr
    res = adopted.edit(REPO, EPIC, ops, "--scan", str(report))
    assert res.returncode == 0, res.stderr
    body = adopted.body(REPO, EPIC)
    assert "- **Last check-in:** 2026-10-14T18:03:27Z" in body
    assert "- **Last issue seen:** #13" in body
    flagged = adopted.tmp / "bool.json"
    flagged.write_text(
        json.dumps(
            {
                "repo": REPO,
                "epic": EPIC,
                "now": "2026-10-14T18:03:27Z",
                "max_number": True,
            }
        )
    )
    res = adopted.edit(REPO, EPIC, ops, "--scan", str(flagged))
    assert res.returncode == 1 and "max_number" in res.stderr  # CR 270
    other = adopted.tmp / "other.json"
    other.write_text(
        json.dumps(
            {"repo": REPO, "epic": 99, "now": "2026-10-14T18:03:27Z", "max_number": 1}
        )
    )
    res = adopted.edit(REPO, EPIC, ops, "--scan", str(other))
    assert res.returncode == 1 and "not a scan.sh report on this epic" in res.stderr


def test_an_empty_header_value_is_idempotent(adopted):
    """CR 251: the line is written without a trailing space, and once."""
    ops = [{"op": "header", "field": "Next", "value": ""}]
    assert summary(adopted.edit(REPO, EPIC, ops))["written"]
    assert "- **Next:**\n" in adopted.body(REPO, EPIC)
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 0 and summary(res).get("unchanged")


def test_a_scans_new_issues_must_be_accounted_for_in_the_write(adopted):
    """CR 265: the report moves the watermark past them, so each is slotted or logged."""
    report = adopted.tmp / "scan.json"
    report.write_text(
        json.dumps(
            {
                "repo": REPO,
                "epic": EPIC,
                "now": "2026-10-14T18:03:27Z",
                "max_number": 14,
                "new_numbers": [
                    {"number": 14, "kind": "issue"},
                    {"number": 13, "kind": "pr"},
                ],
                "updated_since": [],
            }
        )
    )
    header = [{"op": "header", "field": "Last issue seen", "value": "{last_seen}"}]
    res = adopted.edit(REPO, EPIC, header, "--scan", str(report))
    assert res.returncode == 3 and "doesn't mention: #14" in res.stderr
    logged = header + [
        {"op": "log", "text": "{today}: 1 new (#14, out of epic). Next: #12."}
    ]
    res = adopted.edit(REPO, EPIC, logged, "--scan", str(report))
    assert res.returncode == 0, res.stderr


def _report(adopted, **fields):
    report = adopted.tmp / "scan.json"
    base = {
        "repo": REPO,
        "epic": EPIC,
        "now": "2026-10-14T18:03:27Z",
        "max_number": 14,
        "updated_since": [],
    }
    report.write_text(json.dumps({**base, **fields}))
    return str(report)


def test_an_issue_only_updated_since_shows_still_needs_accounting(adopted):
    """CR 276: a transfer keeps its old creation date, so the number walk can miss it."""
    report = _report(
        adopted,
        cursors={"watermark": 13},
        new_numbers=[],
        updated_since=[
            {"number": 14, "kind": "issue"},
            {"number": 12, "kind": "issue"},
        ],
    )
    ops = [{"op": "header", "field": "Last issue seen", "value": "{last_seen}"}]
    res = adopted.edit(REPO, EPIC, ops, "--scan", report)
    assert res.returncode == 3 and "doesn't mention: #14" in res.stderr
    # #5, below the watermark and nowhere in the body, needs no mention (CR 295).
    report = _report(
        adopted,
        cursors={"watermark": 13},
        new_numbers=[],
        updated_since=[{"number": 5, "kind": "issue"}, {"number": 14, "kind": "issue"}],
    )
    ops.append({"op": "log", "text": "{today}: #14 out of epic."})
    res = adopted.edit(REPO, EPIC, ops, "--scan", report)
    assert res.returncode == 0, res.stderr


def test_with_no_watermark_an_old_issues_update_needs_no_mention(adopted):
    """CR 287: {last_seen} is refused, so nothing moves past #5; {checked} alone is fine."""
    report = _report(
        adopted,
        cursors={"watermark": None},
        new_numbers=None,
        updated_since=[{"number": 5, "kind": "issue"}],
    )
    ops = [{"op": "header", "field": "Last check-in", "value": "{checked}"}]
    res = adopted.edit(REPO, EPIC, ops, "--scan", report)
    assert res.returncode == 0, res.stderr


@pytest.mark.parametrize(
    "op",
    [
        {"op": "add-line", "section": "Tier 1", "line": "- **#14:** new follow-up"},
        {"op": "log", "text": "**{today}:** #14 out of epic"},
    ],
    ids=["bold-tier-line", "bold-log-line"],
)
def test_a_bold_led_line_still_mentions_its_ref(adopted, op):
    """CR 278: only the header's cursor lines are excluded."""
    report = _report(adopted, new_numbers=[{"number": 14, "kind": "issue"}])
    res = adopted.edit(REPO, EPIC, [op], "--scan", report)
    assert res.returncode == 0, res.stderr


@pytest.mark.parametrize("rows", [[15], "15", [{"number": "15"}]])
def test_a_malformed_report_row_is_a_usage_error(adopted, rows):
    """CR 282."""
    report = _report(adopted, new_numbers=rows)
    res = adopted.edit(REPO, EPIC, [], "--scan", report)
    assert res.returncode == 1 and "Traceback" not in res.stderr, res.stderr


@pytest.mark.parametrize(
    "cursors", [{"watermark": "13"}, {"watermark": True}, ["x"], "abc"]
)
def test_malformed_report_cursors_are_a_usage_error(adopted, cursors):
    """CR 294."""
    report = _report(adopted, cursors=cursors, new_numbers=[])
    res = adopted.edit(REPO, EPIC, [], "--scan", report)
    assert res.returncode == 1 and "cursors must be" in res.stderr, res.stderr
    assert "Traceback" not in res.stderr


@pytest.mark.parametrize(
    "row",
    [{"number": 14, "kind": "pr"}, {"number": EPIC, "kind": "issue"}],
    ids=["a-pr", "the-epic-itself"],
)
def test_prs_and_the_epic_need_no_mention(adopted, row):
    """CR 285 (for 265): a PR isn't an issue to slot, and the epic is the body itself."""
    report = _report(adopted, new_numbers=[row])
    res = adopted.edit(
        REPO, EPIC, [{"op": "log", "text": "{today}: nothing new."}], "--scan", report
    )
    assert res.returncode == 0, res.stderr


def test_last_seen_needs_a_report_that_scanned_numbers(adopted):
    """CR 276: with new_numbers null, {last_seen} would set a watermark over unseen issues."""
    report = _report(adopted, new_numbers=None)
    ops = [{"op": "header", "field": "Last issue seen", "value": "{last_seen}"}]
    res = adopted.edit(REPO, EPIC, ops, "--scan", report)
    assert res.returncode == 1 and "scanned no numbers" in res.stderr


LEGACY = """\
Burn down the widget backlog.

## Tier 1

- [ ] #11 first thing
"""


def test_an_adopted_epic_comes_onto_the_template_without_a_hand_edit(rig):
    """CR 292: header adds a missing cursor line; add-section adds a section."""
    rig.issue(REPO, EPIC, body=LEGACY)
    ops = [
        {"op": "header", "field": "last check-in", "value": "{now}"},
        {"op": "header", "field": "Last issue seen", "value": "#14"},
        {
            "op": "add-section",
            "heading": "Order",
            "text": "Bugs first.",
            "before": "Tier 1",
        },
        {"op": "add-section", "heading": "Log", "text": "- [ ] #12 adopted"},
        {"op": "log", "text": "{today}: adopted."},
    ]
    res = rig.edit(REPO, EPIC, ops, "--adopt-live")
    assert res.returncode == 0, res.stderr
    assert summary(res)["counts_after"] == {"open": 2, "done": 0}
    body = rig.body(REPO, EPIC)
    assert re.fullmatch(
        r"Burn down the widget backlog\.\n\n"
        r"- \*\*Last check-in:\*\* \d{4}-\d\d-\d\dT\d\d:\d\dZ\n"
        r"- \*\*Last issue seen:\*\* #14\n\n"
        r"## Order\n\nBugs first\.\n\n## Tier 1\n\n- \[ \] #11 first thing\n\n"
        r"## Log\n\n- \[ \] #12 adopted\n- \d{4}-\d\d-\d\d: adopted\.\n",
        body,
    ), body
    again = [ops[1], ops[2]]
    res = rig.edit(REPO, EPIC, again)
    assert res.returncode == 0 and summary(res).get("unchanged"), res.stderr
    clash = [{"op": "add-section", "heading": "Order", "text": "Size first."}]
    assert rig.edit(REPO, EPIC, clash).returncode == 3


def test_add_section_before_a_subsection_takes_its_level(rig):
    """CR 305: a "##" before "### Tier 2" would end "## Tiers" there."""
    body = "## Tiers\n\n### Tier 1\n\n- [ ] #11 a\n\n### Tier 2\n\n- [ ] #12 b\n\n## Log\n\n- x\n"
    rig.issue(REPO, EPIC, body=body)
    ops = [
        {
            "op": "add-section",
            "heading": "Tier 1b",
            "text": "- [ ] #13 c",
            "before": "Tier 2",
        }
    ]
    res = rig.edit(REPO, EPIC, ops, "--adopt-live")
    assert res.returncode == 0, res.stderr
    assert "### Tier 1b\n\n- [ ] #13 c\n\n### Tier 2" in rig.body(REPO, EPIC)


@pytest.mark.parametrize(
    "body, heading",
    [
        ("# Tier 1\n\n- [ ] #11 a\n\n# Parked\n\n- #13 later\n", "# Log"),
        (BODY, "## Notes"),
        ("Intro only.\n", "## Notes"),
    ],
    ids=["top-level-sections", "title-over-sections", "no-headings"],
)
def test_add_section_at_the_end_takes_the_sections_level(rig, body, heading):
    """CR 305: a "## Log" after "# Parked" would be Parked's, and replacing Parked deletes it."""
    rig.issue(REPO, EPIC, body=body)
    title = heading.lstrip("# ")
    ops = [{"op": "add-section", "heading": title, "text": "- 2026-10-14: adopted."}]
    res = rig.edit(REPO, EPIC, ops, "--adopt-live")
    assert res.returncode == 0, res.stderr
    assert rig.body(REPO, EPIC).endswith(f"\n{heading}\n\n- 2026-10-14: adopted.\n")


@pytest.mark.parametrize(
    "op",
    [
        {"op": "add-section", "heading": "Tier 2", "text": "- [ ] #11 copied"},
        {"op": "replace-section", "heading": "Log", "text": "- [ ] #11 copied"},
    ],
    ids=["add-section", "replace-section"],
)
def test_a_whole_section_cant_give_a_ref_a_second_line(adopted, op):
    """CR 307: two item lines for #11 make every later op on it ambiguous."""
    res = adopted.edit(REPO, EPIC, [op])
    assert res.returncode == 3 and "more than one line" in res.stderr, res.stderr
    assert "patches" not in adopted.load()


def test_moving_a_line_between_sections_in_one_call_is_fine(adopted):
    """CR 307: the count is compared, so a move keeps one line."""
    ops = [
        {
            "op": "replace-section",
            "heading": "Tier 1",
            "text": "- [ ] #12 second thing",
        },
        {"op": "add-section", "heading": "Tier 2", "text": "- [ ] #11 first thing"},
    ]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 0, res.stderr


@pytest.mark.parametrize(
    "body, want",
    [
        (
            BODY,
            "- **Next:** #12\n- **Last verified SHA:** abc1234\n\n## Tier 1",
        ),
        (
            "- **Next:** #12\n  - brief posted\n\n## Tier 1\n\n- [ ] #12 b\n",
            "- **Next:** #12\n  - brief posted\n- **Last verified SHA:** abc1234\n\n## Tier 1",
        ),
        (
            "**Goal:** ship\nthe widgets.\n\n## Tier 1\n\n- [ ] #12 b\n",
            "**Goal:** ship\nthe widgets.\n\n- **Last verified SHA:** abc1234\n\n## Tier 1",
        ),
        (
            "# Burn-down\n\nIntro.\n\n## Tier 1\n\n- [ ] #12 b\n",
            "# Burn-down\n\nIntro.\n\n- **Last verified SHA:** abc1234\n\n## Tier 1",
        ),
    ],
    ids=[
        "fields-under-a-title",
        "field-with-sub-bullets",
        "bold-led-paragraph",
        "title-no-fields",
    ],
)
def test_a_new_header_line_joins_the_header_block(rig, body, want):
    """CR 308: never inside a paragraph, between a field and its sub-bullets, or above a title."""
    rig.issue(REPO, EPIC, body=body)
    ops = [{"op": "header", "field": "Last verified SHA", "value": "abc1234"}]
    res = rig.edit(REPO, EPIC, ops, "--adopt-live")
    assert res.returncode == 0, res.stderr
    assert want in rig.body(REPO, EPIC), rig.body(REPO, EPIC)


def test_header_adds_only_a_cursor_field(adopted):
    """CR 292: a typo'd field would make a line no script reads."""
    ops = [{"op": "header", "field": "Last chek-in", "value": "x"}]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 3 and "want exactly one" in res.stderr


@pytest.mark.parametrize(
    "fields, why",
    [
        ({"new_numbers": [], "capped": ["listing new numbers"]}, "page cap"),
        ({"new_numbers": [], "updated_since": None}, "no since"),
    ],
    ids=["number-walk-capped", "no-updated-since"],
)
def test_last_seen_needs_a_complete_report(adopted, fields, why):
    """CR 302: either gap lets the watermark move past an issue nobody saw."""
    report = _report(adopted, **fields)
    ops = [{"op": "header", "field": "Last issue seen", "value": "{last_seen}"}]
    res = adopted.edit(REPO, EPIC, ops, "--scan", report)
    assert res.returncode == 1 and why in res.stderr, res.stderr
    ops = [{"op": "header", "field": "Last check-in", "value": "{checked}"}]
    assert adopted.edit(REPO, EPIC, ops, "--scan", report).returncode == 0


@pytest.mark.parametrize(
    "capped, field, refused",
    [
        (["listing updates"], "Last check-in", True),
        (["listing updates"], "Last issue seen", True),
        (["reading new comments"], "Last check-in", True),
        (["reading the epic's new comments"], "Last check-in", True),
        (["reading new comments"], "Last issue seen", False),
    ],
)
def test_a_capped_updates_or_comments_listing_holds_the_cursors(
    adopted, capped, field, refused
):
    """CR 306: the cut-off rows are exactly the ones the next window would skip."""
    report = _report(adopted, new_numbers=[], capped=capped)
    value = "{checked}" if field == "Last check-in" else "{last_seen}"
    ops = [{"op": "header", "field": field, "value": value}]
    res = adopted.edit(REPO, EPIC, ops, "--scan", report)
    assert res.returncode == (1 if refused else 0), res.stderr
    if refused:
        assert "page cap" in res.stderr


def test_log_appends_at_the_end_of_its_section_once(adopted):
    ops = [{"op": "log", "text": "{today}: #11 closed. No new issues. Next: #12."}]
    assert adopted.edit(REPO, EPIC, ops).returncode == 0
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 0 and summary(res).get("unchanged")
    body = adopted.body(REPO, EPIC)
    assert body.count("#11 closed") == 1
    assert body.rstrip().endswith("Next: #12.")


def test_add_line_lands_in_its_section_and_refuses_a_duplicate_ref(adopted):
    res = adopted.edit(
        REPO,
        EPIC,
        [{"op": "add-line", "section": "Tier 1", "line": "- [ ] #14 a follow-up"}],
    )
    assert res.returncode == 0, res.stderr
    body = adopted.body(REPO, EPIC)
    # After the section's last line, before its trailing blank (CR 295).
    assert (
        "- [ ] acme/gadgets#3 upstream fix\n- [ ] #14 a follow-up\n\n## Parked" in body
    )
    assert summary(res)["counts_after"]["open"] == 4
    res = adopted.edit(
        REPO, EPIC, [{"op": "add-line", "section": "Tier 1", "line": "- [ ] #14 again"}]
    )
    assert res.returncode == 3 and "already has a line" in res.stderr


def test_add_line_after_a_ref_keeps_that_refs_sub_bullets(rig):
    """CR 250: the new item goes after #12's indented notes, not between them."""
    rig.issue(
        REPO,
        EPIC,
        body=BODY.replace(
            "- [ ] #12 second thing\n", "- [ ] #12 second thing\n  - verify on dev\n"
        ),
    )
    assert rig.edit(REPO, EPIC, [], "--adopt-live").returncode == 0
    res = rig.edit(
        REPO,
        EPIC,
        [{"op": "add-line", "after_ref": "#12", "line": "- [ ] #14 follow-up"}],
    )
    assert res.returncode == 0, res.stderr
    assert (
        "- [ ] #12 second thing\n  - verify on dev\n- [ ] #14 follow-up\n"
        in rig.body(REPO, EPIC)
    )


def test_add_line_wont_add_a_third_line_for_an_ambiguous_ref(rig):
    """CR 252."""
    rig.issue(
        REPO,
        EPIC,
        body=BODY.replace(
            "- [ ] #12 second thing\n", "- [ ] #12 second thing\n- [ ] #12 again\n"
        ),
    )
    assert rig.edit(REPO, EPIC, [], "--adopt-live").returncode == 0
    res = rig.edit(
        REPO, EPIC, [{"op": "add-line", "section": "Tier 1", "line": "- [ ] #12 third"}]
    )
    assert res.returncode == 3 and "ambiguous" in res.stderr


def test_add_line_after_a_ref_spans_blank_lines_in_its_block(rig):
    """CR 266: a blank line between sub-bullets doesn't end #12's block."""
    rig.issue(
        REPO,
        EPIC,
        body=BODY.replace(
            "- [ ] #12 second thing\n",
            "- [ ] #12 second thing\n  - sub a\n\n  - sub b\n",
        ),
    )
    assert rig.edit(REPO, EPIC, [], "--adopt-live").returncode == 0
    res = rig.edit(
        REPO,
        EPIC,
        [{"op": "add-line", "after_ref": "#12", "line": "- [ ] #14 follow-up"}],
    )
    assert res.returncode == 0, res.stderr
    assert "  - sub a\n\n  - sub b\n- [ ] #14 follow-up\n" in rig.body(REPO, EPIC)


def test_add_line_without_a_ref_is_idempotent_despite_trailing_spaces(adopted):
    """CR 280."""
    assert (
        adopted.edit(
            REPO, EPIC, [{"op": "add-line", "section": "Tier 1", "line": "plain note"}]
        ).returncode
        == 0
    )
    res = adopted.edit(
        REPO, EPIC, [{"op": "add-line", "section": "Tier 1", "line": "plain note  "}]
    )
    assert res.returncode == 0 and summary(res).get("unchanged")
    assert adopted.body(REPO, EPIC).count("plain note") == 1


def test_a_paragraph_after_a_blank_line_needs_the_content_column(rig):
    """CR 283: " note" (one space) after a blank line isn't part of #12's item."""
    rig.issue(
        REPO,
        EPIC,
        body=BODY.replace(
            "- [ ] #12 second thing\n",
            "- [ ] #12 second thing\n  - sub\n\n not the item's\n",
        ),
    )
    assert rig.edit(REPO, EPIC, [], "--adopt-live").returncode == 0
    res = rig.edit(
        REPO,
        EPIC,
        [{"op": "add-line", "after_ref": "#12", "line": "- [ ] #14 follow-up"}],
    )
    assert res.returncode == 0, res.stderr
    assert "  - sub\n- [ ] #14 follow-up\n\n not the item's\n" in rig.body(REPO, EPIC)


def test_a_tab_indented_sub_line_belongs_to_its_item(rig):
    """CR 285 (for 266): a tab counts as indentation."""
    rig.issue(
        REPO,
        EPIC,
        body=BODY.replace(
            "- [ ] #12 second thing\n", "- [ ] #12 second thing\n\tdetail\n"
        ),
    )
    assert rig.edit(REPO, EPIC, [], "--adopt-live").returncode == 0
    res = rig.edit(
        REPO,
        EPIC,
        [{"op": "add-line", "after_ref": "#12", "line": "- [ ] #14 follow-up"}],
    )
    assert res.returncode == 0, res.stderr
    assert "\tdetail\n- [ ] #14 follow-up\n" in rig.body(REPO, EPIC)


def test_set_line_and_replace_section_keep_the_callers_hard_breaks(adopted):
    """CR 285 (for 274): caller text keeps its trailing spaces."""
    ops = [
        {"op": "set-line", "ref": "#12", "line": "- [ ] #12 two lines  "},
        {"op": "replace-section", "heading": "Parked", "text": "first  \nsecond"},
    ]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 0, res.stderr
    body = adopted.body(REPO, EPIC)
    assert "- [ ] #12 two lines  \n" in body and "first  \nsecond" in body


def test_set_line_must_keep_its_ref(adopted):
    res = adopted.edit(
        REPO, EPIC, [{"op": "set-line", "ref": "#12", "line": "- [ ] #11 oops"}]
    )
    assert res.returncode == 3
    res = adopted.edit(
        REPO,
        EPIC,
        [
            {
                "op": "set-line",
                "ref": "#12",
                "line": "- [ ] #12 dependency met: smaller now",
            }
        ],
    )
    assert res.returncode == 0, res.stderr


def test_a_note_that_is_a_substring_of_the_line_is_still_added(adopted):
    """CR 253."""
    res = adopted.edit(REPO, EPIC, [{"op": "note", "ref": "#12", "text": "second"}])
    assert res.returncode == 0 and summary(res)["written"], res.stderr
    assert "- [ ] #12 second thing second" in adopted.body(REPO, EPIC)
    res = adopted.edit(REPO, EPIC, [{"op": "note", "ref": "#12", "text": "second"}])
    assert summary(res).get("unchanged")


def test_note_on_a_table_row_lands_inside_the_last_cell(adopted):
    """CR 286: GFM drops a cell past the header's count, so the note would vanish."""
    op = {"op": "note", "ref": "#13", "text": "(re-read {today})"}
    res = adopted.edit(REPO, EPIC, [op])
    assert res.returncode == 0, res.stderr
    assert re.search(
        r"^\| #13 \| when the SDK ships \(re-read \d{4}-\d\d-\d\d\) \|$",
        adopted.body(REPO, EPIC),
        re.M,
    )
    assert summary(adopted.edit(REPO, EPIC, [op])).get("unchanged")


def test_a_note_on_a_row_without_a_closing_pipe_ends_the_row(rig):
    rig.issue(
        REPO, EPIC, body=BODY.replace("| #13 | when the SDK ships |", "| #13 | sdk")
    )
    assert rig.edit(REPO, EPIC, [], "--adopt-live").returncode == 0
    res = rig.edit(REPO, EPIC, [{"op": "note", "ref": "#13", "text": "later"}])
    assert res.returncode == 0, res.stderr
    assert "\n| #13 | sdk later\n" in rig.body(REPO, EPIC)


def test_a_note_on_a_row_refuses_a_bare_pipe(adopted):
    res = adopted.edit(REPO, EPIC, [{"op": "note", "ref": "#13", "text": "a | b"}])
    assert res.returncode == 3 and "\\|" in res.stderr
    res = adopted.edit(REPO, EPIC, [{"op": "note", "ref": "#13", "text": "a \\| b"}])
    assert res.returncode == 0, res.stderr


def test_replace_section_counts_its_boxes(adopted):
    res = adopted.edit(
        REPO,
        EPIC,
        [
            {
                "op": "replace-section",
                "heading": "Tier 1",
                "text": "- [x] #11 done\n- [ ] #12 next",
            }
        ],
    )
    assert res.returncode == 0, res.stderr
    s = summary(res)
    assert s["counts_after"] == {"open": 1, "done": 1}
    assert "acme/gadgets#3" not in adopted.body(REPO, EPIC)


def test_adopt_live_with_ops_writes_on_the_adopted_body(rig):
    """CR 264: first use can adopt and edit in one call."""
    res = rig.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}], "--adopt-live")
    assert res.returncode == 0, res.stderr
    s = summary(res)
    assert s["adopted_live"] and s["written"] and s["readback"] == "matches"
    base = (rig.state_dir / "acme" / "widgets" / "10" / "last-written.md").read_text()
    assert "- [x] #11" in base


def test_replace_section_at_the_end_of_the_body(adopted):
    """CR 264: the last section has no following heading; the edit stays idempotent."""
    ops = [
        {"op": "replace-section", "heading": "Log", "text": "- 2026-10-14: rewritten."}
    ]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 0, res.stderr
    assert adopted.body(REPO, EPIC).endswith("## Log\n\n- 2026-10-14: rewritten.\n")
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 0 and summary(res).get("unchanged")


def test_each_write_keeps_a_history_copy(adopted):
    """CR 264: the fallback when the baseline is lost is a local copy of each write."""
    adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    history = list(
        (adopted.state_dir / "acme" / "widgets" / "10" / "history").glob("*.md")
    )
    assert len(history) == 1
    assert history[0].read_text() == adopted.body(REPO, EPIC)


def test_dry_run_writes_nothing(adopted):
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}], "--dry-run")
    assert res.returncode == 0
    assert "+- [x] #11 first thing" in res.stderr
    assert "patches" not in adopted.load()


# ---------------------------------------------------------------- lint


@pytest.mark.parametrize(
    "line, why",
    [
        ("- [ ] SUB3 placeholder child", "SUBn"),
        ("- [ ] #14 waits on acme/gadgets#3, #4", "qualify it"),
        ("- [ ] #14 see #400", "highest number"),
        ("- [ ] #14 token ghp_" + "a" * 36, "secret"),
        ("- [ ] #14 at $NOW", "shell variable"),
        ("- [ ] #14 stamped {{when}}", "{{...}}"),
        ("- [ ] #14 waits on gadgets#3", "short ref"),
    ],
)
def test_lint_refuses_new_lines(adopted, line, why):
    res = adopted.edit(
        REPO, EPIC, [{"op": "add-line", "section": "Tier 1", "line": line}]
    )
    assert res.returncode == 3, res.stdout
    assert why in res.stderr
    assert "ghp_aaaa" not in res.stderr + res.stdout


def test_a_fenced_block_is_linted_for_secrets_only(adopted):
    """CR 290: a command in a fence renders as written."""
    text = '```bash\nbash x.sh --files "$FILES" # skills#348 ${{ matrix.py }} #999\n```'
    ops = [{"op": "replace-section", "heading": "Parked", "text": text}]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 0, res.stderr
    secret = "```\nexport T=ghp_" + "a" * 36 + "\n```"
    ops = [{"op": "replace-section", "heading": "Parked", "text": secret}]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 3 and "secret" in res.stderr


@pytest.mark.parametrize(
    "line",
    [
        "- CI runs `${{ matrix.python }}`",
        "- the template's `{{ name }}` field",
        "- see `#999`",
        "- link form: `https://github.com/o/r/issues/5#issuecomment-123`",
    ],
)
def test_a_code_span_renders_as_written(adopted, line):
    """CR 290: like the shell-variable check, these read outside code spans only."""
    ops = [{"op": "add-line", "section": "Parked", "line": line}]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 0, res.stderr


@pytest.mark.parametrize("line", ["- run \\`make\\` first", "- slot `SUB3` after #12"])
def test_a_code_span_hides_no_leftover(adopted, line):
    """CR 290: a SUBn is a leftover anywhere, and \\` is what makes the span."""
    ops = [{"op": "add-line", "section": "Parked", "line": line}]
    assert adopted.edit(REPO, EPIC, ops).returncode == 3


def test_a_bare_ref_after_this_repos_own_qualified_ref_is_fine(adopted):
    """CR 295: "acme/widgets#11, #12" is this repo's #12 either way."""
    line = "- [ ] #14 after acme/widgets#11, #12"
    ops = [{"op": "add-line", "section": "Tier 1", "line": line}]
    assert adopted.edit(REPO, EPIC, ops).returncode == 0


def test_a_transferred_issue_above_the_newest_created_is_not_refused(adopted):
    """CR 260: #20 exists, though the newest-created issue is #14."""
    adopted.issue(REPO, 20, created_at="2025-01-01T00:00:00Z")
    for n in (10, 11, 12, 13, 14):
        adopted.issue(REPO, n, created_at=f"2026-10-0{n - 9}T00:00:00Z")
    res = adopted.edit(
        REPO,
        EPIC,
        [{"op": "add-line", "section": "Tier 1", "line": "- [ ] #20 moved here"}],
    )
    assert res.returncode == 0, res.stderr


def test_a_shell_variable_inside_a_code_span_is_fine(adopted):
    res = adopted.edit(
        REPO,
        EPIC,
        [
            {
                "op": "add-line",
                "section": "Tier 1",
                "line": "- [ ] #14 reads `$XDG_STATE_HOME`",
            }
        ],
    )
    assert res.returncode == 0, res.stderr


def test_markdown_links_read_as_github_renders_them(adopted):
    """CR 247: a link to another repo's issue is that repo's ref; a doc anchor is no ref."""
    line = (
        "- [ ] #14 see [#400](https://github.com/other/repo/issues/400),"
        " [plan](docs/plan.md#2-steps) and [step](#3-rescan)"
    )
    res = adopted.edit(
        REPO, EPIC, [{"op": "add-line", "section": "Tier 1", "line": line}]
    )
    assert res.returncode == 0, res.stderr
    lines = ee.normalize(adopted.body(REPO, EPIC))
    assert ee.refs_in([line], REPO) == {"acme/widgets#14", "other/repo#400"}
    assert ee.line_ref(f"- [ ] [#12](https://github.com/{REPO}/issues/12) x", REPO) == (
        "item",
        "acme/widgets#12",
    )
    assert "acme/widgets#3" not in ee.refs_in(lines, REPO)


@pytest.mark.parametrize(
    "text, refs",
    [
        ("[x](docs/plan.md#2-steps 'T')", set()),
        ("[x](docs/plan.md#2-steps (T))", set()),
        ("[[#8] x](https://github.com/o/r/issues/8)", {"o/r#8"}),
        ("[w](https://en.wikipedia.org/wiki/C_(x)#3)", set()),
        ("[see #5](docs/a.md)", set()),
        ("![#6](img.png)", set()),
        ("[#9](<https://github.com/o/r/issues/9>)", {"o/r#9"}),
        ("https://github.com/o/r/issues/8", {"o/r#8"}),
        ("<https://github.com/o/r/pull/9>", {"o/r#9"}),
        (f"https://github.com/{REPO}/issues/12#issuecomment-1", {"acme/widgets#12"}),
        ("https://github.com/o/r/issues/8/files", set()),
    ],
    ids=[
        "single-title",
        "paren-title",
        "nested-text",
        "paren-target",
        "link-text",
        "image",
        "angled",
        "bare-url",
        "autolink",
        "comment-url",
        "not-an-issue-url",
    ],
)
def test_link_shapes_read_as_github_renders_them(text, refs):
    """CR 271."""
    assert ee.refs_in([f"see {text} here"], REPO) == refs


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/a/b/issues/5#issuecomment-1",
        "<https://github.com/a/b/issues/5#issuecomment-1>",
    ],
    ids=["bare", "angled"],
)
def test_a_url_with_a_fragment_still_qualifies_only_itself(adopted, url):
    """CR 311: the bare #6 after it is this repo's, whichever form the URL takes."""
    line = f"- [ ] #14 see {url}, #6"
    ops = [{"op": "add-line", "section": "Tier 1", "line": line}]
    res = adopted.edit(REPO, EPIC, ops, "--no-link-check")
    assert res.returncode == 3 and "bare #6 after a/b#" in res.stderr, res.stderr


@pytest.mark.parametrize(
    "line",
    [
        "- [ ] #14 upstream a/b#5 [design](docs/d.md), #12 next",
        "- [ ] #14 a/b#5 and [this note](https://example.com) #12",
        "- [ ] #14 a/b#5 [plan](x.md#2) / #12",
    ],
)
def test_a_dropped_link_doesnt_join_refs_across_it(adopted, line):
    """CR 277: the link between them is not a separator."""
    res = adopted.edit(
        REPO, EPIC, [{"op": "add-line", "section": "Tier 1", "line": line}]
    )
    assert res.returncode == 0, res.stderr


def test_a_comment_link_must_resolve_to_its_issue(adopted):
    adopted.comment(REPO, 12, 555, body="brief")
    good = f"https://github.com/{REPO}/issues/12#issuecomment-555"
    wrong = f"https://github.com/{REPO}/issues/11#issuecomment-555"
    made_up = f"https://github.com/{REPO}/issues/12#issuecomment-999"
    for url, ok in ((wrong, False), (made_up, False), (good, True)):
        res = adopted.edit(
            REPO, EPIC, [{"op": "note", "ref": "#12", "text": f"[brief]({url})"}]
        )
        assert (res.returncode == 0) is ok, (url, res.stderr)


# ---------------------------------------------------------------- accounting, readback, infra


def test_a_child_listed_by_url_is_accounted_for(adopted):
    """CR 288: GitHub renders the URL as #14, so the epic lists it."""
    line = f"- [ ] https://github.com/{REPO}/issues/14 by url"
    ops = [{"op": "add-line", "section": "Tier 1", "line": line}]
    res = adopted.edit(REPO, EPIC, ops, "--account")
    assert res.returncode == 0, res.stderr


def test_account_names_open_issues_the_epic_misses(adopted):
    adopted.issue(REPO, 15)
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}], "--account")
    assert res.returncode == 3
    assert "#15" in res.stderr and "#14" in res.stderr
    assert summary(res)["unlisted"] == [14, 15]


def test_account_from_scopes_a_number_range(adopted):
    adopted.issue(REPO, 15)
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}], "--account", "15")
    assert res.returncode == 3
    assert summary(res)["unlisted"] == [15]


def test_an_edit_landing_during_the_run_refuses_the_write(adopted):
    """CR 258: the second fetch, just before the PATCH, sees the concurrent edit."""
    adopted.change_on_get(EPIC, 2, BODY.replace("second thing", "second thing, edited"))
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 3 and "changed while this run" in res.stderr
    assert "patches" not in adopted.load()
    assert "second thing, edited" in adopted.body(REPO, EPIC)


def test_account_refuses_when_the_open_list_may_be_cut_off(
    adopted, monkeypatch, capsys
):
    """CR 259: at the listing's limit, an empty 'unlisted' proves nothing."""
    monkeypatch.setattr(ee, "ACCOUNT_LIMIT", 3)
    for k, v in adopted.env().items():
        monkeypatch.setenv(k, v)
    rc = ee.run(
        [
            "--repo",
            REPO,
            "--epic",
            str(EPIC),
            "--state-dir",
            str(adopted.state_dir),
            "--account",
        ]
    )
    assert rc == 3
    assert "may be cut off" in capsys.readouterr().err


def test_touched_lines_keep_their_hard_break(rig):
    """CR 274: note and header keep a line's trailing break; caller text keeps its own."""
    body = BODY.replace(
        "- [ ] #12 second thing\n", "- [ ] #12 second thing  \n"
    ).replace("- **Next:** #12\n", "- **Next:** #12  \n")
    rig.issue(REPO, EPIC, body=body)
    assert rig.edit(REPO, EPIC, [], "--adopt-live").returncode == 0
    ops = [
        {"op": "note", "ref": "#12", "text": "(re-read)"},
        {"op": "header", "field": "Next", "value": "#11"},
        {"op": "add-line", "section": "Tier 1", "line": "- [ ] #14 two lines  "},
    ]
    res = rig.edit(REPO, EPIC, ops)
    assert res.returncode == 0, res.stderr
    out = rig.body(REPO, EPIC)
    assert "- [ ] #12 second thing (re-read)  \n" in out
    assert "- **Next:** #11  \n" in out
    assert "- [ ] #14 two lines  \n" in out


def test_a_whitespace_only_edit_during_the_run_refuses_the_write(adopted):
    """CR 274: the compare-and-swap compares raw text."""
    adopted.change_on_get(EPIC, 2, BODY.replace("first thing\n", "first thing  \n"))
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#12"}])
    assert res.returncode == 3 and "changed while this run" in res.stderr


def test_a_write_the_read_back_contradicts_is_exit_4(adopted):
    adopted.set_flag("patch_noop", True)
    base = (
        adopted.state_dir / "acme" / "widgets" / "10" / "last-written.md"
    ).read_text()
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 4
    assert "baseline not updated" in res.stderr
    assert (
        adopted.state_dir / "acme" / "widgets" / "10" / "last-written.md"
    ).read_text() == base


def test_a_failed_read_back_after_the_write_still_says_written(adopted):
    """CR 300: fetch, compare-and-swap re-fetch, PATCH, then the read-back fails."""
    adopted.fail_on_get(EPIC, 3)
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 4, res.stderr
    s = summary(res)
    assert s["written"] and s["readback"] == "failed"
    assert "the body was written" in res.stderr and "502" in res.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_a_baseline_that_cant_be_saved_is_exit_4_not_2(adopted):
    """CR 300."""
    d = adopted.state_dir / "acme" / "widgets" / "10"
    d.chmod(0o500)
    try:
        res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    finally:
        d.chmod(0o700)
    assert res.returncode == 4, res.stderr
    s = summary(res)
    assert s["written"] and s["readback"] == "matches" and s["baseline"] == "not saved"


@pytest.mark.parametrize(
    "line, path",
    [
        ("- [ ] #99 x", "issues/99"),
        (
            f"- [ ] #14 see https://github.com/{REPO}/issues/11#issuecomment-555",
            "issues/comments/555",
        ),
    ],
    ids=["existence-check", "comment-link"],
)
def test_a_gh_outage_during_lint_is_exit_2_not_a_refusal(adopted, line, path):
    """CR 304: only a 404 says the ref is wrong; a 502 says nothing about it."""
    adopted.set_flag("fail_paths", {path: "HTTP 502: Bad Gateway"})
    ops = [{"op": "add-line", "section": "Tier 1", "line": line}]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 2 and "502" in res.stderr, res.stderr
    assert "patches" not in adopted.load()


def test_a_patch_that_lands_despite_a_502_is_a_write(adopted):
    """CR 309: or the next run calls this tool's own tick a foreign one."""
    adopted.set_flag("patch_fails_after_apply", True)
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 0, res.stderr
    assert summary(res)["written"] is True and "it landed" in res.stderr
    adopted.set_flag("patch_fails_after_apply", False)
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#12"}])
    assert res.returncode == 0, res.stderr


def test_a_patch_that_failed_and_didnt_land_is_exit_2(adopted):
    """CR 309: the body is unchanged, so nothing was written."""
    adopted.set_flag("fail_paths", {"PATCH": "HTTP 502: Bad Gateway"})
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 2 and "502" in res.stderr
    assert adopted.body(REPO, EPIC) == BODY


def test_a_failed_patch_and_a_third_body_is_exit_4_written_unknown(adopted):
    """CR 309: fetch, compare-and-swap re-fetch, failed PATCH, then a body nobody sent."""
    adopted.set_flag("fail_paths", {"PATCH": "HTTP 502: Bad Gateway"})
    adopted.change_on_get(EPIC, 3, BODY + "\n- someone else's line\n")
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 4, res.stderr
    assert summary(res)["written"] == "unknown" and "PATCH failed" in res.stderr


def test_a_gh_failure_is_exit_2_and_shows_ghs_own_stderr(adopted):
    adopted.set_flag("fail_all", "HTTP 401: Bad credentials")
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 2
    assert "Bad credentials" in res.stderr


def test_counts_catch_a_transform_that_drops_a_line(adopted, monkeypatch, capsys):
    """The derived-count check is the backstop for a transform bug (seventh run 92)."""
    real = ee.apply_ops

    def lossy(*args):
        new, expect, notes = real(*args)
        return [ln for ln in new if "#12 second" not in ln], expect, notes

    monkeypatch.setattr(ee, "apply_ops", lossy)
    for k, v in adopted.env().items():
        monkeypatch.setenv(k, v)
    ops = adopted.tmp / "ops.json"
    ops.write_text('[{"op": "tick", "ref": "#11"}]')
    rc = ee.run(
        [
            "--repo",
            REPO,
            "--epic",
            str(EPIC),
            "--state-dir",
            str(adopted.state_dir),
            "--ops",
            str(ops),
        ]
    )
    assert rc == 3
    assert "checkbox counts" in capsys.readouterr().err
    assert "patches" not in adopted.load()


@pytest.mark.parametrize(
    "ops, args",
    [
        (None, ["--repo", "not-a-repo"]),
        (None, ["--repo", "../.."]),
        ('[{"op": "tick", "ref": 12}]', []),
        ('[{"op": "frobnicate"}]', []),
        ('[{"op": "add-line", "line": "- [ ] #14 x"}]', []),
        ('[{"op": "note", "ref": "#12"}]', []),
        ("not json", []),
        ('[{"op": "header", "field": "Next", "value": "{checked}"}]', []),
        ('[{"op": ["tick"]}]', []),
        ('[{"op": "tick", "ref": "twelve"}]', []),
        ('[{"op": "add-line", "line": "- x", "after_ref": "12"}]', []),
        ("[]", ["--repo", REPO, "--accept-ticks", "twelve"]),
    ],
    ids=[
        "bad-repo",
        "dot-dot-repo",
        "ref-not-a-string",
        "unknown-op",
        "add-line-no-anchor",
        "missing-field",
        "bad-json",
        "scan-placeholder-without-scan",
        "op-name-not-a-string",
        "ref-not-a-ref",
        "after-ref-not-a-ref",
        "accept-ticks-not-a-ref",
    ],
)
def test_usage_errors_exit_1_before_any_fetch(adopted, ops, args):
    """CR 249: 1 is usage, 2 is infrastructure, and a typo is not an outage."""
    base = ["--repo", REPO, "--epic", str(EPIC), "--state-dir", str(adopted.state_dir)]
    if args:
        base = args + ["--epic", str(EPIC)]
    calls = len(adopted.load().get("calls", []))
    res = adopted.run(
        "epic-edit.sh", *base, *(["--ops", "-"] if ops else []), stdin=ops
    )
    assert res.returncode == 1, (res.returncode, res.stderr)
    assert "Traceback" not in res.stderr
    assert len(adopted.load().get("calls", [])) == calls


# ---------------------------------------------------------------- pure functions


def test_boxes_inside_a_fence_are_not_counted():
    lines = ee.normalize("- [ ] #1 a\n```\n- [ ] #2 b\n```\n- [x] #3 c\n")
    assert ee.counts(lines) == {"open": 1, "done": 1}
    with pytest.raises(ee.Refused):
        ee.find_ref_line(lines, ee.key(None, 2, REPO), REPO, want_item=True)


@pytest.mark.parametrize(
    "body",
    [
        "````md\n```bash\n- [ ] #2 b\n```\n- [ ] #4 d\n````\n- [ ] #1 a\n",
        "```\n- [ ] #2 b\n```python\n- [ ] #4 d\n```\n- [ ] #1 a\n",
        "~~~\n- [ ] #2 b\n```\n- [ ] #4 d\n~~~\n- [ ] #1 a\n",
    ],
    ids=["longer-outer", "info-string-is-not-a-close", "tilde-outer"],
)
def test_fences_follow_commonmark(body):
    """CR 246: only #1 is outside every fence."""
    lines = ee.normalize(body)
    assert ee.counts(lines) == {"open": 1, "done": 0}
    assert (
        ee.find_ref_line(lines, ee.key(None, 1, REPO), REPO, want_item=True)
        == len(lines) - 1
    )


def test_a_backtick_fence_with_a_backtick_in_its_info_opens_nothing():
    """CR 295 (for 246): "```a`b" is an inline code span's text, not a fence."""
    lines = ee.normalize("```a`b\n- [ ] #1 a\n```\n- [ ] #2 b\n")
    assert ee.fenced(lines) == [False, False, True, True]
    assert ee.counts(lines) == {"open": 1, "done": 0}


@pytest.mark.parametrize(
    "line, text",
    [
        ("## Notes on C#", "Notes on C#"),
        ("## Log ##", "Log"),
        ("### Tier 1 — bugs", "Tier 1 — bugs"),
    ],
)
def test_heading_text_follows_commonmark(line, text):
    """CR 255."""
    assert ee.headings([line]) == [(0, line.index(" "), text)]


def test_two_items_for_one_ref_are_ambiguous():
    lines = ee.normalize("- [ ] #1 a\n- [ ] #1 b\n")
    with pytest.raises(ee.Refused, match="ambiguous"):
        ee.find_ref_line(lines, ee.key(None, 1, REPO), REPO)


def test_a_ref_inside_another_repos_ref_is_not_this_repos():
    assert ee.line_ref("- [ ] acme/gadgets#3 x", REPO) == ("item", "acme/gadgets#3")
    assert ee.refs_in(["see acme/gadgets#3"], REPO) == {"acme/gadgets#3"}
