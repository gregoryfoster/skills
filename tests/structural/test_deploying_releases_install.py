"""deploying-releases' install.sh and the core's own marker (#372).

The core is installed into a consumer as a copy, never run from skills-vendor/,
so an upgrade is a diff in the consumer's tree. Two markers make that hold: the
version on line 2, and a sha256 of the file with its own digest zeroed, so a
consumer's test (and `install.sh --check`) can tell a hand edit from the
shipped core without the vendor checkout. Portable: runs on macOS too.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

import pytest

from tests.structural.deploying_releases_rig import CORE, INSTALL, TEMPLATE, clean_env

MARK_SHA = "# deploying-releases-core-sha256: "
ZEROS = "0" * 64


def body_sha(text: str) -> str:
    zeroed = re.sub(rf"^{re.escape(MARK_SHA)}.*$", MARK_SHA + ZEROS, text, flags=re.M)
    return hashlib.sha256(zeroed.encode()).hexdigest()


def recorded_sha(text: str) -> str:
    return re.search(rf"^{re.escape(MARK_SHA)}(\S+)$", text, flags=re.M).group(1)


def install(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALL), "--repo", str(repo), *args],
        capture_output=True,
        text=True,
        env=clean_env(),
        timeout=60,
    )


@pytest.fixture
def repo(tmp_path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=clean_env())
    return tmp_path


class TestTheCoresOwnMarker:
    def test_line_two_names_the_version(self):
        assert (
            CORE.read_text().splitlines()[1] == "# deploying-releases-core: version 1"
        )

    def test_the_recorded_sha256_is_the_files_own(self):
        text = CORE.read_text()
        assert recorded_sha(text) == body_sha(text), (
            "assets/deploy.sh changed without re-stamping its marker. Set line 3 to "
            f"{MARK_SHA}{body_sha(text)}"
        )

    def test_the_core_is_executable(self):
        assert CORE.stat().st_mode & 0o111


class TestInstall:
    def test_installs_the_core_and_the_hooks_template(self, repo):
        result = install(repo)
        assert result.returncode == 0, result.stderr
        assert result.stdout == "installed\t-\t1\n"
        assert (repo / "scripts" / "deploy.sh").read_bytes() == CORE.read_bytes()
        assert (repo / "scripts" / "deploy.sh").stat().st_mode & 0o111
        assert (
            repo / "scripts" / "deploy_hooks.sh"
        ).read_text() == TEMPLATE.read_text()

    def test_a_second_install_is_current_and_writes_nothing(self, repo):
        install(repo)
        hooks = repo / "scripts" / "deploy_hooks.sh"
        hooks.write_text("PROJECT=mine\n")
        result = install(repo)
        assert result.returncode == 0 and result.stdout == "current\t1\t1\n"
        assert hooks.read_text() == "PROJECT=mine\n"

    def test_an_older_core_is_updated(self, repo):
        older = CORE.read_text().replace("version 1", "version 0", 1)
        older = older.replace(recorded_sha(older), body_sha(older), 1)
        (repo / "scripts").mkdir()
        (repo / "scripts" / "deploy.sh").write_text(older)
        assert install(repo, "--check").stdout == "drift\t0\t1\n"
        result = install(repo)
        assert result.returncode == 0 and result.stdout == "updated\t0\t1\n"
        assert (repo / "scripts" / "deploy.sh").read_bytes() == CORE.read_bytes()

    def test_a_repos_own_deploy_is_refused_without_replace(self, repo):
        (repo / "scripts").mkdir()
        own = repo / "scripts" / "deploy.sh"
        own.write_text("#!/usr/bin/env bash\necho mine\n")
        result = install(repo)
        assert result.returncode == 2 and result.stdout.startswith("foreign\t")
        assert own.read_text().endswith("echo mine\n")
        result = install(repo, "--replace")
        assert result.returncode == 0 and own.read_bytes() == CORE.read_bytes()

    def test_a_hand_edited_core_is_refused(self, repo):
        install(repo)
        core = repo / "scripts" / "deploy.sh"
        core.write_text(core.read_text() + "# a local fix\n")
        result = install(repo)
        assert result.returncode == 2 and result.stdout.startswith("edited\t1\t")
        assert core.read_text().endswith("# a local fix\n")
        assert "deploy_hooks.sh" in result.stderr


class TestCheck:
    @pytest.mark.parametrize(
        ("setup", "state"),
        [
            ("none", "missing"),
            ("own", "foreign"),
            ("edited", "edited"),
        ],
    )
    def test_anything_but_current_exits_1(self, repo, setup, state):
        scripts = repo / "scripts"
        if setup == "own":
            scripts.mkdir()
            (scripts / "deploy.sh").write_text("#!/usr/bin/env bash\n")
        elif setup == "edited":
            install(repo)
            (scripts / "deploy.sh").write_text(
                (scripts / "deploy.sh").read_text() + "#\n"
            )
        result = install(repo, "--check")
        assert result.returncode == 1 and result.stdout.split("\t")[0] == state

    def test_current_exits_0_and_changes_nothing(self, repo):
        install(repo)
        before = sorted(p.name for p in (repo / "scripts").iterdir())
        result = install(repo, "--check")
        assert result.returncode == 0 and result.stdout == "current\t1\t1\n"
        assert sorted(p.name for p in (repo / "scripts").iterdir()) == before

    def test_check_never_writes_the_template(self, repo):
        install(repo, "--check")
        assert not (repo / "scripts").exists()


def test_the_template_parses_as_bash():
    result = subprocess.run(
        ["bash", "-n", str(TEMPLATE)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_the_template_names_every_hook_the_core_defaults():
    core = CORE.read_text()
    template = TEMPLATE.read_text()
    defaults = re.findall(r"^(\w+)\(\) \{ (?::|return 2); \}$", core, flags=re.M)
    assert sorted(defaults) == sorted(
        [
            "build_extra",
            "post_build_check",
            "pre_switch_check",
            "migrate",
            "verify",
            "post_verify",
        ]
    )
    for name in defaults:
        assert re.search(rf"^{name}\(\) \{{", template, flags=re.M), (
            f"the template lacks {name}()"
        )
