"""patching-hosts' free-space reckoning: `_probe-lib.sh`'s step sizes, the
canonical disk GC's config, and the gate over them (#390).

apply.sh gates each step on it, and probe.sh's dry run reports it. What
this file pins:

- a step's download and install growth are apt's own figures, read from its
  metadata: each candidate's Size, less one already in apt's cache at that
  size, and its Installed-Size against the installed version's. The
  fixtures are noble's real output (apt 2.8.3, dpkg 1.22, 2026-10-26), for
  which `apt-get --assume-no upgrade` printed "Need to get 2661 kB" and
  "After this operation, 288 kB": 2660798 bytes, and 281 KiB;
- `apt-get --assume-no` itself is never the reading: an install of exactly
  the packages it names asks no question, so it installs them (measured on
  noble: `apt-get --assume-no install --only-upgrade zlib1g zlib1g-dev`
  upgraded both and exited 0);
- the largest upgrade's Installed-Size is the step's peak: dpkg unpacks an
  upgrade beside the files it replaces (a 195313 KiB package took 196508
  KiB more at its peak, and nothing after);
- each filesystem keeps a 131072 KiB floor, apt's cache and / share one
  need where they share a filesystem, and a reading df can't give is
  unknown, never a pass;
- the GC's config, /etc/cannobserv/disk-gc/disk-gc.conf: absent, the gate
  is the space alone; present, a step whose download and growth would take
  the sensor's mount to its alert_at_percent or past it is refused; and an
  unreadable or malformed file is a finding, never a silent pass. A key it
  leaves out takes the GC's own VERSION 2 default (load_config): 85, and /.
"""

import os

import pytest

from tests.structural.patching_hosts_rig import SKILL, dispatcher
from tests.structural.patching_hosts_rig import Host as RigHost

LIB = SKILL / "scripts" / "_probe-lib.sh"
CONF = "etc/cannobserv/disk-gc/disk-gc.conf"
FLOOR = 131072

