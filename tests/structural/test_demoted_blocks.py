"""A demoted "in full" block is a snapshot; nothing checked it against source (#148).

`curating-context` Phase 4 demotes a block out of `SKILL.md` into a reference
doc, and the destination receives it under a heading naming what it is —
`### The Phase 0 preflight, in full`, `### Tagging the row — the Phase 7 text in
full`, `The three surfaces Phase 8 offers once per repo, as SKILL.md carried
them before v1.7 demoted them here`. That convention is what makes demotion
lossless: the detail survives at a URL `SKILL.md` still points readers to.

It is also a **snapshot**. Phase 7 mandates a version bump precisely because
rules change, and when the rule in `SKILL.md` changes the snapshot silently
becomes a second, stale statement of the same rule at a URL the current
`SKILL.md` still recommends. `prove-no-loss.sh` cannot see this: the content did
not go missing, it went out of date, and both copies exist. The same class of
drift has now been observed twice in other skills — a finding format restated in
two files diverging over four versions (#142), and `tests/utils/assertions.py`
pinning `Suggested fix:` while the skill said `Suggested approach:` (#144).

Two mechanisms, chosen per block rather than by blanket rule:

  pinned    A block quoting a hard contract — an entry format, a flag name, a
            script name, an anchor — pins those tokens on *both* sides. This is
            the shape `test_finding_evidence.py` already uses for the
            `SKILL.md` <-> `dimensions.md` envelope, and it is the only one that
            catches **rewording**, the failure mode actually observed. Nearly
            every block quotes such a contract.
  dated     A block with no single token carrying the contract — either pure
            narrative, or a demotion so total that `SKILL.md` no longer states
            the rule at all — instead names the version it left, so a reader can
            see it is a historical record rather than current text. The
            exceptions: `continuous-surfaces.md`'s document preamble, and
            `cohort-patterns.md`'s no-`docs/`-tree note.

REGISTRY is the count of each. Writing the totals into this docstring would put a
number here that the next demotion falsifies — the drift this module exists to
catch, in the file that catches it.

Every discovered block must be covered by one or the other, and discovery is by
prose convention rather than by a hand-kept list — a newly demoted block that
nobody registers fails the first test in this module rather than joining the
unguarded set. That matters: the issue counted 8 blocks from one grep, #148
found 13, and #158 found three more that no grep could reach because their
headings never spoke the convention at all.

What this does NOT catch, stated so it is not rediscovered later:

- **Prose between the pins.** Pins are tokens, not the paragraph around them; a
  reworded justification with the flag name intact passes.
- **Other skills.** Discovery is scoped to `curating-context/references/`, whose
  Phase 4 owns this convention. A demoted block in another skill is unguarded.
- **Whether the snapshot is *useful*.** A block can agree with `SKILL.md` on
  every pinned token and still be redundant with it.

**Additions to `SKILL.md`** used to be on that list and no longer are.
`test_demoted_block_kinds.py` (#158) classifies every entry here as a historical
`record` or a living `excerpt` and holds excerpts to a check derived from the
source rather than registered — which is what it takes to catch a clause that
had not been written when the block was registered.

No API calls required.
"""

import re
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent / "skills" / "curating-context"
SKILL_MD = SKILL_DIR / "SKILL.md"
REFERENCES = SKILL_DIR / "references"

# The convention is spoken in several phrasings. A heading names the block; a
# lead-in sentence introduces the quoted text. Both mark a snapshot.
MARKER_HEADING = re.compile(
    r"^#{2,6} .*(?:\bin full\b|as SKILL\.md carried|as Phase \d+ carried it)", re.I
)
MARKER_LEAD_IN = re.compile(
    r"(?:carried|summarised|summarized|restated|said)\b[^.]*\binline until v\d"
    r"|in these words:"
    r"|as SKILL\.md carried them before",
    re.I,
)
ANY_HEADING = re.compile(r"^#{1,6} ")
VERSION = re.compile(r"\bv(\d+)\.(\d+)\b")


