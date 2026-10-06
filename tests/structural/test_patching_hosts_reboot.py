"""patching-hosts' reboot chain: `reboot-chain.sh` (#313, plan step 6a).

In the step 0 round each reboot ran as a detached root script, so the
operator's disconnect couldn't cut it off: the gate again, the restarters
and services stopped, a checkpoint and the data store stopped, the journal
copied last, then an in-guest reboot. wslcb's transient timer fired 41 s
late until AccuracySec=1s. reboot-chain.sh writes that script and launches
it; without --approve it prints the chain for the owner to read.

What this file pins, against the plan's step 6a list:

- the chain's order, by running it against the stubs: the gate, each
  restarter then each service, the checkpoint then each data store, the
  journal's sync and copy, then the reboot;
- the abort when the gate fails at the chain's own start, which stops
  nothing;
- the journal copy comes after every stop, and it and the chain's log are
  root's only;
- every value in the chain is single-quoted, since it runs as root: a
  unit's name is the knob's, and Redis's address and a cluster's port come
  from files the redis and postgres users can write;
- no platform restart appears: the chain's one restart is
  `systemctl reboot`, in-guest.

Beyond that list:

- the chain is printed, the knob's inflight commands verbatim, before
  anything is written, and the approved text is the text that runs;
- it's written at 0700 and launched with --on-active and AccuracySec=1s,
  less the time the gate took, so it fires at the time its span was gated
  from;
- it refuses a run that aborted, a chain that's scheduled, running or
  already ran, a span outside a window or into a quiet range, a package
  manager that's running, and work in flight;
- a chain that aborted at its own start stopped nothing, so it goes again;
- the chain refuses to start while a package manager runs, since a reboot
  then could cut dpkg off mid-run;
- a journal copy that fails still reboots: by then the services are down;
- only the volatile journal is copied: a persistent one survives the boot;
- Redis is saved first only when it has no save points, and its password
  stays in its own config file;
- Redis is reached where its unit's own arguments say, over the file's;
- a SAVE Redis refuses is logged, although redis-cli exits 0 on it;
- a running Redis whose address reaches another process refuses: the chain
  would check and save that one;
- its unit is recorded before it's launched, and one it can't record is
  never launched; a launch that fails removes the record (CR 189).
"""

import json
import os
import re
import subprocess

import pytest

from tests.structural.patching_hosts_rig import SKILL, dispatcher
from tests.structural.patching_hosts_rig import clean_env as _clean_env
from tests.structural.test_patching_hosts_apply import KNOB, MIN, TUE_1530
from tests.structural.test_patching_hosts_apply import Host as ApplyHost

CHAIN = SKILL / "scripts" / "reboot-chain.sh"
STAMP = "20260929T153000Z"
CLUSTER = (
    "16 main 5432 online postgres /var/lib/postgresql/16/main "
    "/var/log/postgresql/postgresql-16-main.log\n"
)


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


