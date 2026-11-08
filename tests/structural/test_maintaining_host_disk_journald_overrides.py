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

import os
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


def install(tmp_path, root, *extra, files=None, env=None):
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
        env=env,
    )
    return result


def out_of(result, code=0):
    assert result.returncode == code, (result.returncode, result.stdout, result.stderr)
    return rig.stdout_json(result)


DANGLING = "-> /nonexistent"


def put(root, rel, text):
    """A file, a link to /dev/null (None), or a dangling link (DANGLING)."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if text is None:
        p.symlink_to("/dev/null")
    elif text == DANGLING:
        p.symlink_to("/nonexistent")
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
    # CR 1953 (M1): a host file in /usr/lib under the layer's own name is
    # read now, and masked once the layer lands: read only before.
    (
        {f"usr/lib/{JD}/{LAYER}": cap("200M")},
        [entry(f"/usr/lib/{JD}/{LAYER}", "200M", "200M", "512M")],
    ),
    # CR 1953 (M2): a control character in a value is shown as ?, so the
    # report stays JSON; journald can't parse "200M\x01", so it's ignored.
    (
        {f"etc/{JD}/zzz-x.conf": "[Journal]\nSystemMaxUse=200M\x01\n"},
        [entry(f"/etc/{JD}/zzz-x.conf", "200M?", None, "512M")],
    ),
    # CR 1952: so is one in a file name, which is reported, not dropped.
    (
        {f"etc/{JD}/10-\x01x.conf": cap("200M")},
        [entry(f"/etc/{JD}/10-?x.conf", "200M", "200M", "512M")],
    ),
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
    "usr-lib-layer-name",
    "control-char-value",
    "control-char-name",
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


# --- what journald ignores (CR 1951) -------------------------------------------
# journald drops a size it can't parse ("Failed to parse size value,
# ignoring") and keeps the value before it, on 249 and 255 alike: measured by
# running systemd-journald with each value in a zzz- file after the layer's
# 512M, and reading the max it took. parse_size, base 1024: digits, an
# optional fraction, optional whitespace, then E, P, T, G, M, K or B, in
# components whose units fall, a bare number only last.

ACCEPTED = ["200 M", "1.5G", "300", "0", "+300M", "1G 512M", "1G512M", "5.G"]
ACCEPTED += ["1.5", "300B", "300K", "1G 300"]
REJECTED = ["", "200 MB please", "10%", "300m", "300MiB", "infinity", "-300M"]
REJECTED += [".5G", "300M#x", "512M1G", "300 300", "1G 1G", "300 1G", "+ 300M"]


@pytest.mark.usefixtures("linux_tools")
@pytest.mark.parametrize("value", ACCEPTED)
def test_a_size_journald_parses_wins(tmp_path, host, value):
    put(host, f"etc/{JD}/zzz-x.conf", cap(value))
    out = out_of(install(tmp_path, host))
    assert out["journald_overrides"] == [
        entry(f"/etc/{JD}/zzz-x.conf", value, value, value)
    ]


@pytest.mark.usefixtures("linux_tools")
@pytest.mark.parametrize("value", REJECTED)
def test_a_size_journald_ignores_leaves_the_layers(tmp_path, host, value):
    # Listed with what it says, and the layer's 512M after: the raise this
    # issue is about, said on stderr too.
    put(host, f"etc/{JD}/zzz-x.conf", cap(value))
    result = install(tmp_path, host)
    out = out_of(result)
    assert out["journald_overrides"] == [
        entry(f"/etc/{JD}/zzz-x.conf", value, None, "512M")
    ]
    assert f"/etc/{JD}/zzz-x.conf" in result.stderr
    # CR 1965: and the note says why the layer's value stays.
    assert "can't parse" in result.stderr, result.stderr


@pytest.mark.usefixtures("linux_tools")
def test_cr_1965_a_layer_value_journald_ignores_is_no_layer_key(tmp_path, host):
    # The layer's own SystemMaxUse= is empty: journald ignores it, so the
    # layer sets nothing a host file could meet.
    put(host, f"etc/{JD}/10-x.conf", cap("200M"))
    files = rig.gc_files(zz_cannobserv_journal_conf=b"[Journal]\nSystemMaxUse=\n")
    staging = rig.stage(tmp_path / "staging-e", files)
    scripts = rig.pinned_scripts(tmp_path / "scripts-e", staging)
    out = out_of(rig.run(scripts / INSTALL.name, "--staging", staging, "--root", host))
    assert out["journald_overrides"] == []


@pytest.mark.usefixtures("linux_tools")
def test_an_ignored_value_keeps_the_one_before_it_in_the_same_file(tmp_path, host):
    put(host, f"etc/{JD}/zzz-x.conf", "[Journal]\nSystemMaxUse=200M\nSystemMaxUse=\n")
    out = out_of(install(tmp_path, host))
    assert out["journald_overrides"] == [
        entry(f"/etc/{JD}/zzz-x.conf", "200M", "200M", "200M")
    ]


# --- names and renames (CR 1952, CR 1953) ----------------------------------------


@pytest.mark.usefixtures("linux_tools")
@pytest.mark.parametrize(
    "name, shown, after",
    [
        ("10-a\nb.conf", "10-a?b.conf", "512M"),
        ("10-a\tb.conf", "10-a?b.conf", "512M"),
        # A tab name sorting after the layer's is in the merge too.
        ("zzz\tx.conf", "zzz?x.conf", "200M"),
    ],
    ids=["newline", "tab", "tab-sorts-after"],
)
def test_cr_1966_a_tab_or_newline_name_is_merged_and_reported(
    tmp_path, host, name, shown, after
):
    # journald reads it, so it's sorted with the rest, not passed over.
    put(host, f"etc/{JD}/{name}", cap("200M"))
    out = out_of(install(tmp_path, host))
    assert out["journald_overrides"] == [
        entry(f"/etc/{JD}/{shown}", "200M", "200M", after)
    ]


def _has_locale(name):
    try:
        listed = subprocess.run(["locale", "-a"], capture_output=True, text=True).stdout
    except OSError:
        return False
    want = name.lower().replace("-", "")
    return want in {line.lower().replace("-", "") for line in listed.split()}


@pytest.mark.usefixtures("linux_tools")
@pytest.mark.parametrize("locale", ["C", "C.UTF-8"])
def test_cr_1966_bytes_that_arent_printable_ascii_show_as_question_marks(
    tmp_path, host, locale
):
    # Neither a name nor a value may make stdout invalid UTF-8. CR 1976: a
    # ? per byte whatever the host's locale; in C.UTF-8 a bracket range is
    # by character, so "é" would be one ? without printable's own LC_ALL=C.
    if locale != "C" and not _has_locale(locale):
        pytest.skip(f"no {locale} locale here")
    d = host / "etc" / JD
    d.mkdir(parents=True, exist_ok=True)
    with open(os.path.join(os.fsencode(d), b"10-\xffx.conf"), "wb") as f:
        f.write(cap("200M").encode())
    (d / "zzz-y.conf").write_bytes(b"[Journal]\nSystemMaxUse=200M\xc3\xa9\n")
    out = out_of(install(tmp_path, host, env={"LC_ALL": locale}))
    assert out["journald_overrides"] == [
        entry(f"/etc/{JD}/10-?x.conf", "200M", "200M", "512M"),
        entry(f"/etc/{JD}/zzz-y.conf", "200M??", "200M", "512M"),
    ]


@pytest.mark.usefixtures("linux_tools")
def test_a_drop_in_the_update_renames_masks_nothing_once_gone(tmp_path, host):
    """CR 1953 (M3): the new MANIFEST renames the layer's drop-in. The old
    name's file goes with the run, so it no longer masks the host's
    /usr/lib file of that name, which then sorts after the new one."""
    out_of(install(tmp_path, host, "--approve"))
    put(host, f"usr/lib/{JD}/{LAYER}", cap("200M"))
    files = rig.gc_files(version=3)
    files[f"usr/local/lib/{JD}/yy-cannobserv-journal.conf"] = files.pop(rig.JOURNALD)
    out = out_of(install(tmp_path, host, files=files))
    assert out["action"] == "update" and out["removed"] == [rig.JOURNALD]
    assert out["journald_overrides"] == [
        entry(f"/usr/lib/{JD}/{LAYER}", "200M", "512M", "200M")
    ]


# --- systemd's own reading, where it's there ----------------------------------


@pytest.mark.usefixtures("linux_tools")
@pytest.mark.parametrize("files, want", CASES[:7], ids=IDS[:7])
def test_after_is_what_systemd_analyze_reads(tmp_path, host, files, want):
    """The oracle: `systemd-analyze cat-config` on the installed root ends at
    the value `after` says. Skips where there is no systemd-analyze (macOS).

    Only for these cases: cat-config lists a main file outside /etc that
    journald never reads, and prints a value journald ignores as written
    (CR 1950, CR 1951), so it can't check either; the cases above can."""
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


