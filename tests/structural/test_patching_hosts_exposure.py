"""patching-hosts' probe: a third-party origin carrying a serving runtime (#464, ask 1).

A host's network-facing runtime came from a PHP PPA. Its posture looked
healthy (unattended-upgrades on, a low Ubuntu security count), and the
runtime sat 8 patch releases behind for months, because `follow` puts an
origin in the maintenance lane at the host's cadence. Decided by the
operator 2026-11-07: when a pending package from a non-Ubuntu origin is
mapped by a running service, the probe reports that origin's pending set as
a security exposure, and names the expedite path the skill already has: a
dated `window` (#421), then `apply.sh --lane origin:<origin>` with the
owner's approval. No knob keyword.

What this file pins:

- a PPA origin with a pending php-fpm whose shared object a running
  service's process maps is `exposure:<origin>`, kind risk, naming the
  service, the package and the expedite path;
- the same pending set with no service mapping it is plain third-party
  maintenance;
- an Ubuntu package mapped is never this finding, and neither is a
  session's process mapping the PPA's;
- an origin the knob pins or holds, or names nowhere, says so instead of
  the expedite path;
- the finding is keyed as the knob names the origin, by its site too;
- an exception covers it.

The map is the probe's one: `impact.maps`, `/proc/*/maps` against each
pending package's shared objects, by systemd unit. Whether a process
listens isn't in it (`ss -Hltn` carries no pid), so a process in a
`.service` unit, a daemon or a worker, stands in for "listening or worker".
"""

import pytest

from tests.structural.patching_hosts_rig import dispatcher
from tests.structural.test_patching_hosts_probe import Host, _finding, _ids


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


PPA = "LP-PPA-ondrej-php"
SITE = "ppa.launchpadcontent.net"
SURY = "+ubuntu24.04.1+deb.sury.org+1"
SIMULATION = (
    "NOTE: This is only a simulation!\n"
    f"Inst php8.3-fpm [8.3.10-1{SURY}] (8.3.11-1{SURY} {PPA}:24.04/noble [amd64])\n"
    f"Inst php8.3-opcache [8.3.10-1{SURY}] (8.3.11-1{SURY} {PPA}:24.04/noble [amd64])\n"
    "Inst libc6 [2.39-0ubuntu8.3] (2.39-0ubuntu8.4 Ubuntu:24.04/noble-security [amd64])\n"
)
POLICY = (
    f" 500 https://{SITE}/ondrej/php/ubuntu noble/main amd64 Packages\n"
    f"     release v=24.04,o={PPA},a=noble,n=noble,l=PHP,c=main,b=amd64\n"
    f"     origin {SITE}\n"
    " 500 http://archive.ubuntu.com/ubuntu noble-security/main amd64 Packages\n"
    "     release v=24.04,o=Ubuntu,a=noble-security,n=noble,l=Ubuntu,c=main,b=amd64\n"
    "     origin archive.ubuntu.com\n"
)
OPCACHE = "/usr/lib/php/20230831/opcache.so"
LIBC = "/usr/lib/x86_64-linux-gnu/libc.so.6"


def _php_host(
    tmp_path, knob: str, maps: list[str], cgroup: str, more: str = ""
) -> Host:
    """A host whose pending set holds the PPA's php8.3-fpm and opcache, and
    Ubuntu's libc6, and MORE simulation lines, with pid 700 mapping MAPS, in
    CGROUP's unit."""
    h = Host(tmp_path).knob(knob)
    h.on("apt-get", "-s *dist-upgrade", SIMULATION + more)
    h.on("apt-cache", "*policy", POLICY)
    h.on("dpkg-query", "*-L php8.3-fpm", "/usr/sbin\n/usr/sbin/php-fpm8.3\n")
    h.on("dpkg-query", "*-L php8.3-opcache", f"/usr/lib/php/20230831\n{OPCACHE}\n")
    h.on("dpkg-query", "*-L libc6", f"{LIBC}\n")
    h.write(
        "proc/700/maps",
        "".join(f"7f0{i}-7f1{i} r-xp 0 fd:01 {i} {p}\n" for i, p in enumerate(maps)),
    )
    h.write("proc/700/cgroup", f"0::/system.slice/{cgroup}\n")
    return h


FOLLOW = f"posture scheduled\norigin {PPA} follow\n"


