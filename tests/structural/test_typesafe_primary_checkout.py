"""#613: `_typesafe.project_root` follows set U's primary-checkout rule.

`project_root` names the checkout whose untracked `.skills/typesafe` and `.env`
the client reads. It copied the guard `resolve-worktree-root.sh` had before set
U, so it kept three of the gaps set U and #612 close there:

- **(a) an inherited hook variable** (`GIT_DIR`, `GIT_WORK_TREE`,
  `GIT_COMMON_DIR`) answered for the repository it names, not the one `cwd`
  is in;
- **(b) a git failure on the primary** ("dubious ownership") fell back to the
  current checkout, whose knob and key a linked worktree doesn't hold;
- **(c) a `--separate-git-dir` store whose path ends in `/.git`** (#612 gap
  1): git names the directory above it as a work tree, so the primary's own
  answer was that directory.

The parity class holds `project_root` to `resolve-worktree-root.sh
--project-root` on every layout that script resolves.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.structural import merge_mode_layouts as layouts

sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENT = REPO_ROOT / "scripts" / "_typesafe.py"
RESOLVE = (
    REPO_ROOT
    / "skills"
    / "using-git-worktrees"
    / "scripts"
    / "resolve-worktree-root.sh"
)

_spec = importlib.util.spec_from_file_location("_typesafe_primary", CLIENT)
ts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ts)

KEY = "ts-test-key-0123456789"


@pytest.fixture(autouse=True)
def _no_inherited_git(monkeypatch):
    """The tests set the variables they mean; nothing leaks in from a hook."""
    for k in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(k)
    monkeypatch.setenv("LC_ALL", "C")


def _linked(tmp_path: Path) -> tuple[Path, Path]:
    primary = layouts.seed(tmp_path / "primary", "direct\n")
    linked = tmp_path / "wt"
    layouts.git(primary, "worktree", "add", "-q", "-b", "side", str(linked))
    return primary.resolve(), linked.resolve()


class TestInheritedHookVariables:
    """(a) Git exports GIT_DIR to every hook, and it beats cwd."""

    @pytest.mark.parametrize("var", ["GIT_DIR", "GIT_COMMON_DIR"])
    def test_a_variable_naming_another_repo_does_not_answer_for_it(
        self, tmp_path, monkeypatch, var
    ):
        here = layouts.seed(tmp_path / "here", "direct\n").resolve()
        other = layouts.seed(tmp_path / "other", "direct\n").resolve()
        monkeypatch.setenv(var, str(other / ".git"))
        assert ts.project_root(str(here)) == here

    def test_a_linked_worktree_under_a_hook_still_names_its_primary(
        self, tmp_path, monkeypatch
    ):
        primary, linked = _linked(tmp_path)
        gitdir = layouts.git(linked, "rev-parse", "--absolute-git-dir")
        monkeypatch.setenv("GIT_DIR", gitdir)
        monkeypatch.setenv("GIT_WORK_TREE", str(linked))
        assert ts.project_root(str(linked)) == primary


class TestAGitFailureOnThePrimary:
    """(b) "Dubious ownership" is a refusal with git's reason, never the
    current checkout standing in (set U's CR 1858 rule)."""

    def test_project_root_raises_with_gits_reason(self, tmp_path, monkeypatch):
        _, linked = _linked(tmp_path)
        for k, v in layouts.different_owner({}, linked).items():
            monkeypatch.setenv(k, v)
        with pytest.raises(ts.PrimaryUnresolved) as e:
            ts.project_root(str(linked))
        assert "dubious ownership" in str(e.value), str(e.value)

    def test_connect_skips_naming_it_and_sends_nothing(self, tmp_path, monkeypatch):
        """Every TypeSafe step is advisory, and callers catch only Skipped."""
        primary, linked = _linked(tmp_path)
        (primary / ".skills" / "typesafe").write_text("on\n")
        (primary / ".env").write_text(f"TYPESAFE_API_KEY={KEY}\n")
        for k, v in layouts.different_owner({}, linked).items():
            monkeypatch.setenv(k, v)
        with pytest.raises(ts.Skipped) as e:
            ts.connect(environ={}, cwd=str(linked))
        assert e.value.reason == "primary-unresolved", e.value.line
        assert "dubious ownership" in e.value.line, e.value.line
        assert "\n" not in e.value.line


class TestAStoreNamedDotGit:
    """(c) #612 gap 1, from the primary itself."""

    def test_the_primary_names_itself_not_the_stores_parent(self, tmp_path):
        stores = tmp_path / "stores" / "proj"
        stores.mkdir(parents=True)
        primary = tmp_path / "proj"
        layouts.git(
            tmp_path,
            "init",
            "-q",
            "-b",
            "main",
            "--separate-git-dir",
            str(stores / ".git"),
            str(primary),
        )
        assert ts.project_root(str(primary)).resolve() == primary.resolve()
        sub = primary / "a"
        sub.mkdir()
        assert ts.project_root(str(sub)).resolve() == primary.resolve()


def _resolver(cwd: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.pop("WORKTREE_ROOT", None)
    return subprocess.run(
        ["bash", str(RESOLVE), "--project-root"],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def _plain(tmp_path: Path) -> Path:
    return layouts.seed(tmp_path / "plain", "direct\n")


def _plain_linked(tmp_path: Path) -> Path:
    return _linked(tmp_path)[1]


def _submodule(tmp_path: Path) -> Path:
    """The submodule's own checkout; the builder adds a linked worktree too."""
    layouts.submodule_linked(tmp_path, "direct\n")
    return tmp_path / "super" / "sub"


def _separate_primary(tmp_path: Path) -> Path:
    return layouts.separate_git_dir(tmp_path, None)[0]


PARITY = {
    "plain": _plain,
    "plain_linked": _plain_linked,
    "submodule": _submodule,
    "submodule_linked": lambda t: layouts.submodule_linked(t, "direct\n"),
    "bare_home": lambda t: layouts.bare_home(t, "direct\n"),
    "separate_git_dir_primary": _separate_primary,
}


class TestParityWithTheResolver:
    """A layout that resolved at fb4ac041 resolves the same way: as
    `resolve-worktree-root.sh --project-root` names it."""

    @pytest.mark.parametrize("layout", sorted(PARITY))
    def test_project_root_is_the_resolvers_project_root(self, tmp_path, layout):
        cwd = PARITY[layout](tmp_path / "l")
        r = _resolver(cwd)
        assert r.returncode == 0, r.stderr
        assert ts.project_root(str(cwd)).resolve() == Path(r.stdout.strip()).resolve()

    def test_a_linked_worktree_of_a_separate_git_dir_primary_refuses_as_it_does(
        self, tmp_path
    ):
        """No path from here to the primary's work tree: the resolver's exit 2
        is project_root's PrimaryUnresolved, saying to run from the primary."""
        _, linked = layouts.separate_git_dir(tmp_path / "l", None)
        assert _resolver(linked).returncode == 2
        with pytest.raises(ts.PrimaryUnresolved) as e:
            ts.project_root(str(linked))
        assert "run this from the primary checkout" in str(e.value), str(e.value)

    def test_a_failed_worktree_list_is_said_as_such(self, tmp_path, monkeypatch):
        """CR 2290: read as "not bare", it ended as the --separate-git-dir
        message, which says nothing true about git failing."""
        _, linked = layouts.separate_git_dir(tmp_path / "l", None)
        real = subprocess.run(
            ["sh", "-c", "command -v git"], capture_output=True, text=True, check=True
        ).stdout.strip()
        shim = tmp_path / "bin"
        shim.mkdir()
        (shim / "git").write_text(
            "#!/bin/sh\n"
            'case " $* " in *" worktree list "*) echo "fatal: shim says no" >&2; exit 128 ;; esac\n'
            f'exec "{real}" "$@"\n'
        )
        (shim / "git").chmod(0o755)
        monkeypatch.setenv("PATH", f"{shim}{os.pathsep}{os.environ['PATH']}")
        with pytest.raises(ts.PrimaryUnresolved) as e:
            ts.project_root(str(linked))
        assert "git worktree list failed" in str(e.value), str(e.value)
        assert "shim says no" in str(e.value), str(e.value)
