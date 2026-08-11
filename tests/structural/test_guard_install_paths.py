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



class TestGuardCommandForm:
    """#110 — the wired command must not depend on the hook process's cwd."""

    @requires_jq
    def test_installer_writes_a_project_dir_anchored_command(self, tmp_path: Path):
        repo = _repo(tmp_path)
        vendored = _install_guard_at(repo)
        assert _run_installer(repo, vendored).returncode == 0

        assert _post_tool_commands(repo) == [GUARD_COMMAND]

    @requires_jq
    def test_the_wired_command_works_from_a_foreign_cwd(self, tmp_path: Path):
        """The property the issue is actually about: run the literal command
        string with a cwd that is not the project and it must still measure."""
        repo = _repo(tmp_path)
        vendored = _install_guard_at(repo)
        assert _run_installer(repo, vendored).returncode == 0
        (repo / "AGENTS.md").write_text(POLICY_LINE * 2600)

        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        env = _clean_env()
        env["CLAUDE_PROJECT_DIR"] = str(repo)
        command = _post_tool_commands(repo)[0]
        result = subprocess.run(
            ["bash", "-c", command], input=_payload(repo / "AGENTS.md"),
            capture_output=True, text=True, cwd=str(elsewhere),
            env=env, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "context budget" in result.stdout, (
            "the hook did not resolve from a foreign cwd: " + repr(result.stdout)
        )

    @requires_jq
    def test_install_replaces_a_legacy_cwd_relative_entry(self, tmp_path: Path):
        repo = _repo(tmp_path)
        vendored = _install_guard_at(repo)
        (repo / ".claude").mkdir()
        (repo / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {"PostToolUse": [
                {"matcher": "Edit|Write|MultiEdit",
                 "hooks": [{"type": "command", "command": LEGACY_GUARD_COMMAND,
                            "timeout": 10}]},
                {"matcher": "Bash",
                 "hooks": [{"type": "command", "command": "bash other.sh"}]},
            ]}
        }))
        assert _run_installer(repo, vendored).returncode == 0

        assert _post_tool_commands(repo) == ["bash other.sh", GUARD_COMMAND], (
            "the legacy entry survived, so the repo now runs the guard twice"
        )

    @requires_jq
    def test_uninstall_removes_a_legacy_cwd_relative_entry(self, tmp_path: Path):
        """The subtle half: if the removal filter only matches the new string,
        every existing install becomes unremovable."""
        repo = _repo(tmp_path)
        vendored = _install_guard_at(repo)
        (repo / ".claude").mkdir()
        (repo / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {"PostToolUse": [
                {"matcher": "Edit|Write|MultiEdit",
                 "hooks": [{"type": "command", "command": LEGACY_GUARD_COMMAND,
                            "timeout": 10}]},
                {"matcher": "Bash",
                 "hooks": [{"type": "command", "command": "bash other.sh"}]},
            ]}
        }))
        result = _run_installer(repo, vendored, "--uninstall")
        assert result.returncode == 0, result.stdout + result.stderr

        assert _post_tool_commands(repo) == ["bash other.sh"]

    @requires_jq
    def test_install_is_still_idempotent(self, tmp_path: Path):
        repo = _repo(tmp_path)
        vendored = _install_guard_at(repo)
        assert _run_installer(repo, vendored).returncode == 0
        assert _run_installer(repo, vendored).returncode == 0

        assert _post_tool_commands(repo) == [GUARD_COMMAND]

    @requires_jq
    def test_check_recognises_a_legacy_entry_and_names_it(self, tmp_path: Path):
        """A legacy entry is installed and working. Reporting it 'not installed'
        would be a false negative; reporting it silently would strand it."""
        repo = _repo(tmp_path)
        vendored = _install_guard_at(repo)
        assert _run_installer(repo, vendored).returncode == 0
        settings = repo / ".claude" / "settings.json"
        settings.write_text(
            settings.read_text().replace(json.dumps(GUARD_COMMAND)[1:-1],
                                         LEGACY_GUARD_COMMAND)
        )

        result = _run_installer(repo, vendored, "--check")
        assert result.returncode == 0, result.stdout + result.stderr
        # A phrase, not the word "legacy" — pytest's tmp_path embeds the test
        # name, so a bare substring test passes on the paths --check prints.
        assert "cwd-relative command form" in result.stdout, result.stdout



