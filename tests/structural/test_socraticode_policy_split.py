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
does **not** carry the ~680-byte prefetch string any more, and ships a degraded
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


GRAPH_HEALTH_HEADING = "## Graph health"

# The generated `docs/SOCRATICODE.md`'s own marker pair (#210). Distinct token
# from the `AGENTS.md` policy pair above — the two files are edited by different
# steps and a shared token would let one step's sweep find the other's block.
DOC_BEGIN = "<!-- BEGIN socraticode-doc -->"
DOC_END = "<!-- END socraticode-doc -->"
DOC_RESCUE_HEADING = "## Repo-specific notes"

# The ````markdown fence holding the generated file. Four backticks, because the
# template itself contains a ``` bash block.
_TEMPLATE_RE = re.compile(r"^````markdown$\n(.*?)^````$", re.DOTALL | re.MULTILINE)


def _template(doc_text: str) -> str:
    match = _TEMPLATE_RE.search(doc_text)
    assert match, (
        f"references/{DOC_REF.name} carries no ````markdown template fence — "
        "the file is the template for a generated doc and the fence is what "
        "marks which part gets written out"
    )
    return match.group(1)


def _graph_health(doc_text: str) -> str:
    """The `## Graph health` section, heading to the next `##`."""
    start = doc_text.index(GRAPH_HEALTH_HEADING)
    end = doc_text.find("\n## ", start + len(GRAPH_HEALTH_HEADING))
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

    def test_graph_health_explains_unresolved_pct(self, doc_text: str) -> None:
        """#198: the daily hook names `unresolvedPct`; the doc never did.

        `mcp-driver.mjs` emits `graph unresolved N% (> 50%) — corroborates a
        resolver problem` *outside* the verdict branches, so it fires on `ok`
        graphs too, and `socraticode-health.sh` runs it once per UTC day. A
        consumer reading only their generated doc had nothing to interpret it
        with, and the phrase parses as an accusation when it stands alone —
        one cohort repo distrusted a provably exact import graph for weeks on
        the strength of it.

        Pinned as concepts, not as a sentence: the section has to say what the
        statistic counts (call edges), what it is for (corroboration, not the
        verdict), and that a re-index does not move it.
        """
        section = _graph_health(doc_text)
        for concept, why in (
            ("unresolved", "the statistic the daily finding names"),
            ("call edge", "what it actually counts — not import edges"),
            ("corrobo", "it is reported beside the verdict, never as it"),
            ("re-index", "a framework-heavy repo's figure does not come down"),
        ):
            assert concept in section.lower(), (
                f"references/{DOC_REF.name}'s **Graph health** section must "
                f"cover {concept!r} — {why} (#198).\n---\n{section}"
            )

    def test_graph_health_names_the_metric_the_gate_uses(
        self, doc_text: str
    ) -> None:
        """The distinguishing signal, without which the rest is just reassurance.

        A high `unresolvedPct` looks identical on a healthy framework-heavy
        repo and on the src-layout resolver defect (`troubleshooting.md` row
        N). What separates them is edges/file, which is what the gate keys on.
        Telling a reader "do not worry about `unresolvedPct`" without telling
        them what to worry about instead trades one misreading for another.
        """
        section = _graph_health(doc_text)
        assert "edges/file" in section, (
            f"references/{DOC_REF.name}'s **Graph health** section must name "
            "edges/file — the metric `graphYield()` actually gates on — as the "
            "signal that separates a broken import graph from a framework-heavy "
            f"one (#198).\n---\n{section}"
        )

    def test_graph_health_does_not_link_the_skills_own_references(
        self, doc_text: str
    ) -> None:
        """This template is copied into a consumer repo's `docs/`.

        `references/troubleshooting.md` exists next to this file and nowhere
        near the generated doc, so a relative link to it resolves here and
        404s there — and `test_relative_links` blanks fenced blocks, so it
        would never catch the dead link either. Upstream issues get full URLs.
        """
        section = _graph_health(doc_text)
        assert "](troubleshooting.md" not in section, (
            "the **Graph health** section links `troubleshooting.md` relatively. "
            "That path exists only inside this skill; the generated "
            f"{OVERFLOW_DOC} would carry a dead link, and the fenced-block skip "
            f"in test_relative_links means nothing else would notice.\n---\n{section}"
        )
        assert "](references/" not in section, (
            "the **Graph health** section links into the skill's own "
            f"references/ tree, which does not exist beside {OVERFLOW_DOC}"
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


class TestOverflowDocHasARepoSpecificRegion:
    """#210: the generated doc had no marker pair, so a re-run destroyed prose.

    The template used to solve this by instruction — *"repo-specific
    exploration notes belong in `AGENTS.md`"* — which sends read-once detail
    into the one file the split exists to protect and the one section
    `curating-context` will not trim. It also does not work: `wslcb-licensing-
    tracker` accumulated three genuinely repo-specific blocks in its
    `docs/SOCRATICODE.md` (a measured-yield caveat, its real artifact list, and
    why its `.socraticodeignore` keeps `skills/`), and the next audit re-run
    would have deleted all three silently. The `low`-verdict path is worse: it
    tells the author to substitute real measured numbers into a file the
    template then overwrites.

    So the generated file gets the same shape the `AGENTS.md` block already
    has — replace between the markers, preserve what follows `END` — and the
    same rescue discipline for the unmarked files every consumer is carrying
    today.
    """

    @pytest.fixture(scope="class")
    def doc_text(self) -> str:
        return DOC_REF.read_text()

    @pytest.fixture(scope="class")
    def skill_md(self) -> str:
        return SKILL_MD.read_text()

    @pytest.fixture(scope="class")
    def rerun_ref(self) -> str:
        path = SKILL_DIR / "references" / "audit-rerun.md"
        assert path.exists(), f"{path} is missing"
        return path.read_text()

    def test_the_template_carries_both_markers(self, doc_text: str) -> None:
        template = _template(doc_text)
        for marker in (DOC_BEGIN, DOC_END):
            assert marker in template, (
                f"the generated file must carry {marker} so a re-run can "
                f"replace only the region it owns (#210).\n---\n{template}"
            )

    def test_the_markers_bound_the_whole_template(self, doc_text: str) -> None:
        """BEGIN first, END last — the template *is* the managed region.

        A marker pair around only part of the template would leave the rest
        outside anyone's ownership: neither replaced on a re-run nor safe from
        being replaced.
        """
        lines = [line for line in _template(doc_text).splitlines() if line.strip()]
        assert lines[0].strip() == DOC_BEGIN, (
            f"{DOC_BEGIN} must be the first line of the generated file, above "
            f"the H1; got {lines[0]!r}"
        )
        assert lines[-1].strip() == DOC_END, (
            f"{DOC_END} must be the last line the template writes, so every "
            f"line after it in a consumer's file is repo-authored; got "
            f"{lines[-1]!r}"
        )

    def test_the_header_no_longer_forbids_hand_editing_outright(
        self, doc_text: str
    ) -> None:
        template = _template(doc_text)
        assert "do not hand-edit." not in template.lower(), (
            "the generated file still forbids hand-editing outright. With a "
            "marker pair the rule is narrower and true: do not hand-edit "
            f"*above the {DOC_END} marker* (#210)"
        )
        assert "END marker" in template.split("## When to use each tool")[0], (
            "the header, before the first section, must name the END marker — "
            "it is the only place a reader learns where their own notes go"
        )

    def test_each_marker_appears_exactly_once_in_the_template(
        self, doc_text: str
    ) -> None:
        """The trap the sibling `_BLOCK_RE` comment already documents.

        Phase 3 finds the region by searching for the markers. If the header
        spells `<!-- END socraticode-doc -->` inline — the natural way to write
        "do not hand-edit above the END marker" — the search terminates four
        lines into the file and a re-run truncates the doc to its header. The
        prose says "END marker" for exactly this reason; the literal appears
        once, at the bottom, where it means something.
        """
        template = _template(doc_text)
        for marker in (DOC_BEGIN, DOC_END):
            assert template.count(marker) == 1, (
                f"{marker} appears {template.count(marker)} times in the "
                "generated file. Phase 3 locates the region by searching for "
                "these strings, so a second occurrence — even inside a code "
                "span in the header — bounds the wrong region."
            )

    def test_it_no_longer_banishes_repo_notes_to_agents_md(
        self, doc_text: str
    ) -> None:
        """The instruction #210 calls actively wrong.

        `AGENTS.md` is loaded on every invocation and `curating-context`
        refuses to edit the policy section, so this sent read-once detail into
        a permanent, uncurateable cost — the exact bill #115 split the file to
        avoid.
        """
        template = _template(doc_text)
        assert "## Code Exploration Notes (repo-specific)" not in template, (
            "the generated file still routes repo-specific exploration notes "
            "to `AGENTS.md`. That is the file the split exists to protect, and "
            "the policy section is the one `curating-context` will not trim "
            f"(#210, #115).\n---\n{template}"
        )

    def test_it_names_where_repo_notes_do_go(self, doc_text: str) -> None:
        assert DOC_RESCUE_HEADING in doc_text, (
            f"the template must name {DOC_RESCUE_HEADING!r} as the destination "
            "for repo-authored content, or 'preserved after END' is a rule "
            "with no address"
        )

    def test_skill_md_replaces_between_the_markers(self, skill_md: str) -> None:
        """Phase 3 is what an agent actually follows."""
        assert DOC_BEGIN in skill_md and DOC_END in skill_md, (
            "SKILL.md Phase 3 must name the marker pair it writes into "
            f"{OVERFLOW_DOC}; a marker only the reference knows about is not "
            "part of the procedure (#210)"
        )
        idx = skill_md.index("**Detail doc**")
        step = skill_md[idx:skill_md.index("\n3. ", idx)]
        assert "wholesale" not in step, (
            "SKILL.md Phase 3 still tells a re-run to overwrite "
            f"{OVERFLOW_DOC} wholesale.\n---\n{step}"
        )

    def test_skill_md_rescues_an_unmarked_existing_file(
        self, skill_md: str
    ) -> None:
        """Every consumer's current file has no markers.

        The first re-run after this change is the one that would destroy the
        content #210 was filed about, so the unmarked branch has to be written
        down — the way Phase 3's `AGENTS.md` step already writes it down.
        """
        idx = skill_md.index("**Detail doc**")
        step = skill_md[idx:skill_md.index("\n3. ", idx)]
        assert "rescue" in step.lower() or "preserve" in step.lower(), (
            "Phase 3's detail-doc step must say what happens to a consumer's "
            "existing, unmarked `docs/SOCRATICODE.md` — every repo installed "
            f"before #210 has one.\n---\n{step}"
        )

    def test_the_invariant_list_agrees(self, skill_md: str) -> None:
        """SKILL.md's own idempotency invariant said 'overwritten wholesale'."""
        idx = skill_md.index("**All file edits are idempotent.**")
        invariant = skill_md[idx:skill_md.index("\n- **", idx)]
        assert "wholesale" not in invariant, (
            "SKILL.md's idempotency invariant still describes "
            f"{OVERFLOW_DOC} as overwritten wholesale, which contradicts "
            f"Phase 3.\n---\n{invariant}"
        )

    def test_audit_rerun_covers_the_second_file(self, rerun_ref: str) -> None:
        """'The one thing a re-run must not do quietly' now has two shapes."""
        assert "wholesale" not in rerun_ref, (
            "audit-rerun.md's Phase 3 row still says `docs/SOCRATICODE.md` is "
            "overwritten wholesale (#210)"
        )
        assert OVERFLOW_DOC in rerun_ref.split("## One thing a re-run must not")[1], (
            "audit-rerun.md's 'must not do quietly' section covers only the "
            f"`AGENTS.md` span. {OVERFLOW_DOC} has the same failure and a "
            "larger blast radius — a whole file rather than one section (#210)"
        )
