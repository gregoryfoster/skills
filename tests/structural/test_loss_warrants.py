"""A warrant for a loss `prove-no-loss.sh`'s own split forced (#111).

`prove-no-loss.sh` has three outcomes and the ledger three verdicts, and a real
edit fits none of them: **a pointer that had to be rewritten because this same
change moved what it points at.** Two cohort adoptions hit it independently.

- `CannObserv/power-map` split four over-budget reference docs (7 live docs ->
  18) and exited 3 on eight lines: four pointers naming a section that no
  longer exists, four `## Detail Docs` index entries whose descriptions named
  relocated content. Nothing was dropped — every one was replaced by a
  corrected line, and both edits are first-class action tags in this skill's
  own vocabulary (`fix:stale-cross-reference`, `relink:<doc>`).
- `CannObserv/cannobserv` hit it from a direction the skill *mandates*: Phase
  6.5's provenance rule forbids an issue number in a permanent anchor slug, so
  `### uv workspace layout (introduced #129)` MUST become `## uv workspace
  layout`. `prove-no-loss.sh` normalises heading level but not heading text, so
  the rename reports LOST. Ten unaccounted lines, six with no warrant category.

Neither of the three verdicts is honest about that:

  ok       is a lie — the script exited 3.
  failed   is documented as "evidence that anything actually went wrong", and
           score-cohort.sh reads it as a safety violation. Recording it tells
           the gate a change dropped content when it dropped none, which is
           worse than silence in the direction the gate cares about.
  skipped  is false — the check ran and produced a verdict.

The two adopters resolved it in *opposite* directions (one left the ledger
untouched, one recorded `ok`), so the cohort's `no_loss` column already holds
two different claims about the same underlying state.

The shape here is the issue's option 1: an acknowledgement file mirroring
`.skills/context-seams-ok`, with the warranted count riding the row like
`seams_acked`. Every case below is paired with the direction that actually
matters — **a genuine loss must still fail** — because a mechanism that lets an
operator wave away any unaccounted-for line is strictly worse than the current
forced choice.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from .test_context_surface import _arm, _roster, _score  # shared cohort fixtures

SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills" / "curating-context" / "scripts"
)
PROVE = SCRIPTS / "prove-no-loss.sh"
RECORD = SCRIPTS / "record-telemetry.sh"
SCORE = SCRIPTS / "score-cohort.sh"

ACK = ".skills/context-loss-ok"

# The power-map case, reduced to one line of each kind. Both are long enough to
# be distinctive, which matters: the duplication note below has a length floor.
POINTER = "Full naming rules live in [docs/STYLE.md](docs/STYLE.md) §32 — read that before adding a module."
RETARGETED = "Full naming rules live in [docs/naming/STYLE.md](docs/naming/STYLE.md) — read that before adding a module."
INDEX_ENTRY = "- [docs/CONVENTIONS.md](docs/CONVENTIONS.md) — database conventions, change-bus contracts, and shim strategy."


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, env=_clean_env())


def _repo(tmp_path: Path, policy_body: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "AGENTS.md").write_text(policy_body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "before")
    return repo


def _ack(repo: Path, *entries: str, path: str = ACK) -> None:
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(e + "\n" for e in entries))


def _prove(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(PROVE), "--base", "HEAD", *extra],
        capture_output=True, text=True, cwd=str(repo),
        env=_clean_env(), timeout=30,
    )


class TestTheWarrantedLossIsNotALoss:
    """The direction the issue is about: a rewrite this run's own split forced
    is accounted for, and says so, without claiming nothing changed."""

    def _split_repo(self, tmp_path: Path) -> Path:
        """power-map's shape: the policy file points into a section, the run
        splits that section out, and the pointer must be retargeted."""
        repo = _repo(tmp_path, f"# P\n\n## Conventions\n\n{POINTER}\n")
        (repo / "AGENTS.md").write_text(
            f"# P\n\n## Conventions\n\n{RETARGETED}\n")
        (repo / "docs" / "naming").mkdir(parents=True)
        (repo / "docs" / "naming" / "STYLE.md").write_text("# Style\n\n## Naming\n\nrules\n")
        return repo

    def test_without_a_warrant_the_retarget_still_reports_as_loss(
            self, tmp_path: Path):
        """The status quo, pinned. If this ever passes on its own the ack file
        has stopped being necessary — and, far more likely, the normaliser has
        gone target-blind and the check is worthless."""
        r = _prove(self._split_repo(tmp_path))
        assert r.returncode == 3, r.stdout + r.stderr
        assert "docs/STYLE.md" in r.stdout, r.stdout

    def test_a_warranted_retarget_exits_clean(self, tmp_path: Path):
        repo = self._split_repo(tmp_path)
        _ack(repo, f"retarget :: {POINTER}")
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "loss_warranted: 1" in r.stdout, r.stdout
        assert "lost: 0" in r.stdout, r.stdout

    def test_the_warranted_line_is_still_named_in_the_report(
            self, tmp_path: Path):
        """A clean exit that prints nothing about what it waved through is how
        an ack file becomes a blanket. check-seams.sh lists every acknowledged
        hit for the same reason."""
        repo = self._split_repo(tmp_path)
        _ack(repo, f"retarget :: {POINTER}")
        r = _prove(repo)
        assert "WARRANTED" in r.stdout, r.stdout
        assert "retarget" in r.stdout and "docs/STYLE.md" in r.stdout, r.stdout

    def test_the_verdict_line_does_not_claim_nothing_moved(self, tmp_path: Path):
        """`OK — every line is either still inline or relocated verbatim` would
        be false here: one line was neither. The clean exit must say which
        claim it is making."""
        repo = self._split_repo(tmp_path)
        _ack(repo, f"retarget :: {POINTER}")
        r = _prove(repo)
        assert "every line is either still inline or relocated verbatim" \
            not in r.stdout, r.stdout
        assert "1 line(s) warranted, none unexplained" in r.stdout, r.stdout

    def test_the_provenance_rename_phase_65_mandates_has_a_warrant(
            self, tmp_path: Path):
        """cannobserv's case. check-seams.sh class 3b fires on `#\\d{2,}` in any
        heading, so the rename is compulsory; prove-no-loss normalises heading
        level but not heading text, so it reports LOST. No ordering discipline
        avoids this one — the two phases genuinely cannot both be satisfied."""
        repo = _repo(tmp_path, "# P\n\n### uv workspace layout (introduced #129)\n\nbody\n")
        (repo / "AGENTS.md").write_text("# P\n\nSee [docs/UV.md](docs/UV.md).\n")
        (repo / "docs").mkdir()
        (repo / "docs" / "UV.md").write_text(
            "# UV\n\n## uv workspace layout\n\nbody\n\nIntroduced in #129.\n")
        assert _prove(repo).returncode == 3, "fixture must reproduce the rename loss"
        _ack(repo, "rename :: uv workspace layout (introduced #129)")
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "loss_warranted: 1" in r.stdout


class TestAGenuineLossStillFails:
    """The mechanism is only worth having if it cannot be used to wave away an
    ordinary deletion. Every case here has an ack file present and in use."""

    def test_an_unwarranted_line_still_exits_three(self, tmp_path: Path):
        repo = _repo(
            tmp_path,
            f"# P\n\n## A\n\n{POINTER}\n\nload-bearing constraint nobody judged\n")
        (repo / "AGENTS.md").write_text(f"# P\n\n## A\n\n{RETARGETED}\n")
        _ack(repo, f"retarget :: {POINTER}")
        r = _prove(repo)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "LOST" in r.stdout and "load-bearing constraint" in r.stdout
        assert "lost: 1" in r.stdout, r.stdout
        assert "loss_warranted: 1" in r.stdout, r.stdout

    def test_an_entry_expires_the_moment_its_line_changes(self, tmp_path: Path):
        """Matched on content, never on line number, so an acknowledgement
        covers the line that was judged and nothing else. `.skills/
        context-seams-ok` proved this mechanism in the field: two acks stopped
        matching mid-review and forced a re-judge."""
        repo = _repo(tmp_path, f"# P\n\n## A\n\n{POINTER} Also, never skip it.\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n")
        _ack(repo, f"retarget :: {POINTER} Never skip it.")
        r = _prove(repo)
        assert r.returncode == 3, r.stdout
        assert "matched nothing" in r.stdout, r.stdout

    def test_an_entry_cannot_reach_a_line_that_was_accounted_for(
            self, tmp_path: Path):
        """A warrant only ever applies to a line already unaccounted for, so it
        can neither hide a relocation nor manufacture one."""
        repo = _repo(tmp_path, f"# P\n\n## A\n\n{POINTER}\n")
        _ack(repo, "retarget :: Full naming rules")
        r = _prove(repo)
        assert r.returncode == 0
        assert "loss_warranted: 0" in r.stdout, r.stdout
        assert "matched nothing" in r.stdout, r.stdout

    def test_a_blanket_entry_is_warned_about(self, tmp_path: Path):
        """The metric-gaming vector, moved into this file: one broad line
        zeroes the count with no diff anywhere. check-seams.sh's per-pattern
        accountability report is the part worth copying verbatim — the cohort
        named it as what proved no entry had quietly become a blanket."""
        repo = _repo(tmp_path, "# P\n\n## A\n\nfirst rule here\nsecond rule here\nthird rule here\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n")
        _ack(repo, "duplicate :: rule here")
        r = _prove(repo)
        assert r.returncode == 0, r.stdout
        assert "3 hit(s)" in r.stdout, r.stdout
        assert "WARN" in r.stdout and "broad" in r.stdout, r.stdout

    def test_a_precise_entry_is_not_warned_about(self, tmp_path: Path):
        """Or the WARN means nothing."""
        repo = _repo(tmp_path, "# P\n\n## A\n\nfirst rule here\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n")
        _ack(repo, "duplicate :: first rule here")
        r = _prove(repo)
        assert r.returncode == 0, r.stdout
        assert "WARN" not in r.stdout, r.stdout


class TestAWarrantMustBeNamed:
    """An acknowledgement is a *judgement*, and the tag is where it is
    recorded. A free-text or bare entry would make the file a mute allowlist —
    the same file, minus the only thing that makes it reviewable."""

    VOCABULARY = ("retarget", "rename", "duplicate", "disproven", "default")

    def test_every_warrant_in_the_vocabulary_is_accepted(self, tmp_path: Path):
        for tag in self.VOCABULARY:
            repo = _repo(tmp_path / tag, "# P\n\n## A\n\na judged line of policy\n")
            (repo / "AGENTS.md").write_text("# P\n\n## A\n")
            _ack(repo, f"{tag} :: a judged line of policy")
            r = _prove(repo)
            assert r.returncode == 0, f"{tag}: {r.stdout}{r.stderr}"

    def test_an_unknown_warrant_is_refused_not_ignored(self, tmp_path: Path):
        """Refusing beats silently not-matching: a typo would otherwise read as
        an ordinary loss and send the run hunting for content that is fine."""
        repo = _repo(tmp_path, "# P\n\n## A\n\na judged line of policy\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n")
        _ack(repo, "retargetted :: a judged line of policy")
        r = _prove(repo)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "retargetted" in r.stderr, r.stderr

    def test_a_bare_entry_without_a_warrant_is_refused(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\n## A\n\na judged line of policy\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n")
        _ack(repo, "a judged line of policy")
        r = _prove(repo)
        assert r.returncode == 1, r.stdout + r.stderr
        assert " :: " in r.stderr, r.stderr

    def test_an_entry_with_an_empty_content_half_is_refused(self, tmp_path: Path):
        """`retarget :: ` matches every lost line — the blanket in its purest
        form, and the one shape the WARN would report *after* it had already
        exited clean."""
        repo = _repo(tmp_path, "# P\n\n## A\n\na judged line of policy\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n")
        _ack(repo, "retarget :: ")
        r = _prove(repo)
        assert r.returncode == 1, r.stdout + r.stderr

    def test_comments_and_blanks_are_ignored_at_line_start_only(
            self, tmp_path: Path):
        """An inline `#` must not be stripped. check-seams.sh learned this the
        hard way: stripping one turned `Fixed in #412` into `Fixed in`, a
        strictly broader pattern than its author wrote."""
        repo = _repo(tmp_path, "# P\n\n## A\n\nsee the note in #412 for why\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n")
        _ack(repo, "# a comment", "", "disproven :: the note in #412 for why")
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "loss_warranted: 1" in r.stdout

    def test_a_missing_ack_file_is_not_an_error(self, tmp_path: Path):
        """Most repos will never have one, and the default path must not turn
        every clean run into an infrastructure failure."""
        repo = _repo(tmp_path, "# P\n\n## A\n\nkeep me\n")
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "loss_warranted: 0" in r.stdout

    def test_the_ack_file_path_is_configurable(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\n## A\n\na judged line of policy\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n")
        _ack(repo, "duplicate :: a judged line of policy", path="warrants.txt")
        assert _prove(repo).returncode == 3, "default path must not read it"
        r = _prove(repo, "--ack-file", "warrants.txt")
        assert r.returncode == 0, r.stdout + r.stderr


class TestCopiedRatherThanMoved:
    """The second defect #111 reports as invisible to all three gates: bullets
    COPIED rather than moved, still inline in the policy file with nothing
    requiring the duplicate. `prove-no-loss.sh` is satisfied by presence
    anywhere, so it saw nothing; `check-seams` checks references; `links.dead`
    checks links. A review pass caught six in one run, one line reaching three
    occurrences.

    Reported as a hit to JUDGE, never as a failure — the cohort supplied the
    counter-example itself: a public-API rule that is load-bearing inline *and*
    as its destination's lead-in, which they correctly kept in both places.
    """

    def _copied(self, tmp_path: Path) -> Path:
        repo = _repo(tmp_path, f"# P\n\n## A\n\n{INDEX_ENTRY}\n")
        (repo / "docs").mkdir()
        (repo / "docs" / "X.md").write_text(f"# X\n\n{INDEX_ENTRY}\n")
        return repo

    def test_a_line_left_in_both_places_is_reported(self, tmp_path: Path):
        r = _prove(self._copied(tmp_path))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "duplicated: 1" in r.stdout, r.stdout
        assert "docs/X.md" in r.stdout, r.stdout

    def test_it_is_a_note_and_never_changes_the_exit_code(self, tmp_path: Path):
        assert _prove(self._copied(tmp_path)).returncode == 0

    def test_a_clean_move_reports_no_duplication(self, tmp_path: Path):
        repo = _repo(tmp_path, f"# P\n\n## A\n\n{INDEX_ENTRY}\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n")
        (repo / "docs").mkdir()
        (repo / "docs" / "X.md").write_text(f"# X\n\n{INDEX_ENTRY}\n")
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "duplicated: 0" in r.stdout, r.stdout

    def test_short_and_structural_lines_are_not_reported(self, tmp_path: Path):
        """Fences, rules and `## Detail Docs` headings appear in every file by
        construction. Without a floor the note is hundreds of lines of noise
        and gets ignored, which is how the six real ones shipped."""
        repo = _repo(tmp_path, "# P\n\n## A\n\n```bash\nls\n```\n\n---\n")
        (repo / "docs").mkdir()
        (repo / "docs" / "X.md").write_text("# X\n\n## A\n\n```bash\nls\n```\n\n---\n")
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "duplicated: 0" in r.stdout, r.stdout


class TestProvingADocSplit:
    """`--file` takes a REFERENCE DOC, not only the policy file, and that is
    the right tool for a doc split: the split moves nothing out of AGENTS.md,
    so a policy-file run passes while saying nothing about it.

    The interesting half is the one the docs described as working and did not.
    A split that DELETES its source — `docs/API.md` -> `docs/api/*.md`, the
    shape #119 was measured on — left `--file docs/API.md` naming a path with
    no working-tree file, and the explicit argument fell through to the
    autodetect branch's error: "no policy file found (looked for AGENTS.md,
    CLAUDE.md)", exit 1, for a file the caller had named outright.
    """

    def _split(self, tmp_path: Path, keep_source: bool) -> Path:
        repo = _repo(tmp_path, "# P\n\n## A\n\nsee [docs/API.md](docs/API.md)\n")
        docs = repo / "docs"
        docs.mkdir()
        (docs / "API.md").write_text(
            "# API\n\n## Shapes\n\nSee the [helper](../tests/x.py) for the shape.\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "the doc before its split")
        (docs / "api").mkdir()
        # One level deeper than the source, so the link gains a level too —
        # the depth #119 fixed, exercised through the split it describes. The
        # index part is what a real split leaves behind, and it is where the
        # source doc's own `# API` title has to survive.
        (docs / "api" / "README.md").write_text("# API\n\n- [Shapes](shapes.md)\n")
        (docs / "api" / "shapes.md").write_text(
            "# Shapes\n\nSee the [helper](../../tests/x.py) for the shape.\n")
        if not keep_source:
            (docs / "API.md").unlink()
        return repo

    def test_a_split_that_deletes_its_source_is_provable(self, tmp_path: Path):
        r = _prove(self._split(tmp_path, keep_source=False), "--file", "docs/API.md")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "docs/api/shapes.md" in r.stdout, r.stdout

    def test_it_says_the_source_is_gone_rather_than_implying_it_is_empty(
            self, tmp_path: Path):
        """0 still inline out of 3 is indistinguishable from a file that was
        emptied in place, and the two want different review."""
        r = _prove(self._split(tmp_path, keep_source=False), "--file", "docs/API.md")
        assert "docs/API.md no longer exists" in r.stdout, r.stdout

    def test_a_split_that_keeps_its_source_is_still_provable(self, tmp_path: Path):
        r = _prove(self._split(tmp_path, keep_source=True), "--file", "docs/API.md")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_a_line_the_split_dropped_is_still_caught(self, tmp_path: Path):
        """The whole point. Removing the working-tree check must not weaken
        anything: with no inline set, every line has to be in a destination."""
        repo = self._split(tmp_path, keep_source=False)
        (repo / "docs" / "api" / "shapes.md").write_text("# Shapes\n")
        r = _prove(repo, "--file", "docs/API.md")
        assert r.returncode == 3, r.stdout + r.stderr
        assert "helper" in r.stdout, r.stdout

    def test_a_file_absent_at_base_too_is_still_an_infrastructure_error(
            self, tmp_path: Path):
        """Exit 2, not a silent pass over zero lines."""
        repo = _repo(tmp_path, "# P\n")
        r = _prove(repo, "--file", "docs/NEVER.md")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "does not exist at" in r.stderr, r.stderr

    def test_no_file_flag_and_no_policy_file_is_still_a_usage_error(
            self, tmp_path: Path):
        """The autodetect branch keeps its own message — the fix must not turn
        a repo with no policy file into a run over nothing."""
        repo = tmp_path / "bare"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        (repo / "README.md").write_text("hi\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "i")
        r = _prove(repo)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "no policy file found" in r.stderr, r.stderr


class TestTheCountRidesTheRow:
    """`no_loss: ok` alone cannot tell "nothing was unaccounted for" from
    "eight lines were judged and waved through". Recording the count is what
    turns the ack file from a private convenience into cohort data — the thing
    power-map lost by keeping its eight warrants in the PR body.
    """

    def _payload(self) -> str:
        return json.dumps({
            "policy": {"path": "AGENTS.md", "lines": 10, "bytes": 100,
                       "tokens": 40, "tokens_exact": True,
                       "bytes_per_token": 2.5, "budget": 6000,
                       "over_budget": False},
            "totals": {"tokens_live": 40, "files_docs": 0},
            "docs": [], "links": {"dead": [], "orphans": [], "dead_anchors": []},
            "sections": [],
        })

    def _record(self, tmp_path: Path, *flags: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(RECORD), "--dry-run", *flags], input=self._payload(),
            capture_output=True, text=True,
            cwd=str(_repo(tmp_path, "# P\n")), env=_clean_env(), timeout=30,
        )

    def _row(self, tmp_path: Path, *flags: str) -> dict:
        r = self._record(tmp_path, *flags)
        assert r.returncode == 0, r.stdout + r.stderr
        line = [x for x in r.stdout.splitlines() if x.strip().startswith("{")][-1]
        return json.loads(line)

    def test_the_count_lands_on_the_row(self, tmp_path: Path):
        row = self._row(tmp_path, "--no-loss", "ok", "--no-loss-warrants", "8")
        assert row["no_loss"] == "ok"
        assert row["no_loss_warrants"] == 8, row

    def test_absent_records_null_not_zero(self, tmp_path: Path):
        """Null and 0 are different claims, the line the ledger already draws
        for no_loss and seams: a run predating the field has not shown it
        warranted nothing. Every existing row in the cohort carries null."""
        row = self._row(tmp_path, "--no-loss", "ok")
        assert row["no_loss_warrants"] is None, row

    def test_zero_is_recordable_and_is_not_null(self, tmp_path: Path):
        """`--no-loss-warrants 0` is a positive claim — the run read the report
        and had nothing to warrant — and must survive the `or None` shape that
        would fold it back into "not measured"."""
        row = self._row(tmp_path, "--no-loss", "ok", "--no-loss-warrants", "0")
        assert row["no_loss_warrants"] == 0, row

    def test_a_count_without_a_verdict_is_refused(self, tmp_path: Path):
        """Warrants are the *composition* of a verdict. Recorded alone they
        would assert that lines were judged by a check nobody ran."""
        r = self._record(tmp_path, "--no-loss-warrants", "3")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "--no-loss" in r.stderr, r.stderr

    def test_a_count_against_a_skipped_verdict_is_refused(self, tmp_path: Path):
        r = self._record(tmp_path, "--no-loss", "skipped", "--no-loss-warrants", "3")
        assert r.returncode == 1, r.stdout + r.stderr

    def test_a_count_against_a_failed_verdict_is_allowed(self, tmp_path: Path):
        """Five warranted and three not is a real and informative state: the
        run exited 3, and the ledger should still say how much of it was
        judged."""
        row = self._row(tmp_path, "--no-loss", "failed", "--no-loss-warrants", "5")
        assert row["no_loss_warrants"] == 5, row

    def test_a_baseline_row_refuses_the_flag(self, tmp_path: Path):
        """A baseline has relocated nothing, so it has nothing to warrant —
        the same reason it already refuses --no-loss."""
        r = self._record(tmp_path, "--baseline=pre-curation", "--no-loss-warrants", "0")
        assert r.returncode == 1, r.stdout + r.stderr

    @pytest.mark.parametrize("bad", ["eight", "-1", "3.5", ""])
    def test_a_non_numeric_count_is_refused(self, tmp_path: Path, bad):
        r = self._record(tmp_path, "--no-loss", "ok", "--no-loss-warrants", bad)
        assert r.returncode == 1, f"{bad!r} was accepted: {r.stdout}{r.stderr}"


class TestTheGateSeesTheWarrantsWithoutRejectingThem:
    """`score-cohort.sh` must surface the count and must NOT gate on it.

    Gating would recreate the forced choice one level up: a run that correctly
    retargeted four pointers would be rejected for saying so, and the rational
    move would be to stop recording it — which is exactly how the field dies.
    The defence against a ballooning ack file is visibility, per-entry
    accountability in the report, and the delta across runs, the same three the
    cohort settled on for `seams_acked`.

    And the null path is load-bearing: every row in every cohort ledger
    predates this field.
    """

    def test_a_null_does_not_trip_the_gate(self, tmp_path: Path):
        r = _score(_three_good_pairs_local(tmp_path))
        assert "verdict: ADOPT" in r.stdout, r.stdout
        assert r.returncode == 0, r.stdout + r.stderr

    def test_warrants_do_not_trip_the_gate(self, tmp_path: Path):
        r = _score(_three_good_pairs_local(tmp_path, no_loss_warrants=8))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "verdict: ADOPT" in r.stdout, r.stdout

    def test_warrants_are_visible_beside_the_verdict(self, tmp_path: Path):
        """Otherwise the column reads `ok` for a run that waved eight lines
        through and `ok` for one that waved none, which is the ambiguity #111
        opened with."""
        r = _score(_three_good_pairs_local(tmp_path, no_loss_warrants=8))
        assert "ok+8w" in r.stdout, r.stdout

    def test_a_row_without_warrants_reads_as_plain_ok(self, tmp_path: Path):
        """A null row must not render as `ok+0w` — that would claim the run
        measured and warranted nothing, which is the null-is-not-zero line the
        ledger draws everywhere else."""
        r = _score(_three_good_pairs_local(tmp_path))
        assert "ok+" not in r.stdout, r.stdout

    def test_a_recorded_failure_still_rejects_however_many_were_warranted(
            self, tmp_path: Path):
        """The whole point of keeping `failed` meaningful: warranting five of
        eight lines does not make the other three acceptable."""
        r = _score(_three_good_pairs_local(
            tmp_path, no_loss="failed", no_loss_warrants=5))
        assert r.returncode == 3, r.stdout + r.stderr
        assert "verdict: REJECT" in r.stdout
        assert "no_loss=failed" in r.stdout


def _three_good_pairs_local(root: Path, **treatment_kw) -> Path:
    """test_context_surface's fixture, with the treatment arm's extra row
    fields passed through. Shared rather than reimplemented so a change to the
    cohort fixture cannot leave this file testing a shape nobody writes."""
    pairs = [(52000, 20000, 49000, 12000), (28000, 12000, 26000, 9000),
             (19000, 9000, 14000, 7000)]
    spec = []
    for i, (cb, ca, tb, ta) in enumerate(pairs, start=1):
        _arm(root, f"ctl{i}", cb, ca, "1.1")
        _arm(root, f"trt{i}", tb, ta, "1.2", **treatment_kw)
        spec += [(f"ctl{i}", "a", str(i)), (f"trt{i}", "b", str(i))]
    return _roster(root, spec)