# Real output, noble, 2026-10-26: tzdata, age and bison each one release
# behind. apt-get -s's header lines go to stdout too.
SIM = "Reading package lists...\nBuilding dependency tree...\nReading state information...\nSuggested packages:\n  bison-doc\nThe following packages will be upgraded:\n  age bison tzdata\n3 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.\nInst tzdata [2024a-2ubuntu1] (2026e-0ubuntu0.24.04.1 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [all])\nInst age [1.1.1-1build1] (1.1.1-1ubuntu0.24.04.3 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [amd64])\nInst bison [2:3.8.2+dfsg-1build2] (2:3.8.2+dfsg-1ubuntu0.24.04.1 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [amd64])\nConf tzdata (2026e-0ubuntu0.24.04.1 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [all])\nConf age (1.1.1-1ubuntu0.24.04.3 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [amd64])\nConf bison (2:3.8.2+dfsg-1ubuntu0.24.04.1 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [amd64])\n"
SIM_ARGS = "-s -o APT::Get::Always-Include-Phased-Updates=true install --only-upgrade "
SHOW = "Package: tzdata\nPriority: important\nSection: libs\nInstalled-Size: 1389\nMaintainer: Ubuntu Developers <ubuntu-devel-discuss@lists.ubuntu.com>\nArchitecture: all\nVersion: 2026e-0ubuntu0.24.04.1\nReplaces: tzdata-legacy (= 2023c-8ubuntu1)\nProvides: tzdata-trixie\nDepends: debconf (>= 0.5) | debconf-2.0\nBreaks: tzdata-legacy (= 2023c-8ubuntu1)\nFilename: pool/main/t/tzdata/tzdata_2026e-0ubuntu0.24.04.1_all.deb\nSize: 282136\nMD5sum: d04b4d9c76a0acb9f3bdd9408abb857e\nSHA1: 7a8ef24b3da7c6e73cb12f7a2fbdf7faac4f540d\nSHA256: 2f6794a7f31753fc947d9ac02ff03ea46510f34864f9d132a93d7b105e3c4447\nSHA512: 9fb7d6cc56ee21cc8597338a0ff09d93c7f6a979f0a8e22d9421d3bd4685c214d928e1436ecf291184157a029e055fd3091ce68d1c1e41d56c15c01cf3a543ca\nHomepage: https://www.iana.org/time-zones\nDescription: time zone and daylight-saving time data\nDescription-md5: a77a3cc9a67658dd7cfdc6547391b8f8\nMulti-Arch: foreign\nOriginal-Maintainer: GNU Libc Maintainers <debian-glibc@lists.debian.org>\nOrigin: Ubuntu\nBugs: https://bugs.launchpad.net/ubuntu/+filebug\nTask: cloud-minimal, minimal, server-minimal\n\nPackage: age\nPriority: optional\nSection: universe/utils\nInstalled-Size: 5829\nMaintainer: Ubuntu Developers <ubuntu-devel-discuss@lists.ubuntu.com>\nArchitecture: amd64\nVersion: 1.1.1-1ubuntu0.24.04.3\nDepends: libc6 (>= 2.34)\nFilename: pool/universe/a/age/age_1.1.1-1ubuntu0.24.04.3_amd64.deb\nSize: 1629868\nMD5sum: ebd0a1a1db79453e54687d06eaf13415\nSHA1: d4b750d14a7b12011bce6c649b407bf85288dc4c\nSHA256: 22ed034e16d8a7662d94dbb8d9f644f01284c6d87bc6b619903e38ba91125337\nSHA512: d78a9642282acaf9b673e383dfab5f144c9c1c9ea3bd06ef0c9be1e8c10f084ed7f2db2496d097c6d3a8328b25cf865daf878b397c015c685f48680db8bb5825\nHomepage: https://github.com/FiloSottile/age\nDescription: simple, modern and secure encryption tool\nDescription-md5: 85dd9ab1e3fd8da906518326d4c6e3d4\nBuilt-Using: golang-1.22 (= 1.22.2-2ubuntu0.4), golang-filippo-edwards25519 (= 1.0.0~rc1+git20210721-0.1), golang-go.crypto (= 1:0.19.0-1), golang-golang-x-sys (= 0.17.0-1), golang-golang-x-term (= 0.17.0-1)\nOriginal-Maintainer: Debian Go Packaging Team <team+pkg-go@tracker.debian.org>\nOrigin: Ubuntu\nBugs: https://bugs.launchpad.net/ubuntu/+filebug\n\nPackage: bison\nPriority: optional\nSection: devel\nInstalled-Size: 2456\nMaintainer: Ubuntu Developers <ubuntu-devel-discuss@lists.ubuntu.com>\nArchitecture: amd64\nVersion: 2:3.8.2+dfsg-1ubuntu0.24.04.1\nSuggests: bison-doc\nDepends: m4, libc6 (>= 2.38)\nFilename: pool/main/b/bison/bison_3.8.2+dfsg-1ubuntu0.24.04.1_amd64.deb\nSize: 748794\nMD5sum: dfd0ee7383158a5021011734efd1fac7\nSHA1: 40bc7984f26286de24edfe50d8e7584052938a0f\nSHA256: 9d75084d1293f68f3c1a2ee677dea5baa4e010bac2d4c455d8e23177e97aa353\nSHA512: f3b32d1cc5a8f41cc8c5e2ae8e48a18e42bafed9ecffd56136b9aed8bdd45d2a8495135ce165145efc2cde30ff8b530345ca9ff0016b4298ba8c99363d537f0a\nHomepage: https://www.gnu.org/software/bison/\nDescription: YACC-compatible parser generator\nDescription-md5: 3b8154d16aa228f689bcd81364e7088c\nMulti-Arch: foreign\nOriginal-Maintainer: Chuan-kai Lin <cklin@debian.org>\nOrigin: Ubuntu\nBugs: https://bugs.launchpad.net/ubuntu/+filebug\n\n"
DPKG = "age:amd64 5556\nbison:amd64 2456\ntzdata:all 1381\n"
# 1629868 + 748794 + 282136 bytes; (5829 - 5556) + (2456 - 2456) + (1389 - 1381)
DOWNLOAD = (2660798 + 1023) // 1024
GROWTH = 281
PEAK = 5829

# df -P as coreutils 9.4 prints it on noble.
DF_HEAD = "Filesystem     1024-blocks     Used Available Capacity Mounted on\n"


