"""Behavioral tests for the submodule hook's once-per-day lock stamp (#193).

`skills-submodule-update.sh` runs at most once per UTC day, and the entire
contract rests on one write: `date -u +%Y%m%d > "$LOCK"`. That write carried
`|| true`. A read-only or root-owned `.git`, or a full disk, and the lock is
never stamped, the guard reads a stale or absent lock at the next session, and
the hook runs the whole submodule refresh again — every session, silently. A
once-per-day hook becomes an every-session one with nothing to say why.

This is the defect #187 fixed in `socraticode-health.sh`, which the submodule
hook's own comment names as its twin. The fix is that script's shape: checked,
logged, warned on stderr, and never fatal — a SessionStart hook must not block
a session, so a failed stamp degrades to noisier reporting rather than to no
session.

The unwritable lock is produced by putting a *directory* at `$LOCK`. That is
the honest reproduction for these tests: it needs no chmod games, it survives
running as root (which a permission-bit fixture does not), and `[ -f "$LOCK" ]`
is false for it, so the day-guard falls through exactly as it does when the
lock is simply absent.

Coverage:
- unwritable lock  → warned on stderr, logged, exit 0, refresh still runs
- writable lock    → stamped with today's UTC day, and silent about it
- second run       → the stamp actually gates, so nothing runs twice
"""

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "managing-skills"
    / "scripts"
)
HOOK = SCRIPTS / "skills-submodule-update.sh"

VENDOR_REL = "skills-vendor/acme-skills/skills/managing-skills/scripts"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars.

    `GIT_DIR` outranks both `git -C` and the process cwd, and git exports it to
    every hook process — so under pre-commit a fixture that did not scrub it
    would address the real repository (docs/STYLE.md, "A repo-creating git
    command must scrub `GIT_DIR`"). An identity is supplied because the hook
    commits and must not depend on a developer's global gitconfig.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
    )
    return env


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A consumer repo on main with a skills-vendor/ tree, one commit deep.

    `git submodule` is shimmed to a silent success — the hook's real update
    wants a remote, and nothing here is about what it fetches. Every other git
    call reaches real git.
    """
    repo = tmp_path / "repo"
    (repo / VENDOR_REL).mkdir(parents=True)
    (repo / "README.md").write_text("consumer\n")

    _git(repo.parent, "init", "-b", "main", "-q", str(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")

    bindir = tmp_path / "bin"
    bindir.mkdir()
    real_git = shutil.which("git") or "/usr/bin/git"
    shim = bindir / "git"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "submodule" ]; then exit 0; fi\n'
        f'exec {real_git} "$@"\n'
    )
    shim.chmod(0o755)
    return repo


def _run_hook(repo: Path) -> subprocess.CompletedProcess:
    env = _clean_env()
    env["PATH"] = f"{repo.parent / 'bin'}:{env.get('PATH', '/usr/bin:/bin')}"
    return subprocess.run(
        ["bash", str(HOOK)], cwd=repo, capture_output=True, text=True, env=env
    )


def _lock(repo: Path) -> Path:
    return repo / ".git" / "skills-update.lock"


def _log_text(repo: Path) -> str:
    log = repo / ".git" / "skills-update.log"
    return log.read_text() if log.exists() else ""


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


class TestUnwritableLock:
    def test_it_is_reported_on_stderr(self, repo):
        _lock(repo).mkdir()
        r = _run_hook(repo)
        assert "skills-update.lock" in r.stderr, r.stderr
        assert "every session" in r.stderr, r.stderr

    def test_it_is_recorded_in_the_log(self, repo):
        _lock(repo).mkdir()
        _run_hook(repo)
        assert "could not stamp" in _log_text(repo), _log_text(repo)

    def test_it_never_blocks_the_session(self, repo):
        """A SessionStart hook that exits non-zero costs the operator a
        session. A failed stamp must cost them a warning instead."""
        _lock(repo).mkdir()
        assert _run_hook(repo).returncode == 0

    def test_the_hook_proceeds_past_the_failed_stamp(self, repo):
        """Degrade to noisier reporting, not to no work. The stamp sits ahead
        of the update deliberately, so a failed one must not swallow the run
        it was gating — the hook goes on and reaches its update stage."""
        _lock(repo).mkdir()
        _run_hook(repo)
        assert "submodule update did nothing" in _log_text(repo), _log_text(repo)


class TestWritableLock:
    def test_it_is_stamped_with_todays_utc_day(self, repo):
        _run_hook(repo)
        assert _lock(repo).read_text().strip() == _today()

    def test_the_success_path_says_nothing(self, repo):
        """The warning has to stay rare enough to be worth reading."""
        r = _run_hook(repo)
        assert "skills-update.lock" not in r.stderr, r.stderr

    def test_the_stamp_actually_gates_the_next_run(self, repo):
        """The point of checking the write: a stamp that landed must stop the
        second same-day run before it does the work again."""
        _run_hook(repo)
        first = _log_text(repo)
        _run_hook(repo)
        assert _log_text(repo) == first
