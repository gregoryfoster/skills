"""doc-check.sh says when a branch's `.skills/merge_mode` change leaves a rendered artifact to re-render (#647).

`install-cadence.sh` renders `.github/workflows/context-cadence.yml` by the
merge mode it reads from the primary checkout. On a cohort host the knob was
set to `pr` and the workflow kept pushing to the default branch, because
nothing re-ran the renderer. A plain re-render on the knob-flip branch itself
doesn't help: from a linked worktree the renderer reads the primary's knob,
the old mode, and renders that in silence.

`shipping-work`'s doc-check (Step 1.5) treats a changed `.skills/merge_mode`
as touching every knob-rendered artifact that is installed. It is a hit, exit
1, the code that asks the shipper to look. A renderer it can't find or that
fails is said, never exit 2: the doc check itself ran.

Since #674 it reads the knob as the branch commits it and runs the renderer's
`--check --merge-mode <mode>`. A branch whose workflow is already that render
is told so; otherwise the in-branch `install-cadence.sh --merge-mode <mode>`
comes before "re-render after the merge", so the knob and its render can land
in one PR.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.structural.doc_check_fixtures import (
    CLICK_LIVE_TREE,
    make_repo,
    run_doc_check,
    run_git,
)
from tests.utils.skill_loader import SKILLS_DIR

INSTALL_CADENCE = SKILLS_DIR / "curating-context" / "scripts" / "install-cadence.sh"
WF = ".github/workflows/context-cadence.yml"
RENDERER = "skills/curating-context/scripts/install-cadence.sh"


def _with_cadence(repo: Path, *, renderer: bool = True) -> None:
    """The cadence workflow rendered on main, and the renderer where the
    workflow looks for it."""
    run_git(repo, "checkout", "-q", "main")
    if renderer:
        link = repo / RENDERER
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(INSTALL_CADENCE)
    out = repo / WF
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["bash", str(INSTALL_CADENCE), "--print"],
        cwd=repo,
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    out.write_text(r.stdout)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "cadence")
    run_git(repo, "checkout", "-q", "feature")
    run_git(repo, "merge", "-q", "--no-edit", "main")


def _flip_knob(repo: Path, word: str = "pr") -> None:
    (repo / ".skills").mkdir(exist_ok=True)
    (repo / ".skills" / "merge_mode").write_text(word + "\n")
    run_git(repo, "add", ".skills/merge_mode")
    run_git(repo, "commit", "-q", "-m", "merge_mode " + word)


def test_a_knob_flip_says_to_re_render_after_the_merge(tmp_path):
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    _with_cadence(repo)
    _flip_knob(repo)
    r = run_doc_check(repo)
    assert r.returncode == 1, r.stdout + r.stderr
    text = " ".join(r.stdout.split())
    assert ".skills/merge_mode" in text, r.stdout
    assert WF in text, r.stdout
    assert "after this branch merges" in text, r.stdout
    assert RENDERER in text, r.stdout
    assert "install-cadence.sh --check names" in text, r.stdout
    # The renderer's own verdict, read from its --check.
    assert "re-render:" in r.stdout, r.stdout


def test_the_advisory_rides_beside_a_sensitive_path_hit(tmp_path):
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["AGENTS.md"])
    _with_cadence(repo)
    _flip_knob(repo)
    r = run_doc_check(repo)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Sensitive paths changed" in r.stdout, r.stdout
    assert "after this branch merges" in " ".join(r.stdout.split()), r.stdout


def test_no_knob_change_says_nothing_about_renders(tmp_path):
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    _with_cadence(repo)
    r = run_doc_check(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert WF not in r.stdout, r.stdout


def test_no_installed_artifact_says_nothing(tmp_path):
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    _flip_knob(repo)
    r = run_doc_check(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert WF not in r.stdout, r.stdout


def test_a_renderer_it_cannot_find_is_said_and_still_a_hit(tmp_path):
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    _with_cadence(repo, renderer=False)
    _flip_knob(repo)
    r = run_doc_check(repo)
    assert r.returncode == 1, r.stdout + r.stderr
    text = " ".join(r.stdout.split())
    assert "no install-cadence.sh" in text, r.stdout
    assert "after this branch merges" in text, r.stdout


# --- #674: the branch can carry its own re-render ---------------------------
#
# install-cadence.sh --merge-mode renders for the mode named, so the branch
# that flips the knob can carry the workflow's re-render. The doc check reads
# the knob as the branch COMMITS it and asks the renderer's --check whether
# the branch's workflow is already that mode's render.


def _render_on_branch(repo: Path, mode: str) -> None:
    r = subprocess.run(
        ["bash", str(INSTALL_CADENCE), "--merge-mode", mode],
        cwd=repo,
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "re-render for " + mode)


def test_a_differing_render_offers_the_in_branch_command_first(tmp_path):
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    _with_cadence(repo)
    _flip_knob(repo)
    r = run_doc_check(repo)
    assert r.returncode == 1, r.stdout + r.stderr
    text = " ".join(r.stdout.split())
    cmd = f"bash {RENDERER} --merge-mode pr"
    assert cmd in text, r.stdout
    assert text.index(cmd) < text.index("after this branch merges"), r.stdout
    assert "already carries" not in text, r.stdout


def test_a_branch_that_carries_its_render_says_so(tmp_path):
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    _with_cadence(repo)
    _flip_knob(repo)
    _render_on_branch(repo, "pr")
    r = run_doc_check(repo)
    assert r.returncode == 1, r.stdout + r.stderr
    text = " ".join(r.stdout.split())
    assert "already carries its pr render" in text, r.stdout
    assert "after this branch merges" not in text, r.stdout
    assert "re-render: none" in text, r.stdout


def test_a_linked_worktree_branch_that_carries_its_render_says_so(tmp_path):
    """#674's own shape: the primary is on main with no knob, and the branch
    that sets it is a linked worktree, whose plain re-render reads `direct`."""
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    _with_cadence(repo)
    run_git(repo, "checkout", "-q", "main")
    wt = tmp_path / "wt"
    run_git(repo, "worktree", "add", "-q", "-b", "flip", str(wt), "feature")
    _flip_knob(wt)
    before = run_doc_check(wt)
    assert "--merge-mode pr" in " ".join(before.stdout.split()), before.stdout
    _render_on_branch(wt, "pr")
    r = run_doc_check(wt)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "already carries its pr render" in " ".join(r.stdout.split()), r.stdout


def test_a_knob_deleted_on_the_branch_reads_direct(tmp_path):
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    run_git(repo, "checkout", "-q", "main")
    _flip_knob(repo)
    _with_cadence(repo)  # rendered for pr on main, merged into feature
    run_git(repo, "rm", "-q", ".skills/merge_mode")
    run_git(repo, "commit", "-q", "-m", "back to direct")
    r = run_doc_check(repo)
    assert r.returncode == 1, r.stdout + r.stderr
    text = " ".join(r.stdout.split())
    assert f"bash {RENDERER} --merge-mode direct" in text, r.stdout
    _render_on_branch(repo, "direct")
    again = " ".join(run_doc_check(repo).stdout.split())
    assert "already carries its direct render" in again, again


def test_an_unusable_committed_knob_offers_no_command(tmp_path):
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    _with_cadence(repo)
    _flip_knob(repo, "PR")
    r = run_doc_check(repo)
    assert r.returncode == 1, r.stdout + r.stderr
    text = " ".join(r.stdout.split())
    assert "unusable" in text and "'PR'" in text, r.stdout
    assert "--merge-mode" not in text, r.stdout


def test_the_committed_knob_is_read_not_the_working_file(tmp_path):
    """The job reads what is committed, so an uncommitted edit doesn't count."""
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    _with_cadence(repo)
    _flip_knob(repo)
    (repo / ".skills" / "merge_mode").write_text("direct\n")
    r = run_doc_check(repo)
    assert "--merge-mode pr" in " ".join(r.stdout.split()), r.stdout


