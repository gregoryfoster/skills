#!/usr/bin/env python3
"""A standard-library client for TypeSafe's System One endpoint, shared by skill scripts.

Import it; don't run it (`--help` prints this text). Stdlib only, Python 3.9+.
gregoryfoster/skills#448 is the spec, and the epic it serves is #451.

    sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python3 -I` drops it
    import _typesafe

    try:
        client = _typesafe.connect()
    except _typesafe.Skipped as s:
        print(s.line, file=sys.stderr)  # one line naming which skip; the step didn't run
    else:
        try:
            reply = client.ask(state, {"stale": {"type": "noul", "instructions": "..."}})
        except _typesafe.TypeSafeError as e:
            print(e, file=sys.stderr)  # advisory: the host's exit code is untouched
        else:
            print(reply["answers"]["stale"]["noul"])

**The canonical copy is `scripts/_typesafe.py` at the skills repo root.** A
skill that uses it carries its own byte-equal copy in its `scripts/`, because a
skill is vendored on its own and can't import another's.
`tests/structural/test_typesafe_copies.py` holds every copy to the canonical
one. Edit the root copy and re-copy. Never edit a copy in place.

**Opt-in, per repo, default off.** Judged text leaves the machine, so nothing is
sent until a repo opts in. The env var `TYPESAFE_OPT_IN` (`on` or `off`) wins;
set but empty, it counts as unset, as the shell resolvers read an empty
override. Otherwise `.skills/typesafe` is read: one word, `on` or `off`, `#`
comments allowed. Absent means off. The file is read from the *primary*
checkout, as the other `.skills/` resolvers read it (#180, #188, #202), so an
untracked opt-in is seen from a linked worktree too. Any other value reads as
off, and the skip line names the value.

**The key** comes from `TYPESAFE_API_KEY` in the environment only. It's never
logged, never put in an argument, and never in an error message: every message
this module builds is redacted against it.

**Skips go through the API, never an exit code.** `connect()` raises `Skipped`
with `reason` set to `not-opted-in` or `no-key`, and `.line` holds the single
line to print. Exit 3 already means a finding or a loss in several scripts, and
`prove-no-loss.sh` is among them, so a skip that exited 3 would read as content
loss. A pass inside an existing script prints `.line` to stderr and leaves that
script's exit code alone (the epic's boundary rule: every TypeSafe step is
advisory). A new standalone script documents its own skip code, distinct from
its other codes.

**Failures** raise `TypeSafeError`, carrying `.status` (None when nothing came
back), `.error_type` (the API's own code, when it sent one) and the server's own
message from the response body, which `str(HTTPError)` alone would drop. A
failure is advisory too: a pass inside an existing script prints it and leaves
that script's exit code alone, exactly as for a skip. Only a new standalone
script maps it to exit 2. `RequestTooLarge` is the size guard's refusal, raised
before anything is sent.

**Retries.** `408`, `429`, any 5xx (`529 Overloaded` among them), and failures
to connect or read are retried. There are at most `MAX_ATTEMPTS` attempts,
waiting `retry-after-ms` or `retry-after` when the response sends one and
doubling backoff otherwise, and never more than `MAX_WAIT` seconds of waiting
in total. Nothing else is retried. `400`, `401`, `413`, `415` and `422` mean the
request, or its key, is wrong, and a redirect is refused, never followed. A
timeout or a dropped connection can come after the server has the request, so
a retry can bill one judgment twice. The SDK accepts the same cost.

**Size guard.** Jev takes 64k tokens per request (state plus every question)
and 32k per question (state plus any one question). The client sees bytes, not
tokens, so it estimates conservatively at `BYTES_PER_TOKEN`, plus a fixed
`OVERHEAD_TOKENS`, and refuses an oversize request before sending it. It never
sends the long-context header.

**The model is pinned** to `MODEL`. `model=` overrides it, for evaluation runs
only. Each answer echoes the model that actually answered on stderr.
"""

from __future__ import annotations

