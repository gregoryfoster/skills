"""Behavioral tests for doc-check.sh's `.skills/doc-sections` override.

Background ([#261](https://github.com/gregoryfoster/skills/issues/261)):
[#252](https://github.com/gregoryfoster/skills/issues/252) made SENSITIVE_PATHS
overridable per project via `.skills/doc-sensitive-paths`, and DOC_SECTIONS —
the advice printed on the exit-1 path, the one exit code that asks a human to
act — did not get the same treatment. A repo could tailor WHAT the gate watches
while the instructions for what to do about a hit stayed generic: a
worker-first service that binds no port was told to check its route table, and
its `docs/contracts/` hit — charters that sibling repos link and CI enforces —
could not be named at all. Those are two halves of one decision, and forking
the script to fix the second half opts the project out of every later matcher
fix, which is the fork #252 existed to remove.

Pinned here:

- **Replacement, in four copies.** `.skills/doc-sections` replaces the built-in
  DOC_SECTIONS wholesale, in every variant, and the hit output names which
  source it printed — "route table" under `built-in defaults` tells the reader
  exactly which file to add.
- **One grammar, one reader.** Blank lines and `#`-comment lines dropped,
  whitespace trimmed, a final line without a trailing newline kept — the same
  rules as the path list, because both files go through one helper. A `#`
  later in a line is content: advice cites issues.
- **Present-but-empty is exit 2**, checked up front like the path list, so the
  misconfiguration fails on the first run rather than the first hit.
- **The two files are independent.** Tailoring one leaves the other at its
  defaults. There is deliberately no dead-entry probe for advice: it is prose,
  not patterns, so the reader below is the simpler of the two.

Body parity across the four copies is `TestBodyParity`'s job in
test_doc_check_segment_match.py. The repo and runner helpers are imported from
there rather than copied, so both files build the same fixture and a change to
how a throwaway repo is made reaches every doc-check test at once.

No API calls. Self-contained: each test builds a throwaway git repo.
"""

from pathlib import Path

import pytest

from tests.structural.test_doc_check_segment_match import (
    CLICK_LIVE_TREE,
    VARIANTS,
    _git,
    _repo,
    _run,
    _write,
)

# The replicator shape from #261: the sensitive thing is a charter directory,
# and the right advice names the test that enforces it.
CHARTER_PATHS = "docs/contracts/\n"
CHARTER_ADVICE = "docs/contracts/: a charter changes with tests/test_boundaries.py\n"
DEFAULT_ADVICE_MARKER = "AGENTS.md: project structure"


def _commit_override(repo: Path, name: str, body: str) -> None:
    _write(repo, f".skills/{name}", body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"tailor {name}")


def _advice(stdout: str) -> str:
    """The bullets printed under the spot-check heading."""
    assert "Spot-check these doc sections" in stdout, stdout
    return stdout.split("Spot-check these doc sections", 1)[1]


