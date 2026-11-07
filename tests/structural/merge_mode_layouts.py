"""The checkout layouts whose first `git worktree list` entry is a git dir.

`merge-mode.sh` (CR 1860) and the two inline readers that cannot call it
(#584) read `.skills/merge_mode` from the primary checkout, which is the
first `git worktree list --porcelain` block. In two layouts that block names
a git dir rather than a work tree:

- a **bare primary** (`repo.git`, with every checkout a linked worktree): the
  block carries a `bare` line, and the knob can only be the current
  checkout's;
- a **submodule** (`<super>/.git/modules/<n>`, git 2.54): the block carries
  no `bare` line, and `rev-parse --show-toplevel` there names the
  submodule's work tree through `core.worktree`.

Read as a checkout, neither holds `.skills/`, so a reader that did so said
`direct` in silence. Each builder here returns the checkout to read from, with
the knob where that layout keeps it. `different_owner` makes git refuse the
primary alone ("dubious ownership"), which must be a refusal, never a
fallback. Shared by test_merge_mode_knob.py, test_cadence_merge_mode.py and
test_refresh_hook_pr_mode.py; every git call scrubs the inherited `GIT_*`
variables and names its repo explicitly (#189).
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path


def env() -> dict:
    out = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    out["LC_ALL"] = "C"
    return out


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env(),
    ).stdout.strip()


def knob(repo: Path, text: str) -> Path:
    (repo / ".skills").mkdir(exist_ok=True)
    path = repo / ".skills" / "merge_mode"
    path.write_text(text)
    return path


def seed(path: Path, text: str) -> Path:
    """A one-commit repo whose commit carries the knob."""
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "test")
    knob(path, text)
    git(path, "add", "-A")
    git(path, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "knob")
    return path


def bare_home(tmp_path: Path, text: str) -> Path:
    """A bare primary, read from its linked worktree on main."""
    src = seed(tmp_path / "seed", text)
    bare = tmp_path / "repo.git"
    git(tmp_path, "clone", "-q", "--bare", str(src), str(bare))
    home = tmp_path / "home"
    git(bare, "worktree", "add", "-q", str(home), "main")
    assert git(home, "worktree", "list", "--porcelain").splitlines()[1] == "bare"
    return home


def submodule_linked(tmp_path: Path, text: str) -> Path:
    """A submodule's linked worktree; the knob is untracked in the
    submodule's own checkout, as a machine-local knob is."""
    src = seed(tmp_path / "src", "direct\n")
    sup = tmp_path / "super"
    sup.mkdir()
    git(sup, "init", "-q", "-b", "main")
    git(
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
    knob(sub, text)
    wt = tmp_path / "wt"
    git(sub, "worktree", "add", "-q", "-b", "feature/x", str(wt))
    assert "/.git/modules/" in git(wt, "worktree", "list", "--porcelain")
    return wt


LAYOUTS: dict[str, Callable[[Path, str], Path]] = {
    "bare_home": bare_home,
    "submodule_linked": submodule_linked,
}


def different_owner(base: dict, safe: Path) -> dict:
    """`base` with git told every repo has another owner, `safe` excepted:
    run from a linked worktree `safe`, only the primary is refused. The
    GIT_CONFIG_* pair replaces any the base carries."""
    out = dict(base)
    out.update(
        GIT_TEST_ASSUME_DIFFERENT_OWNER="1",
        GIT_CONFIG_COUNT="1",
        GIT_CONFIG_KEY_0="safe.directory",
        GIT_CONFIG_VALUE_0=str(safe.resolve()),
    )
    return out
