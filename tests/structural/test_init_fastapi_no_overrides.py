"""`init-project-fastapi` scaffolds no override: symlinks plus configuration (#540).

Overrides drift from their upstream (#537 step 9), and the scaffold started
every new repo with one: a `skills/brainstorming/` copied from power-map with
its header renamed, plus two optional thin forks. Decided 2026-10-31, option
2: link obra's `brainstorming`, and move the project narrative into the
scaffolded AGENTS.md, which every session loads (`CLAUDE.md` is
`@AGENTS.md`) before obra's skill looks at the project. `writing-plans`'
narrative goes the same way, and the Step 2.5 fork becomes `shipping-work`'s
`.skills/deploy_command` (#345).

No API calls.
"""

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "init-project-fastapi"
SYMLINKS = SKILL / "references" / "skill-symlinks.md"
TEMPLATE = SKILL / "references" / "agents-md-template.md"
REPORT = SKILL / "references" / "completion-report.md"


def _phase_10_overrides() -> str:
    text = SYMLINKS.read_text()
    start = text.index("## Phase 10 — ", text.index("install the symlink doctor"))
    return text[start : text.index("## Phase 11")]


def test_phase_10_scaffolds_no_override():
    section = _phase_10_overrides()
    assert "— power-map" not in section, "the brainstorming copy is still made"
    assert "| `skills/brainstorming/` | `SKILL.md` |" not in section
    assert not re.search(r"\bfork the relevant\b", section), section
    assert "no local override" in section.lower(), section


def test_each_former_override_names_where_its_content_goes():
    section = _phase_10_overrides()
    assert "AGENTS.md" in section
    assert ".skills/deploy_command" in section
    assert ".skills/plans_dir" in section


def _retire_block() -> str:
    text = SYMLINKS.read_text()
    m = re.search(
        r"### Retiring an existing `skills/brainstorming/` override.*?```bash\n(.*?)```",
        text,
        re.S,
    )
    assert m, "no retirement recipe for an existing skills/brainstorming/ override"
    return m.group(1)


def _env() -> dict:
    """No inherited GIT_*: under a hook GIT_DIR would point the fixture at this repo (#189)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(),
    ).stdout


def test_the_retirement_recipe_leaves_obras_skill_linked(tmp_path):
    repo = tmp_path / "repo"
    obra = repo / "skills-vendor" / "obra-superpowers" / "skills" / "brainstorming"
    obra.mkdir(parents=True)
    (obra / "SKILL.md").write_text("---\nname: brainstorming\n---\n# upstream\n")
    override = repo / "skills" / "brainstorming"
    override.mkdir(parents=True)
    (override / "SKILL.md").write_text("---\nname: brainstorming\n---\n# — power-map\n")
    claude = repo / ".claude" / "skills"
    claude.mkdir(parents=True)
    (claude / "brainstorming").symlink_to("../../skills/brainstorming")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "commit.gpgsign=false",
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.com",
        "commit",
        "-q",
        "-m",
        "override",
    )
    subprocess.run(
        ["bash", "-euo", "pipefail", "-c", _retire_block()],
        cwd=repo,
        check=True,
        env=_env(),
    )
    link = repo / "skills" / "brainstorming"
    assert link.is_symlink()
    assert os.readlink(link) == "../skills-vendor/obra-superpowers/skills/brainstorming"
    assert (claude / "brainstorming" / "SKILL.md").read_text().endswith("# upstream\n")
    staged = _git(repo, "ls-files", "-s", "skills/brainstorming")
    assert staged.startswith("120000 "), staged


def test_the_retirement_recipe_moves_the_narrative_first():
    text = SYMLINKS.read_text()
    section = text.split(
        "### Retiring an existing `skills/brainstorming/` override", 1
    )[1]
    section = section.split("\n## ", 1)[0]
    assert "override-reason:" in section and "AGENTS.md" in section, section
    assert section.index("AGENTS.md") < section.index("```bash"), (
        "move the override's project deltas into AGENTS.md before deleting it"
    )


def _template_body() -> str:
    text = TEMPLATE.read_text()
    return text.split("```markdown\n", 1)[1]


def test_the_scaffolded_agents_md_carries_the_design_narrative():
    body = _template_body()
    m = re.search(r"^## Design & Planning\n(.*?)(?=^## )", body, re.M | re.S)
    assert m, "the scaffolded AGENTS.md has no Design & Planning section"
    section = m.group(1)
    for needle in (
        "brainstorming",
        "writing-plans",
        "docs/plans/",
        "gh issue create",
        "using-git-worktrees",
    ):
        assert needle in section, f"{needle!r} missing from Design & Planning"
    assert re.search(r"no brainstorming|not required|needs no", section), section


def test_the_completion_report_names_no_local_override():
    row = next(
        ln for ln in REPORT.read_text().splitlines() if ln.startswith("| Skills |")
    )
    assert "Local overrides" not in row, row
    assert "no local override" in row.lower(), row


def test_skill_md_no_longer_creates_overrides():
    text = (SKILL / "SKILL.md").read_text()
    assert "then create the local overrides" not in text
    assert "local skill overrides" not in text
    assert "Every local override `SKILL.md` declares" not in text


def test_the_plan_bullet_defers_to_writing_plans_own_phase_1():
    """CR 1538: AGENTS.md must not overrule writing-plans' Iron Law, only obra's handoff."""
    section = _template_body().split("## Design & Planning", 1)[1].split("\n## ", 1)[0]
    plan = next(ln for ln in section.splitlines() if ln.startswith("- **Plan:**"))
    assert "Phase 1" in plan, plan
    assert "only for" not in plan, plan
