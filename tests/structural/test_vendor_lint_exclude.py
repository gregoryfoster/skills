"""#336 — a consumer is told to keep its tree-walking tools out of skills-vendor/.

`managing-skills` adds `skills-vendor/<owner>-<repo>/` and, before #336, never
said to exclude it from the consumer's linters. `init-project-fastapi` does, so
a project it bootstrapped was covered and a project that adopted skills later
was not. Measured on `CannObserv/status`, retrofitted through managing-skills
v1.15: `ruff check --show-files .` listed 139 vendored files and
`ruff format --check .` read 226 where 88 were its own. Nothing failed that
day. The failure arrives with a refresh, on code the consumer must not edit,
and only in the local command, since CI checks out without submodules.

What this file pins:

- **The issue's own case is reported**: a consumer whose `[tool.ruff]` does not
  exclude `skills-vendor/` gets a doctor warning that names the file and the fix.
- **The fix fits the table**: where the table already has an `extend-exclude`,
  the doctor says to append to it, since a second one is a duplicate key ruff
  refuses (CR 1806).
- **The check reads the config ruff itself reads**: `.ruff.toml`, then
  `ruff.toml`, then `pyproject.toml`'s `[tool.ruff]`. An exclude in
  `[tool.ruff.lint]` does not count, because `ruff format` still reads the
  vendor then [measured, ruff 0.16.6]; nor does the same exclude as a dotted
  `lint.` or `format.` key. Only a header-shaped line opens a table, not a
  line inside an array that starts with `[` (CR 1814).
- **Silent where it has nothing to say**: no `skills-vendor/`, no ruff config,
  an exclude already present, or a comment in the table naming the vendor
  (the documented way to lint it on purpose).
- **Advisory in every mode**: the exit code never moves, `--check-only`
  included.
- **The remedy works**: the line the doctor prints, applied, leaves ruff
  reading no vendored file (skipped without ruff unless `RUFF_REQUIRED=1`).
- **The docs hold together**: SKILL.md Step 1 points at the reference, the
  reference links `init-project-fastapi`'s canonical snippet by a resolving
  link, and that file still carries the settings the reference names.

Keep this list current — it is the file's index.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MS = REPO_ROOT / "skills" / "managing-skills"
DOCTOR = MS / "scripts" / "doctor.sh"
SKILL_MD = MS / "SKILL.md"
REFERENCE = MS / "references" / "excluding-vendored-code.md"
CANONICAL = (
    REPO_ROOT / "skills" / "init-project-fastapi" / "references" / "pyproject-toml.md"
)

VENDOR = "gregoryfoster-skills"
MARKER = "without excluding skills-vendor/"

# The consumer state #336 measured: ruff configured, nothing excluded.
UNEXCLUDED = """\
[project]
name = "status"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP"]
"""

EXCLUDED_MULTILINE = """\
[project]
name = "status"

[tool.ruff]
line-length = 100
extend-exclude = [
    "alembic/versions/",
    "skills-vendor/",
]

