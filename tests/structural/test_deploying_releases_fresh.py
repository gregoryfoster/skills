"""deploying-releases' fresh mode renders a consumer whose own tests pass (#372).

A fixture consumer is rendered as references/fresh.md says: the core and
hooks template installed, the hooks filled in, the units rendered from
assets/units/, and assets/tests/ copied to tests/deploy/. Its generated tests
must pass as rendered, and each invariant they hold must fail when broken.
Portable: no host tools beyond bash and git.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.structural.deploying_releases_rig import INSTALL, SKILL, clean_env

UNITS = SKILL / "assets" / "units"
TESTS = SKILL / "assets" / "tests"
DEPLOYMENT = SKILL / "assets" / "DEPLOYMENT.md.tmpl"


def render(template: Path, **values: str) -> str:
    text = template.read_text()
    for key, value in values.items():
        text = text.replace(f"<{key}>", value)
    return text


def consumer(tmp: Path) -> Path:
    repo = tmp / "acme"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=clean_env())
    result = subprocess.run(
        ["bash", str(INSTALL), "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=clean_env(),
    )
    assert result.returncode == 0, result.stderr
    hooks = repo / "scripts" / "deploy_hooks.sh"
    text = hooks.read_text().replace('PROJECT="<PROJECT>"', "PROJECT=acme")
    text = text.replace('GITHUB_REPO="<OWNER>/<REPO>"', "GITHUB_REPO=CannObserv/acme")
    text = text.replace(
        "HOST_CONFIGS=()",
        'HOST_CONFIGS=("sysctl.d/60-acme.conf=/etc/sysctl.d/60-acme.conf")',
    )
    hooks.write_text(text)
    deploy = repo / "deploy"
    deploy.mkdir()
    api = render(
        UNITS / "service.tmpl",
        PROJECT="acme",
        NAME="api",
        EXEC_START="uvicorn src.api.main:app --host 127.0.0.1 --port 8000",
    )
    (deploy / "acme-api.service").write_text(api)
    (deploy / "acme-api-dev.service").write_text(
        api.replace("/srv/acme/live", "/srv/acme/dev")
    )
    (deploy / "acme-sweep.service").write_text(
        render(UNITS / "oneshot.tmpl", PROJECT="acme", NAME="sweep", MODULE="src.sweep")
    )
    (deploy / "acme-sweep.timer").write_text(
        render(UNITS / "timer.tmpl", PROJECT="acme", NAME="sweep", INTERVAL="10min")
    )
    (deploy / "sysctl.d").mkdir()
    (deploy / "sysctl.d" / "60-acme.conf").write_text("vm.swappiness = 10\n")
    (repo / "tests" / "deploy").mkdir(parents=True)
    for path in TESTS.glob("test_*.py"):
        shutil.copy(path, repo / "tests" / "deploy" / path.name)
    (repo / "DEPLOYMENT.md").write_text(render(DEPLOYMENT, PROJECT="acme"))
    return repo


def run_tests(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/deploy",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        env=clean_env(),
        timeout=120,
    )


@pytest.fixture
def repo(tmp_path) -> Path:
    return consumer(tmp_path)


def test_the_rendered_consumer_passes_its_own_tests(repo):
    result = run_tests(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed" in result.stdout


def test_no_placeholder_survives_rendering(repo):
    for path in [*(repo / "deploy").glob("acme-*"), repo / "DEPLOYMENT.md"]:
        assert not re.search(r"<[A-Z_]+>", path.read_text()), path.name


def test_the_units_render_onto_the_release_not_the_checkout(repo):
    api = (repo / "deploy" / "acme-api.service").read_text()
    assert "WorkingDirectory=/srv/acme/live" in api
    assert "ExecStart=/srv/acme/live/.venv/bin/uvicorn" in api
    assert "User=acme" in api


BREAKS = {
    "a unit on the checkout": (
        "deploy/acme-api.service",
        lambda t: t.replace(
            "WorkingDirectory=/srv/acme/live", "WorkingDirectory=/home/exedev/acme"
        ),
        "test_no_unit_names_home",
    ),
    "a unit that syncs": (
        "deploy/acme-sweep.service",
        lambda t: t.replace(
            "ExecStart=", "ExecStartPre=/usr/local/bin/uv sync --frozen\nExecStart="
        ),
        "test_no_unit_runs_uv",
    ),
    "a dev unit on live": (
        "deploy/acme-api-dev.service",
        lambda t: t.replace("/srv/acme/dev", "/srv/acme/live"),
        "test_working_directory_is_a_target",
    ),
    "a stray file": (
        "deploy/notes.txt",
        lambda t: "notes\n",
        "test_every_file_under_units_dir_is_a_unit_or_a_host_config",
    ),
    "a timer template the core never installs": (
        "deploy/acme@nightly.timer",
        lambda t: "[Timer]\n",
        "test_every_file_under_units_dir_is_a_unit_or_a_host_config",
    ),
    "an inline secret": (
        "deploy/acme-api.service",
        lambda t: t.replace(
            "Environment=PYTHONDONTWRITEBYTECODE=1", "Environment=API_TOKEN=abc"
        ),
        "test_no_secret_inline",
    ),
    "a sandbox option that breaks a service": (
        "deploy/acme-api.service",
        lambda t: t.replace(
            "LockPersonality=yes", "LockPersonality=yes\nProtectControlGroups=yes"
        ),
        "test_no_sandbox_option_that_breaks_a_service",
    ),
    "an edited core": (
        "scripts/deploy.sh",
        lambda t: t + "# a local fix\n",
        "test_the_core_is_unedited",
    ),
    "a helper in the hooks": (
        "scripts/deploy_hooks.sh",
        lambda t: t + "my_helper() { :; }\n",
        "test_the_hooks_define_only_the_six_hooks",
    ),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_each_invariant_fails_when_broken(repo, name):
    rel, change, test = BREAKS[name]
    path = repo / rel
    path.write_text(change(path.read_text() if path.exists() else ""))
    result = run_tests(repo)
    assert result.returncode == 1, result.stdout
    assert test in result.stdout, result.stdout
