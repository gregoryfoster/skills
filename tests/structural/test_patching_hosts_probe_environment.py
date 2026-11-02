"""patching-hosts' probe: the environment it reads (#313, plan step 3).

Split out of test_patching_hosts_probe.py (#538), whose docstring says what
the probe's tests pin: under `--dist loadfile` a file runs on one worker, so
one file holding every probe case set the parallel suite's floor. The rig,
`Host` and the helpers are that file's.

What this file holds, section by section as they stood there:

- the environment: the session's chain to PID 1, the platform agent's adj,
  the journal's storage, unit files read as root, and the restarter scan;
- systemd's drop-in order (#515, #484 site 5);
- the restarter scan's residual sites (#484);
- exceptions;
- the environment profile;
- exe.dev's platform files (#388, items 1 and 5).
"""

import json
import os

import pytest

from tests.structural.patching_hosts_rig import DAY, dispatcher
from tests.structural.test_patching_hosts_probe import (
    APP,
    SECRET,
    Host,
    _audit,
    _finding,
    _ids,
    _lang,
    _tree,
    _uv,
)


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


@pytest.fixture
def host(tmp_path) -> Host:
    return Host(tmp_path).knob("class production\nposture automatic\n")


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


def test_the_platform_agents_own_adj_is_reported_apart_from_the_sessions(host):
    # #353: exe-init stays at -1000 and starts the session's processes at 0.
    # Taken over the whole chain, the minimum fired on every exe.dev host.
    host.chain(
        [
            (4242, "bash", 0),
            (4100, "claude", 0),
            (218, "exe-init", -1000),
            (1, "systemd", 0),
        ]
    )
    out = host.run("--post-boot")
    s = out["environment"]["session"]
    assert s["min_adj"] == 0
    assert s["platform_agent"] == {"pid": 218, "comm": "exe-init", "adj": -1000}
    assert "session:adj" not in _ids(out)
    checks = {c["check"]: c for c in out["post_boot"]}
    assert checks["session-adj"]["ok"] is True
    # A session process of its own at -1000, under the agent, still counts.
    host.chain(
        [
            (4242, "bash", 0),
            (4100, "claude", -1000),
            (218, "exe-init", -1000),
            (1, "systemd", 0),
        ]
    )
    out = host.run()
    assert out["environment"]["session"]["min_adj"] == -1000
    assert _finding(out, "session:adj")["kind"] == "risk"


@pytest.mark.parametrize("adj, finds", [(0, False), (-1000, True)])
def test_on_the_older_layouts_the_session_ends_below_exe_devs_sshd(host, adj, finds):
    # CR 201: exe.dev's sshd is -1000 on every build; sshd-session and the
    # session follow the build (#346 section 4).
    host.chain(
        [
            (4242, "bash", adj),
            (4100, "sshd-session", adj),
            (300, "sshd", -1000),
            (1, "systemd", 0),
        ]
    )
    out = host.run()
    s = out["environment"]["session"]
    assert s["min_adj"] == adj
    assert s["platform_agent"] == {"pid": 300, "comm": "sshd", "adj": -1000}
    assert ("session:adj" in _ids(out)) is finds


def test_a_stock_hosts_session_ends_below_openssh(host):
    # CR 206: noble's sshd puts its listener at -1000 and each connection's
    # sshd and session at 0 (measured with CAP_SYS_RESOURCE).
    host.chain(
        [
            (4242, "bash", 0),
            (4100, "sshd", 0),
            (900, "sshd", -1000),
            (1, "systemd", 0),
        ]
    )
    out = host.run()
    s = out["environment"]["session"]
    assert s["min_adj"] == 0
    assert s["platform_agent"]["pid"] == 4100
    assert "session:adj" not in _ids(out)


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


def test_a_unit_file_the_user_cant_read_is_read_as_root_or_reported_unread(host):
    # #360: wslcb's health-check unit is 0600 root. Grepped as the user, the
    # scan came back [], which reads as clean.
    unit = host.write(
        "etc/systemd/system/app-health.service",
        "[Service]\nExecStart=/bin/sh -c 'curl -sf x || systemctl restart app'\n",
        mode=0o000,
    )
    try:
        out = host.run()
    finally:
        unit.chmod(0o644)
    sudo_reads = [c for c in host.calls("sudo") if "cat -- " in c[1]]
    if os.geteuid() == 0:
        # A runner as root reads it, as the probe would through sudo.
        assert _finding(out, "restarter:app-health.service")["kind"] == "knob"
        assert out["impact"]["restarters_complete"] is True
    else:
        # The sudo stub runs as this user, so root's read fails too: unread,
        # never an empty list read as clean.
        assert sudo_reads
        assert out["impact"]["restarters_complete"] is False
        f = _finding(out, "restarters:unread")
        assert f["kind"] == "unknown"
        assert "/etc/systemd/system/app-health.service" in f["message"]
        assert any("in-host restarters" in n for n in out["not_read"])


RESTARTS = "#!/bin/sh\nsystemctl restart app.service\n"
NOTIFIES = "#!/bin/sh\ncurl -sf http://notifier/x\n"


RENEW_TIMER = "[Timer]\nOnCalendar=Mon 04:00\nUnit=store-renew.service\n"
RENEW_UNIT = "[Service]\nType=oneshot\nExecStart=/usr/local/bin/store-renew.sh\n"


@pytest.mark.parametrize(
    "program, finds, unread",
    [
        # co-index's shape (#368): the restart is in the script, not the unit.
        ("#!/bin/sh\nif changed; then systemctl restart store; fi\n", True, False),
        (NOTIFIES, False, False),
        # A binary can't be followed: incomplete, not clean.
        (b"\x7fELF\x00\x00", False, True),
    ],
)
def test_a_timers_service_is_read_through_the_script_it_runs(
    host, program, finds, unread
):
    host.write("etc/systemd/system/store-cert.timer", RENEW_TIMER)
    host.write("etc/systemd/system/store-renew.service", RENEW_UNIT)
    host.write("usr/local/bin/store-renew.sh", program)
    out = host.run()
    assert ("restarter:store-renew.service" in _ids(out)) is finds
    assert ("restarters:unread:store-renew.service" in _ids(out)) is unread
    assert out["impact"]["restarters_complete"] is (not unread)
    if finds:
        # CR 221: it may be the unit's own Exec line, with no script.
        assert (
            "what its timer runs starts or restarts one"
            in _finding(out, "restarter:store-renew.service")["message"]
        )
    if unread:
        f = _finding(out, "restarters:unread:store-renew.service")
        assert f["kind"] == "unknown"
        assert "/usr/local/bin/store-renew.sh, a binary" in f["message"]
        assert "exception not-restarter:store-renew.service" in f["message"]
    # Declared, it's a restarter either way: nothing left to find.
    host.knob("posture scheduled\nrestarter store-cert.timer\n")
    out = host.run()
    assert not [i for i in _ids(out) if i.startswith("restarter")]
    assert out["impact"]["restarters_complete"] is True


