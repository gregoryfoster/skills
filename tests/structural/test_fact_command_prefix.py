"""Behavioral tests for verify-facts.sh's command check (#108).

The defect: a documented command carrying a directory prefix — `cd frontend &&
npm run build`, the normal shape of a monorepo's frontend build — was resolved
against the *root* manifest, so a correct claim was reported FALSE. FALSE is the
skill's only deletion-eligible verdict, so a false FALSE points the deletion
licence at content that is right.

Both directions matter here. A fix that made every prefixed command pass would
trade a false FALSE for a false TRUE, which is worse: the script exists to be
trusted mechanically, and a silent TRUE on a broken command is never caught.
"""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "curating-context"
    / "scripts"
)
VERIFY = SCRIPTS / "verify-facts.sh"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — pre-commit exports GIT_INDEX_FILE and
    friends, which leak into the script's own git calls and confuse them."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env=_clean_env(),
    )


def _repo(tmp_path: Path, policy: str, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    for rel, body in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    (repo / "AGENTS.md").write_text(policy)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _commands(repo: Path) -> dict[str, tuple[str, str]]:
    """Run the verifier; return {claim: (verdict, evidence)} for command rows."""
    result = subprocess.run(
        ["bash", str(VERIFY)],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=60,
    )
    assert result.returncode == 0, f"exited {result.returncode}: {result.stderr}"
    rows = {}
    for row in result.stdout.splitlines():
        parts = row.split("\t")
        assert len(parts) == 5, f"malformed TSV row: {row!r}"
        verdict, cls, _loc, claim, evidence = parts
        if cls == "command":
            rows[claim] = (verdict, evidence)
    return rows


SCRIPTED = '{"scripts": {"build": "vite build", "test": "vitest"}}\n'
UNSCRIPTED = '{"name": "root", "private": true}\n'


class TestCdPrefixedCommands:
    """`cd frontend && npm run build` is the reported case: a root package.json
    with no `build`, and a workspace one that has it."""

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        return _repo(
            tmp_path,
            "\n".join(
                [
                    "# Policy",
                    "",
                    "- Frontend build: `cd frontend && npm run build`",
                    "- Frontend tests: `cd frontend && npm run test`",
                    "- Stale: `cd frontend && npm run bundle`",
                    "- Gone: `cd nosuchdir && npm run build`",
                    "- Bare: `cd docs && npm run build`",
                    "",
                ]
            ),
            {
                "package.json": UNSCRIPTED,
                "frontend/package.json": SCRIPTED,
                "docs/index.md": "# docs\n",
            },
        )

    def test_defined_in_the_prefixed_directory_is_true(self, repo: Path):
        """The regression. `build` lives in frontend/package.json, so the claim
        is correct and must not be reported FALSE."""
        rows = _commands(repo)
        claim = "cd frontend && npm run build"
        assert claim in rows, f"the prefixed command was not checked at all: {rows}"
        verdict, evidence = rows[claim]
        assert verdict == "TRUE", f"{verdict} — {evidence}"
        assert "frontend/package.json" in evidence, evidence

    def test_second_prefixed_command_also_resolves(self, repo: Path):
        rows = _commands(repo)
        verdict, evidence = rows["cd frontend && npm run test"]
        assert verdict == "TRUE", f"{verdict} — {evidence}"

    def test_missing_target_in_an_existing_manifest_is_still_false(self, repo: Path):
        """The other direction: frontend/package.json exists and does not define
        `bundle`, so the manifest refutes the claim. This must stay FALSE."""
        verdict, evidence = _commands(repo)["cd frontend && npm run bundle"]
        assert verdict == "FALSE", f"{verdict} — {evidence}"
        assert "bundle" in evidence and "frontend/package.json" in evidence, evidence

    def test_missing_directory_is_false_and_names_the_directory(self, repo: Path):
        """A `cd` into a directory that does not exist is refuted by the
        checkout, not merely undecidable — but the evidence must blame the
        directory, so the operator fixes the right half of the command."""
        verdict, evidence = _commands(repo)["cd nosuchdir && npm run build"]
        assert verdict == "FALSE", f"{verdict} — {evidence}"
        assert "nosuchdir" in evidence, evidence

    def test_directory_without_a_manifest_is_unverifiable(self, repo: Path):
        """docs/ exists but holds no package.json — nothing refutes the claim,
        so it is UNVERIFIABLE and carries no deletion licence."""
        verdict, evidence = _commands(repo)["cd docs && npm run build"]
        assert verdict == "UNVERIFIABLE", f"{verdict} — {evidence}"
        assert "docs" in evidence, evidence


class TestRootResolutionUnchanged:
    """The prefix work must not disturb the unprefixed path."""

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        return _repo(
            tmp_path,
            "\n".join(
                [
                    "# Policy",
                    "",
                    "- Build: `npm run build`",
                    "- Stale: `npm run bundle`",
                    "- Make: `make check`",
                    "- Missing recipe: `make deploy`",
                    "",
                ]
            ),
            {
                "package.json": SCRIPTED,
                "Makefile": "check:\n\techo ok\n",
            },
        )

    def test_root_manifest_still_confirms(self, repo: Path):
        rows = _commands(repo)
        assert rows["npm run build"][0] == "TRUE", rows["npm run build"]
        assert rows["make check"][0] == "TRUE", rows["make check"]

    def test_root_manifest_still_refutes(self, repo: Path):
        rows = _commands(repo)
        assert rows["npm run bundle"][0] == "FALSE", rows["npm run bundle"]
        assert rows["make deploy"][0] == "FALSE", rows["make deploy"]


class TestBuiltInSubcommandCarveOut:
    """`composer install` and friends are not manifest entries; the carve-out
    must survive prefixing, in a repo whose composer.json would refute them."""

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        return _repo(
            tmp_path,
            "\n".join(
                [
                    "# Policy",
                    "",
                    "- Deps: `composer install`",
                    "- API deps: `cd api && composer install`",
                    "- Yarn: `cd frontend && yarn add`",
                    "",
                ]
            ),
            {
                "composer.json": '{"scripts": {"lint": "phpcs"}}\n',
                "api/composer.json": '{"scripts": {"lint": "phpcs"}}\n',
                "frontend/package.json": SCRIPTED,
            },
        )

    def test_built_ins_are_true_with_and_without_a_prefix(self, repo: Path):
        rows = _commands(repo)
        for claim in (
            "composer install",
            "cd api && composer install",
            "cd frontend && yarn add",
        ):
            verdict, evidence = rows[claim]
            assert verdict == "TRUE", f"{claim}: {verdict} — {evidence}"
            assert evidence == "built-in subcommand", f"{claim}: {evidence}"


class TestOtherDirectoryScopingShapes:
    """A chained `cd`, the parenthesised subshell form, and `make -C` all mean
    the same thing: some other manifest is authoritative."""

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        return _repo(
            tmp_path,
            "\n".join(
                [
                    "# Policy",
                    "",
                    "- Chained: `cd apps && cd web && npm run build`",
                    "- Subshell: `(cd frontend && npm run build)`",
                    "- Scoped make: `make -C frontend dist`",
                    "- Recipe: `cd tools && just release`",
                    "",
                ]
            ),
            {
                "package.json": UNSCRIPTED,
                "Makefile": "all:\n\techo root\n",
                "apps/web/package.json": SCRIPTED,
                "frontend/package.json": SCRIPTED,
                "frontend/Makefile": "dist:\n\techo dist\n",
                "tools/justfile": "release:\n    echo release\n",
            },
        )

    def test_chained_cd_resolves_to_the_deepest_directory(self, repo: Path):
        verdict, evidence = _commands(repo)["cd apps && cd web && npm run build"]
        assert verdict == "TRUE", f"{verdict} — {evidence}"
        assert "apps/web/package.json" in evidence, evidence

    def test_subshell_form_resolves(self, repo: Path):
        rows = _commands(repo)
        claim = next(
            (c for c in rows if c.endswith("cd frontend && npm run build")), None
        )
        assert claim is not None, f"the subshell form was not checked: {rows}"
        verdict, evidence = rows[claim]
        assert verdict == "TRUE", f"{verdict} — {evidence}"

    def test_make_dash_c_resolves_against_that_makefile(self, repo: Path):
        """Today this reports FALSE for a target named `-C`. The root Makefile
        has no `dist`, so root resolution would refute a correct claim."""
        verdict, evidence = _commands(repo)["make -C frontend dist"]
        assert verdict == "TRUE", f"{verdict} — {evidence}"
        assert "frontend/Makefile" in evidence, evidence

    def test_prefixed_just_recipe_resolves(self, repo: Path):
        verdict, evidence = _commands(repo)["cd tools && just release"]
        assert verdict == "TRUE", f"{verdict} — {evidence}"


class TestNonDirectoryPrefixes:
    """An env assignment does not change the working directory, so root
    resolution stays correct — but the claim must still be checked, not dropped
    or mis-parsed into a flag-shaped target."""

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        return _repo(
            tmp_path,
            "\n".join(
                [
                    "# Policy",
                    "",
                    "- Env: `CI=1 npm run build`",
                    "- Flag only: `make -C frontend`",
                    "",
                ]
            ),
            {
                "package.json": SCRIPTED,
                "Makefile": "all:\n\techo root\n",
                "frontend/Makefile": "dist:\n\techo dist\n",
            },
        )

    def test_env_assignment_still_resolves_at_the_root(self, repo: Path):
        rows = _commands(repo)
        claim = next((c for c in rows if c.endswith("npm run build")), None)
        assert claim is not None, f"the env-prefixed command was not checked: {rows}"
        verdict, evidence = rows[claim]
        assert verdict == "TRUE", f"{verdict} — {evidence}"

    def test_a_bare_directory_flag_is_never_reported_false(self, repo: Path):
        """`make -C frontend` names no target. Reporting FALSE for a target
        called `-C` is the same false-FALSE failure in a smaller costume."""
        for claim, (verdict, evidence) in _commands(repo).items():
            if "-C" in claim:
                assert verdict != "FALSE", f"{claim}: {evidence}"