def test_a_ppa_runtime_a_service_maps_is_a_security_exposure(tmp_path):
    h = _php_host(tmp_path, FOLLOW, [OPCACHE, LIBC], "php8.3-fpm.service")
    out = h.run()
    f = _finding(out, f"exposure:{PPA}")
    assert f["kind"] == "risk"
    assert f["exception_what"] == f"exposure:{PPA}"
    m = f["message"]
    for word in (
        "php8.3-fpm.service",
        "php8.3-opcache",
        "2 packages pending",
        "security exposure",
        "follows",
        "dated window",
        f"apply.sh --lane origin:{PPA}",
        "pre-announced security release",
    ):
        assert word in m, word
    # It's the origin's whole pending set: libc6 is Ubuntu's.
    assert "libc6" not in m


def test_the_same_set_with_no_service_mapping_it_is_maintenance(tmp_path):
    h = _php_host(tmp_path, FOLLOW, [LIBC], "php8.3-fpm.service")
    out = h.run()
    assert out["pending"]["by_class"]["third_party"] == {PPA: 2}
    assert not [i for i in _ids(out) if i.startswith("exposure:")]


def test_an_ubuntu_package_a_service_maps_is_not_an_exposure(tmp_path):
    h = _php_host(tmp_path, FOLLOW, [LIBC], "postgresql@16-main.service")
    out = h.run()
    units = {u["unit"]: u for u in out["impact"]["maps"]["units"]}
    assert units["postgresql@16-main.service"]["packages"] == ["libc6"]
    assert not [i for i in _ids(out) if i.startswith("exposure:")]


def test_a_sessions_process_mapping_the_ppa_is_no_serving_runtime(tmp_path):
    h = _php_host(
        tmp_path, FOLLOW, [OPCACHE], "../user.slice/user-1000.slice/session-3.scope"
    )
    out = h.run()
    assert not [i for i in _ids(out) if i.startswith("exposure:")]


@pytest.mark.parametrize(
    "line, says",
    [
        (f"origin {PPA} pin 8.3.10", "pins"),
        (f"origin {PPA} hold the app needs 8.3.10", "holds"),
        ("", f"origin:{PPA}"),
    ],
    ids=["pin", "hold", "no-line"],
)
def test_an_origin_no_lane_takes_says_so(tmp_path, line, says):
    h = _php_host(
        tmp_path, f"posture scheduled\n{line}\n", [OPCACHE], "php8.3-fpm.service"
    )
    out = h.run()
    m = _finding(out, f"exposure:{PPA}")["message"]
    assert says in m
    assert "--lane origin:" not in m


def test_the_finding_takes_the_knobs_key_a_site_included(tmp_path):
    h = _php_host(
        tmp_path,
        f"posture scheduled\norigin {SITE} follow\n",
        [OPCACHE],
        "php8.3-fpm.service",
    )
    out = h.run()
    f = _finding(out, f"exposure:{SITE}")
    assert f"--lane origin:{SITE}" in f["message"]


def test_an_exception_covers_the_exposure(tmp_path):
    h = _php_host(
        tmp_path,
        FOLLOW
        + f"exception exposure:{PPA} 2026-12-31 the pool serves localhost only\n",
        [OPCACHE],
        "php8.3-fpm.service",
    )
    out = h.run()
    assert f"exposure:{PPA}" not in _ids(out)
    assert f"exposure:{PPA}" in _ids(out, "excepted")


def test_canonicals_origin_is_first_party_here_too(tmp_path):
    # CR 1959: read_origins counts o=Canonical as first party, so no knob
    # line names it and no origin: finding asks for one; an exposure citing
    # that finding would point at nothing.
    h = _php_host(
        tmp_path,
        FOLLOW,
        [OPCACHE],
        "php8.3-fpm.service",
        more="Inst libpartner1 [1.0] (1.1 Canonical:24.04/noble [amd64])\n",
    )
    h.on("dpkg-query", "*-L libpartner1", "/usr/lib/libpartner.so.1\n")
    h.write("proc/701/maps", "7f00-7f01 r-xp 0 fd:01 1 /usr/lib/libpartner.so.1\n")
    h.write("proc/701/cgroup", "0::/system.slice/partner.service\n")
    out = h.run()
    assert "exposure:Canonical" not in _ids(out)
    assert "origin:Canonical" not in _ids(out)
    assert f"exposure:{PPA}" in _ids(out)
