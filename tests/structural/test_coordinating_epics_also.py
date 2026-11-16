"""coordinating-epics: scan.sh --also re-scans a cross-repo parent's other repos (#400).

A cross-repo parent epic tracks children in several repos, with a watermark
for each. scan.sh read only the epic's own repo, so the other repos' number
walks and updated-since stayed manual, and that is where the archiver#300
run (finding 10) and broker#80's (finding 128) missed things. A watcher run
on 2026-11-11 re-scanned five sibling repos by hand at every check-in.
A fake gh stands in for GitHub.
"""

from __future__ import annotations

import json

from tests.structural.coordinating_epics_rig import Rig, summary

HOST = "acme/widgets"
SIB = "acme/gadgets"
EPIC = 10

BODY = """\
- **Last check-in:** 2026-10-01T09:00Z
- **Last issue seen:** #12
- **Last issue seen (Acme/Gadgets):** acme/gadgets#4

## Tier 1

- [ ] #11 host child
- [ ] acme/gadgets#3 sibling child
"""


def _rig(tmp_path, body=BODY):
    r = Rig(tmp_path)
    r.issue(HOST, EPIC, body=body, updated_at="2026-10-02T00:00:00Z")
    r.issue(HOST, 11, updated_at="2026-09-30T00:00:00Z")
    r.issue(HOST, 12, updated_at="2026-09-30T00:00:00Z")
    old = "2026-09-30T00:00:00Z"
    r.issue(SIB, 3, updated_at="2026-10-03T00:00:00Z", created_at=old)
    r.issue(SIB, 4, updated_at=old, created_at=old)
    for n, body_, when in (
        (5, "Follow-up to acme/widgets#10, the epic.", "2026-10-02T01:00:00Z"),
        (6, "Unrelated: the lint is slow.", "2026-10-02T02:00:00Z"),
        (7, "Found while doing #3.", "2026-10-02T03:00:00Z"),
    ):
        r.issue(SIB, n, body=body_, updated_at=when, created_at=when)
    return r


def scan(r, *extra, rc=0):
    res = r.run("scan.sh", "--repo", HOST, "--epic", str(EPIC), *extra)
    assert res.returncode == rc, res.stderr
    return json.loads(res.stdout) if rc == 0 else res


def test_400_also_walks_the_other_repos_numbers_and_updates(tmp_path):
    """#400, verbatim: `scan.sh --also OWNER/REPO` runs, for that repo, the
    number walk above its watermark and the updated-since listing, keeping
    only issues that mention the epic or one of its children by qualified
    ref. Rows carry their repo. The per-repo cursor comes from the header."""
    r = _rig(tmp_path)
    rep = scan(r, "--also", SIB)
    also = rep["also"]["acme/gadgets"]
    assert also["repo"] == SIB and also["cursors"]["watermark"] == 4
    assert [x["number"] for x in also["new_numbers"]] == [5, 7]
    assert all(x["repo"] == SIB for x in also["new_numbers"])
    five, seven = also["new_numbers"]
    assert five["mentions_epic"] and not five["in_epic"]
    assert seven["mentions_child"] and not seven["mentions_epic"]
    # #3 is the epic's own child there: updated since, so listed.
    assert [x["number"] for x in also["updated_since"]] == [3, 5, 7]
    assert also["updated_since"][0]["in_epic"]
    # #6 mentions neither: counted, not listed, and still past the watermark.
    assert also["unrelated"] == {"new_numbers": 1, "updated_since": 1}
    assert also["max_number"] == 7 and also["capped"] == []
    # The host's own report is as before, keys and all.
    assert rep["repo"] == HOST and rep["max_number"] == 12
    assert rep["cursors"]["watermark"] == 12


def test_400_without_also_the_report_has_no_also_key(tmp_path):
    rep = scan(_rig(tmp_path))
    assert "also" not in rep


def test_400_the_cursor_line_is_read_whatever_the_owners_case(tmp_path):
    """#400's harvest: the body writes CannObserv/watcher, refs_in lowercases.
    The cursor key folds case on both sides, and --also's spelling is kept."""
    r = _rig(tmp_path)
    also = scan(r, "--also", "ACME/gadgets")["also"]["acme/gadgets"]
    assert also["repo"] == "ACME/gadgets" and also["cursors"]["watermark"] == 4


def test_400_a_bare_or_mismatched_cursor_value(tmp_path):
    """A bare #N is read (the issue's form), and a value naming another repo
    is a warning, not a cursor: GitHub links it to that repo's issue."""
    r = _rig(tmp_path, BODY.replace("acme/gadgets#4", "#4"))
    assert scan(r, "--also", SIB)["also"]["acme/gadgets"]["cursors"]["watermark"] == 4
    (tmp_path / "x").mkdir()
    r = _rig(tmp_path / "x", BODY.replace("acme/gadgets#4", "acme/other#4"))
    rep = scan(r, "--also", SIB)
    also = rep["also"]["acme/gadgets"]
    assert also["cursors"]["watermark"] is None and also["new_numbers"] is None
    assert any("acme/other#4" in w for w in rep["warnings"])


