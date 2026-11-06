"""`pr` mode: a closing keyword can't be retracted by editing a PR body (#565).

`references/pr-mode.md` § The PR pass invites a body edit "only if the scope
changed", and the likeliest change is an issue that failed the HARD-GATE after
the PR opened. Editing its `Closes #<n>` line out doesn't reliably unlink it:
GitHub kept the Development-sidebar link and closed the issue at the merge,
twice, in a consumer repo. A checklist imperative to a human ("Close #<n> once
they pass") closed one too, and neither a negation nor trailing punctuation
defeats the parser.

So the reference carries a grep to run over the body file before `gh pr
create` and before any body edit, and the post-merge pass checks that the
merge closed nothing outside the PR's `Closes` lines.

The grep is pinned by behaviour, not by its text: it is lifted from the
reference and run here, on the host's own `grep`, against the issue's cases.
That is what caught the issue's proposed pattern missing two forms GitHub also
honours, `owner/repo#<n>` and a full issue URL. Measured on BSD grep 2.6.0
(macOS `/usr/bin/grep`) and GNU grep 3.11: `\\b` works under `-E` on both.

No API calls. The `gh` fields the prose names were measured read-only against
this repo's own PR #178, whose body's "the tooling written to fix #167" put
#167 in its `closingIssuesReferences`. The closer query was run read-only on
2026-11-06 against issues 167, 101, 172 and 102, and named PRs 170, 106, 175
and 106: their `closedAt` trails `mergedAt` by one to two seconds, so a time
comparison was never the test (CR 1847).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from tests.utils.skill_loader import SKILLS_DIR

REF = SKILLS_DIR / "shipping-work" / "references" / "pr-mode.md"


def _text() -> str:
    return REF.read_text()


def _section(heading: str) -> str:
    text = _text()
    start = text.index(heading)
    nxt = text.find("\n## ", start + len(heading))
    return text[start : nxt if nxt != -1 else len(text)]


def _grep_pattern() -> str:
    """The pattern of the one `grep -niE '<pattern>'` the reference carries."""
    found = re.findall(r"grep -niE '([^']+)'", _text())
    assert len(found) == 1, f"expected one `grep -niE '...'` in {REF.name}: {found}"
    return found[0]


GREPS = [g for g in ("grep", "ggrep") if shutil.which(g)]

# The issue's own cases, verbatim in shape, with <n> as 12, then the two forms
# the proposed pattern missed.
MUST_HIT = [
    "Closes #12",
    "- [ ] Close #12 once they pass",
    "Closes #12?",
    "This doesn't close #12",
    "Fixes: #12",
    "fixed #12",
    "RESOLVES   #12",
    "Closes owner/repo#12",
    "Closes: owner/repo#12",
    "Closes https://github.com/owner/repo/issues/12",
]

# Not closing keywords to GitHub: `Refs`, a keyword not followed by the
# reference, and a word that merely contains one.
MUST_MISS = [
    "Refs #12",
    "closing #12",
    "See the close of #12 later",
    "enclosed #12",
    "prefixes #12",
]


@pytest.mark.parametrize("grep", GREPS)
@pytest.mark.parametrize("line", MUST_HIT)
def test_the_reference_grep_finds_every_closing_form(grep, line, tmp_path):
    body = tmp_path / "body.md"
    body.write_text(f"Summary.\n\n{line}\n")
    result = subprocess.run(
        [grep, "-niE", _grep_pattern(), str(body)], capture_output=True, text=True
    )
    assert result.returncode == 0, f"{grep} missed {line!r}: {result.stderr}"


@pytest.mark.parametrize("grep", GREPS)
@pytest.mark.parametrize("line", MUST_MISS)
def test_the_reference_grep_leaves_other_mentions_alone(grep, line, tmp_path):
    body = tmp_path / "body.md"
    body.write_text(f"Summary.\n\n{line}\n")
    result = subprocess.run(
        [grep, "-niE", _grep_pattern(), str(body)], capture_output=True, text=True
    )
    assert result.returncode == 1, f"{grep} flagged {line!r}: {result.stdout}"


def test_the_pr_pass_says_an_edit_cannot_retract_a_closing_keyword():
    pr_pass = _section("## The PR pass")
    assert "Development" in pr_pass, pr_pass
    assert re.search(r"cannot be retracted|can't be retracted", pr_pass), pr_pass
    assert re.search(r"[Bb]efore `gh pr create`", pr_pass), pr_pass
    assert "closingIssuesReferences" in pr_pass, pr_pass


def test_the_post_merge_pass_checks_nothing_else_was_closed():
    post = _section("## The post-merge pass")
    step3 = post.split("\n3. ", 1)[1].split("\n4. ", 1)[0]
    assert "reopen" in step3, step3


def test_the_post_merge_candidates_include_a_dropped_sidebar_link():
    """CR 1848: the PR pass says a link dropped in the Development sidebar is
    reopened by the post-merge pass, but `closingIssuesReferences` no longer
    lists it. The candidates are the issues closed around the merge (the
    search measured read-only against PR #106: 101, 102 and 104)."""
    post = _section("## The post-merge pass")
    step3 = post.split("\n3. ", 1)[1].split("\n4. ", 1)[0]
    assert re.search(
        r'gh issue list --state closed [^\n]*--search "closed:<mergedAt>\.\.<mergedAt\+5m>"',
        step3,
    ), step3
    assert not re.search(r"each number\s+`gh pr view <m> --json closingIssues", step3)
    assert re.search(r"[Rr]eopen each kept issue that isn't on a `Closes` line", step3)
    assert "post-merge pass reopens it" in _section("## The PR pass")


def test_the_post_merge_pass_asks_github_for_the_closer_and_compares_no_times():
    """CR 1847: "a second after `mergedAt`, measured" was wrong (one to two)."""
    post = _section("## The post-merge pass")
    step3 = post.split("\n3. ", 1)[1].split("\n4. ", 1)[0]
    assert "closedAt` is the merge's" not in step3, step3
    assert "a second after" not in step3, step3
    queries = re.findall(r"gh api graphql -f query='([^']+)'", step3)
    assert len(queries) == 1, step3
    query = queries[0]
    assert query.count("{") == query.count("}"), query
    assert "timelineItems(itemTypes:[CLOSED_EVENT]" in query, query
    assert "... on ClosedEvent{closer{" in query, query
    assert "... on PullRequest{number}" in query, query
    for var in ("$o", "$r", "$n"):
        assert var in query, (var, query)
    assert "-f o=<owner> -f r=<repo> -F n=<n>" in step3, step3


def _closer_jq() -> tuple[str, str]:
    """The post-merge pass's closer query and its `--jq` filter."""
    post = _section("## The post-merge pass")
    step3 = post.split("\n3. ", 1)[1].split("\n4. ", 1)[0]
    found = re.findall(r"gh api graphql -f query='([^']+)'[^\n]*--jq '([^']+)'", step3)
    assert len(found) == 1, step3
    return found[0]


# CR 1864: the query selected only `... on PullRequest{number}`, so a `Commit`
# closer (a commit message's keyword, landed on the default branch by the
# merge) printed an empty line and was dropped: the case the check exists for.
# A commit counts through the PR GitHub says brought it in. Measured read-only
# on 2026-11-06 against this repo: PR 175's branch commit 2025bca9 and its
# merge commit 2e1cf281 both list 175 in `associatedPullRequests`; #426's and
# #434's closers are commits pushed straight to main, which list none; #172's
# closer is PR 175; #470, closed by hand, has a null closer.
CLOSERS = {
    "pull request": ({"number": 175}, ["175"]),
    "commit the PR brought in": (
        {"associatedPullRequests": {"nodes": [{"number": 175}]}},
        ["175"],
    ),
    "commit pushed straight to the branch": (
        {"associatedPullRequests": {"nodes": []}},
        [],
    ),
    "manual close": (None, []),
}


def test_the_closer_query_asks_a_commit_for_its_pr():
    query, _ = _closer_jq()
    assert "... on Commit{associatedPullRequests(" in query, query


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
@pytest.mark.parametrize("case", sorted(CLOSERS))
def test_the_closer_filter_prints_the_pr_a_close_belongs_to(case):
    closer, expected = CLOSERS[case]
    _, jq = _closer_jq()
    payload = {
        "data": {
            "repository": {"issue": {"timelineItems": {"nodes": [{"closer": closer}]}}}
        }
    }
    result = subprocess.run(
        ["jq", "-r", jq],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == expected, result.stdout


def test_the_post_merge_pass_says_a_manual_close_is_not_this_prs():
    post = _section("## The post-merge pass")
    step3 = post.split("\n3. ", 1)[1].split("\n4. ", 1)[0]
    assert "manual close" in step3, step3


def test_the_refs_issues_close_after_the_reopen_check():
    """CR 1873: step 3 closed the `Refs` issues first, then reopened each kept
    issue not on a `Closes` line, so a `Refs` issue the merge closed through
    a retained sidebar link ended reopened though its deploy or check passed.
    The reopen check runs first; closing the `Refs` issues that passed comes
    last, so it stands."""
    post = _section("## The post-merge pass")
    step3 = post.split("\n3. ", 1)[1].split("\n4. ", 1)[0]
    reopen = step3.index("Reopen each kept issue")
    closes = [m.start() for m in re.finditer(r"[Cc]lose each `Refs` issue", step3)]
    assert closes, step3
    assert all(at > reopen for at in closes), step3
