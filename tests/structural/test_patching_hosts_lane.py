"""patching-hosts' other lanes: `apply.sh --lane maintenance` (#313, plan step
6c), `--lane origin:<origin>`, and Tailscale's own auto-update (step 6d).

The other lanes reuse the security lane's gates, recovery point, window and
reboot decision; only the selection differs. The maintenance lane adds
Ubuntu's -updates and each origin the knob follows to the host's own
unattended-upgrades origins, through an APT_CONFIG file, and never names a
pinned or held one. The one-origin lane adds one followed origin, and skips
every other pending package.

What this file pins, against the plan's step 6c list:

- `--lane maintenance` selects -updates and the followed origins, and never a
  held one.

Beyond that list:

- the dry run counts the same lane, and a bulk refuses one of another lane;
- the host's own origins can't take a held or pinned origin in this lane:
  one naming it, one naming no origin, and one whose origin is a pattern;
- apt must read the lane's file;
- a held step runs its bulk's lane, and refuses a knob that follows other
  origins since;
- each script's synopsis names every lane (CR 164).

Against step 6d's list:

- `--lane origin:<origin>` takes that origin alone: every other pending
  package goes in the skip list, anchored and escaped, and only the origin's
  own are hold candidates; a held, pinned or unknown origin is refused;
- the probe's dry run counts one origin the same way;
- `AutoUpdate.Apply` true is a deviation that says what an upgrade drops on
  any host (CR 162), null an unknown that says the node never set it (CR
  161), and false nothing; an exception covers it, and without tailscaled
  it's not read.

Beyond that list, the lane must take its origin (CR 160): a dry run that
counted nothing is refused; a bulk with nothing from the origin pending, a
site apt-cache policy doesn't list included, fails before any hold; and a
step fails when apt still has one of its origin packages pending afterwards,
or can't be read, the bulk's and a held step's alike.

Measured on noble with unattended-upgrade 2.9.1: an APT_CONFIG file's
Origins-Pattern adds to the host's Allowed-Origins, `site=` is a key it
matches, and the maintenance lane's dry run took noble-updates' libaudit1
besides the security set (2026-10-02). The one-origin lane took tailscale
alone of 8 pending packages (2026-10-03). Read in 2.9.1's source the same
day: a package it passes over gets a "Package <name> is ..." line saying why,
and with nothing else to take, the run exits 0. Seen live then too: with
tailscale in the host's own blacklist, the bulk failed on it, nothing
upgraded.
"""

import subprocess

import pytest

from tests.structural.patching_hosts_rig import SKILL, clean_env, dispatcher
from tests.structural.test_patching_hosts_apply import KNOB, TUE_1530, _ready
from tests.structural.test_patching_hosts_apply import Host as ApplyHost
from tests.structural.test_patching_hosts_probe import Host as ProbeHost

UPDATES = "o=Ubuntu,a=${distro_codename}-updates"
ORIGINS = (
    "origin Tailscale follow\n"
    "origin deb.nodesource.com follow\n"
    "origin Docker hold the image pins it\n"
    "origin Grafana pin 10.4.1\n"
)
HOST_DUMP = (
    'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}";\n'
    'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}-security";\n'
)


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


def _dump(host: ApplyHost, extra: str = "", reads_apt_config: bool = True) -> None:
    """apt-config dump as apt prints it: the host's own entries, then those
    an APT_CONFIG file adds."""
    host.cases["apt-config"] = [c for c in host.cases["apt-config"] if c[0] != "dump"]
    text = host.state / "dump"
    text.write_text(HOST_DUMP + extra)
    adds = (
        'if [ -n "${APT_CONFIG:-}" ]; then '
        'sed -n \'s/^  "\\(.*\\)";$/Unattended-Upgrade::Origins-Pattern:: "\\1";/p\' '
        '"$APT_CONFIG"; fi; '
        if reads_apt_config
        else ""
    )
    host.on("apt-config", "dump", script=f'cat "{text}"; {adds}exit 0')


def _lane(tmp_path, knob: str = KNOB + ORIGINS, extra: str = "") -> ApplyHost:
    host = _ready(ApplyHost(tmp_path))
    host.knob(knob)
    _dump(host, extra)
    (host.dry / "summary").write_text(
        f"began={TUE_1530 - 3600}\nexit=0\ncount=6\nwall_seconds=540\n"
        "security_only=0\nlane=maintenance\n"
    )
    return host


