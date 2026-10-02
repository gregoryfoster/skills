"""patching-hosts' pruning: `prune-plan.sh` and `prune.sh` (#313, plan step 6b).

The step 0 round found dormant components: Docker with no containers, an
inactive nginx in six hosts' security sets, a pre-cutover Postgres. A prune
runs disable, then remove, then purge, each after the last one's soak, and a
savepoint lets the purge skip the remove. prune-plan.sh reads what a prune
would take; prune.sh runs one stage on exactly what the plan names.

What this file pins, against the plan's step 6b list:

- each refusal;
- a disable covers docker.socket as well as docker.service;
- the drift refusal when the simulated set changes;
- no command outside the approved set runs.

Beyond that list:

- the plan: units with sockets first, a template's loaded instances, what a
  removal and a purge take and drag along, what a later autoremove would
  take, what else depends
  on them, the purge scripts' deleting lines, debconf's answers, paths with
  sizes, the group and its members, the residue, and the stage the knob
  declares;
- the calendar: each stage after the last one's review-by date, and a
  savepoint that lets the purge follow the disable;
- each apt command names the plan's packages, never autoremoves, and runs
  with needrestart in list mode;
- a data path goes only by --purge-data, and only one the plan names;
- the group's members dropped, and the group deleted at the purge;
- a component from outside apt is disabled, and removed by hand.

Each case runs from a copy of the skill's scripts, against a fake host: one
script answers dpkg-query, apt-get, systemctl and the rest from a JSON state
that apt-get, systemctl and gpasswd change.
"""

import copy
import json
import subprocess

import pytest

from tests.structural.patching_hosts_rig import DAY, SKILL, dispatcher
from tests.structural.patching_hosts_rig import clean_env as _clean_env
from tests.structural.test_patching_hosts_apply import TUE_1530
from tests.structural.test_patching_hosts_apply import Host as ApplyHost

PLAN = SKILL / "scripts" / "prune-plan.sh"
PRUNE = SKILL / "scripts" / "prune.sh"
TODAY = "2026-09-29"
PAST = "2026-09-28"
FUTURE = "2026-10-29"

# One script for every command the scripts ask the host, over a JSON state.
FAKE = r"""
import fnmatch, json, os, sys
state = sys.argv[1]
db = json.load(open(state))
pk, units = db["packages"], db["units"]
cmd, args = sys.argv[2], sys.argv[3:]


def save():
    with open(state, "w") as f:
        json.dump(db, f)


def after(flag):
    return args[args.index(flag) + 1]


if cmd == "dpkg-query":
    if args[0] == "-W" and "Conffiles" in args[2]:
        for n in args[3:]:
            for f in pk.get(n, {}).get("conffiles", []):
                print(" %s %s" % (f, "0" * 32))
            print("")
    elif args[0] == "-W":
        for n in sorted(pk):
            p = pk[n]
            print("%s |%s|%s" % (p["state"], n, p["version"]))
    elif args[0] == "-L":
        p = pk.get(args[1])
        if not p or p["state"] not in ("ii", "hi"):
            sys.exit(1)
        print("\n".join(p.get("files", [])))
    elif args[0] == "--control-show":
        p = pk.get(args[1])
        if not p or "postrm" not in p:
            sys.exit(1)
        sys.stdout.write(p["postrm"])
    sys.exit(0)
if cmd == "apt-cache":
    print(args[-1])
    print("Reverse Depends:")
    for n in sorted(pk):
        if args[-1] in pk[n].get("depends", []) and pk[n]["state"] in ("ii", "hi"):
            print("  " + n)
    sys.exit(0)
if cmd == "apt-get":
    sim = "-s" in args
    # What autoremove takes already: apt lists it as "no longer required"
    # after any removal too.
    gone = db.get("autoremovable", [])
    if "autoremove" in args:
        for n in gone:
            print("Remv %s [1.0]" % n)
        sys.exit(0)
    kind = next(a for a in args if a in ("remove", "purge"))
    names, skip = [], False
    for a in args[args.index(kind) + 1:]:
        if skip:
            skip = False
        elif a == "-o":
            skip = True
        elif not a.startswith("-"):
            names.append(a)
    want = []
    for n in names:
        for m in [n] + pk.get(n, {}).get("drags", []):
            if m not in want:
                want.append(m)
    if not sim and db.get("fail"):
        print("E: " + db["fail"], file=sys.stderr)
        sys.exit(100)
    # As apt does: -s takes a held package, -y doesn't.
    held = [n for n in want if pk.get(n, {}).get("state") == "hi"]
    if not sim and held and "--allow-change-held-packages" not in args:
        print(
            "E: Held packages were changed and -y was used without "
            "--allow-change-held-packages.",
            file=sys.stderr,
        )
        sys.exit(100)
    if sim:
        orphans = gone + [o for n in want for o in pk.get(n, {}).get("orphans", [])]
        if orphans:
            print(
                "The following packages were automatically installed and are"
                " no longer required:"
            )
            print("  " + " ".join(orphans))
            print("Use 'apt autoremove' to remove them.")
        for n in db.get("installs", []):
            print("Inst %s (1.0 Ubuntu:24.04/noble [amd64])" % n)
    for n in want:
        p = pk.get(n)
        if not p or not (p["state"] in ("ii", "hi") or (kind == "purge" and p["state"] == "rc")):
            continue
        if sim:
            print("%s %s [%s]" % ("Remv" if kind == "remove" else "Purg", n, p["version"]))
        elif n in db.get("keeps", []):
            continue
        elif kind == "remove":
            p["state"] = "rc"
            print("Removing %s (%s) ..." % (n, p["version"]))
        else:
            del pk[n]
            print("Purging configuration files for %s ..." % n)
    if not sim:
        for n in db.get("also_takes", []):
            pk.pop(n, None)
        db.setdefault("apt_env", []).append(
            "%s %s %s" % (kind, os.environ.get("DEBIAN_FRONTEND", ""), os.environ.get("NEEDRESTART_MODE", ""))
        )
        save()
    sys.exit(0)
if cmd == "systemctl":
    verb = args[0]
    if verb == "show":
        u = units.get(args[-1])
        props = [args[i + 1] for i, a in enumerate(args) if a == "-p"]
        vals = {
            "LoadState": "loaded" if u else "not-found",
            "ActiveState": u["active"] if u else "inactive",
            "UnitFileState": u["enabled"] if u else "",
            "FragmentPath": u["fragment"] if u else "",
        }
        for p in props:
            print("%s=%s" % (p, vals.get(p, "")))
        sys.exit(0)
    if verb == "list-units":
        for n in sorted(units):
            if fnmatch.fnmatch(n, args[-1]):
                print("%s loaded %s running x" % (n, units[n]["active"]))
        sys.exit(0)
    named = args[args.index("--") + 1:] if "--" in args else args[-1:]
    if any(n not in units for n in named):
        sys.exit(5)
    for u in (units[n] for n in named):
        if verb == "stop":
            u["active"] = "inactive"
        elif verb == "disable":
            if u["enabled"] != "masked":
                u["enabled"] = "disabled"
        elif verb == "mask":
            if u["fragment"].startswith("/etc/systemd/system/"):
                print("Failed to mask unit: File %s already exists." % u["fragment"], file=sys.stderr)
                sys.exit(1)
            u["enabled"] = "masked"
        elif verb == "is-enabled":
            print(u["enabled"])
            sys.exit(0)
        elif verb == "is-active":
            print(u["active"])
            sys.exit(0 if u["active"] == "active" else 3)
        else:
            sys.exit(1)
    save()
    sys.exit(0)
if cmd == "getent":
    g = db["groups"].get(args[-1])
    if g is None:
        sys.exit(2)
    print("%s:x:106:%s" % (args[-1], ",".join(g)))
    sys.exit(0)
if cmd == "gpasswd":
    db["groups"][args[-1]].remove(args[-2])
    save()
    sys.exit(0)
if cmd == "groupdel":
    db["groups"].pop(args[-1])
    save()
    sys.exit(0)
if cmd == "du":
    k = db["paths"].get(args[-1])
    if k is None:
        sys.exit(1)
    print("%s\t%s" % (k, args[-1]))
    sys.exit(0)
if cmd == "pg_lsclusters":
    if db.get("clusters") is None:
        sys.exit(1)
    for v, c, d in db["clusters"]:
        print("%s %s 5432 online postgres %s /var/log/postgresql/%s.log" % (v, c, d, c))
    sys.exit(0)
if cmd == "debconf-show":
    for n in args:
        for line in db.get("debconf", {}).get(n, []):
            print(line)
    sys.exit(0)
if cmd == "tar":
    if db.get("tar_fail"):
        print("tar: " + db["tar_fail"], file=sys.stderr)
        sys.exit(2)
    open(after("-cf"), "w").close()
    sys.exit(0)
sys.exit(1)
"""