def test_a_unit_found_two_ways_is_one_restarter(host):
    # CR 224: its OnFailure= target restarts, and so does its timer's script.
    host.write("etc/systemd/system/store-cert.timer", RENEW_TIMER)
    host.write(
        "etc/systemd/system/store-renew.service",
        RENEW_UNIT + "[Unit]\nOnFailure=store-fix.service\n",
    )
    host.write(
        "etc/systemd/system/store-fix.service",
        "[Service]\nExecStart=/bin/systemctl restart store.service\n",
    )
    host.write("usr/local/bin/store-renew.sh", RESTARTS)
    out = host.run()
    assert _ids(out).count("restarter:store-renew.service") == 1
    units = [r["unit"] for r in out["impact"]["restarters"]]
    assert units.count("store-renew.service") == 1


@pytest.mark.parametrize(
    "exec_line, unread, said",
    [
        # #393: usa-wa's backup. -m takes a module, not a script path; one
        # isn't followed to a file, so it stays unread, named as a module.
        (
            "ExecStart=/home/exedev/usa-wa/.venv/bin/python -m usa_wa_api.backup.run",
            True,
            "python -m usa_wa_api.backup.run, a Python module",
        ),
        (
            "ExecStart=/usr/bin/python3 -mapp.backup",
            True,
            "python3 -m app.backup, a Python module",
        ),
        # -X and -W take a value, which isn't the script: the script is read,
        # and only notifies.
        ("ExecStart=/usr/bin/python3 -X dev -W ignore /opt/app/r.py", False, ""),
        ("ExecStart=/usr/bin/python3 -Xdev /opt/app/r.py", False, ""),
    ],
)
def test_a_python_module_is_named_as_one_and_an_options_value_isnt_the_script(
    host, exec_line, unread, said
):
    host.write("etc/systemd/system/store-cert.timer", RENEW_TIMER)
    host.write(
        "etc/systemd/system/store-renew.service",
        f"[Service]\nType=oneshot\n{exec_line}\n",
    )
    host.write("opt/app/r.py", "import urllib.request\nurllib.request.urlopen('x')\n")
    out = host.run()
    assert "restarter:store-renew.service" not in _ids(out)
    assert ("restarters:unread:store-renew.service" in _ids(out)) is unread
    assert out["impact"]["restarters_complete"] is (not unread)
    if unread:
        f = _finding(out, "restarters:unread:store-renew.service")
        assert said in f["message"]
        assert "relative to its working directory" not in f["message"]
        assert f["exception_what"] == "not-restarter:store-renew.service"


AV = "/home/exedev/address-validator"
SWEEP = f"{AV[1:]}/infra/sweep_cache.py"
OLD_SWEEP = "srv/old/infra/sweep_cache.py"


@pytest.mark.parametrize(
    "wd, dropin, files, finds, said",
    [
        # #418: address-validator's sweep, read where systemd runs it.
        (f"WorkingDirectory={AV}", None, {SWEEP: RESTARTS}, True, ""),
        (f"WorkingDirectory={AV}", None, {SWEEP: NOTIFIES}, False, ""),
        (
            f"WorkingDirectory={AV}",
            None,
            {},
            False,
            f"{AV}/infra/sweep_cache.py, which couldn't be read",
        ),
        # A leading - only says a missing directory is ignored.
        (f"WorkingDirectory=-{AV}", None, {SWEEP: RESTARTS}, True, ""),
        # The last assignment wins, a drop-in's over the unit's.
        (
            "WorkingDirectory=/srv/old",
            f"WorkingDirectory={AV}",
            {SWEEP: NOTIFIES, OLD_SWEEP: RESTARTS},
            False,
            "",
        ),
        (
            f"WorkingDirectory={AV}",
            "WorkingDirectory=/srv/old",
            {SWEEP: NOTIFIES, OLD_SWEEP: RESTARTS},
            True,
            "",
        ),
        # What can't be resolved stays unread, saying why.
        (
            "WorkingDirectory=~",
            None,
            {SWEEP: NOTIFIES},
            False,
            "infra/sweep_cache.py, a path relative to its working directory ~",
        ),
        (
            "WorkingDirectory=%h/address-validator",
            None,
            {SWEEP: NOTIFIES},
            False,
            "infra/sweep_cache.py, a path relative to its working directory "
            "%h/address-validator, which has a specifier",
        ),
        (
            "",
            None,
            {SWEEP: NOTIFIES},
            False,
            "infra/sweep_cache.py, a path relative to a working directory "
            "the unit doesn't set",
        ),
    ],
)
def test_a_relative_script_is_read_against_the_units_working_directory(
    host, wd, dropin, files, finds, said
):
    host.write("etc/systemd/system/cache-sweep.timer", "[Timer]\nOnCalendar=daily\n")
    host.write(
        "etc/systemd/system/cache-sweep.service",
        f"[Service]\nType=oneshot\n{wd}\n"
        f"ExecStart={AV}/.venv/bin/python infra/sweep_cache.py\n",
    )
    if dropin is not None:
        host.write(
            "etc/systemd/system/cache-sweep.service.d/wd.conf", f"[Service]\n{dropin}\n"
        )
    for rel, text in files.items():
        host.write(rel, text)
    out = host.run()
    assert ("restarter:cache-sweep.service" in _ids(out)) is finds
    assert ("restarters:unread:cache-sweep.service" in _ids(out)) is bool(said)
    if said:
        assert said in _finding(out, "restarters:unread:cache-sweep.service")["message"]


def test_a_relative_onfailure_script_is_read_against_its_working_directory(host):
    # #418: address-validator's notifier, a template every unit hooks.
    host.write(
        "etc/systemd/system/address-validator.service",
        "[Unit]\nOnFailure=unit-failure@%n.service\n[Service]\nExecStart=/usr/bin/app\n",
    )
    host.write(
        "etc/systemd/system/unit-failure@.service",
        f"[Service]\nType=oneshot\nWorkingDirectory={AV}\n"
        f"ExecStart={AV}/.venv/bin/python infra/notify_unit_failure.py %i\n",
    )
    host.write(f"{AV[1:]}/infra/notify_unit_failure.py", NOTIFIES)
    out = host.run()
    assert "restarter:address-validator.service" not in _ids(out)
    assert not out["impact"]["restarters"]


def test_a_module_stays_unread_whatever_its_working_directory(host):
    host.write("etc/systemd/system/store-cert.timer", RENEW_TIMER)
    host.write(
        "etc/systemd/system/store-renew.service",
        f"[Service]\nWorkingDirectory={AV}\nExecStart=/usr/bin/python3 -m infra.renew\n",
    )
    host.write(f"{AV[1:]}/infra/renew.py", NOTIFIES)
    out = host.run()
    f = _finding(out, "restarters:unread:store-renew.service")
    assert "python3 -m infra.renew, a Python module" in f["message"]


# --- systemd's drop-in order (#515, #484 site 5) -------------------------------------
# journald.conf(5) and systemd.unit(5): every *.conf across /etc, /run,
# /usr/local/lib and /usr/lib, a name in a higher directory masking the same
# name lower down, then applied in filename order whatever the directory.

JD = "systemd/journald.conf.d"


