"""patching-hosts: a host's standing approval (#673 item 4).

The knob's `standing <lane> [no-reboot] [no-datastore] [no-held] <review-by>
<reason>` is the owner's declaration that a step of one lane needs no
approval in the host's own session, or a plan, within its limits. `--standing`
beside `--approve` holds each step to it:

- apply.sh: an unexpired line for the step's lane, the bulk's `--lane`, or
  for a held step the lane its bulk ran in, read from the run; and the
  bulk's fresh reading inside its limits: no-reboot (an unknown or due
  reboot refuses), no-held, no-datastore (a held step that may restart a
  declared data store), and the lane's own classes. gate.standing reports
  it in gate.plan's shape, and without --approve it's the read-only check;
- recovery-point.sh: any unexpired line;
- reboot-chain.sh: its run's lane's line, refused under no-reboot;
- each records approval {by: standing, lane, review_by, reason, line}.
"""

import pytest

from tests.structural.patching_hosts_rig import dispatcher
from tests.structural.test_patching_hosts_apply import (
    KNOB,
    MAPS,
    QUIET,
    _changed,
    _owners,
    _step4,
)
from tests.structural.test_patching_hosts_apply import Host as ApplyHost
from tests.structural.test_patching_hosts_apply import _ready as _apply_ready
from tests.structural.test_patching_hosts_plan import SELECTED, _summary
from tests.structural.test_patching_hosts_reboot import Host as RebootHost
from tests.structural.test_patching_hosts_reboot import _ready as _reboot_ready
from tests.structural.test_patching_hosts_recovery import Host as RecoveryHost
from tests.structural.test_patching_hosts_recovery import _postgres
from tests.structural.test_patching_hosts_recovery import _ready as _recovery_ready


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


STANDING = "standing security {limits}2099-01-01 weekly security patches\n"
# A selection no held group reaches, and that no step-4 process maps: the
# run reads "no reboot".
QUIET_SEL = {
    "libxml2": ("2.9.14+dfsg-1.3ubuntu3.5", "security"),
    "tzdata": ("2025b-0ubuntu0.24.04.1", "security"),
}


@pytest.fixture
def host(tmp_path) -> ApplyHost:
    h = _apply_ready(ApplyHost(tmp_path))
    _summary(h)
    return h


def _standing(host, limits: str = "", extra: str = "") -> None:
    host.knob(KNOB + extra + STANDING.format(limits=limits))


def _quiet(host) -> None:
    """The selection reaches no held group, and the run reads no reboot."""
    (host.dry / "dry-run.log").write_text(
        "Packages that will be upgraded: libxml2 tzdata\n"
    )
    _summary(host, QUIET_SEL)
    host.pid1_maps.write_text(MAPS)
    _step4(_owners(host), {**QUIET})


def _kinds(out: dict) -> list[tuple[str, str, bool]]:
    return [
        (d["kind"], d["what"], d["inside"])
        for d in out["gate"]["standing"]["differences"]
    ]


def _outside(out: dict) -> list[str]:
    return [r for r in out["refused"] if r.startswith("outside the standing")]


# --- the record --------------------------------------------------------------------


def test_a_standing_line_for_the_lane_runs_the_bulk_and_is_recorded(host):
    _standing(host)
    out = host.run("--standing")
    assert out["apply"]["approval"] == {
        "by": "standing",
        "lane": "security",
        "review_by": "2099-01-01",
        "reason": "weekly security patches",
        "line": 6,
    }
    g = out["gate"]["standing"]
    assert (g["lane"], g["covers"], g["inside"], g["differences"]) == (
        "security",
        True,
        True,
        [],
    )
    assert out["gate"]["plan"] is None


def test_plan_and_standing_are_exclusive(host):
    _standing(host)
    r = host.execute(
        [
            "bash",
            str(host.scripts / "apply.sh"),
            "--step",
            "bulk",
            "--standing",
            "--plan",
            "/nonexistent",
        ],
        rc=2,
    )
    assert "two forms of the owner's approval" in r.stderr


# --- each limit --------------------------------------------------------------------