class Block:
    """One demoted snapshot: its marker line, and the text up to the next heading."""

    def __init__(self, doc: str, line_no: int, marker: str, text: str, fenced: bool):
        self.doc = doc
        self.line_no = line_no
        self.marker = marker
        self.text = text
        self.fenced = fenced

    @property
    def key(self) -> str:
        return f"{self.doc}:{self.line_no}"

    def __repr__(self) -> str:
        return f"<Block {self.key} {self.marker[:50]!r}>"


def _normalize(text: str) -> str:
    """Collapse whitespace and case.

    Markdown reflows: `(`--no-loss ok`)` in SKILL.md is `(`--no-loss\nok`)` in
    the snapshot that quotes it, and a pin must not fail on a rewrap it does not
    care about. Case likewise — no pin here depends on capitalisation to mean
    what it means, and `Archival subtrees` opening a sentence is the same
    contract as `archival subtrees` inside one.
    """
    return " ".join(text.split()).lower()


def _discover(path: Path) -> list[Block]:
    """Every demotion marker in one doc, deduped into blocks.

    A marker inside a preceding marker's extent belongs to that block — a
    `### … in full` heading followed by an `… inline until v1.9:` lead-in is one
    snapshot, not two.
    """
    lines = path.read_text().splitlines()
    fenced_at, fenced = [], False
    for line in lines:
        if line.startswith("```"):
            fenced = not fenced
            fenced_at.append(fenced)  # the fence line itself opens/closes
        else:
            fenced_at.append(fenced)

    blocks: list[Block] = []
    claimed_through = 0
    for i, line in enumerate(lines):
        if not (MARKER_HEADING.match(line) or MARKER_LEAD_IN.search(line)):
            continue
        if i < claimed_through:
            continue  # already inside the block a previous marker opened
        end = len(lines)
        for j in range(i + 1, len(lines)):
            if ANY_HEADING.match(lines[j]) and not fenced_at[j]:
                end = j
                break
        claimed_through = end
        blocks.append(
            Block(
                doc=path.name,
                line_no=i + 1,
                marker=line.strip(),
                text="\n".join(lines[i:end]),
                fenced=fenced_at[i],
            )
        )
    return blocks


def discover_blocks() -> list[Block]:
    found: list[Block] = []
    # Recursive. `curating-context/references/` is flat today, so this changes
    # nothing now — it is the guard against the discovery set going quietly
    # incomplete if a block is ever demoted into a subdirectory, which #152 made
    # a layout the suite permits.
    for path in sorted(REFERENCES.rglob("*.md")):
        found.extend(_discover(path))
    return found


# --------------------------------------------------------------------------
# The registry. Keyed by the marker's identifying phrase rather than by line
# number, which would rot on the first edit above it.
#
#   source  the SKILL.md `## ` heading opening the section the block snapshots.
#   pins    tokens that must survive in BOTH the block and that section.
#   dated   set instead of pins when no single token carries the contract; the
#           block must then name the version it was demoted from.
#   kind    what the block claims to be — `record` or `excerpt` (#158).
#   covers  excerpts only: the span of `source` this block is "in full" of.
#
# `kind` and `covers` are #158's axis and are orthogonal to `pins`/`dated`,
# which are #148's. `pins` asks *how agreement is verified*; `kind` asks *what
# the block is claiming*, which decides whether agreement is owed in one
# direction or two. `tests/structural/test_demoted_block_kinds.py` enforces
# them; the classification itself is argued there.
# --------------------------------------------------------------------------

PHASE_0 = "## Phase 0 — Preflight the credential"
PHASE_1 = "## Phase 1 — Measure"
PHASE_5 = "## Phase 5 — Apply"
PHASE_6 = "## Phase 6 — Prove no loss"
PHASE_7 = "## Phase 7 — Record and ship"
PHASE_8 = "## Phase 8 — Wire the continuous surfaces"
SCOPE = "## Scope: one repo, and only this repo"

