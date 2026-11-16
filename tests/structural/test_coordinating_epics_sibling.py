"""coordinating-epics: scan.sh --sibling compares a child's line across epics (#660).

When two epics each keep a line for the same child, nothing compared the two
boxes. Watcher's 2026-11-11 run, finding 368-F6: a child closed on 11-03 and
was ticked on the backlog epic the same day, but its parent's tick waited
until 11-10. `scan.sh --sibling OWNER/REPO#N` (repeatable) reads each sibling
epic's body, and `cross_epic` lists each child that leads a checklist item in
both, with both boxes, both lines, the child's state, and `drift` when the
boxes differ. Reporting only: nothing here refuses. A child is a line's
subject (#662's parser), so a pointer line, which names the other epic, isn't
one. A fake gh stands in for GitHub.
"""

from __future__ import annotations

import json

from tests.structural.coordinating_epics_gh_layer import install
from tests.structural.coordinating_epics_rig import Rig

HOST = "acme/widgets"
EPIC = 10
SIB = 20

PARENT = """\
- **Last check-in:** 2026-10-01T09:00Z
- **Last issue seen:** #30

## Children

- [ ] #12 the child, closed on 11-03
- [ ] #13 open in both
- [x] #14 ticked in both
- [ ] #15 only here
- Ordered from acme/widgets#20, the backlog epic
"""

BACKLOG = """\
## Tier 1

- [x] #12 the child · [verified](https://github.com/acme/widgets/issues/12#issuecomment-1)
- [ ] #13 open in both
- [x] #14 ticked in both
- [ ] #16 only there
```
- [ ] #15 an example in a fence, no line
```
"""


def _rig(tmp_path, parent=PARENT, backlog=BACKLOG):
    r = Rig(tmp_path)
    r.issue(HOST, EPIC, body=parent, updated_at="2026-10-02T00:00:00Z")
    r.issue(HOST, SIB, body=backlog, updated_at="2026-09-30T00:00:00Z")
    old = "2026-09-30T00:00:00Z"
    for n, st in (
        (12, "closed"),
        (13, "open"),
        (14, "closed"),
        (15, "open"),
        (16, "open"),
    ):
        r.issue(HOST, n, state=st, updated_at=old, created_at=old)
    return r


def scan(r, *extra, rc=0, env=None):
    res = r.run("scan.sh", "--repo", HOST, "--epic", str(EPIC), *extra, extra_env=env)
    assert res.returncode == rc, res.stderr
    return json.loads(res.stdout) if rc == 0 else res


def by_child(rep):
    return {row["child"]: row for row in rep["cross_epic"]}


def test_660_a_child_ticked_on_one_epic_and_not_the_other_is_one_drift_row(tmp_path):
    """#660's red test, watcher's case in miniature."""
    rep = scan(_rig(tmp_path), "--sibling", f"{HOST}#{SIB}")
    rows = by_child(rep)
    assert set(rows) == {"acme/widgets#12", "acme/widgets#13", "acme/widgets#14"}
    twelve = rows["acme/widgets#12"]
    assert twelve["drift"] is True and twelve["state"] == "closed"
    assert twelve["here"] == {
        "ticked": False,
        "line": "- [ ] #12 the child, closed on 11-03",
    }
    assert twelve["sibling"]["epic"] == "acme/widgets#20"
    assert twelve["sibling"]["ticked"] is True
    assert [r["child"] for r in rep["cross_epic"] if r["drift"]] == ["acme/widgets#12"]
    assert rep["siblings"] == [{"epic": "acme/widgets#20", "items": 4, "shared": 3}]
    assert any("acme/widgets#12" in w and "drift" in w for w in rep["warnings"])


def test_660_without_sibling_the_report_has_no_new_keys(tmp_path):
    rep = scan(_rig(tmp_path))
    assert "cross_epic" not in rep and "siblings" not in rep


def test_660_lines_in_step_raise_no_warning(tmp_path):
    backlog = BACKLOG.replace("- [x] #12 the child", "- [ ] #12 the child")
    rep = scan(_rig(tmp_path, backlog=backlog), "--sibling", f"{HOST}#{SIB}")
    assert not [r for r in rep["cross_epic"] if r["drift"]]
    assert not [w for w in rep["warnings"] if "drift" in w]


def test_660_a_paired_lines_second_subject_is_a_child_too(tmp_path):
    """#662's parser: "- [x] #12 + #15" leads with both."""
    backlog = BACKLOG.replace("- [ ] #16 only there", "- [x] #16 + #15 a pair")
    rows = by_child(scan(_rig(tmp_path, backlog=backlog), "--sibling", f"{HOST}#{SIB}"))
    assert rows["acme/widgets#15"]["drift"] is True
    assert rows["acme/widgets#15"]["sibling"]["line"] == "- [x] #16 + #15 a pair"


