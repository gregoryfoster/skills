"""patching-hosts' probe: PID 1's log target, and the shutdown lines it leaves (#684).

`systemd-analyze get-log-target` reads the target PID 1 runs on now. On
exeuntu that's argv's (`--log-target=syslog`, which PID 1 reads as `journal`)
until the first daemon-reload or re-exec, which applies `system.conf.d`'s
`LogTarget=`: the image's `container-overrides.conf` sets `console`. So the
probe records both sources besides the live target, and `--post-boot` judges
the previous boot's PID 1 shutdown lines by their presence, never by the new
boot's target (measured on CannObserv/wslcb-licensing-tracker's host,
2026-11-20, systemd 255.4-1ubuntu8.19).
"""

import pytest

from tests.structural import test_patching_hosts_probe as _probe
from tests.structural.patching_hosts_rig import dispatcher


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


host = _probe.host

CONF = "etc/systemd/system.conf"
DROP = "etc/systemd/system.conf.d"


def _env(host):
    return host.run()["environment"]


def _pid1(host, *argv: str) -> None:
    host.write("proc/1/cmdline", "\0".join(argv) + "\0")


# --- the readings -----------------------------------------------------------------


@pytest.mark.parametrize(
    "argv, want",
    [
        (("/sbin/init", "--log-target=syslog", "--show-status=true"), "syslog"),
        (("/sbin/init", "--log-target", "journal-or-kmsg"), "journal-or-kmsg"),
        (("/sbin/init", "--show-status=true"), None),
    ],
    ids=["equals", "separate", "absent"],
)
def test_pid_1s_argv_log_target_is_read_from_its_cmdline(host, argv, want):
    _pid1(host, *argv)
    assert _env(host)["pid1_log_target_argv"] == want


def test_the_exeuntu_trap_reads_journal_now_and_console_after_a_reload(host):
    # The boot's target from exe-init's argv; the image's override from the
    # first reload on.
    _pid1(host, "/sbin/init", "--log-target=syslog", "--show-status=true")
    host.on("systemd-analyze", "get-log-target", "journal\n")
    host.write(CONF, "[Manager]\n#LogTarget=journal-or-kmsg\n")
    host.write(f"{DROP}/container-overrides.conf", "[Manager]\nLogTarget=console\n")
    env = _env(host)
    assert env["pid1_log_target"] == "journal"
    assert env["pid1_log_target_conf"] == "console"
    assert env["pid1_log_target_conf_set_in"] == f"/{DROP}/container-overrides.conf:2"
    assert env["pid1_log_target_reload"] == "console"
    assert env["pid1_logs_to_journal"] == {"now": True, "after_reload": False}


def test_a_drop_in_sorted_after_the_override_keeps_pid_1_on_the_journal(host):
    _pid1(host, "/sbin/init", "--log-target=syslog")
    host.on("systemd-analyze", "get-log-target", "journal-or-kmsg\n")
    host.write(f"{DROP}/container-overrides.conf", "[Manager]\nLogTarget=console\n")
    host.write(
        f"{DROP}/zz-cannobserv-log-target.conf",
        "[Manager]\nLogTarget=journal-or-kmsg\n",
    )
    env = _env(host)
    assert env["pid1_log_target_conf"] == "journal-or-kmsg"
    assert env["pid1_log_target_reload"] == "journal-or-kmsg"
    assert env["pid1_logs_to_journal"] == {"now": True, "after_reload": True}


def test_a_drop_in_under_usr_lib_is_read_in_filename_order(host):
    host.write("usr/lib/systemd/system.conf.d/90-x.conf", "[Manager]\nLogTarget=kmsg\n")
    host.write(f"{DROP}/10-y.conf", "[Manager]\nLogTarget=journal\n")
    env = _env(host)
    assert env["pid1_log_target_conf"] == "kmsg"
    assert (
        env["pid1_log_target_conf_set_in"]
        == "/usr/lib/systemd/system.conf.d/90-x.conf:2"
    )


