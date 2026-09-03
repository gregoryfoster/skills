"""Knob-file parsing in _context-lib.sh (#132).

A knob file is read once and believed by three surfaces at once — the weekly
measurement, the write guard and the review delta — so a file the library
cannot understand must produce NO number, not a DIFFERENT one.

`ctx_read_num_knob` used `head -1 | tr -dc '0-9'`, which does not parse a
number: it deletes every non-digit and concatenates what is left. `v2 6000`
became 26000, a budget four times the intended one, and the ledger row then
recorded `over_budget: false` — compliance that was never achieved. The same
shape lived in `ctx_read_str_knob` (all whitespace stripped, so `my docs`
became `mydocs`) and in `ctx_bytes_per_token_x100` (`v2 3.5` became 23.5
bytes per token, which passes the plausibility floor and under-counts every
file measured with it).

The fix is parse-then-validate, and the warning matters as much as the
fallback: silence is what lets a wrong budget persist across every future
weekly row. Note the deliberate asymmetry with #126 — a malformed knob FILE
degrades to the default and says so, while a malformed --budget FLAG is a
typo and is refused outright by the callers that accept one.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "curating-context"
    / "scripts"
)
LIB = SCRIPTS / "_context-lib.sh"
MEASURE = SCRIPTS / "measure-context.sh"

POLICY_LINE = "- a policy line naming `some/path.py` and explaining why\n"


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in (
        "CONTEXT_BUDGET",
        "CONTEXT_DOC_BUDGET",
        "CONTEXT_DOCS_DIR",
        "CTX_BPT_X100",
    ):
        env.pop(k, None)
    return env


def _call(func: str, *args: str) -> subprocess.CompletedProcess:
    """Source the library and call one function with the given arguments."""
    return subprocess.run(
        [
            "bash",
            "-c",
            '. "$1"; shift; fn="$1"; shift; "$fn" "$@"',
            "lib",
            str(LIB),
            func,
            *args,
        ],
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=30,
    )


def _knob(tmp_path: Path, name: str, content: str) -> Path:
    d = tmp_path / ".skills"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_text(content)
    return p


class TestNumKnobIsParsedNotStripped:
    @pytest.mark.parametrize(
        "content,expected",
        [
            ("6000\n", "6000"),  # the ordinary case
            ("6000", "6000"),  # no trailing newline
            ("  6000\n", "6000"),  # leading space
            ("6000 # tokens\n", "6000"),  # the tolerance worth keeping
            # Was 60008000. The trailing words are indistinguishable from an
            # annotation without a comment marker, so the first token wins — the
            # defect was the concatenation, not the leniency.
            ("6000 or 8000\n", "6000"),
            ("6000\r\n", "6000"),  # CRLF
            ("6000\n8000\n", "6000"),  # first line only
        ],
    )
    def test_a_readable_knob_still_reads(self, tmp_path, content, expected):
        f = _knob(tmp_path, "context-budget", content)
        r = _call("ctx_read_num_knob", "", "", str(f), "1234")
        assert r.returncode == 0, r.stderr
        assert r.stdout == expected, r.stdout
        assert r.stderr == "", r.stderr

    @pytest.mark.parametrize(
        "content",
        [
            "v2 6000\n",  # the reported case: was 26000
            "4,000\n",  # was 4000, by luck; ambiguous, so refused now
            "six thousand\n",
            "",  # a file that exists and says nothing
            "\n",
            "   \n",
        ],
    )
    def test_an_unparseable_knob_falls_back_and_says_so(self, tmp_path, content):
        f = _knob(tmp_path, "context-budget", content)
        r = _call("ctx_read_num_knob", "", "", str(f), "1234")
        assert r.returncode == 0, r.stderr
        assert r.stdout == "1234", r.stdout
        assert "WARN" in r.stderr and str(f) in r.stderr, r.stderr
        assert "1234" in r.stderr, r.stderr

    def test_a_missing_knob_is_not_a_complaint(self, tmp_path):
        """No knob is the normal state for most repos; only an unreadable one
        is worth a line of stderr."""
        r = _call(
            "ctx_read_num_knob",
            "",
            "",
            str(tmp_path / ".skills" / "context-budget"),
            "1234",
        )
        assert r.stdout == "1234"
        assert r.stderr == "", r.stderr

    def test_the_precedence_is_unchanged(self, tmp_path):
        f = _knob(tmp_path, "context-budget", "6000\n")
        assert _call("ctx_read_num_knob", "", "999", str(f), "1234").stdout == "999"
        assert _call("ctx_read_num_knob", "42", "999", str(f), "1234").stdout == "42"

    @pytest.mark.parametrize("override,env", [("4,000", ""), ("", "4,000")])
    def test_a_malformed_override_still_falls_back(self, tmp_path, override, env):
        """The flag layer refuses a malformed --budget outright (#126); this
        function is the last line of defence for a caller that does not."""
        assert _call("ctx_read_num_knob", override, env, "", "1234").stdout == "1234"


class TestNumKnobEndToEnd:
    def test_the_issue_reproduction(self, tmp_path):
        """`v2 6000` in the knob measured against 26000 and reported an
        over-budget policy file as compliant."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(
            ["git", "-C", str(repo), "init", "-q"],
            check=True,
            capture_output=True,
            env=_clean_env(),
        )
        (repo / "AGENTS.md").write_text(POLICY_LINE * 2000)
        _knob(repo, "context-budget", "v2 6000\n")
        r = subprocess.run(
            ["bash", str(MEASURE), "--no-write"],
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=_clean_env(),
            timeout=60,
        )
        assert r.returncode == 0, r.stderr
        policy = json.loads(r.stdout)["policy"]
        assert policy["budget"] == 6000, policy
        assert policy["over_budget"] is True, policy
        assert "WARN" in r.stderr and "context-budget" in r.stderr, r.stderr


