"""patching-hosts: a declared service still on a replaced binary (#699).

A held step can install a package, pass its health checks and read
`verdict.ok: true`, while the service it was for still runs the old binary.
Seen with cloudflared from Cloudflare's repo: `cloudflared service install`
wrote the unit outside the package's files, so the package's postinst
restarted nothing, and `/proc/<MainPID>/exe` read
`/usr/bin/cloudflared (deleted)` until a reboot taken for other reasons.

What this file pins:

- after each step, `apply.sh` reads `/proc/<pid>/exe` for every process in
  each knob `service`'s cgroup, as `reboot_pids` lists them, so a wrapper's
  child daemon counts and a MainPID of 0 hides nothing (CR 2778). A target
  ending ` (deleted)` is a `stale_binary` entry (unit, pid, path, package,
  version, and whether this step took the package), a `next` line saying
  the version takes effect only at the unit's restart or a reboot, and an
  input to the reboot decision's own `next` line, in the singular or the
  plural (CR 2780). A link or a cgroup that can't be read is
  `stale_binary_unread`, never "not stale";
- what needrestart passes over isn't stale, such as an exec from a memfd,
  which no restart clears (CR 2776);
- a path dpkg records without `/usr`, as noble's iproute2 records
  `/sbin/ip`, still finds its package (CR 2777);
- `verdict.ok` stays true, since the step did what it ran: the verdict's
  `not_in_effect` says the update hasn't taken effect;
- the probe gives each `impact.services` unit `exe_deleted`, from every
  process its cgroup names: true, false, or null when there's no process or
  a link can't be read. A true one is the finding `stale-binary:<unit>`, so
  a pre-run reading catches a daemon an earlier run, or unattended-upgrades,
  left on a replaced binary.
"""

import pytest

from tests.structural import test_patching_hosts_apply as _apply
from tests.structural import test_patching_hosts_probe as _probe
from tests.structural.patching_hosts_rig import dispatcher
from tests.structural.test_patching_hosts_probe import _finding, _ids


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


REDIS_BIN = "/usr/bin/redis-server"
REDIS_NEW = "5:7.0.15-1ubuntu0.24.04.1"
IP_NEW = "6.1.0-1ubuntu6.1"
UNIT = "tunnel.service"
PID = 4300
# dpkg's records: redis-server's binary at its /usr path, iproute2's ip at
# the path noble's dpkg still records, /sbin/ip (CR 2777).
OWNERS = (
    'shift; rc=0; for f; do case $f in /usr/bin/redis-server) echo "redis-server: $f" ;; '
    '/sbin/ip) echo "iproute2: $f" ;; '
    '*) echo "dpkg-query: no path found matching pattern $f" >&2; rc=1 ;; esac; '
    "done; exit $rc"
)


def _cgroup(unit: str) -> str:
    return f"/system.slice/{unit}"


def _declared(host, procs: dict | None, units: tuple[str, ...] = (UNIT,)):
    """A knob `service` line for each of UNITS, each running PROCS: each
    PID's exe link target, or None for a process whose link can't be read.
    PROCS None: no cgroup, the unit isn't running. A second unit's PIDs
    are the first's plus 100."""
    host.knob(_apply.KNOB + "".join(f"service {u}\n" for u in units))
    for n, unit in enumerate(units):
        if procs is None:
            host.on("systemctl", f"show*ControlGroup*-- {unit}", "ControlGroup=\n")
            continue
        host.on(
            "systemctl",
            f"show*ControlGroup*-- {unit}",
            f"ControlGroup={_cgroup(unit)}\n",
        )
        cg = host.root / "sys" / "fs" / "cgroup" / _cgroup(unit).lstrip("/")
        cg.mkdir(parents=True, exist_ok=True)
        pids = {pid + 100 * n: exe for pid, exe in procs.items()}
        (cg / "cgroup.procs").write_text("".join(f"{p}\n" for p in pids))
        for pid, exe in pids.items():
            host.write(f"proc/{pid}/status", f"Name:\tp{pid}\n")
            if exe is not None:
                host.link(f"proc/{pid}/exe", exe)
    host.on("dpkg-query", "-S *", script=OWNERS)
    host.on("dpkg-query", "-W redis-server", f"redis-server\t{REDIS_NEW}\n")
    host.on("dpkg-query", "-W iproute2", f"iproute2\t{IP_NEW}\n")
    return host


