"""patching-hosts: a fleet executor's approved plan (#673 item 1).

An executor runs the skill's own scripts on a host, under an approval the
owner gave off the host, once per cycle, for a plan. The skill can't see
that approval, only the plan file: it hashes the file itself, records what
the plan states, and holds each step to it.

- apply.sh, recovery-point.sh and reboot-chain.sh take --plan FILE beside
  --approve: the plan must parse, cover the host and the step, and not have
  passed its not-after;
- the bulk's fresh reading must sit inside the plan's envelope: a newer
  version of a planned package, or a new package in the security lane, is
  inside; an unplanned held step, a reboot the plan says no to, an unplanned
  package from another class, a new origin, a version that isn't newer, or
  anything unread, is outside;
- without --approve nothing is refused for the plan, and gate.plan says what
  it would decide: the executor's read-only check;
- each step records approval: by plan, with its id, the file's sha256 and
  what it states of its approval, or by session.
"""

import hashlib
import json
import subprocess

import pytest

from tests.structural.patching_hosts_rig import SKILL, dispatcher
from tests.structural.patching_hosts_rig import clean_env as _clean_env
from tests.structural.test_patching_hosts_apply import TUE_1530, _changed
from tests.structural.test_patching_hosts_apply import Host as ApplyHost
from tests.structural.test_patching_hosts_apply import _ready as _apply_ready
from tests.structural.test_patching_hosts_reboot import Host as RebootHost
from tests.structural.test_patching_hosts_reboot import _ready as _reboot_ready
from tests.structural.test_patching_hosts_recovery import Host as RecoveryHost
from tests.structural.test_patching_hosts_recovery import _postgres
from tests.structural.test_patching_hosts_recovery import _ready as _recovery_ready


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


# What the apply rig's dry run selects, with each candidate and class as the
# probe's simulation reads them.
SELECTED = {
    "libc6": ("2.39-0ubuntu8.6", "security"),
    "libxml2": ("2.9.14+dfsg-1.3ubuntu3.5", "security"),
    "libssl3t64": ("3.0.13-0ubuntu3.6", "security"),
    "postgresql-16": ("16.10-0ubuntu0.24.04.1", "security"),
    "libpq5": ("16.10-0ubuntu0.24.04.1", "security"),
}

HEAD = """# cycle 2026-09-29, drafted by the executor
plan cycle-2026-09-29
approved 2026-09-29T14:00:00Z owner, by passkey
not-after 2026-09-29T23:00:00Z
"""


def _section(
    host: str = "web-1",
    lane: str = "security",
    reboot: str = "yes",
    held: tuple[str, ...] = ("postgres",),
    packages: dict | None = None,
) -> str:
    pk = SELECTED if packages is None else packages
    lines = [f"[host {host}]", f"lane {lane}", f"reboot {reboot}"]
    lines += [f"held {h}" for h in held]
    lines += [f"package {n} {v} {c}" for n, (v, c) in pk.items()]
    return "\n".join(lines) + "\n"


def _plan(host, text: str):
    p = host.tmp / "plan"
    p.write_text(text)
    return p


def _summary(host, selected: dict | None = SELECTED, security_only: int = 1):
    text = (
        f"began={TUE_1530 - 3600}\nexit=0\ncount=5\nwall_seconds=540\n"
        f"security_only={security_only}\nlists_refreshed=1\n"
    )
    if selected is not None:
        text += "select_read=1\n"
        text += "".join(f"select={n} {v} {c}\n" for n, (v, c) in selected.items())
    (host.dry / "summary").write_text(text)


@pytest.fixture
def host(tmp_path) -> ApplyHost:
    h = _apply_ready(ApplyHost(tmp_path))
    # dpkg --compare-versions A gt B, as sort -V orders them.
    h.on(
        "dpkg",
        "--compare-versions *",
        script=(
            'a=$2 b=$4; [ "$a" != "$b" ] && '
            '[ "$(printf "%s\\n%s\\n" "$a" "$b" | sort -V | tail -n 1)" = "$a" ]; '
            "exit $?"
        ),
    )
    _summary(h)
    return h


def _kinds(out: dict) -> list[tuple[str, str, bool]]:
    return [
        (d["kind"], d["what"], d["inside"]) for d in out["gate"]["plan"]["differences"]
    ]


