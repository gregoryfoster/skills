"""Behavioral tests for doctor.sh SSH/HTTPS auth remediation (issue #50).

Exercises the script end-to-end against a throwaway git repo with a
dangling skill symlink so the submodule-init code path actually runs.
Fake `git` and `ssh` shims on PATH let us control the failure signal
without making real network calls.

Coverage:
- submodule init fails with each of three classified auth signatures
  → targeted remediation block printed
- submodule init fails with a generic (non-auth) error → generic
  message only (no false-positive remediation)
- SSH pre-flight short-circuits before submodule init when .gitmodules
  references SSH remotes and ssh -T reports Permission denied
- HTTPS-only .gitmodules → pre-flight is a no-op (no ssh invocation)
- --no-preflight skips the SSH ping even when .gitmodules is SSH
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "managing-skills"
    / "scripts"
    / "doctor.sh"
)


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — same precaution as
    test_worktree_destroy_base. Pre-commit and other tooling can set
    GIT_INDEX_FILE etc., which would leak into `git -C <tmp_repo>` calls
    inside the script and confuse them."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _real_git() -> str:
    return shutil.which("git") or "/usr/bin/git"


def _make_git_shim(bin_dir: Path, stderr_body: str, exit_code: int = 1) -> None:
    """Create a fake `git` on PATH that intercepts `git submodule …` with a
    canned stderr + exit code, and delegates every other invocation to the
    real git so `rev-parse --show-toplevel` and friends still work.

    Hand-rolled (no textwrap.dedent) because the heredoc terminator must
    sit at column 0 — dedent uses the common leading whitespace of all
    lines, which collapses to zero when stderr_body is unindented and
    leaves the surrounding shim lines indented, breaking heredoc parsing.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    real = _real_git()
    shim = bin_dir / "git"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "submodule" ]; then\n'
        "  cat >&2 <<'__SHIM_STDERR__'\n"
        f"{stderr_body}\n"
        "__SHIM_STDERR__\n"
        f"  exit {exit_code}\n"
        "fi\n"
        f'exec {real} "$@"\n'
    )
    shim.chmod(0o755)


def _make_ssh_shim(bin_dir: Path, stderr_body: str, exit_code: int = 255) -> None:
    """Create a fake `ssh` on PATH used by the pre-flight ping. GitHub-style
    `ssh -T` returns exit 1 on success and 255 on connection failure; we
    only care about whether stderr contains 'Permission denied'."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "ssh"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        "cat >&2 <<'__SHIM_STDERR__'\n"
        f"{stderr_body}\n"
        "__SHIM_STDERR__\n"
        f"exit {exit_code}\n"
    )
    shim.chmod(0o755)


def _make_ssh_shim_per_host(
    bin_dir: Path, host_responses: dict[str, tuple[str, int]]
) -> None:
    """Per-host dispatch ssh shim. `host_responses` maps the host part of
    `git@<host>` to `(stderr_body, exit_code)`. Uses a POSIX `case`
    statement (not bash `[[`) for portability with the doctor's
    bash-3.2-supported invocation.

    Unmatched ssh invocations exit 99 with a stderr message naming the
    args — useful when a test fails because the doctor's ssh args drifted
    from what the shim expects; check `result.stderr` for the unmatched
    `git@<host>` and update `host_responses` to cover it.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    arms = []
    for host, (stderr_body, exit_code) in host_responses.items():
        arms.append(
            f'  *" git@{host} "*)\n'
            "    cat >&2 <<'__SHIM_STDERR__'\n"
            f"{stderr_body}\n"
            "__SHIM_STDERR__\n"
            f"    exit {exit_code}\n"
            "    ;;\n"
        )
    body = (
        "#!/usr/bin/env bash\n"
        'case " $* " in\n' + "".join(arms) + "  *)\n"
        '    echo "ssh-shim: unmatched args: $*" >&2\n'
        "    exit 99\n"
        "    ;;\n"
        "esac\n"
    )
    shim = bin_dir / "ssh"
    shim.write_text(body)
    shim.chmod(0o755)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Repo with a dangling skills/foo symlink so scan_broken populates and
    the script reaches the submodule-init / pre-flight code paths."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=_clean_env(),
    )
    skills = repo / "skills"
    skills.mkdir()
    # Symlink whose target doesn't exist — triggers the doctor's broken-link path.
    os.symlink("../skills-vendor/nonexistent/skills/foo", skills / "foo")
    return repo


