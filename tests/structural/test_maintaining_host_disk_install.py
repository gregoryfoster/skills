"""#425 — install-disk-gc.sh installs or updates the GC from a staging tree.

The contract's install, on a scratch root prefix: each MANIFEST file with its
staged mode, `sha256sum --strict -c` from the root against the staged
MANIFEST, the removals, `daemon-reload`, and only then MANIFEST itself, the
commit marker a re-run reads (CR 521). An update removes only the paths the
old MANIFEST lists that the new one doesn't. journald restarts only when its
drop-in changed. Nothing touches
`/etc/cannobserv/disk-gc/`, and no timer is enabled or disabled.

No test touches the real `/`: every run takes `--root` under tmp_path, and
systemctl is a stub that logs its argv (`maintaining_host_disk_rig.py`).
"""

import os
import subprocess

import pytest

from tests.structural import maintaining_host_disk_rig as rig

pytestmark = pytest.mark.usefixtures("linux_tools")

INSTALL = rig.SCRIPTS / "install-disk-gc.sh"
OLD_HELPER = f"{rig.GC_DIR}/old-helper"


@pytest.fixture
def linux_tools():
    rig.require_linux_tools()


@pytest.fixture
def host(tmp_path):
    return rig.make_host(tmp_path / "root")


host_files = rig.host_files


def v1_files(**changes):
    files = rig.gc_files(version=1, disk_gc=b"#!/usr/bin/python3 -I\n# v1\n")
    files[OLD_HELPER] = (b"retired in v2\n", 0o644)
    for path, value in changes.items():
        files[path] = value
    return files


def staged(tmp_path, files=None, manifest=None, name="staging"):
    return rig.stage(tmp_path / name, files, manifest)


def install(tmp_path, root, staging, *extra, systemctl=True, pin_from=None, env=None):
    """Run a copy of the installer whose pin names the MANIFEST in
    `pin_from` (default: the staging tree's own)."""
    copies = sorted(tmp_path.glob("scripts-*"))
    scripts = rig.pinned_scripts(
        tmp_path / f"scripts-{len(copies)}", pin_from or staging
    )
    args = ["--staging", staging, "--root", root, *extra]
    stub = None
    if systemctl:
        stub = rig.stub_systemctl(tmp_path / "bin")
        args += ["--systemctl", stub]
    result = rig.run(scripts / INSTALL.name, *args, env=env)
    return result, stub


def ok(result):
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    out = rig.stdout_json(result)
    assert out["ok"] is True, out
    return out


def refused(result, says):
    assert result.returncode == 3, (result.returncode, result.stdout, result.stderr)
    out = rig.stdout_json(result)
    assert out["ok"] is False
    assert any(says in r for r in out["refused"]), out["refused"]
    return out


def installed(root):
    return {p: v for p, v in rig.tree(root).items() if p.startswith("usr/")}


def want_tree(files):
    out = dict(files)
    out[f"{rig.GC_DIR}/MANIFEST"] = (rig.manifest_text(files), 0o644)
    return out


# --- a fresh install ---------------------------------------------------------


def test_plan_changes_nothing(tmp_path, host):
    before = rig.tree(host)
    result, stub = install(tmp_path, host, staged(tmp_path))
    out = ok(result)
    assert out["action"] == "install" and out["applied"] is False
    assert out["journald_restart"] is True
    assert rig.tree(host) == before
    assert rig.calls(stub) == []


def test_fresh_install(tmp_path, host):
    keep = host_files(host)
    result, stub = install(tmp_path, host, staged(tmp_path), "--approve")
    out = ok(result)
    assert out["action"] == "install" and out["applied"] is True
    assert installed(host) == want_tree(rig.gc_files())
    assert rig.calls(stub) == ["daemon-reload", "restart systemd-journald"]
    assert host_files(host) == keep
    assert out["installed_version"] is None and out["staged_version"] == 2


def test_scratch_root_without_systemctl_runs_none(tmp_path, host):
    result, _ = install(tmp_path, host, staged(tmp_path), "--approve", systemctl=False)
    out = ok(result)
    assert out["systemctl_ran"] is False
    assert out["systemctl"] == ["daemon-reload", "restart systemd-journald"]


# --- an update ---------------------------------------------------------------


