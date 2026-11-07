"""CR 1914 — every read the refresh hook redirects from a file is guarded.

Another session can remove a file the hook reads between its `[ -f ]` and
the read: a taken `.heal.<pid>.<epoch>` adopted or dropped, the commit-kill
count reset. Under `set -e`, bash 5 exits on a failed redirect of a compound
command (`while … done <"$f"`), with the EXIT trap's report and nothing else;
bash 3.2 runs on with the loop skipped. `_drop_taken`'s loop read that way
and exited the hook silently, its marker left behind, when the file it was
reading went (reproduced in `bash:5`; this suite runs bash 3.2 only, so the
rule is held by shape).

So an input redirect from a variable's file, `<"$…"`, must be guarded on
its line: a `||` after it, or the condition of an `if`, `elif`, `while` or
`until` — places `set -e` does not reach. A deliberate unguarded one says
why on the line above: `# unguarded-read-ok: <reason>`.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = ROOT / "skills/managing-skills/scripts/skills-submodule-update.sh"

# `<"$x"`, `< "$x"`, `3<"$x"`; not a here-string (`<<<`) or a heredoc (`<<`).
READ = re.compile(r'(?<!<)<(?!<)\s*"\$')
CONDITION = re.compile(r"^\s*(if|elif|while|until)\s")
REASON = "# unguarded-read-ok:"


def _reads() -> list[tuple[int, str, str, str]]:
    lines = HOOK.read_text().splitlines()
    found = []
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        m = READ.search(line)
        if m:
            above = lines[i - 1] if i else ""
            found.append((i + 1, line, line[m.end() :], above))
    return found


def test_the_rule_finds_the_reads():
    """The pattern still sees the hook's reads; an empty scan proves nothing."""
    assert len(_reads()) >= 5, _reads()


def test_every_file_read_is_guarded_or_says_why():
    bad = [
        f"{n}: {line.strip()}"
        for n, line, after, above in _reads()
        if "||" not in after
        and not CONDITION.match(line)
        and not (above.lstrip().startswith(REASON) and above.split(":", 1)[1].strip())
    ]
    assert not bad, (
        'an unguarded `<"$…"` read exits the hook under `set -e` on bash 5 '
        "if its file is gone: guard it (`|| continue`, `|| true`) or say why "
        f"on the line above with `{REASON} <reason>`:\n" + "\n".join(bad)
    )
