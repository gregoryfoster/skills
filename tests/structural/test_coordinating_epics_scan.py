"""coordinating-epics: scan.sh reports all three cursors, because one alone misses things.

archiver#300 finding 10: a follow-up that never mentioned the epic was found
only by the number watermark. The seventh run's finding 152: a reply on a
closed child was found only by `updated_at`. broker#80 finding 128: commits
with no issue number were found only by the commit range. This file pins each
cursor, plus the cross-repo refs (processor#24 F133), against a fake gh and a
throwaway git repo built with GIT_* scrubbed (docs/STYLE.md).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess

import pytest

from tests.structural.coordinating_epics_rig import SCRIPTS, Rig

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
        [
            "base",
            "fix: guard the cache (#12)",
            "chore: bump",
            "docs: tidy (#10)",
            "feat: cache warmer (#16)",
        ]
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
    r.pr(REPO, 16, [12])
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


def test_the_first_header_line_wins_over_a_later_one(rig):
    """CR 295: a log line quoting an old cursor isn't the cursor."""
    body = rig.body(REPO, EPIC) + "\n## Log\n\n- **Last check-in:** 2026-09-01T00:00Z\n"
    rig.issue(REPO, EPIC, body=body)
    assert scan(rig)["cursors"]["since"] == "2026-10-01T09:00:00Z"


def test_a_bots_commit_is_attributed_to_the_bot(rig):
    """CR 295."""
    (rig.checkout / "bot").write_text("b")
    git(rig.checkout, "add", ".")
    git(
        rig.checkout,
        "-c",
        "user.name=dependabot[bot]",
        "commit",
        "-q",
        "-m",
        "chore: bump a dependency",
    )
    assert scan(rig)["commits"][0]["attribution"] == "bot"


def test_now_is_githubs_clock_not_this_machines(rig):
    """CR 301: now becomes the next window's since, which GitHub compares with its own clock."""
    rig.set_flag("server_date", "Tue, 13 Oct 2026 07:05:09 GMT")
    r = scan(rig)
    assert r["now"] == "2026-10-13T07:05:09Z"
    assert not any("Date header" in w for w in r["warnings"])
    rig.set_flag("server_date", "not a date")
    r = scan(rig)
    assert any("Date header" in w for w in r["warnings"]), r["warnings"]


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
    assert [c["attribution"] for c in rows] == [
        "child",
        "epic",
        "unattributed",
        "child",
    ]
    assert rows[3]["children"] == ["acme/widgets#12"] and rows[3]["via_pr"] == []
    # CR 257: a squash commit cites its PR; the child is what the PR closes.
    assert rows[0]["children"] == ["acme/widgets#12"]
    assert rows[0]["via_pr"] == ["acme/widgets#16"]


def test_an_issue_url_is_a_ref_as_github_renders_it(rig):
    """CR 288: a bare or <angled> issue URL mentions the issue, and closes it."""
    rig.issue(
        REPO,
        17,
        updated_at="2026-10-02T14:00:00Z",
        body=f"Part of https://github.com/{REPO}/issues/10",
    )
    rig.issue(
        REPO,
        18,
        updated_at="2026-10-02T14:00:00Z",
        body=f"<https://github.com/{REPO}/issues/10>",
    )
    (rig.checkout / "url").write_text("u")
    git(rig.checkout, "add", ".")
    git(
        rig.checkout,
        "commit",
        "-q",
        "-m",
        "fix: x",
        "-m",
        f"Fixes https://github.com/{REPO}/issues/12",
    )
    r = scan(rig)
    rows = {x["number"]: x for x in r["new_numbers"]}
    assert rows[17]["mentions_epic"] and rows[18]["mentions_epic"]
    last = r["commits"][0]
    assert last["attribution"] == "child" and last["children"] == ["acme/widgets#12"]


