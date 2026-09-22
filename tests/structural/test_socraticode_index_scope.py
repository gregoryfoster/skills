"""The generated doc says which store each control governs (#315).

#270 corrected "directory artifacts honour none of the ignore chain" to "they
honour it". Its issue called that "the same chain the code indexer uses", and
the generated doc said artifacts "run that same chain", with the rooting as a
caveat after the "but". The framing is what misled: the artifact walk builds
its filter from the ARTIFACT path, so the project-root `.socraticodeignore`
never reaches a subtree artifact. Reading it, `CannObserv/address-validator`
concluded that excluding `docs/plans/` from the code index would also empty
the `design-plans` artifact, and shipped a PR reasoning from that. Testing
caught it, not reading: the code index went 2,677 → 1,672 chunks and the
context store stayed at 1,112.

So the generated **Index scope** section must state the separation positively
— the ignore file governs the code index and graph, the manifest governs the
context store, and a path excluded from one stays searchable in the other —
and name the lever for each job. The same issue found the tool table sending
schema questions to a context search that answered from superseded plans, and
asked for a question about dated prose at install time; both are pinned here.

No API calls, no network.
"""

from .test_socraticode_policy_split import (
    DOC_REF,
    SKILL_DIR,
    SKILL_MD,
    _template,
    _tool_table,
)

ARTIFACTS_REF = SKILL_DIR / "references" / "context-artifacts.md"


def _section(text: str, heading: str) -> str:
    """`heading` to the next heading at its level or above."""
    assert heading in text, f"no {heading!r} section"
    start = text.index(heading) + len(heading)
    level = len(heading.split(" ", 1)[0])
    ends = [text.find("\n" + "#" * n + " ", start) for n in range(1, level + 1)]
    end = min((e for e in ends if e != -1), default=len(text))
    return text[start - len(heading) : end]


def _flat(text: str) -> str:
    """Prose as read: line wraps and bold markers do not split a phrase."""
    return " ".join(text.replace("**", "").split())


def _scope() -> str:
    return _section(_template(DOC_REF.read_text()), "## Index scope")


class TestTheGeneratedIndexScope:
    """The part of the template every consumer's `docs/SOCRATICODE.md` carries."""

    def test_it_no_longer_says_same_chain(self) -> None:
        assert "same chain" not in _scope().lower(), (
            f"references/{DOC_REF.name}'s **Index scope** calls the artifact "
            "walk's filter the same chain the code index uses. It is rooted at "
            "the artifact directory, so the project-root `.socraticodeignore` "
            "never reaches a subtree artifact, and the phrase is what led a "
            "consumer to the opposite conclusion (#315)"
        )

    def test_it_names_the_store_each_control_governs(self) -> None:
        scope = _flat(_scope())
        assert "code index and the graph" in scope, scope
        assert "context store" in scope and "manifest" in scope, scope
        assert "stays searchable in the other" in scope, (
            f"references/{DOC_REF.name}'s **Index scope** must say, once and "
            "positively, that a path excluded from one store stays searchable "
            "in the other — the sentence that makes an exclusion safe to "
            "reason about (#315)"
        )

    def test_it_says_where_an_artifacts_ignore_file_goes(self) -> None:
        scope = _flat(_scope())
        assert "at the top of the artifact directory" in scope, scope
        assert "The repo-root `.socraticodeignore` does not reach it" in scope, (
            f"references/{DOC_REF.name}'s **Index scope** must say the "
            "project-root file does not reach a directory artifact — the "
            "conclusion a consumer got backwards (#315)"
        )

    def test_it_names_a_lever_for_each_job(self) -> None:
        """Including where in an artifact each ignore file works.

        A `.gitignore` is read at any depth, a `.socraticodeignore` only at the
        artifact's top — a row saying "an ignore file inside it" sends a reader
        to a nested `.socraticodeignore` that is silently not read (#315 CR 2).
        """
        rows = [ln for ln in _scope().splitlines() if ln.startswith("| ")]
        levers = {
            "trim what code search": "repo-root `.socraticodeignore`",
            "trim a directory artifact": "a `.socraticodeignore` at its top",
            "drop an artifact": "manifest",
        }
        for job, lever in levers.items():
            row = next((r for r in rows if job in r.lower()), "")
            assert lever in row, (
                f"references/{DOC_REF.name}'s **Index scope** has no row sending "
                f"'{job}' to {lever!r} (#315)\n" + "\n".join(rows)
            )


class TestTheSchemaRow:
    """An unfiltered context search answered a schema question from old plans."""

    @staticmethod
    def _rows() -> list[str]:
        table = _tool_table(_template(DOC_REF.read_text()))
        return [ln for ln in table.splitlines() if ln.startswith("| ")]

    def test_the_context_row_does_not_claim_schemas(self) -> None:
        for row in self._rows():
            goal = row.split("|")[1].lower()
            if "`codebase_context`" in row:
                assert "schema" not in goal, (
                    f"references/{DOC_REF.name} still sends schema questions to "
                    "an unfiltered context search, where five of five hits came "
                    f"from design plans asserting a dropped value (#315)\n{row}"
                )

    def test_schema_questions_go_to_code_search(self) -> None:
        rows = [r for r in self._rows() if "schema" in r.split("|")[1].lower()]
        assert rows, f"references/{DOC_REF.name}'s tool table has no schema row"
        (row,) = rows
        assert "`codebase_search`" in row and "artifactName" in row, (
            "the schema row must name `codebase_search` first, and scope any "
            f"context search with `artifactName` (#315)\n{row}"
        )


class TestDatedProseIsAsked:
    """Plans outrank source in code search; the context store keeps them."""

    def test_the_reference_asks_and_says_when_not_to(self) -> None:
        text = _flat(
            _section(
                ARTIFACTS_REF.read_text(),
                "### Dated prose — ask whether it leaves the code index",
            )
        )
        assert "ask the operator" in text.lower() and "docs/plans/" in text, text
        assert "unsearchable" in text, (
            f"references/{ARTIFACTS_REF.name} recommends excluding dated prose "
            "without saying that a directory not registered as an artifact "
            "would then be searchable nowhere (#315)"
        )

    def test_skill_md_carries_the_question(self) -> None:
        phase = _flat(_section(SKILL_MD.read_text(), "### Phase 4"))
        assert "ask whether dated prose" in phase, (
            "SKILL.md Phase 4 must put the dated-prose question to the operator; "
            "the reference that explains it is read only if the phase points "
            "there (#315)"
        )
