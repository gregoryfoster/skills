"""Utilities for loading and parsing SKILL.md files."""

import re
from dataclasses import dataclass
from pathlib import Path

import frontmatter

SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"


@dataclass
class Skill:
    """Parsed representation of a single SKILL.md file."""

    directory: Path
    skill_file: Path
    frontmatter: dict
    body: str

    @property
    def dir_name(self) -> str:
        return self.directory.name

    @property
    def name(self) -> str:
        return self.frontmatter.get("name", "")

    @property
    def description(self) -> str:
        return self.frontmatter.get("description", "")

    @property
    def compatibility(self) -> str:
        return self.frontmatter.get("compatibility", "")

    @property
    def skill_metadata(self) -> dict:
        """The nested 'metadata' block within frontmatter."""
        return self.frontmatter.get("metadata", {}) or {}

    @property
    def scripts_dir(self) -> Path:
        return self.directory / "scripts"

    def scripts(self) -> list[Path]:
        """Return all script files in the skills/scripts/ directory."""
        if not self.scripts_dir.exists():
            return []
        return sorted(self.scripts_dir.glob("*.sh"))

    def referenced_scripts(self) -> set[str]:
        """Extract script filenames the SKILL.md invokes from its own scripts/ dir.

        Two forms are recognized, both scoped to the skill's own context (never
        cross-skill references):

        - `bash "<SKILL_SCRIPTS>/filename.sh"` — the canonical placeholder form
          (see issue #63); `<SKILL_SCRIPTS>` is substituted with the literal path
          printed by the skill's resolution block.
        - `S=filename.sh` — the resolution block's target/sentinel script.

        The legacy `bash scripts/filename.sh` form is deliberately NOT matched:
        TestNoBareScriptPaths forbids it outright, so matching it here would
        encode two opposing expectations about the same string.
        """
        patterns = (
            r'bash\s+"<SKILL_SCRIPTS>/([^"\s]+\.sh)"',
            r"(?m)^\s*(?:N=\S+\s+)?S=([^\s\n]+\.sh)\b",
        )
        return {
            m.group(1) for p in patterns for m in re.finditer(p, self.body)
        }


def load_skill(skill_dir: Path) -> Skill:
    """Load and parse a SKILL.md from the given directory."""
    skill_file = skill_dir / "SKILL.md"
    post = frontmatter.load(str(skill_file))
    return Skill(
        directory=skill_dir,
        skill_file=skill_file,
        frontmatter=dict(post.metadata),
        body=post.content,
    )


def all_skills() -> list[Skill]:
    """Return all skills found in the skills/ directory."""
    return [
        load_skill(d)
        for d in sorted(SKILLS_DIR.iterdir())
        if d.is_dir() and (d / "SKILL.md").exists()
    ]
