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
  not patterns, so its reader is the simpler of the two.
- **A present-but-unusable file is exit 2, not a silent fallback.** Unreadable,
  a dangling symlink, a symlink loop, a directory or a FIFO in its place, or a
  `.skills` that is not a resolvable, searchable directory — each one had restored the
  built-in defaults with no error, or exited 1 in bash's own words. The FIFO is
  the sharp one: the classification runs before the open, and without it the
  gate blocks forever on a file it was asked to read. The callers test `-e || -L` so any
  shape reaches the reader, and the open is checked rather than guarded by an
  `-r` precondition, which is the pattern measure-context.sh settled for this
  class of bug (#184). A symlink that resolves still reads normally.

Body parity across the four copies is `TestBodyParity`'s job in
test_doc_check_segment_match.py. The repo builder and runner come from
doc_check_fixtures.py, shared with that file, so both build the same fixture.

No API calls. Self-contained: each test builds a throwaway git repo.
"""

import os
from pathlib import Path

import pytest

from tests.structural.doc_check_fixtures import (
    CLICK_LIVE_TREE,
    HANG_TIMEOUT_S,
    VARIANTS,
    make_repo,
    run_doc_check,
    run_git,
    write_file,
)

# The replicator shape from #261: the sensitive thing is a charter directory,
# and the right advice names the test that enforces it.
CHARTER_PATHS = "docs/contracts/\n"
CHARTER_ADVICE = "docs/contracts/: a charter changes with tests/test_boundaries.py\n"
DEFAULT_ADVICE_MARKER = "AGENTS.md: project structure"


def _commit_override(repo: Path, name: str, body: str) -> None:
    write_file(repo, f".skills/{name}", body)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", f"tailor {name}")


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
        repo = make_repo(
            tmp_path, ["README.md", "docs/contracts/ingest.md"], ["docs/contracts/ingest.md"]
        )
        _commit_override(repo, "doc-sensitive-paths", CHARTER_PATHS)
        _commit_override(repo, "doc-sections", CHARTER_ADVICE)
        result = run_doc_check(repo, variant)
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
        repo = make_repo(tmp_path, ["README.md", "docs/contracts/ingest.md"], ["README.md"])
        _commit_override(repo, "doc-sections", CHARTER_ADVICE)
        result = run_doc_check(repo)
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
        repo = make_repo(tmp_path, ["README.md"], ["README.md"])
        result = run_doc_check(repo, variant)
        assert result.returncode == 1, f"stderr: {result.stderr}"
        assert DEFAULT_ADVICE_MARKER in _advice(result.stdout), (
            f"{variant} must fall back to its built-in DOC_SECTIONS:\n{result.stdout}"
        )
        assert "(advice: built-in defaults)" in result.stdout, (
            f"{variant} must say the advice is the built-in default:\n{result.stdout}"
        )


class TestGrammar:
    def test_comments_blank_lines_and_padding_are_ignored(self, tmp_path: Path):
        repo = make_repo(tmp_path, ["README.md"], ["README.md"])
        _commit_override(
            repo,
            "doc-sections",
            "# tailored for a worker-first service\n\n   docs/contracts/: see the charter   \n\n",
        )
        result = run_doc_check(repo)
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
        repo = make_repo(tmp_path, ["README.md"], ["README.md"])
        _commit_override(repo, "doc-sections", "AGENTS.md: the worker section, per #75\n")
        result = run_doc_check(repo)
        assert result.returncode == 1, f"stderr: {result.stderr}"
        assert "per #75" in _advice(result.stdout), (
            f"a mid-line # must survive:\n{result.stdout}"
        )

    def test_a_final_line_without_a_trailing_newline_is_kept(self, tmp_path: Path):
        """The guard the path list carries: an editor that omits the final
        newline must not silently drop the last entry."""
        repo = make_repo(tmp_path, ["README.md"], ["README.md"])
        _commit_override(repo, "doc-sections", "first: a\nlast: b")
        result = run_doc_check(repo)
        assert result.returncode == 1, f"stderr: {result.stderr}"
        advice = _advice(result.stdout)
        assert "first: a" in advice and "last: b" in advice, (
            f"both entries must print, newline or not:\n{result.stdout}"
        )

    def test_the_path_list_keeps_the_same_guard(self, tmp_path: Path):
        """One reader serves both files. This is the path-list side of the
        no-trailing-newline guard, pinned by behaviour so that factoring the
        reader out cannot have quietly cost the list its last entry."""
        repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/other.md"])
        _commit_override(repo, "doc-sensitive-paths", "docs")
        result = run_doc_check(repo)
        assert result.returncode == 1, (
            "a one-line list without a trailing newline must still be a list; "
            f"got exit {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "docs/other.md" in result.stdout


class TestEmptyFile:
    def test_empty_sections_file_exits_two_on_a_hit(self, tmp_path: Path):
        """Advice that says nothing sends the reader nowhere — the same
        did-not-run verdict the path list gives an empty file."""
        repo = make_repo(tmp_path, ["README.md"], ["README.md"])
        _commit_override(repo, "doc-sections", "# nothing yet\n\n")
        result = run_doc_check(repo)
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
        repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/other.md"])
        _commit_override(repo, "doc-sections", "\n\n")
        result = run_doc_check(repo)
        assert result.returncode == 2, (
            "an empty .skills/doc-sections must fail even on a doc-neutral branch; "
            f"got exit {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "No sensitive paths changed" not in result.stdout, (
            "the green line must not appear alongside a did-not-run verdict"
        )


class TestIndependence:
    def test_tailoring_sections_alone_keeps_default_paths(self, tmp_path: Path):
        repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["src/co/cli.py"])
        _commit_override(repo, "doc-sections", CHARTER_ADVICE)
        result = run_doc_check(repo)
        assert result.returncode == 1, (
            f"src/ is a click default and must still fire; got exit {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "(list: built-in defaults)" in result.stdout
        assert "(advice: .skills/doc-sections)" in result.stdout

    def test_tailoring_paths_alone_keeps_default_advice(self, tmp_path: Path):
        repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/other.md"])
        _commit_override(repo, "doc-sensitive-paths", "docs/\n")
        result = run_doc_check(repo)
        assert result.returncode == 1, f"stderr: {result.stderr}"
        assert "(list: .skills/doc-sensitive-paths)" in result.stdout
        assert "(advice: built-in defaults)" in result.stdout
        assert DEFAULT_ADVICE_MARKER in _advice(result.stdout)


class TestHelp:
    @pytest.mark.parametrize("variant", VARIANTS)
    def test_help_documents_the_sections_override(self, variant: str, tmp_path: Path):
        repo = make_repo(tmp_path, ["README.md"], ["README.md"])
        result = run_doc_check(repo, variant, "--help")
        assert result.returncode == 0
        assert ".skills/doc-sections" in result.stdout, (
            f"{variant} --help must name the advice override:\n{result.stdout}"
        )
        assert "unreadable" in result.stdout, (
            f"{variant} --help must list an unreadable override under exit 2:\n"
            f"{result.stdout}"
        )


BOTH_FILES = ["doc-sensitive-paths", "doc-sections"]


class TestUnusableOverride:
    """A file the project committed but the script cannot use.

    The presence test was `-f`, which follows symlinks and so reads false for
    a dangling link, a symlink loop and a directory. Each of those restored
    the built-in defaults with no error — a committed tailoring vanishing
    silently, which is the #261 complaint one layer down. The callers now test
    `-e || -L` so a path present in any shape reaches the reader and is named.

    Nothing here depends on file modes, so none of it skips under root.
    """

    @pytest.mark.parametrize("name", BOTH_FILES)
    def test_a_dangling_symlink_is_exit_two(self, name: str, tmp_path: Path):
        """The realistic case: a monorepo points the file at a shared config
        and the target later moves."""
        repo = make_repo(tmp_path, ["README.md"], ["README.md"])
        rel = f".skills/{name}"
        (repo / ".skills").mkdir(parents=True, exist_ok=True)
        (repo / rel).symlink_to("../shared/gone")
        result = run_doc_check(repo)
        assert result.returncode == 2, (
            f"a dangling {rel} must not silently restore the defaults; got exit "
            f"{result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "does not resolve" in result.stderr, (
            f"the message must name the broken link:\n{result.stderr}"
        )
        assert "built-in defaults" not in result.stdout, (
            f"a broken link must not print as an untailored run:\n{result.stdout}"
        )

    def test_a_symlink_loop_is_exit_two(self, tmp_path: Path):
        """A loop stats as ELOOP, which is `-L` true and `-e` false — the same
        branch as a dangling link, and the same silent fallback before it."""
        repo = make_repo(tmp_path, ["README.md"], ["README.md"])
        (repo / ".skills").mkdir(parents=True, exist_ok=True)
        (repo / ".skills/doc-sections").symlink_to("doc-sections")
        result = run_doc_check(repo)
        assert result.returncode == 2, (
            f"a symlink loop is not an empty list; got exit {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "does not resolve" in result.stderr

    @pytest.mark.parametrize("name", BOTH_FILES)
    def test_a_directory_in_its_place_is_exit_two(self, name: str, tmp_path: Path):
        """A directory opens and reads as zero lines, so a checked open alone
        would call it an empty list. It is classified before the open."""
        repo = make_repo(tmp_path, ["README.md"], ["README.md"])
        (repo / ".skills" / name).mkdir(parents=True)
        result = run_doc_check(repo)
        assert result.returncode == 2, (
            f"a directory at .skills/{name} is a did-not-run; got exit "
            f"{result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "not a regular file" in result.stderr, (
            f"the message must name the shape, not blame an empty list:\n"
            f"{result.stderr}"
        )

    @pytest.mark.parametrize("name", BOTH_FILES)
    def test_a_fifo_is_refused_without_blocking(self, name: str, tmp_path: Path):
        """Opening a FIFO for reading blocks until a writer appears, so the
        not-a-regular-file branch is the only thing between a committed FIFO
        and a ship gate that hangs forever — no exit code, no message, nothing
        to report. Verified by removing that branch: the run had to be killed
        by a timeout. Every run in this suite is bounded (see
        RUN_TIMEOUT_S), so without the branch this fails loudly instead of
        wedging the suite."""
        repo = make_repo(tmp_path, ["README.md"], ["README.md"])
        (repo / ".skills").mkdir(parents=True, exist_ok=True)
        os.mkfifo(repo / ".skills" / name)
        # Tighter than RUN_TIMEOUT_S: the default is the ceiling for an unknown
        # hang, and this test knows exactly which one it provokes, in a script
        # that otherwise finishes in about a tenth of a second.
        result = run_doc_check(repo, timeout=HANG_TIMEOUT_S)
        assert result.returncode == 2, (
            f"a FIFO at .skills/{name} must be refused; got exit "
            f"{result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "not a regular file" in result.stderr

    @pytest.mark.parametrize("shape", ["dangling", "loop"])
    def test_a_skills_symlink_that_does_not_resolve_is_exit_two(
        self, shape: str, tmp_path: Path
    ):
        """The same defect as a dangling override FILE, one level up and
        missed for a round: the directory guard asked `-e`, which follows
        symlinks and reads false for both of these, so every lookup beneath
        failed and the built-in defaults came back with no error. Both go
        through `override_present` now, so the file and directory halves
        cannot drift apart again."""
        repo = make_repo(tmp_path, ["README.md"], ["README.md"])
        target = "/nonexistent-target-dir" if shape == "dangling" else ".skills"
        (repo / ".skills").symlink_to(target)
        result = run_doc_check(repo)
        assert result.returncode == 2, (
            f"a {shape} .skills symlink must not silently untailor the run; got "
            f"exit {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "does not resolve" in result.stderr, (
            f"the message must name the broken link:\n{result.stderr}"
        )
        assert "built-in defaults" not in result.stdout

    def test_a_skills_symlink_to_a_real_directory_still_works(self, tmp_path: Path):
        """The reason the guard classifies rather than refusing symlinks: a
        shared .skills/ reached by link is a legitimate layout."""
        repo = make_repo(tmp_path, ["README.md"], ["README.md"])
        write_file(repo, "shared/doc-sections", "AGENTS.md: via a symlinked dir\n")
        (repo / ".skills").symlink_to("shared")
        result = run_doc_check(repo)
        assert result.returncode == 1, (
            f"a resolving .skills symlink must be read normally; got exit "
            f"{result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "via a symlinked dir" in _advice(result.stdout)

    def test_a_skills_that_is_not_a_directory_is_exit_two(self, tmp_path: Path):
        """The last silent-fallback shape: a regular file at .skills makes
        every lookup under it fail with ENOTDIR, and the searchability check
        asks `-d` so it passed straight over this one. .skills/ is a reserved
        directory name in this ecosystem, so a file there is a
        misconfiguration, not an unrelated file to tiptoe around."""
        repo = make_repo(tmp_path, ["README.md"], ["README.md"])
        (repo / ".skills").write_text("not a directory\n")
        result = run_doc_check(repo)
        assert result.returncode == 2, (
            f"a regular file at .skills is a did-not-run; got exit "
            f"{result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "not a directory" in result.stderr, (
            f"the message must name the shape:\n{result.stderr}"
        )
        assert "built-in defaults" not in result.stdout, (
            f"it must not print as an untailored run:\n{result.stdout}"
        )

    def test_a_valid_symlink_still_resolves(self, tmp_path: Path):
        """The reason the presence test cannot simply refuse symlinks: pointing
        the file at a shared config is a use case, and it has to keep working."""
        repo = make_repo(tmp_path, ["README.md"], ["README.md"])
        write_file(repo, "shared/sections", "docs/contracts/: the shared charter\n")
        (repo / ".skills").mkdir(parents=True, exist_ok=True)
        (repo / ".skills/doc-sections").symlink_to("../shared/sections")
        result = run_doc_check(repo)
        assert result.returncode == 1, (
            f"a resolving symlink must be read normally; got exit "
            f"{result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "the shared charter" in _advice(result.stdout), (
            f"the symlinked advice must print:\n{result.stdout}"
        )


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="chmod 000 does not restrict root, so the file stays readable",
)
class TestPermissionDeniedOverride:
    """The permission half, split out so the mode-dependent cases are the only
    ones that go quiet under root — and visibly so, at the class level, which
    is where this suite's two existing precedents put it."""

    @pytest.mark.parametrize("name", BOTH_FILES)
    def test_an_unreadable_override_is_exit_two_not_one(
        self, name: str, tmp_path: Path
    ):
        """A file that exists but cannot be read is a did-not-run. Left to the
        redirection, `set -e` exits 1 with bash's own message — and exit 1 is
        the code that tells the agent to act on a list of hits that was never
        printed. Both files, because the open lives in the reader they share."""
        repo = make_repo(tmp_path, ["README.md"], ["README.md"])
        rel = f".skills/{name}"
        write_file(repo, rel, "README.md\n")
        path = repo / rel
        path.chmod(0)
        try:
            result = run_doc_check(repo)
        finally:
            path.chmod(0o644)
        assert result.returncode == 2, (
            f"an unreadable {rel} is a did-not-run; got exit {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "could not be opened" in result.stderr, (
            f"the message must interpret the failure:\n{result.stderr}"
        )
        assert "Permission denied" in result.stderr, (
            "bash's own diagnostic names the real errno and must reach stderr "
            f"rather than being swallowed by a precondition test:\n{result.stderr}"
        )
        assert rel in result.stderr
        assert "Spot-check" not in result.stdout, (
            "no advice may print alongside a did-not-run verdict"
        )

    def test_an_unsearchable_skills_dir_is_exit_two(self, tmp_path: Path):
        """No per-file test can see this: `-e` and `-L` both have to stat
        inside .skills/, so an unsearchable directory hides both overrides and
        both lists quietly revert."""
        repo = make_repo(tmp_path, ["README.md"], ["README.md"])
        write_file(repo, ".skills/doc-sections", "AGENTS.md: tailored\n")
        skills_dir = repo / ".skills"
        skills_dir.chmod(0)
        try:
            result = run_doc_check(repo)
        finally:
            skills_dir.chmod(0o755)
        assert result.returncode == 2, (
            f"an unsearchable .skills/ is a did-not-run; got exit "
            f"{result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "not searchable" in result.stderr, (
            f"the message must name the directory, not a file:\n{result.stderr}"
        )
