"""coordinating-epics: create-from-plan.sh creates a drafted epic's children, then the epic (#396).

Creation was the step most often redone by hand: a lookbehind missed
`SUB7/#8` (archiver#300 finding 1), the epic's own number went unchecked
against the body's prediction (watcher F11), and a cross-repo parent needed
children in several repos under one parent (watcher#368 F3). A fake gh
stands in for GitHub: no real issue is created.
"""

from __future__ import annotations

import json

import pytest

from tests.structural.coordinating_epics_rig import Rig, summary

HOST = "acme/widgets"
SIB = "acme/gadgets"

EPIC_BODY = """\
Cache warming across two repos. Done when SUB10 is live.

- **Last check-in:** 2026-11-15T09:00Z
- **Last issue seen:** SUB0

## Tier 1

- [ ] SUB1 cache layer
- [ ] SUB10 warm it, after SUB1
- [ ] SUB3 upstream half

## Log

Each check-in's entry is a comment on this epic, first line **Check-in log, <date>**.
"""

BODIES = {
    "epic.md": EPIC_BODY,
    "c1.md": "Part of SUB0. Blocks SUB10.\n",
    "c10.md": "Needs SUB1/#3 first.\n",
    "c3.md": "Upstream half of SUB0; needs SUB1.\n",
}


def _plan(tmp_path, **changes):
    for name, text in BODIES.items():
        (tmp_path / name).write_text(text)
    plan = {
        "epic": {"title": "Epic: cache warming", "body_file": "epic.md"},
        "children": [
            {"id": "SUB1", "title": "Cache layer", "body_file": "c1.md"},
            {
                "id": "SUB10",
                "title": "Warm it",
                "body_file": "c10.md",
                "after": ["SUB1"],
            },
            {
                "id": "SUB3",
                "repo": SIB,
                "title": "Upstream half",
                "body_file": "c3.md",
                "after": ["SUB1"],
            },
        ],
    }
    plan.update(changes)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    return path


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path)
    for n in range(1, 6):
        r.issue(HOST, n, created_at=f"2026-10-0{n}T00:00:00Z")
    for n in (1, 2):
        r.issue(SIB, n, created_at=f"2026-10-0{n}T00:00:00Z")
    r.set_flag("server_now", "2026-11-15T10:00:00Z")
    return r


def create(r, plan, *extra):
    return r.run(
        "create-from-plan.sh",
        "--repo",
        HOST,
        "--plan",
        str(plan),
        "--state-dir",
        str(r.state_dir),
        *extra,
    )


def _issue(r, repo, n):
    return r.load()["repos"][repo]["issues"][str(n)]


def test_396_creates_children_in_order_then_the_epic_and_substitutes_every_body(
    rig, tmp_path
):
    """#396, verbatim: children in dependency order, then placeholders
    substituted across every created body, the epic's number asserted, and
    the run ends in epic-edit.sh --adopt-live --lint-all."""
    res = create(rig, _plan(tmp_path))
    assert res.returncode == 0, res.stderr
    assert rig.load()["creates"] == [[HOST, 6], [HOST, 7], [SIB, 3], [HOST, 8]]
    epic = _issue(rig, HOST, 8)["body"]
    assert "- [ ] #6 cache layer\n- [ ] #7 warm it, after #6\n" in epic
    assert "- [ ] acme/gadgets#3 upstream half" in epic
    assert "- **Last issue seen:** #8" in epic and "SUB" not in epic
    # The other repo's own cursor line, the form #400 reads.
    assert "- **Last issue seen (acme/gadgets):** acme/gadgets#3" in epic
    assert _issue(rig, HOST, 6)["body"] == "Part of #8. Blocks #7.\n"
    assert _issue(rig, SIB, 3)["body"] == (
        "Upstream half of acme/widgets#8; needs acme/widgets#6.\n"
    )
    s = summary(res)
    assert s["epic"]["number"] == 8 and s["epic"]["predicted"] == 8
    assert s["adopt"]["exit"] == 0
    # The first log entry is a log-comment on the epic (#654).
    posts = rig.load()["posts"]
    assert len(posts) == 1 and posts[0].startswith("**Check-in log, ")
    assert "#6" in posts[0] and "acme/gadgets#3" in posts[0]
    assert (rig.state_dir / "acme" / "widgets" / "8" / "last-written.md").exists()


