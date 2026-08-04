"""Behavioral tests for doctor.sh self-sync from the vendored source (#84).

`.skills/doctor.sh` is a real file copy, not a symlink, so it stays reachable
when the vendor submodule is uninitialized — the state it exists to repair.
The cost is drift: upstream fixes only land when something re-runs
install-doctor.sh. `sync_self` closes that gap by re-syncing on every doctor
run, which for a hook-less consumer is the reviewing-*/shipping-* preflight.

Exercised end-to-end against throwaway git repos, because the properties that
matter are runtime ones (does it fire on the healthy fast path, does it stay
non-fatal, does the running instance survive being overwritten).

Coverage:
- stale installed copy on the healthy path        → synced, exit 0
- installed copy identical to vendor              → no-op, no message
- no skills-vendor/ at all                        → no-op, exit unaffected
- installer present but failing                   → exit unaffected, no message
- destination is a user file (no doctor marker)   → left alone, exit unaffected
- vendor only readable after submodule init       → synced at call site 2
- install-doctor.sh replaces by rename, not truncate (the running-script case)
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
DOCTOR = SCRIPTS / "doctor.sh"
INSTALLER = SCRIPTS / "install-doctor.sh"

VENDOR_REL = "skills-vendor/acme-skills/skills/managing-skills/scripts"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — same precaution as
    test_doctor_ssh_remediation. Pre-commit and other tooling can set
    GIT_INDEX_FILE etc., which would leak into git calls inside the script."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _stale_doctor_text() -> str:
    """The current doctor with a different VERSION stamp.

    It must differ from the vendored copy (so sync_self has something to do)
    while still *being* a current doctor — the installed copy is what actually
    runs, so a genuinely old doctor would have no sync_self to test. It must
    also keep the `managing-skills-doctor:` marker or install-doctor.sh would
    refuse to overwrite it, which is a different test.

    The padding is load-bearing: it sits above sync_self, so every byte offset
    below the sync point shifts by ~2 KiB between the two files. Bash reads a
    script incrementally from an open fd, so if install-doctor.sh ever went
    back to a truncating in-place write, the running instance would resume
    mid-token and these tests would fail loudly instead of subtly.
    """
    text = DOCTOR.read_text()
    padding = "".join(f"# stale-copy padding line {i}\n" for i in range(96))
    stale = text.replace('VERSION="', padding + 'VERSION="stale-', 1)
    assert stale != text, "VERSION assignment not found in doctor.sh"
    assert len(stale) - len(text) > 2000, "padding must meaningfully shift offsets"
    return stale


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=path,
        check=True,
        capture_output=True,
        env=_clean_env(),
    )


def _install_vendor(repo: Path, installer_body: str | None = None) -> Path:
    """Populate the vendor tree with a pristine doctor + installer. When
    `installer_body` is given it replaces install-doctor.sh, for failure
    injection."""
    vendor = repo / VENDOR_REL
    vendor.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DOCTOR, vendor / "doctor.sh")
    if installer_body is None:
        shutil.copy2(INSTALLER, vendor / "install-doctor.sh")
    else:
        (vendor / "install-doctor.sh").write_text(installer_body)
    (vendor / "install-doctor.sh").chmod(0o755)
    return vendor


def _install_doctor_copy(repo: Path, text: str) -> Path:
    dest = repo / ".skills" / "doctor.sh"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)
    dest.chmod(0o755)
    return dest


@pytest.fixture
def healthy_repo(tmp_path: Path) -> Path:
    """Repo with a skills/ directory and no dangling symlinks, so the doctor
    takes the early-exit fast path — the case sync_self exists to cover."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "skills").mkdir()
    return repo


def _run_installed_doctor(repo: Path, extra_path: Path | None = None):
    """Run the repo's own .skills/doctor.sh, the way a preflight does."""
    env = _clean_env()
    if extra_path is not None:
        env["PATH"] = f"{extra_path}:{env.get('PATH', '/usr/bin:/bin')}"
    return subprocess.run(
        ["bash", ".skills/doctor.sh"],
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
    )


class TestSelfSyncHealthyPath:
    def test_stale_copy_is_synced(self, healthy_repo):
        _install_vendor(healthy_repo)
        dest = _install_doctor_copy(healthy_repo, _stale_doctor_text())

        result = _run_installed_doctor(healthy_repo)

        assert result.returncode == 0, result.stderr
        assert dest.read_text() == DOCTOR.read_text()
        assert "refreshed .skills/doctor.sh" in result.stderr

    def test_synced_copy_stays_executable(self, healthy_repo):
        _install_vendor(healthy_repo)
        dest = _install_doctor_copy(healthy_repo, _stale_doctor_text())

        _run_installed_doctor(healthy_repo)

        assert os.access(dest, os.X_OK), (
            "a synced doctor must stay executable — the preflight guard is "
            "`[ -x .skills/doctor.sh ]`, so losing the bit silently disables it"
        )

    def test_identical_copy_is_a_silent_noop(self, healthy_repo):
        _install_vendor(healthy_repo)
        dest = _install_doctor_copy(healthy_repo, DOCTOR.read_text())
        before = dest.stat().st_ino

        result = _run_installed_doctor(healthy_repo)

        assert result.returncode == 0, result.stderr
        assert "refreshed" not in result.stderr
        assert dest.stat().st_ino == before, "no-op must not rewrite the file"


