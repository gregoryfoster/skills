"""The `init-socraticode` policy template stays split and stays small (#115, #107).

`init-socraticode` writes a `## Code Exploration Policy` section into every
consuming repo's `AGENTS.md`. Two properties of that section are load-bearing and
neither is visible from inside the skill:

- **It is a fixed cost.** `curating-context` declares the section *not its to
  edit* (`cohort-patterns.md`), so whatever the template puts there can never be
  curated away. Measured on `CannObserv/watcher` after a full curation run, the
  pre-split block was **1,247 exact tokens — 15% of the whole file and 21% of the
  6,000-token budget**, the single largest section, and it was the reason that
  repo could not reach budget without cutting class-A operational rules (#115).
  Every cohort member adopting the skill inherits the same bill.
- **It is the only thing an agent reads before choosing a tool.** When the
  dependency graph is low-yield, the graph tools answer *empty* rather than
  erroring, and a policy that routes to them turns a broken tool into a
  confident "nothing depends on this file" (#107). The degraded variant exists
  to say so out loud.

So this file asserts the shape rather than the prose: the rendered block stays
under a byte ratchet, keeps the negative rule and a link to the overflow doc,
does **not** carry the ~500-byte prefetch string any more, and ships a degraded
twin that names the failure mode. The overflow doc template has to carry what
the block gave up, or the split lost content instead of relocating it.

Bytes, not tokens, deliberately: pre-commit has no `ANTHROPIC_API_KEY`, and a
gate that only fires when someone holds a key is not a gate. The ratchet below
is a byte budget calibrated against the measured token count, the same trade
`test_skill_self_budget.py` documents.

No API calls, no network.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "init-socraticode"
POLICY_REF = SKILL_DIR / "references" / "code-exploration-policy.md"
DOC_REF = SKILL_DIR / "references" / "socraticode-doc.md"
SKILL_MD = SKILL_DIR / "SKILL.md"

BEGIN = "<!-- BEGIN socraticode-policy -->"
END = "<!-- END socraticode-policy -->"

# The rendered AGENTS.md section, marker to marker. Both variants live in the
# reference as fenced ```markdown blocks; the markers bound them exactly.
#
# Anchored to line boundaries on purpose. The prose above the blocks *names* the
# marker pair inline ("a `<!-- BEGIN socraticode-policy -->` / `<!-- END
# socraticode-policy -->` pair already exists"), and an unanchored match happily
# spans from that sentence's BEGIN to its END, yielding a one-line "block" that
# fails every content assertion for the wrong reason.
_BLOCK_RE = re.compile(
    r"^" + re.escape(BEGIN) + r"$.*?^" + re.escape(END) + r"$",
    re.DOTALL | re.MULTILINE,
)

# Byte ceilings for one rendered block, markers included — one per variant.
#
# Why bytes and why these numbers. #115 asked for "~300 tokens in the policy
# file". 300 tokens is ~715 bytes at the 2.38 bytes/token watcher measured for
# this content, which is below what the required parts (indexed-state line,
# negative rule, three tool rows, link) occupy once written honestly. Measured
# here instead of quoted:
#
#   pre-split template block   1,884 bytes   (~711 est tokens)
#   variant A (standard)       1,115 bytes   (~421 est tokens)   -41% bytes
#
# The token saving is larger than the byte saving because the one item that left
# is the densest: the single-line `select:` prefetch string — 499 bytes when the
# split landed, 677 since #209 widened it — is almost all fully-qualified tool
# names, ~200 tokens of near-pure repetition, and it was already being printed by
# the SessionStart hook this same skill installs.
# (Watcher's rendered section measured 1,247 exact tokens; that figure includes
# 732 bytes of repo-authored prose that is not in this template — see the
# corrections in #115. The template's own share was the ~711 above.)
#
# Variant B gets its own, higher ceiling because it earns it: it carries the
# "empty output is a tool failure" warning that is the entire reason it exists,
# and it is only ever installed on repos where the graph is already broken —
# where the alternative cost is an agent concluding "nothing depends on this
# file" from a tool that answered nothing (#107).
#
# Both are ratchets. Lower them when a later trim finds more; raising one means
# arguing in the diff, out loud, that a new line earns a permanent place in a
# file loaded on every single invocation and that `curating-context` will not
# touch.
BLOCK_BYTE_RATCHET = 1_300
DEGRADED_BLOCK_BYTE_RATCHET = 1_600

# Marker-pair discipline in one place: no test here should re-derive it.
NEGATIVE_RULE_MARKER = "**Negative rule.**"
OVERFLOW_DOC = "docs/SOCRATICODE.md"
PREFETCH_PREFIX = "select:mcp__plugin_socraticode_socraticode__codebase_search"

# The doc template's tool table, and the prefetch that has to cover it (#209).
TOOL_TABLE_HEADING = "## When to use each tool"
MCP_PREFIX = "mcp__plugin_socraticode_socraticode__"
_PREFETCH_RE = re.compile(r"select:" + MCP_PREFIX + r"[\w,]+")
_TOOL_RE = re.compile(r"`(codebase_\w+)`")


def _tool_table(doc_text: str) -> str:
    """The `## When to use each tool` section, heading to the next `##`.

    Scoped to the table on purpose. Other sections name `codebase_*` tools the
    prefetch deliberately omits — **Graph health** discusses
    `codebase_graph_status` only to say `READY` is not a yield measure, and
    routes the reader to `mcp-driver.mjs health-check` instead of calling it.
    Those are prose references, not recommendations; the table is the part of
    the doc an agent reads as "call this".
    """
    start = doc_text.index(TOOL_TABLE_HEADING)
    end = doc_text.find("\n## ", start + len(TOOL_TABLE_HEADING))
    return doc_text[start:end if end != -1 else len(doc_text)]


def _prefetched_tools(doc_text: str) -> set[str]:
    match = _PREFETCH_RE.search(doc_text)
    assert match, f"no `select:` prefetch query in references/{DOC_REF.name}"
    return {
        entry[len(MCP_PREFIX):]
        for entry in match.group(0)[len("select:"):].split(",")
        if entry.startswith(MCP_PREFIX)
    }


@pytest.fixture(scope="module")
def policy_text() -> str:
    return POLICY_REF.read_text()


@pytest.fixture(scope="module")
def blocks(policy_text: str) -> list[str]:
    found = _BLOCK_RE.findall(policy_text)
    assert found, f"{POLICY_REF.name} carries no {BEGIN} … {END} block at all"
    return found


class TestBothVariantsExist:
    """#107 needs a degraded twin of the very block #115 trimmed."""

    def test_two_variants(self, blocks: list[str]) -> None:
        assert len(blocks) == 2, (
            "expected exactly two rendered policy blocks in "
            f"{POLICY_REF.name} — variant A (standard) and variant B "
            f"(degraded, graph yield LOW); found {len(blocks)}"
        )

    def test_variants_are_labelled(self, policy_text: str) -> None:
        for heading in ("### Variant A — standard", "### Variant B — degraded"):
            assert heading in policy_text, (
                f"{POLICY_REF.name} must label its variants; missing {heading!r}. "
                "An unlabelled second block reads as a duplicate and gets 'fixed'."
            )


