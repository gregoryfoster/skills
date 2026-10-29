"""`init-project-fastapi` parses env files, never sources them, and its unit
never hands the repo `.env` to production (#517).

Two defects, both copied into every repo the skill scaffolds:

1. Eight `set -a; . …` sites taught a new repo's AGENTS.md, settings errors
   and conftest to load secrets by sourcing. Sourcing runs the file as shell
   code, and `set -a` exports every variable in it, `GH_TOKEN` PATs included,
   to every child process. The `shipping-work*` pre-ship wrappers state the
   opposite rule, so the scaffold contradicted its own gate.
2. The generated unit carried `EnvironmentFile=-<DEPLOY_HOME>/.env`: the
   developer's file, holding `GH_TOKEN` and `ANTHROPIC_API_KEY`, loaded into
   a production process with no use for either.

The replacement is a pointer, not a third copy: the parse-don't-source
`load_env` recipe in `shipping-work-python-fastapi/scripts/pre-ship.sh`'s
header. `TestThePointerRuns` runs the template's load line against that very
recipe, so the pointer cannot name a loader that no longer exists.
"""

import re
import shlex
import subprocess
from pathlib import Path

import pytest

from .test_pre_ship_env_override import _extract_loader

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "init-project-fastapi"
RECIPE_VARIANT = "shipping-work-python-fastapi"
RECIPE = f"skills/{RECIPE_VARIANT}/scripts/pre-ship.sh"
TEMPLATE = SKILL / "references" / "agents-md-template.md"
UNIT_DOC = SKILL / "references" / "systemd-deploy.md"

# Running an env file as shell code: `. file`, `source file`, after a line
# start or a command separator. `>> ./.env` and `grep … ./.env` do not match.
_SOURCES_AN_ENV_FILE = re.compile(r"(?:^|[;&|(`\s])(?:\.|source)\s+\S*\.env\b")
_ENVIRONMENT_FILE = re.compile(r"EnvironmentFile=-?(\S+?)[`\s]")
# The only places a production unit may read env from.
_UNIT_ENV_PREFIXES = ("/etc/<PROJECT_NAME>/", "/run/<PROJECT_NAME>/")