FAKED = (
    "dpkg-query",
    "apt-get",
    "apt-cache",
    "systemctl",
    "getent",
    "gpasswd",
    "groupdel",
    "du",
    "debconf-show",
    "tar",
    "pg_lsclusters",
)
# What changes the host, as the stub log records it.
MUTATING = ("apt-get", "gpasswd", "groupdel", "rm", "tar")
SYSTEMCTL_MUTATING = ("stop", "disable", "mask", "start", "enable", "unmask", "restart")


def _unit(fragment: str, enabled: str = "enabled", active: str = "active") -> dict:
    return {"enabled": enabled, "active": active, "fragment": fragment}


LIB = "/usr/lib/systemd/system/"
DOCKER = {
    "packages": {
        "containerd": {
            "state": "ii",
            "version": "2.2.1",
            "files": [LIB + "containerd.service"],
        },
        "docker.io": {
            "state": "ii",
            "version": "29.1.3",
            "files": [
                LIB + "docker.service",
                LIB + "docker.socket",
                LIB + "multi-user.target.wants/docker.service",
                "/usr/bin/dockerd",
            ],
            "postrm": '#!/bin/sh\nif [ "$1" = purge ]; then\n    rm -f /etc/apparmor.d/local/docker.io || true\nfi\n',
        },
        "runc": {"state": "ii", "version": "1.3.4"},
        "openssh-server": {
            "state": "ii",
            "version": "1:9.6",
            "files": [LIB + "ssh.service"],
        },
    },
    "units": {
        "docker.service": _unit(LIB + "docker.service"),
        "docker.socket": _unit(LIB + "docker.socket"),
        "containerd.service": _unit(LIB + "containerd.service"),
        "ssh.service": _unit(LIB + "ssh.service"),
    },
    "groups": {"docker": ["exedev"]},
    "paths": {"/etc/docker": 4, "/var/lib/docker": 184, "/var/lib/containerd": 96},
    "debconf": {"docker.io": ["  docker.io/restart: false"]},
}
NGINX = {
    "packages": {
        "nginx": {
            "state": "ii",
            "version": "1.24.0",
            "depends": ["nginx-common"],
        },
        "nginx-common": {
            "state": "ii",
            "version": "1.24.0",
            "files": [LIB + "nginx.service"],
            "drags": ["nginx"],
            # /etc/init.d/nginx is gone from this host.
            "conffiles": [
                "/etc/default/nginx",
                "/etc/init.d/nginx",
                "/etc/logrotate.d/nginx",
                "/etc/nginx/nginx.conf",
            ],
            "postrm": '#!/bin/sh\nif [ "$1" = purge ]; then\n    rm -rf /var/lib/nginx /var/log/nginx /etc/nginx\nfi\n',
        },
    },
    "units": {"nginx.service": _unit(LIB + "nginx.service")},
    "groups": {},
    "paths": {
        "/etc/nginx": 84,
        "/var/www": 12,
        "/var/log/nginx": 8,
        "/etc/nginx/nginx.conf": 4,
        "/etc/default/nginx": 4,
        "/etc/logrotate.d/nginx": 4,
    },
}
POSTGRES = {
    "packages": {
        "postgresql": {
            "state": "ii",
            "version": "16+257",
            "depends": ["postgresql-16"],
        },
        "postgresql-16": {
            "state": "ii",
            "version": "16.2",
            "postrm": '#!/bin/sh\n    rm -rf "/var/lib/postgresql/$VERSION/$1/"\n',
        },
        "postgresql-common": {
            "state": "ii",
            "version": "257",
            "files": [LIB + "postgresql.service", LIB + "postgresql@.service"],
        },
        "postgresql-client-16": {
            "state": "ii",
            "version": "16.2",
            "depends": ["postgresql-16"],
        },
    },
    "units": {
        "postgresql.service": _unit(LIB + "postgresql.service"),
        "postgresql@16-main.service": _unit(LIB + "postgresql@.service"),
    },
    "groups": {},
    "paths": {
        "/etc/postgresql": 72,
        "/etc/postgresql-common": 12,
        "/var/lib/postgresql": 39468,
    },
    "debconf": {"postgresql-16": ["* postgresql-16/postrm_purge_data: true"]},
    "clusters": [["16", "main", "/var/lib/postgresql/16/main"]],
}
OLLAMA = {
    "packages": {},
    "units": {"ollama.service": _unit("/etc/systemd/system/ollama.service")},
    "groups": {"ollama": ["exedev"]},
    "paths": {"/usr/local/bin/ollama": 51200, "/usr/share/ollama": 10},
}


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


