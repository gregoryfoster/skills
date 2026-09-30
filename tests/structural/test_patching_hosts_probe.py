"""patching-hosts' read-only probe: `probe.sh` over `_probe-lib.sh` (#313, plan step 3).

In the step 0 round, every reading in references/readings.md was misread, or
found only by hand, on at least one host: masked timers behind a `1`/`1`
20auto-upgrades, a Docker file setting `Periodic::Enable` to 0, a journal that
said persistent and kept nothing, a setup script the platform delivers again
every boot. The probe takes those readings and changes nothing, so it can be
run on any host at any time.

What this file pins, against the plan's step 3 list:

- the masked timers under `1`, and `Periodic::Enable` at 0 with them unmasked,
  are deviations; an absent setting is `unknown`, never its default;
- `reboot-required` is read with its `.pkgs`;
- a deviation an exception covers moves to `excepted`, and one it doesn't, or
  an expired one, stays a finding;
- Docker active with no container is `dormant`, and `kept` under `keep:`; a
  Postgres whose activity needs a failed login is `unknown`, and so is idle
  evidence younger than 30 days;
- a world-readable `/exe.dev/setup` holding a Tailscale key, with the unit
  failed, is a finding that names the pattern and line, and the secret appears
  nowhere the probe writes; no file, but the unit running on every retained
  boot, is a script re-delivered, not a clean host;
- no stubbed command is ever asked to install, remove, hold, restart or write
  apt's lists;
- `Storage=persistent` with the flush masked and nothing on disk is volatile;
- earlyoom's arguments come from `/proc/<pid>/cmdline`, not its journal;
- a runbook service without `After=` its data store is a finding, however its
  first start went;
- the session's chain is read to PID 1, whatever its parents are called;
- an owner's hold on a pending package needs a `held:` exception;
- a database no `datastore` line names is a finding, but `postgres` and the
  templates are not.

Beyond that list, from running it live against a booted systemd 255: a hold
is read from `apt-cache policy`, since `apt-get -s` keeps a held package
back; an empty psql field keeps its place; idle time counts from systemd's
start, not the kernel's; stock Ubuntu's release pocket isn't a widening; and
the output is ASCII.

Each case runs the whole script under the system's bash (3.2 on macOS)
against a fixture root under tmp_path, with `run/systemd/system` marking it
live, and stubs on PATH for every command that asks the running system. Each
stub logs its argv, which is what the no-writes test reads.
"""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL = REPO_ROOT / "skills" / "patching-hosts"
PROBE = SKILL / "scripts" / "probe.sh"
TODAY = "2026-09-30"
DAY = 86400
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
SECRET = "kSECRETVALUE123-abcdefGHIJKL"

# Every command the probe may run that asks the system, so none reaches the
# machine running the tests. Unmatched, each exits 1 with nothing on stdout:
# a reading that couldn't be taken.
STUBBED = (
    "systemctl",
    "journalctl",
    "systemd-analyze",
    "apt-config",
    "apt-get",
    "apt-cache",
    "apt-mark",
    "dpkg-query",
    "dpkg",
    "needrestart",
    "pro",
    "psql",
    "pg_lsclusters",
    "docker",
    "redis-cli",
    "ss",
    "unattended-upgrade",
    "runuser",
    "git",
    "hostname",
    "curl",
)


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["LC_ALL"] = "C"
    env.pop("APT_CONFIG", None)
    return env


# Every stub is a symlink to this one script, which logs its argv and then
# sources the test's cases for the name it was called by. Its fields split on
# the record separator: psql's own -F is the unit separator.
DISPATCH = """#!/bin/sh
name=${0##*/}
printf '%s\\036%s\\036%s\\n' "$name" "$*" "${APT_CONFIG:-}" >> "$STUB_LOG"
. "$STUB_CASES/$name"
exit 1
"""
_DISPATCHER: list[Path] = []


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    p = tmp_path_factory.mktemp("stub") / "dispatch"
    p.write_text(DISPATCH)
    p.chmod(0o755)
    # Run it once, so its first-exec scan is paid here and not in a probe run.
    subprocess.run(
        [str(p)],
        env={"STUB_LOG": "/dev/null", "STUB_CASES": "/nonexistent"},
        capture_output=True,
    )
    _DISPATCHER[:] = [p]
    yield
    _DISPATCHER.clear()


def _pattern(glob: str) -> str:
    """A `case` pattern: `*` stays a wildcard, everything else is literal."""
    return "*".join("'" + part.replace("'", "'\\''") + "'" for part in glob.split("*"))


