"""patching-hosts' gated apply: `apply.sh` (#313, plan step 6).

In the step 0 round every host was patched in the same shape by hand: a
recovery point off the node, a bulk step with the data-store and Docker
packages held, each held group under its own approval with its restarters
stopped, and needrestart held to list mode throughout. apply.sh is that
shape as a script, so each gate is checked rather than remembered.

What this file pins, against the plan's step 6 list:

- each refusal: no --approve, a report-only host, a span that starts inside
  a window but runs past its close, one that starts outside a quiet range
  but runs into it, an inflight count above 0, a missing or mismatched
  --offnode-sha256, one dump of two left unattested, and a backup unit whose
  last successful run predates the recovery point or that lacks
  --offnode-object. A refusal changes nothing;
- the before-versions, recorded root-only;
- the holds: the bulk holds each group's pending packages and never the
  owner's, a held step releases only its own, and `apt-mark showhold` ends
  equal to its recorded value;
- `NEEDRESTART_MODE=l` and `choom -n 0` around unattended-upgrade, even
  through a sudo that resets the environment;
- a failing verdict stops the run, its abort lists the run's own holds, and
  no held step follows it;
- no `systemctl unmask`, `enable` or `reboot`, and no `apt-get remove` or
  `purge`, in a whole run.

Beyond that list, from reading unattended-upgrade 2.9.1 in the exeuntu
image:

- a host whose Automatic-Reboot is true is refused: unattended-upgrade
  reboots by itself, takes no -o, and APT_CONFIG is read before apt.conf.d,
  so nothing passed to it could stop that;
- origins wider than -security are refused without an exception, since the
  security lane would apply them too;
- an unclean `dpkg --audit` before the step is refused;
- the bulk refreshes the host's own lists, which the probe's dry run never
  touches, and a refresh that fails holds nothing;
- exit 0 without "All upgrades installed" or "No packages found" isn't green.

Each case runs apply.sh from a copy of the skill's scripts, with probe.sh
replaced by a stub that logs its arguments, so the re-probe after a step
never reads the machine running the tests. `date +%s` answers a fixed time.
"""

import calendar
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.structural.patching_hosts_rig import SKILL, dispatcher
from tests.structural.patching_hosts_rig import Host as RigHost
from tests.structural.patching_hosts_rig import clean_env as _clean_env

APPLY = SKILL / "scripts" / "apply.sh"
TODAY = "2026-09-29"
# Tuesday 2026-09-29, 15:30 UTC.
TUE_1530 = calendar.timegm((2026, 9, 29, 15, 30, 0))
MIN = 60
SHA_A = "a" * 64
SHA_B = "b" * 64

KNOB = """class production
posture scheduled
window Tue 15:00-21:00
health curl -sf http://localhost:8000/health
restarter app-healthcheck.timer
"""

SIMULATION = """NOTE: This is only a simulation!
Inst libc6 [2.39-0ubuntu8.5] (2.39-0ubuntu8.6 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [arm64])
Inst postgresql-16 [16.9-0ubuntu0.24.04.1] (16.10-0ubuntu0.24.04.1 Ubuntu:24.04/noble-security [arm64])
Inst libpq5 [16.9-0ubuntu0.24.04.1] (16.10-0ubuntu0.24.04.1 Ubuntu:24.04/noble-security [arm64])
Inst redis-server [5:7.0.15-1build2] (5:7.0.15-1ubuntu0.24.04.1 Ubuntu:24.04/noble-security [arm64])
Inst linux-libc-dev-new (6.8.0-85.85 Ubuntu:24.04/noble-security [arm64])
Conf libc6 (2.39-0ubuntu8.6 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [arm64])
"""