class Host(ApplyHost):
    STUBBED = (
        *ApplyHost.STUBBED,
        "pgrep",
        "getent",
        "gpasswd",
        "groupdel",
        "du",
        "debconf-show",
        "tar",
        "rm",
        "sha256sum",
    )
    FALLBACKS = {
        **ApplyHost.FALLBACKS,
        # Nothing is running, unless a case says so.
        "pgrep": "exit 1",
        "sha256sum": (
            "for x in /usr/bin/sha256sum /sbin/sha256sum; do "
            '[ -x "$x" ] && exec "$x" "$@"; done; exec shasum -a 256 "$@"'
        ),
        # Only the test's own files are really removed: the scripts' scratch
        # directories. Anything else is recorded, and left.
        "rm": (
            'case "$*" in *"$TMPDIR"* | *"/prune-run/"*) exec /bin/rm "$@" ;; esac\n'
            "exit 0"
        ),
    }

    def __init__(self, tmp_path, fixture: dict, **kw):
        super().__init__(tmp_path, **kw)
        self.db = self.state / "host.json"
        self.fake = self.tmp / "fakehost.py"
        self.fake.write_text(FAKE)
        self.host_state = copy.deepcopy(fixture)
        for cmd in FAKED:
            self.on(
                cmd, "*", script=f'exec python3 "{self.fake}" "{self.db}" {cmd} "$@"'
            )
        self.on("dpkg", "--audit", "")
        self.knob("class production\nposture scheduled\n")
        self.run_dir = tmp_path / "prune-run"

    def write_state(self) -> None:
        self.db.write_text(json.dumps(self.host_state))

    def read_state(self) -> dict:
        return json.loads(self.db.read_text())

    def declare(self, *lines: str) -> "Host":
        self.knob(
            "class production\nposture scheduled\n"
            + "".join(f"exception {line}\n" for line in lines)
        )
        return self

    def _run(self, cmd: list[str], rc: int) -> dict:
        self.cases["date"] = [("+%s", f"{self.clock}\n", 0, "", None)]
        self.write_state()
        r = self.execute(
            [
                *cmd,
                "--config",
                str(self.knob_path),
                "--host",
                "web-1",
                "--today",
                TODAY,
            ],
            rc,
        )
        self.host_state = self.read_state()
        return json.loads(r.stdout if rc else self.result.stdout)

    def plan(self, component: str, *args: str, rc: int = 0) -> dict:
        out = self.tmp / f"{component}.plan"
        out.unlink(missing_ok=True)
        cmd = [
            "bash",
            str(self.scripts / "prune-plan.sh"),
            "--component",
            component,
            "--out",
            str(out),
            *args,
        ]
        return self._run(cmd, rc)

    def prune(
        self,
        stage: str,
        *args: str,
        rc: int = 0,
        approve: bool = True,
        component: str = "",
    ) -> dict:
        plan = self.tmp / f"{component or self.component}.plan"
        cmd = [
            "bash",
            str(self.scripts / "prune.sh"),
            "--stage",
            stage,
            "--plan",
            str(plan),
        ]
        cmd += ["--run", str(self.run_dir), *args]
        if approve:
            cmd.append("--approve")
        return self._run(cmd, rc)

    def changes(self) -> list[str]:
        """Every call that changed the host, as its stub saw it."""
        out = []
        for name, a, _ in self.calls():
            if name in MUTATING and not (name == "apt-get" and a.startswith("-s ")):
                if name == "rm" and str(self.tmpdir) in a:
                    continue
                out.append(f"{name} {a}")
            elif name == "systemctl" and a.split(" ")[0] in SYSTEMCTL_MUTATING:
                out.append(f"{name} {a}")
        return out


def _host(tmp_path, fixture: dict, component: str) -> Host:
    h = Host(tmp_path, fixture)
    h.component = component
    return h


def _ran(out: dict) -> list[str]:
    """The actions as the stubs see them: env's assignments are env's."""
    env = "env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l "
    return [
        a.removeprefix(env)
        for a in out["actions"]
        if not a.startswith(("mkdir ", "write "))
    ]


# --- the command lines ----------------------------------------------------------