def df_row(used: int, avail: int, mount: str = "/", dev: str = "/dev/vda1") -> str:
    pct = -(-used * 100 // (used + avail)) if used + avail else 0
    return DF_HEAD + f"{dev} {used + avail} {used} {avail} {pct}% {mount}\n"


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


class Host(RigHost):
    STUBBED = (*RigHost.STUBBED, "df")

    def lib(self, body: str, rc: int = 0):
        """Source the library under the fixture root, run BODY, and read the
        JSON it prints."""
        script = (
            f'. "{LIB}"; probe_init "{self.root}"; trap \'rm -rf "$P_TMP"\' EXIT; '
            + body
        )
        return self.execute(["bash", "-c", script], rc)

    def disk(self, path: str, used: int, avail: int, mount: str = "/") -> "Host":
        rel = path.lstrip("/")
        (self.root / rel).mkdir(parents=True, exist_ok=True)
        self.on("df", f"-Pk -- {self.root}/{rel}", df_row(used, avail, mount))
        return self

    def sized(self) -> "Host":
        self.on("apt-get", SIM_ARGS + "*", SIM)
        self.on("apt-cache", "show *", SHOW)
        self.on("dpkg-query", "-W -f *", DPKG)
        return self


@pytest.fixture
def host(tmp_path) -> Host:
    return Host(tmp_path)


STEP = (
    "if step_space tzdata age bison; then rc=0; else rc=$?; fi; "
    'w=""; jadds w why "$SS_WHY"; '
    'printf \'{"rc": %s, "download": %s, "growth": %s, "peak": %s, "n": %s, %s}\n\' '
    '"$rc" "$SS_DOWNLOAD" "$SS_GROWTH" "$SS_PEAK" "$SS_N" "$w"'
)


# --- the step's sizes ---------------------------------------------------------


def test_a_steps_sizes_are_apts_own_from_its_metadata(host):
    out = host.sized().lib(STEP)
    assert out == {
        "rc": 0,
        "download": DOWNLOAD,
        "growth": GROWTH,
        "peak": PEAK,
        "n": 3,
        "why": "",
    }
    # apt resolves the step's own packages, and never installs anything:
    # a simulation, then reads of its metadata and dpkg's.
    [sim] = [a for _, a, _ in host.calls("apt-get")]
    assert sim == SIM_ARGS + "tzdata age bison"
    [show] = [a for _, a, _ in host.calls("apt-cache")]
    assert show == (
        "show tzdata=2026e-0ubuntu0.24.04.1 age=1.1.1-1ubuntu0.24.04.3 "
        "bison=2:3.8.2+dfsg-1ubuntu0.24.04.1"
    )
    [q] = [a for _, a, _ in host.calls("dpkg-query")]
    assert q.endswith(" tzdata:all age:amd64 bison:amd64")


def test_an_archive_already_in_apts_cache_at_its_size_isnt_downloaded(host):
    # apt names it with its epoch's colon as %3a, as it printed "Need to
    # get 749 kB/2379 kB" with age's cached on noble.
    host.write(
        "var/cache/apt/archives/age_1.1.1-1ubuntu0.24.04.3_amd64.deb", b"x" * 1629868
    )
    host.write(
        "var/cache/apt/archives/bison_2%3a3.8.2+dfsg-1ubuntu0.24.04.1_amd64.deb",
        b"x" * 10,
    )
    out = host.sized().lib(STEP)
    # bison's cached file is the wrong size, so it's fetched again.
    assert out["download"] == (748794 + 282136 + 1023) // 1024
    assert out["growth"] == GROWTH


def test_a_new_package_grows_by_all_of_it_and_isnt_the_peak(host):
    new = "Inst libnew1 (2.0-1 Ubuntu:24.04/noble-security [amd64])\n"
    stanza = (
        "Package: libnew1\nInstalled-Size: 9000\nArchitecture: amd64\n"
        "Version: 2.0-1\nSize: 2048\n\n"
    )
    host.on("apt-get", SIM_ARGS + "*", SIM + new)
    host.on("apt-cache", "show *", SHOW + stanza)
    # dpkg-query exits 1 for the package it doesn't have, and prints the rest.
    host.on(
        "dpkg-query",
        "-W -f *",
        DPKG,
        rc=1,
        stderr="dpkg-query: no packages found matching libnew1:amd64\n",
    )
    out = host.lib(STEP)
    assert out["rc"] == 0, out
    assert out["growth"] == GROWTH + 9000
    assert out["download"] == (2660798 + 2048 + 1023) // 1024
    assert out["peak"] == PEAK


@pytest.mark.parametrize(
    "setup, why",
    [
        (
            lambda h: h.on(
                "apt-get", "*", "", rc=100, stderr="E: Unable to locate package age\n"
            ),
            "apt-get -s install --only-upgrade exited 100",
        ),
        (
            lambda h: h.on("apt-get", SIM_ARGS + "*", SIM).on(
                "apt-cache", "*", "", rc=100
            ),
            "apt-cache show exited 100",
        ),
        (
            lambda h: (
                h.on("apt-get", SIM_ARGS + "*", SIM)
                .on("apt-cache", "show *", SHOW.split("\n\nPackage: bison")[0] + "\n\n")
                .on("dpkg-query", "-W -f *", DPKG)
            ),
            "no record of bison:amd64=",
        ),
        (
            lambda h: (
                h.on("apt-get", SIM_ARGS + "*", SIM)
                .on("apt-cache", "show *", SHOW.replace("Size: 748794\n", ""))
                .on("dpkg-query", "-W -f *", DPKG)
            ),
            "no Size or Installed-Size",
        ),
        (
            lambda h: (
                h.on("apt-get", SIM_ARGS + "*", SIM)
                .on("apt-cache", "show *", SHOW)
                .on("dpkg-query", "*", "", rc=2)
            ),
            "dpkg-query -W exited 2",
        ),
    ],
)
def test_sizes_that_cant_be_read_are_unknown_never_zero(host, setup, why):
    setup(host)
    out = host.lib(STEP)
    assert out["rc"] == 1
    assert why in out["why"]


# --- the disk GC's config -----------------------------------------------------

CONF_READ = (
    'disk_gc_conf; o=""; jadds o state "$GC_STATE"; jadds o alert "$GC_ALERT"; '
    'jadds o mount "$GC_MOUNT"; jadds o why "$GC_WHY"; printf \'{%s}\\n\' "$o"'
)

# The GC's template's shape: a multi-line value in another section, and
# both comment prefixes.
VALID = """# the canonical disk GC
[gc]
homes =
    /home/exedev
    /home/agent
tiers = uv npx
; the sensor
[sensor]
alert_at_percent = 80
clear_at_percent = 75
mount = /data
monitor_id =
"""


def test_without_the_gcs_config_there_is_no_headroom_line(host):
    assert host.lib(CONF_READ) == {
        "state": "absent",
        "alert": "",
        "mount": "",
        "why": "",
    }


@pytest.mark.parametrize(
    "text, alert, mount",
    [
        (VALID, "80", "/data"),
        # The GC's own VERSION 2 defaults, for keys it leaves out.
        ("[gc]\ntiers = uv\n[sensor]\nmonitor_id =\n", "85", "/"),
        ("[gc]\n", "85", "/"),
        # configparser folds keys' case, takes : as well as =, and lets a
        # [DEFAULT] key stand in for one a section leaves out.
        ("[sensor]\nAlert_At_Percent: 90\n", "90", "/"),
        ("[DEFAULT]\nalert_at_percent = 70\n[sensor]\n", "70", "/"),
        (
            "[DEFAULT]\nalert_at_percent = 70\n[sensor]\nalert_at_percent = 75\n",
            "75",
            "/",
        ),
        ("[sensor]\r\nalert_at_percent = 88\r\n", "88", "/"),
        ("[sensor]\nalert_at_percent = 085\n", "85", "/"),
    ],
)
def test_the_gcs_config_gives_its_headroom_line(host, text, alert, mount):
    host.write(CONF, text)
    assert host.lib(CONF_READ) == {
        "state": "ok",
        "alert": alert,
        "mount": mount,
        "why": "",
    }


@pytest.mark.parametrize(
    "text, why",
    [
        (
            "alert_at_percent = 80\n[sensor]\n",
            "line 1 comes before any [section] header",
        ),
        ("[sensor]\n[gc]\n[sensor]\n", "line 3 repeats the section [sensor]"),
        (
            "[sensor]\nalert_at_percent = 80\nALERT_AT_PERCENT = 80\n",
            "line 3 repeats alert_at_percent in [sensor]",
        ),
        ("[sensor]\nalert_at_percent 80\n", "line 2 is no section header"),
        ("[sensor]\n= 80\n", "line 2 has no key"),
        ("[sensor\nalert_at_percent = 80\n", "line 1 is no section header"),
        ("[]\n", "line 1 is an empty section header"),
        # No inline comments: the GC reads the whole line as the value.
        (
            "[sensor]\nalert_at_percent = 80 # tighter\n",
            'alert_at_percent is "80 # tighter"',
        ),
        ("[sensor]\nalert_at_percent = 85.5\n", 'alert_at_percent is "85.5"'),
        ("[sensor]\nalert_at_percent = 101\n", 'alert_at_percent is "101"'),
        ("[sensor]\nalert_at_percent =\n", 'alert_at_percent is ""'),
        (
            "[sensor]\nalert_at_percent = 80\n  90\n",
            "line 3 continues [sensor] alert_at_percent",
        ),
        ("[sensor]\nmount = data\n", 'mount is "data", not an absolute path'),
        ("[sensor]\nmount = /data%(x)s\n", 'mount is "/data%(x)s"'),
        (
            "[DEFAULT]\nalert_at_percent = high\n[sensor]\n",
            'alert_at_percent is "high"',
        ),
    ],
)
def test_a_malformed_gc_config_is_never_read_as_absent(host, text, why):
    host.write(CONF, text)
    out = host.lib(CONF_READ)
    assert out["state"] == "bad"
    assert why in out["why"]


def test_a_gc_config_that_isnt_a_file_is_bad(host):
    (host.root / CONF).mkdir(parents=True)
    out = host.lib(CONF_READ)
    assert out == {
        "state": "bad",
        "alert": "",
        "mount": "",
        "why": "it isn't a regular file",
    }


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="chmod 000 does not restrict root, so the unreadable file is readable",
)
def test_an_unreadable_gc_config_is_bad(tmp_path):
    host = Host(tmp_path, sudo=False)
    host.write(CONF, VALID, mode=0o000)
    out = host.lib(CONF_READ)
    assert out["state"] == "bad"
    assert out["why"].startswith("it couldn't be read")