def test_396_substitution_is_token_bounded(rig, tmp_path):
    """archiver#300 finding 1: `SUB7/#8` was missed by a lookbehind. An id
    followed by a slash and a ref substitutes, and SUB1 is no prefix of SUB10."""
    res = create(rig, _plan(tmp_path))
    assert res.returncode == 0, res.stderr
    assert _issue(rig, HOST, 7)["body"] == "Needs #6/#3 first.\n"
    assert "#7 warm it" in _issue(rig, HOST, 8)["body"]  # not "#60"


def test_396_the_epics_number_is_checked_against_its_prediction(rig, tmp_path):
    """watcher F11: another issue took the predicted number. The epic's own
    refs are corrected from the plan before adoption, and the run says so."""
    rig.set_flag("create_skip_title", "Epic: cache warming")
    res = create(rig, _plan(tmp_path))
    assert res.returncode == 0, res.stderr
    s = summary(res)
    assert s["epic"] == dict(s["epic"], predicted=8, number=9, corrected=True)
    assert "- **Last issue seen:** #9" in _issue(rig, HOST, 9)["body"]
    assert _issue(rig, HOST, 6)["body"] == "Part of #9. Blocks #7.\n"
    assert "predicted #8" in res.stderr


def test_396_every_repo_is_checked_reachable_before_anything_is_created(rig, tmp_path):
    """watcher#368 F3: a cross-repo parent. Each child's repo is read first,
    with the token in use; one that can't be read creates nothing."""
    rig.set_flag("fail_paths", {"api repos/acme/gadgets": "HTTP 404: Not Found"})
    res = create(rig, _plan(tmp_path))
    assert res.returncode == 2 and "acme/gadgets" in res.stderr, res.stderr
    assert "creates" not in rig.load()


def test_396_a_repo_without_issues_is_refused_before_anything(rig, tmp_path):
    rig.load()
    rig.state["repos"][SIB]["has_issues"] = False
    rig.save()
    res = create(rig, _plan(tmp_path))
    assert res.returncode == 3 and "issues" in res.stderr, res.stderr
    assert "creates" not in rig.load()


def test_396_every_body_is_linted_before_anything_is_created(rig, tmp_path):
    """comment.sh --lint-file's rules, on a preview with predicted numbers."""
    plan = _plan(tmp_path)
    (tmp_path / "c3.md").write_text("Upstream half of SUB0; see watcher#368.\n")
    res = create(rig, plan)
    assert res.returncode == 3 and "short ref watcher#368" in res.stderr, res.stderr
    assert "c3.md" in res.stderr
    assert "creates" not in rig.load()


def test_396_a_rerun_resumes_from_the_state_file(rig, tmp_path):
    """A state file keyed by local id: the re-run creates only what's left."""
    plan = _plan(tmp_path)
    rig.set_flag(
        "fail_paths", {"gadgets/issues --input": "HTTP 422: Validation Failed"}
    )
    res = create(rig, plan)
    assert res.returncode == 2, res.stderr
    assert rig.load()["creates"] == [[HOST, 6], [HOST, 7]]
    rig.set_flag("fail_paths", {})
    res = create(rig, plan)
    assert res.returncode == 0, res.stderr
    assert rig.load()["creates"] == [[HOST, 6], [HOST, 7], [SIB, 3], [HOST, 8]]
    s = summary(res)
    assert [c["created"] for c in s["children"]] == ["already", "already", True]


def test_396_a_create_that_failed_after_github_stored_it_is_found_not_repeated(
    rig, tmp_path
):
    """comment.sh's 502 rule: a create can come back failed after GitHub
    stored the issue. It is found by its title and body above the number
    read before it, and not created twice."""
    rig.set_flag("create_fails_after_apply", 1)
    res = create(rig, _plan(tmp_path))
    assert res.returncode == 0, res.stderr
    assert rig.load()["creates"] == [[HOST, 6], [HOST, 7], [SIB, 3], [HOST, 8]]
    assert summary(res)["children"][0]["created"] == "found"
    assert "502" in res.stderr


def test_396_a_dry_run_creates_nothing_and_shows_the_order(rig, tmp_path):
    res = create(rig, _plan(tmp_path), "--dry-run")
    assert res.returncode == 0, res.stderr
    s = summary(res)
    assert [(c["id"], c["predicted"]) for c in s["children"]] == [
        ("SUB1", "#6"),
        ("SUB10", "#7"),
        ("SUB3", "acme/gadgets#3"),
    ]
    assert s["epic"]["predicted"] == 8
    assert "creates" not in rig.load() and "posts" not in rig.load()


