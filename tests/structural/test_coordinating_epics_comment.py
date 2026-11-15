"""coordinating-epics: comment.sh lints a comment with the editor's rules, then posts it (#395).

Briefs, write-backs and closing notes go out as comments, and these went
wrong in live runs: a short ref that links nowhere (`watcher#348` for
`owner/watcher#348`), a bare `#N` after a qualified ref, a leftover `SUBn` or
`{{…}}`, an unexpanded `$VAR` from an unquoted heredoc, a comment link to the
wrong issue. epic-edit.sh's lint caught each in a body; comment.sh runs the
same lint over the whole comment before `gh api` posts it, then reads the
comment back. `--lint-file` lints a body with no issue, for a new epic before
`gh issue create`.
"""

from __future__ import annotations

import pytest

from tests.structural.coordinating_epics_gh_layer import install, output, token_calls
from tests.structural.coordinating_epics_rig import Rig, summary

REPO = "acme/widgets"
ISSUE = 12


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path)
    install(r)
    for n in (10, 11, 12, 13, 14):
        r.issue(REPO, n)
    r.issue("acme/watcher", 348)
    r.comment(REPO, 12, 555, body="the brief")
    return r


def body_file(rig, text: str, name: str = "comment.md"):
    p = rig.tmp / name
    p.write_text(text)
    return str(p)


def post(rig, text: str, *flags: str, env: dict | None = None):
    return rig.run(
        "comment.sh",
        "--repo",
        REPO,
        "--issue",
        str(ISSUE),
        "--body-file",
        body_file(rig, text),
        *flags,
        extra_env=env,
    )


def lint_file(rig, text: str, *flags: str):
    return rig.run(
        "comment.sh", "--repo", REPO, "--lint-file", body_file(rig, text), *flags
    )


def posts(rig) -> list[str]:
    return rig.load().get("posts", [])


# ---------------------------------------------------------------- #395's list

# Each failure #395 lists, as a live run wrote it.
FAILURES = {
    "short-ref": ("Waits on watcher#348's answer.", "short ref watcher#348"),
    "bare-after-qualified": (
        "Blocked by acme/watcher#348, #349 until the pin moves.",
        "bare #349 after acme/watcher#",
    ),
    "subn": ("Starts after SUB2 lands.", "SUBn placeholder"),
    "braces": ("Next: {{child}}.", "{{...}} placeholder"),
    "unexpanded-var": (
        "The report is at ${SCRATCH}/scan.json.",
        "unexpanded shell variable",
    ),
    "wrong-issue-link": (
        f"The [brief](https://github.com/{REPO}/issues/11#issuecomment-555) holds it.",
        "comment 555 isn't on #11",
    ),
}


@pytest.mark.parametrize("case", sorted(FAILURES))
def test_each_failure_395_lists_is_refused_and_nothing_is_posted(rig, case):
    text, finding = FAILURES[case]
    res = post(rig, f"## Changed since filed\n\n- {text}\n")
    assert res.returncode == 3, res.stderr
    assert finding in res.stderr, res.stderr
    assert posts(rig) == []
    assert summary(res)["posted"] is False and "refused" in summary(res)


@pytest.mark.parametrize("case", sorted(FAILURES))
def test_lint_file_refuses_the_same_body_with_no_issue(rig, case):
    text, finding = FAILURES[case]
    res = lint_file(rig, f"- {text}\n")
    assert res.returncode == 3, res.stderr
    assert finding in res.stderr
    assert posts(rig) == []


# ---------------------------------------------------------------- the post


CLEAN = """\
## Brief

Pick up #12. It waits on acme/watcher#348 (the pin), and the
[decision](https://github.com/acme/widgets/issues/12#issuecomment-555) holds.

```bash
bash "<scan.sh>" --repo acme/widgets --epic 10 > "$SCRATCH/scan.json"
```

| Ref | Note |
|---|---|
| `watcher#348` | quoted as code |
"""


def test_a_clean_comment_is_posted_and_read_back(rig):
    res = post(rig, CLEAN)
    assert res.returncode == 0, res.stderr
    s = summary(res)
    assert s["posted"] is True and s["readback"] == "matches"
    assert s["url"].startswith(
        f"https://github.com/{REPO}/issues/{ISSUE}#issuecomment-"
    )
    assert posts(rig) == [CLEAN]
    assert s["chars"] == len(CLEAN)