def test_new_comments_on_the_epic_itself_are_reported(rig):
    """CR 289: siblings.md sends a sibling coordinator's note to the epic's comments."""
    rig.comment(
        REPO,
        EPIC,
        801,
        created_at="2026-10-02T11:00:00Z",
        updated_at="2026-10-02T11:00:00Z",
    )
    rig.comment(
        REPO,
        EPIC,
        501,
        created_at="2026-09-01T11:00:00Z",
        updated_at="2026-09-01T11:00:00Z",
    )
    r = scan(rig)
    assert [c["id"] for c in r["epic_comments"]] == [801]
    assert 10 not in {x["number"] for x in r["updated_since"]}
    assert scan(rig, "--since", "2099-01-01T00:00Z")["epic_comments"] == []


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
    assert r["epic_comments"] is None
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
    nowhere = str(tmp_path / "nowhere")
    res = rig.run(
        "scan.sh",
        "--repo",
        REPO,
        "--epic",
        str(EPIC),
        "--git-dir",
        nowhere,
        "--no-fetch",
    )
    assert res.returncode == 0, res.stderr
    r = json.loads(res.stdout)
    assert r["commits"] is None
    lost = [w for w in r["warnings"] if w.startswith("commit range not scanned")]
    # git's own stderr is in the warning, not just our prefix (#398): a
    # report that names no cause is a producer swallowed. git's message names
    # the directory and our prefix never does; "fatal:" would be no proof,
    # since git translates it (CR 321).
    assert lost and nowhere in lost[0], r["warnings"]
    assert [x["number"] for x in r["new_numbers"]] == [15, 16]


def test_a_usage_error_exits_1(rig):
    res = rig.run("scan.sh", "--repo", "not-a-repo", "--epic", str(EPIC))
    assert res.returncode == 1 and "owner/repo" in res.stderr


def test_since_is_converted_to_utc_z_and_a_naive_time_is_refused(rig):
    """CR 256: an offset reaches GitHub as `…Z`; a time with no zone is a usage error."""
    r = scan(rig, "--since", "2026-10-03T11:30+02:00")
    assert r["cursors"]["since"] == "2026-10-03T09:30:00Z"
    assert [x["number"] for x in r["updated_since"]] == [11]
    calls = [c for c in rig.load()["calls"] if any("since=" in a for a in c)]
    assert calls and all("since=2026-10-03T09:30:00Z" in " ".join(c) for c in calls)
    res = rig.run(
        "scan.sh", "--repo", REPO, "--epic", str(EPIC), "--since", "2026-10-03T09:30"
    )
    assert res.returncode == 1 and "time zone" in res.stderr


def test_a_page_cap_is_a_warning_not_a_silent_cut(rig, monkeypatch, capsys):
    """CR 259: 101 updated issues against a one-page cap."""
    for n in range(100, 201):
        rig.issue(REPO, n, updated_at="2026-10-02T00:00:00Z", body="")
    spec = importlib.util.spec_from_file_location("_scan", SCRIPTS / "_scan.py")
    scan_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scan_mod)
    monkeypatch.setattr(scan_mod, "MAX_PAGES", 1)
    for k, v in rig.env().items():
        monkeypatch.setenv(k, v)
    assert (
        scan_mod.run(
            [
                "--repo",
                REPO,
                "--epic",
                str(EPIC),
                "--no-fetch",
                "--git-dir",
                str(rig.checkout),
            ]
        )
        == 0
    )
    r = json.loads(capsys.readouterr().out)
    assert any("listing updates: stopped at 100 rows" in w for w in r["warnings"])
    assert r["capped"] == ["listing new numbers", "listing updates"]


def test_max_number_is_the_highest_seen_not_the_newest_created(rig):
    """CR 260: a transferred issue keeps its old created_at but takes a new number."""
    for n in (10, 11, 12, 14, 15, 16):
        rig.issue(REPO, n, created_at=f"2026-10-0{n % 9 + 1}T00:00:00Z")
    rig.issue(
        REPO,
        17,
        created_at="2025-01-01T00:00:00Z",
        updated_at="2026-10-04T00:00:00Z",
        body="",
    )
    r = scan(rig)
    assert r["max_number"] == 17
    assert 17 in [x["number"] for x in r["updated_since"]]


def test_an_inherited_git_variable_cant_aim_the_range_elsewhere(rig):
    """CR 261: any GIT_* from a hook or worktree is dropped, not just GIT_DIR."""
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
        extra_env={"GIT_OBJECT_DIRECTORY": str(rig.tmp / "no-objects")},
    )
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["commits"] is not None


