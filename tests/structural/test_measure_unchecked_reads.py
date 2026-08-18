"""#184 — the three reads in measure-context.sh that #157 did not cover.

#157 fixed the doc inventory. Three reads of a caller-supplied path were left
using a bare `<"$f"` redirect, and each fails in a different, worse way. All
three were reproduced by execution before this file was written; the notes
below record what was actually observed, not what the issue predicted.

1. The policy file (`P_LINES`/`P_BYTES`)
   Observed: `measure-context.sh: line 475: AGENTS.md: Permission denied`,
   empty stdout, **exit 1**. Only ONE such line, not two — `set -e` aborts on
   the first assignment, so the second redirect never runs. The script's header
   promises "Exit 2 on infrastructure failure so a caller can never mistake a
   broken measurement for a clean one", so a caller that distinguishes 2 from
   everything else reads a broken measurement as a usage error.

2. `est_tokens`
   The issue predicted a raw bash error reaching a hook. What actually happens
   is worse and quieter. The read sits in a command substitution in ARGUMENT
   position — `ctx_est_tokens_for "$ROOT" "$1" "$(wc -c <"$1")"` — a position
   errexit does not check. So the failure does not abort anything: the third
   argument arrives empty, `ctx_est_tokens_for` coerces a non-numeric byte
   count to 0, and the file is priced at **0 tokens** with `tokens_source:
   "repo"`. Reproduced against a doc: exit 0, a full JSON object, a row
   reading `"tokens": 0` beside `"bytes": 777`, and `tokens_docs: 0` in the
   totals. A fabricated zero in an artifact that drives budget decisions is
   exactly the "broken measurement mistaken for a clean one" the header
   forbids.

   Guarding it needed a second change. `exit 2` from `est_tokens` reaches only
   its own subshell, because bash runs command substitutions with errexit
   unset; `shopt -s inherit_errexit` is the opt-out and it postdates bash 3.2,
   which is what this machine has. So `count_tokens` forwards the status
   explicitly. Without that, the guard fired and the run continued with an
   empty token count.

3. `slugs_of`'s awk
   Observed, on stderr, immediately before the clean WARN its caller emits:

       awk: can't open file docs/D.md
        source line number 21
       WARN could not read headings from docs/D.md; …

   Its sibling `extract_links` closes with `' "$1" 2>/dev/null || rc=$?` and
   leaks nothing. Confirmed by execution in the same run: one awk spoke over
   the top of its own diagnosis, the other did not.

Reachability, stated honestly
-----------------------------
Sites 1 and 3 are reachable end to end and are tested that way here. Site 2 is
not, and cannot be made so by construction: every path into `est_tokens` reads
the same file moments earlier — the policy through site 1's fix, a doc through
#157's guard — so any condition that fails at `est_tokens` has already failed
upstream. It is guarded anyway, for the reason `extract_links`' unreachable
`unchecked` append is already guarded in this file: the correctness of a read
must not rest on the order of two other reads. Its regression test is therefore
a source-shape assertion rather than an execution, which is what the rest of
this directory does for rules that cannot be provoked.
"""

import os
import re
import subprocess
from pathlib import Path

SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "curating-context"
    / "scripts"
)
MEASURE = SCRIPTS / "measure-context.sh"

POLICY_LINE = "- a policy line naming `some/path.py` and explaining why\n"


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, env=_clean_env(),
    )


def _repo(tmp_path: Path, policy_extra: str = "") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "AGENTS.md").write_text(POLICY_LINE * 50 + policy_extra)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _measure(repo: Path) -> subprocess.CompletedProcess:
    # --no-write, always: the real invocation rewrites .skills/context-token-*.
    return subprocess.run(
        ["bash", str(MEASURE), "--no-write"],
        capture_output=True, text=True, cwd=str(repo),
        env=_clean_env(), timeout=60,
    )


def _fn_code(name: str) -> str:
    """The CODE of one shell function, comments stripped.

    Stripped because each fix documents the shape it replaced, quoting the bare
    `wc -c <"$1"` verbatim — so a rule read over the whole function matches the
    prose explaining the defect and reports the fix as the defect. Same trap the
    #199 journal records for the escape greps: in a file whose job is to explain
    a hazard, the hazard's own name is in the file.
    """
    src = MEASURE.read_text()
    body = src.split(f"\n{name}() {{", 1)[1].split("\n}\n", 1)[0]
    return "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    )


def _stray_bash_lines(stderr: str) -> list[str]:
    """Lines in bash's own voice standing on their own, rather than quoted as
    the cause inside an ERROR/WARN. The #157 rule, applied to this file's
    sites."""
    return [
        line for line in stderr.splitlines()
        if re.search(r"measure-context\.sh: line \d+:", line)
        and not line.startswith(("ERROR", "WARN", "INFO"))
    ]