class Host(ApplyHost):
    STUBBED = (*ApplyHost.STUBBED, "pgrep", "cp", "sync")
    FALLBACKS = {
        **ApplyHost.FALLBACKS,
        "runuser": 'while [ "$#" -gt 0 ] && [ "$1" != -- ]; do shift; done; shift; exec "$@"',
        # Nothing is running, unless a case says so.
        "pgrep": "exit 1",
        "cp": 'exec /bin/cp "$@"',
        "sync": "exit 0",
    }

    def reboot(
        self, *args: str, rc: int = 0, approve: bool = True, took: int = 0
    ) -> dict:
        # The clock reads TOOK seconds on after its first read: the gate's
        # own time.
        read = self.state / "clock-read"
        read.unlink(missing_ok=True)
        self.cases["date"] = [
            (
                "+%s",
                "",
                0,
                "",
                f'if [ -e "{read}" ]; then echo {self.clock + took}; '
                f'else : > "{read}"; echo {self.clock}; fi; exit 0',
            )
        ]
        cmd = ["bash", str(self.scripts / "reboot-chain.sh")]
        cmd += ["--run", str(self.run_dir), "--config", str(self.knob_path)]
        cmd += ["--host", "web-1", "--today", "2026-09-29"]
        if approve:
            cmd.append("--approve")
        self.execute([*cmd, *args], rc)
        return json.loads(self.result.stdout)

    def fire(self, journals: list[str]) -> subprocess.CompletedProcess:
        """Run the launched chain against the stubs, as systemd-run would,
        with JOURNALS in place of the host's journal directories."""
        script = self.run_dir / "reboot-chain.sh"
        text = script.read_text()
        line = "JOURNAL_DIRS='/run/log/journal'"
        assert text.count(line) == 1
        script.write_text(text.replace(line, f"JOURNAL_DIRS='{' '.join(journals)}'"))
        self.log.write_text("")
        self._write_stubs()
        env = _clean_env()
        env["PATH"] = f"{self.bin}:{self._system_path()}"
        env["STUB_LOG"] = str(self.log)
        env["STUB_CASES"] = str(self.tmp / "cases")
        r = subprocess.run(
            ["sh", str(script)], capture_output=True, text=True, env=env, timeout=60
        )
        self.result = r
        return r

    def sequence(self) -> list[str]:
        keep = (
            "pgrep",
            "runuser",
            "systemctl",
            "redis-cli",
            "journalctl",
            "cp",
            "sync",
        )
        return [f"{n} {a}" for n, a, _ in self.calls() if n in keep]


KNOB_CHAIN = (
    KNOB
    + "service app-web\n"
    + "inflight echo 0\n"
    + "datastore postgres postgresql@16-main app\n"
    + "datastore redis redis-server\n"
)


def _ready(host: Host, save: str = "3600 1 300 100") -> Host:
    host.knob(KNOB_CHAIN)
    host.run_dir.mkdir()
    host.run_dir.chmod(0o700)
    host.on("pg_lsclusters", "-h", CLUSTER)
    conf = host.tmp / "redis.conf"
    conf.write_text("port 6380\nrequirepass pw-in-the-file\n")
    host.show(
        "redis-server.service",
        ExecStart=f"{{ path=/usr/bin/redis-server ; argv[]=/usr/bin/redis-server {conf} ; }}",
        MainPID="4242",
    )
    host.on("redis-cli", "* INFO server", "# Server\r\nprocess_id:4242\r\n")
    s = host.state
    host.on(
        "redis-cli",
        "* CONFIG GET save",
        script=f'echo "${{REDISCLI_AUTH:-}}" >> "{s}/auth"; printf "save\\n{save}\\n"; exit 0',
    )
    host.on("redis-cli", "* SAVE", "OK\n")
    host.on("psql", "*CHECKPOINT", "")
    host.on("journalctl", "*", "")
    host.on("systemctl", "stop -- *", "")
    host.on("systemctl", "reboot", "")
    host.on("systemd-run", "*", "")
    return host


@pytest.fixture
def host(tmp_path) -> Host:
    return _ready(Host(tmp_path))


def _journals(host: Host) -> list[str]:
    src = host.tmp / "journal-src" / "run"
    (src / "abc123").mkdir(parents=True)
    (src / "abc123" / "system.journal").write_text("journal")
    os.chmod(src / "abc123" / "system.journal", 0o640)
    return [str(src), str(host.tmp / "journal-src" / "empty")]


# --- the command line -------------------------------------------------------------


def test_help_names_the_chain_and_the_exit_codes():
    r = subprocess.run(
        ["bash", str(CHAIN), "--help"], capture_output=True, text=True, env=_clean_env()
    )
    assert r.returncode == 0
    for word in (
        # What's left of the delay once the gate has run (step 8).
        "--on-active=<left>",
        "--timer-property=AccuracySec=1s",
        "systemctl reboot",
        "a platform restart is a",
        "  3  refused",
    ):
        assert word in r.stdout, word