def test_update_removes_only_what_it_dropped(tmp_path, host):
    rig.stage(host, v1_files())
    stray = host / rig.GC_DIR / "host-notes"
    stray.write_text("the host's own\n")
    keep = host_files(host)
    result, stub = install(tmp_path, host, staged(tmp_path), "--approve")
    out = ok(result)
    assert out["action"] == "update"
    assert (out["installed_version"], out["staged_version"]) == (1, 2)
    assert out["removed"] == [OLD_HELPER]
    assert not (host / OLD_HELPER).exists()
    assert stray.read_text() == "the host's own\n"
    got = installed(host)
    got.pop(f"{rig.GC_DIR}/host-notes")
    assert got == want_tree(rig.gc_files())
    assert host_files(host) == keep


def test_update_with_journald_unchanged_does_not_restart_it(tmp_path, host):
    rig.stage(host, v1_files())
    result, stub = install(tmp_path, host, staged(tmp_path), "--approve")
    out = ok(result)
    assert out["journald_restart"] is False
    assert rig.calls(stub) == ["daemon-reload"]


def test_update_with_journald_changed_restarts_it(tmp_path, host):
    rig.stage(
        host, v1_files(**{rig.JOURNALD: (b"[Journal]\nSystemMaxUse=1G\n", 0o644)})
    )
    result, stub = install(tmp_path, host, staged(tmp_path), "--approve")
    assert ok(result)["journald_restart"] is True
    assert rig.calls(stub) == ["daemon-reload", "restart systemd-journald"]


def test_update_that_drops_the_journald_conf_removes_it_and_restarts(tmp_path, host):
    rig.stage(host, v1_files())
    new = rig.gc_files(zz_cannobserv_journal_conf=None)
    result, stub = install(tmp_path, host, staged(tmp_path, new), "--approve")
    out = ok(result)
    assert rig.JOURNALD in out["removed"]
    assert not (host / rig.JOURNALD).exists()
    assert rig.calls(stub) == ["daemon-reload", "restart systemd-journald"]


def test_update_never_touches_a_timer(tmp_path, host):
    rig.stage(host, v1_files())
    result, stub = install(tmp_path, host, staged(tmp_path), "--approve")
    ok(result)
    assert not [
        c for c in rig.calls(stub) if "enable" in c or "disable" in c or "timer" in c
    ]
    link = host / "etc/systemd/system/timers.target.wants/cannobserv-disk-gc.timer"
    assert link.is_symlink()


def test_same_version_is_current_and_changes_nothing(tmp_path, host):
    rig.stage(host, rig.gc_files())
    before = rig.tree(host)
    result, stub = install(tmp_path, host, staged(tmp_path), "--approve")
    out = ok(result)
    assert out["action"] == "current"
    assert rig.tree(host) == before
    assert rig.calls(stub) == ["daemon-reload"]


def test_same_version_without_approve_runs_nothing(tmp_path, host):
    rig.stage(host, rig.gc_files())
    result, stub = install(tmp_path, host, staged(tmp_path))
    assert ok(result)["action"] == "current"
    assert rig.calls(stub) == []


def test_same_version_with_drift_refuses_until_reinstall(tmp_path, host):
    rig.stage(host, rig.gc_files())
    (host / rig.GC_DIR / "disk-gc").write_text("edited on the host\n")
    result, _ = install(tmp_path, host, staged(tmp_path), "--approve")
    refused(result, "--reinstall")
    assert (host / rig.GC_DIR / "disk-gc").read_text() == "edited on the host\n"
    result, _ = install(
        tmp_path, host, staged(tmp_path, name="again"), "--approve", "--reinstall"
    )
    assert ok(result)["action"] == "reinstall"
    assert installed(host) == want_tree(rig.gc_files())


def test_downgrade_is_refused(tmp_path, host):
    rig.stage(host, rig.gc_files(version=3))
    before = rig.tree(host)
    result, _ = install(tmp_path, host, staged(tmp_path), "--approve")
    refused(result, "older")
    assert rig.tree(host) == before


# --- refusals before anything changes ----------------------------------------


def test_staging_that_fails_its_manifest(tmp_path, host):
    manifest = rig.manifest_text(rig.gc_files())
    files = rig.gc_files(disk_gc=b"tampered\n")
    before = rig.tree(host)
    result, stub = install(
        tmp_path, host, staged(tmp_path, files, manifest), "--approve"
    )
    refused(result, "sha256sum")
    assert rig.tree(host) == before
    assert rig.calls(stub) == []


def test_staging_with_an_extra_file(tmp_path, host):
    staging = staged(tmp_path)
    (staging / rig.GC_DIR / "stowaway").write_text("x")
    result, _ = install(tmp_path, host, staging, "--approve")
    refused(result, "stowaway")
    assert not (host / "usr").exists()


