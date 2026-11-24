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
from tests.structural.test_patching_hosts_lane import (
    EXTRA,
    ORIGINS,
    TS,
    _lane,
    _one_origin,
    _refreshed,
)
from tests.structural.test_patching_hosts_lane import POLICY as LANE_POLICY
from tests.structural.test_patching_hosts_probe import STOCK_ORIGINS, _finding, _ids
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


# Measured on ubuntu:24.04, apt 2.8.3 (CR 2807): pha and phb at 1, -updates
# has 2 of each at Phased-Update-Percentage 0, and -security has phb 1.5.
# Without Always-Include, apt's header lists both as deferred, then it
# installs phb's phased 2 anyway: a pending security update lifts phasing.
MEASURED_WITH = (
    "Inst pha [1] (2 Ubuntu:noble-updates [all])\n"
    "Inst phb [1] (2 Ubuntu:noble-updates [all])\n"
)
MEASURED_WITHOUT = (
    "The following upgrades have been deferred due to phasing:\n"
    "  pha\n"
    "  phb\n"
    "Inst phb [1] (2 Ubuntu:noble-updates [all])\n"
)


def test_a_package_apt_installs_despite_its_header_isnt_deferred(tmp_path):
    h = ProbeHost(tmp_path).knob("class production\nposture scheduled\n")
    h.on(
        "apt-get", "-s *Always-Include-Phased-Updates=true*dist-upgrade", MEASURED_WITH
    )
    h.on("apt-get", "-s *dist-upgrade", MEASURED_WITHOUT)
    h.on(
        "apt-cache",
        "*policy pha phb",
        _policy("pha", "1", "2", 0) + _policy("phb", "1", "2", 0),
    )
    out = h.run()
    # The Inst lines decide, never the header.
    assert out["pending"]["phasing"]["deferred"] == ["pha"]
    assert out["pending"]["phasing"]["in_phase"] == ["phb"]


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


def _origins(h: ProbeHost, extra: str = "") -> ProbeHost:
    h.apt_config(Enable="1", Lists="1", UU="1", Reboot="false")
    h.on("apt-config", "dump", STOCK_ORIGINS + extra)
    return h


WIDE = (
    'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}-updates";\n'
)


def test_respect_doesnt_touch_a_security_only_dry_run(tmp_path):
    h = _origins(
        _probe(tmp_path, "class production\nposture scheduled\nphasing respect\n")
    )
    out = _dry(h, "libc6")
    assert out["pending"]["dry_run"]["security_only"] is True
    [(_, _, apt_config)] = h.calls("unattended-upgrade")
    assert "Package-Blacklist" not in open(apt_config).read()


def test_respect_blacklists_in_a_security_lane_whose_origins_take_updates(tmp_path):
    # CR 2805: a uu:origins exception lets the host's own origins take
    # -updates, phased ones included, in the security lane.
    h = _origins(
        _probe(tmp_path, "class production\nposture scheduled\nphasing respect\n"),
        WIDE,
    )
    out = _dry(h, "libc6 libgl1-mesa-dri")
    assert out["pending"]["dry_run"]["security_only"] is False
    [(_, _, apt_config)] = h.calls("unattended-upgrade")
    skipped = open(apt_config).read().split("Package-Blacklist {")[1]
    assert '  "^libsystemd0$";' in skipped and '  "^udev$";' in skipped
    summary = (h.tmp / "dry" / "summary").read_text()
    assert "phasing=respect\nphased_deferred=libsystemd0 udev\n" in summary


def test_the_default_flags_a_security_lane_that_forces_phased_updates(tmp_path):
    h = _origins(_probe(tmp_path), WIDE)
    out = _dry(h, "libc6 libsystemd0 udev")
    f = _finding(out, "dry-run:phased")
    assert "The security lane takes 2 phased updates apt would defer" in f["message"]


def test_under_respect_a_dry_run_that_still_takes_a_deferred_one_says_so(tmp_path):
    # CR 2806: the blacklist didn't hold, as a host apt.conf.d line that
    # clears it, read after APT_CONFIG, makes it.
    h = _probe(tmp_path, "class production\nposture scheduled\nphasing respect\n")
    out = _dry(h, "libc6 libsystemd0", "--lane", "maintenance")
    f = _finding(out, "dry-run:phased")
    assert f["kind"] == "risk"
    for word in ("blacklist", "didn't hold", "libsystemd0", "Package-Blacklist"):
        assert word in f["message"], word