@pytest.mark.parametrize(
    "args, message",
    [
        ([], "--run DIR is required"),
        (["--run", "rel/dir"], "absolute path"),
        (["--run", "/x", "--delay", "0"], "--delay and --expect"),
    ],
)
def test_usage_errors_exit_2(args, message):
    r = subprocess.run(
        ["bash", str(CHAIN), *args], capture_output=True, text=True, env=_clean_env()
    )
    assert r.returncode == 2
    assert message in r.stderr


# --- the chain as approved --------------------------------------------------------


def test_without_approve_it_prints_the_chain_and_writes_nothing(host):
    out = host.reboot(approve=False, rc=3)
    assert any("no --approve" in r for r in out["refused"])
    chain = out["chain"]
    assert chain[0] == "#!/bin/sh"
    # The inflight command verbatim, run as the invoking user, never root.
    assert "# knob line 7: echo 0" in chain
    assert any(
        line.startswith("out=$(runuser -u 'exedev' -- timeout -k 10 60 sh -c 'echo 0'")
        for line in chain
    )
    assert not (host.run_dir / "reboot-chain.sh").exists()
    assert not host.calls("systemd-run")
    # The password stays in Redis's own file.
    assert "pw-in-the-file" not in host.result.stdout + host.result.stderr


def test_the_chains_one_restart_is_an_in_guest_reboot(host):
    chain = host.reboot(approve=False, rc=3)["chain"]
    commands = [line for line in chain if line and not line.startswith("#")]
    assert commands[-1] == "systemctl reboot"
    # Command words only: what the chain says in its log is quoted.
    text = "\n".join(
        re.sub(r"""say ("[^"]*"|'[^']*')""", 'say ""', line) for line in commands
    )
    for word in (
        "ssh ",
        "exe ",
        "curl",
        "shutdown",
        "poweroff",
        "halt",
        "kexec",
        "sysrq",
    ):
        assert word not in text, word
    # The word, not the chain's own file names.
    assert re.findall(r".{0,10}\breboot\b(?!-)", text) == [
        "say reboot",
        "systemctl reboot",
    ]


def test_approved_it_writes_the_chain_at_0700_and_launches_it_detached(host):
    out = host.reboot()
    script = host.run_dir / "reboot-chain.sh"
    assert oct(script.stat().st_mode & 0o777) == "0o700"
    # The approved text is the text that runs.
    assert script.read_text() == "\n".join(out["chain"]) + "\n"
    [launch] = [a for _, a, _ in host.calls("systemd-run")]
    assert launch == (
        f"--unit=patching-hosts-reboot-{STAMP} --on-active=120 "
        f"--timer-property=AccuracySec=1s {script}"
    )
    assert out["launched"]["fires_at"] == "2026-09-29T15:32:00Z"
    assert host.record("reboot-chain.unit") == (
        f"patching-hosts-reboot-{STAMP} 2026-09-29T15:32:00Z\n"
    )
    assert any("--post-boot" in n for n in out["next"])


def test_the_chain_fires_at_the_time_its_span_was_gated_from(host):
    # The inflight commands took 30 s: the timer gets the 90 s left.
    out = host.reboot(took=30)
    [launch] = [a for _, a, _ in host.calls("systemd-run")]
    assert " --on-active=90 " in launch
    assert out["launched"]["on_active_seconds"] == 90
    assert out["launched"]["fires_at"] == "2026-09-29T15:32:00Z"


def test_a_gate_that_takes_the_whole_delay_schedules_nothing(host):
    out = host.reboot(took=120, rc=1)
    assert not host.calls("systemd-run")
    assert any("the whole --delay of 120 s" in w for w in out["launched"]["why"])
    assert out["launched"]["fires_at"] is None
    assert not (host.run_dir / "reboot-chain.unit").exists()


