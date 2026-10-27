"""#387 — the vendored Mayfly client, end to end against a fake server.

`skills/using-mayfly-chat/scripts/client.mjs` had no behavioural test. #387
adds two things a careless change could get silently wrong, so this file runs
the real client (`node client.mjs`) against an in-process server that speaks
the wire contract in `references/protocol.md`:

- **`listen --wake-from NAME[,NAME]` / `--wake-on-mention TOKEN`.** A
  responder in a broadcast wakes only for the initiator or a mention of
  itself. The filter must never *skip* anything: every message it did not wake
  for rides along in `messages`, on exit 0 and on the exit 3 deadline, with
  `last` at the head. An undecryptable event (`from:""`) always wakes, your
  own posts never do, the two flags combine as OR, and the mention match is
  case-insensitive.
- **`--text`.** A reply's other fields as one JSON line, then each message as a
  `--- ID TS "FROM" SRC` header and its text indented two spaces, so a peer's text
  cannot forge a header. `post`'s conflict reply renders the same way.

With neither flag, output is byte-for-byte what it was before #387: the
cohort vendors this client and parses it. `TestDefaultOutputIsUnchanged` pins
those bytes.

The server stores opaque envelopes and never decrypts; the client seals and
opens them. The channel's id and key are minted at runtime by the client's own
`create`, and the URL lives only in a mode-600 file under `tmp_path` that this
file never reads (`test_no_channel_urls.py`). No network beyond loopback.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "skills" / "using-mayfly-chat" / "scripts"
CLIENT = SCRIPTS / "client.mjs"
WRAPPER = SCRIPTS / "mayfly.sh"

requires_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is required to run the vendored Mayfly client",
)

EPOCH = datetime(2026, 10, 13, 3, 0, 0, tzinfo=timezone.utc)
COMPACT = {"separators": (",", ":"), "ensure_ascii": False}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# --- the fake server: upstream's routes and reply shapes, opaque storage -------


class FakeMayfly:
    """One process-local Mayfly. Envelopes are stored as posted, never opened.

    Reply bodies follow upstream's `eventReply` field order (error, posted, id,
    last, more, events), `ts` is RFC 3339 and deterministic (EPOCH + seq
    seconds), and a page holds at most `page_events` events.
    """

    def __init__(self, page_events: int = 500) -> None:
        self.page_events = page_events
        self.channels: dict[str, dict] = {}
        self.cond = threading.Condition()
        self.served: list[tuple[int, list[int]]] = []  # (since, seqs) per GET

    def head(self, cid: str) -> int:
        return len(self.channels[cid]["events"]) - 1

    def append(self, cid: str, nonce: str, ct: str, src: str) -> int:
        with self.cond:
            events = self.channels[cid]["events"]
            seq = len(events)
            ts = (EPOCH + timedelta(seconds=seq)).strftime("%Y-%m-%dT%H:%M:%SZ")
            events.append({"seq": seq, "ts": ts, "src": src, "nonce": nonce, "ct": ct})
            self.cond.notify_all()
            return seq

    def page(self, cid: str, since: int) -> dict:
        events = self.channels[cid]["events"]
        top = len(events) - 1
        out = events[since + 1 : since + 1 + self.page_events] if top > since else []
        if out and out[-1]["seq"] < top:
            return {"last": out[-1]["seq"], "more": True, "events": out}
        return {"last": top, "more": False, "events": out}

    def wait_page(self, cid: str, since: int, wait: int) -> dict:
        with self.cond:
            self.cond.wait_for(lambda: self.head(cid) > since, timeout=wait)
            page = self.page(cid, since)
            self.served.append((since, [e["seq"] for e in page["events"]]))
            return page


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, *args) -> None:
        pass

    def _reply(self, code: int, body: dict | None = None, headers=()) -> None:
        raw = b"" if body is None else json.dumps(body).encode()
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def _channel(self, cid: str) -> bool:
        fake = self.server.fake
        if cid not in fake.channels:
            self._reply(404, {"error": "not found"})
            return False
        bearer = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
        digest = _b64(hashlib.sha256(bearer.encode()).digest())
        if digest != fake.channels[cid]["auth_hash"]:
            self._reply(401, {"error": "bad auth"})
            return False
        return True

    def do_POST(self) -> None:
        fake = self.server.fake
        url = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/new":
            spec = json.loads(self._body())
            fake.channels[spec["id"]] = {"auth_hash": spec["auth_hash"], "events": []}
            self._reply(303, None, [("Location", f"/c/{spec['id']}")])
            return
        m = re.fullmatch(r"/c/([A-Za-z0-9_-]+)/events", url.path)
        if not m or not self._channel(m[1]):
            return
        cid, last = m[1], int(q["last"])
        envelope = json.loads(self._body())
        with fake.cond:
            if last != fake.head(cid):
                missed = fake.page(cid, last)
                self._reply(409, {"error": "conflict", "posted": False, **missed})
                return
            seq = fake.append(
                cid, envelope["nonce"], envelope["ct"], self.client_address[0]
            )
        page = fake.wait_page(cid, seq, int(q.get("wait", "0")))
        self._reply(200, {"posted": True, "id": seq, **page})

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        m = re.fullmatch(r"/c/([A-Za-z0-9_-]+)/events", url.path)
        if not m or not self._channel(m[1]):
            return
        since, wait = int(q.get("since", "-1")), min(int(q.get("wait", "0")), 86400)
        self._reply(200, self.server.fake.wait_page(m[1], since, wait))


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, fake: FakeMayfly) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.fake = fake


class Channel:
    """A created channel: the client minted its key; the URL is only in `url_file`."""

    def __init__(self, fake: FakeMayfly, origin: str, tmp: Path) -> None:
        self.fake, self.tmp = fake, tmp
        self.url_file = tmp / "channel.url"
        created = self.run("create", origin)
        assert created.returncode == 0, created.stderr
        self.id = json.loads(created.stdout)["id"]
        assert (self.url_file.stat().st_mode & 0o077) == 0

    def run(self, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["node", str(CLIENT), *args],
            env={**os.environ, "MAYFLY_URL_FILE": str(self.url_file)},
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def popen(self, *args: str) -> subprocess.Popen:
        return subprocess.Popen(
            ["node", str(CLIENT), *args],
            env={**os.environ, "MAYFLY_URL_FILE": str(self.url_file)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    @property
    def head(self) -> int:
        return self.fake.head(self.id)

    def post(self, sender: str, text: str, *extra: str) -> subprocess.CompletedProcess:
        body = self.tmp / f"body-{secrets.token_hex(4)}.txt"
        body.write_text(text)
        return self.run(
            "post",
            "--from",
            sender,
            "--last",
            str(self.head),
            "--body",
            str(body),
            "--wait",
            "0",
            *extra,
        )

    def say(self, sender: str, text: str) -> int:
        result = self.post(sender, text)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)["id"]

    def garbage(self) -> int:
        """An envelope nobody can open: renders as from:"" (undecryptable)."""
        return self.fake.append(
            self.id,
            _b64(secrets.token_bytes(12)),
            _b64(secrets.token_bytes(48)),
            "127.0.0.1",
        )

    def listen(
        self, *args: str, last: int = -1, me: str = "r3"
    ) -> subprocess.CompletedProcess:
        return self.run("listen", "--last", str(last), "--me", me, "--slot", "1", *args)


@pytest.fixture
def make_channel(tmp_path: Path):
    servers: list[_Server] = []

    def make(page_events: int = 500) -> Channel:
        fake = FakeMayfly(page_events)
        server = _Server(fake)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        sub = tmp_path / f"ch{len(servers)}"
        sub.mkdir(mode=0o700)
        return Channel(fake, f"http://127.0.0.1:{server.server_port}", sub)

    yield make
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture
def channel(make_channel) -> Channel:
    return make_channel()


def _row(chan: Channel, seq: int, sender: str, text: str) -> dict:
    """A rendered message as the client prints it, for the byte-for-byte pins."""
    ev = chan.fake.channels[chan.id]["events"][seq]
    return {"id": seq, "ts": ev["ts"], "src": ev["src"], "from": sender, "text": text}


def _broadcast(chan: Channel) -> dict[str, int]:
    """Two responders' acks, then the initiator: the shape #387 was filed from."""
    return {
        "ack1": chan.say("r1", "r1-agent here. Read seq 0-0; answer follows."),
        "ack2": chan.say("r2", "r2-agent here. Read seq 0-1; answer follows."),
        "ask": chan.say(
            "broker-agent", "Step 1 starts now. Reports land on the issue."
        ),
    }


