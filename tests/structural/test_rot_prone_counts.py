"""#258 — a bare number in a policy file rots, and no gate had an opinion about it.

`AGENTS.md` on `CannObserv/power-map` carried "**180** `hx-get` reveals mean the
forms don't exist without JS anyway". Three parties measured that same claim in
one week:

| Source | Count |
|---|---|
| The original claim | **180** |
| A `curating-context` run's own agent | **189** |
| `grep -ro 'hx-get' src/templates/ \\| wc -l` | **182** |

Nobody was wrong. The sentence never said *what* was counted — occurrences or
lines, templates only or Python too — so three reasonable methods produced three
answers and none could be checked against the sentence. A number that cannot be
reproduced cannot be maintained, and it is worse than no number, because it reads
as precise.

Five sibling counts in the same file were correct only by luck of nothing having
changed. One was not: "the three a11y test tiers" had been wrong since a fourth
tier landed, and the doc that owns the subject said four the whole time.

**Nothing in the surface saw this class.** `prove-no-loss.sh` compares claims,
not their arithmetic — "six audits" surviving a move is a preserved claim
whether or not six is true. `check-seams.sh` sweeps cross-references, and a count
is not a reference. The budget cadence reports the total and cannot say a number
*inside* the file is stale. And a curation run is exactly when it gets worse: an
agent rewriting a section faithfully carries a number forward, and may re-measure
it by a different method than the original author used, which is how the 189
appeared.

A count earns its place in exactly one of three forms — attach the command that
re-derives it, drop the precision, or make it a gate — and `check-counts.sh`
reports against those three.

What this file pins, and why each is a mechanism rather than a spelling:

- **Per CLAUSE, not per line.** Policy-file lines run long; a per-line check let
  one properly re-derived count shelter every bare one beside it. And clauses
  are found in the JOINED paragraph, because a hard wrap falling between a
  number and its command would otherwise break the exemption that earns it.
- **Bare digits are deliberately out of scope.** In a policy file they are
  overwhelmingly status codes, ports, standards and versions, and a gate that
  cries wolf on `403` and `ISO 8601` is a gate someone deletes. The gap is real
  and stays documented rather than closed.
- **`one` is excluded.** It reads as "a single", not a tally.
- **A counting command in the clause is an automatic pass.** That is form 1, and
  needing an acknowledgement for it would tax the remedy.
- **The acknowledgement vocabulary is closed, and class-scoped.** A warrant that
  merely failed to match would report as an ordinary hit and send the reader to
  re-judge a line they already judged.
- **The index bound is a PROPERTY, not a diff.** "The index cannot grow" is
  unenforceable, since adding a doc must be allowed. A delta-vs-`HEAD` check
  goes quiet the moment the growth is committed.
- **This repo's own `AGENTS.md` passes.** A rule the author is exempt from is
  not a rule.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "skills" / "curating-context" / "scripts"
CHECK = SCRIPTS / "check-counts.sh"
RECORD = SCRIPTS / "record-telemetry.sh"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — a linked worktree shares .git/config
    with its main checkout, so a fixture-creating git command that inherits
    them reaches out of the fixture and writes the wrong repo (#189)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _repo(tmp_path: Path, policy: str, ack: str | None = None) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "init", "-q"],
        check=True,
        capture_output=True,
        env=_clean_env(),
        timeout=60,
    )
    (repo / "AGENTS.md").write_text(policy)
    if ack is not None:
        (repo / ".skills").mkdir(exist_ok=True)
        (repo / ".skills/context-counts-ok").write_text(ack)
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(CHECK), *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=120,
    )


def _counts(result: subprocess.CompletedProcess) -> tuple[int, int]:
    """The machine-readable trailer, read by anchored prefix as the caller does."""
    new = acked = None
    for line in result.stdout.splitlines():
        if line.startswith("counts: "):
            new = int(line.split(": ", 1)[1])
        elif line.startswith("counts_acked: "):
            acked = int(line.split(": ", 1)[1])
    assert new is not None and acked is not None, result.stdout
    return new, acked


class TestWhatIsReported:
    def test_a_cardinal_word_is_a_count(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, "# P\n\nEight scheduled timers keep the tree fresh.\n")
        result = _run(repo)
        assert result.returncode == 3
        assert _counts(result)[0] == 1
        assert "Eight" in result.stdout

    def test_a_digit_qualifying_a_backticked_term_is_a_count(
        self,
        tmp_path: Path,
    ) -> None:
        """The reported shape, bold markers and all."""
        repo = _repo(
            tmp_path,
            "# P\n\n**180** `hx-get` reveals mean the forms "
            "do not exist without JS anyway.\n",
        )
        assert _counts(_run(repo))[0] == 1

    def test_a_bare_digit_is_left_alone(self, tmp_path: Path) -> None:
        """The documented gap, held open on purpose.

        In a policy file a bare digit is overwhelmingly a status code, a port, a
        standard or a version. A gate that cries wolf on those is a gate someone
        deletes, taking the class it was written for with it.
        """
        repo = _repo(
            tmp_path,
            "# P\n\nThe API answers 403 for an expired token, "
            "and timestamps are ISO 8601.\n",
        )
        assert _counts(_run(repo))[0] == 0

    def test_one_is_not_a_tally(self, tmp_path: Path) -> None:
        repo = _repo(
            tmp_path, "# P\n\nThere is one migration path and it is documented.\n"
        )
        assert _counts(_run(repo))[0] == 0

    def test_a_clause_carrying_its_command_needs_no_warrant(
        self,
        tmp_path: Path,
    ) -> None:
        """Form 1, detected rather than declared."""
        repo = _repo(
            tmp_path,
            "# P\n\nSix templates reveal it (`grep -rl hx-get src/ | wc -l`).\n",
        )
        assert _counts(_run(repo))[0] == 0

    def test_the_command_still_counts_across_a_hard_wrap(
        self,
        tmp_path: Path,
    ) -> None:
        """Clauses are found in the joined paragraph, not per line.

        A policy file is wrapped at a column nobody chose for semantic reasons.
        Split per line, the number and the command that re-derives it land in
        different "clauses" whenever the wrap falls between them — and the
        exemption then fails on exactly the sentences that earned it.
        """
        repo = _repo(
            tmp_path,
            "# P\n\nSix templates reveal it, which is what\n"
            "`grep -rl hx-get src/ | wc -l` prints today.\n",
        )
        assert _counts(_run(repo))[0] == 0

    def test_a_bare_count_beside_a_derived_one_is_not_sheltered(
        self,
        tmp_path: Path,
    ) -> None:
        """Per clause, not per line — the first version's actual bug."""
        repo = _repo(
            tmp_path,
            "# P\n\nSix templates reveal it (`grep -rl hx-get src/ | wc -l`); "
            "eight scheduled timers keep it fresh.\n",
        )
        new, _ = _counts(_run(repo))
        assert new == 1, (
            "one properly re-derived count sheltered a bare one on the same line"
        )

    def test_a_table_row_is_its_own_clause(self, tmp_path: Path) -> None:
        """CR round 1, finding 1.

        A table row rarely ends in clause punctuation, so joining consecutive
        rows into one block collapsed a whole table into a single clause — and
        a `wc -l` in one cell then exempted every bare count in the rows below
        it. That is the defect per-clause scanning exists to prevent, at table
        scope, and a table is where a policy file puts exactly this kind of
        claim: this repo's own "Rationalization prevention" is one.
        """
        repo = _repo(
            tmp_path,
            (
                "# P\n\n"
                "| Thought | Reality |\n"
                "|---|---|\n"
                '| "a" | Six templates reveal it (`grep -rl hx-get src/ | wc -l`) |\n'
                '| "b" | Eight scheduled timers keep the tree fresh |\n'
            ),
        )
        new, _ = _counts(_run(repo))
        assert new == 1, (
            "the first row's counting command sheltered the second row's bare "
            "count — the whole table read as one clause"
        )

    def test_a_blockquote_line_is_its_own_clause(self, tmp_path: Path) -> None:
        """CR round 2, finding 13 — finding 1's shape, one construct over.

        A quoted passage merged into the prose around it, so a counting command
        inside the quote could exempt a bare count in the paragraph beneath it.
        """
        repo = _repo(
            tmp_path,
            (
                "# P\n\n"
                "> Six templates reveal it (`grep -rl hx-get src/ | wc -l`)\n\n"
                "Eight scheduled timers keep the tree fresh\n"
            ),
        )
        assert _counts(_run(repo))[0] == 1

    def test_fenced_code_is_skipped(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, "# P\n\n```bash\nrun --workers three --retries 6\n```\n")
        assert _counts(_run(repo))[0] == 0

    def test_the_hit_names_the_line_not_the_paragraph(self, tmp_path: Path) -> None:
        repo = _repo(
            tmp_path,
            "# P\n\nA paragraph opens here and runs on\n"
            "for a while before it mentions eight timers.\n",
        )
        result = _run(repo)
        assert "AGENTS.md:4" in result.stdout, result.stdout


