"""#448 — the TypeSafe client: opt-in, skip-loudly, retries, size guard, key hygiene.

Every proposal in the TypeSafe epic (#451) calls one endpoint through
`scripts/_typesafe.py`, so this file pins the contract they all lean on:

- **A skip is an exception, never an exit code.** Exit 3 already means a finding
  or a loss in `prove-no-loss.sh` and others, so a skip that exited 3 would read
  as content loss. `connect()` raises `Skipped`, and `.line` is the one line to print.
- **Opt-in is off by default and fails closed.** The env var wins, then
  `.skills/typesafe` in the primary checkout. A value that isn't `on` or `off`
  reads as off, and the line says so.
- **Only transient failures are retried,** within a bounded count and wait.
  A `422` or `401` is the caller's problem, and retrying it only spends time.
- **The server's message survives,** and the key never appears in it.

No network: a fake transport stands in for the API, and the one test of the real
`urllib` transport talks to a loopback server. The live call is
`tests/integration/test_typesafe_live.py`.
"""

from __future__ import annotations

import http.server
import importlib.util
import io
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENT = REPO_ROOT / "scripts" / "_typesafe.py"

_spec = importlib.util.spec_from_file_location("_typesafe", CLIENT)
ts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ts)

KEY = "ts-test-key-0123456789"
QUESTIONS = {"stale": {"type": "noul", "instructions": "Is this sentence stale?"}}


def _ok(model=ts.MODEL, answers=None):
    body = {
        "model": model,
        "answers": answers or {"stale": {"type": "noul", "noul": 0.9}},
        "usage": {"input_tokens": 297, "output_tokens": 1},
    }
    return 200, {}, json.dumps(body).encode()


class Fake:
    """A transport that replays canned (status, headers, body) answers, or raises them."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, url, data, headers, timeout):
        self.calls.append(
            {"url": url, "data": data, "headers": headers, "timeout": timeout}
        )
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _client(*answers):
    fake, sleeps, err = Fake(*answers), [], io.StringIO()
    client = ts.Client(KEY, transport=fake, sleep=sleeps.append, stderr=err)
    return client, fake, sleeps, err


def _clean_env() -> dict:
    # The fixture repos below must not be steered at the repo running the
    # suite by an inherited GIT_DIR (docs/STYLE.md, #189).
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, env=_clean_env(), check=True, capture_output=True
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A primary checkout with one commit, and no knob."""
    for k in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(k)
    root = tmp_path / "primary"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(
        root,
        "-c",
        "user.email=a@b",
        "-c",
        "user.name=A",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "init",
    )
    return root


def _knob(root: Path, text: str) -> None:
    (root / ".skills").mkdir(exist_ok=True)
    (root / ".skills" / "typesafe").write_text(text)


# --- opt-in and skip ---------------------------------------------------------


