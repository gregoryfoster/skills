"""Behavioral tests for the auto-refresh hook's commit scope (issue #86).

The hook installs `.skills/doctor.sh` on every session but historically only
staged `skills-vendor/`, so the file it had just written stayed untracked
forever. Four of twelve audited consumers had been reinstalling a doctor for
weeks that had never once been committed — leaving their fresh worktrees and
CI clones with no doctor and a silently short-circuiting Phase 1 preflight.

Run end-to-end against throwaway repos with a shimmed `git submodule`, because
what matters is runtime behaviour: which paths get staged, whether an untracked
file is noticed at all, and whether operator config gets swept in alongside.

Coverage:
- untracked .skills/doctor.sh                → committed (the #86 case)
- modified tracked .skills/doctor.sh         → committed
- operator config (.skills/plans_dir)        → never staged
- unrelated dirty work                       → never absorbed
- nothing changed                            → no empty commit
- no .skills/doctor.sh at all                → unaffected, still exits 0
- commit message names what actually changed
- non-main branch                            → installs but does not commit
- `git status` fails                         → logged with git's own stderr,
                                               commit skipped, scratch cleaned
- `git commit` fails                         → index unstaged, install kept

Keep this list current — it is the file's index, and it undercounted for two
rounds while tests were added around it.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "managing-skills"
    / "scripts"
)
HOOK = SCRIPTS / "skills-submodule-update.sh"
DOCTOR = SCRIPTS / "doctor.sh"
INSTALLER = SCRIPTS / "install-doctor.sh"

VENDOR_REL = "skills-vendor/acme-skills/skills/managing-skills/scripts"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — pre-commit and other tooling set
    GIT_INDEX_FILE etc., which would leak into the hook's git calls."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    # The hook commits; give it an identity that doesn't depend on the
    # developer's global gitconfig being present.
    env.update(
        {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
    )
    return env


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A consumer repo on main with a vendored skills tree, one commit deep.

    `git submodule` is shimmed to a silent success: the hook's real submodule
    update needs a network remote, and none of these tests are about that.
    Every other git invocation reaches real git.
    """
    repo = tmp_path / "repo"
    (repo / VENDOR_REL).mkdir(parents=True)
    shutil.copy2(DOCTOR, repo / VENDOR_REL / "doctor.sh")
    shutil.copy2(INSTALLER, repo / VENDOR_REL / "install-doctor.sh")
    (repo / VENDOR_REL / "install-doctor.sh").chmod(0o755)
    (repo / "README.md").write_text("consumer\n")

    _git(repo.parent, "init", "-b", "main", "-q", str(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")

    _shim_dir(repo).mkdir()
    _write_git_shim(repo)
    return repo


def _shim_dir(repo: Path) -> Path:
    """Shim location derived from the repo path rather than carried on it —
    Path instances reject attribute assignment."""
    return repo.parent / "bin"


def _write_git_shim(repo: Path, extra_arms: str = "") -> None:
    """Install a fake `git` on the hook's PATH.

    `submodule` is always intercepted with a silent success — the hook's real
    submodule update needs a network remote and no test here is about that.
    `extra_arms` injects further subcommand interceptions (each a complete
    `if` statement) ahead of the delegation to real git, so a test can make a
    specific subcommand fail without restating the base shim.
    """
    real_git = shutil.which("git") or "/usr/bin/git"
    shim = _shim_dir(repo) / "git"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "submodule" ]; then exit 0; fi\n'
        f"{extra_arms}"
        f'exec {real_git} "$@"\n'
    )
    shim.chmod(0o755)


def _run_hook(repo: Path) -> subprocess.CompletedProcess:
    env = _clean_env()
    env["PATH"] = f"{_shim_dir(repo)}:{env.get('PATH', '/usr/bin:/bin')}"
    return subprocess.run(
        ["bash", str(HOOK)], cwd=repo, capture_output=True, text=True, env=env
    )


def _head_message(repo: Path) -> str:
    return _git(repo, "log", "-1", "--pretty=%s").stdout.strip()


def _commit_count(repo: Path) -> int:
    return int(_git(repo, "rev-list", "--count", "HEAD").stdout.strip())


