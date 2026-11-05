"""The tracer behind pre-commit's test selection records what a test touches (#537).

`tests/utils/gate_trace.py` is the evidence the selection map is built from,
so a kind of access it fails to see is a test the selector will skip when that
dependency changes. Each case here runs a synthetic test file through the
plugin in a child pytest and reads back what the trace recorded:

- an open, a directory listing, a `glob`, a symlink into the repo, and an
  existence check (`os.stat` raises no audit event, so it is wrapped);
- a script passed to a subprocess, and a subprocess started from inside the
  repo (recorded with its argv, a path outside the repo shown as `<outside>`);
- nothing from a tmp path, `.git` or the venv;
- one trace file per xdist worker.

No API calls. Each case is one child pytest run against this checkout.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _trace(tmp_path: Path, body: str, *extra: str) -> dict[str, dict]:
    case = tmp_path / "case"
    case.mkdir()
    (case / "pytest.ini").write_text("[pytest]\n")
    (case / "test_case.py").write_text(
        "import glob, os, subprocess, tempfile\n"
        "from pathlib import Path\n"
        f"REPO = Path({str(REPO)!r})\n\n" + textwrap.dedent(body)
    )
    prefix = tmp_path / "trace"
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GATE_TRACE"] = str(prefix)
    env["PYTHONPATH"] = str(REPO)
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "tests.utils.gate_trace",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
            "--rootdir",
            str(case),
            str(case / "test_case.py"),
            *extra,
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    records: dict[str, dict] = {}
    for path in sorted(tmp_path.glob("trace.*.jsonl")):
        for line in path.read_text().splitlines():
            rec = json.loads(line)
            merged = records.setdefault(rec.pop("file"), {})
            for kind, items in rec.items():
                merged.setdefault(kind, set()).update(items)
    return records


def _only(records: dict[str, dict]) -> dict:
    assert list(records) == ["test_case.py"], records
    return records["test_case.py"]


def test_an_open_is_recorded_repo_relative(tmp_path):
    rec = _only(
        _trace(
            tmp_path,
            """
        def test_it():
            (REPO / "retired-skills").read_text()
    """,
        )
    )
    assert "retired-skills" in rec["open"]


def test_a_path_through_claude_skills_resolves_to_skills(tmp_path):
    """.claude/skills is a symlink to skills/, and one dependency is one path."""
    rec = _only(
        _trace(
            tmp_path,
            """
        def test_it():
            (REPO / ".claude/skills/shipping-work/SKILL.md").read_text()
    """,
        )
    )
    assert "skills/shipping-work/SKILL.md" in rec["open"]


def test_an_existence_check_is_recorded(tmp_path):
    """A test that only asks whether a file exists depends on it too: adding
    or deleting that file can flip the test."""
    rec = _only(
        _trace(
            tmp_path,
            """
        def test_it():
            (REPO / "retired-skills").exists()
            os.path.isfile(REPO / "AGENTS.md")
            (REPO / "no-such-file").is_file()
    """,
        )
    )
    assert {"retired-skills", "AGENTS.md", "no-such-file"} <= rec["stat"]


def test_listings_and_globs_are_recorded(tmp_path):
    rec = _only(
        _trace(
            tmp_path,
            """
        def test_it():
            list((REPO / "skills").iterdir())
            list((REPO / "skills" / "shipping-work").glob("*.md"))
            glob.glob(str(REPO / "docs" / "*.md"))
    """,
        )
    )
    assert {"skills", "skills/shipping-work", "docs"} <= rec["list"]


def test_a_symlink_into_the_repo_records_its_target(tmp_path):
    rec = _only(
        _trace(
            tmp_path,
            """
        def test_it(tmp_path):
            os.symlink(REPO / "skills" / "managing-skills", tmp_path / "vendored")
    """,
        )
    )
    assert "skills/managing-skills" in rec["open"]


def test_a_script_passed_to_a_subprocess_is_recorded(tmp_path):
    rec = _only(
        _trace(
            tmp_path,
            """
        def test_it(tmp_path):
            subprocess.run(
                ["bash", str(REPO / "skills/shipping-work/scripts/merge-mode.sh"), "--help"],
                cwd=tmp_path, capture_output=True,
            )
    """,
        )
    )
    assert "skills/shipping-work/scripts/merge-mode.sh" in rec["exec"]
    assert "proc" not in rec, "run from a tmp dir, so not a proc from inside the repo"


def test_a_subprocess_from_inside_the_repo_keeps_its_argv(tmp_path):
    rec = _only(
        _trace(
            tmp_path,
            """
        def test_it(tmp_path):
            subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], capture_output=True)
            subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True)
    """,
        )
    )
    procs = {tuple(json.loads(p)) for p in rec["proc"]}
    assert (".", "git", "-C", "<outside>", "init", "-q") in procs
    assert (".", "git", "ls-files") in procs


def test_tmp_git_and_venv_paths_are_never_recorded(tmp_path):
    rec = _trace(
        tmp_path,
        """
        def test_it(tmp_path):
            (tmp_path / "x").write_text("x")
            (tmp_path / "x").read_text()
            git = REPO / ".git"  # a file in a linked worktree
            (git if git.is_file() else git / "HEAD").read_text()
            import pytest  # an import from the venv
    """,
    ).get("test_case.py", {})
    seen = set().union(*rec.values()) if rec else set()
    assert not {p for p in seen if p.startswith((".git", ".venv")) or "tmp" in p}, seen


@pytest.mark.skipif(
    subprocess.run([sys.executable, "-c", "import xdist"]).returncode != 0,
    reason="pytest-xdist is not installed",
)
def test_each_xdist_worker_writes_its_own_trace(tmp_path):
    body = "".join(
        f"""
        def test_{i}():
            (REPO / "retired-skills").read_text()
        """
        for i in range(4)
    )
    _trace(tmp_path, body, "-n", "2")
    names = sorted(p.name for p in tmp_path.glob("trace.*.jsonl"))
    assert {"trace.gw0.jsonl", "trace.gw1.jsonl"} <= set(names), names