def test_respect_with_the_set_unsimulated_points_at_the_simulation(tmp_path):
    # CR 2811: not_read says nothing of it; pending:simulate does.
    h = _probe(tmp_path, "class production\nposture scheduled\nphasing respect\n")
    h.cases["apt-get"] = [("-s *dist-upgrade", "", 100, "E: boom\n", None)]
    out = _dry(h, "libc6", "--lane", "maintenance")
    f = _finding(out, "dry-run")
    assert "pending:simulate" in f["message"] and "not_read" not in f["message"]


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


HOST_DUMP = (
    'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}";\n'
    'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}-security";\n'
)


def _dump(host: ApplyHost, extra: str = "", blacklist: bool = True) -> None:
    """apt-config dump: the host's own entries, then each list an APT_CONFIG
    file adds, its Package-Blacklist only where BLACKLIST (a host line that
    clears it, read after the file, leaves none)."""
    host.cases["apt-config"] = [c for c in host.cases["apt-config"] if c[0] != "dump"]
    text = host.state / "dump"
    text.write_text(HOST_DUMP + extra)
    keep = "" if blacklist else ' && b != "Unattended-Upgrade::Package-Blacklist"'
    adds = (
        'if [ -n "${APT_CONFIG:-}" ]; then awk \''
        '/^[A-Za-z].* \\{$/ { b = $1; next } /^};/ { b = ""; next } '
        f'/^  "/ && b != ""{keep} {{ sub(/^  /, ""); print b ":: " $0 }}'
        '\' "$APT_CONFIG"; fi; '
    )
    host.on("apt-config", "dump", script=f'cat "{text}"; {adds}exit 0')


def _bulk(
    tmp_path,
    phasing: str = "respect",
    summary: str = "",
    lane: str = "maintenance",
    extra_knob: str = "",
) -> ApplyHost:
    """A bulk with postgresql-16 from -security and the phased libsystemd0
    and udev, which apt defers here; udev is a hold group's."""
    line = f"phasing {phasing}\n" if phasing else ""
    host = _lane(tmp_path, KNOB + ORIGINS + "hold udev sysd\n" + line + extra_knob)
    _dump(host, WIDE if lane == "security" else "")
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
        f"security_only=0\nlane={lane}\nlists_refreshed=1\n"
        "held_versions=udev=255.4-1ubuntu8.11\n" + summary
    )
    (host.dry / "dry-run.log").write_text(
        "Packages that will be upgraded: postgresql-16\n"
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
        ("respect", "phasing=ignore\nphased_deferred=libsystemd0\n", "ignore"),
        ("", RESPECTED, "respect"),
    ],
    ids=["no-line", "ignore-unread", "ignore", "respect"],
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


def test_a_dry_run_under_the_other_phasing_with_nothing_deferred_isnt_refused(
    tmp_path,
):
    # CR 2809: nothing deferred, so its count can't differ.
    host = _bulk(tmp_path, "respect", "phasing=ignore\nphased_deferred=\n")
    out = host.run("--lane", "maintenance")
    assert not [r for r in out["refused"] if "phasing" in r], out["refused"]


@pytest.mark.parametrize("word", ['udev";', "$(id)", "Udev", "-x", "a b\\"])
def test_a_deferred_name_that_isnt_a_package_name_is_refused(tmp_path, word):
    # CR 2810: the summary is the operator's file, and lane.conf is root's.
    host = _bulk(
        tmp_path, summary=f"phasing=respect\nphased_deferred=libsystemd0 {word}\n"
    )
    out = host.run("--lane", "maintenance", rc=3)
    assert any("isn't a package name" in r for r in out["refused"]), out["refused"]
    assert not host.calls("unattended-upgrade")


def test_a_blacklist_apt_doesnt_read_fails_before_any_hold(tmp_path):
    # CR 2806: read back through apt-config, as the lane's patterns are.
    host = _bulk(tmp_path, summary=RESPECTED)
    _dump(host, blacklist=False)
    out = host.run("--lane", "maintenance", rc=1)
    assert any(
        "Package-Blacklist" in f and "libsystemd0" in f for f in out["verdict"]["why"]
    ), out
    assert not [a for _, a, _ in host.calls("apt-mark") if a.startswith("hold")]
    assert not host.calls("unattended-upgrade")


def test_a_deferred_update_the_bulk_took_fails_it(tmp_path):
    # CR 2806: a host line read after APT_CONFIG can still clear it for
    # unattended-upgrade, which re-reads apt.conf.d.
    host = _bulk(tmp_path, summary=RESPECTED)
    host.uu(
        "Packages that will be upgraded: postgresql-16 libsystemd0\n"
        "All upgrades installed\n"
    )
    out = host.run("--lane", "maintenance", rc=1)
    assert any(
        "took libsystemd0" in f and "phasing respect" in f
        for f in out["verdict"]["why"]
    ), out["verdict"]["why"]


