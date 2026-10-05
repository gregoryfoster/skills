"""patching-hosts: a followed origin is scoped to the packages it was added
for (#313, plan step 6e; #344).

A followed origin named by its site selects every upgradable package that
site serves, and at apt's default priority, 500, which ties Ubuntu's, a
third-party package under an Ubuntu name and a higher version wins. So the
probe reads, from `apt-cache policy`:

- each followed origin's priority, the one its release lines show: a
  `Package: *` pin for its site moves it, and at 500 or more it's a
  deviation, `unscoped:<origin>`;
- each installed package whose candidate comes from a followed origin and
  that no package pin names, `unpinned:<package>`: a catch-all pin doesn't
  stop its upgrades until it's under 100.

What this file pins, against the plan's step 6e list:

- both findings, and neither under the processor's pins (`Package: *` at 100,
  `nodejs` at 600, `nsolid` at 100);
- a catch-all alone leaves the installed package unpinned;
- an origin named by its o= field is read through its sites;
- an Ubuntu candidate, and an origin the knob holds, are left alone;
- an exception covers each; an origin apt doesn't list is checked against
  nothing; an unreadable package list is null and not_read, never [].

Measured on noble with apt 2.8.3 against NodeSource's node_22.x repository
(2026-10-05): the release line read 500, then 100 and 499 under a
`Package: *` pin, and a package pin was listed under "Pinned packages:" for
each version it matched; a catch-all never was, nor a pin on a package
nothing serves. With Ubuntu's nodejs installed, unpinned NodeSource
replaced it with its own; at 100 or 499 Ubuntu's stayed. With NodeSource's
nodejs installed and no package pin, a catch-all at 100 still upgraded it,
and at 99 kept it. A package pin sets the installed version's priority too:
at 99 it didn't keep it, a pin on its installed version did. A version
line has 5 columns before it, and a source line right-aligns its priority
after 7 or more.
"""

import pytest

from tests.structural.patching_hosts_rig import dispatcher
from tests.structural.test_patching_hosts_probe import Host

KNOB = "class production\nposture scheduled\norigin deb.nodesource.com follow\n"
SITE = "deb.nodesource.com"
DPKG_ALL = "*-W -f ${Package} ${db:Status-Abbrev}\\n"


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


def _policy(priority: int = 500, pins: str = "") -> str:
    """`apt-cache policy` with no argument, as noble's apt 2.8.3 prints it."""
    return (
        "Package files:\n"
        " 100 /var/lib/dpkg/status\n"
        "     release a=now\n"
        f" {priority} https://deb.nodesource.com/node_22.x nodistro/main arm64 Packages\n"
        "     release o=. nodistro,a=nodistro,n=nodistro,l=. nodistro,c=main,b=arm64\n"
        "     origin deb.nodesource.com\n"
        " 500 http://ports.ubuntu.com/ubuntu-ports noble/universe arm64 Packages\n"
        "     release v=24.04,o=Ubuntu,a=noble,n=noble,l=Ubuntu,c=universe,b=arm64\n"
        "     origin ports.ubuntu.com\n"
        "Pinned packages:\n" + pins
    )


PROCESSOR_PINS = (
    "     nodejs -> 22.23.3-1nodesource1 with priority 600\n"
    "     nodejs -> 22.23.2-1nodesource1 with priority 600\n"
    "     nsolid -> 22.23.3-ns6.3.8 with priority 100\n"
)


def _nodejs(cand: str = "22.23.3-1nodesource1", prio: int = 500) -> str:
    """`apt-cache policy nodejs`, NodeSource's 22.23.2 installed."""
    return (
        "nodejs:\n"
        "  Installed: 22.23.2-1nodesource1\n"
        f"  Candidate: {cand}\n"
        "  Version table:\n"
        f"     22.23.3-1nodesource1 {prio}\n"
        f"        {prio} https://deb.nodesource.com/node_22.x nodistro/main arm64 Packages\n"
        f" *** 22.23.2-1nodesource1 {prio}\n"
        f"        {prio} https://deb.nodesource.com/node_22.x nodistro/main arm64 Packages\n"
        "        100 /var/lib/dpkg/status\n"
        "     18.19.1+dfsg-6ubuntu5 500\n"
        "        500 http://ports.ubuntu.com/ubuntu-ports noble/universe arm64 Packages\n"
    )


