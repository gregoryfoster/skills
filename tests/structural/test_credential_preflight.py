"""`measure-context.sh --check-credential` asks the endpoint (#271).

The preflight used to report `ok` for any non-empty `ANTHROPIC_API_KEY` without
ever calling anything. A key that authenticates but cannot spend — lapsed credit
balance, exhausted quota, an entitlement that does not cover `--model` — passed
Phase 0 green, and the run then did eight phases of work and lost the week's
ledger row to `record-telemetry.sh` exit 4, whose remediation line advises
catching it next time with the preflight that had just passed.

That is the failure #104 filed the preflight to prevent, recurring past the
guard #104 produced, and it is not enumerable: balance is a property of the
account at that moment, not of the credential's shape. So the preflight makes
one real `count_tokens` call — free, one character of input, the same request
the run will make for the same `--model`.

These tests run against a stub on `ANTHROPIC_BASE_URL`, so "the API said no" is
exercised without a bad key and without a network.
"""

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "curating-context"
    / "scripts"
)
MEASURE = SCRIPTS / "measure-context.sh"

KEY = "sk-ant-not-a-real-key"
CREDIT_MESSAGE = (
    "Your credit balance is too low to access the Anthropic API. Please go to "
    "Plans & Billing to upgrade or purchase credits."
)


