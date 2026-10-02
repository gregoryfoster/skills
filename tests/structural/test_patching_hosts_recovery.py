"""patching-hosts' recovery point: `recovery-point.sh` (#313, plan step 6a).

In the step 0 round each data-store host's dump was taken by hand, as root
at mode 600 because a `>` from the session shell can't write under
/var/backups, and checked three ways: the pipeline's exit status, the
table of contents, and a full read, since a custom-format dump cut off after
its table of contents still lists. watcher's own backup regime stood in for
a dump. recovery-point.sh is that, as a script, writing the record apply.sh's
bulk reads.

What this file pins, against the plan's step 6a list:

- each dump's mode, 600, and that it's written as root, by root's own sh,
  with pg_dump running as postgres;
- the roles (`pg_dumpall --globals-only`) written at mode 600, recorded as
  `local`, and never asked for an off-node attestation;
- a dump that lists but fails a full read fails the gate, and nothing is
  recorded;
- each dump's sha256, printed for the owner's off-node copy, and recorded;
- the backup regime preferred where the knob declares one that succeeded,
  started now, and recorded in place of every dump;
- the record it writes is one apply.sh's bulk accepts.

Beyond that list:

- a stated retention is required, and recorded;
- a dump that holds personal data is flagged in the record;
- Redis is reached at the address and port its own config file binds, and
  its password, where the file sets one, never reaches an argv or the
  output;
- a run's filesystem with less free space than the data refuses: a full
  disk mid-dump can stop the data store it shares the disk with.

Each case runs from a copy of the skill's scripts, with probe.sh replaced
by a stub, through the apply tests' host.
"""

import hashlib
import json
import subprocess

import pytest

from tests.structural.patching_hosts_rig import SKILL, dispatcher
from tests.structural.patching_hosts_rig import clean_env as _clean_env
from tests.structural.test_patching_hosts_apply import KNOB, TUE_1530, _changed, _ready
from tests.structural.test_patching_hosts_apply import Host as ApplyHost

RECOVER = SKILL / "scripts" / "recovery-point.sh"
RETAIN = "2026-10-29"
STAMP = "20260929T153000Z"
PG = KNOB + "datastore postgres postgresql@16-main app\n"
CLUSTER = (
    "16 main 5432 online postgres /var/lib/postgresql/16/main "
    "/var/log/postgresql/postgresql-16-main.log\n"
)


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


class Host(ApplyHost):
    STUBBED = (
        *ApplyHost.STUBBED,
        "pg_dump",
        "pg_dumpall",
        "pg_restore",
        "redis-check-rdb",
        "sha256sum",
        "df",
        "stat",
    )
    FALLBACKS = {
        **ApplyHost.FALLBACKS,
        # runuser runs its command, after its options.
        "runuser": 'while [ "$#" -gt 0 ] && [ "$1" != -- ]; do shift; done; shift; exec "$@"',
        "sha256sum": (
            "for x in /usr/bin/sha256sum /sbin/sha256sum; do "
            '[ -x "$x" ] && exec "$x" "$@"; done; exec shasum -a 256 "$@"'
        ),
        "df": 'exec /bin/df "$@"',
        "stat": 'exec /usr/bin/stat "$@"',
    }

    def recover(self, *args: str, rc: int = 0, approve: bool = True) -> dict:
        self.cases["date"] = [("+%s", f"{self.clock}\n", 0, "", None)]
        cmd = ["bash", str(self.scripts / "recovery-point.sh")]
        cmd += ["--run", str(self.run_dir), "--config", str(self.knob_path)]
        cmd += ["--host", "web-1", "--today", "2026-09-29"]
        cmd += ["--retain-until", RETAIN]
        if approve:
            cmd.append("--approve")
        self.execute([*cmd, *args], rc)
        return json.loads(self.result.stdout)

    def dump_path(self, db: str = "app") -> str:
        return f"{self.run_dir}/postgresql@16-main-{db}-{STAMP}.dump"


def _postgres(host: Host) -> Host:
    host.knob(PG)
    host.on("pg_lsclusters", "-h", CLUSTER)
    host.on(
        "psql",
        "*-v db=app",
        script=f'cat > "{host.state}/psql.in"; echo 1048576; exit 0',
    )
    host.on("pg_dump", "-Fc -p 5432 -d app", "PGDMP app-data\n")
    host.on("pg_dumpall", "--globals-only -p 5432", "CREATE ROLE app;\n")
    host.on("pg_restore", "--list -- *", "")
    host.on("pg_restore", "-f /dev/null -- *", "")
    return host