class TestOptIn:
    def test_absent_everywhere_is_off(self, repo):
        on, why = ts.opted_in({}, str(repo))
        assert not on
        assert "absent" in why

    @pytest.mark.parametrize(
        "text", ["on\n", "  on  \n", "# opt in: judged text leaves the machine\n\non\n"]
    )
    def test_the_file_says_on(self, repo, text):
        _knob(repo, text)
        assert ts.opted_in({}, str(repo))[0]

    def test_the_file_says_off(self, repo):
        _knob(repo, "off\n")
        on, why = ts.opted_in({}, str(repo))
        assert not on and "says off" in why

    @pytest.mark.parametrize("word", ["yes", "ON", "true", "1"])
    def test_any_other_word_in_the_file_is_off_and_named(self, repo, word):
        _knob(repo, f"{word}\n")
        on, why = ts.opted_in({}, str(repo))
        assert not on
        assert repr(word) in why, "the skip line must name the value it refused"

    def test_an_empty_or_comment_only_file_is_off(self, repo):
        _knob(repo, "# nothing yet\n\n")
        assert not ts.opted_in({}, str(repo))[0]

    def test_env_off_wins_over_file_on(self, repo):
        _knob(repo, "on\n")
        on, why = ts.opted_in({ts.OPT_IN_ENV: "off"}, str(repo))
        assert not on and ts.OPT_IN_ENV in why

    def test_env_on_wins_over_file_absent(self, repo):
        assert ts.opted_in({ts.OPT_IN_ENV: "on"}, str(repo))[0]

    def test_a_malformed_env_value_is_off_and_does_not_fall_through_to_the_file(
        self, repo
    ):
        """A typo in the override must not silently hand the decision to the file."""
        _knob(repo, "on\n")
        on, why = ts.opted_in({ts.OPT_IN_ENV: "yes"}, str(repo))
        assert not on
        assert "'yes'" in why

    def test_outside_a_git_checkout_only_the_env_can_opt_in(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
        assert not ts.opted_in({}, str(tmp_path))[0]
        assert ts.opted_in({ts.OPT_IN_ENV: "on"}, str(tmp_path))[0]

    def test_a_linked_worktree_reads_the_primary_checkouts_untracked_knob(
        self, repo, tmp_path
    ):
        """The #180 / #188 / #202 rule: an untracked knob exists only in the primary checkout."""
        _knob(repo, "on\n")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "side", str(wt))
        assert not (wt / ".skills" / "typesafe").exists()
        on, why = ts.opted_in({}, str(wt))
        assert on, why
        assert ts.project_root(str(wt / ".")).resolve() == repo.resolve()

    def test_a_subdirectory_resolves_to_the_checkout_root(self, repo):
        _knob(repo, "on\n")
        sub = repo / "a" / "b"
        sub.mkdir(parents=True)
        assert ts.opted_in({}, str(sub))[0]

    def test_a_submodule_reads_its_own_knob_not_the_superprojects(self, repo, tmp_path):
        """Inside a submodule the common dir's parent is `<super>/.git/modules`, not a checkout."""
        inner = tmp_path / "inner"
        inner.mkdir()
        _git(inner, "init", "-q", "-b", "main")
        _knob(inner, "on\n")
        _git(inner, "add", ".skills/typesafe")
        _git(
            inner,
            "-c",
            "user.email=a@b",
            "-c",
            "user.name=A",
            "commit",
            "-q",
            "-m",
            "knob",
        )
        _git(
            repo,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(inner),
            "vendor/inner",
        )
        _knob(repo, "off\n")
        sub = repo / "vendor" / "inner"
        assert ts.project_root(str(sub)).resolve() == sub.resolve()
        assert ts.opted_in({}, str(sub))[0]


class TestConnectSkips:
    def test_not_opted_in_is_a_skip_naming_its_reason(self, repo):
        with pytest.raises(ts.Skipped) as e:
            ts.connect(environ={ts.KEY_ENV: KEY}, cwd=str(repo))
        assert e.value.reason == "not-opted-in"
        assert e.value.line.startswith("typesafe: skipped (not-opted-in): ")
        assert "\n" not in e.value.line

    @pytest.mark.parametrize("key", [None, "", "   "])
    def test_opted_in_without_a_key_is_a_skip_naming_its_reason(self, repo, key):
        env = {ts.OPT_IN_ENV: "on"}
        if key is not None:
            env[ts.KEY_ENV] = key
        with pytest.raises(ts.Skipped) as e:
            ts.connect(environ=env, cwd=str(repo))
        assert e.value.reason == "no-key"
        assert ts.KEY_ENV in e.value.line and "\n" not in e.value.line

    def test_the_opt_in_is_checked_before_the_key(self, repo):
        """A repo that never opted in hears about the opt-in, not about a key it doesn't need."""
        with pytest.raises(ts.Skipped) as e:
            ts.connect(environ={}, cwd=str(repo))
        assert e.value.reason == "not-opted-in"

    def test_a_skip_is_not_a_typesafe_error(self):
        """A caller catching failures must not catch a skip and report it as one, or vice versa."""
        assert not issubclass(ts.Skipped, ts.TypeSafeError)
        assert not issubclass(ts.TypeSafeError, ts.Skipped)

    def test_opted_in_with_a_key_connects_to_the_pinned_model(self, repo):
        client = ts.connect(
            environ={ts.OPT_IN_ENV: "on", ts.KEY_ENV: KEY}, cwd=str(repo)
        )
        assert client.model == "jev-1.13.0"


# --- the request -------------------------------------------------------------