class Host:
    """A fixture root, the stubs that answer for it, and the knob."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        live: bool = True,
        uptime_days: int = 40,
        sudo: bool = True,
    ):
        self.tmp = tmp_path
        self.root = tmp_path / "root"
        self.bin = tmp_path / "bin"
        self.repo = tmp_path / "repo"
        self.log = tmp_path / "argv.log"
        self.knob_path = tmp_path / "knob"
        self.tmpdir = tmp_path / "tmp"
        for d in (self.root, self.bin, self.repo, self.tmpdir):
            d.mkdir()
        self.now = int(time.time())
        self.sudo = sudo
        self.cases: dict[str, list[tuple[str, str, int, str]]] = {
            n: [] for n in STUBBED
        }
        if live:
            (self.root / "run" / "systemd" / "system").mkdir(parents=True)
        self.write(
            "proc/stat", f"cpu  1 2 3\nbtime {self.now - uptime_days * DAY - 60}\n"
        )
        self.chain([(4242, "bash", 0), (1, "systemd", 0)])

    # --- the tree -----------------------------------------------------------

    def write(
        self,
        rel: str,
        text: str | bytes = "",
        mode: int | None = None,
        age_days: float | None = None,
    ) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            p.write_bytes(text)
        else:
            p.write_text(text)
        if mode is not None:
            p.chmod(mode)
        if age_days is not None:
            then = self.now - age_days * DAY
            os.utime(p, (then, then))
        return p

    def link(self, rel: str, target: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.symlink_to(target)

    def mask(self, unit: str) -> None:
        self.link(f"etc/systemd/system/{unit}", "/dev/null")

    def enable(self, unit: str, target: str = "timers.target") -> None:
        self.write(
            f"usr/lib/systemd/system/{unit}", f"[Unit]\n[Install]\nWantedBy={target}\n"
        )
        self.link(
            f"etc/systemd/system/{target}.wants/{unit}",
            f"/usr/lib/systemd/system/{unit}",
        )

    def chain(self, procs: list[tuple[int, str, int]]) -> None:
        for i, (pid, comm, adj) in enumerate(procs):
            ppid = procs[i + 1][0] if i + 1 < len(procs) else 0
            self.write(f"proc/{pid}/status", f"Name:\t{comm}\nPPid:\t{ppid}\n")
            self.write(f"proc/{pid}/comm", comm + "\n")
            self.write(f"proc/{pid}/oom_score_adj", f"{adj}\n")

    # --- the stubs ----------------------------------------------------------

    def on(
        self, cmd: str, glob: str, stdout: str = "", rc: int = 0, stderr: str = ""
    ) -> "Host":
        self.cases[cmd].append((glob, stdout, rc, stderr))
        return self

    def installed(self, *pkgs: str) -> "Host":
        for p in pkgs:
            self.on("dpkg-query", "*-W -f ${db:Status-Abbrev} " + p, "ii ")
        return self

    def show(self, unit: str, **props: str) -> "Host":
        return self.on(
            "systemctl",
            f"show*-- {unit}",
            "".join(f"{k}={v}\n" for k, v in props.items()),
        )

    def apt_config(self, **values: str) -> "Host":
        names = {"Enable": "PE", "Lists": "PU", "UU": "PUU", "Reboot": "UR"}
        self.on(
            "apt-config",
            "shell*",
            "".join(f"{names[k]}='{v}'\n" for k, v in values.items()),
        )
        return self

    def knob(self, text: str) -> "Host":
        self.knob_path.write_text(text)
        return self

    def _write_stubs(self) -> None:
        # A symlink to the session's dispatcher, and a sourced file of cases:
        # macOS scans a newly written executable on its first run, about 0.1 s
        # each, which made every probe run here cost 2 s.
        cases = self.tmp / "cases"
        cases.mkdir(exist_ok=True)
        for name, rows in self.cases.items():
            lines = ['case "$*" in']
            for i, (glob, out, rc, err) in enumerate(rows):
                o = cases / f".{name}.{i}.out"
                o.write_text(out)
                redirect = ""
                if err:
                    (cases / f".{name}.{i}.err").write_text(err)
                    redirect = f" cat '{cases}/.{name}.{i}.err' >&2;"
                lines.append(f"  {_pattern(glob)}) cat '{o}';{redirect} exit {rc} ;;")
            lines += ["esac", "exit 1", ""]
            (cases / name).write_text("\n".join(lines))
        # sudo runs its command as root, or as -u's user, and id answers for
        # whoever that is.
        (cases / "sudo").write_text(
            "STUB_USER=root\n"
            "while [ $# -gt 0 ]; do case $1 in -n) shift ;; -u) STUB_USER=$2; shift 2 ;; --) shift; break ;; *) break ;; esac; done\n"
            'export STUB_USER\nexec "$@"\n'
            if self.sudo
            else "echo 'sudo: a password is required' >&2\nexit 1\n"
        )
        (cases / "id").write_text(
            "case ${STUB_USER:-exedev} in root) u=0 ;; *) u=1000 ;; esac\n"
            'case "$1" in -u) echo $u ;; -un) echo ${STUB_USER:-exedev} ;; *) echo "uid=$u(${STUB_USER:-exedev})" ;; esac\nexit 0\n'
        )
        (cases / "choom").write_text(
            "while [ $# -gt 0 ]; do case $1 in -n) shift 2 ;; --) shift; break ;; *) break ;; esac; done\n"
            'exec "$@"\n'
        )
        for name in (*STUBBED, "sudo", "id", "choom"):
            link = self.bin / name
            if not link.is_symlink():
                link.symlink_to(_DISPATCHER[0])

    def run(self, *args: str, rc: int = 0, root: bool = True):
        self._write_stubs()
        cmd = ["bash", str(PROBE)]
        if root:
            cmd += ["--root", str(self.root)]
        cmd += [
            "--config",
            str(self.knob_path),
            "--host",
            "web-1",
            "--repo",
            str(self.repo),
            "--today",
            TODAY,
            "--session-pid",
            "4242",
            *args,
        ]
        env = _clean_env()
        env["PATH"] = f"{self.bin}:{SYSTEM_PATH}"
        env["TMPDIR"] = str(self.tmpdir)
        env["STUB_LOG"] = str(self.log)
        env["STUB_CASES"] = str(self.tmp / "cases")
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=180)
        self.result = r
        assert r.returncode == rc, f"exit {r.returncode}\n{r.stderr}"
        return json.loads(r.stdout) if rc == 0 else r

    def calls(self, name: str | None = None) -> list[tuple[str, str, str]]:
        if not self.log.exists():
            return []
        # split("\n"), not splitlines(): that breaks on the record separator too.
        lines = [line for line in self.log.read_text().split("\n") if line]
        rows = [tuple((line.split("\x1e") + ["", ""])[:3]) for line in lines]
        return [r for r in rows if name is None or r[0] == name]


def _ids(out: dict, key: str = "findings") -> list[str]:
    return [f["id"] for f in out[key]]


def _finding(out: dict, fid: str, key: str = "findings") -> dict:
    hits = [f for f in out[key] if f["id"] == fid]
    assert hits, f"no {fid} in {key}: {_ids(out, key)}"
    return hits[0]


def _dormant(out: dict, name: str) -> dict:
    hits = [d for d in out["dormant"] if d["name"] == name]
    assert hits, f"no {name} in dormant: {[d['name'] for d in out['dormant']]}"
    return hits[0]


@pytest.fixture
def host(tmp_path) -> Host:
    return Host(tmp_path).knob("class production\nposture automatic\n")


# --- the command line -----------------------------------------------------------


def test_help_names_the_readings_and_exit_codes():
    r = subprocess.run(
        ["bash", str(PROBE), "--help"], capture_output=True, text=True, env=_clean_env()
    )
    assert r.returncode == 0
    for word in (
        "--root",
        "--refresh-into",
        "--dry-run-into",
        "--post-boot",
        "Exit codes",
        "readings.md",
    ):
        assert word in r.stdout


@pytest.mark.parametrize(
    "args, message",
    [
        (["--bogus"], "unknown argument"),
        (["--root"], "needs a value"),
        (["--root", "/nonexistent-root-xyz"], "not a directory"),
        (["--session-pid", "abc"], "process id"),
        (["--config", "a\nb"], "control character"),
    ],
)
def test_usage_errors_exit_2(args, message):
    r = subprocess.run(
        ["bash", str(PROBE), *args], capture_output=True, text=True, env=_clean_env()
    )
    assert r.returncode == 2, r.stderr
    assert message in r.stderr


def test_an_unreadable_knob_exits_2(tmp_path):
    h = Host(tmp_path)
    h.knob_path.mkdir()
    r = h.run(rc=2)
    assert "can't be read" in r.stderr


def test_refresh_and_dry_run_refuse_a_tree_nothing_runs(tmp_path):
    h = Host(tmp_path, live=False).knob("posture scheduled\n")
    r = h.run("--refresh-into", str(tmp_path / "scratch"), rc=2)
    assert "running system" in r.stderr


def test_every_top_level_key_is_there_and_the_scratch_directory_goes(host):
    out = host.run()
    assert list(out) == [
        "probe",
        "knob",
        "environment",
        "updates",
        "pending",
        "impact",
        "dormant",
        "findings",
        "excepted",
        "not_read",
    ]
    assert out["probe"]["live"] is True
    assert out["probe"]["privilege"] == "sudo"
    assert out["knob"]["posture"]["value"] == "automatic"
    assert list(host.tmpdir.iterdir()) == []


# --- what updates this host -------------------------------------------------


def test_masked_timers_under_a_1_1_auto_upgrades_are_deviations(host):
    host.write(
        "etc/apt/apt.conf.d/20auto-upgrades",
        'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n',
    )
    for u in (
        "apt-daily.timer",
        "apt-daily-upgrade.timer",
        "unattended-upgrades.service",
    ):
        host.mask(u)
        host.on("systemctl", f"is-enabled {u}", "masked\n", rc=1)
    host.apt_config(Enable="1", Lists="1", UU="1", Reboot="false")
    out = host.run()
    units = {u["unit"]: u for u in out["updates"]["units"]}
    assert units["apt-daily.timer"] == {
        "unit": "apt-daily.timer",
        "disk": "masked",
        "live": "masked",
    }
    for u in ("apt-daily.timer", "apt-daily-upgrade.timer"):
        f = _finding(out, f"timer:{u}")
        assert f["kind"] == "deviation"
        assert f["exception_what"] == f"timer:{u}"
    assert not [i for i in _ids(out) if i.startswith("periodic:")]
    assert out["updates"]["periodic"]["Update-Package-Lists"]["value"] == "1"


def test_masks_are_read_from_disk_on_a_tree_nothing_runs(tmp_path):
    h = Host(tmp_path, live=False).knob("posture automatic\n")
    h.mask("apt-daily.timer")
    h.mask("apt-daily-upgrade.timer")
    out = h.run()
    units = {u["unit"]: u for u in out["updates"]["units"]}
    assert units["apt-daily-upgrade.timer"]["disk"] == "masked"
    assert units["apt-daily-upgrade.timer"]["live"] is None
    assert _finding(out, "timer:apt-daily-upgrade.timer")["kind"] == "deviation"
    assert any("run/systemd/system is absent" in n for n in out["not_read"])
    # Nothing asked a running system that isn't there.
    for name in ("systemctl", "journalctl", "docker", "psql", "needrestart"):
        assert h.calls(name) == [], name


def test_periodic_enable_0_with_the_timers_unmasked_is_a_deviation(host):
    for u in ("apt-daily.timer", "apt-daily-upgrade.timer"):
        host.enable(u)
        host.on("systemctl", f"is-enabled {u}", "enabled\n")
    host.write(
        "etc/apt/apt.conf.d/docker-disable-periodic-update",
        'APT::Periodic::Enable "0";\n',
    )
    host.apt_config(Enable="0", Lists="1", UU="1", Reboot="false")
    out = host.run()
    assert not [i for i in _ids(out) if i.startswith("timer:")]
    f = _finding(out, "periodic:Enable")
    assert f["kind"] == "deviation"
    assert "/etc/apt/apt.conf.d/docker-disable-periodic-update:1" in f["message"]
    assert out["updates"]["periodic"]["Enable"] == {
        "value": "0",
        "set_in": ["/etc/apt/apt.conf.d/docker-disable-periodic-update:1"],
    }


def test_an_absent_setting_is_unknown_never_its_default(host):
    for u in ("apt-daily.timer", "apt-daily-upgrade.timer"):
        host.enable(u)
    host.apt_config(Lists="1", UU="1")
    out = host.run()
    assert out["updates"]["periodic"]["Enable"]["value"] is None
    assert _finding(out, "periodic:Enable")["kind"] == "unknown"
    assert out["updates"]["unattended_upgrades"]["automatic_reboot"] is None
    assert _finding(out, "uu:automatic-reboot")["kind"] == "unknown"


def test_the_scheduled_posture_wants_the_timers_masked(tmp_path):
    h = Host(tmp_path).knob("posture scheduled\n")
    h.mask("apt-daily.timer")
    h.enable("apt-daily-upgrade.timer")
    out = h.run()
    assert "timer:apt-daily.timer" not in _ids(out)
    assert "enabled" in _finding(out, "timer:apt-daily-upgrade.timer")["message"]
    # The scheduled posture doesn't read Periodic at all.
    assert not [i for i in _ids(out) if i.startswith("periodic:")]


@pytest.mark.parametrize(
    "files, finding",
    [
        ({}, "No file sets"),
        ({"etc/needrestart/conf.d/x.conf": "$nrconf{restart} = 'a';\n"}, "is 'a'"),
        ({"etc/needrestart/conf.d/x.conf": "$nrconf{restart} = 'l';\n"}, None),
        (
            {
                "etc/needrestart/needrestart.conf": "#$nrconf{restart} = 'i';\n",
                "etc/needrestart/conf.d/a.conf": "$nrconf{restart} = 'a';\n",
                "etc/needrestart/conf.d/b.conf": "$nrconf{restart} = 'l';\n",
            },
            None,
        ),
    ],
)
def test_the_needrestart_drop_in_is_read_from_its_files(host, files, finding):
    host.installed("needrestart")
    for rel, text in files.items():
        host.write(rel, text)
    out = host.run()
    if finding is None:
        assert "needrestart:restart" not in _ids(out)
        assert out["updates"]["needrestart"]["restart"] == "l"
    else:
        assert finding in _finding(out, "needrestart:restart")["message"]


def test_a_drop_in_needrestart_ignores_is_a_deviation(host):
    host.installed("needrestart")
    host.write("etc/needrestart/conf.d/x.conf", "$nrconf{restart} = 'l';\n")
    host.on(
        "needrestart", "-m u -b -r l", "NEEDRESTART-VER: 3.6\nNEEDRESTART-KSTA: 1\n"
    )
    out = host.run()
    assert out["updates"]["needrestart"]["proof"] == "ubuntu-mode"
    assert "doesn't load" in _finding(out, "needrestart:restart")["message"]


STOCK_ORIGINS = (
    'Unattended-Upgrade::Allowed-Origins "";\n'
    'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}";\n'
    'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}-security";\n'
    'Unattended-Upgrade::Allowed-Origins:: "${distro_id}ESMApps:${distro_codename}-apps-security";\n'
    'Unattended-Upgrade::Allowed-Origins:: "${distro_id}ESM:${distro_codename}-infra-security";\n'
)


@pytest.mark.parametrize(
    "extra, widened",
    [
        ("", None),
        (
            'Unattended-Upgrade::Origins-Pattern:: "origin=Ubuntu,archive=${distro_codename}";\n',
            None,
        ),
        (
            'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}-updates";\n',
            "-updates",
        ),
        (
            'Unattended-Upgrade::Origins-Pattern:: "origin=Tailscale";\n',
            "origin=Tailscale",
        ),
    ],
)
def test_unattended_upgrades_taking_more_than_security_is_a_deviation(
    host, extra, widened
):
    # Ubuntu's stock list names the release pocket, which never changes after
    # release: read on a real noble image, 2026-09-30.
    host.installed("unattended-upgrades")
    host.apt_config(Enable="1", Lists="1", UU="1", Reboot="false")
    host.on("apt-config", "dump", STOCK_ORIGINS + extra)
    out = host.run()
    assert len(out["updates"]["unattended_upgrades"]["origins"]) == 4 + bool(extra)
    if widened is None:
        assert "uu:origins" not in _ids(out)
    else:
        assert widened in _finding(out, "uu:origins")["message"]


def test_the_output_is_ascii_even_where_the_references_are_not(host):
    host.installed("needrestart")
    host.write("etc/systemd/journald.conf", "[Journal]\nStorage=volatile\n")
    host.chain([(4242, "bash", -1000), (1, "systemd", 0)])
    out = host.run()
    assert {"needrestart:restart", "journal:volatile", "session:adj"} <= set(_ids(out))
    assert host.result.stdout.isascii()
    assert "run.md section 1" in _finding(out, "needrestart:restart")["message"]


def test_a_third_party_origin_without_a_policy_is_a_knob_finding(host):
    host.on(
        "apt-cache",
        "*policy",
        " 500 https://pkgs.tailscale.com/stable/ubuntu noble/main amd64 Packages\n"
        "     release o=Tailscale,a=noble,n=noble,l=Tailscale,c=main,b=amd64\n"
        "     origin pkgs.tailscale.com\n"
        " 500 http://archive.ubuntu.com/ubuntu noble-security/main amd64 Packages\n"
        "     release v=24.04,o=Ubuntu,a=noble-security,n=noble,l=Ubuntu,c=main,b=amd64\n"
        "     origin archive.ubuntu.com\n",
    )
    out = host.run()
    assert {(o["origin"], o["third_party"]) for o in out["updates"]["origins"]} == {
        ("Tailscale", True),
        ("Ubuntu", False),
    }
    assert _finding(out, "origin:Tailscale")["kind"] == "knob"
    host.knob(
        "posture automatic\norigin Tailscale hold its upgrade drops the tailnet\n"
    )
    assert "origin:Tailscale" not in _ids(host.run())


# --- the pending set --------------------------------------------------------

SIMULATION = (
    "NOTE: This is only a simulation!\n"
    "Inst libc6 [2.39-0ubuntu8.3] (2.39-0ubuntu8.4 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [amd64])\n"
    "Conf libc6 (2.39-0ubuntu8.4 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [amd64])\n"
    "Inst libxml2 [2.9.14+dfsg-1.3ubuntu3] (2.9.14+dfsg-1.3ubuntu3.1 Ubuntu:24.04/noble-security [amd64])\n"
    "Inst tzdata [2024a-3ubuntu1] (2024b-0ubuntu0.24.04 Ubuntu:24.04/noble-updates [all])\n"
    "Inst tailscale [1.74.0] (1.76.1 Tailscale:/noble [amd64])\n"
    "Inst postgresql-16 [16.4-0ubuntu0.24.04.1] (16.6-0ubuntu0.24.04.1 Ubuntu:24.04/noble-security [amd64])\n"
    "Inst libpq5 [16.4-0ubuntu0.24.04.1] (16.6-0ubuntu0.24.04.1 Ubuntu:24.04/noble-security [amd64])\n"
    "Remv libde265-0 [1.0.15-1build3]\n"
)


def test_the_pending_set_is_counted_by_class(host):
    host.on("apt-get", "-s *dist-upgrade", SIMULATION)
    host.on(
        "pro",
        "security-status --format json",
        '{"summary": {"ua": {"attached": false}, "num_esm_apps_updates": 29, "num_esm_infra_updates": 0}}',
    )
    host.write(
        "var/lib/apt/lists/archive.ubuntu.com_ubuntu_dists_noble-security_InRelease",
        "x",
        age_days=3,
    )
    out = host.run()
    p = out["pending"]
    assert p["by_class"] == {
        "security_lower_bound": 4,
        "updates": 1,
        "esm_visible": 0,
        "ubuntu_other": 0,
        "third_party": {"Tailscale": 1},
    }
    assert p["packages"]["security"] == ["libc6", "libxml2", "postgresql-16", "libpq5"]
    assert p["removals"] == ["libde265-0"]
    assert p["esm"]["num_esm_apps_updates"] == 29
    assert p["esm"]["attached"] is False
    assert p["lists"]["security_age_hours"] >= 71
    assert _finding(out, "lists:stale")["kind"] == "risk"
    groups = {g["step"]: g["pending"] for g in p["hold_groups"]}
    assert groups["postgres"] == ["postgresql-16", "libpq5"]
    assert groups["docker"] == []


def _policy(name: str, installed: str, candidate: str, suites: list[str]) -> str:
    """apt-cache policy for one package: the candidate in each suite, then the installed version."""
    lines = [
        f"{name}:",
        f"  Installed: {installed}",
        f"  Candidate: {candidate}",
        "  Version table:",
    ]
    if candidate != installed:
        lines.append(f"     {candidate} 500")
        lines += [
            f"        500 http://archive.ubuntu.com/ubuntu {s}/main amd64 Packages"
            for s in suites
        ]
    lines += [
        f" *** {installed} 500",
        "        500 http://archive.ubuntu.com/ubuntu noble/main amd64 Packages",
        "        100 /var/lib/dpkg/status",
    ]
    return "\n".join(lines) + "\n"


def test_an_owner_hold_on_a_pending_package_needs_a_held_exception(host):
    # apt-get -s keeps a held package back, so it never appears as Inst: the
    # probe has to read each hold's versions itself.
    host.on(
        "apt-get",
        "-s *dist-upgrade",
        "The following packages have been kept back:\n  libxml2\n",
    )
    host.on("apt-mark", "showhold", "libxml2\nfoo\ntzdata\n")
    host.on(
        "apt-cache",
        "*policy libxml2",
        _policy(
            "libxml2",
            "2.9.14+dfsg-1.3ubuntu3",
            "2.9.14+dfsg-1.3ubuntu3.1",
            ["noble-updates", "noble-security"],
        ),
    )
    host.on("apt-cache", "*policy foo", _policy("foo", "1.0", "1.0", []))
    host.on(
        "apt-cache",
        "*policy tzdata",
        _policy("tzdata", "2024a-3ubuntu1", "2024b-0ubuntu0.24.04", ["noble-updates"]),
    )
    out = host.run()
    f = _finding(out, "held:libxml2")
    assert f["kind"] == "deviation"
    assert "a security update waiting" in f["message"]
    assert "an update waiting" in _finding(out, "held:tzdata")["message"]
    assert "held:foo" not in _ids(out)
    holds = {h["package"]: h for h in out["pending"]["owner_holds"]}
    assert holds["libxml2"] == {
        "package": "libxml2",
        "installed": "2.9.14+dfsg-1.3ubuntu3",
        "candidate": "2.9.14+dfsg-1.3ubuntu3.1",
        "pending": True,
        "security": True,
    }
    assert holds["tzdata"]["security"] is False
    assert holds["foo"]["pending"] is False
    host.knob(
        "posture automatic\nexception held:libxml2 2099-01-01 waits for the vendor's fix\n"
    )
    out = host.run()
    assert "held:libxml2" not in _ids(out)
    assert _finding(out, "held:libxml2", "excepted")["exception_line"] == 2


def test_the_dry_run_counts_security_exactly_into_its_scratch_cache(host):
    scratch = host.tmp / "dry"
    host.on(
        "unattended-upgrade",
        "--dry-run -d",
        "Allowed origins are: o=Ubuntu,a=noble-security\n"
        "Packages that will be upgraded: libc6 libxml2 libssl3t64 postgresql-16\n",
    )
    out = host.run("--dry-run-into", str(scratch))
    d = out["pending"]["dry_run"]
    assert d["count"] == 4
    assert d["exit"] == 0
    assert d["packages"] == ["libc6", "libxml2", "libssl3t64", "postgresql-16"]
    [(_, _, apt_config)] = host.calls("unattended-upgrade")
    conf = Path(apt_config).read_text()
    assert f'Dir::Cache::archives "{scratch.resolve()}/archives/";' in conf
    assert f'Dir "{host.root.resolve()}/";' in conf
    assert [c for c in host.calls("choom") if "-n 0" in c[1]]


def test_a_refresh_writes_lists_only_into_its_scratch_directory(host):
    scratch = host.tmp / "fresh"
    host.on("apt-get", "update*", "Reading package lists...\n")
    out = host.run("--refresh-into", str(scratch))
    [(_, args, _)] = [
        c
        for c in host.calls("apt-get")
        if " update" in c[1] or c[1].startswith("update")
    ]
    assert f"Dir::State::Lists={scratch.resolve()}/lists/" in args
    assert f"Dir::Cache::archives={scratch.resolve()}/archives/" in args
    assert out["pending"]["lists"]["refreshed"] is True
    sims = [c[1] for c in host.calls("apt-get") if "-s" in c[1].split()]
    assert sims and all(
        f"Dir::State::Lists={scratch.resolve()}/lists/" in s for s in sims
    )


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
        ("postgres", "7000000", "0", "", "C.UTF-8", "c", ""),
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
    assert [c for c in host.calls("sudo") if c[1].startswith("-n -u postgres -- psql")]


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


# --- the environment ------------------------------------------------------------


def test_the_session_chain_is_read_to_pid_1_whatever_its_parents_are(host):
    # Reparented to PID 1 through an sh: a check looking for exe-init or sshd
    # as the parent would skip here and read green (CannObserv/watcher#333).
    host.chain([(4242, "node", -1000), (4200, "sh", -1000), (1, "systemd", 0)])
    out = host.run()
    s = out["environment"]["session"]
    assert [(p["pid"], p["comm"], p["adj"]) for p in s["chain"]] == [
        (4242, "node", -1000),
        (4200, "sh", -1000),
        (1, "systemd", 0),
    ]
    assert s["reaches_pid1"] is True
    assert s["min_adj"] == -1000
    assert _finding(out, "session:adj")["kind"] == "risk"


def test_a_chain_that_leaves_the_pid_namespace_says_so(host):
    # Under docker exec the session's parent is outside the container, so its
    # PPid reads 0 before PID 1 is reached.
    host.chain([(4242, "bash", 0), (4200, "bash", 0)])
    out = host.run()
    assert out["environment"]["session"]["reaches_pid1"] is False
    f = _finding(out, "session:chain")
    assert f["kind"] == "unknown"
    assert "leaves this PID namespace at pid 4200" in f["message"]


def test_persistent_storage_with_the_flush_masked_and_nothing_on_disk_is_volatile(host):
    # Nothing under /run/log/journal either, as in an image read offline: the
    # masked flush alone makes it volatile.
    host.write("etc/systemd/journald.conf", "[Journal]\nStorage=persistent\n")
    host.mask("systemd-journal-flush.service")
    (host.root / "var" / "log" / "journal").mkdir(parents=True)
    out = host.run()
    j = out["environment"]["journal"]
    assert j["storage"] == "persistent"
    assert j["storage_set_in"] == "/etc/systemd/journald.conf:2"
    assert j["flush"] == "masked"
    assert j["persistent_files"] == 0
    assert j["verdict"] == "volatile"
    assert _finding(out, "journal:volatile")["kind"] == "risk"


def test_journal_files_only_under_run_are_volatile(host):
    (host.root / "var" / "log" / "journal").mkdir(parents=True)
    host.write("run/log/journal/abc/system.journal", "x")
    out = host.run()
    assert out["environment"]["journal"]["verdict"] == "volatile"
    assert out["environment"]["journal"]["volatile_files"] == 1


def test_journal_files_on_disk_are_persistent(host):
    host.write("etc/systemd/journald.conf", "[Journal]\nStorage=persistent\n")
    host.write("var/log/journal/abc/system.journal", "x")
    host.on(
        "journalctl",
        "-q -o short-unix --no-pager",
        f"{host.now - 12 * DAY}.000001 web-1 kernel: Linux\n",
    )
    out = host.run()
    j = out["environment"]["journal"]
    assert j["verdict"] == "persistent"
    assert j["reach_days"] == 12
    assert "journal:volatile" not in _ids(out)


def test_a_readable_setup_script_holding_a_key_is_named_by_pattern_and_line_only(host):
    host.write(
        "exe.dev/setup",
        f'#!/bin/sh\nset -e\nTS_AUTHKEY=tskey-auth-{SECRET}\ntailscale up --authkey="$TS_AUTHKEY"\n',
        mode=0o755,
    )
    host.write(
        "usr/lib/systemd/system/exe-setup.service",
        "[Unit]\nConditionPathExists=/exe.dev/setup\n",
    )
    host.show(
        "exe-setup.service",
        LoadState="loaded",
        ConditionResult="yes",
        Result="exit-code",
        ActiveState="failed",
    )
    out = host.run()
    f = _finding(out, "setup-script:present")
    assert f["kind"] == "leftover"
    assert "tailscale-auth-key at line 3" in f["message"]
    assert "readable by every user" in f["message"]
    assert "exit-code" in f["message"]
    s = out["environment"]["setup_script"]
    assert s["file"]["mode"] == "0755"
    assert {"pattern": "tailscale-auth-key", "line": 3} in s["file"]["secrets"]
    assert s["verdict"] == "present"
    for text in (host.result.stdout, host.result.stderr, host.log.read_text()):
        assert SECRET not in text


@pytest.mark.parametrize(
    "journal, verdict, finds",
    [
        (
            "Starting exe-setup.service - Exe setup...\nexe-setup.service: Deactivated successfully.\nFinished exe-setup.service - Exe setup.\n",
            "redelivered",
            True,
        ),
        (
            "exe-setup.service - Exe setup was skipped because of an unmet condition check (ConditionPathExists=/exe.dev/setup).\n",
            "none-delivered",
            False,
        ),
        ("", "unknown", False),
    ],
)
def test_an_absent_setup_script_that_ran_every_boot_is_redelivered_not_clean(
    host, journal, verdict, finds
):
    host.write(
        "usr/lib/systemd/system/exe-setup.service",
        "[Unit]\nConditionPathExists=/exe.dev/setup\n",
    )
    boots = [f"{i:x}" * 32 for i in range(1, 4)]
    host.on(
        "journalctl",
        "--list-boots*",
        "IDX BOOT ID                          FIRST ENTRY                 LAST ENTRY\n"
        + "".join(
            f" {-2 + i} {b[:32]} Mon 2026-09-2{i} 10:00:00 UTC Mon 2026-09-2{i} 11:00:00 UTC\n"
            for i, b in enumerate(boots)
        ),
    )
    for b in boots:
        host.on("journalctl", f"-b {b[:32]} -u exe-setup.service*", journal)
    out = host.run()
    s = out["environment"]["setup_script"]
    assert s["file"]["present"] is False
    assert len(s["boots"]) == 3
    assert s["verdict"] == verdict
    assert ("setup-script:redelivered" in _ids(out)) is finds
    if finds:
        assert (
            "3 retained boots" in _finding(out, "setup-script:redelivered")["message"]
        )


def test_anything_staged_under_tmp_is_listed_and_a_control_byte_never_printed(host):
    host.write("usr/lib/tmpfiles.d/tmp.conf", "D /tmp 1777 root root 30d\n")
    host.write("tmp/staged-binary", "x")
    host.write("tmp/evil\x1b[31mname", "x")
    (host.root / "tmp" / "systemd-private-abc").mkdir()
    out = host.run()
    t = out["environment"]["tmp"]
    assert t["cleared_at_boot"] is True
    assert t["rule"] == "D /tmp 1777 root root 30d"
    assert sorted(t["staged"]) == ["evil?[31mname", "staged-binary"]
    assert "\x1b" not in host.result.stdout


def test_the_probes_own_scratch_directory_is_not_staged(host):
    host.tmpdir = host.root / "tmp"
    host.tmpdir.mkdir()
    host.write("tmp/staged-binary", "x")
    out = host.run()
    assert out["environment"]["tmp"]["staged"] == ["staged-binary"]


# --- exceptions ---------------------------------------------------------------------


def test_an_exception_moves_a_deviation_to_excepted_until_it_expires(host):
    host.mask("apt-daily.timer")
    host.mask("apt-daily-upgrade.timer")
    host.knob(
        "posture automatic\n"
        "exception timer:apt-daily.timer 2099-01-01 masked by the image\n"
        "exception timer:apt-daily-upgrade.timer 2026-09-01 masked by the image\n"
    )
    out = host.run()
    e = _finding(out, "timer:apt-daily.timer", "excepted")
    assert (e["exception_line"], e["review_by"], e["reason"]) == (
        2,
        "2099-01-01",
        "masked by the image",
    )
    assert "timer:apt-daily.timer" not in _ids(out)
    # Expired: the deviation is a finding again, and so is the expiry.
    assert _finding(out, "timer:apt-daily-upgrade.timer")["kind"] == "deviation"
    assert [
        f for f in out["findings"] if f["kind"] == "knob" and "line 3" in f["message"]
    ]


# --- dormant components ---------------------------------------------------------


def _docker(host: Host, containers: str = "") -> Host:
    host.installed("docker.io")
    host.show("docker.service", ActiveState="active")
    host.on("docker", "ps -aq", containers)
    host.on("docker", "images -q", "abc123\n")
    host.on("docker", "volume ls -q", "")
    return host


def test_docker_active_with_no_container_is_dormant(host):
    out = _docker(host).run()
    d = _dormant(out, "docker")
    assert d["verdict"] == "dormant"
    assert d["workload"] == {"containers": 0, "images": 1, "volumes": 0}
    f = _finding(out, "dormant:docker")
    assert f["exception_what"] == "keep:docker"


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


def test_idle_evidence_younger_than_30_days_is_unknown(tmp_path):
    h = Host(tmp_path, uptime_days=10).knob("posture automatic\n")
    out = _docker(h).run()
    d = _dormant(out, "docker")
    assert d["verdict"] == "unknown"
    assert "fewer than 30" in d["evidence"]
    assert "dormant:docker" not in _ids(out)


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


def test_an_inactive_nginx_idle_past_30_days_is_dormant(host):
    host.installed("nginx")
    host.show("nginx.service", ActiveState="inactive", InactiveEnterTimestamp="")
    out = host.run()
    d = _dormant(out, "nginx")
    assert d["verdict"] == "dormant"
    assert "40 days" in d["evidence"]


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


def _mutating(name: str, args: str) -> bool:
    """Whether one stubbed call would change the host."""
    a = args.split()
    if name == "apt-get":
        if "-s" in a:
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
        "backup app-backup.service\n"
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
