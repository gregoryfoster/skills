"""#238 — the doctor warns when a local override has drifted behind its vendor.

A local override is the one file the drift mitigations cannot reach. #105's
wrapper recipe stopped the scripts forking; per-script symlinks track upstream
for free; the auto-refresh hook moves the submodule pointer. `SKILL.md` itself
is a real file by construction, and it sat at v1.2 in a consumer while vendor
reached v1.4 — reintroducing #63's exact failure sixteen months after it was
closed, because the file carrying the fix was the fork. Nothing detected it:
the doctor deliberately walks symlinks and skips overrides, the refresh hook
never touches forked files, and the skill documented no re-sync procedure.

The frontmatter already carries the machine-readable link, from
managing-skills' own override recipe: `overrides:` names the vendor path and
`version:` sits beside it. The semantics of `version:` in an override are the
load-bearing part and are pinned here: it records **the vendor version last
synced from**, not a version of the local file — bumped on every re-sync even
when the local deltas are unchanged. The two readings diverge the moment
someone edits an override after syncing, which is an override's whole job.

What this file pins:

- **Drift is warned about, with both versions named.** The data sat unused;
  comparing it is a grep and a string compare.
- **The warning teaches the direction AND the check.** Reapplying upstream
  onto the old fork is the easy inversion; verifying the merge by presence is
  the easy false pass (#267), and neither is visible from the fact of drift.
- **Warn only, in every mode.** Never auto-merge — the whole point of an
  override is that upstream text cannot be applied blindly — and never a
  non-zero exit, including under `--check-only`: drift is doc-sync debt, not
  the damage or wiring gap that mode gates on (#231).
- **Unversioned upstreams are never silently skipped.** A vendor that ships no
  `version:` falls back to the override's `synced-from:` sibling key, which
  pins the vendor commit last synced from; the vendor tree is then compared
  path-scoped between that commit and HEAD. An override that cannot be
  compared at all is warned about too — silence there is the same failure as
  not detecting at all.
- **Who is NOT warned about.** A symlinked skill tracks upstream by
  construction, and a local directory without `overrides:` is a
  project-authored skill, not a fork of anything.

Keep this list current — it is the file's index.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCTOR = REPO_ROOT / "skills" / "managing-skills" / "scripts" / "doctor.sh"

VENDOR_REPO = "acme-skills"
DRIFT_MARKER = "has fallen behind"
UNASSESSED_MARKER = "cannot be assessed"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — a linked worktree shares .git/config
    with its main checkout, so a fixture-creating git command that inherits
    them reaches out of the fixture and writes the wrong repo (#189)."""
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


def _skill_md(
    name: str,
    version: str | None = None,
    overrides: str | None = None,
    synced_from: str | None = None,
) -> str:
    meta = ["  author: t"]
    if version is not None:
        meta.append(f'  version: "{version}"')
    if overrides is not None:
        meta.append(f"  overrides: {overrides}")
        meta.append('  override-reason: "sources /etc/consumer/.env"')
    if synced_from is not None:
        meta.append(f'  synced-from: "{synced_from}"')
    return (
        "---\n"
        f"name: {name}\n"
        'description: "A fixture skill."\n'
        "metadata:\n" + "\n".join(meta) + "\n"
        "---\n\n"
        f"# {name}\n\nBody.\n"
    )


@pytest.fixture
def consumer(tmp_path: Path) -> Path:
    """A consumer with an empty skills/ tree and a plain-directory vendor —
    healthy in every way the doctor already checks, so the only signal in any
    test below is the override-drift one."""
    repo = tmp_path / "consumer"
    (repo / "skills").mkdir(parents=True)
    (repo / "skills-vendor" / VENDOR_REPO / "skills").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    return repo


def _vendor_skill(consumer: Path, name: str, version: str | None) -> Path:
    skill = consumer / "skills-vendor" / VENDOR_REPO / "skills" / name
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text(_skill_md(name, version=version))
    return skill


def _override(
    consumer: Path,
    name: str,
    version: str | None,
    synced_from: str | None = None,
    overrides: str | None = "unset",
) -> Path:
    if overrides == "unset":
        overrides = f"{VENDOR_REPO}/{name}"
    skill = consumer / "skills" / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        _skill_md(name, version=version, overrides=overrides, synced_from=synced_from)
    )
    return skill


