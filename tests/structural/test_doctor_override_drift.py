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
- **One remedy block for the whole list, in BOTH voices.** The per-override
  lines are the only ones that differ; repeating the remedy under each buries
  them, and un-assessable multiplies by the whole override set because one
  uninitialized submodule makes every override unassessable at once.
- **Warn only, in every mode.** Never auto-merge — the whole point of an
  override is that upstream text cannot be applied blindly — and never a
  non-zero exit, including under `--check-only`: drift is doc-sync debt, not
  the damage or wiring gap that mode gates on (#231).
- **Unversioned upstreams are never silently skipped.** A vendor that ships no
  `version:` is covered by the override's `synced-from:` sibling key, which
  pins the vendor commit last synced from; the vendor tree is then compared
  path-scoped between that commit and HEAD. An override that cannot be
  compared at all is warned about too — silence there is the same failure as
  not detecting at all.
- **Both comparands are read, and either one reports** (#286). The commit
  comparison is not an unversioned-vendor fallback: gating it behind an absent
  `version:` hid the third case neither comparand covers — the vendor changes
  and `version:` does not. An override with no `synced-from:` warns nothing
  new, because for a versioned vendor the stamps still compare.
- **The commit diff is scoped to the override's own real files.** A symlinked
  script tracks upstream by construction and cannot fall behind, so
  whole-directory scope was a false-positive generator; a forked file is the
  only thing that can, and it keeps its signal because `check_silent_forks`
  skips declared overrides wholesale.
- **Which side moved decides the finding** (#290). The commit diff is
  symmetric, so a recorded commit AHEAD of the submodule's HEAD used to be
  reported as the override having fallen behind — with the re-sync remedy,
  the opposite of the right one. The history decides now: recorded commit
  behind HEAD is drift; HEAD behind the recorded commit is the POINTER
  lagging, remedied by one submodule bump and no edit to the override; a
  diverged history is un-assessable. Versioned and unversioned vendors alike.
- **With no history to read, the stamps decide by direction** (#290 CR 3).
  A recorded commit not fetched yet, or no `synced-from:` at all, leaves the
  version stamps as the only verdict: only an OLDER override version is
  drift, a newer one is un-assessable with the fetch that settles it, and the
  stamps are ordered as numbers (1.14 is newer than 1.4).
- **A commit compared clean leaves the stamps no verdict** (#290 CR 40). The
  diff covers the vendor's `SKILL.md`, `version:` included, so a stamp that
  disagrees over a clean diff is a stale key whichever way it points —
  un-assessable in every direction, never drift.
- **Who is NOT warned about.** A symlinked skill tracks upstream by
  construction, and a local directory without `overrides:` is a
  project-authored skill, not a fork of anything.

Keep this list current — it is the file's index.
"""

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCTOR = REPO_ROOT / "skills" / "managing-skills" / "scripts" / "doctor.sh"

VENDOR_REPO = "acme-skills"
DRIFT_MARKER = "has fallen behind"
UNASSESSED_MARKER = "cannot be assessed"
POINTER_MARKER = "is AHEAD of its submodule pointer"
# Drift's remedy, which a pointer finding must never print — the two are
# opposites (#290).
RESYNC_REMEDY = "local deltas onto"


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


def _flat(stderr: str) -> str:
    """The doctor's stderr as prose: `doctor: ` prefixes stripped, wrap undone.

    Its messages are hand-wrapped across `echo` lines, so a match against raw
    stderr can only ever bind a fragment of a sentence — and a re-wrap, which
    changes no contract, breaks such a test. Flattening lets an assertion name
    the whole sentence it means.
    """
    out = []
    for line in stderr.splitlines():
        line = line.strip()
        out.append(
            line[len("doctor:") :].strip() if line.startswith("doctor:") else line
        )
    return " ".join(out)


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


def _short_sha(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
        env=_clean_env(),
        timeout=60,
    ).stdout.strip()


def _vendor_commit(vendor: Path, msg: str) -> str:
    _git(vendor, "add", "-A")
    _git(vendor, "commit", "-qm", msg)
    return _short_sha(vendor)


def _init_vendor_git(
    consumer: Path, name: str, version: str | None
) -> tuple[Path, str]:
    """The vendor submodule as a real git repo holding one skill at one commit.

    Module-level rather than a method on the `synced-from:` class that first
    needed it: #286 made the commit comparison run for versioned vendors too,
    so both classes drive the same fixture and a second copy would be the
    place the two quietly diverge.
    """
    vendor = consumer / "skills-vendor" / VENDOR_REPO
    _vendor_skill(consumer, name, version)
    _git(vendor, "init", "-q", "-b", "main")
    _git(vendor, "config", "user.email", "t@t.invalid")
    _git(vendor, "config", "user.name", "t")
    return vendor, _vendor_commit(vendor, "vendor at sync time")


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
        flat = _flat(result.stderr)
        assert "account for every removed line" in flat, (
            "the drift warning should tell the operator to account for every "
            f"removed line (#267), not only how to merge:\n{result.stderr}"
        )
        # The idea, not one word: a copy taken before the merge. Matching
        # "aside" alone would fail on a faithful rewording and, worse, could be
        # repaired by re-inserting the word without the instruction.
        assert re.search(r"cop(y|ies)[^.]*(aside|before|first)", flat), (
            "the check needs the pre-merge override, which the merge destroys, "
            f"so the warning has to ask for the copy up front:\n{result.stderr}"
        )

    def test_several_drifted_overrides_share_one_remedy(self, consumer: Path):
        """One remedy block for the whole list, not one per file.

        The remedy is the long half of this message and identical every time,
        so printing it per override buries the only lines that differ: three
        drifted overrides read as 27 lines of which 24 were the same
        paragraph. This is the shape `check_silent_forks` and the content
        checks already settled on, and drift was the one class outside it.
        """
        for name in ("shipping-work", "reviewing-code"):
            _vendor_skill(consumer, name, "1.4")
            _override(consumer, name, "1.2")
        result = _doctor(consumer)
        assert result.stderr.count(DRIFT_MARKER) == 1, (
            f"two drifted overrides produced {result.stderr.count(DRIFT_MARKER)} "
            f"headers; the list is one report:\n{result.stderr}"
        )
        remedy = "never upstream changes onto the old fork"
        assert _flat(result.stderr).count(remedy) == 1, (
            f"the remedy is repeated per override:\n{result.stderr}"
        )
        for name in ("shipping-work", "reviewing-code"):
            assert f"skills/{name}" in result.stderr, (
                f"{name} drifted but is not named in the list:\n{result.stderr}"
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

    def test_several_unassessable_overrides_share_one_remedy(self, consumer: Path):
        """The same batching, for the voice with the worse multiplier.

        Un-assessable's likeliest cause is an uninitialized submodule, which
        makes EVERY override unassessable at once — so the repeated tail is
        proportional to the whole override set rather than to the few that
        drifted.
        """
        for name in ("shipping-work", "reviewing-code"):
            _override(consumer, name, "1.2")
        result = _doctor(consumer)
        assert result.stderr.count(UNASSESSED_MARKER) == 1, (
            "two unassessable overrides produced "
            f"{result.stderr.count(UNASSESSED_MARKER)} headers; the list is "
            f"one report:\n{result.stderr}"
        )
        remedy = (
            "an override nothing can compare is the same failure as not "
            "detecting drift at all (#238)."
        )
        assert _flat(result.stderr).count(remedy) == 1, (
            f"the remedy is repeated per override:\n{result.stderr}"
        )
        for name in ("shipping-work", "reviewing-code"):
            assert f"skills/{name}" in result.stderr, (
                f"{name} is unassessable but is not named:\n{result.stderr}"
            )

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


class TestSyncedFromForUnversionedVendors:
    """obra-superpowers ships no `version:` at all, so an override of one of
    its skills has nothing to compare on the stamps — the case the field
    cannot express. The `synced-from:` sibling key pins the vendor commit last
    synced from, and the comparison is a path-scoped diff between that commit
    and HEAD: drift means the SKILL changed upstream, not that the submodule
    moved.

    Not a *fallback*, which is what this class was called until #286 — the
    commit comparison runs for versioned vendors too, and the class named for
    that is below. The old name is worth not restoring: it was the model that
    hid four un-bumped changes, and a test name is where a superseded model is
    least likely to be questioned (CR 4)."""

    def _vendor_git(self, consumer: Path, name: str) -> tuple[Path, str]:
        return _init_vendor_git(consumer, name, None)

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


class TestSyncedFromIsReadForVersionedVendorsToo:
    """#286 — the commit comparison is not an unversioned-vendor fallback.

    It used to be: the versioned branch ended in `continue`, so a recorded
    commit was never read when the vendor shipped a `version:`. That left a
    third case uncovered by either comparand — **the vendor changes and
    `version:` does not.** CannObserv/archiver's
    `shipping-work-python-fastapi` override recorded `synced-from: 662de71`
    against a vendor also at 1.4, and four separate SKILL.md changes had
    landed at that same 1.4 since. The doctor ran clean, correctly by its own
    contract, and the gap was found by reading a report.

    This is not #260's declined stored-hash direction. That compares the
    override with the vendor, where divergence is EXPECTED. This compares the
    vendor with itself — the synced-from commit against the vendor now — so
    the override's own deltas never enter it.
    """

    def _vendor_changes_without_a_bump(self, consumer: Path, name: str, ver: str):
        """The #286 state: vendor SKILL.md gains text, `version:` stays put."""
        vendor, sha = _init_vendor_git(consumer, name, ver)
        skill_md = vendor / "skills" / name / "SKILL.md"
        skill_md.write_text(
            skill_md.read_text() + "\nStep 1.5, new at the same version.\n"
        )
        _vendor_commit(vendor, "a change at the same version")
        return vendor, sha

    def test_a_vendor_change_at_a_matching_version_is_warned_about(
        self, consumer: Path
    ):
        """The headline case. Both stamps read 1.4 and the vendor moved."""
        _, sha = self._vendor_changes_without_a_bump(consumer, "shipping-work", "1.4")
        _override(
            consumer,
            "shipping-work",
            "1.4",
            synced_from=f"{VENDOR_REPO} 1.4 ({sha})",
        )
        result = _doctor(consumer)
        assert DRIFT_MARKER in result.stderr, (
            "the vendor's SKILL.md changed at an unchanged version: and the "
            "override records the exact commit it synced from — the "
            f"comparison that sees it is one git diff away (#286):\n{result.stderr}"
        )
        assert "skills/shipping-work" in result.stderr, result.stderr
        assert "SKILL.md" in result.stderr, (
            "the finding names the file to re-sync, which is the work order "
            f"for an operator merging by hand:\n{result.stderr}"
        )

    def test_the_warning_says_the_stamps_matched(self, consumer: Path):
        """Without this the report is unbelievable.

        A reader told an override has fallen behind checks `version:` first.
        Finding it equal on both sides, the reasonable conclusion is that the
        doctor is wrong — so the message has to say that the stamps match and
        the comparison fired anyway, which is the whole state #286 reports.
        """
        _, sha = self._vendor_changes_without_a_bump(consumer, "shipping-work", "1.4")
        _override(
            consumer, "shipping-work", "1.4", synced_from=f"{VENDOR_REPO} 1.4 ({sha})"
        )
        flat = _flat(_doctor(consumer).stderr)
        assert re.search(r"stamps match|version 1\.4 still", flat), (
            "an operator who checks the versions and finds them equal needs "
            f"the message to have said so already:\n{flat}"
        )

    def test_a_versioned_vendor_is_named_even_with_no_override_version(
        self, consumer: Path
    ):
        """The doctor knows the vendor's version; the drift line must not
        disown it.

        The wording branched on whether the two stamps were EQUAL, so an
        override recording no `version:` at all made that false and fell
        through to the unversioned-vendor prose — reporting "a vendor tree"
        about a vendor the doctor had just read 1.4 from, on the one line
        meant to be the work order (CR 1). No test covered this combination,
        which is why the branch survived a verification pass.
        """
        _, sha = self._vendor_changes_without_a_bump(consumer, "shipping-work", "1.4")
        _override(
            consumer, "shipping-work", None, synced_from=f"{VENDOR_REPO} 1.4 ({sha})"
        )
        result = _doctor(consumer)
        assert DRIFT_MARKER in result.stderr, result.stderr
        drift = [ln for ln in result.stderr.splitlines() if "last synced at" in ln]
        assert len(drift) == 1, f"expected one drift line:\n{result.stderr}"
        assert "1.4" in drift[0], (
            "the vendor's version was read and must be named rather than "
            f"generalised to 'a vendor tree':\n{drift[0]}"
        )
        assert "a vendor tree" not in drift[0], drift[0]

    def test_no_change_since_the_recorded_commit_is_silent(self, consumer: Path):
        """The comparison must not fire merely because a commit is recorded."""
        _, sha = _init_vendor_git(consumer, "shipping-work", "1.4")
        _override(
            consumer, "shipping-work", "1.4", synced_from=f"{VENDOR_REPO} 1.4 ({sha})"
        )
        result = _doctor(consumer)
        assert DRIFT_MARKER not in result.stderr, result.stderr
        assert UNASSESSED_MARKER not in result.stderr, result.stderr

    def test_an_override_with_no_synced_from_behaves_exactly_as_before(
        self, consumer: Path
    ):
        """No new warning for a versioned vendor whose override records no
        commit.

        Every override in the cohort is in this state today, so warning here
        would fire on all of them at once over a key none has been asked for
        — which is how a new detector teaches its reader to skim past it.
        The recommendation lives in the docs; the absence is a finding only
        when nothing else can compare.
        """
        self._vendor_changes_without_a_bump(consumer, "shipping-work", "1.4")
        _override(consumer, "shipping-work", "1.4")
        result = _doctor(consumer)
        assert result.stderr.strip() == "", (
            "an override without synced-from: must warn nothing new — the "
            f"vendor's version: is still a comparand and it matched:\n{result.stderr}"
        )

    def test_a_symlinked_script_changing_upstream_is_not_drift(self, consumer: Path):
        """The false positive direction 1 of #286 asks to avoid.

        Whole-directory scope reported `scripts/doc-check.sh` beside the
        SKILL.md that really had fallen behind — and the override followed
        that script through a symlink, so it already had the change with
        nothing to re-sync. A symlink cannot fall behind by construction.
        """
        vendor, sha = _init_vendor_git(consumer, "shipping-work", "1.4")
        script = vendor / "skills" / "shipping-work" / "scripts" / "doc-check.sh"
        script.write_text("echo upstream moved\n")
        _vendor_commit(vendor, "a script changes, SKILL.md does not")
        override = _override(
            consumer, "shipping-work", "1.4", synced_from=f"{VENDOR_REPO} 1.4 ({sha})"
        )
        (override / "scripts").mkdir()
        (override / "scripts" / "doc-check.sh").symlink_to(
            f"../../../skills-vendor/{VENDOR_REPO}/skills/shipping-work/scripts/doc-check.sh"
        )
        result = _doctor(consumer)
        assert DRIFT_MARKER not in result.stderr, (
            "the only vendor-side change is to a file the override symlinks, "
            f"so it is already in the consumer's hands:\n{result.stderr}"
        )

    def test_a_forked_script_changing_upstream_is_drift(self, consumer: Path):
        """The mirror, and why the scope is the override's real files rather
        than SKILL.md alone.

        `check_silent_forks` skips a declared override wholesale — its drift
        is this check's business — so this comparison is the only detector a
        forked script inside an override has. Narrowing to SKILL.md would
        have dropped that signal silently.
        """
        vendor, sha = _init_vendor_git(consumer, "shipping-work", "1.4")
        script = vendor / "skills" / "shipping-work" / "scripts" / "doc-check.sh"
        script.write_text("echo upstream moved\n")
        _vendor_commit(vendor, "a script changes, SKILL.md does not")
        override = _override(
            consumer, "shipping-work", "1.4", synced_from=f"{VENDOR_REPO} 1.4 ({sha})"
        )
        (override / "scripts").mkdir()
        (override / "scripts" / "doc-check.sh").write_text("echo the old text\n")
        result = _doctor(consumer)
        assert DRIFT_MARKER in result.stderr, result.stderr
        assert "scripts/doc-check.sh" in result.stderr, (
            f"the finding must name the forked file that fell behind:\n{result.stderr}"
        )

    def test_both_comparisons_firing_is_one_finding(self, consumer: Path):
        """One override, one line. The operator re-syncs once."""
        vendor, sha = _init_vendor_git(consumer, "shipping-work", "1.4")
        skill_md = vendor / "skills" / "shipping-work" / "SKILL.md"
        skill_md.write_text(
            skill_md.read_text().replace('version: "1.4"', 'version: "1.5"')
            + "\nAnd new text.\n"
        )
        _vendor_commit(vendor, "a bumped change")
        _override(
            consumer, "shipping-work", "1.4", synced_from=f"{VENDOR_REPO} 1.4 ({sha})"
        )
        result = _doctor(consumer)
        assert DRIFT_MARKER in result.stderr, result.stderr
        listed = result.stderr.count(f"overrides {VENDOR_REPO}/shipping-work")
        assert listed == 1, (
            "the version stamps and the recorded commit both fired for one "
            f"override; that is one finding, not {listed}:\n{result.stderr}"
        )
        assert "1.5" in result.stderr, (
            f"the vendor's current version is still named:\n{result.stderr}"
        )

    def test_an_unresolvable_commit_does_not_suppress_version_drift(
        self, consumer: Path
    ):
        """A broken second comparand must not cost the first one.

        The two comparisons are independent: a shallow clone or a hash typo
        makes the commit diff unrunnable, and the version stamps still say
        the override is two releases behind.
        """
        vendor, _ = _init_vendor_git(consumer, "shipping-work", "1.4")
        skill_md = vendor / "skills" / "shipping-work" / "SKILL.md"
        skill_md.write_text(
            skill_md.read_text().replace('version: "1.4"', 'version: "1.6"')
        )
        _vendor_commit(vendor, "a bump")
        _override(
            consumer,
            "shipping-work",
            "1.4",
            synced_from=f"{VENDOR_REPO} 1.4 (feedface)",
        )
        result = _doctor(consumer)
        assert DRIFT_MARKER in result.stderr, (
            "the version comparison still has both comparands and they "
            f"differ:\n{result.stderr}"
        )
        assert "1.4" in result.stderr and "1.6" in result.stderr, result.stderr
        assert UNASSESSED_MARKER in result.stderr, (
            "the operator wrote a synced-from: that cannot be read; an "
            f"escape hatch that quietly does not apply is its own defect:\n{result.stderr}"
        )

    def test_an_unreadable_synced_from_is_reported_even_when_versions_match(
        self, consumer: Path
    ):
        """Matching stamps are no longer the end of the enquiry.

        With the commit comparison unrunnable, the override is stale in
        exactly the way #286 describes and nothing can see it — so silence
        here would report an un-assessable override as clean, which is #238's
        own principle.
        """
        self._vendor_changes_without_a_bump(consumer, "shipping-work", "1.4")
        _override(
            consumer,
            "shipping-work",
            "1.4",
            synced_from=f"{VENDOR_REPO} 1.4 (feedface)",
        )
        result = _doctor(consumer)
        assert UNASSESSED_MARKER in result.stderr, result.stderr


def _vendor_head(vendor: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(vendor),
        capture_output=True,
        text=True,
        check=True,
        env=_clean_env(),
        timeout=60,
    ).stdout.strip()


def _bumps(stderr: str) -> list[str]:
    """The `git -C … merge --ff-only …` commands the pointer finding prints."""
    return [
        ln.strip() for ln in stderr.splitlines() if ln.strip().startswith("git -C ")
    ]


def _run(consumer: Path, cmd: str) -> None:
    """Run a command exactly as the doctor printed it."""
    subprocess.run(
        shlex.split(cmd),
        cwd=str(consumer),
        check=True,
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=60,
    )


def _resolve(vendor: Path, commitish: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", f"{commitish}^{{commit}}"],
        cwd=str(vendor),
        capture_output=True,
        text=True,
        check=True,
        env=_clean_env(),
        timeout=60,
    ).stdout.strip()


class TestWhichSideMoved:
    """#290 — the commit diff cannot say which side moved; the history can.

    `git diff <recorded> HEAD` is symmetric, so an override whose
    `synced-from:` records a commit AHEAD of the submodule's HEAD was reported
    exactly like one that had fallen behind — and handed the re-sync remedy,
    which there means reapplying local deltas onto OLDER text. The live case
    was the first consumer to do the right thing by #286: CannObserv/archiver
    re-synced its override, stamped `178ec64`, and left its pointer 26 commits
    back at `980a0d1`. The repair is one submodule bump and no edit to the
    override at all — the opposite remedy, so it gets its own voice.

    Detection is unchanged; only the diagnosis branches. Three states, one
    per `merge-base --is-ancestor` answer, and each reachable from both the
    versioned and the unversioned vendor, since #286 routes both through the
    same diff.
    """

    def _two_commits(
        self, consumer: Path, name: str, old_ver: str | None, new_ver: str | None
    ) -> tuple[Path, str, str]:
        """The vendor at OLD then NEW, each a real SKILL.md change."""
        vendor, old = _init_vendor_git(consumer, name, old_ver)
        skill_md = vendor / "skills" / name / "SKILL.md"
        text = skill_md.read_text() + "\nNew upstream text.\n"
        if old_ver is not None and new_ver is not None:
            text = text.replace(f'version: "{old_ver}"', f'version: "{new_ver}"')
        skill_md.write_text(text)
        return vendor, old, _vendor_commit(vendor, "upstream moves")

    def _pointer_behind(
        self, consumer: Path, ver: str | None = "1.4", new_ver: str | None = "1.4"
    ) -> tuple[Path, str, str]:
        """The issue's reproduction: two vendor commits, the submodule checked
        out at the OLDER one, the override recording the NEWER one."""
        vendor, old, new = self._two_commits(consumer, "sw", ver, new_ver)
        _git(vendor, "checkout", "-q", old)
        _override(consumer, "sw", new_ver, synced_from=f"{VENDOR_REPO} 1.4 ({new})")
        return vendor, old, new

    @pytest.mark.parametrize("ver", ["1.4", None], ids=["versioned", "unversioned"])
    def test_a_recorded_commit_ahead_of_the_pointer_is_not_drift(
        self, consumer: Path, ver: str | None
    ):
        """The reproduction, for both vendor shapes. Every clause of the drift
        report is wrong here in the same direction, so none of it may print."""
        _, _, new = self._pointer_behind(consumer, ver, ver)
        result = _doctor(consumer)
        assert DRIFT_MARKER not in result.stderr, (
            "the override is AHEAD of the pointer, not behind the vendor — the "
            f"drift voice is the wrong diagnosis:\n{result.stderr}"
        )
        assert RESYNC_REMEDY not in result.stderr, (
            "the re-sync remedy would reapply local deltas onto OLDER text; it "
            f"is the opposite of the repair here:\n{result.stderr}"
        )
        assert POINTER_MARKER in result.stderr, result.stderr
        assert UNASSESSED_MARKER not in result.stderr, result.stderr
        entry = [ln for ln in result.stderr.splitlines() if "overrides " in ln]
        assert len(entry) == 1, f"expected one entry:\n{result.stderr}"
        assert f"skills-vendor/{VENDOR_REPO}" in entry[0] and new in entry[0], (
            "the entry names the one submodule to bump and the commit to reach "
            f"— 'your submodule is behind' sends a reader to the hook:\n{entry[0]}"
        )

    def test_the_printed_bump_clears_the_finding(self, consumer: Path):
        """The remedy is executable, and it is the whole repair.

        Run exactly what the doctor printed, touch nothing else: the pointer
        reaches the recorded commit and the next run is silent — the override
        was never the thing out of date."""
        vendor, _, new = self._pointer_behind(consumer)
        override_md = consumer / "skills" / "sw" / "SKILL.md"
        before = override_md.read_text()
        result = _doctor(consumer)
        commands = [
            ln.strip()
            for ln in result.stderr.splitlines()
            if ln.strip().startswith("git -C ")
        ]
        assert len(commands) == 1, f"expected one bump command:\n{result.stderr}"
        subprocess.run(
            shlex.split(commands[0]),
            cwd=str(consumer),
            check=True,
            capture_output=True,
            text=True,
            env=_clean_env(),
            timeout=60,
        )
        assert _vendor_head(vendor).startswith(new), (
            f"the printed command did not reach the recorded commit: {commands[0]}"
        )
        again = _doctor(consumer)
        assert again.stderr.strip() == "", (
            f"the bump should have been the whole repair:\n{again.stderr}"
        )
        assert override_md.read_text() == before

    def test_a_bump_that_moves_the_stamps_too_is_one_finding(self, consumer: Path):
        """The pointer lags a BUMPED release, so the version stamps disagree as
        well (override 1.5, vendor HEAD 1.4). That is the same fact, and a
        drift line beside the pointer finding would print both opposite
        remedies for one override."""
        self._pointer_behind(consumer, "1.4", "1.5")
        result = _doctor(consumer)
        assert POINTER_MARKER in result.stderr, result.stderr
        assert DRIFT_MARKER not in result.stderr, result.stderr
        listed = result.stderr.count(f"overrides {VENDOR_REPO}/sw")
        assert listed == 1, f"one override, {listed} entries:\n{result.stderr}"

    def test_a_recorded_commit_behind_the_pointer_is_still_drift(self, consumer: Path):
        """The first state, unchanged: HEAD descends from the recorded commit,
        so upstream moved and the override has fallen behind."""
        _, old, _ = self._two_commits(consumer, "sw", "1.4", "1.4")
        _override(consumer, "sw", "1.4", synced_from=f"{VENDOR_REPO} 1.4 ({old})")
        result = _doctor(consumer)
        assert DRIFT_MARKER in result.stderr, result.stderr
        assert RESYNC_REMEDY in result.stderr, result.stderr
        assert POINTER_MARKER not in result.stderr, result.stderr

    @pytest.mark.parametrize("ver", ["1.4", None], ids=["versioned", "unversioned"])
    def test_a_diverged_history_is_unassessable(self, consumer: Path, ver: str | None):
        """Neither commit contains the other — a vendor whose history was
        rewritten, or a fork. `--is-ancestor` reads false in both directions,
        and "bump the pointer" is as wrong there as "re-sync" is: no direction
        can be read, so neither remedy may print."""
        vendor, base = _init_vendor_git(consumer, "sw", ver)
        skill_md = vendor / "skills" / "sw" / "SKILL.md"
        original = skill_md.read_text()
        skill_md.write_text(original + "\nOne side of the fork.\n")
        theirs = _vendor_commit(vendor, "one line of history")
        _git(vendor, "checkout", "-q", "-b", "rewritten", base)
        skill_md.write_text(original + "\nThe other side.\n")
        _vendor_commit(vendor, "the other line of history")
        _override(consumer, "sw", ver, synced_from=f"{VENDOR_REPO} 1.4 ({theirs})")
        result = _doctor(consumer)
        assert UNASSESSED_MARKER in result.stderr, result.stderr
        assert "diverged" in result.stderr, (
            f"the reason must say which state this is:\n{result.stderr}"
        )
        assert DRIFT_MARKER not in result.stderr, result.stderr
        assert POINTER_MARKER not in result.stderr, result.stderr

    def test_an_ancestry_check_that_fails_is_unassessable(
        self, consumer: Path, tmp_path: Path
    ):
        """`--is-ancestor` exits 1 for "no" and anything else for an error.
        Read as "no", a failure would fall through both questions to
        `diverged` — or, with the order reversed, to a verdict it never
        earned. It is its own un-assessable reason instead."""
        self._pointer_behind(consumer)
        real_git = shutil.which("git") or "/usr/bin/git"
        shim_dir = tmp_path / "bin"
        shim_dir.mkdir()
        shim = shim_dir / "git"
        shim.write_text(
            "#!/usr/bin/env bash\n"
            'for a in "$@"; do [ "$a" = merge-base ] && exit 128; done\n'
            f'exec {real_git} "$@"\n'
        )
        shim.chmod(0o755)
        env = _clean_env()
        env["PATH"] = f"{shim_dir}:{env.get('PATH', '/usr/bin:/bin')}"
        result = subprocess.run(
            ["bash", str(DOCTOR), "--no-preflight"],
            cwd=str(consumer),
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        assert UNASSESSED_MARKER in result.stderr, result.stderr
        assert "merge-base" in result.stderr, result.stderr
        for marker in (DRIFT_MARKER, POINTER_MARKER, "diverged"):
            assert marker not in result.stderr, result.stderr

    def test_the_pointer_finding_is_advisory_and_changes_nothing(self, consumer: Path):
        """Same contract as drift: exit 0 in every mode, and the doctor never
        moves the pointer itself — which commit a consumer vendors is the
        operator's decision, and an automatic bump is the auto-refresh hook's
        job, not a preflight's."""
        vendor, old, _ = self._pointer_behind(consumer)
        for args in ((), ("--check-only",)):
            result = _doctor(consumer, *args)
            assert result.returncode == 0, result.stderr
            assert POINTER_MARKER in result.stderr, result.stderr
        assert _vendor_head(vendor).startswith(old), "the doctor moved the pointer"


class TestAPinnedPointer:
    """#290 CR 13 — the pointer remedy reads the pin before prescribing a bump.

    `.skills/skills-pin` (or `$SKILLS_PIN_FILE`) holds a submodule at a commit
    on purpose. Bumping it alone ends that hold, and the auto-refresh hook
    then reports pin drift at every session, because a pin holds the recorded
    pointer still but cannot move it back. So a held entry says so and offers
    the two repairs that keep pin and pointer agreeing.

    CR 41 — the pin is resolved and settled per submodule. A pin that already
    names the recorded commit is not re-pinned to itself (the bump completes
    it), and several overrides of one held submodule get one re-pin, to the
    commit their bumps converge on.
    """

    def _pinned(self, consumer: Path, pin_text: str, pin_name: str = "skills-pin"):
        vendor, old, new = TestWhichSideMoved()._pointer_behind(consumer)
        pin = consumer / ".skills" / pin_name
        pin.parent.mkdir(exist_ok=True)
        pin.write_text(pin_text.format(old=old, new=new))
        return vendor, old, new, pin

    def test_a_pinned_submodule_is_named_with_both_repairs(self, consumer: Path):
        _, old, new, _ = self._pinned(
            consumer, "# control arm\nskills-vendor/acme-skills {old}\n"
        )
        result = _doctor(consumer)
        assert POINTER_MARKER in result.stderr, result.stderr
        flat = _flat(result.stderr)
        assert f"pinned at {old} by .skills/skills-pin" in flat, (
            "a bump alone ends the operator's hold — the entry has to say the "
            f"submodule is held before prescribing one:\n{result.stderr}"
        )
        assert f'"skills-vendor/{VENDOR_REPO} {new}"' in flat, (
            f"the re-pin names the exact line to write:\n{result.stderr}"
        )
        assert f"re-sync the override to {old}" in flat, (
            f"keeping the hold is the other repair:\n{result.stderr}"
        )
        assert DRIFT_MARKER not in result.stderr, result.stderr

    def test_the_repin_and_bump_leave_pin_and_pointer_agreeing(self, consumer: Path):
        """Follow the first repair as printed: write the pin line, run the
        doctor again, run the bump. The pin then names the pointer — the
        comparison the hook's pin drift check makes — and the doctor is silent.

        The run BETWEEN the two steps is the one CR 41 found wrong. The pin
        already names the recorded commit there, so re-pinning to it is
        advice to do what was just done, and "a bump alone ends that hold" is
        false: the bump is what puts the hold into effect."""
        vendor, _, new, pin = self._pinned(
            consumer, "skills-vendor/acme-skills {old}\n"
        )
        result = _doctor(consumer)
        line = re.search(r're-pin that line to "([^"]+)"', _flat(result.stderr))
        assert line, result.stderr
        pin.write_text(line.group(1) + "\n")
        between = _doctor(consumer)
        flat = _flat(between.stderr)
        assert POINTER_MARKER in between.stderr, between.stderr
        assert "re-pin" not in flat, (
            f"the pin already names {new}; there is nothing to re-pin:\n{flat}"
        )
        assert "a bump alone ends" not in flat, (
            f"the bump completes this hold rather than ending it:\n{flat}"
        )
        assert "the bump completes the hold" in flat, flat
        bump = _bumps(between.stderr)
        assert len(bump) == 1, between.stderr
        _run(consumer, bump[0])
        assert _resolve(vendor, line.group(1).split()[1]) == _vendor_head(vendor), (
            "the pin and the pointer disagree"
        )
        assert _doctor(consumer).stderr.strip() == ""

    def _two_overrides(self, consumer: Path, diverged: bool = False):
        """Two overrides of one pinned vendor, each ahead of the pointer at a
        different recorded commit: `sa` at the NEWER one, sorting first, so
        re-pinning entry by entry would leave the pin at the older one while
        the ff-only bumps converge on the newer. `sb` is unchanged between the
        two, so once the pointer reaches the newer both are current. `diverged`
        puts the two commits on separate lines of history instead."""
        vendor = consumer / "skills-vendor" / VENDOR_REPO
        for name in ("sa", "sb"):
            _vendor_skill(consumer, name, "1.4")
        _git(vendor, "init", "-q", "-b", "main")
        _git(vendor, "config", "user.email", "t@t.invalid")
        _git(vendor, "config", "user.name", "t")
        base = _vendor_commit(vendor, "A")
        commits = []
        for step, names in (("B", ("sa", "sb")), ("C", ("sa",))):
            if diverged:
                _git(vendor, "checkout", "-q", "-B", f"line-{step}", base)
            for name in names:
                md = vendor / "skills" / name / "SKILL.md"
                md.write_text(md.read_text() + f"\n{step}.\n")
            commits.append(_vendor_commit(vendor, step))
        _git(vendor, "checkout", "-q", base)
        older, newer = commits
        _override(consumer, "sa", "1.4", synced_from=f"{VENDOR_REPO} x ({newer})")
        _override(consumer, "sb", "1.4", synced_from=f"{VENDOR_REPO} x ({older})")
        pin = consumer / ".skills" / "skills-pin"
        pin.parent.mkdir()
        pin.write_text(f"skills-vendor/{VENDOR_REPO} {base}\n")
        return vendor, base, older, newer, pin

    def test_two_overrides_of_one_held_submodule_get_one_repin(self, consumer: Path):
        """One pin-file line, so one re-pin, to the commit the bumps converge
        on. Two re-pin lines for one line contradict each other, and followed
        entry by entry they left the pin at the OLDER commit while the bumps
        took the pointer to the newer — the pin drift the note exists to
        prevent (CR 41)."""
        vendor, base, _, newer, pin = self._two_overrides(consumer)
        result = _doctor(consumer)
        flat = _flat(result.stderr)
        repins = re.findall(r're-pin that line to "([^"]+)"', flat)
        assert repins == [f"skills-vendor/{VENDOR_REPO} {newer}"], (
            f"one re-pin, to the newest recorded commit:\n{result.stderr}"
        )
        assert flat.count(f"pinned at {base}") == 1, result.stderr
        pin.write_text(repins[0] + "\n")
        between = _flat(_doctor(consumer).stderr)
        assert "re-pin" not in between, between
        assert "a bump alone ends" not in between, between
        for cmd in _bumps(result.stderr):
            _run(consumer, cmd)
        assert _resolve(vendor, newer) == _vendor_head(vendor), (
            "the pin and the pointer disagree"
        )
        assert _doctor(consumer).stderr.strip() == ""

    def test_overrides_on_diverged_lines_get_no_repin(self, consumer: Path):
        """No recorded commit contains the other, so no one pin serves both
        and the bumps cannot converge. Naming either would be a guess; the
        hold is the repair left."""
        _, base, _, _, _ = self._two_overrides(consumer, diverged=True)
        flat = _flat(_doctor(consumer).stderr)
        assert "re-pin that line" not in flat, flat
        assert flat.count(f"pinned at {base}") == 1, flat
        assert f"re-sync each of them to {base}" in flat, flat

    def test_the_env_var_pin_file_is_read(self, consumer: Path):
        """Same resolution as the hook: `$SKILLS_PIN_FILE` first."""
        _, old, _, _ = self._pinned(
            consumer, "skills-vendor/acme-skills {old}\n", pin_name="pin.override"
        )
        env = _clean_env()
        env["SKILLS_PIN_FILE"] = ".skills/pin.override"
        result = subprocess.run(
            ["bash", str(DOCTOR), "--no-preflight"],
            cwd=str(consumer),
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        assert f"pinned at {old} by .skills/pin.override" in _flat(result.stderr), (
            result.stderr
        )

    @pytest.mark.parametrize(
        "pin_text",
        [
            "skills-vendor/other-skills {old}\n",
            "# skills-vendor/acme-skills {old}\n",
            "skills-vendor/acme-skills {old} extra\n",
        ],
        ids=["another-submodule", "commented-out", "malformed"],
    )
    def test_a_pin_that_does_not_hold_it_changes_nothing(
        self, consumer: Path, pin_text: str
    ):
        """The hook's grammar: another path, a comment, or a line that is not
        two words pins nothing here — the hook refuses a malformed line on
        its own channel."""
        self._pinned(consumer, pin_text)
        result = _doctor(consumer)
        assert POINTER_MARKER in result.stderr, result.stderr
        assert "pinned" not in result.stderr, result.stderr


class TestStampsDecideByDirection:
    """#290 CR 3 — when the version stamps are the only verdict, they decide
    by direction, and a NEWER override version is never drift.

    The ancestry check needs the recorded commit on disk. Without it — not
    fetched yet, or no `synced-from:` at all — the stamps were compared for
    equality alone, so an override re-synced from upstream's newest release
    over a pointer still at the previous one read "last synced at version 1.5,
    vendor now at version 1.4" with the re-sync remedy: the opposite of the fix
    #290 exists to print, which a fetch and a re-run then printed correctly.
    """

    def _unfetched(self, consumer: Path, tmp_path: Path) -> tuple[Path, str]:
        """The reviewer's fixture: upstream A (1.4), the consumer's vendor
        cloned at A, upstream B (1.5) not fetched, the override recording B."""
        up = tmp_path / "upstream"
        (up / "skills" / "sw").mkdir(parents=True)
        md = up / "skills" / "sw" / "SKILL.md"
        md.write_text(_skill_md("sw", version="1.4"))
        _git(up, "init", "-q", "-b", "main")
        _git(up, "config", "user.email", "t@t.invalid")
        _git(up, "config", "user.name", "t")
        _vendor_commit(up, "A")
        vendor = consumer / "skills-vendor" / VENDOR_REPO
        shutil.rmtree(vendor)
        _git(consumer, "clone", "-q", str(up), str(vendor))
        md.write_text(
            md.read_text().replace('version: "1.4"', 'version: "1.5"') + "\nB.\n"
        )
        new = _vendor_commit(up, "B")
        _override(consumer, "sw", "1.5", synced_from=f"{VENDOR_REPO} 1.5 ({new})")
        return vendor, new

    def test_an_unfetched_commit_over_a_version_bump_is_not_drift(
        self, consumer: Path, tmp_path: Path
    ):
        self._unfetched(consumer, tmp_path)
        result = _doctor(consumer)
        assert DRIFT_MARKER not in result.stderr, (
            "the override's version is NEWER than the vendor's — calling that "
            f"drift hands out the re-sync remedy onto older text:\n{result.stderr}"
        )
        assert RESYNC_REMEDY not in result.stderr, result.stderr
        assert UNASSESSED_MARKER in result.stderr, result.stderr
        listed = result.stderr.count(f"overrides {VENDOR_REPO}/sw")
        assert listed == 1, f"one override, {listed} entries:\n{result.stderr}"

    def test_the_printed_fetch_leads_to_the_pointer_finding(
        self, consumer: Path, tmp_path: Path
    ):
        """Cause 5 leads with its likeliest cause and the command for it, and
        that command is the whole way to the right diagnosis: run it, re-run
        the doctor, and the history now says the pointer lags."""
        vendor, new = self._unfetched(consumer, tmp_path)
        flat = _flat(_doctor(consumer).stderr)
        assert "not fetched yet" in flat, flat
        fetch = re.search(r"`(git -C \S+ fetch)`", flat)
        assert fetch, f"no fetch command printed:\n{flat}"
        subprocess.run(
            shlex.split(fetch.group(1)),
            cwd=str(consumer),
            check=True,
            capture_output=True,
            text=True,
            env=_clean_env(),
            timeout=60,
        )
        again = _doctor(consumer)
        assert POINTER_MARKER in again.stderr, again.stderr
        assert DRIFT_MARKER not in again.stderr, again.stderr
        assert new in again.stderr, again.stderr

    def test_no_synced_from_and_a_newer_version_is_not_drift(self, consumer: Path):
        """No commit at all, so nothing but the stamps — and they say the
        override is ahead of its vendor, not behind it."""
        _vendor_skill(consumer, "sw", "1.4")
        _override(consumer, "sw", "1.5")
        result = _doctor(consumer)
        assert DRIFT_MARKER not in result.stderr, result.stderr
        assert RESYNC_REMEDY not in result.stderr, result.stderr
        assert UNASSESSED_MARKER in result.stderr, result.stderr
        flat = _flat(result.stderr)
        assert "NEWER" in flat and "synced-from" in flat, (
            "the reason names the direction, and the key that would let the "
            f"doctor name the commit to bump to:\n{flat}"
        )

    @pytest.mark.parametrize(
        ("override", "vendor", "drift"),
        [
            ("1.4", "1.14", True),
            ("1.14", "1.4", False),
            ("1.2", "1.4", True),
            ("1.4.1", "1.4", False),
        ],
    )
    def test_the_stamps_are_ordered_as_numbers(
        self, consumer: Path, override: str, vendor: str, drift: bool
    ):
        """Field by field, never as strings: the library ships both 1.4 and
        1.14, and a string compare puts them the wrong way round."""
        _vendor_skill(consumer, "sw", vendor)
        _override(consumer, "sw", override)
        result = _doctor(consumer)
        assert (DRIFT_MARKER in result.stderr) is drift, result.stderr

    def test_the_same_release_spelled_twice_is_silent(self, consumer: Path):
        _vendor_skill(consumer, "sw", "1.4.0")
        _override(consumer, "sw", "1.4")
        assert _doctor(consumer).stderr.strip() == ""

    def test_stamps_that_cannot_be_ordered_are_unassessable(self, consumer: Path):
        """A stamp nobody can order is reported as such, never guessed at in
        either direction."""
        _vendor_skill(consumer, "sw", "1.4")
        _override(consumer, "sw", "1.5-rc1")
        result = _doctor(consumer)
        assert UNASSESSED_MARKER in result.stderr, result.stderr
        assert DRIFT_MARKER not in result.stderr, result.stderr


class TestACleanCommitLeavesTheStampsNoVerdict:
    """#290 CR 40 — a recorded commit fetched and compared CLEAN outranks the
    stamps in every direction, not only the newer one.

    The commit diff always covers the vendor's `SKILL.md`, which carries
    `version:`, so a clean diff means the vendor's version at the recorded
    commit IS the one at `HEAD`. A stamp that disagrees is then a stale stamp
    whichever way it points. Only the newer arm said so; an older stamp still
    read "last synced at version 1.4, vendor now at version 1.5" with the full
    re-sync remedy over files history had just shown unchanged — the common
    case being a re-sync that bumped `synced-from:` and forgot `version:`.
    """

    @pytest.mark.parametrize(
        ("override", "vendor"),
        [("1.4", "1.5"), ("1.6", "1.5"), ("1.5-rc1", "1.4")],
        ids=["older", "newer", "unordered"],
    )
    def test_a_stamp_mismatch_over_a_clean_commit_is_one_reason(
        self, consumer: Path, override: str, vendor: str
    ):
        _, sha = _init_vendor_git(consumer, "sw", vendor)
        _override(consumer, "sw", override, synced_from=f"{VENDOR_REPO} x ({sha})")
        result = _doctor(consumer)
        assert DRIFT_MARKER not in result.stderr, (
            "history shows nothing moved since the recorded commit — the "
            f"stamp is stale, not the override:\n{result.stderr}"
        )
        assert RESYNC_REMEDY not in result.stderr, result.stderr
        assert UNASSESSED_MARKER in result.stderr, result.stderr
        flat = _flat(result.stderr)
        assert "the two keys disagree" in flat, (
            f"every direction gets the one reason that fits it:\n{flat}"
        )
        assert "cannot be told" not in flat, (
            f"the history already told which side moved — neither:\n{flat}"
        )
        listed = result.stderr.count(f"overrides {VENDOR_REPO}/sw")
        assert listed == 1, f"one override, {listed} entries:\n{result.stderr}"

    def test_the_same_release_spelled_twice_over_a_clean_commit_is_silent(
        self, consumer: Path
    ):
        _, sha = _init_vendor_git(consumer, "sw", "1.5.0")
        _override(consumer, "sw", "1.5", synced_from=f"{VENDOR_REPO} x ({sha})")
        assert _doctor(consumer).stderr.strip() == ""


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
