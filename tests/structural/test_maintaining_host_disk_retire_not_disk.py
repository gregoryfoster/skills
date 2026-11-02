"""#548 — a unit known not to be disk tooling is reported apart, not offered.

power-map's `power-map-prune` runs `uv run python -m scripts.prune --execute`,
which deletes database rows past their TTL (tombstones, the request log) and
touches no disk. Its name matches LOOKALIKE's `prune`, so retire-check.sh
offered it, and its timer, as candidates to retire beside the GC. The
not-disk list names it with the reason, and the check reports it under
`not_disk` so the operator still sees it. Only a unit with that name *and*
nothing but that command qualifies: anything else stays a candidate.

The unit text is power-map's own (infra/, at 8d6de1e8), comments dropped.
"""

import os
import re

import pytest

from tests.structural import maintaining_host_disk_rig as rig

RETIRE = rig.SCRIPTS / "retire-check.sh"
SYSD = "etc/systemd/system"

PRUNE_SERVICE = """\
[Unit]
Description=power-map TTL prune: bare-delete tombstones, request log (#204, #502, #651)
After=network.target

[Service]
Type=oneshot
User=exedev
WorkingDirectory=/home/exedev/power-map
EnvironmentFile=/etc/power-map/.env
ExecStart=uv run python -m scripts.prune --execute
Environment=STATUS_MONITOR_ID=01M4RF3TS7HK2PMZFQ3P5JXE6F
LoadCredential=status-checkin:/etc/power-map/status-api.key
SetCredential=status-checkin:\\n
ExecStopPost=-/usr/bin/python3 /home/exedev/power-map/scripts/status_checkin.py %n
"""
PRUNE_TIMER = """\
[Unit]
Description=Daily power-map tombstone + request-log TTL prune (issue #204)

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
"""
DISK_PRUNE_SERVICE = """\
[Unit]
Description=power-map daily root-disk prune (issues #665, #690)
After=local-fs.target

[Service]
Type=oneshot
User=exedev
WorkingDirectory=/home/exedev/power-map
ExecStart=/usr/bin/python3 /home/exedev/power-map/scripts/prune_disk.py --execute
TimeoutStartSec=1800
Nice=10
IOSchedulingClass=idle
SyslogLevelPrefix=yes
ExecStopPost=-/usr/bin/python3 /home/exedev/power-map/scripts/status_checkin.py %n
"""
DISK_PRUNE_TIMER = """\
[Unit]
Description=power-map daily root-disk prune (issues #665, #690)

[Timer]
OnCalendar=*-*-* 05:30:00 UTC
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
"""


@pytest.fixture(autouse=True)
def tools():
    missing = rig.missing_tools("python3")
    if missing:
        pytest.skip(f"needs {missing}")


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def enable(root, unit):
    d = root / SYSD / "timers.target.wants"
    d.mkdir(parents=True, exist_ok=True)
    os.symlink(f"/{SYSD}/{unit}", d / unit)


@pytest.fixture
def power_map(tmp_path):
    """power-map's host as its infra/installed.toml lays it out: both prune
    units in /etc/systemd/system, their timers enabled."""
    root = tmp_path / "root"
    write(root, f"{SYSD}/power-map-prune.service", PRUNE_SERVICE)
    write(root, f"{SYSD}/power-map-prune.timer", PRUNE_TIMER)
    write(root, f"{SYSD}/power-map-disk-prune.service", DISK_PRUNE_SERVICE)
    write(root, f"{SYSD}/power-map-disk-prune.timer", DISK_PRUNE_TIMER)
    enable(root, "power-map-prune.timer")
    enable(root, "power-map-disk-prune.timer")
    return root


def check(root):
    result = rig.run(RETIRE, "--root", root)
    assert result.returncode == 0, (result.stdout, result.stderr)
    return rig.stdout_json(result)


def units(entries):
    return {e.get("unit") for e in entries}


def test_power_map_prune_is_not_a_candidate(power_map):
    out = check(power_map)
    assert units(out["candidates"]) == set()
    assert units(out["not_disk"]) == {
        "power-map-prune.service",
        "power-map-prune.timer",
    }


def test_not_disk_says_whose_it_is_and_why(power_map):
    (service,) = [
        e
        for e in check(power_map)["not_disk"]
        if e["unit"] == "power-map-prune.service"
    ]
    assert service["repo"] == "power-map"
    assert service["kind"] == "systemd" and service["scope"] == "system"
    assert service["where"] == f"{SYSD}/power-map-prune.service:10"
    # Every Exec* line, ExecStart first (CR 1647): the check-in shows too.
    assert service["command"] == (
        "uv run python -m scripts.prune --execute "
        "-/usr/bin/python3 /home/exedev/power-map/scripts/status_checkin.py %n"
    )
    assert "database rows" in service["why"]