def _uu_apt_config(host: ApplyHost) -> list[str]:
    return [c for _, _, c in host.calls("unattended-upgrade")]


def test_the_maintenance_lane_adds_updates_and_followed_origins_and_no_held_one(
    tmp_path,
):
    host = _lane(tmp_path)
    out = host.run("--lane", "maintenance")
    assert out["verdict"]["ok"] is True, out
    assert out["apply"]["lane"] == "maintenance"
    want = [UPDATES, "o=Tailscale", "site=deb.nodesource.com"]
    assert out["gate"]["lane"] == {"name": "maintenance", "patterns": want}
    conf = host.record("lane.conf")
    for p in want:
        assert f'  "{p}";' in conf
    assert "Docker" not in conf and "Grafana" not in conf
    assert oct((host.run_dir / "lane.conf").stat().st_mode & 0o777) == "0o600"
    # unattended-upgrade reads it, as NEEDRESTART_MODE and choom still reach it.
    assert _uu_apt_config(host) == [str(host.run_dir / "lane.conf")]
    assert "NEEDRESTART_MODE=l\n" in host.record("bulk.log")


def test_the_security_lane_names_no_apt_config(tmp_path):
    host = _ready(ApplyHost(tmp_path))
    host.knob(KNOB + ORIGINS)
    out = host.run()
    assert out["apply"]["lane"] == "security"
    assert out["gate"]["lane"] == {"name": "security", "patterns": []}
    assert _uu_apt_config(host) == [""]
    assert not (host.run_dir / "lane.conf").exists()


@pytest.mark.parametrize(
    "summary_lane, args, counted, runs",
    [
        ("", ["--lane", "maintenance"], "security", "maintenance"),
        ("lane=maintenance\n", [], "maintenance", "security"),
    ],
    ids=["security-dry-run", "maintenance-dry-run"],
)
def test_a_dry_run_of_another_lane_is_refused(
    tmp_path, summary_lane, args, counted, runs
):
    host = _lane(tmp_path)
    (host.dry / "summary").write_text(
        f"began={TUE_1530 - 3600}\nexit=0\ncount=6\nwall_seconds=540\n{summary_lane}"
    )
    out = host.run(*args, rc=3)
    assert any(
        f"counted the {counted} lane, and this bulk runs the {runs} lane" in r
        for r in out["refused"]
    ), out["refused"]
    assert not host.calls("unattended-upgrade")


@pytest.mark.parametrize(
    "entry, refused",
    [
        ('"o=Docker,a=noble"', "which names Docker, an origin the knob holds or pins"),
        ('"o=Grafana"', "which names Grafana, an origin the knob holds or pins"),
        ('"a=stable"', "which names no origin or site"),
        ('"o=Dock*,a=noble"', "whose Dock* is a pattern"),
    ],
    ids=["held", "pinned", "no-origin", "a-pattern"],
)
def test_host_origins_that_could_take_a_held_origin_are_refused(
    tmp_path, entry, refused
):
    # The owner let the security lane take more (exception uu:origins); the
    # maintenance lane, which adds to it, still never takes a held origin.
    knob = KNOB + ORIGINS + "exception uu:origins 2026-12-31 the owner's call\n"
    host = _lane(tmp_path, knob, f"Unattended-Upgrade::Origins-Pattern:: {entry};\n")
    out = host.run("--lane", "maintenance", rc=3)
    assert any(refused in r for r in out["refused"]), out["refused"]
    assert not host.calls("unattended-upgrade")


def test_a_lane_file_apt_doesnt_read_is_refused(tmp_path):
    host = _lane(tmp_path)
    _dump(host, reads_apt_config=False)
    out = host.run("--lane", "maintenance", rc=3)
    assert any(
        "apt-config didn't read the maintenance lane's patterns" in r
        for r in out["refused"]
    ), out["refused"]


def test_an_origin_no_pattern_can_carry_is_refused(tmp_path):
    host = _lane(tmp_path, KNOB + 'origin Evil"Co follow\n')
    out = host.run("--lane", "maintenance", rc=3)
    assert any('the origin Evil"Co holds a character' in r for r in out["refused"]), (
        out["refused"]
    )


