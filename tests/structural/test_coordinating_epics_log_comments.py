"""coordinating-epics: the log in comments, after #654, meets --account and re-runs.

#657: `--account` reads the body only, so after compaction an issue that only
a moved log line accounted for reads as unlisted. The fix is the recipe's:
each such disposition gets a line in a body section before the log moves.

#658: `log-comment`'s re-run match was by body, so two check-ins on one date
that logged identical text posted once. The editor now records each comment
it posts or tries to post, and a re-run matches only its own unfinished
attempt. A fake gh stands in for GitHub.
"""

from __future__ import annotations

import datetime as dt
import json

from tests.structural.coordinating_epics_rig import Rig, summary

REPO = "acme/widgets"
EPIC = 10

# An --account epic before compaction: #14 and #15 are accounted for only by
# log lines.
LOGGED = """\
# Burn-down

- **Last check-in:** 2026-11-14T09:00Z
- **Last issue seen:** #15

## Tier 1

- [ ] #11 first thing
- [ ] #12 second thing
- [ ] #13 third thing

## Log

- 2026-11-01: created.
- 2026-11-02: #14 out of epic: a docs typo, fixed in passing.
- 2026-11-03: #15 duplicate of #12.
"""

MOVED = "\n".join(LOGGED.split("## Log\n\n")[1].splitlines())
POINTER = (
    "Each check-in's entry is a comment on this epic, first line"
    " **Check-in log, <date>**."
)


def _rig(tmp_path, body=LOGGED):
    r = Rig(tmp_path)
    r.issue(REPO, EPIC, body=body)
    for n in (11, 12, 13, 14, 15):
        r.issue(REPO, n)
    res = r.edit(REPO, EPIC, [], "--adopt-live", "--account")
    assert res.returncode == 0, res.stderr  # the in-body log accounts for all
    return r


def _move_the_log(r):
    """compaction.md step 2's first call: the log, posted as a comment."""
    op = {
        "op": "log-comment",
        "text": MOVED,
        "date": "2026-11-01 to 2026-11-03, moved from the body",
    }
    res = r.edit(REPO, EPIC, [op], "--account")
    assert res.returncode == 0, res.stderr
    assert summary(res)["log_comments"][0]["posted"] is True


def test_657_an_issue_only_a_moved_log_line_accounted_for_is_refused_with_the_fix(
    tmp_path,
):
    """#657, verbatim: an issue mentioned only in a log line, compacted per
    the recipe, then --account. It refuses (exit 3), and the refusal names
    the way forward: a log comment doesn't count, a body line does."""
    r = _rig(tmp_path)
    _move_the_log(r)
    ops = [{"op": "replace-section", "heading": "Log", "text": POINTER}]
    res = r.edit(REPO, EPIC, ops, "--account")
    assert res.returncode == 3, res.stderr
    assert summary(res)["unlisted"] == [14, 15]
    assert "open issues the epic doesn't reference: #14, #15" in res.stderr
    assert "a log comment doesn't count" in res.stderr
    assert "## Out of epic" in res.stderr and "compaction.md" in res.stderr
    assert "## Log\n\n- 2026-11-01: created." in r.body(REPO, EPIC)  # unwritten


def test_657_the_recipes_dry_run_names_them_and_a_body_section_accounts_for_them(
    tmp_path,
):
    """The recipe's extra step: the --account dry run of the log-removing call
    names each issue only a log line held, and one line each in a body section,
    in the same call, makes the same --account pass."""
    r = _rig(tmp_path)
    _move_the_log(r)
    pointer = {"op": "replace-section", "heading": "Log", "text": POINTER}
    res = r.edit(REPO, EPIC, [pointer], "--account", "--dry-run")
    assert res.returncode == 3 and summary(res)["unlisted"] == [14, 15]
    section = {
        "op": "add-section",
        "heading": "Out of epic",
        "before": "Log",
        "text": "- #14 · out of epic: a docs typo, fixed in passing, 2026-11-02.\n"
        "- #15 · duplicate of #12, 2026-11-03.",
    }
    res = r.edit(REPO, EPIC, [section, pointer], "--account")
    assert res.returncode == 0, res.stderr
    body = r.body(REPO, EPIC)
    assert "## Out of epic\n\n- #14 · out of epic" in body
    assert body.rstrip().endswith(POINTER)
    s = summary(res)
    assert s["unlisted"] == [] and s["counts_after"] == s["counts_before"]


# ---------------------------------------------------------------- #658


def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


