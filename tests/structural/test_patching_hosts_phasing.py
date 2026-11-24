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
from tests.structural.test_patching_hosts_apply import KNOB, SIM_ARGS, TUE_1530
from tests.structural.test_patching_hosts_apply import Host as ApplyHost
from tests.structural.test_patching_hosts_knob import KNOB_MD, _read
from tests.structural.test_patching_hosts_lane import ORIGINS, _lane
from tests.structural.test_patching_hosts_probe import Host as ProbeHost
from tests.structural.test_patching_hosts_probe import _finding, _ids


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


# --- the knob's phasing line ----------------------------------------------------


def test_phasing_defaults_to_ignore(tmp_path):
    assert _read(tmp_path, "posture scheduled\n")["phasing"] == {
        "value": "ignore",
        "line": None,
    }


@pytest.mark.parametrize("value", ["respect", "ignore"])
def test_a_phasing_line_is_respect_or_ignore(tmp_path, value):
    out = _read(tmp_path, f"posture scheduled\nphasing {value}\n")
    assert out["phasing"] == {"value": value, "line": 2}
    assert out["findings"] == []


@pytest.mark.parametrize("line", ["phasing", "phasing on", "phasing respect ignore"])
def test_a_bad_phasing_line_is_malformed(tmp_path, line):
    out = _read(tmp_path, f"posture scheduled\n{line}\n")
    [f] = out["findings"]
    assert f["kind"] == "malformed"
    assert "phasing takes respect or ignore" in f["message"]
    assert out["report_only"] is True


def test_a_phasing_line_is_one_value_the_most_specific_scope_sets(tmp_path):
    text = "posture scheduled\nphasing respect\n[host web-*]\nphasing ignore\n"
    assert _read(tmp_path, text)["phasing"] == {"value": "ignore", "line": 4}


def test_knob_md_names_the_phasing_directive():
    text = KNOB_MD.read_text()
    table = text.split("## Directives", 1)[1]
    [row] = [r for r in table.splitlines() if r.startswith("| `phasing")]
    for word in ("respect", "ignore", "Package-Blacklist", "#686"):
        assert word in row, word
    one_value = [r for r in text.splitlines() if r.startswith("| one value")][0]
    assert "`phasing`" in one_value


# --- pending.phasing: the split -------------------------------------------------


def test_the_probe_splits_the_phased_updates_into_deferred_and_in_phase(tmp_path):
    out = _probe(tmp_path).run()
    p = out["pending"]
    # The percentages, as before.
    assert p["phased"] == {"libsystemd0": 10, "udev": 10, "libgl1-mesa-dri": 80}
    assert p["phasing"] == {
        "knob": "ignore",
        "deferred": ["libsystemd0", "udev"],
        "in_phase": ["libgl1-mesa-dri"],
    }


def test_only_a_phased_package_is_deferred(tmp_path):
    # A simulation that answered nothing defers only what's phased: libc6 is
    # missing from it, and isn't deferred.
    h = _probe(tmp_path)
    h.cases["apt-get"] = [
        c for c in h.cases["apt-get"] if c[0] != "-s *dist-upgrade"
    ] + [("-s *dist-upgrade", "", 0, "", None)]
    out = h.run()
    assert out["pending"]["phasing"]["deferred"] == [
        "libsystemd0",
        "udev",
        "libgl1-mesa-dri",
    ]


def test_nothing_phased_runs_no_second_simulation(tmp_path):
    h = _probe(tmp_path)
    h.cases["apt-cache"] = [
        ("*policy libc6 *", POLICY.split("libsystemd0:")[0], 0, "", None)
    ]
    out = h.run()
    assert out["pending"]["phasing"] == {
        "knob": "ignore",
        "deferred": [],
        "in_phase": [],
    }
    sims = [a for _, a, _ in h.calls("apt-get") if a.endswith("dist-upgrade")]
    assert len(sims) == 1, sims


def test_a_simulation_without_phased_updates_that_fails_is_unread(tmp_path):
    h = _probe(tmp_path)
    h.cases["apt-get"] = [
        c for c in h.cases["apt-get"] if c[0] != "-s *dist-upgrade"
    ] + [("-s *dist-upgrade", "", 100, "E: boom\n", None)]
    out = h.run()
    assert out["pending"]["phasing"] is None
    assert [n for n in out["not_read"] if "apt would defer" in n]


