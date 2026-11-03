"""patching-hosts' probe: impact, components and what it writes (#313, plan step 3).

Split out of test_patching_hosts_probe.py (#538), whose docstring says what
the probe's tests pin: under `--dist loadfile` a file runs on one worker, so
one file holding every probe case set the parallel suite's floor. The rig,
`Host` and the helpers are that file's.

What this file holds, section by section as they stood there:

- impact: reboot-required, data stores and databases, earlyoom's arguments,
  a runbook service's ordering, restarters and health checks;
- dormant components;
- text names a component; only a working line uses it (#491);
- privilege and writes;
- a database: exception's glob (#455);
- after the boot;
- a Redis after the boot (#380);
- a data store's own dependency (#384);
- a Redis whose config sets the users (#458);
- what the probe changes (#423, #490, #501).
"""

import subprocess

import pytest

from tests.structural import test_patching_hosts_probe as _probe
from tests.structural.patching_hosts_rig import DAY, dispatcher
from tests.structural.patching_hosts_rig import clean_env as _clean_env
from tests.structural.test_patching_hosts_probe import (
    PROBE,
    SIMULATION,
    STOCK_ORIGINS,
    TODAY,
    Host,
    _finding,
    _ids,
    _policy,
)


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


# The probe file's `host`, bound here by name so pytest finds it. An import
# of it would read as unused to ruff (F401), and each test's argument as its
# redefinition (F811).
host = _probe.host


def _dormant(out: dict, name: str) -> dict:
    hits = [d for d in out["dormant"] if d["name"] == name]
    assert hits, f"no {name} in dormant: {[d['name'] for d in out['dormant']]}"
    return hits[0]


# --- impact -----------------------------------------------------------------


def test_reboot_required_is_read_with_its_packages(host):
    host.write("run/reboot-required", "*** System restart required ***\n")
    host.write("run/reboot-required.pkgs", "libc6\nsystemd\n")
    out = host.run()
    assert out["impact"]["reboot"]["required"] is True
    assert out["impact"]["reboot"]["packages"] == ["libc6", "systemd"]
    assert _finding(out, "reboot:pending")["kind"] == "risk"


def test_a_datastore_process_mapping_a_pending_library_is_named(host):
    host.knob("posture scheduled\ndatastore postgres postgresql@16-main app\n")
    host.on("apt-get", "-s *dist-upgrade", SIMULATION)
    host.on(
        "dpkg-query",
        "*-L libc6",
        "/usr/lib/x86_64-linux-gnu\n/usr/lib/x86_64-linux-gnu/libc.so.6\n",
    )
    host.on(
        "dpkg-query", "*-L libxml2", "/usr/lib/x86_64-linux-gnu/libxml2.so.2.9.14\n"
    )
    host.write(
        "proc/555/maps",
        "7f00-7f01 r-xp 0 fd:01 1 /usr/lib/x86_64-linux-gnu/libc.so.6\n7f02-7f03 r-xp 0 fd:01 2 /usr/lib/x86_64-linux-gnu/libxml2.so.2.9.14\n",
    )
    host.write("proc/555/cgroup", "0::/system.slice/postgresql@16-main.service\n")
    host.write(
        "proc/556/maps", "7f00-7f01 r-xp 0 fd:01 1 /lib/x86_64-linux-gnu/libc.so.6\n"
    )
    host.write("proc/556/cgroup", "0::/system.slice/postgresql@16-main.service\n")
    host.write(
        "proc/600/maps",
        "7f00-7f01 r-xp 0 fd:01 1 /usr/lib/x86_64-linux-gnu/libc.so.6\n",
    )
    host.write("proc/600/cgroup", "0::/user.slice/user-1000.slice/session-3.scope\n")
    out = host.run()
    units = {u["unit"]: u for u in out["impact"]["maps"]["units"]}
    pg = units["postgresql@16-main.service"]
    assert pg == {
        "unit": "postgresql@16-main.service",
        "processes": 2,
        "packages": ["libc6", "libxml2"],
        "datastore": True,
    }
    assert units["session-3.scope"]["datastore"] is False


def test_a_database_no_datastore_line_names_is_a_finding(host):
    host.knob("posture scheduled\ndatastore postgres postgresql@16-main app\n")
    host.on(
        "pg_lsclusters",
        "-h",
        "16 main 5432 online postgres /var/lib/postgresql/16/main /var/log/postgresql/postgresql-16-main.log\n",
    )
    rows = [
        ("postgres", "7000000", "0", "", "C.UTF-8", "c", "", "0"),
        ("template0", "7000000", "0", "", "C.UTF-8", "c", ""),
        ("template1", "7000000", "0", "", "C.UTF-8", "c", ""),
        ("app", "90000000", "1200", "1700000000", "en_US.UTF-8", "c", "2.39"),
        ("stray", "8000000", "0", "", "en_US.UTF-8", "c", "2.39"),
    ]
    host.on("psql", "*-p 5432*", "".join("\x1f".join(r) + "\n" for r in rows))
    out = host.run()
    assert _finding(out, "database:stray")["kind"] == "knob"
    for db in ("app", "postgres", "template0", "template1"):
        assert f"database:{db}" not in _ids(out)
    [cluster] = out["impact"]["datastores"]["postgres"]
    dbs = {d["name"]: d for d in cluster["databases"]}
    assert (
        dbs["app"]["collate"],
        dbs["app"]["collversion"],
        dbs["app"]["stats_reset"],
    ) == ("en_US.UTF-8", "2.39", 1700000000)
    # An empty field keeps its place: psql's fields split on a unit
    # separator, since a tab is IFS whitespace and would collapse.
    assert (
        dbs["stray"]["stats_reset"],
        dbs["stray"]["collate"],
        dbs["stray"]["provider"],
    ) == (None, "en_US.UTF-8", "c")
    # The catalogs are read as postgres, through sudo -n.
    assert [
        c
        for c in host.calls("sudo")
        if c[1].startswith("-n -u postgres -- env LC_ALL=C psql")
    ]


def test_the_catalog_query_names_no_column_postgres_14_lacks(host):
    # datlocprovider and datcollversion came with 15: on 14 a query naming
    # them fails whole ("column d.datlocprovider does not exist", measured).
    _postgres(host, [("postgres", "7000000", "0", "", "C.UTF-8", "", "", "0")])
    host.run()
    [query] = [c[1] for c in host.calls("psql")]
    assert "d.datlocprovider" not in query and "d.datcollversion" not in query
    # Before 15, every database's provider was libc.
    assert "coalesce(to_jsonb(d) ->> 'datlocprovider', 'c')" in query


def test_a_refused_pg_stat_file_costs_only_the_creation_dates(host):
    # A role that isn't a superuser may not run pg_stat_file, and Postgres
    # refuses the whole query for it, CASE or not (measured on 16).
    host.on(
        "psql",
        "*pg_stat_file*",
        rc=1,
        stderr="ERROR:  permission denied for function pg_stat_file\n",
    )
    _postgres(
        host,
        [
            ("postgres", "7000000", "0", "", "C.UTF-8", "c", "", "0", "", "1", "3"),
            ("stray", "8000000", "0", "", "C.UTF-8", "c", "", "", "", "1", "0"),
        ],
    )
    out = host.run()
    [cluster] = out["impact"]["datastores"]["postgres"]
    assert {d["name"]: d["created"] for d in cluster["databases"]} == {
        "postgres": None,
        "stray": None,
    }
    assert _finding(out, "database:stray")["kind"] == "knob"


def test_earlyoom_arguments_come_from_cmdline_not_the_journal(host):
    host.write("proc/777/comm", "earlyoom\n")
    host.write(
        "proc/777/cmdline", b"/usr/bin/earlyoom\x00-m\x005\x00--prefer\x00postgres\x00"
    )
    host.on(
        "journalctl",
        "*earlyoom*",
        "earlyoom[312]: earlyoom v1.7 -m 10 -s 10\nearlyoom[9001]: earlyoom v1.7 -m 5 --prefer postgres\n",
    )
    out = host.run()
    [e] = [a for a in out["impact"]["live_args"] if a["process"] == "earlyoom"]
    assert e == {
        "process": "earlyoom",
        "pid": 777,
        "args": "/usr/bin/earlyoom -m 5 --prefer postgres",
        "source": "/proc/777/cmdline",
    }
    assert not [c for c in host.calls("journalctl") if "earlyoom" in c[1]]


@pytest.mark.parametrize(
    "after, finds",
    [
        ("network.target basic.target", True),
        ("network.target postgresql.service", False),
        ("postgresql@16-main.service", False),
    ],
)
def test_a_runbook_service_without_after_its_datastore_is_a_finding(host, after, finds):
    host.knob(
        "posture scheduled\nservice app-web.service\ndatastore postgres postgresql@16-main app\n"
    )
    host.show(
        "app-web.service",
        After=after,
        Result="success",
        NRestarts="0",
        ActiveState="active",
        RequiredBy="app-health.timer",
        BoundBy="",
    )
    out = host.run()
    [svc] = out["impact"]["services"]
    assert svc["result"] == "success"
    assert svc["required_by"] == ["app-health.timer"]
    if finds:
        f = _finding(out, "ordering:app-web.service")
        assert "postgresql@16-main.service" in f["message"]
    else:
        assert "ordering:app-web.service" not in _ids(out)


def test_a_service_that_is_its_own_datastore_isnt_held_to_ordering_on_itself(host):
    # #367: co-index's knob names qdrant.service as a service and its store.
    host.knob(
        "posture scheduled\nservice qdrant.service\n"
        "datastore qdrant qdrant.service qdrant https://q:6333 -\n"
    )
    host.show(
        "qdrant.service",
        After="network.target docker.service",
        Result="success",
        NRestarts="0",
        ActiveState="active",
        RequiredBy="",
        BoundBy="",
    )
    out = host.run()
    assert "ordering:qdrant.service" not in _ids(out)
    checks = {c["check"] for c in host.run("--post-boot")["post_boot"]}
    assert "ordering:qdrant.service" not in checks


