"""#260 — version equality checks the stamp, so #63 came back at a constant version.

[#238] closed the gap that let a *stale* override reintroduce [#63], and its
proposal 1 shipped: `doctor.sh` reads each override's `overrides:` target and
warns when `metadata.version` has fallen behind the vendor's.

That detector catches **staleness**. It cannot catch **divergence at the same
version**. `CannObserv/cannabis.observer-wordpress` overrides `shipping-work-php`
at `version: "1.1"` against a vendor also at `1.1` — the doctor exited 0,
correctly by its own contract — while the override's Step 1 had replaced
upstream's `bash "<SKILL_SCRIPTS>/pre-ship.sh"` with `bash scripts/pre-ship.sh`
for all six scripts, plus a note asserting the substitution was safe because the
scripts `cd "$(git rev-parse --show-toplevel)"`. The premise is true and beside
the point: that resolves the root the scripts *operate on*, not the path `bash`
uses to *open the file*. It is #63 exactly, and it shipped under an honest stamp.

`version:` records the vendor version last synced from. The failure mode is not
"someone forgot to bump it" — it is "someone synced from 1.1 and, in the same
edit, replaced upstream text with something worse". Nothing in a stamp
comparison ever looks at content.

Divergence is also the **expected** state: an override exists to differ, so the
check cannot simply diff and warn on any difference. That is presumably why
version comparison was chosen, and it is a reasonable first cut. What closes the
remaining hole is the vendor naming the small set that is *not* optional:

    <!-- skill:required -->
    ```bash
    …the fragment…
    ```

The marker arms the fenced block that follows it. An override must carry each
armed block, compared insensitive to whitespace; everything else in the file is
the override's own business.

A second detector needs no vendor cooperation at all, and is the one that would
have caught this report where it arrived from — a human code review noticing a
broken command rather than any tooling flagging it. `TestNoBareScriptPaths` gates
`bash scripts/X.sh` out of every SKILL.md **in this repo**. Nothing gated it in a
consumer's override, which is the one file the vendor's suite cannot reach and
the doctor can.

What this file pins:

- **Every SKILL.md carrying the resolution block marks it required.** A fence
  nobody applied is a mechanism that detects nothing.
- **A marker arms a fenced block, and only the block.** Prose is legitimately
  reworded; a fragment check over prose flags every honest edit.
- **The check runs at a MATCHING version.** Behind the drift verdict it would
  sit on the far side of the `continue` that #260 is about.
- **A faithful override, reflowed, stays silent.** A whitespace-sensitive check
  is a check consumers turn off.
- **A vendor that marks nothing says nothing.** No fence is a vendor making no
  claim, which is not the same as an override satisfying every claim made.
- **Both findings are advisory.** Same call as the drift check and the
  silent-fork check beside them (#238, #256): re-syncing an override is debt an
  operator pays down on a schedule, and a probe that failed on it would push
  consumers toward deleting overrides rather than repairing them.

Two follow-ups from the first consumer the pair ran against, `CannObserv/cli`,
where both fired on the same override in the same run:

- **#265 — an omission can be deliberate.** That override ships no `scripts/`
  directory at all, so the `<SKILL_SCRIPTS>` block resolves nothing there.
  Re-syncing it would put a runnable-looking fence into a file where running it
  fails, which is #63 arriving through the remedy, and the whole delta is
  `SKILL.md`, so there is nothing to reduce to per-file symlinks. A marker now
  carries `id=<slug>` and an override declares one by id in
  `metadata.omits-required` — a declaration that names a fragment rather than
  muting the check, so a block armed in a later release still reports.
- **#266 — `scripts/` at the project root belongs to the project.** The
  bare-script check read a consumer's own `scripts/setup-worktree.sh` as the
  skill's, and offered a `<SKILL_SCRIPTS>` substitution with nothing to
  substitute. The doctor's cwd is the project root, so the report is skipped
  when the named path exists there.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
DOCTOR = SKILLS_DIR / "managing-skills" / "scripts" / "doctor.sh"

# The idded form every marker in this repo carries since #265. The id is what a
# consumer names to declare one fragment deliberately inapplicable, so a vendor
# that arms an un-idded block leaves its consumers no move but to paste it back
# or fork away from it.
MARKER = "<!-- skill:required id=skill-scripts -->"
MARKER_RE = re.compile(
    r"^<!--\s*skill:required(?:\s+id=(?P<id>[A-Za-z0-9][A-Za-z0-9._-]*))?\s*-->$"
)

# The line that identifies the #63 resolution block, shared with
# test_content_invariants.py's RESOLUTION_LOOP.
RESOLUTION_LOOP = (
    'for d in scripts ".claude/skills/$N/scripts" '
    '"$HOME/.claude/skills/$N/scripts"; do'
)

SKILLS_WITH_RESOLUTION = sorted(
    p for p in SKILLS_DIR.glob("*/SKILL.md") if RESOLUTION_LOOP in p.read_text()
)


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — a linked worktree shares .git/config
    with its main checkout, so a fixture-creating git command that inherits
    them reaches out of the fixture and writes the wrong repo (#189)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


class TestTheVendorMarksWhatIsNotOptional:
    """The fence is applied where dropping the block reintroduces #63."""

    def test_the_mechanism_has_something_to_check(self) -> None:
        assert SKILLS_WITH_RESOLUTION, (
            "no SKILL.md carries the resolution block any more; if that is "
            "deliberate, this whole file is describing a fix nobody needs"
        )

    @pytest.mark.parametrize(
        "skill_md", SKILLS_WITH_RESOLUTION,
        ids=lambda p: p.parent.name,
    )
    def test_the_resolution_block_is_marked_required(self, skill_md: Path) -> None:
        lines = skill_md.read_text().splitlines()
        loop = next(i for i, l in enumerate(lines) if RESOLUTION_LOOP in l)
        opener = max(i for i in range(loop) if lines[i].startswith("```"))
        marked = MARKER_RE.match(lines[opener - 1].strip())
        assert marked, (
            f"{skill_md.relative_to(SKILLS_DIR)}'s <SKILL_SCRIPTS> resolution "
            f"block is not preceded by {MARKER}. An override that drops it "
            "reintroduces #63, and a version: stamp cannot see that — which is "
            "how #63 came back a second time under a version that matched "
            "exactly (#260)."
        )
        assert marked.group("id"), (
            f"{skill_md.relative_to(SKILLS_DIR)} arms the resolution block "
            "without an id=. A consumer that cannot run it — an override "
            "shipping no scripts/ at all — can then only paste back a fence "
            "that fails or fork away from the skill, because a declaration "
            "names a fragment by its id (#265)."
        )

    @pytest.mark.parametrize(
        "skill_md", sorted(SKILLS_DIR.glob("*/SKILL.md")),
        ids=lambda p: p.parent.name,
    )
    def test_every_marker_arms_a_fenced_block(self, skill_md: Path) -> None:
        """A marker followed by prose claims nothing and reads as if it does."""
        lines = skill_md.read_text().splitlines()
        for i, line in enumerate(lines):
            if not MARKER_RE.match(line.strip()):
                continue
            following = next(
                (l for l in lines[i + 1:] if l.strip()), "",
            )
            assert following.startswith("```"), (
                f"{skill_md.relative_to(SKILLS_DIR)}:{i + 1} arms nothing — "
                f"{MARKER} marks the fenced block that follows it, and the "
                f"next non-blank line is {following.strip()[:60]!r}. The "
                "doctor disarms on prose, so this claim would be silently "
                "dropped."
            )

    @pytest.mark.parametrize(
        "skill_md", sorted(SKILLS_DIR.glob("*/SKILL.md")),
        ids=lambda p: p.parent.name,
    )
    def test_every_marker_is_well_formed_and_named(self, skill_md: Path) -> None:
        """A near-miss marker arms nothing, and says nothing about that.

        The doctor matches the marker exactly; `<!-- skill:required id= -->` or
        a stray attribute simply fails to arm, so a vendor's strongest claim
        about its own file becomes a comment. And a marker with no id cannot be
        declared inapplicable by a consumer at all (#265), which is what the
        second assertion is for.
        """
        seen: dict[str, int] = {}
        for i, line in enumerate(skill_md.read_text().splitlines()):
            if "skill:required" not in line:
                continue
            marked = MARKER_RE.match(line.strip())
            assert marked, (
                f"{skill_md.relative_to(SKILLS_DIR)}:{i + 1} looks like a "
                f"required-fragment marker and is not one: {line.strip()!r}. "
                f"The exact form is {MARKER}; anything else arms nothing and "
                "reads as if it armed something."
            )
            fid = marked.group("id")
            assert fid, (
                f"{skill_md.relative_to(SKILLS_DIR)}:{i + 1} arms a fragment "
                "with no id=. A consumer for whom the fragment cannot apply "
                "has no way to say so (#265)."
            )
            assert fid not in seen, (
                f"{skill_md.relative_to(SKILLS_DIR)}:{i + 1} reuses id="
                f"{fid}, already armed at line {seen[fid]}. A declaration "
                "naming it would resolve to two fragments and excuse whichever "
                "the doctor reached first."
            )
            seen[fid] = i + 1