def test_one_deferred_now_that_the_dry_run_counted_is_named(tmp_path):
    # CR 2808: in phase at the dry run, deferred at the bulk: it leaves the
    # approved set, and its held step has nothing to take.
    host = _bulk(tmp_path, summary="phasing=respect\nphased_deferred=libsystemd0\n")
    (host.dry / "dry-run.log").write_text(
        "Packages that will be upgraded: postgresql-16 udev\n"
    )
    out = host.run("--lane", "maintenance")
    assert out["holds"]["newly_deferred"] == ["udev"]
    [n] = [x for x in out["next"] if "udev" in x and "phas" in x]
    assert "sysd" in n and "dry run counted" in n


def test_respect_in_a_security_lane_whose_origins_take_updates(tmp_path):
    # CR 2805: the bulk and its held steps read the blacklist from lane.conf.
    host = _bulk(
        tmp_path,
        summary=RESPECTED,
        lane="security",
        extra_knob="exception uu:origins 2026-12-31 the owner takes -updates\n",
    )
    out = host.run()
    assert out["holds"]["phased_deferred"] == ["libsystemd0", "udev"]
    skipped = host.record("lane.conf").split("Package-Blacklist {")[1]
    assert '  "^libsystemd0$";' in skipped
    assert [c for _, _, c in host.calls("unattended-upgrade")] == [
        str(host.run_dir / "lane.conf")
    ]


def test_a_security_lanes_held_step_reads_the_bulks_blacklist(tmp_path):
    # CR 2812: the bulk wrote lane.conf, so its held steps read it too.
    host = _bulk(
        tmp_path,
        summary=RESPECTED,
        lane="security",
        extra_knob="exception uu:origins 2026-12-31 the owner takes -updates\n",
    )
    out = host.run()
    assert out["holds"]["placed"].get("postgres") == ["postgresql-16"], out["holds"]
    host.uu("Packages that will be upgraded: postgresql-16\nAll upgrades installed\n")
    host.run(step="postgres")
    assert [c for _, _, c in host.calls("unattended-upgrade")] == [
        str(host.run_dir / "lane.conf")
    ] * 2


def test_respect_leaves_the_one_origin_lane_alone(tmp_path):
    # CR 2812: a one-origin lane takes its origin's packages alone, and a
    # third party's aren't phased. Under respect, its bulk rewrote lane.conf
    # with the phased blacklist alone, and took every pending package.
    knob = (
        KNOB + ORIGINS.replace("Tailscale", "pkgs.tailscale.com") + "phasing respect\n"
    )
    host = _one_origin(tmp_path, knob)
    with (host.dry / "summary").open("a") as f:
        f.write("phasing=respect\nphased_deferred=libsystemd0\n")
    out = host.run("--lane", TS)
    assert out["verdict"]["ok"] is True, out
    skipped = host.record("lane.conf").split("Package-Blacklist {")[1]
    assert '  "^libc6$";' in skipped
    assert "libsystemd0" not in skipped
    assert "phased_deferred" not in out["holds"]


def test_respect_leaves_the_probes_one_origin_dry_run_alone(tmp_path):
    # CR 2812: the dry run and the bulk agree; the skip list stays one list.
    h = ProbeHost(tmp_path).knob(
        "class production\nposture scheduled\norigin pkgs.tailscale.com follow\n"
        "phasing respect\n"
    )
    libc = "Inst libc6 [2.39-0ubuntu8.3] (2.39-0ubuntu8.4 Ubuntu:24.04/noble-security [arm64])\n"
    sysd = f"Inst libsystemd0 [255.4-1ubuntu8.10] (255.4-1ubuntu8.11 {UPD})\n"
    h.on(
        "apt-get",
        "-s *Always-Include-Phased-Updates=true*dist-upgrade",
        libc + sysd + EXTRA,
    )
    h.on("apt-get", "-s *dist-upgrade", libc + EXTRA)
    h.on(
        "apt-cache",
        "*policy libc6 *",
        _policy("libsystemd0", "255.4-1ubuntu8.10", "255.4-1ubuntu8.11", 10),
    )
    h.on("apt-cache", "*policy", LANE_POLICY)
    h.on(
        "unattended-upgrade",
        "--dry-run -d",
        "Packages that will be upgraded: tailscale\n",
    )
    out = h.run(*_refreshed(h), "--dry-run-into", str(h.tmp / "dry"), "--lane", TS)
    assert out["pending"]["phasing"]["deferred"] == ["libsystemd0"]
    [(_, _, apt_config)] = h.calls("unattended-upgrade")
    conf = open(apt_config).read()
    assert conf.count("Package-Blacklist {") == 1
    assert conf.count('"^libsystemd0$"') == 1
