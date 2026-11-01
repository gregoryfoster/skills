"""`.skills/deploy_command`: ship through the project's deploy script (#345).

A project whose production runs immutable releases deploys through its own
script, and `shipping-work`'s Step 8 ("migrate, then systemctl restart")
is wrong there both ways: the restart restarts the *old* release, and a hand
migration runs outside the deploy's order. The knob names the command;
`run-deploy-command.sh` runs it once, after the push, with the pushed SHA as
its last argument (operator's decision, 2026-10-30), from the primary
checkout's root.

Every test here uses a stub command that records its arguments, its working
directory and its exit code. No real deploy runs: that is the epic's
verification debt. No API calls; each test gets a fresh repo.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.utils.skill_loader import SKILLS_DIR

SKILL = SKILLS_DIR / "shipping-work"
SCRIPT = SKILL / "scripts" / "run-deploy-command.sh"

# Records each argument on its own line, then the cwd, then exits with
# $STUB_EXIT (default 0), printing a line to each stream on the way.
STUB = """\
#!/usr/bin/env bash
out="${STUB_RECORD:?}"
: >"$out"
for a in "$@"; do printf 'arg=%s\\n' "$a" >>"$out"; done
printf 'cwd=%s\\n' "$(pwd -P)" >>"$out"
printf 'foo=%s\\n' "${FOO:-}" >>"$out"
echo "stub stdout: deploying"
echo "stub stderr: target left on a build that doesn't answer" >&2
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


def _commit(repo: Path, message: str) -> None:
    # No signing: the fixture's commits never leave the tmp dir (#546).
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A primary checkout on main, pushed to a bare origin, with the stub."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    stub = repo / "scripts" / "deploy.sh"
    stub.parent.mkdir()
    stub.write_text(STUB)
    stub.chmod(0o755)
    _git(repo, "add", "-A")
    _commit(repo, "initial")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo


def _knob(repo: Path, text: str) -> None:
    (repo / ".skills").mkdir(exist_ok=True)
    (repo / ".skills" / "deploy_command").write_text(text)


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


class TestTheCommandRuns:
    def test_the_pushed_sha_is_the_last_argument(self, repo, tmp_path):
        _knob(repo, "scripts/deploy.sh\n")
        record = tmp_path / "record"
        result = _run(repo, record=record)
        assert result.returncode == 0, result.stdout + result.stderr
        assert _recorded(record)["arg"] == [_git(repo, "rev-parse", "HEAD")]

    def test_the_knobs_own_words_come_first(self, repo, tmp_path):
        """`env FOO=1 cmd --flag` stands in for `setsid -w scripts/deploy.sh`."""
        _knob(
            repo,
            "# deploys through the release layout\nenv FOO=1 scripts/deploy.sh --no-restart\n",
        )
        record = tmp_path / "record"
        result = _run(repo, record=record)
        assert result.returncode == 0, result.stdout + result.stderr
        seen = _recorded(record)
        assert seen["arg"] == ["--no-restart", _git(repo, "rev-parse", "HEAD")]
        assert seen["foo"] == ["1"]

    def test_it_runs_from_the_primary_checkouts_root(self, repo, tmp_path):
        _knob(repo, "scripts/deploy.sh\n")
        (repo / "sub").mkdir()
        record = tmp_path / "record"
        assert _run(repo / "sub", record=record).returncode == 0
        assert _recorded(record)["cwd"] == [str(repo.resolve())]

    def test_from_a_worktree_the_primary_checkouts_knob_is_read(self, repo, tmp_path):
        """The knob is read like `worktree_root`: from the primary checkout."""
        _knob(repo, "scripts/deploy.sh\n")  # untracked: the worktree has no copy
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feature", str(wt))
        _git(wt, "push", "-q", "-u", "origin", "feature")
        record = tmp_path / "record"
        result = _run(wt, record=record)
        assert result.returncode == 0, result.stdout + result.stderr
        seen = _recorded(record)
        assert seen["cwd"] == [str(repo.resolve())]
        assert seen["arg"] == [_git(wt, "rev-parse", "HEAD")]

    def test_the_commands_output_is_not_filtered(self, repo, tmp_path):
        _knob(repo, "scripts/deploy.sh\n")
        result = _run(repo, record=tmp_path / "record")
        assert "stub stdout: deploying" in result.stdout
        assert "target left on a build that doesn't answer" in result.stderr


class TestAFailedDeployIsReportedVerbatim:
    @pytest.mark.parametrize("code", ["1", "4", "127"])
    def test_a_non_zero_exit_is_exit_1_naming_the_commands_own_code(
        self, repo, tmp_path, code
    ):
        _knob(repo, "scripts/deploy.sh\n")
        result = _run(repo, record=tmp_path / "record", STUB_EXIT=code)
        assert result.returncode == 1, result.stdout + result.stderr
        assert re.search(rf"\bexited {code}\b", result.stdout + result.stderr)
        assert "target left on a build that doesn't answer" in result.stderr


class TestAbsentMeansTodaysBehaviour:
    def test_no_knob_is_exit_3_and_runs_nothing(self, repo, tmp_path):
        record = tmp_path / "record"
        result = _run(repo, record=record)
        assert result.returncode == 3, result.stdout + result.stderr
        assert not record.exists()
        assert "deploy_command" in result.stdout + result.stderr