REGISTRY: dict[tuple[str, str], dict] = {
    # -- budget-and-metrics.md -------------------------------------------------
    ("budget-and-metrics.md", "Phase 1 carried this and the archival exclusion inline"): {
        "source": PHASE_1,
        "kind": "record",  # "carried this ... inline until v1.9, in these words:"
        "pins": (
            "`totals.tokens_live`",
            "`policy.tokens`",
            "archival subtrees",
            "demotion *raises* it",
        ),
    },
    ("budget-and-metrics.md", "### The Phase 0 preflight, in full"): {
        "source": PHASE_0,
        # Undated and present tense: SKILL.md kept a *tightened* Phase 0 and this
        # is the long form a reader comes here for. It must track additions.
        "kind": "excerpt",
        "covers": ("One command, before anything else.", "refuses at the very end."),
        "pins": (
            "One command, before anything else",
            "Exit 0 means `--exact` will work",
            "exit 3 means resolve a credential **now**",
            "autonomously, **abort the run**",
            "eight phases of work toward a ledger row that `record-telemetry.sh` refuses",
        ),
    },
    ("budget-and-metrics.md", "### The Phase 1 credential note, in full"): {
        "source": PHASE_1,
        # "restated the rule above inline until v1.9, when it was demoted here
        # and replaced by a pointer. The words it carried:" — history, and the
        # heading's "in full" describes the quote, not a current claim.
        "kind": "record",
        "pins": (
            "A credential is not optional even interactively",
            "estimate whatever credential was accepted",
            "#measuring-tokens",
            "#the-baseline-row-is-not-optional-either",
        ),
    },
    # -- cohort-patterns.md ----------------------------------------------------
    ("cohort-patterns.md", "### Normalizing the index — the Phase 5 step in full"): {
        "source": PHASE_5,
        "kind": "record",  # "carried this inline until v1.7 demoted it here:"
        "pins": (
            "`## Detail Docs` section listing every live reference doc with a one-line purpose",
            "canonical section order",
            "`docs/` filenames to align with",
        ),
    },
    ("cohort-patterns.md", "### Starting with no `docs/` tree — the Phase 5 step 4 note in full"): {
        "source": PHASE_5,
        # Headed and dated by #158: it shipped as an indented block under the
        # filenames table introduced by nothing at all. Phase 5 no longer says
        # any of this — the demotion was total — so there is no token to pin on
        # both sides, and the date is the whole of what it owes.
        "kind": "record",
        "dated": True,
    },
    ("cohort-patterns.md", "### Demoting class B — the Phase 5 step 4 text in full"): {
        "source": PHASE_5,
        # Headed and dated by #158: it shipped as a bare `4.` opening a list of
        # one, under a heading about command blocks. The tail of its
        # relative-links bullet had been left behind in `validation-gate.md`.
        "kind": "record",
        "pins": (
            "unreviewable content change wearing a refactor's clothes",
            "Phase 6.5 checks both",
            "`prove-no-loss.sh` normalises exactly these two",
        ),
    },
    ("cohort-patterns.md", "### The rule in full"): {
        "source": SCOPE,
        # The block #158 was filed about. No date, no past tense, and a heading
        # promising the rule *in full* — so it owes the bidirectional check, and
        # failed it: SKILL.md's Scope grew `--no-write` after v1.7.
        "kind": "excerpt",
        "covers": ("This skill edits", "expected pre-adoption state"),
        "pins": (
            "This skill edits **the repo it is invoked in**",
            "It never writes to a sibling checkout, even one it just measured",
            "Cross-repo work is filed as **issues**, not commits",
        ),
    },
    # -- continuous-surfaces.md ------------------------------------------------
    ("continuous-surfaces.md", "as SKILL.md carried them before"): {
        "source": PHASE_8,
        # Narrative: a document preamble saying what the whole file is. It quotes
        # no flag, no script and no format — the only falsifiable thing in it is
        # *when* SKILL.md stopped carrying the three surfaces inline. Pinning
        # "three surfaces" against Phase 8 would assert a word, not a contract.
        "kind": "record",  # "as SKILL.md carried them before v1.7 demoted them here"
        "dated": True,
    },
    ("continuous-surfaces.md", "As Phase 8 summarised it inline until v1.9:", 1): {
        "source": PHASE_8,
        "kind": "record",  # "summarised it inline until v1.9:"
        "pins": (
            "`install-cadence.sh`",
            "**measurement, not a curation**",
            "`ANTHROPIC_API_KEY` repository secret",
        ),
    },
    ("continuous-surfaces.md", "As Phase 8 summarised it inline until v1.9:", 2): {
        "source": PHASE_8,
        "kind": "record",
        "pins": (
            "`context-delta.sh`",
            "`reviewing-code*`",
            "`Edit|Write|MultiEdit`",
            "`NotebookEdit`",
            "shell redirect",
        ),
    },
    ("continuous-surfaces.md", "As Phase 8 summarised it inline until v1.9:", 3): {
        "source": PHASE_8,
        "kind": "record",
        "pins": (
            "`install-guard.sh --budget 6000 --doc-budget 10000`",
            "`PostToolUse` hook",
            "never blocks",
        ),
    },
    # -- telemetry.md ----------------------------------------------------------
    ("telemetry.md", "### Tagging the row — the Phase 7 text in full"): {
        "source": PHASE_7,
        # Undated, present tense, "in full". Covers the tagging paragraph and
        # the attribution paragraph that follows it — not all of Phase 7, whose
        # remaining paragraphs went to four other destinations.
        "kind": "excerpt",
        "covers": (
            "`<N>` and `<M>` are Phase 6.5's two counts",
            "makes the cohort look uniform when it isn't.",
        ),
        "pins": (
            "`<N>`",
            "`<M>`",
            "`<W>`",
            "`loss_warranted:`",
            "Tag `--actions` honestly and specifically",
            '`"cleanup"` teaches nothing',
            '`"demote:Project Layout"`',
        ),
    },
    ("telemetry.md", "### The cross-repo view, as Phase 7 carried it"): {
        "source": PHASE_7,
        # Past tense in the heading itself, and its inner quote is dated to
        # v1.9. SKILL.md points readers at `## Cohort roll-up` above it, which
        # is the live statement; this is the record of the demoted wording.
        "kind": "record",
        # Unbackticked: the block spells the script inside a bash fence and in a
        # flagged invocation, never as a bare code span.
        "pins": (
            "cohort-report.sh",
            "cross-repo view",
        ),
    },
    # -- validation-gate.md ----------------------------------------------------
    ("validation-gate.md", "### The Phase 6 no-loss bullet in full"): {
        "source": PHASE_6,
        "kind": "excerpt",
        "covers": (
            "Every non-blank line of the policy file",
            "unscorable, never a pass.",
        ),
        "pins": (
            "present verbatim, inline or in a destination",
            "Exit 3 lists what is not",
            "distinctive-phrase grep is **not** sufficient",
            "(`--no-loss ok`)",
            "unscorable, never a pass",
        ),
    },
    ("validation-gate.md", "### Phase 6's remaining assertions in full"): {
        "source": PHASE_6,
        "kind": "excerpt",
        "covers": (
            "A line the run had to **rewrite** rather than move",
            "and no gate sees depth.",
        ),
        "pins": (
            "`.skills/context-loss-ok`",
            "`WARRANT :: CONTENT`",
            "`PATH :: WARRANT :: CONTENT`",
            "`--no-loss-warrants M`",
            "warrant from the closed set in `--help`",
            "`duplicated: N` lists them",
            "silently reparents everything below it",
            "**Never** warrant a line you have not read against its replacement",
        ),
    },
    ("validation-gate.md", "### Two more Phase 6 notes, in full"): {
        # Registered by #158. It was a demoted block all along — Phase 6's last
        # two bullets — but its heading did not speak the convention, so
        # `_discover` never saw it and #148 could not count it. It shipped with
        # the first of its two notes replaced by a stray tail of Phase 5's step
        # 4, five-space indented; `test_demotion_debris.py` is what found it.
        "source": PHASE_6,
        "kind": "excerpt",
        "covers": (
            "`policy.tokens` is at or under budget",
            "structural tests that read `AGENTS.md`.",
        ),
        "pins": (
            "or the Phase 4 report explains why not",
            "several cohort repos have structural tests",
        ),
    },
}