@pytest.mark.parametrize(
    "limits, extra, quiet, kinds",
    [
        # no-reboot: PID 1's map can't be read, so the reboot is unknown.
        ("no-reboot ", "", False, [("reboot", "host", False)]),
        ("no-reboot ", "", True, []),
        # no-held: the selection reaches the postgres group.
        ("no-held ", "", False, [("held-step", "postgres", False)]),
        ("no-held ", "", True, []),
        # no-datastore: the postgres group restarts the declared cluster...
        (
            "no-datastore ",
            "datastore postgres postgresql@16-main app\n",
            False,
            [("datastore", "postgres", False)],
        ),
        # ...but with no data store declared, it restarts none.
        ("no-datastore ", "", False, []),
    ],
    ids=[
        "no-reboot-unknown",
        "no-reboot-clean",
        "no-held",
        "no-held-clean",
        "no-datastore",
        "no-datastore-none-declared",
    ],
)
def test_each_limit_refuses_what_it_names(host, limits, extra, quiet, kinds):
    _standing(host, limits, extra)
    if quiet:
        _quiet(host)
    out = host.run("--standing", rc=3 if (kinds or extra) else 0)
    assert _kinds(out) == kinds
    assert len(_outside(out)) == len(kinds)
    if kinds:
        assert _changed(host) == []


def test_the_security_lanes_line_takes_only_security(host):
    # The host's origins are wider than security (security_only=0), and the
    # selection holds an -updates package.
    _standing(host)
    _summary(host, {**SELECTED, "libxml2": ("2.9.14+dfsg-1.3ubuntu3.6", "updates")}, 0)
    out = host.run("--standing", rc=3)
    assert _kinds(out) == [("lane-scope", "libxml2", False)]


def test_an_unread_class_refuses(host):
    _standing(host)
    _summary(host, None)
    out = host.run("--standing", rc=3)
    assert _kinds(out) == [("unread", "selection", False)]


# --- what doesn't approve ----------------------------------------------------------


@pytest.mark.parametrize(
    "knob_line, args, why",
    [
        (
            "standing security 2026-01-01 lapsed\n",
            (),
            "passed its review-by date, 2026-01-01",
        ),
        (
            "standing maintenance 2099-01-01 the monthly run\n",
            (),
            "no standing line for the security lane",
        ),
        (
            "standing origin:Example 2099-01-01 a bulletin\n",
            ("--lane", "origin:Example"),
            "names an origin the knob doesn't follow",
        ),
    ],
    ids=["expired", "another-lane", "origin-not-followed"],
)
def test_a_line_that_doesnt_approve_refuses(host, knob_line, args, why):
    host.knob(KNOB + knob_line)
    out = host.run("--standing", *args, rc=3)
    assert any(why in r for r in out["refused"]), out["refused"]
    assert out["gate"]["standing"]["covers"] is False
    assert _changed(host) == []


def test_without_approve_the_limits_are_reported_and_nothing_else_refused(host):
    _standing(host, "no-held ")
    out = host.run("--standing", approve=False, rc=3)
    assert [r for r in out["refused"] if not r.startswith("no --approve")] == []
    assert out["gate"]["standing"]["inside"] is False
    assert _kinds(out) == [("held-step", "postgres", False)]


# --- a held step -------------------------------------------------------------------


def test_a_held_step_whose_lane_cant_be_read_isnt_approved(host):
    _standing(host)
    out = host.run("--standing", step="postgres", rc=3)
    assert any("can't be read" in r for r in out["refused"]), out["refused"]


def test_a_held_step_under_no_held_is_refused(host):
    _standing(host, "no-held ")
    host.run_dir.mkdir()
    host.run_dir.chmod(0o700)
    (host.run_dir / "dry-run").write_text("lane=security\n")
    out = host.run("--standing", step="postgres", rc=3)
    assert _kinds(out) == [("held-step", "postgres", False)]


# --- recovery-point.sh and reboot-chain.sh -----------------------------------------


@pytest.fixture
def recovery(tmp_path) -> RecoveryHost:
    return _postgres(_recovery_ready(RecoveryHost(tmp_path)))


def test_the_recovery_point_takes_any_unexpired_line(recovery):
    recovery.knob(recovery.knob_path.read_text() + STANDING.format(limits="no-held "))
    out = recovery.recover("--standing")
    a = out["recovery_point"]["approval"]
    assert (a["by"], a["lane"]) == ("standing", "security")
    assert out["gate"]["standing"]["covers"] is True