@pytest.mark.parametrize(
    "files, storage, set_in",
    [
        # The disk GC's layer installs its drop-in under /usr/local/lib.
        (
            {f"usr/local/lib/{JD}/zz-cannobserv-journal.conf": "volatile"},
            "volatile",
            f"/usr/local/lib/{JD}/zz-cannobserv-journal.conf:2",
        ),
        ({f"run/{JD}/50-x.conf": "none"}, "none", f"/run/{JD}/50-x.conf:2"),
        # By filename, not by directory: zz-a sorts after 10-b, and wins.
        (
            {
                f"usr/lib/{JD}/zz-a.conf": "volatile",
                f"etc/{JD}/10-b.conf": "persistent",
            },
            "volatile",
            f"/usr/lib/{JD}/zz-a.conf:2",
        ),
        # /etc's copy of a name masks /usr/lib's.
        (
            {
                f"usr/lib/{JD}/50-x.conf": "volatile",
                f"etc/{JD}/50-x.conf": "persistent",
            },
            "persistent",
            f"/etc/{JD}/50-x.conf:2",
        ),
        # And so does a link to /dev/null, which reads as nothing.
        (
            {f"usr/lib/{JD}/50-x.conf": "volatile", f"etc/{JD}/50-x.conf": None},
            "persistent",
            "/etc/systemd/journald.conf:2",
        ),
    ],
    ids=["usr-local-lib", "run", "filename-order", "masked", "masked-by-null"],
)
def test_journald_drop_ins_are_read_as_journald_reads_them(
    host, files, storage, set_in
):
    host.write("etc/systemd/journald.conf", "[Journal]\nStorage=persistent\n")
    for rel, value in files.items():
        if value is None:
            host.link(rel, "/dev/null")
        else:
            host.write(rel, f"[Journal]\nStorage={value}\n")
    j = host.run()["environment"]["journal"]
    assert (j["storage"], j["storage_set_in"]) == (storage, set_in)


def test_a_working_directory_drop_in_in_usr_local_lib_is_read_in_name_order(host):
    # read_language's drop-in merge read /etc and /run alone (CR 236): a
    # drop-in under /usr/local/lib that sorts last sets the tree.
    _tree(host)
    _uv(host)
    d = "systemd/system/app.service.d"
    host.write(f"etc/{d}/10-elsewhere.conf", "[Service]\nWorkingDirectory=/srv/x\n")
    host.write(
        f"usr/local/lib/{d}/zz-app.conf", f"[Service]\nWorkingDirectory=/{APP}\n"
    )
    [t] = _lang(_audit(host))
    assert t["dir"] == f"/{APP}"


@pytest.mark.parametrize(
    "dropins, finds",
    [
        # Site 5: zz-a sorts last, so its WorkingDirectory= wins, though it's
        # in /etc and 10-b in /usr/lib.
        (
            {
                "etc/systemd/system/cache-sweep.service.d/zz-a.conf": f"WorkingDirectory={AV}",
                "usr/lib/systemd/system/cache-sweep.service.d/10-b.conf": "WorkingDirectory=/srv/old",
            },
            True,
        ),
        (
            {
                "etc/systemd/system/cache-sweep.service.d/10-a.conf": f"WorkingDirectory={AV}",
                "usr/lib/systemd/system/cache-sweep.service.d/zz-b.conf": "WorkingDirectory=/srv/old",
            },
            False,
        ),
        # /run's copy of a name masks /usr/lib's.
        (
            {
                "run/systemd/system/cache-sweep.service.d/50-wd.conf": f"WorkingDirectory={AV}",
                "usr/lib/systemd/system/cache-sweep.service.d/50-wd.conf": "WorkingDirectory=/srv/old",
            },
            True,
        ),
    ],
    ids=["etc-sorts-last", "usr-lib-sorts-last", "run-masks-usr-lib"],
)
def test_the_restarter_scans_working_directory_follows_drop_in_filename_order(
    host, dropins, finds
):
    host.write("etc/systemd/system/cache-sweep.timer", "[Timer]\nOnCalendar=daily\n")
    host.write(
        "etc/systemd/system/cache-sweep.service",
        f"[Service]\nType=oneshot\nExecStart={AV}/.venv/bin/python infra/sweep_cache.py\n",
    )
    for rel, line in dropins.items():
        host.write(rel, f"[Service]\n{line}\n")
    host.write(SWEEP, RESTARTS)
    host.write(OLD_SWEEP, NOTIFIES)
    out = host.run()
    assert ("restarter:cache-sweep.service" in _ids(out)) is finds


# --- the restarter scan's residual sites (#484) --------------------------------------
# Sites 1 and 4 can hide a real restarter: a restart the scan should find,
# and didn't.


def test_a_plain_units_own_systemctl_start_is_a_restarter(host):
    # Site 4: read_restarters' own grep took restart and not start, an older
    # matcher than RESTART_RE; a unit that's neither an OnFailure= target nor
    # a timer's service was found only through it.
    host.write(
        "etc/systemd/system/app-watch.service",
        "[Service]\nExecStart=/usr/bin/app-watch\n"
        "ExecStartPost=/bin/systemctl start app.service\n",
    )
    out = host.run()
    f = _finding(out, "restarter:app-watch.service")
    assert f["exception_what"] is None
    assert "app-watch.service" in {r["unit"] for r in out["impact"]["restarters"]}
    # A restart on an Exec line was read, so no exception silences it.
    host.knob(
        "posture scheduled\n"
        "exception not-restarter:app-watch.service 2099-01-01 it only starts\n"
    )
    assert "restarter:app-watch.service" in _ids(host.run())


def test_an_inline_commands_relative_script_is_read_against_its_working_directory(
    host,
):
    # Site 1: #418's defect at the inline-command site. A relative command
    # word runs from WorkingDirectory=, as a script on an Exec line does.
    host.write("etc/systemd/system/store-cert.timer", RENEW_TIMER)
    host.write(
        "etc/systemd/system/store-renew.service",
        "[Service]\nType=oneshot\nWorkingDirectory=/opt/app\n"
        "ExecStart=/bin/sh -c 'scripts/renew.sh && ./scripts/after.sh'\n",
    )
    host.write("opt/app/scripts/renew.sh", NOTIFIES)
    host.write("opt/app/scripts/after.sh", RESTARTS)
    out = host.run()
    assert "restarters:unread:store-renew.service" not in _ids(out)
    f = _finding(out, "restarter:store-renew.service")
    assert "/opt/app/scripts/after.sh, which matches at line 2" in f["message"]


def test_an_inline_command_names_every_script_that_matches(host):
    # Site 1: #419's first-match shape. Each matching script is named, so
    # an exception is declared over all of them, not the first alone. An
    # absolute path is also a word of the Exec line, which unit_restarts
    # reads; a relative one is only the inline command's.
    host.write("etc/systemd/system/store-cert.timer", RENEW_TIMER)
    host.write(
        "etc/systemd/system/store-renew.service",
        "[Service]\nType=oneshot\nWorkingDirectory=/opt/app\n"
        "ExecStart=/bin/sh -c './a.sh; ./b.sh'\n",
    )
    host.write("opt/app/a.sh", "#!/bin/sh\necho 'then systemctl restart x'\n")
    host.write("opt/app/b.sh", RESTARTS)
    out = host.run()
    msg = _finding(out, "restarter:store-renew.service")["message"]
    assert "/opt/app/a.sh, which matches at line 2" in msg
    assert "/opt/app/b.sh, which matches at line 2" in msg