def _step(host, upgraded: str = "redis-server") -> dict:
    host.run()
    host.uu(f"Packages that will be upgraded: {upgraded}\nAll upgrades installed\n")
    return host.run(step="redis")


STALE = {PID: f"{REDIS_BIN} (deleted)"}


@pytest.fixture
def ahost(tmp_path):
    return _apply._ready(_apply.Host(tmp_path))


# --- apply.sh, after a step ------------------------------------------------------


def test_a_held_step_whose_service_still_runs_the_replaced_binary_says_so(ahost):
    out = _step(_declared(ahost, STALE))
    assert out["stale_binary"] == [
        {
            "unit": UNIT,
            "pid": PID,
            "path": REDIS_BIN,
            "package": "redis-server",
            "version": REDIS_NEW,
            "taken": True,
        }
    ]
    assert out["stale_binary_unread"] == []
    # The step did what it ran, so it stays green, and says what it didn't do.
    assert out["verdict"]["ok"] is True
    [said] = out["verdict"]["not_in_effect"]
    assert UNIT in said and REDIS_BIN in said and REDIS_NEW in said
    restart = [n for n in out["next"] if n.startswith(f"restart {UNIT}")]
    assert restart == [
        f"restart {UNIT}, or reboot, before redis-server {REDIS_NEW} takes effect: "
        f"it still runs the replaced {REDIS_BIN} (stale_binary)"
    ]
    # And it reaches the reboot decision.
    assert out["next"][-1] == (
        "the reboot decision: reboot-and-record.md section 4. 1 declared service "
        "still runs a replaced binary (stale_binary): restart it, or reboot"
    )
    assert out["next"].index(restart[0]) < len(out["next"]) - 1


def test_two_stale_services_reach_the_reboot_decision_in_the_plural(ahost):
    # CR 2780.
    out = _step(_declared(ahost, STALE, units=(UNIT, "relay.service")))
    assert [e["unit"] for e in out["stale_binary"]] == [UNIT, "relay.service"]
    assert out["next"][-1] == (
        "the reboot decision: reboot-and-record.md section 4. 2 declared services "
        "still run a replaced binary (stale_binary): restart them, or reboot"
    )


def test_a_service_on_its_current_binary_is_not_stale(ahost):
    out = _step(_declared(ahost, {PID: REDIS_BIN}))
    assert out["stale_binary"] == []
    assert out["stale_binary_unread"] == []
    assert out["verdict"]["not_in_effect"] == []
    assert out["next"][-1] == "the reboot decision: reboot-and-record.md section 4"
    assert not [n for n in out["next"] if "stale_binary" in n]


def test_a_wrappers_child_on_a_replaced_binary_is_stale(ahost):
    # CR 2778: Type=forking with GuessMainPID=no, or a oneshot's
    # RemainAfterExit, leaves MainPID at a wrapper or 0; the daemon is a
    # process in the unit's cgroup all the same.
    out = _step(
        _declared(ahost, {PID: "/usr/bin/bash", PID + 1: f"{REDIS_BIN} (deleted)"})
    )
    [e] = out["stale_binary"]
    assert e["pid"] == PID + 1 and e["path"] == REDIS_BIN


def test_a_service_running_from_a_memfd_is_not_stale(ahost):
    # CR 2776: /memfd:<name> (deleted) is no replaced file, and no restart
    # clears it. needrestart passes it over, as reboot_maps does.
    out = _step(_declared(ahost, {PID: "/memfd:svc (deleted)"}))
    assert out["stale_binary"] == []
    assert out["verdict"]["not_in_effect"] == []


def test_a_binary_dpkg_records_without_usr_finds_its_package(ahost):
    # CR 2777: /proc reads /usr/sbin/ip; noble's dpkg records /sbin/ip.
    out = _step(_declared(ahost, {PID: "/usr/sbin/ip (deleted)"}), upgraded="iproute2")
    [e] = out["stale_binary"]
    assert e["path"] == "/usr/sbin/ip"
    assert e["package"] == "iproute2" and e["version"] == IP_NEW
    assert e["taken"] is True


def test_a_stale_binary_the_step_didnt_take_is_still_reported(ahost):
    # Left by the bulk, an earlier step or unattended-upgrades: still stale.
    out = _step(_declared(ahost, STALE), upgraded="")
    [e] = out["stale_binary"]
    assert e["taken"] is False
    assert out["next"][-1].endswith("restart it, or reboot")