# --- the gate ---------------------------------------------------------------

GATE = (
    "SS_DOWNLOAD=$1 SS_GROWTH=$2 SS_PEAK=$3; space_gate 'the step'; "
    'w=""; for i in ${SPACE_WHY[@]+"${!SPACE_WHY[@]}"}; do '
    'jpushs w "${SPACE_KIND[$i]} ${SPACE_ID[$i]} ${SPACE_WHY[$i]}"; done; '
    'printf \'{"space": %s, "short": [%s]}\n\' "$SPACE_JSON" "$w"'
)


def gate(host: Host, download: int, growth: int, peak: int) -> dict:
    return host.lib(
        GATE.replace("$1", str(download))
        .replace("$2", str(growth))
        .replace("$3", str(peak))
    )


def test_a_step_that_fits_with_the_floor_kept_passes(host):
    # apt's cache and / on one filesystem: one need, every part summed.
    need = 300000 + 20000 + 50000 + FLOOR
    host.disk("var/cache/apt/archives", 9000000, need).disk("/", 9000000, need)
    out = gate(host, 300000, 20000, 50000)
    assert out["short"] == []
    assert out["space"]["filesystems"] == [
        {
            "mount": "/",
            "paths": ["/var/cache/apt/archives", "/"],
            "free_kib": need,
            "need_kib": need,
        }
    ]
    assert out["space"]["floor_kib"] == FLOOR
    assert out["space"]["headroom"] is None


