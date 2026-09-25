"""A group acknowledgement for source that is ABOUT policy files (#321).

Any demotion out of this repo's AGENTS.md opened the source sweep on ~700
filename mentions — fixture names, synthetic policy files and code paths in its
own suite, subject matter rather than references. Acknowledging them took one
line-scoped entry each, expiring whenever the busiest test file changed, so
the curation lever that makes real headroom was priced out. `check-seams.sh`
now takes one judged, non-expiring entry for them:

    @mentions SWEPT-FILE PATH-PREFIX :: REASON

What this file pins:

- **It covers filename mentions under its prefix**, counts them into
  `seams_acked`, and prints its reason with the count.
- **It declines a line naming content that moved**: a title that left the
  swept file, or a surviving section a body line left — the generic-title tier
  only on a line that points somewhere, as class 2 matches it — including
  when a title moved and another section shrank in the same run.
- **It reaches nothing else**: not a doc back-reference, not
  `source-moved-title`, not a path outside its prefix — matched on a path
  segment, so `tests` does not reach `tests-data/` — not a run against
  another swept file.
- **A reason is required**; a malformed entry exits 1 and names the form.
- **A line-scoped entry still expires** beside a group: the gate still fails
  when an acknowledged doc line changes.
- **This repo declares its groups**, each with a reason, and the prose names
  the entry where the seam count is explained.

Keep this list current — it is the file's index.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SEAMS = ROOT / "skills" / "curating-context" / "scripts" / "check-seams.sh"
SEAM_ACCOUNTING = (
    ROOT / "skills" / "curating-context" / "references" / "seam-accounting.md"
)
ACK = ".skills/context-seams-ok"

BASE_POLICY = (
    "# Guide\n\n## Build\n\nrun make before every commit, always.\n\n"
    "## Release Checklist\n\n"
    "Tag the release only after the changelog entry lands.\n"
    "Publish the wheel from the tagged commit, never from a branch.\n"
)
MOVED_POLICY = (
    "# Guide\n\n## Build\n\nrun make before every commit, always.\n\n"
    "## Detail Docs\n\n- [docs/RELEASE.md](docs/RELEASE.md) — releasing\n"
)
MOVED_DOC = (
    "# Releasing\n\n## Release Checklist\n\n"
    "Tag the release only after the changelog entry lands.\n"
    "Publish the wheel from the tagged commit, never from a branch.\n"
)
# The heading stays; one body line leaves — the #272 demotion shape.
PARTIAL_POLICY = (
    "# Guide\n\n## Build\n\nrun make before every commit, always.\n\n"
    "## Release Checklist\n\n"
    "Tag the release only after the changelog entry lands.\n"
    "Publishing: [docs/RELEASE.md](docs/RELEASE.md).\n"
)
PARTIAL_DOC = (
    "# Releasing\n\n## Publishing\n\n"
    "Publish the wheel from the tagged commit, never from a branch.\n"
)
FIXTURES = (
    'POLICY = "AGENTS.md"\n'
    'SIBLING = "CLAUDE.md -> AGENTS.md"\n'
    "def test_reads_it():\n"
    '    assert open("AGENTS.md")\n'
)
CITES_SECTION = "# AGENTS.md's release checklist is what this pins\n"


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env=_clean_env(),
    )


def _write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _repo(tmp_path: Path, *, extra: dict | None = None, shape: str = "moved") -> Path:
    """AGENTS.md committed with its Release Checklist inline and a tests/ tree
    naming it; then, uncommitted, the demotion SHAPE."""
    repo = tmp_path / "grp"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _write(repo, "AGENTS.md", BASE_POLICY)
    _write(repo, "tests/test_policy.py", FIXTURES)
    for rel, text in (extra or {}).items():
        _write(repo, rel, text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "pre")
    policy, doc = (
        (MOVED_POLICY, MOVED_DOC) if shape == "moved" else (PARTIAL_POLICY, PARTIAL_DOC)
    )
    _write(repo, "AGENTS.md", policy)
    _write(repo, "docs/RELEASE.md", doc)
    return repo


def _ack(repo: Path, *entries: str) -> None:
    _write(repo, ACK, "".join(e + "\n" for e in entries))


def _seams(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SEAMS), "--base", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=60,
    )


def _count(r: subprocess.CompletedProcess, key: str) -> int:
    return int(
        next(
            ln.split(": ", 1)[1]
            for ln in r.stdout.splitlines()
            if ln.startswith(f"{key}: ")
        )
    )


TESTS_GROUP = "@mentions AGENTS.md tests/ :: fixtures name the file as a subject"


class TestTheGroupCovers:
    def test_without_it_every_mention_is_a_seam(self, tmp_path: Path):
        r = _seams(_repo(tmp_path))
        assert r.returncode == 3, r.stdout
        assert _count(r, "seams") == 3, r.stdout

    def test_it_acknowledges_the_mentions_and_says_why(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _ack(repo, TESTS_GROUP)
        r = _seams(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert _count(r, "seams") == 0
        assert _count(r, "seams_acked") == 3
        assert "3 hit(s) in 1 file(s) under tests/" in r.stdout
        assert "fixtures name the file as a subject" in r.stdout


class TestTheGroupDeclines:
    def test_a_line_naming_a_title_that_moved(self, tmp_path: Path):
        repo = _repo(tmp_path, extra={"tests/test_release.py": CITES_SECTION})
        _ack(repo, TESTS_GROUP)
        r = _seams(repo)
        assert r.returncode == 3, r.stdout
        assert _count(r, "seams") == 1, r.stdout
        assert "tests/test_release.py:1" in r.stdout
        assert "'Release Checklist', a title that moved" in r.stdout
        assert "1 declined" in r.stdout

    def test_a_line_naming_a_section_a_body_line_left(self, tmp_path: Path):
        """No title moved, so moved-title is empty — the shape in which a
        group without this would have hidden the one real seam."""
        repo = _repo(
            tmp_path, extra={"tests/test_release.py": CITES_SECTION}, shape="partial"
        )
        _ack(repo, TESTS_GROUP)
        r = _seams(repo)
        assert r.returncode == 3, r.stdout
        assert _count(r, "seams") == 1, r.stdout
        assert "'Release Checklist', a section content left" in r.stdout

    def test_a_shrunk_section_in_a_run_where_another_title_moved(self, tmp_path: Path):
        """CR 9. A moved title skips the first relocation walk, so the group
        runs its own — the branch that finds `Build` lost a line while
        `Release Checklist` left whole."""
        repo = _repo(
            tmp_path, extra={"tests/test_build.py": "# see AGENTS.md § Build\n"}
        )
        _write(
            repo,
            "AGENTS.md",
            "# Guide\n\n## Build\n\nBuild steps: [docs/RELEASE.md](docs/RELEASE.md).\n",
        )
        _write(
            repo,
            "docs/RELEASE.md",
            MOVED_DOC + "\n## Building\n\nrun make before every commit, always.\n",
        )
        _ack(repo, TESTS_GROUP)
        r = _seams(repo)
        assert "tests/test_build.py:1" in r.stdout, r.stdout
        assert "'Build', a section content left" in r.stdout, r.stdout

    def test_a_generic_title_only_where_the_line_points(self, tmp_path: Path):
        """`Build` is one word, so class 2 matches it only beside a pointer;
        a group declines on the same rule, or every "build" would reopen."""
        repo = _repo(
            tmp_path,
            extra={
                "tests/test_build.py": (
                    "# AGENTS.md says to build first\n# see AGENTS.md § Build\n"
                )
            },
        )
        _write(repo, "AGENTS.md", "# Guide\n\n## Detail Docs\n\n- x\n")
        _write(
            repo,
            "docs/RELEASE.md",
            MOVED_DOC + "\n## Build\n\nrun make before every commit, always.\n",
        )
        _ack(repo, TESTS_GROUP)
        r = _seams(repo)
        assert "tests/test_build.py:2" in r.stdout, r.stdout
        assert "tests/test_build.py:1" not in r.stdout, r.stdout


class TestTheGroupReachesNothingElse:
    def test_not_a_path_outside_its_prefix(self, tmp_path: Path):
        repo = _repo(tmp_path, extra={"scripts/tool.sh": "# reads AGENTS.md\n"})
        _ack(repo, TESTS_GROUP)
        r = _seams(repo)
        assert _count(r, "seams") == 1, r.stdout
        assert "scripts/tool.sh:1" in r.stdout

    def test_not_a_sibling_sharing_the_prefix_text(self, tmp_path: Path):
        """CR 1. `tests` names a directory, not a string: `tests-data/` is
        another tree, and an entry that never expires must not reach it."""
        repo = _repo(tmp_path, extra={"tests-data/seed.sh": "# reads AGENTS.md\n"})
        _ack(repo, "@mentions AGENTS.md tests :: fixtures name the file")
        r = _seams(repo)
        assert _count(r, "seams") == 1, r.stdout
        assert "tests-data/seed.sh:1" in r.stdout
        assert "3 hit(s) in 1 file(s) under tests/" in r.stdout

    def test_not_a_doc_back_reference(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _write(repo, "docs/RELEASE.md", MOVED_DOC + "\nSee AGENTS.md for builds.\n")
        _ack(repo, TESTS_GROUP, "@mentions AGENTS.md docs/ :: tried on a doc")
        r = _seams(repo)
        assert _count(r, "seams") == 1, r.stdout
        assert "back-reference  docs/RELEASE.md" in r.stdout

    def test_not_a_source_moved_title(self, tmp_path: Path):
        repo = _repo(
            tmp_path, extra={"tests/test_steps.py": "# the Release Checklist steps\n"}
        )
        _ack(repo, TESTS_GROUP)
        r = _seams(repo)
        assert _count(r, "seams") == 1, r.stdout
        assert "source-moved-title" in r.stdout

    def test_not_a_run_against_another_swept_file(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _ack(repo, "@mentions CLAUDE.md tests/ :: judged for another target")
        r = _seams(repo)
        assert _count(r, "seams") == 3, r.stdout


class TestAMalformedEntry:
    def test_a_missing_reason_exits_1_naming_the_form(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _ack(repo, "@mentions AGENTS.md tests/ ::   ")
        r = _seams(repo)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "@mentions <swept-file> <path-prefix> :: <reason>" in r.stderr
        assert f"{ACK}:1" in r.stderr

    def test_a_missing_prefix_exits_1(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _ack(repo, "@mentions AGENTS.md :: no prefix")
        assert _seams(repo).returncode == 1


class TestLineScopedEntriesStillExpire:
    def test_a_changed_doc_line_fails_the_gate_beside_a_group(self, tmp_path: Path):
        repo = _repo(tmp_path)
        doc = MOVED_DOC + "\nThe build rules stay in AGENTS.md.\n"
        _write(repo, "docs/RELEASE.md", doc)
        _ack(
            repo,
            TESTS_GROUP,
            "docs/RELEASE.md :: The build rules stay in AGENTS.md.",
        )
        assert _seams(repo).returncode == 0
        _write(repo, "docs/RELEASE.md", doc.replace("stay", "now live"))
        r = _seams(repo)
        assert r.returncode == 3, r.stdout
        assert "back-reference  docs/RELEASE.md" in r.stdout


class TestThisRepo:
    def test_declares_its_groups_each_with_a_reason(self):
        groups = [
            ln
            for ln in (ROOT / ACK).read_text().splitlines()
            if ln.startswith("@mentions ")
        ]
        prefixes = {ln.split()[2] for ln in groups}
        assert {"tests/", "skills/"} <= prefixes, groups
        for ln in groups:
            assert ln.split(" :: ", 1)[1].strip(), ln

    def test_the_prose_names_the_entry(self):
        text = SEAM_ACCOUNTING.read_text()
        assert "@mentions" in text
        assert "#321" in text or "issues/321" in text