class TestBlockStaysSmall:
    """The block is paid on every invocation and cannot be curated away."""

    def test_under_byte_ratchet(self, blocks: list[str]) -> None:
        ratchets = (BLOCK_BYTE_RATCHET, DEGRADED_BLOCK_BYTE_RATCHET)
        oversize = [
            (f"variant {'AB'[i]}", len(b.encode()), ratchets[i])
            for i, b in enumerate(blocks)
            if len(b.encode()) > ratchets[i]
        ]
        assert not oversize, (
            f"policy block(s) over their byte ratchet (name, bytes, ratchet): "
            f"{oversize}. This section is loaded on every invocation and "
            "`curating-context` will not edit it, so growth here is permanent. "
            f"Move the addition to references/{DOC_REF.name} instead (#115)."
        )

    def test_prefetch_string_left_the_block(self, blocks: list[str]) -> None:
        """The 499-byte one-line `select:` query was the single biggest item."""
        for i, block in enumerate(blocks):
            assert PREFETCH_PREFIX not in block, (
                f"variant {i} still inlines the ToolSearch prefetch query. It is "
                "~680 bytes of fully-qualified tool names on one line, it is "
                "already printed by the SessionStart hook this skill installs, "
                f"and it belongs in {OVERFLOW_DOC} (#115)."
            )


