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
    assert (adopted.state_dir / "acme-widgets-10" / "last-written.md").is_file()
    assert "patches" not in adopted.load()


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
    base = (adopted.state_dir / "acme-widgets-10" / "last-written.md").read_text()
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
            }
        )
    )
    ops = [
        {"op": "header", "field": "Last check-in", "value": "{checked}"},
        {"op": "header", "field": "Last issue seen", "value": "{last_seen}"},
    ]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 3 and "needs --scan" in res.stderr
    res = adopted.edit(REPO, EPIC, ops, "--scan", str(report))
    assert res.returncode == 0, res.stderr
    body = adopted.body(REPO, EPIC)
    assert "- **Last check-in:** 2026-10-14T18:03:27Z" in body
    assert "- **Last issue seen:** #13" in body
    other = adopted.tmp / "other.json"
    other.write_text(
        json.dumps(
            {"repo": REPO, "epic": 99, "now": "2026-10-14T18:03:27Z", "max_number": 1}
        )
    )
    res = adopted.edit(REPO, EPIC, ops, "--scan", str(other))
    assert res.returncode == 3 and "another epic" in res.stderr


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
    assert body.index("#14 a follow-up") < body.index("## Parked")
    assert summary(res)["counts_after"]["open"] == 4
    res = adopted.edit(
        REPO, EPIC, [{"op": "add-line", "section": "Tier 1", "line": "- [ ] #14 again"}]
    )
    assert res.returncode == 3 and "already has a line" in res.stderr


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


def test_note_works_on_a_table_row(adopted):
    res = adopted.edit(
        REPO, EPIC, [{"op": "note", "ref": "#13", "text": "(re-read {today})"}]
    )
    assert res.returncode == 0, res.stderr
    assert re.search(
        r"\| #13 \| when the SDK ships \| \(re-read \d{4}-", adopted.body(REPO, EPIC)
    )


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


def test_a_write_the_read_back_contradicts_is_exit_4(adopted):
    adopted.set_flag("patch_noop", True)
    base = (adopted.state_dir / "acme-widgets-10" / "last-written.md").read_text()
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#11"}])
    assert res.returncode == 4
    assert "baseline not updated" in res.stderr
    assert (
        adopted.state_dir / "acme-widgets-10" / "last-written.md"
    ).read_text() == base


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


def test_two_items_for_one_ref_are_ambiguous():
    lines = ee.normalize("- [ ] #1 a\n- [ ] #1 b\n")
    with pytest.raises(ee.Refused, match="ambiguous"):
        ee.find_ref_line(lines, ee.key(None, 1, REPO), REPO)


def test_a_ref_inside_another_repos_ref_is_not_this_repos():
    assert ee.line_ref("- [ ] acme/gadgets#3 x", REPO) == ("item", "acme/gadgets#3")
    assert ee.refs_in(["see acme/gadgets#3"], REPO) == {"acme/gadgets#3"}
