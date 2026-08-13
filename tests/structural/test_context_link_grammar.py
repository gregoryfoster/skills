"""`extract_links()` in measure-context.sh must extract links, not link-shaped text (#147).

The extractor matched `\\]\\([^)]+\\)` — a bare `](…)` fragment with no `[label]`
in front of it, anywhere in the file including inside code. Two consequences,
both observed on this repo's own tree:

- Prose *about* links is extracted as links. `curating-context/SKILL.md`
  explains that a demoted block turns `` `](tests/x.py)` `` into
  `` `](../tests/x.py)` ``; the extractor reported four dead links from those
  two lines, so the skill's own SKILL.md could never satisfy the Phase 6
  assertion that `links.dead` is empty.
- A link inside a fenced block or a code span never renders as a link, so no
  reader can click it and it cannot be dead in any sense they experience.

`tests/structural/test_relative_links.py` (#143) settled the grammar for this
repo's own `skills/**/*.md`: a link is `[label](target)` outside code. It cannot
be shared with `measure-context.sh` — that script runs against a *consuming*
repo's tree — so the rule is re-stated here against the script's behaviour, and
the two are pinned to agree on the one file that motivated both.

The `#fragment` behaviour (#120, #124) is re-asserted rather than assumed: this
function has already lost anchor resolution once to an extraction change.

No API calls required.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CURATING = REPO_ROOT / "skills" / "curating-context"
MEASURE = CURATING / "scripts" / "measure-context.sh"


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for key in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR",
                "ANTHROPIC_API_KEY"):
        env.pop(key, None)
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, env=_clean_env(),
    )


def _repo(tmp_path: Path, policy: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "AGENTS.md").write_text(policy)
    (repo / "docs").mkdir()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _measure(repo: Path, *args: str) -> dict:
    result = subprocess.run(
        ["bash", str(MEASURE), "--no-write", *args],
        capture_output=True, text=True, cwd=str(repo),
        env=_clean_env(), timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _dead(repo: Path, *args: str) -> list[str]:
    return _measure(repo, *args)["links"]["dead"]


class TestALinkNeedsALabel:
    """`](target)` is a fragment of a link, not a link. A renderer shows it as
    literal text, so nothing about it can be dead."""

    def test_a_bare_bracket_paren_fragment_is_not_a_link(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\nrewrite ](docs/GONE.md) as ](../docs/GONE.md)\n")
        assert _dead(repo) == []

    def test_a_labelled_link_on_the_same_line_is_still_found(self, tmp_path: Path):
        """The discriminator is the label, not the line."""
        repo = _repo(
            tmp_path,
            "# P\n\nrewrite ](docs/GONE.md) — see [g](docs/ALSOGONE.md)\n",
        )
        assert _dead(repo) == ["AGENTS.md -> docs/ALSOGONE.md"]

    def test_an_empty_label_is_a_link(self, tmp_path: Path):
        """CommonMark permits `[](target)`; only the brackets are required."""
        repo = _repo(tmp_path, "# P\n\n[](docs/GONE.md)\n")
        assert _dead(repo) == ["AGENTS.md -> docs/GONE.md"]

    def test_an_image_is_a_link(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\n![alt](docs/diagram.png)\n")
        assert _dead(repo) == ["AGENTS.md -> docs/diagram.png"]


class TestLinksInsideCodeAreNotLinks:
    """A link inside a fence or a code span never renders as a link."""

    def test_a_link_inside_a_fence_is_not_extracted(self, tmp_path: Path):
        repo = _repo(
            tmp_path,
            "# P\n\n```md\n[g](docs/GONE.md)\n```\n",
        )
        assert _dead(repo) == []

    def test_a_tilde_fence_masks_a_backtick_fence_inside_it(self, tmp_path: Path):
        repo = _repo(
            tmp_path,
            "# P\n\n~~~md\n```\n[g](docs/GONE.md)\n```\n~~~\n",
        )
        assert _dead(repo) == []

    def test_an_info_string_does_not_close_a_fence(self, tmp_path: Path):
        repo = _repo(
            tmp_path,
            "# P\n\n```sh\n[g](docs/GONE.md)\n```python\n[h](docs/ALSO.md)\n```\n",
        )
        assert _dead(repo) == [], (
            "```python is an opening info string, not a close — everything "
            "between the first and last fence is code"
        )

    def test_a_link_after_a_closing_fence_is_still_found(self, tmp_path: Path):
        """Proves the mask closes. A fence that never reopens the scanner would
        turn the whole check off from its first code block onward."""
        repo = _repo(
            tmp_path,
            "# P\n\n```md\n[g](docs/INSIDE.md)\n```\n\n[h](docs/AFTER.md)\n",
        )
        assert _dead(repo) == ["AGENTS.md -> docs/AFTER.md"]

    def test_a_link_inside_a_code_span_is_not_extracted(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\nwrite `[g](docs/GONE.md)` to link it\n")
        assert _dead(repo) == []

    def test_a_code_span_may_wrap_a_line(self, tmp_path: Path):
        repo = _repo(
            tmp_path,
            "# P\n\nthe form is `[g](docs/GONE.md) and\n[h](docs/ALSO.md)` in full\n",
        )
        assert _dead(repo) == []

    def test_an_unpaired_backtick_does_not_mask_the_rest_of_the_file(
        self, tmp_path: Path
    ):
        """The load-bearing guard. Without a blank-line boundary a single stray
        backtick pairs with the next one hundreds of lines away and silently
        turns the check off in the files most likely to have drifted."""
        repo = _repo(
            tmp_path,
            "# P\n\na stray ` backtick\n\n[g](docs/GONE.md)\n\nand ` another\n",
        )
        assert _dead(repo) == ["AGENTS.md -> docs/GONE.md"]

    def test_a_code_span_in_a_label_leaves_the_link_checked(self, tmp_path: Path):
        """The trap: masking must blank a span's *contents*, not drop the span.
        Dropping it takes the label's brackets with it and the link vanishes —
        and `[`name`](path)` is this cohort's most common link shape."""
        repo = _repo(tmp_path, "# P\n\nSee [`docs/GONE.md`](docs/GONE.md).\n")
        assert _dead(repo) == ["AGENTS.md -> docs/GONE.md"]