def test_an_undeclared_restarter_is_a_knob_finding(host):
    host.write(
        "etc/systemd/system/app-health.service",
        "[Service]\nExecStart=/bin/sh -c 'curl -sf localhost || systemctl restart app'\n",
    )
    host.write(
        "etc/systemd/system/app.service",
        "[Unit]\nOnFailure=app-alert.service\n[Service]\nExecStart=/usr/bin/app\n",
    )
    out = host.run()
    assert (
        "systemctl restart" in _finding(out, "restarter:app-health.service")["message"]
    )
    assert "OnFailure" in _finding(out, "restarter:app.service")["message"]
    host.knob("posture automatic\nrestarter app-health.timer\nrestarter app.service\n")
    out = host.run()
    assert not [i for i in _ids(out) if i.startswith("restarter:")]


NOTIFY_UNIT = (
    "[Service]\nType=oneshot\n"
    "ExecStart=/bin/bash /home/exedev/app/scripts/notify_failure.sh %i\n"
)


@pytest.mark.parametrize(
    "script, finds, said",
    [
        # replicator's shape (#351): it records and notifies, and mentions
        # systemctl only in a comment.
        (
            "#!/usr/bin/env bash\n# shown in systemctl status + OnFailure=\ncurl -sf x\n",
            False,
            "",
        ),
        (
            '#!/bin/sh\nsystemctl restart "$1"\n',
            True,
            "its OnFailure= target starts or restarts one",
        ),
        (None, True, "notify_failure.sh, which couldn't be read"),
    ],
)
def test_an_onfailure_target_is_a_restarter_only_when_it_restarts_something(
    host, script, finds, said
):
    host.write(
        "etc/systemd/system/app.service",
        "[Unit]\nOnFailure=app-notify@%n.service\n[Service]\nExecStart=/usr/bin/app\n",
    )
    host.write("etc/systemd/system/app-notify@.service", NOTIFY_UNIT)
    if script is not None:
        host.write("home/exedev/app/scripts/notify_failure.sh", script)
    out = host.run()
    assert ("restarter:app.service" in _ids(out)) is finds
    if finds:
        assert said in _finding(out, "restarter:app.service")["message"]
    else:
        assert not out["impact"]["restarters"]


def test_health_checks_run_as_the_user_and_a_failing_one_is_a_finding(host):
    marker = host.tmp / "ran"
    host.knob(
        f"posture automatic\nhealth touch {marker}; id -u >> {marker}\nhealth false\n"
    )
    out = host.run()
    assert marker.read_text().strip() == "1000"
    assert [h["exit"] for h in out["impact"]["health"]] == [0, 1]
    assert not [c for c in host.calls("sudo") if "touch" in c[1]]
    assert _finding(out, "health:3")["kind"] == "risk"
    assert not [c for c in host.calls("runuser")]


@pytest.mark.parametrize(
    "rc, said", [(124, "times out after 60 s"), (137, "is killed")]
)
def test_a_health_check_runs_under_a_time_limit(host, rc, said):
    # A check that hangs (a curl to a dead host) mustn't hang the probe, nor
    # one that ignores the TERM: timeout waits for it unless -k sends a KILL.
    host.knob("posture automatic\nhealth probe-check --slow\n")
    host.on("timeout", "-k 10 60 sh -c probe-check --slow", rc=rc)
    out = host.run()
    assert out["impact"]["health"][0]["exit"] == rc
    assert said in _finding(out, "health:2")["message"]


# --- dormant components ---------------------------------------------------------


def _docker(host: Host, containers: str = "") -> Host:
    host.installed("docker.io")
    host.show("docker.service", ActiveState="active")
    host.on("docker", "ps -aq", containers)
    host.on("docker", "images -q", "abc123\n")
    host.on("docker", "volume ls -q", "")
    return host


@pytest.mark.parametrize(
    "knob, finds",
    [
        ("posture scheduled\n", True),
        (
            "posture scheduled\ndatastore qdrant qdrant.service qdrant https://q:6333 -\n",
            False,
        ),
    ],
)
def test_a_qdrant_container_no_datastore_line_names_is_a_knob_finding(
    host, knob, finds
):
    # #367: on co-index nothing said the host held a data store.
    host.knob(knob)
    _docker(host, "c1\nc2\n")
    host.on(
        "docker",
        "ps --format {{.Names}} {{.Image}}",
        "qdrant docker.io/qdrant/qdrant:v1.17.0\nollama socraticode/ollama-slim:latest\n",
    )
    out = host.run()
    assert out["impact"]["datastores"]["qdrant"] == [
        {
            "container": "qdrant",
            "image": "docker.io/qdrant/qdrant:v1.17.0",
            "declared": not finds,
        }
    ]
    assert ("datastore:qdrant" in _ids(out)) is finds
    if finds:
        f = _finding(out, "datastore:qdrant")
        assert f["kind"] == "knob"
        assert f["exception_what"] == "datastore:qdrant"
        assert "datastore qdrant <unit> qdrant <url> <key-file>" in f["message"]


def test_a_qdrant_the_owner_rebuilds_instead_is_excepted(host):
    host.knob(
        "posture scheduled\n"
        "exception datastore:qdrant 2099-01-01 the index rebuilds from git\n"
    )
    _docker(host, "c1\n")
    host.on("docker", "ps --format {{.Names}} {{.Image}}", "qdrant qdrant/qdrant\n")
    out = host.run()
    assert "datastore:qdrant" not in _ids(out)
    assert "datastore:qdrant" in _ids(out, "excepted")


def test_docker_active_with_no_container_is_dormant(host):
    out = _docker(host).run()
    d = _dormant(out, "docker")
    assert d["verdict"] == "dormant"
    assert d["workload"] == {"containers": 0, "images": 1, "volumes": 0}
    f = _finding(out, "dormant:docker")
    assert f["exception_what"] == "keep:docker"


def test_a_dormant_component_lists_its_pending_security_packages_only(host):
    host.on(
        "apt-get",
        "-s *dist-upgrade",
        "Inst docker.io [28.2] (29.1 Ubuntu:24.04/noble-security [amd64])\n"
        "Inst containerd [1.7.27] (1.7.28 Ubuntu:24.04/noble-updates [amd64])\n",
    )
    d = _dormant(_docker(host).run(), "docker")
    assert d["pending_security"] == ["docker.io"]


@pytest.mark.parametrize(
    "extra, security_only, listed",
    [
        ("", True, ["docker.io"]),
        (
            'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}-updates";\n',
            False,
            [],
        ),
    ],
)
def test_the_dry_runs_selection_is_security_only_while_its_origins_are(
    host, extra, security_only, listed
):
    # The dry run takes whatever unattended-upgrades' origins allow: with
    # -updates among them, docker.io on its line may be a -updates fix.
    host.apt_config(Enable="1", Lists="1", UU="1", Reboot="false")
    host.on("apt-config", "dump", STOCK_ORIGINS + extra)
    host.on(
        "unattended-upgrade",
        "--dry-run -d",
        "Packages that will be upgraded: docker.io\n",
    )
    out = _docker(host).run("--dry-run-into", str(host.tmp / "dry"))
    assert out["pending"]["dry_run"]["security_only"] is security_only
    assert _dormant(out, "docker")["pending_security"] == listed


def test_an_idle_docker_is_never_asked(host):
    # exeuntu enables docker.socket and disables docker.service, so the first
    # docker call starts dockerd: measured in the image, 2026-10-01. That
    # changes the host, and restarts the idle clock the verdict reads.
    host.installed("docker.io")
    host.show(
        "docker.service",
        ActiveState="inactive",
        InactiveEnterTimestamp=f"@{host.now - 40 * DAY}",
    )
    host.show("docker.socket", ActiveState="active")
    host.on("docker", "*", "")
    out = host.run()
    assert _dormant(out, "docker")["verdict"] == "dormant"
    assert any("docker.socket" in n for n in out["not_read"])
    checks = {c["check"]: c for c in host.run("--post-boot")["post_boot"]}
    # No data root on disk: Docker never held a container.
    assert checks["containers"]["ok"] is True
    assert host.calls("docker") == []


def test_docker_socket_is_named_only_while_it_listens(host):
    # A docker CLI with no socket of its own, say one pointed elsewhere.
    host.installed("docker.io")
    host.show("docker.service", ActiveState="inactive")
    host.on("docker", "*", "")
    out = host.run()
    [n] = [n for n in out["not_read"] if n.startswith("container images")]
    assert "docker.socket" not in n


def _docker_disk(host: Host, root: str = "var/lib/docker") -> None:
    """Three containers and a volume on disk, the way dockerd 29 writes them."""
    for cid, policy, manual in (
        ("a1", "unless-stopped", "false"),
        ("b2", "unless-stopped", "true"),
        ("c3", "no", "false"),
    ):
        host.write(
            f"{root}/containers/{cid}/hostconfig.json",
            '{"Binds":null,"RestartPolicy":{"Name":"%s","MaximumRetryCount":0}}'
            % policy,
        )
        host.write(
            f"{root}/containers/{cid}/config.v2.json",
            '{"HasBeenManuallyStopped":%s}' % manual,
        )
    (host.root / root / "volumes" / "pgdata" / "_data").mkdir(parents=True)
    host.write(f"{root}/volumes/metadata.db", "")


