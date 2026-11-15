"""deploying-releases' fresh mode renders a consumer whose own tests pass (#372).

A fixture consumer is rendered as references/fresh.md says: the core and
hooks template installed, the hooks filled in, the units rendered from
assets/units/, and assets/tests/ copied to tests/deploy/. Its generated tests
must pass as rendered, and each invariant they hold must fail when broken.
Portable: no host tools beyond bash and git.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.structural.deploying_releases_rig import INSTALL, SKILL, clean_env
from tests.utils.nested_pytest import nested_pytest_env

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
    (deploy / "acme-migrate@.service").write_text(
        render(UNITS / "migrate@.tmpl", PROJECT="acme")
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
        # The nested scrub (#554); its temp root beside the consumer, in the
        # calling test's tmp_path.
        env=nested_pytest_env(repo.parent, clean_env()),
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


def systemd_argv(line: str, instance: str) -> list[str]:
    """An ExecStart= value as systemd execs it: split, then %i, %% and $$ resolved.
    A bare $ or % is refused: systemd would expand it before the shell saw it."""
    assert "$" not in line.replace("$$", ""), f"a bare $ systemd expands: {line}"
    assert not re.search(r"%[^i%]", line.replace("%%", "")), f"a bare %: {line}"
    specifier = {"i": instance, "%": "%"}
    return [
        re.sub(r"%([i%])", lambda m: specifier[m.group(1)], word).replace("$$", "$")
        for word in shlex.split(line)
    ]


MIGRATE_RUNS = {
    "current or ahead": (0, 0, False),
    "behind": (3, 0, True),
    "a failed upgrade": (3, 1, True),
    "an error": (2, 2, False),
}


@pytest.mark.parametrize("case", sorted(MIGRATE_RUNS))
def test_the_migrate_template_upgrades_only_when_behind(tmp_path, case):
    state_rc, want_rc, upgrades = MIGRATE_RUNS[case]
    unit = render(UNITS / "migrate@.tmpl", PROJECT="acme")
    (exec_start,) = re.findall(r"^ExecStart=(.*)$", unit, flags=re.M)
    sha = "0123456789ab"
    release = tmp_path / "releases" / sha
    venv = release / ".venv" / "bin"
    venv.mkdir(parents=True)
    log = tmp_path / "calls"
    for name, rc in (("python", state_rc), ("alembic", 1 if want_rc == 1 else 0)):
        (venv / name).write_text(f'#!/bin/sh\necho "{name} $*" >>"{log}"\nexit {rc}\n')
        (venv / name).chmod(0o755)
    argv = [
        w.replace("/srv/acme", str(tmp_path)) for w in systemd_argv(exec_start, sha)
    ]
    result = subprocess.run(argv, cwd=release, env={"PATH": os.defpath})
    calls = log.read_text().splitlines()
    assert result.returncode == want_rc
    assert calls[0] == "python -m src.core.schema_state"
    assert calls[1:] == (["alembic upgrade head"] if upgrades else [])


def test_a_journal_stdout_still_passes(repo):
    api = repo / "deploy" / "acme-api.service"
    api.write_text(
        api.read_text().replace("Type=simple", "Type=simple\nStandardOutput=journal")
    )
    result = run_tests(repo)
    assert result.returncode == 0, result.stdout + result.stderr


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
    "a service with no start limit": (
        "deploy/acme-api.service",
        lambda t: t.replace("StartLimitBurst=10\n", ""),
        "test_a_long_running_service_caps_its_restarts_in_unit",
    ),
    "a start limit in [Service], which systemd ignores": (
        "deploy/acme-api-dev.service",
        lambda t: t.replace("StartLimitIntervalSec=300\n", "").replace(
            "[Service]\n", "[Service]\nStartLimitIntervalSec=300\n"
        ),
        "test_a_long_running_service_caps_its_restarts_in_unit",
    ),
    "a start limit turned off": (
        "deploy/acme-api.service",
        lambda t: t.replace("StartLimitIntervalSec=300", "StartLimitIntervalSec=0"),
        "test_a_long_running_service_caps_its_restarts_in_unit",
    ),
    "a start limit turned off with a unit": (
        "deploy/acme-api.service",
        lambda t: t.replace("StartLimitIntervalSec=300", "StartLimitIntervalSec=0s"),
        "test_a_long_running_service_caps_its_restarts_in_unit",
    ),
    "a priority prefix journald keeps": (
        "deploy/acme-sweep.service",
        lambda t: t.replace("Type=oneshot", "Type=oneshot\nSyslogLevelPrefix=no"),
        "test_stdout_is_the_journal_and_its_prefix_is_stripped",
    ),
    "stdout that is not the journal": (
        "deploy/acme-api.service",
        lambda t: t.replace("Type=simple", "Type=simple\nStandardOutput=null"),
        "test_stdout_is_the_journal_and_its_prefix_is_stripped",
    ),
    "a migration from another release": (
        "deploy/acme-migrate@.service",
        lambda t: t.replace(
            "WorkingDirectory=/srv/acme/releases/%i",
            "WorkingDirectory=/srv/acme/releases/0123456789ab",
        ),
        "test_a_template_runs_a_target_or_the_release_its_instance_names",
    ),
    "a migration that runs the live release's code": (
        "deploy/acme-migrate@.service",
        lambda t: t.replace("exec /srv/acme/releases/%i/", "exec /srv/acme/live/"),
        "test_a_template_runs_a_target_or_the_release_its_instance_names",
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
