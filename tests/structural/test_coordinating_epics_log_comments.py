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
