"""`.skills/next-steps`: a project's own Step 8 table (#564).

Step 8's rows came only from the detected framework's stack file, so a
project whose post-merge work differs (a Bedrock site that deploys by workflow
dispatch, where `yarn bud build` and `wp acf import` are the wrong rows) had no
file the skill reads to say so. `pr` mode widened the gap: the post-merge pass
often runs in a later session than the PR pass.

The knob has `.skills/doc-sections`' shape and grammar: one row per line,
`#`-comment and blank lines dropped, whitespace trimmed. `read-next-steps.sh`
reads it through doc-check.sh's own `read_list_file`, held byte-equal below.
Its rows replace the stack file's table, and present but unusable is exit 2,
never a silent fallback to the stack file's rows.

The issue's own case is the first class: a project's file replaces the stack
table, and Step 8 says which source it used. No API calls.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.utils.skill_loader import SKILLS_DIR

SKILL = SKILLS_DIR / "shipping-work"
SCRIPT = SKILL / "scripts" / "read-next-steps.sh"

BEDROCK_ROWS = """\
# Deploys by workflow dispatch: no yarn bud build, no wp acf import here.
Deploy: any merge to main -> gh workflow run deploy.yml, then watch it

ETL: etl/ changed -> run scripts/etl-backfill.sh   # a trailing note is content
"""


def _env(**extra: str) -> dict:
    """No inherited GIT_*: under a hook GIT_DIR would point the fixture at this repo (#189)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(extra)
    return env


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(),
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "composer.json").write_text("{}\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "initial")
    return repo


def _knob(repo: Path, text: str) -> Path:
    (repo / ".skills").mkdir(exist_ok=True)
    path = repo / ".skills" / "next-steps"
    path.write_text(text)
    return path


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=_env(),
        timeout=60,
    )


class TestTheProjectsRowsReplaceTheStackTable:
    """The issue's own case: a Bedrock site's own rows, not stack-php.md's."""

    def test_its_rows_are_printed_one_per_line_and_the_source_named(self, repo):
        _knob(repo, BEDROCK_ROWS)
        result = _run(repo)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.splitlines() == [
            "Deploy: any merge to main -> gh workflow run deploy.yml, then watch it",
            "ETL: etl/ changed -> run scripts/etl-backfill.sh   # a trailing note is content",
        ]
        assert ".skills/next-steps" in result.stderr
        assert "yarn bud build" not in result.stdout

    def test_a_last_row_without_a_newline_is_kept(self, repo):
        _knob(repo, "Deploy: gh workflow run deploy.yml")
        result = _run(repo)
        assert result.stdout.splitlines() == ["Deploy: gh workflow run deploy.yml"]

    def test_from_a_worktree_the_primary_checkouts_file_is_read(self, repo, tmp_path):
        _knob(repo, BEDROCK_ROWS)  # untracked: the worktree has no copy
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feature", str(wt))
        result = _run(wt)
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(result.stdout.splitlines()) == 2


class TestAbsentMeansTheStackFile:
    def test_no_file_is_exit_3_and_prints_no_rows(self, repo):
        result = _run(repo)
        assert result.returncode == 3, result.stdout + result.stderr
        assert "stack file" in result.stdout


class TestPresentButUnusableIsExit2:
    """Never a silent fallback to the stack file's rows."""

    @pytest.mark.parametrize(
        "text", ["", "\n   \n", "# only comments\n  # indented too\n"]
    )
    def test_no_row_after_comments_is_exit_2(self, repo, text):
        _knob(repo, text)
        result = _run(repo)
        assert result.returncode == 2, result.stdout + result.stderr
        assert result.stdout == ""

    def test_a_directory_is_exit_2(self, repo):
        (repo / ".skills" / "next-steps").mkdir(parents=True)
        assert _run(repo).returncode == 2

    def test_a_dangling_symlink_is_exit_2(self, repo):
        (repo / ".skills").mkdir()
        (repo / ".skills" / "next-steps").symlink_to(repo / "nowhere")
        assert _run(repo).returncode == 2

    @pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 file")
    def test_an_unreadable_file_is_exit_2(self, repo):
        path = _knob(repo, BEDROCK_ROWS)
        path.chmod(0)
        try:
            assert _run(repo).returncode == 2
        finally:
            path.chmod(0o644)

    def test_a_skills_that_is_a_file_is_exit_2(self, repo):
        (repo / ".skills").write_text("not a directory\n")
        assert _run(repo).returncode == 2

    def test_a_dangling_skills_symlink_is_exit_2(self, repo):
        (repo / ".skills").symlink_to(repo / "nowhere")
        assert _run(repo).returncode == 2

    @pytest.mark.skipif(os.geteuid() == 0, reason="root searches a mode-000 dir")
    def test_an_unsearchable_skills_is_exit_2(self, repo):
        _knob(repo, BEDROCK_ROWS)
        (repo / ".skills").chmod(0o600)
        try:
            assert _run(repo).returncode == 2
        finally:
            (repo / ".skills").chmod(0o755)


def test_help_documents_the_exit_codes():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"], capture_output=True, text=True, env=_env()
    )
    assert result.returncode == 0
    for code in ("0", "2", "3"):
        assert re.search(rf"^\s+{code}\s", result.stdout, re.M), result.stdout


def test_an_unknown_argument_is_exit_2(repo):
    assert _run(repo, "--bogus").returncode == 2


# --- the same grammar as doc-sections, through the same reader ---------------------


def _function(text: str, name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.M | re.S)
    assert m, f"no {name}() in the script"
    return m.group(0)


@pytest.mark.parametrize("name", ["read_list_file", "override_present"])
def test_the_reader_is_doc_checks_own_byte_for_byte(name):
    """A guard fixed in doc-check.sh's reader must reach this one too (#261)."""
    ours = (SKILL / "scripts" / "read-next-steps.sh").read_text()
    theirs = (SKILL / "scripts" / "doc-check.sh").read_text()
    assert _function(ours, name) == _function(theirs, name)


# --- the prose: Step 8 reads it first and names its source --------------------------


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n### ", start + len(heading))
    return text[start : end if end != -1 else len(text)]


def test_the_deploy_path_lists_the_projects_rows_as_written():
    """CR 1856: "minus the DB migration and service restart rows" names the
    stack table's rows; a project's free-text rows can't be told apart, and
    they are its own, so they are listed as written."""
    step8 = _section((SKILL / "SKILL.md").read_text(), "### Step 8")
    item1 = next(line for line in step8.splitlines() if line.startswith("1. "))
    assert re.search(r"`\.skills/next-steps`\) are listed as written", item1), item1


def test_step_8_reads_the_projects_rows_first_and_names_the_source():
    step8 = _section((SKILL / "SKILL.md").read_text(), "### Step 8")
    para = next(p for p in step8.split("\n\n") if "<read-next-steps.sh>" in p)
    assert "replace" in para, para
    assert re.search(r"exit 2", para, re.I) and "never fall back" in para, para
    assert re.search(r"which source|names? (it|the source)", para), para


@pytest.mark.parametrize("stack", ["fastapi", "click", "php"])
def test_each_stack_table_yields_to_the_projects_rows(stack):
    text = (SKILL / "references" / f"stack-{stack}.md").read_text()
    step8 = text[text.index("## Step 8") :]
    assert ".skills/next-steps" in step8, stack
