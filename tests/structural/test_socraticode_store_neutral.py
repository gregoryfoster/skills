"""The generated text names no store, so it is true under either `STORE` (#328).

Both policy-block variants opened with "SocratiCode is the preferred
semantic-search tool here once indexed (local Qdrant store + on-disk graph;
…)". Under `STORE=external` both halves are false: the store is remote, reached
by `QDRANT_URL`, and the graph is not on disk — it lives in the same store as
the `<projectId>_symgraph_*` collections. Under `managed` the second half is
false too, since the file and symbol graphs are Qdrant collections in either
mode (socraticode 1.14.0's `services/symbol-graph-store.js`). Every repo in the
CannObserv cohort is on the external store.

A consumer could not keep a correction. The block sits between markers in an
always-loaded `AGENTS.md`, so an audit re-run replaces whatever a repo wrote
there with the template: CannObserv/watcher's hand fix (watcher@06fcca2) would
be undone by the next run.

The issue offered a `STORE`-selected phrase or no phrase. This pins the second:
nothing between either file's markers says where the store is, so there is no
render under `STORE=external` that differs from the template, and no adaptation
an agent could get wrong. Where the store is belongs to `codebase_health`, not
to a line every session loads.

No API calls, no network.
"""

import re

from .test_socraticode_policy_split import (
    _BLOCK_RE,
    DOC_REF,
    POLICY_REF,
    _template,
)

# A claim about where the index lives. `Qdrant` alone is not one — the doc may
# name the store without placing it — but "local", "on disk", Docker and a
# container each put it somewhere that `STORE=external` contradicts.
STORAGE_CLAIM = re.compile(
    r"\blocal\s+(?:qdrant|store)\b|\bon[- ]disk\b|\bdocker\b|\bcontainers?\b",
    re.IGNORECASE,
)


def _blocks() -> list[str]:
    found = _BLOCK_RE.findall(POLICY_REF.read_text())
    assert len(found) == 2, (
        f"{POLICY_REF.name} should carry exactly variants A and B; a third "
        f"block is how a STORE-selected variant would arrive. Found {len(found)}."
    )
    return found


class TestTheBlockNamesNoStore:
    def test_neither_variant_places_the_store(self) -> None:
        for name, block in zip("AB", _blocks()):
            hits = STORAGE_CLAIM.findall(block)
            assert not hits, (
                f"variant {name} says where the store is ({hits}). That is "
                "false under one STORE or the other, and a consumer's fix is "
                f"overwritten on every re-run (#328).\n---\n{block}"
            )

    def test_neither_variant_names_qdrant(self) -> None:
        """Stricter than the doc: the block pays rent on every invocation.

        The parenthetical the issue removed was the only mention, and nothing
        an agent needs on nearly every task depends on which vector store
        answers.
        """
        for name, block in zip("AB", _blocks()):
            assert "qdrant" not in block.lower(), (
                f"variant {name} names Qdrant again (#328)\n---\n{block}"
            )

    def test_the_reference_says_there_is_nothing_to_adapt(self) -> None:
        """Without it, the adaptation rule invites the claim back.

        "Project-adapted, not copied verbatim" plus a store the agent can see
        is how a "shared store at <host>" line would reappear inside the
        markers — true for one repo, lost on its next re-run.
        """
        text = " ".join(POLICY_REF.read_text().split())
        assert "The block names no store" in text, (
            f"{POLICY_REF.name} must say the block names no store, so an agent "
            "adapting it does not add one (#328)"
        )


class TestTheGeneratedDocNamesNoStore:
    """The same failure, one file over: `docs/SOCRATICODE.md` is regenerated
    between its own markers, so a storage claim there is just as permanent."""

    def test_the_template_does_not_place_the_store(self) -> None:
        template = _template(DOC_REF.read_text())
        hits = STORAGE_CLAIM.findall(template)
        assert not hits, (
            f"references/{DOC_REF.name}'s template says where the store is "
            f"({hits}) — false under one STORE or the other (#328)"
        )