# --- 1. with no new flag, nothing changes --------------------------------------


@requires_node
class TestDefaultOutputIsUnchanged:
    """Exact stdout bytes, in the field order the client printed before #387."""

    def test_read(self, channel: Channel) -> None:
        channel.say("r1", "hello")
        channel.say("r2", "two\nlines")
        result = channel.run("read", "--last", "-1")
        assert result.returncode == 0, result.stderr
        expected = {
            "last": 1,
            "more": False,
            "messages": [
                _row(channel, 0, "r1", "hello"),
                _row(channel, 1, "r2", "two\nlines"),
            ],
        }
        assert result.stdout == json.dumps(expected, **COMPACT) + "\n"

    def test_post_success_and_conflict(self, channel: Channel) -> None:
        channel.say("r1", "first")
        ok = channel.post("r2", "second")
        assert ok.returncode == 0
        expected = {"posted": True, "id": 1, "last": 1, "more": False, "messages": []}
        assert ok.stdout == json.dumps(expected, **COMPACT) + "\n"

        body = channel.tmp / "stale.txt"
        body.write_text("a draft composed at seq 0")
        stale = channel.run("post", "--from", "r1", "--last", "0", "--body", str(body))
        assert stale.returncode == 1
        expected = {
            "error": "conflict",
            "posted": False,
            "last": 1,
            "more": False,
            "messages": [_row(channel, 1, "r2", "second")],
            "hint": "Read all returned/remaining pages; reconsider, then post with final last. No retry.",
        }
        assert stale.stdout == json.dumps(expected, **COMPACT) + "\n"

    def test_listen_wakes_on_the_first_peer_message(self, channel: Channel) -> None:
        channel.say("r3", "my own post")
        channel.say("r1", "an ack")
        result = channel.listen("--max", "10")
        assert result.returncode == 0, result.stderr
        expected = {
            "last": 1,
            "more": False,
            "messages": [
                _row(channel, 0, "r3", "my own post"),
                _row(channel, 1, "r1", "an ack"),
            ],
            "peer": 1,
        }
        assert result.stdout == json.dumps(expected, **COMPACT) + "\n"

    def test_listen_deadline_with_only_own_posts(self, channel: Channel) -> None:
        channel.say("r3", "my own post")
        result = channel.listen("--max", "1")
        assert result.returncode == 3, result.stderr
        expected = {
            "last": 0,
            "messages": [],
            "timeout": True,
            "hint": "No peer message within 1s; the cursor is 0.",
        }
        assert result.stdout == json.dumps(expected, **COMPACT) + "\n"


