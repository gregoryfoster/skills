"""Behavioral tests for the `.skills/worktree_venv` opt-out (#201).

`worktree-create.sh` symlinks a new worktree's `.venv` at the main checkout's,
which is right when the main checkout is just a checkout. Where it is also a
running service's `WorkingDirectory=`, the link makes every worktree share one
*mutable* environment while being isolated in every other respect, and the
service's own tooling rewrites it underneath a worktree's test run:

* `uv run` reinstalls the current project, restamping
  `importlib.metadata.version(...)` to the main checkout's version mid-run — a
  worktree suite on a bumped version fails in a full run and passes in
  isolation.
* `uv sync` prunes every dependency group it was not asked for, deleting an
  opt-in group whose test modules `pytest.importorskip` at module scope — a few
  hundred tests become "skipped" against a suite that still reports green.

The knob is `link` (default — nothing changes for existing users) or `none`.

The load-bearing case is `TestKnobIsReadFromThePrimaryCheckout`. `.skills/`
knobs are machine-local and untracked by convention, and #202 established that
an untracked file in the primary checkout **does not exist in a linked worktree
at all**. A knob read from `git rev-parse --show-toplevel` would therefore be
invisible whenever this script runs from inside a worktree — silently restoring
the venv link in exactly the deployment the knob exists to protect. So the knob
is resolved against the primary checkout, the way `resolve-worktree-root.sh`
resolves `.skills/worktree_root`, and it works untracked.

No API calls. Self-contained: each test builds a throwaway repo under tmp_path.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "skills" / "using-git-worktrees" / "scripts"
CREATE = SCRIPTS / "worktree-create.sh"
SKILL_MD = REPO_ROOT / "skills" / "using-git-worktrees" / "SKILL.md"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars, and with a predictable locale.

    An inherited GIT_DIR beats both `-C` and cwd, so a fixture that ran under
    pre-commit would otherwise initialise and commit into the *real* repo.
    WORKTREE_ROOT wins over everything in the root resolution order and must
    not leak in from the caller.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["LC_ALL"] = "C"
    env.pop("WORKTREE_ROOT", None)
    return env


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, check=True, env=_clean_env(),
    )


def _create(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(CREATE), *args],
        capture_output=True, text=True, cwd=str(cwd), env=_clean_env(),
    )


def _venv(repo: Path) -> Path:
    """A venv the linker will recognise: it probes `.venv/bin/activate`."""
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / ".venv" / "bin" / "activate").write_text("# stub\n")
    return repo / ".venv"


def _knob(repo: Path, content: str) -> Path:
    (repo / ".skills").mkdir(exist_ok=True)
    p = repo / ".skills" / "worktree_venv"
    p.write_text(content)
    return p


@pytest.fixture
def primary(tmp_path: Path) -> Path:
    """A one-commit repo with a stub venv, resolved through /var -> /private/var.

    git reports physical paths, so the fixture must too or every comparison
    against script output is a false-unequal.
    """
    repo = (tmp_path / "repo").resolve()
    repo.mkdir()
    _git(tmp_path.resolve(), "init", "-q", "-b", "main", str(repo))
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("initial\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial")
    _venv(repo)
    return repo


class TestDefaultStaysLink:
    """Absent or `link`, the venv is linked exactly as before (#156)."""

    def test_no_knob_file_links_the_venv(self, primary: Path):
        r = _create("--new", "feat/a", cwd=primary)
        assert r.returncode == 0, f"creation failed: {r.stderr}"
        wt = Path(r.stdout.strip())
        assert wt.joinpath(".venv").is_symlink(), (
            "with no knob the pre-#201 behaviour must be unchanged: a worktree "
            "inherits no virtualenv, so the link is what keeps the first "
            "`.venv/bin/python -m pytest` in it from dying before any test runs"
        )
        assert wt.joinpath(".venv").resolve() == primary.joinpath(".venv").resolve()

    def test_explicit_link_links_the_venv(self, primary: Path):
        _knob(primary, "link\n")
        r = _create("--new", "feat/b", cwd=primary)
        assert r.returncode == 0, f"creation failed: {r.stderr}"
        assert Path(r.stdout.strip()).joinpath(".venv").is_symlink(), (
            "`link` is the default spelled out, not a third behaviour"
        )


class TestNoneSkipsTheLink:
    def test_none_creates_no_venv(self, primary: Path):
        _knob(primary, "none\n")
        r = _create("--new", "feat/c", cwd=primary)
        assert r.returncode == 0, f"creation failed: {r.stderr}"
        wt = Path(r.stdout.strip())
        assert not wt.joinpath(".venv").exists(), "no .venv may be created"
        assert not wt.joinpath(".venv").is_symlink(), (
            "and no dangling symlink either — `-e` is false for a broken link, "
            "so a later linker would fall through to an `ln -s` that fails"
        )

    def test_none_is_announced_on_stderr(self, primary: Path):
        _knob(primary, "none\n")
        r = _create("--new", "feat/d", cwd=primary)
        assert "worktree_venv" in r.stderr, (
            "skipping the link must say which knob skipped it, or the missing "
            "venv reads as the #156 bug it was introduced to fix"
        )

    def test_stdout_is_still_only_the_path(self, primary: Path):
        """The stdout contract survives the new branch (#188 item 1)."""
        _knob(primary, "none\n")
        r = _create("--new", "feat/e", cwd=primary)
        lines = r.stdout.strip().splitlines()
        assert len(lines) == 1, f"stdout must be one line, got {lines!r}"
        assert Path(lines[0]).is_dir()

    def test_comments_and_blank_lines_are_ignored(self, primary: Path):
        """Same first-non-blank-non-comment read as `.skills/worktree_root`."""
        _knob(primary, "# main checkout is a systemd WorkingDirectory\n\n  none  \n")
        r = _create("--new", "feat/f", cwd=primary)
        assert r.returncode == 0, f"creation failed: {r.stderr}"
        assert not Path(r.stdout.strip()).joinpath(".venv").exists()

    def test_empty_knob_falls_through_to_the_default(self, primary: Path):
        """All-comments or empty must default, not crash under `pipefail`."""
        _knob(primary, "# nothing configured\n\n")
        r = _create("--new", "feat/g", cwd=primary)
        assert r.returncode == 0, f"creation failed: {r.stderr}"
        assert Path(r.stdout.strip()).joinpath(".venv").is_symlink()


class TestUnrecognisedValue:
    """#132's lesson: a malformed knob file degrades to the default AND says so.

    Silence is what lets a wrong setting persist. The fallback is `link` because
    the default is `link`; the WARN is what stops a typo (`non`, `off`, `false`)
    from reading as a working opt-out.
    """

    def test_typo_still_links(self, primary: Path):
        _knob(primary, "off\n")
        r = _create("--new", "feat/h", cwd=primary)
        assert r.returncode == 0, f"creation failed: {r.stderr}"
        assert Path(r.stdout.strip()).joinpath(".venv").is_symlink()

    def test_typo_warns_and_names_the_accepted_values(self, primary: Path):
        _knob(primary, "off\n")
        r = _create("--new", "feat/i", cwd=primary)
        assert "WARN" in r.stderr, "an unrecognised value must not be silent"
        assert "link" in r.stderr and "none" in r.stderr, (
            "the warning must name both accepted values so the operator can "
            "fix the file without reading the script"
        )


class TestKnobIsReadFromThePrimaryCheckout:
    """The knob is machine-local, so it is untracked — and #202 established
    that an untracked file does not exist in a linked worktree at all.

    Read against the current checkout, the knob would be invisible whenever
    `worktree-create.sh` runs from inside a worktree, and the shared-venv link
    would come back in exactly the deployment the knob exists to protect.
    """

    def test_honoured_from_inside_a_linked_worktree(self, primary: Path):
        _knob(primary, "none\n")
        linked = primary / ".worktrees" / "gen-one"
        _git(primary, "worktree", "add", "-q", "-b", "gen/one", str(linked))
        # The harness-provisioned shape from SKILL.md Phase 3: the worktree got
        # a venv by hand, so the current-checkout probe below finds one to link.
        linked.joinpath(".venv").symlink_to(primary / ".venv")
        assert not (linked / ".skills" / "worktree_venv").exists(), (
            "fixture precondition: the knob is untracked and thus absent here"
        )

        r = _create("--new", "gen/two", cwd=linked)
        assert r.returncode == 0, f"creation failed: {r.stderr}"
        grandchild = Path(r.stdout.strip())
        assert not grandchild.joinpath(".venv").exists(), (
            "the knob must be resolved against the primary checkout; read from "
            "`--show-toplevel` it is absent here and the link silently returns"
        )


class TestKnobIsDocumented:
    """The script is vendored into repos that never read this test file."""

    def test_help_names_the_knob(self):
        r = subprocess.run(
            ["bash", str(CREATE), "--help"],
            capture_output=True, text=True, env=_clean_env(),
        )
        assert r.returncode == 0
        assert ".skills/worktree_venv" in r.stdout, (
            "--help documents the root knob; the venv knob belongs beside it"
        )

    def test_skill_md_documents_the_knob_and_both_mechanisms(self):
        body = SKILL_MD.read_text()
        assert ".skills/worktree_venv" in body
        for token in ("WorkingDirectory", "uv run", "uv sync"):
            assert token in body, (
                f"SKILL.md must name '{token}' so a reader can recognise the "
                "case rather than memorise a rule"
            )
