"""Behavioral tests for how hooks are *located* once installed (#109, #110, #99).

Three defects with one shape: the install path was written relative to something
that is not always what it was assumed to be.

- #109 — the guard logged to `$(git rev-parse --show-toplevel)/.git/…`. In a
  linked worktree that `.git` is a *file*, so every append failed and was
  swallowed by `|| true` — no audit trail in precisely the trees several cohort
  repos mandate all development happens in.
- #110 — the wired `PostToolUse` command was `bash .claude/hooks/…`, relative to
  the hook process's cwd. It works only because Claude Code happens to run hooks
  from the project dir. The removal filters must keep matching entries written in
  the old form, or an existing install becomes unremovable.
- #99 — `doctor.sh` only walked `skills/*`, so a dangling `.claude/hooks/*`
  symlink (fresh clone, `git worktree add`, shallow CI clone) failed with exit
  127 on every Edit|Write|MultiEdit while `ls` showed the symlink present.

Plus the documentation half of #103: the guard's matcher cannot see shell
redirects or `NotebookEdit`, and the docs must say so rather than let a reader
infer coverage that does not exist.

No API calls: every path here uses the guard's offline estimate.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CTX_SCRIPTS = REPO_ROOT / "skills" / "curating-context" / "scripts"
GUARD = CTX_SCRIPTS / "context-budget-guard.sh"
INSTALL = CTX_SCRIPTS / "install-guard.sh"
CTX_SKILL = REPO_ROOT / "skills" / "curating-context" / "SKILL.md"
GUARD_DOC = REPO_ROOT / "skills" / "curating-context" / "references" / "write-guard-hook.md"

MS_SCRIPTS = REPO_ROOT / "skills" / "managing-skills" / "scripts"
DOCTOR = MS_SCRIPTS / "doctor.sh"
MS_SKILL = REPO_ROOT / "skills" / "managing-skills" / "SKILL.md"
FASTAPI_SKILL = REPO_ROOT / "skills" / "init-project-fastapi" / "SKILL.md"

# The canonical command form, matching the `${CLAUDE_PROJECT_DIR:-.}` house style
# init-socraticode established: the fallback keeps an environment that fires the
# hook without the variable set from degrading to `bash "/.claude/hooks/…"`.
GUARD_COMMAND = 'bash "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/context-budget-guard.sh"'
LEGACY_GUARD_COMMAND = "bash .claude/hooks/context-budget-guard.sh"
UPDATE_COMMAND = 'bash "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/skills-submodule-update.sh"'
LEGACY_UPDATE_COMMAND = "bash .claude/hooks/skills-submodule-update.sh"

POLICY_LINE = "- a policy line naming `some/path.py` and explaining why\n"

requires_jq = pytest.mark.skipif(
    shutil.which("jq") is None, reason="jq is required to merge settings.json"
)


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR",
              "CLAUDE_PROJECT_DIR"):
        env.pop(k, None)
    return env


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True, capture_output=True, text=True, env=_clean_env(),
    ).stdout.strip()


def _repo(tmp_path: Path, policy_lines: int = 2000) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "AGENTS.md").write_text(POLICY_LINE * policy_lines)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _install_guard_at(repo: Path) -> Path:
    """Copy the guard + its library into the repo and wire it, the way a
    vendored install does. Returns the vendored scripts dir."""
    vendored = repo / "skills-vendor" / "acme" / "scripts"
    vendored.mkdir(parents=True)
    for name in ("context-budget-guard.sh", "install-guard.sh", "_context-lib.sh"):
        shutil.copy2(CTX_SCRIPTS / name, vendored / name)
    return vendored


def _run_installer(repo: Path, vendored: Path, *args: str):
    return subprocess.run(
        ["bash", str(vendored / "install-guard.sh"), *args],
        capture_output=True, text=True, cwd=str(repo), env=_clean_env(), timeout=60,
    )


def _payload(file_path: Path) -> str:
    return json.dumps(
        {"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}
    )


def _settings(repo: Path) -> dict:
    return json.loads((repo / ".claude" / "settings.json").read_text())


def _post_tool_commands(repo: Path) -> list[str]:
    out = []
    for entry in _settings(repo).get("hooks", {}).get("PostToolUse", []):
        for hook in entry.get("hooks", []):
            out.append(hook.get("command", ""))
    return out


class TestGuardLogPath:
    """#109 — the log must land in the git dir that actually exists."""

    def test_main_checkout_logs_under_dot_git(self, tmp_path: Path):
        repo = _repo(tmp_path)
        result = subprocess.run(
            ["bash", str(GUARD)], input=_payload(repo / "AGENTS.md"),
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=30,
        )
        assert result.returncode == 0, result.stderr
        log = repo / ".git" / "context-budget.log"
        assert log.exists(), "no log written in an ordinary checkout"
        assert "AGENTS.md" in log.read_text()

    def test_linked_worktree_logs_into_its_own_git_dir(self, tmp_path: Path):
        """`$ROOT/.git` is a FILE in a linked worktree, so the old path could
        never be appended to — and the failure was swallowed by `|| true`."""
        repo = _repo(tmp_path)
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feature", str(wt))
        assert (wt / ".git").is_file(), "fixture is not a linked worktree"

        # Push it over budget in the worktree so the guard has something to say.
        (wt / "AGENTS.md").write_text(POLICY_LINE * 2600)
        result = subprocess.run(
            ["bash", str(GUARD)], input=_payload(wt / "AGENTS.md"),
            capture_output=True, text=True, cwd=str(wt),
            env=_clean_env(), timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip(), "the guard stayed silent on an over-budget file"

        gitdir = Path(_git(wt, "rev-parse", "--absolute-git-dir"))
        log = gitdir / "context-budget.log"
        assert log.exists(), (
            f"no log at {log} — the guard still writes to a path that is a file "
            "in a linked worktree"
        )
        assert "WARN" in log.read_text()

    def test_installer_hint_names_the_resolved_log_path(self, tmp_path: Path):
        """The hardcoded `tail .git/context-budget.log` hint fails in a worktree,
        which reads as 'the guard is broken' when it is not."""
        repo = _repo(tmp_path)
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feature", str(wt))
        vendored = _install_guard_at(wt)

        result = _run_installer(wt, vendored)
        assert result.returncode == 0, result.stdout + result.stderr

        gitdir = _git(wt, "rev-parse", "--absolute-git-dir")
        assert f"{gitdir}/context-budget.log" in result.stdout, result.stdout