# --- the dry run under each phasing ---------------------------------------------


def test_the_default_says_how_many_phased_updates_the_lane_forces(tmp_path):
    out = _dry(
        _probe(tmp_path),
        "libc6 libsystemd0 udev libgl1-mesa-dri",
        "--lane",
        "maintenance",
    )
    d = out["pending"]["dry_run"]
    assert d["phased_deferred"] == ["libsystemd0", "udev"]
    f = _finding(out, "dry-run:phased")
    assert f["kind"] == "risk"
    m = f["message"]
    for word in (
        "takes 2 phased updates apt would defer",
        "libsystemd0 udev",
        "phasing respect",
    ):
        assert word in m, word


def test_a_declared_ignore_is_the_owners_choice_and_says_nothing(tmp_path):
    out = _dry(
        _probe(tmp_path, "class production\nposture scheduled\nphasing ignore\n"),
        "libc6 libsystemd0 udev libgl1-mesa-dri",
        "--lane",
        "maintenance",
    )
    assert out["pending"]["dry_run"]["phased_deferred"] == ["libsystemd0", "udev"]
    assert "dry-run:phased" not in _ids(out)


def test_respect_blacklists_the_deferred_in_the_maintenance_dry_run(tmp_path):
    h = _probe(tmp_path, "class production\nposture scheduled\nphasing respect\n")
    out = _dry(h, "libc6 libgl1-mesa-dri", "--lane", "maintenance")
    [(_, _, apt_config)] = h.calls("unattended-upgrade")
    skipped = open(apt_config).read().split("Package-Blacklist {")[1]
    assert '  "^libsystemd0$";' in skipped and '  "^udev$";' in skipped
    assert "mesa" not in skipped
    d = out["pending"]["dry_run"]
    assert d["phased_deferred"] == []
    assert "dry-run:phased" not in _ids(out)
    summary = (h.tmp / "dry" / "summary").read_text()
    assert "phasing=respect\nphased_deferred=libsystemd0 udev\n" in summary


def test_respect_doesnt_touch_the_security_lanes_dry_run(tmp_path):
    h = _probe(tmp_path, "class production\nposture scheduled\nphasing respect\n")
    _dry(h, "libc6")
    [(_, _, apt_config)] = h.calls("unattended-upgrade")
    assert "Package-Blacklist" not in open(apt_config).read()


def test_respect_with_the_split_unread_doesnt_run_the_maintenance_dry_run(tmp_path):
    h = _probe(tmp_path, "class production\nposture scheduled\nphasing respect\n")
    h.cases["apt-get"] = [
        c for c in h.cases["apt-get"] if c[0] != "-s *dist-upgrade"
    ] + [("-s *dist-upgrade", "", 100, "E: boom\n", None)]
    out = _dry(h, "libc6", "--lane", "maintenance")
    f = _finding(out, "dry-run")
    assert "phasing respect" in f["message"]
    assert not h.calls("unattended-upgrade")


# --- the bulk under respect -----------------------------------------------------

NOPHASE_ARGS = "-s -o Dir::Log::Planner=/dev/null dist-upgrade"
BULK_SIM = (
    "Inst postgresql-16 [16.9-0ubuntu0.24.04.1] "
    "(16.10-0ubuntu0.24.04.1 Ubuntu:24.04/noble-security [arm64])\n"
    "Inst libsystemd0 [255.4-1ubuntu8.10] (255.4-1ubuntu8.11 Ubuntu:24.04/noble-updates [arm64])\n"
    "Inst udev [255.4-1ubuntu8.10] (255.4-1ubuntu8.11 Ubuntu:24.04/noble-updates [arm64])\n"
)
BULK_NOPHASE = BULK_SIM.split("Inst libsystemd0")[0]


