"""What check-seams.sh sweeps, and what it refuses to sweep (#131, #113).

Separate from test_context_surface.py's TestCheckSeams, which covers the three
original classes, because both cases here are about the sweep's *reach*: which
moved titles are specific enough to match bare prose (#131), and which files
the sweep looks at at all (#113). The helpers are local rather than imported —
these repos need tracked source files, which no existing fixture builds.

Every case is a measured defect, not a hypothetical:

- #131: a `curating-context` run on CannObserv/power-map split a doc into six
  per-resource docs with one-word titles (`People`, `Organizations`,
  `Jurisdictions`). The sweep returned 205 moved-title hits, every one a
  verified false positive — an admin breadcrumb, a scope-table row — against 0
  real references. The pre-existing floor was CHARACTER-based (>= 8), and
  `Organizations` is thirteen characters.
- #113: 16 docstring references across 13 shipped Python files cited the policy
  file for content the same run had just relocated, and the sweep reported zero
  of them while exiting clean. Seven of the sixteen cited the section title
  rather than the filename, so a filename-only grep finds nine.
"""

import os
import subprocess
from pathlib import Path

SEAMS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills" / "curating-context" / "scripts" / "check-seams.sh"
)


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, env=_clean_env())


def _write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


BASE_POLICY = (
    "# Guide\n\n## Build\n\nrun make\n\n"
    "## People\n\nEvery person carries a canonical name.\n\n"
    "## Organizations\n\nOrgs own assignments.\n\n"
    "## Deployment Topology\n\nThe workers connect to the bus directly.\n"
)

NOW_POLICY = (
    "# Guide\n\n## Build\n\nrun make\n\n## Detail Docs\n\n"
    "- [docs/ENTITIES.md](docs/ENTITIES.md) — entities\n"
)


def _moved_repo(tmp_path: Path, name: str = "seams") -> Path:
    """A curation one commit old: `People`, `Organizations` and `Deployment
    Topology` all left the policy file for docs/ENTITIES.md."""
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _write(repo, "AGENTS.md", BASE_POLICY)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "pre")
    _write(repo, "AGENTS.md", NOW_POLICY)
    _write(repo, "docs/ENTITIES.md",
           "# Entities\n\n## People\n\nEvery person carries a canonical "
           "name.\n\n## Organizations\n\nOrgs own assignments.\n\n"
           "## Deployment Topology\n\nThe workers connect to the bus "
           "directly.\n")
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SEAMS), "--base", "HEAD", *args],
        cwd=repo, capture_output=True, text=True, env=_clean_env(), timeout=60,
    )


class TestGenericMovedTitles:
    """#131: a one-word title matches every ordinary mention of the word."""

    def test_ordinary_prose_mentioning_a_one_word_title_is_not_a_seam(
            self, tmp_path: Path):
        """The three shapes measured on power-map, verbatim. None of them
        points at anything; all three were reported."""
        repo = _moved_repo(tmp_path)
        _write(repo, "docs/UI.md",
               "# UI\n\n"
               '<a href="/admin/orgs/">Organizations</a><span>*</span>\n'
               "| POST | /api/v1/organizations | organizations:write scope |\n"
               "- **No dup surface** — organizations have no dup tables\n")
        r = _run(repo)
        assert "moved-title" not in r.stdout, r.stdout
        assert r.returncode == 0, r.stdout

    def test_a_one_word_title_is_still_caught_where_something_points_at_it(
            self, tmp_path: Path):
        """The case the class exists for. `People` is one word, so it is only
        swept on lines that point somewhere — and this one does."""
        repo = _moved_repo(tmp_path)
        _write(repo, "docs/API.md",
               "# API\n\nSee docs/ENTITIES.md § People for the field list.\n")
        r = _run(repo)
        assert r.returncode == 3, r.stdout
        assert "moved-title" in r.stdout
        assert "docs/API.md:3" in r.stdout

    def test_a_section_marker_alone_corroborates(self, tmp_path: Path):
        repo = _moved_repo(tmp_path)
        _write(repo, "docs/API.md", "# API\n\nField list: § Organizations.\n")
        r = _run(repo)
        assert r.returncode == 3, r.stdout
        assert "docs/API.md:3" in r.stdout

    def test_a_markdown_link_corroborates(self, tmp_path: Path):
        repo = _moved_repo(tmp_path)
        _write(repo, "docs/API.md",
               "# API\n\nRead [People](#people) before adding a field.\n")
        r = _run(repo)
        assert r.returncode == 3, r.stdout
        assert "docs/API.md:3" in r.stdout

    def test_a_specific_title_is_still_swept_bare(self, tmp_path: Path):
        """Descriptive titles produced ZERO false positives on the same
        programme, and #113's source sweep depends on bare matching: seven of
        its sixteen misses named the title and nothing else."""
        repo = _moved_repo(tmp_path)
        _write(repo, "docs/API.md",
               "# API\n\nThe Deployment Topology section has the diagram.\n")
        r = _run(repo)
        assert r.returncode == 3, r.stdout
        assert "moved-title" in r.stdout
        assert "docs/API.md:3" in r.stdout

    def test_a_long_one_word_title_is_generic_too(self, tmp_path: Path):
        """The character floor was the whole filter, and `Organizations` is
        thirteen characters. Word count is what separates a pointer from a
        noun."""
        repo = _moved_repo(tmp_path)
        _write(repo, "docs/UI.md",
               "# UI\n\nOrganizations are listed alphabetically.\n")
        r = _run(repo)
        assert r.returncode == 0, r.stdout

    def test_the_report_names_the_titles_it_only_swept_for_pointers(
            self, tmp_path: Path):
        """A silent narrowing is the failure mode of a heuristic that fixes a
        flood: the run must be able to see which titles got the weaker sweep."""
        r = _run(_moved_repo(tmp_path))
        assert "People" in r.stdout and "Organizations" in r.stdout
        assert "Deployment Topology" not in r.stdout