class TestSelfSyncIsNonFatal:
    """Preflights invoke the doctor with `|| exit 1`. No self-sync failure may
    change the exit code — that would block a review over a cosmetic concern."""

    def test_missing_vendor_is_a_noop(self, healthy_repo):
        stale = _stale_doctor_text()
        dest = _install_doctor_copy(healthy_repo, stale)

        result = _run_installed_doctor(healthy_repo)

        assert result.returncode == 0, result.stderr
        assert dest.read_text() == stale
        assert "refreshed" not in result.stderr

    def test_failing_installer_does_not_change_exit_code(self, healthy_repo):
        _install_vendor(
            healthy_repo, installer_body="#!/usr/bin/env bash\nexit 1\n"
        )
        stale = _stale_doctor_text()
        dest = _install_doctor_copy(healthy_repo, stale)

        result = _run_installed_doctor(healthy_repo)

        assert result.returncode == 0, result.stderr
        assert dest.read_text() == stale
        assert "refreshed" not in result.stderr, (
            "success message must be gated on the installer actually succeeding"
        )

    def test_absent_installer_does_not_change_exit_code(self, healthy_repo):
        vendor = _install_vendor(healthy_repo)
        (vendor / "install-doctor.sh").unlink()
        _install_doctor_copy(healthy_repo, _stale_doctor_text())

        result = _run_installed_doctor(healthy_repo)

        assert result.returncode == 0, result.stderr

    def test_user_file_at_destination_is_left_alone(self, healthy_repo):
        """install-doctor.sh's no-clobber guard still holds under sync_self:
        a file without the doctor marker is refused, and the refusal is
        swallowed rather than surfacing as a doctor failure."""
        _install_vendor(healthy_repo)
        body = "#!/usr/bin/env bash\necho mine\n"
        dest = _install_doctor_copy(healthy_repo, body)

        result = _run_installed_doctor(healthy_repo)

        assert result.returncode == 0, result.stderr
        assert dest.read_text() == body
        assert "refreshed" not in result.stderr


class TestSelfSyncAfterHeal:
    """Call site 2: when the vendor only becomes readable after submodule
    init, the first sync_self found nothing and the second must catch it."""

    def test_syncs_once_submodule_init_exposes_the_vendor(self, tmp_path: Path):
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "skills").mkdir()
        # Dangling until the shimmed `git submodule update` materializes it.
        os.symlink("../skills-vendor/acme-skills/skills/foo", repo / "skills" / "foo")
        stale = _stale_doctor_text()
        dest = _install_doctor_copy(repo, stale)

        # Fake git: `submodule update` creates the vendor tree and the symlink
        # target, mimicking a real init. Everything else delegates to real git
        # so rev-parse --show-toplevel still works.
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        real_git = shutil.which("git") or "/usr/bin/git"
        vendor_scripts = repo / VENDOR_REL
        (bin_dir / "git").write_text(
            "#!/usr/bin/env bash\n"
            'if [ "$1" = "submodule" ]; then\n'
            f'  mkdir -p "{vendor_scripts}" "{repo}/skills-vendor/acme-skills/skills/foo"\n'
            f'  cp "{DOCTOR}" "{vendor_scripts}/doctor.sh"\n'
            f'  cp "{INSTALLER}" "{vendor_scripts}/install-doctor.sh"\n'
            f'  chmod 755 "{vendor_scripts}/install-doctor.sh"\n'
            "  exit 0\n"
            "fi\n"
            f'exec {real_git} "$@"\n'
        )
        (bin_dir / "git").chmod(0o755)

        result = _run_installed_doctor(repo, extra_path=bin_dir)

        assert result.returncode == 0, result.stderr
        assert dest.read_text() == DOCTOR.read_text(), (
            "sync_self after a successful init must pick up the vendor tree "
            "that only just became readable"
        )


class TestInstallerReplacesByRename:
    """The doctor rewrites itself while executing. A truncating in-place write
    would make the running bash resume at a byte offset into new content."""

    def test_destination_inode_changes(self, tmp_path: Path):
        repo = tmp_path / "repo"
        _init_repo(repo)
        vendor = _install_vendor(repo)
        dest = _install_doctor_copy(repo, _stale_doctor_text())
        before = dest.stat().st_ino

        result = subprocess.run(
            ["bash", str(vendor / "install-doctor.sh")],
            capture_output=True,
            text=True,
            cwd=repo,
            env=_clean_env(),
        )

        assert result.returncode == 0, result.stderr
        assert dest.stat().st_ino != before, (
            "install-doctor.sh must replace the destination by rename, not "
            "rewrite it in place — the running doctor holds an fd on the old "
            "inode and must be able to read it to completion"
        )
        assert dest.read_text() == DOCTOR.read_text()

    def test_no_temp_file_left_behind(self, tmp_path: Path):
        repo = tmp_path / "repo"
        _init_repo(repo)
        vendor = _install_vendor(repo)
        _install_doctor_copy(repo, _stale_doctor_text())

        subprocess.run(
            ["bash", str(vendor / "install-doctor.sh")],
            check=True,
            capture_output=True,
            text=True,
            cwd=repo,
            env=_clean_env(),
        )

        leftovers = sorted(p.name for p in (repo / ".skills").glob(".doctor.sh.tmp.*"))
        assert leftovers == [], f"temp files not cleaned up: {leftovers}"