class TestRequest:
    def test_one_post_to_systemone_with_bearer_auth_and_the_pinned_model(self):
        client, fake, _, err = _client(_ok())
        reply = client.ask("Some state.", QUESTIONS)
        assert reply["answers"]["stale"]["noul"] == 0.9
        (call,) = fake.calls
        assert call["url"] == "https://api.typesafe.ai/v1/systemone"
        assert call["headers"]["Authorization"] == f"Bearer {KEY}"
        assert call["headers"]["Content-Type"] == "application/json"
        sent = json.loads(call["data"])
        assert sent == {
            "model": "jev-1.13.0",
            "state": "Some state.",
            "questions": QUESTIONS,
        }
        assert "TypeSafe-Danger-Zone-Long-Context" not in call["headers"]

    def test_the_answering_model_is_echoed_on_stderr(self):
        client, _, _, err = _client(_ok(model="jev-1.13.0"))
        client.ask("x", QUESTIONS)
        assert (
            "answered by jev-1.13.0 (asked for jev-1.13.0), 297 input tokens"
            in err.getvalue()
        )

    def test_a_model_override_is_sent_and_a_different_answering_model_is_visible(self):
        fake, err = Fake(_ok(model="jev-1.14.0")), io.StringIO()
        client = ts.Client(KEY, model="jev-preview", transport=fake, stderr=err)
        client.ask("x", QUESTIONS)
        assert json.loads(fake.calls[0]["data"])["model"] == "jev-preview"
        assert "answered by jev-1.14.0 (asked for jev-preview)" in err.getvalue()

    def test_non_ascii_state_is_sent_as_utf8_json(self):
        client, fake, _, _ = _client(_ok())
        client.ask("naïve — ☃", QUESTIONS)
        assert "naïve — ☃".encode() in fake.calls[0]["data"]

    @pytest.mark.parametrize("questions", [{}, None, ["stale"]])
    def test_questions_must_be_a_non_empty_object(self, questions):
        client, fake, _, _ = _client()
        with pytest.raises(ts.TypeSafeError, match="non-empty object"):
            client.ask("x", questions)
        assert not fake.calls

    @pytest.mark.parametrize(
        "state", [{"ratio": float("nan")}, {"inf": float("inf")}, {"ids": {1, 2}}]
    )
    def test_a_value_the_api_cannot_take_is_refused_before_sending(self, state):
        client, fake, _, _ = _client()
        with pytest.raises(ts.TypeSafeError, match="valid JSON"):
            client.ask(state, QUESTIONS)
        assert not fake.calls

    def test_a_missing_answer_is_a_failure_not_a_partial_result(self):
        client, _, _, _ = _client(_ok(answers={"other": {"type": "noul", "noul": 0.1}}))
        with pytest.raises(ts.TypeSafeError, match="no answer for stale"):
            client.ask("x", QUESTIONS)

    @pytest.mark.parametrize("body", [b"not json", b"[]", b'{"model": "jev-1.13.0"}'])
    def test_a_malformed_200_is_a_failure(self, body):
        client, _, _, _ = _client((200, {}, body))
        with pytest.raises(ts.TypeSafeError) as e:
            client.ask("x", QUESTIONS)
        assert e.value.status == 200


# --- failures and retries ----------------------------------------------------