import datetime
import email.utils
import http.client
import json
import math
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"
OPT_IN_ENV = "TYPESAFE_OPT_IN"
KNOB = ".skills/typesafe"
KEY_ENV = "TYPESAFE_API_KEY"

TIMEOUT = 30.0  # seconds per attempt
MAX_ATTEMPTS = 3
BACKOFF_INITIAL = 0.5
BACKOFF_MAX = 5.0
MAX_WAIT = 30.0  # seconds of waiting between attempts, all retries together
RETRYABLE = frozenset({408, 429, *range(500, 600)})

PER_REQUEST_TOKENS = 64_000
PER_QUESTION_TOKENS = 32_000
# Measured 2026-10-19 against jev-1.13.0, as an input-token delta over a
# one-character state: 3.7-4.0 bytes per token for prose, Python and bash, and
# 273 tokens for the smallest request. 3 bytes per token overestimates by about
# a quarter, so the guard refuses early rather than paying for a server 400.
BYTES_PER_TOKEN = 3.0
OVERHEAD_TOKENS = 300
ERROR_BODY_CHARS = 2000

USER_AGENT = "gregoryfoster-skills-typesafe/1"


class Skipped(Exception):
    """The step did not run: not opted in, or no key. Not a result, not a failure."""

    def __init__(self, reason: str, detail: str):
        self.reason = reason  # "not-opted-in" | "no-key"
        self.line = f"typesafe: skipped ({reason}): {detail}"
        super().__init__(self.line)


class TypeSafeError(Exception):
    """The call failed: unreachable, or the API said no.

    `.status` is None when nothing came back. `.error_type` is the API's own
    code when it sent one (`max_tokens_exceeded`, `api_usage_error`,
    `authentication_error`), so a caller can branch on it without parsing text.
    """

    def __init__(self, status: int | None, message: str, error_type: str | None = None):
        self.status = status
        self.message = message
        self.error_type = error_type
        where = f"HTTP {status}" if status is not None else "no response"
        super().__init__(f"typesafe: {where}: {message}")


class RequestTooLarge(TypeSafeError):
    """The size guard's refusal. Nothing was sent."""

    def __init__(self, message: str):
        super().__init__(None, message)


# --- opt-in ------------------------------------------------------------------


