"""`.skills/merge_mode`: how a project lands work on its default branch (#342).

`direct` is a local merge, then a push: what `shipping-work` Step 3 and
`using-git-worktrees` Phase 4 have always done. `pr` pushes the branch and
opens a pull request instead, and the merge happens on GitHub. **Absent means
`direct`** (the operator's 2026-10-30 decision, recorded on #342), so a repo
that commits nothing keeps today's behaviour exactly.

Each skill resolves its own scripts (#63, #301), so each ships a reader:
`shipping-work/scripts/merge-mode.sh` and
`using-git-worktrees/scripts/merge-mode.sh`. They are one definition in two
places, held byte-identical here, and every behavioural test below runs
against both.

The rule that matters is the house one: **present but unusable is exit 2,
never read as absent.** A typo such as `PR` or `pull-request` that fell back
to `direct` would merge locally in a repo that asked for review, which is the
one direction the knob exists to prevent. That includes an empty file.

No API calls. Each test builds a throwaway repo; every git call scrubs the
inherited `GIT_*` variables (#189).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.utils.skill_loader import SKILLS_DIR

READERS = {
    "shipping-work": SKILLS_DIR / "shipping-work" / "scripts" / "merge-mode.sh",
    "using-git-worktrees": SKILLS_DIR
    / "using-git-worktrees"
    / "scripts"
    / "merge-mode.sh",
}


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["LC_ALL"] = "C"
    return env


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(),
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "initial")
    return repo


@pytest.fixture(params=sorted(READERS))
def reader(request) -> Path:
    return READERS[request.param]


def _knob(repo: Path, text: str) -> Path:
    (repo / ".skills").mkdir(exist_ok=True)
    knob = repo / ".skills" / "merge_mode"
    knob.write_text(text)
    return knob


def _read(reader: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(reader), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=_env(),
        timeout=30,
    )


def test_the_two_readers_are_one_definition():
    """Two copies, because each skill resolves its own scripts. A fix to one
    that missed the other would read the same file two ways in one ship."""
    a, b = (READERS[k].read_bytes() for k in sorted(READERS))
    assert a == b, (
        "skills/shipping-work/scripts/merge-mode.sh and "
        "skills/using-git-worktrees/scripts/merge-mode.sh differ; copy the "
        "changed one over the other"
    )


class TestAbsentMeansDirect:
    def test_no_knob_prints_direct_and_nothing_else(self, reader, repo):
        r = _read(reader, repo)
        assert (r.returncode, r.stdout, r.stderr) == (0, "direct\n", "")

    def test_no_skills_directory_at_all_is_the_same(self, reader, repo):
        assert not (repo / ".skills").exists()
        r = _read(reader, repo)
        assert (r.returncode, r.stdout) == (0, "direct\n")


class TestTheTwoWords:
    @pytest.mark.parametrize("word", ["pr", "direct"])
    def test_each_word_is_printed(self, reader, repo, word):
        _knob(repo, f"{word}\n")
        r = _read(reader, repo)
        assert (r.returncode, r.stdout, r.stderr) == (0, f"{word}\n", "")

    def test_comments_blank_lines_crlf_and_padding_are_ignored(self, reader, repo):
        _knob(repo, "# reviewed through PRs since 2026-11\r\n\r\n   pr  \r\n\n")
        r = _read(reader, repo)
        assert (r.returncode, r.stdout) == (0, "pr\n"), r.stderr

    def test_a_missing_final_newline_still_reads(self, reader, repo):
        _knob(repo, "pr")
        assert _read(reader, repo).stdout == "pr\n"

    def test_it_is_read_from_the_primary_checkout(self, reader, repo, tmp_path):
        """Untracked knobs do not exist in a linked worktree, so a reader
        that asked the current checkout would see `direct` from every
        worktree of a `pr` repo."""
        _knob(repo, "pr\n")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feature/x", str(wt))
        assert not (wt / ".skills" / "merge_mode").exists()
        r = _read(reader, wt)
        assert (r.returncode, r.stdout) == (0, "pr\n"), r.stderr

    def test_from_a_subdirectory(self, reader, repo):
        _knob(repo, "pr\n")
        (repo / "sub").mkdir()
        assert _read(reader, repo / "sub").stdout == "pr\n"


class TestUnusableIsExit2NeverAbsent:
    @pytest.mark.parametrize(
        "text",
        [
            "PR\n",
            "pull-request\n",
            "merge\n",
            "pr direct\n",
            "pr\ndirect\n",
            "pr # reviewed\n",
            "",
            "# only a comment\n\n",
        ],
        ids=[
            "upper-case",
            "another-word",
            "merge",
            "two-words",
            "two-lines",
            "trailing-comment",
            "empty",
            "comments-only",
        ],
    )
    def test_it_is_exit_2_with_nothing_on_stdout(self, reader, repo, text):
        _knob(repo, text)
        r = _read(reader, repo)
        assert r.returncode == 2, r.stdout + r.stderr
        assert r.stdout == "", "an unusable knob must print no mode"
        assert ".skills/merge_mode" in r.stderr
        # The remedy names both words and the way back to the default.
        assert "pr" in r.stderr and "direct" in r.stderr

    def test_a_directory_is_exit_2(self, reader, repo):
        (repo / ".skills" / "merge_mode").mkdir(parents=True)
        r = _read(reader, repo)
        assert (r.returncode, r.stdout) == (2, "")

    def test_a_dangling_symlink_is_exit_2(self, reader, repo):
        (repo / ".skills").mkdir()
        (repo / ".skills" / "merge_mode").symlink_to(repo / "nowhere")
        r = _read(reader, repo)
        assert (r.returncode, r.stdout) == (2, "")

    @pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 file")
    def test_an_unreadable_file_is_exit_2(self, reader, repo):
        knob = _knob(repo, "pr\n")
        knob.chmod(0)
        try:
            r = _read(reader, repo)
        finally:
            knob.chmod(0o644)
        assert (r.returncode, r.stdout) == (2, "")

    def test_outside_a_git_checkout_is_exit_2(self, reader, tmp_path):
        bare = tmp_path / "not-a-repo"
        bare.mkdir()
        r = _read(reader, bare)
        assert (r.returncode, r.stdout) == (2, "")


class TestTheInterface:
    def test_help_names_the_words_the_default_and_the_exit_codes(self, reader):
        r = subprocess.run(
            ["bash", str(reader), "--help"], capture_output=True, text=True
        )
        assert r.returncode == 0
        for needle in ("pr", "direct", "absent", "primary", "0 ", "2 "):
            assert needle in r.stdout, needle

    def test_an_unknown_argument_is_exit_2(self, reader, repo):
        r = _read(reader, repo, "--mode")
        assert (r.returncode, r.stdout) == (2, "")


class TestPrimaryLayouts:
    """CR 1860: the first list entry is a git dir in two layouts.

    For a bare primary it is `repo.git`; in a submodule (git 2.54),
    `<super>/.git/modules/<n>`. Read as a checkout, neither holds `.skills/`,
    so both printed `direct` in silence. A bare primary's knob is the current
    checkout's; a submodule's primary is its work tree.
    """

    @staticmethod
    def _seed(path: Path, knob: str) -> Path:
        path.mkdir(parents=True)
        _git(path, "init", "-q", "-b", "main")
        _git(path, "config", "user.email", "test@example.com")
        _git(path, "config", "user.name", "test")
        _knob(path, knob)
        _git(path, "add", "-A")
        _git(path, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "knob")
        return path

    def _bare_home(self, tmp_path: Path, knob: str) -> Path:
        seed = self._seed(tmp_path / "seed", knob)
        bare = tmp_path / "repo.git"
        _git(tmp_path, "clone", "-q", "--bare", str(seed), str(bare))
        home = tmp_path / "home"
        _git(bare, "worktree", "add", "-q", str(home), "main")
        assert _git(home, "worktree", "list", "--porcelain").splitlines()[1] == "bare"
        return home

    def _submodule_linked(self, tmp_path: Path, knob: str) -> Path:
        src = self._seed(tmp_path / "src", "direct\n")
        sup = tmp_path / "super"
        sup.mkdir()
        _git(sup, "init", "-q", "-b", "main")
        _git(
            sup,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "-q",
            "add",
            str(src),
            "sub",
        )
        sub = sup / "sub"
        # Untracked in the submodule's checkout, as a machine-local knob is.
        _knob(sub, knob)
        wt = tmp_path / "wt"
        _git(sub, "worktree", "add", "-q", "-b", "feature/x", str(wt))
        assert "/.git/modules/" in _git(wt, "worktree", "list", "--porcelain")
        return wt

    LAYOUTS = ["_bare_home", "_submodule_linked"]

    @pytest.mark.parametrize("layout", LAYOUTS)
    def test_pr_is_read(self, reader, tmp_path, layout):
        checkout = getattr(self, layout)(tmp_path, "pr\n")
        r = _read(reader, checkout)
        assert (r.returncode, r.stdout) == (0, "pr\n"), r.stderr

    @pytest.mark.parametrize("layout", LAYOUTS)
    def test_an_unusable_word_is_still_exit_2(self, reader, tmp_path, layout):
        checkout = getattr(self, layout)(tmp_path, "PR\n")
        r = _read(reader, checkout)
        assert (r.returncode, r.stdout) == (2, ""), r.stderr
        assert ".skills/merge_mode" in r.stderr

    def test_a_primary_git_cannot_open_is_exit_2(self, reader, repo, tmp_path):
        """Only the primary is refused ("dubious ownership"); never a fallback."""
        _knob(repo, "pr\n")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feature/x", str(wt))
        env = _env()
        env.update(
            GIT_TEST_ASSUME_DIFFERENT_OWNER="1",
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0="safe.directory",
            GIT_CONFIG_VALUE_0=str(wt.resolve()),
        )
        r = subprocess.run(
            ["bash", str(reader)],
            cwd=wt,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert (r.returncode, r.stdout) == (2, ""), r.stderr
        assert "dubious ownership" in r.stderr, "git's reason is let through"
        assert f"'{repo.resolve()}'" in r.stderr, r.stderr
