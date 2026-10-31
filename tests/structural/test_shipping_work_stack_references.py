"""The one shipping-work skill keeps what each variant's SKILL.md promised (#537).

The variants' next-steps categories, and the fastapi variant's worktree-aware
merge, are held by test_content_invariants.py against each variant's
SKILL.md. Folded into one skill, the categories live in
`references/stack-<framework>.md` and the merge step in SKILL.md itself.
These are the same assertions against their new homes, so the variants can
go without the content they carried going with them.

No API calls.
"""

from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "skills" / "shipping-work"

CATEGORIES = {
    "php": ("ACF JSON sync", "Asset build", "WP-CLI cache", "Composer deps"),
    "fastapi": (
        "DB migration",
        "Service restart",
        "Integration tests",
        "Env var",
        "Dev-server cleanup",
    ),
    "click": ("Dep update", "Cross-package consumer", "Pydantic pin", "New command"),
}


@pytest.mark.parametrize("framework", sorted(CATEGORIES))
def test_each_frameworks_next_steps_categories_are_kept(framework):
    text = (SKILL / "references" / f"stack-{framework}.md").read_text()
    missing = [c for c in CATEGORIES[framework] if c not in text]
    assert not missing, f"stack-{framework}.md lost next-steps categories: {missing}"


@pytest.mark.parametrize("framework", sorted(CATEGORIES))
def test_skill_md_routes_each_framework_to_its_file(framework):
    """The Detected line names the framework; SKILL.md must name its file."""
    body = (SKILL / "SKILL.md").read_text()
    assert f"references/stack-{framework}.md" in body


def test_the_worktree_aware_merge_step_is_kept():
    """It closed the loop #10 opened, and was never FastAPI-specific."""
    body = (SKILL / "SKILL.md").read_text()
    assert "Step 2.5 — Worktree-aware merge" in body
    assert "using-git-worktrees" in body


def test_the_click_rationalization_is_kept():
    text = (SKILL / "references" / "stack-click.md").read_text()
    assert "No tests/ directory means nothing to verify" in text
