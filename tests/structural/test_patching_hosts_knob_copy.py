"""patching-hosts: a --config knob kept in the run's directory (#681).

A one-off window goes in a --config copy of the knob, never in the tracked
knob. On watcher's run (#669) that copy was under the agent's /tmp, which
the boot emptied: `reboot-chain.sh`'s next named it for the post-boot probe,
and the knob that gated the run was in no record. So:

- the first step given --config (the recovery point, the bulk, a held step
  or the chain) copies it into the run's directory, root's at 0600, named
  knob-<its sha256's first 12>, and its JSON records the copy's path and
  sha256; a later step given the same knob reuses the copy;
- a knob that changed between steps, as a fresh one-off window at a late
  approval does (#680, #687), is kept beside the earlier one and named in
  next, never refused;
- the chain's next names the copy, so it resolves after the scratch
  directory is gone; before an approval the chain writes nothing, and names
  an earlier step's copy where there is one;
- without --config the tracked knob is the record: nothing is copied;
- the copy is root's, under a 0700 directory, so the knob reader reads one
  the caller can't through sudo -n, and one sudo can't read is an error,
  never an absent knob, which would read as the defaults.
"""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.structural.patching_hosts_rig import SKILL, dispatcher
from tests.structural.patching_hosts_rig import clean_env as _clean_env
from tests.structural.test_patching_hosts_apply import KNOB, TODAY
from tests.structural.test_patching_hosts_apply import Host as ApplyHost
from tests.structural.test_patching_hosts_apply import _ready as _ready_apply
from tests.structural.test_patching_hosts_reboot import Host as ChainHost
from tests.structural.test_patching_hosts_reboot import _ready as _ready_chain
from tests.structural.test_patching_hosts_recovery import Host as RecoveryHost
from tests.structural.test_patching_hosts_recovery import _postgres

READ_KNOB = SKILL / "scripts" / "read-knob.sh"
ONE_OFF = (
    "# a one-off window, set when the approval arrived\nwindow 2026-09-29 15:00-23:00\n"
)


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


def _scratch(host, text: str) -> Path:
    """The knob as a one-off --config copy, under a scratch directory."""
    d = host.tmp / "scratch"
    d.mkdir(exist_ok=True)
    k = d / "knob"
    k.write_text(text)
    host.knob_path = k
    return k


def _copy_of(host, text: str) -> tuple[str, str]:
    sha = hashlib.sha256(text.encode()).hexdigest()
    return f"{host.run_dir}/knob-{sha[:12]}", sha


def _copies(host) -> list[str]:
    return sorted(p.name for p in host.run_dir.glob("knob*"))


@pytest.fixture
def bulk_host(tmp_path):
    return _ready_apply(ApplyHost(tmp_path))


# --- apply.sh ---------------------------------------------------------------------


def test_the_bulk_keeps_a_config_knob_in_the_run_root_only(bulk_host):
    host = bulk_host
    knob = _scratch(host, KNOB)
    out = host.run()
    assert out["verdict"]["ok"] is True, out["verdict"]
    path, sha = _copy_of(host, KNOB)
    assert out["apply"]["knob_copy"] == {
        "path": path,
        "sha256": sha,
        "given": str(knob),
        "earlier": [],
    }
    assert Path(path).read_text() == KNOB
    assert oct(Path(path).stat().st_mode & 0o777) == "0o600"
    assert _copies(host) == [Path(path).name]


def test_without_config_the_tracked_knob_is_the_record_and_nothing_is_copied(
    bulk_host,
):
    host = bulk_host
    tracked = host.tmp / ".skills" / "patching-hosts"
    tracked.parent.mkdir()
    tracked.write_text(KNOB)
    (host.state / "holds").write_text("")
    host.cases["date"] = [("+%s", f"{host.clock}\n", 0, "", None)]
    cmd = ["bash", str(host.scripts / "apply.sh"), "--step", "bulk"]
    cmd += ["--run", str(host.run_dir), "--host", "web-1", "--today", TODAY]
    cmd += ["--approve", "--dry-run", str(host.dry)]
    out = host.execute(cmd)
    assert out["verdict"]["ok"] is True, out["verdict"]
    assert out["apply"]["knob"] == str(tracked)
    assert out["apply"]["knob_copy"] is None
    assert _copies(host) == []


def test_a_held_step_given_the_same_knob_reuses_the_copy(bulk_host):
    host = bulk_host
    _scratch(host, KNOB)
    first = host.run()["apply"]["knob_copy"]
    out = host.run(step="postgres")
    assert out["verdict"]["ok"] is True, out["verdict"]
    assert out["apply"]["knob_copy"] == first
    assert _copies(host) == [Path(first["path"]).name]
    assert not [n for n in out["next"] if "other than an earlier step's" in n]