@pytest.mark.parametrize("root", ["var/lib/docker", "srv/docker"])
def test_containers_on_disk_count_while_dockerd_is_down(host, root):
    # Measured in the exeuntu image: with docker.service disabled, a
    # container with --restart unless-stopped stayed down after a reboot.
    # Read from disk, it fails the post-boot check, and an idle Docker
    # holding it isn't dormant.
    host.installed("docker.io")
    if root != "var/lib/docker":
        host.write("etc/docker/daemon.json", '{"data-root": "/%s"}\n' % root)
    _docker_disk(host, root)
    host.show(
        "docker.service",
        ActiveState="inactive",
        InactiveEnterTimestamp=f"@{host.now - 40 * DAY}",
    )
    host.on("docker", "*", "")
    d = _dormant(host.run(), "docker")
    assert d["verdict"] == "unknown"
    assert d["workload"] == {"containers": 3, "volumes": 1, "read_from": "disk"}
    checks = {c["check"]: c for c in host.run("--post-boot")["post_boot"]}
    assert checks["containers"]["ok"] is False
    assert (
        "1 containers with a restart policy aren't back"
        in checks["containers"]["evidence"]
    )
    assert host.calls("docker") == []


def test_docker_under_a_keep_exception_is_kept(host):
    host.knob(
        "posture automatic\nexception keep:docker 2099-01-01 builds run here monthly\n"
    )
    out = _docker(host).run()
    d = _dormant(out, "docker")
    assert d["verdict"] == "kept"
    assert d["exception"] == "keep:docker"
    assert "dormant:docker" not in _ids(out)


def test_docker_with_a_container_is_in_use(host):
    out = _docker(host, "f00d\n").run()
    assert _dormant(out, "docker")["verdict"] == "in-use"


# --- text names a component; only a working line uses it (#491) ----------------------
# On co-processor, a comment in deploy/processor.service saying the service
# user is NOT in group docker made an idle Docker in-use, hiding a prune
# candidate.

NOT_IN_GROUP = (
    "[Service]\n# The service user is not in group docker: it never runs containers.\n"
    "ExecStart=/srv/app/serve\n"
)


def _repo(host: Host, rel: str, text: str) -> None:
    p = host.repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


@pytest.mark.parametrize(
    "rel, text",
    [
        ("deploy/processor.service", NOT_IN_GROUP),
        ("deploy/README.md", "We used Docker once, and don't now.\n"),
    ],
    ids=["comment", "prose"],
)
def test_a_component_deploy_names_only_in_text_is_named(host, rel, text):
    _repo(host, rel, text)
    out = _docker(host).run()
    d = _dormant(out, "docker")
    assert d["verdict"] == "named"
    assert rel in d["named_by"]
    assert "no container in any state" in d["evidence"]
    assert "dormant:docker" not in _ids(out)
    # Not a prune candidate without the operator's look, which it asks for.
    f = _finding(out, "named:docker")
    assert (f["kind"], f["exception_what"]) == ("dormant", "keep:docker")
    assert "look before proposing a prune" in f["message"]
    host.knob("posture automatic\nexception keep:docker 2099-01-01 kept on purpose\n")
    assert _dormant(host.run(), "docker")["verdict"] == "kept"


@pytest.mark.parametrize(
    "rel, text, evidence",
    [
        (
            "deploy/processor.service",
            "[Unit]\nAfter=docker.service\n[Service]\nExecStart=/srv/app/serve\n",
            "deploy/processor.service names it on a line that isn't a comment",
        ),
        (
            "deploy/compose.sh",
            "#!/bin/sh\n# start it\ndocker compose up -d\n",
            "deploy/compose.sh names it on a line that isn't a comment",
        ),
    ],
    ids=["unit", "script"],
)
def test_a_working_deploy_line_is_in_use(host, rel, text, evidence):
    _repo(host, rel, text)
    d = _dormant(_docker(host).run(), "docker")
    assert (d["verdict"], d["evidence"]) == ("in-use", evidence)


@pytest.mark.parametrize(
    "line, uses",
    [
        ("Requires=docker.service", True),
        ("After=docker.service", True),
        ("ExecStartPre=/usr/bin/docker pull app", True),
        # A description, or a comment, is text.
        ("Description=Not docker", False),
        ("# After=docker.service", False),
    ],
)
def test_a_host_units_requires_after_or_exec_naming_it_is_in_use(host, line, uses):
    host.write(
        "etc/systemd/system/app.service",
        f"[Unit]\n{line}\n[Service]\nExecStart=/srv/app/serve\n",
    )
    d = _dormant(_docker(host).run(), "docker")
    if uses:
        assert d["verdict"] == "in-use"
        assert d["evidence"].startswith("/etc/systemd/system/app.service names it")
    else:
        assert d["verdict"] == "dormant"


def test_idle_evidence_younger_than_30_days_is_unknown(tmp_path):
    h = Host(tmp_path, uptime_days=10).knob("posture automatic\n")
    out = _docker(h).run()
    d = _dormant(out, "docker")
    assert d["verdict"] == "unknown"
    assert "fewer than 30" in d["evidence"]
    assert "dormant:docker" not in _ids(out)


@pytest.mark.parametrize(
    "engine, unit, package, cli",
    [
        ("docker", "docker.service", "docker.io", "docker"),
        ("redis", "redis-server.service", "redis-server", "redis-cli"),
    ],
)
def test_an_active_engine_without_its_cli_says_so(host, engine, unit, package, cli):
    host.installed(package)
    host.show(unit, ActiveState="active")
    host.absent(cli)
    d = _dormant(host.run(), engine)
    assert d["verdict"] == "unknown"
    assert f"{cli}" in d["evidence"] and "isn't on PATH" in d["evidence"]


def test_a_postgres_whose_activity_needs_a_failed_login_is_unknown(host):
    host.on(
        "dpkg-query",
        "*-W -f ${Package} ${db:Status-Abbrev}\\n postgresql-[0-9]*",
        "postgresql-16 ii \n",
    )
    host.on(
        "pg_lsclusters",
        "-h",
        "16 main 5432 online postgres /var/lib/postgresql/16/main /var/log/postgresql/postgresql-16-main.log\n",
    )
    host.on(
        "psql",
        "*",
        "",
        rc=2,
        stderr="psql: error: connection to server failed: FATAL:  Peer authentication failed\n",
    )
    out = host.run()
    d = _dormant(out, "postgres")
    assert d["verdict"] == "unknown"
    assert "login" in d["evidence"]
    assert "dormant:postgres" not in _ids(out)


def test_idle_since_boot_counts_from_when_systemd_started(host):
    # In a container, or after a soft reboot, systemd starts long after the
    # kernel: the kernel's 40 days aren't 40 days of nginx sitting idle.
    host.installed("nginx")
    host.show("nginx.service", ActiveState="inactive", InactiveEnterTimestamp="")
    host.on(
        "systemctl",
        "show --timestamp=unix -p UserspaceTimestamp",
        f"UserspaceTimestamp=@{host.now - 5 * DAY - 60}\n",
    )
    out = host.run()
    assert out["environment"]["boot"]["systemd_started_days"] == 5
    d = _dormant(out, "nginx")
    assert d["verdict"] == "unknown"
    assert "for 5 days" in d["evidence"]


def test_docker_counts_its_idle_window_from_its_own_start(host):
    _docker(host)
    host.cases["systemctl"].insert(
        0,
        (
            "show*-- docker.service",
            f"ActiveState=active\nActiveEnterTimestamp=@{host.now - 3 * DAY}\n",
            0,
            "",
        ),
    )
    d = _dormant(host.run(), "docker")
    assert d["verdict"] == "unknown"
    assert "active for only 3 days" in d["evidence"]


@pytest.mark.parametrize("days, verdict", [(3, "unknown"), (35, "dormant")])
def test_an_empty_postgres_counts_from_its_own_start(host, days, verdict):
    # The kernel booted 40 days ago, but the cluster only started `days` ago.
    host.on(
        "dpkg-query",
        "*-W -f ${Package} ${db:Status-Abbrev}\\n postgresql-[0-9]*",
        "postgresql-16 ii \n",
    )
    host.on(
        "pg_lsclusters",
        "-h",
        "16 main 5432 online postgres /var/lib/postgresql/16/main "
        "/var/log/postgresql/postgresql-16-main.log\n",
    )
    rows = ["postgres", "template0", "template1"]
    host.on(
        "psql",
        "*",
        "".join(f"{r}\x1f1\x1f0\x1f\x1fC.UTF-8\x1fc\x1f\x1f0\n" for r in rows),
    )
    host.show(
        "postgresql@16-main.service",
        ActiveState="active",
        ActiveEnterTimestamp=f"@{host.now - days * DAY - 60}",
    )
    d = _dormant(host.run(), "postgres")
    assert d["verdict"] == verdict
    assert f"up {'only ' if days < 30 else ''}{days} days" in d["evidence"]


def _postgres(host: Host, rows: list[tuple[str, ...]]) -> Host:
    """An installed, online 16/main cluster whose catalog query returns ROWS."""
    host.on(
        "dpkg-query",
        "*-W -f ${Package} ${db:Status-Abbrev}\\n postgresql-[0-9]*",
        "postgresql-16 ii \n",
    )
    host.on(
        "pg_lsclusters",
        "-h",
        "16 main 5432 online postgres /var/lib/postgresql/16/main "
        "/var/log/postgresql/postgresql-16-main.log\n",
    )
    host.on("psql", "*", "".join("\x1f".join(r) + "\n" for r in rows))
    return host


