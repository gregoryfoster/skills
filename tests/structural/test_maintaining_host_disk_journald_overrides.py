"""#604 — the install says when the layer's journald drop-in outranks a host's own.

The layer ships `zz-cannobserv-journal.conf` (`SystemMaxUse=512M`) under
/usr/local/lib. journald reads its main file, then every
`journald.conf.d/*.conf` across /etc, /run, /usr/local/lib and /usr/lib by
file name: a name in a higher directory masks the same name lower down (a
link to /dev/null masks it with nothing), and among different names the later
one in sort order wins each key. So a host's own `10-x.conf` in /etc, or its
main file, capped lower, is raised by the install, which said nothing on
CannObserv/usa-wa#508. Only a file of the layer's own name in a higher
directory, or one sorting after it, keeps the host's value. That is the rule
patching-hosts' read_journal learned in #515, tested the same way here.

`install-disk-gc.sh` reports each host file that sets a key the layer sets,
in plan mode and on `--approve`, as `journald_overrides`, with the value in
effect before and after. It never refuses: a lower cap is the host's call.
"""

import re
import shutil
import subprocess

import pytest

from tests.structural import maintaining_host_disk_rig as rig

INSTALL = rig.SCRIPTS / "install-disk-gc.sh"
JD = "systemd/journald.conf.d"
LAYER = rig.JOURNALD.rsplit("/", 1)[1]
SKILL_MD = rig.SKILL / "SKILL.md"
VERIFYING = rig.SKILL / "references" / "verifying.md"


@pytest.fixture
def linux_tools():
    rig.require_linux_tools()


@pytest.fixture
def host(tmp_path):
    return rig.make_host(tmp_path / "root")


def install(tmp_path, root, *extra, files=None):
    staging = rig.stage(
        tmp_path / f"staging-{len(list(tmp_path.glob('staging-*')))}", files
    )
    copies = sorted(tmp_path.glob("scripts-*"))
    scripts = rig.pinned_scripts(tmp_path / f"scripts-{len(copies)}", staging)
    stub = rig.stub_systemctl(tmp_path / "bin")
    result = rig.run(
        scripts / INSTALL.name,
        "--staging",
        staging,
        "--root",
        root,
        "--systemctl",
        stub,
        *extra,
    )
    return result


def out_of(result, code=0):
    assert result.returncode == code, (result.returncode, result.stdout, result.stderr)
    return rig.stdout_json(result)