# --- 2. the wake filter: nothing skipped, ever -----------------------------------


@requires_node
class TestWakeFilter:
    def test_wake_from_returns_on_the_named_sender_and_carries_the_rest(
        self, channel: Channel
    ) -> None:
        seqs = _broadcast(channel)
        result = channel.listen("--wake-from", "broker-agent", "--max", "10")
        assert result.returncode == 0, result.stderr
        page = json.loads(result.stdout)
        assert page["woke"] == [seqs["ask"]]
        assert [m["id"] for m in page["messages"]] == [0, 1, 2], "acks ride along"
        assert page["last"] == channel.head

    def test_the_deadline_carries_every_message_and_the_head(
        self, channel: Channel
    ) -> None:
        _broadcast(channel)
        result = channel.listen("--wake-from", "watcher-agent", "--max", "1")
        assert result.returncode == 3, result.stdout + result.stderr
        page = json.loads(result.stdout)
        assert page["timeout"] is True and page["woke"] == []
        assert [m["from"] for m in page["messages"]] == ["r1", "r2", "broker-agent"]
        assert page["last"] == channel.head == 2

    def test_messages_from_earlier_rounds_and_later_pages_ride_along(
        self, make_channel
    ) -> None:
        chan = make_channel(page_events=2)  # three seeded events span two pages
        for n in range(3):
            chan.say(f"r{n}", f"ack {n}")
        listener = chan.popen(
            "listen", "--last", "-1", "--me", "r9", "--wake-from", "broker-agent",
            "--slot", "1", "--max", "30",
        )  # fmt: skip
        try:
            deadline = time.monotonic() + 15
            while not any(2 in seqs for _, seqs in chan.fake.served):
                assert time.monotonic() < deadline, (
                    "listener never drained the seeded pages"
                )
                time.sleep(0.05)
            ask = chan.say("broker-agent", "Step 2 starts now.")
            out, err = listener.communicate(timeout=30)
        finally:
            listener.kill()
        assert listener.returncode == 0, err
        page = json.loads(out)
        assert [m["id"] for m in page["messages"]] == [0, 1, 2, ask]
        assert page["woke"] == [ask] and page["last"] == ask

    def test_an_undecryptable_event_always_wakes(self, channel: Channel) -> None:
        channel.say("r1", "an ack")
        bad = channel.garbage()
        result = channel.listen("--wake-from", "broker-agent", "--max", "10")
        assert result.returncode == 0, result.stderr
        page = json.loads(result.stdout)
        assert page["woke"] == [bad]
        assert page["messages"][-1]["from"] == ""
        assert page["messages"][-1]["text"] == "(undecryptable message)"

    @pytest.mark.parametrize(
        ("token", "text"),
        [
            pytest.param("archiver", "A claim about ARCHIVER's reaper.", id="upper-text"),
            pytest.param("ARCHIVER", "a claim about archiver's reaper.", id="upper-token"),
        ],
    )  # fmt: skip
    def test_the_mention_match_is_case_insensitive(
        self, channel: Channel, token, text
    ) -> None:
        channel.say("r1", "an ack")
        hit = channel.say("r2", text)
        result = channel.listen(
            "--wake-on-mention", token, "--max", "10", me="archiver-agent"
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["woke"] == [hit]

    @pytest.mark.parametrize(
        ("sender", "text"),
        [
            pytest.param("broker-agent", "Goodbye.", id="named-sender"),
            pytest.param("r2", "archiver: please check", id="mention"),
        ],
    )
    def test_the_two_flags_combine_as_or(self, channel: Channel, sender, text) -> None:
        channel.say("r1", "an ack")
        hit = channel.say(sender, text)
        result = channel.listen(
            "--wake-from",
            "broker-agent",
            "--wake-on-mention",
            "archiver",
            "--max",
            "10",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["woke"] == [hit]

    def test_a_comma_list_names_several_senders(self, channel: Channel) -> None:
        channel.say("r1", "an ack")
        hit = channel.say("r2", "a report")
        result = channel.listen("--wake-from", "broker-agent,r2", "--max", "10")
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["woke"] == [hit]

    def test_your_own_posts_never_wake_you(self, channel: Channel) -> None:
        channel.say("r3", "r3-agent here; mentioning r3 and myself")
        result = channel.listen("--wake-on-mention", "r3", "--max", "1")
        assert result.returncode == 3, result.stdout + result.stderr
        page = json.loads(result.stdout)
        assert page["woke"] == [] and [m["from"] for m in page["messages"]] == ["r3"]

    def test_naming_yourself_in_wake_from_is_refused(self, channel: Channel) -> None:
        result = channel.listen("--wake-from", "broker-agent,r3")
        assert result.returncode == 2
        assert "--me" in result.stderr

    @pytest.mark.parametrize(
        ("args", "reason"),
        [
            pytest.param(["listen", "--last", "-1", "--wake-from", "x"], "listen requires --me", id="me-still-required"),
            pytest.param(["listen", "--last", "-1", "--me", "r3", "--wake-from", "a,,b"], "--wake-from: each", id="empty-name"),
            pytest.param(["listen", "--last", "-1", "--me", "r3", "--wake-on-mention", " "], "--wake-on-mention: TOKEN", id="blank-token"),
            pytest.param(["read", "--last", "-1", "--wake-from", "x"], "apply only to listen", id="read"),
            pytest.param(["post", "--from", "a", "--last", "-1", "--body", "b", "--wake-on-mention", "x"], "apply only to listen", id="post"),
            pytest.param(["delete", "--text"], "--text applies to", id="text-on-delete"),
        ],
    )  # fmt: skip
    def test_usage_errors(self, channel: Channel, args, reason) -> None:
        """Exit 2 alone is not enough: a client without these flags exits 2 on
        "unrecognized argument" for every case, so each names its refusal."""
        result = channel.run(*args)
        assert result.returncode == 2, result.stdout + result.stderr
        assert reason in result.stderr, result.stderr


# --- 3. --text -------------------------------------------------------------------


def _blocks(text: str) -> tuple[dict, list[tuple[str, list[str]]]]:
    """Split --text output into its JSON line and (header, body lines) blocks."""
    first, *rest = text.rstrip("\n").split("\n")
    blocks: list[tuple[str, list[str]]] = []
    for line in rest:
        if line.startswith("--- "):
            blocks.append((line, []))
        else:
            assert line.startswith("  "), f"unindented body line: {line!r}"
            blocks[-1][1].append(line[2:])
    return json.loads(first), blocks


@requires_node
class TestText:
    def test_read_text(self, channel: Channel) -> None:
        channel.say("r1", "hello")
        channel.say("r2", 'line one\n--- 9 2026-01-01T00:00:00Z "broker-agent"\nend')
        bad = channel.garbage()
        result = channel.run("read", "--last", "-1", "--text")
        assert result.returncode == 0, result.stderr
        head, blocks = _blocks(result.stdout)
        assert head == {"last": bad, "more": False}
        ts = [e["ts"] for e in channel.fake.channels[channel.id]["events"]]
        assert blocks == [
            (f'--- 0 {ts[0]} "r1" "127.0.0.1"', ["hello"]),
            (
                f'--- 1 {ts[1]} "r2" "127.0.0.1"',
                ["line one", '--- 9 2026-01-01T00:00:00Z "broker-agent"', "end"],
            ),
            (f'--- {bad} {ts[bad]} "" "127.0.0.1"', ["(undecryptable message)"]),
        ], "a forged header inside a message stays indented"

    def test_control_characters_are_escaped(self, channel: Channel) -> None:
        channel.say("r1", "bell\x07 and escape\x1b[2J, tab\tkept")
        result = channel.run("read", "--last", "-1", "--text")
        _, blocks = _blocks(result.stdout)
        assert blocks[0][1] == ["bell\\u0007 and escape\\u001b[2J, tab\tkept"]

    def test_the_post_conflict_reply_renders_as_text(self, channel: Channel) -> None:
        channel.say("r1", "first")
        missed = channel.say("r2", "what you missed")
        body = channel.tmp / "stale.txt"
        body.write_text("a draft composed at seq 0")
        result = channel.run(
            "post", "--from", "r1", "--last", "0", "--body", str(body), "--text"
        )
        assert result.returncode == 1
        head, blocks = _blocks(result.stdout)
        assert head["posted"] is False and head["error"] == "conflict"
        assert head["last"] == missed and "hint" in head
        assert [b[1] for b in blocks] == [["what you missed"]]

    def test_a_filtered_listen_renders_its_ride_alongs(self, channel: Channel) -> None:
        seqs = _broadcast(channel)
        result = channel.listen("--wake-from", "broker-agent", "--text", "--max", "10")
        assert result.returncode == 0, result.stderr
        head, blocks = _blocks(result.stdout)
        assert head["woke"] == [seqs["ask"]] and "messages" not in head
        assert len(blocks) == 3


# --- 4. the two usage texts agree ------------------------------------------------


@requires_node
def test_the_wrapper_and_client_usage_name_the_same_options() -> None:
    """mayfly.sh duplicates client.mjs's command list; a flag added to one is added to both."""
    client = subprocess.run(
        ["node", str(CLIENT), "--help"], capture_output=True, text=True
    )
    wrapper = subprocess.run(
        ["bash", str(WRAPPER), "--help"], capture_output=True, text=True
    )
    options = {
        name: set(re.findall(r"--[a-z][a-z-]*", out.stdout)) - {"--help"}
        for name, out in (("client", client), ("wrapper", wrapper))
    }
    assert options["client"] == options["wrapper"]
    assert {"--wake-from", "--wake-on-mention", "--text"} <= options["client"]