def test_staging_with_a_symlink(tmp_path, host):
    staging = staged(tmp_path)
    os.symlink("/etc/shadow", staging / rig.GC_DIR / "link")
    result, _ = install(tmp_path, host, staging, "--approve")
    refused(result, "link")
    assert not (host / "usr").exists()


def test_staging_manifest_naming_etc(tmp_path, host):
    files = rig.gc_files()
    files["etc/cannobserv/disk-gc/disk-gc.conf"] = (b"overwritten\n", 0o644)
    keep = host_files(host)
    result, _ = install(tmp_path, host, staged(tmp_path, files), "--approve")
    refused(result, "outside usr/local/lib/")
    assert host_files(host) == keep


def test_installed_manifest_naming_etc_is_refused(tmp_path, host):
    """An update removes what the old MANIFEST listed: one that names the
    host's config would delete it."""
    old = v1_files()
    manifest = rig.manifest_text(old) + (
        b"%s  etc/cannobserv/disk-gc/disk-gc.conf\n" % (b"0" * 64)
    )
    rig.stage(host, old, manifest)
    keep = host_files(host)
    result, _ = install(tmp_path, host, staged(tmp_path), "--approve")
    refused(result, "outside usr/local/lib/")
    assert host_files(host) == keep


def test_target_that_is_a_symlink_is_refused(tmp_path, host):
    target = host / rig.GC_DIR / "disk-gc"
    target.parent.mkdir(parents=True)
    os.symlink(host / "etc/cannobserv/disk-gc/disk-gc.conf", target)
    keep = host_files(host)
    result, _ = install(tmp_path, host, staged(tmp_path), "--approve")
    refused(result, "symlink")
    assert host_files(host) == keep


def test_installed_version_unreadable_is_refused(tmp_path, host):
    rig.stage(host, rig.gc_files())
    (host / rig.GC_DIR / "VERSION").write_text("two\n")
    result, _ = install(tmp_path, host, staged(tmp_path), "--approve")
    refused(result, "VERSION")


# --- CR 520: the root install trusts only what the pin names ------------------


def test_staged_mode_changed_after_the_pull_is_refused(tmp_path, host):
    staging = staged(tmp_path)
    (staging / rig.UNIT_DIR / "cannobserv-disk-gc.service").chmod(0o666)
    result, stub = install(tmp_path, host, staging, "--approve")
    refused(result, "mode")
    assert not (host / "usr").exists()
    assert rig.calls(stub) == []


def test_staged_directory_mode_other_than_0755_is_refused(tmp_path, host):
    staging = staged(tmp_path)
    (staging / rig.UNIT_DIR).chmod(0o777)
    result, _ = install(tmp_path, host, staging, "--approve")
    refused(result, "mode")
    assert not (host / "usr").exists()


def test_content_and_manifest_swapped_together_is_refused(tmp_path, host):
    """Both changed in step, so sha256sum -c passes; the pin still doesn't."""
    files = rig.gc_files(disk_gc=b"#!/bin/sh\nrm -rf /\n")
    staging = staged(tmp_path, files)
    pin_from = staged(tmp_path, name="the-real-release")
    result, _ = install(tmp_path, host, staging, "--approve", pin_from=pin_from)
    refused(result, "pin")
    assert not (host / "usr").exists()


# --- CR 521: MANIFEST is the commit marker, written last ----------------------


def test_fresh_install_that_fails_to_reload_leaves_no_marker_and_resumes(
    tmp_path, host
):
    staging = staged(tmp_path)
    stub = rig.stub_systemctl(tmp_path / "bin")
    rig.fail_once(stub, "daemon-reload")
    result, _ = install(tmp_path, host, staging, "--approve")
    assert result.returncode == 1, result.stdout
    assert rig.stdout_json(result)["failed"]
    assert not (host / rig.GC_DIR / "MANIFEST").exists()
    result, stub = install(tmp_path, host, staging, "--approve")
    out = ok(result)
    assert out["action"] == "install"
    assert installed(host) == want_tree(rig.gc_files())
    assert rig.calls(stub)[-2:] == ["daemon-reload", "restart systemd-journald"]


def test_update_that_fails_to_reload_keeps_the_old_marker_and_resumes(tmp_path, host):
    rig.stage(host, v1_files())
    old_manifest = (host / rig.GC_DIR / "MANIFEST").read_bytes()
    staging = staged(tmp_path)
    stub = rig.stub_systemctl(tmp_path / "bin")
    rig.fail_once(stub, "daemon-reload")
    result, _ = install(tmp_path, host, staging, "--approve")
    assert result.returncode == 1, result.stdout
    assert (host / rig.GC_DIR / "MANIFEST").read_bytes() == old_manifest
    result, stub = install(tmp_path, host, staging, "--approve")
    out = ok(result)
    assert out["action"] == "update"
    assert not (host / OLD_HELPER).exists()
    assert installed(host) == want_tree(rig.gc_files())
    assert rig.calls(stub)[-1] == "daemon-reload"