def _help(script):
    return subprocess.run(
        ["bash", str(rig.SCRIPTS / script), "--help"], capture_output=True, text=True
    ).stdout


def test_cr_1963_the_docs_scope_the_main_file_rule_to_systemds_version():
    # CR 1950 measured 249 and 255; 256, 257 and 259 read the first of the
    # four directories, as cat-config does.
    usage = " ".join(_help(INSTALL.name).split())
    assert "systemd 255 and older" in usage, usage
    assert "256 and newer" in usage, usage
    text = VERIFYING.read_text()
    section = text.split("## After an install or update", 1)[1].split("\n## ", 1)[0]
    flat = " ".join(section.split())
    assert "the last `SystemMaxUse=` is the cap in effect" not in flat, flat
    assert "systemd 255 and older" in flat, flat
    assert "256 and newer" in flat, flat
    assert "can't parse" in flat, flat


# --- the main file, by systemd's version (CR 1963) -------------------------------
# Measured by running systemd-journald: 249 (ubuntu:22.04) and 255 (24.04)
# read the main file from /etc only; 256 (fedora:41), 257 (ubuntu:25.10) and
# 259 (26.04) read the first of /etc, /run, /usr/local/lib and /usr/lib, an
# /etc link to /dev/null masking the rest. The version is the root's dpkg
# database's.