class TestVersionDriftIsWarnedAbout:
    """The mechanism is a version comparison, so the comparand's definition is
    part of the mechanism: `version:` in an override is the vendor version last
    synced from (#238)."""

    def test_a_drifted_override_is_warned_about(self, consumer: Path):
        _vendor_skill(consumer, "shipping-work", "1.4")
        _override(consumer, "shipping-work", "1.2")
        result = _doctor(consumer)
        assert DRIFT_MARKER in result.stderr, result.stderr
        assert "skills/shipping-work" in result.stderr, result.stderr
        assert "1.2" in result.stderr and "1.4" in result.stderr, (
            "both versions must be named — an operator deciding whether to "
            f"re-sync needs the distance, not just the fact:\n{result.stderr}"
        )

    def test_the_warning_states_the_resync_direction(self, consumer: Path):
        """The direction is easy to get backwards and ruinous when it is:
        reapply the LOCAL deltas onto the newer UPSTREAM text, never upstream
        changes onto the old fork."""
        _vendor_skill(consumer, "shipping-work", "1.4")
        _override(consumer, "shipping-work", "1.2")
        result = _doctor(consumer)
        assert "local deltas onto" in result.stderr, result.stderr

    def test_the_warning_states_the_removal_check(self, consumer: Path):
        """Direction is only half of what a re-sync gets wrong.

        #267's operator got the direction right and then verified by presence
        — grepping the merged file for what they expected to find — which is
        green by construction over a local delta the merge dropped. The
        message that already teaches the direction is where an operator meets
        the re-sync at all, so it teaches the check too, and names the copy
        that has to be taken before the merge overwrites the original.
        """
        _vendor_skill(consumer, "shipping-work", "1.4")
        _override(consumer, "shipping-work", "1.2")
        result = _doctor(consumer)
        assert "removed line" in result.stderr, (
            "the drift warning should tell the operator to account for every "
            f"removed line (#267), not only how to merge:\n{result.stderr}"
        )
        assert "aside" in result.stderr, (
            "the check needs the pre-merge override, which step 2 destroys, so "
            f"the warning has to ask for the copy up front:\n{result.stderr}"
        )

    def test_a_current_override_is_silent(self, consumer: Path):
        _vendor_skill(consumer, "shipping-work", "1.4")
        _override(consumer, "shipping-work", "1.4")
        result = _doctor(consumer)
        assert DRIFT_MARKER not in result.stderr, result.stderr
        assert UNASSESSED_MARKER not in result.stderr, result.stderr

    def test_an_override_without_a_version_is_not_silently_skipped(
        self, consumer: Path
    ):
        """No `version:` means no comparand, which is the same failure as not
        detecting at all — the warning asks for the field rather than guessing."""
        _vendor_skill(consumer, "shipping-work", "1.4")
        _override(consumer, "shipping-work", None)
        result = _doctor(consumer)
        assert UNASSESSED_MARKER in result.stderr, result.stderr
        assert "skills/shipping-work" in result.stderr, result.stderr

    def test_a_missing_vendor_copy_is_not_silently_skipped(self, consumer: Path):
        """An `overrides:` target with nothing on disk — moved upstream,
        renamed, or a submodule state the other scans happen not to cover."""
        _override(consumer, "shipping-work", "1.2")
        result = _doctor(consumer)
        assert UNASSESSED_MARKER in result.stderr, result.stderr


class TestWhoIsNotWarnedAbout:
    def test_a_local_skill_without_overrides_is_ignored(self, consumer: Path):
        """A regular directory with no `overrides:` key is a project-authored
        skill — it forks nothing, so there is nothing to fall behind."""
        _vendor_skill(consumer, "shipping-work", "1.4")
        skill = consumer / "skills" / "house-style"
        skill.mkdir()
        (skill / "SKILL.md").write_text(_skill_md("house-style", version="0.1"))
        result = _doctor(consumer)
        assert result.stderr.strip() == "", result.stderr

    def test_a_symlinked_skill_is_ignored(self, consumer: Path):
        """A symlink tracks upstream by construction; comparing it to itself
        can only ever agree, and scanning it is how a huge vendor tree turns
        the preflight slow."""
        _vendor_skill(consumer, "reviewing-code", "2.0")
        (consumer / "skills" / "reviewing-code").symlink_to(
            f"../skills-vendor/{VENDOR_REPO}/skills/reviewing-code"
        )
        result = _doctor(consumer)
        assert result.stderr.strip() == "", result.stderr