def test_a_fence_and_a_code_span_are_read_over_the_whole_body(rig):
    """fenced() and tabled() run over the whole comment: a fenced $SCRATCH and
    a spanned short ref are text, as in the editor (CR 290, #415)."""
    assert lint_file(rig, CLEAN).returncode == 0


@pytest.mark.parametrize("text", ["", "   \n\n\t\n"], ids=["empty", "whitespace"])
def test_an_empty_file_is_refused(rig, text):
    res = post(rig, text)
    assert res.returncode == 3 and "empty" in res.stderr, res.stderr
    assert posts(rig) == []


def test_a_body_over_githubs_cap_is_refused_before_posting(rig):
    res = post(rig, "x " * 33000)
    assert res.returncode == 3 and "65,536" in res.stderr, res.stderr
    assert posts(rig) == []


def test_a_secret_is_refused_without_echoing_it(rig):
    tok = "ghp_" + "A" * 36
    res = post(rig, f"use {tok} here\n")
    assert res.returncode == 3 and tok not in output(res)
    assert posts(rig) == []


def test_a_dry_run_lints_and_reads_the_issue_but_posts_nothing(rig):
    res = post(rig, CLEAN, "--dry-run")
    assert res.returncode == 0, res.stderr
    assert summary(res)["posted"] is False and summary(res)["dry_run"] is True
    assert posts(rig) == []


def test_a_dry_run_on_an_issue_that_isnt_there_is_exit_2(rig):
    res = rig.run(
        "comment.sh",
        "--repo",
        REPO,
        "--issue",
        "99",
        "--body-file",
        body_file(rig, CLEAN),
        "--dry-run",
    )
    assert res.returncode == 2 and "HTTP 404" in res.stderr


def test_lint_file_needs_no_issue_and_posts_nothing(rig):
    res = lint_file(rig, CLEAN)
    assert res.returncode == 0, res.stderr
    assert summary(res)["lint"] == "clean"
    assert posts(rig) == []
    assert not any(c[:3] == ["api", "-X", "POST"] for c in rig.load()["calls"])


@pytest.mark.parametrize(
    "args",
    [
        ["--repo", REPO],
        ["--repo", REPO, "--issue", "12"],
        ["--repo", REPO, "--body-file", "x.md"],
        ["--repo", REPO, "--lint-file", "x.md", "--issue", "12"],
        ["--repo", REPO, "--lint-file", "x.md", "--dry-run"],
        ["--repo", "not-a-repo", "--lint-file", "x.md"],
        ["--repo", REPO, "--issue", "12", "--body-file", "/nonexistent/x.md"],
    ],
    ids=[
        "no-mode",
        "no-body",
        "no-issue",
        "lint-with-issue",
        "lint-with-dry-run",
        "bad-repo",
        "missing-file",
    ],
)
def test_a_usage_error_is_exit_1_and_fetches_nothing(rig, args):
    res = rig.run("comment.sh", *args)
    assert res.returncode == 1, res.stderr
    assert rig.load().get("calls", []) == []


def test_help_names_the_modes_and_exit_codes(rig):
    res = rig.run("comment.sh", "--help")
    assert res.returncode == 0
    for word in ("--lint-file", "--dry-run", "--token-for", "exit codes", "65,536"):
        assert word in res.stdout, word


# ---------------------------------------------------------------- failures


def test_a_gh_failure_is_exit_2_and_shows_ghs_own_stderr(rig):
    """A gate script keeps gh's whole stderr, not its last line (#398, #410)."""
    rig.set_flag("fail_all", "HTTP 401: Bad credentials\nhint: run gh auth login")
    res = post(rig, "See #12.\n")
    assert res.returncode == 2
    assert "Bad credentials" in res.stderr and "hint: run gh auth login" in res.stderr
    assert posts(rig) == []


def test_a_post_github_refused_is_exit_2_with_its_whole_cause(rig):
    rig.set_flag("post_error", "HTTP 422: Validation Failed\nBody is too long")
    res = post(rig, "See #12.\n")
    assert res.returncode == 2, res.stderr
    assert "Validation Failed" in res.stderr and "Body is too long" in res.stderr
    assert summary(res)["posted"] is False


def test_a_failed_post_that_didnt_land_is_exit_2(rig):
    """A 502 can come back after GitHub stored the comment, so the issue's
    comments are read before calling it unposted."""
    rig.set_flag("post_error", "HTTP 502: Bad Gateway")
    res = post(rig, "See #12.\n")
    assert res.returncode == 2, res.stderr
    assert "nothing was posted" in res.stderr
    assert summary(res)["posted"] is False


