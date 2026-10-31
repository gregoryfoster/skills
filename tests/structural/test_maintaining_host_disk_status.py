"""maintaining-host-disk: the SKILL.md status line says who has adopted it (#541).

"Status: new" outlived the first adoption by days. The line now names who
has adopted the skill and what is still unproven, dated and sourced, so the
next reader can tell how stale it is. It names public repos only: a private
repo or a cohort host's name doesn't belong in a public skill (#541's brief).
"""

from __future__ import annotations

import re

from tests.structural import maintaining_host_disk_rig as rig

STATUS_RE = re.compile(r"^\*\*Status:.*$", re.M)


def _status() -> str:
    lines = STATUS_RE.findall((rig.SKILL / "SKILL.md").read_text())
    assert len(lines) == 1, lines
    return lines[0]


def test_the_status_line_is_no_longer_new():
    assert not _status().startswith("**Status: new.**"), _status()


def test_the_status_line_is_dated_and_names_its_roster():
    line = _status()
    assert re.search(r"\[read 20\d\d-\d\d-\d\d\]", line), line
    assert "issues/510" in line, "the roster is #510's per-host bump list"


def test_the_status_line_names_no_private_repo_or_host():
    line = _status()
    assert "provisioner" not in line.lower(), line
    assert not re.search(r"\bco-[a-z]", line), line
    assert "still unproven" in line.lower(), line