def _registry_key(block: Block, seen: dict[tuple[str, str], int]) -> tuple:
    """Match a discovered block to its registry key, disambiguating repeats.

    `continuous-surfaces.md` says "As Phase 8 summarised it inline until v1.9:"
    three times, once per surface, so identical markers are ordinal-suffixed in
    document order.
    """
    for key in REGISTRY:
        doc, phrase = key[0], key[1]
        if doc != block.doc or phrase not in block.marker:
            continue
        if len(key) == 2:
            return key
        seen[(doc, phrase)] = seen.get((doc, phrase), 0) + 1
        candidate = (doc, phrase, seen[(doc, phrase)])
        if candidate in REGISTRY:
            return candidate
        return candidate  # unregistered ordinal — reported by the coverage test
    return (block.doc, block.marker)


@pytest.fixture(scope="module")
def blocks() -> list[Block]:
    return discover_blocks()


@pytest.fixture(scope="module")
def matched(blocks: list[Block]) -> list[tuple[tuple, Block]]:
    seen: dict[tuple[str, str], int] = {}
    return [(_registry_key(b, seen), b) for b in blocks]


@pytest.fixture(scope="module")
def skill_text() -> str:
    return SKILL_MD.read_text()


@pytest.fixture(scope="module")
def skill_sections(skill_text: str) -> dict[str, str]:
    """SKILL.md split on `## ` headings."""
    sections: dict[str, str] = {}
    current, buf = None, []
    for line in skill_text.splitlines():
        if line.startswith("## "):
            if current:
                sections[current] = "\n".join(buf)
            current, buf = line.strip(), [line]
        elif current:
            buf.append(line)
    if current:
        sections[current] = "\n".join(buf)
    return sections