def test_help_names_the_stages_and_the_exit_codes():
    for script, words in (
        (
            PLAN,
            ("--component", "--out", "apt-get -s remove", "debconf", "2 usage error"),
        ),
        (
            PRUNE,
            (
                "disable",
                "savepoint",
                "remove",
                "purge",
                "--purge-data",
                "never an autoremove",
                "3 refused",
            ),
        ),
    ):
        r = subprocess.run(
            ["bash", str(script), "--help"],
            capture_output=True,
            text=True,
            env=_clean_env(),
        )
        assert r.returncode == 0
        text = " ".join(r.stdout.split())
        for word in words:
            assert word in text, (script.name, word)


@pytest.mark.parametrize(
    "script, args, message",
    [
        (PLAN, [], "--component is required"),
        (PLAN, ["--component", "apache2"], "one the probe knows"),
        (PRUNE, ["--plan", "p"], "--stage takes"),
        (PRUNE, ["--stage", "disable"], "--plan FILE is required"),
        (
            PRUNE,
            ["--stage", "disable", "--plan", "p", "--purge-data", "/var/www"],
            "belong to --stage purge",
        ),
        (
            PRUNE,
            ["--stage", "purge", "--plan", "p", "--purge-data", "var/www"],
            "absolute paths",
        ),
        # An action runs as the words of its line.
        (
            PRUNE,
            ["--stage", "savepoint", "--plan", "p", "--run", "/var/backups/a b"],
            "--run takes a path without whitespace",
        ),
    ],
)
def test_usage_errors_exit_2(script, args, message):
    r = subprocess.run(
        ["bash", str(script), *args], capture_output=True, text=True, env=_clean_env()
    )
    assert r.returncode == 2
    assert message in r.stderr


# --- the plan --------------------------------------------------------------------


def test_the_plan_names_every_unit_package_path_and_member(tmp_path):
    host = _host(tmp_path, DOCKER, "docker")
    out = host.plan("docker")
    # The socket first: stopped after the service, it would start it again.
    assert [u["unit"] for u in out["units"]] == [
        "docker.socket",
        "containerd.service",
        "docker.service",
    ]
    assert out["units"][0] == {
        "unit": "docker.socket",
        "active": "active",
        "enabled": "enabled",
        "file": LIB + "docker.socket",
    }
    pk = out["packages"]
    assert pk["roots"] == ["containerd", "docker.io", "runc"]
    assert [p["package"] for p in pk["remove"]] == ["containerd", "docker.io", "runc"]
    assert pk["remove"][1]["version"] == "29.1.3"
    assert [p["text"] for p in out["purge_scripts"]] == [
        "rm -f /etc/apparmor.d/local/docker.io || true"
    ]
    assert out["debconf"] == ["docker.io/restart: false"]
    assert out["paths"] == [
        {"kind": "config", "path": "/etc/docker", "kib": 4},
        {"kind": "data", "path": "/var/lib/docker", "kib": 184},
        {"kind": "data", "path": "/var/lib/containerd", "kib": 96},
    ]
    assert out["group"] == {"name": "docker", "exists": True, "members": ["exedev"]}
    assert out["stage"]["declared"] == "none" and out["stage"]["next"] == "disable"
    # Nothing outside the component: ssh stays out of every list.
    assert "ssh" not in json.dumps(out)
    assert host.changes() == []
    plan = (tmp_path / "docker.plan").read_text().splitlines()
    assert plan[:3] == ["patching-hosts prune plan", "component docker", "host web-1"]
    assert "member docker exedev" in plan and "unit docker.socket" in plan
    assert oct((tmp_path / "docker.plan").stat().st_mode & 0o777) == "0o600"


def test_the_plan_shows_what_a_purge_drags_along_and_deletes(tmp_path):
    host = _host(tmp_path, POSTGRES, "postgres")
    out = host.plan("postgres")
    # A template's loaded instance stands in for it.
    assert [u["unit"] for u in out["units"]] == [
        "postgresql.service",
        "postgresql@16-main.service",
    ]
    assert out["reverse_depends"] == [
        {"package": "postgresql-client-16", "depends_on": "postgresql-16"}
    ]
    # Its purge script takes the cluster's data, unless debconf says not to.
    assert [p["text"] for p in out["purge_scripts"]] == [
        'rm -rf "/var/lib/postgresql/$VERSION/$1/"'
    ]
    assert out["debconf"] == ["postgresql-16/postrm_purge_data: true"]
    # postgresql-common's purge script deletes its createcluster.conf.
    assert {"kind": "config", "path": "/etc/postgresql-common", "kib": 12} in out[
        "paths"
    ]

    (tmp_path / "n").mkdir()
    host = _host(tmp_path / "n", NGINX, "nginx")
    out = host.plan("nginx")
    assert [p["package"] for p in out["packages"]["purge"]] == ["nginx", "nginx-common"]


@pytest.mark.parametrize(
    "lines, next_stage",
    [
        ([], "disable"),
        ([f"disabled:nginx {FUTURE} soaking"], "savepoint"),
        ([f"disabled:nginx {PAST} soaked"], "remove, or savepoint then purge"),
        ([f"removed:nginx {FUTURE} soaking"], None),
        ([f"removed:nginx {PAST} soaked"], "purge"),
        ([f"keep:nginx {FUTURE} the owner keeps it"], None),
        ([f"keep:nginx {PAST} it was kept"], "disable"),
        # A keep stops the prune wherever it got to.
        (
            [f"disabled:nginx {PAST} soaked", f"keep:nginx {FUTURE} kept after all"],
            None,
        ),
    ],
)
def test_the_plan_names_the_next_stage(tmp_path, lines, next_stage):
    host = _host(tmp_path, NGINX, "nginx").declare(*lines)
    assert host.plan("nginx")["stage"]["next"] == next_stage


def test_the_plan_names_what_a_later_autoremove_would_take(tmp_path):
    host = _host(tmp_path, DOCKER, "docker")
    host.host_state["packages"]["docker.io"]["orphans"] = ["iptables", "libnftables1"]
    # An old kernel autoremove takes already is no part of the prune.
    host.host_state["autoremovable"] = ["linux-image-6.8.0-31-generic"]
    out = host.plan("docker")
    assert out["autoremove_would_take"] == ["iptables", "libnftables1"]
    assert not any("autoremove" in n for n in out["not_read"])