def _git(args: list[str], cwd: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def project_root(cwd: str | None = None) -> Path | None:
    """The primary checkout holding `cwd`, or None outside a git work tree.

    `--show-toplevel` names the current checkout, which from a linked worktree
    is the worktree, where an untracked knob doesn't exist. The parent of
    `--git-common-dir` is the primary checkout, except inside a submodule,
    where it's `<super>/.git/modules`, so the candidate is kept only if it's a
    checkout sharing that common dir. This is the same guard as
    `resolve-plans-dir.sh`, and it shares that script's one unhandled shape
    (#203): a linked worktree of a submodule falls back to the worktree.
    """
    if cwd is None:
        try:
            cwd = os.getcwd()
        except (
            OSError
        ):  # the directory was deleted under us: outside any checkout (CR 400)
            return None
    top = _git(["rev-parse", "--show-toplevel"], cwd)
    if top is None:
        return None
    common = _git(["rev-parse", "--git-common-dir"], cwd)
    if common is not None:
        common_abs = os.path.realpath(os.path.join(cwd, common))
        candidate = os.path.dirname(common_abs)
        cand_common = _git(["rev-parse", "--git-common-dir"], candidate)
        if (
            cand_common is not None
            and os.path.realpath(os.path.join(candidate, cand_common)) == common_abs
        ):
            return Path(candidate)
    return Path(top)


class _Unreadable(Exception):
    pass


def _knob_word(path: Path) -> str | None:
    """The first non-blank, non-comment line of the knob file, or None if it's absent.

    Read as utf-8-sig, so an editor's byte-order mark doesn't turn `on` into a
    word that reads as off (CR 391). Raises `_Unreadable` naming the cause.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        raise _Unreadable(e.__class__.__name__) from None
    for line in text.splitlines():
        word = line.strip()
        if word and not word.startswith("#"):
            return word
    return ""


def opted_in(environ=None, cwd: str | None = None) -> tuple[bool, str]:
    """(on, where the answer came from). Anything but `on` is off, and says why."""
    environ = os.environ if environ is None else environ
    value = environ.get(OPT_IN_ENV)
    # Empty is unset, as `[[ -n "${PLANS_DIR:-}" ]]` reads it in the shell
    # resolvers, so a template exporting the name blank can't veto the file (CR 387).
    if value is not None and value.strip():
        word = value.strip()
        if word == "on":
            return True, f"{OPT_IN_ENV}=on"
        if word == "off":
            return False, f"{OPT_IN_ENV}=off"
        return False, f"{OPT_IN_ENV}={value!r} is not on or off, so it reads as off"
    root = project_root(cwd)
    if root is None:
        return (
            False,
            f"{OPT_IN_ENV} is unset and there's no git checkout to hold {KNOB}",
        )
    where = root / KNOB
    try:
        word = _knob_word(where)
    except _Unreadable as e:
        return False, f"{where} can't be read ({e}), so it reads as off"
    if word is None:
        return False, f"{OPT_IN_ENV} is unset and {where} is absent"
    if word == "on":
        return True, f"{where} says on"
    if word == "off":
        return False, f"{where} says off"
    return False, f"{where} holds {word!r}, not on or off, so it reads as off"


def connect(
    *,
    model: str = MODEL,
    environ=None,
    cwd: str | None = None,
    transport=None,
    sleep=time.sleep,
    stderr=None,
) -> Client:
    """A client, or `Skipped`. The opt-in is checked first: no key is asked for until a repo opts in."""
    environ = os.environ if environ is None else environ
    on, why = opted_in(environ, cwd)
    if not on:
        # A set env var outranks the file, so only it can turn this on (CR 390).
        where = (
            OPT_IN_ENV
            if why.startswith(f"{OPT_IN_ENV}=")
            else f"{OPT_IN_ENV} or {KNOB}"
        )
        raise Skipped(
            "not-opted-in", f"{why}; set {where} to on to send text to api.typesafe.ai"
        )
    key = (environ.get(KEY_ENV) or "").strip()
    if not key:
        raise Skipped("no-key", f"opted in ({why}), but {KEY_ENV} is unset or empty")
    return Client(key, model=model, transport=transport, sleep=sleep, stderr=stderr)


# --- the call ----------------------------------------------------------------


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Hand a 3xx back as an HTTP answer instead of following it.

    urllib follows a 301, 302 or 303 on a POST by sending a GET with every
    header but the content ones, Authorization included, to whatever host the
    Location names. The API has no reason to redirect a POST, and the key must
    not go anywhere else (CR 386).
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_RefuseRedirects)


def urllib_transport(url: str, data: bytes, headers: dict, timeout: float):
    """POST once. Returns (status, headers, body) for any HTTP answer; raises OSError for none.

    A broken answer (a truncated body, a garbled status line) is an
    `http.client.HTTPException`, which isn't an OSError. It's re-raised as one,
    so it reaches the retry loop and never escapes a caller catching
    `TypeSafeError` (CR 385).
    """
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        try:
            with _OPENER.open(req, timeout=timeout) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except (OSError, http.client.HTTPException):
                body = b""
            return e.code, e.headers, body
    except http.client.HTTPException as e:
        raise OSError(f"{e.__class__.__name__}: {e}") from e


def _encode(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


def estimate_tokens(n_bytes: int) -> int:
    return math.ceil(n_bytes / BYTES_PER_TOKEN)


def _check_size(state, questions: dict) -> None:
    state_tokens = estimate_tokens(len(_encode(state)))
    per_q = {
        name: estimate_tokens(len(_encode({name: q}))) for name, q in questions.items()
    }
    total = OVERHEAD_TOKENS + state_tokens + sum(per_q.values())
    if total > PER_REQUEST_TOKENS:
        raise RequestTooLarge(
            f"request estimated at {total:,} tokens, over the {PER_REQUEST_TOKENS:,} "
            f"per-request limit (state {state_tokens:,}, {len(per_q)} questions "
            f"{sum(per_q.values()):,}). The estimate counts {BYTES_PER_TOKEN:g} bytes "
            "per token, which overestimates on purpose. Split the questions or the state"
        )
    name, biggest = max(per_q.items(), key=lambda kv: kv[1])
    one = OVERHEAD_TOKENS + state_tokens + biggest
    if one > PER_QUESTION_TOKENS:
        raise RequestTooLarge(
            f"question {name!r} estimated at {one:,} tokens with the state, over the "
            f"{PER_QUESTION_TOKENS:,} per-question limit (state {state_tokens:,}). "
            f"The estimate counts {BYTES_PER_TOKEN:g} bytes per token, which "
            "overestimates on purpose. Shorten the state"
        )


def _server_message(body: bytes) -> tuple[str, str | None]:
    """(what the server said, its error_type or None), from the body.

    The API answers `{"detail": {"error_type": ..., "message": ...}}` for a 400
    or 401 [measured 2026-10-19], and FastAPI's list of `{loc, msg}` for a 422,
    rendered as `loc: msg`. A string `detail` or a non-JSON body is kept as is
    (CR 394).
    """
    text = body.decode("utf-8", errors="replace").strip()
    error_type = None
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict) and "detail" in parsed:
        detail = parsed["detail"]
        if isinstance(detail, list) and all(isinstance(d, dict) for d in detail):
            text = "; ".join(
                f"{'.'.join(str(p) for p in d.get('loc', []))}: {d.get('msg', '')}"
                for d in detail
            )
        elif isinstance(detail, dict) and isinstance(detail.get("error_type"), str):
            error_type = detail["error_type"]
            message = detail.get("message")
            text = f"{message} ({error_type})" if message else error_type
        elif isinstance(detail, str):
            text = detail
        else:
            text = json.dumps(detail)
    if not text:
        text = "(empty body)"
    if len(text) > ERROR_BODY_CHARS:
        text = f"{text[:ERROR_BODY_CHARS]}... ({len(text) - ERROR_BODY_CHARS} more characters)"
    return text, error_type


def _retry_after(headers) -> float | None:
    """Seconds the server asked us to wait, from `retry-after-ms` or `retry-after`, else None."""
    lower = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    ms = lower.get("retry-after-ms")
    if ms is not None:
        try:
            return max(0.0, float(ms) / 1000)
        except ValueError:
            pass
    value = lower.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:  # a `-0000` zone parses naive; HTTP dates are UTC (CR 388)
        when = when.replace(tzinfo=datetime.timezone.utc)
    return max(0.0, when.timestamp() - time.time())


class Client:
    """One key, one model. `ask()` is the only call."""

    def __init__(
        self,
        key: str,
        *,
        model: str = MODEL,
        transport=None,
        sleep=time.sleep,
        stderr=None,
    ):
        self._key = key
        self.model = model
        self._transport = transport or urllib_transport
        self._sleep = sleep
        self._stderr = stderr

    def __repr__(self) -> str:
        return f"Client(model={self.model!r})"

    def _say(self, line: str) -> None:
        print(self._redact(line), file=self._stderr or sys.stderr)

    def _redact(self, text: str) -> str:
        return text.replace(self._key, "[redacted]") if self._key else text

    def _error(
        self, status: int | None, message: str, error_type: str | None = None
    ) -> TypeSafeError:
        # Redacted here because the server can echo anything back, the key included.
        return TypeSafeError(status, self._redact(message), error_type)

    def ask(self, state, questions: dict) -> dict:
        """POST state and named questions. Returns the response object, with `answers` keyed by name."""
        # String names only: JSON turns 1 into "1", and the answer check would
        # then compare the two and crash in sorted() (CR 401).
        if (
            not isinstance(questions, dict)
            or not questions
            or not all(isinstance(name, str) for name in questions)
        ):
            raise TypeSafeError(
                None, "questions must be a non-empty object of string-named questions"
            )
        try:
            data = _encode(
                {"model": self.model, "state": state, "questions": questions}
            )
        except (
            TypeError,
            ValueError,
        ) as e:  # NaN, Infinity, or a value JSON can't hold
            raise TypeSafeError(
                None, f"request isn't valid JSON for the API: {e}"
            ) from None
        _check_size(state, questions)
        # http.client refuses a header value with a newline, and its ValueError
        # quotes the whole "Bearer <key>" (CR 399). Refuse first, without the key.
        if not self._key.isascii() or not all(
            c.isprintable() and not c.isspace() for c in self._key
        ):
            raise TypeSafeError(
                None,
                f"{KEY_ENV} holds whitespace, a control character or non-ASCII, which "
                "an HTTP header can't carry. Check how the key was copied",
            )
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        waited = 0.0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                status, resp_headers, body = self._transport(
                    ENDPOINT, data, headers, TIMEOUT
                )
            except (ValueError, UnicodeError) as e:
                # A request the transport won't build: not transient, and its
                # message can quote a header, so it's redacted (CR 399).
                raise self._error(None, f"couldn't build the request: {e}") from None
            except OSError as e:
                if isinstance(getattr(e, "reason", e), ssl.SSLCertVerificationError):
                    # Not transient, so not retried (CR 397). On macOS a
                    # python.org build without its certificates is the usual cause.
                    raise self._error(
                        None,
                        f"couldn't verify api.typesafe.ai's certificate: {e}. Check "
                        "this Python's CA bundle (on macOS, a python.org build's "
                        "'Install Certificates.command')",
                    ) from None
                status, resp_headers = None, None
                err = self._error(None, f"couldn't reach api.typesafe.ai: {e}")
            else:
                if status == 200:
                    return self._parse(body, questions)
                err = self._error(status, *_server_message(body))
            if status is not None and status not in RETRYABLE:
                raise err
            if attempt == MAX_ATTEMPTS:
                raise TypeSafeError(
                    err.status,
                    f"{err.message} (gave up after {attempt} attempts)",
                    err.error_type,
                )
            delay = _retry_after(resp_headers)
            if delay is None:
                delay = min(BACKOFF_MAX, BACKOFF_INITIAL * 2 ** (attempt - 1))
            if waited + delay > MAX_WAIT:
                raise TypeSafeError(
                    err.status,
                    f"{err.message} (not retried: waiting {delay:g} s more would pass "
                    f"the {MAX_WAIT:g} s retry budget)",
                    err.error_type,
                )
            what = f"HTTP {status}" if status is not None else "no response"
            self._say(
                f"typesafe: {what}, retrying in {delay:g} s (attempt {attempt + 1} of {MAX_ATTEMPTS})"
            )
            self._sleep(delay)
            waited += delay
        raise AssertionError("unreachable")  # pragma: no cover

    def _parse(self, body: bytes, questions: dict) -> dict:
        try:
            reply = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise self._error(200, f"response isn't JSON: {e}") from None
        if not isinstance(reply, dict) or not isinstance(reply.get("answers"), dict):
            raise self._error(
                200, f"response has no answers object: {_server_message(body)[0]}"
            )
        missing = sorted(set(questions) - set(reply["answers"]))
        if missing:
            raise self._error(200, f"response has no answer for {', '.join(missing)}")
        usage = reply.get("usage") if isinstance(reply.get("usage"), dict) else {}
        tokens = usage.get("input_tokens", "?")
        self._say(
            f"typesafe: answered by {reply.get('model', '<no model field>')} "
            f"(asked for {self.model}), {tokens} input tokens"
        )
        return reply


def main(argv: list[str]) -> int:
    if argv in (["--help"], ["-h"]):
        print(__doc__.strip())
        return 0
    print(
        "usage: python3 _typesafe.py --help\n"
        "This is a library. Import it from a skill script; see --help.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