def _tracked(repo: Path, path: str) -> bool:
    return _git(repo, "ls-files", "--error-unmatch", path, check=False).returncode == 0


class TestDoctorGetsCommitted:
    def test_untracked_doctor_is_committed(self, repo):
        """The #86 case: the hook installs the doctor, so it exists but has
        never been tracked. A `git diff HEAD` guard would not even see it."""
        assert not (repo / ".skills").exists()

        result = _run_hook(repo)

        assert result.returncode == 0, result.stderr
        assert _tracked(repo, ".skills/doctor.sh"), (
            "the hook installed the doctor but left it untracked — this is "
            "exactly the state that left 4 of 12 consumers with no doctor in CI"
        )
        assert (repo / ".skills" / "doctor.sh").read_text() == DOCTOR.read_text()

    def test_stale_tracked_doctor_is_committed(self, repo):
        skills = repo / ".skills"
        skills.mkdir()
        stale = DOCTOR.read_text().replace('VERSION="', 'VERSION="stale-', 1)
        (skills / "doctor.sh").write_text(stale)
        (skills / "doctor.sh").chmod(0o755)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "add stale doctor")
        before = _commit_count(repo)

        result = _run_hook(repo)

        assert result.returncode == 0, result.stderr
        assert _commit_count(repo) == before + 1
        assert (skills / "doctor.sh").read_text() == DOCTOR.read_text()

    def test_working_tree_is_clean_afterwards(self, repo):
        """The end-to-end property: nothing the hook touched is left dangling."""
        _run_hook(repo)

        status = _git(repo, "status", "--porcelain").stdout
        assert status == "", f"hook left the tree dirty: {status!r}"


class TestCommitScopeIsNarrow:
    """Matching diff scope to add scope is the invariant that keeps unrelated
    work out of an automated commit. Widening to `.skills/` would break it."""

    def test_operator_config_is_never_staged(self, repo):
        skills = repo / ".skills"
        skills.mkdir()
        (skills / "plans_dir").write_text("docs/notes\n")
        (skills / "worktree_root").write_text("/tmp/wt\n")

        result = _run_hook(repo)

        assert result.returncode == 0, result.stderr
        assert _tracked(repo, ".skills/doctor.sh")
        for cfg in ("plans_dir", "worktree_root"):
            assert not _tracked(repo, f".skills/{cfg}"), (
                f".skills/{cfg} is operator config — the hook must never "
                "commit it. Staging `.skills/` wholesale would."
            )
            assert (skills / cfg).exists(), "and it must be left in place"

    def test_unrelated_dirty_work_is_not_absorbed(self, repo):
        (repo / "README.md").write_text("local edit in flight\n")
        (repo / "scratch.py").write_text("untracked\n")

        _run_hook(repo)

        # Asserted via status, not via `git show HEAD` — the latter passes
        # vacuously whenever the hook makes no commit at all, which is the
        # state the pre-#86 hook was in for this fixture.
        status = _git(repo, "status", "--porcelain").stdout
        assert " M README.md" in status, (
            "the in-flight edit must still be uncommitted after the hook runs"
        )
        assert "?? scratch.py" in status, "the untracked file must stay untracked"
        assert (repo / "README.md").read_text() == "local edit in flight\n"

    def test_no_empty_commit_when_nothing_changed(self, repo):
        _run_hook(repo)
        settled = _commit_count(repo)

        # The lock MUST be cleared before the second run. The first run stamps
        # it with today's UTC date, so a second run would exit at the lock
        # check and never reach the commit block — making this assertion pass
        # no matter what the commit logic does.
        lock = repo / ".git" / "skills-update.lock"
        assert lock.exists(), "first run should have stamped the once-daily lock"
        lock.unlink()
        log_before = (repo / ".git" / "skills-update.log").read_text()

        _run_hook(repo)

        log_after = (repo / ".git" / "skills-update.log").read_text()
        assert log_after != log_before, (
            "second run must actually reach the update/commit block — if the "
            "log is unchanged it exited early and this test proves nothing"
        )
        assert _commit_count(repo) == settled, "no empty commit"
        assert "commit skills update:" not in log_after[len(log_before):], (
            "the commit block should not even have been entered on a clean tree"
        )

    def test_consumer_without_a_doctor_is_unaffected(self, repo):
        """A consumer whose vendor tree ships no installer must not error —
        `git add` on a path that isn't there would."""
        (repo / VENDOR_REL / "install-doctor.sh").unlink()
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "drop installer")
        before = _commit_count(repo)

        result = _run_hook(repo)

        assert result.returncode == 0, result.stderr
        assert not (repo / ".skills" / "doctor.sh").exists()
        assert _commit_count(repo) == before


