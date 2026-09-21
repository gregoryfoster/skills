"""When the auto-refresh hook installs `.skills/doctor.sh`, and from which vendor.

Two defects in one loop, found together in CannObserv/observo, whose committed
doctor was ten days stale and had never self-healed — missing `check_unpushed()`
entirely, so the "main is ahead of its upstream" sensor did not exist there.

- **#299 — the install ran only BEFORE the submodule update.** On the session
  that advances the pointer, the installer copied the doctor out of the
  PRE-bump vendor tree, and the commit step recorded that old doctor beside
  the new pointer. Every bump carried a guaranteed one-session lag, and a
  consumer whose sessions mostly run elsewhere never closed it. The loop now
  also runs after a successful update, ahead of the commit, so the doctor
  committed with a bump is the one that bump ships.
- **#300 — the loop broke after the first installer whether or not it
  succeeded.** The `skills-vendor/*` glob exists to span every vendored repo,
  so a second one shipping `managing-skills` is the fallback when the first
  fails; the unconditional `break` meant it was never tried, and the failure
  reached only `$LOG`. Now the first installer that SUCCEEDS wins, and every
  one failing reaches stderr — the channel every other failure in the hook
  uses — once per run, although the install is called twice.

The #299 cases run the real `git submodule update` against a throwaway
upstream over the `file` transport, because the defect is an ordering between
that update and the install — a shimmed submodule call cannot move a vendor
tree, so it cannot show which doctor the installer saw. The #300 cases shim
`git submodule` away like the hook's other tests: they are about which
installer runs, not about what the update does.

Coverage:
- a bump commits the post-bump doctor, whether the doctor was already
  tracked or first installed in that same session          (#299)
- a failing first installer falls through to the next vendor (#300)
- the fall-through is logged, naming the installer that failed
- every installer failing is logged and reaches stderr
- ...once per run, though both call sites fail
- a succeeding first installer still ends the search — one doctor wins

Keep this list current — it is the file's index.
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

MS_SCRIPTS = "skills/managing-skills/scripts"

# `git submodule` refuses the `file` transport by default since git 2.38
# (CVE-2022-39253); the throwaway upstream below needs it, for the fixture's
# own git calls and for the hook's.
FILE_TRANSPORT = {"GIT_ALLOW_PROTOCOL": "file"}

NO_INSTALL = "could not install .skills/doctor.sh"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — `GIT_DIR` outranks `git -C` and the
    cwd, and git exports it to every hook, so an unscrubbed fixture would
    address the real repository (docs/STYLE.md). An identity is supplied
    because the hook commits."""
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


def _git(repo: Path, *args: str, env_extra: dict | None = None) -> str:
    env = _clean_env()
    env.update(env_extra or {})
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    ).stdout