def test_400_a_record_comment_on_a_sibling_child_is_dropped_by_the_hosts_key(
    tmp_path,
):
    """The record filter applies per repo, keyed by the host's epic: a record
    naming acme/widgets#10 on acme/gadgets#3 is the coordinator's own, and
    the row it alone listed goes."""
    r = _rig(tmp_path)
    r.comment(
        SIB,
        3,
        801,
        body="**Coordinator record, acme/widgets#10**\n\nverified",
        created_at="2026-10-03T00:00:00Z",
        updated_at="2026-10-03T00:00:00Z",
    )
    also = scan(r, "--also", SIB)["also"]["acme/gadgets"]
    assert [x["number"] for x in also["updated_since"]] == [5, 7]
    assert also["own_comments"] == {"record": 1, "rows_dropped": [3]}


def test_666_an_also_row_stamped_a_second_after_its_record_is_dropped(tmp_path):
    """#666: the --also walk shares the host's predicate, so GitHub's
    one-second stamp after a record comment drops the row there too."""
    r = _rig(tmp_path)
    r.issue(
        SIB, 3, updated_at="2026-10-03T00:00:01Z", created_at="2026-09-30T00:00:00Z"
    )
    r.comment(
        SIB,
        3,
        801,
        body="**Coordinator record, acme/widgets#10**\n\nverified",
        created_at="2026-10-03T00:00:00Z",
        updated_at="2026-10-03T00:00:00Z",
    )
    also = scan(r, "--also", SIB)["also"]["acme/gadgets"]
    assert also["own_comments"] == {"record": 1, "rows_dropped": [3]}


def test_400_a_failed_listing_in_an_also_repo_is_exit_2(tmp_path):
    """A warning would let {checked} move past that repo's unread window."""
    r = _rig(tmp_path)
    r.set_flag("fail_paths", {"repos/acme/gadgets/issues?": "HTTP 404: Not Found"})
    res = scan(r, "--also", SIB, rc=2)
    assert "acme/gadgets" in res.stderr and "HTTP 404" in res.stderr


def test_400_also_takes_only_another_repo(tmp_path):
    r = _rig(tmp_path)
    for bad in (HOST, "Acme/Widgets", "nope"):
        res = r.run("scan.sh", "--repo", HOST, "--epic", str(EPIC), "--also", bad)
        assert res.returncode == 1, (bad, res.stderr)


# ---------------------------------------------------------------- the editor


def _adopted(tmp_path):
    r = _rig(tmp_path)
    res = r.edit(HOST, EPIC, [], "--adopt-live")
    assert res.returncode == 0, res.stderr
    return r


def _report(r, tmp_path, *extra):
    rep = scan(r, "--also", SIB, *extra)
    path = tmp_path / "scan.json"
    path.write_text(json.dumps(rep))
    return rep, str(path)


SLOTS = [
    {"op": "add-line", "section": "Tier 1", "line": "- [ ] acme/gadgets#5 follow-up"},
    {"op": "log-comment", "text": "acme/gadgets#7 out of epic."},
]


def test_400_last_seen_per_repo_injects_the_qualified_ref(tmp_path):
    """{last_seen:owner/repo} becomes that repo's highest number, qualified,
    into its own cursor line, found whatever the case."""
    r = _adopted(tmp_path)
    _, path = _report(r, tmp_path)
    ops = SLOTS + [
        {
            "op": "header",
            "field": "Last issue seen (acme/gadgets)",
            "value": "{last_seen:acme/gadgets}",
        },
    ]
    res = r.edit(HOST, EPIC, ops, "--scan", path)
    assert res.returncode == 0, res.stderr
    body = r.body(HOST, EPIC)
    assert "- **Last issue seen (Acme/Gadgets):** acme/gadgets#7\n" in body


def test_400_a_new_issue_in_an_also_repo_must_be_mentioned(tmp_path):
    """The editor's refusal of new issues the body doesn't mention applies
    per repo, by qualified ref."""
    r = _adopted(tmp_path)
    _, path = _report(r, tmp_path)
    res = r.edit(HOST, EPIC, SLOTS[:1], "--scan", path)
    assert res.returncode == 3 and "acme/gadgets#7" in res.stderr, res.stderr
    assert r.edit(HOST, EPIC, SLOTS, "--scan", path).returncode == 0


