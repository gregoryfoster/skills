"""The stale-artifact remedy is the incremental call, not the full re-embed (#317).

#225 made a stale context artifact a **defect** rather than a note, and the
severity rests on one sentence of its rationale: "it is repaired by one named
call". The call it named was `codebase_context_index`, and that is the one
remedy in this skill a session cannot afford to follow.

Measured on `CannObserv/watcher`, from the finding this file exists to fix:

    13:07:47  Calling MCP tool: codebase_context_index
    13:37:47  aborting: no response or progress notification for 1800s

The server finished at 14:24:37Z — 47 minutes after the client gave up — so the
remedy *failed while succeeding*, and the session paid the full idle timeout for
three stale artifacts. `codebase_context_index` -> `indexAllArtifacts` re-embeds
every artifact unconditionally: no content-hash skip, no MCP progress
notifications, one awaited run. `codebase_update` -> `ensureArtifactsIndexed`
compares each artifact's `contentHash` and `configurationSignature` and
re-embeds only what moved; a doc saved at 14:38:39Z on that same host reached
the context collection at 14:38:57Z.

Two properties are pinned, because they rot in opposite directions:

1. **The finding names `codebase_update`** and does not send the reader back to
   the full re-embed. A driver run against a stub server proves the string an
   agent actually reads, not the source it was written from.
2. **The three places `codebase_context_index` is still, correctly, documented
   carry its cost** — it stays the install-time call, and a reader who reaches
   for it has to be told it can outlast the 1800 s timeout and that a timeout
   there is not evidence of failure. Without that second half the next agent
   re-runs a job the server already finished.

The parity module owns the finding's existence and severity; this file owns
which call it names. Its fixtures are imported rather than rebuilt so the two
cannot drift into testing different drivers.
"""

import re
from pathlib import Path

from .test_context_artifact_parity import (
    ARTIFACTS_REF,
    CONTEXT_ALL_INDEXED,
    DEFAULT_REPLIES,
    DOC_REF,
    EDITED_AFTER_INDEXING,
    SKILL_DIR,
    STATUS_COMPLETE,
    _health_check,
    _repo,
    _stamp,
    requires_node,
)

SKILL_MD = SKILL_DIR / "SKILL.md"

# Every spelling that reads as an INSTRUCTION to start a full re-embed. Naming
# the tool to say what it costs is the point of the fix, so a bare mention must
# stay legal; only the imperative is the regression.
#
# Three things the first draft of this pattern got wrong, each verified against
# the string it let through:
#   - `\b(?:re-)?run` cannot match the unhyphenated "rerun": the boundary is
#     consumed by "re", and there is no boundary before the inner "run".
#   - a single ` +` between verb and tool rejects "re-run the full
#     codebase_context_index", which is the same instruction with two words in
#     it. Up to three intervening words are allowed instead.
#   - it is applied to the FINDING and the generated doc, never to SKILL.md,
#     where `codebase_context_index { projectPath }` is the correct
#     install-time imperative and must stay one.
RERUN_FULL = re.compile(
    r"(?:re-? ?)?run(?:ning|s)?\b(?:\s+\w+){0,3}\s+`?codebase_context_index", re.I
)
RUN_INCREMENTAL = re.compile(r"\brun +`?codebase_update", re.I)

# The claim itself, not just the handle for checking it. Each file words it
# differently ("not evidence it failed", "not evidence the index failed"), so
# the pattern spans the verb rather than pinning one phrasing.
NOT_A_FAILURE = re.compile(r"not evidence[^.]{0,40}fail", re.I)


def _stale_finding(tmp_path: Path) -> str:
    """The health-check finding for a repo with one artifact edited since index."""
    repo = _repo(tmp_path)
    _stamp(repo / "AGENTS.md", EDITED_AFTER_INDEXING)
    replies = {
        **DEFAULT_REPLIES,
        "codebase_status": STATUS_COMPLETE,
        "codebase_context": CONTEXT_ALL_INDEXED,
    }
    _, report, _calls = _health_check(tmp_path, repo, replies)
    assert report is not None, "health-check produced no JSON report"
    stale = [f for f in report["findings"] if "stale" in f]
    assert stale, f"no stale finding to check the remedy of:\n{report}"
    return stale[0]


