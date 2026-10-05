"""patching-hosts' process log records counts and families, never versions
(#313, plan step 7).

The log is public, and a host's entry describes what it ran. Its "Adding an
entry" rule says an entry that lists pending security updates lands only after
they are applied, and records package families ("PostgreSQL 16", "a major
docker.io bump"), never versions: a published version still pending tells a
reader what the host is exposed to, and one already applied still dates the
host's patch level. Whether an update was applied when the entry landed can't
be read from the text, so the gate is the stricter half: no entry carries a
Debian package version at all.

A Debian version is recognised by the shapes the archive's own versions take:
an `ubuntu<N>` or `build<N>` revision, a `~24.04`-style backport suffix, an
epoch (`5:7.0.15`), a PGDG suffix, or an upstream version with a Debian
revision (`2.39-0ubuntu8`, `16.10-0`), or a bare three-part upstream version
(`28.2.2`). Calendar dates, durations, counts and a four-part IP address don't
match. A two-part version (`16.13`) reads like a decimal (`0.30 s`), so it
stays the author's to leave out.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

LOG = Path(__file__).resolve().parents[2] / "skills/patching-hosts/references"
ENTRIES = sorted(
    p for p in (LOG / "process-log").glob("*/*.md") if p.name != "index.md"
)
FILES = [
    LOG / "process-log.md",
    *sorted((LOG / "process-log").glob("*/index.md")),
    *ENTRIES,
]

VERSION = re.compile(
    r"ubuntu\d"
    r"|build\d"
    r"|~\d{2}\.\d{2}"
    r"|\b\d+:\d+\.\d+"
    r"|pgdg"
    r"|\b\d+(?:\.\d+)+-\d"
    r"|(?<![\d.])\d+\.\d+\.\d+(?![\d.])"
)


def test_the_log_has_entries() -> None:
    # A moved layout must not empty the parametrization into a green run.
    assert ENTRIES, f"no entries under {LOG / 'process-log'}"


@pytest.mark.parametrize("doc", FILES, ids=lambda p: p.name)
def test_no_entry_carries_a_package_version(doc: Path) -> None:
    hits = [
        (n, m.group(0))
        for n, line in enumerate(doc.read_text().splitlines(), 1)
        if (m := VERSION.search(line))
    ]
    assert not hits, (
        f"{doc.name} carries what reads as a package version: {hits}. "
        "process-log.md's 'Adding an entry' records counts and families, never versions."
    )


@pytest.mark.parametrize(
    "text, is_version",
    [
        ("2.39-0ubuntu8.6", True),
        ("5:7.0.15-1build2", True),
        ("14.2.0-4ubuntu2~24.04.1", True),
        ("16.10-1.pgdg24.04+1", True),
        ("6.8.0-85", True),
        ("dockerd 28.2.2", True),
        ("127.0.0.1:9999", False),
        ("0.39–4.36 s", False),
        ("2026-09-29", False),
        ("21:33, 266 MiB", False),
        ("PostgreSQL 16", False),
        ("a major docker.io bump", False),
    ],
)
def test_the_pattern_tells_a_version_from_a_date_or_a_count(text, is_version):
    assert bool(VERSION.search(text)) is is_version


def test_the_skill_files_a_vendored_hosts_entry_upstream() -> None:
    # Step 8b's hosts vendor the skill: an agent following SKILL.md alone must
    # not write its entry into the submodule copy (process-log.md, "Adding an
    # entry").
    skill = (LOG.parent / "SKILL.md").read_text()
    prefix = "7. **Record**"
    step = next((line for line in skill.splitlines() if line.startswith(prefix)), "")
    assert step, f"SKILL.md has no step starting {prefix!r}: move this test with it"
    assert "process-log.md" in step
    assert "vendored" in step and "upstream" in step