def test_tables_kept_in_the_postgres_database_are_data(host):
    # The default database: an app pointed at .../postgres keeps its tables
    # there, and they're neither dormant nor outside the recovery point.
    _postgres(host, [("postgres", "9000000", "40", "", "C.UTF-8", "c", "", "3")])
    out = host.run()
    d = _dormant(out, "postgres")
    assert d["verdict"] == "in-use"
    assert d["workload"] == {
        "databases": 1,
        "writes_since_stats_reset": 40,
        "sessions_since_stats_reset": None,
    }
    assert "3 tables of its own" in _finding(out, "database:postgres")["message"]


@pytest.mark.parametrize(
    "created, started, verdict, evidence",
    [
        (10, 40, "unknown", "cover only 10 days"),
        (60, 35, "dormant", "no session in the 35 days"),
    ],
)
def test_a_databases_statistics_cover_no_more_than_its_own_life(
    host, created, started, verdict, evidence
):
    # Never reset, a database's counters start with it: one created 10 days
    # ago on a server up 40 has 10 days of evidence, not 40.
    def ago(days: int) -> str:
        return str(host.now - days * DAY - 60)

    _postgres(
        host,
        [
            (
                "app",
                "9000000",
                "0",
                "",
                "C.UTF-8",
                "c",
                "",
                "",
                ago(created),
                ago(started),
                "0",
            ),
            (
                "postgres",
                "7000000",
                "0",
                "",
                "C.UTF-8",
                "c",
                "",
                "0",
                ago(90),
                ago(started),
            ),
        ],
    )
    d = _dormant(host.run(), "postgres")
    assert d["verdict"] == verdict
    assert evidence in d["evidence"]


def test_a_database_name_stays_whole(host):
    # Legal in Postgres: split on IFS it was two databases, and the '*'
    # expanded against the current directory.
    (host.tmp / "x").touch()
    _postgres(
        host,
        [
            (
                "a b|*",
                "9000000",
                "7",
                "1700000000",
                "C.UTF-8",
                "c",
                "",
                "",
                "",
                "",
                "2",
            ),
            ("postgres", "7000000", "0", "", "C.UTF-8", "c", "", "0"),
        ],
    )
    d = _dormant(host.run(), "postgres")
    assert d["workload"] == {
        "databases": 1,
        "writes_since_stats_reset": 7,
        "sessions_since_stats_reset": 2,
    }


@pytest.mark.parametrize(
    "sessions, verdict, evidence",
    [
        ("4", "unknown", "4 sessions"),
        ("", "unknown", "before Postgres 14"),
        ("0", "dormant", "no session"),
    ],
)
def test_a_database_only_read_isnt_dormant(host, sessions, verdict, evidence):
    # An app that only reads writes no row. sessions counts its connections,
    # and autovacuum's don't (measured on 16).
    old = str(host.now - 60 * DAY)
    _postgres(
        host,
        [
            ("ref", "9000000", "0", "", "C.UTF-8", "c", "", "", old, old, sessions),
            ("postgres", "7000000", "0", "", "C.UTF-8", "c", "", "0", old, old, "9"),
        ],
    )
    d = _dormant(host.run(), "postgres")
    assert d["verdict"] == verdict
    assert evidence in d["evidence"]


@pytest.mark.parametrize(
    "main, b_down, verdict, evidence",
    [
        ("online", 2, "unknown", "16/b (down 2 days)"),
        ("online", 45, "dormant", "no database but postgres"),
        ("down", 45, "dormant", "every cluster down, the latest for 45 days"),
        ("down", 2, "unknown", "16/b (down 2 days)"),
    ],
)
def test_every_postgres_cluster_counts_toward_the_verdict(
    host, main, b_down, verdict, evidence
):
    # A cluster stopped two days ago could be the busy one. postgresql.service
    # stays active (exited) with every cluster down, so each cluster's own
    # unit says how long it's been down.
    _postgres(host, [("postgres", "7000000", "0", "", "C.UTF-8", "c", "", "0")])
    host.cases["pg_lsclusters"].clear()
    host.on(
        "pg_lsclusters",
        "-h",
        f"16 main 5432 {main} postgres /var/lib/postgresql/16/main "
        "/var/log/postgresql/postgresql-16-main.log\n"
        "16 b 5433 down postgres /var/lib/postgresql/16/b "
        "/var/log/postgresql/postgresql-16-b.log\n",
    )
    then = f"@{host.now - 45 * DAY - 60}"
    if main == "online":
        host.show(
            "postgresql@16-main.service",
            ActiveState="active",
            ActiveEnterTimestamp=then,
        )
    else:
        host.show(
            "postgresql@16-main.service",
            ActiveState="inactive",
            InactiveEnterTimestamp=then,
        )
    host.show(
        "postgresql@16-b.service",
        ActiveState="inactive",
        InactiveEnterTimestamp=f"@{host.now - b_down * DAY - 60}",
    )
    host.show("postgresql.service", ActiveState="active")
    d = _dormant(host.run(), "postgres")
    assert d["verdict"] == verdict
    assert evidence in d["evidence"]


REDIS_IDLE = {
    "uptime_in_days": "40",
    "connected_clients": "1",
    "keyspace_hits": "0",
    "keyspace_misses": "0",
    "expired_keys": "0",
    "pubsub_channels": "0",
    "pubsub_patterns": "0",
}


@pytest.mark.parametrize(
    "change, verdict, evidence",
    [
        ({}, "dormant", "no lookup"),
        ({"keyspace_misses": "12"}, "in-use", "12 key lookups"),
        ({"expired_keys": "5"}, "in-use", "5 keys expired"),
        ({"pubsub_channels": "2"}, "in-use", "2 pub/sub"),
        ({"connected_clients": "3"}, "in-use", "2 clients besides"),
        ({"pubsub_patterns": None}, "unknown", "INFO lacked"),
    ],
)
def test_a_redis_with_no_key_is_dormant_only_when_nothing_uses_it(
    host, change, verdict, evidence
):
    # A cache whose keys expired, or a bus, holds no key (measured on 7).
    info = {**REDIS_IDLE, **change}
    host.installed("redis-server")
    host.show("redis-server.service", ActiveState="active")
    host.on(
        "redis-cli",
        "INFO",
        "".join(f"{k}:{v}\r\n" for k, v in info.items() if v is not None),
    )
    d = _dormant(host.run(), "redis")
    assert d["verdict"] == verdict
    assert evidence in d["evidence"]


@pytest.mark.parametrize(
    "unit, uses",
    [
        # CR 889: only a unit whose name starts with the component's is its
        # own; app-redis-worker.service, which needs Redis, uses it.
        ("app-redis-worker.service", True),
        ("redis-server.service.d/override.conf", False),
    ],
)
def test_a_unit_whose_name_merely_holds_the_components_isnt_its_own(host, unit, uses):
    host.installed("redis-server")
    host.show("redis-server.service", ActiveState="active")
    host.on("redis-cli", "INFO", "".join(f"{k}:{v}\r\n" for k, v in REDIS_IDLE.items()))
    host.write(
        f"etc/systemd/system/{unit}",
        "[Unit]\nRequires=redis-server.service\n[Service]\nExecStart=/srv/app/work\n",
    )
    d = _dormant(host.run(), "redis")
    assert d["verdict"] == ("in-use" if uses else "dormant")
    if uses:
        assert d["evidence"].startswith(f"/etc/systemd/system/{unit} names it")


def test_a_redis_that_needs_a_login_says_so(host):
    # Unauthenticated, as the probe asks: an ACL'd Redis answers NOAUTH, and
    # nothing reaches its ACL LOG (#379; measured on 7.0).
    host.installed("redis-server")
    host.show("redis-server.service", ActiveState="active")
    host.on("redis-cli", "INFO", "NOAUTH Authentication required.\n")
    d = _dormant(host.run(), "redis")
    assert d["verdict"] == "unknown"
    assert "it needs a login (INFO answered NOAUTH)" in d["evidence"]


def test_an_unpackaged_engine_counts_from_its_own_start(host):
    host.write("usr/lib/systemd/system/ollama.service", "[Service]\n")
    (host.root / "usr/share/ollama/.ollama/models/manifests").mkdir(parents=True)
    host.show(
        "ollama.service",
        ActiveState="active",
        ActiveEnterTimestamp=f"@{host.now - 3 * DAY - 60}",
    )
    d = _dormant(host.run(), "ollama")
    assert d["verdict"] == "unknown"
    assert "active for only 3 days" in d["evidence"]


def test_an_inactive_nginx_idle_past_30_days_is_dormant(host):
    host.installed("nginx")
    host.show("nginx.service", ActiveState="inactive", InactiveEnterTimestamp="")
    out = host.run()
    d = _dormant(out, "nginx")
    assert d["verdict"] == "dormant"
    assert "40 days" in d["evidence"]


def test_parsed_lines_stay_english_when_sudo_resets_the_locale(tmp_path):
    # needrestart's "Disabling Ubuntu mode" and unattended-upgrade's "Packages
    # that will be upgraded" are translated by gettext, and sudoers' env_reset
    # can drop LC_ALL on the way to root.
    h = Host(tmp_path, sudo="reset").knob("posture automatic\n")
    h.installed("needrestart")
    h.write("etc/needrestart/conf.d/x.conf", "$nrconf{restart} = 'l';\n")
    h.on(
        "needrestart",
        "-m u -b -r l",
        script='if [ "${LC_ALL:-}" = C ]; then '
        'echo "Disabling Ubuntu mode, explicit restart mode configured"; '
        'else echo "Ubuntu-Modus deaktiviert"; fi; '
        "echo NEEDRESTART-VER: 3.6; exit 0",
    )
    out = h.run()
    assert out["updates"]["needrestart"]["proof"] == "explicit"
    assert "needrestart:restart" not in _ids(out)


# --- privilege and writes -------------------------------------------------------------


