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
    an existing install becomes unremovable.

    The INSTALL half is now install-refresh.sh rather than a jq block in
    SKILL.md (#167) — a hand-executed procedure left four of twelve consumers
    half-installed — so these two run the script. The rule is unchanged and
    still belongs here; only its implementation moved from prose to code. The
    uninstall filter below is still documented prose and still run verbatim."""

    def _consumer(self, tmp_path: Path) -> Path:
        """A checkout install-refresh.sh will act on: a git repo with the hook
        script vendored where the installer's glob looks for it."""
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True,
                       env=_clean_env())
        vendor = (tmp_path / "skills-vendor" / "acme-skills" / "skills"
                  / "managing-skills" / "scripts")
        vendor.mkdir(parents=True)
        (vendor / "skills-submodule-update.sh").write_text(
            (MS_SCRIPTS / "skills-submodule-update.sh").read_text())
        return tmp_path

    def _install(self, cwd: Path):
        result = subprocess.run(
            ["bash", str(MS_SCRIPTS / "install-refresh.sh"), "--quiet"],
            capture_output=True, text=True, cwd=str(cwd), env=_clean_env(),
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr

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
    def test_the_installer_writes_the_anchored_command(self, tmp_path):
        repo = self._consumer(tmp_path)
        settings = self._seed(repo, "bash unrelated-only.sh")
        settings.write_text(json.dumps({}))
        self._install(repo)

        assert self._session_commands(settings) == [UPDATE_COMMAND]

    @requires_jq
    def test_the_installer_replaces_a_legacy_entry(self, tmp_path):
        repo = self._consumer(tmp_path)
        settings = self._seed(repo, LEGACY_UPDATE_COMMAND)
        self._install(repo)

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


class TestCheckRecognisesTheFormItJustWrote:
    """CR round 1, finding 1.

    `--check` compared $COMMAND against the raw settings.json with `grep -qF`.
    jq writes the command with its inner quotes JSON-escaped —
    `bash \"${CLAUDE_PROJECT_DIR:-.}/…\"` — so the grep could never match what
    the installer had just written, and the "older cwd-relative command form"
    note fired forever, including on the run immediately after a successful
    normalize.

    A check that cannot report success is worse than no check: it trains the
    reader to ignore it, which is the same failure this whole batch is about.
    """

    LEGACY_NOTE = "older cwd-relative command form"

    def test_check_is_quiet_after_a_fresh_install(self, tmp_path: Path):
        repo = _repo(tmp_path)
        vendored = _install_guard_at(repo)
        assert _run_installer(repo, vendored).returncode == 0

        r = _run_installer(repo, vendored, "--check")
        assert r.returncode == 0, r.stdout + r.stderr
        assert self.LEGACY_NOTE not in r.stdout, (
            "--check called its own freshly written command legacy:\n" + r.stdout
        )

    def test_check_is_quiet_after_normalizing_a_legacy_entry(self, tmp_path: Path):
        """The reported reproduction: normalize, then immediately re-check."""
        repo = _repo(tmp_path)
        vendored = _install_guard_at(repo)
        hooks = repo / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "context-budget-guard.sh").symlink_to(vendored / "context-budget-guard.sh")
        (repo / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {"PostToolUse": [{
                "matcher": "Edit|Write|MultiEdit",
                "hooks": [{"type": "command",
                           "command": "bash .claude/hooks/context-budget-guard.sh",
                           "timeout": 10}],
            }]}
        }))
        assert self.LEGACY_NOTE in _run_installer(repo, vendored, "--check").stdout, (
            "the legacy form was not detected before normalizing — test is vacuous"
        )
        assert _run_installer(repo, vendored).returncode == 0
        r = _run_installer(repo, vendored, "--check")
        assert self.LEGACY_NOTE not in r.stdout, (
            "still reported legacy after a successful normalize:\n" + r.stdout
        )
        assert len(_post_tool_commands(repo)) == 1, "normalize duplicated the entry"

    def test_a_genuine_legacy_entry_still_reports(self, tmp_path: Path):
        """The fix must not buy silence by never reporting."""
        repo = _repo(tmp_path)
        vendored = _install_guard_at(repo)
        hooks = repo / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "context-budget-guard.sh").symlink_to(vendored / "context-budget-guard.sh")
        (repo / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {"PostToolUse": [{
                "matcher": "Edit|Write|MultiEdit",
                "hooks": [{"type": "command",
                           "command": "bash .claude/hooks/context-budget-guard.sh"}],
            }]}
        }))
        r = _run_installer(repo, vendored, "--check")
        assert self.LEGACY_NOTE in r.stdout, r.stdout