class TestTheExtractorDoesNotFailQuietly:
    """A link extractor that returns nothing is indistinguishable from a clean
    run, so the two failure modes that could produce one are pinned."""

    def test_crlf_line_endings_do_not_wedge_the_fence_scanner(self, tmp_path: Path):
        """A trailing `\\r` left on a closing fence closes nothing, and every
        link after the first code block in the file goes unchecked."""
        repo = _repo(tmp_path, "")
        (repo / "AGENTS.md").write_bytes(
            b"# P\r\n\r\n```md\r\n[g](docs/INSIDE.md)\r\n```\r\n\r\n[h](docs/AFTER.md)\r\n"
        )
        assert _dead(repo) == ["AGENTS.md -> docs/AFTER.md"]

    def test_an_unreadable_source_warns_rather_than_reading_as_clean(
        self, tmp_path: Path
    ):
        """Scanned via the archival path, which is the one place a file is read
        for its links and for nothing else — so the extractor's own tolerance is
        what is under test, not the inventory's.
        """
        repo = _repo(tmp_path, "# P\n\n[g](docs/GUIDE.md)\n")
        (repo / "docs" / "GUIDE.md").write_text("# G\n")
        (repo / "docs" / "plans").mkdir()
        plan = repo / "docs" / "plans" / "2026-01-01-old.md"
        plan.write_text("# Plan\n\n[g](../GUIDE.md#gone)\n")
        plan.chmod(0o000)
        try:
            result = subprocess.run(
                ["bash", str(MEASURE), "--no-write"],
                capture_output=True, text=True, cwd=str(repo),
                env=_clean_env(), timeout=60,
            )
        finally:
            plan.chmod(0o644)
        assert result.returncode == 0, result.stderr
        assert (
            "WARN could not extract links from docs/plans/2026-01-01-old.md"
            in result.stderr
        ), result.stderr
        assert json.loads(result.stdout)["links"]["dead_anchors"] == [], (
            "the unreadable file contributes nothing — but it said so out loud"
        )