def test_without_root_the_root_only_readings_are_named_not_read(tmp_path):
    h = Host(tmp_path, sudo=False).knob("posture automatic\n")
    h.installed("needrestart")
    h.on("apt-get", "-s *dist-upgrade", SIMULATION)
    out = h.run()
    assert out["probe"]["privilege"] == "none"
    assert out["impact"]["maps"] is None
    assert out["updates"]["needrestart"]["proof"] == "unknown"
    assert any("sudo -n needs a password" in n for n in out["not_read"])
    assert not h.calls("needrestart")


@pytest.mark.parametrize("case", ["no-root", "unknown-lane"])
def test_a_dry_run_that_doesnt_run_leaves_no_earlier_summary(tmp_path, case):
    # CR 191: exit 0 with a dry-run finding, and an earlier summary in DIR
    # that apply.sh would have counted with.
    h = Host(tmp_path, sudo=case != "no-root").knob(
        "class production\nposture scheduled\n"
    )
    scratch = h.tmp / "dry"
    scratch.mkdir()
    (scratch / "summary").write_text(
        f"began={h.now - 600}\nexit=0\ncount=3\nwall_seconds=60\n"
    )
    args = ["--lane", "origin:pkgs.example.com"] if case == "unknown-lane" else []
    out = h.run("--dry-run-into", str(scratch), *args)
    assert _finding(out, "dry-run")["kind"] == "unknown"
    assert not (scratch / "summary").exists()
    assert not h.calls("unattended-upgrade")


@pytest.mark.parametrize(
    "hostname, rc, host",
    [
        (None, 2, None),
        ("", 2, None),
        ("web-2\r\n", 0, "web-2"),
        (" web-2 \n", 0, "web-2"),
    ],
    ids=["missing", "empty", "crlf", "blanks"],
)
def test_a_root_trees_host_is_its_own_never_the_probing_machines(
    tmp_path, hostname, rc, host
):
    # CR 192: under --root, a tree without etc/hostname took `hostname`,
    # the machine running the probe, and so its knob sections.
    h = Host(tmp_path).knob("class production\nposture automatic\n")
    if hostname is not None:
        h.write("etc/hostname", hostname)
    r = h.execute(
        [
            "bash",
            str(PROBE),
            "--root",
            str(h.root),
            "--config",
            str(h.knob_path),
            "--repo",
            str(h.repo),
            "--today",
            TODAY,
            "--session-pid",
            "4242",
        ],
        rc,
    )
    if rc:
        assert "has no readable etc/hostname naming the host: pass --host" in r.stderr
        assert not h.calls("hostname")
    else:
        assert r["knob"]["host"] == host


def test_an_unsimulated_set_leaves_what_it_touches_null_never_none(host):
    # CR 193: apt-get -s failing left the set empty, and maps read
    # "nothing pending", each hold group's pending [].
    host.on("apt-get", "-s *dist-upgrade", "", rc=100, stderr="E: lock\n")
    out = host.run()
    assert out["impact"]["maps"] is None
    assert any(
        "map a library in the set: the pending set couldn't be simulated" in n
        for n in out["not_read"]
    )
    assert out["pending"]["hold_groups"]
    assert all(g["pending"] is None for g in out["pending"]["hold_groups"])


def test_unread_apt_config_leaves_the_uu_origins_null(host):
    # CR 193: no apt-config reading, so no origin list, never an empty one.
    host.installed("unattended-upgrades")
    assert host.run()["updates"]["unattended_upgrades"]["origins"] is None
    host.apt_config(Enable="1", Lists="1", UU="1", Reboot="false")
    host.on("apt-config", "dump", STOCK_ORIGINS)
    assert len(host.run()["updates"]["unattended_upgrades"]["origins"]) == 4


@pytest.mark.parametrize(
    "answer, services",
    [
        (
            "NEEDRESTART-VER: 3.6\nNEEDRESTART-SVC: tailscaled.service\n",
            ["tailscaled.service"],
        ),
        ("NEEDRESTART-VER: 3.6\n", []),
        ("", None),
    ],
    ids=["one", "none", "unread"],
)
def test_needrestarts_services_are_null_unless_it_answered(host, answer, services):
    # CR 193: [] meant both "nothing to restart" and "never asked".
    host.installed("needrestart")
    host.on("needrestart", "*", answer, rc=0 if answer else 1)
    out = host.run()
    assert out["impact"]["reboot"]["needrestart_services"] == services


def test_an_undeclared_backup_regime_is_named_with_the_grammar_to_declare_it(host):
    # CR 198: "declare it" alone reads as `backup <unit>`, which CR 194 made
    # malformed.
    host.write("etc/systemd/system/app-backup.service", "[Service]\n")
    f = _finding(host.run(), "backup:app-backup")
    assert f["kind"] == "knob"
    assert "backup app-backup <datastore unit>..." in f["message"]
    host.knob(
        "class production\nposture automatic\n"
        "datastore postgres postgresql@16-main app\n"
        "backup app-backup.service postgresql@16-main\n"
    )
    assert "backup:app-backup" not in _ids(host.run())


def test_a_backup_over_a_cluster_of_several_databases_is_a_finding_before_a_run(host):
    # #480: the recovery point and the bulk refuse it, so the probe names it
    # first, with the line to write.
    knob = (
        "class production\nposture automatic\n"
        "datastore postgres postgresql@16-main app app_test\n"
    )
    host.knob(knob + "backup app-backup.service postgresql@16-main\n")
    f = _finding(
        host.run(), "backup-covers:app-backup.service:postgresql@16-main.service"
    )
    assert f["kind"] == "knob" and f["exception_what"] is None
    assert "backup app-backup.service postgresql@16-main:app,app_test" in f["message"]
    host.knob(knob + "backup app-backup.service postgresql@16-main:app\n")
    assert not [i for i in _ids(host.run()) if i.startswith("backup-covers:")]


def test_a_backup_refusals_line_names_each_database_once(host):
    # CR 895: two datastore lines for one unit whose lists overlap.
    host.knob(
        "class production\nposture automatic\n"
        "datastore postgres postgresql@16-main app\n"
        "datastore postgres postgresql@16-main app b\n"
        "backup app-backup.service postgresql@16-main\n"
    )
    f = _finding(
        host.run(), "backup-covers:app-backup.service:postgresql@16-main.service"
    )
    assert "backup app-backup.service postgresql@16-main:app,b," in f["message"]
    assert "whose datastore lines name app b," in f["message"]


# --- a database: exception's glob (#455) --------------------------------------------
# host 6's test suite made one database per pytest-xdist worker, and each new
# worker was a new finding.

_WORKERS = [
    ("postgres", "7000000", "0", "", "C.UTF-8", "c", "", "0"),
    ("app", "90000000", "1200", "1700000000", "en_US.UTF-8", "c", "2.39"),
    ("app_test", "8000000", "0", "", "en_US.UTF-8", "c", "2.39"),
    ("app_test_gw0", "8000000", "0", "", "en_US.UTF-8", "c", "2.39"),
    ("app_test_gw1", "8000000", "0", "", "en_US.UTF-8", "c", "2.39"),
    ("stray", "8000000", "0", "", "en_US.UTF-8", "c", "2.39"),
]


def test_a_database_exception_takes_a_glob(host):
    _postgres(host, _WORKERS)
    host.knob(
        "posture scheduled\ndatastore postgres postgresql@16-main app\n"
        "exception database:app_test* 2099-01-01 the test suite's, rebuilt by every run\n"
    )
    out = host.run()
    for db in ("app_test", "app_test_gw0", "app_test_gw1"):
        assert f"database:{db}" not in _ids(out)
        assert _finding(out, f"database:{db}", "excepted")["exception_line"] == 3
    assert _finding(out, "database:stray")["kind"] == "knob"


def test_an_exact_database_exception_beats_a_glob(host):
    _postgres(host, _WORKERS)
    host.knob(
        "posture scheduled\ndatastore postgres postgresql@16-main app\n"
        "exception database:app_test* 2099-01-01 the test suite's\n"
        "exception database:app_test_gw1 2099-02-01 this worker's own reason\n"
    )
    out = host.run()
    f = _finding(out, "database:app_test_gw1", "excepted")
    assert (f["exception_line"], f["review_by"]) == (4, "2099-02-01")
    assert _finding(out, "database:app_test_gw0", "excepted")["exception_line"] == 3


def test_a_glob_excepts_nothing_but_a_database(host):
    # A held:<package> names one thing: a glob there would over-cover.
    host.on("apt-mark", "showhold", "libxml2\n")
    host.on(
        "apt-cache",
        "*policy libxml2",
        _policy("libxml2", "2.9.14", "2.9.14.1", ["noble-updates", "noble-security"]),
    )
    host.knob("posture automatic\nexception held:lib* 2099-01-01 every library\n")
    assert "held:libxml2" in _ids(host.run())


def _mutating(name: str, args: str) -> bool:
    """Whether one stubbed call would change the host."""
    a = args.split()
    if name == "apt-get":
        # --print-uris prints what it would fetch, and fetches nothing (#499).
        if "-s" in a or "--print-uris" in a:
            return False
        return not (
            "update" in a
            and any(x.startswith("Dir::State::Lists=") and "/lists/" in x for x in a)
        )
    if name == "apt-mark":
        return a != ["showhold"]
    if name == "dpkg":
        return True
    if name == "systemctl":
        verbs = {
            "start", "stop", "restart", "reload", "try-restart", "reload-or-restart", "enable",
            "disable", "mask", "unmask", "daemon-reload", "kill", "reset-failed", "reboot",
            "poweroff", "isolate", "set-property", "edit", "link", "preset", "revert",
        }  # fmt: skip
        return bool(verbs & set(a))
    if name == "unattended-upgrade":
        return "--dry-run" not in a
    if name == "needrestart":
        return not ("-r" in a and a[a.index("-r") + 1] == "l")
    if name == "docker":
        return a[:1] not in (["ps"], ["images"]) and a[:2] != ["volume", "ls"]
    if name == "pro":
        return a[:1] != ["security-status"]
    if name == "redis-cli":
        return a != ["INFO"]
    if name == "psql":
        return not args.split("-c ", 1)[-1].lower().startswith("select ")
    return False