def test_its_disk_tooling_is_still_found(power_map):
    out = check(power_map)
    (found,) = out["found"]
    assert (found["repo"], found["entry"]) == ("power-map", "prune_disk.py")
    assert found["unit"] == "power-map-disk-prune.service"
    assert "power-map-disk-prune.service" not in units(out["not_disk"])


def test_another_command_beside_it_makes_it_a_candidate_again(power_map):
    """A drop-in that adds a line is no longer the unit the list vouches for."""
    write(
        power_map,
        f"{SYSD}/power-map-prune.service.d/override.conf",
        "[Service]\nExecStartPost=/usr/bin/docker system prune -f\n",
    )
    out = check(power_map)
    assert units(out["not_disk"]) == set()
    assert units(out["candidates"]) == {
        "power-map-prune.service",
        "power-map-prune.timer",
    }


def test_a_drop_in_that_replaces_the_command_makes_it_a_candidate(power_map):
    write(
        power_map,
        f"{SYSD}/power-map-prune.service.d/override.conf",
        "[Service]\nExecStart=\nExecStart=/usr/bin/find /tmp -mtime +7 -delete\n",
    )
    assert "power-map-prune.service" in units(check(power_map)["candidates"])


def replace_exec_start(root, command):
    write(
        root,
        f"{SYSD}/power-map-prune.service.d/override.conf",
        f"[Service]\nExecStart=\nExecStart={command}\n",
    )


@pytest.mark.parametrize(
    "command",
    [
        '/bin/sh -c "python -m scripts.prune && find /var/cache/pm -mtime +7 -delete"',
        "uv run python -m scripts.prune --execute ; /usr/bin/find /var/cache/pm -delete",
        "uv run python -m scripts.prune --execute; rm -rf /var/cache/pm",
    ],
)
def test_cr1642_its_module_beside_another_command_is_a_candidate(power_map, command):
    """CR 1642: the word anywhere in the line vouched for a shell that also
    deletes files. Only the module run, and nothing else, is vouched for."""
    replace_exec_start(power_map, command)
    out = check(power_map)
    assert "power-map-prune.service" in units(out["candidates"])
    assert units(out["not_disk"]) == set()


@pytest.mark.parametrize(
    "command",
    [
        "uv run python -m scripts.prune --execute",
        "/home/exedev/power-map/.venv/bin/python -m scripts.prune --execute",
        "/usr/bin/python3 -m scripts.prune --execute --request-log-retention-days 30",
    ],
)
def test_cr1642_the_module_run_alone_is_vouched_for(power_map, command):
    replace_exec_start(power_map, command)
    assert "power-map-prune.service" in units(check(power_map)["not_disk"])


@pytest.mark.parametrize(
    "key", ["ExecStopPost", "ExecReload", "ExecCondition", "ExecSomethingNew"]
)
def test_cr1647_a_deletion_under_any_exec_key_is_a_candidate(power_map, key):
    """CR 1647: only four Exec keys were read, so a drop-in's
    ExecStopPost= (or ExecReload=, ExecCondition=) deletion left the unit
    vouched for. Every Exec* key counts, one the scan doesn't know too."""
    write(
        power_map,
        f"{SYSD}/power-map-prune.service.d/override.conf",
        f"[Service]\n{key}=/usr/bin/find /var/cache/pm -mtime +7 -delete\n",
    )
    out = check(power_map)
    assert units(out["not_disk"]) == set()
    assert {"power-map-prune.service", "power-map-prune.timer"} <= units(
        out["candidates"]
    )


def test_cr1647_its_co_status_check_in_is_vouched_for(power_map):
    """power-map's real unit carries `ExecStopPost=-/usr/bin/python3
    …/scripts/status_checkin.py %n`, an HTTP check-in that removes nothing:
    with every Exec key read, it must not unvouch the unit. Another script
    in its place does."""
    out = check(power_map)
    assert "power-map-prune.service" in units(out["not_disk"])
    write(
        power_map,
        f"{SYSD}/power-map-prune.service.d/override.conf",
        "[Service]\nExecStopPost=\nExecStopPost=-/usr/bin/python3 "
        "/home/exedev/power-map/scripts/tidy_cache.py %n\n",
    )
    assert "power-map-prune.service" in units(check(power_map)["candidates"])