class _ConsumerFixture:
    """A consumer repo with one vendored skill and one override of it.

    Not named Test*, so pytest does not collect it — three classes below build
    the same shape and a second copy of it would be a place for them to
    disagree about what "an override" looks like.
    """

    def _consumer(self, tmp_path: Path, override_body: str,
                  vendor_body: str | None = None,
                  override_version: str = "1.1",
                  override_meta: str = "",
                  project_files: tuple[str, ...] = ()) -> Path:
        repo = tmp_path / "consumer"
        vendor = repo / "skills-vendor/acme-skills/skills/demo"
        vendor.mkdir(parents=True)
        local = repo / "skills/demo"
        local.mkdir(parents=True)
        for rel in project_files:
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("#!/usr/bin/env bash\necho project-owned\n")
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True,
                       capture_output=True, env=_clean_env(), timeout=60)

        if vendor_body is None:
            vendor_body = (
                "# Demo\n\n"
                f"{MARKER}\n"
                "```bash\n"
                "N=demo S=pre-ship.sh SD=\n"
                'for d in scripts ".claude/skills/$N/scripts"; do\n'
                '  [ -f "$d/$S" ] && { SD="$d"; break; }\n'
                "done\n"
                "```\n"
            )
        (vendor / "SKILL.md").write_text(
            "---\nname: demo\ndescription: d\nmetadata:\n"
            '  version: "1.1"\n---\n\n' + vendor_body
        )
        (local / "SKILL.md").write_text(
            "---\nname: demo\ndescription: d\nmetadata:\n"
            f'  version: "{override_version}"\n'
            "  overrides: acme-skills/demo\n"
            "  override-reason: local paths\n"
            + override_meta
            + "---\n\n" + override_body
        )
        return repo

    def _doctor(self, repo: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(DOCTOR), "--no-preflight"], cwd=str(repo),
            capture_output=True, text=True, env=_clean_env(), timeout=120,
        )


