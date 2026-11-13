"""The units the release deploy installs, held to its invariants (deploying-releases, #372).

Copied in by deploying-releases' fresh mode; the repo owns it after. It reads
PROJECT, UNITS_DIR, SERVICE_DIR and HOST_CONFIGS from scripts/deploy_hooks.sh.

- No unit names /home, and none runs uv: a start never syncs, and nothing runs
  the development checkout.
- Every service's WorkingDirectory= is /srv/<project>/live or /dev: that is its
  target, and a -dev name says dev.
- Every file under UNITS_DIR is a unit or a listed host config.
- No unit inlines a secret; none sets the three sandbox options that break a
  service (observo#696).
- On the host, each installed unit equals the live release's copy, never the
  working tree's: a merge not yet deployed is not drift.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "scripts" / "deploy_hooks.sh"


def _config() -> dict[str, str]:
    script = (
        'source "$1"; printf "%s\\n" "$PROJECT" "${SERVICE_DIR:-.}" "${UNITS_DIR:-deploy}"; '
        'for e in "${HOST_CONFIGS[@]}"; do printf "%s\\n" "${e%%=*}"; done'
    )
    lines = subprocess.run(
        ["bash", "-c", script, "_", str(HOOKS)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return {
        "project": lines[0],
        "service_dir": lines[1],
        "units_dir": lines[2],
        "host": lines[3:],
    }


CONFIG = _config()
PROJECT = CONFIG["project"]
UNITS = REPO / CONFIG["service_dir"] / CONFIG["units_dir"]
ROOT = f"/srv/{PROJECT}"
UNIT_NAME = re.compile(rf"^{re.escape(PROJECT)}([-@][\w.@-]*)?\.(service|timer)$")


def units() -> list[Path]:
    return sorted(p for p in UNITS.iterdir() if p.is_file() and UNIT_NAME.match(p.name))


def services() -> list[Path]:
    return [p for p in units() if p.suffix == ".service"]


def directive(path: Path, key: str) -> list[str]:
    return [
        m.group(1).strip()
        for m in re.finditer(rf"^{key}=(.*)$", path.read_text(), flags=re.M)
    ]


def test_there_are_units():
    assert units(), f"no {PROJECT}-*.service or .timer under {UNITS}"


@pytest.mark.parametrize("path", units(), ids=lambda p: p.name)
def test_no_unit_names_home(path):
    body = "\n".join(
        line
        for line in path.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "/home/" not in body


@pytest.mark.parametrize("path", services(), ids=lambda p: p.name)
def test_no_unit_runs_uv(path):
    for line in directive(path, "ExecStart") + directive(path, "ExecStartPre"):
        assert not re.search(r"(^|[/\s-])uv(\s|$)", line), (
            f"{path.name} runs uv: {line}"
        )


@pytest.mark.parametrize(
    "path", [p for p in services() if "@" not in p.name], ids=lambda p: p.name
)
def test_working_directory_is_a_target(path):
    workdirs = [w.lstrip("-") for w in directive(path, "WorkingDirectory")]
    assert workdirs, f"{path.name} has no WorkingDirectory="
    assert workdirs[-1] in (f"{ROOT}/live", f"{ROOT}/dev"), workdirs[-1]
    is_dev = workdirs[-1] == f"{ROOT}/dev"
    assert is_dev == path.stem.endswith("-dev"), (
        f"{path.name}: a -dev name and the dev target go together"
    )


def test_every_file_under_units_dir_is_a_unit_or_a_host_config():
    listed = set(CONFIG["host"])
    for path in sorted(p for p in UNITS.rglob("*") if p.is_file()):
        rel = str(path.relative_to(UNITS))
        assert UNIT_NAME.match(path.name) or rel in listed, (
            f"{rel}: a unit, or a HOST_CONFIGS entry"
        )


@pytest.mark.parametrize("path", services(), ids=lambda p: p.name)
def test_no_secret_inline(path):
    for line in directive(path, "Environment"):
        assert not re.search(r"(KEY|TOKEN|PASSWORD|SECRET)\w*=\S", line, flags=re.I), (
            f"{path.name}: a secret goes through LoadCredential=, not Environment="
        )


@pytest.mark.parametrize("path", services(), ids=lambda p: p.name)
@pytest.mark.parametrize(
    "option", ["ProtectControlGroups", "MemoryDenyWriteExecute", "PrivateUsers"]
)
def test_no_sandbox_option_that_breaks_a_service(path, option):
    assert not directive(path, option), f"{path.name} sets {option}= (observo#696)"


@pytest.mark.parametrize("path", units(), ids=lambda p: p.name)
def test_the_installed_unit_is_the_live_releases(path):
    live = Path(ROOT) / "live" / CONFIG["units_dir"] / path.name
    installed = Path("/etc/systemd/system") / path.name
    if not live.exists():
        pytest.skip(f"not on the host, or {path.name} is not deployed yet: no {live}")
    if not installed.exists():
        pytest.skip(f"{path.name} is in the live release but not installed")
    assert installed.read_bytes() == live.read_bytes(), (
        f"{installed} differs from the live release's copy: deploy, or put back the hand edit"
    )
