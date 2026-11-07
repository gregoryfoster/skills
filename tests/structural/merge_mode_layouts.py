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
`direct` in silence. A third, `separate_git_dir` (CR 1892), names a store no
`-C` can resolve; it is kept out of LAYOUTS because from its linked worktree
the honest answer is unusable. Each builder here returns the checkout to read from, with
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


def separate_git_dir(tmp_path: Path, text: str | None) -> tuple[Path, Path]:
    """A primary whose `.git` is a pointer file to a store outside its work
    tree (`git init --separate-git-dir`), and a linked worktree of it; the
    knob, when `text` is given, untracked in the primary. Returns
    `(primary, linked)`.

    The first block names the store: no `bare` line and no `core.worktree`,
    so `git -C <store> rev-parse --show-toplevel` fails ("must be run in a
    work tree") and no reader can name the primary's work tree from it (CR
    1892). From the primary itself that work tree is this checkout, whose git
    dir is the common dir. From the linked worktree git knows no path to it,
    so a reader there is unusable, honestly, and not in LAYOUTS: every
    LAYOUTS entry reads `pr` from its checkout.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    primary = tmp_path / "work"
    git(
        tmp_path,
        "init",
        "-q",
        "-b",
        "main",
        "--separate-git-dir",
        str(tmp_path / "store.git"),
        str(primary),
    )
    git(primary, "config", "user.email", "test@example.com")
    git(primary, "config", "user.name", "test")
    (primary / "README.md").write_text("x\n")
    git(primary, "add", "-A")
    git(primary, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init")
    if text is not None:
        knob(primary, text)
    linked = tmp_path / "wt"
    git(primary, "worktree", "add", "-q", "-b", "feature/x", str(linked))
    first = git(linked, "worktree", "list", "--porcelain").split("\n\n")[0]
    assert first.splitlines()[0].endswith("/store.git"), first
    assert "\nbare" not in first, first
    return primary, linked


# A linked worktree's message names the layout it cannot read, as long as git
# can open the store; "dubious ownership" is git's reason alone.
SEPARATE_GIT_DIR_HINT = "--separate-git-dir"


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
