"""Shared fixtures for the doc-check.sh behavioral tests.

Two files exercise the four `shipping-work*` copies of doc-check.sh against a
throwaway git repo: test_doc_check_segment_match.py (#252 — the matcher, the
dead-entry probe, the path-list override) and test_doc_check_doc_sections.py
(#261 — the advice override). They build the same fixture, so the builder lives
here once: a change to how a repo is made, or to which variants exist, reaches
every doc-check test at the same time instead of drifting between two copies
of the same twenty lines.

Not a test module — pytest collects `test_*.py` only — and nothing here is
private to either caller.
"""

import os
import subprocess
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

VARIANTS = [
    "shipping-work",
    "shipping-work-php",
    "shipping-work-python-click",
    "shipping-work-python-fastapi",
]

# A tree where every click default is live, so the dead-entry probe stays quiet
# and each test's assertion is about the thing it names.
CLICK_LIVE_TREE = [
    "AGENTS.md",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "src/co/__init__.py",
    ".env.example",
    "docs/notes.md",
]


def script_path(variant: str) -> Path:
    return SKILLS_DIR / variant / "scripts" / "doc-check.sh"


def clean_env() -> dict:
    """Env without inherited GIT_* vars.

    Pre-commit and other tooling set GIT_INDEX_FILE / GIT_DIR / GIT_WORK_TREE,
    which would otherwise leak into the throwaway repo and point git at the
    parent checkout.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=clean_env(),
    )


def write_file(repo: Path, rel: str, body: str = "x\n") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


# Every run is bounded. These invocations finish in well under a second, so the
# only way to reach this ceiling is a script that blocked — which doc-check.sh
# can be made to do by handing it a FIFO, if a refactor ever moves the open
# ahead of the not-a-regular-file classification. A hang has no exit code and
# no message; TimeoutExpired turns it into a loud failure that names the test
# instead of wedging the suite.
RUN_TIMEOUT_S = 60

# For a test that provokes a KNOWN hang, where the ceiling above is only
# costing wall-clock on the way to a failure that is already certain.
HANG_TIMEOUT_S = 15


def run_doc_check(
    repo: Path,
    variant: str = "shipping-work-python-click",
    *args: str,
    timeout: float = RUN_TIMEOUT_S,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script_path(variant)), *args],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=clean_env(),
        timeout=timeout,
    )


def make_repo(tmp_path: Path, base_files: list[str], branch_files: list[str]) -> Path:
    """A repo with `base_files` committed on main and `branch_files` added on a
    feature branch. doc-check.sh auto-detects `main` as the base ref when no
    remote exists.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "test")
    for rel in base_files:
        write_file(repo, rel)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "initial")

    run_git(repo, "checkout", "-b", "feature")
    for rel in branch_files:
        write_file(repo, rel, "changed\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "work")
    return repo