def _skill_lines():
    for path in sorted(SKILL.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            for n, line in enumerate(path.read_text().splitlines(), 1):
                yield path.relative_to(ROOT), n, line


class TestNoFileIsSourced:
    def test_no_set_a(self):
        hits = [f"{p}:{n}" for p, n, ln in _skill_lines() if "set -a" in ln]
        assert not hits, (
            "init-project-fastapi must not teach `set -a`: it exports every "
            f"variable in the sourced file to every child process. Point at the "
            f"load_env recipe in {RECIPE}'s header instead. Sites: {hits}"
        )

    def test_no_env_file_is_sourced(self):
        hits = [
            f"{p}:{n}" for p, n, ln in _skill_lines() if _SOURCES_AN_ENV_FILE.search(ln)
        ]
        assert not hits, (
            "an env file is data: parse it with load_env, never run it with "
            f"`.` or `source`. Sites: {hits}"
        )

    @pytest.mark.parametrize(
        "line",
        [
            "set +a; . /etc/x/.env",
            ". .env",
            "source ~/app/.env",
            '"Load env: (. /etc/<PROJECT_NAME>/.env)"',
        ],
    )
    def test_the_sourcing_detector_fires(self, line):
        assert _SOURCES_AN_ENV_FILE.search(line), line

    @pytest.mark.parametrize(
        "line",
        [
            "cat >> ./.env <<ENV",
            "grep -q '^DATABASE_URL=' ./.env 2>/dev/null",
            "load_env /etc/<PROJECT_NAME>/.env; load_env .env",
        ],
    )
    def test_the_sourcing_detector_spares_reads_and_writes(self, line):
        assert not _SOURCES_AN_ENV_FILE.search(line), line


class TestTheUnitReadsOnlyEtc:
    def test_every_environment_file_is_under_etc_or_run(self):
        hits = []
        for p, n, ln in _skill_lines():
            for path in _ENVIRONMENT_FILE.findall(ln + " "):
                if not path.startswith(_UNIT_ENV_PREFIXES):
                    hits.append(f"{p}:{n}: {path}")
        assert not hits, (
            "a production unit reads /etc/<PROJECT_NAME>/.env (and its own "
            "/run build-id) only. The repo .env is the developer's file, with "
            f"GH_TOKEN and ANTHROPIC_API_KEY in it. Sites: {hits}"
        )

    def test_the_detector_sees_the_removed_line(self):
        assert _ENVIRONMENT_FILE.findall("EnvironmentFile=-<DEPLOY_HOME>/.env\n") == [
            "<DEPLOY_HOME>/.env"
        ]

    def test_the_unit_template_names_its_two_env_files(self):
        unit = UNIT_DOC.read_text().split("```ini", 1)[1].split("```", 1)[0]
        assert re.findall(r"^EnvironmentFile=(\S+)$", unit, re.M) == [
            "-/run/<PROJECT_NAME>/build-id",
            "/etc/<PROJECT_NAME>/.env",
        ]

    @pytest.mark.parametrize(
        "path,stale",
        [
            ("SKILL.md", "three-tier"),
            ("SKILL.md", "repo-`.env` `EnvironmentFile`"),
            ("SKILL.md", "then the repo `.env`"),
            ("references/agents-md-template.md", "loads both"),
            ("references/systemd-deploy.md", "optional repo-local overrides"),
        ],
    )
    def test_no_prose_says_the_unit_loads_the_repo_env(self, path, stale):
        assert stale not in (SKILL / path).read_text(), (
            f"{path} still says the unit loads the repo .env ({stale!r})"
        )


def _template_load_lines() -> list[str]:
    return [
        ln.strip()
        for ln in TEMPLATE.read_text().splitlines()
        if ln.strip().startswith(("load_env ", "# load_env "))
    ]


class TestThePointerRuns:
    def test_the_template_names_the_recipe(self):
        text = TEMPLATE.read_text()
        assert RECIPE in text, f"{TEMPLATE.name} must point at {RECIPE}"
        assert (ROOT / RECIPE).is_file()

    def test_the_recipe_is_still_there_and_liftable(self):
        assert "load_env() {" in _extract_loader(RECIPE_VARIANT)
        assert "safe to lift into a shell" in (ROOT / RECIPE).read_text()

    def test_every_template_load_line_loads_and_prints_nothing(self, tmp_path: Path):
        """The template's own lines, run against the recipe they point at. The
        value is a sentinel and must reach a child, not the transcript."""
        lines = _template_load_lines()
        assert lines, f"{TEMPLATE.name} carries no `load_env …` line to run"
        for line in lines:
            self._loads_and_prints_nothing(line, tmp_path)

    @staticmethod
    def _loads_and_prints_nothing(line: str, tmp_path: Path) -> None:
        secret = "sentinel-not-a-real-token"
        (tmp_path / ".env").write_text(f"# dev\nGH_TOKEN={secret}\n")
        line = line.removeprefix("# ").split("#", 1)[0]
        line = line.replace("<PROJECT_NAME>", "no-such-project-517")
        script = (
            "set -euo pipefail\n"
            + _extract_loader(RECIPE_VARIANT)
            + f"\n{line}\n"
            + 'bash -c \'[ "${GH_TOKEN:-}" = "$0" ]\' '
            + shlex.quote(secret)
            + "\n"
        )
        r = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, cwd=tmp_path
        )
        assert r.returncode == 0, f"{line!r} did not export GH_TOKEN"
        assert secret not in r.stdout + r.stderr, f"{line!r} printed a value"


class TestTheGateIsWrappedNotForked:
    """skill-symlinks.md told a project needing env before its tests to fork
    the vendored pre-ship.sh, the shape #105 retired: a fork stops receiving
    upstream gate fixes without saying so. The recipe is a wrapper."""

    def test_the_pre_ship_override_is_a_wrapper(self):
        doc = SKILL / "references" / "skill-symlinks.md"
        lines = [ln for ln in doc.read_text().splitlines() if "pre-ship.sh" in ln]
        assert lines, f"{doc.name} no longer mentions pre-ship.sh"
        for ln in lines:
            assert "fork only if" not in ln, ln
        assert any("wrapper" in ln and RECIPE in ln for ln in lines), lines