def test_400_a_cursor_lines_ref_is_no_mention(tmp_path):
    """The per-repo cursor line is a cursor: its ref doesn't account for a
    new issue, as the host's Last issue seen doesn't."""
    r = _adopted(tmp_path)
    _, path = _report(r, tmp_path)
    ops = [
        SLOTS[0],
        {
            "op": "header",
            "field": "Last issue seen (acme/gadgets)",
            "value": "acme/gadgets#7",
        },
    ]
    res = r.edit(HOST, EPIC, ops, "--scan", path)
    assert res.returncode == 3 and "acme/gadgets#7" in res.stderr, res.stderr


def test_400_last_seen_per_repo_keeps_the_guards_per_repo(tmp_path):
    """CR 265, 276, 302 per repo: no watermark there, a capped walk there, or
    a repo the report didn't scan, refuses {last_seen:owner/repo}."""
    r = _adopted(tmp_path)
    rep, path = _report(r, tmp_path)
    op = {
        "op": "header",
        "field": "Last issue seen (acme/gadgets)",
        "value": "{last_seen:acme/gadgets}",
    }
    for change, why in (
        (lambda a: a.update(new_numbers=None), "no watermark"),
        (lambda a: a.update(capped=["listing new numbers"]), "page cap"),
        (lambda a: a.update(updated_since=None), "no since"),
    ):
        bad = json.loads(json.dumps(rep))
        change(bad["also"]["acme/gadgets"])
        (tmp_path / "bad.json").write_text(json.dumps(bad))
        res = r.edit(HOST, EPIC, SLOTS + [op], "--scan", str(tmp_path / "bad.json"))
        assert res.returncode == 1 and why in res.stderr, (why, res.stderr)
    other = dict(op, value="{last_seen:acme/other}")
    res = r.edit(HOST, EPIC, SLOTS + [other], "--scan", path)
    assert res.returncode == 1 and "--also acme/other" in res.stderr, res.stderr


def test_400_a_capped_also_listing_holds_checked(tmp_path):
    """{checked} is one time for every repo: a sibling's capped updates
    listing would move it past rows nobody listed (CR 306)."""
    r = _adopted(tmp_path)
    rep, _ = _report(r, tmp_path)
    rep["also"]["acme/gadgets"]["capped"] = ["listing updates"]
    (tmp_path / "bad.json").write_text(json.dumps(rep))
    op = {"op": "header", "field": "Last check-in", "value": "{checked}"}
    res = r.edit(HOST, EPIC, SLOTS + [op], "--scan", str(tmp_path / "bad.json"))
    assert res.returncode == 1 and "acme/gadgets" in res.stderr, res.stderr


def test_400_last_seen_per_repo_needs_a_scan(tmp_path):
    r = _adopted(tmp_path)
    op = {
        "op": "header",
        "field": "Last issue seen (acme/gadgets)",
        "value": "{last_seen:acme/gadgets}",
    }
    res = r.edit(HOST, EPIC, [op])
    assert res.returncode == 1 and "--scan" in res.stderr, res.stderr


def test_400_an_uninjected_per_repo_placeholder_is_linted(tmp_path):
    """Typed into a comment, it would post as written."""
    r = _adopted(tmp_path)
    (tmp_path / "c.md").write_text("Last seen {last_seen:acme/gadgets}.\n")
    res = r.run("comment.sh", "--repo", HOST, "--lint-file", str(tmp_path / "c.md"))
    assert res.returncode == 3 and "uninjected" in res.stderr, res.stderr
    assert summary(res)["refused"]


def test_cr2227_a_cursor_with_no_also_holds_checked_and_warns(tmp_path):
    """The body keeps acme/gadgets's cursor, but the scan left out --also:
    {checked} would move past gadgets' unread window."""
    r = _adopted(tmp_path)
    rep = scan(r)
    assert any("--also acme/gadgets" in w for w in rep["warnings"])
    path = tmp_path / "plain.json"
    path.write_text(json.dumps(rep))
    op = {"op": "header", "field": "Last check-in", "value": "{checked}"}
    res = r.edit(HOST, EPIC, [op], "--scan", str(path))
    assert res.returncode == 3 and "--also acme/gadgets" in res.stderr, res.stderr


def test_cr2232_an_unknown_last_seen_repo_is_refused_before_any_fetch(tmp_path):
    r = _adopted(tmp_path)
    _, path = _report(r, tmp_path)
    before = len(r.load()["calls"])
    op = {"op": "header", "field": "Next", "value": "{last_seen:acme/other}"}
    res = r.edit(HOST, EPIC, [op], "--scan", path)
    assert res.returncode == 1 and "--also acme/other" in res.stderr
    assert len(r.load()["calls"]) == before


def test_cr2235_also_takes_the_form_a_cursor_line_can_hold(tmp_path):
    r = _rig(tmp_path)
    res = r.run("scan.sh", "--repo", HOST, "--epic", str(EPIC), "--also", "user_corp/x")
    assert res.returncode == 1 and "owner/repo" in res.stderr