@pytest.mark.parametrize(
    "exec_line, finds, said",
    [
        # Site 2: an option's value was read as the script. Relative, as an
        # absolute path is also read as any word of the line.
        ("/bin/bash -o pipefail ./r.sh", True, ""),
        ("/bin/bash -O extglob ./r.sh", True, ""),
        # A cluster holding c is -c: each simple command is read.
        ("/bin/bash -ec 'true && ./r.sh'", True, ""),
        ("/usr/bin/perl -I /opt/lib ./r.sh", True, ""),
        ("/usr/bin/perl -M strict ./r.sh", True, ""),
        ("/usr/bin/node -r dotenv/config ./r.sh", True, ""),
        ("/usr/bin/node --require dotenv/config ./r.sh", True, ""),
        ("/usr/bin/python3 --check-hash-based-pycs never ./r.sh", True, ""),
        ("/usr/bin/python3 -u -X dev ./r.sh", True, ""),
        # Combined short flags: -um is -u, then -m and its module.
        (
            "/usr/bin/python3 -um app.backup",
            False,
            "python3 -m app.backup, a Python module",
        ),
        ("/usr/bin/python3 -uX dev ./r.sh", True, ""),
        # Code on the command line is another language's: it isn't read as
        # a shell's, and stays unread, saying so.
        (
            "/usr/bin/python3 -c 'import app'",
            False,
            "python3 -c, code the scan doesn't read",
        ),
        ("/usr/bin/perl -e 'system 1'", False, "perl -e, code the scan doesn't read"),
        ("/usr/bin/node -e 'run()'", False, "node -e, code the scan doesn't read"),
        # perl's -c only checks the syntax: the script after it is read.
        ("/usr/bin/perl -c ./r.sh", True, ""),
        # CR 888: perl's and ruby's -x take a directory attached, never the
        # next word, which is the script.
        ("/usr/bin/perl -x ./r.sh", True, ""),
        ("/usr/bin/ruby -x ./r.sh", True, ""),
        # CR 891: bash's --rcfile and --init-file take a file.
        ("/bin/bash --rcfile /etc/app.rc ./r.sh", True, ""),
        ("/bin/bash --init-file /etc/app.rc ./r.sh", True, ""),
    ],
)
def test_an_interpreters_option_value_isnt_its_script(host, exec_line, finds, said):
    host.write("etc/systemd/system/store-cert.timer", RENEW_TIMER)
    host.write(
        "etc/systemd/system/store-renew.service",
        f"[Service]\nType=oneshot\nWorkingDirectory=/opt/app\nExecStart={exec_line}\n",
    )
    host.write("opt/app/r.sh", RESTARTS)
    host.write("etc/app.rc", NOTIFIES)
    out = host.run()
    assert ("restarter:store-renew.service" in _ids(out)) is finds
    assert ("restarters:unread:store-renew.service" in _ids(out)) is bool(said)
    if said:
        assert said in _finding(out, "restarters:unread:store-renew.service")["message"]


def test_a_home_working_directory_is_read_through_the_units_user(host):
    # Site 3: ~ is User='s home, as systemd reads it, and read_language
    # already resolves it.
    host.write(
        "etc/passwd",
        "root:x:0:0:root:/root:/bin/bash\nexedev:x:1000:1000::/home/exedev:/bin/bash\n",
    )
    host.write("etc/systemd/system/cache-sweep.timer", "[Timer]\nOnCalendar=daily\n")
    host.write(
        "etc/systemd/system/cache-sweep.service",
        "[Service]\nType=oneshot\nUser=exedev\nWorkingDirectory=~\n"
        f"ExecStart={AV}/.venv/bin/python address-validator/infra/sweep_cache.py\n",
    )
    host.write(SWEEP, RESTARTS)
    out = host.run()
    assert "restarters:unread:cache-sweep.service" not in _ids(out)
    assert "restarter:cache-sweep.service" in _ids(out)


def test_an_exception_clears_a_timers_service_the_scan_cant_follow(host):
    host.write("etc/systemd/system/store-cert.timer", RENEW_TIMER)
    host.write("etc/systemd/system/store-renew.service", RENEW_UNIT)
    host.write("usr/local/bin/store-renew.sh", b"\x7fELF\x00\x00")
    host.knob(
        "posture scheduled\n"
        "exception not-restarter:store-renew.service 2099-01-01 renews a cert only\n"
    )
    out = host.run()
    assert "restarters:unread:store-renew.service" not in _ids(out)
    assert "restarters:unread:store-renew.service" in _ids(out, "excepted")
    assert out["impact"]["restarters_complete"] is True


@pytest.mark.parametrize(
    "target, exec_line, files, finds, said",
    [
        # CR 199: what can't be read stays a restarter.
        (
            "app-notify.service",
            "ExecStart=/usr/local/bin/watchdog %i",
            {"usr/local/bin/watchdog": b"\x7fELF\x00\x00"},
            True,
            "/usr/local/bin/watchdog, a binary",
        ),
        (
            "reboot.target",
            None,
            {},
            True,
            "reboot.target isn't a service",
        ),
        (
            "app-notify.service",
            "ExecStart=/usr/bin/python3 -m app.notify",
            {},
            True,
            "python3 -m app.notify, a Python module",
        ),
        # env, then the interpreter's script.
        (
            "app-notify.service",
            "ExecStart=/usr/bin/env LANG=C bash /opt/app/r.sh",
            {"opt/app/r.sh": RESTARTS},
            True,
            "its OnFailure= target starts or restarts one",
        ),
        (
            "app-notify.service",
            "ExecStart=/usr/bin/env LANG=C bash /opt/app/r.sh",
            {"opt/app/r.sh": NOTIFIES},
            False,
            "",
        ),
        # A script named inside an inline command is read too.
        (
            "app-notify.service",
            "ExecStart=/bin/sh -c '/opt/app/r.sh %i || true'",
            {"opt/app/r.sh": RESTARTS},
            True,
            "its OnFailure= target starts or restarts one",
        ),
        # A program that starts nothing.
        (
            "app-notify.service",
            "ExecStart=/usr/bin/curl -sf http://notifier/x",
            {},
            False,
            "",
        ),
        # CR 205: each simple command of an inline one is read.
        (
            "app-notify.service",
            "ExecStart=/bin/sh -c '/usr/local/bin/helper %i'",
            {"usr/local/bin/helper": b"\x7fELF\x00\x00"},
            True,
            "/usr/local/bin/helper, a binary",
        ),
        (
            "app-notify.service",
            "ExecStart=/bin/sh -c 'notify-send failed; exit 0'",
            {},
            True,
            "notify-send, a command it can't read",
        ),
        (
            "app-notify.service",
            "ExecStart=/bin/sh -c 'curl -sf http://notifier/x || true; exit 0'",
            {},
            False,
            "",
        ),
    ],
)
def test_an_onfailure_target_is_cleared_only_when_what_it_runs_was_read(
    host, target, exec_line, files, finds, said
):
    host.write(
        "etc/systemd/system/app.service",
        f"[Unit]\nOnFailure={target}\n[Service]\nExecStart=/usr/bin/app\n",
    )
    if exec_line:
        host.write(
            f"etc/systemd/system/{target}", f"[Service]\nType=oneshot\n{exec_line}\n"
        )
    for rel, text in files.items():
        host.write(rel, text)
    out = host.run()
    assert ("restarter:app.service" in _ids(out)) is finds
    if finds:
        assert said in _finding(out, "restarter:app.service")["message"]