@pytest.mark.parametrize(
    "change, why",
    [
        ({"children": [{"id": "S1", "title": "x", "body_file": "c1.md"}]}, "SUBn"),
        (
            {
                "children": [
                    {
                        "id": "SUB1",
                        "title": "x",
                        "body_file": "c1.md",
                        "after": ["SUB1"],
                    }
                ]
            },
            "cycle",
        ),
        (
            {
                "children": [
                    {
                        "id": "SUB1",
                        "title": "x",
                        "body_file": "c1.md",
                        "after": ["SUB4"],
                    }
                ]
            },
            "SUB4",
        ),
        (
            {"children": [{"id": "SUB1", "title": "x", "body_file": "nope.md"}]},
            "nope.md",
        ),
    ],
    ids=["id-form", "cycle", "unknown-after", "missing-file"],
)
def test_396_a_malformed_plan_is_a_usage_error(rig, tmp_path, change, why):
    res = create(rig, _plan(tmp_path, **change))
    assert res.returncode == 1 and why in res.stderr, res.stderr
    assert "creates" not in rig.load()


def test_396_a_placeholder_no_plan_id_names_is_a_usage_error(rig, tmp_path):
    plan = _plan(tmp_path)
    (tmp_path / "c3.md").write_text("Needs SUB9 and acme/gadgets#SUB1.\n")
    res = create(rig, plan)
    assert res.returncode == 1, res.stderr
    assert "SUB9" in res.stderr and "acme/gadgets#SUB1" in res.stderr


def test_a_gh_failure_is_exit_2_and_shows_ghs_whole_stderr(rig, tmp_path):
    """The gate-script rule (#398): gh's stderr, every line of it, never its
    last line alone; with the token to try for the repo it couldn't read."""
    rig.set_flag(
        "fail_paths",
        {
            "gadgets/issues --input": "HTTP 502: Bad Gateway\ngh: upstream said: try later"
        },
    )
    res = create(rig, _plan(tmp_path))
    assert res.returncode == 2, res.stderr
    assert "HTTP 502: Bad Gateway" in res.stderr and "upstream said" in res.stderr
    st = json.loads((tmp_path / "plan.json.state.json").read_text())
    assert st["items"]["SUB3"]["state"] == "pending"  # the re-run looks first


# ---------------------------------------------------------------- CR 2224–2236


def test_cr2224_a_state_file_that_disagrees_with_the_plan_is_a_usage_error(
    rig, tmp_path
):
    """A child the state records in one repo, which the plan now puts in
    another, would be read and patched in the wrong repo."""
    plan = _plan(tmp_path)
    assert create(rig, plan).returncode == 0
    p = json.loads(plan.read_text())
    p["children"][2]["repo"] = HOST
    plan.write_text(json.dumps(p))
    res = create(rig, plan)
    assert res.returncode == 1 and "SUB3" in res.stderr and SIB in res.stderr, (
        res.stderr
    )
    other = rig.run(
        "create-from-plan.sh",
        "--repo",
        SIB,
        "--plan",
        str(plan),
        "--state",
        str(tmp_path / "plan.json.state.json"),
    )
    assert other.returncode == 1 and HOST in other.stderr, other.stderr


def test_cr2225_a_pending_create_is_found_by_its_recorded_title_past_one_page(
    rig, tmp_path
):
    """The stored issue is looked for by the title and body sent, and past
    the newest 100 issues."""
    plan = _plan(tmp_path)
    rig.set_flag("create_fails_after_apply", 1)
    rig.set_flag("fail_paths", {"direction=desc&per_page=100": "HTTP 502: Bad Gateway"})
    assert create(rig, plan).returncode == 2  # stored, and the lookup failed
    rig.set_flag("fail_paths", {})
    for n in range(7, 120):  # a busy repo since
        rig.issue(HOST, n, created_at="2026-11-16T00:00:00Z")
    p = json.loads(plan.read_text())
    p["children"][0]["title"] = "Cache layer, renamed"
    plan.write_text(json.dumps(p))
    res = create(rig, plan)
    assert res.returncode == 0, res.stderr
    assert [c for c in rig.load()["creates"] if c[0] == HOST][0] == [HOST, 6]
    assert summary(res)["children"][0] == dict(
        summary(res)["children"][0], number=6, created="found"
    )


