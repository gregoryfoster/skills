"""`context-delta.sh` lists every changed path, and never reads a failed diff as
"no change" (#570).

The review's context-budget block is built from one list of changed files, and
until #570 that list was built three ways that each dropped paths with no word:

- **git's default `core.quotePath` C-quotes a non-ASCII path**, so an untracked
  `docs/Résumé.md` arrived as `"docs/R\\303\\251sum\\303\\251.md"`, matched no
  `docs/*.md` pattern, and dropped out of the delta.
- **There was no `--`**, so a file named `HEAD` at the root made
  `git diff --name-only HEAD` ambiguous. git refused it, and the refusal was
  thrown away with the rest of stderr.
- **Every error was discarded** (`2>/dev/null || true`), so a bad `--base` or a
  shallow clone gave an empty list, and an empty list prints nothing: the same
  output as a branch that touched no context file.

All three are the shape set B fixed in `reviewing-code`'s `gather-context.sh` as
CR 1807. The four `gather-context.sh` copies call this script with `|| true` and
let its stderr through, so the exit code is for direct callers. What a review
sees is the stdout line saying the delta is unknown, and git's own error.

No API calls: every path here uses the offline estimate.
"""

import os
import subprocess
from pathlib import Path

DELTA = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "curating-context"
    / "scripts"
    / "context-delta.sh"
)

POLICY = "Run the tests before you commit. Keep the policy file short.\n"


def _clean_env() -> dict:
    # GIT_DIR and friends would point every fixture command at the real repo
    # when the suite runs from a hook (#189).
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in (
        "CONTEXT_BUDGET",
        "CONTEXT_DOC_BUDGET",
        "CONTEXT_DOCS_DIR",
        "CONTEXT_PROXIMITY_PCT",
        "CTX_BPT_X100",
        "ANTHROPIC_API_KEY",
    ):
        env.pop(k, None)
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=t",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
        env=_clean_env(),
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "AGENTS.md").write_text(POLICY)
    (repo / "docs").mkdir()
    (repo / "docs" / "GUIDE.md").write_text("# Guide\n\nOne line.\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _delta(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(DELTA), *args],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=60,
    )


def _rows(out: str) -> list[str]:
    return [
        ln.split()[0]
        for ln in out.splitlines()
        if ln.split()[:1] and ".md" in ln.split()[0]
    ]


class TestNonAsciiPath:
    def test_untracked_non_ascii_doc_is_listed(self, tmp_path: Path):
        repo = _repo(tmp_path)
        (repo / "docs" / "Résumé.md").write_text("# Résumé\n\n" + "word " * 200)
        r = _delta(repo)
        assert r.returncode == 0, r.stderr
        assert "docs/Résumé.md" in _rows(r.stdout), r.stdout

    def test_modified_non_ascii_doc_is_listed(self, tmp_path: Path):
        repo = _repo(tmp_path)
        doc = repo / "docs" / "Café.md"
        doc.write_text("# Café\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "add")
        doc.write_text("# Café\n\n" + "word " * 200)
        r = _delta(repo)
        assert r.returncode == 0, r.stderr
        assert "docs/Café.md" in _rows(r.stdout), r.stdout


class TestFileNamedLikeARef:
    def test_a_file_named_head_does_not_hide_the_policy_change(self, tmp_path: Path):
        repo = _repo(tmp_path)
        (repo / "HEAD").write_text("not a ref\n")
        _git(repo, "add", "HEAD")
        _git(repo, "commit", "-q", "-m", "a file named HEAD")
        (repo / "AGENTS.md").write_text(POLICY * 40)
        r = _delta(repo)
        assert r.returncode == 0, r.stderr
        assert "AGENTS.md" in _rows(r.stdout), (r.stdout, r.stderr)

    def test_a_file_named_like_the_base_branch(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _git(repo, "checkout", "-q", "-b", "topic")
        (repo / "main").write_text("a file named like the base branch\n")
        (repo / "AGENTS.md").write_text(POLICY * 40)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "topic")
        r = _delta(repo, "--base", "main")
        assert r.returncode == 0, r.stderr
        assert "AGENTS.md" in _rows(r.stdout), (r.stdout, r.stderr)


class TestFailedDiff:
    def test_bad_base_reports_unknown_not_no_change(self, tmp_path: Path):
        repo = _repo(tmp_path)
        (repo / "AGENTS.md").write_text(POLICY * 40)
        r = _delta(repo, "--base", "no-such-ref")
        assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
        # The review block shows stdout: it must say the delta is unknown, and
        # must not print a table that reads as a measurement.
        assert "delta unknown" in r.stdout, r.stdout
        assert "no-such-ref" in r.stdout, r.stdout
        assert "headroom" not in r.stdout, r.stdout
        # git's own error reaches stderr, named by the command that failed.
        assert "context-delta:" in r.stderr and "git diff" in r.stderr, r.stderr
        assert "no-such-ref" in r.stderr, r.stderr

    def test_bad_base_is_reported_under_quiet(self, tmp_path: Path):
        """--quiet silences a clean report, not an unknown one: an unmeasured
        branch may be the one that grew the file."""
        repo = _repo(tmp_path)
        r = _delta(repo, "--quiet", "--base", "no-such-ref")
        assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
        assert "delta unknown" in r.stdout, r.stdout

    def test_unborn_head_still_measures_new_files(self, tmp_path: Path):
        """A repo with no commit yet has no HEAD to diff against. That is not a
        failure: every file is new, so the base is the empty tree."""
        repo = tmp_path / "fresh"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        (repo / "AGENTS.md").write_text(POLICY * 40)
        _git(repo, "add", "AGENTS.md")
        (repo / "docs").mkdir()
        (repo / "docs" / "NEW.md").write_text("# New\n")
        r = _delta(repo)
        assert r.returncode == 0, (r.stdout, r.stderr)
        rows = _rows(r.stdout)
        assert "AGENTS.md" in rows and "docs/NEW.md" in rows, r.stdout
        assert "delta unknown" not in r.stdout

    def test_clean_branch_still_prints_nothing(self, tmp_path: Path):
        repo = _repo(tmp_path)
        r = _delta(repo)
        assert r.returncode == 0 and r.stdout == "", (r.stdout, r.stderr)
