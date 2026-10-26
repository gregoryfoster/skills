"""#425 — remove-disk-gc.sh takes the GC off a host, as the contract says.

Disable both timers, remove MANIFEST's files and MANIFEST, then
`daemon-reload` and restart journald. The host's own `/etc/cannobserv/disk-gc/`
and the GC's state stay, and so does anything MANIFEST doesn't list. A file
that no longer matches MANIFEST is someone's edit, so it refuses without
`--even-modified`. Scratch root and stub systemctl only.
"""

import os

import pytest

from tests.structural import maintaining_host_disk_rig as rig

pytestmark = pytest.mark.usefixtures("linux_tools")

REMOVE = rig.SCRIPTS / "remove-disk-gc.sh"


@pytest.fixture
def linux_tools():
    rig.require_linux_tools()


@pytest.fixture
def host(tmp_path):
    return rig.make_host(tmp_path / "root")


host_files = rig.host_files


def remove(tmp_path, root, *extra):
    stub = rig.stub_systemctl(tmp_path / "bin", root=root)
    result = rig.run(REMOVE, "--root", root, "--systemctl", stub, *extra)
    return result, stub


def test_plan_changes_nothing(tmp_path, host):
    rig.stage(host, rig.gc_files())
    before = rig.tree(host)
    result, stub = remove(tmp_path, host)
    assert result.returncode == 0, result.stderr
    out = rig.stdout_json(result)
    assert out["action"] == "remove" and out["applied"] is False
    assert rig.tree(host) == before
    assert rig.calls(stub) == []


def test_removes_manifest_files_and_keeps_the_hosts(tmp_path, host):
    rig.stage(host, rig.gc_files())
    stray = host / rig.GC_DIR / "host-notes"
    stray.write_text("mine\n")
    keep = host_files(host)
    result, stub = remove(tmp_path, host, "--approve")
    assert result.returncode == 0, result.stderr
    out = rig.stdout_json(result)
    assert out["applied"] is True
    left = [p for p in rig.tree(host) if p.startswith("usr/")]
    assert left == [f"{rig.GC_DIR}/host-notes"]
    assert host_files(host) == keep
    assert rig.calls(stub) == [
        "disable --now cannobserv-disk-gc.timer cannobserv-disk-headroom.timer",
        "stop cannobserv-disk-gc.service cannobserv-disk-headroom.service",
        "daemon-reload",
        "restart systemd-journald",
    ]
    assert "etc/cannobserv/disk-gc" in " ".join(out["kept"])


def test_modified_file_refuses_without_even_modified(tmp_path, host):
    rig.stage(host, rig.gc_files())
    (host / rig.GC_DIR / "disk-gc").write_text("edited\n")
    before = rig.tree(host)
    result, stub = remove(tmp_path, host, "--approve")
    assert result.returncode == 3, result.stdout
    assert "disk-gc" in " ".join(rig.stdout_json(result)["refused"])
    assert rig.tree(host) == before
    assert rig.calls(stub) == []
    result, _ = remove(tmp_path, host, "--approve", "--even-modified")
    assert result.returncode == 0, result.stderr
    assert not (host / rig.GC_DIR / "disk-gc").exists()


def test_remove_that_fails_to_reload_keeps_the_marker_and_resumes(tmp_path, host):
    """CR 521: MANIFEST goes last, after the reload, so a re-run finds it."""
    rig.stage(host, rig.gc_files())
    stub = rig.stub_systemctl(tmp_path / "bin")
    rig.fail_once(stub, "daemon-reload")
    result = rig.run(REMOVE, "--root", host, "--systemctl", stub, "--approve")
    assert result.returncode == 1, result.stdout
    assert (host / rig.GC_DIR / "MANIFEST").exists()
    result, stub = remove(tmp_path, host, "--approve")
    assert result.returncode == 0, result.stderr
    assert not (host / rig.GC_DIR / "MANIFEST").exists()
    assert "daemon-reload" in rig.calls(stub)


def test_remove_that_fails_to_restart_journald_restarts_it_on_the_re_run(
    tmp_path, host
):
    rig.stage(host, rig.gc_files())
    stub = rig.stub_systemctl(tmp_path / "bin")
    rig.fail_once(stub, "restart")
    result = rig.run(REMOVE, "--root", host, "--systemctl", stub, "--approve")
    assert result.returncode == 1, result.stdout
    assert not (host / rig.JOURNALD).exists()
    result, stub = remove(tmp_path, host, "--approve")
    assert result.returncode == 0, result.stderr
    assert rig.calls(stub)[-1] == "restart systemd-journald"


