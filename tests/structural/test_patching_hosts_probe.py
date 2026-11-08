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
- a database no `datastore` line names is a finding, but the templates are
  not, nor `postgres` while it holds no table of its own.

Beyond that list, from running it live against a booted systemd 255, and
from review:

- a hold is read from `apt-cache policy`, since `apt-get -s` keeps a held
  package back.
- an empty psql field keeps its place.
- idle time counts from systemd's start, not the kernel's.
- stock Ubuntu's release pocket isn't a widening.
- the output is ASCII.
- a vendor's origin name stays literal: never globbed, and escaped as a key.
- after a boot, a service's first start is read from the journal: a start by
  hand doesn't count in NRestarts.
- a knob command runs under a time limit, so a hung check can't hang the probe.
- a line parsed from a root command stays English when sudo resets the locale.
- every idle window counts from the component's own start, never the kernel's.
- a dormant component lists only its pending security packages.
- a dry run that exits 0 without a selection line is a finding, not silence.
- an empty unit file is a mask, as systemd reads it.
- a hold on a package that isn't installed defers nothing.
- a refused run leaves no scratch directory behind.
- an active engine whose CLI isn't on PATH says so.
- the ESM counts say they come from the host's own lists.
- tables kept in the `postgres` database are data like any other's.
- a dry run's empty selection line counts 0.
- a first start that never stopped holds by its own timestamps, with no
  journal behind them.
- the dry run's selection is security only while unattended-upgrades'
  origins are.
- a database's statistics cover no more than its own life.
- a knob command that ignores the time limit's TERM is killed.
- pro isn't asked about an offline tree, which it can't read.
- the catalog query names no column Postgres 14 lacks.
- a database's name stays whole: never split or globbed.
- a database only read isn't dormant: its sessions show the reads.
- a Redis with no key isn't dormant while anything looks it up, lets keys
  expire, subscribes or connects.
- every Postgres cluster counts toward the verdict: an unread or recently
  stopped one makes it unknown.
- a refused pg_stat_file costs only the creation dates.
- on Postgres 14 the provider reads libc, the only one it had.
- the image's own markers name the profile in an offline tree, and only
  they date the generation.
- the dry run makes the `archives/partial` its fetcher needs, and a failed
  one still reports its max RSS past GNU time's status line (plan step 6's
  live run).

Plan step 4: the probe names the environment profile and the image
generation from the profile's markers, each read on its own, and names none
on a host no profile matches.

Plan step 5, from the real image: an idle Docker is never asked, since
docker.socket would start it, and what it holds is read from disk.

Plan step 8, where the code broke what its help promised:
- a dry run that doesn't run leaves no earlier summary behind (CR 191);
- under --root the host is the tree's etc/hostname, trimmed, or a usage
  error, never the probing machine's (CR 192);
- maps, each hold group's pending, the unattended-upgrades origins and
  needrestart's services are null when unread, never empty (CR 193).