def test_cr2226_a_failed_adoption_is_exit_6_with_epic_edits_code(rig, tmp_path):
    """Exit 1 and 3 mean nothing was created; after creation, epic-edit's
    refusal is its own code in the summary, and this script's is 6."""
    (tmp_path / "x").mkdir()
    plan = _plan(tmp_path)
    rig.set_flag("fail_paths", {"issues/8/comments --input": "HTTP 422: Unprocessable"})
    res = create(rig, plan)
    assert res.returncode == 6, res.stderr
    assert summary(res)["adopt"]["exit"] == 5


def test_cr2228_a_childs_repo_spelled_like_the_hosts_is_the_host(rig, tmp_path):
    p = _plan(tmp_path)
    plan = json.loads(p.read_text())
    plan["children"][0]["repo"] = "Acme/Widgets"
    p.write_text(json.dumps(plan))
    res = create(rig, p)
    assert res.returncode == 0, res.stderr
    epic = _issue(rig, HOST, 8)["body"]
    assert "Last issue seen (Acme/Widgets)" not in epic and "- [ ] #6 cache" in epic


def test_cr2229_a_pending_epic_found_on_the_rerun_is_not_corrected(rig, tmp_path):
    plan = _plan(tmp_path)
    rig.set_flag("create_fails_after_apply", 0)
    rig.set_flag("fail_paths", {"direction=desc&per_page=100": "HTTP 502: Bad Gateway"})
    rig.load()
    # Only the epic's create stores and fails: the children go through first.
    rig.state["create_fail_title"] = "Epic: cache warming"
    rig.save()
    res = create(rig, plan)
    assert res.returncode == 2, res.stderr
    rig.set_flag("fail_paths", {})
    res = create(rig, plan)
    assert res.returncode == 0, res.stderr
    e = summary(res)["epic"]
    assert e["number"] == 8 and e["created"] == "found" and e["corrected"] is False
    assert "predicted" not in res.stderr


def test_cr2230_a_rerun_after_adoption_touches_nothing(rig, tmp_path):
    plan = _plan(tmp_path)
    assert create(rig, plan).returncode == 0
    before = len(rig.load()["calls"])
    rig.issue(SIB, 3, body="A person wrote SUB1 here later.\n")
    res = create(rig, plan)
    assert res.returncode == 0, res.stderr
    calls = rig.load()["calls"][before:]
    assert not [c for c in calls if "PATCH" in c or "POST" in c]
    assert _issue(rig, SIB, 3)["body"] == "A person wrote SUB1 here later.\n"


def test_cr2231_ids_in_code_stay_and_one_in_a_link_is_refused(rig, tmp_path):
    """A fenced example renders as written, so its id stays (and isn't an
    unknown id); one in a code span stays too, which the lint refuses, as it
    refuses a SUBn left anywhere; one inside a link would break it."""
    plan = _plan(tmp_path)
    (tmp_path / "c3.md").write_text(
        "Upstream half of SUB0.\n\n```\nexample: SUB9\n```\n"
    )
    assert create(rig, plan, "--dry-run").returncode == 0
    (tmp_path / "c3.md").write_text("Upstream half of SUB0. See `SUB1`.\n")
    res = create(rig, plan, "--dry-run")
    assert res.returncode == 3 and "SUBn" in res.stderr, res.stderr
    (tmp_path / "c3.md").write_text(
        "See https://github.com/acme/widgets/issues/SUB1.\n"
    )
    res = create(rig, plan, "--dry-run")
    assert res.returncode == 1 and "link" in res.stderr, res.stderr
    assert "creates" not in rig.load()


def test_cr2234_a_fenced_cursor_line_doesnt_count_as_the_header(rig, tmp_path):
    p = _plan(tmp_path)
    (tmp_path / "epic.md").write_text(
        EPIC_BODY + "\n```\n- **Last issue seen (acme/gadgets):** acme/gadgets#1\n```\n"
    )
    assert create(rig, p).returncode == 0
    epic = _issue(rig, HOST, 8)["body"]
    assert "- **Last issue seen (acme/gadgets):** acme/gadgets#3\n" in epic
