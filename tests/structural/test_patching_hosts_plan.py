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

import pytest

from tests.structural.patching_hosts_rig import dispatcher
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