# --- the record --------------------------------------------------------------------


def test_a_covering_plan_runs_the_bulk_and_records_its_approval(host):
    p = _plan(host, HEAD + _section())
    out = host.run("--plan", str(p))
    a = out["apply"]["approval"]
    assert a == {
        "by": "plan",
        "plan": "cycle-2026-09-29",
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "approved_at": "2026-09-29T14:00:00Z",
        "approved_by": "owner, by passkey",
    }
    assert out["apply"]["approved"] is True
    g = out["gate"]["plan"]
    assert (g["covers"], g["inside"], g["differences"]) == (True, True, [])
    assert (g["id"], g["lane"], g["reboot"]) == ("cycle-2026-09-29", "security", "yes")


def test_without_a_plan_the_approval_is_the_sessions(host):
    out = host.run()
    assert out["apply"]["approval"] == {"by": "session"}
    assert out["gate"]["plan"] is None


def test_without_approve_there_is_no_approval(host):
    out = host.run(approve=False, rc=3)
    assert out["apply"]["approval"] is None


# --- the envelope ------------------------------------------------------------------


def _without(*names: str) -> dict:
    return {n: v for n, v in SELECTED.items() if n not in names}


@pytest.mark.parametrize(
    "plan_kw, selected, security_only, kinds",
    [
        # A planned package's candidate moved on: inside.
        (
            {},
            {**SELECTED, "libc6": ("2.39-0ubuntu8.7", "security")},
            1,
            [("version-newer", "libc6", True)],
        ),
        # A planned package the dry run no longer selects: noted, inside.
        (
            {
                "packages": {
                    **SELECTED,
                    "zlib1g": ("1:1.3.dfsg-3.1ubuntu2.1", "security"),
                }
            },
            SELECTED,
            1,
            [("not-pending", "zlib1g", True)],
        ),
        # A new package in the security lane: inside.
        (
            {"packages": _without("libssl3t64")},
            SELECTED,
            1,
            [("new-security", "libssl3t64", True)],
        ),
        # A planned package at a version that isn't newer: outside.
        (
            {},
            {**SELECTED, "libc6": ("2.39-0ubuntu8.5", "security")},
            1,
            [("version-other", "libc6", False)],
        ),
        # An unplanned package from -updates, the host's origins wider than
        # security: outside.
        (
            {"packages": _without("libxml2")},
            {**SELECTED, "libxml2": ("2.9.14+dfsg-1.3ubuntu3.6", "updates")},
            0,
            [("new-package", "libxml2", False)],
        ),
        # An origin the plan doesn't name: outside, even in the security lane.
        (
            {"packages": _without("libxml2")},
            {**SELECTED, "libxml2": ("2.9.15-1", "third-party:Example")},
            1,
            [("new-origin", "libxml2", False)],
        ),
        # A held step the plan doesn't name: a data store restarts there.
        ({"held": ()}, SELECTED, 1, [("held-step", "postgres", False)]),
        # The plan says no reboot, and PID 1's map can't be read: unknown.
        ({"reboot": "no"}, SELECTED, 1, [("reboot", "host", False)]),
        # A dry run from before this skill wrote each candidate and class.
        ({}, None, 1, [("unread", "selection", False)]),
    ],
    ids=[
        "version-newer",
        "not-pending",
        "new-security",
        "version-other",
        "new-package",
        "new-origin",
        "held-step",
        "reboot",
        "unread",
    ],
)
def test_the_bulk_is_held_to_the_plans_envelope(
    host, plan_kw, selected, security_only, kinds
):
    _summary(host, selected, security_only)
    p = _plan(host, HEAD + _section(**plan_kw))
    inside = all(k[2] for k in kinds)
    out = host.run("--plan", str(p), rc=0 if inside else 3)
    assert _kinds(out) == kinds
    assert out["gate"]["plan"]["inside"] is inside
    outside = [r for r in out["refused"] if r.startswith("outside the plan")]
    assert len(outside) == sum(1 for k in kinds if not k[2])
    if not inside:
        assert _changed(host) == []


