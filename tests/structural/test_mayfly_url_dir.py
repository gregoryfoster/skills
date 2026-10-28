"""#509 — every Mayfly channel URL file lives in `~/.mayfly/`, nowhere else.

`using-mayfly-chat` used to let the agent put the URL file in the harness
scratchpad. That path is long and specific to one session, so the operator
copied it out of a status message to relay the URL, and a second channel in
the same session got a second, near-identical path (CannObserv/status#67).
Scratchpads also outlive their session where nobody looks. With every file in
one directory, a leftover takes one `ls` to find.

Two halves:

- **The skill offers no alternative.** SKILL.md never mentions a scratchpad,
  and every `MAYFLY_URL_FILE=` it shows, and the wrapper's usage, names
  `$HOME/.mayfly/`.
- **`mayfly.sh create` warns without refusing.** After a successful `create`
  whose file is outside `$HOME/.mayfly/`, the wrapper adds a warning on stderr
  and keeps exit 0. A file inside gets no warning. A failed `create` leaves
  stderr as the client's one JSON object, because callers parse it.

The `create` here runs against a loopback stub that answers `POST /new` with
the 303 the real service sends. The URL it mints lives only in a mode-600 file
under `tmp_path` that this file never reads (`test_no_channel_urls.py`).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "using-mayfly-chat"
SKILL_MD = SKILL_DIR / "SKILL.md"
WRAPPER = SKILL_DIR / "scripts" / "mayfly.sh"

requires_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is required to run the vendored Mayfly client",
)


# --- 1. the skill names one place -----------------------------------------------


def test_skill_md_never_offers_a_scratchpad() -> None:
    text = SKILL_MD.read_text()
    assert not re.search(r"scratch\s*pad", text, re.IGNORECASE), (
        "SKILL.md mentions a scratchpad; the URL file goes in ~/.mayfly/ only (#509)"
    )


def test_phase_one_creates_the_directory_at_mode_700() -> None:
    assert 'install -d -m 700 "$HOME/.mayfly"' in SKILL_MD.read_text()


@pytest.mark.parametrize("path", [SKILL_MD, WRAPPER], ids=lambda p: p.name)
def test_every_shown_url_file_is_under_dot_mayfly(path: Path) -> None:
    shown = re.findall(r"MAYFLY_URL_FILE=(\S+)", path.read_text())
    assert shown, f"{path.name} shows no MAYFLY_URL_FILE= example"
    stray = [s for s in shown if not s.lstrip("\\").startswith("$HOME/.mayfly/")]
    assert not stray, f"{path.name}: MAYFLY_URL_FILE outside $HOME/.mayfly/: {stray}"


def test_joining_refuses_a_name_already_taken() -> None:
    """CR 625: `install` overwrites, and ~/.mayfly/ is shared by every session.

    Overwriting another session's URL file sends its next post into this
    channel, so the join step guards the create with `test ! -e`.
    """
    text = SKILL_MD.read_text()
    guarded = (
        '{ test ! -e "$MAYFLY_URL_FILE" || { echo "taken: choose another name" >&2;'
        ' false; }; } && install -m 600 /dev/null "$MAYFLY_URL_FILE"'
    )
    assert guarded in text
    assert text.count('install -m 600 /dev/null "$MAYFLY_URL_FILE"') == 1
    # CR 631: a silent exit 1 is easy to miss, and the file-write step after
    # it would overwrite the other session's file all the same.
    assert "never into one that already existed" in text


def test_the_join_guard_says_why_it_refused(tmp_path: Path) -> None:
    """CR 631: the guard, run as SKILL.md shows it, refuses loudly."""
    line = re.search(r"`(\{ test ! -e [^`]+)`", SKILL_MD.read_text())
    assert line, "the join guard is not shown in a code span"
    taken = tmp_path / "status-67"
    taken.write_text("another session's channel\n")
    result = subprocess.run(
        ["bash", "-c", line.group(1)],
        env={**os.environ, "MAYFLY_URL_FILE": str(taken)},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "taken" in result.stderr
    assert taken.read_text() == "another session's channel\n"

    fresh = tmp_path / "status-67-2"
    result = subprocess.run(
        ["bash", "-c", line.group(1)],
        env={**os.environ, "MAYFLY_URL_FILE": str(fresh)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (fresh.stat().st_mode & 0o777) == 0o600


# --- 2. the wrapper warns after create ------------------------------------------


class _New(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(303 if self.path == "/new" else 404)
        self.send_header("Content-Length", "0")
        self.end_headers()


@pytest.fixture
def origin():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _New)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".mayfly").mkdir(parents=True, mode=0o700)
    return home


def _create(home: Path, url_file: Path, origin: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(WRAPPER), "create", origin],
        env={**os.environ, "HOME": str(home), "MAYFLY_URL_FILE": str(url_file)},
        capture_output=True,
        text=True,
        timeout=60,
    )


@requires_node
class TestCreateWarning:
    def test_a_file_in_dot_mayfly_is_silent(self, home: Path, origin: str) -> None:
        url_file = home / ".mayfly" / "status-67"
        result = _create(home, url_file, origin)
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        assert json.loads(result.stdout)["created"] is True
        assert (url_file.stat().st_mode & 0o077) == 0

    def test_a_relative_path_resolves_before_the_check(
        self, home: Path, origin: str
    ) -> None:
        result = subprocess.run(
            ["bash", str(WRAPPER), "create", origin],
            env={**os.environ, "HOME": str(home), "MAYFLY_URL_FILE": "status-67"},
            cwd=home / ".mayfly",
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""

    def test_cdpath_does_not_change_the_check(
        self, home: Path, tmp_path: Path, origin: str
    ) -> None:
        """CR 627: under CDPATH, `cd` prints the directory it found, so the
        captured value spans two lines, and a relative path can resolve to a
        decoy directory that CDPATH names."""
        decoy = tmp_path / "decoy" / ".mayfly"
        decoy.mkdir(parents=True)
        result = subprocess.run(
            ["bash", str(WRAPPER), "create", origin],
            env={
                **os.environ,
                "HOME": str(home),
                "CDPATH": str(tmp_path / "decoy"),
                "MAYFLY_URL_FILE": ".mayfly/status-67",
            },
            cwd=home,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        assert (home / ".mayfly" / "status-67").is_file()

    def test_a_file_elsewhere_warns_and_still_creates(
        self, home: Path, tmp_path: Path, origin: str
    ) -> None:
        scratch = tmp_path / "scratchpad"
        scratch.mkdir(mode=0o700)
        url_file = scratch / "url"
        result = _create(home, url_file, origin)
        assert result.returncode == 0, result.stderr
        assert result.stderr.startswith("WARNING:"), result.stderr
        assert "$HOME/.mayfly/" in result.stderr
        assert json.loads(result.stdout)["created"] is True
        assert url_file.is_file()

    def test_a_subdirectory_of_dot_mayfly_warns(self, home: Path, origin: str) -> None:
        nested = home / ".mayfly" / "status"
        nested.mkdir(mode=0o700)
        result = _create(home, nested / "67", origin)
        assert result.returncode == 0, result.stderr
        assert result.stderr.startswith("WARNING:"), result.stderr

    def test_no_dot_mayfly_at_all_warns(self, tmp_path: Path, origin: str) -> None:
        bare_home = tmp_path / "bare"
        bare_home.mkdir()
        result = _create(bare_home, tmp_path / "url", origin)
        assert result.returncode == 0, result.stderr
        assert result.stderr.startswith("WARNING:"), result.stderr

    def test_a_failed_create_leaves_stderr_one_json_object(
        self, home: Path, tmp_path: Path, origin: str
    ) -> None:
        url_file = tmp_path / "taken"
        url_file.write_text("")
        result = _create(home, url_file, origin)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "error" in json.loads(result.stderr)
