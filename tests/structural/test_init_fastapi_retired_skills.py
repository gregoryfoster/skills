"""`init-project-fastapi` scaffolds no retired skill (#537).

The scaffold is copied into every new repo, so a retired name in it plants a
link the doctor must later repoint — and a `skills/<old>/` path in the
scaffolded AGENTS.md holds that repoint until someone rewrites it by hand.
So the vendor loop links `shipping-work`, not a variant, and no file the skill
ships names a retired skill's path.

No API calls.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "init-project-fastapi"
SYMLINKS = SKILL / "references" / "skill-symlinks.md"


def _retired() -> list[str]:
    olds = []
    for raw in (ROOT / "retired-skills").read_text().splitlines():
        fields = raw.split("#", 1)[0].split()
        if fields:
            olds.append(fields[0])
    return olds


def _vendor_loop() -> str:
    text = SYMLINKS.read_text()
    block = re.search(r"## Phase 10 — vendor symlinks.*?```bash\n(.*?)```", text, re.S)
    assert block, "the Phase 10 vendor loop moved"
    return block.group(1)


def test_the_vendor_loop_links_shipping_work_and_no_variant(tmp_path: Path):
    for vendor, names in {
        "obra-superpowers": ["writing-plans", "brainstorming"],
        "gregoryfoster-skills": [
            "writing-plans",
            "reviewing-code",
            "reviewing-code-php",
            "reviewing-code-python-fastapi",
            "shipping-work",
            *_retired(),
        ],
    }.items():
        for name in names:
            (tmp_path / "skills-vendor" / vendor / "skills" / name).mkdir(parents=True)
    subprocess.run(["bash", "-c", _vendor_loop()], cwd=tmp_path, check=True)
    linked = sorted(p.name for p in (tmp_path / "skills").iterdir())
    assert linked == [
        "brainstorming",
        "reviewing-code-python-fastapi",
        "shipping-work",
        "writing-plans",
    ]


def test_no_file_the_skill_ships_names_a_retired_skills_path():
    hits = [
        f"{path.relative_to(ROOT)}: skills/{old}/"
        for path in SKILL.rglob("*")
        if path.is_file()
        for old in _retired()
        if f"skills/{old}/" in path.read_text(errors="replace")
    ]
    assert not hits, "\n".join(hits)