def test_without_approve_the_envelope_is_reported_and_nothing_else_refused(host):
    # The executor's read-only check: the gate runs whole, and gate.plan
    # says the host would drop out.
    p = _plan(host, HEAD + _section(reboot="no"))
    out = host.run("--plan", str(p), approve=False, rc=3)
    assert [r for r in out["refused"] if not r.startswith("no --approve")] == []
    assert out["gate"]["plan"]["inside"] is False
    assert _kinds(out) == [("reboot", "host", False)]
    assert out["gate"]["run_span"]["reboot"] is None
    assert _changed(host) == []


# --- what a plan must cover --------------------------------------------------------


@pytest.mark.parametrize(
    "text, why",
    [
        (
            HEAD.replace("2026-09-29T23:00:00Z", "2026-09-29T15:00:00Z") + _section(),
            "passed its not-after, 2026-09-29T15:00:00Z",
        ),
        (HEAD + _section(host="web-2"), "has no [host web-1] section"),
        (HEAD + _section(lane="maintenance"), "approves the maintenance lane"),
    ],
    ids=["expired", "another-host", "another-lane"],
)
def test_a_plan_that_doesnt_cover_the_step_refuses_it(host, text, why):
    out = host.run("--plan", str(_plan(host, text)), rc=3)
    assert any(why in r for r in out["refused"]), out["refused"]
    assert out["gate"]["plan"]["covers"] is False
    assert _changed(host) == []


@pytest.mark.parametrize(
    "text, why",
    [
        (HEAD + "[host web-1]\nlane security\n", "needs a lane line and a reboot line"),
        (HEAD + _section() + "colour blue\n", "colour isn't a plan directive"),
        (HEAD + "lane security\n", "lane belongs in a [host <name>] section"),
        (_section(), "needs its plan, approved and not-after lines"),
        (HEAD + "[host web-*]\nlane security\nreboot no\n", "an exact name"),
        (HEAD + _section() + _section(), "[host web-1] appears twice"),
        (HEAD + _section() + "plan again\n", "plan belongs before any section"),
        (
            HEAD.replace("14:00:00Z", "25:00:00Z") + _section(),
            "approved takes a UTC time",
        ),
        (HEAD + _section() + "package libc6 2.39 testing\n", "package takes"),
        (HEAD + _section() + "reboot maybe\n", "reboot takes yes or no"),
    ],
    ids=[
        "no-reboot-line",
        "unknown-directive",
        "outside-a-section",
        "no-head",
        "glob-section",
        "section-twice",
        "head-in-a-section",
        "bad-time",
        "bad-class",
        "bad-reboot",
    ],
)
def test_a_malformed_plan_is_refused_never_guessed(host, text, why):
    out = host.run("--plan", str(_plan(host, text)), rc=3)
    [r] = [r for r in out["refused"] if r.startswith("the plan is malformed")]
    assert why in r
    assert _changed(host) == []


def test_a_held_step_the_plan_doesnt_name_is_refused(host):
    p = _plan(host, HEAD + _section(held=()))
    out = host.run("--plan", str(p), step="postgres", rc=3)
    assert any("doesn't name the held step postgres" in r for r in out["refused"])


# --- recovery-point.sh and reboot-chain.sh -----------------------------------------


@pytest.fixture
def recovery(tmp_path) -> RecoveryHost:
    return _postgres(_recovery_ready(RecoveryHost(tmp_path)))


def test_the_recovery_point_records_a_covering_plans_approval(recovery):
    p = _plan(recovery, HEAD + _section())
    out = recovery.recover("--plan", str(p))
    assert out["recovery_point"]["approval"]["by"] == "plan"
    assert (
        out["recovery_point"]["approval"]["sha256"]
        == hashlib.sha256(p.read_bytes()).hexdigest()
    )
    assert out["gate"]["plan"]["covers"] is True


def test_the_recovery_point_refuses_a_plan_for_another_host(recovery):
    p = _plan(recovery, HEAD + _section(host="web-2"))
    out = recovery.recover("--plan", str(p), rc=3)
    assert any("has no [host web-1] section" in r for r in out["refused"])


@pytest.fixture
def chain(tmp_path) -> RebootHost:
    return _reboot_ready(RebootHost(tmp_path))


def test_the_reboot_runs_under_a_plan_that_says_reboot_yes(chain):
    p = _plan(chain, HEAD + _section(reboot="yes"))
    (chain.run_dir / "approval").write_text(f"plan {_sha(p)} cycle-2026-09-29\n")
    out = chain.reboot("--plan", str(p))
    assert out["reboot_chain"]["approval"]["by"] == "plan"
    assert out["gate"]["plan"]["covers"] is True