class TestTheDoctorReadsTheContent(_ConsumerFixture):
    """Fixtures reproducing the report, and the two states that must stay quiet."""

    def test_a_dropped_fragment_is_reported_at_a_matching_version(
        self, tmp_path: Path,
    ) -> None:
        """The reported case: an honest stamp over content that lost the fix."""
        repo = self._consumer(tmp_path, "# Demo\n\n```bash\nbash scripts/pre-ship.sh\n```\n")
        result = self._doctor(repo)
        assert "fallen behind" not in result.stderr, (
            "the fixture is only interesting while the version check is quiet"
        )
        assert "marks as required" in result.stderr, (
            "the override dropped a fenced-required block and nothing said so "
            "— #238's scenario reached at a constant version (#260)"
        )

    def test_a_faithful_override_is_silent_even_reflowed(self, tmp_path: Path) -> None:
        """Whitespace is not content.

        An override that re-indents a block it kept verbatim has dropped
        nothing, and a check that says otherwise is one consumers switch off.
        """
        repo = self._consumer(tmp_path, (
            "# Demo override\n\n"
            "```bash\n"
            "N=demo    S=pre-ship.sh   SD=\n"
            '  for d in scripts ".claude/skills/$N/scripts"; do\n'
            '      [ -f "$d/$S" ] && { SD="$d"; break; }\n'
            "  done\n"
            "```\n\n"
            "Local deltas below.\n"
        ))
        result = self._doctor(repo)
        assert "marks as required" not in result.stderr, result.stderr

    def test_a_vendor_that_marks_nothing_reports_nothing(self, tmp_path: Path) -> None:
        repo = self._consumer(
            tmp_path,
            "# Demo override\n\nEntirely our own text.\n",
            vendor_body="# Demo\n\n```bash\nsomething\n```\n",
        )
        result = self._doctor(repo)
        assert "marks as required" not in result.stderr, (
            "an upstream that fences nothing is making no claim; reporting one "
            "would flag every override of every skill in the cohort"
        )

    def test_a_bare_script_path_is_reported_without_any_fence(
        self, tmp_path: Path,
    ) -> None:
        """The detector that needs no vendor cooperation.

        This is the one that would have caught the report where it actually
        arrived from, and it works against a vendor that has adopted nothing.
        """
        repo = self._consumer(
            tmp_path,
            "# Demo override\n\n```bash\nbash scripts/pre-ship.sh\n```\n",
            vendor_body="# Demo\n\nNo fences here.\n",
        )
        result = self._doctor(repo)
        assert "resolves from nowhere" in result.stderr
        assert "bash scripts/pre-ship.sh" in result.stderr

    def test_prose_warning_against_the_pattern_is_not_a_finding(
        self, tmp_path: Path,
    ) -> None:
        """CR round 1, finding 3.

        A whole-file grep reported an override carrying upstream's own "never
        write `bash scripts/X.sh`" note as committing the defect it warns
        about — the false positive landing on the most careful override there
        is. Only a fenced code block is scanned now, which is where both real
        occurrences of #63 lived and where the string is an instruction to
        execute rather than a citation of one.
        """
        repo = self._consumer(
            tmp_path,
            "# Demo override\n\n"
            "Never write `bash scripts/X.sh` — the agent's cwd is the project "
            "root (#63).\nUse the resolved placeholder form instead.\n",
            vendor_body="# Demo\n\nNo fences here.\n",
        )
        assert "resolves from nowhere" not in self._doctor(repo).stderr

    def test_the_locator_is_copy_pasteable(self, tmp_path: Path) -> None:
        """`path:line`, like the fork and seam reports beside it."""
        repo = self._consumer(
            tmp_path,
            "# Demo override\n\n```bash\nbash scripts/pre-ship.sh\n```\n",
            vendor_body="# Demo\n\nNo fences here.\n",
        )
        stderr = self._doctor(repo).stderr
        assert re.search(r"skills/demo/SKILL\.md:\d+\s+bash scripts/pre-ship\.sh",
                         stderr), stderr

    def test_both_findings_stay_advisory(self, tmp_path: Path) -> None:
        """Same call as the drift and silent-fork checks beside them.

        A probe that failed here would push consumers toward deleting an
        override rather than repairing it — the outcome #238 explicitly did not
        want, and the reason its own detector warns rather than exits.
        """
        repo = self._consumer(tmp_path, "# Demo\n\n```bash\nbash scripts/x.sh\n```\n")
        assert self._doctor(repo).returncode == 0
        result = subprocess.run(
            ["bash", str(DOCTOR), "--no-preflight", "--check-only"],
            cwd=str(repo), capture_output=True, text=True,
            env=_clean_env(), timeout=120,
        )
        assert result.returncode == 0, (
            "--check-only now fails on override content drift. That mode gates "
            "damage and wiring gaps (#231); doc-sync debt is neither."
        )

    def test_the_report_names_the_override_and_the_target(self, tmp_path: Path) -> None:
        repo = self._consumer(tmp_path, "# Demo\n\nnothing kept\n")
        stderr = self._doctor(repo).stderr
        assert "skills/demo/SKILL.md" in stderr
        assert "acme-skills/demo" in stderr, (
            "the finding must name which parent was diverged from — the vendor "
            "prefix is what disambiguates two vendored sources shipping the "
            "same skill name"
        )