def test_install_that_fails_to_restart_journald_restarts_it_on_the_re_run(
    tmp_path, host
):
    """The drop-in is already on disk after the failed run, so only the
    marker can say journald hasn't taken it yet."""
    staging = staged(tmp_path)
    stub = rig.stub_systemctl(tmp_path / "bin")
    rig.fail_once(stub, "restart")
    result, _ = install(tmp_path, host, staging, "--approve")
    assert result.returncode == 1, result.stdout
    assert (host / rig.JOURNALD).exists()
    result, stub = install(tmp_path, host, staging, "--approve")
    assert ok(result)["journald_restart"] is True
    assert rig.calls(stub)[-1] == "restart systemd-journald"


def test_current_after_a_lost_reload_reloads_again(tmp_path, host):
    """A run that installed the marker but whose reload didn't take reads
    as current; with --approve, current still reloads."""
    rig.stage(host, rig.gc_files())
    result, stub = install(tmp_path, host, staged(tmp_path), "--approve")
    assert ok(result)["action"] == "current"
    assert rig.calls(stub) == ["daemon-reload"]


def test_real_root_needs_root(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("runs as root, so the refusal for a non-root caller can't arise")
    result = rig.run(INSTALL, "--staging", staged(tmp_path), "--approve")
    refused(result, "root")


def test_staging_is_required():
    result = rig.run(INSTALL)
    assert result.returncode == 2
    assert "--staging" in result.stderr


# --- CR 529: --root // is / ---------------------------------------------------


@pytest.mark.parametrize("spelling", ["//", "///", "/./"])
def test_slashes_that_name_root_are_root(tmp_path, spelling):
    """A plan only (no --approve), so it reads / and changes nothing."""
    result, _ = install(tmp_path, spelling, staged(tmp_path), systemctl=False)
    out = rig.stdout_json(result)
    assert out["root"] == "/"


# --- CR 530: a unit the new MANIFEST drops is disabled before it goes -------

OLD_TIMER = f"{rig.UNIT_DIR}/cannobserv-disk-old.timer"


def test_a_dropped_unit_is_disabled_before_it_is_removed(tmp_path, host):
    rig.stage(host, v1_files(**{OLD_TIMER: (b"[Timer]\n", 0o644)}))
    result, stub = install(tmp_path, host, staged(tmp_path))
    plan = ok(result)
    assert plan["systemctl"] == [
        "disable --now cannobserv-disk-old.timer",
        "daemon-reload",
    ]
    result, stub = install(tmp_path, host, staged(tmp_path, name="again"), "--approve")
    ok(result)
    assert rig.calls(stub) == [
        "disable --now cannobserv-disk-old.timer",
        "daemon-reload",
    ]
    assert not (host / OLD_TIMER).exists()


# --- CR 531: applied only once something is installed -----------------------


def test_a_failure_before_any_install_says_applied_false(tmp_path, host):
    rig.stage(host, rig.gc_files())
    stub = rig.stub_systemctl(tmp_path / "bin")
    rig.fail_once(stub, "daemon-reload")
    result, _ = install(tmp_path, host, staged(tmp_path), "--approve")
    assert result.returncode == 1, result.stdout
    out = rig.stdout_json(result)
    assert out["failed"] and out["applied"] is False


def test_no_private_directory_is_a_json_failure_with_applied_false(tmp_path, host):
    scripts = rig.pinned_scripts(tmp_path / "s", staged(tmp_path))
    # A mktemp that fails, as root or not (as root, TMPDIR is ignored).
    bindir = tmp_path / "shim"
    bindir.mkdir()
    (bindir / "mktemp").write_text("#!/usr/bin/env bash\nexit 1\n")
    (bindir / "mktemp").chmod(0o755)
    result = rig.run(
        scripts / INSTALL.name,
        "--staging",
        tmp_path / "staging",
        "--root",
        host,
        "--approve",
        env={"PATH": f"{bindir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 1, result.stdout
    out = rig.stdout_json(result)
    assert "private directory" in out["failed"]
    assert out["applied"] is False
    assert not (host / "usr").exists()


# --- CR 537b: a symlinked parent, not just the last component ----------------


def test_a_symlinked_parent_directory_is_refused(tmp_path, host):
    outside = tmp_path / "outside"
    outside.mkdir()
    (host / "usr/local/lib").mkdir(parents=True)
    os.symlink(outside, host / "usr/local/lib/systemd")
    result, stub = install(tmp_path, host, staged(tmp_path), "--approve")
    refused(result, "symlink")
    assert list(outside.iterdir()) == []
    assert rig.calls(stub) == []


@pytest.mark.parametrize(
    "path, ok",
    [
        ("usr/local/lib/x", True),
        ("usr/local/lib/./x", False),
        ("./usr/local/lib/x", False),
        ("usr/local/lib/x//y", False),
        ("usr/local/lib/x/", False),
        ("usr/local/lib/../lib/x", False),
        ("usr/local/lib/.wh.x", False),
        ("usr/local/libx", False),
        ("usr/local/lib/x y", False),
    ],
)
def test_safe_rel(path, ok):
    lib = rig.SCRIPTS / "_manifest-lib.sh"
    result = subprocess.run(
        ["bash", "-c", '. "$1"; safe_rel "$2"', "_", str(lib), path],
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is ok, (path, result.stderr)


# --- CR 540: a symlinked --staging is copied as the tree it names ------------


def test_a_symlinked_staging_tree_is_copied_not_followed(tmp_path, host):
    """An `install` shim plants a file in the user's tree after the first
    install call, as a user racing the root install would. A private copy
    made through the link already holds the real bytes; a copy that is
    itself the link reads the planted one."""
    real = staged(tmp_path)
    link = tmp_path / "staging-link"
    os.symlink(real, link)
    planted = real / rig.GC_DIR / "disk-gc"
    bindir = tmp_path / "shim"
    bindir.mkdir()
    flag = bindir / "planted"
    shim = bindir / "install"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'if [ ! -e "{flag}" ]; then : >"{flag}"; '
        f'printf "#!/bin/sh\\necho planted\\n" >"{planted}"; fi\n'
        'exec /usr/bin/install "$@"\n'
    )
    shim.chmod(0o755)
    path = f"{bindir}:{os.environ['PATH']}"
    result, _ = install(
        tmp_path, host, link, "--approve", pin_from=real, env={"PATH": path}
    )
    ok(result)
    assert flag.exists(), "the shim must have run"
    assert installed(host) == want_tree(rig.gc_files())


# --- CR 542: as root, the private directory never sits in the user's TMPDIR -


def test_as_root_the_private_directory_ignores_tmpdir(tmp_path, host):
    """sudo can keep a user's TMPDIR, whose owner can rename the directory
    away and put their own in its place."""
    if os.geteuid() != 0:
        pytest.skip("needs root: TMPDIR is honoured for a non-root run")
    user_tmp = tmp_path / "user-tmp"
    user_tmp.mkdir()
    bindir = tmp_path / "shim"
    bindir.mkdir()
    log = bindir / "mktemp.log"
    shim = bindir / "mktemp"
    shim.write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"{log}"\nexec /usr/bin/mktemp "$@"\n'
    )
    shim.chmod(0o755)
    env = {"PATH": f"{bindir}:{os.environ['PATH']}", "TMPDIR": str(user_tmp)}
    result, _ = install(tmp_path, host, staged(tmp_path), "--approve", env=env)
    ok(result)
    calls = log.read_text()
    assert str(user_tmp) not in calls, calls
    assert list(user_tmp.iterdir()) == []


# --- CR 550: --reinstall over a drifted drop-in restarts journald ------------


def test_reinstall_over_a_drifted_drop_in_restarts_journald(tmp_path, host):
    rig.stage(host, rig.gc_files())
    with open(host / rig.JOURNALD, "a") as f:
        f.write("SystemMaxUse=8G\n")
    result, stub = install(tmp_path, host, staged(tmp_path), "--reinstall")
    plan = ok(result)
    assert plan["journald_restart"] is True
    assert "restart systemd-journald" in plan["systemctl"]


# --- CR 551: an interrupted update once the pin has moved -------------------


def test_an_update_interrupted_before_the_pin_moved_names_its_recovery(tmp_path, host):
    """VERSION 1's marker, VERSION 2's files from an update that stopped,
    and now the skill pins VERSION 3: neither marker nor staging explains
    the disk, and the refusal says how to get out."""
    rig.stage(host, v1_files())
    (host / rig.GC_DIR / "VERSION").write_text("2\n")
    result, _ = install(
        tmp_path, host, staged(tmp_path, rig.gc_files(version=3)), "--approve"
    )
    out = refused(result, "old pin")
    assert any("then update" in r for r in out["refused"])