STUB_PROBE = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "${0%/*}/../probe-calls"
echo '{"probe": "stub"}'
"""


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


class Host(RigHost):
    STUBBED = (*RigHost.STUBBED, "date", "sleep")
    FALLBACKS = {
        **RigHost.FALLBACKS,
        "date": 'exec /bin/date "$@"',
        "sleep": "exit 0",
    }

    def __init__(self, tmp_path: Path, **kw):
        super().__init__(tmp_path, **kw)
        self.scripts = tmp_path / "scripts"
        shutil.copytree(SKILL / "scripts", self.scripts)
        (self.scripts / "probe.sh").write_text(STUB_PROBE)
        self.run_dir = tmp_path / "run"
        self.dry = tmp_path / "dry"
        self.dry.mkdir()
        (self.dry / "summary").write_text(
            "exit=0\ncount=4\nwall_seconds=540\nsecurity_only=1\n"
        )
        self.state = tmp_path / "state"
        self.state.mkdir()
        self.clock = TUE_1530
        self.owner_holds: list[str] = []

    def unit(self, name: str, state: str = "active") -> "Host":
        """A unit whose state stop and start change, and is-active reads."""
        f = self.state / f"unit.{name}"
        f.write_text(state + "\n")
        self.on(
            "systemctl",
            f"is-active -- {name}",
            script=f'cat "{f}"; [ "$(cat "{f}")" = active ]; exit $?',
        )
        self.on("systemctl", f"stop -- {name}", script=f'echo inactive > "{f}"; exit 0')
        self.on("systemctl", f"start -- {name}", script=f'echo active > "{f}"; exit 0')
        return self

    def uu(self, out: str, rc: int = 0, before: str = "") -> "Host":
        """unattended-upgrade -v: runs BEFORE, prints NEEDRESTART_MODE as it
        sees it, then OUT, and exits RC."""
        o = self.state / "uu.out"
        o.write_text(out)
        self.cases["unattended-upgrade"] = [
            (
                "-v",
                "",
                0,
                "",
                f'{before}echo "NEEDRESTART_MODE=${{NEEDRESTART_MODE:-}}"; cat "{o}"; exit {rc}',
            )
        ]
        return self

    def holds(self) -> list[str]:
        f = self.state / "holds"
        return sorted(set(f.read_text().split())) if f.exists() else []

    def run(
        self,
        *args: str,
        rc: int = 0,
        step: str = "bulk",
        approve: bool = True,
        dry: bool = True,
        env: dict | None = None,
    ) -> dict:
        holds = self.state / "holds"
        if not holds.exists():
            holds.write_text("".join(p + "\n" for p in self.owner_holds))
        self.cases["date"] = [("+%s", f"{self.clock}\n", 0, "", None)]
        cmd = ["bash", str(self.scripts / "apply.sh"), "--step", step]
        cmd += ["--run", str(self.run_dir), "--config", str(self.knob_path)]
        cmd += ["--host", "web-1", "--today", TODAY]
        if approve:
            cmd.append("--approve")
        if dry and step == "bulk":
            cmd += ["--dry-run", str(self.dry)]
        self.execute([*cmd, *args], rc, env)
        return json.loads(self.result.stdout)

    def record(self, name: str) -> str:
        return (self.run_dir / name).read_text()


def _ready(host: Host) -> Host:
    """A host a bulk goes green on: every reading answered, nothing in flight."""
    host.knob(KNOB)
    host.apt_config(Reboot="false")
    host.on(
        "apt-config",
        "dump",
        'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}";\n'
        'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}-security";\n',
    )
    host.on("dpkg", "--audit", "")
    host.on("apt-get", "update", "Hit:1 http://ports.ubuntu.com noble InRelease\n")
    host.on("apt-get", "-s dist-upgrade", SIMULATION)
    host.on(
        "dpkg-query",
        "-W",
        "libc6\t2.39-0ubuntu8.5\npostgresql-16\t16.9-0ubuntu0.24.04.1\n",
    )
    host.on("apt-mark", "showauto", "libpq5\n")
    s = host.state
    host.on("apt-mark", "showhold", script=f'sort -u "{s}/holds"; exit 0')
    host.on(
        "apt-mark",
        "hold *",
        script=f'shift; for p; do echo "$p" >> "{s}/holds"; done; exit 0',
    )
    host.on(
        "apt-mark",
        "unhold *",
        script=(
            f'shift; for p; do grep -vxF "$p" "{s}/holds" > "{s}/h" || true; '
            f'mv "{s}/h" "{s}/holds"; done; exit 0'
        ),
    )
    host.uu("Packages that will be upgraded: libc6\nAll upgrades installed\n")
    host.on("curl", "*", "")
    host.unit("app-healthcheck.timer")
    return host


@pytest.fixture
def host(tmp_path) -> Host:
    return _ready(Host(tmp_path))


def _changed(host: Host) -> list[str]:
    """Every call that changes the host."""
    out = []
    for name, args, _ in host.calls():
        if (
            (name == "apt-get" and not args.startswith("-s "))
            or (name == "apt-mark" and args.split()[0] in ("hold", "unhold"))
            or name == "unattended-upgrade"
            or (name == "systemctl" and args.split()[0] in ("stop", "start"))
        ):
            out.append(f"{name} {args}")
    return out


# --- the command line -----------------------------------------------------------


def test_help_names_the_steps_the_refusals_and_the_exit_codes():
    r = subprocess.run(
        ["bash", str(APPLY), "--help"], capture_output=True, text=True, env=_clean_env()
    )
    assert r.returncode == 0
    for word in (
        "--approve",
        "--offnode-sha256",
        "--offnode-object",
        "NEEDRESTART_MODE=l choom -n 0",
        "Automatic-Reboot",
        "quiet",
        "inflight",
        "before-versions",
        "  3  refused",
    ):
        assert word in r.stdout, word


@pytest.mark.parametrize(
    "args, message",
    [
        ([], "--step is required"),
        (["--step", "Bulk"], "--step takes bulk"),
        (["--step", "bulk", "--run", "rel/dir"], "absolute path"),
        (
            ["--step", "postgres", "--run", "/x", "--dry-run", "/d"],
            "belong to the bulk",
        ),
        (["--step", "postgres"], "needs --run"),
        (["--step", "bulk", "--offnode-sha256", "abc"], "64 hex digits"),
        (["--step", "bulk", "--health-within", "0"], "--health-within"),
        (["--step", "bulk", "--bogus"], "unknown argument"),
    ],
)
def test_usage_errors_exit_2(args, message):
    r = subprocess.run(
        ["bash", str(APPLY), *args], capture_output=True, text=True, env=_clean_env()
    )
    assert r.returncode == 2
    assert message in r.stderr


# --- refusals ---------------------------------------------------------------------


def test_without_approve_it_refuses_and_changes_nothing(host):
    out = host.run(approve=False, rc=3)
    assert any("no --approve" in r for r in out["refused"])
    # The gate still reads, so the operator sees it before asking the owner.
    assert out["gate"]["span"]["window"]["line"] == 3
    assert _changed(host) == []
    assert not host.run_dir.exists()
    assert out["verdict"] is None


@pytest.mark.parametrize(
    "knob, why",
    [
        (KNOB + "class ephemeral\n", "class ephemeral"),
        (KNOB.replace("posture scheduled\n", ""), "no posture line"),
        (KNOB + "window Tue 25:00-26:00\n", "a malformed line"),
        (None, "no knob"),
    ],
)
def test_a_report_only_host_is_refused(host, knob, why):
    if knob is None:
        host.knob_path.unlink()
    else:
        host.knob(knob)
    out = host.run(rc=3)
    assert any(r.startswith("report-only:") and why in r for r in out["refused"])
    assert _changed(host) == []


def test_a_span_that_starts_inside_a_window_but_runs_past_its_close_is_refused(host):
    # 540 s of dry run and 300 s of health checks from 20:50 end at 21:04.
    host.clock = TUE_1530 + 5 * 3600 + 20 * MIN
    out = host.run(rc=3)
    [r] = [r for r in out["refused"] if "window" in r]
    assert "2026-09-29T20:50:00Z to 2026-09-29T21:04:00Z" in r
    assert out["gate"]["span"]["window"] is None
    assert _changed(host) == []


def test_a_span_that_starts_outside_a_quiet_range_but_runs_into_it_is_refused(host):
    host.knob(KNOB + "quiet 15:40-16:00\nquiet 16:00-16:30\n")
    out = host.run(rc=3)
    [r] = [r for r in out["refused"] if "quiet" in r]
    assert "15:40-16:00 (line 6)" in r
    assert [q["line"] for q in out["gate"]["span"]["quiet_overlaps"]] == [6]
    assert _changed(host) == []


def test_a_quiet_range_on_another_weekday_doesnt_count(host):
    host.knob(KNOB + "quiet 15:40-16:00 Wed\n")
    assert host.run()["verdict"]["ok"] is True


@pytest.mark.parametrize(
    "window, clock",
    [
        # Opens Tuesday at 22:00 and closes Wednesday at 02:00.
        ("window Tue 22:00-02:00", TUE_1530 + 9 * 3600 + 30 * MIN),
        # Opens Sunday at 23:00, so a Monday 00:10 is in last week's.
        ("window Sun 23:00-01:00", TUE_1530 - 39 * 3600 - 20 * MIN),
    ],
)
def test_a_window_that_wraps_past_midnight_holds_the_span(host, window, clock):
    host.knob(KNOB.replace("window Tue 15:00-21:00", window))
    host.clock = clock
    out = host.run()
    assert out["gate"]["span"]["window"]["line"] == 3


def test_no_window_refuses(host):
    host.knob(KNOB.replace("window Tue 15:00-21:00\n", ""))
    out = host.run(rc=3)
    assert any("no window is declared" in r for r in out["refused"])


@pytest.mark.parametrize(
    "answer, said",
    [
        ({"stdout": "3\n"}, 'printed "3", not 0'),
        ({"stdout": "", "rc": 124}, "timed out after 60 s"),
    ],
)
def test_work_in_flight_refuses(host, answer, said):
    host.knob(KNOB + "inflight queue-depth\n")
    host.on("timeout", "*queue-depth", **answer)
    out = host.run(rc=3)
    assert any(said in r for r in out["refused"])
    assert out["gate"]["inflight"][0]["ok"] is False


def test_a_host_that_would_reboot_itself_is_refused(host):
    host.cases["apt-config"] = [c for c in host.cases["apt-config"] if c[0] != "shell*"]
    host.apt_config(Reboot="true")
    out = host.run(rc=3)
    assert any('Automatic-Reboot is "true"' in r for r in out["refused"])
    assert _changed(host) == []


def test_origins_wider_than_security_refuse_unless_excepted(host):
    host.on(
        "apt-config",
        "dump",
        'Unattended-Upgrade::Origins-Pattern:: "origin=Ubuntu,archive=noble-updates";\n',
    )
    host.cases["apt-config"].insert(0, host.cases["apt-config"].pop())
    out = host.run(rc=3)
    assert any("takes more than -security" in r for r in out["refused"])
    assert out["gate"]["unattended_upgrade"]["wider"] == [
        "origin=Ubuntu,archive=noble-updates"
    ]
    host.knob(KNOB + "exception uu:origins 2026-12-31 the owner takes -updates\n")
    assert host.run()["gate"]["unattended_upgrade"]["wider_excepted"] is True


def test_an_unclean_dpkg_audit_refuses(host):
    host.cases["dpkg"] = []
    host.on("dpkg", "--audit", "The following packages are only half configured:\n")
    out = host.run(rc=3)
    assert any("half configured" in r for r in out["refused"])
    assert _changed(host) == []


def test_knob_commands_never_run_as_root(host):
    # Root with no invoking user: nobody to run the health check as.
    out = host.run(rc=3, env={"STUB_USER": "root"})
    assert any("never run as root" in r for r in out["refused"])
    assert not host.calls("curl")


# --- the recovery point -----------------------------------------------------------

DATASTORE = KNOB + "datastore postgres postgresql@16-main app audit\n"


def _recovery(host: Host, *lines: str, began: int | None = None) -> None:
    host.run_dir.mkdir()
    host.run_dir.chmod(0o700)
    began = TUE_1530 - 3600 if began is None else began
    (host.run_dir / "recovery-point").write_text(
        f"began {began}\n" + "".join(line + "\n" for line in lines)
    )


def test_a_datastore_without_a_recovery_point_is_refused(host):
    host.knob(DATASTORE)
    out = host.run(rc=3)
    assert any("holds no recovery point" in r for r in out["refused"])


def test_every_dump_must_be_attested_off_the_node(host):
    host.knob(DATASTORE)
    _recovery(
        host,
        f"dump postgres postgresql@16-main app {SHA_A} /var/backups/app-1.dump",
        f"dump postgres postgresql@16-main audit {SHA_B} /var/backups/audit-1.dump",
        "local /var/backups/globals-1.sql",
    )
    # None attested, then one of two.
    out = host.run(rc=3)
    assert len([r for r in out["refused"] if "isn't attested" in r]) == 2
    out = host.run("--offnode-sha256", SHA_A.upper(), rc=3)
    [r] = [r for r in out["refused"] if "isn't attested" in r]
    assert "/var/backups/audit-1.dump" in r
    # The expected value never appears: the owner types it from their copy.
    assert SHA_B not in host.result.stdout + host.result.stderr
    assert _changed(host) == []
    out = host.run("--offnode-sha256", SHA_A, "--offnode-sha256", SHA_B)
    assert [d["attested"] for d in out["gate"]["recovery_point"]["dumps"]] == [
        True,
        True,
    ]


def test_a_mismatched_sha256_attests_nothing(host):
    host.knob(DATASTORE.replace(" audit\n", "\n"))
    _recovery(
        host, f"dump postgres postgresql@16-main app {SHA_A} /var/backups/app-1.dump"
    )
    out = host.run("--offnode-sha256", "c" * 64, rc=3)
    assert any("isn't attested" in r for r in out["refused"])
    assert any("matches no dump" in r for r in out["refused"])


def test_a_database_the_recovery_point_missed_is_refused(host):
    host.knob(DATASTORE)
    _recovery(
        host, f"dump postgres postgresql@16-main app {SHA_A} /var/backups/app-1.dump"
    )
    out = host.run("--offnode-sha256", SHA_A, rc=3)
    [r] = [r for r in out["refused"] if "no dump of" in r]
    assert "postgres postgresql@16-main audit" in r


def test_a_recovery_point_from_another_day_is_refused(host):
    host.knob(DATASTORE.replace(" audit\n", "\n"))
    _recovery(
        host,
        f"dump postgres postgresql@16-main app {SHA_A} /var/backups/app-1.dump",
        began=TUE_1530 - 25 * 3600,
    )
    out = host.run("--offnode-sha256", SHA_A, rc=3)
    assert any("more than 24 hours ago" in r for r in out["refused"])


@pytest.mark.parametrize(
    "started, objects, refused",
    [
        (
            -2 * 3600,
            ["s3://bucket/app-1"],
            "hasn't started since the recovery point began",
        ),
        # Begun before the recovery point, though it finished after: it read
        # the data as it stood then.
        (-MIN, ["s3://bucket/app-1"], "hasn't started since the recovery point began"),
        (10 * MIN, [], "--offnode-object names were given"),
        (10 * MIN, ["s3://bucket/app-1"], None),
    ],
)
def test_a_backup_unit_must_have_run_since_the_recovery_point(
    host, started, objects, refused
):
    host.knob(DATASTORE)
    began = TUE_1530 - 3600
    _recovery(host, "backup app-backup", began=began)
    host.show(
        "app-backup.service",
        Result="success",
        ExecMainStartTimestamp=f"@{began + started}",
        ExecMainExitTimestamp=f"@{began + started + 120}",
    )
    args = [a for o in objects for a in ("--offnode-object", o)]
    if refused:
        out = host.run(*args, rc=3)
        assert any(refused in r for r in out["refused"])
        assert _changed(host) == []
    else:
        out = host.run(*args)
        assert out["gate"]["recovery_point"]["backups"][0]["ok"] is True


def test_an_attestation_with_no_datastore_is_refused(host):
    out = host.run("--offnode-sha256", SHA_A, rc=3)
    assert any("declares no datastore" in r for r in out["refused"])


# --- the bulk ---------------------------------------------------------------------


def test_the_bulk_records_the_before_versions_root_only(host):
    out = host.run()
    assert out["verdict"]["ok"] is True
    assert oct(host.run_dir.stat().st_mode & 0o777) == "0o700"
    for name in (
        "before-versions",
        "before-showhold",
        "before-showauto",
        "holds",
        "steps",
    ):
        assert oct((host.run_dir / name).stat().st_mode & 0o777) == "0o600", name
    assert "postgresql-16\t16.9-0ubuntu0.24.04.1" in host.record("before-versions")
    assert host.record("before-showauto") == "libpq5\n"
    # Recorded before anything was held.
    calls = [f"{n} {a}" for n, a, _ in host.calls()]
    assert calls.index("dpkg-query -W") < calls.index(
        next(c for c in calls if c.startswith("apt-mark hold"))
    )


def test_the_bulk_holds_each_groups_pending_packages_and_never_the_owners(host):
    host.owner_holds = ["libpq5"]
    out = host.run()
    assert out["holds"]["placed"] == {
        "postgres": ["postgresql-16"],
        "redis": ["redis-server"],
    }
    assert out["holds"]["owner"] == ["libpq5"]
    [hold] = [a for n, a, _ in host.calls("apt-mark") if a.startswith("hold")]
    assert hold == "hold postgresql-16 redis-server"
    assert host.record("holds") == "postgres postgresql-16\nredis redis-server\n"
    # The lists were refreshed first, then the bulk ran with the holds on.
    changed = _changed(host)
    assert changed[0] == "apt-get update"
    assert changed.index("apt-mark hold postgresql-16 redis-server") < changed.index(
        "unattended-upgrade -v"
    )
    assert out["next"][:2] == [
        f"bash apply.sh --approve --step postgres --run {host.run_dir}: approval 3(a), a restart",
        f"bash apply.sh --approve --step redis --run {host.run_dir}: approval 3(a), a restart",
    ]


@pytest.mark.parametrize("sudo", [True, "reset"])
def test_needrestart_mode_and_choom_reach_unattended_upgrade(tmp_path, sudo):
    host = _ready(Host(tmp_path, sudo=sudo))
    out = host.run()
    assert "NEEDRESTART_MODE=l\n" in host.record("bulk.log")
    # GNU time, where it's there, sits between them to read max RSS.
    [choom] = [a for _, a, _ in host.calls("choom")]
    assert choom.startswith("-n 0 -- ")
    assert choom.endswith(" unattended-upgrade -v")
    assert out["upgrade"]["upgraded"] == ["libc6"]
    assert out["upgrade"]["all_installed"] is True
    assert out["upgrade"]["max_rss_kib"] == 2048


def test_the_bulk_reprobes_into_the_run(host):
    host.run()
    assert (
        (host.tmp / "probe-calls")
        .read_text()
        .startswith(f"--config {host.knob_path} --host web-1 --today {TODAY}")
    )
    assert json.loads(host.record("probe-after-bulk.json")) == {"probe": "stub"}
    assert (
        oct((host.run_dir / "probe-after-bulk.json").stat().st_mode & 0o777) == "0o600"
    )


def test_lists_that_wont_refresh_hold_nothing_and_the_bulk_can_run_again(host):
    green = host.cases["apt-get"]
    host.cases["apt-get"] = [("update", "", 100, "", None), *green]
    out = host.run(rc=1)
    assert out["abort"]["instructions"] == [
        "Nothing was held or upgraded: fix what failed, then run this step again."
    ]
    assert not [a for _, a, _ in host.calls("apt-mark") if a.startswith("hold")]
    host.cases["apt-get"] = green
    assert host.run()["verdict"]["ok"] is True


def test_a_bulk_that_already_started_is_refused(host):
    host.run()
    out = host.run(rc=3)
    assert any("bulk already started" in r for r in out["refused"])


# --- the verdict and the abort ------------------------------------------------------


@pytest.mark.parametrize(
    "uu, rc, audit, why",
    [
        ("Installing the upgrades failed!\n", 1, "", "unattended-upgrade exited 1"),
        (
            "Packages that will be upgraded: libc6\n",
            0,
            "",
            'neither "All upgrades installed"',
        ),
        (
            "All upgrades installed\n",
            0,
            "The following packages are in a mess:\n",
            "dpkg --audit isn't clean after the step",
        ),
    ],
)
def test_a_failing_verdict_stops_the_run_and_lists_its_holds(host, uu, rc, audit, why):
    # Clean before the step, then not.
    host.cases["dpkg"] = [
        (
            "--audit",
            "",
            0,
            "",
            f'if [ -e "{host.state}/ran" ]; then printf %s "{audit}"; fi; exit 0',
        )
    ]
    host.uu(uu, rc, before=f'touch "{host.state}/ran"; ')
    out = host.run(rc=1)
    assert out["verdict"]["ok"] is False
    assert any(why in w for w in out["verdict"]["why"])
    # Read past GNU time's status line on a failed run.
    assert out["upgrade"]["max_rss_kib"] == 2048
    # In the simulation's order.
    assert out["abort"]["holds_left"] == [
        {"step": "postgres", "package": "postgresql-16"},
        {"step": "postgres", "package": "libpq5"},
        {"step": "redis", "package": "redis-server"},
    ]
    assert any("exception held:<package>" in i for i in out["abort"]["instructions"])
    assert out["next"] == []
    # No held step follows an abort.
    out = host.run(step="postgres", rc=3)
    assert any("the run aborted at bulk" in r for r in out["refused"])


def test_a_hold_that_didnt_take_stops_the_bulk_before_it_upgrades(host):
    # apt-mark exits 0 having held only the first package.
    s = host.state
    host.cases["apt-mark"] = [
        ("hold *", "", 0, "", f'echo "$2" >> "{s}/holds"; exit 0'),
        *host.cases["apt-mark"],
    ]
    out = host.run(rc=1)
    [why] = out["verdict"]["why"]
    assert "not held: libpq5 redis-server" in why
    assert not host.calls("unattended-upgrade")
    assert out["abort"]["holds_left"] == [
        {"step": "postgres", "package": "postgresql-16"}
    ]


def test_nothing_to_upgrade_is_green(host):
    host.uu(
        "No packages found that can be upgraded unattended and no pending auto-removals\n"
    )
    out = host.run()
    assert out["verdict"]["ok"] is True
    assert out["upgrade"]["nothing_to_do"] is True


# --- held steps -------------------------------------------------------------------


def test_a_held_step_needs_a_green_bulk(host):
    out = host.run(step="postgres", rc=3)
    assert any("holds no bulk step" in r for r in out["refused"])


def test_held_steps_release_only_their_own_holds_and_showhold_ends_as_recorded(host):
    host.owner_holds = ["nginx"]
    host.run()
    assert host.holds() == ["libpq5", "nginx", "postgresql-16", "redis-server"]
    out = host.run(step="postgres")
    assert out["holds"]["released"] == ["postgresql-16", "libpq5"]
    assert host.holds() == ["nginx", "redis-server"]
    assert out["next"][0].startswith("bash apply.sh --approve --step redis")
    out = host.run(step="redis")
    assert out["verdict"]["ok"] is True
    assert host.holds() == ["nginx"]
    assert out["next"] == ["the reboot decision: run.md section 4"]
    unholds = [a for _, a, _ in host.calls("apt-mark") if a.startswith("unhold")]
    assert unholds == ["unhold postgresql-16 libpq5", "unhold redis-server"]
    assert not [a for _, a, _ in host.calls("apt-mark") if "nginx" in a]
    out = host.run(step="redis", rc=3)
    assert any("already ran" in r for r in out["refused"])


def test_a_held_step_stops_its_restarters_around_the_restart_and_polls_health(host):
    host.run()
    out = host.run(step="postgres")
    changed = _changed(host)
    # Stopped, then released, then upgraded, then started again.
    i = changed.index("systemctl stop -- app-healthcheck.timer")
    assert changed[i + 1 : i + 4] == [
        "apt-mark unhold postgresql-16 libpq5",
        "unattended-upgrade -v",
        "systemctl start -- app-healthcheck.timer",
    ]
    assert out["restarters"] == [
        {"unit": "app-healthcheck.timer", "before": "active", "left_stopped": False}
    ]
    assert out["health"]["passed"] is True
    assert out["health"]["polls"] == 2
    log = host.record("postgres-health.log").splitlines()
    assert len(log) == 2
    assert all(line.endswith(" line 4 exit 0") for line in log)
    assert all(line[:4] == "2026" for line in log)


def test_a_restart_the_health_checks_never_pass_leaves_the_restarters_stopped(host):
    host.run()
    host.cases["curl"] = []
    host.on("curl", "*", "", rc=7)
    out = host.run("--health-within", "1", step="postgres", rc=1)
    assert out["health"]["passed"] is False
    assert any("didn't pass twice in a row" in w for w in out["verdict"]["why"])
    assert out["abort"]["restarters_stopped"] == ["app-healthcheck.timer"]
    assert "systemctl start -- app-healthcheck.timer" not in _changed(host)
    assert [h["package"] for h in out["abort"]["holds_left"]] == ["redis-server"]


@pytest.mark.parametrize("fails", ["stop", "unhold"])
def test_a_held_step_that_fails_before_its_upgrade_can_run_again(host, fails):
    # Two restarters: the second won't stop, or the release fails after both
    # have. Either way nothing was upgraded, so the step isn't recorded, the
    # restarters it stopped start again, and the group stays held.
    host.knob(KNOB + "restarter app-watchdog.service\n")
    host.unit("app-watchdog.service")
    host.run()
    green = (list(host.cases["systemctl"]), list(host.cases["apt-mark"]))
    if fails == "stop":
        host.cases["systemctl"].insert(
            0, ("stop -- app-watchdog.service", "", 1, "", None)
        )
    else:
        host.cases["apt-mark"].insert(0, ("unhold *", "", 100, "", None))
    out = host.run(step="postgres", rc=1)
    assert not host.calls("unattended-upgrade")[1:]
    if fails == "stop":
        assert not [a for _, a, _ in host.calls("apt-mark") if a.startswith("unhold")]
    assert "postgres" not in host.record("steps")
    assert host.holds() == ["libpq5", "postgresql-16", "redis-server"]
    assert out["abort"]["instructions"][0].startswith("Nothing was upgraded")
    assert [h["package"] for h in out["abort"]["holds_left"]] == [
        "postgresql-16",
        "libpq5",
        "redis-server",
    ]
    assert out["abort"]["restarters_stopped"] == []
    assert (host.state / "unit.app-healthcheck.timer").read_text() == "active\n"
    # Once it's fixed, the same step runs.
    host.cases["systemctl"], host.cases["apt-mark"] = green
    assert host.run(step="postgres")["verdict"]["ok"] is True


def test_a_restarter_stopped_before_the_step_stays_stopped(host):
    host.unit("app-healthcheck.timer", "inactive")
    host.run()
    out = host.run(step="postgres")
    assert not [c for c in _changed(host) if c.startswith("systemctl")]
    assert out["restarters"][0]["before"] == "inactive"


# --- what it never does -------------------------------------------------------------


def test_a_whole_run_never_unmasks_enables_reboots_removes_or_purges(host):
    host.run()
    host.run(step="postgres")
    host.run(step="redis")
    for name, args, _ in host.calls():
        words = args.split()
        if name == "systemctl":
            assert words[0] in ("is-active", "stop", "start", "show"), args
        if name == "apt-get":
            assert words[0] in ("update", "-s"), args
        if name == "apt-mark":
            assert words[0] in ("hold", "unhold", "showhold", "showauto"), args
        assert name not in ("shutdown", "reboot", "needrestart"), name
    assert host.holds() == []
