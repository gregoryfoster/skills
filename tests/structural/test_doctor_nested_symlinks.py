"""#238 — scan_broken() covers nested `skills/*/scripts/*` symlinks.

The per-script symlink pattern is the best available shape for a local
override — real files only for what actually differs, symlinks into the
submodule for the rest, so five of six scripts in the consumer that motivated
#238 never drifted. But promoting it without deepening the scan widens a blind
spot: `scan_broken()` walked one level (`for entry in "$dir"/*`), and
per-script symlinks live at `skills/<override>/scripts/*.sh` — two levels
down, below that glob.

Scoping the blind spot honestly, because it is narrower than it first sounds:
the fresh-clone case was always covered — `scan_uninit()` catches an
uninitialized submodule through `git submodule status`, independent of any
symlink. The uncovered case is an initialized, healthy submodule where
upstream RENAMES OR DELETES a script. Every top-level symlink resolves,
`scan_uninit` reports nothing, and the dangling nested symlink is invisible
until it surfaces as `No such file or directory` mid-run — the exact failure
mode the doctor exists to turn into an actionable message. That is the new
risk the per-script pattern introduces, which is why #238's amendment makes
this scan a PREREQUISITE of recommending the pattern, not a follow-up.

What this file pins:

- **A dangling nested symlink is damage**: named, and non-zero in both modes —
  `--check-only` reports it, the default mode reports it as unrepaired after
  the heal attempt.
- **A resolving nested symlink is silent**, and a regular nested file (the
  #105 wrapper, the override's own real scripts) is not scanned at all — it
  is not a symlink, and nagging the healthy shape trains skimming.
- **The scan does not dive through top-level symlinked skills.** A symlinked
  skill IS the healthy vendor chain; its target's internals belong upstream.

Keep this list current — it is the file's index.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCTOR = REPO_ROOT / "skills" / "managing-skills" / "scripts" / "doctor.sh"

VENDOR_SCRIPTS = "skills-vendor/acme-skills/skills/shipping-work/scripts"


def _clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=60,
    )


def _doctor(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(DOCTOR), "--no-preflight", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=120,
    )


@pytest.fixture
def consumer(tmp_path: Path) -> Path:
    """The #238 override shape: a regular directory whose scripts/ mixes one
    real file (the #105 wrapper) with per-script symlinks into the vendor."""
    repo = tmp_path / "consumer"
    vendor = repo / VENDOR_SCRIPTS
    vendor.mkdir(parents=True)
    (vendor / "check-status.sh").write_text("#!/usr/bin/env bash\nexit 0\n")

    scripts = repo / "skills" / "shipping-work" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "pre-ship.sh").write_text(
        "#!/usr/bin/env bash\nexec bash ../vendor/pre-ship.sh\n"
    )
    (scripts / "check-status.sh").symlink_to(
        f"../../../{VENDOR_SCRIPTS}/check-status.sh"
    )
    _git(repo, "init", "-q", "-b", "main")
    return repo


class TestDanglingNestedSymlinksAreDamage:
    def test_check_only_reports_and_fails_on_a_dangling_nested_symlink(
        self, consumer: Path
    ):
        """Upstream deletes (or renames) a script: the top-level chain is
        healthy, scan_uninit has nothing to say, and only this scan stands
        between the operator and a mid-ship `No such file or directory`."""
        (consumer / VENDOR_SCRIPTS / "check-status.sh").unlink()
        result = _doctor(consumer, "--check-only")
        assert result.returncode == 1, result.stdout + result.stderr
        assert "skills/shipping-work/scripts/check-status.sh" in result.stderr, (
            "the doctor must name the broken nested symlink; a report that "
            f"does not identify the file is not actionable.\n{result.stderr}"
        )

    def test_the_default_mode_reports_it_unrepaired_after_the_heal(
        self, consumer: Path
    ):
        """No submodule can restore a script upstream deleted, so the heal
        runs, changes nothing, and the doctor must say the repair did not
        take rather than exit 0 over a residue it just re-scanned."""
        (consumer / VENDOR_SCRIPTS / "check-status.sh").unlink()
        result = _doctor(consumer)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "skills/shipping-work/scripts/check-status.sh" in result.stderr, (
            result.stderr
        )


class TestHealthyNestedShapesAreSilent:
    def test_a_resolving_nested_symlink_is_silent(self, consumer: Path):
        result = _doctor(consumer, "--check-only")
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr.strip() == "", result.stderr

    def test_a_regular_nested_script_is_not_scanned(self, consumer: Path):
        """The #105 wrapper is a real file and stays one — it is the part of
        the override that is genuinely local."""
        (consumer / "skills" / "shipping-work" / "scripts" / "check-status.sh").unlink()
        result = _doctor(consumer, "--check-only")
        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_scan_does_not_dive_through_a_symlinked_skill(self, consumer: Path):
        """A top-level symlinked skill is the healthy vendor chain; whatever
        its target holds internally is upstream's business, and reporting a
        vendor-internal path as consumer damage hands the operator a repair
        for a file they do not own. The dangling TOP-LEVEL link is still the
        symlink scan's to report, exactly as before."""
        (consumer / "skills" / "reviewing-code").symlink_to(
            "../skills-vendor/acme-skills/skills/reviewing-code"
        )
        result = _doctor(consumer, "--check-only")
        assert result.returncode == 1, result.stdout + result.stderr
        assert "skills/reviewing-code" in result.stderr, result.stderr
        assert "reviewing-code/scripts" not in result.stderr, result.stderr