def test_cr1647_a_lookalike_in_exec_stop_post_is_found(tmp_path):
    """The wider read serves the rest of the scan too: a retire-list tool
    run from ExecStopPost is found, not missed."""
    root = tmp_path / "root"
    write(
        root,
        f"{SYSD}/app.service",
        "[Service]\nExecStart=/srv/app/run\nExecStopPost=/srv/watcher/cleanup.sh\n",
    )
    (found,) = check(root)["found"]
    assert (found["repo"], found["entry"]) == ("watcher", "cleanup.sh")
    assert found["where"] == f"{SYSD}/app.service:3"


def test_the_command_under_another_unit_name_stays_a_candidate(tmp_path):
    """The list vouches for power-map's unit, not for every `scripts.prune`:
    another repo's module of that name may well prune disk."""
    root = tmp_path / "root"
    write(
        root,
        f"{SYSD}/nightly-prune.service",
        "[Service]\nExecStart=uv run python -m scripts.prune --execute\n",
    )
    out = check(root)
    assert units(out["candidates"]) == {"nightly-prune.service"}
    assert out["not_disk"] == []


def test_a_timer_whose_service_is_missing_stays_a_candidate(tmp_path):
    root = tmp_path / "root"
    write(root, f"{SYSD}/power-map-prune.timer", PRUNE_TIMER)
    out = check(root)
    assert units(out["candidates"]) == {"power-map-prune.timer"}
    assert out["not_disk"] == []


def test_the_help_names_not_disk():
    help_text = rig.run(RETIRE, "--help").stdout
    assert "not_disk" in help_text.split("candidates", 1)[1].split("canonical", 1)[0]


def test_each_report_key_in_the_help_starts_its_description_at_column_15():
    """CR 1638: the not_disk paragraph's edit took a space from by_hand's line."""
    help_text = rig.run(RETIRE, "--help").stdout
    block = help_text.split("\n  found", 1)[1].split("\nOptions:", 1)[0]
    keys = re.findall(r"^  ([a-z_]+)( +)\S", "  found" + block, re.M)
    assert {k for k, _ in keys} >= {"found", "candidates", "not_disk", "by_hand"}
    for key, gap in keys:
        assert len("  " + key + gap) == 14, f"{key}'s description is misaligned"


@pytest.mark.parametrize(
    "key, command",
    [
        (
            "ExecStopPost",
            "@/usr/bin/python3 /home/exedev/power-map/scripts/status_checkin.py "
            "/srv/cache/wipe_old.py",
        ),
        ("ExecStart", "+/usr/bin/python3 -m scripts.prune --execute"),
        ("ExecStart", "!!/usr/bin/python3 -m scripts.prune --execute"),
        ("ExecStart", "--/usr/bin/python3 -m scripts.prune --execute"),
        ("ExecStart", "+/usr/local/bin/uv run python -m scripts.prune --execute"),
    ],
)
def test_cr1653_a_prefix_other_than_one_dash_is_a_candidate(power_map, key, command):
    """CR 1653: the interpreter's pattern took any prefix glued to its path.
    `@` makes the second word argv[0], so `@python3 status_checkin.py
    wipe_old.py` runs python as wipe_old.py's interpreter; `+`, `!`, `!!`
    and `:` change privileges or expansion. Only systemd's `-` is vouched."""
    write(
        power_map,
        f"{SYSD}/power-map-prune.service.d/override.conf",
        f"[Service]\n{key}=\n{key}={command}\n",
    )
    out = check(power_map)
    assert units(out["not_disk"]) == set()
    assert "power-map-prune.service" in units(out["candidates"])


@pytest.mark.parametrize(
    "setting",
    ["ExecPaths=/home/exedev/power-map", "ExecSearchPath=/usr/local/bin:/usr/bin"],
)
def test_cr1655_a_sandbox_or_search_path_setting_keeps_it_vouched_for(
    power_map, setting
):
    """CR 1655: ExecPaths= and ExecSearchPath= start with `Exec` but run
    nothing, so a hardening drop-in setting one is no reason to unvouch."""
    write(
        power_map,
        f"{SYSD}/power-map-prune.service.d/hardening.conf",
        f"[Service]\n{setting}\n",
    )
    out = check(power_map)
    assert units(out["not_disk"]) == {
        "power-map-prune.service",
        "power-map-prune.timer",
    }
    assert units(out["candidates"]) == set()