def test_a_component_from_outside_apt_is_its_unit_and_binary(tmp_path):
    host = _host(tmp_path, OLLAMA, "ollama")
    out = host.plan("ollama")
    assert out["prune_plan"]["from_apt"] is False
    assert [u["unit"] for u in out["units"]] == ["ollama.service"]
    assert {"kind": "binary", "path": "/usr/local/bin/ollama", "kib": 51200} in out[
        "paths"
    ]
    assert any("outside apt" in n for n in out["not_read"])


def test_a_removed_components_residue_is_what_its_purge_takes(tmp_path):
    host = _host(tmp_path, NGINX, "nginx")
    del host.host_state["packages"]["nginx"]
    host.host_state["packages"]["nginx-common"]["state"] = "rc"
    out = host.plan("nginx")
    assert out["residue"] == ["nginx-common"]
    assert out["packages"]["roots"] == []
    assert [p["package"] for p in out["packages"]["purge"]] == ["nginx-common"]


# --- a stage ---------------------------------------------------------------------


def test_without_approve_a_stage_prints_its_commands_and_runs_none(tmp_path):
    host = _host(tmp_path, DOCKER, "docker")
    host.plan("docker")
    out = host.prune("disable", rc=3, approve=False)
    assert any("no --approve" in r for r in out["refused"])
    # One call each: systemd orders the stops itself.
    assert out["actions"] == [
        "systemctl stop -- docker.socket containerd.service docker.service",
        "systemctl disable -- docker.socket containerd.service docker.service",
        "systemctl mask -- docker.socket containerd.service docker.service",
    ]
    assert out["done"] is None
    assert host.changes() == []


def test_a_disable_covers_docker_socket_and_runs_nothing_else(tmp_path):
    host = _host(tmp_path, DOCKER, "docker")
    host.plan("docker")
    out = host.prune("disable")
    assert out["verdict"] == {"ok": True, "why": []}
    assert host.changes() == _ran(out)
    for u in ("docker.socket", "docker.service", "containerd.service"):
        assert host.host_state["units"][u]["enabled"] == "masked", u
        assert host.host_state["units"][u]["active"] == "inactive", u
    assert host.host_state["units"]["ssh.service"]["active"] == "active"
    assert any(
        "exception disabled:docker 2026-10-29 <reason>" in n for n in out["next"]
    )
    log = host.run_dir / "disable.log"
    assert "$ systemctl mask -- docker.socket containerd.service docker.service" in (
        log.read_text()
    )
    assert oct(log.stat().st_mode & 0o777) == "0o600"


def test_a_remove_takes_exactly_the_plans_packages(tmp_path):
    host = _host(tmp_path, NGINX, "nginx").declare(f"disabled:nginx {PAST} soaked")
    host.plan("nginx")
    out = host.prune("remove")
    assert out["verdict"]["ok"] is True
    assert host.changes() == [
        "apt-get remove -y -o APT::Get::AutomaticRemove=false nginx nginx-common"
    ]
    assert host.host_state["apt_env"] == ["remove noninteractive l"]
    assert {n: p["state"] for n, p in host.host_state["packages"].items()} == {
        "nginx": "rc",
        "nginx-common": "rc",
    }
    assert any("exception removed:nginx" in n for n in out["next"])


def test_a_purge_after_a_savepoint_skips_the_remove(tmp_path):
    host = _host(tmp_path, DOCKER, "docker").declare(f"disabled:docker {PAST} soaked")
    host.plan("docker")
    out = host.prune("savepoint")
    assert out["verdict"]["ok"] is True
    for f in ("config.tar", "versions", "savepoint"):
        assert oct((host.run_dir / f).stat().st_mode & 0o777) == "0o600", f
    assert "component docker\nhost web-1\n" in (host.run_dir / "savepoint").read_text()
    assert "docker.io 29.1.3" in (host.run_dir / "versions").read_text()
    assert any("holds no data" in n for n in out["next"])

    host.plan("docker")
    out = host.prune(
        "purge", "--savepoint", str(host.run_dir), "--purge-data", "/var/lib/docker"
    )
    assert out["verdict"]["ok"] is True
    assert host.changes()[-4:] == [
        "apt-get purge -y -o APT::Get::AutomaticRemove=false containerd docker.io runc",
        "gpasswd -d exedev docker",
        "groupdel docker",
        "rm -rf /var/lib/docker",
    ]
    assert set(host.host_state["packages"]) == {"openssh-server"}
    assert host.host_state["groups"] == {}
    # The data it wasn't told to delete stays, and next says so.
    assert any("/var/lib/containerd is still there" in n for n in out["next"])
    assert not any("/var/lib/docker is still" in n for n in out["next"])


def test_a_purge_that_drops_postgres_clusters_waits_for_the_owner_to_name_them(
    tmp_path,
):
    # postgresql-16's purge script drops every cluster, whatever debconf
    # says: no --purge-data, no purge.
    host = _host(tmp_path, POSTGRES, "postgres").declare(
        f"removed:postgres {PAST} soaked"
    )
    host.plan("postgres")
    out = host.prune("purge", rc=3)
    assert any(
        r.startswith("postgresql-16's purge script deletes /var/lib/postgresql")
        and "--purge-data /var/lib/postgresql" in r
        for r in out["refused"]
    ), out["refused"]
    assert host.changes() == []

    out = host.prune("purge", "--purge-data", "/var/lib/postgresql")
    assert out["verdict"]["ok"] is True
    assert host.changes()[-1] == "rm -rf /var/lib/postgresql"