def test_no_command_installs_removes_holds_restarts_or_writes_lists(host):
    host.knob(
        "posture scheduled\n"
        "service app-web.service\n"
        "restarter app-health.timer\n"
        "backup app-backup.service postgresql@16-main\n"
        "datastore postgres postgresql@16-main app\n"
        "datastore redis redis-server\n"
    )
    host.installed(
        "needrestart", "unattended-upgrades", "docker.io", "redis-server", "nginx"
    )
    host.write("etc/needrestart/conf.d/x.conf", "$nrconf{restart} = 'l';\n")
    host.on(
        "needrestart",
        "*",
        "Disabling Ubuntu mode, explicit restart mode configured\nNEEDRESTART-VER: 3.6\n",
    )
    host.on("apt-get", "update*", "")
    host.on("apt-get", "-s *dist-upgrade", SIMULATION)
    host.on("apt-mark", "showhold", "")
    host.on(
        "unattended-upgrade", "--dry-run -d", "Packages that will be upgraded: libc6\n"
    )
    host.on(
        "pg_lsclusters",
        "-h",
        "16 main 5432 online postgres /var/lib/postgresql/16/main /var/log/postgresql/postgresql-16-main.log\n",
    )
    host.on("psql", "*", "app\x1f1\x1f5\x1f\x1fC.UTF-8\x1fc\x1f\n")
    host.on("redis-cli", "INFO", "uptime_in_days:40\r\ndb0:keys=3,expires=0\r\n")
    host.show("docker.service", ActiveState="active")
    host.show("redis-server.service", ActiveState="active")
    host.on("docker", "*", "")
    host.on("dpkg-query", "*-L *", "/usr/lib/x86_64-linux-gnu/libc.so.6\n")
    host.write(
        "proc/555/maps",
        "7f00-7f01 r-xp 0 fd:01 1 /usr/lib/x86_64-linux-gnu/libc.so.6\n",
    )
    host.write(
        "proc/1/maps",
        "7f00-7f01 r-xp 0 fd:01 1 /usr/lib/systemd/libsystemd-shared.so (deleted)\n",
    )
    host.on("systemctl", "*", "")
    host.on("journalctl", "*", "")
    host.run(
        "--refresh-into",
        str(host.tmp / "fresh"),
        "--dry-run-into",
        str(host.tmp / "dry"),
    )
    host.run("--post-boot")
    calls = host.calls()
    assert len(calls) > 50, "the probe asked the stubs almost nothing"
    bad = [
        (n, a) for n, a, _ in calls if n not in ("sudo", "choom") and _mutating(n, a)
    ]
    assert bad == []


# --- after the boot -------------------------------------------------------------------


@pytest.mark.parametrize(
    "tail, ok",
    [
        (
            "systemd-journald.service: Deactivated successfully.\nJournal stopped\n",
            True,
        ),
        ("kernel: Linux version 6.12\n", False),
    ],
)
def test_post_boot_reads_a_persistent_journals_previous_boot_for_its_stop(
    host, tail, ok
):
    # #356: a persistent journal isn't copied, so a copy check read null
    # there. Its previous boot's own last line says the shutdown was clean.
    host.write("var/log/journal/" + "a" * 32 + "/system.journal", "x")
    host.on("journalctl", "-b -1 -n 20 -q --no-pager -o cat", tail)
    out = host.run("--post-boot")
    checks = {c["check"]: c for c in out["post_boot"]}
    assert checks["shutdown:journal-stopped"]["ok"] is ok
    assert "shutdown:journal-copy" not in checks
    assert ("post-boot:shutdown:journal-stopped" in _ids(out)) is not ok


RUN = "var/backups/patching-hosts-20261006T164500Z"
COPIED = "2026-10-06T16:46:48Z journal /run/log/journal copied to /x/journal/_run_log_journal, and read back\n"
FAILED = "2026-10-06T16:46:48Z the copy of /run/log/journal failed: the shutdown has no record of its own\n"


@pytest.mark.parametrize(
    "log, partial, ok, said",
    [
        (COPIED, False, True, "copied the volatile journal"),
        # CR 200: the chain makes the directory before cp, so a failed copy
        # leaves one behind; its log is what says.
        (FAILED, True, False, "copy of the volatile journal failed"),
        (
            "2026-10-06T16:46:48Z /run/log/journal holds no journal: a persistent one survives the boot\n",
            False,
            False,
            "isn't persistent (verdict volatile)",
        ),
        (
            "2026-10-06T16:46:00Z start\n2026-10-06T16:46:01Z ABORT\n",
            False,
            None,
            "has no journal step",
        ),
        (None, False, None, "no reboot chain log"),
    ],
)
def test_post_boot_reads_a_volatile_journals_record_from_the_chains_log(
    host, log, partial, ok, said
):
    host.write("run/log/journal/" + "a" * 32 + "/system.journal", "x")
    (host.root / RUN).mkdir(parents=True)
    if log is not None:
        host.write(f"{RUN}/reboot-chain.log", log)
    if partial:
        host.write(f"{RUN}/journal/_run_log_journal/system.journal", "x")
    checks = {c["check"]: c for c in host.run("--post-boot")["post_boot"]}
    c = checks["shutdown:journal-copy"]
    assert c["ok"] is ok
    assert said in c["evidence"]


def test_post_boot_without_a_run_says_to_pass_one(host):
    host.write("run/log/journal/" + "a" * 32 + "/system.journal", "x")
    checks = {c["check"]: c for c in host.run("--post-boot")["post_boot"]}
    assert checks["shutdown:journal-copy"]["ok"] is None
    assert "pass --run" in checks["shutdown:journal-copy"]["evidence"]


QURL = "https://q.example:6333"


def _qdrant_after_boot(host, now: dict[str, int], counted: bool = True) -> dict:
    host.knob(f"posture scheduled\ndatastore qdrant qdrant.service qdrant {QURL} -\n")
    rec = "began 1\n"
    if counted:
        rec += f"counts qdrant qdrant.service /{RUN}/qdrant-counts.txt\n"
    host.write(f"{RUN}/recovery-point", rec)
    host.write(f"{RUN}/qdrant-counts.txt", "a 10\nb 20\nc 5\n")
    names = ",".join(f'{{"name":"{c}"}}' for c in now)
    cases = [(f"* {QURL}/collections", f'{{"result":{{"collections":[{names}]}}}}')]
    for c, n in now.items():
        cases.append(
            (f"* {QURL}/collections/{c}/points/count", f'{{"result":{{"count":{n}}}}}')
        )
    for glob, out in cases:
        host.cases["curl"].insert(0, (glob, out + "\n", 0, "", None))
    checks = host.run("--post-boot", "--run", "/" + RUN)["post_boot"]
    return {c["check"]: c for c in checks}["qdrant:qdrant.service"]


@pytest.mark.parametrize(
    "now, ok, said",
    [
        # #367: clients write through the run, so a count moves either way.
        ({"a": 10, "b": 25, "c": 4}, True, "2 counts moved"),
        ({"a": 10, "b": 20}, False, "c (gone; it held 5)"),
        ({"a": 0, "b": 20, "c": 5}, False, "a (emptied; it held 10)"),
    ],
)
def test_post_boot_checks_a_qdrant_against_its_recovery_points_counts(
    host, now, ok, said
):
    c = _qdrant_after_boot(host, now)
    assert c["ok"] is ok
    assert said in c["evidence"]


def test_post_boot_says_a_qdrant_with_no_counts_is_unchecked(host):
    c = _qdrant_after_boot(host, {"a": 10}, counted=False)
    assert c["ok"] is None
    assert "holds no counts of it" in c["evidence"]


# --- a Redis after the boot (#380) ----------------------------------------------
# broker's Redis logs to a file, not journald, so a journal-based check would
# read an empty pass. Lines as Redis 7.0 writes them (measured on noble).

BEFORE = (
    "309128:C 12 Oct 2026 00:00:00.000 # oO0OoO0OoO0Oo Redis is starting oO0OoO0OoO0Oo\n"
    "309128:M 12 Oct 2026 00:00:00.100 * Ready to accept connections tcp\n"
    "309128:M 13 Oct 2026 04:22:08.505 * Saving the final RDB snapshot before exiting.\n"
)
CLEAN_EXIT = (
    "309128:M 13 Oct 2026 04:22:08.540 # Redis is now ready to exit, bye bye...\n"
)
BANNER = (
    "414:C 13 Oct 2026 04:22:18.900 # oO0OoO0OoO0Oo Redis is starting oO0OoO0OoO0Oo\n"
)
LOADED = (
    "414:M 13 Oct 2026 04:22:18.996 * DB loaded from base file appendonly.aof.3.base.rdb: 0.014 seconds\n"
    "414:M 13 Oct 2026 04:22:18.996 * Done loading RDB, keys loaded: 40, keys expired: 0.\n"
)
# A save's child logs as itself: it starts no run.
CHILD = "415:C 13 Oct 2026 04:22:19.000 * DB saved on disk\n"
READY = "414:M 13 Oct 2026 04:22:19.093 * Ready to accept connections tcp\n"
NO_AOF = "414:M 13 Oct 2026 04:22:18.996 * Creating AOF base file appendonly.aof.1.base.rdb on server start\n"


