"""patching-hosts: a declared service still on a replaced binary (#699).

A held step can install a package, pass its health checks and read
`verdict.ok: true`, while the service it was for still runs the old binary.
Seen with cloudflared from Cloudflare's repo: `cloudflared service install`
wrote the unit outside the package's files, so the package's postinst
restarted nothing, and `/proc/<MainPID>/exe` read
`/usr/bin/cloudflared (deleted)` until a reboot taken for other reasons.

What this file pins:

- after each step, `apply.sh` reads `/proc/<MainPID>/exe` for each knob
  `service`. A target ending ` (deleted)` is a `stale_binary` entry (unit,
  pid, path, package, version, and whether this step took the package), a
  `next` line saying the version takes effect only at the unit's restart or
  a reboot, and an input to the reboot decision's own `next` line. A link
  that can't be read is `stale_binary_unread`, never "not stale";
- `verdict.ok` stays true, since the step did what it ran: the verdict's
  `not_in_effect` says the update hasn't taken effect;
- the probe gives each `impact.services` unit `exe_deleted`, true, false or
  null when there's no process or its link can't be read, and a true one is
  the finding `stale-binary:<unit>`, so a pre-run reading catches a daemon
  an earlier run, or unattended-upgrades, left on a replaced binary.
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
UNIT = "tunnel.service"
PID = 4300


def _declared(host, exe: str | None, pid: int = PID):
    """A knob `service` line for UNIT, its MainPID PID, and that PID's exe
    link pointing at EXE (None: no link to read)."""
    host.knob(_apply.KNOB + f"service {UNIT}\n")
    host.show(UNIT, MainPID=str(pid))
    if exe is not None:
        host.link(f"proc/{pid}/exe", exe)
    elif pid:
        # The process is there; its link isn't readable.
        host.write(f"proc/{pid}/status", "Name:\ttunnel\n")
    host.on(
        "dpkg-query",
        "-S *",
        script=(
            'shift; rc=0; for f; do case $f in */redis-server) echo "redis-server: $f" ;; '
            '*) echo "dpkg-query: no path found matching pattern $f" >&2; rc=1 ;; esac; '
            "done; exit $rc"
        ),
    )
    host.on("dpkg-query", "-W redis-server", f"redis-server\t{REDIS_NEW}\n")
    return host


def _redis_step(host, upgraded: str = "redis-server") -> dict:
    host.run()
    host.uu(f"Packages that will be upgraded: {upgraded}\nAll upgrades installed\n")
    return host.run(step="redis")


@pytest.fixture
def ahost(tmp_path):
    return _apply._ready(_apply.Host(tmp_path))


# --- apply.sh, after a step ------------------------------------------------------


def test_a_held_step_whose_service_still_runs_the_replaced_binary_says_so(ahost):
    out = _redis_step(_declared(ahost, f"{REDIS_BIN} (deleted)"))
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


def test_a_service_on_its_current_binary_is_not_stale(ahost):
    out = _redis_step(_declared(ahost, REDIS_BIN))
    assert out["stale_binary"] == []
    assert out["stale_binary_unread"] == []
    assert out["verdict"]["not_in_effect"] == []
    assert out["next"][-1] == "the reboot decision: reboot-and-record.md section 4"
    assert not [n for n in out["next"] if "stale_binary" in n]


def test_a_stale_binary_the_step_didnt_take_is_still_reported(ahost):
    # Left by the bulk, an earlier step or unattended-upgrades: still stale.
    out = _redis_step(_declared(ahost, f"{REDIS_BIN} (deleted)"), upgraded="")
    [e] = out["stale_binary"]
    assert e["taken"] is False
    assert out["next"][-1].endswith("restart it, or reboot")


def test_a_binary_that_cant_be_read_is_unread_not_current(ahost):
    out = _redis_step(_declared(ahost, None))
    assert out["stale_binary"] == []
    assert out["stale_binary_unread"] == [
        {"unit": UNIT, "pid": PID, "why": f"/proc/{PID}/exe couldn't be read as root"}
    ]
    by_hand = [n for n in out["next"] if n.startswith(f"read {UNIT}'s binary by hand")]
    assert by_hand, out["next"]


def test_a_service_with_no_process_runs_no_binary(ahost):
    out = _redis_step(_declared(ahost, None, pid=0))
    assert out["stale_binary"] == []
    assert out["stale_binary_unread"] == []


def test_the_bulk_reads_its_services_binaries_too(ahost):
    _declared(ahost, f"{REDIS_BIN} (deleted)")
    out = ahost.run()
    [e] = out["stale_binary"]
    assert e["unit"] == UNIT and e["taken"] is False


def test_a_refused_step_reads_no_binary(ahost):
    _declared(ahost, f"{REDIS_BIN} (deleted)")
    out = ahost.run(step="postgres", rc=3)
    assert out["stale_binary"] is None
    assert out["stale_binary_unread"] is None


def test_no_declared_service_reads_nothing(ahost):
    out = ahost.run()
    assert out["stale_binary"] == []
    assert not [a for _, a, _ in ahost.calls("systemctl") if "MainPID" in a]


# --- probe.sh, before a run ------------------------------------------------------


host = _probe.host


def _probe_service(host, exe: str | None, pid: int = PID):
    host.knob(f"posture scheduled\nservice {UNIT}\n")
    host.show(
        UNIT,
        After="network.target",
        Result="success",
        NRestarts="0",
        ActiveState="active",
        RequiredBy="",
        BoundBy="",
        MainPID=str(pid),
    )
    if exe is not None:
        host.link(f"proc/{pid}/exe", exe)
    return host


def test_the_probe_reads_a_service_left_on_a_replaced_binary(host):
    out = _probe_service(host, "/usr/bin/cloudflared (deleted)").run()
    [svc] = out["impact"]["services"]
    assert svc["exe_deleted"] is True
    f = _finding(out, f"stale-binary:{UNIT}")
    assert f["kind"] == "risk"
    assert "/usr/bin/cloudflared" in f["message"]


def test_the_probe_reads_a_service_on_its_current_binary(host):
    out = _probe_service(host, "/usr/bin/cloudflared").run()
    [svc] = out["impact"]["services"]
    assert svc["exe_deleted"] is False
    assert f"stale-binary:{UNIT}" not in _ids(out)


@pytest.mark.parametrize("pid, exe", [(0, None), (PID, None)])
def test_no_process_or_an_unreadable_link_is_null(host, pid, exe):
    out = _probe_service(host, exe, pid=pid).run()
    [svc] = out["impact"]["services"]
    assert svc["exe_deleted"] is None
    assert f"stale-binary:{UNIT}" not in _ids(out)