def _entries():
    """(key, entry) for every registry row, for parametrization."""
    return [pytest.param(k, v, id=f"{k[0]}::{k[1][:44]}" + (f"#{k[2]}" if len(k) > 2 else ""))
            for k, v in REGISTRY.items()]


class TestEveryDemotedBlockIsAccountedFor:
    def test_discovery_finds_the_blocks(self, blocks):
        assert blocks, (
            "No demoted blocks discovered in curating-context/references/. Either the "
            "convention was abandoned or the marker patterns in this module no longer "
            "match how Phase 4 writes them — check MARKER_HEADING / MARKER_LEAD_IN."
        )

    def test_no_block_is_unregistered(self, matched):
        unregistered = [b.key for key, b in matched if key not in REGISTRY]
        assert not unregistered, (
            f"Demoted blocks with no entry in REGISTRY: {unregistered}. A block demoted "
            "'in full' is a snapshot of a SKILL.md section; register it here with the "
            "section it snapshots and the contract tokens both sides must keep, or it "
            "joins the unguarded set this module exists to eliminate (#148)."
        )

    def test_no_registry_entry_is_stale(self, matched):
        found = {key for key, _ in matched}
        orphaned = [k for k in REGISTRY if k not in found]
        assert not orphaned, (
            f"REGISTRY entries matching no block in the tree: {orphaned}. The block was "
            "removed or its marker reworded; drop the entry or fix the phrase."
        )

    def test_no_marker_is_buried_in_a_code_fence(self, blocks):
        """A heading inside ```` ``` ```` is not a heading.

        `### Normalizing the index — the Phase 5 step in full` shipped inside the
        fenced `## Detail Docs` example from v1.7 until #148 — invisible as a
        heading, unlinkable, polluting the example it landed in, and with its
        first line lost in transit. Nothing saw it, because a fenced relative
        link is not a link either, so `test_relative_links.py` was silent too.
        """
        buried = [b.key for b in blocks if b.fenced]
        assert not buried, (
            f"Demotion markers inside a code fence: {buried}. A fenced heading renders "
            "as literal text — the block is unreachable by any anchor SKILL.md could "
            "point at, and no link or heading gate can see it."
        )


class TestEachBlockIsCoveredByAMechanism:
    @pytest.mark.parametrize("key,entry", _entries())
    def test_entry_declares_pins_or_a_date(self, key, entry):
        assert bool(entry.get("pins")) ^ bool(entry.get("dated")), (
            f"{key}: an entry must declare either `pins` (a hard contract quoted on both "
            "sides) or `dated` (narrative, so it must name the version it left SKILL.md "
            "at) — exactly one, so no block is silently exempt from both."
        )

    @pytest.mark.parametrize("key,entry", _entries())
    def test_pins_are_substantial(self, key, entry):
        pins = entry.get("pins") or ()
        if not pins:
            pytest.skip("dated entry")
        assert len(pins) >= 2, (
            f"{key}: pin at least two tokens. One token is one coincidence away from a "
            "check that passes for the wrong reason."
        )
        # A backticked token is discriminating by construction — `<N>` is short
        # and is nonetheless the exact placeholder Phase 7's command substitutes.
        # Bare prose has to be long enough not to collide by accident.
        flimsy = [p for p in pins if len(p) < 6 and not (p.startswith("`") and p.endswith("`"))]
        assert not flimsy, f"{key}: pins too short to discriminate: {flimsy}"