def test_nothing_installed(tmp_path, host):
    result, stub = remove(tmp_path, host, "--approve")
    assert result.returncode == 0, result.stderr
    assert rig.stdout_json(result)["action"] == "absent"
    assert rig.calls(stub) == []


def test_installed_manifest_naming_etc_is_refused(tmp_path, host):
    files = rig.gc_files()
    manifest = rig.manifest_text(files) + (
        b"%s  etc/cannobserv/disk-gc/disk-gc.conf\n" % (b"0" * 64)
    )
    rig.stage(host, files, manifest)
    keep = host_files(host)
    result, _ = remove(tmp_path, host, "--approve", "--even-modified")
    assert result.returncode == 3, result.stdout
    assert host_files(host) == keep


def test_double_slash_root_is_root():
    """CR 529: a plan only, so it reads / and changes nothing."""
    result = rig.run(REMOVE, "--root", "//")
    assert result.returncode == 0, result.stderr
    assert rig.stdout_json(result)["root"] == "/"


def test_a_symlinked_parent_directory_is_refused(tmp_path, host):
    """CR 537b: the parent check, not just the last component."""
    rig.stage(host, rig.gc_files())
    outside = tmp_path / "outside"
    (host / "usr/local/lib/systemd").rename(outside)
    os.symlink(outside, host / "usr/local/lib/systemd")
    before = sorted(p.name for p in outside.rglob("*"))
    result, stub = remove(tmp_path, host, "--approve")
    assert result.returncode == 3, result.stdout
    assert "symlink" in " ".join(rig.stdout_json(result)["refused"])
    assert sorted(p.name for p in outside.rglob("*")) == before
    assert rig.calls(stub) == []


def test_a_remove_interrupted_after_its_rm_loop_can_be_finished(tmp_path, host):
    """CR 541: with the unit files gone, real systemctl refuses to disable
    or stop them; a re-run must skip what is already gone, not fail on it."""
    rig.stage(host, rig.gc_files())
    stub = rig.stub_systemctl(tmp_path / "bin", root=host)
    rig.fail_once(stub, "daemon-reload")
    result = rig.run(REMOVE, "--root", host, "--systemctl", stub, "--approve")
    assert result.returncode == 1, result.stdout
    assert not (host / rig.UNIT_DIR / "cannobserv-disk-gc.timer").exists()
    first = len(rig.calls(stub))  # one log for both runs
    result, stub = remove(tmp_path, host, "--approve")
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert not (host / rig.GC_DIR / "MANIFEST").exists()
    rerun = rig.calls(stub)[first:]
    assert not [c for c in rerun if c.startswith(("disable", "stop"))], rerun


# --- CR 543: remove after an interrupted install or update -------------------


def v2_payload_over(host):
    """An update to VERSION 2 that stopped before its MANIFEST: the new
    files on disk, VERSION 1's MANIFEST still the marker."""
    for path, (data, mode) in rig.gc_files().items():
        p = host / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        p.chmod(mode)


def test_remove_after_an_interrupted_update_says_to_finish_it(tmp_path, host):
    rig.stage(host, rig.gc_files(version=1, disk_gc=b"#!/usr/bin/python3 -I\n# v1\n"))
    v2_payload_over(host)
    before = rig.tree(host)
    result, stub = remove(tmp_path, host, "--approve")
    assert result.returncode == 3, result.stdout
    why = " ".join(rig.stdout_json(result)["refused"])
    assert "interrupted" in why and "install-disk-gc.sh" in why
    assert rig.tree(host) == before
    assert rig.calls(stub) == []


def test_remove_after_an_interrupted_fresh_install_points_at_install(tmp_path, host):
    v2_payload_over(host)
    result, stub = remove(tmp_path, host, "--approve")
    assert result.returncode == 0, result.stderr
    out = rig.stdout_json(result)
    assert out["action"] == "absent"
    assert "install-disk-gc.sh" in out["note"]
    assert rig.calls(stub) == []


def test_an_interrupted_update_names_the_old_pin_recovery(tmp_path, host):
    """CR 559: once the pin has moved, finishing the update takes the skill
    at the old pin; the refusal says so."""
    rig.stage(host, rig.gc_files(version=1, disk_gc=b"#!/usr/bin/python3 -I\n# v1\n"))
    v2_payload_over(host)
    result, _ = remove(tmp_path, host, "--approve")
    assert result.returncode == 3, result.stdout
    assert "old pin" in " ".join(rig.stdout_json(result)["refused"])