class TestBlockKeepsWhatMatters:
    """Trimming is only correct if the class-A parts survive."""

    def test_negative_rule_present(self, blocks: list[str]) -> None:
        for i, block in enumerate(blocks):
            assert NEGATIVE_RULE_MARKER in block, (
                f"variant {i} dropped the negative rule. It is the one line an "
                "agent needs on nearly every task — semantic questions to "
                "`codebase_search`, `grep` only for exact strings."
            )

    def test_indexed_state_named(self, blocks: list[str]) -> None:
        for i, block in enumerate(blocks):
            assert ".socraticodecontextartifacts.json" in block, (
                f"variant {i} dropped the indexed-state line; an agent cannot "
                "tell a cold repo from a hot one without it."
            )

    def test_deferred_tools_flagged(self, blocks: list[str]) -> None:
        for i, block in enumerate(blocks):
            assert "deferred" in block, (
                f"variant {i} must say the `codebase_*` tools are deferred — "
                "calling one before the ToolSearch prefetch fails validation."
            )

    def test_links_to_overflow_doc(self, blocks: list[str]) -> None:
        for i, block in enumerate(blocks):
            assert OVERFLOW_DOC in block, (
                f"variant {i} must link {OVERFLOW_DOC}; without the link the "
                "trim is a deletion, not a split."
            )


class TestDegradedVariant:
    """#107: empty graph output must not read as 'no dependents'."""

    @pytest.fixture(scope="class")
    def degraded(self, blocks: list[str]) -> str:
        return blocks[1]

    def test_warns_empty_is_failure(self, degraded: str) -> None:
        assert "tool failure, not as absence" in degraded, (
            "the degraded variant's whole reason to exist is the sentence "
            "'treat empty graph output as tool failure, not as absence'. "
            "`codebase_graph_query` answers a low-yield graph with an ordinary "
            "'No dependency information found' sentence, which an agent reads "
            "as a fact about the code rather than about the tool (#107)."
        )

    def test_routes_dependency_questions_to_grep(self, degraded: str) -> None:
        row = [
            line for line in degraded.splitlines()
            if "Imports/dependents" in line
        ]
        assert row, "the degraded variant lost its imports/dependents row"
        assert "codebase_graph_query" not in row[0], (
            "the degraded variant still routes imports/dependents to "
            f"`codebase_graph_query`: {row[0]!r}. That is the broken tool."
        )
        assert "rg" in row[0] or "grep" in row[0], (
            f"the degraded variant must route dependency questions to grep: {row[0]!r}"
        )

    def test_standard_variant_still_uses_the_graph(self, blocks: list[str]) -> None:
        """Guard against the degraded wording leaking into variant A."""
        assert "codebase_graph_query" in blocks[0], (
            "variant A is the healthy-graph block and must still route "
            "imports/dependents to `codebase_graph_query`"
        )
        assert "tool failure, not as absence" not in blocks[0], (
            "variant A must not carry the degraded warning — a repo with a "
            "working graph would be told to distrust it"
        )