# --- CR 2568, 2570 b/f: the committed knob behind a link; what --check prints


def _commit_link(repo: Path, link: str, target: str, files: dict[str, str]) -> None:
    for rel, body in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    lp = repo / link
    lp.parent.mkdir(parents=True, exist_ok=True)
    if lp.is_symlink() or lp.exists():
        lp.unlink()
    lp.symlink_to(target)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "link " + link)


def test_a_knob_committed_as_a_symlink_is_read_through_it(tmp_path):
    """CR 2568: the job's `[ -f ]` follows the link, so doc-check does too."""
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    _with_cadence(repo)
    _commit_link(
        repo,
        ".skills/merge_mode",
        "merge_mode.shared",
        {".skills/merge_mode.shared": "pr\n"},
    )
    text = " ".join(run_doc_check(repo).stdout.split())
    assert "unusable" not in text, text
    assert f"bash {RENDERER} --merge-mode pr" in text, text


def test_a_symlinked_skills_dir_is_read_through_it(tmp_path):
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    _with_cadence(repo)
    _commit_link(repo, ".skills", "config/skills", {"config/skills/merge_mode": "pr\n"})
    text = " ".join(run_doc_check(repo).stdout.split())
    assert f"bash {RENDERER} --merge-mode pr" in text, text


def test_a_dangling_knob_link_is_unusable_as_the_job_finds_it(tmp_path):
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    _with_cadence(repo)
    _commit_link(repo, ".skills/merge_mode", "nowhere", {})
    text = " ".join(run_doc_check(repo).stdout.split())
    assert "unusable" in text and "--merge-mode" not in text, text
    # CR 2573 a: the reason, not only the verdict.
    assert "isn't in the tree" in text, text
    assert "other than a regular file" not in text, text