class TestGuardMergeFailsHonestly:
    """#181 — a settings rewrite that fails must say so and leave no debris.

    `jq … >"$SETTINGS.tmp" && mv -f "$SETTINGS.tmp" "$SETTINGS"` is the shape
    that let install-refresh.sh report a registration it had not written: under
    `set -e` the failure of the FIRST element of an `&&` list is exempt, so
    neither the abort nor the skip happens and the success line runs anyway.

    Here the list is the last command of `merge_settings`, and the function is
    called as a plain command — so errexit DOES fire on the caller and the
    false success line is not reached (verified, not assumed). What survives is
    the rest of the damage the checked form prevents: an orphaned
    `.claude/settings.json.tmp` for `git add -A` to collect, and a bare jq
    parse error with nothing saying which of settings.json and the symlink was
    actually touched.

    The driver is a settings.json that is valid JSON — so the existing
    `jq -e .` guard passes it — but whose `.hooks` is the wrong TYPE, which is
    what a hand edit produces and what makes the merge filter error mid-run.
    """

    # Valid JSON, wrong shape: `.hooks.PostToolUse //= []` cannot index a
    # string, so jq exits 5 having written nothing.
    WRONG_SHAPE = '{"hooks": "was-a-string"}'

    def _seed(self, tmp_path: Path):
        repo = _repo(tmp_path)
        vendored = _install_guard_at(repo)
        (repo / ".claude").mkdir(exist_ok=True)
        (repo / ".claude" / "settings.json").write_text(self.WRONG_SHAPE)
        return repo, vendored

    @requires_jq
    def test_a_failed_merge_leaves_no_temp_file(self, tmp_path: Path):
        """`git add -A` would otherwise pick up .claude/settings.json.tmp."""
        repo, vendored = self._seed(tmp_path)
        _run_installer(repo, vendored)
        assert not (repo / ".claude" / "settings.json.tmp").exists(), sorted(
            p.name for p in (repo / ".claude").iterdir()
        )

    @requires_jq
    def test_a_failed_merge_does_not_claim_a_merge(self, tmp_path: Path):
        repo, vendored = self._seed(tmp_path)
        r = _run_installer(repo, vendored)
        assert r.returncode != 0, r.stdout + r.stderr
        assert "merged the PostToolUse entry" not in r.stdout, (
            "claimed a merge it did not write:\n" + r.stdout
        )
        assert (repo / ".claude" / "settings.json").read_text() == self.WRONG_SHAPE

    @requires_jq
    def test_a_failed_merge_names_the_file_it_did_not_modify(self, tmp_path: Path):
        """A bare `jq: error (at …)` and exit 5 is not a diagnosis. The symlink
        line has already printed by then, so the reader needs to be told which
        half landed — install-refresh.sh's CR finding 14, same shape."""
        repo, vendored = self._seed(tmp_path)
        r = _run_installer(repo, vendored)
        assert "settings.json" in r.stderr, r.stderr
        assert "not modified" in r.stderr.lower(), r.stderr

    @requires_jq
    def test_a_failed_uninstall_does_not_claim_an_uninstall(self, tmp_path: Path):
        """The uninstall path removes the symlink AFTER the merge and then
        announces both. A merge that fails must not reach either."""
        repo, vendored = self._seed(tmp_path)
        # Wire the symlink by hand: the installer cannot get that far here.
        hooks = repo / ".claude" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        hook = hooks / "context-budget-guard.sh"
        hook.symlink_to(vendored / "context-budget-guard.sh")
        r = _run_installer(repo, vendored, "--uninstall")
        assert r.returncode != 0, r.stdout + r.stderr
        assert "uninstalled:" not in r.stdout, (
            "claimed an uninstall it did not perform:\n" + r.stdout
        )
        assert hook.is_symlink(), "removed the hook after failing to unregister it"
        assert not (repo / ".claude" / "settings.json.tmp").exists()