@pytest.mark.parametrize(
    "value, since, warned",
    [
        ("2026-02-30T10:00Z", None, "not a valid time"),
        ("yesterday", None, "no ISO time"),
        ("2026-10-01T11:00+02:00", "2026-10-01T09:00:00Z", None),
    ],
)
def test_a_bad_header_time_is_a_warning_not_a_traceback(rig, value, since, warned):
    """CR 267."""
    rig.issue(
        REPO,
        EPIC,
        body=BODY.format(sha=rig.base[:9]).replace("2026-10-01T09:00Z", value),
    )
    r = scan(rig)
    assert r["cursors"]["since"] == since
    assert (warned is None) or any(warned in w for w in r["warnings"])


def test_git_keeps_auth_variables_and_never_prompts(monkeypatch):
    """CR 268: only repository-local variables go; auth ones stay."""
    spec = importlib.util.spec_from_file_location("_scan", SCRIPTS / "_scan.py")
    scan_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scan_mod)
    monkeypatch.setenv("GIT_DIR", "/elsewhere/.git")
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", "/elsewhere/objects")
    monkeypatch.setenv(
        "GIT_SHALLOW_FILE", "/elsewhere/shallow"
    )  # listed by git, not the floor
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /k")
    monkeypatch.setenv("GIT_ASKPASS", "/bin/askpass")
    # CR 303: `git -c` and GIT_CONFIG_KEY_n config can carry the fetch's auth.
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'http.extraheader'='X: y'")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "http.extraheader")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "AUTHORIZATION: basic x")
    env = scan_mod.git_env()
    assert env["GIT_CONFIG_PARAMETERS"] == "'http.extraheader'='X: y'"
    assert env["GIT_CONFIG_COUNT"] == "1" and "GIT_CONFIG_KEY_0" in env
    assert "GIT_DIR" not in env and "GIT_OBJECT_DIRECTORY" not in env
    assert "GIT_SHALLOW_FILE" not in env  # CR 285: the --local-env-vars query is used
    assert (
        env["GIT_SSH_COMMAND"] == "ssh -i /k" and env["GIT_ASKPASS"] == "/bin/askpass"
    )
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_a_pr_closing_another_repos_issue_isnt_this_repos_child(rig):
    """CR 273: the closing reference's repo comes from its own fields."""
    rig.pr(REPO, 16, ["other/repo#12"])
    rows = scan(rig)["commits"]
    assert rows[0]["attribution"] == "unattributed" and rows[0]["children"] == []


def test_another_repos_number_is_never_read_as_this_repos_pr(rig):
    """CR 295 (for 257): gadgets#16 is not widgets' PR #16, which closes #12."""
    (rig.checkout / "sync").write_text("s")
    git(rig.checkout, "add", ".")
    git(rig.checkout, "commit", "-q", "-m", "chore: sync with acme/gadgets#16")
    last = scan(rig)["commits"][0]
    assert last["attribution"] == "unattributed", last
    assert last["via_pr"] == [] and last["children"] == []


def test_a_pr_lookup_failure_is_a_warning(rig):
    """CR 273: only gh's own "not a PR" answer is read as one."""
    rig.set_flag("pr_error", "HTTP 403: API rate limit exceeded")
    r = scan(rig)
    assert r["commits"][0]["attribution"] == "unattributed"
    assert any("rate limit" in w for w in r["warnings"])


def test_git_missing_costs_the_commit_cursor_only(rig):
    """CR 279: no traceback, and the other cursors still report."""
    import shutil
    import sys

    minbin = rig.tmp / "minbin"
    minbin.mkdir()
    for tool, path in (
        ("bash", shutil.which("bash")),
        ("dirname", shutil.which("dirname")),
    ):
        (minbin / tool).symlink_to(path)
    (minbin / "python3").symlink_to(sys.executable)
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
        extra_env={"PATH": f"{rig.bin}:{minbin}"},
    )
    assert res.returncode == 0, res.stderr
    r = json.loads(res.stdout)
    assert r["commits"] is None and r["new_numbers"] is not None
    assert any("git could not run" in w for w in r["warnings"])
