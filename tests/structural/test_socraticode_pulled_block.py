"""init-socraticode: a session that *pulled* the env block can't index either
(#626), and the completion report prints each new link's stub step (#574).

#626, from CannObserv/usa-wa#556: the `env` block and `.socraticode.json`
arrived in the checkout that indexes by `git pull`. That checkout's editor
session had started before the pull, so its server stayed in managed mode,
read the new `projectId` live from `.socraticode.json`, and indexed the new
collection names into the LOCAL Qdrant. A driver `index` then waited out its
ceiling behind that server's locks. The skill named only "the session that
wrote the block" as unable to index, and confirmed `Qdrant mode: external`
only in Phase 6, after the index.

#574 part 1: a stub is a host step, not the skill's, so the completion report
prints it for each link the run added that does not resolve here, rather than
leaving the daily health hook to find the gap a day later.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL = REPO_ROOT / "skills" / "init-socraticode"
SKILL_MD = SKILL / "SKILL.md"
EXTERNAL_REF = SKILL / "references" / "external-store.md"


def _flat(path: Path) -> str:
    return " ".join(path.read_text().split())


def _section(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i : text.index(end, i + len(start))]


class TestAPulledBlockIsNamed:
    """#626 ask 1: any session that predates the block, however it arrived."""

    def test_no_doc_names_only_the_writing_session(self) -> None:
        for path in (SKILL_MD, *sorted((SKILL / "references").glob("*.md"))):
            assert "session that wrote the block" not in _flat(path), path

    def test_both_places_say_written_or_pulled(self) -> None:
        for path in (SKILL_MD, EXTERNAL_REF):
            flat = _flat(path)
            assert "before the block reached this checkout" in flat, path
            assert "whether written there or pulled" in flat, path


class TestTheServerIsAskedBeforeTheIndex:
    """#626 ask 2: Phase 6's server-side check, moved ahead of the first index."""

    def test_the_native_path_asks_codebase_health_first(self) -> None:
        flat = _flat(SKILL_MD)
        native = _section(flat, "**Preferred (native) path**", "**Fallback path**")
        health = native.find("`codebase_health`")
        index = native.find("`codebase_index {")
        assert health != -1, native
        assert index != -1, native
        assert health < index, "the mode check must precede the first codebase_index"
        assert "Qdrant mode: external" in native[health:index], native

    def test_the_reference_carries_the_pre_index_check(self) -> None:
        trust = _section(
            _flat(EXTERNAL_REF),
            "## Confirm trust before the first index",
            "## One host per",
        )
        assert "before the first `codebase_index`" in trust, trust
        assert "Qdrant mode: external" in trust, trust
        # The fallback path's own guard, named so nobody adds a second one.
        assert "validate-store" in trust, trust

    def test_the_symptom_is_named(self) -> None:
        """#626 ask 3."""
        trust = _section(
            _flat(EXTERNAL_REF),
            "## Confirm trust before the first index",
            "## One host per",
        )
        for phrase in ("local", "locks", "INDEX_TIMEOUT_MS", "restart"):
            assert phrase in trust, (phrase, trust)


class TestTheStubStepIsReported:
    """#574 part 1."""

    def test_the_store_config_row_carries_it(self) -> None:
        row = next(
            line
            for line in SKILL_MD.read_text().splitlines()
            if line.startswith("| Store config |")
        )
        assert "stub" in row, row

    def test_the_reference_gives_the_exact_step(self) -> None:
        para = _section(_flat(EXTERNAL_REF), "**A stub is a host step", "## Adopting")
        assert "each link this run added" in para, para
        assert "/.socraticode.json" in para, para
        assert "projectId" in para, para
        assert "every host" in para, para
        # On a managed store a stub names a collection this host's Qdrant
        # lacks: the step there is a checkout this host indexes.
        assert "managed store" in para, para


def _trust() -> str:
    return _section(
        _flat(EXTERNAL_REF),
        "## Confirm trust before the first index",
        "## One host per",
    )


class TestTheFallbackPathWaitsOnAStaleSessionToo:
    """CR 2465: the driver's guard checks only its own environment, while the
    index lock is host-local and keyed on projectId (upstream lock.js:
    os.tmpdir()/socraticode-locks/<projectId>-index). So a correctly
    configured driver `index` waits behind a stale editor session's lock —
    #626's own incident."""

    def test_the_fallback_path_is_not_called_covered(self) -> None:
        assert "needs no extra step" not in _trust()

    def test_stale_sessions_are_closed_before_the_driver_indexes(self) -> None:
        trust = _trust()
        assert "keyed on the `projectId`" in trust, trust
        assert "before `mcp-driver.mjs index`" in trust, trust


class TestTheStraysAreNotRemovedThroughTheSharedNames:
    """CR 2466: the strays share their names with the shared store's
    collections, so the remove tools, run from a restarted session, delete
    the SHARED collections. The cleanup is a prohibition, not a remark."""

    def test_the_remove_tools_are_ruled_out(self) -> None:
        trust = _trust()
        assert "Don't clean them up with the remove tools" in trust, trust
        assert "delete the **shared** collections" in trust, trust

    def test_the_safe_choices_are_named(self) -> None:
        trust = _trust()
        assert "remove them from the local Qdrant itself, or leave them" in trust


class TestTheStubCommandQuotesItsPlaceholders:
    """CR 2469: an entry or id substituted unquoted splits on a space or
    expands a glob, and the stub lands somewhere the link does not name."""

    def test_every_placeholder_is_quoted(self) -> None:
        command = (
            'mkdir -p "<entry>" && printf \'{"projectId": "%s"}\\n\' '
            '"<sibling-id>" > "<entry>/.socraticode.json"'
        )
        assert command in EXTERNAL_REF.read_text()


class TestTheSkillAndTheReferenceAgree:
    """CR 2470: three places where SKILL.md said less than, or other than,
    external-store.md."""

    def test_the_pre_index_check_is_phase_six_s_whole_check(self) -> None:
        """(a) The reference requires the store's endpoint and no container
        too; step 1 defers to Phase 6's check, which names all three."""
        flat = _flat(SKILL_MD)
        native = _section(flat, "**Preferred (native) path**", "**Fallback path**")
        assert "as Phase 6 checks it" in native, native
        phase6 = _section(flat, "### Phase 6", "**Graph yield")
        for phrase in ("Qdrant mode: external", "store's endpoint", "not a container"):
            assert phrase in phase6, (phrase, phase6)

    def test_the_row_names_the_host_step_on_either_store(self) -> None:
        """(b) On a managed store the step is a check-out, not a stub."""
        row = next(
            line
            for line in SKILL_MD.read_text().splitlines()
            if line.startswith("| Store config |")
        )
        assert "host step" in row, row
        assert "check-out" in row, row

    def test_the_path_hash_is_shared_only_by_one_layout(self) -> None:
        """(c) Only hosts with the same checkout layout share the hash."""
        flat = _flat(SKILL_MD)
        assert "checkout-path hash that hosts share." not in flat
        assert "checkout-path hash that hosts with one layout share" in flat

    def test_the_stub_paragraph_names_the_health_check_s_link_findings(self) -> None:
        """The daily check now names a full clone where a stub would do, and a
        link whose collection is missing or empty (#573)."""
        para = _section(_flat(EXTERNAL_REF), "**A stub is a host step", "## Adopting")
        assert "full clone" in para, para
        assert "missing or empty" in para, para