class TestFailures:
    def test_a_422_carries_the_servers_field_and_message_and_is_not_retried(self):
        detail = {
            "detail": [
                {
                    "loc": ["body", "questions", "stale", "criteria"],
                    "msg": "Field required",
                    "type": "missing",
                }
            ]
        }
        client, fake, sleeps, _ = _client((422, {}, json.dumps(detail).encode()))
        with pytest.raises(ts.TypeSafeError) as e:
            client.ask("x", QUESTIONS)
        assert e.value.status == 422
        assert "body.questions.stale.criteria: Field required" in str(e.value)
        assert len(fake.calls) == 1 and not sleeps

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 415, 422])
    def test_a_request_or_key_error_is_never_retried(self, status):
        client, fake, sleeps, _ = _client((status, {}, b'{"detail": "no"}'))
        with pytest.raises(ts.TypeSafeError) as e:
            client.ask("x", QUESTIONS)
        assert e.value.status == status
        assert len(fake.calls) == 1 and not sleeps

    def test_a_non_json_error_body_is_kept_verbatim(self):
        client, _, _, _ = _client((401, {}, b"Unauthorized: bad token"))
        with pytest.raises(ts.TypeSafeError, match="Unauthorized: bad token"):
            client.ask("x", QUESTIONS)

    def test_a_huge_error_body_is_truncated_and_says_so(self):
        client, _, _, _ = _client((400, {}, b"x" * 10_000))
        with pytest.raises(ts.TypeSafeError) as e:
            client.ask("x", QUESTIONS)
        assert "more characters" in str(e.value) and len(str(e.value)) < 3000

    def test_429_waits_the_servers_retry_after_then_succeeds(self):
        client, fake, sleeps, err = _client((429, {"Retry-After": "2"}, b"{}"), _ok())
        client.ask("x", QUESTIONS)
        assert sleeps == [2.0] and len(fake.calls) == 2
        assert "HTTP 429, retrying in 2 s (attempt 2 of 3)" in err.getvalue()

    def test_retry_after_ms_wins_over_retry_after(self):
        client, _, sleeps, _ = _client(
            (429, {"retry-after-ms": "250", "retry-after": "9"}, b"{}"), _ok()
        )
        client.ask("x", QUESTIONS)
        assert sleeps == [0.25]

    def test_an_http_date_retry_after_is_honoured(self):
        client, _, sleeps, _ = _client(
            (429, {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}, b"{}"), _ok()
        )
        client.ask("x", QUESTIONS)
        assert sleeps == [0.0], "a date in the past means retry now"

    def test_a_garbled_retry_after_falls_back_to_backoff(self):
        client, _, sleeps, _ = _client((429, {"Retry-After": "soon"}, b"{}"), _ok())
        client.ask("x", QUESTIONS)
        assert sleeps == [ts.BACKOFF_INITIAL]

    @pytest.mark.parametrize("status", [408, 500, 502, 503, 529])
    def test_transient_statuses_back_off_and_retry(self, status):
        client, fake, sleeps, _ = _client((status, {}, b""), (status, {}, b""), _ok())
        client.ask("x", QUESTIONS)
        assert sleeps == [0.5, 1.0] and len(fake.calls) == 3

    def test_retries_are_bounded_and_the_last_error_is_raised(self):
        client, fake, sleeps, _ = _client(*[(529, {}, b'{"detail": "Overloaded"}')] * 3)
        with pytest.raises(ts.TypeSafeError) as e:
            client.ask("x", QUESTIONS)
        assert len(fake.calls) == ts.MAX_ATTEMPTS == 3
        assert e.value.status == 529
        assert "Overloaded" in str(e.value) and "gave up after 3 attempts" in str(
            e.value
        )

    def test_a_retry_after_past_the_budget_gives_up_instead_of_sleeping(self):
        client, fake, sleeps, _ = _client(
            (429, {"Retry-After": "3600"}, b'{"detail": "slow down"}')
        )
        with pytest.raises(ts.TypeSafeError) as e:
            client.ask("x", QUESTIONS)
        assert not sleeps and len(fake.calls) == 1
        assert "slow down" in str(e.value) and "retry budget" in str(e.value)

    def test_a_connection_failure_is_retried_then_raised_without_a_status(self):
        boom = OSError("nodename nor servname provided")
        client, fake, sleeps, _ = _client(boom, boom, boom)
        with pytest.raises(ts.TypeSafeError) as e:
            client.ask("x", QUESTIONS)
        assert e.value.status is None and len(fake.calls) == 3
        assert "couldn't reach api.typesafe.ai" in str(e.value)

    def test_a_connection_failure_then_success_returns_the_answer(self):
        client, _, _, _ = _client(TimeoutError("timed out"), _ok())
        assert client.ask("x", QUESTIONS)["model"] == ts.MODEL


# --- the key -----------------------------------------------------------------


class TestKeyHygiene:
    def test_a_server_echoing_the_key_is_redacted_in_the_error(self):
        client, _, _, _ = _client((401, {}, f'{{"detail": "bad key {KEY}"}}'.encode()))
        with pytest.raises(ts.TypeSafeError) as e:
            client.ask("x", QUESTIONS)
        assert KEY not in str(e.value) and "[redacted]" in str(e.value)

    def test_a_connection_error_naming_the_key_is_redacted(self):
        client, _, _, _ = _client(*[OSError(f"proxy said {KEY}")] * 3)
        with pytest.raises(ts.TypeSafeError) as e:
            client.ask("x", QUESTIONS)
        assert KEY not in str(e.value)

    def test_the_key_is_not_in_the_clients_repr_or_on_stderr(self):
        client, _, _, err = _client((429, {}, b"{}"), _ok())
        client.ask("x", QUESTIONS)
        assert KEY not in repr(client) and KEY not in err.getvalue()

    def test_the_key_is_never_in_the_skip_line(self, repo):
        with pytest.raises(ts.Skipped) as e:
            ts.connect(environ={ts.KEY_ENV: KEY, ts.OPT_IN_ENV: "nope"}, cwd=str(repo))
        assert KEY not in e.value.line


# --- the size guard ----------------------------------------------------------


