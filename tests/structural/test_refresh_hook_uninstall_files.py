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

CR 1909 — the derivation is held to the suffixed files too, in either
quoting (`"$VAR.suffix"` and `"$VAR".suffix`), or the check passed on none.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = ROOT / "skills/managing-skills/scripts/skills-submodule-update.sh"
DOC = ROOT / "skills/managing-skills/references/auto-refresh-hook.md"

ASSIGNED = re.compile(r'^\s*([A-Z_]+)="\$gitdir/([\w.-]+)"', re.M)


def _hook_files(text: str | None = None) -> set[str]:
    if text is None:
        text = HOOK.read_text()
    files = set()
    for var, name in ASSIGNED.findall(text):
        files.add(name)
        # "$VAR.suffix" or "$VAR".suffix — a sibling the script writes
        # beside it.
        for suffix in re.findall(rf'"\${var}"?(\.[a-z]+)', text):
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
        # The suffixed siblings (CR 1909): without them the scan for
        # suffixes could find none and the next test would pass on nothing.
        "skills-update.commit-kills.tmp",
        "skills-update.pr-index.lock",
        "skills-update.staging.heal",
    ):
        assert name in files, sorted(files)


def test_a_suffix_after_the_closing_quote_is_seen():
    """CR 1909: `"$STAGING".heal…` — the spelling `_adopt_taken` already
    uses — names the same file as `"$STAGING.heal…`. Respelled so, the
    taken file vanished from the derivation, and dropping the uninstall
    step's `find … -delete` stayed green."""
    text = HOOK.read_text()
    respelled = text.replace('TAKEN="$STAGING.heal.', 'TAKEN="$STAGING".heal.')
    assert respelled != text, "fixture: TAKEN's assignment has moved"
    assert "skills-update.staging.heal" in _hook_files(respelled)


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