UNIT_FAILURE = (
    "[Service]\nType=oneshot\nExecStart=/usr/local/bin/notify-unit-failure %i\n"
)


def _hooked(host, units: tuple[str, ...], target: str) -> None:
    for u in units:
        host.write(
            f"etc/systemd/system/{u}",
            f"[Unit]\nOnFailure={target}\n[Service]\nExecStart=/usr/bin/{u}\n",
        )


@pytest.mark.parametrize(
    "target, unit_file, key",
    [
        # #420: address-validator's notifier, which seven units hook. The
        # template is the key, whatever instance a unit names.
        (
            "unit-failure@%n.service",
            "unit-failure@.service",
            "not-restarter:unit-failure@.service",
        ),
        (
            "app-notify.service",
            "app-notify.service",
            "not-restarter:app-notify.service",
        ),
    ],
)
def test_an_unreadable_onfailure_target_takes_a_not_restarter_exception(
    host, target, unit_file, key
):
    _hooked(host, ("app.service", "worker.service"), target)
    host.write(f"etc/systemd/system/{unit_file}", UNIT_FAILURE)
    host.write("usr/local/bin/notify-unit-failure", b"\x7fELF\x00\x00")
    out = host.run()
    for u in ("app.service", "worker.service"):
        f = _finding(out, f"restarter:{u}")
        assert f["exception_what"] == key
        assert f"exception {key} <review-by> <reason>" in f["message"]
        assert "/usr/local/bin/notify-unit-failure, a binary" in f["message"]
    # One declaration covers every unit hooked to it.
    host.knob(f"posture scheduled\nexception {key} 2099-01-01 notifies only\n")
    out = host.run()
    assert not [i for i in _ids(out) if i.startswith("restarter")]
    assert {"restarter:app.service", "restarter:worker.service"} <= set(
        _ids(out, "excepted")
    )
    assert not out["impact"]["restarters"]
    assert out["impact"]["restarters_complete"] is True
    # An expired one covers nothing.
    host.knob(f"posture scheduled\nexception {key} 2001-01-01 notifies only\n")
    out = host.run()
    assert "restarter:app.service" in _ids(out)


def test_a_not_restarter_exception_doesnt_cover_a_restart_the_scan_read(host):
    # app.service's other target restarts on an Exec line, and worker's own
    # Exec line does: what was read isn't declared away.
    _hooked(host, ("app.service",), "app-notify.service store-fix.service")
    host.write("etc/systemd/system/app-notify.service", UNIT_FAILURE)
    host.write("usr/local/bin/notify-unit-failure", b"\x7fELF\x00\x00")
    host.write(
        "etc/systemd/system/store-fix.service",
        "[Service]\nExecStart=/bin/systemctl restart store.service\n",
    )
    host.write(
        "etc/systemd/system/worker.service",
        "[Unit]\nOnFailure=app-notify.service\n"
        "[Service]\nExecStart=/usr/bin/worker\n"
        "ExecStopPost=/bin/systemctl restart store.service\n",
    )
    host.knob(
        "posture scheduled\n"
        "exception not-restarter:app-notify.service 2099-01-01 notifies only\n"
    )
    out = host.run()
    for u in ("app.service", "worker.service"):
        f = _finding(out, f"restarter:{u}")
        assert f["exception_what"] is None
        assert "not-restarter" not in f["message"]
    assert {"app.service", "worker.service"} <= {
        r["unit"] for r in out["impact"]["restarters"]
    }


NOTIFY_DOCSTRING = (
    '"""Notify the operator that a unit failed.\n'
    "\n"
    "Set by systemd (>= 251) for an ``OnFailure=`` handler; absent on a manual\n"
    "``systemctl start unit-failure@<unit>.service``:\n"
    '"""\n'
    "import urllib.request\n"
)


def test_a_script_match_is_named_and_can_be_declared_not_a_call(host):
    # #419: address-validator's notifier matches only in its docstring. Every
    # non-comment line still counts, since a missed restarter runs unstopped
    # through a data-store step; the finding names the line.
    _hooked(host, ("app.service", "worker.service"), "unit-failure@%n.service")
    host.write(
        "etc/systemd/system/unit-failure@.service",
        f"[Service]\nType=oneshot\nWorkingDirectory={AV}\n"
        f"ExecStart={AV}/.venv/bin/python infra/notify_unit_failure.py %i\n",
    )
    host.write(f"{AV[1:]}/infra/notify_unit_failure.py", NOTIFY_DOCSTRING)
    out = host.run()
    for u in ("app.service", "worker.service"):
        f = _finding(out, f"restarter:{u}")
        assert f["exception_what"] == "not-restarter:unit-failure@.service"
        assert (
            f"{AV}/infra/notify_unit_failure.py, which matches at line 4: "
            "``systemctl start unit-failure@<unit>.service``:"
        ) in f["message"]
        assert "its OnFailure= target starts or restarts one" in f["message"]
        assert (
            "if none of the lines it matched is a call, declare exception "
            "not-restarter:unit-failure@.service <review-by> <reason>"
        ) in f["message"]
        # Said once: "its OnFailure= target starts or restarts one:
        # unit-failure@%n.service runs ..." (review of cbb59c0).
        assert f["message"].count("its OnFailure= target") == 1
    host.knob(
        "posture scheduled\n"
        "exception not-restarter:unit-failure@.service 2099-01-01 a docstring\n"
    )
    out = host.run()
    assert not [i for i in _ids(out) if i.startswith("restarter")]
    assert "restarter:app.service" in _ids(out, "excepted")
    assert not out["impact"]["restarters"]


def test_a_timers_script_match_is_named_and_can_be_declared_not_a_call(host):
    host.write("etc/systemd/system/store-cert.timer", RENEW_TIMER)
    host.write("etc/systemd/system/store-renew.service", RENEW_UNIT)
    host.write(
        "usr/local/bin/store-renew.sh",
        "#!/bin/sh\n# systemctl restart store, if the cert changed\n"
        "  if changed; then systemctl restart store; fi\n",
    )
    out = host.run()
    f = _finding(out, "restarter:store-renew.service")
    assert f["exception_what"] == "not-restarter:store-renew.service"
    assert (
        "what its timer runs starts or restarts one: store-renew.service runs "
        "/usr/local/bin/store-renew.sh, which matches at line 3: "
        "if changed; then systemctl restart store; fi"
    ) in f["message"]
    host.knob(
        "posture scheduled\n"
        "exception not-restarter:store-renew.service 2099-01-01 never changes\n"
    )
    out = host.run()
    assert "restarter:store-renew.service" in _ids(out, "excepted")
    assert not out["impact"]["restarters"]


