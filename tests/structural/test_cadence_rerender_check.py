"""`install-cadence.sh --check` says when a re-render would change the workflow (#647).

A template change alone, such as the checkout pin moving from `@v5` to `@v7`,
used to read `behind` on the pin line and exit 0. Any other template change
read nothing at all. Measured on a cohort host (2026-11-14): the workflow was
rendered on 2026-09-25 and stayed that way through many submodule bumps.

`--check` now ends the workflow's lines with one `re-render:` line. It renders
the workflow the way `--print` does, keeping the installed schedule and
ledger, and compares that with the installed file. `none` means a re-render
writes the file back unchanged, and `behind` means it would change lines.
The line never sets the exit code, because consumers' CI may call `--check`.
The refresh hook (`skills-submodule-update.sh`) and `shipping-work`'s
`doc-check.sh` read the `behind` form.

A Dependabot-moved pin (a SHA pin, or `@vN` at or above the template's) is
kept by a re-render (#373), so it is not drift. Neither is a custom schedule.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from tests.utils.skill_loader import SKILLS_DIR

INSTALL_CADENCE = SKILLS_DIR / "curating-context" / "scripts" / "install-cadence.sh"
WF = Path(".github/workflows/context-cadence.yml")
CHECKOUT = re.compile(r"^ *- uses: actions/checkout@.*$", re.M)
SHA_LINE = "      - uses: actions/checkout@" + "3d3c42e5" * 5 + " # v99.0.1"
# The form the hook and doc-check.sh match. Kept here as a literal so a
# rewording of the line fails this file, not a consumer's hook in silence.
BEHIND = re.compile(r"^re-render: +behind\b", re.M)
NONE = re.compile(r"^re-render: +none\b", re.M)


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALL_CADENCE), *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_env(),
        timeout=60,
    )


def _installed(tmp_path: Path, *args: str) -> Path:
    repo = tmp_path / "r"
    repo.mkdir(parents=True)
    r = subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo)],
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert r.returncode == 0, r.stderr
    r = _run(repo, *args)
    assert r.returncode == 0, r.stdout + r.stderr
    return repo


def _move_pin(repo: Path, line: str) -> None:
    wf = repo / WF
    text, n = CHECKOUT.subn(line, wf.read_text(), count=1)
    assert n == 1, "the rendered workflow has no checkout line to move"
    wf.write_text(text)


def test_a_current_install_reads_none(tmp_path):
    repo = _installed(tmp_path)
    r = _run(repo, "--check")
    assert r.returncode == 0, r.stdout + r.stderr
    assert NONE.search(r.stdout), r.stdout
    assert not BEHIND.search(r.stdout), r.stdout


def test_a_template_only_change_is_behind_and_the_exit_is_unchanged(tmp_path):
    """The issue's template half: the installed workflow carries `@v5`, the
    template writes `@v7`, and nothing else differs. Before #647 this was
    exit 0 with only the pin line saying `behind`."""
    repo = _installed(tmp_path)
    _move_pin(repo, "      - uses: actions/checkout@v5")
    r = _run(repo, "--check")
    assert r.returncode == 0, r.stdout + r.stderr
    assert BEHIND.search(r.stdout), r.stdout
    assert "1 line" in r.stdout, r.stdout


def test_any_other_template_line_is_behind_too(tmp_path):
    """Not only the pin: a step the template has changed since the render."""
    repo = _installed(tmp_path)
    wf = repo / WF
    wf.write_text(wf.read_text() + "# a line an older template wrote\n")
    r = _run(repo, "--check")
    assert r.returncode == 0, r.stdout + r.stderr
    assert BEHIND.search(r.stdout), r.stdout


def test_a_custom_schedule_is_not_drift(tmp_path):
    repo = _installed(tmp_path, "--cron", "1 2 * * 3")
    r = _run(repo, "--check")
    assert r.returncode == 0, r.stdout + r.stderr
    assert NONE.search(r.stdout), r.stdout


def test_a_custom_ledger_is_not_drift(tmp_path):
    repo = _installed(tmp_path, "--ledger", "metrics/ctx.jsonl")
    r = _run(repo, "--check")
    assert NONE.search(r.stdout), r.stdout


def test_a_dependabot_pin_is_not_drift(tmp_path):
    """A SHA pin is kept verbatim by a re-render (#373), so it isn't drift."""
    repo = _installed(tmp_path)
    _move_pin(repo, SHA_LINE)
    r = _run(repo, "--check")
    assert r.returncode == 0, r.stdout + r.stderr
    assert NONE.search(r.stdout), r.stdout


def test_a_pr_knob_under_a_direct_render_is_behind_and_still_exit_3(tmp_path):
    """The issue's knob half: the knob says pr and the workflow was rendered
    direct. STALE is exit 3, as before; the re-render line agrees."""
    repo = _installed(tmp_path)
    (repo / ".skills").mkdir(exist_ok=True)
    (repo / ".skills" / "merge_mode").write_text("pr\n")
    r = _run(repo, "--check")
    assert r.returncode == 3, r.stdout + r.stderr
    assert "STALE" in r.stdout, r.stdout
    assert BEHIND.search(r.stdout), r.stdout


def test_an_unusable_knob_says_the_re_render_is_unknown(tmp_path):
    """No re-render can run (exit 5), so the line says why rather than none."""
    repo = _installed(tmp_path)
    (repo / ".skills").mkdir(exist_ok=True)
    (repo / ".skills" / "merge_mode").write_text("maybe\n")
    r = _run(repo, "--check")
    assert r.returncode == 3, r.stdout + r.stderr
    assert re.search(r"^re-render: +unknown\b", r.stdout, re.M), r.stdout
    assert not NONE.search(r.stdout) and not BEHIND.search(r.stdout), r.stdout


def test_no_workflow_prints_no_re_render_line(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], env=_env())
    r = _run(repo, "--check")
    assert r.returncode == 3
    assert "re-render:" not in r.stdout, r.stdout


def test_check_writes_nothing(tmp_path):
    """--check stays read-only: the re-render goes to a pipe, never the file."""
    repo = _installed(tmp_path)
    _move_pin(repo, "      - uses: actions/checkout@v5")
    before = (repo / WF).read_text()
    _run(repo, "--check")
    assert (repo / WF).read_text() == before


def test_the_help_names_the_line():
    r = subprocess.run(
        ["bash", str(INSTALL_CADENCE), "--help"],
        capture_output=True,
        text=True,
        env=_env(),
        timeout=30,
    )
    assert r.returncode == 0
    text = " ".join(r.stdout.split())
    assert "A tenth, re-render," in text, r.stdout
    assert "`none`, or `behind`" in text, r.stdout
