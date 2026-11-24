"""patching-hosts: the redaction by name's bounds (#707, CR 2814, CR 2815).

live_args and the backup log share _probe-lib.sh's redaction, and a word
they read can be as long as an argv or a journal entry allows. The
redaction reads it in one loop, never by recursion, so a word of thousands
of values can't overflow bash's stack, and jumps from quote to quote, so a
long value is scanned in linear time. Both run the library directly, under
LC_ALL=C as probe.sh and recovery-point.sh do.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time

from tests.structural.patching_hosts_rig import SKILL, clean_env

LIB = SKILL / "scripts" / "_probe-lib.sh"


def _redact(*words: str) -> tuple[str, float]:
    # The words go through a file, NUL-separated: Linux takes no single
    # argument or environment string over 128 KB.
    with tempfile.NamedTemporaryFile("wb", delete=False) as f:
        f.write(b"".join(w.encode() + b"\0" for w in words))
    body = (
        f'. "{LIB}"; a=(); while IFS= read -r -d "" w; do a+=("$w"); done < "{f.name}"; '
        'RW_QUOTE=""; redact_words o "${a[@]}"; printf %s "$o"'
    )
    start = time.monotonic()
    try:
        r = subprocess.run(
            ["bash", "-c", body],
            capture_output=True,
            text=True,
            env={**clean_env(), "LC_ALL": "C"},
            check=True,
            timeout=120,
        )
    finally:
        os.unlink(f.name)
    return r.stdout, time.monotonic() - start


def test_a_word_of_thousands_of_values_is_read_in_a_loop():
    # CR 2814: each value's closing quote and ; started a recursive call, and
    # 2000 of them in one word overflowed bash 5.2's stack (rc 139). Past
    # QS_MAX the rest of the line is dropped, marked (CR 2835).
    out, took = _redact("+", "X_TOKEN='zq9';" * 2500, "done")
    assert out == "+ X_TOKEN=<redacted> <...>"
    assert took < 10


def test_a_long_or_quote_dense_value_is_dropped_not_scanned():
    # CR 2815, CR 2835: the scan copied the rest of its text per character,
    # then per quote: 128 KB of a'b' took 40 s. A value past QS_MAX, or a
    # line past RS_SCAN_MAX scanned, drops the rest of the line, marked.
    long = "a" * 128000
    dense = "a'b'" * 32000
    for words, shown in [
        (
            ["run", "--password", f"'{long}", f"{long}'", "--region", "us"],
            "run --password <redacted> <...>",
        ),
        (["+", f'X_TOKEN="{long}\\"{long}"', "next"], "+ X_TOKEN=<redacted> <...>"),
        ([f"--password={dense}", "after"], "--password=<redacted> <...>"),
        (
            ["run", "--password", "'x", *["a'b'" * 1000] * 500, "end"],
            "run --password <redacted> <...>",
        ),
        (["ok", "--password", "'x", "y'", "shown"], "ok --password <redacted> shown"),
    ]:
        out, took = _redact(*words)
        assert out == shown
        assert took < 10


def test_a_query_as_long_as_an_argument_may_be_is_redacted_quickly():
    # CR 2841: each parameter captured the rest of the URL, and a # strip of
    # a long prefix copied it again: 40 KB took 14.7 s. Each still copies
    # the rest, so it's bounded instead: an argv element by ARGS_MAX (16 KB),
    # a log line by BJ_TAKE (2000 bytes).
    env = {**clean_env(), "LC_ALL": "C"}
    url = "https://h/?" + "a=1&" * 4000 + "token=zq9"
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write(url)
    start = time.monotonic()
    try:
        r = subprocess.run(
            [
                "bash",
                "-c",
                f'. "{LIB}"; u=$(cat "{f.name}"); redact_url o "$u"; printf %s "$o"',
            ],
            capture_output=True,
            text=True,
            env=env,
            check=True,
            timeout=120,
        )
    finally:
        os.unlink(f.name)
    assert time.monotonic() - start < 5
    assert r.stdout.endswith("&token=<redacted>")