def test_the_reboot_is_refused_under_a_plan_that_says_reboot_no(chain):
    p = _plan(chain, HEAD + _section(reboot="no"))
    out = chain.reboot("--plan", str(p), rc=3)
    assert any("says reboot no" in r for r in out["refused"])
    assert not any(n == "systemd-run" for n, _, _ in chain.calls())


# --- CR 2529: one read, of a regular file ------------------------------------------


class HashHost(ApplyHost):
    """The apply rig, with sha256sum a stub a case can answer."""

    STUBBED = (*ApplyHost.STUBBED, "sha256sum")
    FALLBACKS = {
        **ApplyHost.FALLBACKS,
        "sha256sum": (
            "for x in /usr/bin/sha256sum /sbin/sha256sum; do "
            '[ -x "$x" ] && exec "$x" "$@"; done; exec shasum -a 256 "$@"'
        ),
    }


def test_a_plan_is_parsed_and_hashed_from_one_read(tmp_path):
    # The file changes between a parse and a second read for the hash: the
    # record must hash what was parsed (CR 2529).
    host = _apply_ready(HashHost(tmp_path))
    _summary(host)
    good = HEAD + _section()
    p = _plan(host, good)
    other = host.tmp / "other"
    other.write_text(HEAD + _section(reboot="no", held=()))
    host.on(
        "sha256sum",
        "*",
        script=(
            f'cp "{other}" "{p}"; for x in /usr/bin/sha256sum /sbin/sha256sum; do '
            '[ -x "$x" ] && exec "$x" "$@"; done; exec shasum -a 256 "$@"'
        ),
    )
    out = host.run("--plan", str(p))
    sha = hashlib.sha256(good.encode()).hexdigest()
    assert out["apply"]["approval"]["sha256"] == sha
    assert out["gate"]["plan"]["reboot"] == "yes"


def test_a_plan_that_isnt_a_regular_file_is_refused(host):
    # A pipe: /dev/stdin, as an executor might pass it (CR 2529).
    p = _plan(host, HEAD + _section())
    cmd = [
        "bash",
        "-c",
        'f=$1; shift; cat "$f" | "$@"',
        "x",
        str(p),
        "bash",
        str(host.scripts / "apply.sh"),
        "--step",
        "bulk",
        "--run",
        str(host.run_dir),
        "--config",
        str(host.knob_path),
        "--host",
        "web-1",
        "--today",
        "2026-09-29",
        "--approve",
        "--dry-run",
        str(host.dry),
        "--plan",
        "/dev/stdin",
    ]
    host.cases["date"] = [("+%s", f"{host.clock}\n", 0, "", None)]
    (host.state / "holds").write_text("")
    r = host.execute(cmd, 3)
    assert "isn't a regular file" in r.stdout
    assert _changed(host) == []


def test_a_plan_holding_a_nul_byte_is_refused(host):
    p = host.tmp / "plan"
    p.write_bytes(
        (HEAD + _section()).replace("lane security", "lane secu\0rity").encode()
    )
    out = host.run("--plan", str(p), rc=3)
    [r] = [r for r in out["refused"] if r.startswith("the plan is malformed")]
    assert "NUL" in r


# --- CR 2530: the plan against the bulk's refreshed lists, and its held steps --------


def test_a_release_since_the_dry_run_for_a_planned_held_step_stops_the_bulk(host):
    # postgresql-16 wasn't pending at the dry run; the refreshed lists offer
    # it, the bulk would hold it for postgres, which the plan approves for
    # libpq5, and that step would install and restart an unplanned version.
    sel = {k: v for k, v in SELECTED.items() if k != "postgresql-16"}
    (host.dry / "dry-run.log").write_text(
        "Packages that will be upgraded: " + " ".join(sel) + "\n"
    )
    _summary(host, sel)
    p = _plan(host, HEAD + _section(packages=sel))
    out = host.run("--plan", str(p), rc=1)
    text = json.dumps(out)
    assert "postgresql-16" in text and "refreshed lists" in text
    assert host.holds() == []
    assert not host.calls("unattended-upgrade")