[tool.ruff.lint]
select = ["E", "F"]
"""


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — a linked worktree shares .git/config
    with its main checkout, so a fixture-creating git command that inherits
    them reaches out of the fixture and writes the wrong repo (#189)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


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
    """A consumer healthy in every way the doctor already checks, carrying a
    vendored tree with Python in it, so the only signal below is this one."""
    repo = tmp_path / "consumer"
    repo.mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "init", "-q", "-b", "main"],
        check=True,
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=60,
    )
    scripts = repo / "skills-vendor" / VENDOR / "scripts"
    scripts.mkdir(parents=True)
    # Unformatted and unused: a ruff that reads it has something to say.
    (scripts / "measure.py").write_text("import os\nx=1\n")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("x = 1\n")
    return repo


# --------------------------------------------------------------- the issue


class TestTheIssuesCase:
    def test_a_consumer_retrofitted_through_managing_skills_is_told(
        self, consumer: Path
    ):
        """#336 verbatim: `[tool.ruff]` configured, `skills-vendor/` not
        excluded. Before the fix the doctor said nothing about it."""
        (consumer / "pyproject.toml").write_text(UNEXCLUDED)
        result = _doctor(consumer)
        assert result.returncode == 0, result.stderr
        assert MARKER in result.stderr, (
            "the doctor did not report a [tool.ruff] that leaves skills-vendor/ "
            f"to the consumer's ruff:\n{result.stderr}"
        )
        assert "pyproject.toml" in result.stderr
        assert 'extend-exclude = ["skills-vendor/"]' in result.stderr, (
            "the warning must print the line to add, not only name the gap"
        )
        assert "#336" in result.stderr


# A [tool.ruff] that already carries an extend-exclude, without the vendor.
EXTENDS_WITHOUT_VENDOR = """\
[project]
name = "status"

[tool.ruff]
line-length = 100
extend-exclude = ["alembic/versions/"]