@pytest.mark.parametrize(
    "text, want",
    [
        ("[Manager]\nLogTarget = console \n", "console"),
        ("[Manager]\nLogTarget=console\nLogTarget=bogus\n", "console"),
        ("[Manager]\nLogTarget=console\nLogTarget=\n", "console"),
        ("LogTarget=console\n[Manager]\n", None),
        ("[Manager]\n; LogTarget=console\n", None),
    ],
    ids=[
        "blanks",
        "unparseable-keeps-earlier",
        "empty-keeps-earlier",
        "outside",
        "comment",
    ],
)
def test_log_target_is_parsed_as_pid_1_parses_it(host, text, want):
    host.write(CONF, text)
    assert _env(host)["pid1_log_target_conf"] == want


# --- what a reload applies (CR 2774) ---------------------------------------------
# systemd v255's main.c: a reload's parse_configuration() reads system.conf,
# then log_parse_environment() the kernel's systemd.log_target= and then
# SYSTEMD_LOG_TARGET, each later one winning. reset_arguments() never resets
# the log target, so with none of them set the reload keeps the live one.


def test_with_no_line_a_reload_keeps_the_live_target(host):
    _pid1(host, "/sbin/init", "--log-target=console")
    host.on("systemd-analyze", "get-log-target", "console\n")
    env = _env(host)
    assert env["pid1_log_target_conf"] is None
    assert env["pid1_log_target_reload"] == "console"
    assert env["pid1_logs_to_journal"]["after_reload"] is False


def test_the_kernels_log_target_beats_system_conf_at_a_reload(host):
    host.on("systemd-analyze", "get-log-target", "journal-or-kmsg\n")
    host.write(
        "proc/cmdline", "console=hvc0 systemd.log_target=console root=/dev/vda\n"
    )
    env = _env(host)
    assert env["pid1_log_target_kernel"] == "console"
    assert env["pid1_log_target_reload"] == "console"
    host.write(CONF, "[Manager]\nLogTarget=journal\n")
    assert _env(host)["pid1_log_target_reload"] == "console"


def test_pid_1s_environment_beats_the_kernel_and_system_conf(host):
    host.write("proc/cmdline", "systemd.log_target=console\n")
    host.write(CONF, "[Manager]\nLogTarget=journal\n")
    host.write("proc/1/environ", "HOME=/\0SYSTEMD_LOG_TARGET=kmsg\0TERM=linux\0")
    env = _env(host)
    assert env["pid1_log_target_env"] == "kmsg"
    assert env["pid1_log_target_reload"] == "kmsg"


def test_an_invalid_kernel_or_environment_target_is_ignored(host):
    host.write("proc/cmdline", "systemd.log_target=bogus\n")
    host.write("proc/1/environ", "SYSTEMD_LOG_TARGET=\0")
    host.write(CONF, "[Manager]\nLogTarget=journal\n")
    env = _env(host)
    assert (env["pid1_log_target_kernel"], env["pid1_log_target_env"]) == (None, None)
    assert env["pid1_log_target_reload"] == "journal"


def test_an_environment_that_cant_be_read_is_null_and_unread(tmp_path):
    h = _probe.Host(tmp_path, sudo=False).knob("posture automatic\n")
    h.write("proc/1/environ", "SYSTEMD_LOG_TARGET=kmsg\0", mode=0)
    out = h.run()
    assert out["environment"]["pid1_log_target_env"] is None
    assert [n for n in out["not_read"] if "SYSTEMD_LOG_TARGET" in n]


def test_a_runtime_override_reads_as_what_system_conf_would_apply(host):
    # An accepted limitation: systemd-analyze set-log-target journal survives a
    # reload (main.c's log_target_overridden), but nothing the probe can read
    # tells it from argv's target, so the reload reads as system.conf's.
    _pid1(host, "/sbin/init", "--log-target=syslog")
    host.on("systemd-analyze", "get-log-target", "journal\n")
    host.write(f"{DROP}/container-overrides.conf", "[Manager]\nLogTarget=console\n")
    assert _env(host)["pid1_log_target_reload"] == "console"