def systemd_version(root, version, status="install ok installed"):
    d = root / "var/lib/dpkg"
    d.mkdir(parents=True, exist_ok=True)
    (d / "status").write_text(
        f"Package: systemd\nStatus: {status}\nVersion: {version}\n"
        "Architecture: amd64\nMaintainer: x\nDescription: x\n"
    )


MAIN = "systemd/journald.conf"
OLD, NEW = "255.4-1ubuntu8.18", "259.9-0ubuntu0.1"
VERSIONED = [
    (OLD, {f"usr/lib/{MAIN}": cap("200M")}, []),
    (OLD, {f"run/{MAIN}": cap("200M")}, []),
    (
        "256.17-1",
        {f"usr/lib/{MAIN}": cap("200M")},
        [entry(f"/usr/lib/{MAIN}", "200M", "200M", "512M")],
    ),
    # The reviewer's case: 259, a /run main file at 200M, the layer's 512M.
    (
        NEW,
        {f"run/{MAIN}": cap("200M")},
        [entry(f"/run/{MAIN}", "200M", "200M", "512M")],
    ),
    # /etc's masks the rest, a link to /dev/null with nothing.
    (NEW, {f"etc/{MAIN}": None, f"usr/lib/{MAIN}": cap("200M")}, []),
    (
        NEW,
        {f"etc/{MAIN}": cap("300M"), f"run/{MAIN}": cap("200M")},
        [entry(f"/etc/{MAIN}", "300M", "300M", "512M")],
    ),
]
VERSIONED += [
    # CR 1975: from 256, journald skips a dangling link at a main file and
    # reads on (measured on 257 and 259); a link to /dev/null, a directory
    # or an empty file stops it. On 255 and older, /etc's only: nothing.
    (
        NEW,
        {f"etc/{MAIN}": DANGLING, f"usr/lib/{MAIN}": cap("200M")},
        [entry(f"/usr/lib/{MAIN}", "200M", "200M", "512M")],
    ),
    (
        NEW,
        {f"run/{MAIN}": DANGLING, f"usr/lib/{MAIN}": cap("200M")},
        [entry(f"/usr/lib/{MAIN}", "200M", "200M", "512M")],
    ),
    (OLD, {f"etc/{MAIN}": DANGLING, f"usr/lib/{MAIN}": cap("200M")}, []),
]
VERSIONED_IDS = [
    "255-usr-lib",
    "255-run",
    "256-usr-lib",
    "259-run",
    "259-etc-null-masks",
    "259-etc-masks-run",
    "259-etc-dangling",
    "259-run-dangling",
    "255-etc-dangling",
]


@pytest.mark.usefixtures("linux_tools")
@pytest.mark.parametrize("version, files, want", VERSIONED, ids=VERSIONED_IDS)
def test_cr_1963_the_main_file_is_read_as_the_hosts_systemd_reads_it(
    tmp_path, host, version, files, want
):
    if shutil.which("dpkg-query") is None:
        pytest.skip("needs dpkg-query (a Debian or Ubuntu host)")
    systemd_version(host, version)
    for rel, text in files.items():
        put(host, rel, text)
    result = install(tmp_path, host)
    assert out_of(result)["journald_overrides"] == want
    assert "systemd's version" not in result.stderr


@pytest.mark.usefixtures("linux_tools")
@pytest.mark.parametrize(
    "installed, etc",
    [(False, False), (True, False), (False, True)],
    ids=["no-dpkg", "config-files", "etc-dangling"],
)
def test_cr_1963_an_unreadable_version_reads_as_256_and_says_so(
    tmp_path, host, installed, etc
):
    # It reports more: a main file the newer rule reads and the older doesn't.
    # A dangling /etc link is no main file there (CR 1975).
    if installed:
        systemd_version(host, "259.1", status="deinstall ok config-files")
    if etc:
        put(host, f"etc/{MAIN}", DANGLING)
    put(host, f"usr/lib/{MAIN}", cap("200M"))
    result = install(tmp_path, host)
    assert out_of(result)["journald_overrides"] == [
        entry(f"/usr/lib/{MAIN}", "200M", "200M", "512M")
    ]
    assert "systemd's version" in result.stderr, result.stderr


def test_cr_1954_the_remove_usage_keeps_the_files_wrap():
    wide = [line for line in _help("remove-disk-gc.sh").splitlines() if len(line) > 77]
    assert not wide, wide


@pytest.mark.usefixtures("linux_tools")
def test_cr_1977_an_unreadable_version_is_quiet_when_etc_has_the_main_file(
    tmp_path, host
):
    # Both rules read /etc's then, so there's nothing to say.
    put(host, f"etc/{MAIN}", cap("300M"))
    put(host, f"usr/lib/{MAIN}", cap("200M"))
    result = install(tmp_path, host)
    assert out_of(result)["journald_overrides"] == [
        entry(f"/etc/{MAIN}", "300M", "300M", "512M")
    ]
    assert "systemd's version" not in result.stderr, result.stderr
