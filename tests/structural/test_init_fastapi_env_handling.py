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

import hashlib
import re
import subprocess
from pathlib import Path

import pytest

from .test_context_surface import _clean_env
from .test_env_file_names import _checkout_with_worktree
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
# A path, not the bare `EnvironmentFile=` that prose names (private-wheelhouse.md).
_ENVIRONMENT_FILE = re.compile(r"EnvironmentFile=-?([^`\s]+)")
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
        assert _ENVIRONMENT_FILE.findall("`EnvironmentFile=-%h/app/.env`") == [
            "%h/app/.env"
        ]

    def test_the_detector_skips_a_bare_mention(self):
        assert _ENVIRONMENT_FILE.findall("from an `EnvironmentFile=` that") == []

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


# The template's one line that defines `load_env` from the recipe, in place
# (CR 1044). The recipe stays the only copy of the loader.
EXTRACT = f"eval \"$(sed -n 's/^#   //; /^load_env() [{{]/,/^[}}]/p' {RECIPE})\""
SENTINEL = "sentinel-not-a-real-token"


def _template_load_blocks() -> list[str]:
    """Each command in the template that loads env: from the EXTRACT line to
    its `load_env` line, as an agent pastes it into one tool call. Scanned by
    line rather than by fence, since the template sits in an outer fence."""
    blocks, block = [], []
    for ln in TEMPLATE.read_text().splitlines():
        if ln.startswith("eval ") or block:
            block.append(ln)
        if block and ln.startswith("load_env "):
            blocks.append("\n".join(block))
            block = []
    assert blocks, f"{TEMPLATE.name} carries no load command to run"
    return blocks


def _copy_recipe(checkout: Path) -> None:
    """A consuming repo reaches the recipe through its skills/ symlink."""
    dest = checkout / RECIPE
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text((ROOT / RECIPE).read_text())


def _run_block(block: str, cwd: Path) -> subprocess.CompletedProcess:
    """In a fresh shell, as an agent's tool call is: no load_env defined."""
    script = (
        "set -euo pipefail\n"
        + block.replace("<PROJECT_NAME>", "no-such-project-517")
        + '\nbash -c \'printf "%s" "${GH_TOKEN:-}" | sha256sum\''
    )
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=_clean_env(),
        timeout=60,
    )


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class TestThePointerRuns:
    def test_the_template_names_the_recipe(self):
        text = TEMPLATE.read_text()
        assert RECIPE in text, f"{TEMPLATE.name} must point at {RECIPE}"
        assert (ROOT / RECIPE).is_file()

    def test_the_recipe_is_still_there_and_liftable(self):
        assert "load_env() {" in _extract_loader(RECIPE_VARIANT)
        assert "safe to lift into a shell" in (ROOT / RECIPE).read_text()

    def test_the_extraction_defines_the_recipes_loader(self, tmp_path: Path):
        """The template's EXTRACT line, run against the real pre-ship.sh. If
        the recipe's indentation or braces move, this goes red, so the line
        and the recipe cannot drift apart unseen (CR 1044)."""
        assert EXTRACT in TEMPLATE.read_text().splitlines(), (
            f"{TEMPLATE.name} no longer carries the extraction line"
        )
        env_file = tmp_path / ".env"
        env_file.write_text(f"# dev\nGH_TOKEN={SENTINEL}\n")
        r = _run_block(f"{EXTRACT}\nload_env {env_file}", ROOT)
        assert r.returncode == 0, r.stderr
        assert r.stdout.split()[0] == _sha(SENTINEL), "load_env did not load it"
        assert SENTINEL not in r.stdout + r.stderr


class TestTheTemplateLoadsInOneCommand:
    """CR 1044: an agent's Bash tool starts a fresh shell per call, so "define
    load_env once per shell" meant pasting a 17-line function before every
    command, and in practice `set -a; .` again. Each template command now
    defines the loader from the recipe in place, loads, and runs.

    CR 1043: `load_env .env` loaded nothing in a linked worktree, silently,
    since load_env returns 0 on a missing file. The commands fall back to the
    primary checkout's `.env` as the recipe's ENV_FILE lines do: the
    checkout's own file first, else the primary's."""

    def test_every_load_command_starts_with_the_extraction(self):
        blocks = _template_load_blocks()
        assert len(blocks) >= 4, (
            "expected the dev-server, both Environment Variables variants and "
            f"Common Commands to carry a load command; found {len(blocks)}"
        )
        for block in blocks:
            assert block.splitlines()[0] == EXTRACT, block

    def test_it_says_to_run_it_in_the_same_command(self):
        assert "same command" in TEMPLATE.read_text()

    def test_it_no_longer_says_once_per_shell(self):
        assert "once per shell" not in TEMPLATE.read_text()

    def _layout(self, tmp_path: Path) -> tuple[Path, Path]:
        main, worktree = _checkout_with_worktree(tmp_path)
        (main / ".env").write_text(f"# dev\nGH_TOKEN={SENTINEL}\n")
        for checkout in (main, worktree):
            _copy_recipe(checkout)
        return main, worktree

    def test_each_command_loads_in_the_primary(self, tmp_path: Path):
        main, _ = self._layout(tmp_path)
        for block in _template_load_blocks():
            r = _run_block(block, main)
            assert r.returncode == 0, block + "\n" + r.stderr
            assert r.stdout.split()[0] == _sha(SENTINEL), block
            assert SENTINEL not in r.stdout + r.stderr, block

    def test_each_command_finds_the_primarys_env_from_a_worktree(self, tmp_path: Path):
        _, worktree = self._layout(tmp_path)
        assert not (worktree / ".env").exists()
        for block in _template_load_blocks():
            r = _run_block(block, worktree)
            assert r.returncode == 0, block + "\n" + r.stderr
            assert r.stdout.split()[0] == _sha(SENTINEL), (
                f"a linked worktree loaded nothing:\n{block}"
            )
            assert SENTINEL not in r.stdout + r.stderr, block

    def test_a_worktrees_own_env_wins_as_in_the_recipe(self, tmp_path: Path):
        _, worktree = self._layout(tmp_path)
        (worktree / ".env").write_text("GH_TOKEN=the-worktrees-own\n")
        for block in _template_load_blocks():
            r = _run_block(block, worktree)
            assert r.returncode == 0, block + "\n" + r.stderr
            assert r.stdout.split()[0] == _sha("the-worktrees-own"), block


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