def _bulk(tmp_path, phasing: str = "respect", summary: str = "") -> ApplyHost:
    """A maintenance bulk with postgresql-16 from -security and the phased
    libsystemd0 and udev, which apt defers here; udev is a hold group's."""
    line = f"phasing {phasing}\n" if phasing else ""
    host = _lane(tmp_path, KNOB + ORIGINS + "hold udev sysd\n" + line)
    host.cases["apt-get"].insert(0, (SIM_ARGS, BULK_SIM, 0, "", None))
    host.cases["apt-get"].insert(0, (NOPHASE_ARGS, BULK_NOPHASE, 0, "", None))
    host.on(
        "apt-cache",
        "policy postgresql-16 *",
        _policy(
            "postgresql-16", "16.9-0ubuntu0.24.04.1", "16.10-0ubuntu0.24.04.1", None
        )
        + _policy("libsystemd0", "255.4-1ubuntu8.10", "255.4-1ubuntu8.11", 10)
        + _policy("udev", "255.4-1ubuntu8.10", "255.4-1ubuntu8.11", 10),
    )
    (host.dry / "summary").write_text(
        f"began={TUE_1530 - 3600}\nexit=0\ncount=1\nwall_seconds=60\n"
        "security_only=0\nlane=maintenance\nlists_refreshed=1\n"
        "held_versions=udev=255.4-1ubuntu8.11\n" + summary
    )
    return host


RESPECTED = "phasing=respect\nphased_deferred=libsystemd0 udev\n"


def test_respect_blacklists_what_apt_defers_and_holds_none_of_it(tmp_path):
    host = _bulk(tmp_path, summary=RESPECTED)
    out = host.run("--lane", "maintenance")
    assert out["verdict"]["ok"] is True, out
    skipped = host.record("lane.conf").split("Package-Blacklist {")[1]
    assert '  "^libsystemd0$";' in skipped and '  "^udev$";' in skipped
    assert "postgresql" not in skipped
    h = out["holds"]
    assert h["phased_deferred"] == ["libsystemd0", "udev"]
    # A hold group's deferred package is never held, and is checked untaken.
    assert "sysd" not in h["placed"]
    assert "udev" in h["not_in_lane"]
    assert h["taken_unheld"] == []


def test_respect_blacklists_what_the_dry_run_left_though_its_in_phase_now(tmp_path):
    host = _bulk(
        tmp_path, summary="phasing=respect\nphased_deferred=libsystemd0 udev zlib1g\n"
    )
    host.run("--lane", "maintenance")
    assert '  "^zlib1g$";' in host.record("lane.conf")


@pytest.mark.parametrize(
    "phasing, summary, counted",
    [
        ("respect", "", "ignore"),
        ("respect", "phasing=ignore\n", "ignore"),
        ("", RESPECTED, "respect"),
    ],
    ids=["no-line", "ignore", "respect"],
)
def test_a_dry_run_counted_under_the_other_phasing_is_refused(
    tmp_path, phasing, summary, counted
):
    host = _bulk(tmp_path, phasing, summary)
    out = host.run("--lane", "maintenance", rc=3)
    knob = phasing or "ignore"
    want = f"the dry run counted with phasing {counted}, and the knob says {knob}"
    assert any(want in r for r in out["refused"]), out["refused"]
    assert not host.calls("unattended-upgrade")


def test_ignore_runs_no_simulation_without_phased_updates(tmp_path):
    host = _bulk(tmp_path, "", "phasing=ignore\nphased_deferred=libsystemd0 udev\n")
    out = host.run("--lane", "maintenance")
    assert "phased_deferred" not in out["holds"]
    assert not [a for _, a, _ in host.calls("apt-get") if a == NOPHASE_ARGS]
    assert "Package-Blacklist" not in host.record("lane.conf")


def test_a_deferred_hold_group_package_whose_candidate_moved_isnt_held(tmp_path):
    # Outside the dry run's selection at a candidate it didn't count, a
    # group's package is held as before (#383); deferred, it's blacklisted,
    # so a held step would take nothing.
    host = _bulk(tmp_path, summary=RESPECTED)
    s = host.dry / "summary"
    s.write_text(
        s.read_text().replace("udev=255.4-1ubuntu8.11", "udev=255.4-1ubuntu8.9")
    )
    out = host.run("--lane", "maintenance")
    assert "sysd" not in out["holds"]["placed"]
    assert "udev" in out["holds"]["not_in_lane"]
    assert not [a for _, a, _ in host.calls("apt-mark") if "udev" in a]