class TestTheIndexBound:
    def test_a_long_index_line_is_reported(self, tmp_path: Path) -> None:
        long_blurb = "- [docs/X.md](docs/X.md) — " + ("clause and clause " * 12)
        repo = _repo(tmp_path, f"# P\n\n## Detail Docs\n\n{long_blurb}\n")
        result = _run(repo)
        assert _counts(result)[0] == 1
        assert "index-line" in result.stdout

    def test_a_short_one_is_not(self, tmp_path: Path) -> None:
        repo = _repo(
            tmp_path,
            "# P\n\n## Detail Docs\n\n- [docs/X.md](docs/X.md) — the X contract\n",
        )
        assert _counts(_run(repo))[0] == 0

    def test_a_new_line_is_allowed_and_only_length_is_bounded(
        self,
        tmp_path: Path,
    ) -> None:
        """The rule is a property, not a delta.

        "The index cannot grow" is unenforceable — adding a doc must be allowed.
        A delta-vs-HEAD check goes quiet the moment the growth is committed, and
        so guards a diff rather than a property.
        """
        repo = _repo(
            tmp_path,
            "# P\n\n## Detail Docs\n\n"
            + "".join(
                f"- [docs/{n}.md](docs/{n}.md) — the {n} contract\n" for n in "abcdefgh"
            ),
        )
        assert _counts(_run(repo))[0] == 0

    def test_a_missing_section_is_said_out_loud(self, tmp_path: Path) -> None:
        """A heuristic that found nothing to check must not read as a clean pass."""
        repo = _repo(tmp_path, "# P\n\nNothing here.\n")
        assert "no 'Detail Docs' section" in _run(repo).stdout

    def test_the_class_can_be_turned_off(self, tmp_path: Path) -> None:
        long_blurb = "- [docs/X.md](docs/X.md) — " + ("clause and clause " * 12)
        repo = _repo(tmp_path, f"# P\n\n## Detail Docs\n\n{long_blurb}\n")
        result = _run(repo, "--index-max", "0")
        assert _counts(result)[0] == 0
        assert "not checked" in result.stdout

    def test_an_index_line_is_judged_once(self, tmp_path: Path) -> None:
        """A long blurb that also states a count is ONE finding.

        Reporting it in both classes would make the acknowledgement grammar
        ambiguous about which remedy was applied.
        """
        blurb = (
            "- [docs/X.md](docs/X.md) — the six recurring integrity audits, "
            + "and clause and clause " * 8
        )
        repo = _repo(tmp_path, f"# P\n\n## Detail Docs\n\n{blurb}\n")
        assert _counts(_run(repo))[0] == 1