def test_an_exec_line_restart_wins_over_an_earlier_script_match(host):
    # Review of cbb59c0: the first Exec line's script matches only in its
    # docstring, and a later Exec line restarts. That restart was read, so
    # no exception may cover it.
    _hooked(host, ("app.service",), "unit-failure@%n.service")
    host.write(
        "etc/systemd/system/unit-failure@.service",
        f"[Service]\nType=oneshot\nWorkingDirectory={AV}\n"
        f"ExecStart={AV}/.venv/bin/python infra/notify_unit_failure.py %i\n"
        "ExecStartPost=/bin/systemctl restart store.service\n",
    )
    host.write(f"{AV[1:]}/infra/notify_unit_failure.py", NOTIFY_DOCSTRING)
    host.knob(
        "posture scheduled\n"
        "exception not-restarter:unit-failure@.service 2099-01-01 a docstring\n"
    )
    out = host.run()
    f = _finding(out, "restarter:app.service")
    assert f["exception_what"] is None
    assert "not-restarter" not in f["message"]
    assert "app.service" in {r["unit"] for r in out["impact"]["restarters"]}


def test_a_timers_service_exec_line_restart_wins_over_its_script_match(host):
    # The timer-service twin, in a drop-in, and with start, which the unit
    # files' own restart grep doesn't take.
    host.write("etc/systemd/system/store-cert.timer", RENEW_TIMER)
    host.write("etc/systemd/system/store-renew.service", RENEW_UNIT)
    host.write(
        "etc/systemd/system/store-renew.service.d/after.conf",
        "[Service]\nExecStartPost=/bin/systemctl start store.service\n",
    )
    host.write(
        "usr/local/bin/store-renew.sh",
        "#!/bin/sh\necho 'run systemctl restart store by hand'\n",
    )
    host.knob(
        "posture scheduled\n"
        "exception not-restarter:store-renew.service 2099-01-01 a usage line\n"
    )
    out = host.run()
    f = _finding(out, "restarter:store-renew.service")
    assert f["exception_what"] is None
    assert "not-restarter" not in f["message"]


@pytest.mark.parametrize(
    "tail, said",
    [
        # Review of cbb59c0: the docstring at line 4 and the call at line 8
        # are both named, so declaring it can't silence the call unread.
        (
            'import subprocess\nsubprocess.run(["systemctl", "restart", "store.service"])\n',
            "notify_unit_failure.py, which matches at lines 4 and 8 "
            "(line 4: ``systemctl start unit-failure@<unit>.service``:; "
            'line 8: subprocess.run(["systemctl", "restart", "store.service"]))',
        ),
        # Capped: three named, and the count of the rest.
        (
            "".join(f"# {i}\nprint('systemctl restart x{i}')\n" for i in range(4)),
            "which matches at lines 4, 8, 10 and 2 more (line 4: ",
        ),
    ],
)
def test_a_script_match_names_every_line_it_matched(host, tail, said):
    _hooked(host, ("app.service",), "unit-failure@%n.service")
    host.write(
        "etc/systemd/system/unit-failure@.service",
        f"[Service]\nType=oneshot\nWorkingDirectory={AV}\n"
        f"ExecStart={AV}/.venv/bin/python infra/notify_unit_failure.py %i\n",
    )
    host.write(f"{AV[1:]}/infra/notify_unit_failure.py", NOTIFY_DOCSTRING + tail)
    out = host.run()
    f = _finding(out, "restarter:app.service")
    assert said in f["message"]
    assert "if none of the lines it matched is a call" in f["message"]


def test_a_match_in_each_of_two_scripts_is_named(host):
    # The first script's docstring doesn't hide the second script's call.
    _hooked(host, ("app.service",), "unit-failure@%n.service")
    host.write(
        "etc/systemd/system/unit-failure@.service",
        f"[Service]\nType=oneshot\nWorkingDirectory={AV}\n"
        f"ExecStart={AV}/.venv/bin/python infra/notify_unit_failure.py %i\n"
        "ExecStartPost=/bin/sh /opt/app/fix.sh\n",
    )
    host.write(f"{AV[1:]}/infra/notify_unit_failure.py", NOTIFY_DOCSTRING)
    host.write("opt/app/fix.sh", RESTARTS)
    out = host.run()
    f = _finding(out, "restarter:app.service")
    assert "notify_unit_failure.py, which matches at line 4" in f["message"]
    assert (
        ", and /opt/app/fix.sh, which matches at line 2: systemctl restart app.service"
        in f["message"]
    )


def test_a_restart_on_a_targets_exec_line_takes_no_exception(host):
    _hooked(host, ("app.service",), "store-fix.service")
    host.write(
        "etc/systemd/system/store-fix.service",
        "[Service]\nExecStart=/bin/systemctl restart store.service\n",
    )
    out = host.run()
    assert _finding(out, "restarter:app.service")["exception_what"] is None


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


def _setup_owned_by(host, uid: int) -> None:
    """stat answers UID for /exe.dev/setup's owner, and runs the real stat
    for everything else: a test can't chown to root, and a runner as root
    owns every fixture."""
    host.STUBBED = (*host.STUBBED, "stat")
    host.FALLBACKS = {**host.FALLBACKS, "stat": 'exec /usr/bin/stat "$@"'}
    host.cases["stat"] = [
        ("*%u */exe.dev/setup", f"{uid}\n", 0, "", None),
    ]


@pytest.mark.parametrize(
    "mode, disabled, root, verdict",
    [
        # notifier#99's measure: disabled, 0600, root's.
        (0o600, True, True, "contained"),
        # Still enabled: the next boot runs it again.
        (0o600, False, True, "present"),
        # Group-readable.
        (0o640, True, True, "present"),
        # exedev's own 0600: the unit's user can still read and run it.
        (0o600, True, False, "present"),
    ],
)
def test_a_setup_script_contained_in_place_is_not_a_leftover(
    host, mode, disabled, root, verdict
):
    # #352: the preventative measure keeps the file, root's alone, with the
    # unit disabled. Shredded, it comes back at 0755.
    host.write(
        "exe.dev/setup",
        f"#!/bin/sh\nTS_AUTHKEY=tskey-auth-{SECRET}\n",
        mode=mode,
    )
    host.write(
        "usr/lib/systemd/system/exe-setup.service",
        "[Unit]\nConditionPathExists=/exe.dev/setup\n"
        "[Install]\nWantedBy=multi-user.target\n",
    )
    if not disabled:
        host.link(
            "etc/systemd/system/multi-user.target.wants/exe-setup.service",
            "/usr/lib/systemd/system/exe-setup.service",
        )
    _setup_owned_by(host, 0 if root else 1000)
    out = host.run()
    s = out["environment"]["setup_script"]
    assert s["verdict"] == verdict
    assert ("setup-script:present" in _ids(out)) is (verdict == "present")
    if verdict == "present":
        m = _finding(out, "setup-script:present")["message"]
        assert "chmod 600 /exe.dev/setup" in m
        assert "Don't shred it" in m
    assert s["file"]["owner_uid"] == (0 if root else 1000)
    for text in (host.result.stdout, host.result.stderr, host.log.read_text()):
        assert SECRET not in text