Plan step 8b, from replicator's run under the scripts:
- a phased update is in the pending set and flagged with its percentage, and
  what a dry run selects that no class list names is a finding (#354);
- the session's adj stops below the platform's agent, exe-init or exe.dev's
  sshd, whose own -1000 is reported apart (#353, CR 201);
- an OnFailure= target is a restarter when it starts or restarts something,
  and is cleared only when everything it runs was read (#351, CR 199);
- a redelivered setup script takes an exception, and one contained in place,
  root's alone with its unit disabled, is no leftover (#352);
- after a boot, a persistent journal's record is its previous boot's
  "Journal stopped", and a volatile one's is the chain's own log line about
  its copy (#356, CR 200);
- a service's uv.lock is audited in a fresh copy, as the lockfile's owner and
  never as root, and a tree it couldn't audit, or any other lockfile, is
  "not audited", never clean (#366, plan 6g).

Each case runs the whole script under the system's bash (3.2 on macOS)
against a fixture root under tmp_path, with `run/systemd/system` marking it
live, and stubs on PATH for every command that asks the running system. Each
stub logs its argv, which is what the no-writes test reads. The rig is
patching_hosts_rig.py, shared with apply.sh's tests.

Under `--dist loadfile` a file runs on one worker, so one file holding every
probe case set the parallel suite's floor (#538). The environment's sections
moved to test_patching_hosts_probe_environment.py, and impact, the
components and what the probe writes to
test_patching_hosts_probe_components.py. Both import this file's Host and
helpers, so the pins listed above span all three files.
"""

import os
import subprocess
from pathlib import Path

import pytest

from tests.structural.patching_hosts_rig import SKILL, dispatcher
from tests.structural.patching_hosts_rig import Host as RigHost
from tests.structural.patching_hosts_rig import clean_env as _clean_env
from tests.structural.test_patching_hosts_space import (
    CONF as GC_CONF,
)
from tests.structural.test_patching_hosts_space import (
    DOWNLOAD,
    DPKG,
    FLOOR,
    GROWTH,
    PEAK,
    SHOW,
    SIM,
    df_row,
)

PROBE = SKILL / "scripts" / "probe.sh"
TODAY = "2026-09-30"
SECRET = "kSECRETVALUE123-abcdefGHIJKL"
# What apt would fetch into the dry run's DIR/archives (#499): the format
# noble's apt 2.8.3 prints for `apt-get --print-uris -qq`, with the sizes of
# the tzdata, age and bison the space fixtures resolve, 2660798 bytes.
PRINT_URIS = (
    "'http://archive.ubuntu.com/ubuntu/pool/main/t/tzdata/tzdata_2026e-0ubuntu0.24.04.1_all.deb'"
    " tzdata_2026e-0ubuntu0.24.04.1_all.deb 282136 MD5Sum:d04b4d9c76a0acb9f3bdd9408abb857e\n"
    "'http://archive.ubuntu.com/ubuntu/pool/universe/a/age/age_1.1.1-1ubuntu0.24.04.3_amd64.deb'"
    " age_1.1.1-1ubuntu0.24.04.3_amd64.deb 1629868 MD5Sum:ebd0a1a1db79453e54687d06eaf13415\n"
    "'http://archive.ubuntu.com/ubuntu/pool/main/b/bison/bison_3.8.2+dfsg-1ubuntu0.24.04.1_amd64.deb'"
    " bison_2%3a3.8.2+dfsg-1ubuntu0.24.04.1_amd64.deb 748794 MD5Sum:dfd0ee7383158a5021011734efd1fac7\n"
)


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


class Host(RigHost):
    # df answers as the system's own unless a case says otherwise (#390).
    STUBBED = (*RigHost.STUBBED, "df")
    FALLBACKS = {
        **RigHost.FALLBACKS,
        "df": 'for d in /bin /usr/bin; do [ -x "$d/df" ] && exec "$d/df" "$@"; done; exit 127',
    }

    def run(self, *args: str, rc: int = 0, root: bool = True):
        # What the dry run's selection would write (#390): noble's real
        # output for tzdata, age and bison, after every case a test set.
        for cmd, glob, out in (
            ("apt-get", "-s *install --only-upgrade *", SIM),
            ("apt-get", "--print-uris *", PRINT_URIS),
            ("apt-cache", "* show *", SHOW),
            (
                "dpkg-query",
                "*-W -f ${Package}:${Architecture} ${Installed-Size}*",
                DPKG,
            ),
        ):
            if not any(c[0] == glob for c in self.cases[cmd]):
                self.on(cmd, glob, out)
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
        return self.execute(cmd, rc)


def _ids(out: dict, key: str = "findings") -> list[str]:
    return [f["id"] for f in out[key]]


def _finding(out: dict, fid: str, key: str = "findings") -> dict:
    hits = [f for f in out[key] if f["id"] == fid]
    assert hits, f"no {fid} in {key}: {_ids(out, key)}"
    return hits[0]


@pytest.fixture
def host(tmp_path) -> Host:
    # The probe files' one `host`: _environment and _components bind this
    # same fixture by name (#538).
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
    assert not (tmp_path / "scratch").exists()


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


def test_an_empty_unit_file_is_a_mask(tmp_path):
    # systemd.unit(5): an empty unit file loads as masked, like a symlink to
    # /dev/null.
    h = Host(tmp_path, live=False).knob("posture scheduled\n")
    h.write("etc/systemd/system/apt-daily.timer", "")
    h.mask("apt-daily-upgrade.timer")
    out = h.run()
    units = {u["unit"]: u["disk"] for u in out["updates"]["units"]}
    assert units["apt-daily.timer"] == "masked"
    assert not [i for i in _ids(out) if i.startswith("timer:")]


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
        # Every Ubuntu pocket carries the release's codename, so this takes
        # -updates and -backports too (noble's Release files, 2026-10-01).
        (
            'Unattended-Upgrade::Origins-Pattern:: "origin=Ubuntu,codename=${distro_codename}";\n',
            "codename=${distro_codename}",
        ),
        # unattended-upgrade matches each field with fnmatch.
        (
            'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:*";\n',
            "${distro_id}:*",
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


def test_a_vendors_origin_name_stays_literal_and_valid_json(host):
    # A repository names its own origin. Split unquoted, a "*" would expand
    # against the current directory; written raw, a quote would break the JSON.
    host.on(
        "apt-get",
        "-s *dist-upgrade",
        'Inst a [1] (2 Ev"il\\x:1/stable [all])\nInst b [1] (2 *:1/stable [all])\n',
    )
    out = host.run()
    assert out["pending"]["by_class"]["third_party"] == {'Ev"il\\x': 1, "*": 1}
    assert host.result.stdout.isascii()


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


def test_the_pending_set_is_counted_by_class(tmp_path):
    # CR 1446: with no os-release, a list counts as fetched only from the
    # probe's start on, and one written a second boundary before it read as
    # unpacked (72 h). A tree unpacked two hours ago dates it as a fetch.
    host = StatHost(tmp_path).knob("class production\nposture automatic\n")
    host.write(OS_RELEASE, 'NAME="Ubuntu"\n')
    host.ctime(OS_RELEASE, host.now - 2 * 3600)
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
        # #361: unknown without a dry run.
        "passed_over": None,
    }
    assert p["packages"]["security"] == ["libc6", "libxml2", "postgresql-16", "libpq5"]
    assert p["removals"] == ["libde265-0"]
    assert p["esm"]["num_esm_apps_updates"] == 29
    assert p["esm"]["attached"] is False
    # #493: the archive last published 3 days ago, and the lists were
    # fetched just now, so they're current.
    assert p["lists"]["security_last_modified_hours"] >= 71
    assert p["lists"]["security_age_hours"] == 0
    assert "lists:stale" not in _ids(out)
    groups = {g["step"]: g["pending"] for g in p["hold_groups"]}
    assert groups["postgres"] == ["postgresql-16", "libpq5"]
    assert groups["docker"] == []


# --- the lists' age (#493) -----------------------------------------------------
# apt sets a list's mtime from the archive's Last-Modified, so a quiet day for
# noble-security read as stale lists right after a host apt-get update. What
# moves at a fetch, measured on noble (apt 2.8.3, 2026-10-30): each InRelease's
# ctime, at a Get and at a Hit alike, and only when it was fetched. lists/
# partial/'s mtime moves at a failed update too, and nothing in apt writes
# /var/lib/apt/periodic/update-success-stamp: update-notifier-common's hook
# does, where it's installed.

SECURITY_IN_RELEASE = (
    "var/lib/apt/lists/archive.ubuntu.com_ubuntu_dists_noble-security_InRelease"
)


class StatHost(Host):
    """stat answering a file's ctime as a case sets it, and as the system's
    stat otherwise: a ctime can't be set back, nor an hour's gap slept for
    (CR 1300)."""

    STUBBED = (*Host.STUBBED, "stat")
    FALLBACKS = {
        **Host.FALLBACKS,
        "stat": 'for d in /usr/bin /bin; do [ -x "$d/stat" ] && exec "$d/stat" "$@"; done; exit 127',
    }

    def ctime(self, path: str, epoch: int) -> "StatHost":
        """PATH's ctime, as file_ctime reads it: PATH ends the argv."""
        return self.on("stat", f"-c %Z *{path}", f"{epoch}\n")


class LaterHost(StatHost):
    """The probe's clock HOURS on from the tree's, so a list written now
    reads as fetched HOURS ago: a ctime can't be set back."""

    STUBBED = (*StatHost.STUBBED, "date")
    FALLBACKS = {
        **StatHost.FALLBACKS,
        "date": 'for d in /bin /usr/bin; do [ -x "$d/date" ] && exec "$d/date" "$@"; done; exit 127',
    }

    def __init__(self, tmp_path, hours: int):
        super().__init__(tmp_path)
        self.on("date", "+%s", f"{self.now + hours * 3600 + 600}\n")


# CR 1295: a ctime is also when a tree was unpacked, so a list that came
# with an image would read as fetched at provisioning. The reference is a
# file apt-get update never writes; a list it fetched is newer.
OS_RELEASE = "usr/lib/os-release"


def _unpacked_then_fetched(host: StatHost) -> None:
    """The tree's own file, unpacked 5 hours before a fetch's list now."""
    host.write(OS_RELEASE, 'NAME="Ubuntu"\n')
    host.ctime(OS_RELEASE, host.now - 5 * 3600)


def test_the_lists_age_from_their_fetch_not_the_archives_last_modified(tmp_path):
    # co-processor, 2026-10-26: noble-security hadn't published for 26 h.
    host = StatHost(tmp_path)
    _unpacked_then_fetched(host)
    host.write(SECURITY_IN_RELEASE, "x", age_days=26 / 24)
    out = host.run()
    lists = out["pending"]["lists"]
    assert lists["security_age_hours"] == 0
    assert lists["security_last_modified_hours"] >= 25
    assert "fetched" in lists["source"]
    assert "lists:stale" not in _ids(out)


@pytest.mark.parametrize("hours, stale", [(30, True), (20, False)])
def test_lists_fetched_more_than_a_day_ago_are_stale(tmp_path, hours, stale):
    host = LaterHost(tmp_path, hours)
    _unpacked_then_fetched(host)
    host.write(SECURITY_IN_RELEASE, "x")
    out = host.run()
    assert out["pending"]["lists"]["security_age_hours"] == hours
    assert ("lists:stale" in _ids(out)) is stale
    if stale:
        f = _finding(out, "lists:stale")
        assert f["kind"] == "risk"
        assert f"fetched {hours} hours ago" in f["message"]


@pytest.mark.parametrize("reference", [True, False], ids=["unpacked", "no-reference"])
def test_lists_unpacked_with_the_tree_age_from_their_last_modified(tmp_path, reference):
    # The image's lists, unpacked with the tree: their ctime is the unpack's,
    # no newer than os-release's, so it says nothing of a fetch. Without the
    # reference file, nothing tells the two apart either.
    host = LaterHost(tmp_path, 1)
    host.write(SECURITY_IN_RELEASE, "x", age_days=3)
    if reference:
        host.write(OS_RELEASE, 'NAME="Ubuntu"\n')
    out = host.run()
    lists = out["pending"]["lists"]
    assert lists["security_age_hours"] == lists["security_last_modified_hours"] >= 73
    assert "unpack" in lists["source"]
    assert _finding(out, "lists:stale")["kind"] == "risk"


@pytest.mark.parametrize(
    "gap, fetched", [(5, False), (3601, True)], ids=["within-margin", "past-margin"]
)
def test_a_list_within_an_hour_of_the_unpack_reads_as_unpacked(tmp_path, gap, fetched):
    # CR 1300: an image's layers unpack over seconds (buildpack-deps:noble's
    # top layer 1 s after os-release's), and a RUN apt-get update puts its
    # lists in a later layer. Only a ctime past the margin is a fetch.
    host = StatHost(tmp_path)
    # CR 1445: half an hour more, so the fetch's age is mid-hour; at a whole
    # hour less 1 s, a probe whose clock read 1 s after this one's got 3, not 2.
    ref = host.now - 3 * 3600 - 1800
    host.write(OS_RELEASE, 'NAME="Ubuntu"\n')
    host.ctime(OS_RELEASE, ref)
    host.write(SECURITY_IN_RELEASE, "x", age_days=3)
    host.ctime(SECURITY_IN_RELEASE, ref + gap)
    out = host.run()
    lists = out["pending"]["lists"]
    if fetched:
        assert lists["security_age_hours"] == (host.now - ref - gap) // 3600
        assert "lists:stale" not in _ids(out)
        return
    assert lists["security_age_hours"] == lists["security_last_modified_hours"] >= 72
    assert "an hour" in lists["source"]
    assert _finding(out, "lists:stale")["kind"] == "risk"


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


def test_a_hold_on_a_package_that_isnt_installed_defers_nothing(host):
    host.on("apt-mark", "showhold", "ghost\n")
    host.on(
        "apt-cache",
        "*policy ghost",
        _policy("ghost", "(none)", "1.0", ["noble-security"]),
    )
    out = host.run()
    assert out["pending"]["owner_holds"] == [
        {
            "package": "ghost",
            "installed": "(none)",
            "candidate": "1.0",
            "pending": False,
        }
    ]
    assert "held:ghost" not in _ids(out)


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
    # apt fetches into archives/partial, which the fetcher never makes.
    assert (scratch / "archives" / "partial").is_dir()
    assert d["max_rss_kib"] == 2048
    # apply.sh reads its cost, and when it began, from the summary.
    summary = (scratch / "summary").read_text()
    assert "exit=0\ncount=4\n" in summary
    assert "wall_seconds=" in summary
    began = int(summary.split("began=")[1].split("\n")[0])
    assert host.now - 5 <= began <= host.now + 300
    [(_, _, apt_config)] = host.calls("unattended-upgrade")
    conf = Path(apt_config).read_text()
    assert f'Dir::Cache::archives "{scratch.resolve()}/archives/";' in conf
    assert f'Dir "{host.root.resolve()}/";' in conf
    assert [c for c in host.calls("choom") if "-n 0" in c[1]]


# --- the dry run's free space (#390) ------------------------------------------


def _counted(host: Host) -> Host:
    host.on(
        "unattended-upgrade",
        "--dry-run -d",
        "Packages that will be upgraded: tzdata age bison\n",
    )
    return host


def test_help_says_what_the_dry_runs_space_reads():
    r = subprocess.run(
        ["bash", str(PROBE), "--help"], capture_output=True, text=True, env=_clean_env()
    )
    text = " ".join(r.stdout.split())
    for words in (
        "pending.dry_run.space",
        "131072 KiB",
        "/var/backups",
        "alert_at_percent",
    ):
        assert words in text, words


def test_the_dry_run_sizes_what_the_run_writes_and_the_free_space_beside_it(host):
    out = _counted(host).run("--dry-run-into", str(host.tmp / "dry"))
    d = out["pending"]["dry_run"]
    assert (d["space"]["download_kib"], d["space"]["growth_kib"]) == (DOWNLOAD, GROWTH)
    assert d["space"]["peak_kib"] == PEAK
    assert d["space"]["headroom"] is None
    assert isinstance(d["free_kib_root"], int)
    assert isinstance(d["free_kib_run_dir"], int)
    assert not [i for i in _ids(out) if i.startswith("dry-run:space")]
    # Sized from the selection, against the tree's own apt and dpkg.
    [sim] = [a for _, a, _ in host.calls("apt-get") if "--only-upgrade" in a]
    assert sim.endswith("install --only-upgrade tzdata age bison")
    assert "-o Debug::NoLocking=1" in sim
    [q] = [a for _, a, _ in host.calls("dpkg-query") if "Installed-Size" in a]
    assert q.startswith(f"--admindir={host.root}/var/lib/dpkg -W ")


def test_a_run_that_wouldnt_fit_is_a_finding(host):
    _counted(host)
    # The dry run's own download fits in DIR (#499); the run doesn't.
    host.on("df", f"-Pk -- {host.tmp}/dry/archives", df_row(1, 9000000, "/scratch"))
    host.on("df", "-Pk -- *", df_row(9000000, 1000))
    out = host.run("--dry-run-into", str(host.tmp / "dry"))
    f = _finding(out, "dry-run:space:disk")
    assert f["kind"] == "risk"
    assert f["message"].startswith("The run needs ")
    assert "131072 KiB floor" in f["message"]
    assert out["pending"]["dry_run"]["free_kib_root"] == 1000


# --- the dry run's own download (#499) ----------------------------------------
# It downloads the lane's whole selection into DIR/archives as root, so it is
# sized first, from apt's own --print-uris against the dry run's own apt
# config: an upper bound, since the selection isn't known until it has run.


def test_the_dry_run_sizes_its_own_download_before_it_starts(host):
    out = _counted(host).run("--dry-run-into", str(host.tmp / "dry"))
    d = out["pending"]["dry_run"]
    assert d["download_bound_kib"] == DOWNLOAD
    assert isinstance(d["free_kib_dry_run_dir"], int)
    calls = host.calls()
    [i] = [
        i
        for i, c in enumerate(calls)
        if c[0] == "apt-get" and c[1].startswith("--print-uris")
    ]
    [j] = [i for i, c in enumerate(calls) if c[0] == "unattended-upgrade"]
    assert i < j
    _, args, apt_config = calls[i]
    # Where the dry run downloads, and against the lists it counts with.
    assert apt_config == str(host.tmp / "dry" / "apt.conf") == calls[j][2]
    assert args.endswith(" dist-upgrade")
    assert "-o Debug::NoLocking=1" in args
    assert "-o APT::Get::Always-Include-Phased-Updates=true" in args


@pytest.mark.parametrize("short", [1, 0], ids=["short-1-kib", "exactly-enough"])
def test_a_dry_run_whose_download_wouldnt_fit_doesnt_start(host, short):
    _counted(host)
    dry = host.tmp / "dry"
    free = DOWNLOAD + FLOOR - short
    host.on("df", f"-Pk -- {dry}/archives", df_row(9000000, free, "/scratch"))
    out = host.run("--dry-run-into", str(dry))
    if not short:
        assert out["pending"]["dry_run"]["free_kib_dry_run_dir"] == free
        assert host.calls("unattended-upgrade")
        assert "dry-run" not in _ids(out)
        return
    f = _finding(out, "dry-run")
    assert f["kind"] == "risk"
    for words in (f"{DOWNLOAD} KiB", f"{FLOOR} KiB floor", "/scratch", f"{free}"):
        assert words in f["message"], words
    assert out["pending"]["dry_run"] is None
    assert not host.calls("unattended-upgrade")
    assert not (dry / "summary").exists()


@pytest.mark.parametrize("unread", ["print-uris", "df"])
def test_a_dry_run_whose_download_cant_be_sized_doesnt_start(host, unread):
    _counted(host)
    dry = host.tmp / "dry"
    if unread == "print-uris":
        host.on("apt-get", "--print-uris *", rc=100, stderr="E: Broken packages\n")
    else:
        host.on("df", f"-Pk -- {dry}/archives", rc=1)
    out = host.run("--dry-run-into", str(dry))
    f = _finding(out, "dry-run")
    assert f["kind"] == "unknown"
    assert "didn't run" in f["message"]
    assert out["pending"]["dry_run"] is None
    assert not host.calls("unattended-upgrade")


def test_help_says_the_dry_run_sizes_its_download_first():
    r = subprocess.run(
        ["bash", str(PROBE), "--help"], capture_output=True, text=True, env=_clean_env()
    )
    text = " ".join(r.stdout.split())
    assert "--print-uris" in text
    assert "download_bound_kib" in text


def test_a_run_that_would_cross_the_gcs_headroom_line_is_a_finding(host):
    _counted(host)
    host.write(GC_CONF, "[sensor]\nalert_at_percent = 80\n")
    # 80% used less 1 KiB: the run's 2599 KiB and 281 KiB cross the line.
    host.on("df", "-Pk -- *", df_row(7999999, 2000001))
    out = host.run("--dry-run-into", str(host.tmp / "dry"))
    f = _finding(out, "dry-run:space:headroom")
    assert f["kind"] == "risk"
    assert "alert_at_percent of 80" in f["message"]
    assert out["pending"]["dry_run"]["space"]["headroom"]["mount"] == "/"


@pytest.mark.parametrize(
    "conf",
    ["[sensor]\nalert_at_percent = 80 # tighter\n", None],
    ids=["malformed", "unreadable"],
)
def test_a_gc_config_that_cant_be_read_is_a_finding(host, conf):
    _counted(host)
    if conf is None:
        (host.root / GC_CONF).mkdir(parents=True)
    else:
        host.write(GC_CONF, conf)
    out = host.run("--dry-run-into", str(host.tmp / "dry"))
    f = _finding(out, "dry-run:space:disk-gc-conf")
    assert f["kind"] == "unknown"
    assert f["message"].startswith(str(host.root / GC_CONF) + ": ")


def test_sizes_the_dry_run_cant_read_are_a_finding(host):
    _counted(host)
    host.on("apt-cache", "* show *", "", rc=100, stderr="E: no such version\n")
    out = host.run("--dry-run-into", str(host.tmp / "dry"))
    f = _finding(out, "dry-run:space")
    assert f["kind"] == "unknown"
    assert "apt-cache show exited 100" in f["message"]
    assert out["pending"]["dry_run"]["space"] is None


def test_the_dry_run_records_the_version_it_counted_of_each_held_package(host):
    # #383: broker's tailscale step took a release published between the dry
    # run and the apply. The summary keeps what the dry run counted, for the
    # steps to compare.
    scratch = host.tmp / "dry"
    host.knob("class production\nposture automatic\nhold tailscale tailscale\n")
    host.cases["apt-get"].insert(
        0,
        (
            "-s *dist-upgrade",
            "Inst libc6 [2.39-0ubuntu8.5] (2.39-0ubuntu8.6 Ubuntu:24.04/noble-security [arm64])\n"
            "Inst postgresql-16 [16.9-0ubuntu0.24.04.1] (16.10-0ubuntu0.24.04.1 Ubuntu:24.04/noble-security [arm64])\n"
            "Inst tailscale [1.102.3] (1.102.4 Tailscale:stable [arm64])\n"
            "Inst newpkg (1.0 Ubuntu:24.04/noble-security [arm64])\n",
            0,
            "",
            None,
        ),
    )
    host.on(
        "unattended-upgrade",
        "--dry-run -d",
        "Packages that will be upgraded: libc6 postgresql-16 tailscale\n",
    )
    out = host.run("--dry-run-into", str(scratch))
    assert out["pending"]["dry_run"]["held_versions"] == [
        {"package": "postgresql-16", "version": "16.10-0ubuntu0.24.04.1"},
        {"package": "tailscale", "version": "1.102.4"},
    ]
    summary = (scratch / "summary").read_text()
    assert (
        "held_versions=postgresql-16=16.10-0ubuntu0.24.04.1 tailscale=1.102.4\n"
        in summary
    )


PHASED_SIM = (
    "Inst libc6 [2.39-0ubuntu8.3] (2.39-0ubuntu8.4 Ubuntu:24.04/noble-security [amd64])\n"
    "Inst dnsmasq-base [2.90-2ubuntu0.4] (2.91-0ubuntu0.24.04.2 Ubuntu:24.04/noble-updates [amd64])\n"
)
PHASED_POLICY = (
    "libc6:\n  Installed: 2.39-0ubuntu8.3\n  Candidate: 2.39-0ubuntu8.4\n  Version table:\n"
    "     2.39-0ubuntu8.4 500\n"
    "        500 http://archive.ubuntu.com/ubuntu noble-security/main amd64 Packages\n"
    "dnsmasq-base:\n  Installed: 2.90-2ubuntu0.4\n  Candidate: 2.91-0ubuntu0.24.04.2\n"
    "  Version table:\n"
    "     2.91-0ubuntu0.24.04.2 500 (phased 10%)\n"
    "        500 http://archive.ubuntu.com/ubuntu noble-updates/main amd64 Packages\n"
    " *** 2.90-2ubuntu0.4 500\n"
    "        100 /var/lib/dpkg/status\n"
)


def test_a_phased_update_is_in_the_pending_set_and_flagged(host):
    # #354: apt-get -s defers a phased update outside the machine's phase,
    # and unattended-upgrade takes it anyway, so the counts left it out.
    host.on(
        "apt-get",
        "-s -o Debug::NoLocking=1 -o APT::Get::Always-Include-Phased-Updates=true *dist-upgrade",
        PHASED_SIM,
    )
    host.on("apt-cache", "*policy libc6 dnsmasq-base", PHASED_POLICY)
    out = host.run()
    p = out["pending"]
    assert p["by_class"]["updates"] == 1
    assert p["packages"]["updates"] == ["dnsmasq-base"]
    assert p["phased"] == {"dnsmasq-base": 10}


def test_a_dry_run_selection_the_class_lists_dont_name_is_a_finding(host):
    host.on("apt-get", "-s *dist-upgrade", PHASED_SIM.split("\n")[0] + "\n")
    host.on(
        "unattended-upgrade",
        "--dry-run -d",
        "Packages that will be upgraded: libc6 dnsmasq-base\n",
    )
    out = host.run("--dry-run-into", str(host.tmp / "dry"))
    assert out["pending"]["dry_run"]["unlisted"] == ["dnsmasq-base"]
    f = _finding(out, "dry-run:unlisted")
    assert f["kind"] == "risk"
    assert "dnsmasq-base" in f["message"]
    # Nothing unlisted, no finding.
    host.cases["apt-get"].insert(0, ("-s *dist-upgrade", PHASED_SIM, 0, "", None))
    out = host.run("--dry-run-into", str(host.tmp / "dry2"))
    assert out["pending"]["dry_run"]["unlisted"] == []
    assert "dry-run:unlisted" not in _ids(out)


def test_a_package_passed_over_at_a_conffile_prompt_is_named_with_its_conffiles(host):
    # #361: the exeuntu image deleted fwupd's motd conffile, and
    # unattended-upgrade passed fwupd over at the prompt and exited 1. The
    # probe said only "exit 1".
    said = "Package fwupd has conffile prompt and needs to be upgraded manually\n"
    fwupd = "Inst fwupd [1.9.16-1] (1.9.30-0ubuntu1~24.04.1 Ubuntu:24.04/noble-updates [amd64])\n"
    host.cases["apt-get"].insert(
        0, ("-s *dist-upgrade", SIMULATION + fwupd, 0, "", None)
    )
    host.on(
        "unattended-upgrade",
        "--dry-run -d",
        said
        + "Packages blacklist due to conffile prompts: ['fwupd$']\n"
        + said
        + "Packages that will be upgraded: libc6\n",
        rc=1,
    )
    host.on(
        "dpkg-query",
        "*-W -f ${Conffiles}\\n fwupd",
        " /etc/update-motd.d/85-fwupd 0123abcd\n"
        " /etc/fwupd/fwupd.conf 4567cdef\n"
        " /etc/fwupd/old.conf 89ab0123 obsolete\n",
    )
    host.write("etc/fwupd/fwupd.conf", "unchanged\n")
    host.STUBBED = (*host.STUBBED, "md5sum")
    host.cases["md5sum"] = [("*fwupd.conf", "4567cdef  x\n", 0, "", None)]
    out = host.run("--dry-run-into", str(host.tmp / "dry"))
    d = out["pending"]["dry_run"]
    assert d["conffile_prompts"] == [
        {
            "package": "fwupd",
            "class": "updates",
            "conffiles": [{"path": "/etc/update-motd.d/85-fwupd", "state": "missing"}],
        }
    ]
    # #361: the class counts mark what the lane won't install.
    assert out["pending"]["by_class"]["updates"] == 2
    assert out["pending"]["by_class"]["passed_over"] == {"updates": 1}
    f = _finding(out, "dry-run:conffile:fwupd")
    assert f["kind"] == "risk"
    assert "/etc/update-motd.d/85-fwupd (missing)" in f["message"]
    assert "exception held:fwupd" in f["message"]
    assert "though by_class.updates counts it" in f["message"]
    # CR 212: the exit code it read, not one assumed.
    assert "(the dry run exited 1)" in f["message"]
    assert "dry-run:conffile" in _finding(out, "dry-run")["message"]
    # CR 213: dpkg-query is asked once, for the record and the finding both.
    asks = [c for c in host.calls("dpkg-query") if "Conffiles" in c[1]]
    assert len(asks) == 1


# #582: on address-validator's Feb-2026 image, fwupd's installed 1.9.33 had
# left noble-updates, so apt-cache policy listed it from dpkg's status file
# alone, and a --force-confmiss reinstall resolved to 2.0.20: a three-package
# upgrade outside the gate, the window and the recovery point.
FWUPD_INSTALLED = "1.9.33-0ubuntu1~24.04.1ubuntu1"
FWUPD_CANDIDATE = "2.0.20-1ubuntu2~24.04.2"


def _fwupd_policy(
    installed_sources: list[str],
    status: str = "        100 /var/lib/dpkg/status",
) -> str:
    lines = [
        "fwupd:",
        f"  Installed: {FWUPD_INSTALLED}",
        f"  Candidate: {FWUPD_CANDIDATE}",
        "  Version table:",
        f"     {FWUPD_CANDIDATE} 500",
        "        500 http://archive.ubuntu.com/ubuntu noble-updates/main amd64 Packages",
        f" *** {FWUPD_INSTALLED} 100",
        *installed_sources,
        status,
        "     1.9.15-2 500",
        "        500 http://archive.ubuntu.com/ubuntu noble/main amd64 Packages",
    ]
    return "\n".join(lines) + "\n"


def _conffile_prompt(host: Host, policy: str | None, missing: bool = True) -> dict:
    said = "Package fwupd has conffile prompt and needs to be upgraded manually\n"
    fwupd = f"Inst fwupd [{FWUPD_INSTALLED}] ({FWUPD_CANDIDATE} Ubuntu:24.04/noble-updates [amd64])\n"
    host.cases["apt-get"].insert(
        0, ("-s *dist-upgrade", SIMULATION + fwupd, 0, "", None)
    )
    host.on(
        "unattended-upgrade",
        "--dry-run -d",
        said + "Packages that will be upgraded: libc6\n",
        rc=1,
    )
    host.on(
        "dpkg-query",
        "*-W -f ${Conffiles}\\n fwupd",
        " /etc/update-motd.d/85-fwupd 0123abcd\n /etc/fwupd/fwupd.conf 4567cdef\n",
    )
    host.write("etc/fwupd/fwupd.conf", "changed\n")
    host.STUBBED = (*host.STUBBED, "md5sum")
    host.cases["md5sum"] = [("*fwupd.conf", "ffff0000  x\n", 0, "", None)]
    if not missing:
        host.write("etc/update-motd.d/85-fwupd", "unchanged\n")
        host.cases["md5sum"].insert(0, ("*85-fwupd", "0123abcd  x\n", 0, "", None))
    if policy is None:
        host.on("apt-cache", "*policy fwupd", "", rc=100, stderr="E: broken\n")
    else:
        host.on("apt-cache", "*policy fwupd", policy)
    out = host.run("--dry-run-into", str(host.tmp / "dry"))
    return _finding(out, "dry-run:conffile:fwupd")


CONFMISS = "Dpkg::Options::=--force-confmiss"


def _reinstall_offered(msg: str, version: str = FWUPD_INSTALLED) -> bool:
    """Whether the finding offers the reinstall, which must name the build.

    CR 1955: a conffile prompt always has a newer candidate pending, and an
    unversioned apt-get install --reinstall takes it: on noble's apt, curl's
    upgraded 2 packages where curl=<installed> reinstalled 1 (2026-11-07).
    """
    named = f"apt-get install --reinstall -o {CONFMISS} 'fwupd={version}'"
    assert msg.count(CONFMISS) == msg.count(named), msg
    return named in msg


def test_a_reinstall_that_would_upgrade_isnt_offered_as_a_reinstall(host):
    f = _conffile_prompt(host, _fwupd_policy([]))
    assert not _reinstall_offered(f["message"])
    assert (
        f"a reinstall with --force-confmiss would upgrade it to {FWUPD_CANDIDATE}"
        in f["message"]
    )
    assert f"apt lists its installed {FWUPD_INSTALLED} from no archive" in f["message"]
    # The deleted conffile's own restore, which touches no package state.
    assert (
        f"restore the deleted conffile alone from the {FWUPD_INSTALLED} .deb"
        in f["message"]
    )
    # CR 1948: the general recipe, not one host's worked example.
    assert "(policy.md, the conffile restore)" in f["message"]
    assert "exe-dev-exeuntu.md" not in f["message"]


def test_a_reinstall_of_a_build_still_in_an_archive_is_offered(host):
    archive = (
        "        500 http://archive.ubuntu.com/ubuntu noble-updates/main amd64 Packages"
    )
    f = _conffile_prompt(host, _fwupd_policy([archive]))
    assert _reinstall_offered(f["message"])
    assert "would upgrade" not in f["message"]
    assert "restore the deleted conffile alone" in f["message"]


def test_a_reinstall_names_a_version_with_an_epoch_as_apt_prints_it(host):
    # A version can carry an epoch, ~ and +: the command names it verbatim,
    # quoted, never the bare package.
    epoch = "1:1.9.33+dfsg-0ubuntu1~24.04.1"
    archive = (
        "        500 http://archive.ubuntu.com/ubuntu noble-updates/main amd64 Packages"
    )
    policy = _fwupd_policy([archive]).replace(FWUPD_INSTALLED, epoch)
    f = _conffile_prompt(host, policy)
    assert _reinstall_offered(f["message"], epoch)


# CR 1946: apt right-aligns the priority in four columns after seven spaces,
# so a priority of 1000 or more prints one space short of the usual eight,
# and a negative one keeps eight (noble's apt, Pin-Priority 1001 and -10,
# measured 2026-11-07). Each is still a source line.
@pytest.mark.parametrize(
    "source",
    [
        "       1001 http://archive.ubuntu.com/ubuntu noble-updates/main amd64 Packages",
        "        -10 http://archive.ubuntu.com/ubuntu noble-updates/main amd64 Packages",
    ],
    ids=["1001", "-10"],
)
def test_a_source_of_any_priority_under_the_installed_version_counts(host, source):
    f = _conffile_prompt(host, _fwupd_policy([source]))
    assert _reinstall_offered(f["message"])
    assert "would upgrade" not in f["message"]


def test_a_status_line_of_four_digits_is_still_the_status_file(host):
    f = _conffile_prompt(
        host, _fwupd_policy([], status="       1001 /var/lib/dpkg/status")
    )
    assert not _reinstall_offered(f["message"])
    assert f"apt lists its installed {FWUPD_INSTALLED} from no archive" in f["message"]


def test_a_reinstall_whose_source_cant_be_read_says_so(host):
    f = _conffile_prompt(host, None)
    assert not _reinstall_offered(f["message"])
    assert "whether apt can fetch its installed build couldn't be read" in f["message"]


def test_a_modified_conffile_alone_has_no_restore(host):
    # Restoring the packaged file over an admin's change would lose it.
    f = _conffile_prompt(host, _fwupd_policy([]), missing=False)
    assert "/etc/fwupd/fwupd.conf (modified)" in f["message"]
    assert "restore the deleted conffile" not in f["message"]
    assert "settle the change by hand" in f["message"]


def test_a_failed_dry_run_still_reports_its_cost(host):
    # GNU time writes the failed command's status line above its own.
    host.on("unattended-upgrade", "--dry-run -d", "An error occurred\n", rc=1)
    d = host.run("--dry-run-into", str(host.tmp / "dry"))["pending"]["dry_run"]
    assert d["exit"] == 1
    assert d["max_rss_kib"] == 2048


def test_a_dry_run_without_a_selection_line_is_a_finding(host):
    # Exit 0, but nothing to count: the operator who asked hears why.
    host.on("unattended-upgrade", "--dry-run -d", "Lock could not be acquired\n")
    out = host.run("--dry-run-into", str(host.tmp / "dry"))
    assert out["pending"]["dry_run"]["count"] is None
    f = _finding(out, "dry-run")
    assert "neither" in f["message"] and "dry-run.log" in f["message"]


@pytest.mark.parametrize("line", ["upgraded: ", "upgraded:"])
def test_a_dry_runs_empty_selection_line_counts_0(host, line):
    # Nothing to upgrade, but auto-removals pending: unattended-upgrade 2.9.1
    # logs the selection line with no name on it. Its trailing space is all
    # that kept the count from reading as missing, and on bash 3.2 the empty
    # list was an unbound variable.
    host.on(
        "unattended-upgrade",
        "--dry-run -d",
        f"Packages that will be {line}\nPackages that are auto removed: libfoo1\n",
    )
    out = host.run("--dry-run-into", str(host.tmp / "dry"))
    d = out["pending"]["dry_run"]
    assert (d["count"], d["packages"]) == (0, [])
    assert "dry-run" not in _ids(out)


def test_pro_isnt_asked_about_a_tree_nothing_runs(tmp_path):
    # pro reads the machine it runs on: its counts would describe that
    # machine, not the tree under --root.
    h = Host(tmp_path, live=False).knob("posture scheduled\n")
    h.on("pro", "security-status --format json", '{"num_esm_apps_updates": 2}')
    out = h.run()
    assert out["pending"]["esm"] is None
    assert any("not a tree under --root" in n for n in out["not_read"])
    assert not h.calls("pro")


def test_a_refresh_writes_lists_only_into_its_scratch_directory(host):
    scratch = host.tmp / "fresh"
    host.on("apt-get", "update*", "Reading package lists...\n")
    host.on("pro", "security-status --format json", '{"num_esm_apps_updates": 2}')
    out = host.run("--refresh-into", str(scratch))
    # pro reads apt's own lists, which a refresh into scratch can't reach.
    assert out["pending"]["esm"]["lists"] == "the host's own, even under --refresh-into"
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


def _update_args(host: Host) -> list[list[str]]:
    return [
        a.split() for _, a, _ in host.calls("apt-get") if a.split()[:1] == ["update"]
    ]


def test_a_refresh_with_a_source_that_failed_isnt_a_refresh(host):
    # #542: apt-get update exits 0 when one source fails, and the pending set
    # was counted against that source's old lists, or none.
    host.apt_update(failed_source=True)
    out = host.run("--refresh-into", str(host.tmp / "fresh"))
    assert out["pending"]["lists"]["refreshed"] is False
    f = _finding(out, "lists:refresh")
    assert "exit 100" in f["message"]
    [args] = _update_args(host)
    assert "--error-on=any" in args


def test_a_refresh_whose_sources_all_fetch_is_one(host):
    host.apt_update()
    out = host.run("--refresh-into", str(host.tmp / "fresh"))
    assert out["pending"]["lists"]["refreshed"] is True
    assert "lists:refresh" not in _ids(out)
    [args] = _update_args(host)
    assert args[:2] == ["update", "--error-on=any"]


# --- language dependencies (#366, plan 6g) ------------------------------------

APP = "home/exedev/app"
UV_CLEAN = (
    "warning: `uv audit` is experimental and may change without warning.\n"
    "Resolved 64 packages in 7ms\n"
    "Found no known vulnerabilities and no adverse project statuses in 63 packages\n"
)
UV_FOUND = (
    "\nVulnerabilities:\n\n"
    "cryptography 42.0.0 has 15 known vulnerabilities:\n\n"
    "- GHSA-537c-gmf6-5ccf: Vulnerable OpenSSL included in cryptography wheels\n\n"
    "urllib3 2.0.0 has 20 known vulnerabilities:\n\n"
    "- GHSA-v845-jxx5-vc9f: urllib3's Cookie header isn't stripped\n"
)


def _tree(
    h: Host,
    *,
    user: str = "exedev",
    units: tuple[str, ...] = ("app.service",),
    locks: tuple[str, ...] = ("uv.lock",),
) -> Host:
    # The test's own uid first: under a root container it's 0, and the first
    # entry for a uid is the one its files belong to.
    h.write(
        "etc/passwd",
        f"{user}:x:{os.getuid()}:{os.getgid()}::/home/{user}:/bin/bash\n"
        "root:x:0:0:root:/root:/bin/bash\n",
    )
    for u in units:
        h.write(
            f"etc/systemd/system/{u}",
            f"[Service]\nUser=exedev\nWorkingDirectory=/{APP}\nExecStart=/{APP}/serve.sh\n",
        )
    h.write(f"{APP}/pyproject.toml", '[project]\nname = "app"\n')
    for lf in locks:
        h.write(f"{APP}/{lf}", "version = 1\n")
    return h


def _uv(h: Host, stdout: str = "", stderr: str = UV_CLEAN, rc: int = 0) -> Path:
    # Records where uv ran, and as whom, then answers as uv 0.11.8 did.
    seen = h.tmp / "uv.seen"
    (h.tmp / "uv.out").write_text(stdout)
    (h.tmp / "uv.err").write_text(stderr)
    h.on(
        "uv",
        "audit *",
        script=(
            f'printf "%s %s %s\\n" "$PWD" "${{STUB_USER:-exedev}}" "$(ls)" > "{seen}"; '
            f'cat "{h.tmp}/uv.out"; cat "{h.tmp}/uv.err" >&2; exit {rc}'
        ),
    )
    return seen


def _lang(out: dict) -> list[dict]:
    return out["pending"]["language"]["trees"]


def _audit(h: Host) -> dict:
    # The audit asks OSV, so it's taken only under --refresh-into (CR 231).
    h.on("apt-get", "update*", "Reading package lists...\n")
    return h.run("--refresh-into", str(h.tmp / "fresh"))


def test_a_clean_uv_lock_is_audited_in_a_copy_as_its_owner(host):
    _tree(host)
    seen = _uv(host)
    out = _audit(host)
    [t] = _lang(out)
    assert t == {
        "dir": f"/{APP}",
        "lockfile": "uv.lock",
        "units": ["app.service"],
        "owner": "unknown",
        "owner_line": None,
        "audited": True,
        "advisories": 0,
        "packages": [],
        "why": None,
    }
    assert out["pending"]["language"]["complete"] is True
    [(_, args, _)] = host.calls("uv")
    assert args == "audit --frozen --no-cache --no-python-downloads --no-config"
    # A fresh directory holding only the two files: never the tree itself,
    # and gone afterwards.
    where, who, files = seen.read_text().split(" ", 2)
    assert where != str(host.root / APP) and not where.startswith(str(host.root))
    assert who == "exedev" and files.split() == ["pyproject.toml", "uv.lock"]
    assert not Path(where).exists()
    assert list(host.tmpdir.iterdir()) == []


def test_a_uv_lock_with_advisories_counts_them_by_package(host):
    _tree(host)
    _uv(
        host,
        UV_FOUND,
        "Found 35 known vulnerabilities and no adverse project statuses in 4 packages\n",
        rc=1,
    )
    [t] = _lang(_audit(host))
    assert (t["audited"], t["advisories"]) == (True, 35)
    # The count is the header's. Each advisory's id and fix: #594, in
    # test_patching_hosts_language.py.
    assert [(p["name"], p["version"], p["advisories"]) for p in t["packages"]] == [
        ("cryptography", "42.0.0", 15),
        ("urllib3", "2.0.0", 20),
    ]


@pytest.mark.parametrize(
    "stdout, stderr, rc, why",
    [
        # OSV unreachable: an error, never a clean tree.
        (
            "",
            "warning: `uv audit` is experimental\nerror: Failed to query OSV\n  Caused by: tcp connect error\n",
            2,
            "uv audit exited 2: error: Failed to query OSV",
        ),
        # Exit 1 with nothing it can read: the format changed, or a status
        # that isn't an advisory.
        (
            "Something new\n",
            "Found 1 adverse project status\n",
            1,
            "uv audit exited 1, and no advisory in its output could be read: Found 1 adverse project status",
        ),
        # The time limit.
        ("", "", 124, "uv audit exited 124"),
    ],
)
def test_an_audit_that_cant_be_read_is_not_audited(host, stdout, stderr, rc, why):
    _tree(host)
    _uv(host, stdout, stderr, rc)
    out = _audit(host)
    [t] = _lang(out)
    assert (t["audited"], t["advisories"], t["packages"]) == (False, None, None)
    assert t["why"] == why
    assert out["pending"]["language"]["complete"] is False


def test_another_lockfile_is_found_but_not_audited(host):
    _tree(host, locks=("uv.lock", "package-lock.json"))
    _uv(host)
    out = _audit(host)
    by = {t["lockfile"]: t for t in _lang(out)}
    assert by["uv.lock"]["audited"] is True
    assert by["package-lock.json"]["audited"] is False
    assert by["package-lock.json"]["why"] == "package-lock.json: v1 audits uv.lock only"
    assert out["pending"]["language"]["complete"] is False
    assert len(host.calls("uv")) == 1


def test_two_units_running_one_tree_are_one_entry(host):
    _tree(host, units=("app.service", "app-dev.service"))
    _uv(host)
    [t] = _lang(_audit(host))
    assert sorted(t["units"]) == ["app-dev.service", "app.service"]
    assert len(host.calls("uv")) == 1


def test_a_working_directory_set_in_a_drop_in_is_read(host):
    # A packaged unit, customised in /etc: the drop-in names the tree, and
    # a later setting wins over the unit's own (CR 234).
    _tree(host, units=())
    _uv(host)
    host.write(
        "usr/lib/systemd/system/pkg.service",
        "[Service]\nWorkingDirectory=/srv/elsewhere\n",
    )
    host.write(
        "etc/systemd/system/pkg.service.d/10-app.conf",
        f"[Service]\nUser=exedev\nWorkingDirectory=/{APP}\n",
    )
    [t] = _lang(_audit(host))
    assert (t["dir"], t["units"], t["audited"]) == (f"/{APP}", ["pkg.service"], True)


def test_drop_ins_apply_in_name_order_and_etc_overrides_run(host):
    # systemd merges /etc's and /run's drop-ins by name, and /etc's copy of
    # a name both hold replaces /run's (CR 236).
    _tree(host)
    _uv(host)
    d = "systemd/system/app.service.d"
    host.write(f"run/{d}/05-early.conf", "[Service]\nWorkingDirectory=/srv/early\n")
    host.write(f"etc/{d}/10-app.conf", f"[Service]\nWorkingDirectory=/{APP}\n")
    host.write(f"run/{d}/10-app.conf", "[Service]\nWorkingDirectory=/srv/shadowed\n")
    [t] = _lang(_audit(host))
    assert t["dir"] == f"/{APP}"


def test_the_owner_is_the_knobs_line_else_the_checkouts_github_origin(host):
    _tree(host)
    _uv(host)
    # A token in the remote's URL never reaches the output.
    host.write(
        f"{APP}/.git/config",
        '[core]\n\tbare = false\n[remote "origin"]\n'
        f"\turl = https://x-access-token:{SECRET}@github.com/CannObserv/app.git\n",
    )
    out = _audit(host)
    [t] = _lang(out)
    assert (t["owner"], t["owner_line"]) == ("CannObserv/app", None)
    assert SECRET not in host.result.stdout
    host.knob(
        "class production\nposture automatic\nowner /home/exedev/app CannObserv/other\n"
    )
    [t] = _lang(_audit(host))
    assert (t["owner"], t["owner_line"]) == ("CannObserv/other", 3)


def test_a_uv_lock_with_no_uv_says_so_and_a_users_own_is_found(host):
    _tree(host)
    host.absent("uv")
    [t] = _lang(_audit(host))
    assert (t["audited"], t["why"]) == (
        False,
        "no uv in exedev's ~/.local/bin, /usr/local/bin, /usr/bin or on PATH",
    )
    host.write(
        "home/exedev/.local/bin/uv",
        f'#!/bin/sh\nprintf "%s\\n" "$*" > "{host.tmp}/own-uv"\n'
        'echo "Found no known vulnerabilities" >&2\nexit 0\n',
        mode=0o755,
    )
    [t] = _lang(_audit(host))
    assert (t["audited"], t["advisories"]) == (True, 0)
    assert (host.tmp / "own-uv").read_text().startswith("audit --frozen")


def test_the_owners_own_uv_comes_before_the_probes_path(host):
    # One on the probe user's PATH may sit in a home the owner can't enter
    # (CR 233).
    _tree(host)
    _uv(host)
    host.write(
        "home/exedev/.local/bin/uv",
        f'#!/bin/sh\ntouch "{host.tmp}/own-uv"\necho "Found no known vulnerabilities" >&2\n',
        mode=0o755,
    )
    [t] = _lang(_audit(host))
    assert t["audited"] is True
    assert (host.tmp / "own-uv").exists()
    assert not host.calls("uv")


def test_uv_runs_as_the_lockfiles_owner_and_never_as_root(host):
    _tree(host, user="app")
    seen = _uv(host)
    [t] = _lang(_audit(host))
    assert t["audited"] is True
    assert seen.read_text().split(" ")[1] == "app"
    # A root-owned lock is never audited as root: as nobody, and only with
    # a uv root alone can change, which the probe's PATH isn't (#456;
    # test_patching_hosts_language.py has the rest).
    host.write("etc/passwd", f"root:x:{os.getuid()}:0:root:/root:/bin/bash\n")
    seen.unlink()
    [t] = _lang(_audit(host))
    assert (t["audited"], t["why"]) == (
        False,
        "its uv.lock is root's, so it's audited as nobody with a uv only root "
        "can change, and neither /usr/local/bin/uv nor /usr/bin/uv is one",
    )
    assert not seen.exists()


def test_a_probe_without_refresh_into_audits_nothing(host):
    # apply.sh's probe after each step passes no --refresh-into: an apt step
    # can't change a lockfile, and an audit there would spend the step's
    # window on a network call (CR 231).
    _tree(host)
    _uv(host)
    out = host.run()
    assert out["pending"]["language"] is None
    assert any("only with --refresh-into" in n for n in out["not_read"])
    assert not host.calls("uv")


def test_a_uv_lock_whose_owner_isnt_in_passwd_says_which_uid(host):
    _tree(host)
    _uv(host)
    host.write("etc/passwd", "root:x:0:0:root:/root:/bin/bash\n")
    if os.getuid() == 0:
        pytest.skip("a root container's files are uid 0, which root names")
    [t] = _lang(_audit(host))
    assert (t["audited"], t["why"]) == (
        False,
        f"its uv.lock's owner, uid {os.getuid()}, isn't in /etc/passwd",
    )
    assert not host.calls("uv")


def test_a_tree_an_unprivileged_probe_cant_enter_leaves_the_class_incomplete(tmp_path):
    # With no root to look as, a tree it can't enter was skipped, and the
    # class read complete (CR 235).
    if os.getuid() == 0:
        pytest.skip("root enters any directory")
    h = _tree(Host(tmp_path, sudo=False).knob("class production\nposture automatic\n"))
    _uv(h)
    app = h.root / APP
    app.chmod(0o600)
    try:
        out = _audit(h)
    finally:
        app.chmod(0o755)
    assert out["pending"]["language"] == {"trees": [], "complete": False}
    assert any(f"/{APP} can't be entered without root" in n for n in out["not_read"])
    assert not h.calls("uv")


def test_language_dependencies_arent_read_from_a_tree_nothing_runs(tmp_path):
    h = _tree(Host(tmp_path, live=False).knob("posture scheduled\n"))
    _uv(h)
    out = h.run()
    assert out["pending"]["language"] is None
    assert any("language dependencies" in n for n in out["not_read"])
    assert not h.calls("uv")