def test_a_launch_that_fails_schedules_nothing(host):
    host.cases["systemd-run"] = [
        ("*", "", 1, "Failed to start transient timer unit\n", None)
    ]
    out = host.reboot(rc=1)
    assert out["launched"]["exit"] == 1
    assert out["launched"]["fires_at"] is None
    assert not (host.run_dir / "reboot-chain.unit").exists()


def test_a_chain_it_cant_record_is_never_launched(host):
    # CR 189: recorded after the launch, a failed record left a scheduled
    # reboot behind an exit 1 that says nothing is, and out of the
    # earlier-chain gate's sight.
    (host.run_dir / "reboot-chain.unit").mkdir()
    out = host.reboot(rc=1)
    assert not host.calls("systemd-run")
    assert out["launched"]["fires_at"] is None
    assert any(
        "reboot-chain.unit couldn't be written: nothing is scheduled" in w
        for w in out["launched"]["why"]
    )


# --- refusals ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "setup, refused",
    [
        (
            lambda h: (h.run_dir / "steps").write_text(
                "bulk\tok\t1\t1\t1\npostgres\tfailed\t2\t1\t1\n"
            ),
            "the run aborted at postgres",
        ),
        (
            lambda h: (
                (h.run_dir / "reboot-chain.unit").write_text(
                    "x 2026-09-29T15:00:00Z\n"
                ),
                h.on("systemctl", "is-active -- x.timer", "active\n"),
            ),
            "this run's chain, x.timer, is active",
        ),
        # Fired, and stopping services: its timer has elapsed.
        (
            lambda h: (
                (h.run_dir / "reboot-chain.unit").write_text(
                    "x 2026-09-29T15:00:00Z\n"
                ),
                h.on("systemctl", "is-active -- x.service", "active\n"),
            ),
            "this run's chain, x.service, is active",
        ),
        (
            lambda h: (
                (h.run_dir / "reboot-chain.unit").write_text(
                    "x 2026-09-29T15:00:00Z\n"
                ),
                (h.run_dir / "reboot-chain.log").write_text(
                    "2026-09-29T15:02:00Z start\n2026-09-29T15:02:09Z reboot\n"
                ),
            ),
            "ran and didn't end in ABORT",
        ),
        # 120 s of delay and 600 s of boot from 20:55 end at 21:07.
        (
            lambda h: setattr(h, "clock", TUE_1530 + 5 * 3600 + 25 * MIN),
            "isn't wholly inside one window",
        ),
        (
            lambda h: h.knob(KNOB_CHAIN + "quiet 15:35-15:40\n"),
            "runs into the quiet range 15:35-15:40",
        ),
        (
            lambda h: h.knob(KNOB_CHAIN.replace("inflight echo 0", "inflight echo 3")),
            'printed "3", not 0',
        ),
        (lambda h: h.on("pgrep", "-x *", "4242\n"), "dpkg or apt is running"),
        (lambda h: h.on("pgrep", "-f *", "4243\n"), "unattended-upgrade is running"),
        (lambda h: h.run_dir.rmdir(), "doesn't exist"),
        (
            lambda h: h.knob(KNOB_CHAIN + "class ephemeral\n"),
            "report-only: class ephemeral",
        ),
        (lambda h: h.cases["pg_lsclusters"].clear(), "pg_lsclusters couldn't be read"),
        # From postgresql.conf, which postgres can write: the chain is root's.
        (
            lambda h: (
                h.cases["pg_lsclusters"].clear(),
                h.on("pg_lsclusters", "-h", CLUSTER.replace(" 5432 ", " 5432;id ")),
            ),
            "port, 5432;id, isn't a number",
        ),
    ],
    ids=[
        "the-run-aborted",
        "already-scheduled",
        "already-running",
        "already-ran",
        "past-the-window",
        "into-a-quiet-range",
        "work-in-flight",
        "dpkg-running",
        "unattended-upgrade-running",
        "no-run",
        "report-only",
        "no-cluster",
        "a-port-that-isnt-a-number",
    ],
)
def test_a_chain_it_shouldnt_launch_is_refused(host, setup, refused):
    setup(host)
    out = host.reboot(rc=3)
    assert any(refused in r for r in out["refused"]), out["refused"]
    assert not host.calls("systemd-run")