def test_a_postgres_cluster_kept_elsewhere_is_named_before_any_purge(tmp_path):
    # Which script drops it decides whether /srv/pg/alt goes: the owner names
    # it, and the purge deletes it whichever ran.
    host = _host(tmp_path, POSTGRES, "postgres").declare(
        f"removed:postgres {PAST} soaked"
    )
    host.host_state["clusters"].append(["16", "alt", "/srv/pg/alt"])
    out = host.plan("postgres")
    assert out["clusters"] == [
        {"cluster": "16/main", "data": "/var/lib/postgresql/16/main"},
        {"cluster": "16/alt", "data": "/srv/pg/alt"},
    ]
    assert "cluster 16/alt /srv/pg/alt" in (tmp_path / "postgres.plan").read_text()
    out = host.prune("purge", "--purge-data", "/var/lib/postgresql", rc=3)
    assert out["refused"] == [
        "the purge drops Postgres cluster 16/alt and its data at /srv/pg/alt: pass"
        " --purge-data /srv/pg/alt to approve that, or leave postgres removed rather"
        " than purged"
    ]
    assert host.changes() == []

    out = host.prune(
        "purge", "--purge-data", "/var/lib/postgresql", "--purge-data", "/srv/pg/alt"
    )
    assert out["verdict"]["ok"] is True
    assert host.changes()[-2:] == [
        "rm -rf /var/lib/postgresql",
        "rm -rf /srv/pg/alt",
    ]


def test_a_purge_with_clusters_it_cant_list_is_refused(tmp_path):
    host = _host(tmp_path, POSTGRES, "postgres").declare(
        f"removed:postgres {PAST} soaked"
    )
    host.host_state["clusters"] = None
    out = host.plan("postgres")
    assert any("Postgres's clusters" in n for n in out["not_read"])
    out = host.prune("purge", "--purge-data", "/var/lib/postgresql", rc=3)
    assert any("clusters couldn't be listed" in r for r in out["refused"])
    assert host.changes() == []


def test_a_savepoint_keeps_the_conffiles_a_purge_deletes_outside_the_config(
    tmp_path,
):
    host = _host(tmp_path, NGINX, "nginx").declare(f"disabled:nginx {PAST} soaked")
    out = host.plan("nginx")
    assert out["conffiles"] == ["/etc/default/nginx", "/etc/logrotate.d/nginx"]
    assert "conffile /etc/default/nginx" in (tmp_path / "nginx.plan").read_text()
    out = host.prune("savepoint")
    assert out["verdict"]["ok"] is True
    assert (
        f"tar -cf {host.run_dir}/config.tar /etc/nginx /etc/default/nginx"
        " /etc/logrotate.d/nginx" in host.changes()
    )


def test_a_savepoint_of_another_components_lets_no_purge_skip_the_remove(tmp_path):
    host = _host(tmp_path, DOCKER, "docker").declare(f"disabled:docker {PAST} soaked")
    host.plan("docker")
    host.prune("savepoint")
    record = host.run_dir / "savepoint"
    record.write_text(record.read_text().replace("component docker", "component nginx"))
    host.plan("docker")
    out = host.prune("purge", "--savepoint", str(host.run_dir), rc=3)
    assert any(
        "holds nginx's savepoint on web-1, not docker's on web-1" in r
        for r in out["refused"]
    ), out["refused"]


def test_a_savepoint_that_failed_or_changed_since_lets_no_purge_skip_the_remove(
    tmp_path,
):
    host = _host(tmp_path, DOCKER, "docker").declare(f"disabled:docker {PAST} soaked")
    host.plan("docker")
    assert host.prune("savepoint")["verdict"]["ok"] is True
    # A second attempt whose tar fails leaves no record of the first.
    host.host_state["tar_fail"] = "/var/backups: No space left on device"
    host.prune("savepoint", rc=1)
    del host.host_state["tar_fail"]
    host.plan("docker")
    out = host.prune("purge", "--savepoint", str(host.run_dir), rc=3)
    assert any("holds no savepoint record" in r for r in out["refused"]), out["refused"]

    # A tarball that isn't the one its record names.
    assert host.prune("savepoint")["verdict"]["ok"] is True
    (host.run_dir / "config.tar").write_text("truncated")
    host.plan("docker")
    out = host.prune("purge", "--savepoint", str(host.run_dir), rc=3)
    assert any(
        "config.tar isn't the tarball its record names" in r for r in out["refused"]
    ), out["refused"]
    assert not [c for c in host.changes() if c.startswith("apt-get purge")]


def test_a_failed_savepoint_leaves_its_error_in_the_log_it_points_to(tmp_path):
    host = _host(tmp_path, DOCKER, "docker").declare(f"disabled:docker {PAST} soaked")
    host.plan("docker")
    host.host_state["tar_fail"] = "/var/backups: No space left on device"
    out = host.prune("savepoint", rc=1)
    assert any("savepoint.log" in w for w in out["verdict"]["why"])
    log = (host.run_dir / "savepoint.log").read_text()
    assert f"$ tar -cf {host.run_dir}/config.tar" in log
    assert "tar: /var/backups: No space left on device" in log

    # A record that can't be written: its path is a directory.
    del host.host_state["tar_fail"]
    (host.run_dir / "versions").mkdir()
    host.plan("docker")
    out = host.prune("savepoint", rc=1)
    log = (host.run_dir / "savepoint.log").read_text()
    assert f"$ write {host.run_dir}/versions\n" in log
    assert "Is a directory" in log


def test_a_savepoint_whose_tarball_cant_be_read_writes_no_record(tmp_path):
    host = _host(tmp_path, DOCKER, "docker").declare(f"disabled:docker {PAST} soaked")
    host.plan("docker")
    host.on("sha256sum", "*", rc=1, stderr="sha256sum: Input/output error\n")
    out = host.prune("savepoint", rc=1)
    assert any("sha256sum couldn't read" in w for w in out["verdict"]["why"])
    assert not (host.run_dir / "savepoint").exists()


