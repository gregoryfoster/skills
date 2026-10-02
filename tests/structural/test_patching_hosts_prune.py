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
  removal and a purge take and drag along, metapackages, what else depends
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
    if args[0] == "-W":
        for n in sorted(pk):
            p = pk[n]
            print("%s |%s|%s|%s" % (p["state"], n, p["version"], p.get("section", "misc")))
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
    if sim:
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
if cmd == "debconf-show":
    for n in args:
        for line in db.get("debconf", {}).get(n, []):
            print(line)
    sys.exit(0)
if cmd == "tar":
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
            "section": "admin",
            "files": [LIB + "containerd.service"],
        },
        "docker.io": {
            "state": "ii",
            "version": "29.1.3",
            "section": "admin",
            "files": [
                LIB + "docker.service",
                LIB + "docker.socket",
                LIB + "multi-user.target.wants/docker.service",
                "/usr/bin/dockerd",
            ],
            "postrm": '#!/bin/sh\nif [ "$1" = purge ]; then\n    rm -f /etc/apparmor.d/local/docker.io || true\nfi\n',
        },
        "runc": {"state": "ii", "version": "1.3.4", "section": "devel"},
        "openssh-server": {
            "state": "ii",
            "version": "1:9.6",
            "section": "net",
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
            "section": "httpd",
            "depends": ["nginx-common"],
        },
        "nginx-common": {
            "state": "ii",
            "version": "1.24.0",
            "section": "httpd",
            "files": [LIB + "nginx.service"],
            "drags": ["nginx"],
            "postrm": '#!/bin/sh\nif [ "$1" = purge ]; then\n    rm -rf /var/lib/nginx /var/log/nginx /etc/nginx\nfi\n',
        },
    },
    "units": {"nginx.service": _unit(LIB + "nginx.service")},
    "groups": {},
    "paths": {"/etc/nginx": 84, "/var/www": 12, "/var/log/nginx": 8},
}
POSTGRES = {
    "packages": {
        "postgresql": {
            "state": "ii",
            "version": "16+257",
            "section": "metapackages",
            "depends": ["postgresql-16"],
        },
        "postgresql-16": {
            "state": "ii",
            "version": "16.2",
            "section": "database",
            "postrm": '#!/bin/sh\n    rm -rf "/var/lib/postgresql/$VERSION/$1/"\n',
        },
        "postgresql-common": {
            "state": "ii",
            "version": "257",
            "section": "database",
            "files": [LIB + "postgresql.service", LIB + "postgresql@.service"],
        },
        "postgresql-client-16": {
            "state": "ii",
            "version": "16.2",
            "section": "database",
            "depends": ["postgresql-16"],
        },
    },
    "units": {
        "postgresql.service": _unit(LIB + "postgresql.service"),
        "postgresql@16-main.service": _unit(LIB + "postgresql@.service"),
    },
    "groups": {},
    "paths": {"/etc/postgresql": 72, "/var/lib/postgresql": 39468},
    "debconf": {"postgresql-16": ["* postgresql-16/postrm_purge_data: true"]},
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
        "rm": 'case "$*" in *"$TMPDIR"*) exec /bin/rm "$@" ;; esac\nexit 0',
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
    assert out["metapackages"] == ["postgresql"]
    assert out["reverse_depends"] == [
        {"package": "postgresql-client-16", "depends_on": "postgresql-16"}
    ]
    # Its purge script takes the cluster's data, unless debconf says not to.
    assert [p["text"] for p in out["purge_scripts"]] == [
        'rm -rf "/var/lib/postgresql/$VERSION/$1/"'
    ]
    assert out["debconf"] == ["postgresql-16/postrm_purge_data: true"]

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
    ],
)
def test_the_plan_names_the_next_stage(tmp_path, lines, next_stage):
    host = _host(tmp_path, NGINX, "nginx").declare(*lines)
    assert host.plan("nginx")["stage"]["next"] == next_stage


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


def test_a_savepoint_of_another_components_lets_no_purge_skip_the_remove(tmp_path):
    host = _host(tmp_path, DOCKER, "docker").declare(f"disabled:docker {PAST} soaked")
    host.plan("docker")
    host.prune("savepoint")
    record = host.run_dir / "savepoint"
    record.write_text(record.read_text().replace("component docker", "component nginx"))
    host.plan("docker")
    out = host.prune("purge", "--savepoint", str(host.run_dir), rc=3)
    assert any("holds no savepoint for docker on web-1" in r for r in out["refused"])


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
        "section": "libs",
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
        "section": "doc",
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
    ],
    ids=[
        "report-only",
        "not-a-plan",
        "another-host",
        "stale-plan",
        "no-header",
        "a-path-not-its",
        "a-line-it-doesnt-write",
        "kept",
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
    ],
)
def test_a_stage_it_shouldnt_run_is_refused(tmp_path, stage, setup, refused):
    host = _host(tmp_path, NGINX, "nginx")
    host.plan("nginx")
    setup(host)
    out = host.prune(stage, rc=3)
    assert any(refused in r for r in out["refused"]), out["refused"]
    assert host.changes() == []


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