class TestADeliberateOmissionCanBeDeclared(_ConsumerFixture):
    """#265 — a fragment can be inapplicable, and the check could not hear it.

    `CannObserv/cli` overrides `using-git-worktrees` and ships **no `scripts/`
    directory at all**: it fixes the worktree root at `.worktrees/<branch-slug>/`
    and enforces it from a project-owned script that refuses any other path. The
    `<SKILL_SCRIPTS>` resolution loop resolves nothing there, so the omission is
    deliberate and both offered remedies made the file worse — pasting the
    fragment back puts a fence that cannot succeed into a skill file, which is
    #63 arriving through the remedy, and "drop the override for per-file
    symlinks" has nothing to apply to when the whole delta *is* `SKILL.md`.

    The check was already satisfiable by dead text: it is a whole-file substring
    search, so pasting the block under a "not used here" heading silenced it.
    The declaration is the honest version of that move, and it is the escape
    hatch `check_silent_forks` already offers one check away (`.skills/forked-ok`).

    What makes it a declaration rather than a mute is the **id**: it names one
    fragment, so a block armed in a later release still reports against a file
    that already carries a declaration.
    """

    def test_a_declared_fragment_is_not_reported(self, tmp_path: Path) -> None:
        repo = self._consumer(
            tmp_path,
            "# Demo override\n\nThis project ships none of those scripts.\n",
            override_meta=(
                '  omits-required: "skill-scripts: this project ships no '
                'scripts/ at all"\n'
            ),
        )
        result = self._doctor(repo)
        assert "marks as required" not in result.stderr, result.stderr
        assert "excuses nothing" not in result.stderr, result.stderr

    def test_a_declaration_covers_only_the_fragment_it_names(
        self, tmp_path: Path,
    ) -> None:
        """The property that keeps a declaration from rotting into a blanket mute.

        A vendor arming a second fragment in a later release must still be heard
        by a file that already declares the first.
        """
        vendor_body = (
            "# Demo\n\n"
            f"{MARKER}\n```bash\nthe first fragment\n```\n\n"
            "<!-- skill:required id=env-load -->\n"
            "```bash\nthe newly armed fragment\n```\n"
        )
        repo = self._consumer(
            tmp_path, "# Demo override\n\nNeither block is here.\n",
            vendor_body=vendor_body,
            override_meta='  omits-required: "skill-scripts: no scripts here"\n',
        )
        stderr = self._doctor(repo).stderr
        assert "the newly armed fragment" in stderr, (
            "a declaration naming skill-scripts excused a fragment it does not "
            "name — that is a blanket mute, which is how the check rots (#265)"
        )
        assert "the first fragment" not in stderr, stderr
        assert "missing (id=env-load)" in stderr, (
            "the finding must print the id to declare, or the remedy cannot be "
            f"followed: {stderr}"
        )

    def test_a_declaration_matching_no_armed_fragment_is_reported(
        self, tmp_path: Path,
    ) -> None:
        """A vendor that renames or drops a fragment voids the declaration.

        Left unreported, the line goes on reading — to the next person — as a
        decision taken, while covering nothing at all.
        """
        repo = self._consumer(
            tmp_path, "# Demo override\n\nnothing kept\n",
            override_meta='  omits-required: "worktree-root: not used here"\n',
        )
        stderr = self._doctor(repo).stderr
        assert "excuses nothing" in stderr, stderr
        assert "id=worktree-root — the vendor arms no such fragment" in stderr, stderr
        assert "missing (id=skill-scripts)" in stderr, (
            "the fragment the declaration failed to name is still omitted, and "
            f"must still be reported: {stderr}"
        )

    def test_a_declaration_for_a_fragment_the_override_carries_is_reported(
        self, tmp_path: Path,
    ) -> None:
        """Re-syncing the fragment leaves the mute behind."""
        repo = self._consumer(
            tmp_path,
            "# Demo override\n\n```bash\n"
            "N=demo S=pre-ship.sh SD=\n"
            'for d in scripts ".claude/skills/$N/scripts"; do\n'
            '  [ -f "$d/$S" ] && { SD="$d"; break; }\n'
            "done\n```\n",
            override_meta='  omits-required: "skill-scripts: not used here"\n',
        )
        stderr = self._doctor(repo).stderr
        assert "id=skill-scripts — already carried by the override" in stderr, \
            stderr

    def test_a_declaration_without_a_reason_is_reported_and_still_excuses(
        self, tmp_path: Path,
    ) -> None:
        """The ids are what the check needs; the warrant is what the reader needs.

        Refusing to honour an unexplained declaration would leave the operator
        with two findings for one line and no way to clear either in one edit,
        so it is honoured — and an unexplained mute is exactly the thing that
        rots, so it is reported.
        """
        repo = self._consumer(
            tmp_path, "# Demo override\n\nnothing kept\n",
            override_meta='  omits-required: "skill-scripts"\n',
        )
        stderr = self._doctor(repo).stderr
        assert "carries no reason after the id" in stderr, stderr
        assert "marks as required" not in stderr, stderr

    def test_one_broken_declaration_is_one_finding(self, tmp_path: Path) -> None:
        """A declaration wrong in two ways is still one line in the file."""
        repo = self._consumer(
            tmp_path, "# Demo override\n\nnothing kept\n",
            override_meta='  omits-required: "worktree-root"\n',
        )
        stderr = self._doctor(repo).stderr
        assert "carries no reason after the id" not in stderr, (
            "the missing warrant is only worth saying when the ids are sound; "
            f"here the id names nothing, which is the finding: {stderr}"
        )
        assert "the vendor arms no such fragment" in stderr, stderr

    def test_a_declaration_written_as_prose_is_one_finding(
        self, tmp_path: Path,
    ) -> None:
        """CR round 1, finding 2.

        The grammar puts the ids first, so a value written as plain English —
        the likeliest first mistake with a new key — parses as a word per id.
        One line per word was seven findings for one line, which is what teaches
        a reader to skim a report.
        """
        repo = self._consumer(
            tmp_path, "# Demo override\n\nnothing kept\n",
            override_meta='  omits-required: "we ship no scripts here at all"\n',
        )
        stderr = self._doctor(repo).stderr
        lines = [l for l in stderr.splitlines()
                 if "the vendor arms no such fragment" in l]
        assert len(lines) == 1, (
            f"one declaration produced {len(lines)} findings: {stderr}"
        )
        assert "id=we, ship, no, scripts, here, at, all" in lines[0], lines[0]
        assert "a reason written before the colon parses as ids" in stderr, (
            "nothing matched and there were several tokens, which is the shape "
            f"of a reason written where the ids go — say so: {stderr}"
        )

    def test_a_repeated_id_is_one_declaration(self, tmp_path: Path) -> None:
        repo = self._consumer(
            tmp_path, "# Demo override\n\nnothing kept\n",
            override_meta='  omits-required: "nope, nope: stale twice over"\n',
        )
        stderr = self._doctor(repo).stderr
        assert stderr.count("the vendor arms no such fragment") == 1, stderr
        assert "id=nope —" in stderr, stderr

    def test_an_unidded_fragment_cannot_be_declared(self, tmp_path: Path) -> None:
        """A vendor that arms an anonymous block leaves no move but to carry it.

        Reported as `no id` rather than silently un-declarable, because the
        remedy is upstream's — add an `id=` — and the operator has to be told
        which side of the vendor boundary it lives on.
        """
        repo = self._consumer(
            tmp_path, "# Demo override\n\nnothing kept\n",
            vendor_body=(
                "# Demo\n\n<!-- skill:required -->\n"
                "```bash\nan anonymous fragment\n```\n"
            ),
            override_meta='  omits-required: "skill-scripts: no scripts here"\n',
        )
        stderr = self._doctor(repo).stderr
        assert "missing (no id)" in stderr, stderr
        assert "cannot be declared until its vendor names it" in stderr, stderr

    def test_the_declaration_findings_stay_advisory(self, tmp_path: Path) -> None:
        repo = self._consumer(
            tmp_path, "# Demo override\n\nnothing kept\n",
            override_meta='  omits-required: "worktree-root: stale"\n',
        )
        assert self._doctor(repo).returncode == 0
        result = subprocess.run(
            ["bash", str(DOCTOR), "--no-preflight", "--check-only"],
            cwd=str(repo), capture_output=True, text=True,
            env=_clean_env(), timeout=120,
        )
        assert result.returncode == 0, (
            "--check-only now fails on a stale declaration. That mode gates "
            "damage and wiring gaps (#231); a declaration is doc-sync debt."
        )