class TestFragmentsSurviveTheGrammarChange:
    """#120 and #124: the fragment is kept through extraction and resolved
    against the target's headings. An extraction rewrite is exactly how that was
    lost the first time."""

    def test_a_dead_anchor_on_a_live_file_is_still_reported(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\n[g](docs/GUIDE.md#gone)\n")
        (repo / "docs" / "GUIDE.md").write_text("# G\n\n## Kept\n")
        data = _measure(repo)
        assert data["links"]["dead"] == []
        assert data["links"]["dead_anchors"] == ["AGENTS.md -> docs/GUIDE.md#gone"]

    def test_a_live_anchor_is_still_clean(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\n[g](docs/GUIDE.md#kept)\n")
        (repo / "docs" / "GUIDE.md").write_text("# G\n\n## Kept\n")
        data = _measure(repo)
        assert data["links"]["dead"] == []
        assert data["links"]["dead_anchors"] == []

    def test_a_same_file_fragment_is_still_checked(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\n## Setup\n\n[a](#setup) and [b](#teardown)\n")
        data = _measure(repo)
        assert data["links"]["dead_anchors"] == ["AGENTS.md -> AGENTS.md#teardown"]

    def test_reachability_and_refs_still_follow_real_links(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\n[g](docs/GUIDE.md#kept)\n")
        (repo / "docs" / "GUIDE.md").write_text("# G\n\n## Kept\n")
        data = _measure(repo)
        assert data["links"]["refs"] == ["docs/GUIDE.md"]
        assert data["links"]["orphans"] == []

    def test_a_prose_target_is_still_dropped_whole(self, tmp_path: Path):
        """The `is_prose` guard still earns its place: this is a real link in
        rendered prose whose target is a naming convention, not a path."""
        repo = _repo(tmp_path, "# P\n\n[l](references/<name>.md#h)\n")
        data = _measure(repo)
        assert data["links"]["dead"] == []
        assert data["links"]["dead_anchors"] == []

    def test_an_absolute_url_is_still_dropped(self, tmp_path: Path):
        repo = _repo(
            tmp_path,
            "# P\n\n[a](https://example.com/x) [b](mailto:a@b.c) [c](//host/x)\n",
        )
        assert _dead(repo) == []


class TestCuratingContextSkillCanSatisfyItsOwnPhaseSix:
    """The acceptance test from #147. `curating-context/SKILL.md` reported four
    dead links — `tests/x.py`, `../tests/x.py`, `docs/X.md`, `X.md` — from the
    two lines that quote those very fragments in inline code while explaining
    that a demotion must re-aim them. The file was never the problem.

    Measured as the skill measures a consuming repo: SKILL.md as the policy
    file, with its `references/` tree beside it, which is the layout its own
    relative links are written against.
    """

    def _repo_from_skill(self, tmp_path: Path) -> Path:
        repo = _repo(tmp_path, (CURATING / "SKILL.md").read_text())
        shutil.copytree(CURATING / "references", repo / "references")
        return repo

    def test_no_dead_links(self, tmp_path: Path):
        dead = _dead(self._repo_from_skill(tmp_path))
        assert dead == [], (
            "curating-context/SKILL.md must be able to satisfy the Phase 6 "
            "assertion its own skill makes"
        )

    def test_it_agrees_with_the_python_gate_on_the_same_file(self, tmp_path: Path):
        """`test_relative_links.py` reports zero for this file. Two extractors
        disagreeing about what a link is, in the same repo, is the defect."""
        from tests.structural.test_relative_links import dead_links_in

        assert dead_links_in(CURATING / "SKILL.md", REPO_ROOT) == []
        assert self._dead_paths(tmp_path) == []

    def _dead_paths(self, tmp_path: Path) -> list[str]:
        return _dead(self._repo_from_skill(tmp_path))

    def test_the_real_links_are_still_found(self, tmp_path: Path):
        """Zero dead is worthless if it is zero links. The file's prose links
        into `references/` must all still be walked."""
        data = _measure(self._repo_from_skill(tmp_path))
        refs = set(data["links"]["refs"])
        assert "references/keep-cut-rubric.md" in refs
        assert "references/telemetry.md" in refs
        assert len(refs) >= 8, refs

    def test_a_real_dead_link_in_that_file_would_still_be_caught(
        self, tmp_path: Path
    ):
        """Mutation check: the file passes because it is clean, not because the
        extractor stopped looking at it."""
        repo = self._repo_from_skill(tmp_path)
        policy = repo / "AGENTS.md"
        policy.write_text(
            policy.read_text() + "\n\nSee [the rubric](references/NOT-THERE.md).\n"
        )
        assert _dead(repo) == ["AGENTS.md -> references/NOT-THERE.md"]