def test_a_held_step_runs_its_bulks_lane(tmp_path):
    host = _lane(tmp_path)
    assert host.run("--lane", "maintenance")["verdict"]["ok"] is True
    host.uu("Packages that will be upgraded: postgresql-16\nAll upgrades installed\n")
    out = host.run(step="postgres")
    assert out["apply"]["lane"] == "maintenance"
    assert _uu_apt_config(host) == [str(host.run_dir / "lane.conf")] * 2


def test_a_held_step_refuses_a_knob_that_follows_other_origins_since_its_bulk(
    tmp_path,
):
    host = _lane(tmp_path)
    assert host.run("--lane", "maintenance")["verdict"]["ok"] is True
    host.knob(KNOB + ORIGINS + "origin Grafana_Labs follow\n")
    out = host.run(step="postgres", rc=3)
    assert any(
        "the knob follows other origins than it did at the bulk" in r
        for r in out["refused"]
    ), out["refused"]
    assert len(host.calls("unattended-upgrade")) == 1


def test_a_held_step_takes_no_lane_of_its_own(tmp_path):
    host = _lane(tmp_path)
    host.run("--lane", "maintenance")
    r = host.execute(
        [
            "bash",
            str(host.scripts / "apply.sh"),
            "--step",
            "postgres",
            "--lane",
            "security",
            "--run",
            str(host.run_dir),
        ],
        2,
    )
    assert "a held step runs its bulk's lane" in r.stderr


# --- the dry run counts the lane ---------------------------------------------------


def test_the_probes_dry_run_counts_the_maintenance_lane(tmp_path):
    host = ProbeHost(tmp_path).knob("class production\nposture scheduled\n" + ORIGINS)
    host.on(
        "unattended-upgrade",
        "--dry-run -d",
        "Packages that will be upgraded: libaudit1 libc6\n",
    )
    scratch = host.tmp / "dry"
    out = host.run("--dry-run-into", str(scratch), "--lane", "maintenance")
    d = out["pending"]["dry_run"]
    assert d["lane"] == "maintenance"
    assert d["security_only"] is False
    assert "lane=maintenance\n" in (scratch / "summary").read_text()
    [(_, _, apt_config)] = host.calls("unattended-upgrade")
    conf = open(apt_config).read()
    for p in (UPDATES, "o=Tailscale", "site=deb.nodesource.com"):
        assert f'  "{p}";' in conf
    assert "Docker" not in conf and "Grafana" not in conf


@pytest.mark.parametrize(
    "args, message",
    [
        (["--lane", "maintenance"], "it goes with --dry-run-into"),
        (
            ["--lane", "monthly", "--dry-run-into", "d"],
            "--lane takes security, maintenance or origin:",
        ),
    ],
)
def test_the_probes_lane_is_a_dry_runs(args, message):
    r = subprocess.run(
        ["bash", str(SKILL / "scripts" / "probe.sh"), *args],
        capture_output=True,
        text=True,
        env=clean_env(),
    )
    assert r.returncode == 2
    assert message in r.stderr


@pytest.mark.parametrize("script", ["probe.sh", "apply.sh"])
def test_each_synopsis_names_every_lane(script):
    r = subprocess.run(
        ["bash", str(SKILL / "scripts" / script), "--help"],
        capture_output=True,
        text=True,
        env=clean_env(),
    )
    synopsis = r.stdout.split("\n\n")[0]
    assert "[--lane security|maintenance|origin:<origin>]" in synopsis


# --- plan step 6d: one origin, for a bulletin's out-of-cycle window ---------------

POLICY = (
    " 500 https://pkgs.tailscale.com/stable/ubuntu noble/main arm64 Packages\n"
    "     release o=Tailscale,n=noble,l=Tailscale,c=main,b=arm64\n"
    "     origin pkgs.tailscale.com\n"
    " 500 http://ports.ubuntu.com/ubuntu-ports noble-updates/main arm64 Packages\n"
    "     release v=24.04,o=Ubuntu,a=noble-updates,n=noble,l=Ubuntu,c=main,b=arm64\n"
    "     origin ports.ubuntu.com\n"
)
# As apt-get -s prints Tailscale's origin (noble, 2026-10-03), and a name
# unattended-upgrade's regex blacklist would misread unescaped.
EXTRA = (
    "Inst tailscale [1.102.2] (1.102.4 Tailscale:pkgs.tailscale.com [arm64])\n"
    "Inst libstdc++6 [14.2.0-4ubuntu2~24.04] (14.2.0-4ubuntu2~24.04.1"
    " Ubuntu:24.04/noble-updates [arm64])\n"
)
TS = "origin:pkgs.tailscale.com"
TS_INST = EXTRA.splitlines(keepends=True)[0]
TOOK = "Packages that will be upgraded: tailscale\nAll upgrades installed\n"
# unattended-upgrade 2.9.1 on an upgrade whose dependency the lane skips: a
# "kept back" line, then the nothing-to-do path, which exits 0.
PASSED_OVER = (
    "Package tailscale is kept back because a related package is kept back"
    " or due to local apt_preferences(5).\n"
    "No packages found that can be upgraded unattended and no pending auto-removals\n"
)