def test_a_held_package_is_named_and_no_removal_of_it_runs(tmp_path):
    host = _host(tmp_path, DOCKER, "docker").declare(f"disabled:docker {PAST} soaked")
    host.host_state["packages"]["docker.io"]["state"] = "hi"
    assert host.plan("docker")["packages"]["held"] == ["docker.io"]
    out = host.prune("remove", rc=3)
    assert any(
        "apt-mark holds docker.io" in r and "apt-mark unhold docker.io" in r
        for r in out["refused"]
    ), out["refused"]
    assert host.changes() == []


def test_a_package_apt_leaves_installed_fails_the_stage(tmp_path):
    host = _host(tmp_path, NGINX, "nginx").declare(f"disabled:nginx {PAST} soaked")
    host.plan("nginx")
    host.host_state["keeps"] = ["nginx-common"]
    out = host.prune("remove", rc=1)
    assert "nginx-common is still ii after the remove" in out["verdict"]["why"]


def test_a_component_from_outside_apt_is_disabled_and_not_masked_where_it_cant_be(
    tmp_path,
):
    host = _host(tmp_path, OLLAMA, "ollama")
    host.plan("ollama")
    out = host.prune("disable")
    assert out["verdict"]["ok"] is True
    assert host.changes() == [
        "systemctl stop -- ollama.service",
        "systemctl disable -- ollama.service",
    ]
    assert any("Not masked" in n for n in out["next"])


def test_a_failed_apt_run_stops_the_stage(tmp_path):
    host = _host(tmp_path, DOCKER, "docker").declare(f"disabled:docker {PAST} soaked")
    host.plan("docker")
    host.host_state["fail"] = "Sub-process /usr/bin/dpkg returned an error code (1)"
    out = host.prune("remove", rc=1)
    assert out["done"][0]["exit"] == 100
    assert any("exited 100" in w for w in out["verdict"]["why"])
    # The group's members stay: nothing after the failed command ran.
    assert host.host_state["groups"] == {"docker": ["exedev"]}
    assert not [c for c in host.changes() if c.startswith("gpasswd")]


def test_apt_taking_a_package_outside_the_plan_fails_the_stage(tmp_path):
    host = _host(tmp_path, NGINX, "nginx").declare(f"disabled:nginx {PAST} soaked")
    host.host_state["packages"]["libgd3"] = {
        "state": "ii",
        "version": "2.3",
    }
    host.plan("nginx")
    host.host_state["also_takes"] = ["libgd3"]
    out = host.prune("remove", rc=1)
    assert any(
        "apt took libgd3, which the plan doesn't name" in w
        for w in out["verdict"]["why"]
    )


# --- refusals ----------------------------------------------------------------------


def _drift_package(h):
    h.host_state["packages"]["nginx-doc"] = {
        "state": "ii",
        "version": "1.24.0",
    }
    h.host_state["packages"]["nginx-common"]["drags"] = ["nginx", "nginx-doc"]


@pytest.mark.parametrize(
    "stage, setup, refused",
    [
        (
            "disable",
            lambda h: h.knob("class ephemeral\n"),
            "report-only: class ephemeral",
        ),
        (
            "disable",
            lambda h: (h.tmp / "nginx.plan").write_text("not a plan\n"),
            "isn't a plan prune-plan.sh wrote",
        ),
        (
            "disable",
            lambda h: (h.tmp / "nginx.plan").write_text(
                (h.tmp / "nginx.plan").read_text().replace("host web-1", "host web-2")
            ),
            "taken on web-2, and this is web-1",
        ),
        (
            "disable",
            lambda h: setattr(h, "clock", h.clock + DAY + 60),
            "more than 24 hours ago",
        ),
        (
            "disable",
            lambda h: setattr(h, "clock", h.clock - 600),
            "later than the clock says it is now",
        ),
        # Its body, without the line that says prune-plan.sh wrote it.
        (
            "disable",
            lambda h: (h.tmp / "nginx.plan").write_text(
                "# a plan\n" + (h.tmp / "nginx.plan").read_text().split("\n", 1)[1]
            ),
            "isn't a plan prune-plan.sh wrote",
        ),
        (
            "disable",
            lambda h: (h.tmp / "nginx.plan").write_text(
                (h.tmp / "nginx.plan").read_text() + "data /home\n"
            ),
            "names /home, which isn't nginx's data",
        ),
        (
            "disable",
            lambda h: (h.tmp / "nginx.plan").write_text(
                (h.tmp / "nginx.plan").read_text() + "rm -rf /\n"
            ),
            "lines prune-plan.sh doesn't write",
        ),
        (
            "disable",
            lambda h: h.declare(f"keep:nginx {FUTURE} the owner keeps it"),
            "the knob keeps nginx",
        ),
        (
            "remove",
            lambda h: h.declare(
                f"disabled:nginx {PAST} soaked", f"keep:nginx {FUTURE} kept after all"
            ),
            "the knob keeps nginx",
        ),
        (
            "disable",
            lambda h: h.declare(f"removed:nginx {FUTURE} soaking"),
            "already removed",
        ),
        ("remove", lambda h: None, "disable nginx first"),
        (
            "remove",
            lambda h: h.declare(f"disabled:nginx {FUTURE} soaking"),
            "soaking until 2026-10-29",
        ),
        (
            "purge",
            lambda h: h.declare(f"disabled:nginx {PAST} soaked"),
            "a savepoint lets the purge skip it",
        ),
        (
            "purge",
            lambda h: h.declare(f"removed:nginx {FUTURE} soaking"),
            "soaking until 2026-10-29",
        ),
        ("savepoint", lambda h: None, "disable nginx first"),
        (
            "remove",
            lambda h: (
                h.declare(f"disabled:nginx {PAST} soaked"),
                h.on("pgrep", "-x *", "4242\n"),
            ),
            "dpkg or apt is running",
        ),
        (
            "remove",
            lambda h: (
                h.declare(f"disabled:nginx {PAST} soaked"),
                h.cases["dpkg"].clear(),
                h.on("dpkg", "--audit", "nginx: half-configured\n"),
            ),
            "dpkg --audit isn't clean (nginx: half-configured)",
        ),
        (
            "remove",
            lambda h: (h.declare(f"disabled:nginx {PAST} soaked"), _drift_package(h)),
            "the host no longer matches the plan",
        ),
        (
            "remove",
            lambda h: (
                h.declare(f"disabled:nginx {PAST} soaked"),
                h.host_state.update(installs=["apache2"]),
            ),
            "apt would install apache2",
        ),
        # Its own purge script deletes it, so the owner names it.
        (
            "purge",
            lambda h: h.declare(f"removed:nginx {PAST} soaked"),
            "nginx-common's purge script deletes /var/log/nginx (postrm line 3",
        ),
    ],
    ids=[
        "report-only",
        "not-a-plan",
        "another-host",
        "stale-plan",
        "future-plan",
        "no-header",
        "a-path-not-its",
        "a-line-it-doesnt-write",
        "kept",
        "kept-after-a-disable",
        "already-removed",
        "remove-before-disable",
        "remove-while-soaking",
        "purge-needs-remove-or-savepoint",
        "purge-while-soaking",
        "savepoint-before-disable",
        "package-manager-running",
        "dpkg-unclean",
        "drift",
        "a-removal-that-installs",
        "a-purge-script-deleting-data",
    ],
)
def test_a_stage_it_shouldnt_run_is_refused(tmp_path, stage, setup, refused):
    host = _host(tmp_path, NGINX, "nginx")
    host.plan("nginx")
    setup(host)
    out = host.prune(stage, rc=3)
    assert any(refused in r for r in out["refused"]), out["refused"]
    assert host.changes() == []