def test_a_knob_changed_between_steps_is_kept_beside_the_earlier_and_named(
    bulk_host,
):
    # address-validator's 3(b) came 8 h late, and a fresh one-off window
    # was set for it (#687): a changed knob is expected, never refused.
    host = bulk_host
    _scratch(host, KNOB)
    first = host.run()["apply"]["knob_copy"]
    _scratch(host, KNOB + ONE_OFF)
    out = host.run(step="postgres")
    assert out["verdict"]["ok"] is True, out["verdict"]
    path, sha = _copy_of(host, KNOB + ONE_OFF)
    kc = out["apply"]["knob_copy"]
    assert (kc["path"], kc["sha256"]) == (path, sha)
    assert kc["earlier"] == [first["path"]]
    [n] = [n for n in out["next"] if "other than an earlier step's" in n]
    assert path in n and first["path"] in n
    assert len(_copies(host)) == 2
    # The earlier copy is unchanged: it's the record of what gated the bulk.
    assert Path(first["path"]).read_text() == KNOB


def test_a_copy_that_cant_be_written_fails_the_bulk_before_it_changes_anything(
    bulk_host,
):
    host = bulk_host
    _scratch(host, KNOB)
    host.STUBBED = (*host.STUBBED, "mv")
    host.cases["mv"] = [("*", "", 1, "mv: cannot move\n", None)]
    out = host.run(rc=1)
    assert any(
        "couldn't be named" in w and "nothing was held or upgraded" in w
        for w in out["verdict"]["why"]
    ), out["verdict"]
    assert not host.calls("unattended-upgrade")
    assert _copies(host) == []


def test_the_copy_is_the_knob_the_step_read_not_one_edited_since(bulk_host):
    # CR 2799: the gates read the knob at the step's start, and can take
    # minutes; an edit made meanwhile isn't what gated the step.
    host = bulk_host
    knob = _scratch(host, KNOB)
    host.cases["dpkg"].insert(
        0, ("--audit", "", 0, "", f'echo "# edited" >> "{knob}"; exit 0')
    )
    out = host.run()
    assert out["verdict"]["ok"] is True, out["verdict"]
    path, sha = _copy_of(host, KNOB)
    assert out["apply"]["knob_copy"]["sha256"] == sha
    assert Path(path).read_text() == KNOB
    [n] = [n for n in out["next"] if "changed after this step read it" in n]
    assert path in n and str(knob) in n


def test_a_knob_whose_last_line_has_no_newline_is_copied_byte_for_byte(bulk_host):
    host = bulk_host
    text = KNOB.rstrip("\n")
    _scratch(host, text)
    out = host.run()
    path, sha = _copy_of(host, text)
    assert out["apply"]["knob_copy"]["sha256"] == sha
    assert Path(path).read_text() == text
    assert not [n for n in out["next"] if "changed after this step read it" in n]


def test_a_step_without_config_names_the_runs_copy_it_didnt_run_under(bulk_host):
    # CR 2800: the held step gated on the tracked knob, not the one-off copy.
    host = bulk_host
    _scratch(host, KNOB + ONE_OFF)
    copy = host.run()["apply"]["knob_copy"]["path"]
    tracked = host.tmp / ".skills" / "patching-hosts"
    tracked.parent.mkdir()
    tracked.write_text(KNOB)
    host.cases["date"] = [("+%s", f"{host.clock}\n", 0, "", None)]
    cmd = ["bash", str(host.scripts / "apply.sh"), "--step", "postgres"]
    cmd += ["--run", str(host.run_dir), "--host", "web-1", "--today", TODAY]
    out = host.execute([*cmd, "--approve"])
    assert out["verdict"]["ok"] is True, out["verdict"]
    assert out["apply"]["knob_copy"] is None
    [n] = [n for n in out["next"] if "not the run's copy" in n]
    assert copy in n and str(tracked) in n


def test_a_relative_config_is_recorded_as_an_absolute_path(bulk_host):
    # CR 2802: the record names the knob wherever it's read from.
    host = bulk_host
    (host.tmp / "rel-knob").write_text(KNOB)
    host.knob_path = Path("rel-knob")
    out = host.run()
    given = out["apply"]["knob_copy"]["given"]
    assert os.path.isabs(given)
    assert os.path.realpath(given) == os.path.realpath(host.tmp / "rel-knob")


# --- recovery-point.sh ------------------------------------------------------------