class TestSyncedFromFallbackForUnversionedVendors:
    """obra-superpowers ships no `version:` at all, so an override of one of
    its skills has nothing to compare — the case the field cannot express. The
    `synced-from:` sibling key pins the vendor commit last synced from, and
    the comparison becomes a path-scoped diff between that commit and HEAD:
    drift means the SKILL changed upstream, not that the submodule moved."""

    def _vendor_git(self, consumer: Path, name: str) -> tuple[Path, str]:
        vendor = consumer / "skills-vendor" / VENDOR_REPO
        _vendor_skill(consumer, name, None)
        _git(vendor, "init", "-q", "-b", "main")
        _git(vendor, "config", "user.email", "t@t.invalid")
        _git(vendor, "config", "user.name", "t")
        _git(vendor, "add", "-A")
        _git(vendor, "commit", "-qm", "vendor at sync time")
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(vendor),
            capture_output=True,
            text=True,
            check=True,
            env=_clean_env(),
            timeout=60,
        ).stdout.strip()
        return vendor, sha

    def test_unchanged_since_the_recorded_commit_is_silent(self, consumer: Path):
        _, sha = self._vendor_git(consumer, "brainstorming")
        _override(
            consumer, "brainstorming", None, synced_from=f"{VENDOR_REPO} v6.3.0 ({sha})"
        )
        result = _doctor(consumer)
        assert DRIFT_MARKER not in result.stderr, result.stderr
        assert UNASSESSED_MARKER not in result.stderr, result.stderr

    def test_an_upstream_change_to_the_skill_is_warned_about(self, consumer: Path):
        vendor, sha = self._vendor_git(consumer, "brainstorming")
        skill_md = vendor / "skills" / "brainstorming" / "SKILL.md"
        skill_md.write_text(skill_md.read_text() + "\nA restructure.\n")
        _git(vendor, "add", "-A")
        _git(vendor, "commit", "-qm", "restructure the skill")
        _override(
            consumer, "brainstorming", None, synced_from=f"{VENDOR_REPO} v6.3.0 ({sha})"
        )
        result = _doctor(consumer)
        assert DRIFT_MARKER in result.stderr, result.stderr
        assert "skills/brainstorming" in result.stderr, result.stderr

    def test_an_upstream_change_elsewhere_is_silent(self, consumer: Path):
        """The diff is scoped to the overridden skill's path. Warning on every
        submodule bump — most of which touch other skills — is the noise that
        trains a reader to skim past the warning that matters."""
        vendor, sha = self._vendor_git(consumer, "brainstorming")
        _vendor_skill(consumer, "unrelated", None)
        _git(vendor, "add", "-A")
        _git(vendor, "commit", "-qm", "an unrelated skill changes")
        _override(
            consumer, "brainstorming", None, synced_from=f"{VENDOR_REPO} v6.3.0 ({sha})"
        )
        result = _doctor(consumer)
        assert DRIFT_MARKER not in result.stderr, result.stderr

    def test_no_synced_from_at_all_is_not_silently_skipped(self, consumer: Path):
        """The follow-up comment's point: a detector with an undefined fallback
        silently skips exactly the overrides it cannot read, which is the same
        failure as not detecting at all."""
        self._vendor_git(consumer, "brainstorming")
        _override(consumer, "brainstorming", None)
        result = _doctor(consumer)
        assert UNASSESSED_MARKER in result.stderr, result.stderr
        assert "synced-from" in result.stderr, (
            "the warning must name the field that would make the override "
            f"assessable:\n{result.stderr}"
        )

    def test_an_unresolvable_recorded_commit_is_not_silently_skipped(
        self, consumer: Path
    ):
        """A shallow vendor clone, or a hash typo: the comparison cannot run,
        and saying nothing would report the un-assessable override as clean."""
        self._vendor_git(consumer, "brainstorming")
        _override(
            consumer,
            "brainstorming",
            None,
            synced_from=f"{VENDOR_REPO} v6.3.0 (feedface)",
        )
        result = _doctor(consumer)
        assert UNASSESSED_MARKER in result.stderr, result.stderr


class TestDriftIsAdvisoryInEveryMode:
    """Warn only, never auto-merge, never an exit code. #231 gave --check-only
    a non-zero exit for the unregistered-hook state; drift deliberately does
    NOT join it — an override behind its vendor is doc-sync debt the operator
    pays down on their schedule, and a CI probe that fails on it would push
    consumers toward deleting overrides rather than re-syncing them."""

    def test_default_mode_exits_zero_with_drift(self, consumer: Path):
        _vendor_skill(consumer, "shipping-work", "1.4")
        _override(consumer, "shipping-work", "1.2")
        result = _doctor(consumer)
        assert result.returncode == 0, result.stderr

    def test_check_only_exits_zero_with_drift(self, consumer: Path):
        _vendor_skill(consumer, "shipping-work", "1.4")
        _override(consumer, "shipping-work", "1.2")
        result = _doctor(consumer, "--check-only")
        assert result.returncode == 0, result.stderr
        assert DRIFT_MARKER in result.stderr, (
            f"advisory does not mean silent:\n{result.stderr}"
        )

    def test_the_doctor_never_edits_the_override(self, consumer: Path):
        """Never auto-merge: the whole point of an override is that upstream
        text cannot be applied blindly."""
        _vendor_skill(consumer, "shipping-work", "1.4")
        override_md = _override(consumer, "shipping-work", "1.2") / "SKILL.md"
        before = override_md.read_text()
        _doctor(consumer)
        assert override_md.read_text() == before