class TestAnUnusableKnobIsNeverAbsent:
    """Present but unusable is exit 2: it must not read as 'no deploy configured'."""

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "# only a comment\n\n",
            "scripts/deploy.sh\nscripts/other.sh\n",
            "scripts/missing.sh\n",
            "no-such-command-anywhere-345\n",
        ],
        ids=["empty", "comment-only", "two-commands", "missing-path", "not-on-path"],
    )
    def test_it_is_exit_2_and_runs_nothing(self, repo, tmp_path, text):
        _knob(repo, text)
        record = tmp_path / "record"
        result = _run(repo, record=record)
        assert result.returncode == 2, result.stdout + result.stderr
        assert not record.exists()

    def test_a_command_that_is_not_executable_is_exit_2(self, repo, tmp_path):
        (repo / "scripts" / "deploy.sh").chmod(0o644)
        _knob(repo, "scripts/deploy.sh\n")
        record = tmp_path / "record"
        assert _run(repo, record=record).returncode == 2
        assert not record.exists()

    def test_a_knob_that_is_a_directory_is_exit_2(self, repo, tmp_path):
        (repo / ".skills" / "deploy_command").mkdir(parents=True)
        assert _run(repo, record=tmp_path / "record").returncode == 2


class TestOnlyPushedCodeIsDeployed:
    def test_an_unpushed_head_is_exit_2_and_runs_nothing(self, repo, tmp_path):
        _knob(repo, "scripts/deploy.sh\n")
        (repo / "a.txt").write_text("unpushed\n")
        _git(repo, "add", "a.txt")
        _commit(repo, "not pushed")
        record = tmp_path / "record"
        result = _run(repo, record=record)
        assert result.returncode == 2, result.stdout + result.stderr
        assert not record.exists()
        assert "push" in result.stderr.lower()

    def test_no_upstream_is_exit_2(self, repo, tmp_path):
        _knob(repo, "scripts/deploy.sh\n")
        _git(repo, "checkout", "-q", "-b", "local-only")
        record = tmp_path / "record"
        assert _run(repo, record=record).returncode == 2
        assert not record.exists()


class TestCheckRunsNothing:
    def test_check_prints_the_command_line_and_runs_nothing(self, repo, tmp_path):
        _knob(repo, "env FOO=1 scripts/deploy.sh\n")
        record = tmp_path / "record"
        result = _run(repo, "--check", record=record)
        assert result.returncode == 0, result.stdout + result.stderr
        assert not record.exists()
        sha = _git(repo, "rev-parse", "HEAD")
        assert f"env FOO=1 scripts/deploy.sh {sha}" in result.stdout

    def test_check_with_no_knob_is_exit_3(self, repo, tmp_path):
        assert _run(repo, "--check", record=tmp_path / "r").returncode == 3

    def test_check_with_an_unusable_knob_is_exit_2(self, repo, tmp_path):
        _knob(repo, "scripts/missing.sh\n")
        assert _run(repo, "--check", record=tmp_path / "r").returncode == 2


def test_help_documents_the_exit_codes():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"], capture_output=True, text=True, env=_env()
    )
    assert result.returncode == 0
    for code in ("0", "1", "2", "3"):
        assert re.search(rf"^\s+{code}\s", result.stdout, re.M), result.stdout


def test_an_unknown_argument_is_exit_2(repo, tmp_path):
    assert _run(repo, "--bogus", record=tmp_path / "r").returncode == 2


# --- SKILL.md: the steps that branch on the knob ------------------------------------


def _section(heading: str) -> str:
    text = (SKILL / "SKILL.md").read_text()
    start = text.index(heading)
    end = text.find("\n### ", start + len(heading))
    return text[start : end if end != -1 else len(text)]


def test_step_8_offers_the_deploy_once_through_the_script():
    step8 = _section("### Step 8")
    assert ".skills/deploy_command" in step8
    assert '"<run-deploy-command.sh>"' in step8
    assert re.search(r"once", step8, re.I)
    assert re.search(r"close nothing|close no", step8, re.I), step8


def test_step_6_waits_for_the_deploy_when_the_knob_is_set():
    step6 = _section("### Step 6")
    gate = step6.split("<HARD-GATE>", 1)[1].split("</HARD-GATE>", 1)[0]
    assert ".skills/deploy_command" in gate, gate
    assert re.search(r"production", gate) and re.search(r"exited 0", gate), gate
    assert re.search(r"after Step 8|Step 8 first", step6), step6


def test_step_3_warns_that_merging_can_be_deploying_without_the_knob():
    step3 = _section("### Step 3")
    assert ".skills/deploy_command" in step3
    assert "WorkingDirectory=" in step3


def test_the_fastapi_stack_drops_its_migrate_and_restart_rows_under_the_knob():
    text = (SKILL / "references" / "stack-fastapi.md").read_text()
    assert ".skills/deploy_command" in text


def test_the_generic_step_8_names_no_project():
    """The generic table hard-coded `systemctl restart power-map`."""
    assert "power-map" not in _section("### Step 8")