def test_the_recovery_point_refuses_without_a_line(recovery):
    out = recovery.recover("--standing", rc=3)
    assert any("the knob has no standing line" in r for r in out["refused"])


@pytest.fixture
def chain(tmp_path) -> RebootHost:
    h = _reboot_ready(RebootHost(tmp_path))
    (h.run_dir / "dry-run").write_text("lane=security\n")
    return h


def test_the_reboot_runs_under_its_runs_lanes_line(chain):
    chain.knob(chain.knob_path.read_text() + STANDING.format(limits="no-held "))
    out = chain.reboot("--standing")
    assert out["reboot_chain"]["approval"]["by"] == "standing"
    assert out["gate"]["standing"]["covers"] is True


def test_the_reboot_is_refused_under_no_reboot(chain):
    chain.knob(chain.knob_path.read_text() + STANDING.format(limits="no-reboot "))
    out = chain.reboot("--standing", rc=3)
    assert any("says no-reboot" in r for r in out["refused"])
    assert not any(n == "systemd-run" for n, _, _ in chain.calls())


def test_a_standing_lines_expiry_is_read_from_the_clock_not_today(host):
    # CR 2528: --today is the caller's, and a standing line is the owner's
    # declaration against the host's own clock. The clock reads 2026-09-29;
    # the line expired on the 28th, and --today says the 1st.
    host.knob(KNOB + "standing security 2026-09-28 lapsed\n")
    out = host.run("--standing", "--today", "2026-09-01", rc=3)
    assert any("passed its review-by date, 2026-09-28" in r for r in out["refused"]), (
        out["refused"]
    )
    assert _changed(host) == []


def test_the_recovery_point_reads_a_standing_lines_expiry_from_the_clock(recovery):
    recovery.knob(
        recovery.knob_path.read_text() + "standing security 2026-09-28 lapsed\n"
    )
    out = recovery.recover("--standing", "--today", "2026-09-01", rc=3)
    assert any("passed its review-by date" in r for r in out["refused"])


def test_the_bulks_next_held_step_carries_standing(host):
    _standing(host)
    out = host.run("--standing")
    [n] = [x for x in out["next"] if "--step postgres" in x]
    assert "--standing" in n


def test_the_recovery_points_next_bulk_carries_standing(recovery):
    recovery.knob(recovery.knob_path.read_text() + STANDING.format(limits=""))
    out = recovery.recover("--standing")
    [n] = [x for x in out["next"] if "--step bulk" in x]
    assert "--standing" in n


# --- CR 2548: a followed origin declared by its site ---------------------------------

DOCKER_POLICY = (
    "Package files:\n"
    " 500 https://download.docker.com/linux/ubuntu noble/stable amd64 Packages\n"
    "     release o=Docker,a=noble,n=noble,l=Docker CE,c=stable,b=amd64\n"
    "     origin download.docker.com\n"
)


@pytest.mark.parametrize("decl", ["Docker", "download.docker.com"])
def test_the_maintenance_lines_followed_origin_may_be_declared_by_its_site(host, decl):
    host.knob(
        KNOB + f"origin {decl} follow\n" + "standing maintenance 2099-01-01 monthly\n"
    )
    host.on("apt-cache", "policy", DOCKER_POLICY)
    _summary(host, {**SELECTED, "libxml2": ("9", "third-party:Docker")}, 0)
    out = host.run("--standing", "--lane", "maintenance", rc=3)
    assert [k for k in _kinds(out) if k[0] == "lane-scope"] == []


# --- CR 2549: the recovery point's lane ----------------------------------------------


def test_the_recovery_point_takes_its_lanes_line_and_carries_the_lane(recovery):
    recovery.knob(
        recovery.knob_path.read_text()
        + "standing security 2026-01-01 lapsed\n"
        + "standing maintenance 2099-01-01 monthly\n"
    )
    refused = recovery.recover("--standing", rc=3)
    assert any("passed its review-by date" in r for r in refused["refused"])
    out = recovery.recover("--standing", "--lane", "maintenance")
    assert out["recovery_point"]["approval"]["lane"] == "maintenance"
    [n] = [x for x in out["next"] if "--step bulk" in x]
    assert "--standing --lane maintenance" in n
