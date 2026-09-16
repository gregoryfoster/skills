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
- **Who is NOT warned about.** A symlinked skill tracks upstream by
  construction, and a local directory without `overrides:` is a
  project-authored skill, not a fork of anything.

Keep this list current — it is the file's index.
"""

import os
import re
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


class TestSyncedFromFallbackForUnversionedVendors:
    """obra-superpowers ships no `version:` at all, so an override of one of
    its skills has nothing to compare — the case the field cannot express. The
    `synced-from:` sibling key pins the vendor commit last synced from, and
    the comparison becomes a path-scoped diff between that commit and HEAD:
    drift means the SKILL changed upstream, not that the submodule moved."""

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

    def test_no_change_since_the_recorded_commit_is_silent(self, consumer: Path):
        """The comparison must not fire merely because a commit is recorded."""
        vendor, sha = _init_vendor_git(consumer, "shipping-work", "1.4")
        del vendor
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