class TestSizeGuard:
    def test_a_state_over_the_per_question_limit_is_refused_before_sending(self):
        client, fake, _, _ = _client()
        state = "x" * int(ts.PER_QUESTION_TOKENS * ts.BYTES_PER_TOKEN)
        with pytest.raises(ts.RequestTooLarge) as e:
            client.ask(state, QUESTIONS)
        assert not fake.calls
        assert "per-question" in str(e.value) and "estimate" in str(e.value)

    def test_many_questions_over_the_per_request_limit_are_refused(self):
        """Each question fits with the state; all of them together don't."""
        client, fake, _, _ = _client()
        state = "x" * int(20_000 * ts.BYTES_PER_TOKEN)
        questions = {
            f"q{i}": {"type": "noul", "instructions": "y" * 9000} for i in range(15)
        }
        with pytest.raises(ts.RequestTooLarge) as e:
            client.ask(state, questions)
        assert not fake.calls
        assert "per-request" in str(e.value) and "estimate" in str(e.value)

    def test_a_request_inside_both_limits_is_sent(self):
        client, fake, _, _ = _client(_ok())
        client.ask("x" * 60_000, QUESTIONS)  # ~20k estimated tokens, ~15k real
        assert len(fake.calls) == 1

    def test_too_large_is_a_typesafe_error_without_a_status(self):
        assert issubclass(ts.RequestTooLarge, ts.TypeSafeError)
        assert ts.RequestTooLarge("m").status is None


# --- the real urllib transport, against loopback ----------------------------


class _Handler(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):
        self.seen.append(
            (dict(self.headers), self.rfile.read(int(self.headers["Content-Length"])))
        )
        code, headers, body = self.server.reply
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def loopback():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, f"http://127.0.0.1:{server.server_port}/v1/systemone"
    server.shutdown()


class TestUrllibTransport:
    def test_an_http_error_returns_status_headers_and_body_instead_of_raising(
        self, loopback
    ):
        """`str(HTTPError)` is only the reason phrase; the server's detail is in the body."""
        server, url = loopback
        server.reply = (
            401,
            {"Content-Type": "application/json", "Retry-After": "1"},
            b'{"detail": "Invalid API key"}',
        )
        status, headers, body = ts.urllib_transport(
            url, b"{}", {"Authorization": f"Bearer {KEY}"}, 5
        )
        assert status == 401
        assert headers["Retry-After"] == "1"
        assert json.loads(body)["detail"] == "Invalid API key"

    def test_a_200_returns_the_body_and_sends_the_headers(self, loopback):
        server, url = loopback
        server.reply = (200, {}, b'{"ok": true}')
        _Handler.seen.clear()
        status, _, body = ts.urllib_transport(
            url,
            b'{"a": 1}',
            {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
            5,
        )
        assert status == 200 and body == b'{"ok": true}'
        sent_headers, sent_body = _Handler.seen[0]
        assert (
            sent_headers["Authorization"] == f"Bearer {KEY}"
            and sent_body == b'{"a": 1}'
        )

    def test_an_unreachable_host_raises_oserror_for_the_retry_loop(self):
        with pytest.raises(OSError):
            ts.urllib_transport("http://127.0.0.1:9/v1/systemone", b"{}", {}, 2)

    def test_the_whole_client_through_loopback_names_the_server_message_and_not_the_key(
        self, loopback, monkeypatch
    ):
        server, url = loopback
        server.reply = (
            401,
            {"Content-Type": "application/json"},
            b'{"detail": "Invalid API key"}',
        )
        monkeypatch.setattr(ts, "ENDPOINT", url)
        client = ts.Client(KEY, stderr=io.StringIO())
        with pytest.raises(ts.TypeSafeError) as e:
            client.ask("x", QUESTIONS)
        assert e.value.status == 401
        assert "Invalid API key" in str(e.value) and KEY not in str(e.value)


# --- the module as a script --------------------------------------------------


class TestCli:
    def test_help_prints_the_contract_and_exits_0(self):
        out = subprocess.run(
            [sys.executable, str(CLIENT), "--help"], capture_output=True, text=True
        )
        assert out.returncode == 0
        assert "Skips go through the API, never an exit code" in out.stdout
        assert "TYPESAFE_OPT_IN" in out.stdout and ".skills/typesafe" in out.stdout

    @pytest.mark.parametrize("argv", [[], ["--check"]])
    def test_anything_else_is_a_usage_error_and_sends_nothing(self, argv):
        out = subprocess.run(
            [sys.executable, str(CLIENT), *argv], capture_output=True, text=True
        )
        assert out.returncode == 1 and "--help" in out.stderr