def test_a_failed_post_that_landed_is_found_and_confirmed(rig):
    rig.set_flag("post_fails_after_apply", "HTTP 502: Bad Gateway")
    res = post(rig, "See #12.\n")
    assert res.returncode == 0, res.stderr
    assert "WARNING" in res.stderr and "landed" in res.stderr
    s = summary(res)
    assert s["posted"] is True and s["readback"] == "matches"


def test_a_failed_post_whose_landing_cant_be_read_is_exit_4(rig):
    rig.set_flag("post_error", "HTTP 502: Bad Gateway")
    rig.set_flag("fail_paths", {"/comments?": "HTTP 503: Service Unavailable"})
    res = post(rig, "See #12.\n")
    assert res.returncode == 4, res.stderr
    assert summary(res)["posted"] == "unknown"
    assert "Bad Gateway" in res.stderr and "Service Unavailable" in res.stderr
    assert "again" in res.stderr  # the way forward: don't post a duplicate


def test_a_read_back_that_differs_is_exit_4(rig):
    rig.set_flag("post_stores", "See #13.\n")
    res = post(rig, "See #12.\n")
    assert res.returncode == 4, res.stderr
    s = summary(res)
    assert s["posted"] is True and s["readback"] == "differs"
    assert s["url"] and "don't post it again" in res.stderr


def test_a_failed_read_back_is_exit_4(rig):
    rig.set_flag("comment_get_error", "HTTP 502: Bad Gateway\nretry later")
    res = post(rig, "See #12.\n")
    assert res.returncode == 4, res.stderr
    assert summary(res)["readback"] == "failed"
    assert "retry later" in res.stderr


# ---------------------------------------------------------------- tokens (#520)


def test_a_private_repo_is_posted_with_its_mapped_token(rig):
    rig.set_flag("tokens", {REPO: "widgets-SECRET-4444"})
    flags = ["--token-for", f"{REPO}=GH_TOKEN_WIDGETS"]
    res = post(
        rig, "See #12.\n", *flags, env={"GH_TOKEN_WIDGETS": "widgets-SECRET-4444"}
    )
    assert res.returncode == 0, res.stderr
    assert {t for _, t in token_calls(rig)} == {"widgets-SECRET-4444"}
    assert "widgets-SECRET-4444" not in output(res)


def test_a_missing_mapped_variable_is_exit_1_and_posts_nothing(rig):
    res = post(
        rig,
        "See #12.\n",
        "--token-for",
        f"{REPO}=GH_TOKEN_WIDGETS",
        env={"GH_TOKEN_WIDGETS": ""},
    )
    assert res.returncode == 1 and "GH_TOKEN_WIDGETS is empty" in res.stderr
    assert token_calls(rig) == []


def test_a_cross_repo_comment_link_names_the_token_to_map(rig):
    rig.issue("acme/private", 9)
    rig.comment("acme/private", 9, 777, body="x")
    rig.set_flag("tokens", {"acme/private": "private-SECRET-5555"})
    url = "https://github.com/acme/private/issues/9#issuecomment-777"
    env = {"GH_TOKEN_PRIVATE": "private-SECRET-5555"}
    res = post(rig, f"See [the ask]({url}).\n", env=env)
    assert res.returncode == 3
    assert (
        "GH_TOKEN_PRIVATE is set: pass --token-for acme/private=GH_TOKEN_PRIVATE"
        in res.stderr
    )
    res = post(
        rig,
        f"See [the ask]({url}).\n",
        "--token-for",
        "acme/private=GH_TOKEN_PRIVATE",
        env=env,
    )
    assert res.returncode == 0, res.stderr


# ---------------------------------------------------------------- creation


def test_lint_file_takes_the_new_issues_own_predicted_number(rig):
    """creation.md's chain lints the epic's body before `gh issue create`. A
    body that names its own number, the one it predicts, would otherwise be
    refused as above the repo's highest; --predicted names that one number."""
    text = "- **Next:** #12, brief on the issue\n\nThis epic is #15.\n"
    res = lint_file(rig, text)
    assert res.returncode == 3 and "#15 is above" in res.stderr, res.stderr
    assert lint_file(rig, text, "--predicted", "15").returncode == 0
    res = lint_file(rig, text.replace("#15", "#16"), "--predicted", "15")
    assert res.returncode == 3 and "#16 is above" in res.stderr


def test_predicted_is_only_for_lint_file(rig):
    res = post(rig, "See #12.\n", "--predicted", "15")
    assert res.returncode == 1 and rig.load().get("calls", []) == []
