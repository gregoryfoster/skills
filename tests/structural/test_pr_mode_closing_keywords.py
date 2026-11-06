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
#167 in its `closingIssuesReferences`.
"""

from __future__ import annotations

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
    assert "before `gh pr create`" in pr_pass, pr_pass
    assert "closingIssuesReferences" in pr_pass, pr_pass


def test_the_post_merge_pass_checks_nothing_else_was_closed():
    post = _section("## The post-merge pass")
    step3 = next(p for p in post.split("\n3. ")[1:2])
    step3 = step3.split("\n4. ")[0]
    assert "closingIssuesReferences" in step3, step3
    assert "reopen" in step3, step3