NO_CHANGE = {"op": "log-comment", "text": "No change. Next: #13."}


def _adopted(tmp_path):
    r = Rig(tmp_path)
    r.issue(REPO, EPIC, body=LOGGED, updated_at="2026-11-14T09:00:00Z")
    for n in (11, 12, 13, 14, 15):
        r.issue(REPO, n)
    res = r.edit(REPO, EPIC, [], "--adopt-live")
    assert res.returncode == 0, res.stderr
    r.set_flag("server_now", "2026-11-15T10:00:00Z")
    r.set_flag("post_bumps_issue", True)
    return r


def test_658_two_check_ins_on_one_date_with_identical_text_post_two_comments(
    tmp_path,
):
    """#658, verbatim: two calls on the same date with identical log-comment
    text post two comments. The log records every check-in, one that found
    nothing included."""
    r = _adopted(tmp_path)
    first = r.edit(REPO, EPIC, [NO_CHANGE])
    assert first.returncode == 0, first.stderr
    second = r.edit(REPO, EPIC, [NO_CHANGE])
    assert second.returncode == 0, second.stderr
    assert summary(second)["log_comments"][0]["posted"] is True
    want = f"**Check-in log, {_today()}**\n\nNo change. Next: #13."
    assert r.load()["posts"] == [want, want]
    urls = [summary(x)["log_comments"][0]["url"] for x in (first, second)]
    assert urls[0] != urls[1]


def test_658_a_rerun_after_exit_5_still_posts_nothing_twice(tmp_path):
    """#658, verbatim: a re-run after an exit 5 still posts nothing twice,
    both when the failed POST stored nothing and when it landed anyway."""
    r = _adopted(tmp_path)
    r.set_flag("fail_paths", {"POST": "HTTP 502: Bad Gateway"})
    assert r.edit(REPO, EPIC, [NO_CHANGE]).returncode == 5
    r.set_flag("fail_paths", {})
    res = r.edit(REPO, EPIC, [NO_CHANGE])  # nothing was stored: it posts
    assert res.returncode == 0 and summary(res)["log_comments"][0]["posted"] is True
    assert len(r.load()["posts"]) == 1

    r.set_flag("post_fails_after_apply", 1)
    assert r.edit(REPO, EPIC, [NO_CHANGE]).returncode == 5
    assert len(r.load()["posts"]) == 2  # stored, though gh said 502
    res = r.edit(REPO, EPIC, [NO_CHANGE])
    assert res.returncode == 0, res.stderr
    post = summary(res)["log_comments"][0]
    assert post["posted"] == "already"
    assert post["url"] == r.load()["repos"][REPO]["comments"][str(EPIC)][-1]["html_url"]
    assert len(r.load()["posts"]) == 2


def test_658_a_rerun_days_after_the_epic_last_moved_still_finds_its_comment(
    tmp_path,
):
    """#658's second edge: the re-run comes after a later comment moved the
    epic's updated_at more than two days on. The old window, two days before
    updated_at, no longer held the comment, and it posted again."""
    r = _adopted(tmp_path)
    r.set_flag("post_fails_after_apply", 1)
    assert r.edit(REPO, EPIC, [NO_CHANGE]).returncode == 5
    r.comment(
        REPO,
        EPIC,
        777,
        body="a sibling's note",
        created_at="2026-11-19T10:00:00Z",
        updated_at="2026-11-19T10:00:00Z",
    )
    r.issue(REPO, EPIC, updated_at="2026-11-19T10:00:00Z")
    res = r.edit(REPO, EPIC, [NO_CHANGE])
    assert res.returncode == 0, res.stderr
    assert summary(res)["log_comments"][0]["posted"] == "already"
    assert len(r.load()["posts"]) == 1


def test_658_each_attempt_is_recorded_beside_the_baseline(tmp_path):
    """Option 2: the editor records each comment it posts or tries to post,
    with a write id; a dry run records nothing."""
    r = _adopted(tmp_path)
    assert r.edit(REPO, EPIC, [NO_CHANGE], "--dry-run").returncode == 0
    path = r.state_dir / "acme" / "widgets" / str(EPIC) / "comments.jsonl"
    assert not path.exists()
    assert r.edit(REPO, EPIC, [NO_CHANGE]).returncode == 0
    recs = [json.loads(ln) for ln in path.read_text().splitlines()]
    assert [x["state"] for x in recs] == ["pending", "posted"]
    assert recs[0]["id"] == recs[1]["id"] and recs[1]["url"].endswith("-9901")