def put(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if text is None:
        p.symlink_to("/dev/null")
    else:
        p.write_text(text)


def cap(value, key="SystemMaxUse"):
    return f"[Journal]\n{key}={value}\n"


def entry(file, host, before, after, key="SystemMaxUse", layer="512M"):
    return {
        "file": file,
        "key": key,
        "host": host,
        "layer": layer,
        "before": before,
        "after": after,
    }


# --- merge-by-name, on a fresh install's plan ---------------------------------

CASES = [
    # usa-wa#508: a lower cap under a name sorting before zz- is raised.
    (
        {f"etc/{JD}/10-x.conf": cap("200M")},
        [entry(f"/etc/{JD}/10-x.conf", "200M", "200M", "512M")],
    ),
    # The main file is read before every drop-in, whatever its name.
    (
        {"etc/systemd/journald.conf": cap("200M")},
        [entry("/etc/systemd/journald.conf", "200M", "200M", "512M")],
    ),
    # /run's drop-ins merge by name the same way.
    (
        {f"run/{JD}/40-x.conf": cap("300M")},
        [entry(f"/run/{JD}/40-x.conf", "300M", "300M", "512M")],
    ),
    # The layer's own name in /etc masks its file outright: the layer's
    # value never applies, so it's listed with the host's value after.
    (
        {f"etc/{JD}/{LAYER}": cap("200M")},
        [entry(f"/etc/{JD}/{LAYER}", "200M", "200M", "200M")],
    ),
    # A name sorting after the layer's keeps its value.
    (
        {f"etc/{JD}/zzz-x.conf": cap("200M")},
        [entry(f"/etc/{JD}/zzz-x.conf", "200M", "200M", "200M")],
    ),
    # A link to /dev/null under the layer's name masks it with nothing, so
    # the host's 10-x.conf still applies after.
    (
        {f"etc/{JD}/{LAYER}": None, f"etc/{JD}/10-x.conf": cap("200M")},
        [entry(f"/etc/{JD}/10-x.conf", "200M", "200M", "200M")],
    ),
    # /etc's 10-x.conf masks /usr/lib's: the masked file is never read, so
    # it isn't listed.
    (
        {
            f"usr/lib/{JD}/10-x.conf": cap("999M"),
            f"etc/{JD}/10-x.conf": cap("200M"),
        },
        [entry(f"/etc/{JD}/10-x.conf", "200M", "200M", "512M")],
    ),
    # A key the layer doesn't set is the host's alone.
    ({f"etc/{JD}/10-x.conf": cap("1week", "MaxRetentionSec")}, []),
    # Only [Journal] counts, comments don't, and whitespace around = goes.
    (
        {
            f"etc/{JD}/10-x.conf": (
                "[Journal]\n#SystemMaxUse=1G\n  SystemMaxUse = 200M  \n"
                "[Other]\nSystemMaxUse=7G\n"
            )
        },
        [entry(f"/etc/{JD}/10-x.conf", "200M", "200M", "512M")],
    ),
    # Nothing of the host's: nothing to list.
    ({}, []),
]
IDS = [
    "lower-name",
    "main-file",
    "run",
    "same-name-masks",
    "sorts-after",
    "masked-by-null",
    "etc-masks-usr-lib",
    "other-key",
    "parsing",
    "none",
]


@pytest.mark.usefixtures("linux_tools")
@pytest.mark.parametrize("files, want", CASES, ids=IDS)
def test_the_plan_lists_each_host_setting_the_layer_meets(tmp_path, host, files, want):
    for rel, text in files.items():
        put(host, rel, text)
    out = out_of(install(tmp_path, host))
    assert out["action"] == "install" and out["applied"] is False
    assert out["journald_overrides"] == want


@pytest.mark.usefixtures("linux_tools")
def test_the_approved_install_reports_it_and_never_refuses(tmp_path, host):
    # A lower cap is a host decision, not an error: the install goes ahead.
    put(host, f"etc/{JD}/10-x.conf", cap("200M"))
    result = install(tmp_path, host, "--approve")
    out = out_of(result)
    assert out["applied"] is True and out["refused"] == []
    assert out["journald_overrides"] == [
        entry(f"/etc/{JD}/10-x.conf", "200M", "200M", "512M")
    ]
    # And it's said on stderr too, where the raise was silent.
    assert f"/etc/{JD}/10-x.conf" in result.stderr and "512M" in result.stderr
    # The host's file is untouched.
    assert (host / f"etc/{JD}/10-x.conf").read_text() == cap("200M")


@pytest.mark.usefixtures("linux_tools")
def test_an_update_reads_the_installed_layer_as_the_layers_not_the_hosts(
    tmp_path, host
):
    # The installed zz- file is the layer's own: never listed as a host's,
    # and the value in effect before is already the layer's.
    out_of(install(tmp_path, host, "--approve"))
    put(host, f"etc/{JD}/10-x.conf", cap("200M"))
    files = rig.gc_files(version=3, zz_cannobserv_journal_conf=cap("1G").encode())
    out = out_of(install(tmp_path, host, files=files))
    assert out["action"] == "update"
    assert out["journald_overrides"] == [
        entry(f"/etc/{JD}/10-x.conf", "200M", "512M", "1G", layer="1G")
    ]


@pytest.mark.usefixtures("linux_tools")
def test_the_layer_file_name_and_keys_come_from_the_staged_manifest(tmp_path, host):
    # Nothing is hard-coded: a layer whose drop-in sets another key is read
    # for that key.
    files = rig.gc_files(
        zz_cannobserv_journal_conf=b"[Journal]\nSystemMaxUse=512M\nMaxRetentionSec=1month\n"
    )
    put(host, f"etc/{JD}/10-x.conf", cap("1week", "MaxRetentionSec"))
    staging = rig.stage(tmp_path / "staging-x", files)
    scripts = rig.pinned_scripts(tmp_path / "scripts-x", staging)
    out = out_of(rig.run(scripts / INSTALL.name, "--staging", staging, "--root", host))
    assert out["journald_overrides"] == [
        entry(
            f"/etc/{JD}/10-x.conf",
            "1week",
            "1week",
            "1month",
            key="MaxRetentionSec",
            layer="1month",
        )
    ]


@pytest.mark.usefixtures("linux_tools")
def test_a_refusal_reads_no_journald_settings(tmp_path, host):
    # Nothing from a refused staging tree is read for the report.
    files = rig.gc_files()
    staging = rig.stage(tmp_path / "staging-r", files)
    scripts = rig.copy_scripts(
        tmp_path / "scripts-r", "https://ghcr.io", "sha256:" + "0" * 64
    )
    (staging / rig.GC_DIR / "VERSION").write_text("x\n")
    out = out_of(
        rig.run(scripts / INSTALL.name, "--staging", staging, "--root", host), 3
    )
    assert out["journald_overrides"] is None


# --- systemd's own reading, where it's there ----------------------------------


@pytest.mark.usefixtures("linux_tools")
@pytest.mark.parametrize("files, want", CASES[:7], ids=IDS[:7])
def test_after_is_what_systemd_analyze_reads(tmp_path, host, files, want):
    """The oracle: `systemd-analyze cat-config` on the installed root ends at
    the value `after` says. Skips where there is no systemd-analyze (macOS)."""
    if shutil.which("systemd-analyze") is None:
        pytest.skip("needs systemd-analyze (a Linux host with systemd)")
    for rel, text in files.items():
        put(host, rel, text)
    out = out_of(install(tmp_path, host, "--approve"))
    read = subprocess.run(
        ["systemd-analyze", f"--root={host}", "cat-config", "systemd/journald.conf"],
        capture_output=True,
        text=True,
    )
    assert read.returncode == 0, read.stderr
    section, last = None, None
    for line in read.stdout.splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line
        elif section == "[Journal]" and re.match(r"SystemMaxUse\s*=", line):
            last = line.split("=", 1)[1].strip()
    afters = {e["after"] for e in out["journald_overrides"]} or {"512M"}
    assert afters == {last}, (read.stdout, out["journald_overrides"])


# --- the docs ------------------------------------------------------------------


def test_the_usage_names_journald_overrides():
    result = subprocess.run(
        ["bash", str(INSTALL), "--help"], capture_output=True, text=True
    )
    assert "journald_overrides" in result.stdout


def _step(text, n):
    return re.search(rf"^{n}\. .*$", text, re.M)[0]


def test_skill_step_2_says_to_read_cat_config_and_how_to_keep_a_lower_cap():
    step = _step(SKILL_MD.read_text(), 2)
    assert "journald_overrides" in step
    assert "systemd-analyze cat-config systemd/journald.conf" in step
    assert f"/etc/{JD}/{LAYER}" in step


def test_verifying_says_to_read_cat_config_and_how_to_keep_a_lower_cap():
    text = VERIFYING.read_text()
    section = text.split("## After an install or update", 1)[1].split("\n## ", 1)[0]
    assert "systemd-analyze cat-config systemd/journald.conf" in section
    assert f"/etc/{JD}/{LAYER}" in section
    assert "journald_overrides" in section


def test_removing_says_a_hosts_mask_survives():
    """remove-disk-gc.sh removes only MANIFEST's files: a host's same-name
    file in /etc stays, and keeps capping."""
    para = re.search(r"^\*\*Removing it:\*\*.*$", SKILL_MD.read_text(), re.M)[0]
    assert LAYER in para
    usage = subprocess.run(
        ["bash", str(rig.SCRIPTS / "remove-disk-gc.sh"), "--help"],
        capture_output=True,
        text=True,
    ).stdout
    assert LAYER in usage