def test_660_a_cross_repo_siblings_bare_ref_is_its_own_repos_issue(tmp_path):
    """A bare #12 on acme/gadgets#40 is acme/gadgets#12, not this repo's #12:
    keyed by the host, it would read as a shared child and a false drift."""
    r = _rig(tmp_path)
    r.issue("acme/gadgets", 40, body=BACKLOG)
    r.issue("acme/gadgets", 12, state="closed")
    rep = scan(r, "--sibling", "acme/gadgets#40")
    assert rep["cross_epic"] == []
    parent = PARENT + "- [ ] acme/gadgets#12 a sibling repo's child\n"
    (tmp_path / "x").mkdir()
    r = _rig(tmp_path / "x", parent=parent)
    r.issue("acme/gadgets", 40, body=BACKLOG)
    r.issue("acme/gadgets", 12, state="closed")
    rows = by_child(scan(r, "--sibling", "Acme/Gadgets#40"))
    assert set(rows) == {"acme/gadgets#12"}
    assert rows["acme/gadgets#12"]["state"] == "closed"
    assert rows["acme/gadgets#12"]["sibling"]["epic"] == "acme/gadgets#40"


def test_660_siblings_repeat_and_each_row_names_its_epic(tmp_path):
    r = _rig(tmp_path)
    r.issue(HOST, 21, body="- [x] #13 ticked here\n")
    rep = scan(r, "--sibling", f"{HOST}#{SIB}", "--sibling", f"{HOST}#21")
    thirteen = [x for x in rep["cross_epic"] if x["child"] == "acme/widgets#13"]
    assert [(x["sibling"]["epic"], x["drift"]) for x in thirteen] == [
        ("acme/widgets#20", False),
        ("acme/widgets#21", True),
    ]
    assert [s["epic"] for s in rep["siblings"]] == [
        "acme/widgets#20",
        "acme/widgets#21",
    ]


def test_660_an_unreadable_sibling_is_a_warning_naming_the_token(tmp_path):
    """Reporting only, so exit 0, but never read as 'no drift': the sibling is
    listed with its error, and the warning names the token to map (#520)."""
    r = _rig(tmp_path)
    install(r)
    r.issue("acme/private", 40, body=BACKLOG)
    r.set_flag("tokens", {"acme/private": "private-SECRET-5555"})
    env = {"GH_TOKEN_PRIVATE": "private-SECRET-5555"}
    rep = scan(r, "--sibling", "acme/private#40", env=env)
    assert rep["cross_epic"] == []
    assert rep["siblings"][0]["epic"] == "acme/private#40"
    assert "error" in rep["siblings"][0]
    assert any(
        "acme/private#40" in w and "--token-for acme/private=GH_TOKEN_PRIVATE" in w
        for w in rep["warnings"]
    )
    assert "private-SECRET-5555" not in json.dumps(rep)
    rep = scan(
        r,
        "--sibling",
        "acme/private#40",
        "--token-for",
        "acme/private=GH_TOKEN_PRIVATE",
        env=env,
    )
    assert rep["siblings"] == [{"epic": "acme/private#40", "items": 4, "shared": 0}]


def test_660_an_unread_childs_state_is_null_with_a_warning(tmp_path):
    r = _rig(tmp_path)
    r.set_flag("graphql_error", "HTTP 502: Bad Gateway")
    rep = scan(r, "--sibling", f"{HOST}#{SIB}")
    rows = by_child(rep)
    assert rows["acme/widgets#12"]["state"] is None
    assert rows["acme/widgets#12"]["drift"] is True
    assert any("state" in w and "502" in w for w in rep["warnings"])


def test_660_sibling_takes_owner_repo_number_and_never_the_epic_itself(tmp_path):
    r = _rig(tmp_path)
    for bad in (
        "acme/widgets",
        "#20",
        "acme/widgets#x",
        f"{HOST}#{EPIC}",
        "Acme/Widgets#10",
    ):
        res = r.run("scan.sh", "--repo", HOST, "--epic", str(EPIC), "--sibling", bad)
        assert res.returncode == 1, (bad, res.stderr)
        assert "--sibling" in res.stderr


def test_660_help_names_the_flag_and_its_keys(tmp_path):
    res = _rig(tmp_path).run("scan.sh", "--help")
    for word in ("--sibling", "cross_epic", "drift", "#660"):
        assert word in res.stdout, word