class TestTheWarrantVocabulary:
    POLICY = "# P\n\nEight scheduled timers keep the tree fresh.\n"

    def test_a_warranted_count_is_acknowledged(self, tmp_path: Path) -> None:
        repo = _repo(
            tmp_path, self.POLICY, ack="enumerated :: Eight scheduled timers\n"
        )
        result = _run(repo)
        assert result.returncode == 0
        assert _counts(result) == (0, 1)

    def test_an_unrecognised_warrant_is_refused(self, tmp_path: Path) -> None:
        """Refused, not ignored.

        A warrant that merely failed to match would report as an ordinary hit
        and send the reader to re-judge a line they already judged.
        """
        repo = _repo(tmp_path, self.POLICY, ack="fine :: Eight scheduled timers\n")
        result = _run(repo)
        assert result.returncode == 1
        # stderr, per AGENTS.md's "diagnostics to stderr" and the sibling
        # prove-no-loss.sh (CR round 1, finding 4). On stdout, a caller
        # grepping stderr for ERROR saw nothing at all.
        assert "no recognised warrant" in result.stderr
        assert "no recognised warrant" not in result.stdout
        assert "counts:" not in result.stdout, (
            "the machine-readable trailer is promised on exits 0 and 3 only; "
            "emitting it here would hand a caller a zero for a run that "
            "counted nothing"
        )

    def test_a_warrant_belongs_to_one_class(self, tmp_path: Path) -> None:
        """`pointer` says nothing about whether a number is reproducible."""
        repo = _repo(tmp_path, self.POLICY, ack="pointer :: Eight scheduled timers\n")
        assert _counts(_run(repo))[0] == 1

    def test_an_entry_expires_when_the_text_changes(self, tmp_path: Path) -> None:
        repo = _repo(
            tmp_path,
            "# P\n\nNine scheduled timers keep the tree fresh.\n",
            ack="enumerated :: Eight scheduled timers\n",
        )
        result = _run(repo)
        assert _counts(result)[0] == 1
        assert "matched nothing" in result.stdout

    def test_a_path_scoped_entry_is_accepted(self, tmp_path: Path) -> None:
        repo = _repo(
            tmp_path,
            self.POLICY,
            ack="AGENTS.md :: enumerated :: Eight scheduled timers\n",
        )
        assert _counts(_run(repo)) == (0, 1)

    def test_a_broad_entry_is_warned_about(self, tmp_path: Path) -> None:
        """One entry, one judged line. A blanket pattern is the way to zero this
        metric with no edit to the file it measures."""
        repo = _repo(
            tmp_path,
            "# P\n\nEight timers run daily.\n\nEight timers also run weekly.\n",
            ack="stable :: Eight timers\n",
        )
        result = _run(repo)
        assert _counts(result) == (0, 2)
        assert "WARN" in result.stdout