class TestManagingSkillsHookCommand:
    """#110's second and third installers. The documented jq snippets are run
    verbatim, because a removal filter that stops matching the old form is how
    an existing install becomes unremovable."""

    def _fenced_blocks(self, text: str) -> list[str]:
        return re.findall(r"```(?:bash|json)\n(.*?)```", text, re.DOTALL)

    def _jq_block(self, needle: str) -> str:
        blocks = [
            b for b in self._fenced_blocks(MS_SKILL.read_text())
            if "jq " in b and needle in b
        ]
        assert len(blocks) == 1, (
            f"expected exactly one documented jq block containing {needle!r}, "
            f"found {len(blocks)}"
        )
        return blocks[0]

    def _seed(self, tmp_path: Path, command: str) -> Path:
        (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {"SessionStart": [
                {"matcher": ".*",
                 "hooks": [{"type": "command", "command": command}]},
                {"matcher": ".*",
                 "hooks": [{"type": "command", "command": "bash unrelated.sh"}]},
            ]}
        }))
        return tmp_path / ".claude" / "settings.json"

    def _session_commands(self, settings: Path) -> list[str]:
        data = json.loads(settings.read_text())
        return [
            h.get("command", "")
            for e in data.get("hooks", {}).get("SessionStart", [])
            for h in e.get("hooks", [])
        ]

    def _run_block(self, block: str, cwd: Path):
        result = subprocess.run(
            ["bash", "-c", block], capture_output=True, text=True,
            cwd=str(cwd), env=_clean_env(), timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    @requires_jq
    def test_documented_install_snippet_writes_the_anchored_command(self, tmp_path):
        settings = self._seed(tmp_path, "bash unrelated-only.sh")
        settings.write_text(json.dumps({}))
        self._run_block(self._jq_block("SessionStart +="), tmp_path)

        assert self._session_commands(settings) == [UPDATE_COMMAND]

    @requires_jq
    def test_documented_install_snippet_replaces_a_legacy_entry(self, tmp_path):
        settings = self._seed(tmp_path, LEGACY_UPDATE_COMMAND)
        self._run_block(self._jq_block("SessionStart +="), tmp_path)

        assert self._session_commands(settings) == [
            "bash unrelated.sh", UPDATE_COMMAND
        ]

    @requires_jq
    def test_documented_uninstall_snippet_removes_a_legacy_entry(self, tmp_path):
        settings = self._seed(tmp_path, LEGACY_UPDATE_COMMAND)
        self._run_block(self._jq_block("if .hooks.SessionStart then"), tmp_path)

        assert self._session_commands(settings) == ["bash unrelated.sh"]

    @requires_jq
    def test_documented_uninstall_snippet_removes_the_current_entry(self, tmp_path):
        settings = self._seed(tmp_path, UPDATE_COMMAND)
        self._run_block(self._jq_block("if .hooks.SessionStart then"), tmp_path)

        assert self._session_commands(settings) == ["bash unrelated.sh"]

    def test_no_installer_still_documents_the_cwd_relative_form(self):
        """All three installers must agree, or a repo's settings.json ends up
        with a mix of styles — which is what made this visible in review."""
        offenders = []
        for path in (MS_SKILL, FASTAPI_SKILL, INSTALL):
            for i, line in enumerate(path.read_text().splitlines(), 1):
                if re.search(r'bash \.claude/hooks/\S+\.sh', line):
                    offenders.append(f"{path.name}:{i}: {line.strip()}")
        assert not offenders, "\n".join(offenders)



class TestDoctorHealsHookSymlinks:
    """#99 — a dangling hook symlink fails on every Edit|Write|MultiEdit, which
    is a far higher-frequency event than invoking a skill."""

    def _repo_with_hooks(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        (repo / ".claude" / "hooks").mkdir(parents=True)
        return repo

    def _doctor(self, repo: Path, *args: str):
        return subprocess.run(
            ["bash", str(DOCTOR), *args], capture_output=True, text=True,
            cwd=str(repo), env=_clean_env(), timeout=60,
        )

    def test_dangling_hook_symlink_is_reported(self, tmp_path: Path):
        repo = self._repo_with_hooks(tmp_path)
        (repo / "skills").mkdir()
        (repo / ".claude" / "hooks" / "context-budget-guard.sh").symlink_to(
            "../../skills-vendor/acme/scripts/context-budget-guard.sh"
        )

        result = self._doctor(repo, "--check-only")
        assert result.returncode == 1, result.stdout + result.stderr
        assert ".claude/hooks/context-budget-guard.sh" in result.stderr, result.stderr

    def test_dangling_hook_symlink_is_reported_without_a_skills_dir(self, tmp_path):
        """The early exit was `[ ! -d skills ]`. A consumer that wires a hook but
        keeps no skills/ tree must still be checked."""
        repo = self._repo_with_hooks(tmp_path)
        (repo / ".claude" / "hooks" / "context-budget-guard.sh").symlink_to(
            "../../skills-vendor/acme/scripts/context-budget-guard.sh"
        )

        result = self._doctor(repo, "--check-only")
        assert result.returncode == 1, result.stdout + result.stderr
        assert ".claude/hooks/context-budget-guard.sh" in result.stderr, result.stderr

    def test_resolving_hook_symlink_is_silent(self, tmp_path: Path):
        repo = self._repo_with_hooks(tmp_path)
        target = repo / "real-hook.sh"
        target.write_text("#!/usr/bin/env bash\n")
        (repo / ".claude" / "hooks" / "context-budget-guard.sh").symlink_to(
            "../../real-hook.sh"
        )

        result = self._doctor(repo, "--check-only")
        assert result.returncode == 0, result.stdout + result.stderr

    def test_regular_files_in_hooks_are_not_symlinks(self, tmp_path: Path):
        repo = self._repo_with_hooks(tmp_path)
        (repo / ".claude" / "hooks" / "local.sh").write_text("#!/bin/sh\n")

        result = self._doctor(repo, "--check-only")
        assert result.returncode == 0, result.stdout + result.stderr

    def test_no_scan_dirs_at_all_is_a_silent_noop(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")

        result = self._doctor(repo)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr.strip() == "", result.stderr

    def test_heal_scope_is_documented(self):
        """A heal scope nobody knows about gets re-litigated in every consumer."""
        text = MS_SKILL.read_text()
        assert ".claude/hooks/" in text and "doctor" in text.lower()
        help_text = subprocess.run(
            ["bash", str(DOCTOR), "--help"], capture_output=True, text=True,
            env=_clean_env(), timeout=30,
        ).stdout
        assert ".claude/hooks/" in help_text, help_text



class TestUncoveredWritePathsAreDocumented:
    """#103 — documentation only. Widening the matcher to `Bash` would fire the
    guard on every shell command to catch a small fraction of writes, inverting
    its deliberate cheapness. The fix is to stop the docs implying coverage."""

    def test_the_guard_doc_names_the_uncovered_write_paths(self):
        text = GUARD_DOC.read_text()
        assert "NotebookEdit" in text, "the doc never names the NotebookEdit gap"
        assert re.search(r"redirect|heredoc|>>", text), (
            "the doc never names shell-redirect writes"
        )
        assert "context-delta.sh" in text, (
            "the doc names the gap without naming the surface that covers it"
        )

    def test_phase_8_names_which_half_covers_which_failure(self):
        text = CTX_SKILL.read_text()
        phase8 = text[text.index("## Phase 8"):]
        assert "NotebookEdit" in phase8 or "redirect" in phase8, (
            "Phase 8 still frames the ratchet without naming what the guard "
            "cannot see"
        )
        assert "context-delta.sh" in phase8

    def test_the_matcher_is_unchanged(self):
        assert "Edit|Write|MultiEdit" in INSTALL.read_text()
        assert '"Bash"' not in INSTALL.read_text()