@pytest.fixture
def host(tmp_path) -> Host:
    return _postgres(_ready(Host(tmp_path)))


def _sha(path) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


# --- the command line -------------------------------------------------------------


def test_help_names_the_gates_and_the_record():
    r = subprocess.run(
        ["bash", str(RECOVER), "--help"],
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    assert r.returncode == 0
    for word in (
        "--retain-until",
        "--personal-data",
        "pg_restore --list",
        "pg_restore -f /dev/null",
        "--globals-only",
        "BGSAVE",
        "  3  refused",
    ):
        assert word in r.stdout, word


@pytest.mark.parametrize(
    "args, message",
    [
        ([], "--retain-until is required"),
        (["--retain-until", "next month"], "takes a date"),
        (["--retain-until", RETAIN, "--run", "rel/dir"], "absolute path"),
        (["--retain-until", RETAIN, "--redis-within", "0"], "--redis-within"),
    ],
)
def test_usage_errors_exit_2(args, message):
    r = subprocess.run(
        ["bash", str(RECOVER), *args], capture_output=True, text=True, env=_clean_env()
    )
    assert r.returncode == 2
    assert message in r.stderr


# --- refusals ---------------------------------------------------------------------


def test_without_approve_it_refuses_and_writes_nothing(host):
    out = host.recover(approve=False, rc=3)
    assert any("no --approve" in r for r in out["refused"])
    # The name reaches psql as a variable, in a query on stdin: psql never
    # substitutes one in -c's string.
    assert ":'db'" in (host.state / "psql.in").read_text()
    # The gate still reads, so the owner sees what would be dumped.
    assert out["gate"]["datastores"] == [
        {"datastore": "postgres postgresql@16-main.service app", "bytes": 1048576}
    ]
    assert not host.run_dir.exists()
    assert not host.calls("pg_dump")


@pytest.mark.parametrize(
    "setup, refused",
    [
        (lambda h: h.knob(KNOB), "declares no datastore"),
        (lambda h: h.knob(PG + "class ephemeral\n"), "report-only: class ephemeral"),
        (
            lambda h: h.knob(PG.replace("16-main", "15-main")),
            "the host has no cluster 15/main",
        ),
        (
            lambda h: h.knob(PG.replace("postgresql@16-main", "postgresql")),
            None,
        ),
        (lambda h: h.cases["psql"].clear(), "database app isn't in the cluster"),
        (
            lambda h: h.on(
                "df",
                "-Pk -- *",
                "Filesystem 1024-blocks Used Available\n/dev/vda1 10 9 1\n",
            ),
            "KiB free, and the data would take up to 1024 KiB",
        ),
    ],
    ids=[
        "no-datastore",
        "report-only",
        "no-such-cluster",
        "the-umbrella-unit-with-one-cluster",
        "no-such-database",
        "too-little-space",
    ],
)
def test_a_recovery_point_it_cant_take_is_refused(host, setup, refused):
    setup(host)
    if refused is None:
        assert host.recover()["verdict"]["ok"] is True
        return
    out = host.recover(rc=3)
    assert any(refused in r for r in out["refused"]), out["refused"]
    assert not host.calls("pg_dump")


def test_the_umbrella_unit_on_a_host_with_two_clusters_is_refused(host):
    host.knob(KNOB + "datastore postgres postgresql app\n")
    host.cases["pg_lsclusters"] = []
    host.on(
        "pg_lsclusters", "-h", CLUSTER + CLUSTER.replace("16 main 5432", "15 main 5433")
    )
    out = host.recover(rc=3)
    assert any("names no cluster, and the host has 2" in r for r in out["refused"])


def test_a_recovery_point_after_the_bulk_started_is_refused(host):
    host.run_dir.mkdir()
    host.run_dir.chmod(0o700)
    (host.run_dir / "holds").write_text("")
    out = host.recover(rc=3)
    assert any("bulk already started" in r for r in out["refused"])


@pytest.mark.parametrize(
    "name, refused",
    [
        ("billing", "--personal-data billing names no"),
        # Its dumps are per database, so it's flagged by database.
        ("postgresql@16-main", "--personal-data postgresql@16-main is a Postgres unit"),
    ],
)
def test_personal_data_must_name_a_declared_datastore(host, name, refused):
    out = host.recover("--personal-data", name, rc=3)
    assert any(refused in r for r in out["refused"]), out["refused"]


# --- the dumps --------------------------------------------------------------------


def test_a_dump_is_written_as_root_at_600_and_recorded_with_its_sha256(host):
    out = host.recover("--personal-data", "app")
    assert out["verdict"] == {"ok": True, "why": []}
    [d] = out["dumps"]
    path = host.dump_path()
    assert d["path"] == path
    assert (d["pg_dump_exit"], d["list_exit"], d["full_read_exit"]) == (0, 0, 0)
    assert d["mode"] == "0600"
    assert oct(host.run_dir.stat().st_mode & 0o777) == "0o700"
    assert open(path).read() == "PGDMP app-data\n"
    assert d["sha256"] == _sha(path)
    assert d["personal_data"] is True
    # pg_dump ran as postgres, under root's sh: the file was root's from
    # creation, never written through a session shell's `>`.
    runs = [a for _, a, _ in host.calls("runuser")]
    assert "-u postgres -- pg_dump -Fc -p 5432 -d app" in runs
    roles = f"{host.run_dir}/postgresql@16-main-globals-{STAMP}.sql"
    assert host.record("recovery-point") == (
        f"began {TUE_1530}\n"
        f"retain {RETAIN}\n"
        f"dump postgres postgresql@16-main.service app {d['sha256']} {path}\n"
        f"local {roles}\n"
        f"personal {path}\n"
    )
    assert oct((host.run_dir / "recovery-point").stat().st_mode & 0o777) == "0o600"


def test_the_roles_stay_on_the_node_at_600_and_are_never_attested(host):
    out = host.recover()
    [g] = out["local"]
    assert g["mode"] == "0600"
    assert g["path"].endswith(f"postgresql@16-main-globals-{STAMP}.sql")
    assert open(g["path"]).read() == "CREATE ROLE app;\n"
    # Recorded as local: apply.sh never asks for an attestation of it.
    assert f"local {g['path']}\n" in host.record("recovery-point")
    assert "globals" not in json.dumps(out["dumps"])
    assert not any("globals" in n for n in out["next"])


def test_a_dump_that_lists_but_fails_a_full_read_records_nothing(host):
    # A custom-format dump written to a pipe puts its table of contents
    # first: cut off mid-data, it still lists.
    host.cases["pg_restore"] = [
        ("--list -- *", "", 0, "", None),
        (
            "-f /dev/null -- *",
            "",
            1,
            "pg_restore: error: could not read input file\n",
            None,
        ),
    ]
    out = host.recover(rc=1)
    [d] = out["dumps"]
    assert (d["list_exit"], d["full_read_exit"], d["ok"]) == (0, 1, False)
    assert d["sha256"] is None
    assert any("a full read fails" in w for w in out["verdict"]["why"])
    assert not (host.run_dir / "recovery-point").exists()
    assert out["next"][0].startswith("Nothing was recorded")


@pytest.mark.parametrize(
    "case, why",
    [
        ("unlistable", "pg_restore --list can't read the dump of app"),
        ("mode-644", "is mode 0644, not 0600"),
    ],
)
def test_a_dump_that_fails_another_gate_records_nothing(host, case, why):
    if case == "unlistable":
        host.cases["pg_restore"].insert(0, ("--list -- *", "", 1, "", None))
    else:
        # As stat would read it, on GNU or BSD.
        host.on("stat", "-c %a -- *.dump", "644\n")
    out = host.recover(rc=1)
    assert any(why in w for w in out["verdict"]["why"]), out["verdict"]
    assert out["dumps"][0]["sha256"] is None
    assert not (host.run_dir / "recovery-point").exists()


def test_a_dump_whose_pg_dump_failed_records_nothing(host):
    host.cases["pg_dump"] = [
        ("*", "PGDMP", 1, "pg_dump: error: connection lost\n", None)
    ]
    out = host.recover(rc=1)
    assert any("pg_dump of app" in w and "exited 1" in w for w in out["verdict"]["why"])
    assert out["dumps"][0]["list_exit"] is None
    assert not (host.run_dir / "recovery-point").exists()


def test_the_bulk_accepts_the_record_it_writes(host):
    sha = host.recover("--personal-data", "app")["dumps"][0]["sha256"]
    out = host.run("--offnode-sha256", sha)
    assert out["refused"] == []
    rp = out["gate"]["recovery_point"]
    assert [d["attested"] for d in rp["dumps"]] == [True]
    assert rp["retain_until"] == RETAIN
    assert out["verdict"]["ok"] is True


# --- Redis ------------------------------------------------------------------------


def _redis(
    host: Host, conf: str = "", busy: bool = False, saved: int = 2000, check: int = 0
) -> Host:
    host.knob(KNOB + "datastore redis redis-server\n")
    rdb = host.tmp / "redis" / "dump.rdb"
    rdb.parent.mkdir()
    rdb.write_bytes(b"REDIS0011 data")
    conf_path = host.tmp / "redis.conf"
    conf_path.write_text(conf)
    host.show(
        "redis-server.service",
        ExecStart=f"{{ path=/usr/bin/redis-server ; argv[]=/usr/bin/redis-server {conf_path} ; ignore_errors=no ; }}",
    )
    s = host.state
    auth = f'echo "${{REDISCLI_AUTH:-}}" >> "{s}/auth"; '
    host.on(
        "redis-cli",
        "* CONFIG GET dir",
        script=f'{auth}printf "dir\\n{rdb.parent}\\n"; exit 0',
    )
    host.on(
        "redis-cli",
        "* CONFIG GET dbfilename",
        script=f'{auth}printf "dbfilename\\ndump.rdb\\n"; exit 0',
    )
    host.on("redis-cli", "* LASTSAVE", "1000\n")
    host.on("redis-cli", "* BGSAVE", "Background saving started\n")
    info = (
        "rdb_bgsave_in_progress:1\r\n"
        if busy
        else f"rdb_bgsave_in_progress:0\r\nrdb_last_save_time:{saved}\r\n"
    )
    host.on("redis-cli", "* INFO persistence", info + "rdb_last_bgsave_status:ok\r\n")
    host.on("redis-check-rdb", "*", "", rc=check)
    return host


def test_redis_is_saved_then_copied_at_600_and_recorded(tmp_path):
    host = _redis(_ready(Host(tmp_path)))
    out = host.recover()
    [d] = out["dumps"]
    path = f"{host.run_dir}/redis-server-{STAMP}.rdb"
    assert (d["path"], d["bgsave"], d["copy_exit"], d["check_exit"]) == (
        path,
        "ok",
        0,
        0,
    )
    assert d["mode"] == "0600"
    assert open(path, "rb").read() == b"REDIS0011 data"
    assert f"dump redis redis-server.service {_sha(path)} {path}\n" in host.record(
        "recovery-point"
    )
    # Its default address, with no config file to say otherwise.
    assert [a for _, a, _ in host.calls("redis-cli")][0].startswith(
        "-h 127.0.0.1 -p 6379 "
    )


def test_a_redis_unit_is_flagged_with_or_without_its_suffix(tmp_path):
    host = _redis(_ready(Host(tmp_path)))
    host.knob(KNOB + "datastore redis redis-server.service\n")
    out = host.recover("--personal-data", "redis-server")
    [d] = out["dumps"]
    assert d["personal_data"] is True
    assert f"personal {d['path']}\n" in host.record("recovery-point")


def test_redis_is_reached_where_its_config_binds_and_its_password_stays_hidden(
    tmp_path,
):
    host = _redis(
        _ready(Host(tmp_path)),
        conf="bind 10.1.2.3 -::1\nport 6380\nrequirepass s3cret-pass\n",
    )
    out = host.recover()
    assert out["verdict"]["ok"] is True
    calls = [a for _, a, _ in host.calls("redis-cli")]
    assert calls and all(a.startswith("-h 10.1.2.3 -p 6380 ") for a in calls)
    # In redis-cli's environment, never its argv or the output.
    assert set((host.state / "auth").read_text().split()) == {"s3cret-pass"}
    assert "s3cret" not in host.log.read_text()
    assert "s3cret" not in host.result.stdout + host.result.stderr


@pytest.mark.parametrize(
    "kw",
    [
        {"busy": True},
        # Done, but the save it reports is older than the request: not ours.
        {"saved": 900},
    ],
    ids=["still-saving", "an-old-save"],
)
def test_a_bgsave_that_doesnt_finish_records_nothing(tmp_path, kw):
    host = _redis(_ready(Host(tmp_path)), **kw)
    out = host.recover("--redis-within", "1", rc=1)
    assert any("didn't end ok (timeout)" in w for w in out["verdict"]["why"])
    assert not (host.run_dir / "recovery-point").exists()


# --- the backup regime ------------------------------------------------------------


def _regime(host: Host, last: str = "success", now: str = "success") -> Host:
    """app-backup.timer starts app-backup.service, whose last run ended in
    LAST; a start now ends in NOW."""
    host.knob(PG + "backup app-backup.timer\n")
    host.show("app-backup.timer", Triggers="app-backup.service")
    s = host.state
    state = s / "backup"
    state.write_text(
        f"LoadState=loaded\nResult={last}\nExecMainStartTimestamp=@{TUE_1530 - 86400}\n"
        f"ExecMainExitTimestamp=@{TUE_1530 - 86000}\n"
    )
    host.on("systemctl", "show*-- app-backup.service", script=f'cat "{state}"; exit 0')
    host.on(
        "systemctl",
        "start -- app-backup.service",
        script=(
            f'printf "LoadState=loaded\\nResult={now}\\nExecMainStartTimestamp=@{TUE_1530 + 5}\\n'
            f'ExecMainExitTimestamp=@{TUE_1530 + 65}\\n" > "{state}"; exit 0'
        ),
    )
    return host


def test_the_hosts_own_backup_regime_stands_in_for_the_dumps(host):
    _regime(host)
    out = host.recover()
    assert out["backup"]["unit"] == "app-backup.service"
    assert out["backup"]["ok"] is True
    assert out["dumps"] is None
    assert not host.calls("pg_dump")
    # The roles still stay on the node.
    assert [g["ok"] for g in out["local"]] == [True]
    rec = host.record("recovery-point")
    assert "backup app-backup.service\n" in rec
    assert "dump " not in rec
    assert out["next"][0].startswith("Confirm the object app-backup.service wrote")
    # And the bulk takes it, with the object named.
    out = host.run("--offnode-object", "gs://bucket/app-1")
    assert out["refused"] == []
    assert out["gate"]["recovery_point"]["backups"][0]["ok"] is True


def test_dump_takes_dumps_even_with_a_backup_regime(host):
    _regime(host)
    out = host.recover("--dump")
    assert out["gate"]["backup_regime"] == {"unit": None, "not_used": "--dump"}
    assert out["backup"] is None
    assert [d["ok"] for d in out["dumps"]] == [True]


def test_a_backup_regime_whose_last_run_failed_isnt_relied_on(host):
    _regime(host, last="exit-code")
    out = host.recover()
    assert "ended in exit-code" in out["gate"]["backup_regime"]["not_used"]
    assert [d["ok"] for d in out["dumps"]] == [True]


def test_an_rdb_copy_redis_check_rdb_cant_read_records_nothing(tmp_path):
    host = _redis(_ready(Host(tmp_path)), check=1)
    out = host.recover(rc=1)
    assert out["dumps"][0]["check_exit"] == 1
    assert any("redis-check-rdb can't read" in w for w in out["verdict"]["why"])
    assert not (host.run_dir / "recovery-point").exists()


def test_a_backup_start_that_runs_nothing_now_records_nothing(host):
    _regime(host)
    # The start returns, and the unit's last run is still yesterday's.
    host.cases["systemctl"].insert(0, ("start -- app-backup.service", "", 0, "", None))
    out = host.recover(rc=1)
    assert any("didn't start a run now" in w for w in out["verdict"]["why"])
    assert not (host.run_dir / "recovery-point").exists()


def test_a_backup_run_that_fails_now_records_nothing(host):
    _regime(host, now="exit-code")
    out = host.recover(rc=1)
    assert out["backup"]["ok"] is False
    assert any("Run again with --dump" in w for w in out["verdict"]["why"])
    assert not (host.run_dir / "recovery-point").exists()


def test_a_recovery_point_restarts_nothing(host):
    host.recover()
    assert _changed(host) == []
