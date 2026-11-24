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
    # 2000 of them in one word overflowed bash 5.2's stack (rc 139).
    out, _ = _redact("+", "X_TOKEN='zq9';" * 2500, "done")
    assert out == "+ " + "X_TOKEN=<redacted>;" * 2500 + " done"


def test_a_long_value_is_scanned_in_linear_time():
    # CR 2815: a copy of the rest per character took 65 s on 128 KB.
    long = "a" * 128000
    out, took = _redact("run", "--password", f"'{long}", f"{long}'", "--region", "us")
    assert out == "run --password <redacted> --region us"
    assert took < 10
    out, took = _redact("+", f'X_TOKEN="{long}\\"{long}"', "next")
    assert out == "+ X_TOKEN=<redacted> next"
    assert took < 10