def _held_run(host, plan_path, approval: str | None, versions: str) -> None:
    host.run_dir.mkdir()
    host.run_dir.chmod(0o700)
    (host.run_dir / "dry-run").write_text("lane=security\n")
    (host.run_dir / "holds").write_text("postgres postgresql-16\npostgres libpq5\n")
    (host.run_dir / "hold-versions").write_text(versions)
    if approval is not None:
        (host.run_dir / "approval").write_text(approval)


PG_VERSIONS = "postgresql-16 16.10-0ubuntu0.24.04.1\nlibpq5 16.10-0ubuntu0.24.04.1\n"


def _sha(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "approval, why",
    [
        (None, "can't be read"),
        ("session\n", "isn't this plan"),
        ("plan " + "0" * 64 + " cycle-2026-09-28\n", "isn't this plan"),
    ],
    ids=["no-record", "session", "another-plan"],
)
def test_a_held_step_runs_only_under_its_bulks_plan(host, approval, why):
    p = _plan(host, HEAD + _section())
    _held_run(host, p, approval, PG_VERSIONS)
    out = host.run("--plan", str(p), step="postgres", rc=3)
    assert any(why in r for r in out["refused"]), out["refused"]


def test_a_held_step_releasing_an_unplanned_package_is_refused(host):
    sel = {k: v for k, v in SELECTED.items() if k != "postgresql-16"}
    p = _plan(host, HEAD + _section(packages=sel))
    _held_run(host, p, f"plan {_sha(p)} cycle-2026-09-29\n", PG_VERSIONS)
    out = host.run("--plan", str(p), step="postgres", rc=3)
    assert ("held-package", "postgresql-16", False) in _kinds(out)


def test_a_held_step_under_its_bulks_plan_compares_versions(host):
    p = _plan(host, HEAD + _section())
    newer = PG_VERSIONS.replace("libpq5 16.10", "libpq5 16.11")
    _held_run(host, p, f"plan {_sha(p)} cycle-2026-09-29\n", newer)
    out = host.run("--plan", str(p), step="postgres", rc=3)
    # Refused for the bulk the run never ran, not for the plan.
    assert not [r for r in out["refused"] if "plan" in r], out["refused"]
    assert ("version-newer", "libpq5", True) in _kinds(out)


def test_the_reboot_runs_only_under_its_bulks_plan(chain):
    p = _plan(chain, HEAD + _section(reboot="yes"))
    (chain.run_dir / "approval").write_text("session\n")
    out = chain.reboot("--plan", str(p), rc=3)
    assert any("isn't this plan" in r for r in out["refused"])


# --- CR 2531: a planned package's class -------------------------------------------


@pytest.mark.parametrize(
    "fresh, security_only, kinds",
    [
        # Now from a third-party origin the plan names for another package.
        (
            ("2.39-0ubuntu8.7", "third-party:Example"),
            1,
            [("class-changed", "libc6", False)],
        ),
        # Now from -updates, the host's origins wider than security.
        (("2.39-0ubuntu8.7", "updates"), 0, [("class-changed", "libc6", False)]),
        # The masking case: in a security-only lane, a newer -updates
        # version hides the -security one the step installs. Inside.
        (("2.39-0ubuntu8.7", "updates"), 1, [("version-newer", "libc6", True)]),
    ],
    ids=["third-party", "updates-wide", "updates-masking"],
)
def test_a_planned_packages_class_change_is_outside(host, fresh, security_only, kinds):
    _summary(host, {**SELECTED, "libc6": fresh}, security_only)
    pk = {**SELECTED, "docker-ce": ("1.0", "third-party:Example")}
    p = _plan(host, HEAD + _section(packages=pk))
    inside = all(k[2] for k in kinds)
    out = host.run("--plan", str(p), rc=0 if inside else 3)
    got = [k for k in _kinds(out) if k[1] == "libc6"]
    assert got == kinds


# --- CR 2532: the masking rule, said ----------------------------------------------


@pytest.mark.parametrize("cls", ["updates", "esm", "ubuntu-other"])
def test_an_unplanned_masked_package_in_a_security_only_lane_says_so(host, cls):
    # The dry run of a security lane whose origins are security alone
    # selected it, so the step takes its -security version; the simulation
    # shows a newer one from elsewhere. Inside, and the detail says whose
    # version it names.
    _summary(host, {**SELECTED, "libxml2": ("2.9.14+dfsg-1.3ubuntu3.6", cls)}, 1)
    p = _plan(host, HEAD + _section(packages=_without("libxml2")))
    out = host.run("--plan", str(p))
    [d] = out["gate"]["plan"]["differences"]
    assert (d["kind"], d["inside"]) == ("new-security", True)
    assert "the simulation's" in d["detail"] and cls in d["detail"]