@pytest.mark.parametrize(
    ("target", "files"),
    [
        ("/etc/merge_mode", {}),
        ("hop", {".skills/far": "pr\n"}),
    ],
    ids=["outside-the-tree", "two-hops"],
)
def test_a_link_doc_check_cannot_follow_is_said_not_guessed(tmp_path, target, files):
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    _with_cadence(repo)
    if target == "hop":
        (repo / ".skills").mkdir(exist_ok=True)
        (repo / ".skills" / "hop").symlink_to("far")
    _commit_link(repo, ".skills/merge_mode", target, files)
    text = " ".join(run_doc_check(repo).stdout.split())
    assert "check it by hand" in text, text
    assert "--merge-mode" not in text and "the job refuses" not in text, text


def test_carrying_a_direct_render_names_no_merge_mode_line(tmp_path):
    """CR 2570 b: --check prints no merge mode line for a direct knob."""
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    run_git(repo, "checkout", "-q", "main")
    _flip_knob(repo)
    _with_cadence(repo)
    run_git(repo, "rm", "-q", ".skills/merge_mode")
    run_git(repo, "commit", "-q", "-m", "back to direct")
    _render_on_branch(repo, "direct")
    text = " ".join(run_doc_check(repo).stdout.split())
    assert "already carries its direct render" in text, text
    assert "and merge mode direct" not in text, text
    assert "'merge mode:" not in text.split("says:")[0], text


def test_carrying_a_pr_render_names_the_line_check_prints(tmp_path):
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    _with_cadence(repo)
    _flip_knob(repo)
    _render_on_branch(repo, "pr")
    text = " ".join(run_doc_check(repo).stdout.split())
    # Described, not quoted: --check pads the line (CR 2570 b, CR 2573).
    assert "pr on its merge mode: line" in text, text


def test_an_uncommitted_render_is_not_called_carried(tmp_path):
    """CR 2570 f: Step 1.5 runs before the commit, and --check reads the
    working file. A render in the tree but not in HEAD is not carried yet."""
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    _with_cadence(repo)
    _flip_knob(repo)
    r = subprocess.run(
        ["bash", str(INSTALL_CADENCE), "--merge-mode", "pr"],
        cwd=repo,
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    text = " ".join(run_doc_check(repo).stdout.split())
    assert "already carries" not in text, text
    assert "not committed" in text, text


# --- CR 2572, 2573: a retargeted link under a linked .skills; a target under a file


def test_a_knob_link_retargeted_under_a_linked_skills_dir_is_a_hit(tmp_path):
    """CR 2572: `.skills -> cfg`, and `cfg/merge_mode` moves from `other`
    (direct) to `real` (pr). The diff names only cfg/merge_mode, the link's
    own path, which the trigger must still match."""
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    run_git(repo, "checkout", "-q", "main")
    (repo / "cfg").mkdir()
    (repo / "cfg" / "real").write_text("pr\n")
    (repo / "cfg" / "other").write_text("direct\n")
    (repo / ".skills").symlink_to("cfg")
    (repo / "cfg" / "merge_mode").symlink_to("other")
    _with_cadence(repo)
    _commit_link(repo, "cfg/merge_mode", "real", {})
    changed = run_git(repo, "diff", "--name-only", "main...HEAD").stdout.split()
    knobbish = [p for p in changed if p.startswith((".skills", "cfg/"))]
    assert knobbish == ["cfg/merge_mode"], changed
    r = run_doc_check(repo)
    assert r.returncode == 1, r.stdout + r.stderr
    assert f"bash {RENDERER} --merge-mode pr" in " ".join(r.stdout.split()), r.stdout


def test_a_knob_link_through_a_regular_file_is_unusable(tmp_path):
    """CR 2573 b: `.skills/merge_mode -> ../conf/x` with `conf` a FILE saying
    pr. The job's read step refuses it (-L, not -f); conf is not the knob."""
    repo = make_repo(tmp_path, CLICK_LIVE_TREE, ["docs/notes.md"])
    _with_cadence(repo)
    _commit_link(repo, ".skills/merge_mode", "../conf/x", {"conf": "pr\n"})
    text = " ".join(run_doc_check(repo).stdout.split())
    assert "unusable" in text, text
    assert "--merge-mode" not in text, text