def test_a_today_later_than_the_clock_ends_no_soak(tmp_path):
    host = _host(tmp_path, NGINX, "nginx").declare(f"disabled:nginx {PAST} soaked")
    # On the clock it's still the soak's last day, PAST, which still counts.
    host.clock -= DAY
    host.plan("nginx")
    r = host.execute(
        [
            "bash",
            str(host.scripts / "prune.sh"),
            "--stage",
            "remove",
            "--plan",
            str(tmp_path / "nginx.plan"),
            "--run",
            str(host.run_dir),
            "--approve",
            "--config",
            str(host.knob_path),
            "--host",
            "web-1",
            "--today",
            TODAY,
        ],
        2,
    )
    assert f"--today {TODAY} is later than the clock's date, {PAST}" in r.stderr
    assert host.changes() == []


@pytest.mark.parametrize(
    "stage, lines, data, refused",
    [
        ("disable", [], {}, "no unit of nginx is left to disable"),
        ("remove", ["disabled"], {}, "no package of nginx is left to remove"),
        (
            "purge",
            ["removed"],
            {"/var/www": 12},
            "its data is still there (/var/www): delete it with --purge-data",
        ),
        (
            "purge",
            ["removed"],
            {},
            "replace the knob's stage line with exception purged:nginx",
        ),
    ],
    ids=["disable", "remove", "purge-data-left", "purge-nothing-left"],
)
def test_a_stage_with_nothing_to_run_is_refused_not_declared(
    tmp_path, stage, lines, data, refused
):
    # nginx isn't installed here: no unit, no package.
    gone = {**NGINX, "packages": {}, "units": {}, "paths": data}
    host = _host(tmp_path, gone, "nginx").declare(
        *[f"{x}:nginx {PAST} soaked" for x in lines]
    )
    assert host.plan("nginx")["prune_plan"]["installed"] is False
    out = host.prune(stage, rc=3)
    assert any(refused in r for r in out["refused"]), out["refused"]
    assert out["next"] == []


def test_a_remove_with_only_residue_left_says_the_purge_comes_next(tmp_path):
    host = _host(tmp_path, NGINX, "nginx").declare(f"disabled:nginx {PAST} soaked")
    del host.host_state["packages"]["nginx"]
    host.host_state["packages"]["nginx-common"]["state"] = "rc"
    host.plan("nginx")
    out = host.prune("remove", rc=3)
    assert any(
        "only residue (nginx-common): the purge comes next" in r
        and "exception removed:nginx" in r
        for r in out["refused"]
    ), out["refused"]


def test_drift_names_what_changed(tmp_path):
    host = _host(tmp_path, DOCKER, "docker")
    host.plan("docker")
    host.host_state["groups"]["docker"].append("deploy")
    out = host.prune("disable", rc=3)
    assert out["gate"]["drift"]["differs"] == ["> member docker deploy"]
    assert host.changes() == []


@pytest.mark.parametrize(
    "stage, args, refused",
    [
        (
            "purge",
            ["--purge-data", "/home"],
            "--purge-data /home isn't a path the plan names",
        ),
        ("remove", [], "comes from outside apt"),
    ],
)
def test_a_path_or_a_removal_it_cant_vouch_for_is_refused(
    tmp_path, stage, args, refused
):
    fixture, comp = (OLLAMA, "ollama") if stage == "remove" else (NGINX, "nginx")
    host = _host(tmp_path, fixture, comp).declare(
        f"removed:{comp} {PAST} soaked", f"disabled:{comp} {PAST} soaked"
    )
    host.plan(comp)
    out = host.prune(stage, *args, rc=3)
    assert any(refused in r for r in out["refused"]), out["refused"]
    assert host.changes() == []


def test_without_root_a_stage_is_refused(tmp_path):
    host = Host(tmp_path, NGINX, sudo=False)
    host.component = "nginx"
    host.plan("nginx")
    out = host.prune("disable", rc=3)
    assert any("no root" in r for r in out["refused"])
    assert host.changes() == []


def test_a_plan_its_unchanged_host_still_matches_is_good_until_it_is_a_day_old(
    tmp_path,
):
    host = _host(tmp_path, NGINX, "nginx")
    host.plan("nginx")
    host.clock = TUE_1530 + DAY - 60
    assert host.prune("disable")["verdict"]["ok"] is True