def _redis_after_boot(
    host, log: str, conf: str = "appendonly yes\n", journal: bool = False
) -> dict:
    host.knob("posture scheduled\ndatastore redis redis-server\n")
    if not journal:
        conf += "logfile /var/log/redis/redis-server.log\n"
        host.write("var/log/redis/redis-server.log", log)
    else:
        host.on("journalctl", "-u redis-server.service -o cat --no-pager -n 5000", log)
    host.write("etc/redis/redis.conf", "port 6379\n" + conf)
    host.show(
        "redis-server.service",
        ExecStart="{ path=/usr/bin/redis-server ; argv[]=/usr/bin/redis-server /etc/redis/redis.conf ; }",
        MainPID="414",
    )
    checks = host.run("--post-boot")["post_boot"]
    return {c["check"]: c for c in checks}["redis:redis-server.service"]


@pytest.mark.parametrize(
    "log, conf, ok, said",
    [
        (
            BEFORE + CLEAN_EXIT + BANNER + LOADED + CHILD + READY,
            "appendonly yes\n",
            True,
            "logged a clean shutdown (ready to exit), and process 414 loaded its data",
        ),
        # The process before it was killed: no "ready to exit".
        (
            BEFORE + BANNER + LOADED + READY,
            "appendonly yes\n",
            False,
            'didn\'t log a clean shutdown: its last line in /var/log/redis/redis-server.log was "Saving the final RDB snapshot before exiting."',
        ),
        # Under appendonly yes, a base created at start means no AOF was found.
        (
            BEFORE + CLEAN_EXIT + BANNER + NO_AOF + READY,
            "appendonly yes\n",
            False,
            "found no AOF at its start, so it loaded nothing",
        ),
        (BEFORE + CLEAN_EXIT + BANNER + READY, "", False, 'logged no "DB loaded from"'),
        (
            BEFORE + CLEAN_EXIT + BANNER + LOADED,
            "appendonly yes\n",
            False,
            'hasn\'t logged "Ready to accept connections"',
        ),
        # One that persists nothing loads nothing.
        (
            BEFORE + CLEAN_EXIT + BANNER + READY,
            'save ""\n',
            True,
            "it persists nothing, so it loaded nothing",
        ),
        # Nothing from before it: the shutdown wasn't read.
        (
            BANNER + LOADED + READY,
            "appendonly yes\n",
            None,
            "holds nothing from the process before it",
        ),
        ("", "appendonly yes\n", None, "holds no line from its main process, 414"),
    ],
    ids=[
        "clean",
        "killed",
        "aof-lost",
        "nothing-loaded",
        "not-ready",
        "persists-nothing",
        "no-before",
        "no-lines",
    ],
)
def test_post_boot_reads_a_redis_from_its_own_log(host, log, conf, ok, said):
    c = _redis_after_boot(host, log, conf)
    assert c["ok"] is ok, c
    assert said in c["evidence"]


def test_post_boot_reads_a_redis_that_logs_to_the_journal_there(host):
    c = _redis_after_boot(
        host, BEFORE + CLEAN_EXIT + BANNER + LOADED + READY, journal=True
    )
    assert c["ok"] is True, c
    assert "in redis-server.service's journal" in c["evidence"]


def test_post_boot_starts_a_redis_run_at_its_banner_when_its_pid_comes_round(host):
    # The PID before the boot was 414 too, and that run loaded its data:
    # this one, from its banner on, loaded nothing.
    before = (
        BANNER + "414:M 12 Oct 2026 00:00:00.050 * DB loaded from disk: 0.001 seconds\n"
    )
    before += READY + CLEAN_EXIT.replace("309128:", "414:")
    c = _redis_after_boot(host, before + BANNER + READY, conf="")
    assert c["ok"] is False, c
    assert 'logged no "DB loaded from"' in c["evidence"]


# --- a data store's own dependency (#384) ----------------------------------------
# broker's Redis binds the tailnet address, so it needs tailscaled up first.


@pytest.mark.parametrize(
    "after, finds",
    [("network.target tailscaled.service", False), ("network.target", True)],
    ids=["after-it", "not-after-it"],
)
def test_a_datastore_with_no_after_on_what_it_depends_on_is_a_finding(
    host, after, finds
):
    host.knob(
        "posture scheduled\ndatastore redis redis-server\ndepends redis-server tailscaled\n"
    )
    host.show("redis-server.service", After=after)
    out = host.run()
    assert out["impact"]["depends"] == [
        {
            "datastore": "redis-server.service",
            "unit": "tailscaled.service",
            "after": not finds,
        }
    ]
    hit = "depends:redis-server.service:tailscaled.service" in _ids(out)
    assert hit is finds
    # Not a service: nothing is held to ordering on the data store.
    assert not [i for i in _ids(out) if i.startswith("ordering:")]


def test_a_depends_line_naming_no_datastore_is_a_knob_finding(host):
    host.knob("posture scheduled\ndepends redis-server tailscaled\n")
    out = host.run()
    f = _finding(out, "depends:redis-server.service:tailscaled.service")
    assert "which no datastore line declares" in f["message"]


# --- a Redis whose config sets the users (#458) -----------------------------------
# Host 6's knob named no user for its Redis, whose redis.conf set an inline
# user line: the recovery point refused it, three hours before the window,
# and no probe before it had said so.

REDIS_USER_LINE = "user default on >other ~* +@all\n"
REDIS_ACLFILE = "aclfile /etc/redis/users.acl\n"


@pytest.mark.parametrize(
    "line, conf, extra, cause",
    [
        # Nothing covers it: the recovery point's dump needs a login.
        ("redis-server", REDIS_USER_LINE, "", "a user line in /etc/redis/redis.conf"),
        ("redis-server", REDIS_ACLFILE, "", "its aclfile"),
        # A backup line covers its dump, and its stop doesn't persist it, so
        # the chain must SAVE it.
        (
            "redis-server",
            REDIS_USER_LINE + 'save ""\n',
            "backup redis-backup.timer redis-server\n",
            "a user line in /etc/redis/redis.conf",
        ),
        # A user on the line, nothing setting the users, or a backup line
        # with save points: nothing refuses.
        ("redis-server ops /etc/redis/ops.key", REDIS_USER_LINE, "", None),
        ("redis-server", "requirepass mine\n", "", None),
        (
            "redis-server",
            REDIS_USER_LINE,
            "backup redis-backup.timer redis-server\n",
            None,
        ),
    ],
    ids=["user-line", "aclfile", "chain-save", "has-user", "no-users", "covered"],
)
def test_a_redis_line_with_no_user_where_its_config_sets_the_users_is_a_finding(
    host, line, conf, extra, cause
):
    host.knob(f"posture scheduled\ndatastore redis {line}\n{extra}")
    host.write("etc/redis/redis.conf", "port 6379\nrequirepass nobodys\n" + conf)
    host.show(
        "redis-server.service",
        ExecStart="{ path=/usr/bin/redis-server ; argv[]=/usr/bin/redis-server /etc/redis/redis.conf ; }",
    )
    out = host.run()
    fid = "redis-login:redis-server.service"
    if cause is None:
        assert fid not in _ids(out)
        return
    f = _finding(out, fid)
    assert f["kind"] == "knob"
    assert f"{cause} sets the users" in f["message"]
    # The fix, in the knob's own words.
    assert "datastore redis redis-server <user> <key-file>" in f["message"]


def test_a_redis_whose_config_includes_another_file_says_its_users_are_unread(host):
    host.knob("posture scheduled\ndatastore redis redis-server\n")
    host.write(
        "etc/redis/redis.conf",
        "port 6379\nrequirepass nobodys\ninclude /etc/redis/local.conf\n",
    )
    host.show(
        "redis-server.service",
        ExecStart="{ path=/usr/bin/redis-server ; argv[]=/usr/bin/redis-server /etc/redis/redis.conf ; }",
    )
    out = host.run()
    assert "redis-login:redis-server.service" not in _ids(out)
    assert any(
        "redis-server.service" in n and "/etc/redis/redis.conf includes" in n
        for n in out["not_read"]
    ), out["not_read"]


@pytest.mark.parametrize(
    "ts, state, ok",
    [
        (5_000_000, "active", True),
        (9_000_000, "active", False),
        (5_000_000, "inactive", False),
    ],
    ids=["first", "after-it", "down"],
)
def test_post_boot_checks_a_dependency_came_up_before_its_datastore(
    host, ts, state, ok
):
    host.knob(
        "posture scheduled\ndatastore redis redis-server\ndepends redis-server tailscaled\n"
    )
    host.show("redis-server.service", ActiveEnterTimestampMonotonic="7000000")
    host.show(
        "tailscaled.service", ActiveState=state, ActiveEnterTimestampMonotonic=str(ts)
    )
    checks = {c["check"]: c for c in host.run("--post-boot")["post_boot"]}
    c = checks["depends:redis-server.service:tailscaled.service"]
    assert c["ok"] is ok, c


# #534 finding 2: the knob's exception for a missing After= covers the same
# reading after the boot, as it does before a run. A down dependency is no
# ordering at all, so nothing excepts it.
@pytest.mark.parametrize(
    "review, excepted", [("2099-01-01", True), ("2026-01-01", False)]
)
def test_post_boot_honours_an_ordering_exception(host, review, excepted):
    host.knob(
        "posture scheduled\nservice app-web.service\n"
        "datastore postgres postgresql@16-main app\n"
        f"exception ordering:app-web.service {review} it retries until the store is up\n"
    )
    host.show(
        "app-web.service",
        ActiveState="active",
        NRestarts="0",
        Result="success",
        After="network.target",
    )
    out = host.run("--post-boot")
    checks = {c["check"]: c for c in out["post_boot"]}
    assert checks["ordering:app-web.service"]["ok"] is False
    key = "excepted" if excepted else "findings"
    f = _finding(out, "post-boot:ordering:app-web.service", key)
    assert f["exception_what"] == "ordering:app-web.service"
    if excepted:
        assert "post-boot:ordering:app-web.service" not in _ids(out)
        assert f["exception_line"] == 4


