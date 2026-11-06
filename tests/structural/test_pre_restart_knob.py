"""`.skills/pre_restart`: the project's check before Step 8's restart rows (#557).

Without `.skills/deploy_command` the main checkout is the deployment, and
Step 8's migrate and restart rows ran with nothing checked first.
CannObserv/power-map#748 restarted a unit whose `ExecStartPre` applies the
schema while its DB was unreachable: each attempt hung 60 s on a connect with
no timeout, so `StartLimitBurst` never tripped, and the unit looped in
start-pre for about 16 h before applying the pending schema unwatched.

The knob names a check, in `deploy_command`'s grammar and through the same
reader (`_command-knob.sh`). `run-pre-restart.sh` runs it; a non-zero exit
means Step 8 offers no restart row. The issue's own case is the first test
below: a check that refuses is exit 1, with its code and output verbatim.

Every test uses a stub that records its arguments and cwd. No real restart
runs: that is the issue's verification debt. Each test gets a fresh repo.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.utils.skill_loader import SKILLS_DIR

SKILL = SKILLS_DIR / "shipping-work"
SCRIPT = SKILL / "scripts" / "run-pre-restart.sh"

# Records each argument, the cwd and whether stdin is empty, then exits with
# $STUB_EXIT, printing a line to each stream on the way. The stderr line is
# power-map's own refusal, in shape.
STUB = """\
#!/usr/bin/env bash
out="${STUB_RECORD:?}"
: >"$out"
for a in "$@"; do printf 'arg=%s\\n' "$a" >>"$out"; done
printf 'cwd=%s\\n' "$(pwd -P)" >>"$out"
printf 'stdin=%s\\n' "$(cat)" >>"$out"
echo "stub stdout: probing the DSN ExecStartPre uses"
echo "stub stderr: DB unreachable within 5 s; refusing the restart" >&2
exit "${STUB_EXIT:-0}"
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
    """A primary checkout on main with the stub check, never pushed: the
    check is about the host, so nothing about HEAD is asked."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    stub = repo / "scripts" / "pre-restart-check.sh"
    stub.parent.mkdir()
    stub.write_text(STUB)
    stub.chmod(0o755)
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "initial")
    return repo


def _knob(repo: Path, text: str) -> None:
    (repo / ".skills").mkdir(exist_ok=True)
    (repo / ".skills" / "pre_restart").write_text(text)


def _run(
    cwd: Path, *args: str, record: Path, **env: str
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=_env(STUB_RECORD=str(record), **env),
        timeout=60,
    )


def _recorded(record: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in record.read_text().splitlines():
        key, _, value = line.partition("=")
        out.setdefault(key, []).append(value)
    return out


class TestARefusingCheckOffersNoRestart:
    """The issue's own case: the check exits non-zero, so no restart row."""

    @pytest.mark.parametrize("code", ["1", "3"])
    def test_a_non_zero_check_is_exit_1_with_its_code_and_output_verbatim(
        self, repo, tmp_path, code
    ):
        _knob(repo, "scripts/pre-restart-check.sh\n")
        result = _run(repo, record=tmp_path / "record", STUB_EXIT=code)
        assert result.returncode == 1, result.stdout + result.stderr
        assert re.search(rf"\bexited {code}\b", result.stdout), result.stdout
        assert "stub stdout: probing the DSN" in result.stdout
        assert "DB unreachable within 5 s; refusing the restart" in result.stderr
        assert re.search(r"no restart row", result.stderr), result.stderr


class TestTheCheckRuns:
    def test_a_passing_check_is_exit_0(self, repo, tmp_path):
        _knob(repo, "scripts/pre-restart-check.sh\n")
        result = _run(repo, record=tmp_path / "record")
        assert result.returncode == 0, result.stdout + result.stderr

    def test_nothing_is_appended_and_the_knobs_words_pass_through(self, repo, tmp_path):
        """Unlike deploy_command, no SHA: power-map's check takes `--force`."""
        _knob(repo, "# probes the DSN\nscripts/pre-restart-check.sh --timeout 5\n")
        record = tmp_path / "record"
        assert _run(repo, record=record).returncode == 0
        assert _recorded(record)["arg"] == ["--timeout", "5"]

    def test_stdin_is_dev_null(self, repo, tmp_path):
        _knob(repo, "scripts/pre-restart-check.sh\n")
        record = tmp_path / "record"
        subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=repo,
            input="a prompt answer that must never arrive\n",
            capture_output=True,
            text=True,
            env=_env(STUB_RECORD=str(record)),
            timeout=60,
        )
        assert _recorded(record)["stdin"] == [""]

    def test_from_a_worktree_the_primary_checkouts_knob_is_read_and_run_there(
        self, repo, tmp_path
    ):
        _knob(repo, "scripts/pre-restart-check.sh\n")  # untracked: not in the worktree
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feature", str(wt))
        record = tmp_path / "record"
        result = _run(wt, record=record)
        assert result.returncode == 0, result.stdout + result.stderr
        assert _recorded(record)["cwd"] == [str(repo.resolve())]