def _run_doctor(
    repo: Path,
    extra_path: Path | None = None,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess:
    env = _clean_env()
    if extra_path is not None:
        # Prepend shim dir so our shims win over /usr/bin/{git,ssh}.
        env["PATH"] = f"{extra_path}:{env.get('PATH', '/usr/bin:/bin')}"
    args = ["bash", str(SCRIPT), *(extra_args or [])]
    return subprocess.run(args, capture_output=True, text=True, cwd=repo, env=env)


# ---------------------------------------------------------------------------
# Submodule-init stderr classification
# ---------------------------------------------------------------------------


class TestSubmoduleInitClassification:
    """When submodule init fails with a recognized auth signature, the doctor
    prints the targeted remediation block instead of the generic line."""

    def test_publickey_denied_triggers_remediation(self, tmp_repo, tmp_path):
        _make_git_shim(
            tmp_path / "bin",
            "Cloning into '/tmp/x'...\n"
            "git@github.com: Permission denied (publickey).\n"
            "fatal: Could not read from remote repository.\n"
            "Please make sure you have the correct access rights\n"
            "and the repository exists.",
        )
        # --no-preflight so the SSH ping path doesn't intercept first.
        result = _run_doctor(
            tmp_repo, extra_path=tmp_path / "bin", extra_args=["--no-preflight"]
        )
        assert result.returncode == 1, result.stderr
        # Remediation markers — keep loose so wording tweaks don't break the test.
        assert "ssh-add -l" in result.stderr
        assert "apple-use-keychain" in result.stderr
        assert "insteadOf" in result.stderr
        # Original git stderr is still mirrored back so the user sees the raw signal.
        assert "Permission denied (publickey)" in result.stderr

    def test_could_not_read_from_remote_triggers_remediation(self, tmp_repo, tmp_path):
        _make_git_shim(
            tmp_path / "bin",
            "fatal: Could not read from remote repository.\n"
            "Please make sure you have the correct access rights.",
        )
        result = _run_doctor(
            tmp_repo, extra_path=tmp_path / "bin", extra_args=["--no-preflight"]
        )
        assert result.returncode == 1
        assert "apple-use-keychain" in result.stderr

    def test_https_authentication_failed_triggers_remediation(self, tmp_repo, tmp_path):
        _make_git_shim(
            tmp_path / "bin",
            "fatal: Authentication failed for 'https://github.com/example/foo.git/'",
        )
        result = _run_doctor(
            tmp_repo, extra_path=tmp_path / "bin", extra_args=["--no-preflight"]
        )
        assert result.returncode == 1
        assert "apple-use-keychain" in result.stderr

    def test_password_denied_triggers_remediation(self, tmp_repo, tmp_path):
        """The tightened `Permission denied \\(` regex must catch the
        password-method variant, not just publickey."""
        _make_git_shim(
            tmp_path / "bin",
            "git@example.com: Permission denied (password).\n"
            "fatal: Could not read from remote repository.",
        )
        result = _run_doctor(
            tmp_repo, extra_path=tmp_path / "bin", extra_args=["--no-preflight"]
        )
        assert result.returncode == 1
        assert "apple-use-keychain" in result.stderr

    def test_multi_method_denied_triggers_remediation(self, tmp_repo, tmp_path):
        """Servers with multiple auth methods enabled return a comma-joined
        list inside the parentheses — the open-paren regex still catches it."""
        _make_git_shim(
            tmp_path / "bin",
            "git@example.com: Permission denied (publickey,password,keyboard-interactive).\n"
            "fatal: Could not read from remote repository.",
        )
        result = _run_doctor(
            tmp_repo, extra_path=tmp_path / "bin", extra_args=["--no-preflight"]
        )
        assert result.returncode == 1
        assert "apple-use-keychain" in result.stderr

    def test_generic_failure_no_false_positive_remediation(self, tmp_repo, tmp_path):
        """A non-auth submodule failure must not trigger the SSH remediation
        block — only the original generic line. Protects against the
        classifier matching too broadly and confusing the operator."""
        _make_git_shim(
            tmp_path / "bin",
            "fatal: destination path '/tmp/x' already exists and is not empty",
        )
        result = _run_doctor(
            tmp_repo, extra_path=tmp_path / "bin", extra_args=["--no-preflight"]
        )
        assert result.returncode == 1
        assert "'git submodule update --init --recursive' failed" in result.stderr
        assert "apple-use-keychain" not in result.stderr
        assert "ssh-add -l" not in result.stderr


# ---------------------------------------------------------------------------
# SSH pre-flight ping
# ---------------------------------------------------------------------------


class TestSSHPreflight:
    """The pre-flight runs only when .gitmodules references SSH remotes.
    A 'Permission denied' result short-circuits before submodule init."""

    def _write_gitmodules(self, repo: Path, body: str) -> None:
        (repo / ".gitmodules").write_text(body)

    def test_ssh_preflight_failure_short_circuits(self, tmp_repo, tmp_path):
        self._write_gitmodules(
            tmp_repo,
            '[submodule "vendor/x"]\n'
            "\tpath = vendor/x\n"
            "\turl = git@github.com:example/x.git\n",
        )
        # Shim ssh to fail with Permission denied. Also shim git so that
        # IF the script doesn't short-circuit, we'd see a distinguishable
        # generic failure — but the expectation is the pre-flight catches it.
        bin_dir = tmp_path / "bin"
        _make_ssh_shim(
            bin_dir,
            "git@github.com: Permission denied (publickey).",
            exit_code=255,
        )
        # Sentinel: if git submodule were called, this stderr would appear.
        _make_git_shim(bin_dir, "SHOULD NOT REACH submodule init")
        result = _run_doctor(tmp_repo, extra_path=bin_dir)
        assert result.returncode == 1
        assert "SSH pre-flight failed" in result.stderr
        assert "github.com" in result.stderr
        assert "apple-use-keychain" in result.stderr
        # Submodule init must not have been invoked.
        assert "SHOULD NOT REACH" not in result.stderr

    def test_https_only_gitmodules_skips_preflight(self, tmp_repo, tmp_path):
        """No SSH URLs → no ssh invocation. We prove this by shimming ssh
        to error loudly; if pre-flight ran, that error would surface."""
        self._write_gitmodules(
            tmp_repo,
            '[submodule "vendor/x"]\n'
            "\tpath = vendor/x\n"
            "\turl = https://github.com/example/x.git\n",
        )
        bin_dir = tmp_path / "bin"
        _make_ssh_shim(bin_dir, "PREFLIGHT SHOULD NOT INVOKE SSH", exit_code=1)
        # Generic git failure so the test exits 1 deterministically without
        # network. We only care that ssh wasn't called.
        _make_git_shim(bin_dir, "fatal: some non-auth problem")
        result = _run_doctor(tmp_repo, extra_path=bin_dir)
        assert result.returncode == 1
        assert "PREFLIGHT SHOULD NOT INVOKE SSH" not in result.stderr
        assert "SSH pre-flight failed" not in result.stderr

    def test_no_preflight_flag_skips_ping(self, tmp_repo, tmp_path):
        """Even with SSH URLs in .gitmodules, --no-preflight must skip the
        ssh call entirely — operator opt-out for the 3-second timeout."""
        self._write_gitmodules(
            tmp_repo,
            '[submodule "vendor/x"]\n'
            "\tpath = vendor/x\n"
            "\turl = git@github.com:example/x.git\n",
        )
        bin_dir = tmp_path / "bin"
        _make_ssh_shim(bin_dir, "PREFLIGHT SHOULD NOT INVOKE SSH", exit_code=1)
        _make_git_shim(bin_dir, "fatal: some non-auth problem")
        result = _run_doctor(
            tmp_repo, extra_path=bin_dir, extra_args=["--no-preflight"]
        )
        assert result.returncode == 1
        assert "PREFLIGHT SHOULD NOT INVOKE SSH" not in result.stderr
        assert "SSH pre-flight failed" not in result.stderr

    def test_ssh_preflight_success_proceeds_to_submodule_init(self, tmp_repo, tmp_path):
        """When ssh -T returns GitHub's success banner, the pre-flight passes
        and the script continues to submodule init. We prove this by
        shimming git submodule with a sentinel error and asserting the
        sentinel appears in stderr — that's only possible if the
        submodule call actually ran."""
        self._write_gitmodules(
            tmp_repo,
            '[submodule "vendor/x"]\n'
            "\tpath = vendor/x\n"
            "\turl = git@github.com:example/x.git\n",
        )
        bin_dir = tmp_path / "bin"
        _make_ssh_shim(
            bin_dir,
            "Hi gregoryfoster! You've successfully authenticated, "
            "but GitHub does not provide shell access.",
            exit_code=1,
        )
        _make_git_shim(bin_dir, "SUBMODULE_INIT_REACHED_SENTINEL")
        result = _run_doctor(tmp_repo, extra_path=bin_dir)
        assert result.returncode == 1  # sentinel fails the init deliberately
        assert "SUBMODULE_INIT_REACHED_SENTINEL" in result.stderr
        assert "SSH pre-flight failed" not in result.stderr

    def test_ssh_preflight_host_key_failure_short_circuits_with_keyscan_hint(
        self, tmp_repo, tmp_path
    ):
        """Host-key-verification failures are classified separately from
        auth failures and surface the keyscan-based remediation, not the
        agent/keychain one."""
        self._write_gitmodules(
            tmp_repo,
            '[submodule "vendor/x"]\n'
            "\tpath = vendor/x\n"
            "\turl = git@github.com:example/x.git\n",
        )
        bin_dir = tmp_path / "bin"
        _make_ssh_shim(
            bin_dir,
            "No ED25519 host key is known for github.com and you have requested "
            "strict checking.\nHost key verification failed.",
            exit_code=255,
        )
        _make_git_shim(bin_dir, "SHOULD NOT REACH submodule init")
        result = _run_doctor(tmp_repo, extra_path=bin_dir)
        assert result.returncode == 1
        assert "host key not trusted" in result.stderr
        assert "ssh-keyscan" in result.stderr
        # Agent remediation should NOT appear — wrong rung for this failure.
        assert "apple-use-keychain" not in result.stderr
        # Submodule init must not have been invoked.
        assert "SHOULD NOT REACH" not in result.stderr

    def test_ssh_preflight_mixed_failures_prints_both_remediations(
        self, tmp_repo, tmp_path
    ):
        """Two hosts, two different failure modes: the doctor must print
        each remediation once and tag each host into the right bucket.
        Refactors that collapse the two arrays into one would regress
        this — the test fails if either remediation goes missing."""
        self._write_gitmodules(
            tmp_repo,
            '[submodule "vendor/a"]\n'
            "\tpath = vendor/a\n"
            "\turl = git@host-a.example.com:owner/a.git\n"
            '[submodule "vendor/b"]\n'
            "\tpath = vendor/b\n"
            "\turl = git@host-b.example.com:owner/b.git\n",
        )
        bin_dir = tmp_path / "bin"
        _make_ssh_shim_per_host(
            bin_dir,
            {
                "host-a.example.com": (
                    "git@host-a.example.com: Permission denied (publickey).",
                    255,
                ),
                "host-b.example.com": (
                    "No ED25519 host key is known for host-b.example.com.\n"
                    "Host key verification failed.",
                    255,
                ),
            },
        )
        _make_git_shim(bin_dir, "SHOULD NOT REACH submodule init")
        result = _run_doctor(tmp_repo, extra_path=bin_dir)
        assert result.returncode == 1
        # Each host appears in the corresponding bucket's diagnostic line.
        assert "agent cannot authenticate to: host-a.example.com" in result.stderr
        assert "host key not trusted for: host-b.example.com" in result.stderr
        # Both remediation blocks rendered.
        assert "apple-use-keychain" in result.stderr
        assert "ssh-keyscan" in result.stderr
        # Pre-flight short-circuited before submodule init.
        assert "SHOULD NOT REACH" not in result.stderr


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class TestCLISurface:
    def test_help_documents_no_preflight_flag(self):
        result = subprocess.run(
            ["bash", str(SCRIPT), "--help"], capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "--no-preflight" in result.stdout

    def test_help_mentions_host_key_remediation_path(self):
        """The host-key failure mode is a distinct path documented in
        --help. Pin a stable substring so a doc-only refactor that
        removes the mention surfaces as a test failure."""
        result = subprocess.run(
            ["bash", str(SCRIPT), "--help"], capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "host-key" in result.stdout or "ssh-keyscan" in result.stdout

    def test_unknown_flag_still_exits_2(self):
        result = subprocess.run(
            ["bash", str(SCRIPT), "--bogus"], capture_output=True, text=True
        )
        assert result.returncode == 2
        assert "unknown option" in result.stderr