class TestOverflowDocTemplate:
    """What the block gave up has to land somewhere, or the split lost it."""

    @pytest.fixture(scope="class")
    def doc_text(self) -> str:
        assert DOC_REF.exists(), (
            f"{DOC_REF} is missing — the trimmed block links {OVERFLOW_DOC} and "
            "this reference is the template that writes it"
        )
        return DOC_REF.read_text()

    def test_carries_the_prefetch_query(self, doc_text: str) -> None:
        assert PREFETCH_PREFIX in doc_text, (
            f"references/{DOC_REF.name} must carry the full ToolSearch prefetch "
            "query — it is what the policy block stopped inlining"
        )

    def test_carries_the_full_tool_table(self, doc_text: str) -> None:
        """Every tool dropped from the block must be reachable from the doc."""
        for tool in (
            "codebase_search", "codebase_impact", "codebase_flow",
            "codebase_symbol", "codebase_graph_query", "codebase_context",
            "codebase_context_search",
        ):
            assert tool in doc_text, (
                f"references/{DOC_REF.name} is missing `{tool}`; the block's "
                "seven-row table was relocated here, not deleted"
            )

    def test_prefetch_covers_every_tool_the_table_recommends(
        self, doc_text: str
    ) -> None:
        """#209: the table and the prefetch are one file, twenty lines apart.

        The `codebase_*` schemas are **deferred** — calling one before the
        prefetch loads it fails validation. So a tool the table recommends but
        the prefetch omits is an `InputValidationError` for an agent following
        the doc it was just handed, which is the exact failure the prefetch
        exists to prevent. `codebase_graph_circular` sat in that gap in two
        cohort repos before anyone filed it.

        Asserted as a superset rather than tool-by-tool: the next row someone
        adds to the table is covered without their having to know this test is
        here. The prefetch may load *more* than the table lists — it already
        carries `codebase_status`, which no row names.
        """
        prefetched = _prefetched_tools(doc_text)
        recommended = sorted(set(_TOOL_RE.findall(_tool_table(doc_text))))
        missing = [tool for tool in recommended if tool not in prefetched]
        assert not missing, (
            f"references/{DOC_REF.name} recommends {missing} in its tool table "
            "but the `select:` prefetch does not load them. The schemas are "
            "deferred, so an agent that follows the table gets "
            "`InputValidationError` (#209). Add them to the prefetch string in "
            f"both pinned copies — this template and scripts/"
            "socraticode-reminder.sh — or drop the row."
        )

    def test_names_its_destination(self, doc_text: str) -> None:
        assert OVERFLOW_DOC in doc_text, (
            f"references/{DOC_REF.name} must name its destination "
            f"({OVERFLOW_DOC}) — the block's link has to resolve"
        )

    def test_skill_md_wires_it(self) -> None:
        body = SKILL_MD.read_text()
        assert DOC_REF.name in body, (
            f"SKILL.md must reference references/{DOC_REF.name} — Phase 3 writes "
            f"{OVERFLOW_DOC} from it (also: test_references.py forbids orphans)"
        )
        assert OVERFLOW_DOC in body, (
            f"SKILL.md must name {OVERFLOW_DOC} so the completion table and the "
            "re-run audit cover the new file"
        )


class TestUnmarkedSectionRescue:
    """#115's second finding: whole-span replacement deleted repo-authored prose.

    The unmarked branch replaces heading-to-next-`##`. `CannObserv/watcher` had
    grown a 732-byte repo-authored `Index scope` paragraph inside that span; a
    re-run would have deleted it with no warning. Correct per the old contract,
    and silent, which is what made it a defect.
    """

    RESCUE_HEADING = "## Code Exploration Notes (repo-specific)"

    def test_reference_documents_the_rescue(self, policy_text: str) -> None:
        assert self.RESCUE_HEADING in policy_text, (
            f"{POLICY_REF.name} must name the rescue destination "
            f"({self.RESCUE_HEADING!r}) so repo-authored content survives an "
            "unmarked-section replacement"
        )
        assert "repo-authored" in policy_text, (
            f"{POLICY_REF.name} must say which content is repo-authored — "
            "'anything the template does not itself carry' — or the rule is "
            "unfollowable"
        )

    def test_rescue_heading_survives_the_sweep(self, policy_text: str) -> None:
        """Step 2 deletes every other `## Code Exploration Policy` section."""
        assert self.RESCUE_HEADING != "## Code Exploration Policy", (
            "the rescue heading must differ from the policy heading or step 2's "
            "unconditional sweep deletes the rescued content on the next re-run"
        )

    def test_skill_md_carries_the_rule(self) -> None:
        body = SKILL_MD.read_text()
        assert self.RESCUE_HEADING in body, (
            "SKILL.md Phase 3 must carry the rescue rule, not only the "
            "reference — Phase 3 is what an agent follows when it edits "
            "AGENTS.md"
        )
