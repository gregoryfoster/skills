"""CR 1901 — the hand-uninstall step names every file the refresh hook leaves in `.git/`.

`references/auto-refresh-hook.md`'s "Uninstalling by hand" ends with an `rm`
of the hook's files under the git dir, introduced by a sentence that says
which of them outlive a completed run. It said "all but the lock and the
log are transient", but `skills-update.commit-kills` (#575) outlives
completed runs by design: it is the count of commit-stage kills in a row,
and only a commit that returns removes it. An operator who believes it
transient can read a stale one as a crash's leftover.

Two checks, both derived where they can be:
- every file the hook names under `$gitdir` — a variable assigned from it,
  and each suffix the script adds to one of those (`.tmp`, `.lock`, the
  heal's `.heal.<pid>.<epoch>`) — is in the uninstall commands;
- the sentence names the kill count beside the lock and the log as the
  files that are not transient.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = ROOT / "skills/managing-skills/scripts/skills-submodule-update.sh"
DOC = ROOT / "skills/managing-skills/references/auto-refresh-hook.md"

ASSIGNED = re.compile(r'^\s*([A-Z_]+)="\$gitdir/([\w.-]+)"', re.M)


def _hook_files() -> set[str]:
    text = HOOK.read_text()
    files = set()
    for var, name in ASSIGNED.findall(text):
        files.add(name)
        # "$VAR.suffix" — a sibling the script writes beside it.
        for suffix in re.findall(rf'"\${var}(\.[a-z]+)', text):
            files.add(name + suffix)
    return files


def _uninstall_section() -> str:
    text = DOC.read_text()
    start = text.index("## Uninstalling by hand")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


def test_the_derivation_sees_the_files_it_must():
    """Vacuity guard: a regex that matched nothing would pass the rest."""
    files = _hook_files()
    for name in (
        "skills-update.lock",
        "skills-update.log",
        "skills-update.staging",
        "skills-update.commit-kills",
        "skills-update.pr-index",
    ):
        assert name in files, sorted(files)


def test_every_file_the_hook_writes_is_in_the_uninstall_commands():
    section = _uninstall_section()
    missing = []
    for name in sorted(_hook_files()):
        if name.endswith(".heal"):
            ok = "skills-update.staging.heal.*" in section
        else:
            ok = f".git/{name}" in section
        if not ok:
            missing.append(name)
    assert missing == [], (
        f"the hook writes .git/{missing} but the hand-uninstall step does not remove them"
    )


def test_the_kill_count_is_not_called_transient():
    section = _uninstall_section()
    sentence = next(s for s in re.split(r"(?<=[.:])\s", section) if "transient" in s)
    assert "kill count" in sentence, (
        "the uninstall step calls every file but the lock and the log "
        "transient, and skills-update.commit-kills outlives completed runs: " + sentence
    )