# --- CR 2533: an empty --plan --------------------------------------------------------


@pytest.mark.parametrize(
    "script, args",
    [
        ("apply.sh", ["--step", "bulk"]),
        ("recovery-point.sh", ["--retain-until", "2099-01-01"]),
        ("reboot-chain.sh", ["--run", "/nonexistent"]),
    ],
)
def test_an_empty_plan_is_a_usage_error_not_a_session(script, args):
    # "--plan ''" read as no plan: the step ran as the session's approval.
    r = subprocess.run(
        ["bash", str(SKILL / "scripts" / script), *args, "--approve", "--plan", ""],
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    assert r.returncode == 2
    assert "--plan takes a file" in r.stderr


# --- CR 2535: the next commands carry the approval ---------------------------------


def test_the_bulks_next_held_step_carries_its_plan(host):
    p = _plan(host, HEAD + _section())
    out = host.run("--plan", str(p))
    [n] = [x for x in out["next"] if "--step postgres" in x]
    assert f'--plan "{p}"' in n


def test_the_recovery_points_next_bulk_carries_its_plan(recovery):
    p = _plan(recovery, HEAD + _section())
    out = recovery.recover("--plan", str(p))
    [n] = [x for x in out["next"] if "--step bulk" in x]
    assert f'--plan "{p}"' in n


def test_a_package_named_twice_in_a_section_is_malformed(host):
    # CR 2536: "package libc6 0 security" beside the real line made any
    # candidate newer than planned, so inside.
    p = _plan(host, HEAD + _section() + "package libc6 0 security\n")
    out = host.run("--plan", str(p), rc=3)
    [r] = [r for r in out["refused"] if r.startswith("the plan is malformed")]
    assert "package libc6 appears twice in [host web-1]" in r


# --- CR 2537: a step's span ends before the plan's not-after ------------------------


def test_a_bulk_whose_span_runs_past_the_plans_not_after_is_refused(host):
    # From 15:30 the run's span is about an hour; the plan ends at 15:45.
    p = _plan(
        host, HEAD.replace("2026-09-29T23:00:00Z", "2026-09-29T15:45:00Z") + _section()
    )
    out = host.run("--plan", str(p), rc=3)
    assert any(
        "span runs to 2026-09-29T16:29:00Z, past the plan cycle-2026-09-29's "
        "not-after, 2026-09-29T15:45:00Z" in r
        for r in out["refused"]
    ), out["refused"]


def test_a_reboot_whose_span_runs_past_the_plans_not_after_is_refused(chain):
    # The chain's span is its 120 s delay, 60 s of gate and 600 s of boot.
    p = _plan(
        chain, HEAD.replace("2026-09-29T23:00:00Z", "2026-09-29T15:35:00Z") + _section()
    )
    (chain.run_dir / "approval").write_text(f"plan {_sha(p)} cycle-2026-09-29\n")
    out = chain.reboot("--plan", str(p), rc=3)
    assert any(
        "span runs to 2026-09-29T15:43:00Z, past the plan" in r for r in out["refused"]
    ), out["refused"]


# --- CR 2539: a clock that can't be read ---------------------------------------------


def test_a_plan_is_refused_when_the_clock_cant_be_read(tmp_path):
    p = tmp_path / "plan"
    p.write_text(HEAD + _section())
    lib = SKILL / "scripts"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    script = (
        "set -euo pipefail; "
        + "".join(
            f'. "{lib}/{x}"; '
            for x in ("_knob-lib.sh", "_probe-lib.sh", "_gate-lib.sh", "_plan-lib.sh")
        )
        + f'P_PRIV=none P_TMP="{scratch}" P_NOW=soon; '
        + f'if plan_gate 1 "{p}" web-1; then echo stood; else printf "%s\\n" "${{REFUSED[@]}}"; fi'
    )
    r = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=_clean_env()
    )
    assert "stood" not in r.stdout, r.stderr
    assert "clock can't be read" in r.stdout, (r.stdout, r.stderr)