def test_a_redelivered_setup_script_whose_key_is_revoked_is_declared_not_reported(
    host,
):
    # #352: revoking the key changes nothing the probe reads, so without an
    # exception a remedied host reported it on every run.
    host.write(
        "usr/lib/systemd/system/exe-setup.service",
        "[Unit]\nConditionPathExists=/exe.dev/setup\n",
    )
    boot = "a" * 32
    host.on(
        "journalctl",
        "--list-boots*",
        "IDX BOOT ID                          FIRST ENTRY                 LAST ENTRY\n"
        f" 0 {boot} Mon 2026-09-21 10:00:00 UTC Mon 2026-09-21 11:00:00 UTC\n",
    )
    host.on(
        "journalctl",
        f"-b {boot} -u exe-setup.service*",
        "Finished exe-setup.service - Exe setup.\n",
    )
    out = host.run()
    f = _finding(out, "setup-script:redelivered")
    assert f["exception_what"] == "setup-script:redelivered"
    assert "exception setup-script:redelivered" in f["message"]
    host.knob(
        "posture automatic\n"
        "exception setup-script:redelivered 2099-01-01 key revoked 2026-10-06\n"
    )
    out = host.run()
    assert "setup-script:redelivered" not in _ids(out)
    e = _finding(out, "setup-script:redelivered", "excepted")
    assert e["reason"] == "key revoked 2026-10-06"


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


# --- the environment profile -------------------------------------------------------

LINUX_IMAGE = "*-W -f ${Package} ${db:Status-Abbrev}\\n linux-image-*"
# The image's own markers, since its import (boldsoftware/exeuntu 6f88f30).
EXEDEV_PASSWD = (
    "root:x:0:0:root:/root:/bin/bash\n"
    "exedev:x:1000:1000:exe.dev user:/home/exedev:/bin/bash\n"
)
INIT_WRAPPER = (
    "#!/bin/bash\n# Wraps systemd init with two important precursor commands.\n"
    "# \tdocker run -it ghcr.io/boldsoftware/exeuntu:latest\n"
)


def test_a_host_no_profile_matches_names_none_and_the_generic_path(host):
    p = host.run()["environment"]["profile"]
    assert (p["name"], p["generation"], p["reference"]) == (None, None, None)
    assert 'SKILL.md\'s "Hosts no profile matches"' in p["fallback"]
    assert p["markers"]["exe_dev_dir"] is False


@pytest.mark.parametrize(
    "setup, exeuntu, image, generation",
    [
        (False, False, True, "feb-2026"),
        (True, False, True, "may-2026"),
        (True, True, True, "newer"),
        (False, True, True, "unknown"),
        # On the platform alone, the image could be another: not dated.
        (False, False, False, "unknown"),
    ],
)
def test_an_exe_dev_host_names_its_profile_and_generation(
    host, setup, exeuntu, image, generation
):
    # The guest can't see its image digest, so the profile's markers decide,
    # each read on its own: usa-wa's May-2026 image had exe-setup.service but
    # no exeuntu.
    (host.root / "exe.dev" / "bin").mkdir(parents=True)
    if image:
        host.write("etc/passwd", EXEDEV_PASSWD)
        host.write("usr/local/bin/init", INIT_WRAPPER, mode=0o755)
    host.write(
        "proc/cmdline",
        "root=/dev/vda init=/exe.dev/bin/exe-init console=hvc0\n",
    )
    host.write("proc/sys/kernel/osrelease", "6.12.93\n")
    host.on(
        "dpkg-query",
        LINUX_IMAGE,
        rc=1,
        stderr="dpkg-query: no packages found matching linux-image-*\n",
    )
    if setup:
        host.write(
            "usr/lib/systemd/system/exe-setup.service",
            "[Service]\nExecStart=/exe.dev/setup\n[Install]\nWantedBy=multi-user.target\n",
        )
    if exeuntu:
        host.write("usr/local/bin/exeuntu", "#!/bin/sh\n", mode=0o755)
    out = host.run()
    p = out["environment"]["profile"]
    assert p["name"] == "exe-dev-exeuntu"
    assert p["reference"] == "references/environments/exe-dev-exeuntu.md"
    assert p["generation"] == generation
    assert (p["platform"], p["image"]) == (True, image)
    assert p["markers"] == {
        "exe_init_cmdline": True,
        "exe_dev_dir": True,
        "exedev_account": image,
        "init_wrapper": image,
        "exeuntu": exeuntu,
        "exe_setup_unit": "disabled" if setup else "not-found",
        "linux_image_packages": 0,
        "kernel": "6.12.93",
    }
    # No guest kernel: needrestart's kernel lines mean nothing here.
    assert "never decide a reboot" in out["impact"]["reboot"]["kernel_status_note"]


def test_an_offline_image_tree_is_matched_by_its_files(tmp_path):
    # Nothing runs the tree, and the platform supplies /exe.dev/ at boot, so
    # only the image's own files name the profile here.
    h = Host(tmp_path, live=False).knob("posture scheduled\n")
    h.write("etc/passwd", EXEDEV_PASSWD)
    h.write("usr/local/bin/init", INIT_WRAPPER)
    h.write("usr/local/bin/exeuntu", "#!/bin/sh\n")
    h.write("etc/systemd/system/exe-setup.service", "[Service]\n")
    h.on("dpkg-query", LINUX_IMAGE, "linux-image-6.8.0-45-generic ii \n")
    p = h.run()["environment"]["profile"]
    assert (p["name"], p["generation"]) == ("exe-dev-exeuntu", "newer")
    assert (p["platform"], p["image"]) == (False, True)
    assert p["markers"]["exe_init_cmdline"] is None
    assert p["markers"]["exe_dev_dir"] is False
    assert p["markers"]["linux_image_packages"] == 1


# --- exe.dev's platform files (#388, items 1 and 5) ------------------------------
# The guest can't see its image's digest, but /exe.dev/etc/image.conf holds
# the image's OCI config, labels included: its build time, its commit and its
# channel. The values are the test VM's of #346, 2026-09-30.

LABELS = {
    "created": "2026-09-29T17:09:11.717Z",
    "revision": "1b74aabd1c7082239c73dc9fe249fcf04634c765",
    "version": "nightly",
}
OCI = {
    "architecture": "amd64",
    "os": "linux",
    "config": {
        "Env": ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"],
        "Labels": {
            "org.opencontainers.image.created": LABELS["created"],
            "org.opencontainers.image.revision": LABELS["revision"],
            "org.opencontainers.image.source": "https://github.com/boldsoftware/exe",
            "org.opencontainers.image.version": LABELS["version"],
        },
    },
}


def _exe_dev(host: Host) -> Host:
    """An exe.dev VM, as the platform's own markers name it."""
    (host.root / "exe.dev" / "etc").mkdir(parents=True)
    host.write("proc/cmdline", "root=/dev/vda init=/exe.dev/bin/exe-init\n")
    return host


@pytest.mark.parametrize("indent", [None, 2], ids=["compact", "indented"])
def test_an_exe_dev_host_reports_its_images_labels(host, indent):
    _exe_dev(host).write("exe.dev/etc/image.conf", json.dumps(OCI, indent=indent))
    c = host.run()["environment"]["image_conf"]
    assert c == {"path": "/exe.dev/etc/image.conf", "present": True, **LABELS}