def _one_origin(
    tmp_path, knob: str = KNOB + ORIGINS.replace("Tailscale", "pkgs.tailscale.com")
):
    """A host whose apt has tailscale pending until an upgrade takes it."""
    host = _lane(tmp_path, knob)
    sim = [c for c in host.cases["apt-get"] if c[0] == "-s dist-upgrade"][0][1]
    s = host.state
    (s / "sim").write_text(sim + EXTRA)
    (s / "sim-after").write_text(sim + EXTRA.replace(TS_INST, ""))
    host.cases["apt-get"].insert(
        0,
        (
            "-s dist-upgrade",
            "",
            0,
            "",
            f'if [ -e "{s}/took" ]; then cat "{s}/sim-after"; else cat "{s}/sim"; fi; exit 0',
        ),
    )
    host.on("apt-cache", "policy", POLICY)
    host.uu(TOOK, before=f'touch "{s}/took"; ')
    (host.dry / "summary").write_text(
        f"began={TUE_1530 - 3600}\nexit=0\ncount=1\nwall_seconds=60\n"
        f"security_only=0\nlane={TS}\n"
    )
    return host


def test_the_one_origin_lane_takes_that_origin_and_skips_everything_else(tmp_path):
    host = _one_origin(tmp_path)
    out = host.run("--lane", TS)
    assert out["verdict"]["ok"] is True, out
    assert out["gate"]["lane"] == {"name": TS, "patterns": ["site=pkgs.tailscale.com"]}
    conf = host.record("lane.conf")
    assert '  "site=pkgs.tailscale.com";' in conf
    assert "-updates" not in conf and "deb.nodesource.com" not in conf
    skipped = conf.split("Package-Blacklist {")[1]
    for name in (
        "libc6",
        "postgresql-16",
        "libpq5",
        "redis-server",
        "linux-libc-dev-new",
        "libstdc\\+\\+6",
    ):
        assert f'  "^{name}$";' in skipped, name
    assert "tailscale" not in skipped
    # Only the origin's own packages are candidates for a hold group.
    assert not [a for _, a, _ in host.calls("apt-mark") if a.startswith("hold")]
    assert out["upgrade"]["origin_pending"] == ["tailscale"]
    assert out["upgrade"]["origin_left"] == []
    assert _uu_apt_config(host) == [str(host.run_dir / "lane.conf")]


def test_a_one_origin_dry_run_that_counted_nothing_is_refused(tmp_path):
    host = _one_origin(tmp_path)
    (host.dry / "summary").write_text(
        f"began={TUE_1530 - 3600}\nexit=0\ncount=0\nwall_seconds=60\nlane={TS}\n"
    )
    out = host.run("--lane", TS, rc=3)
    assert any(
        "the dry run counted nothing from the pkgs.tailscale.com origin" in r
        for r in out["refused"]
    ), out["refused"]
    assert not host.calls("unattended-upgrade")


@pytest.mark.parametrize(
    "case, failed",
    [
        ("current", "nothing from the pkgs.tailscale.com origin is pending"),
        ("owner-held", "the owner holds them (apt-mark showhold: tailscale)"),
        ("no-source", "apt-cache policy lists no origin at pkgs.tailscale.com"),
    ],
)
def test_a_one_origin_bulk_with_nothing_from_it_pending_fails_before_any_hold(
    tmp_path, case, failed
):
    host = _one_origin(tmp_path)
    # Since the dry run: apt kept a held package back, or the source went.
    if case == "no-source":
        host.cases["apt-cache"] = []
        host.on("apt-cache", "policy", POLICY[POLICY.index(" 500 http://ports") :])
    else:
        (host.state / "sim").write_text((host.state / "sim-after").read_text())
    if case == "owner-held":
        host.owner_holds = ["tailscale"]
    out = host.run("--lane", TS, rc=1)
    assert out["verdict"]["ok"] is False
    assert any(failed in f for f in out["verdict"]["why"]), out["verdict"]
    assert not host.calls("unattended-upgrade")
    assert not [a for _, a, _ in host.calls("apt-mark") if a.startswith("hold")]


