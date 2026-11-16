"""Every instruction names the main checkout as git does (#614).

Set U's #587 rewrote shipping-work's post-merge pass to ask git for the
main checkout (`git -C <row> rev-parse --show-toplevel`), since the first
row of `git worktree list` is the bare repository in a bare layout and the
store in a `--separate-git-dir` one. Copies of the old "first row" rule
remained, and `using-git-worktrees`' by-hand venv link took the parent of
the common dir, the lookup set U removed from `worktree-create.sh`: in a
submodule it dangled, and it ignored `.skills/worktree_venv`.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.structural import merge_mode_layouts as layouts

REPO = Path(__file__).resolve().parent.parent.parent
UGW = REPO / "skills" / "using-git-worktrees"
SW = REPO / "skills" / "shipping-work"
DESTROY = UGW / "scripts" / "worktree-destroy.sh"

# The old rule, in each form it took: the first row's path as the checkout.
FIRST_ROW = [
    re.compile(r"git worktree list \| head -n ?1"),
    re.compile(r"awk '\{print \$1\}'"),
    re.compile(r"listed first in `git worktree list`"),
    re.compile(r"its path is the first row"),
]
SURFACES = sorted(
    p
    for d in (UGW, SW)
    for p in d.rglob("*")
    if p.is_file() and p.suffix in (".md", ".sh")
)


@pytest.mark.parametrize("path", SURFACES, ids=lambda p: str(p.relative_to(REPO)))
def test_no_copy_takes_the_first_row_for_the_main_checkout(path: Path):
    text = path.read_text()
    hits = [rx.pattern for rx in FIRST_ROW if rx.search(text)]
    assert not hits, f"{path.relative_to(REPO)} still reads the first row: {hits}"


def _venv_command() -> str:
    """The by-hand venv link, from whichever of the skill's docs gives it."""
    for doc in [UGW / "SKILL.md", *sorted((UGW / "references").glob("*.md"))]:
        for block in re.findall(r"```bash\n(.*?)```", doc.read_text(), re.S):
            if "ln -s" in block and ".venv" in block:
                return block
    raise AssertionError("no by-hand venv link in using-git-worktrees' docs")


def _link(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", _venv_command()],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=layouts.env(),
        timeout=30,
    )


def _venv(checkout: Path) -> None:
    (checkout / ".venv" / "bin").mkdir(parents=True)


def test_the_by_hand_link_is_the_primarys_venv(tmp_path):
    primary = layouts.seed(tmp_path / "p", "direct\n")
    _venv(primary)
    wt = tmp_path / "wt"
    layouts.git(primary, "worktree", "add", "-q", "-b", "feature/x", str(wt))
    r = _link(wt)
    assert r.returncode == 0, r.stderr
    assert (wt / ".venv").resolve() == (primary / ".venv").resolve()


def test_in_a_submodule_the_link_does_not_dangle(tmp_path):
    """#614's reproduction: the parent of a submodule's common dir is
    `<super>/.git/modules`, which holds no .venv."""
    wt = layouts.submodule_linked(tmp_path, "direct\n")
    sub = tmp_path / "super" / "sub"
    _venv(sub)
    r = _link(wt)
    assert r.returncode == 0, r.stderr
    assert (wt / ".venv").is_symlink()
    assert (wt / ".venv").resolve() == (sub / ".venv").resolve(), "the link dangles"


def test_the_link_honours_worktree_venv_none(tmp_path):
    """#614's reproduction: the by-hand link ignored .skills/worktree_venv."""
    primary = layouts.seed(tmp_path / "p", "direct\n")
    _venv(primary)
    layouts.knob(primary, "# the service runs here\nnone\n", "worktree_venv")
    wt = tmp_path / "wt"
    layouts.git(primary, "worktree", "add", "-q", "-b", "feature/x", str(wt))
    r = _link(wt)
    assert r.returncode == 0, r.stderr
    assert not (wt / ".venv").exists() and not (wt / ".venv").is_symlink()


def test_a_bare_primary_links_nothing(tmp_path):
    """No work tree to ask: the command fails, and the reference says what
    to do, rather than linking a .venv that isn't there."""
    home = layouts.bare_home(tmp_path, "direct\n")
    r = _link(home)
    assert r.returncode != 0
    assert not (home / ".venv").is_symlink()


def test_destroying_this_worktree_names_the_main_checkout(tmp_path):
    """#614: worktree-destroy.sh said `cd to the main checkout first: git
    worktree list | head -n1`, which in a bare layout names repo.git."""
    primary = layouts.seed(tmp_path / "p", "direct\n")
    wt = tmp_path / "wts" / "feature-x"
    layouts.git(primary, "worktree", "add", "-q", "-b", "feature/x", str(wt))
    env = {**layouts.env(), "WORKTREE_ROOT": str(tmp_path / "wts")}
    r = subprocess.run(
        ["bash", str(DESTROY), "feature/x", "--dry-run"],
        cwd=wt,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert r.returncode == 2, r.stdout + r.stderr
    assert f"cd {primary.resolve()}" in r.stderr, r.stderr
    assert "head -n1" not in r.stderr, r.stderr


def test_in_a_bare_layout_it_points_to_the_reference(tmp_path):
    home = layouts.bare_home(tmp_path, "direct\n")
    env = {**layouts.env(), "WORKTREE_ROOT": str(tmp_path / "wts")}
    r = subprocess.run(
        ["bash", str(DESTROY), "main", "--dry-run"],
        cwd=home,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert r.returncode == 2, r.stdout + r.stderr
    assert "main-checkout.md" in r.stderr, r.stderr
    assert "repo.git" not in r.stderr.split("refusing", 1)[-1], r.stderr
