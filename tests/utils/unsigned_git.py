"""Fixture commits never sign, whatever the caller's git config says (#546).

The suite's fixture repos commit with the caller's git config, so they used to
inherit `commit.gpgsign=true` wherever the caller set it. In a cloud session
every fixture commit then went through the session's signing helper, which
leaked a file descriptor per call: five full runs exhausted it, and from then
on every commit in the session failed, the session's own included. Locally a
signing setup that prompts, or needs an agent, would stall the suite.

Why `HOME`, and not something narrower:

- `GIT_CONFIG_GLOBAL` / `GIT_CONFIG_*` never reach most fixtures: they scrub
  `GIT_*` from the environment they hand git (#189).
- A `-c commit.gpgsign=false` at each fixture commit misses the commits the
  scripts under test make themselves (install-hook, install-cadence,
  skills-submodule-update, ...), and there are over 200 sites in test code.
- `HOME` survives every scrub, and git reads `~/.gitconfig` after
  `$XDG_CONFIG_HOME/git/config`, so a value set there wins over both.

So `isolate` points `HOME` at a directory that mirrors the real one entry by
entry, through symlinks, so a test that reads `HOME` sees the same content.
Only `.gitconfig` differs: it includes the caller's own global config, then
turns signing off. If the caller set `GIT_CONFIG_GLOBAL`, that file is the one
included, and the variable is repointed at the new config, so a fixture that
does not scrub `GIT_*` gets the same answer as one that does.

It runs once per session tree: xdist workers and nested pytest runs inherit
the isolated `HOME` and the marker below, and leave both alone.
"""

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

MARKER = "SKILLS_TESTS_REAL_HOME"
UNSIGNED = """\
[commit]
\tgpgSign = false
[tag]
\tgpgSign = false
\tforceSignAnnotated = false
[push]
\tgpgSign = false
"""


def _quoted(path: str) -> str:
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Isolation:
    root: Path
    saved: dict = field(default_factory=dict)  # name -> value, None if unset


def isolate(environ=os.environ) -> Isolation | None:
    """Point `environ`'s HOME at an unsigned mirror; None if nothing to do.

    Nothing to do means no HOME, or a parent session already isolated this
    one.
    """
    if MARKER in environ or not environ.get("HOME"):
        return None
    real = Path(environ["HOME"])
    source = environ.get("GIT_CONFIG_GLOBAL") or str(real / ".gitconfig")
    done = Isolation(Path(tempfile.mkdtemp(prefix="skills-tests-home-")))
    home = done.root / "home"
    home.mkdir()
    # A HOME it can't list mirrors nothing but still gets the unsigned config:
    # signing off matters more than a test reading HOME (CR 1588).
    try:
        entries = list(real.iterdir()) if real.is_dir() else []
    except OSError:
        entries = []
    for entry in entries:
        if entry.name != ".gitconfig":
            (home / entry.name).symlink_to(entry)
    # A missing include is silently skipped by git, which is the right answer
    # for a caller with no global config.
    (home / ".gitconfig").write_text(
        f"[include]\n\tpath = {_quoted(source)}\n" + UNSIGNED
    )
    for name in (MARKER, "HOME", "GIT_CONFIG_GLOBAL"):
        done.saved[name] = environ.get(name)
    environ[MARKER] = str(real)
    environ["HOME"] = str(home)
    if "GIT_CONFIG_GLOBAL" in environ:
        environ["GIT_CONFIG_GLOBAL"] = str(home / ".gitconfig")
    return done


def restore(done: Isolation | None, environ=os.environ) -> None:
    """Undo `isolate`: put the environment back, remove the mirror, never its
    targets."""
    if done is None:
        return
    for name, value in done.saved.items():
        if value is None:
            environ.pop(name, None)
        else:
            environ[name] = value
    # Unlink the mirror's own links first, so nothing below can follow one
    # into the real HOME; whatever a test created there goes with the root.
    home = done.root / "home"
    if home.is_dir():
        for entry in home.iterdir():
            if entry.is_symlink():
                entry.unlink()
    shutil.rmtree(done.root, ignore_errors=True)
