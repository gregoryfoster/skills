"""coordinating-epics: scan.sh reports all three cursors, because one alone misses things.

archiver#300 finding 10: a follow-up that never mentioned the epic was found
only by the number watermark. The seventh run's finding 152: a reply on a
closed child was found only by `updated_at`. broker#80 finding 128: commits
with no issue number were found only by the commit range. This file pins each
cursor, plus the cross-repo refs (processor#24 F133), against a fake gh and a
throwaway git repo built with GIT_* scrubbed (docs/STYLE.md).
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from tests.structural.coordinating_epics_rig import Rig

REPO = "acme/widgets"
EPIC = 10

BODY = """\
- **Last check-in:** 2026-10-01T09:00Z
- **Last issue seen:** #14
- **Last verified SHA:** {sha}

## Tier 1

- [x] #11 shipped
- [ ] #12 next
- [ ] acme/gadgets#3 upstream fix

## Waits

- acme/private#9 their answer
- the [plan](docs/plan.md#2-steps) holds no ref
"""


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    ).stdout.strip()


@pytest.fixture
def checkout(tmp_path):
    repo = tmp_path / "checkout"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "a@b")
    git(repo, "config", "user.name", "Coder")
    for i, msg in enumerate(
        ["base", "fix: guard the cache (#12)", "chore: bump", "docs: tidy (#10)"]
    ):
        (repo / f"f{i}").write_text(str(i))
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", msg)
    return repo


@pytest.fixture
def rig(tmp_path, checkout):
    r = Rig(tmp_path)
    base = git(checkout, "rev-list", "--max-parents=0", "HEAD")
    r.base = base
    r.checkout = checkout
    r.issue(
        REPO, EPIC, body=BODY.format(sha=base[:9]), updated_at="2026-10-02T00:00:00Z"
    )
    r.issue(REPO, 11, state="closed", updated_at="2026-10-03T10:00:00Z", body="")
    r.issue(REPO, 12, updated_at="2026-09-30T00:00:00Z", body="")
    r.issue(REPO, 14, updated_at="2026-09-30T00:00:00Z", body="")
    r.issue(
        REPO,
        15,
        title="follow-up, no epic link",
        updated_at="2026-10-02T12:00:00Z",
        body="",
    )
    r.issue(
        REPO,
        16,
        title="its PR",
        pull_request={"url": "x"},
        updated_at="2026-10-02T13:00:00Z",
        body="Refs #10",
    )
    r.comment(
        REPO,
        11,
        701,
        created_at="2026-10-03T10:00:00Z",
        updated_at="2026-10-03T10:00:00Z",
    )
    r.comment(
        REPO,
        11,
        600,
        created_at="2026-09-20T10:00:00Z",
        updated_at="2026-10-03T09:00:00Z",
    )
    r.issue(
        "acme/gadgets",
        3,
        state="closed",
        updated_at="2026-10-02T08:00:00Z",
        closed_at="2026-10-02T08:00:00Z",
    )
    return r


def scan(rig, *extra):
    res = rig.run(
        "scan.sh",
        "--repo",
        REPO,
        "--epic",
        str(EPIC),
        "--git-dir",
        str(rig.checkout),
        "--ref",
        "main",
        "--no-fetch",
        *extra,
    )
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_cursors_come_from_the_epic_header(rig):
    r = scan(rig)
    assert r["cursors"]["since"] == "2026-10-01T09:00:00Z"
    assert r["cursors"]["watermark"] == 14
    assert rig.base.startswith(r["cursors"]["from_sha"])
    assert r["max_number"] == 16


def test_numbers_above_the_watermark_include_unlinked_issues_and_prs(rig):
    rows = {x["number"]: x for x in scan(rig)["new_numbers"]}
    assert sorted(rows) == [15, 16]
    assert rows[15]["kind"] == "issue" and not rows[15]["mentions_epic"]
    assert rows[16]["kind"] == "pr" and rows[16]["mentions_epic"]


def test_updates_since_carry_new_and_edited_comments_on_epic_items(rig):
    rows = {x["number"]: x for x in scan(rig)["updated_since"]}
    assert 10 not in rows and 12 not in rows
    closed = rows[11]
    assert closed["in_epic"] and closed["state"] == "closed"
    comments = {c["id"]: c for c in closed["new_comments"]}
    assert set(comments) == {600, 701}
    assert comments[600]["edited"] and not comments[701]["edited"]
    assert "new_comments" not in rows[15]


def test_the_commit_range_attributes_every_commit(rig):
    rows = scan(rig)["commits"]
    assert [c["attribution"] for c in rows] == ["epic", "unattributed", "child"]
    assert rows[2]["children"] == ["acme/widgets#12"]


def test_cross_repo_refs_carry_state_or_say_why_not(rig):
    r = scan(rig)
    cross = {x["ref"]: x for x in r["cross_repo"]}
    assert (
        cross["acme/gadgets#3"]["state"] == "closed"
        and cross["acme/gadgets#3"]["updated_since"]
    )
    assert "error" in cross["acme/private#9"]
    assert set(cross) == {"acme/gadgets#3", "acme/private#9"}
    assert any("acme/private#9" in w for w in r["warnings"])


def test_a_missing_cursor_is_skipped_loudly_not_guessed(rig):
    rig.issue(REPO, EPIC, body="## Tier 1\n\n- [ ] #12 next\n")
    r = scan(rig)
    assert (
        r["new_numbers"] is None and r["updated_since"] is None and r["commits"] is None
    )
    assert len(r["warnings"]) == 3


def test_explicit_cursors_override_the_header(rig):
    r = scan(rig, "--watermark", "15", "--since", "2026-10-03T09:30:00Z")
    assert [x["number"] for x in r["new_numbers"]] == [16]
    assert [x["number"] for x in r["updated_since"]] == [11]


def test_a_gh_failure_is_exit_2(rig):
    rig.set_flag("fail_all", "HTTP 401: Bad credentials")
    res = rig.run("scan.sh", "--repo", REPO, "--epic", str(EPIC), "--no-fetch")
    assert res.returncode == 2 and "Bad credentials" in res.stderr


def test_a_git_failure_costs_the_commit_cursor_only(rig, tmp_path):
    """CR 245: not a checkout, a missing ref or an unknown SHA keeps the rest."""
    res = rig.run(
        "scan.sh",
        "--repo",
        REPO,
        "--epic",
        str(EPIC),
        "--git-dir",
        str(tmp_path / "nowhere"),
        "--no-fetch",
    )
    assert res.returncode == 0, res.stderr
    r = json.loads(res.stdout)
    assert r["commits"] is None
    assert any(w.startswith("commit range not scanned") for w in r["warnings"])
    assert [x["number"] for x in r["new_numbers"]] == [15, 16]