def _run_hook(repo: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = _clean_env()
    shims = repo.parent / "bin"
    if shims.is_dir():
        env["PATH"] = f"{shims}:{env.get('PATH', '/usr/bin:/bin')}"
    env.update(env_extra or {})
    result = subprocess.run(
        ["bash", str(HOOK)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, f"the hook must never block: {result.stderr}"
    return result


def _log(repo: Path) -> str:
    log = repo / ".git" / "skills-update.log"
    return log.read_text() if log.exists() else ""


def _doctor_text(stamp: str) -> str:
    """A real doctor under a distinguishable VERSION stamp. It keeps the
    `managing-skills-doctor:` marker, or install-doctor.sh would refuse to
    overwrite it — a different test."""
    text = DOCTOR.read_text()
    stamped = text.replace('VERSION="', f'VERSION="{stamp}-', 1)
    assert stamped != text, "VERSION assignment not found in doctor.sh"
    return stamped


# ------------------------------------------------------------------- #299


@pytest.fixture
def bumped(tmp_path: Path):
    """A consumer recording its vendor one commit behind an upstream whose
    newer commit ships a different doctor — the state every pointer bump is.

    The consumer's own doctor is written by each test, since #299 has two
    shapes: tracked already (observo's), or first installed in the very
    session that bumps.
    """
    from types import SimpleNamespace

    up = tmp_path / "up"
    scripts = up / MS_SCRIPTS
    scripts.mkdir(parents=True)
    old, new = _doctor_text("pre-bump"), _doctor_text("post-bump")
    (scripts / "doctor.sh").write_text(old)
    shutil.copy2(INSTALLER, scripts / "install-doctor.sh")
    (scripts / "install-doctor.sh").chmod(0o755)
    _git(tmp_path, "init", "-q", "-b", "main", str(up))
    _git(up, "add", "-A")
    _git(up, "commit", "-qm", "vendor at the recorded pointer")

    repo = tmp_path / "repo"
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    (repo / "README.md").write_text("consumer\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    _git(
        repo,
        "submodule",
        "add",
        "-q",
        str(up),
        "skills-vendor/acme-skills",
        env_extra=FILE_TRANSPORT,
    )
    _git(repo, "commit", "-qm", "vendor")

    (scripts / "doctor.sh").write_text(new)
    _git(up, "commit", "-qam", "the vendor ships a newer doctor")
    return SimpleNamespace(path=repo, old=old, new=new)


def _committed(repo: Path, path: str) -> str:
    return _git(repo, "show", f"HEAD:{path}")


class TestABumpCommitsThePostBumpDoctor:
    def test_a_tracked_doctor_is_committed_at_the_bumped_version(self, bumped):
        """observo's shape. The doctor is tracked and current for the old
        pointer, so the pre-update install is a no-op; before #299 the run
        committed the pointer alone and left the doctor a version behind it."""
        doctor = bumped.path / ".skills" / "doctor.sh"
        doctor.parent.mkdir()
        doctor.write_text(bumped.old)
        doctor.chmod(0o755)
        _git(bumped.path, "add", "-A")
        _git(bumped.path, "commit", "-qm", "doctor for the recorded pointer")

        _run_hook(bumped.path, env_extra=FILE_TRANSPORT)

        assert _committed(bumped.path, ".skills/doctor.sh") == bumped.new, (
            "the run that advanced the pointer committed a doctor from BEFORE "
            f"the advance (#299):\n{_log(bumped.path)}"
        )
        subject = _git(bumped.path, "log", "-1", "--format=%s").strip()
        assert subject == (
            "chore: update skills submodules and refresh .skills/doctor.sh"
        ), f"one commit records both, and says so: {subject!r}"

    def test_a_first_install_in_the_bumping_session_is_the_bumped_doctor(self, bumped):
        """No doctor yet: call site 1 installs the pre-bump one, the update
        moves the vendor, and the commit must still record the post-bump one —
        a first install is not exempt from the lag."""
        _run_hook(bumped.path, env_extra=FILE_TRANSPORT)

        assert _committed(bumped.path, ".skills/doctor.sh") == bumped.new, (
            f"the first committed doctor predates the pointer:\n{_log(bumped.path)}"
        )
        assert (bumped.path / ".skills" / "doctor.sh").read_text() == bumped.new


# ------------------------------------------------------------------- #300


def _vendor(repo: Path, name: str, installer_body: str | None = None) -> Path:
    """A vendored managing-skills tree. With no `installer_body` it carries the
    real installer and doctor; with one, that body replaces the installer."""
    scripts = repo / "skills-vendor" / name / MS_SCRIPTS
    scripts.mkdir(parents=True)
    shutil.copy2(DOCTOR, scripts / "doctor.sh")
    installer = scripts / "install-doctor.sh"
    if installer_body is None:
        shutil.copy2(INSTALLER, installer)
    else:
        installer.write_text(installer_body)
    installer.chmod(0o755)
    return installer


FAILING = '#!/usr/bin/env bash\necho "install-doctor: simulated failure" >&2\nexit 1\n'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A consumer on main whose vendors each test adds. `git submodule` is
    shimmed to a silent success: these tests are about which installer runs,
    and the update needs a network remote."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("consumer\n")
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    _shim_submodule(repo, "exit 0")
    return repo


def _shim_submodule(repo: Path, body: str) -> None:
    shims = repo.parent / "bin"
    shims.mkdir(exist_ok=True)
    real_git = shutil.which("git") or "/usr/bin/git"
    shim = shims / "git"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$1" = "submodule" ]; then\n{body}\nfi\n'
        f'exec {real_git} "$@"\n'
    )
    shim.chmod(0o755)


class TestTheFirstInstallerThatSucceedsWins:
    def test_a_failing_first_installer_falls_through_to_the_next(self, repo):
        """The #300 case. `aaa-` sorts first in the glob and fails; before
        the fix the loop broke there and no doctor was installed at all."""
        _vendor(repo, "aaa-broken", FAILING)
        _vendor(repo, "zzz-skills")

        _run_hook(repo)

        installed = repo / ".skills" / "doctor.sh"
        assert installed.exists(), (
            "the second vendor's installer was never tried — the loop stopped "
            f"at the first one, which failed:\n{_log(repo)}"
        )
        assert installed.read_text() == DOCTOR.read_text()

    def test_the_fall_through_is_logged(self, repo):
        """Which installer failed, and that the search went on — the log line
        that tells an operator why the doctor came from the second vendor."""
        _vendor(repo, "aaa-broken", FAILING)
        _vendor(repo, "zzz-skills")

        _run_hook(repo)

        log = _log(repo)
        assert "aaa-broken" in log and "trying the next vendor" in log, log
        assert "simulated failure" in log, (
            f"the installer's own stderr must reach the log:\n{log}"
        )

    def test_every_installer_failing_reaches_stderr(self, repo):
        """A stale doctor with nothing said is how observo sat for ten days.
        $LOG is a file nobody reads until something has already gone wrong."""
        _vendor(repo, "aaa-broken", FAILING)
        _vendor(repo, "zzz-broken", FAILING)

        result = _run_hook(repo)

        assert NO_INSTALL in result.stderr, (
            f"every installer failed and the session was told nothing:\n{result.stderr}"
        )
        assert "all 2 vendored installer(s) failed" in _log(repo), _log(repo)
        assert not (repo / ".skills" / "doctor.sh").exists()

    def test_the_failure_is_reported_once_per_run(self, repo):
        """Both call sites run here — the refresh succeeds, so call site 2
        does too — and both fail. The second would only repeat the first's
        news, so stderr carries one line while the log records both."""
        _vendor(repo, "aaa-broken", FAILING)
        (repo / ".gitmodules").write_text(
            '[submodule "aaa-broken"]\n'
            "\tpath = skills-vendor/aaa-broken\n"
            "\turl = https://example.invalid/aaa-broken.git\n"
        )
        # Initialized (' ' prefix), so the refresh reads as a success and the
        # hook reaches the post-update install.
        _shim_submodule(
            repo,
            'if [ "$2" = "status" ]; then\n'
            "  echo ' 1111111111111111111111111111111111111111 "
            "skills-vendor/aaa-broken'\n"
            "fi\n"
            "exit 0",
        )

        result = _run_hook(repo)

        assert _log(repo).count("vendored installer(s) failed") == 2, (
            "the post-update install did not run — this test would then prove "
            f"nothing about the dedupe:\n{_log(repo)}"
        )
        assert result.stderr.count(NO_INSTALL) == 1, result.stderr

    def test_a_succeeding_first_installer_ends_the_search(self, repo):
        """One doctor wins. Falling through on failure must not become
        running every vendor's installer, each overwriting the last."""
        _vendor(repo, "aaa-skills")
        marker = repo.parent / "second-installer-ran"
        _vendor(
            repo,
            "zzz-skills",
            f'#!/usr/bin/env bash\ntouch "{marker}"\nexit 0\n',
        )

        _run_hook(repo)

        assert (repo / ".skills" / "doctor.sh").exists()
        assert not marker.exists(), "a second installer ran after the first succeeded"