class TestAbsentMeansTodaysTable:
    def test_no_knob_is_exit_3_and_runs_nothing(self, repo, tmp_path):
        record = tmp_path / "record"
        result = _run(repo, record=record)
        assert result.returncode == 3, result.stdout + result.stderr
        assert not record.exists()
        assert "pre_restart" in result.stdout


class TestAnUnusableKnobIsNeverAbsent:
    @pytest.mark.parametrize(
        "text",
        [
            "",
            "# only a comment\n\n",
            "scripts/pre-restart-check.sh\nscripts/other.sh\n",
            "scripts/missing.sh\n",
            "pre-restart-check.sh\n",
        ],
        ids=["empty", "comment-only", "two-commands", "missing-path", "bare-word"],
    )
    def test_it_is_exit_2_and_runs_nothing(self, repo, tmp_path, text):
        _knob(repo, text)
        record = tmp_path / "record"
        result = _run(repo, record=record)
        assert result.returncode == 2, result.stdout + result.stderr
        assert not record.exists()

    def test_a_knob_that_is_a_directory_is_exit_2(self, repo, tmp_path):
        (repo / ".skills" / "pre_restart").mkdir(parents=True)
        assert _run(repo, record=tmp_path / "record").returncode == 2


class TestCheckRunsNothing:
    def test_check_prints_the_command_line_and_runs_nothing(self, repo, tmp_path):
        _knob(repo, "scripts/pre-restart-check.sh --timeout 5\n")
        record = tmp_path / "record"
        result = _run(repo, "--check", record=record)
        assert result.returncode == 0, result.stdout + result.stderr
        assert not record.exists()
        assert result.stdout.strip() == "scripts/pre-restart-check.sh --timeout 5"

    def test_check_with_no_knob_is_exit_3(self, repo, tmp_path):
        assert _run(repo, "--check", record=tmp_path / "r").returncode == 3


def test_help_documents_the_exit_codes():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"], capture_output=True, text=True, env=_env()
    )
    assert result.returncode == 0
    for code in ("0", "1", "2", "3"):
        assert re.search(rf"^\s+{code}\s", result.stdout, re.M), result.stdout


def test_an_unknown_argument_is_exit_2(repo, tmp_path):
    assert _run(repo, "--bogus", record=tmp_path / "r").returncode == 2


# --- one grammar: deploy_command's reader serves both knobs --------------------------


def test_both_command_knobs_read_through_the_one_parser():
    """The brief: reuse deploy_command's parser, don't fork a second grammar."""
    for name in ("run-deploy-command.sh", "run-pre-restart.sh"):
        text = (SKILL / "scripts" / name).read_text()
        assert '. "$SCRIPT_DIR/_command-knob.sh"' in text, name
        assert "read_command_knob " in text, name
        assert "read -r -a words" not in text, f"{name} parses the knob itself"


# --- the prose: Step 8 conditions its restart rows on the check ---------------------


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n### ", start + len(heading))
    return text[start : end if end != -1 else len(text)]


SKILL_MD = (SKILL / "SKILL.md").read_text()


def test_step_8_runs_the_check_before_offering_a_restart_row():
    step8 = _section(SKILL_MD, "### Step 8")
    assert '"<run-pre-restart.sh>"' in step8, step8
    para = next(p for p in step8.split("\n\n") if "<run-pre-restart.sh>" in p)
    assert re.search(r"restart", para) and re.search(r"offer no|offer none", para)
    assert "verbatim" in para and "Done when" in para, para


def test_step_6_waits_for_step_8_when_the_check_is_set():
    """The issue's "close no issue" can't hold if Step 6 closed it first."""
    step6 = _section(SKILL_MD, "### Step 6")
    first = step6.split("\n\n")[1]
    assert ".skills/pre_restart" in first and "Step 8 first" in first, first


def test_the_fastapi_restart_rows_point_at_the_check():
    text = (SKILL / "references" / "stack-fastapi.md").read_text()
    assert "<run-pre-restart.sh>" in text


@pytest.mark.parametrize(
    "path", ["SKILL.md", "references/stack-fastapi.md"], ids=["skill", "fastapi"]
)
def test_the_env_var_row_names_no_invented_path(path):
    """The issue's stray finding: consumers use /etc/<project>/.env, not /env."""
    text = (SKILL / path).read_text()
    assert "/etc/<project>/env" not in text
    assert "the project's env file" in text


def test_the_deploy_reference_says_the_deploy_command_owns_its_check():
    text = (SKILL / "references" / "deploy-command.md").read_text()
    assert ".skills/pre_restart" in text


def test_the_post_merge_pass_runs_the_check():
    text = (SKILL / "references" / "pr-mode.md").read_text()
    post = text[text.index("## The post-merge pass") :]
    assert ".skills/pre_restart" in post