LIBC6 = (
    "libc6:\n"
    "  Installed: 2.39-0ubuntu8.4\n"
    "  Candidate: 2.39-0ubuntu8.4\n"
    "  Version table:\n"
    " *** 2.39-0ubuntu8.4 500\n"
    "        500 http://ports.ubuntu.com/ubuntu-ports noble-security/main arm64 Packages\n"
    "        100 /var/lib/dpkg/status\n"
)


def _host(tmp_path, knob: str = KNOB, policy: str | None = None, nodejs: str = ""):
    host = Host(tmp_path).knob(knob)
    host.on("apt-cache", "*policy", _policy() if policy is None else policy)
    # nsolid's configuration is all that's left of it: not installed.
    host.on("dpkg-query", DPKG_ALL, "libc6 ii \nnodejs ii \nnsolid rc \n")
    host.on("apt-cache", "*policy libc6 nodejs", LIBC6 + (nodejs or _nodejs()))
    return host


def _ids(out: dict, key: str = "findings") -> list[str]:
    return [f["id"] for f in out[key]]


def _scope(out: dict) -> list[dict]:
    return out["updates"]["origin_scope"]


def test_an_unpinned_followed_origin_and_its_package_are_findings(tmp_path):
    out = _host(tmp_path).run()
    assert _scope(out) == [
        {"origin": SITE, "sites": [SITE], "priority": 500, "unpinned": ["nodejs"]}
    ]
    f = {x["id"]: x for x in out["findings"]}
    assert f[f"unscoped:{SITE}"]["kind"] == "deviation"
    assert f[f"unscoped:{SITE}"]["exception_what"] == f"unscoped:{SITE}"
    assert "at apt priority 500" in f[f"unscoped:{SITE}"]["message"]
    assert f["unpinned:nodejs"]["exception_what"] == "unpinned:nodejs"
    assert "only below 100" in f["unpinned:nodejs"]["message"]
    assert "pin its installed version" in f["unpinned:nodejs"]["message"]
    assert "unpinned:libc6" not in f


def test_the_processors_pins_scope_it(tmp_path):
    out = _host(
        tmp_path,
        policy=_policy(100, PROCESSOR_PINS),
        nodejs=_nodejs(prio=600),
    ).run()
    assert _scope(out) == [
        {"origin": SITE, "sites": [SITE], "priority": 100, "unpinned": []}
    ]
    assert not [i for i in _ids(out) if i.startswith(("unscoped:", "unpinned:"))]


def test_a_catch_all_alone_leaves_the_installed_package_unpinned(tmp_path):
    # Measured: at 100, NodeSource's installed nodejs was still upgraded.
    out = _host(tmp_path, policy=_policy(100), nodejs=_nodejs(prio=100)).run()
    ids = _ids(out)
    assert "unpinned:nodejs" in ids
    assert f"unscoped:{SITE}" not in ids


def test_a_catch_all_at_499_is_below_ubuntus(tmp_path):
    out = _host(tmp_path, policy=_policy(499, PROCESSOR_PINS)).run()
    assert _scope(out)[0]["priority"] == 499
    assert f"unscoped:{SITE}" not in _ids(out)


def test_an_origin_is_as_high_as_its_highest_release(tmp_path):
    # A pin on one of its releases leaves the other at 500.
    policy = _policy(500).replace(
        "     origin deb.nodesource.com\n",
        "     origin deb.nodesource.com\n"
        " 100 https://deb.nodesource.com/nsolid_22.x nodistro/main arm64 Packages\n"
        "     release o=. nodistro,a=nodistro,n=nodistro,l=. nodistro,c=main,b=arm64\n"
        "     origin deb.nodesource.com\n",
    )
    out = _host(tmp_path, policy=policy).run()
    assert _scope(out)[0]["priority"] == 500
    assert f"unscoped:{SITE}" in _ids(out)


def test_a_four_digit_priority_is_still_read(tmp_path):
    # apt right-aligns a priority: 1001 starts its source line one column in
    # from 100, and its release line at the margin.
    policy = _policy().replace(" 500 https://deb", "1001 https://deb")
    nodejs = _nodejs().replace("        500 https://deb", "       1001 https://deb")
    out = _host(tmp_path, policy=policy, nodejs=nodejs).run()
    assert _scope(out)[0]["priority"] == 1001
    assert {f"unscoped:{SITE}", "unpinned:nodejs"} <= set(_ids(out))