def _clean_env() -> dict:
    """Env without inherited GIT_* vars or this repo's own credential.

    Everything the preflight resolves must come from the fixture, or a
    developer's exported key answers instead of the case under test.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_OAUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        env.pop(k, None)
    return env


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "init", "-q"],
        check=True,
        capture_output=True,
        env=_clean_env(),
    )
    (repo / "AGENTS.md").write_text("- a policy line\n")
    return repo


def _no_ant(tmp_path: Path, env: dict) -> dict:
    """Shadow any real `ant` CLI with one that has no profile.

    Without this, "no credential resolves" passes or fails according to whether
    the developer running the suite happens to be logged in.
    """
    stub = tmp_path / "no-ant-bin"
    stub.mkdir(exist_ok=True)
    (stub / "ant").write_text("#!/bin/sh\nexit 1\n")
    (stub / "ant").chmod(0o755)
    env["PATH"] = f"{stub}:{env['PATH']}"
    return env


def _without_python3(tmp_path: Path, env: dict) -> dict:
    """A PATH carrying every tool the script needs except python3.

    Mirroring PATH minus one name, rather than hand-listing the tools the
    preflight happens to shell out to, is what keeps this case about the
    missing interpreter: a guessed-short list fails for whichever utility the
    script grows next, and the assertion would still be green for the wrong
    reason.
    """
    stub = tmp_path / "no-python-bin"
    stub.mkdir(exist_ok=True)
    for directory in env.get("PATH", "").split(os.pathsep):
        d = Path(directory)
        if not d.is_dir():
            continue
        for entry in d.iterdir():
            if entry.name.startswith("python"):
                continue
            link = stub / entry.name
            if link.exists() or link.is_symlink():
                continue
            try:
                link.symlink_to(entry)
            except OSError:
                pass
    env["PATH"] = str(stub)
    return env


def _with_ant(tmp_path: Path, env: dict, token: str = "fake-jwt-token") -> dict:
    stub = tmp_path / "ant-bin"
    stub.mkdir(exist_ok=True)
    (stub / "ant").write_text(f"#!/bin/sh\necho {token}\n")
    (stub / "ant").chmod(0o755)
    env["PATH"] = f"{stub}:{env['PATH']}"
    return env


class _Stub:
    """A count_tokens endpoint that answers however the test needs, and records
    what it was asked — the probe's model, body and auth headers are half the
    contract."""

    def __init__(self, status: int = 200, payload: dict | None = None):
        self.status = status
        self.payload = payload if payload is not None else {"input_tokens": 1}
        self.requests: list[dict] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 — BaseHTTPRequestHandler's spelling
                length = int(self.headers.get("content-length", 0))
                raw = self.rfile.read(length)
                stub.requests.append(
                    {
                        "path": self.path,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "body": json.loads(raw or b"{}"),
                    }
                )
                out = json.dumps(stub.payload).encode()
                self.send_response(stub.status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *args):  # keep pytest output clean
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "_Stub":
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _refusal(message: str, kind: str = "invalid_request_error") -> dict:
    return {"type": "error", "error": {"type": kind, "message": message}}


def _run(repo: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(MEASURE), "--check-credential", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def _run_exact(repo: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(MEASURE), "--exact", "--no-write", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _repo(tmp_path)


class TestTheProbeIsMade:
    def test_an_accepted_key_is_ok(self, repo: Path, tmp_path: Path):
        env = _no_ant(tmp_path, _clean_env())
        env["ANTHROPIC_API_KEY"] = KEY
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _run(repo, env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "environment" in r.stdout
        assert KEY not in r.stdout + r.stderr  # never the value
        assert len(stub.requests) == 1, "the preflight did not call the endpoint"

    def test_the_probe_costs_one_character_at_the_run_s_model(
        self, repo: Path, tmp_path: Path
    ):
        """Entitlement is per model, so the preflight must answer for the model
        the run will use — and it must not pay to count the policy file twice."""
        env = _no_ant(tmp_path, _clean_env())
        env["ANTHROPIC_API_KEY"] = KEY
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _run(repo, env, "--model", "claude-haiku-4-5-20251001")
        assert r.returncode == 0, r.stdout + r.stderr
        sent = stub.requests[0]
        assert sent["path"] == "/v1/messages/count_tokens"
        assert sent["body"]["model"] == "claude-haiku-4-5-20251001"
        assert sent["body"]["messages"][0]["content"] == "x"
        assert sent["headers"]["x-api-key"] == KEY

    def test_no_credential_never_calls_the_endpoint(self, repo: Path, tmp_path: Path):
        env = _no_ant(tmp_path, _clean_env())
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _run(repo, env)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "BEFORE starting the run" in r.stderr
        assert stub.requests == []


class TestWhatIsNotACredentialVerdict:
    """Exit 3 is "fix your credential". Nothing else may borrow it — SKILL.md's
    Phase 0 turns a 3 into "resolve a credential now; autonomously, abort", and
    an agent that reads that over a missing interpreter goes to work on the one
    thing that is not wrong."""

    def test_a_missing_python3_is_exit_2(self, repo: Path, tmp_path: Path):
        env = _without_python3(tmp_path, _clean_env())
        env["ANTHROPIC_API_KEY"] = KEY
        r = _run(repo, env)
        assert r.returncode == 2, r.stdout + r.stderr
        assert "python3 is missing" in r.stderr
        assert "is a verdict on a credential" in r.stderr


class TestARefusedCredentialIsNotOk:
    def test_a_zero_balance_key_is_exit_3(self, repo: Path, tmp_path: Path):
        """#271 itself: this key authenticates and cannot spend. Before the
        probe it passed the preflight green and cost the week's row."""
        env = _no_ant(tmp_path, _clean_env())
        env["ANTHROPIC_API_KEY"] = KEY
        with _Stub(status=400, payload=_refusal(CREDIT_MESSAGE)) as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _run(repo, env)
        assert r.returncode == 3, r.stdout + r.stderr
        assert not r.stdout.startswith("ok")
        assert "credit balance is too low" in r.stderr
        assert KEY not in r.stdout + r.stderr

    def test_the_endpoint_s_own_words_are_quoted(self, repo: Path, tmp_path: Path):
        """`error.message` is more actionable than anything this script could
        infer from a 400 — and the JSON envelope around it is not."""
        env = _no_ant(tmp_path, _clean_env())
        env["ANTHROPIC_API_KEY"] = KEY
        with _Stub(
            status=401,
            payload=_refusal("invalid x-api-key", kind="authentication_error"),
        ) as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _run(repo, env)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "invalid x-api-key" in r.stderr
        assert '{"type"' not in r.stderr, "the raw envelope was dumped, not the message"

    def test_a_key_from_the_secrets_file_is_probed_too(
        self, repo: Path, tmp_path: Path
    ):
        """The `.env` branch had the same gap: it returned on non-empty."""
        (repo / ".env").write_text(f"ANTHROPIC_API_KEY={KEY}\n")
        env = _no_ant(tmp_path, _clean_env())
        with _Stub(status=400, payload=_refusal(CREDIT_MESSAGE)) as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _run(repo, env)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "credit balance is too low" in r.stderr
        assert KEY not in r.stdout + r.stderr

    def test_an_accepted_key_from_the_secrets_file_says_so(
        self, repo: Path, tmp_path: Path
    ):
        (repo / ".env").write_text(f"ANTHROPIC_API_KEY={KEY}\n")
        env = _no_ant(tmp_path, _clean_env())
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _run(repo, env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "secrets file" in r.stdout
        assert KEY not in r.stdout + r.stderr

    def test_no_env_file_still_refuses_to_read_it(self, repo: Path, tmp_path: Path):
        (repo / ".env").write_text(f"ANTHROPIC_API_KEY={KEY}\n")
        env = _no_ant(tmp_path, _clean_env())
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _run(repo, env, "--no-env-file")
        assert r.returncode == 3, r.stdout + r.stderr
        assert stub.requests == []


class TestUnreachableIsNotRefused:
    def test_a_closed_endpoint_is_exit_2(self, repo: Path, tmp_path: Path):
        """An offline or sandboxed runner must not be told its billing lapsed.
        The operator's next action differs, so the exit code does too: 2 is this
        script's infrastructure failure, 3 is 'fix your credential'."""
        env = _no_ant(tmp_path, _clean_env())
        env["ANTHROPIC_API_KEY"] = KEY
        with _Stub() as stub:
            closed = stub.url  # bound, then released on exit — nothing listens
        env["ANTHROPIC_BASE_URL"] = closed
        r = _run(repo, env)
        assert r.returncode == 2, r.stdout + r.stderr
        assert "could not reach" in r.stderr
        assert "REFUSED" not in r.stderr
        assert KEY not in r.stdout + r.stderr


class TestTheJwtProfile:
    """The hand-maintained JWT branch is now the general case: the endpoint is
    asked, and its answer is quoted. The profile is still last, and still loses
    to a key from either of the two sources ahead of it."""

    def test_the_profile_is_probed_on_bearer_with_the_oauth_beta(
        self, repo: Path, tmp_path: Path
    ):
        env = _with_ant(tmp_path, _clean_env())
        with _Stub(
            status=401,
            payload=_refusal(
                "jwt auth is not yet supported on count_tokens",
                kind="authentication_error",
            ),
        ) as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _run(repo, env)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "jwt auth is not yet supported" in r.stderr
        assert "fake-jwt-token" not in r.stdout + r.stderr
        sent = stub.requests[0]
        assert sent["headers"]["authorization"] == "Bearer fake-jwt-token"
        assert sent["headers"]["anthropic-beta"] == "oauth-2025-04-20"
        assert "x-api-key" not in sent["headers"]

    def test_a_secrets_file_key_still_beats_the_profile(
        self, repo: Path, tmp_path: Path
    ):
        """The order #144 established: on a machine with the `ant` CLI the
        broken credential used to win and a good key in .env was never reached.
        Only the first source that resolves is probed, because only the first
        one the run would use."""
        (repo / ".env").write_text(f"ANTHROPIC_API_KEY={KEY}\n")
        env = _with_ant(tmp_path, _clean_env())
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _run(repo, env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert stub.requests[0]["headers"]["x-api-key"] == KEY


class TestExactAnnouncesTheSourceItResolved:
    """The announcements are the other half of ctx_resolve_credential's contract.

    They used to sit inside the branch that selected the source, where they
    could not drift from it. They now hang off a `case` switching on a string
    that branch sets 200 lines earlier, so a renamed label silently deletes
    them — and both are load-bearing: the INFO line is how an interactive run
    learns it read a key out of `.env` (which `--no-env-file` exists to
    refuse), and the WARN is the only warning that an `ant` profile will 401
    and quietly downgrade the row.
    """

    def test_the_secrets_file_source_says_so(self, repo: Path, tmp_path: Path):
        (repo / ".env").write_text(f"ANTHROPIC_API_KEY={KEY}\n")
        env = _no_ant(tmp_path, _clean_env())
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _run_exact(repo, env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "read ANTHROPIC_API_KEY from a repo-root secrets file" in r.stderr
        assert "--no-env-file" in r.stderr, "the announcement omits how to refuse it"
        assert KEY not in r.stdout + r.stderr
        # The announcement has to be about a credential that was actually used,
        # or it is only evidence that some string was printed.
        assert json.loads(r.stdout)["policy"]["tokens_exact"] is True
        assert stub.requests[0]["headers"]["x-api-key"] == KEY

    def test_the_profile_source_warns_about_jwt(self, repo: Path, tmp_path: Path):
        env = _with_ant(tmp_path, _clean_env())
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _run_exact(repo, env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "falling back to the `ant auth` profile" in r.stderr
        assert "yet accept JWT auth" in r.stderr
        assert "fake-jwt-token" not in r.stdout + r.stderr
        assert stub.requests[0]["headers"]["authorization"] == "Bearer fake-jwt-token"

    def test_the_environment_source_announces_nothing(self, repo: Path, tmp_path: Path):
        """The silent default, pinned so a later `*)` arm cannot start
        narrating the ordinary case into every scheduled run's log."""
        env = _no_ant(tmp_path, _clean_env())
        env["ANTHROPIC_API_KEY"] = KEY
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _run_exact(repo, env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "secrets file" not in r.stderr
        assert "ant auth" not in r.stderr

    def test_no_credential_says_what_the_row_will_record(
        self, repo: Path, tmp_path: Path
    ):
        env = _no_ant(tmp_path, _clean_env())
        r = _run_exact(repo, env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "using offline estimate" in r.stderr
        assert "tokens_exact=false" in r.stderr
        assert json.loads(r.stdout)["policy"]["tokens_exact"] is False


class TestOneRequestDefinition:
    """The root cause was two implementations of one question. Keep them one."""

    def test_the_preflight_and_the_counts_share_the_request(self):
        script = MEASURE.read_text()
        assert script.count("/v1/messages/count_tokens") == 1, (
            "the count_tokens URL is built in more than one place, so the "
            "preflight can again answer for a request the run never makes"
        )
        assert script.count("ctx_write_count_py ") == 2, (
            "the preflight and the per-file counts no longer both write their "
            "request from ctx_write_count_py"
        )