class TestUnreadablePolicyFile:
    """Site 1. The same defect #157 fixed, one stage earlier, and worse: the
    stage that dies is the one the header's exit-2 promise is about."""

    def _repo(self, tmp_path: Path) -> Path:
        repo = _repo(tmp_path)
        (repo / "AGENTS.md").chmod(0o000)
        return repo

    def test_exits_two_with_no_partial_json(self, tmp_path: Path):
        result = _measure(self._repo(tmp_path))
        assert result.returncode == 2, (
            f"expected exit 2 (infrastructure failure), got {result.returncode}: "
            f"{result.stderr}"
        )
        assert result.stdout.strip() == "", (
            f"emitted partial JSON before failing: {result.stdout!r}"
        )

    def test_the_diagnosis_names_the_file_and_the_stage(self, tmp_path: Path):
        result = _measure(self._repo(tmp_path))
        assert "ERROR could not read AGENTS.md" in result.stderr, result.stderr
        assert "policy file" in result.stderr, result.stderr

    def test_it_is_not_reported_as_an_empty_policy_file(self, tmp_path: Path):
        """A file of 2,750 readable bytes is not empty. Routing an unreadable
        policy into the `no measurable content` branch would exit 2 with a
        message that sends the operator to edit a file that is fine."""
        result = _measure(self._repo(tmp_path))
        assert "no measurable content" not in result.stderr, result.stderr

    def test_bashs_own_words_appear_only_as_the_quoted_cause(self, tmp_path: Path):
        result = _measure(self._repo(tmp_path))
        assert _stray_bash_lines(result.stderr) == [], result.stderr


class TestSlugsOfDoesNotSpeakOverItsOwnDiagnosis:
    """Site 3. `anchor_missing` already prints a clean WARN when `slugs_of`
    fails; awk printed its own two-line complaint in front of it."""

    def _repo(self, tmp_path: Path) -> Path:
        repo = _repo(tmp_path, policy_extra="\n[a](docs/D.md#foo)\n")
        (repo / "docs").mkdir()
        doc = repo / "docs" / "D.md"
        doc.write_text("# D\n\nsome live reference prose\n")
        doc.chmod(0o000)
        return repo

    def test_awk_does_not_leak_its_own_error(self, tmp_path: Path):
        result = _measure(self._repo(tmp_path))
        leaked = [
            line for line in result.stderr.splitlines()
            if line.startswith("awk:") or line.startswith(" source line number")
        ]
        assert leaked == [], (
            f"awk spoke for itself alongside the WARN: {leaked}\n{result.stderr}"
        )

    def test_the_warn_still_fires_and_carries_the_cause(self, tmp_path: Path):
        """Suppressing awk's stderr must not also discard it. #157's rule: the
        text bash or awk produced is the truest description of the cause, so it
        is quoted inside the diagnosis rather than dropped."""
        result = _measure(self._repo(tmp_path))
        warn = [
            line for line in result.stderr.splitlines()
            if line.startswith("WARN could not read headings from docs/D.md")
        ]
        assert len(warn) == 1, result.stderr
        assert "can't open file" in warn[0], warn[0]


class TestEstTokensReadIsChecked:
    """Site 2, guarded but unreachable — see this module's docstring. Asserted
    on the source, the way the rest of this directory asserts rules that cannot
    be provoked from outside."""

    def test_no_bare_redirect_remains_in_est_tokens(self):
        body = _fn_code("est_tokens")
        assert 'wc -c <"$1"' not in body, (
            "est_tokens still reads its argument through an unchecked bare "
            "redirect; a failure here prices the file at 0 tokens and reports "
            f"a clean run:\n{body}"
        )

    def test_the_error_redirect_precedes_the_input_redirect(self):
        """Bash applies redirections left to right, and the INPUT redirect is
        the one that fails. Set up after `2>`, its diagnosis lands in the
        capture file; set up before, bash writes `Permission denied` to the
        terminal and the capture file is empty — verified experimentally, both
        orderings, before this assertion was written."""
        body = _fn_code("est_tokens")
        reads = [m for m in re.finditer(r"wc [^\n]*<\"\$1\"", body)]
        assert reads, f"est_tokens no longer reads $1 at all:\n{body}"
        for m in reads:
            assert re.search(r"2>\"[^\"]+\"\s*<\"\$1\"", m.group(0)), (
                f"`2>` must precede `<` on this read: {m.group(0)!r}"
            )

    def test_a_failed_read_is_not_priced_as_zero_tokens(self):
        """The observed defect: the substitution sits in argument position, so
        errexit never sees it, the byte count arrives empty, and
        ctx_est_tokens_for coerces it to 0. The guard must exit 2 rather than
        hand a number downstream."""
        body = _fn_code("est_tokens")
        assert "exit 2" in body, (
            f"est_tokens has no infrastructure-failure exit:\n{body}"
        )

    def test_count_tokens_forwards_the_refusal(self):
        """The half of the fix that is easy to lose. `exit 2` inside a command
        substitution reaches only that subshell: bash runs command substitutions
        with errexit UNSET, and the opt-out (`shopt -s inherit_errexit`) does
        not exist before bash 4.4 — this machine runs 3.2, so it is not
        available at all. Measured without the forward: the guard fired, the run
        continued with an empty token count, printed `[: : integer expression
        expected`, and died several stages later on an unrelated awk."""
        body = _fn_code("count_tokens")
        assert re.search(r'est_out="\$\(est_tokens "\$f"\)"\s*\|\|\s*exit', body), (
            "count_tokens swallows est_tokens' exit; the guard fires and the "
            f"run carries on with no token count:\n{body}"
        )