@pytest.mark.parametrize(
    "state, ts, excepted",
    [("active", 9_000_000, True), ("inactive", 5_000_000, False)],
    ids=["after-it", "down"],
)
def test_post_boot_honours_a_depends_exception_only_for_the_order(
    host, state, ts, excepted
):
    host.knob(
        "posture scheduled\ndatastore redis redis-server\ndepends redis-server tailscaled\n"
        "exception depends:redis-server.service:tailscaled.service 2099-01-01 binds 0.0.0.0\n"
    )
    host.show("redis-server.service", ActiveEnterTimestampMonotonic="7000000")
    host.show(
        "tailscaled.service", ActiveState=state, ActiveEnterTimestampMonotonic=str(ts)
    )
    out = host.run("--post-boot")
    fid = "post-boot:depends:redis-server.service:tailscaled.service"
    assert (fid in _ids(out, "excepted")) is excepted
    assert (fid in _ids(out)) is not excepted


# --- what the probe changes (#423, #490, #501) ---------------------------------


def test_a_recovery_line_runs_only_after_a_boot(host):
    # A health line runs at every probe; a recovery line, with its real
    # request and new row, never does before a run.
    marker = host.tmp / "recovered"
    host.knob(f"posture scheduled\nrecovery touch {marker}\nrecovery false\n")
    out = host.run()
    assert not marker.exists()
    assert not [i for i in _ids(out) if "recovery" in i]
    out = host.run("--post-boot")
    assert marker.exists()
    checks = {c["check"]: c for c in out["post_boot"]}
    assert checks["recovery:2"]["ok"] is True
    assert checks["recovery:3"]["ok"] is False
    assert "exits 1" in checks["recovery:3"]["evidence"]
    assert "post-boot:recovery:3" in _ids(out)


def test_no_sudo_reads_nothing_through_sudo(host):
    assert host.run()["probe"]["privilege"] == "sudo"
    host.log.unlink()
    out = host.run("--no-sudo")
    assert out["probe"]["privilege"] == "none"
    assert not host.calls("sudo")
    [n] = [n for n in out["not_read"] if n.startswith("root-only readings")]
    assert "--no-sudo" in n


def test_help_names_no_sudo_and_what_the_probe_writes():
    r = subprocess.run(
        ["bash", str(PROBE), "--help"], capture_output=True, text=True, env=_clean_env()
    )
    text = " ".join(r.stdout.split())
    assert "--no-sudo" in text
    assert "probe.privilege" in text
    assert "/var/log/ubuntu-advantage.log" in text


# pro security-status as root appends to its log and takes its lock: under
# systemd's ProtectSystem=strict it exits 1 within ~3 s, a traceback ending
# in EROFS (exe.dev, ubuntu-pro-client 37.2, 2026-10-26).
EROFS = (
    "Traceback (most recent call last):\n"
    '  File "/usr/lib/python3/dist-packages/uaclient/log.py", line 1, in emit\n'
    "OSError: [Errno 30] Read-only file system: '/var/log/ubuntu-advantage.log'\n"
)


@pytest.mark.parametrize(
    "stderr, read_only",
    [(EROFS, True), ("Failed to connect to the contract server\n", False)],
    ids=["read-only", "other"],
)
def test_a_pro_read_a_read_only_filesystem_stopped_says_so(host, stderr, read_only):
    host.on("pro", "security-status --format json", rc=1, stderr=stderr)
    out = host.run()
    assert out["pending"]["esm"] is None
    [n] = [n for n in out["not_read"] if n.startswith("Ubuntu Pro / ESM")]
    assert ("read-only filesystem" in n) is read_only
    if not read_only:
        assert "couldn't be read" in n


def test_post_boot_reads_the_run_it_is_given(host):
    host.write("run/log/journal/" + "a" * 32 + "/system.journal", "x")
    host.write(f"{RUN}/reboot-chain.log", COPIED)
    other = "var/backups/patching-hosts-20261001T000000Z"
    host.write(f"{other}/reboot-chain.log", FAILED)
    checks = {
        c["check"]: c
        for c in host.run("--post-boot", "--run", "/" + other)["post_boot"]
    }
    assert checks["shutdown:journal-copy"]["ok"] is False
    r = host.run("--run", "/" + RUN, rc=2)
    assert "--run" in r.stderr


@pytest.mark.parametrize(
    "props, ok",
    [
        ({"NextElapseUSecRealtime": "@1790000000"}, True),
        # #363: OnBootSec=/OnUnitActiveSec= leave the realtime elapse empty.
        (
            {
                "NextElapseUSecRealtime": "",
                "NextElapseUSecMonotonic": "12min 30.192576s",
            },
            True,
        ),
        ({"NextElapseUSecRealtime": "", "NextElapseUSecMonotonic": "0"}, False),
        # CR 211: a stopped timer reads infinity (systemd 255).
        (
            {"NextElapseUSecRealtime": "", "NextElapseUSecMonotonic": "infinity"},
            False,
        ),
    ],
)
def test_post_boot_reads_a_monotonic_restarter_timer_as_scheduled(host, props, ok):
    host.knob("posture scheduled\nrestarter app-health.timer\n")
    host.show("app-health.timer", ActiveState="active", **props)
    checks = {c["check"]: c for c in host.run("--post-boot")["post_boot"]}
    assert checks["timer:app-health.timer"]["ok"] is ok


def test_post_boot_checks_fail_on_a_restarted_service_and_a_pending_reboot(host):
    host.knob(
        "posture scheduled\nservice app-web.service\nrestarter app-health.timer\ndatastore postgres postgresql@16-main app\n"
    )
    host.show(
        "app-web.service",
        ActiveState="active",
        NRestarts="2",
        Result="success",
        After="postgresql.service",
    )
    host.show(
        "app-health.timer", ActiveState="active", NextElapseUSecRealtime="@1790000000"
    )
    host.write("run/reboot-required", "")
    host.knob(host.knob_path.read_text() + "health true\nhealth false\n")
    host.on(
        "systemctl",
        "list-units --failed*",
        "app-old.service loaded failed failed Old app\n",
    )
    out = host.run("--post-boot")
    checks = {c["check"]: c for c in out["post_boot"]}
    assert checks["service:app-web.service"]["ok"] is False
    assert checks["ordering:app-web.service"]["ok"] is True
    assert checks["restarter:app-health.timer"]["ok"] is True
    assert checks["timer:app-health.timer"]["ok"] is True
    assert checks["reboot-required"]["ok"] is False
    assert (checks["health:5"]["ok"], checks["health:6"]["ok"]) == (True, False)
    assert checks["failed-units"] == {
        "check": "failed-units",
        "ok": False,
        "evidence": "app-old.service",
    }
    assert {
        "post-boot:service:app-web.service",
        "post-boot:reboot-required",
        "post-boot:health:6",
        "post-boot:failed-units",
    } <= set(_ids(out))
    assert "updates" not in out and "dormant" not in out


@pytest.mark.parametrize(
    "journal, ok",
    [
        (
            "Starting app-web.service - App...\n"
            "app-web.service: Main process exited, code=exited, status=1/FAILURE\n"
            "app-web.service: Failed with result 'exit-code'.\n"
            "Starting app-web.service - App...\n"
            "Started app-web.service - App.\n",
            False,
        ),
        ("Starting app-web.service - App...\nStarted app-web.service - App.\n", True),
        ("app-web: Starting the server\n", None),
    ],
)
def test_post_boot_reads_the_first_start_from_the_journal_not_nrestarts(
    host, journal, ok
):
    # Started by hand after a failed first start, the service is active with
    # 0 automatic restarts. It has stopped since it started, so only the
    # journal tells a failure from a stop by hand. App lines that merely say
    # "Starting" aren't PID 1's.
    host.knob("posture scheduled\nservice app-web.service\n")
    host.show(
        "app-web.service",
        ActiveState="active",
        NRestarts="0",
        Result="success",
        After="network.target",
        InactiveExitTimestamp=f"@{host.now - 600}",
        InactiveEnterTimestamp=f"@{host.now - 590}",
    )
    host.on("journalctl", "-b 0 -u app-web.service*", journal)
    out = host.run("--post-boot")
    checks = {c["check"]: c for c in out["post_boot"]}
    assert checks["service:app-web.service"]["ok"] is ok
    assert ("post-boot:service:app-web.service" in _ids(out)) is (ok is False)


@pytest.mark.parametrize("stopped, ok", [(False, True), (True, None)])
def test_post_boot_reads_the_first_start_from_its_timestamps_without_the_journal(
    host, stopped, ok
):
    # On exeuntu PID 1 logs to the console, so the journal has none of its
    # lines. A unit that started and never stopped or failed has no
    # InactiveEnterTimestamp (systemd 255); one that did can't be told apart.
    host.knob("posture scheduled\nservice app-web.service\n")
    host.show(
        "app-web.service",
        ActiveState="active",
        NRestarts="0",
        Result="success",
        After="network.target",
        InactiveExitTimestamp=f"@{host.now - 600}",
        InactiveEnterTimestamp=f"@{host.now - 590}" if stopped else "",
    )
    host.on("journalctl", "-b 0 -u app-web.service*", "app-web: listening on :8080\n")
    out = host.run("--post-boot")
    checks = {c["check"]: c for c in out["post_boot"]}
    assert checks["service:app-web.service"]["ok"] is ok
