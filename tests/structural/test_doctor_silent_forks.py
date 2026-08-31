"""#256 — a vendored file committed as a regular file is a silent fork.

Two vendoring shapes are in cohort use and they are indistinguishable from a
shell: a **whole-directory symlink** at `skills/<name>` (everything beneath it
is upstream by construction), and a real directory of **per-file symlinks** (a
change reaches it file by file). In the second shape, one file committed as
`100644`/`100755` opts out of every future update, permanently, with nothing
reporting it — not `managing-skills`, not `.skills/doctor.sh`, not the
consumer's own tooling.

Measured cost across the 12 skills-vendoring members: one repo carried
`skills/shipping-work-php/scripts/doc-check.sh` as a regular file among five
symlinked siblings, so it still ran the pre-#252 matcher and its own carefully
tailored path list had matched nothing since it was written. Three others
forked `SKILL.md` while symlinking every script beneath it — their scripts
update, the instructions describing those scripts do not, and an agent
following them misreads the new verdict. All four were found by hand-reading a
trees API listing, which is the point: absent a check, the next one is found
the same way or not at all.

What this file pins:

- **A regular file where the vendor ships one is reported**, naming both sides.
- **The three shapes that are NOT forks**: a whole-directory symlink, a
  per-file symlink, and a file the consumer simply does not carry.
- **A declared override is out of scope** — it is local by definition, and its
  staleness is `check_override_drift`'s business (#238). Reporting every file
  in it would bury the real finding.
- **Two ways to declare a deliberate fork**: `pre-ship.sh` by name (upstream
  ships a stub for the bare variant, and docs/STYLE.md blesses a
  project-supplied wrapper), and `.skills/forked-ok` for anything else.
- **Advisory in every mode, including `--check-only`**, and never healed —
  same call as the override-drift warning it sits beside.

Keep this list current — it is the file's index.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCTOR = REPO_ROOT / "skills" / "managing-skills" / "scripts" / "doctor.sh"

VENDOR_REPO = "acme-skills"
FORK_MARKER = "silently forked"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — a linked worktree shares .git/config
    with its main checkout, so a fixture-creating git command that inherits
    them reaches out of the fixture and writes the wrong repo (#189)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _doctor(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(DOCTOR), "--no-preflight", *args],
        cwd=str(repo), capture_output=True, text=True,
        env=_clean_env(), timeout=120,
    )


def _skill_md(name: str, overrides: str | None = None) -> str:
    meta = ["  author: t"]
    if overrides is not None:
        meta.append(f"  overrides: {overrides}")
        meta.append('  override-reason: "sources /etc/consumer/.env"')
        meta.append('  version: "1.4"')
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
    """A consumer whose vendor tree is a plain directory — healthy in every way
    the doctor already checks, so the only signal in any test below is the
    fork one."""
    repo = tmp_path / "consumer"
    (repo / "skills").mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True,
        capture_output=True, text=True, env=_clean_env(), timeout=60,
    )
    return repo


def _vendor_skill(consumer: Path, name: str = "shipping-work") -> Path:
    """The upstream copy: a SKILL.md, two scripts and a reference."""
    skill = consumer / "skills-vendor" / VENDOR_REPO / "skills" / name
    (skill / "scripts").mkdir(parents=True)
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(_skill_md(name))
    (skill / "scripts" / "doc-check.sh").write_text("echo upstream doc-check\n")
    (skill / "scripts" / "pre-ship.sh").write_text("echo upstream stub\n")
    (skill / "references" / "rubric.md").write_text("# rubric\n")
    return skill


def _link(consumer: Path, name: str, rel: str) -> None:
    """Symlink one file of the vendored skill into skills/<name>/, the way a
    per-file vendoring lays it out."""
    dst = consumer / "skills" / name / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    src = consumer / "skills-vendor" / VENDOR_REPO / "skills" / name / rel
    dst.symlink_to(os.path.relpath(src, dst.parent))


def _copy(consumer: Path, name: str, rel: str, body: str = "local\n") -> Path:
    """Commit a regular file where a symlink was expected — the defect."""
    dst = consumer / "skills" / name / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(body)
    return dst


class TestARegularFileIsReported:
    def test_a_forked_script_is_named_with_its_vendor_source(self, consumer: Path):
        _vendor_skill(consumer)
        _link(consumer, "shipping-work", "SKILL.md")
        _copy(consumer, "shipping-work", "scripts/doc-check.sh")
        result = _doctor(consumer)
        assert FORK_MARKER in result.stderr, result.stderr
        assert "skills/shipping-work/scripts/doc-check.sh" in result.stderr, (
            f"the report must name the consumer's file:\n{result.stderr}"
        )
        assert (
            "skills-vendor/acme-skills/skills/shipping-work/scripts/doc-check.sh"
            in result.stderr
        ), (
            "and the vendor file it stopped tracking — an operator restoring "
            f"the symlink needs the target:\n{result.stderr}"
        )

    def test_a_forked_skill_md_is_reported(self, consumer: Path):
        """The shape three cohort members were in: every script symlinked, the
        instructions describing them forked."""
        _vendor_skill(consumer)
        _copy(consumer, "shipping-work", "SKILL.md", _skill_md("shipping-work"))
        _link(consumer, "shipping-work", "scripts/doc-check.sh")
        result = _doctor(consumer)
        assert FORK_MARKER in result.stderr, result.stderr
        assert "skills/shipping-work/SKILL.md" in result.stderr, result.stderr

    def test_the_report_names_the_remedy(self, consumer: Path):
        _vendor_skill(consumer)
        _copy(consumer, "shipping-work", "scripts/doc-check.sh")
        result = _doctor(consumer)
        assert "symlink" in result.stderr, (
            f"the report must say what to do about it:\n{result.stderr}"
        )
        assert ".skills/forked-ok" in result.stderr, (
            "and how to declare a deliberate one, or the only way to silence "
            f"it is to stop reading the output:\n{result.stderr}"
        )

    def test_it_is_advisory_in_both_modes(self, consumer: Path):
        """Same call as the override-drift warning beside it (#238): a fork is
        sync debt an operator pays down on their schedule, and a probe that
        failed on it would push consumers toward deleting the file rather than
        declaring it."""
        _vendor_skill(consumer)
        _copy(consumer, "shipping-work", "scripts/doc-check.sh")
        for args in ((), ("--check-only",)):
            result = _doctor(consumer, *args)
            assert result.returncode == 0, (
                f"doctor {args} exited {result.returncode} on a fork; the "
                f"finding is advisory:\n{result.stderr}"
            )
            assert FORK_MARKER in result.stderr, result.stderr

    def test_the_file_is_not_healed(self, consumer: Path):
        """Report, never repair — a local divergence is sometimes deliberate,
        and the doctor cannot tell which from the file alone."""
        _vendor_skill(consumer)
        forked = _copy(consumer, "shipping-work", "scripts/doc-check.sh",
                       "echo local edit\n")
        _doctor(consumer)
        assert not forked.is_symlink(), "the doctor replaced a local file"
        assert forked.read_text() == "echo local edit\n", (
            "the doctor rewrote a local file it was only supposed to report"
        )


class TestWhatIsNotAFork:
    def test_a_whole_directory_symlink_is_silent(self, consumer: Path):
        """Nothing beneath it can drift — it IS the vendor tree."""
        _vendor_skill(consumer)
        dst = consumer / "skills" / "shipping-work"
        src = consumer / "skills-vendor" / VENDOR_REPO / "skills" / "shipping-work"
        dst.symlink_to(os.path.relpath(src, dst.parent))
        result = _doctor(consumer)
        assert FORK_MARKER not in result.stderr, result.stderr

    def test_a_fully_symlinked_directory_is_silent(self, consumer: Path):
        _vendor_skill(consumer)
        for rel in ("SKILL.md", "scripts/doc-check.sh", "references/rubric.md"):
            _link(consumer, "shipping-work", rel)
        result = _doctor(consumer)
        assert FORK_MARKER not in result.stderr, result.stderr

    def test_a_file_the_consumer_does_not_carry_is_silent(self, consumer: Path):
        """Absent is not forked: a consumer that links only some of a skill's
        files is using less of it, not diverging from it."""
        _vendor_skill(consumer)
        _link(consumer, "shipping-work", "SKILL.md")
        result = _doctor(consumer)
        assert FORK_MARKER not in result.stderr, result.stderr

    def test_a_project_authored_skill_is_silent(self, consumer: Path):
        """No vendor copy of that name — a fork of nothing."""
        _vendor_skill(consumer)
        _copy(consumer, "house-style", "SKILL.md", _skill_md("house-style"))
        result = _doctor(consumer)
        assert FORK_MARKER not in result.stderr, result.stderr

    def test_a_declared_override_is_out_of_scope(self, consumer: Path):
        """An override is local by definition; its staleness is the drift
        check's business (#238). Reporting every file in it would bury the
        real finding under the one case that is always expected."""
        _vendor_skill(consumer)
        _copy(consumer, "shipping-work", "SKILL.md",
              _skill_md("shipping-work", overrides=f"{VENDOR_REPO}/shipping-work"))
        _copy(consumer, "shipping-work", "scripts/doc-check.sh")
        result = _doctor(consumer)
        assert FORK_MARKER not in result.stderr, result.stderr


class TestDeclaringADeliberateFork:
    def test_pre_ship_is_exempt_by_name(self, consumer: Path):
        """Upstream ships a stub for the bare variant, and docs/STYLE.md
        blesses a project-supplied wrapper — so a regular pre-ship.sh is the
        documented shape, not a defect."""
        _vendor_skill(consumer)
        _copy(consumer, "shipping-work", "scripts/pre-ship.sh",
              "echo project gate\n")
        result = _doctor(consumer)
        assert FORK_MARKER not in result.stderr, result.stderr

    def test_a_listed_path_is_silenced(self, consumer: Path):
        _vendor_skill(consumer)
        _copy(consumer, "shipping-work", "scripts/doc-check.sh")
        (consumer / ".skills").mkdir()
        (consumer / ".skills" / "forked-ok").write_text(
            "# tailored for this repo's layout\n\n"
            "skills/shipping-work/scripts/doc-check.sh\n"
        )
        result = _doctor(consumer)
        assert FORK_MARKER not in result.stderr, result.stderr

    def test_a_listed_path_silences_only_itself(self, consumer: Path):
        _vendor_skill(consumer)
        _copy(consumer, "shipping-work", "scripts/doc-check.sh")
        _copy(consumer, "shipping-work", "SKILL.md", _skill_md("shipping-work"))
        (consumer / ".skills").mkdir()
        (consumer / ".skills" / "forked-ok").write_text(
            "skills/shipping-work/scripts/doc-check.sh\n"
        )
        result = _doctor(consumer)
        assert "skills/shipping-work/SKILL.md" in result.stderr, result.stderr
        assert "doc-check.sh" not in result.stderr, (
            f"a declared fork must not be reported:\n{result.stderr}"
        )

    def test_a_list_without_a_trailing_newline_still_matches(self, consumer: Path):
        """The guard doc-check.sh reads .skills/doc-sensitive-paths with: an
        editor that omits the final newline must not silently un-declare the
        last entry."""
        _vendor_skill(consumer)
        _copy(consumer, "shipping-work", "scripts/doc-check.sh")
        (consumer / ".skills").mkdir()
        (consumer / ".skills" / "forked-ok").write_text(
            "skills/shipping-work/scripts/doc-check.sh"
        )
        result = _doctor(consumer)
        assert FORK_MARKER not in result.stderr, result.stderr


class TestTheHelpDocumentsIt:
    def test_help_names_the_check_and_its_escape_hatches(self):
        result = subprocess.run(
            ["bash", str(DOCTOR), "--help"],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "forked" in result.stdout, (
            "--help must describe the fork check — a consumer reading an "
            "unexplained warning has nowhere else to look"
        )
        assert ".skills/forked-ok" in result.stdout, result.stdout
        assert "pre-ship.sh" in result.stdout, result.stdout
