"""The one doc-check.sh watches what each detected framework's docs describe (#537).

Plan Step 5 row 23. The four `doc-check.sh` copies differed only in their
default watch list and one advice line, so the baseline copy asks
`detect-stack.sh` for the repo's frameworks and uses each one's list — exactly
the paths its variant watches today — on top of `AGENTS.md` and `README.md`.
A repo with no framework keeps the generic list, and `.skills/doc-sensitive-
paths` still replaces whatever the defaults are.

Built on doc_check_fixtures; no API calls, a fresh repo per test.
"""

from pathlib import Path

import pytest

from tests.structural.doc_check_fixtures import run_doc_check, run_git, write_file

FASTAPI_PYPROJECT = '[project]\nname = "svc"\ndependencies = ["fastapi>=0.110"]\n'
CLICK_PYPROJECT = '[project]\nname = "cli"\ndependencies = ["click>=8"]\n'


def _repo(tmp_path: Path, pyproject: str | None, changed: list[str], extra=()):
    """main holds the docs and the stack files; `work` changes `changed`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-q", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "test")
    for rel in ("AGENTS.md", "README.md", *extra):
        write_file(repo, rel)
    if pyproject is not None:
        write_file(repo, "pyproject.toml", pyproject)
        write_file(repo, "uv.lock", "version = 1\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "initial")
    run_git(repo, "checkout", "-q", "-b", "work")
    for rel in changed:
        write_file(repo, rel, "changed\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "change")
    return repo


def _check(repo: Path):
    return run_doc_check(repo, "shipping-work", "--base", "main")


@pytest.mark.parametrize(
    ("pyproject", "changed", "inventory"),
    [
        (FASTAPI_PYPROJECT, "alembic/versions/0001_init.py", "route table"),
        (FASTAPI_PYPROJECT, "deploy/svc.service", "route table"),
        (CLICK_PYPROJECT, "src/cli/main.py", "command inventory"),
    ],
)
def test_a_frameworks_own_paths_are_watched(tmp_path, pyproject, changed, inventory):
    repo = _repo(tmp_path, pyproject, [changed])
    result = _check(repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert changed in result.stdout
    assert inventory in result.stdout


def test_php_paths_are_watched(tmp_path):
    repo = _repo(
        tmp_path,
        None,
        ["web/app/themes/site/functions.php"],
        extra=["composer.json"],
    )
    result = _check(repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "CPT/Skills tables" in result.stdout


def test_a_path_only_another_framework_watches_is_not_flagged(tmp_path):
    """A FastAPI service's `src/cli/` is not click's `src/`: no hit."""
    repo = _repo(tmp_path, FASTAPI_PYPROJECT, ["src/cli/tool.py"])
    result = _check(repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_no_framework_keeps_the_generic_list(tmp_path):
    repo = _repo(tmp_path, None, ["skills/x/SKILL.md"])
    result = _check(repo)
    assert result.returncode == 1, result.stdout + result.stderr


def test_the_knob_still_replaces_the_defaults(tmp_path):
    repo = _repo(tmp_path, FASTAPI_PYPROJECT, ["alembic/versions/0001_init.py"])
    write_file(repo, ".skills/doc-sensitive-paths", "README.md\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "knob")
    result = _check(repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_help_works_outside_a_repository(tmp_path):
    """CR 1393: detection runs before argument parsing, and must not cost
    `--help` the property every variant has — it needs no repo."""
    import subprocess

    from tests.structural.doc_check_fixtures import clean_env, script_path

    result = subprocess.run(
        ["bash", str(script_path("shipping-work")), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=clean_env(),
    )
    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stdout