# --- which targets reach the journal (CR 2775) --------------------------------------


@pytest.mark.parametrize(
    "target, journal",
    [
        ("journal", True),
        ("journal-or-kmsg", True),
        # PID 1 upgrades syslog to the journal (log.c's upgrade_syslog_to_journal).
        ("syslog", True),
        ("syslog-or-kmsg", True),
        # journald reads kmsg (ReadKMsg=yes, its default), and auto is
        # journal-or-kmsg for PID 1 (log.c's log_settle_target).
        ("kmsg", True),
        ("auto", True),
        ("console", False),
        ("console-prefixed", False),
        ("null", False),
    ],
)
def test_the_targets_that_reach_the_journal(host, target, journal):
    host.on("systemd-analyze", "get-log-target", f"{target}\n")
    host.write(CONF, f"[Manager]\nLogTarget={target}\n")
    env = _env(host)
    assert env["pid1_logs_to_journal"] == {"now": journal, "after_reload": journal}


def test_kmsg_doesnt_reach_the_journal_when_journald_doesnt_read_it(host):
    host.write("etc/systemd/journald.conf", "[Journal]\nReadKMsg=no\n")
    host.on("systemd-analyze", "get-log-target", "kmsg\n")
    host.write(CONF, "[Manager]\nLogTarget=journal-or-kmsg\n")
    assert _env(host)["pid1_logs_to_journal"] == {"now": False, "after_reload": True}


def test_a_tree_nothing_runs_reads_no_argv(tmp_path):
    h = _probe.Host(tmp_path, live=False).knob("posture automatic\n")
    h.write("proc/1/cmdline", "/sbin/init\0--log-target=syslog\0")
    env = h.run()["environment"]
    assert env["pid1_log_target_argv"] is None
    assert env["pid1_logs_to_journal"]["now"] is None


# --- after the boot -------------------------------------------------------------


PERSISTENT = "var/log/journal/" + "a" * 32 + "/system.journal"
PID1_QUERY = "-b -1 _PID=1 + _TRANSPORT=kernel SYSLOG_PID=1 -n 200 -q --no-pager -o cat"
PID1_TAIL = "Reached target final.target - Late Shutdown Services.\nShutting down.\n"


@pytest.mark.parametrize("now", ["journal", "console"])
def test_post_boot_reads_pid_1s_shutdown_lines_by_their_presence(host, now):
    # Whatever the new boot's target: it isn't the one the shutdown ran on.
    host.write(PERSISTENT, "x")
    host.on("systemd-analyze", "get-log-target", f"{now}\n")
    host.on("journalctl", PID1_QUERY, PID1_TAIL)
    out = host.run("--post-boot")
    checks = {c["check"]: c for c in out["post_boot"]}
    assert checks["shutdown:pid1-lines"]["ok"] is True
    assert "Shutting down." in checks["shutdown:pid1-lines"]["evidence"]


@pytest.mark.parametrize("now", ["journal", "console"])
def test_absent_pid_1_lines_are_no_evidence_either_way(host, now):
    # A reload may have moved PID 1 to the console long before the shutdown:
    # their absence isn't a failed shutdown, and files no finding.
    host.write(PERSISTENT, "x")
    host.on("systemd-analyze", "get-log-target", f"{now}\n")
    host.on("journalctl", PID1_QUERY, "Started x.\n")
    out = host.run("--post-boot")
    c = {c["check"]: c for c in out["post_boot"]}["shutdown:pid1-lines"]
    assert c["ok"] is None
    assert "console" in c["evidence"]
    assert not [f for f in out["findings"] if "pid1-lines" in f["id"]]
