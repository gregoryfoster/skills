"""#425 — retire-check.sh lists a host's own disk tooling beside the GC's report.

The retire check is a hypothesis (#485's plan, Key decisions): what can
honestly be mechanised is finding the units, timers and cron lines that run a
retire-list implementation, and pairing them with the GC's report-only `gc`
run. What each old implementation removed that the GC keeps can't be read
from an arbitrary script, so that stays a by-hand checklist, and the script
says so rather than guessing.

It only reads. A scratch root stands in for the host.
"""

import os

import pytest

from tests.structural import maintaining_host_disk_rig as rig

RETIRE = rig.SCRIPTS / "retire-check.sh"


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


def enable(root, unit, wants="timers.target.wants", base="etc/systemd/system"):
    d = root / base / wants
    d.mkdir(parents=True, exist_ok=True)
    os.symlink(f"/{base}/{unit}", d / unit)


@pytest.fixture
def host(tmp_path):
    root = tmp_path / "root"
    sysd = "etc/systemd/system"
    # power-map's two, one timer enabled and one not
    write(
        root,
        f"{sysd}/prune-disk.service",
        "[Service]\nType=oneshot\nExecStart=/home/exedev/power-map/.venv/bin/python "
        "/home/exedev/power-map/scripts/prune_disk.py --apply\n",
    )
    write(root, f"{sysd}/prune-disk.timer", "[Timer]\nOnCalendar=daily\n")
    enable(root, "prune-disk.timer")
    write(
        root,
        f"{sysd}/headroom-check.service",
        "[Service]\nExecStart=/usr/bin/python3 /opt/pm/check_disk_headroom.py\n",
    )
    write(
        root, f"{sysd}/headroom-check.timer", "[Timer]\nUnit=headroom-check.service\n"
    )
    # broker's, as a user unit
    write(
        root,
        "home/exedev/.config/systemd/user/editors.service",
        "[Service]\nExecStart=%h/broker/scripts/prune_editor_builds.sh --apply\n",
    )
    # address-validator's docker-prune, matched by its unit's name
    write(
        root,
        f"{sysd}/docker-prune.service",
        "[Service]\nExecStart=/usr/bin/docker system prune -f\n",
    )
    write(root, f"{sysd}/docker-prune.timer", "[Timer]\nOnCalendar=weekly\n")
    enable(root, "docker-prune.timer")
    # watcher's, through a drop-in that replaces ExecStart
    write(root, f"{sysd}/maint.service", "[Service]\nExecStart=/bin/true\n")
    write(
        root,
        f"{sysd}/maint.service.d/override.conf",
        "[Service]\nExecStart=\nExecStart=/srv/watcher/cleanup.sh\n",
    )
    # wslcb's, from cron
    write(
        root,
        "etc/cron.d/wslcb",
        "# disk\n15 4 * * * exedev /home/exedev/wslcb/.venv/bin/python /home/exedev/wslcb/scripts/disk_hygiene.py\n",
    )
    # the canonical GC: installed, its GC timer enabled; never a match or a candidate
    for path, (data, _mode) in rig.gc_files().items():
        write(root, path, data.decode())
    write(
        root,
        f"{rig.UNIT_DIR}/cannobserv-disk-gc.service",
        "[Service]\nExecStart=/usr/bin/python3 -I /usr/local/lib/cannobserv/disk-gc/disk-gc gc --apply\n",
    )
    enable(root, "cannobserv-disk-gc.timer")
    # a host-local unit that only looks like disk tooling
    write(
        root,
        f"{sysd}/cache-cleanup.service",
        "[Service]\nExecStart=/opt/observo/bin/clear-caches\n",
    )
    write(root, f"{sysd}/cache-cleanup.timer", "[Timer]\nOnCalendar=hourly\n")
    # packaged and unrelated units: neither
    write(root, "lib/systemd/system/systemd-tmpfiles-clean.timer", "[Timer]\n")
    write(
        root,
        "lib/systemd/system/systemd-tmpfiles-clean.service",
        "[Service]\nExecStart=/bin/systemd-tmpfiles --clean\n",
    )
    write(root, f"{sysd}/app.service", "[Service]\nExecStart=/srv/app/run\n")
    return root


def check(root, *extra):
    result = rig.run(RETIRE, "--root", root, *extra)
    assert result.returncode == 0, (result.stdout, result.stderr)
    return rig.stdout_json(result)


def by_entry(out):
    return {(f["repo"], f["entry"]): f for f in out["found"]}