class TestAProjectOwnedScriptIsNotTheSkills(_ConsumerFixture):
    """#266 — `scripts/` at the project root belongs to the project.

    The bare-script check reads any fenced `bash scripts/X.sh` as the #63 shape,
    and could not tell the skill's `scripts/` from the consumer's own. It
    reported `CannObserv/cli`'s `bash scripts/setup-worktree.sh` — a
    project-owned script, run from a step that has just `cd`'d into the worktree
    — with a remedy (`bash "<SKILL_SCRIPTS>/setup-worktree.sh"`) that has no
    correct substitution to make: that placeholder resolves to a skill directory
    and the override ships no `scripts/` at all.

    The doctor's cwd is the project root, so the distinguishing fact is directly
    testable, and precise in both directions. It also covers the copy the vendor
    already blesses — `using-git-worktrees` says "a project-local `scripts/` copy
    wins if one exists", which this check would have flagged the moment anyone
    spelled it out.
    """

    def test_a_project_owned_script_is_not_reported(self, tmp_path: Path) -> None:
        repo = self._consumer(
            tmp_path,
            "# Demo override\n\n`cd` into the worktree and run:\n\n"
            "```bash\nbash scripts/setup-worktree.sh\n```\n",
            vendor_body="# Demo\n\nNo fences here.\n",
            project_files=("scripts/setup-worktree.sh",),
        )
        assert "resolves from nowhere" not in self._doctor(repo).stderr

    def test_a_path_that_exists_nowhere_still_reports(self, tmp_path: Path) -> None:
        """#63's own shape is unchanged: a skill's scripts/ is not at the root."""
        repo = self._consumer(
            tmp_path,
            "# Demo override\n\n```bash\nbash scripts/pre-ship.sh\n```\n",
            vendor_body="# Demo\n\nNo fences here.\n",
            project_files=("scripts/setup-worktree.sh",),
        )
        stderr = self._doctor(repo).stderr
        assert "resolves from nowhere" in stderr, stderr
        assert "bash scripts/pre-ship.sh" in stderr, stderr
        assert "setup-worktree" not in stderr, (
            "one project-owned script does not exempt the file it appears in; "
            f"the two lines are judged separately: {stderr}"
        )

    def test_the_report_says_why_a_sibling_line_is_absent(
        self, tmp_path: Path,
    ) -> None:
        """A finding that lists one of two identical-looking lines must say so.

        Otherwise the reader's next move is to grep the file, find the other
        one, and conclude the detector is unreliable.
        """
        repo = self._consumer(
            tmp_path,
            "# Demo override\n\n```bash\nbash scripts/setup-worktree.sh\n"
            "bash scripts/pre-ship.sh\n```\n",
            vendor_body="# Demo\n\nNo fences here.\n",
            project_files=("scripts/setup-worktree.sh",),
        )
        stderr = self._doctor(repo).stderr
        assert "EXISTS at the project root" in stderr, stderr

    def test_every_invocation_on_a_line_is_judged(self, tmp_path: Path) -> None:
        """CR round 1, finding 1.

        The exemption is about an instruction, and a line can carry two. Judging
        only the first made a project-owned script at the head of a line launder
        a broken one behind it — a false negative the exemption introduced,
        since the line reported unconditionally before it.
        """
        repo = self._consumer(
            tmp_path,
            "# Demo override\n\n```bash\n"
            "bash scripts/present.sh && bash scripts/absent.sh\n```\n",
            vendor_body="# Demo\n\nNo fences here.\n",
            project_files=("scripts/present.sh",),
        )
        stderr = self._doctor(repo).stderr
        assert "resolves from nowhere" in stderr, (
            "the second invocation resolves nowhere and the line was exempted "
            f"by the first: {stderr}"
        )

    def test_a_line_whose_every_path_resolves_is_still_quiet(
        self, tmp_path: Path,
    ) -> None:
        repo = self._consumer(
            tmp_path,
            "# Demo override\n\n```bash\n"
            "bash scripts/present.sh && bash scripts/second.sh\n```\n",
            vendor_body="# Demo\n\nNo fences here.\n",
            project_files=("scripts/present.sh", "scripts/second.sh"),
        )
        assert "resolves from nowhere" not in self._doctor(repo).stderr

    def test_a_tilde_fence_is_scanned_like_a_backtick_one(
        self, tmp_path: Path,
    ) -> None:
        """Both fence characters, and a block closes on the one it opened."""
        repo = self._consumer(
            tmp_path,
            "# Demo override\n\n~~~bash\nbash scripts/pre-ship.sh\n~~~\n",
            vendor_body="# Demo\n\nNo fences here.\n",
        )
        assert "resolves from nowhere" in self._doctor(repo).stderr

    def test_the_finding_stays_advisory(self, tmp_path: Path) -> None:
        repo = self._consumer(
            tmp_path,
            "# Demo override\n\n```bash\nbash scripts/pre-ship.sh\n```\n",
            vendor_body="# Demo\n\nNo fences here.\n",
        )
        assert self._doctor(repo).returncode == 0