class TestTheRationaleIsTrue:
    """CR 1038: load_env exports what it loads, as `set -a` does, so the
    template's reason to parse must be the one that holds: sourcing runs the
    file as shell code."""

    def test_it_does_not_claim_parsing_avoids_exporting(self):
        text = TEMPLATE.read_text()
        assert "hands every secret in it to every child process" not in text
        assert "runs a file as shell code" in text
        assert "`load_env` exports" in text, (
            "say plainly that load_env exports what it loads"
        )


# A variable whose name says it holds a secret (#530). Anchored at the end so
# `KEY_PATH`, `P_TOKENS` and git-config key names stay out.
_SECRET_NAME = re.compile(
    r"(?:^|_)(?:PG)?(?:PW|PASS|PASSWD|PASSWORD|SECRET|TOKEN|PAT|API_KEY|"
    r"SECRET_KEY|PRIVATE_KEY)$",
    re.I,
)
# An expansion of a variable's value: `$X` or `${X…}`, but not `${#X}`, which
# expands to its length, and not an escaped `\$X`.
_EXPANSION = re.compile(r"(?<!\\)\$(?:\{(?!#))?([A-Za-z_][A-Za-z0-9_]*)")
# One echo/printf command, up to the next separator: `;`, `&&`, `||` or `|`.
_PRINT_CMD = re.compile(
    r"\b(?:echo|printf)\b(?P<args>(?:[^;&|]|&(?!&))*)(?P<end>\|\|?|;|&&|$)"
)


def _echoed_secrets(line: str) -> list[str]:
    """The secret-named variables a line prints to the terminal. Output piped
    to a command (`printf '%s' "$TOKEN" | gh auth login --with-token`) or
    redirected to a file never reaches the transcript, so it is spared;
    `>&2` still prints."""
    found = []
    for m in _PRINT_CMD.finditer(line):
        if m["end"] == "|" or re.search(r">>?\s*(?!&)\S", m["args"]):
            continue
        found += [v for v in _EXPANSION.findall(m["args"]) if _SECRET_NAME.search(v)]
    return found


class TestNoSecretIsEchoed:
    """#530: postgres-provisioning.md § 3 echoed the role password it had just
    generated, into the agent's transcript and every log that keeps it. Step 5
    already writes it to `.env`. No file in the skill prints a secret-holding
    variable's value; its length (`${#PG_PW}`) is fine."""

    def test_no_file_echoes_a_secret_variable(self):
        hits = [
            f"{p}:{n}: {', '.join(vs)}"
            for p, n, ln in _skill_lines()
            if (vs := _echoed_secrets(ln))
        ]
        assert not hits, (
            "a secret printed to the terminal lands in the transcript. Print "
            f"that it is set and its length, never its value. Sites: {hits}"
        )

    @pytest.mark.parametrize(
        "line,var",
        [
            ('echo "PG_PW=$PG_PW   # save this"', "PG_PW"),
            ('printf "%s\\n" "${GH_TOKEN}"', "GH_TOKEN"),
            ('echo "key: ${ANTHROPIC_API_KEY:-unset}" >&2', "ANTHROPIC_API_KEY"),
            ("echo $PGPASSWORD", "PGPASSWORD"),
            ('test -n "$X" && echo "pw $DB_PASSWORD"', "DB_PASSWORD"),
            ('echo "$SECRET_KEY" || true', "SECRET_KEY"),
            ('echo "$PG_PW" 2>/dev/null', "PG_PW"),  # CR 1189: stderr only
        ],
    )
    def test_the_detector_fires(self, line, var):
        assert _echoed_secrets(line) == [var], line

    @pytest.mark.parametrize(
        "line",
        [
            'echo "PG_PW set (${#PG_PW} chars)"',
            'PGPASSWORD="$PG_PW" psql -h localhost -c "SELECT 1;"',
            "printf '%s' \"$GH_TOKEN\" | gh auth login --with-token",
            'echo "$PG_PW" > ./pw.txt',
            'echo "$PG_PW" 1>>./pw.txt',
            'echo "$PG_PW" &>./pw.txt',
            'echo "Key already exists at $KEY_PATH — skipping generation."',
            'echo "GATE over budget: $P_TOKENS tokens"',
            'echo "set git config: $DRIVER_KEY=$DRIVER_VALUE"',
            'echo "no variable: \\$PG_PW"',
        ],
    )
    def test_the_detector_spares_lengths_pipes_files_and_non_secrets(self, line):
        assert _echoed_secrets(line) == [], line