def test_finds_each_retire_list_implementation(host):
    found = by_entry(check(host))
    assert set(found) == {
        ("power-map", "prune_disk.py"),
        ("power-map", "check_disk_headroom.py"),
        ("broker", "prune_editor_builds.sh"),
        ("address-validator", "docker-prune"),
        ("watcher", "cleanup.sh"),
        ("wslcb", "disk_hygiene.py"),
    }


def test_reports_where_and_whether_it_runs(host):
    found = by_entry(check(host))
    prune = found[("power-map", "prune_disk.py")]
    assert prune["kind"] == "systemd"
    assert prune["unit"] == "prune-disk.service"
    assert prune["timer"] == "prune-disk.timer"
    assert prune["enabled"] is True
    assert "prune_disk.py --apply" in prune["command"]
    headroom = found[("power-map", "check_disk_headroom.py")]
    assert headroom["timer"] == "headroom-check.timer"
    assert headroom["enabled"] is False
    assert found[("broker", "prune_editor_builds.sh")]["scope"] == "user:exedev"
    assert (
        found[("watcher", "cleanup.sh")]["where"]
        == "etc/systemd/system/maint.service.d/override.conf:3"
    )
    cron = found[("wslcb", "disk_hygiene.py")]
    assert cron["kind"] == "cron" and cron["where"] == "etc/cron.d/wslcb:2"


def test_canonical_gc_is_neither_found_nor_a_candidate(host):
    out = check(host)
    units = [f.get("unit") for f in out["found"]] + [
        c.get("unit") for c in out["candidates"]
    ]
    assert not [u for u in units if u and u.startswith("cannobserv-")]
    assert out["canonical"]["installed"] is True
    assert out["canonical"]["version"] == 2
    assert out["canonical"]["timers"] == {
        "cannobserv-disk-gc.timer": "enabled",
        "cannobserv-disk-headroom.timer": "disabled",
    }


def test_usa_wa_disk_gc_sh_is_not_the_canonical_disk_gc(host):
    found = by_entry(check(host))
    assert ("usa-wa", "disk-gc.sh") not in found
    write(
        host,
        "etc/systemd/system/gc.service",
        "[Service]\nExecStart=/srv/usa-wa/scripts/disk-gc.sh\n",
    )
    assert ("usa-wa", "disk-gc.sh") in by_entry(check(host))


def test_candidates_are_host_local_lookalikes_only(host):
    out = check(host)
    names = {c.get("unit") for c in out["candidates"]}
    assert "cache-cleanup.service" in names or "cache-cleanup.timer" in names
    assert not [n for n in names if n and "tmpfiles" in n]
    assert "app.service" not in names
    found_units = {f.get("unit") for f in out["found"]}
    assert not names & found_units


def test_observo_is_by_hand(host):
    out = check(host)
    assert [b for b in out["by_hand"] if b["repo"] == "observo"]


def test_gc_report_from_a_file(host, tmp_path):
    report = tmp_path / "gc-report.txt"
    report.write_text("<6>vscode-servers: would remove 2 builds, 1.3G\n<6>ok\n")
    out = check(host, "--gc-report", report)
    assert out["gc_report"]["lines"] == [
        "<6>vscode-servers: would remove 2 builds, 1.3G",
        "<6>ok",
    ]


def test_without_a_report_it_says_how_to_get_one(host):
    out = check(host)
    assert out["gc_report"] is None
    assert any("disk-gc gc" in n for n in out["next"])


def stub_python(tmp_path, body):
    """An interpreter that records its argv and runs `body` instead of the
    GC, so --run-gc-report can be tested on / without running anything."""
    argv = tmp_path / "argv"
    stub = tmp_path / "python-stub"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" >"{argv}"\n{body}\n')
    stub.chmod(0o755)
    return stub, argv


def test_run_gc_report_runs_gc_json_and_nothing_else(tmp_path):
    """CR 526: on / only, with the GC's --json. The stub stands in for the
    interpreter, so nothing runs; the scan of / only reads."""
    stub, argv = stub_python(
        tmp_path, """echo '{"tiers": {"uv": {"would_remove": 0}}}'"""
    )
    result = rig.run(RETIRE, "--root", "/", "--run-gc-report", "--python", stub)
    assert result.returncode == 0, result.stderr
    out = rig.stdout_json(result)
    assert argv.read_text().split() == [
        "-I",
        "/usr/local/lib/cannobserv/disk-gc/disk-gc",
        "gc",
        "--json",
    ]
    assert out["gc_report"]["json"] == {"tiers": {"uv": {"would_remove": 0}}}
    assert out["gc_report"]["exit"] == 0