def test_a_package_unattended_upgrade_passes_over_fails_the_step(tmp_path):
    host = _one_origin(tmp_path)
    host.uu(PASSED_OVER)
    out = host.run("--lane", TS, rc=1)
    assert out["upgrade"]["nothing_to_do"] is True
    assert out["upgrade"]["origin_pending"] == ["tailscale"]
    assert out["upgrade"]["origin_left"] == ["tailscale"]
    assert any(
        "unattended-upgrade exited 0 but left tailscale from the pkgs.tailscale.com"
        " origin pending: "
        in f
        and 'says why, in a "Package <name> is ..." line' in f
        for f in out["verdict"]["why"]
    ), out["verdict"]


def test_what_the_step_took_unread_fails_it(tmp_path):
    host = _one_origin(tmp_path)
    host.uu(PASSED_OVER, before=f'touch "{host.state}/took"; ')
    host.cases["apt-get"].insert(
        0,
        (
            "-s dist-upgrade",
            "",
            0,
            "",
            f'[ -e "{host.state}/took" ] || {{ cat "{host.state}/sim"; exit 0; }}; '
            'echo "E: Could not get lock" >&2; exit 100',
        ),
    )
    out = host.run("--lane", TS, rc=1)
    assert out["upgrade"]["origin_left"] is None
    assert any(
        "so whether it took tailscale from the pkgs.tailscale.com origin is unknown"
        in f
        for f in out["verdict"]["why"]
    ), out["verdict"]


@pytest.mark.parametrize("took", [True, False], ids=["took-it", "passed-over"])
def test_a_one_origin_held_step_must_take_its_packages(tmp_path, took):
    knob = KNOB + ORIGINS.replace("Tailscale", "pkgs.tailscale.com")
    host = _one_origin(tmp_path, knob + "hold tailscale ts\n")
    # The run holds tailscale, so the bulk has nothing of the origin to take.
    host.uu("No packages found that can be upgraded unattended\n")
    out = host.run("--lane", TS)
    assert out["verdict"]["ok"] is True, out
    assert out["holds"]["placed"] == {"ts": ["tailscale"]}
    assert out["upgrade"]["origin_pending"] == []
    assert out["upgrade"]["origin_left"] == []
    if took:
        host.uu(TOOK, before=f'touch "{host.state}/took"; ')
    else:
        host.uu(PASSED_OVER)
    out = host.run(step="ts", rc=0 if took else 1)
    assert out["verdict"]["ok"] is took, out
    assert out["upgrade"]["origin_pending"] == ["tailscale"]
    assert out["upgrade"]["origin_left"] == ([] if took else ["tailscale"])


@pytest.mark.parametrize(
    "lane, refused",
    [
        ("origin:Docker", "holds the origin Docker"),
        ("origin:Grafana", "pins the origin Grafana"),
        ("origin:pkgs.example.com", "the knob names no origin pkgs.example.com"),
    ],
    ids=["held", "pinned", "unknown"],
)
def test_the_one_origin_lane_takes_only_an_origin_the_knob_follows(
    tmp_path, lane, refused
):
    host = _one_origin(tmp_path)
    (host.dry / "summary").write_text(
        f"began={TUE_1530 - 3600}\nexit=0\ncount=1\nwall_seconds=60\nlane={lane}\n"
    )
    out = host.run("--lane", lane, rc=3)
    assert any(refused in r for r in out["refused"]), out["refused"]
    assert not host.calls("unattended-upgrade")