class TestAMalformedMarkerIsNotSilent(_ConsumerFixture):
    """CR round 1, finding 3 — the id syntax widened the ways to write it wrong.

    A marker that misses the arming form arms nothing, and the silence used to
    be total: the vendor's strongest claim about its own file degraded into a
    comment, with neither side told. This repo's suite can only hold its own
    markers; the doctor is what reads everyone else's.
    """

    def test_a_marker_that_arms_nothing_is_reported(self, tmp_path: Path) -> None:
        repo = self._consumer(
            tmp_path, "# Demo override\n\nnothing kept\n",
            vendor_body=(
                "# Demo\n\n<!-- skill:required id= -->\n"
                "```bash\nfragment one\n```\n\n"
                "<!-- skill:required id=skill scripts -->\n"
                "```bash\nfragment two\n```\n"
            ),
        )
        stderr = self._doctor(repo).stderr
        assert "arms" in stderr and "nothing" in stderr, stderr
        located = re.search(
            r"skills-vendor/acme-skills/skills/demo/SKILL\.md:(\d+)", stderr,
        )
        assert located, f"the finding must name the vendor file and line: {stderr}"
        vendor_lines = (
            repo / "skills-vendor/acme-skills/skills/demo/SKILL.md"
        ).read_text().splitlines()
        assert "skill:required" in vendor_lines[int(located.group(1)) - 1], (
            "the locator points at a line that is not the marker — a report "
            f"nobody can follow: {stderr}"
        )
        assert "id=skill scripts" in stderr, stderr
        assert "fix it upstream" in stderr, (
            "the file belongs to the vendor; a consumer cannot repair a claim "
            f"it does not own: {stderr}"
        )

    def test_prose_about_the_convention_is_not_accused(
        self, tmp_path: Path,
    ) -> None:
        """Only a line that opens with `<!--` is an attempt at a marker.

        A skill documenting the convention mid-sentence is the most careful
        vendor there is, and #260 CR round 1 already spent one false positive
        landing on exactly that kind of file.
        """
        repo = self._consumer(
            tmp_path, "# Demo override\n\nnothing kept\n",
            vendor_body=(
                "# Demo\n\nMark a block with `<!-- skill:required -->` to "
                "require it.\n"
            ),
        )
        assert "arms nothing" not in self._doctor(repo).stderr

    def test_a_tilde_armed_fragment_is_compared(self, tmp_path: Path) -> None:
        """A vendor arming a ~~~ block was making a claim nothing read."""
        repo = self._consumer(
            tmp_path, "# Demo override\n\nnothing kept\n",
            vendor_body=(
                "# Demo\n\n<!-- skill:required id=skill-scripts -->\n"
                "~~~bash\nthe tilde fragment\n~~~\n"
            ),
        )
        stderr = self._doctor(repo).stderr
        assert "the tilde fragment" in stderr, stderr

    def test_a_quoted_fence_does_not_close_the_block(
        self, tmp_path: Path,
    ) -> None:
        """A ``` block quoting a ~~~ line ends where it says it ends."""
        repo = self._consumer(
            tmp_path, "# Demo override\n\nnothing kept\n",
            vendor_body=(
                "# Demo\n\n<!-- skill:required id=skill-scripts -->\n"
                "```markdown\nbefore\n~~~\nafter\n```\n"
            ),
        )
        stderr = self._doctor(repo).stderr
        assert "before ~~~ after" in stderr, (
            f"the armed block was cut short at a quoted fence: {stderr}"
        )

    def test_the_finding_stays_advisory(self, tmp_path: Path) -> None:
        repo = self._consumer(
            tmp_path, "# Demo override\n\nnothing kept\n",
            vendor_body="# Demo\n\n<!-- skill:required id= -->\n```bash\nx\n```\n",
        )
        assert self._doctor(repo).returncode == 0