def test_a_binary_that_cant_be_read_is_unread_not_current(ahost):
    out = _step(_declared(ahost, {PID: None}))
    assert out["stale_binary"] == []
    assert out["stale_binary_unread"] == [
        {"unit": UNIT, "pid": PID, "why": f"/proc/{PID}/exe couldn't be read as root"}
    ]
    by_hand = [n for n in out["next"] if n.startswith(f"read {UNIT}'s binary by hand")]
    assert by_hand, out["next"]


def test_a_cgroup_that_cant_be_read_is_unread_not_current(ahost):
    _declared(ahost, STALE)
    cg = ahost.root / "sys" / "fs" / "cgroup" / _cgroup(UNIT).lstrip("/")
    (cg / "cgroup.procs").unlink()
    cg.rmdir()
    out = _step(ahost)
    assert out["stale_binary"] == []
    [u] = out["stale_binary_unread"]
    assert u["unit"] == UNIT and u["pid"] is None and "isn't there" in u["why"]


def test_a_service_that_isnt_running_runs_no_binary(ahost):
    out = _step(_declared(ahost, None))
    assert out["stale_binary"] == []
    assert out["stale_binary_unread"] == []


def test_the_bulk_reads_its_services_binaries_too(ahost):
    _declared(ahost, STALE)
    out = ahost.run()
    [e] = out["stale_binary"]
    assert e["unit"] == UNIT and e["taken"] is False


def test_a_refused_step_reads_no_binary(ahost):
    _declared(ahost, STALE)
    out = ahost.run(step="postgres", rc=3)
    assert out["stale_binary"] is None
    assert out["stale_binary_unread"] is None


def test_no_declared_service_reads_nothing(ahost):
    out = ahost.run()
    assert out["stale_binary"] == []
    assert not [a for _, a, _ in ahost.calls("systemctl") if UNIT in a]


# --- probe.sh, before a run ------------------------------------------------------


host = _probe.host


def _probe_service(host, procs: dict):
    """UNIT, active, running PROCS: each PID's exe target, None for a link
    that can't be read. Each is in UNIT's cgroup, as /proc/<pid>/cgroup
    names it."""
    host.knob(f"posture scheduled\nservice {UNIT}\n")
    host.show(
        UNIT,
        After="network.target",
        Result="success",
        NRestarts="0",
        ActiveState="active",
        RequiredBy="",
        BoundBy="",
    )
    for pid, exe in procs.items():
        host.write(f"proc/{pid}/cgroup", f"0::{_cgroup(UNIT)}\n")
        if exe is not None:
            host.link(f"proc/{pid}/exe", exe)
    return host


def test_the_probe_reads_a_service_left_on_a_replaced_binary(host):
    out = _probe_service(host, {PID: "/usr/bin/cloudflared (deleted)"}).run()
    [svc] = out["impact"]["services"]
    assert svc["exe_deleted"] is True
    f = _finding(out, f"stale-binary:{UNIT}")
    assert f["kind"] == "risk"
    assert "/usr/bin/cloudflared" in f["message"]


def test_the_probe_reads_a_wrappers_child(host):
    # CR 2778.
    out = _probe_service(
        host, {PID: "/usr/bin/bash", PID + 1: "/usr/bin/cloudflared (deleted)"}
    ).run()
    [svc] = out["impact"]["services"]
    assert svc["exe_deleted"] is True


@pytest.mark.parametrize(
    "procs",
    [{PID: "/usr/bin/cloudflared"}, {PID: "/memfd:svc (deleted)"}],
    ids=["current", "memfd"],
)
def test_the_probe_reads_a_service_that_isnt_stale(host, procs):
    out = _probe_service(host, procs).run()
    [svc] = out["impact"]["services"]
    assert svc["exe_deleted"] is False
    assert f"stale-binary:{UNIT}" not in _ids(out)


@pytest.mark.parametrize(
    "procs",
    [{}, {PID: None}, {PID: "/usr/bin/cloudflared", PID + 1: None}],
    ids=["no-process", "unreadable", "one-unreadable"],
)
def test_no_process_or_an_unreadable_link_is_null(host, procs):
    out = _probe_service(host, procs).run()
    [svc] = out["impact"]["services"]
    assert svc["exe_deleted"] is None
    assert f"stale-binary:{UNIT}" not in _ids(out)