class TestTheFindingNamesTheAffordableCall:
    @requires_node
    def test_the_remedy_is_codebase_update(self, tmp_path: Path) -> None:
        line = _stale_finding(tmp_path)
        assert RUN_INCREMENTAL.search(line), (
            "the stale-artifact finding does not tell the reader to run "
            f"`codebase_update`, the only remedy that re-embeds just what "
            f"changed (#317): {line!r}"
        )

    @requires_node
    def test_it_does_not_send_the_session_into_a_full_re_embed(
        self, tmp_path: Path
    ) -> None:
        """The regression itself: a remedy that costs 30 minutes and then aborts."""
        line = _stale_finding(tmp_path)
        assert not RERUN_FULL.search(line), (
            "the stale-artifact finding instructs a full `codebase_context_index` "
            "re-embed. On CannObserv/watcher that blocked the session for the "
            "whole 1800 s idle timeout, aborted, and the server went on to "
            f"finish 47 minutes later (#317): {line!r}"
        )

    @requires_node
    def test_the_stale_artifacts_are_still_named(self, tmp_path: Path) -> None:
        """A remedy swap must not cost the finding what #225 gave it."""
        line = _stale_finding(tmp_path)
        assert "agent-guidelines" in line, (
            f"the finding named a remedy and stopped naming the artifact: {line!r}"
        )


class TestTheFullReEmbedIsDocumentedWithItsCost:
    """Wherever `codebase_context_index` survives, so must what it costs.

    It is still the right call at install time — nothing is indexed, so there is
    no incremental delta to carry — and #317 does not remove it. What it adds is
    the other half a reader needs before reaching for it: the run is unbounded
    from the session's side, and the abort that follows says nothing about
    whether the index completed.
    """

    @staticmethod
    def _sources() -> list[Path]:
        return [SKILL_MD, DOC_REF, ARTIFACTS_REF]

    def test_each_names_the_idle_timeout(self) -> None:
        for path in self._sources():
            text = path.read_text()
            assert "codebase_context_index" in text, (
                f"{path.name} stopped documenting `codebase_context_index`; if "
                "that is deliberate, drop it from this test's sources"
            )
            assert "1800" in text, (
                f"{path.name} hands a reader `codebase_context_index` without "
                "saying the run can outlast Claude Code's 1800 s tool idle "
                "timeout (#317)"
            )

    def test_each_says_a_timeout_is_not_a_failed_index(self) -> None:
        """The expensive half of #317 was the inverse trap, not the wait.

        A red that succeeded reads exactly like a red that failed, and the
        second re-run costs another hour for nothing.

        Both halves are required, because either alone is survivable prose. The
        CLAIM without the handle leaves a reader believing the run may have
        finished and no way to find out; the handle without the claim names a
        field nothing has given them a reason to read. This test asserted only
        the handle until #317's own review.
        """
        for path in self._sources():
            text = path.read_text()
            assert NOT_A_FAILURE.search(text), (
                f"{path.name} names the 1800 s timeout without saying that "
                "hitting it is not evidence the index failed — the server runs "
                "on past the client's abort (#317)"
            )
            assert "lastIndexedAt" in text, (
                f"{path.name} does not tell a reader whose call timed out how to "
                "find out whether the index finished anyway — `lastIndexedAt` on "
                "the project's `socraticode_metadata` point (#317)"
            )

    def test_each_points_at_the_incremental_path(self) -> None:
        for path in self._sources():
            assert "codebase_update" in path.read_text(), (
                f"{path.name} documents the full re-embed and never names "
                "`codebase_update`, so a reader with three stale artifacts has "
                "only the expensive call to reach for (#317)"
            )


class TestTheGeneratedDocCarriesIt:
    """The template is what every adopting repo's `docs/SOCRATICODE.md` becomes.

    Advice above the END marker travels on the next re-run; advice outside the
    fenced block never reaches a consumer at all, which is the failure mode
    worth a test — the prose can be perfect and land nowhere.
    """

    @staticmethod
    def _template() -> str:
        """Between the markers — the ones on their own line.

        The prose above the fence quotes both marker names inline while
        explaining idempotency, so a plain `.index()` finds that sentence and
        returns a slice no consumer ever sees. Anchor on the line.
        """
        text = DOC_REF.read_text()
        start = text.index("\n<!-- BEGIN socraticode-doc -->\n")
        end = text.index("\n<!-- END socraticode-doc -->\n")
        return text[start:end]

    def test_the_remedy_reaches_consumers(self) -> None:
        template = self._template()
        assert "codebase_update" in template, (
            "`codebase_update` is documented in references/socraticode-doc.md "
            "but outside the marker block, so no generated docs/SOCRATICODE.md "
            "carries it (#317)"
        )
        assert "1800" in template and "lastIndexedAt" in template, (
            "the generated doc names `codebase_context_index` without the cost "
            "and the not-a-failure rule that make it safe to reach for (#317)"
        )

    def test_no_instruction_to_re_run_the_full_embed_survives(self) -> None:
        template = self._template()
        assert not RERUN_FULL.search(template), (
            "the generated doc still tells every adopting repo to re-run "
            "`codebase_context_index` — the advice #317 measured at 77 minutes "
            "for a repair worth seconds"
        )