class TestTheConventionIsWrittenDown:
    """An override author needs to be told the fence exists before diverging."""

    def test_conventions_documents_the_marker(self) -> None:
        text = (REPO_ROOT / "docs" / "CONVENTIONS.md").read_text()
        assert MARKER in text, (
            "docs/CONVENTIONS.md is where AGENTS.md sends an override author, "
            f"and it does not mention {MARKER}. A fence the author never reads "
            "about is a warning they will meet for the first time as a doctor "
            "finding."
        )
        assert re.search(r"#260|issues/260", text), (
            "the convention should carry the issue that produced it, as its "
            "neighbours in that file do"
        )

    def test_conventions_documents_the_declaration(self) -> None:
        """An author meeting the check needs the escape hatch in the same place.

        Without it the only documented remedies are "re-sync" and "drop the
        override", and for an override that ships none of the scripts a block
        resolves, the first pastes back a fence that fails and the second has
        nothing to apply to (#265).
        """
        text = (REPO_ROOT / "docs" / "CONVENTIONS.md").read_text()
        assert "omits-required:" in text, (
            "docs/CONVENTIONS.md documents the required-fragment check without "
            "the one remedy that fits a deliberately inapplicable fragment"
        )
        assert re.search(r"#265|issues/265", text)

    def test_the_override_reference_covers_a_deliberate_omission(self) -> None:
        """`references/local-overrides.md` is where the doctor sends an operator.

        It covered falling behind and re-syncing, and said nothing about an
        override that is *supposed* to omit something.
        """
        text = (
            SKILLS_DIR / "managing-skills" / "references" / "local-overrides.md"
        ).read_text()
        assert "omits-required:" in text, (
            "the reference on override mechanics does not mention the "
            "declaration, so an operator meets it for the first time as a "
            "doctor finding (#265)"
        )
        assert re.search(r"#266|issues/266", text), (
            "the same file should say that a project-owned scripts/ path is "
            "exempt from the bare-script check, since that is the other half "
            "of what an override author writes into a fenced block (#266)"
        )