def test_a_step_short_of_its_floor_on_a_shared_filesystem_is_refused(host):
    need = 300000 + 20000 + 50000 + FLOOR
    host.disk("var/cache/apt/archives", 9000000, need - 1).disk("/", 9000000, need - 1)
    [short] = gate(host, 300000, 20000, 50000)["short"]
    assert short.startswith(f"risk space:disk the step needs {need} KiB free on /")
    assert f"it has {need - 1}" in short


def test_apts_cache_and_root_on_their_own_filesystems_each_keep_the_floor(host):
    host.disk("var/cache/apt/archives", 100, 300000 + FLOOR - 1, mount="/var/cache")
    host.disk("/", 100, 20000 + 50000 + FLOOR - 1)
    short = gate(host, 300000, 20000, 50000)["short"]
    assert [s.split(" ")[1] for s in short] == ["space:apt-cache", "space:root"]
    assert "on /var/cache, which holds apt's cache" in short[0]


def test_an_install_that_frees_space_still_keeps_the_peak_and_floor(host):
    host.disk("var/cache/apt/archives", 9000000, 50000 + FLOOR).disk(
        "/", 9000000, 50000 + FLOOR
    )
    assert gate(host, 0, -400000, 50000)["short"] == []
    host.disk("var/cache/apt/archives", 9000000, 50000 + FLOOR - 1).disk(
        "/", 9000000, 50000 + FLOOR - 1
    )
    host.cases["df"] = host.cases["df"][2:]
    assert len(gate(host, 0, -400000, 50000)["short"]) == 1