def test_run_gc_report_refuses_a_root_other_than_slash(host, tmp_path):
    """The GC reads the live config and /proc, whatever --root says."""
    stub, argv = stub_python(tmp_path, "echo '{}'")
    result = rig.run(RETIRE, "--root", host, "--run-gc-report", "--python", stub)
    assert result.returncode == 2
    assert "--root" in result.stderr
    assert not argv.exists()


def test_run_gc_report_times_out(tmp_path):
    stub, _ = stub_python(tmp_path, "sleep 5")
    result = rig.run(
        RETIRE, "--root", "/", "--run-gc-report", "--python", stub, "--gc-timeout", "1"
    )
    assert result.returncode == 0, result.stderr
    assert rig.stdout_json(result)["gc_report"]["exit"] == "timeout"


def test_run_gc_report_with_a_missing_interpreter_is_a_usage_error(tmp_path):
    result = rig.run(
        RETIRE,
        "--root",
        "/",
        "--run-gc-report",
        "--python",
        tmp_path / "no-such-python",
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_report_flags_are_mutually_exclusive(host, tmp_path):
    report = tmp_path / "r.txt"
    report.write_text("<6>ok\n")
    result = rig.run(RETIRE, "--root", host, "--gc-report", report, "--run-gc-report")
    assert result.returncode == 2


def test_a_long_report_says_it_was_cut(host, tmp_path):
    report = tmp_path / "long.txt"
    report.write_text("".join(f"<6>line {i}\n" for i in range(600)))
    gc = check(host, "--gc-report", report)["gc_report"]
    assert len(gc["lines"]) == 500
    assert gc["truncated"] is True and gc["total_lines"] == 600


def test_only_reads(host):
    before = {
        p: (p.stat().st_mtime_ns, p.read_bytes())
        for p in host.rglob("*")
        if p.is_file()
    }
    check(host)
    after = {
        p: (p.stat().st_mtime_ns, p.read_bytes())
        for p in host.rglob("*")
        if p.is_file()
    }
    assert before == after


def test_empty_host(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    out = check(root)
    assert out["found"] == [] and out["candidates"] == []
    assert out["canonical"]["installed"] is False


def test_unreadable_home_is_reported_not_fatal(host):
    if os.geteuid() == 0:
        pytest.skip("root reads a mode-000 directory, so the case can't arise")
    locked = host / "home/exedev/.config/systemd/user"
    locked.chmod(0o000)
    try:
        out = check(host)
    finally:
        locked.chmod(0o755)
    assert "home/exedev/.config/systemd/user" in out["unreadable"]
    assert any("root" in n for n in out["next"])


# --- CR 522: drop-ins from every directory, merged as systemd merges them ---


def units_found(out, unit):
    return [f for f in out["found"] if f.get("unit") == unit]


def test_etc_drop_in_on_a_unit_lower_down_is_read(host):
    """`systemctl edit` writes /etc/systemd/system/<unit>.d/ even when the
    unit itself ships in /usr/local/lib or /lib."""
    write(
        host, "lib/systemd/system/hygiene.service", "[Service]\nExecStart=/bin/true\n"
    )
    write(
        host,
        "etc/systemd/system/hygiene.service.d/override.conf",
        "[Service]\nExecStart=\nExecStart=/srv/address-validator/disk-hygiene.sh\n",
    )
    found = units_found(check(host), "hygiene.service")
    assert [(f["repo"], f["entry"]) for f in found] == [
        ("address-validator", "disk-hygiene.sh")
    ]
    assert found[0]["where"].startswith(
        "etc/systemd/system/hygiene.service.d/override.conf"
    )


def test_etc_drop_in_that_blanks_a_lower_units_command_unfinds_it(host):
    write(
        host,
        "usr/local/lib/systemd/system/legacy-prune.service",
        "[Service]\nExecStart=/opt/pm/prune_disk.py\n",
    )
    write(
        host,
        "etc/systemd/system/legacy-prune.service.d/off.conf",
        "[Service]\nExecStart=\nExecStart=/bin/true\n",
    )
    assert units_found(check(host), "legacy-prune.service") == []


def test_lower_drop_in_on_an_etc_unit_is_read(host):
    write(
        host, "etc/systemd/system/wslcb-gc.service", "[Service]\nExecStart=/bin/true\n"
    )
    write(
        host,
        "usr/local/lib/systemd/system/wslcb-gc.service.d/10-run.conf",
        "[Service]\nExecStart=\nExecStart=/srv/wslcb/scripts/disk_hygiene.py\n",
    )
    found = units_found(check(host), "wslcb-gc.service")
    assert [(f["repo"], f["entry"]) for f in found] == [("wslcb", "disk_hygiene.py")]


def test_same_named_drop_in_in_etc_wins(host):
    write(host, "lib/systemd/system/sweep.service", "[Service]\nExecStart=/bin/true\n")
    write(
        host,
        "lib/systemd/system/sweep.service.d/override.conf",
        "[Service]\nExecStart=\nExecStart=/srv/watcher/cleanup.sh\n",
    )
    write(
        host,
        "etc/systemd/system/sweep.service.d/override.conf",
        "[Service]\nExecStart=\nExecStart=/bin/true\n",
    )
    assert units_found(check(host), "sweep.service") == []


def test_drop_ins_apply_in_filename_order_across_directories(host):
    write(host, "lib/systemd/system/order.service", "[Service]\nExecStart=/bin/true\n")
    write(
        host,
        "etc/systemd/system/order.service.d/10-run.conf",
        "[Service]\nExecStart=\nExecStart=/srv/watcher/cleanup.sh\n",
    )
    write(
        host,
        "lib/systemd/system/order.service.d/20-off.conf",
        "[Service]\nExecStart=\nExecStart=/bin/true\n",
    )
    assert units_found(check(host), "order.service") == []


# --- CR 523: a timer's drop-ins count too -----------------------------------


def test_timer_whose_drop_in_names_its_service(host):
    """An enabled timer whose drop-in sets Unit=: the service it starts is
    scheduled, and must not read as off."""
    write(
        host,
        "etc/systemd/system/hygiene-job.service",
        "[Service]\nExecStart=/srv/address-validator/disk-hygiene.sh\n",
    )
    write(host, "etc/systemd/system/nightly.timer", "[Timer]\nOnCalendar=daily\n")
    write(
        host,
        "etc/systemd/system/nightly.timer.d/unit.conf",
        "[Timer]\nUnit=hygiene-job.service\n",
    )
    enable(host, "nightly.timer")
    (found,) = units_found(check(host), "hygiene-job.service")
    assert found["timer"] == "nightly.timer"
    assert found["enabled"] is True


# --- CR 524: the JSON is pasted onto an issue, so no secret reaches it -------

SECRETS = (
    "ghp_unitsecret",
    "uuid-secret-1",
    "cronsecret",
    "abcsecret",
    "keysecret",
    "hunter2secret",
    "userinfo-secret",
)


def test_secrets_in_commands_never_reach_stdout(host):
    write(
        host,
        "etc/systemd/system/watch-clean.service",
        "[Service]\nExecStart=/usr/bin/env GH_TOKEN=ghp_unitsecret "
        "/srv/watcher/cleanup.sh --ping https://hc-ping.com/uuid-secret-1\n",
    )
    write(
        host,
        "etc/cron.d/hygiene",
        '0 3 * * * root curl -H "Authorization: Bearer cronsecret" '
        "https://example.com/ping/abcsecret; /srv/wslcb/disk_hygiene.py "
        "--api-key=keysecret\n",
    )
    write(
        host,
        "etc/systemd/system/cache-clean2.service",
        "[Service]\nExecStart=/opt/x/clear-cache --password hunter2secret "
        "--to https://bob:userinfo-secret@backup.example.com/x\n",
    )
    result = rig.run(RETIRE, "--root", host)
    assert result.returncode == 0, result.stderr
    leaked = [s for s in SECRETS if s in result.stdout]
    assert not leaked, leaked
    out = rig.stdout_json(result)
    (unit,) = units_found(out, "watch-clean.service")
    assert unit["match"] == "cleanup.sh"
    assert unit["where"] == "etc/systemd/system/watch-clean.service:2"
    assert "hc-ping.com" in unit["command"]
    (cron,) = [f for f in out["found"] if f["where"].startswith("etc/cron.d/hygiene")]
    assert cron["where"] == "etc/cron.d/hygiene:1"
    assert cron["match"] == "disk_hygiene.py"


# --- CR 525: more ways discovery missed a tool -------------------------------


def test_homes_come_from_passwd(host):
    write(
        host,
        "etc/passwd",
        "root:x:0:0:root:/root:/bin/bash\nsvc:x:998:998::/srv/svc:/usr/sbin/nologin\n",
    )
    write(
        host,
        "srv/svc/.config/systemd/user/tidy.service",
        "[Service]\nExecStart=/srv/svc/watcher/cleanup.sh\n",
    )
    (found,) = units_found(check(host), "tidy.service")
    assert found["scope"] == "user:svc"


def test_local_share_user_units_are_scanned(host):
    write(
        host,
        "home/exedev/.local/share/systemd/user/pm.service",
        "[Service]\nExecStart=/home/exedev/power-map/scripts/prune_disk.py\n",
    )
    (found,) = units_found(check(host), "pm.service")
    assert found["scope"] == "user:exedev"


def run_parts(host, name, target=None, mode=0o755):
    path = host / "etc/cron.daily" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if target:
        os.symlink(target, path)
    else:
        path.write_text("#!/bin/sh\n")
        path.chmod(mode)
    return path


def cron_found(out, where):
    return [f for f in out["found"] if f["where"] == where]


def test_run_parts_symlink_is_matched_by_its_target(host):
    run_parts(host, "pm-prune", target="/home/exedev/power-map/scripts/prune_disk.py")
    (found,) = cron_found(check(host), "etc/cron.daily/pm-prune")
    assert (found["repo"], found["entry"]) == ("power-map", "prune_disk.py")


def test_run_parts_skips_a_name_with_a_dot(host):
    """run-parts runs only names of letters, digits, _ and -: cleanup.sh in
    cron.daily never runs, so it is found but not enabled."""
    run_parts(host, "cleanup.sh")
    (found,) = cron_found(check(host), "etc/cron.daily/cleanup.sh")
    assert found["enabled"] is False


def test_run_parts_skips_a_file_that_is_not_executable(host):
    """A run-parts entry runs only when executable; a link's target is
    judged inside the root, not on the machine running the check."""
    target = host / "opt/pm/prune_disk.py"
    target.parent.mkdir(parents=True)
    target.write_text("#!/usr/bin/python3\n")
    target.chmod(0o644)
    run_parts(host, "pm-prune", target="/opt/pm/prune_disk.py")
    (found,) = cron_found(check(host), "etc/cron.daily/pm-prune")
    assert found["enabled"] is False
    target.chmod(0o755)
    (found,) = cron_found(check(host), "etc/cron.daily/pm-prune")
    assert found["enabled"] is True


@pytest.mark.parametrize(
    "command, entry",
    [
        ('/bin/sh -c "/srv/watcher/cleanup.sh --apply"', "cleanup.sh"),
        ("/usr/bin/python3 /opt/pm/prune_disk.py>/dev/null 2>&1", "prune_disk.py"),
        ("/bin/bash -c '/srv/b/prune_editor_builds.sh;true'", "prune_editor_builds.sh"),
    ],
)
def test_tokens_match_on_word_boundaries_inside_a_command(host, command, entry):
    write(
        host, "etc/systemd/system/wrapped.service", f"[Service]\nExecStart={command}\n"
    )
    found = units_found(check(host), "wrapped.service")
    assert [f["entry"] for f in found] == [entry]


def test_a_longer_name_is_not_a_match(host):
    write(
        host,
        "etc/systemd/system/other.service",
        "[Service]\nExecStart=/srv/x/my-cleanup.sh.bak /srv/x/notprune_disk.py\n",
    )
    assert units_found(check(host), "other.service") == []


def test_anacrontab_is_read(host):
    write(
        host,
        "etc/anacrontab",
        "SHELL=/bin/sh\n# period delay job command\n1 5 pm.prune /opt/pm/prune_disk.py --apply\n",
    )
    found = [f for f in check(host)["found"] if f["where"] == "etc/anacrontab:3"]
    assert [(f["kind"], f["entry"]) for f in found] == [("anacron", "prune_disk.py")]


# --- CR 537c: Unit= by a different name, and a blanking drop-in ------------


def test_a_timer_named_unlike_its_service_still_schedules_it(host):
    write(
        host,
        "etc/systemd/system/pm-prune.service",
        "[Service]\nExecStart=/opt/pm/prune_disk.py\n",
    )
    write(
        host, "etc/systemd/system/gc-nightly.timer", "[Timer]\nUnit=pm-prune.service\n"
    )
    enable(host, "gc-nightly.timer")
    (found,) = units_found(check(host), "pm-prune.service")
    assert found["timer"] == "gc-nightly.timer"
    assert found["enabled"] is True


def test_a_drop_in_that_blanks_the_command_unfinds_it(host):
    write(
        host,
        "etc/systemd/system/old-hygiene.service",
        "[Service]\nExecStart=/srv/wslcb/disk_hygiene.py\n",
    )
    write(
        host,
        "etc/systemd/system/old-hygiene.service.d/retired.conf",
        "[Service]\nExecStart=\nExecStart=/bin/true\n",
    )
    assert units_found(check(host), "old-hygiene.service") == []
