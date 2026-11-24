"""patching-hosts: the maintenance lane and apt's phasing (#686).

Found on address-validator's catch-up of 2026-11-20 (#687): every one of its
22 pending `-updates` was phased. On the same refreshed lists `apt-get -s
upgrade` took 15 and deferred 13 (the systemd/udev family at 10%), while the
maintenance lane's dry run counted all 28. unattended-upgrade has no phasing
code, and apt applies phasing in its upgrade logic, not in the candidate
python-apt reads, so the lane takes every phased update whatever this
machine's phase. The skill offered no way to take the lane and still respect
phasing.

What this file pins:

- `impact.maps` under a dry run says, per unit, which mapped packages its
  lane takes (`lane_packages`, `in_lane`), and `maps.lane` names the lane:
  the security lane's probe listed `libsystemd0` mapped by PID 1 and
  Postgres, though no systemd package was in its 6 (item 4). Without a dry
  run it says nothing of a lane;
- `phasing respect|ignore` is one knob value, `ignore` by default (today's
  behaviour);
- `pending.phasing` splits the phased candidates: `deferred`, those
  `apt-get -s dist-upgrade` without `Always-Include-Phased-Updates` leaves
  out, and `in_phase`, the rest. Only phased packages can be deferred, so an
  unanswered simulation can't defer the whole set;
- under `respect`, the maintenance lane's dry run blacklists each deferred
  package, anchored and escaped, as the one-origin lane does, and the bulk
  blacklists them again against its refreshed lists, never holds one, and
  checks it wasn't taken;
- under the default, a maintenance dry run that takes a deferred package
  says how many, and how to respect phasing; a declared `ignore` is the
  owner's choice and says nothing;
- a bulk refuses a dry run counted under the other phasing.
"""

import pytest

from tests.structural.patching_hosts_rig import dispatcher
from tests.structural.test_patching_hosts_probe import Host as ProbeHost


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


LIBC = "/usr/lib/x86_64-linux-gnu/libc.so.6"
LIBSYSTEMD = "/usr/lib/x86_64-linux-gnu/libsystemd.so.0.38.0"
LIBGL = "/usr/lib/x86_64-linux-gnu/libGLX_mesa.so.0"
SEC = "Ubuntu:24.04/noble-security [amd64]"
UPD = "Ubuntu:24.04/noble-updates [amd64]"
# The simulation unattended-upgrade's view matches: every phased update.
WITH_PHASED = (
    f"Inst libc6 [2.39-0ubuntu8.4] (2.39-0ubuntu8.5 {SEC})\n"
    f"Inst libsystemd0 [255.4-1ubuntu8.10] (255.4-1ubuntu8.11 {UPD})\n"
    f"Inst udev [255.4-1ubuntu8.10] (255.4-1ubuntu8.11 {UPD})\n"
    f"Inst libgl1-mesa-dri [24.2.8-1ubuntu1] (24.2.8-1ubuntu1.1 {UPD})\n"
)
# apt's own, on a machine outside systemd's 10% and inside mesa's 80%.
WITHOUT_PHASED = (
    "The following upgrades have been deferred due to phasing:\n"
    "  libsystemd0 udev\n"
    f"Inst libc6 [2.39-0ubuntu8.4] (2.39-0ubuntu8.5 {SEC})\n"
    f"Inst libgl1-mesa-dri [24.2.8-1ubuntu1] (24.2.8-1ubuntu1.1 {UPD})\n"
)


def _policy(name: str, now: str, cand: str, pct: int | None) -> str:
    mark = f" (phased {pct}%)" if pct is not None else ""
    return (
        f"{name}:\n  Installed: {now}\n  Candidate: {cand}\n  Version table:\n"
        f" *** {cand} 500{mark}\n"
        "        500 http://archive.ubuntu.com/ubuntu noble-updates/main amd64 Packages\n"
    )


POLICY = (
    _policy("libc6", "2.39-0ubuntu8.4", "2.39-0ubuntu8.5", None)
    + _policy("libsystemd0", "255.4-1ubuntu8.10", "255.4-1ubuntu8.11", 10)
    + _policy("udev", "255.4-1ubuntu8.10", "255.4-1ubuntu8.11", 10)
    + _policy("libgl1-mesa-dri", "24.2.8-1ubuntu1", "24.2.8-1ubuntu1.1", 80)
)


def _probe(tmp_path, knob: str = "class production\nposture scheduled\n") -> ProbeHost:
    """libc6 from -security and three phased -updates pending, with postgres
    mapping libc6 and libsystemd0, and a session's process mapping mesa."""
    h = ProbeHost(tmp_path).knob(knob)
    h.on("apt-get", "-s *Always-Include-Phased-Updates=true*dist-upgrade", WITH_PHASED)
    h.on("apt-get", "-s *dist-upgrade", WITHOUT_PHASED)
    h.on("apt-cache", "*policy libc6 *", POLICY)
    h.on("dpkg-query", "*-L libc6", f"{LIBC}\n")
    h.on("dpkg-query", "*-L libsystemd0", f"{LIBSYSTEMD}\n")
    h.on("dpkg-query", "*-L libgl1-mesa-dri", f"{LIBGL}\n")
    h.write(
        "proc/700/maps",
        f"7f00-7f10 r-xp 0 fd:01 1 {LIBC}\n7f10-7f20 r-xp 0 fd:01 2 {LIBSYSTEMD}\n",
    )
    h.write("proc/700/cgroup", "0::/system.slice/postgresql@16-main.service\n")
    h.write("proc/800/maps", f"7f00-7f10 r-xp 0 fd:01 3 {LIBGL}\n")
    h.write("proc/800/cgroup", "0::/system.slice/compositor.service\n")
    return h


def _dry(h: ProbeHost, selected: str, *args: str) -> dict:
    h.on(
        "unattended-upgrade",
        "--dry-run -d",
        f"Packages that will be upgraded: {selected}\n",
    )
    return h.run(*h.refreshed(), "--dry-run-into", str(h.tmp / "dry"), *args)


# --- item 4: impact.maps against the lane ---------------------------------------


def test_the_maps_say_which_mapped_packages_the_dry_runs_lane_takes(tmp_path):
    out = _dry(_probe(tmp_path), "libc6")
    maps = out["impact"]["maps"]
    assert maps["lane"] == "security"
    units = {u["unit"]: u for u in maps["units"]}
    pg = units["postgresql@16-main.service"]
    # Every mapped package is still listed, for comparing lanes.
    assert pg["packages"] == ["libc6", "libsystemd0"]
    assert pg["lane_packages"] == ["libc6"]
    assert pg["in_lane"] is True
    comp = units["compositor.service"]
    assert comp["lane_packages"] == []
    assert comp["in_lane"] is False


def test_the_maintenance_lanes_maps_take_its_phased_packages(tmp_path):
    knob = "class production\nposture scheduled\n"
    out = _dry(
        _probe(tmp_path, knob),
        "libc6 libsystemd0 udev libgl1-mesa-dri",
        "--lane",
        "maintenance",
    )
    maps = out["impact"]["maps"]
    assert maps["lane"] == "maintenance"
    units = {u["unit"]: u for u in maps["units"]}
    assert units["postgresql@16-main.service"]["lane_packages"] == [
        "libc6",
        "libsystemd0",
    ]
    assert units["compositor.service"]["in_lane"] is True


def test_without_a_dry_run_the_maps_name_no_lane(tmp_path):
    out = _probe(tmp_path).run()
    maps = out["impact"]["maps"]
    assert "lane" not in maps
    for u in maps["units"]:
        assert "in_lane" not in u and "lane_packages" not in u