class TestStrKnobRejectsRatherThanStrips:
    @pytest.mark.parametrize(
        "content,expected",
        [
            ("documentation\n", "documentation"),
            ("  documentation  \n", "documentation"),
            ("documentation\r\n", "documentation"),
            ("./documentation/\n", "documentation"),
            ("a/b\n", "a/b"),
        ],
    )
    def test_a_readable_knob_still_reads(self, tmp_path, content, expected):
        f = _knob(tmp_path, "context-docs-dir", content)
        r = _call("ctx_read_str_knob", "", "", str(f), "docs")
        assert r.returncode == 0, r.stderr
        assert r.stdout == expected, r.stdout
        assert r.stderr == "", r.stderr

    @pytest.mark.parametrize(
        "content",
        [
            "my docs\n",  # was "mydocs" — a directory that does not exist
            "documentation # ref\n",  # was "documentation#ref"
            "/abs/documentation\n",  # already refused, now audibly
            "",
            "  \n",
        ],
    )
    def test_an_unusable_knob_falls_back_and_says_so(self, tmp_path, content):
        f = _knob(tmp_path, "context-docs-dir", content)
        r = _call("ctx_read_str_knob", "", "", str(f), "docs")
        assert r.returncode == 0, r.stderr
        assert r.stdout == "docs", r.stdout
        assert "WARN" in r.stderr and str(f) in r.stderr, r.stderr

    def test_a_missing_knob_is_not_a_complaint(self, tmp_path):
        r = _call(
            "ctx_read_str_knob",
            "",
            "",
            str(tmp_path / ".skills" / "context-docs-dir"),
            "docs",
        )
        assert r.stdout == "docs"
        assert r.stderr == "", r.stderr

    def test_the_precedence_is_unchanged(self, tmp_path):
        f = _knob(tmp_path, "context-docs-dir", "documentation\n")
        assert (
            _call("ctx_read_str_knob", "", "reference", str(f), "docs").stdout
            == "reference"
        )
        assert (
            _call("ctx_read_str_knob", "guide", "reference", str(f), "docs").stdout
            == "guide"
        )

    def test_docs_dir_reads_the_knob_through_the_same_path(self, tmp_path):
        _knob(tmp_path, "context-docs-dir", "documentation\n")
        assert _call("ctx_docs_dir", str(tmp_path)).stdout == "documentation"


class TestTokenRatioIsParsedNotStripped:
    """The same defect, one function down: the ratio divides every byte count
    in every surface, and a mutated one is plausible enough to survive the
    >= 1.00 floor."""

    @pytest.mark.parametrize(
        "content,expected",
        [
            ("2.70\n", "270"),
            ("3\n", "300"),
            ("2.7\n", "270"),
            ("3.5 # measured 2026-08-11\n", "350"),
        ],
    )
    def test_a_readable_ratio_still_reads(self, tmp_path, content, expected):
        _knob(tmp_path, "context-token-ratio", content)
        r = _call("ctx_bytes_per_token_x100", str(tmp_path))
        assert r.returncode == 0, r.stderr
        assert r.stdout == expected, r.stdout
        assert r.stderr == "", r.stderr

    @pytest.mark.parametrize(
        "content",
        [
            "v2 3.5\n",  # was 23.5 bytes/token: plausible, and 8x wrong
            "2.7.1\n",  # already fell back, silently
            "abc\n",
            "0.5\n",  # implausible: under one byte per token
            "",
        ],
    )
    def test_an_unusable_ratio_falls_back_and_says_so(self, tmp_path, content):
        _knob(tmp_path, "context-token-ratio", content)
        r = _call("ctx_bytes_per_token_x100", str(tmp_path))
        assert r.returncode == 0, r.stderr
        assert r.stdout == "270", r.stdout
        assert "WARN" in r.stderr and "context-token-ratio" in r.stderr, r.stderr

    def test_a_missing_ratio_is_not_a_complaint(self, tmp_path):
        r = _call("ctx_bytes_per_token_x100", str(tmp_path))
        assert r.stdout == "270"
        assert r.stderr == "", r.stderr