# --- the chain, run ---------------------------------------------------------------


def test_the_chain_runs_in_order_and_copies_the_journal_after_every_stop(host):
    host.reboot()
    r = host.fire(_journals(host))
    assert r.returncode == 0, r.stderr
    seq = host.sequence()
    stops = [i for i, c in enumerate(seq) if c.startswith("systemctl stop -- ")]
    assert [seq[i] for i in stops] == [
        "systemctl stop -- app-healthcheck.timer",
        "systemctl stop -- app-web.service",
        "systemctl stop -- postgresql@16-main.service",
        "systemctl stop -- redis-server.service",
    ]
    # The gate first: no package manager, then the inflight read.
    assert seq[0].startswith("pgrep -x dpkg|apt|apt-get")
    assert seq[2] == "runuser -u exedev -- timeout -k 10 60 sh -c echo 0"
    assert (
        seq.index("runuser -u postgres -- psql -XAtq -p 5432 -d postgres -c CHECKPOINT")
        < stops[2]
    )
    sync = seq.index("journalctl --sync")
    copy = next(i for i, c in enumerate(seq) if c.startswith("cp -a "))
    assert stops[-1] < sync < copy
    assert seq[-2:] == ["sync ", "systemctl reboot"]
    # The copy is root's only: no group or other bits.
    copied = (
        host.run_dir
        / "journal"
        / str(host.tmp / "journal-src" / "run").replace("/", "_")
    )
    f = copied / "abc123" / "system.journal"
    assert f.read_text() == "journal"
    assert f.stat().st_mode & 0o077 == 0
    assert oct((host.run_dir / "journal").stat().st_mode & 0o777) == "0o700"
    log = host.record("reboot-chain.log")
    # It holds the read-back's journal lines.
    assert (host.run_dir / "reboot-chain.log").stat().st_mode & 0o077 == 0
    assert "gate passed" in log
    assert "and read back" in log
    assert "holds no journal: a persistent one survives the boot" in log
    assert log.rstrip().endswith("reboot")


def test_no_value_reaches_the_chain_unquoted(host):
    # A unit's name is the knob's, and Redis's address its own config
    # file's, which the redis user can write. The chain runs as root, so a
    # $( ) in either would too.
    mark = host.tmp / "ran"
    host.knob(KNOB_CHAIN + f"service app-$(id>{mark}-unit)\n")
    (host.tmp / "redis.conf").write_text(f"bind 127.0.0.1;id>{mark}-bind\nport 6380\n")
    host.reboot()
    r = host.fire(_journals(host))
    assert r.returncode == 0, r.stderr
    assert not list(host.tmp.glob("ran-*"))
    seq = host.sequence()
    assert f"systemctl stop -- app-$(id>{mark}-unit).service" in seq
    assert f"redis-cli -h 127.0.0.1;id>{mark}-bind -p 6380 CONFIG GET save" in seq


def test_a_chain_whose_gate_fails_at_its_start_stops_nothing(host):
    count = host.tmp / "in-flight"
    count.write_text("0\n")
    host.knob(KNOB_CHAIN.replace("inflight echo 0", f"inflight cat {count}"))
    host.reboot()
    # Work arrived between the launch and the chain's start.
    count.write_text("3\n")
    r = host.fire(_journals(host))
    assert r.returncode == 1
    assert not [c for c in host.sequence() if c.startswith("systemctl")]
    log = host.record("reboot-chain.log")
    assert "printed: 3. Nothing was stopped." in log


