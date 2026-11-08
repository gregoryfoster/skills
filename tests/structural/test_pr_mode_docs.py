"""The prose half of `.skills/merge_mode` (#342).

The scripts are pinned by behaviour elsewhere (`test_merge_mode_knob.py`,
`test_worktree_destroy_pr_mode.py`, `test_pr_mode_deploy.py`). What an agent
reads is pinned here: each step of `shipping-work` that `pr` mode changes says
so in one line and points at `references/pr-mode.md`, and `using-git-worktrees`
Phase 4 stops prescribing a local merge in a `pr` repo.

Three corrections to #342's Proposal live in the references and are pinned
because each is the easy thing to get wrong:

- `gh pr view` finds a branch's PR in any state, so "it found one, the push
  updated it" is true only of an `OPEN` PR (checked against gh 2.102.0).
- With `.skills/deploy_command`, a production requirement can't ride a
  `Closes` line: the merge would close it before the deploy ran.
- After a squash merge, the local branch may need `git branch -D`.

No API calls. Pure text.
"""

from __future__ import annotations

import pytest

from tests.utils.skill_loader import SKILLS_DIR

SW = SKILLS_DIR / "shipping-work"
WT = SKILLS_DIR / "using-git-worktrees"
PR_LINE = "**`pr` mode:**"


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = text.find("\n### ", start + len(heading))
    return text[start : nxt if nxt != -1 else len(text)]


def _read(path):
    return path.read_text() if path.exists() else ""


SW_MD = _read(SW / "SKILL.md")


@pytest.mark.parametrize(
    "heading",
    [
        "### Step 2.5 — Worktree-aware merge (if applicable)",
        "### Step 3 — Ensure on main",
        "### Step 4 — Push",
        "### Step 5 — Comment on GitHub issues",
        "### Step 6 — Close GitHub issues",
        "### Step 7 — Report",
        "### Step 8 — Deploy, or next-steps notification",
    ],
)
def test_each_step_pr_mode_changes_says_so(heading):
    assert PR_LINE in _section(SW_MD, heading), (
        f"shipping-work {heading!r} has no {PR_LINE} line"
    )


def test_the_mode_is_read_through_the_script_and_the_reference_is_linked():
    assert '"<merge-mode.sh>"' in SW_MD
    assert "](references/pr-mode.md)" in SW_MD


def test_step_3_says_the_pull_deploys_in_pr_mode_without_the_deploy_knob():
    step3 = _section(SW_MD, "### Step 3 — Ensure on main")
    assert "WorkingDirectory=" in step3 and "pull" in step3


SW_REF = _read(SW / "references" / "pr-mode.md")


@pytest.mark.parametrize(
    "needle",
    [
        '"state":"OPEN"',
        '"state":"MERGED"',
        '"state":"CLOSED"',
        "no pull requests found for branch",
        "gh pr create --base <default>",
        "Closes #<n>",
        "Refs #<n>",
        "git pull --ff-only",
        "run-deploy-command.sh",
        "git branch -D",
        "PR #<m> open, awaiting review",
    ],
)
def test_the_shipping_reference_covers(needle):
    assert needle in SW_REF, needle


def test_the_deploy_reference_states_pr_modes_branch_rule():
    text = (SW / "references" / "deploy-command.md").read_text()
    assert "merge_mode" in text and "default branch" in text


WT_MD = _read(WT / "SKILL.md")


def test_phase_4_routes_a_pr_repo_to_the_reference():
    phase4 = _section(WT_MD, "### Phase 4")
    assert ".skills/merge_mode" in phase4
    assert '"<merge-mode.sh>"' in phase4
    assert "](references/pr-mode.md)" in phase4
    assert "consult AGENTS.md for the project's PR-vs-direct-merge policy" not in (
        phase4
    ), "the knob replaces the AGENTS.md escape hatch"


def test_phase_5_names_the_merged_pr_evidence():
    phase5 = _section(WT_MD, "### Phase 5")
    assert "merged PR" in phase5


def test_the_venv_none_reason_notes_the_deploy_knob():
    venv = _section(WT_MD.replace("## Venv", "### Venv"), "### Venv linking")
    assert ".skills/deploy_command" in venv


WT_REF = _read(WT / "references" / "pr-mode.md")


@pytest.mark.parametrize(
    "needle",
    [
        "gh pr list --head <branch>",
        "git fetch origin",
        "--base <ref>",
        "--dry-run",
        "exit 2",
        "git pull --ff-only",
        "git branch -D",
    ],
)
def test_the_worktree_reference_covers(needle):
    assert needle in WT_REF, needle


def _post_merge_step_1() -> str:
    """The post-merge pass's first step, whitespace-normalised."""
    section = SW_REF[SW_REF.index("## The post-merge pass") :]
    step = section[section.index("1. **Move to the main checkout,**") :]
    return " ".join(step[: step.index("\n2. ")].split())


def test_the_post_merge_pass_can_be_followed_from_a_bare_primary():
    """#587: with a bare primary (`clone --bare` + `git worktree add`) the
    first row of `git worktree list` is the bare repository, which has no
    work tree to `git switch` in. The step names the checkout to use there,
    the linked worktree that holds the default branch, and what to do when
    none does."""
    step = _post_merge_step_1()
    assert "(bare)" in step, step
    assert "the linked worktree that holds the default branch" in step, step
    assert "If no worktree holds it, stop" in step, step


def test_a_bare_clones_missing_upstream_is_set_not_read_as_local_commits():
    """CR 2009: `git clone --bare` sets no upstream and no fetch refspec, so
    the pull says "There is no tracking information", or step 2's deploy
    says there is no upstream. Neither means local commits: only a refusal
    to fast-forward does. The step names the commands that set it."""
    step = _post_merge_step_1()
    assert "Only a pull that refuses to fast-forward" in step, step
    assert "There is no tracking information" in step, step
    assert "git branch --set-upstream-to=origin/<default>" in step, step
    assert "'+refs/heads/*:refs/remotes/origin/*'" in step, step
    # CR 2012: the steps in the order they work, the refspec first.
    refspec = step.index("remote.origin.fetch '+refs/heads/*")
    fetch = step.index("`git fetch origin`")
    upstream = step.index("--set-upstream-to=origin/<default>")
    assert refspec < fetch < upstream, step


def test_step_1_finds_the_main_checkout_by_asking_git():
    """CR 2010a: a --separate-git-dir store's row carries no marker, so "the
    work tree of the first row" could not be followed. One question covers
    every layout; test_primary_checkout_layouts.py holds git to its answers."""
    step = _post_merge_step_1()
    assert "`git -C <row> rev-parse --show-toplevel`" in step, step
    assert "**Marked `(bare)`:**" in step, step
    assert "**Unmarked:** the store of a primary made with" in step, step


def test_step_1_tells_a_refusal_from_a_layout():
    """CR 2027e: "dubious ownership" also makes the question fail, and read
    as "no work tree" it fell under the separate-git-dir bullet."""
    step = _post_merge_step_1()
    assert 'When it fails with "must be run in a work tree"' in step, step
    assert '"dubious ownership", is a refusal, not a layout' in step, step


def test_step_1_names_what_a_plain_bare_clones_pull_does():
    """CR 2027b: with no fetch refspec a plain bare clone's pull fetches
    origin's HEAD and fast-forwards with exit 0, so "There is no tracking
    information" never appears there: step 2's no-upstream is the trigger."""
    step = _post_merge_step_1()
    assert "With a fetch refspec, its pull says" in step, step
    assert "its pull fetches origin's HEAD and fast-forwards" in step, step