def test_free_space_df_cant_read_is_unknown_never_a_pass(host):
    host.disk("/", 100, 10**9)
    [short] = gate(host, 1, 1, 1)["short"]
    assert short.startswith(
        "unknown space:apt-cache the free space under /var/cache/apt/archives couldn't be read"
    )


HEADROOM = "[sensor]\nalert_at_percent = 85\n"


def test_a_step_that_would_cross_the_gcs_alert_line_is_refused(host):
    host.write(CONF, HEADROOM)
    # 80% used today: 8000000 of 10000000. 500000 KiB more is 85%.
    host.disk("var/cache/apt/archives", 8000000, 2000000).disk("/", 8000000, 2000000)
    out = gate(host, 300000, 200000, 0)
    [short] = out["short"]
    assert short.startswith(
        "risk space:headroom the step would take / to 85% used, 500000 KiB more"
    )
    assert "alert_at_percent of 85" in short
    assert out["space"]["headroom"] == {
        "config": str(host.root / CONF),
        "mount": "/",
        "alert_at_percent": 85,
        "used_kib": 8000000,
        "free_kib": 2000000,
        "add_kib": 500000,
        "projected_percent": 85,
    }


def test_a_step_that_stays_under_the_gcs_alert_line_passes(host):
    host.write(CONF, HEADROOM)
    host.disk("var/cache/apt/archives", 8000000, 2000000).disk("/", 8000000, 2000000)
    out = gate(host, 300000, 199999, 0)
    assert out["short"] == []
    assert out["space"]["headroom"]["projected_percent"] == 85


def test_the_line_reads_the_sensors_own_mount(host):
    # The sensor watches /data; the step writes / alone, so it adds nothing
    # there, even with /data past its line.
    host.write(CONF, "[sensor]\nalert_at_percent = 85\nmount = /data\n")
    host.disk("var/cache/apt/archives", 100, 10**8).disk("/", 100, 10**8)
    host.disk("data", 9500000, 500000, mount="/data")
    out = gate(host, 300000, 200000, 0)
    assert out["short"] == []
    assert out["space"]["headroom"]["add_kib"] == 0


def test_a_step_that_adds_nothing_passes_a_host_already_past_its_line(host):
    host.write(CONF, HEADROOM)
    host.disk("var/cache/apt/archives", 9000000, 1000000).disk("/", 9000000, 1000000)
    assert gate(host, 0, -10, 0)["short"] == []
    assert len(gate(host, 0, 10, 0)["short"]) == 1


def test_a_malformed_gc_config_is_unknown_for_the_step(host):
    host.write(CONF, "[sensor]\nalert_at_percent = high\n")
    host.disk("var/cache/apt/archives", 100, 10**8).disk("/", 100, 10**8)
    out = gate(host, 1, 1, 1)
    [short] = out["short"]
    assert short.startswith(
        f"unknown space:disk-gc-conf {host.root / CONF}: [sensor] alert_at_percent"
    )
    assert out["space"]["headroom"]["config"] == str(host.root / CONF)
    assert "alert_at_percent" in out["space"]["headroom"]["error"]


def test_the_sensors_mount_df_cant_read_is_unknown(host):
    host.write(CONF, "[sensor]\nmount = /data\n")
    host.disk("var/cache/apt/archives", 100, 10**8).disk("/", 100, 10**8)
    [short] = gate(host, 1, 1, 1)["short"]
    assert short.startswith(
        "unknown space:headroom the free space under /data, the disk GC's [sensor] mount"
    )
