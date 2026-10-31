"""`detect-stack.sh` says what a repo has, so one gate serves every repo (#537).

Two kinds of answer, kept apart (plan Step 5, rows 1 and 1b):

- `toolchain` decides which CHECKS run: `uv` (a pyproject.toml with a uv.lock
  or a [tool.uv] table), `composer` (a composer.json at the root, or one level
  under themes/ or plugins/), `npm` (a package.json).
- `framework` decides only which DOCS apply — doc-check's default watch list
  and which references/stack-*.md loads: `fastapi` when fastapi is a declared
  dependency, `click` when click or typer is and fastapi is not, `php` for any
  composer toolchain.

Output is one `kind<TAB>name` line per finding; nothing found is exit 0 with
no output. No API calls; each test gets a fresh repo.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "skills" / "shipping-work" / "scripts" / "detect-stack.sh"


def _clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=_clean_env())
    return repo


def _detect(repo: Path) -> set[tuple[str, str]]:
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    assert result.returncode == 0, result.stderr
    return {tuple(line.split("\t")) for line in result.stdout.splitlines()}


def _pyproject(repo: Path, deps: str = "", tool_uv: bool = False) -> None:
    text = f'[project]\nname = "demo-app"\ndependencies = [{deps}]\n'
    if tool_uv:
        text += "\n[tool.uv]\ndev-dependencies = []\n"
    (repo / "pyproject.toml").write_text(text)


class TestToolchains:
    def test_nothing(self, repo):
        assert _detect(repo) == set()

    def test_a_uv_lock_makes_pyproject_a_uv_repo(self, repo):
        _pyproject(repo)
        (repo / "uv.lock").write_text("version = 1\n")
        assert ("toolchain", "uv") in _detect(repo)

    def test_a_tool_uv_table_does_too(self, repo):
        _pyproject(repo, tool_uv=True)
        assert ("toolchain", "uv") in _detect(repo)

    def test_a_pyproject_uv_does_not_manage_is_not_one(self, repo):
        """A Poetry or pip project gets the remedy, not uv run against it."""
        _pyproject(repo)
        assert _detect(repo) == set()

    def test_composer_at_the_root(self, repo):
        (repo / "composer.json").write_text("{}\n")
        assert ("toolchain", "composer") in _detect(repo)

    @pytest.mark.parametrize("parent", ["themes", "plugins"])
    def test_composer_one_level_under_themes_or_plugins(self, repo, parent):
        (repo / parent / "site").mkdir(parents=True)
        (repo / parent / "site" / "composer.json").write_text("{}\n")
        assert ("toolchain", "composer") in _detect(repo)

    def test_npm(self, repo):
        (repo / "package.json").write_text("{}\n")
        assert _detect(repo) == {("toolchain", "npm")}

    def test_every_stack_a_repo_has(self, repo):
        (repo / "composer.json").write_text("{}\n")
        (repo / "package.json").write_text("{}\n")
        found = _detect(repo)
        assert ("toolchain", "composer") in found
        assert ("toolchain", "npm") in found


class TestFrameworks:
    @pytest.mark.parametrize(
        "dep", ['"fastapi>=0.110"', '"fastapi[standard]"', '"FastAPI==0.1"']
    )
    def test_fastapi(self, repo, dep):
        _pyproject(repo, dep, tool_uv=True)
        assert ("framework", "fastapi") in _detect(repo)

    @pytest.mark.parametrize("dep", ['"click>=8"', '"typer"'])
    def test_click(self, repo, dep):
        _pyproject(repo, dep, tool_uv=True)
        found = _detect(repo)
        assert ("framework", "click") in found
        assert ("framework", "fastapi") not in found

    def test_fastapi_wins_over_click(self, repo):
        """A service that pulls in click for a management command is a service."""
        _pyproject(repo, '"fastapi", "click"', tool_uv=True)
        found = _detect(repo)
        assert ("framework", "fastapi") in found
        assert ("framework", "click") not in found

    def test_a_name_that_only_starts_with_one_is_not_it(self, repo):
        _pyproject(repo, '"clickhouse-driver", "fastapi-utils-x"', tool_uv=True)
        found = _detect(repo)
        assert ("framework", "click") not in found
        assert ("framework", "fastapi") not in found

    def test_php_comes_with_composer(self, repo):
        (repo / "composer.json").write_text("{}\n")
        assert ("framework", "php") in _detect(repo)

    def test_a_plain_uv_repo_has_no_framework(self, repo):
        _pyproject(repo, '"httpx"', tool_uv=True)
        assert _detect(repo) == {("toolchain", "uv")}


def test_outside_a_repository_is_exit_2(tmp_path):
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    assert result.returncode == 2


def test_help(tmp_path):
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "toolchain" in result.stdout and "framework" in result.stdout