class TestTheSourceSectionStillExists:
    @pytest.mark.parametrize("key,entry", _entries())
    def test_source_heading_present(self, key, entry, skill_sections):
        assert entry["source"] in skill_sections, (
            f"{key} snapshots {entry['source']!r}, which SKILL.md no longer has. The "
            f"section was renamed or removed; the block is now a record of a rule with "
            f"no current statement. SKILL.md headings: {sorted(skill_sections)}"
        )


class TestPinnedContractsAgreeOnBothSides:
    @pytest.mark.parametrize("key,entry", _entries())
    def test_pins_present_in_the_source_section(self, key, entry, skill_sections):
        pins = entry.get("pins") or ()
        if not pins:
            pytest.skip("dated entry")
        section = _normalize(skill_sections[entry["source"]])
        missing = [p for p in pins if _normalize(p) not in section]
        assert not missing, (
            f"{key}: {entry['source']} no longer states {missing}. SKILL.md changed and "
            f"the demoted block still says the old thing — that is the drift #148 is "
            f"about. Update the block, or drop the pin if the contract genuinely went."
        )

    @pytest.mark.parametrize("key,entry", _entries())
    def test_pins_present_in_the_demoted_block(self, key, entry, matched):
        pins = entry.get("pins") or ()
        if not pins:
            pytest.skip("dated entry")
        block = next(b for k, b in matched if k == key)
        text = _normalize(block.text)
        missing = [p for p in pins if _normalize(p) not in text]
        assert not missing, (
            f"{block.key}: the block claims to carry {entry['source']} in full but no "
            f"longer states {missing}."
        )

    @pytest.mark.parametrize("key,entry", _entries())
    def test_at_least_one_pin_binds_to_the_registered_section(self, key, entry, skill_sections):
        """A pin every section shares proves nothing about *this* one."""
        pins = entry.get("pins") or ()
        if not pins:
            pytest.skip("dated entry")
        for pin in pins:
            hits = [h for h, body in skill_sections.items() if _normalize(pin) in _normalize(body)]
            if hits == [entry["source"]]:
                return
        pytest.fail(
            f"{key}: no pin is unique to {entry['source']} — every one also appears in "
            "another SKILL.md section, so the pins would still pass if the block were "
            "re-sourced from the wrong place. Pin something this section alone says."
        )


class TestDatedBlocksSayWhenTheyLeft:
    @pytest.mark.parametrize("key,entry", _entries())
    def test_narrative_block_names_its_version(self, key, entry, matched):
        if not entry.get("dated"):
            pytest.skip("pinned entry")
        block = next(b for k, b in matched if k == key)
        assert VERSION.search(block.text), (
            f"{block.key}: this block carries no pinnable contract, so the one thing it "
            "must do is say which SKILL.md version it was demoted from — otherwise a "
            "reader cannot tell a historical record from current text."
        )

    def test_no_block_claims_a_version_that_does_not_exist_yet(self, blocks, skill_text):
        m = re.search(r'^\s*version:\s*"?(\d+)\.(\d+)"?', skill_text, re.M)
        assert m, "SKILL.md frontmatter has no `version:`"
        current = (int(m.group(1)), int(m.group(2)))
        ahead = [
            (b.key, f"v{a}.{mi}")
            for b in blocks
            for a, mi in [(int(x), int(y)) for x, y in VERSION.findall(b.text)]
            if (a, mi) > current
        ]
        assert not ahead, (
            f"Blocks dated after SKILL.md's own version v{current[0]}.{current[1]}: {ahead}. "
            "A snapshot cannot predate a version that has not shipped."
        )