def test_the_recovery_point_keeps_the_knob_when_it_makes_the_run(tmp_path):
    host = _postgres(_ready_apply(RecoveryHost(tmp_path)))
    knob = _scratch(host, host.knob_path.read_text())
    out = host.recover()
    assert out["verdict"]["ok"] is True, out["verdict"]
    path, sha = _copy_of(host, knob.read_text())
    assert out["recovery_point"]["knob_copy"]["path"] == path
    assert out["recovery_point"]["knob_copy"]["sha256"] == sha
    assert oct(Path(path).stat().st_mode & 0o777) == "0o600"


# --- reboot-chain.sh --------------------------------------------------------------


@pytest.fixture
def chain_host(tmp_path):
    return _ready_chain(ChainHost(tmp_path))


def _read_knob(path: str, **env_extra: str) -> subprocess.CompletedProcess:
    env = _clean_env()
    env.update(env_extra)
    return subprocess.run(
        ["bash", str(READ_KNOB), "--config", path, "--host", "web-1", "--today", TODAY],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_the_chains_next_names_the_copy_which_outlives_the_scratch_directory(
    chain_host,
):
    # Watcher's knob was under /tmp, and the boot emptied it (#669).
    host = chain_host
    text = host.knob_path.read_text()
    knob = _scratch(host, text)
    out = host.reboot()
    path, sha = _copy_of(host, text)
    assert out["reboot_chain"]["knob_copy"]["path"] == path
    assert out["reboot_chain"]["knob"] == str(knob)
    [n] = [n for n in out["next"] if "--post-boot" in n]
    assert f'--config "{path}"' in n
    assert str(knob) not in n
    shutil.rmtree(knob.parent)
    r = _read_knob(path)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["knob"]["present"] is True


def test_before_an_approval_the_chain_copies_nothing_and_names_the_given_knob(
    chain_host,
):
    host = chain_host
    knob = _scratch(host, host.knob_path.read_text())
    out = host.reboot(approve=False, rc=3)
    out = json.loads(host.result.stdout)
    assert out["reboot_chain"]["knob_copy"] is None
    [n] = [n for n in out["next"] if "--post-boot" in n]
    assert f'--config "{knob}"' in n
    assert _copies(host) == []


def test_before_an_approval_the_chain_names_an_earlier_steps_copy(chain_host):
    host = chain_host
    text = host.knob_path.read_text()
    _scratch(host, text)
    path, _ = _copy_of(host, text)
    Path(path).write_text(text)
    out = host.reboot(approve=False, rc=3)
    out = json.loads(host.result.stdout)
    assert out["reboot_chain"]["knob_copy"]["path"] == path
    [n] = [n for n in out["next"] if "--post-boot" in n]
    assert f'--config "{path}"' in n


def test_a_chain_whose_knob_cant_be_copied_schedules_nothing(chain_host):
    host = chain_host
    _scratch(host, host.knob_path.read_text())
    host.STUBBED = (*host.STUBBED, "mv")
    host.cases["mv"] = [("*", "", 1, "mv: cannot move\n", None)]
    host.reboot(rc=1)
    out = json.loads(host.result.stdout)
    assert any("couldn't be named" in w for w in out["launched"]["why"])
    assert not host.calls("systemd-run")
    assert not (host.run_dir / "reboot-chain.sh").exists()


def test_before_an_approval_the_chain_names_an_earlier_copy_of_another_knob(
    chain_host,
):
    # CR 2804: the refused path's next carries the copy note too.
    host = chain_host
    text = host.knob_path.read_text()
    _scratch(host, text)
    path, _ = _copy_of(host, text)
    Path(path).write_text(text)
    other = host.run_dir / "knob-aaaaaaaaaaaa"
    other.write_text(KNOB)
    out = host.reboot(approve=False, rc=3)
    assert out["reboot_chain"]["knob_copy"]["earlier"] == [str(other)]
    [n] = [n for n in out["next"] if "other than an earlier step's" in n]
    assert str(other) in n


def test_a_chain_given_a_relative_config_names_it_absolutely(chain_host):
    host = chain_host
    (host.tmp / "rel-knob").write_text(host.knob_path.read_text())
    host.knob_path = Path("rel-knob")
    out = host.reboot(approve=False, rc=3)
    [n] = [n for n in out["next"] if "--post-boot" in n]
    rel = n.split('--config "')[1].split('"')[0]
    assert os.path.isabs(rel)
    assert os.path.realpath(rel) == os.path.realpath(host.tmp / "rel-knob")


def test_a_chain_without_config_names_the_runs_copy(chain_host):
    host = chain_host
    text = host.knob_path.read_text()
    copy = host.run_dir / "knob-0123456789ab"
    copy.write_text(text)
    tracked = host.tmp / ".skills" / "patching-hosts"
    tracked.parent.mkdir()
    tracked.write_text(text)
    host.cases["date"] = [("+%s", f"{host.clock}\n", 0, "", None)]
    cmd = ["bash", str(host.scripts / "reboot-chain.sh"), "--run", str(host.run_dir)]
    cmd += ["--host", "web-1", "--today", "2026-09-29"]
    host.execute(cmd, 3)
    out = json.loads(host.result.stdout)
    [n] = [n for n in out["next"] if "not the run's copy" in n]
    assert str(copy) in n


# --- the reader: a knob only root can read ----------------------------------------


def _root_only(tmp_path: Path, knob: str | None) -> tuple[Path, Path]:
    """A run directory only root may enter, and a sudo that enters it."""
    run = tmp_path / "run"
    run.mkdir()
    k = run / "knob-0123456789ab"
    if knob is not None:
        k.write_text(knob)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    sudo = bin_ / "sudo"
    sudo.write_text(
        "#!/bin/sh\n"
        'while [ "$1" = -n ] || [ "$1" = -- ]; do shift; done\n'
        f'chmod 700 "{run}"; "$@"; rc=$?; chmod 000 "{run}"; exit $rc\n'
    )
    sudo.chmod(0o755)
    run.chmod(0)
    return k, bin_


@pytest.fixture
def unroot():
    if os.geteuid() == 0:
        pytest.skip("root enters a mode-000 directory")
    dirs: list[Path] = []
    yield dirs
    for d in dirs:
        d.chmod(0o700)


def _sudo_path(bin_: Path) -> str:
    return f"{bin_}:{_clean_env()['PATH']}"


@pytest.mark.parametrize("where", ["in-it", "two-below", "symlink"])
def test_a_knob_out_of_the_callers_sight_is_read_through_sudo(tmp_path, unroot, where):
    # CR 2798: a path two levels below the directory it can't enter, and a
    # symlink into it, are out of sight too, not absent.
    k, bin_ = _root_only(tmp_path, None)
    unroot.append(k.parent)
    k.parent.chmod(0o700)
    if where == "two-below":
        (k.parent / "sub").mkdir()
        k = k.parent / "sub" / "knob"
    k.write_text(KNOB)
    if where == "two-below":
        k.parent.parent.chmod(0)
    else:
        k.parent.chmod(0)
    given = k
    if where == "symlink":
        given = tmp_path / "link"
        given.symlink_to(k)
    r = _read_knob(str(given), PATH=_sudo_path(bin_))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["knob"] == {"path": str(given), "present": True}
    assert out["posture"]["value"] == "scheduled"
    # Nothing is staged in a shared directory (CR 2802).
    assert not list(tmp_path.glob("knob.*"))


@pytest.mark.parametrize("where", ["in-it", "two-below", "symlink"])
def test_a_knob_root_finds_no_file_at_is_an_error_not_the_defaults(
    tmp_path, unroot, where
):
    # CR 2798: an absent knob reads as the defaults; one the caller can't
    # see, and root can't find, is a path that's wrong.
    k, bin_ = _root_only(tmp_path, None)
    unroot.append(k.parent)
    given = k
    if where == "two-below":
        given = k.parent / "sub" / "knob"
    elif where == "symlink":
        given = tmp_path / "link"
        given.symlink_to(k)
    r = _read_knob(str(given), PATH=_sudo_path(bin_))
    assert r.returncode == 2
    assert r.stdout == ""
    assert "isn't there, even to root" in r.stderr


def test_a_knob_the_caller_sees_is_absent_still_reads_as_the_defaults(tmp_path):
    # The documented no-knob case, unchanged: no sudo is asked.
    r = _read_knob(str(tmp_path / "absent"), PATH="/usr/bin:/bin")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["knob"]["present"] is False


@pytest.mark.parametrize(
    "how, why",
    [
        ("sudo-refuses", "sudo -n couldn't read it: it asks for a password"),
        ("no-sudo", "--no-sudo (P_NO_SUDO=1) keeps it from being read as root"),
    ],
)
def test_a_root_only_knob_sudo_cant_read_is_an_error_not_the_defaults(
    tmp_path, unroot, how, why
):
    k, bin_ = _root_only(tmp_path, KNOB)
    unroot.append(k.parent)
    env = {"PATH": _sudo_path(bin_)}
    if how == "no-sudo":
        env["P_NO_SUDO"] = "1"
    else:
        (bin_ / "sudo").write_text(
            "#!/bin/sh\necho 'sudo: a password is required' >&2\nexit 1\n"
        )
    r = _read_knob(str(k), **env)
    assert r.returncode == 2
    assert r.stdout == ""
    assert why in r.stderr
    if how == "no-sudo":
        assert "sudo -n couldn't" not in r.stderr