[tool.ruff.lint]
select = ["E", "F"]
"""


class TestAnExistingExtendExclude:
    """CR 1806. The remedy printed a literal `extend-exclude = [...]` line even
    where the table already had one; added as printed, that is a duplicate
    TOML key, and ruff refuses the whole file."""

    @pytest.mark.parametrize(
        "cfg, text, where",
        [
            ("pyproject.toml", EXTENDS_WITHOUT_VENDOR, "[tool.ruff] in pyproject.toml"),
            (
                "ruff.toml",
                'line-length = 100\nextend-exclude = [\n    "alembic/",\n]\n',
                "the top level of ruff.toml",
            ),
        ],
        ids=["pyproject", "ruff-toml-multiline"],
    )
    def test_the_remedy_says_append_not_add(self, consumer, cfg, text, where):
        (consumer / cfg).write_text(text)
        result = _doctor(consumer)
        assert result.returncode == 0, result.stderr
        assert MARKER in result.stderr, result.stderr
        assert 'extend-exclude = ["skills-vendor/"]' not in result.stderr, (
            "the doctor told a config that already has extend-exclude to add a "
            f"second one, a duplicate key (CR 1806):\n{result.stderr}"
        )
        flat = " ".join(
            ln.removeprefix("doctor:").strip() for ln in result.stderr.splitlines()
        ).lower()
        assert (
            'append "skills-vendor/" to the existing extend-exclude array in ' + where
            in flat
        ), result.stderr

    def test_a_lint_only_extend_exclude_still_gets_the_line(self, consumer):
        """Only the table the doctor reads counts: an extend-exclude in
        [tool.ruff.lint] is another table's key, so the line to add is still
        right."""
        (consumer / "pyproject.toml").write_text(
            UNEXCLUDED + 'extend-exclude = ["alembic/"]\n'
        )
        result = _doctor(consumer)
        assert 'extend-exclude = ["skills-vendor/"]' in result.stderr, result.stderr


# ------------------------------------------------------- what counts as ruff


class TestTheCheckReadsTheConfigRuffReads:
    def test_an_exclude_in_tool_ruff_is_covered(self, consumer: Path):
        (consumer / "pyproject.toml").write_text(EXCLUDED_MULTILINE)
        result = _doctor(consumer)
        assert MARKER not in result.stderr, result.stderr

    def test_an_exclude_only_in_tool_ruff_lint_is_not(self, consumer: Path):
        """`[tool.ruff.lint] exclude` is lint-only: `ruff format` still reads
        the vendor [measured, ruff 0.16.6]."""
        (consumer / "pyproject.toml").write_text(
            UNEXCLUDED + 'exclude = ["skills-vendor/"]\n'
        )
        result = _doctor(consumer)
        assert MARKER in result.stderr, result.stderr

    def test_a_lint_table_alone_still_configures_ruff(self, consumer: Path):
        (consumer / "pyproject.toml").write_text(
            '[project]\nname = "x"\n\n[tool.ruff.lint]\nselect = ["E"]\n'
        )
        result = _doctor(consumer)
        assert MARKER in result.stderr, result.stderr

    def test_ruff_toml_outranks_pyproject(self, consumer: Path):
        """Ruff reads ruff.toml over pyproject.toml, so an exclude there covers
        a pyproject [tool.ruff] that has none."""
        (consumer / "pyproject.toml").write_text(UNEXCLUDED)
        (consumer / "ruff.toml").write_text(
            'line-length = 100\nextend-exclude = ["skills-vendor/"]\n'
        )
        result = _doctor(consumer)
        assert MARKER not in result.stderr, result.stderr

    def test_dot_ruff_toml_outranks_ruff_toml(self, consumer: Path):
        (consumer / "ruff.toml").write_text('extend-exclude = ["skills-vendor/"]\n')
        (consumer / ".ruff.toml").write_text("line-length = 90\n")
        result = _doctor(consumer)
        assert MARKER in result.stderr, result.stderr
        assert ".ruff.toml" in result.stderr

    def test_a_ruff_toml_exclude_must_be_top_level(self, consumer: Path):
        (consumer / "ruff.toml").write_text(
            'line-length = 90\n\n[lint]\nexclude = ["skills-vendor/"]\n'
        )
        result = _doctor(consumer)
        assert MARKER in result.stderr, result.stderr


class TestOnlyHeaderShapedLinesAreTables:
    """CR 1814. Any line starting `[` was read as a table header, so a line
    inside a multi-line array left the table and the exclude after it went
    unseen: a false warning, against the rule that an over-eager match costs
    a missed warning, never a wrong one. And a dotted `lint.` key inside the
    table counted as covered, though it sets [tool.ruff.lint], which does not
    count in its header form."""

    def test_a_bracket_line_inside_an_array_is_not_a_table(self, consumer):
        # The doctor reads lines, not ruff's schema: what matters is a value
        # line that starts with "[" ahead of the exclude.
        (consumer / "pyproject.toml").write_text(
            '[project]\nname = "x"\n\n[tool.ruff]\nline-length = 100\n'
            'pairs = [\n    ["a", "b"],\n    [1, 2],\n]\n'
            'extend-exclude = ["skills-vendor/"]\n'
        )
        result = _doctor(consumer)
        assert MARKER not in result.stderr, result.stderr

    @pytest.mark.parametrize(
        "header", ["[tool.ruff]  # the linter", "[ tool . ruff ]", "[tool.ruff ]"]
    )
    def test_a_header_with_a_comment_or_spaces_is_still_a_table(self, consumer, header):
        (consumer / "pyproject.toml").write_text(
            f'[project]\nname = "x"\n\n{header}\nline-length = 100\n'
        )
        result = _doctor(consumer)
        assert MARKER in result.stderr, result.stderr

    @pytest.mark.parametrize(
        "cfg, text",
        [
            (
                "pyproject.toml",
                '[tool.ruff]\nline-length = 100\nlint.exclude = ["skills-vendor/"]\n',
            ),
            (
                "pyproject.toml",
                '[tool.ruff]\nlint.exclude = [\n    "skills-vendor/",\n]\n'
                "line-length = 100\n",
            ),
            ("ruff.toml", 'line-length = 100\nlint.exclude = ["skills-vendor/"]\n'),
            (".ruff.toml", 'format.exclude = [\n    "skills-vendor/",\n]\n'),
        ],
        ids=["pyproject-inline", "pyproject-multiline", "ruff-toml", "format"],
    )
    def test_a_dotted_sub_table_key_does_not_cover(self, consumer, cfg, text):
        (consumer / cfg).write_text(text)
        result = _doctor(consumer)
        assert MARKER in result.stderr, (
            f"a dotted sub-table exclude in {cfg} counted as covered (CR 1814):\n"
            + result.stderr
        )

    def test_a_comment_after_a_dotted_array_still_opts_out(self, consumer):
        (consumer / "pyproject.toml").write_text(
            '[tool.ruff]\nlint.select = [\n    "E",\n]\n'
            "# skills-vendor/ is linted on purpose here.\n"
        )
        result = _doctor(consumer)
        assert MARKER not in result.stderr, result.stderr


class TestSilentWhereThereIsNothingToSay:
    def test_no_skills_vendor_directory(self, tmp_path: Path):
        repo = tmp_path / "plain"
        repo.mkdir()
        subprocess.run(
            ["git", "-C", str(repo), "init", "-q", "-b", "main"],
            check=True,
            capture_output=True,
            env=_clean_env(),
            timeout=60,
        )
        (repo / "pyproject.toml").write_text(UNEXCLUDED)
        result = _doctor(repo)
        assert result.returncode == 0, result.stderr
        assert MARKER not in result.stderr, result.stderr

    def test_no_ruff_config_at_all(self, consumer: Path):
        result = _doctor(consumer)
        assert MARKER not in result.stderr, result.stderr

    def test_a_pyproject_that_does_not_configure_ruff(self, consumer: Path):
        (consumer / "pyproject.toml").write_text(
            '[project]\nname = "x"\n\n[tool.pytest.ini_options]\n'
            'testpaths = ["tests"]\n'
        )
        result = _doctor(consumer)
        assert MARKER not in result.stderr, result.stderr

    def test_a_comment_naming_the_vendor_is_the_opt_out(self, consumer: Path):
        (consumer / "pyproject.toml").write_text(
            UNEXCLUDED.replace(
                "[tool.ruff]\n",
                "[tool.ruff]\n# skills-vendor/ is linted on purpose here.\n",
            )
        )
        result = _doctor(consumer)
        assert MARKER not in result.stderr, result.stderr


class TestAdvisoryInEveryMode:
    def test_check_only_reports_and_keeps_its_exit_code(self, consumer: Path):
        """--check-only is the CI probe; a lint gap is not damage it gates on."""
        (consumer / "pyproject.toml").write_text(UNEXCLUDED)
        result = _doctor(consumer, "--check-only")
        assert result.returncode == 0, result.stderr
        assert MARKER in result.stderr, result.stderr

    def test_reported_once_per_run(self, consumer: Path):
        (consumer / "pyproject.toml").write_text(UNEXCLUDED)
        result = _doctor(consumer)
        assert result.stderr.count(MARKER) == 1, result.stderr


# ------------------------------------------------------- the remedy, in ruff


def _find_ruff() -> str | None:
    """The running interpreter's own ruff first, then PATH — the order
    test_python_lint.py uses, for the reason it gives."""
    candidate = Path(sys.executable).parent / "ruff"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return shutil.which("ruff")


_RUFF = _find_ruff()
_RUFF_REQUIRED = os.environ.get("RUFF_REQUIRED", "") not in ("", "0")


def _ruff(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_RUFF, *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=60,
        env={**_clean_env(), "RUFF_NO_CACHE": "true"},
    )


class TestTheRemedyWorks:
    @pytest.fixture(autouse=True)
    def _need_ruff(self):
        if _RUFF is None:
            if _RUFF_REQUIRED:
                pytest.fail("ruff not found and RUFF_REQUIRED is set")
            pytest.skip("ruff not found; RUFF_REQUIRED=1 makes this a failure")

    def test_the_printed_line_keeps_ruff_out_of_the_vendor(self, consumer: Path):
        (consumer / "pyproject.toml").write_text(UNEXCLUDED)

        before = _ruff(consumer, "check", "--show-files", ".")
        assert "skills-vendor" in before.stdout, (
            "precondition: #336's ruff reads the vendored tree\n" + before.stdout
        )
        assert _ruff(consumer, "format", "--check", ".").returncode == 1, (
            "precondition: ruff format reads the unformatted vendored file"
        )

        warning = _doctor(consumer).stderr
        line = re.search(r'extend-exclude = \["skills-vendor/"\]', warning)
        assert line, warning
        (consumer / "pyproject.toml").write_text(
            UNEXCLUDED.replace(
                'target-version = "py312"\n',
                'target-version = "py312"\n' + line.group(0) + "\n",
            )
        )

        after = _ruff(consumer, "check", "--show-files", ".")
        assert after.returncode == 0, after.stderr
        assert "skills-vendor" not in after.stdout, after.stdout
        assert "src/app.py" in after.stdout, "the project's own code still linted"

        fmt = _ruff(consumer, "format", "--check", ".")
        assert fmt.returncode == 0, fmt.stdout + fmt.stderr

        assert MARKER not in _doctor(consumer).stderr

    def test_the_append_works_where_a_second_line_would_not(self, consumer: Path):
        """CR 1806, in ruff: the old remedy beside an existing extend-exclude
        is a duplicate key ruff refuses, and the append the doctor now asks
        for keeps ruff out of the vendor."""
        existing = 'extend-exclude = ["alembic/versions/"]\n'
        (consumer / "pyproject.toml").write_text(
            EXTENDS_WITHOUT_VENDOR.replace(
                existing, existing + 'extend-exclude = ["skills-vendor/"]\n'
            )
        )
        dup = _ruff(consumer, "check", ".")
        assert dup.returncode == 2 and "duplicate key" in dup.stderr, (
            "precondition: ruff refuses a duplicate extend-exclude\n" + dup.stderr
        )

        (consumer / "pyproject.toml").write_text(
            EXTENDS_WITHOUT_VENDOR.replace(
                '["alembic/versions/"]', '["alembic/versions/", "skills-vendor/"]'
            )
        )
        after = _ruff(consumer, "check", "--show-files", ".")
        assert after.returncode == 0, after.stderr
        assert "skills-vendor" not in after.stdout, after.stdout
        assert MARKER not in _doctor(consumer).stderr


# ---------------------------------------------------------------- the docs


def _step_1(text: str) -> str:
    start = text.index("#### Step 1")
    return text[start : text.index("#### Step 2", start)]


class TestTheDocsHoldTogether:
    def test_step_1_points_at_the_reference(self):
        step = _step_1(SKILL_MD.read_text())
        assert "(references/excluding-vendored-code.md)" in step, (
            "managing-skills Step 1 adds the submodule; the pointer to excluding "
            "it from the project's tools belongs right there (#336)"
        )

    def test_the_reference_links_the_canonical_snippet(self):
        text = REFERENCE.read_text()
        links = re.findall(r"\]\(([^)#\s]*pyproject-toml\.md)(?:#[^)]*)?\)", text)
        assert links, "the reference must link init-project-fastapi's snippet"
        for link in links:
            target = (REFERENCE.parent / link).resolve()
            assert target == CANONICAL.resolve(), f"{link} resolves to {target}"

    @pytest.mark.parametrize(
        "needle",
        [
            'extend-exclude = ["skills-vendor/"]',
            "[tool.ty.src]",
            'exclude = ["skills-vendor/"]',
            'testpaths = ["tests"]',
        ],
    )
    def test_the_canonical_file_still_carries_what_the_reference_names(
        self, needle: str
    ):
        assert needle in CANONICAL.read_text(), (
            f"{CANONICAL.relative_to(REPO_ROOT)} no longer carries {needle!r}, "
            "which managing-skills' excluding-vendored-code.md points readers at"
        )

    def test_the_doctor_names_a_reference_that_exists(self):
        names = set(re.findall(r"references/([a-z0-9-]+\.md)", DOCTOR.read_text()))
        assert "excluding-vendored-code.md" in names
        for name in names:
            assert (MS / "references" / name).is_file(), name