def test_the_probes_dry_run_counts_one_origin(tmp_path):
    host = ProbeHost(tmp_path).knob(
        "class production\nposture scheduled\norigin pkgs.tailscale.com follow\n"
    )
    host.on(
        "apt-get",
        "-s *dist-upgrade",
        "Inst libc6 [2.39-0ubuntu8.3] (2.39-0ubuntu8.4 Ubuntu:24.04/noble-security [arm64])\n"
        + EXTRA,
    )
    host.on("apt-cache", "*policy", POLICY)
    host.on(
        "unattended-upgrade",
        "--dry-run -d",
        "Packages that will be upgraded: tailscale\n",
    )
    scratch = host.tmp / "dry"
    out = host.run("--dry-run-into", str(scratch), "--lane", TS)
    d = out["pending"]["dry_run"]
    assert d["lane"] == TS and d["count"] == 1
    assert d["origin_pending"] == ["tailscale"]
    assert f"lane={TS}\n" in (scratch / "summary").read_text()
    [(_, _, apt_config)] = host.calls("unattended-upgrade")
    conf = open(apt_config).read()
    assert '  "site=pkgs.tailscale.com";' in conf
    assert '  "^libc6$";' in conf and '  "^libstdc\\+\\+6$";' in conf
    assert '"^tailscale$"' not in conf


# --- Tailscale's own auto-update ----------------------------------------------------


def _prefs(apply: str) -> str:
    return (
        "{\n"
        '\t"ControlURL": "https://controlplane.tailscale.com",\n'
        '\t"AutoUpdate": {\n'
        '\t\t"Check": true,\n'
        f'\t\t"Apply": {apply}\n'
        "\t},\n"
        '\t"AppConnector": {\n'
        '\t\t"Advertise": false\n'
        "\t}\n"
        "}\n"
    )


@pytest.mark.parametrize(
    "apply, kind",
    [("true", "deviation"), ("null", "unknown"), ("false", None)],
)
def test_the_probe_reports_tailscales_own_auto_update(tmp_path, apply, kind):
    host = ProbeHost(tmp_path).knob("class production\nposture scheduled\n")
    host.installed("tailscale")
    host.on("tailscale", "version", "1.102.2\n  tailscale commit: 6cac918\n")
    host.on("tailscale", "debug prefs", _prefs(apply))
    out = host.run()
    assert out["updates"]["tailscale"] == {
        "version": "1.102.2",
        "auto_update": {"true": True, "false": False, "null": None}[apply],
    }
    hits = [f for f in out["findings"] if f["id"] == "tailscale:auto-update"]
    assert [f["kind"] for f in hits] == ([kind] if kind else [])
    if apply == "null":
        # Never set on the node: the tailnet's setting configures a device
        # only as it joins (Tailscale's KB 1067), so it isn't deciding now.
        assert "was never set on this node" in hits[0]["message"]
        assert "default decides" not in hits[0]["message"]
    if apply == "true":
        # A global skill: what an upgrade drops, said of any host.
        assert "anything that reaches it over the tailnet" in hits[0]["message"]
        assert "cohort" not in hits[0]["message"]


def test_tailscales_auto_update_is_unread_without_tailscaled_and_ignored_without_it(
    tmp_path,
):
    host = ProbeHost(tmp_path).knob("class production\nposture scheduled\n")
    out = host.run()
    assert out["updates"]["tailscale"] is None
    assert "tailscale:auto-update" not in [f["id"] for f in out["findings"]]

    host.installed("tailscale")
    host.on(
        "tailscale",
        "debug prefs",
        "",
        rc=1,
        stderr="failed to connect to local tailscaled\n",
    )
    out = host.run()
    assert out["updates"]["tailscale"]["auto_update"] is None
    assert any("is tailscaled running?" in n for n in out["not_read"])


@pytest.mark.parametrize(
    "doc", ["references/run.md", "references/environments/exe-dev-exeuntu.md"]
)
def test_the_daemon_check_reads_the_daemon(doc):
    # Plain `tailscale version` prints the client's version and never warns,
    # even over a stale tailscaled (noble, 2026-10-04): only --daemon reads it.
    text = (SKILL / doc).read_text()
    assert "`tailscale version --daemon`" in text
    assert "until `tailscale version` prints" not in text
    assert "`tailscale version` warns" not in text


def test_an_exception_covers_tailscales_auto_update(tmp_path):
    host = ProbeHost(tmp_path).knob(
        "class production\nposture scheduled\n"
        "exception tailscale:auto-update 2026-12-31 the owner takes them as they come\n"
    )
    host.installed("tailscale")
    host.on("tailscale", "debug prefs", _prefs("true"))
    out = host.run()
    assert "tailscale:auto-update" not in [f["id"] for f in out["findings"]]
    assert "tailscale:auto-update" in [f["id"] for f in out["excepted"]]
