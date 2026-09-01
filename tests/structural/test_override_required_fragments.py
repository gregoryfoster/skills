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
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
DOCTOR = SKILLS_DIR / "managing-skills" / "scripts" / "doctor.sh"

MARKER = "<!-- skill:required -->"

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
        assert lines[opener - 1].strip() == MARKER, (
            f"{skill_md.relative_to(SKILLS_DIR)}'s <SKILL_SCRIPTS> resolution "
            f"block is not preceded by {MARKER}. An override that drops it "
            "reintroduces #63, and a version: stamp cannot see that — which is "
            "how #63 came back a second time under a version that matched "
            "exactly (#260)."
        )

    @pytest.mark.parametrize(
        "skill_md", sorted(SKILLS_DIR.glob("*/SKILL.md")),
        ids=lambda p: p.parent.name,
    )
    def test_every_marker_arms_a_fenced_block(self, skill_md: Path) -> None:
        """A marker followed by prose claims nothing and reads as if it does."""
        lines = skill_md.read_text().splitlines()
        for i, line in enumerate(lines):
            if line.strip() != MARKER:
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


class TestTheDoctorReadsTheContent:
    """Fixtures reproducing the report, and the two states that must stay quiet."""

    def _consumer(self, tmp_path: Path, override_body: str,
                  vendor_body: str | None = None,
                  override_version: str = "1.1") -> Path:
        repo = tmp_path / "consumer"
        vendor = repo / "skills-vendor/acme-skills/skills/demo"
        vendor.mkdir(parents=True)
        local = repo / "skills/demo"
        local.mkdir(parents=True)
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
            "  override-reason: local paths\n---\n\n" + override_body
        )
        return repo

    def _doctor(self, repo: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(DOCTOR), "--no-preflight"], cwd=str(repo),
            capture_output=True, text=True, env=_clean_env(), timeout=120,
        )

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