def test_a_chain_that_aborted_goes_again_once_the_gate_passes(host):
    host.reboot()
    host.on("pgrep", "-f *", "4243\n")
    host.fire(_journals(host))
    assert "ABORT: a package manager is running" in host.record("reboot-chain.log")
    # It stopped nothing: once the package manager is done, it goes again.
    host.cases["pgrep"].clear()
    host.clock += 5 * MIN
    out = host.reboot()
    assert out["refused"] == []
    assert out["gate"]["earlier_chain"]["last_line"].endswith("Nothing was stopped.")
    [launch] = [a for _, a, _ in host.calls("systemd-run")]
    assert launch.startswith("--unit=patching-hosts-reboot-20260929T153500Z ")
    assert host.record("reboot-chain.unit").startswith(
        "patching-hosts-reboot-20260929T153500Z "
    )


def test_a_chain_refuses_to_start_while_a_package_manager_runs(host):
    host.reboot()
    host.on("pgrep", "-f *", "4243\n")
    r = host.fire(_journals(host))
    assert r.returncode == 1
    assert not [c for c in host.sequence() if c.startswith("systemctl")]
    assert "ABORT: a package manager is running" in host.record("reboot-chain.log")


def test_only_the_volatile_journal_is_copied(host):
    # A persistent journal survives the boot, and a copy of it, up to
    # journald's 4 GiB cap, would land on the disk the data stores boot from.
    chain = host.reboot(approve=False, rc=3)["chain"]
    assert "JOURNAL_DIRS='/run/log/journal'" in chain
    assert not [
        line
        for line in chain
        if "/var/log/journal" in line and not line.startswith("#")
    ]


def test_a_journal_copy_that_fails_still_reboots(host):
    host.reboot()
    host.on("cp", "*", "", rc=1)
    r = host.fire(_journals(host))
    assert r.returncode == 0
    assert host.sequence()[-1] == "systemctl reboot"
    assert "has no record of its own" in host.record("reboot-chain.log")


@pytest.mark.parametrize(
    "args, words",
    [
        ("--port 6391", "-h '127.0.0.1' -p '6391'"),
        ("--unixsocket /run/redis/cache.sock", "-s '/run/redis/cache.sock'"),
    ],
)
def test_redis_is_reached_where_its_units_own_arguments_say(host, args, words):
    # Redis takes them over its file's: a second Redis may share the file.
    conf = host.tmp / "redis.conf"
    host.cases["systemctl"] = [
        c for c in host.cases["systemctl"] if "redis-server.service" not in c[0]
    ]
    host.show(
        "redis-server.service",
        ExecStart=f"{{ path=/usr/bin/redis-server ; argv[]=/usr/bin/redis-server {conf} {args} ; }}",
    )
    chain = host.reboot(approve=False, rc=3)["chain"]
    assert any(f"redis-cli {words} CONFIG GET save" in line for line in chain)


@pytest.mark.parametrize(
    "line",
    [
        "requirepass {pw}",
        'requirepass "{pw}"',
        "requirepass '{pw}'",
        "requirepass {pw}   ",
    ],
    ids=["plain", "double-quoted", "single-quoted", "trailing-space"],
)
def test_the_chain_reads_the_password_as_redis_does(host, line):
    # Measured on Redis 7.0: each form sets the same password.
    conf = "port 6380\n" + line.format(pw="pw-in-the-file") + "\n"
    (host.tmp / "redis.conf").write_text(conf)
    host.reboot()
    host.fire(_journals(host))
    assert (host.state / "auth").read_text().split("\n") == ["pw-in-the-file", ""]