class TestTheLedgerCarriesIt:
    """A skill change claiming to reduce this class must be visible to the gate."""

    @pytest.mark.skipif(shutil.which("python3") is None, reason="needs python3")
    def test_the_pair_lands_on_a_row(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, "# P\n\nNothing here.\n")
        measured = subprocess.run(
            ["bash", str(SCRIPTS / "measure-context.sh"), "--no-write"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            env={**_clean_env(), "ANTHROPIC_API_KEY": ""},
            timeout=180,
        )
        assert measured.returncode == 0, measured.stderr
        row = subprocess.run(
            [
                "bash",
                str(RECORD),
                "--baseline",
                "--counts",
                "4",
                "--counts-acked",
                "2",
                "--dry-run",
            ],
            input=measured.stdout,
            cwd=str(repo),
            capture_output=True,
            text=True,
            env=_clean_env(),
            timeout=120,
        )
        assert row.returncode == 0, row.stderr
        assert '"counts": 4' in row.stdout
        assert '"counts_acked": 2' in row.stdout

    def test_a_non_count_is_refused(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, "# P\n\nNothing here.\n")
        row = subprocess.run(
            ["bash", str(RECORD), "--counts", "four", "--dry-run"],
            input="{}",
            cwd=str(repo),
            capture_output=True,
            text=True,
            env=_clean_env(),
            timeout=120,
        )
        assert row.returncode == 1
        assert "--counts" in row.stderr


class TestTheAuthorIsNotExempt:
    """A rule this repo enforces on a cohort's AGENTS.md and not on its own is
    a rule the first cohort maintainer to measure us finds out about."""

    def test_this_repos_policy_file_passes(self) -> None:
        result = subprocess.run(
            ["bash", str(CHECK)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env=_clean_env(),
            timeout=120,
        )
        assert result.returncode == 0, (
            "AGENTS.md carries an unjudged rot-prone count or an over-long "
            "index line:\n" + result.stdout
        )
