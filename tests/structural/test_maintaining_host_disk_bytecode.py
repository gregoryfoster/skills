"""#514 — loading the staged GC with Python leaves bytecode the installer refuses.

`disk-gc` has no extension, so loading it with `SourceFileLoader` (to call its
`load_config` on a host's config before installing, say) writes
`__pycache__/disk-gc…pyc` beside it: bytecode writing is on by default, and
`-I` doesn't turn it off. `install-disk-gc.sh` then refuses the staging tree,
as it should, but said only "staging holds files MANIFEST doesn't list", with
no word on where the file came from or how to recover (CannObserv/processor#82).

The refusal stays a refusal. When every unlisted file is under `__pycache__/`,
it now says so and names the recovery: re-pull into a fresh directory, never
edit staging. The docs say not to run or import from staging at all, how to
load the GC with bytecode off, and that a repo test loading the installed GC
does the same, since as root it would add a file MANIFEST doesn't list.
"""

import subprocess
import sys

import pytest

from tests.structural import maintaining_host_disk_rig as rig

from .test_maintaining_host_disk_install import install, refused, staged

pytestmark = pytest.mark.usefixtures("linux_tools")

BYTECODE = "bytecode"
PYC = "__pycache__/disk-gccpython-312.pyc"  # the name processor#82 saw


@pytest.fixture
def linux_tools():
    rig.require_linux_tools()


@pytest.fixture
def host(tmp_path):
    return rig.make_host(tmp_path / "root")


def _load(path, *python_flags):
    """What processor#82's thread did: load the extensionless GC as a module."""
    code = (
        "import importlib.machinery as m, importlib.util as u, sys\n"
        "loader = m.SourceFileLoader('disk_gc', sys.argv[1])\n"
        "spec = u.spec_from_loader('disk_gc', loader)\n"
        "loader.exec_module(u.module_from_spec(spec))\n"
    )
    r = subprocess.run(
        [sys.executable, *python_flags, "-c", code, str(path)],
        capture_output=True,
        text=True,
        env=rig.clean_env(None),
        timeout=60,
    )
    assert r.returncode == 0, r.stderr


class TestTheRefusalNamesTheBytecode:
    def test_a_loaded_staging_tree_is_refused_with_its_recovery(self, tmp_path, host):
        staging = staged(tmp_path)
        _load(staging / rig.GC_DIR / "disk-gc")
        assert list((staging / rig.GC_DIR / "__pycache__").iterdir()), (
            "the load wrote no bytecode, so this test reproduces nothing"
        )
        result, stub = install(tmp_path, host, staging, "--approve")
        out = refused(result, "__pycache__/")
        why = next(r for r in out["refused"] if "__pycache__/" in r)
        assert BYTECODE in why, why
        assert "re-pull" in why and "fresh directory" in why, why
        assert not (host / "usr").exists()
        assert rig.calls(stub) == []

    def test_only_bytecode_is_still_refused(self, tmp_path, host):
        staging = staged(tmp_path)
        pyc = staging / rig.GC_DIR / PYC
        pyc.parent.mkdir()
        pyc.parent.chmod(0o755)
        pyc.write_bytes(b"\x00")
        pyc.chmod(0o644)
        result, _ = install(tmp_path, host, staging)
        why = refused(result, PYC)["refused"]
        assert any(BYTECODE in r for r in why), why

    def test_bytecode_beside_another_stray_gets_the_plain_refusal(self, tmp_path, host):
        """The hint is for the one known cause. A stray that isn't bytecode
        means something else wrote into staging, so no hint names a cause."""
        staging = staged(tmp_path)
        pyc = staging / rig.GC_DIR / PYC
        pyc.parent.mkdir()
        pyc.parent.chmod(0o755)
        pyc.write_bytes(b"\x00")
        pyc.chmod(0o644)
        (staging / rig.GC_DIR / "stowaway").write_text("x")
        result, _ = install(tmp_path, host, staging)
        why = refused(result, "stowaway")["refused"]
        assert not any(BYTECODE in r for r in why), why

    @pytest.mark.parametrize("flags", [("-B",), ("-I", "-B")])
    def test_a_load_with_bytecode_off_leaves_staging_installable(
        self, tmp_path, host, flags
    ):
        staging = staged(tmp_path)
        _load(staging / rig.GC_DIR / "disk-gc", *flags)
        assert not (staging / rig.GC_DIR / "__pycache__").exists()
        result, _ = install(tmp_path, host, staging)
        assert result.returncode == 0, result.stdout + result.stderr
        assert rig.stdout_json(result)["action"] == "install"


class TestTheDocsSayIt:
    def test_the_skill_says_never_load_from_staging(self):
        text = (rig.SKILL / "SKILL.md").read_text()
        assert "python3 -B" in text and "PYTHONDONTWRITEBYTECODE" in text, (
            "SKILL.md must name how to load the GC with bytecode off"
        )
        assert "fresh directory" in text, "SKILL.md must name the re-pull"

    def test_a_repo_test_loads_the_installed_gc_with_bytecode_off(self):
        text = (rig.SKILL / "references" / "verifying.md").read_text()
        assert "dont_write_bytecode" in text, text
        assert "__pycache__" in text, text
