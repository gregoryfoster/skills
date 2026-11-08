"""Two copies of one composer reach answer the same (#588, CR 2003).

`shipping-work`'s gate (`detect-stack.sh`'s `nested`, `pre-ship.sh`'s
`nested_dirs`) and `reviewing-code-php`'s `gather-context.sh` each find the
`composer.json` files one level under `themes/` and `plugins/` and run
`composer validate` on each. Skills are self-contained, so the PHP review
keeps its own copy of the lister; this file holds the two to the same
answers. The rule (the operator's, 2026-11-08): a repo gates only its own
code. A nested composer.json counts only when git tracks it, never through
a submodule or a dot-directory, and no inherited GIT_*_PATHSPECS setting
widens or empties the listing. The root composer.json stays a filesystem
check.

Each case starts from a root composer.json and a tracked theme, adds one
edge, and wants both scripts to validate exactly the root and the theme.
Every git call scrubs the inherited GIT_* variables and names its repo
explicitly (#189). The tools are gate_fakes' fakes, so nothing real runs.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.structural.gate_fakes import ALL_TOOLS, fake_env
from tests.utils.skill_loader import SKILLS_DIR

GATE = SKILLS_DIR / "shipping-work" / "scripts" / "pre-ship.sh"
REVIEW = SKILLS_DIR / "reviewing-code-php" / "scripts" / "gather-context.sh"
WANT = [".", "themes/site"]


def _env() -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env=_env(),
    )


def _init(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")


def _commit(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "state")


def _manifest(repo: Path, rel: str) -> None:
    (repo / rel).mkdir(parents=True, exist_ok=True)
    (repo / rel / "composer.json").write_text("{}\n")


def _gitignored(repo: Path, tmp_path: Path) -> dict:
    (repo / ".gitignore").write_text("/plugins/vendor-plugin/\n")
    _commit(repo)
    _manifest(repo, "plugins/vendor-plugin")
    return {}


def _untracked(repo: Path, tmp_path: Path) -> dict:
    _manifest(repo, "themes/new")
    return {}


def _dot_directory(repo: Path, tmp_path: Path) -> dict:
    _manifest(repo, "themes/.old")
    _commit(repo)
    return {}


def _submodule(repo: Path, tmp_path: Path) -> dict:
    src = tmp_path / "theme-src"
    _init(src)
    (src / "composer.json").write_text("{}\n")
    _commit(src)
    _git(
        repo,
        *("-c", "protocol.file.allow=always", "submodule", "add", "-q"),
        *(str(src), "themes/sub"),
    )
    _commit(repo)
    assert (repo / "themes" / "sub" / "composer.json").is_file()
    return {}


def _icase(repo: Path, tmp_path: Path) -> dict:
    """Plugins/, not Themes/: on a case-insensitive volume Themes/ would be
    the fixture's own themes/."""
    _manifest(repo, "Plugins/Up")
    _commit(repo)
    return {"GIT_ICASE_PATHSPECS": "1"}


def _literal(repo: Path, tmp_path: Path) -> dict:
    """Under the literal setting `:(glob)` was a literal path, which listed
    nothing: the tracked theme must still be found."""
    return {"GIT_LITERAL_PATHSPECS": "1"}


CASES: dict[str, Callable[[Path, Path], dict]] = {
    "gitignored": _gitignored,
    "untracked": _untracked,
    "dot-directory": _dot_directory,
    "submodule": _submodule,
    "icase-pathspecs": _icase,
    "literal-pathspecs": _literal,
}


@pytest.fixture(params=sorted(CASES))
def case(request, tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "composer.json").write_text("{}\n")
    (repo / "index.php").write_text("<?php\n")
    _manifest(repo, "themes/site")
    _commit(repo)
    extra = CASES[request.param](repo, tmp_path)
    return repo, extra


def _composer_validations(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return [c for c in calls if c[0] == "composer" and "validate" in c]


def _gate_validates(repo: Path, extra: dict) -> list[str]:
    log = repo.parent / "gate-tools.log"
    env = fake_env(repo.parent / "fakebin", log, ALL_TOOLS, GATE_STAMP="off")
    env.update(extra)
    result = subprocess.run(
        ["bash", str(GATE)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return sorted(
        c[1].removeprefix("--working-dir=") for c in _composer_validations(log)
    )


def _review_validates(repo: Path, extra: dict) -> list[str]:
    log = repo.parent / "review-tools.log"
    cwd_log = repo.parent / "review-cwd.log"
    home = repo.parent / "home"
    home.mkdir(exist_ok=True)
    env = fake_env(
        repo.parent / "fakebin",
        log,
        ALL_TOOLS,
        HOME=str(home),
        TOOL_CWD_LOG=str(cwd_log),
    )
    env.update(extra)
    result = subprocess.run(
        ["bash", str(REVIEW)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    dirs = []
    for line in cwd_log.read_text().splitlines():
        cwd, tool, *argv = json.loads(line)
        if tool == "composer" and "validate" in argv:
            rel = os.path.relpath(os.path.realpath(cwd), os.path.realpath(repo))
            dirs.append(rel)
    return sorted(dirs)


def test_the_gate_and_the_php_review_validate_the_same_composer_dirs(case):
    repo, extra = case
    gate = _gate_validates(repo, extra)
    review = _review_validates(repo, extra)
    assert gate == WANT, gate
    assert review == WANT, review


def test_the_review_names_its_twin():
    """The copy says where its twin lives, so a fix to one reaches both."""
    text = REVIEW.read_text()
    assert "detect-stack.sh" in text and "test_composer_reach_parity.py" in text
