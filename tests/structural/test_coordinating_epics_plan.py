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
