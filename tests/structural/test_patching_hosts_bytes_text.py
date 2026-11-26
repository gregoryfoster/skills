"""patching-hosts: recovery-point.sh's bytes_text, in time linear in its input (#710).

journald writes a message as an array of its bytes when it holds a control
byte or invalid UTF-8, and the backup log decodes the array with bytes_text.
It decoded only the first BJ_TAKE bytes, but split the whole array first,
with ${2//,/ }, which bash 3.2 runs in quadratic time: 32 s for 10,000 bytes.
It now splits a prefix of the string, so a message of a megabyte costs what
2,000 bytes do.

The function is read out of the script and run on its own, under LC_ALL=C as
recovery-point.sh runs, with the array passed through a file: Linux takes no
single argument over 128 KB.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile

import pytest

from tests.structural.patching_hosts_rig import SKILL, clean_env

RECOVER = (SKILL / "scripts" / "recovery-point.sh").read_text()
LIB = (SKILL / "scripts" / "_probe-lib.sh").read_text()
BJ_TAKE = int(re.search(r"^BJ_TAKE=(\d+)$", RECOVER, re.M).group(1))


def _function(text: str, name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{.*?^\}}$", text, re.M | re.S)
    assert m, name
    return m.group(0)


FNS = "\n".join(
    [
        _function(LIB, "is_int"),
        f"BJ_TAKE={BJ_TAKE}",
        _function(RECOVER, "name_byte"),
        _function(RECOVER, "bytes_text"),
    ]
)


def _decode(array: str, timeout: float = 20) -> str:
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write(array)
    try:
        r = subprocess.run(
            [
                "bash",
                "-c",
                f'{FNS}\nbytes_text o "$(cat "$1")"; printf %s "$o"',
                "-",
                f.name,
            ],
            capture_output=True,
            text=True,
            env={**clean_env(), "LC_ALL": "C"},
            check=True,
            timeout=timeout,
        )
    finally:
        os.unlink(f.name)
    return r.stdout


def _csv(data: bytes) -> str:
    return ",".join(str(b) for b in data)


def test_bj_take_is_the_cap_the_string_form_takes_too():
    assert BJ_TAKE == 2000
    assert "_bj_m=${_bj_m:0:$BJ_TAKE}" in RECOVER


def test_a_megabyte_message_is_decoded_in_seconds_not_hours():
    # #710: 5 KB took 6.1 s and 10 KB 45 s on bash 3.2, and 2 MB over 60 s
    # on bash 5.2. Every value past the cap is dropped, so a megabyte costs
    # about what the cap does. The timeout leaves room for a loaded host.
    data = (
        b"rclone copy --s3-secret-access-key zq9SEKRET \x1b[1mdone\x1b[0m " * 20000
    )[:1_000_000]
    # The cap falls inside a word ("acce|ss"), clear of a sequence.
    want = data[:BJ_TAKE].decode().replace("\x1b[1m", " ").replace("\x1b[0m", " ")
    assert want.endswith("secret-acce")
    assert _decode(_csv(data)) == want


@pytest.mark.parametrize(
    "data, shown",
    [
        # A CSI the cap cuts ends there: its parameter and final, past the
        # cap, are never read as text.
        (b"a" * 1998 + b"\x1b[" + b"1mpassword=zq9", "a" * 1998 + " "),
        (b"a" * 1997 + b"\x1b[1" + b"mX", "a" * 1997 + " "),
        (b"a" * 1999 + b"\x1b" + b"[1m", "a" * 1999 + " "),
        # A final at the cap is taken or read as text by the byte after it,
        # the one byte past the cap that's ever read.
        (b"a" * 1997 + b"\x1b[m" + b"password", "a" * 1997 + " m"),
        (b"a" * 1997 + b"\x1b[m" + b" password", "a" * 1997 + " "),
        # Nothing past the cap is appended, so the cut can't join two words.
        (b"a" * 1993 + b" --pass" + b"word zq9", "a" * 1993 + " --pass"),
        (b"a" * 1999 + b" " + b"x", "a" * 1999 + " "),
    ],
    ids=[
        "esc-bracket-at-the-cap",
        "a-parameter-at-the-cap",
        "esc-at-the-cap",
        "final-before-a-letter",
        "final-before-a-space",
        "a-name-cut-in-two",
        "a-space-at-the-cap",
    ],
)
def test_the_cut_at_the_cap_never_shows_or_joins_what_follows(data, shown):
    assert _decode(_csv(data)) == shown


def test_values_split_as_the_whole_array_did():
    # BJ_BIN allows any space between values, and a byte that isn't a
    # number reads as a space, as with ${2//,/ }: an empty field is
    # dropped, and read stops at a line break.
    assert _decode("65, 66,\t67,,x,68 ,  ,69,") == "ABC DE"
    assert _decode(",65 ,66") == "AB"
    assert _decode("65,66\n,67") == "AB"
    assert _decode("") == ""


def test_space_between_values_grows_the_prefix_not_the_cost():
    # Values padded past the first prefix are still read up to the cap,
    # and one past it.
    out = _decode(",          ".join(["120"] * (BJ_TAKE + 5)), timeout=60)
    assert out == "x" * BJ_TAKE
    assert (
        _decode(",   ".join(["97"] * 1997 + ["27", "91", "109", "112"]))
        == "a" * 1997 + " m"
    )