def test_a_save_that_took_isnt_logged_as_failed_for_an_auth_warning(tmp_path):
    host = _ready(Host(tmp_path), save="")
    # The file sets a password the server doesn't: redis-cli warns on
    # stderr, and the reply on stdout is OK (measured on 7.0).
    host.cases["redis-cli"] = [c for c in host.cases["redis-cli"] if c[0] != "* SAVE"]
    host.on(
        "redis-cli",
        "* SAVE",
        "OK\n",
        0,
        "AUTH failed: ERR AUTH <password> called without any password configured for the default user.\n",
    )
    host.reboot()
    host.fire(_journals(host))
    log = host.record("reboot-chain.log")
    assert "AUTH failed" in log
    assert "SAVE failed" not in log


def test_a_redis_with_no_file_gets_no_other_redis_password(host):
    host.knob(KNOB_CHAIN + "datastore redis redis-cache\n")
    host.show(
        "redis-cache.service",
        ExecStart="{ path=/usr/bin/redis-server ; argv[]=/usr/bin/redis-server --port 6390 ; }",
    )
    host.reboot()
    host.fire(_journals(host))
    # The first Redis's CONFIG GET with its file's password, the second's
    # with none.
    assert (host.state / "auth").read_text().split("\n") == ["pw-in-the-file", "", ""]


@pytest.mark.parametrize(
    "answer, refused",
    [("process_id:999\r\n", True), ("process_id:4242\r\n", False)],
    ids=["another-redis", "its-own"],
)
def test_a_redis_address_that_reaches_another_process_is_refused(host, answer, refused):
    host.cases["redis-cli"] = [
        c for c in host.cases["redis-cli"] if c[0] != "* INFO server"
    ]
    host.on("redis-cli", "* INFO server", answer)
    out = host.reboot(rc=3 if refused else 0)
    hit = any("reaches process 999" in r for r in out["refused"])
    assert hit is refused, out["refused"]


def test_a_redis_that_isnt_running_has_nothing_to_save(host):
    host.cases["systemctl"] = [
        c for c in host.cases["systemctl"] if "redis-server.service" not in c[0]
    ]
    host.show("redis-server.service", MainPID="0")
    assert host.reboot()["refused"] == []


def test_the_chain_reads_a_key_in_any_case_after_leading_space(host):
    # Redis takes both (measured on 7.0).
    (host.tmp / "redis.conf").write_text("  Port 6380\n  REQUIREPASS pw-in-the-file\n")
    host.reboot()
    host.fire(_journals(host))
    assert "redis-cli -h 127.0.0.1 -p 6380 CONFIG GET save" in host.sequence()
    assert (host.state / "auth").read_text().split("\n") == ["pw-in-the-file", ""]


def test_a_save_redis_refuses_is_logged(tmp_path):
    host = _ready(Host(tmp_path), save="")
    # An error reply, on which redis-cli exits 0 (measured on 7.0).
    host.cases["redis-cli"] = [c for c in host.cases["redis-cli"] if c[0] != "* SAVE"]
    host.on("redis-cli", "* SAVE", "NOAUTH Authentication required.\n")
    host.reboot()
    r = host.fire(_journals(host))
    assert r.returncode == 0, r.stderr
    assert "SAVE failed: NOAUTH Authentication required." in host.record(
        "reboot-chain.log"
    )
    # The stop goes on: the boot would stop it anyway.
    assert "systemctl stop -- redis-server.service" in host.sequence()


@pytest.mark.parametrize("save, saved", [("3600 1 300 100", False), ("", True)])
def test_redis_is_saved_first_only_without_save_points(tmp_path, save, saved):
    host = _ready(Host(tmp_path), save=save)
    host.reboot()
    host.fire(_journals(host))
    calls = [c for c in host.sequence() if c.startswith("redis-cli")]
    assert calls[0] == "redis-cli -h 127.0.0.1 -p 6380 CONFIG GET save"
    assert ("redis-cli -h 127.0.0.1 -p 6380 SAVE" in calls) is saved
    # Read from its own file when the chain runs, not written into it.
    assert (host.state / "auth").read_text().split() == ["pw-in-the-file"]
    assert "pw-in-the-file" not in (host.run_dir / "reboot-chain.sh").read_text()