class TestStatusFailureIsDiagnosable:
    """The status check drives the commit branch. A git that fails for an
    unexpected reason must not read as "nothing to commit" — that would
    silently stop this hook committing forever with no trace anywhere."""

    def test_failure_is_logged_and_skipped(self, repo):
        _write_git_shim(
            repo,
            extra_arms=(
                'if [ "$1" = "status" ]; then '
                'echo "fatal: simulated index corruption" >&2; exit 128; fi\n'
            ),
        )
        before = _commit_count(repo)

        result = _run_hook(repo)

        assert result.returncode == 0, "the hook must never block a session"
        log = (repo / ".git" / "skills-update.log").read_text()
        assert "git status failed (rc=128)" in log
        assert "simulated index corruption" in log, (
            "git's own stderr must reach the log — the rc alone doesn't say why"
        )
        assert _commit_count(repo) == before, "must skip the commit, not guess"
        assert not (repo / ".git" / "skills-status.err").exists(), (
            "the stderr scratch file must be cleaned up"
        )


class TestFailedCommitLeavesNoResidue:
    """`git add` may stage a previously untracked .skills/doctor.sh. Leaving a
    file the operator never touched sitting in their index is worse than
    leaving the commit undone — the next run retries cleanly either way."""

    def test_failed_commit_unstages(self, repo):
        _write_git_shim(
            repo,
            extra_arms=(
                'if [ "$1" = "commit" ]; then '
                'echo "shim: commit refused" >&2; exit 1; fi\n'
            ),
        )

        result = _run_hook(repo)

        assert result.returncode == 0, "the hook must never block a session"
        staged = _git(repo, "diff", "--cached", "--name-only").stdout
        assert staged == "", f"index left dirty after a failed commit: {staged!r}"
        assert (repo / ".skills" / "doctor.sh").exists(), (
            "the working-tree install must survive — only the staging is undone"
        )


class TestCommitMessageNamesWhatChanged:
    def test_doctor_only_refresh(self, repo):
        """Nothing moved in skills-vendor/ (submodule is shimmed), so the
        message must not claim a submodule update."""
        _run_hook(repo)

        assert _head_message(repo) == "chore: refresh .skills/doctor.sh", (
            f"got {_head_message(repo)!r}"
        )

    def test_both_changed(self, repo):
        """Simulate a pointer bump landing alongside the doctor install by
        dirtying a tracked file under skills-vendor/."""
        (repo / VENDOR_REL / "doctor.sh").write_text(
            DOCTOR.read_text() + "\n# vendor moved\n"
        )

        _run_hook(repo)

        assert _head_message(repo) == (
            "chore: update skills submodules and refresh .skills/doctor.sh"
        ), f"got {_head_message(repo)!r}"

    def test_submodule_only(self, repo):
        skills = repo / ".skills"
        skills.mkdir()
        shutil.copy2(DOCTOR, skills / "doctor.sh")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "doctor already current")
        (repo / VENDOR_REL / "install-doctor.sh").write_text(
            INSTALLER.read_text() + "\n# vendor moved\n"
        )

        _run_hook(repo)

        assert _head_message(repo) == "chore: update skills submodules", (
            f"got {_head_message(repo)!r}"
        )


class TestBranchGating:
    def test_feature_branch_installs_but_does_not_commit(self, repo):
        """The install is the working-tree repair and runs everywhere; the
        commit is main-only, as it was before #86."""
        _git(repo, "checkout", "-qb", "feature/x")
        before = _commit_count(repo)

        result = _run_hook(repo)

        assert result.returncode == 0, result.stderr
        assert (repo / ".skills" / "doctor.sh").exists(), (
            "the working-tree install must still happen off main"
        )
        assert _commit_count(repo) == before, "no auto-commit off main"
        assert not _tracked(repo, ".skills/doctor.sh")