def test_a_label_image_conf_lacks_is_null_never_a_default(host):
    oci = json.loads(json.dumps(OCI))
    del oci["config"]["Labels"]["org.opencontainers.image.version"]
    _exe_dev(host).write("exe.dev/etc/image.conf", json.dumps(oci))
    c = host.run()["environment"]["image_conf"]
    assert c["version"] is None
    assert c["revision"] == LABELS["revision"]


# A runner as root reads a 0000 file, as the probe would through sudo.
AS_ROOT = pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-0000 file")


@AS_ROOT
def test_an_image_conf_that_cant_be_read_is_not_read(tmp_path):
    host = Host(tmp_path, sudo=False).knob("class production\nposture automatic\n")
    _exe_dev(host).write("exe.dev/etc/image.conf", json.dumps(OCI), mode=0o000)
    out = host.run()
    c = out["environment"]["image_conf"]
    assert c["present"] is True
    assert (c["created"], c["revision"], c["version"]) == (None, None, None)
    assert any("/exe.dev/etc/image.conf" in n for n in out["not_read"]), out["not_read"]


def test_an_exe_dev_host_without_image_conf_says_so(host):
    c = _exe_dev(host).run()["environment"]["image_conf"]
    assert c == {
        "path": "/exe.dev/etc/image.conf",
        "present": False,
        "created": None,
        "revision": None,
        "version": None,
    }


def test_a_host_no_profile_matches_reads_no_exe_dev_file(host):
    env = host.run()["environment"]
    assert env["image_conf"] is None
    assert env["exe_init"] is None


# exe-init's layout is a separate axis from the generation (the profile):
# what's resident decides it.
EXE_INIT = "/exe.dev/bin/exe-init"


def _proc(host: Host, pid: int, comm: str, args: str, uid: int = 0, exe=None) -> None:
    """A process: its comm, its argv (/exe.dev/bin/<comm> and ARGS), the
    owner its status names, and its exe link, to EXE or the argv's binary."""
    host.write(f"proc/{pid}/comm", comm + "\n")
    host.write(
        f"proc/{pid}/status", f"Name:\t{comm}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n"
    )
    argv = [f"/exe.dev/bin/{comm}", *args.split()]
    host.write(f"proc/{pid}/cmdline", "".join(a + "\0" for a in argv).encode())
    host.link(f"proc/{pid}/exe", exe or argv[0])


@pytest.mark.parametrize(
    "procs, layout, roles",
    [
        (
            {77: ("exe-init", "guestd"), 78: ("exe-scroll", "")},
            "guestd",
            ["guestd"],
        ),
        (
            {77: ("exe-init", "op-ssh"), 79: ("exe-init", "memd")},
            "op-ssh+memd",
            ["memd", "op-ssh"],
        ),
        ({}, "init-only", []),
        # A role the profile doesn't know: never guessed.
        ({77: ("exe-init", "something-new")}, "unknown", ["something-new"]),
        # CR 1645: the operator's own exe-init --version, which the profile
        # says to run, as exedev or under sudo, isn't resident.
        (
            {77: ("exe-init", "guestd"), 90: ("exe-init", "--version", 1000)},
            "guestd",
            ["guestd"],
        ),
        (
            {77: ("exe-init", "guestd"), 91: ("exe-init", "--version")},
            "guestd",
            ["guestd"],
        ),
        # A process named exe-init that isn't the platform's binary.
        (
            {92: ("exe-init", "guestd", 0, "/home/exedev/exe-init")},
            "init-only",
            [],
        ),
        # A role is a word, never a glob: [g]uestd matches the file guestd
        # in the probe's working directory.
        ({77: ("exe-init", "[g]uestd")}, "unknown", ["[g]uestd"]),
        # CR 1649: root's resident exe-init with another option first isn't
        # an invocation to skip: its role is unknown, never init-only.
        (
            {77: ("exe-init", "--log-level=debug guestd")},
            "unknown",
            ["--log-level=debug"],
        ),
        # CR 1652: the platform's binary with a role, run by a user, isn't
        # the resident one: root's alone is.
        ({93: ("exe-init", "guestd", 1000)}, "init-only", []),
        # CR 1654: -v with a role after it is an option, verbose say, not
        # the query exe-init -v alone would be.
        ({77: ("exe-init", "-v guestd")}, "unknown", ["-v"]),
        # The query alone, as root, isn't resident.
        ({77: ("exe-init", "guestd"), 94: ("exe-init", "-h")}, "guestd", ["guestd"]),
    ],
    ids=[
        "guestd",
        "op-ssh-memd",
        "init-only",
        "unknown-role",
        "operators-version",
        "operators-version-as-root",
        "not-the-platforms",
        "role-not-globbed",
        "leading-option",
        "a-users-guestd",
        "short-option-with-a-role",
        "short-query-alone",
    ],
)
def test_an_exe_dev_host_reports_exe_inits_layout(host, procs, layout, roles):
    _exe_dev(host)
    (host.tmp / "guestd").write_text("")
    for pid, p in procs.items():
        _proc(host, pid, *p)
    e = host.run()["environment"]["exe_init"]
    assert e["layout"] == layout
    assert sorted(r["role"] for r in e["resident"]) == roles


def test_an_exe_init_whose_binary_cant_be_read_makes_the_layout_unknown(host):
    # CR 1645: /proc/<pid>/exe is root's alone to read; one even root can't
    # read is never taken as the platform's binary, or as not.
    _exe_dev(host)
    _proc(host, 77, "exe-init", "guestd")
    (host.root / "proc" / "77" / "exe").unlink()
    host.write("proc/77/exe", "not a link")
    out = host.run()
    assert out["environment"]["exe_init"]["layout"] == "unknown"
    assert any("/proc/77/exe" in n for n in out["not_read"]), out["not_read"]


def test_an_exe_init_whose_owner_cant_be_read_makes_the_layout_unknown(host):
    # CR 1652: with no status to name its owner, whether it's root's is
    # unknown, never skipped.
    _exe_dev(host)
    _proc(host, 77, "exe-init", "guestd")
    (host.root / "proc" / "77" / "status").unlink()
    out = host.run()
    assert out["environment"]["exe_init"]["layout"] == "unknown"
    assert any("/proc/77/status" in n for n in out["not_read"]), out["not_read"]


@AS_ROOT
def test_exe_inits_layout_is_unknown_where_proc_hides_other_processes(host):
    # hidepid hides PID 1 as it hides exe-init: no exe-init seen isn't
    # init-only then.
    _exe_dev(host)
    (host.root / "proc" / "1" / "comm").chmod(0o000)
    out = host.run()
    assert out["environment"]["exe_init"]["layout"] == "unknown"
    assert any("exe-init's layout" in n for n in out["not_read"]), out["not_read"]


def test_an_offline_image_tree_reads_no_layout(tmp_path):
    h = Host(tmp_path, live=False).knob("posture scheduled\n")
    h.write("etc/passwd", EXEDEV_PASSWD)
    h.write("usr/local/bin/init", INIT_WRAPPER)
    out = h.run()
    assert out["environment"]["profile"]["name"] == "exe-dev-exeuntu"
    assert out["environment"]["exe_init"]["layout"] is None
    assert any("exe-init's layout" in n for n in out["not_read"]), out["not_read"]