class TestOverrideReplacesAdvice:
    @pytest.mark.parametrize("variant", VARIANTS)
    def test_every_variant_prints_the_tailored_sections(
        self, variant: str, tmp_path: Path
    ):
        """The bug that motivated #261 was in four copies; the fix has to be."""
        repo = _repo(
            tmp_path, ["README.md", "docs/contracts/ingest.md"], ["docs/contracts/ingest.md"]
        )
        _commit_override(repo, "doc-sensitive-paths", CHARTER_PATHS)
        _commit_override(repo, "doc-sections", CHARTER_ADVICE)
        result = _run(repo, variant)
        assert result.returncode == 1, (
            f"{variant}: docs/contracts/ changed and is listed; got exit "
            f"{result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        advice = _advice(result.stdout)
        assert "tests/test_boundaries.py" in advice, (
            f"{variant} must print the tailored advice:\n{result.stdout}"
        )
        assert "(advice: .skills/doc-sections)" in result.stdout, (
            f"{variant} must name the advice's source on the hit path:\n{result.stdout}"
        )

    def test_override_replaces_rather_than_extends(self, tmp_path: Path):
        """A default the override drops must stop printing — otherwise a repo
        with no route table cannot get rid of the line telling it to check one."""
        repo = _repo(tmp_path, ["README.md", "docs/contracts/ingest.md"], ["README.md"])
        _commit_override(repo, "doc-sections", CHARTER_ADVICE)
        result = _run(repo)
        assert result.returncode == 1, f"stderr: {result.stderr}"
        advice = _advice(result.stdout)
        assert DEFAULT_ADVICE_MARKER not in advice, (
            f"the built-in AGENTS.md line must not survive an override:\n{result.stdout}"
        )
        assert "README.md:" not in advice, (
            f"the built-in README.md line must not survive an override:\n{result.stdout}"
        )

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_defaults_survive_when_the_file_is_absent(
        self, variant: str, tmp_path: Path
    ):
        """No file → the variant's own advice, labelled as such."""
        repo = _repo(tmp_path, ["README.md"], ["README.md"])
        result = _run(repo, variant)
        assert result.returncode == 1, f"stderr: {result.stderr}"
        assert DEFAULT_ADVICE_MARKER in _advice(result.stdout), (
            f"{variant} must fall back to its built-in DOC_SECTIONS:\n{result.stdout}"
        )
        assert "(advice: built-in defaults)" in result.stdout, (
            f"{variant} must say the advice is the built-in default:\n{result.stdout}"
        )


class TestGrammar:
    def test_comments_blank_lines_and_padding_are_ignored(self, tmp_path: Path):
        repo = _repo(tmp_path, ["README.md"], ["README.md"])
        _commit_override(
            repo,
            "doc-sections",
            "# tailored for a worker-first service\n\n   docs/contracts/: see the charter   \n\n",
        )
        result = _run(repo)
        assert result.returncode == 1, f"stderr: {result.stderr}"
        advice = _advice(result.stdout)
        assert "  - docs/contracts/: see the charter\n" in advice, (
            f"the entry must print trimmed, as one bullet:\n{result.stdout}"
        )
        assert "tailored for" not in advice, (
            f"a #-comment line is not an entry:\n{result.stdout}"
        )

    def test_a_hash_later_in_the_line_is_content(self, tmp_path: Path):
        """Advice cites issues. Only a line that STARTS with # is a comment."""
        repo = _repo(tmp_path, ["README.md"], ["README.md"])
        _commit_override(repo, "doc-sections", "AGENTS.md: the worker section, per #75\n")
        result = _run(repo)
        assert result.returncode == 1, f"stderr: {result.stderr}"
        assert "per #75" in _advice(result.stdout), (
            f"a mid-line # must survive:\n{result.stdout}"
        )

    def test_a_final_line_without_a_trailing_newline_is_kept(self, tmp_path: Path):
        """The guard the path list carries: an editor that omits the final
        newline must not silently drop the last entry."""
        repo = _repo(tmp_path, ["README.md"], ["README.md"])
        _commit_override(repo, "doc-sections", "first: a\nlast: b")
        result = _run(repo)
        assert result.returncode == 1, f"stderr: {result.stderr}"
        advice = _advice(result.stdout)
        assert "first: a" in advice and "last: b" in advice, (
            f"both entries must print, newline or not:\n{result.stdout}"
        )

    def test_the_path_list_keeps_the_same_guard(self, tmp_path: Path):
        """One reader serves both files. This is the path-list side of the
        no-trailing-newline guard, pinned by behaviour so that factoring the
        reader out cannot have quietly cost the list its last entry."""
        repo = _repo(tmp_path, CLICK_LIVE_TREE, ["docs/other.md"])
        _commit_override(repo, "doc-sensitive-paths", "docs")
        result = _run(repo)
        assert result.returncode == 1, (
            "a one-line list without a trailing newline must still be a list; "
            f"got exit {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "docs/other.md" in result.stdout


class TestEmptyFile:
    def test_empty_sections_file_exits_two_on_a_hit(self, tmp_path: Path):
        """Advice that says nothing sends the reader nowhere — the same
        did-not-run verdict the path list gives an empty file."""
        repo = _repo(tmp_path, ["README.md"], ["README.md"])
        _commit_override(repo, "doc-sections", "# nothing yet\n\n")
        result = _run(repo)
        assert result.returncode == 2, (
            f"an empty override is a did-not-run; got exit {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "lists no sections" in result.stderr
        assert ".skills/doc-sections" in result.stderr

    def test_empty_sections_file_exits_two_even_when_nothing_changed(
        self, tmp_path: Path
    ):
        """Checked up front, like the path list: a misconfigured file fails on
        the first run, not on the first hit weeks later."""
        repo = _repo(tmp_path, CLICK_LIVE_TREE, ["docs/other.md"])
        _commit_override(repo, "doc-sections", "\n\n")
        result = _run(repo)
        assert result.returncode == 2, (
            "an empty .skills/doc-sections must fail even on a doc-neutral branch; "
            f"got exit {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "No sensitive paths changed" not in result.stdout, (
            "the green line must not appear alongside a did-not-run verdict"
        )


class TestIndependence:
    def test_tailoring_sections_alone_keeps_default_paths(self, tmp_path: Path):
        repo = _repo(tmp_path, CLICK_LIVE_TREE, ["src/co/cli.py"])
        _commit_override(repo, "doc-sections", CHARTER_ADVICE)
        result = _run(repo)
        assert result.returncode == 1, (
            f"src/ is a click default and must still fire; got exit {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "(list: built-in defaults)" in result.stdout
        assert "(advice: .skills/doc-sections)" in result.stdout

    def test_tailoring_paths_alone_keeps_default_advice(self, tmp_path: Path):
        repo = _repo(tmp_path, CLICK_LIVE_TREE, ["docs/other.md"])
        _commit_override(repo, "doc-sensitive-paths", "docs/\n")
        result = _run(repo)
        assert result.returncode == 1, f"stderr: {result.stderr}"
        assert "(list: .skills/doc-sensitive-paths)" in result.stdout
        assert "(advice: built-in defaults)" in result.stdout
        assert DEFAULT_ADVICE_MARKER in _advice(result.stdout)


class TestHelp:
    @pytest.mark.parametrize("variant", VARIANTS)
    def test_help_documents_the_sections_override(self, variant: str, tmp_path: Path):
        repo = _repo(tmp_path, ["README.md"], ["README.md"])
        result = _run(repo, variant, "--help")
        assert result.returncode == 0
        assert ".skills/doc-sections" in result.stdout, (
            f"{variant} --help must name the advice override:\n{result.stdout}"
        )