def test_an_ubuntu_candidate_is_left_alone(tmp_path):
    # Ubuntu's nodejs installed under the catch-all: its candidate stays
    # Ubuntu's, measured at 100 and 499.
    ubuntu = (
        "nodejs:\n"
        "  Installed: 18.19.1+dfsg-6ubuntu5\n"
        "  Candidate: 18.19.1+dfsg-6ubuntu5\n"
        "  Version table:\n"
        "     22.23.3-1nodesource1 100\n"
        "        100 https://deb.nodesource.com/node_22.x nodistro/main arm64 Packages\n"
        " *** 18.19.1+dfsg-6ubuntu5 500\n"
        "        500 http://ports.ubuntu.com/ubuntu-ports noble/universe arm64 Packages\n"
        "        100 /var/lib/dpkg/status\n"
    )
    out = _host(tmp_path, policy=_policy(100), nodejs=ubuntu).run()
    assert _scope(out)[0]["unpinned"] == []
    assert "unpinned:nodejs" not in _ids(out)


def test_an_origin_named_by_its_o_field_is_read_through_its_sites(tmp_path):
    host = Host(tmp_path).knob(
        "class production\nposture scheduled\norigin Tailscale follow\n"
    )
    host.on(
        "apt-cache",
        "*policy",
        " 500 https://pkgs.tailscale.com/stable/ubuntu noble/main arm64 Packages\n"
        "     release o=Tailscale,n=noble,l=Tailscale,c=main,b=arm64\n"
        "     origin pkgs.tailscale.com\n"
        "Pinned packages:\n",
    )
    host.on("dpkg-query", DPKG_ALL, "tailscale ii \n")
    host.on(
        "apt-cache",
        "*policy tailscale",
        "tailscale:\n"
        "  Installed: 1.102.2\n"
        "  Candidate: 1.102.4\n"
        "  Version table:\n"
        "     1.102.4 500\n"
        "        500 https://pkgs.tailscale.com/stable/ubuntu noble/main arm64 Packages\n"
        " *** 1.102.2 500\n"
        "        500 https://pkgs.tailscale.com/stable/ubuntu noble/main arm64 Packages\n"
        "        100 /var/lib/dpkg/status\n",
    )
    out = host.run()
    assert _scope(out) == [
        {
            "origin": "Tailscale",
            "sites": ["pkgs.tailscale.com"],
            "priority": 500,
            "unpinned": ["tailscale"],
        }
    ]
    assert {"unscoped:Tailscale", "unpinned:tailscale"} <= set(_ids(out))


def test_an_origin_the_knob_holds_is_not_checked(tmp_path):
    host = _host(
        tmp_path,
        knob="class production\nposture scheduled\n"
        "origin deb.nodesource.com hold the app pins its node\n",
    )
    out = host.run()
    assert _scope(out) == []
    assert not [i for i in _ids(out) if i.startswith(("unscoped:", "unpinned:"))]
    assert not [a for _, a, _ in host.calls("dpkg-query") if a.endswith("\\n")]


def test_an_exception_covers_each(tmp_path):
    out = _host(
        tmp_path,
        knob=KNOB + f"exception unscoped:{SITE} 2026-12-31 serves only nodejs\n"
        "exception unpinned:nodejs 2026-12-31 the app ships its own pin\n",
    ).run()
    assert {f"unscoped:{SITE}", "unpinned:nodejs"} <= set(_ids(out, "excepted"))
    assert not [i for i in _ids(out) if i.startswith(("unscoped:", "unpinned:"))]


def test_an_origin_apt_doesnt_list_is_checked_against_nothing(tmp_path):
    host = _host(tmp_path, policy=_policy().split(" 500 https://deb")[0])
    out = host.run()
    assert _scope(out) == [
        {"origin": SITE, "sites": [], "priority": None, "unpinned": []}
    ]
    assert not [i for i in _ids(out) if i.startswith(("unscoped:", "unpinned:"))]
    assert not [a for _, a, _ in host.calls("dpkg-query") if a.endswith("\\n")]


@pytest.mark.parametrize("fails", ["dpkg-query", "apt-cache"])
def test_an_unreadable_package_list_is_null_not_empty(tmp_path, fails):
    host = _host(tmp_path)
    if fails == "dpkg-query":
        host.cases["dpkg-query"] = []
    else:
        host.cases["apt-cache"] = [
            c for c in host.cases["apt-cache"] if c[0] == "*policy"
        ]
    out = host.run()
    assert _scope(out)[0]["unpinned"] is None
    assert f"unscoped:{SITE}" in _ids(out)
    assert any(
        "which installed packages a followed origin serves" in n
        for n in out["not_read"]
    )
