"""Every rendered relative link inside `skills/**/*.md` must resolve — file and
`#fragment` both.

Surfaced by #143. Two dead relative links sat in
`orchestrating-issue-backlog/references/process-log.md` across several sessions:
`[skills/using-git-worktrees/SKILL.md](../using-git-worktrees/SKILL.md)`, which
resolves one level short from `references/`, and a `src/templates/...` path that
belongs to a *different* repo. Both survived a full CR and every session that
edited the file, because a reader who knows what a link means never clicks it.
`test_references.py` checks that `references/` and `assets/` links named in a
SKILL.md resolve, but nothing checked the links *inside* those files, and
`curating-context`'s dead-link check runs against a consuming repo's context
surface, not this repo's own skills.

## The exemption mechanism, and why it is shaped this way

#143 proposed restricting the check to targets that begin `./` or `../`, on the
theory that every false positive is a bare `docs/`-style path standing in for a
consumer's tree. The orchestration comment disproved that: a relative-prefixed
example exists too. Neither claim survives contact with the real tree, because
both are discriminators over the *target string* when the real distinction is
about the *context the link sits in*.

Every carve-out in this repo is markup that a Markdown renderer never turns into
a link at all — it lives inside a fenced code block or an inline code span:

- `curating-context/SKILL.md` explains that a demoted block turns
  `` `](tests/x.py)` `` into `` `](../tests/x.py)` `` — inline code, and not even
  a whole link (no `[label]`), so a correct link regex never sees it.
- `curating-context/references/budget-and-metrics.md` quotes
  `` `[l](docs/FOO.md#some-heading)` `` as an inline code span while describing a
  bug in an *extractor*.
- `curating-context/references/cohort-patterns.md`,
  `init-project-fastapi/references/systemd-deploy.md` and
  `init-socraticode/references/code-exploration-policy.md` carry fenced blocks of
  template content destined for a *consuming* repo's tree.

So the rule is: a link inside code is not a link. It cannot exhibit the failure
this gate exists to prevent, because no reader can click it. That clears every
carve-out with an empty allowlist, and — unlike a target-string discriminator —
it does not weaken as soon as someone writes an example with a different prefix.

The limitation is deliberate and worth stating: a genuinely dead link written
inside a fence is not caught. That is the same trade as not spell-checking code.
Links in prose — the only place the observed failures occurred — are checked with
no exemption at all, and a new illustrative link in prose needs a reviewable
`EXEMPT_LINKS` entry to pass.

## The anchor half (#223)

This file used to end its scope section by handing `#anchor` resolution to
`curating-context` — `measure-context.sh`, `links.dead_anchors`. **That handoff
never landed.** `measure-context.sh` runs against a *consuming* repo's context
surface, `AGENTS.md` plus its `docs/` tree, and is never pointed at `skills/`;
`test_context_anchors.py` exercises the feature against synthetic tmp repos,
which verifies the detector, not this tree. So the job was disclaimed by one
test and picked up by no other, and 33 anchored links went unchecked.

It is the same defect class #120 built `links.dead_anchors` for: a link whose
file exists and whose heading does not, invisible to a file-resolution check.
Splitting an over-budget doc — the operation `curating-context` most
encourages — moves headings out of a file while leaving the file in place, so
the gate was blind exactly where the advice points.

`dead_anchors_in` reads from `_rendered_links`, the same extractor
`dead_links_in` uses, so "a link that counts here" and "a link whose anchor must
resolve" cannot drift apart — the argument `test_references.py` already makes
for sharing the extractor with reachability. It also settles the one link a
naive sweep of this tree calls broken: `` `[l](docs/FOO.md#some-heading)` `` in
`budget-and-metrics.md` is a code span, so the shared extractor never yields it
and it needs no `EXEMPT_LINKS` entry. Both halves ship with an empty registry.

`slugify` **re-states** GitHub's rules rather than sharing `measure-context.sh`'s
`slugs_of`, because that is a bash function running against another repo's tree
and cannot be imported — the same wall `test_context_link_grammar.py` hit for
`extract_links`, settled the same way, and `TestSlugifierAgreesWithMeasureContext`
pins the two against a shared table so a drift fails a test.

## Scope

- `skills/**/*.md` only. `AGENTS.md` and `docs/` have their own coverage.
- Both halves: the file must exist, and a `#fragment` on an existing `.md`
  target must name one of its ATX headings. A bare `[jump](#setup)` is checked
  against its own file — `measure-context.sh` checks those and
  `budget-and-metrics.md` documents that it does. A fragment on a non-`.md`
  target is not checked: `script.sh#L10` is GitHub's line anchor, not a heading.
- Inline links `[label](target)` and images `![alt](target)`. No reference-style
  definitions (`[ref]: target`) — none exist in `skills/` outside code fences.
- Indented (four-space) code blocks are not masked. Distinguishing one from a
  continuation paragraph inside a list is unreliable, no carve-out needs it, and
  `EXEMPT_LINKS` is the escape hatch if one ever does.

No API calls required. The two pin tests shell out to `measure-context.sh` with
`--no-write` and `ANTHROPIC_API_KEY` stripped from the environment, so it uses
its offline estimator — the same harness shape `test_context_link_grammar.py`
and `test_context_anchors.py` use.
"""

import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "skills"
MEASURE_CONTEXT = SKILLS_DIR / "curating-context" / "scripts" / "measure-context.sh"

# Inline link / image destination. The label may not contain `]`, which keeps
# the match from running past its own closing bracket; the destination stops at
# the first whitespace or paren so a CommonMark title (`[l](t "Title")`) is
# excluded rather than glued onto the path.
_LINK_RE = re.compile(
    r"!?\[[^\]]*\]\(\s*(?P<target>[^()\s]+)(?:\s+\"[^\"]*\")?\s*\)"
)

# A URI scheme (`https:`, `mailto:`, `tel:`, …) or a protocol-relative `//host`.
_ABSOLUTE_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.\-]*:|//)")

# An opening or closing code fence, per CommonMark: up to three spaces of
# indent, then at least three backticks or tildes.
_FENCE_RE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<info>.*)$")

# A backtick code span. The opening and closing runs must be the same length,
# hence the backreference and the lookarounds. A span may wrap onto the next
# line but not cross a blank one — a code span lives inside a paragraph — and
# that guard is load-bearing: without it a single unpaired backtick pairs with
# the next one hundreds of lines away and masks every link in between, turning
# the gate off in exactly the files most likely to have drifted.
_CODE_SPAN_RE = re.compile(
    r"(?<!`)(`+)(?!`)((?:(?!\n[ \t]*\n).)+?)(?<!`)\1(?!`)", re.DOTALL
)

# An ATX heading: up to three spaces of indent, one to six hashes, then a space.
# The space is required — `#!/bin/sh` and `#nohash` are not headings.
_ATX_RE = re.compile(r"^ {0,3}#{1,6} +(?P<text>.*)$")

# A closed ATX heading's trailing run: `## Heading ##`.
_CLOSED_ATX_RE = re.compile(r" +#+ *$")

# A link inside a heading. GitHub slugs the heading on the link's *text*, so the
# destination goes and the label's brackets are dropped as punctuation below.
_HEADING_LINK_RE = re.compile(r"\]\([^)]*\)")

# Everything GitHub drops when minting a heading id.
_NOT_IN_SLUG_RE = re.compile(r"[^a-z0-9 _-]")


# Links that must stay dead. Key is `(path relative to repo root, exact target)`;
# value is the reason, which a reviewer reads in the diff.
#
# Empty by design — every illustrative link in this repo sits inside a code
# fence or code span and is skipped on principle rather than by name. Add an
# entry only for a link in *rendered prose* that must not resolve, and say why.
EXEMPT_LINKS: dict[tuple[str, str], str] = {}


def _blank_fenced_lines(lines: list[str]) -> None:
    """Blank every line of every fenced block, in place, keeping line offsets.

    Shared by the two readers with opposite needs for code *spans*: a link's
    target must be read with spans masked, a heading's text must be read with
    them intact. Both need the same answer to "is this line inside a fence",
    and one nested-fence rule for the whole module is the point of sharing it.
    """
    open_fence: str | None = None
    for index, line in enumerate(lines):
        match = _FENCE_RE.match(line)
        if open_fence is None:
            # An opening backtick fence's info string may not contain a
            # backtick; that is what separates ```` ```python ```` from a code
            # span like `` `a` `` sitting alone on a line.
            if match and not (match["fence"][0] == "`" and "`" in match["info"]):
                open_fence = match["fence"]
                lines[index] = ""
        else:
            lines[index] = ""
            closes = (
                match is not None
                and match["fence"][0] == open_fence[0]
                and len(match["fence"]) >= len(open_fence)
                and not match["info"].strip()
            )
            if closes:
                open_fence = None


def _mask_code(text: str) -> str:
    """Blank out fenced blocks and inline code spans, preserving line offsets.

    Every masked character becomes `x` and every newline is kept, so a line
    number computed against the masked text still points at the right source
    line. Masking the *contents* of a span rather than dropping it also keeps a
    link whose label merely contains a code span intact:
    ``[`docs/X.md`](docs/X.md)`` becomes ``[xxxxxxxxxxx](docs/X.md)`` and is
    still checked.
    """
    lines = text.split("\n")
    _blank_fenced_lines(lines)
    masked = "\n".join(lines)
    return _CODE_SPAN_RE.sub(
        lambda m: m.group(1)
        + "".join("\n" if c == "\n" else "x" for c in m.group(2))
        + m.group(1),
        masked,
    )


def unexempted(findings: list[tuple[str, int, str]]) -> list[tuple[str, int, str]]:
    """Drop findings covered by an `EXEMPT_LINKS` entry."""
    return [f for f in findings if (f[0], f[2]) not in EXEMPT_LINKS]


def stale_exemptions(
    findings: list[tuple[str, int, str]],
) -> list[tuple[tuple[str, str], str]]:
    """Return `EXEMPT_LINKS` entries that no longer name a dead link in `findings`."""
    live = {(relative, target) for relative, _, target in findings}
    return [(key, reason) for key, reason in EXEMPT_LINKS.items() if key not in live]


def slugify(heading_text: str) -> str:
    """GitHub's id for one heading's text, before same-file duplicate suffixing.

    Lowercase, drop everything outside `[a-z0-9 _-]`, then one hyphen per
    remaining space. The last clause is the whole trap and it is why this is
    spelled as a substitution rather than a `\\s+` collapse: dropping a character
    leaves its spaces behind, so `Phase 5d — Provision PostgreSQL` becomes
    `phase-5d--provision-postgresql`, double hyphen and all. Collapsing runs
    validates against ids GitHub never mints, and this repo's headings are dense
    with em dashes — see `REAL_HEADINGS`.
    """
    text = _HEADING_LINK_RE.sub("]", heading_text).lower()
    return _NOT_IN_SLUG_RE.sub("", text).replace(" ", "-")


def heading_slugs(markdown: Path) -> list[str]:
    """Every ATX heading id in one file, in document order.

    A repeat of an earlier id in the SAME FILE gets `-1`, `-2`, … Per file, not
    per pre-split document: a split that moves the third `### PHP layers` into a
    file of its own makes it `php-layers` again (#120).

    Headings inside fenced blocks do not count — a `# comment` in a bash fence
    would otherwise manufacture an id that makes a genuinely dead anchor
    resolve, and this cohort's docs are dense with bash fences. Code *spans* are
    left intact, unlike in `_mask_code`: `` ### Backfilling `repo_commit` ``
    slugs on the word inside the backticks.

    Not modelled, matching `measure-context.sh`: explicit `<a id="…">` anchors
    and setext headings (`Title` over `=====`). Either produces a reported miss
    to judge rather than a silent pass, which is the safe direction. Neither
    exists in `skills/` today.
    """
    lines = markdown.read_text().split("\n")
    _blank_fenced_lines(lines)
    seen: dict[str, int] = {}
    slugs: list[str] = []
    for line in lines:
        match = _ATX_RE.match(line.replace("\t", "    "))
        if match is None:
            continue
        slug = slugify(_CLOSED_ATX_RE.sub("", match["text"].rstrip()))
        if not slug:
            continue
        seen[slug] = seen.get(slug, 0) + 1
        slugs.append(slug if seen[slug] == 1 else f"{slug}-{seen[slug] - 1}")
    return slugs


def _rendered_links(text: str) -> list[tuple[int, str]]:
    """`(line number, target)` for every relative link a renderer actually makes.

    The one extractor both halves of this gate read from, so "a link that counts
    here" and "a link whose anchor must resolve" cannot drift apart — the
    argument `test_references.py` already makes for sharing it with reachability.
    Absolute URIs and protocol-relative URLs are dropped as out of scope for both;
    everything else is left for the caller to filter, because a bare `#fragment`
    is nothing to the path half and the whole subject of the anchor half.
    """
    links: list[tuple[int, str]] = []
    for match in _LINK_RE.finditer(text):
        target = match["target"]
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        if not target or _ABSOLUTE_RE.match(target):
            continue
        links.append((text.count("\n", 0, match.start()) + 1, target))
    return links


def dead_links_in(markdown: Path, base: Path) -> list[tuple[str, int, str]]:
    """Return `(path-relative-to-base, line number, target)` for one file's dead links.

    A target is checked when it is relative and names a path: absolute URIs,
    protocol-relative URLs and bare `#fragment` anchors are out of scope here,
    and a `#fragment`/`?query` suffix is stripped before resolving — so this is a
    check that `foo.md` exists and nothing more. `dead_anchors_in` checks the
    fragment, off the same extractor.
    """
    text = _mask_code(markdown.read_text())
    relative = markdown.relative_to(base).as_posix()
    findings: list[tuple[str, int, str]] = []
    for line, target in _rendered_links(text):
        if target.startswith("#"):
            continue
        path = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if not path:
            continue
        if (markdown.parent / path).exists():
            continue
        findings.append((relative, line, target))
    return findings


def dead_anchors_in(markdown: Path, base: Path) -> list[tuple[str, int, str]]:
    """Return `(path-relative-to-base, line, target)` for fragments naming no heading.

    Checked only when the target is an existing `.md` file — a missing file is
    one defect, not two, and `dead_links_in` already holds it; `script.sh#L10` is
    GitHub's line anchor, not a heading id. An empty path means the file itself,
    so `[jump](#setup)` is checked against its own headings: a rename inside one
    long file breaks it exactly as a cross-file rename does.

    The fragment is compared lowercased and otherwise verbatim, matching
    `measure-context.sh`. GitHub only ever mints lowercase ids, so an author who
    typed `#Some-Heading` meant the heading that exists, and reporting that as a
    miss is the noise this class exists to avoid.
    """
    text = _mask_code(markdown.read_text())
    relative = markdown.relative_to(base).as_posix()
    findings: list[tuple[str, int, str]] = []
    for line, target in _rendered_links(text):
        path_part, _, fragment = target.partition("#")
        if not fragment:
            continue
        if path_part:
            path = unquote(path_part.split("?", 1)[0])
            if not path:
                continue
            resolved = markdown.parent / path
        else:
            resolved = markdown
        if resolved.suffix != ".md" or not resolved.is_file():
            continue
        if fragment.lower() in heading_slugs(resolved):
            continue
        findings.append((relative, line, target))
    return findings


def dead_links(root: Path, base: Path | None = None) -> list[tuple[str, int, str]]:
    """`dead_links_in` over every `*.md` under `root`, in path order."""
    base = root if base is None else base
    return [
        finding
        for markdown in sorted(root.rglob("*.md"))
        for finding in dead_links_in(markdown, base)
    ]


def dead_anchors(root: Path, base: Path | None = None) -> list[tuple[str, int, str]]:
    """`dead_anchors_in` over every `*.md` under `root`, in path order."""
    base = root if base is None else base
    return [
        finding
        for markdown in sorted(root.rglob("*.md"))
        for finding in dead_anchors_in(markdown, base)
    ]


_SKILL_MARKDOWN = sorted(SKILLS_DIR.rglob("*.md"))


@pytest.fixture(params=_SKILL_MARKDOWN, ids=lambda p: p.relative_to(SKILLS_DIR).as_posix())
def markdown(request) -> Path:
    return request.param


class TestRelativeLinks:
    """Rendered relative links in skills/**/*.md resolve from their own file."""

    def test_links_resolve(self, markdown: Path) -> None:
        for relative, line, target in unexempted(dead_links_in(markdown, base=REPO_ROOT)):
            pytest.fail(
                f"{relative}:{line} links to `{target}`, which does not resolve "
                f"relative to {markdown.parent.relative_to(REPO_ROOT).as_posix()}/. "
                f"Fix the path, or — if the link is illustrative and must stay "
                f"dead — add it to EXEMPT_LINKS in "
                f"tests/structural/test_relative_links.py with a reason."
            )

    def test_no_stale_exemptions(self) -> None:
        """An exemption whose link now resolves is a stale carve-out — drop it.

        Without this the registry only ever grows, and a target-string entry
        keeps silencing a link long after the path was fixed or deleted.
        """
        stale = stale_exemptions(
            dead_links(SKILLS_DIR, base=REPO_ROOT)
            + dead_anchors(SKILLS_DIR, base=REPO_ROOT)
        )
        assert stale == [], (
            "EXEMPT_LINKS entries no longer name a dead link — the link resolves, "
            f"moved, or was deleted. Remove them: {stale}"
        )


class TestSkillAnchors:
    """A `#fragment` in skills/**/*.md names a heading that exists.

    The half `test_links_resolve` never covered: the file resolves, the heading
    does not, and the reader lands at the top of a document that no longer holds
    what they were sent for.
    """

    def test_anchors_resolve(self, markdown: Path) -> None:
        for relative, line, target in unexempted(dead_anchors_in(markdown, base=REPO_ROOT)):
            path_part, _, fragment = target.partition("#")
            resolved = (markdown if not path_part else markdown.parent / path_part)
            pytest.fail(
                f"{relative}:{line} links to `{target}`, whose file resolves but "
                f"whose `#{fragment}` names no heading in "
                f"{Path(resolved).resolve().relative_to(REPO_ROOT).as_posix()}. "
                f"Fix the fragment, or — if the link is illustrative and must "
                f"stay dead — add it to EXEMPT_LINKS in "
                f"tests/structural/test_relative_links.py with a reason. "
                f"Headings there slug to: {heading_slugs(Path(resolved))}"
            )


class TestGateBehaviour:
    """The gate is proven against fixtures, not only against a passing tree.

    A structural gate that has never been seen to fail is indistinguishable from
    one that cannot fail. These build a throwaway tree instead of adding a dead
    link to a real file.
    """

    @staticmethod
    def _skills_tree(root: Path, link: str) -> Path:
        """Mirror the #143 layout: a `<skill>/references/` file linking a sibling skill."""
        (root / "using-git-worktrees").mkdir(parents=True)
        (root / "using-git-worktrees" / "SKILL.md").write_text("# skill\n")
        log = root / "orchestrating-issue-backlog" / "references" / "process-log.md"
        log.parent.mkdir(parents=True)
        log.write_text(f"See [the worktrees skill]({link}) for the flow.\n")
        return log

    def test_dead_prose_link_is_caught(self, tmp_path: Path) -> None:
        """The exact #143 link: one `../` short of its sibling skill."""
        self._skills_tree(tmp_path, "../using-git-worktrees/SKILL.md")
        assert dead_links(tmp_path) == [
            (
                "orchestrating-issue-backlog/references/process-log.md",
                1,
                "../using-git-worktrees/SKILL.md",
            )
        ]

    def test_resolving_link_passes(self, tmp_path: Path) -> None:
        """The same link with the depth it needed — the shipped fix."""
        self._skills_tree(tmp_path, "../../using-git-worktrees/SKILL.md")
        assert dead_links(tmp_path) == []

    def test_foreign_repo_path_is_caught(self, tmp_path: Path) -> None:
        """The second #143 link: another repo's path written as repo-relative."""
        (tmp_path / "log.md").write_text(
            "[_name_metadata_fields.html](src/templates/admin/_name_metadata_fields.html)\n"
        )
        assert [t for _, _, t in dead_links(tmp_path)] == [
            "src/templates/admin/_name_metadata_fields.html"
        ]

    def test_external_and_anchor_targets_are_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text(
            "[i](https://example.com/x.md) [m](mailto:a@b.c) [f](#heading) "
            "[p](//cdn.example/x.md)\n"
        )
        assert dead_links(tmp_path) == []

    def test_fenced_example_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text(
            "Append this to the consumer's README:\n\n"
            "```markdown\n"
            "- [docs/COMMANDS.md](docs/COMMANDS.md) — every runnable command\n"
            "```\n"
        )
        assert dead_links(tmp_path) == []

    def test_code_span_example_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text(
            "The extractor stripped the fragment, so `[l](docs/FOO.md#some-heading)` "
            "only checked the file.\n"
        )
        assert dead_links(tmp_path) == []

    def test_an_unpaired_backtick_does_not_mask_the_rest_of_the_file(
        self, tmp_path: Path
    ) -> None:
        """A stray backtick must not pair across a paragraph break and mute the gate."""
        (tmp_path / "a.md").write_text(
            "A stray ` backtick opens nothing.\n\nSee [gone](docs/GONE.md).\n\n"
            "And a closing ` here.\n"
        )
        assert [t for _, _, t in dead_links(tmp_path)] == ["docs/GONE.md"]

    def test_a_code_span_wrapping_one_line_is_still_masked(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text(
            "The extractor sees `[l](docs/FOO.md)\nand [m](docs/BAR.md)` as code.\n"
        )
        assert dead_links(tmp_path) == []

    def test_code_span_in_a_label_still_checks_the_target(self, tmp_path: Path) -> None:
        """Masking span *contents* must not hide the link the span sits inside."""
        (tmp_path / "a.md").write_text("See [`docs/GONE.md`](docs/GONE.md).\n")
        assert [t for _, _, t in dead_links(tmp_path)] == ["docs/GONE.md"]

    def test_fence_inside_a_fence_does_not_reopen_the_block(self, tmp_path: Path) -> None:
        """A longer outer fence wrapping a shorter inner one stays closed.

        `systemd-deploy.md` nests a ```bash block inside a ```markdown block;
        a naive tracker treats the inner opener as the outer closer and starts
        checking template content as prose.
        """
        (tmp_path / "a.md").write_text(
            "````markdown\n"
            "```bash\n"
            "echo hi\n"
            "```\n"
            "[t](docs/TEMPLATE.md)\n"
            "````\n"
            "[real](docs/REAL.md)\n"
        )
        assert [t for _, _, t in dead_links(tmp_path)] == ["docs/REAL.md"]

    def test_fragment_and_query_suffixes_are_stripped(self, tmp_path: Path) -> None:
        (tmp_path / "b.md").write_text("# b\n")
        (tmp_path / "a.md").write_text("[b](b.md#heading) [c](b.md?plain=1)\n")
        assert dead_links(tmp_path) == []

    def test_percent_escapes_are_decoded(self, tmp_path: Path) -> None:
        (tmp_path / "two words.md").write_text("# t\n")
        (tmp_path / "a.md").write_text("[t](two%20words.md)\n")
        assert dead_links(tmp_path) == []

    def test_image_targets_are_checked(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("![diagram](assets/missing.png)\n")
        assert [t for _, _, t in dead_links(tmp_path)] == ["assets/missing.png"]

    def test_link_title_is_not_part_of_the_target(self, tmp_path: Path) -> None:
        (tmp_path / "b.md").write_text("# b\n")
        (tmp_path / "a.md").write_text('[b](b.md "The B file")\n')
        assert dead_links(tmp_path) == []

    def test_directory_target_resolves(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "a.md").write_text("[sub](sub/)\n")
        assert dead_links(tmp_path) == []


class TestExemptionRegistry:
    """`EXEMPT_LINKS` ships empty, so its behaviour is proven against fixtures.

    An escape hatch nobody has exercised is a liability: it is where a future
    carve-out goes, and if it silences the wrong link — or never stops silencing
    a fixed one — the gate quietly stops gating.
    """

    _LOG = "orchestrating-issue-backlog/references/process-log.md"
    _DEAD = "../using-git-worktrees/SKILL.md"

    def test_ships_empty(self) -> None:
        """The survey behind #143 found no carve-out in rendered prose."""
        assert EXEMPT_LINKS == {}

    def test_an_entry_silences_exactly_its_own_link(self, tmp_path, monkeypatch) -> None:
        TestGateBehaviour._skills_tree(tmp_path, self._DEAD)
        other = tmp_path / "using-git-worktrees" / "notes.md"
        other.write_text("[gone](../elsewhere/GONE.md)\n")
        monkeypatch.setitem(EXEMPT_LINKS, (self._LOG, self._DEAD), "fixture")
        assert [t for _, _, t in unexempted(dead_links(tmp_path))] == [
            "../elsewhere/GONE.md"
        ]

    def test_an_entry_keyed_to_another_file_does_not_silence(
        self, tmp_path, monkeypatch
    ) -> None:
        """The key is `(file, target)`, so the same target stays dead elsewhere."""
        TestGateBehaviour._skills_tree(tmp_path, self._DEAD)
        monkeypatch.setitem(EXEMPT_LINKS, ("some/other/file.md", self._DEAD), "fixture")
        assert [t for _, _, t in unexempted(dead_links(tmp_path))] == [self._DEAD]

    def test_a_fixed_link_makes_its_exemption_stale(self, tmp_path, monkeypatch) -> None:
        TestGateBehaviour._skills_tree(tmp_path, "../../using-git-worktrees/SKILL.md")
        monkeypatch.setitem(EXEMPT_LINKS, (self._LOG, self._DEAD), "fixture")
        assert stale_exemptions(dead_links(tmp_path)) == [
            ((self._LOG, self._DEAD), "fixture")
        ]

    def test_a_still_dead_link_keeps_its_exemption_fresh(
        self, tmp_path, monkeypatch
    ) -> None:
        TestGateBehaviour._skills_tree(tmp_path, self._DEAD)
        monkeypatch.setitem(EXEMPT_LINKS, (self._LOG, self._DEAD), "fixture")
        assert stale_exemptions(dead_links(tmp_path)) == []

    def test_an_anchor_entry_silences_its_own_anchor(self, tmp_path, monkeypatch) -> None:
        """One registry serves both halves, so a dead anchor is exemptible too."""
        (tmp_path / "b.md").write_text("# B\n")
        (tmp_path / "a.md").write_text("[b](b.md#gone) [c](b.md#also-gone)\n")
        monkeypatch.setitem(EXEMPT_LINKS, ("a.md", "b.md#gone"), "fixture")
        assert [t for _, _, t in unexempted(dead_anchors(tmp_path))] == ["b.md#also-gone"]

    def test_a_fixed_anchor_makes_its_exemption_stale(self, tmp_path, monkeypatch) -> None:
        (tmp_path / "b.md").write_text("# B\n\n## Gone\n")
        (tmp_path / "a.md").write_text("[b](b.md#gone)\n")
        monkeypatch.setitem(EXEMPT_LINKS, ("a.md", "b.md#gone"), "fixture")
        assert stale_exemptions(dead_anchors(tmp_path)) == [
            (("a.md", "b.md#gone"), "fixture")
        ]


# Headings copied verbatim out of this repo's own tree, each with the id GitHub
# mints for it. The table is the instrument's calibration, not a sample of
# Markdown in general: four entries carry an em dash, and every one of those
# slugs to a DOUBLE hyphen, because the dash is dropped as punctuation and both
# of the spaces that flanked it still become hyphens.
#
# That case is the whole trap. A slugifier that collapses `\s+` to one hyphen
# passes every other row here and fails all four of those — and it fails them by
# declaring a live anchor dead, so the operator reads a repair list rather than a
# broken instrument. The first survey of this tree did exactly that and reported
# three anchors broken; none of them were.
REAL_HEADINGS: tuple[tuple[str, str], ...] = (
    # using-git-worktrees/SKILL.md
    ("## Venv linking — `.skills/worktree_venv`", "venv-linking--skillsworktree_venv"),
    (
        "### Phase 1 — Decide whether a worktree is appropriate",
        "phase-1--decide-whether-a-worktree-is-appropriate",
    ),
    ("### Phase 3.5 — Verify worktree health", "phase-35--verify-worktree-health"),
    # vendoring-openapi-client/references/carve-outs.md
    (
        "## pre-commit (when the repo uses it — `.pre-commit-config.yaml`)",
        "pre-commit-when-the-repo-uses-it--pre-commit-configyaml",
    ),
    # curating-context/references/telemetry.md — both are live anchor targets.
    ("### The pair, not the row", "the-pair-not-the-row"),
    ("### Backfilling `repo_commit`", "backfilling-repo_commit"),
    # curating-context/references/validation-gate.md — live anchor targets.
    (
        "### A registered metric may name its bound",
        "a-registered-metric-may-name-its-bound",
    ),
    (
        "### Warranted losses are not the same claim as no loss",
        "warranted-losses-are-not-the-same-claim-as-no-loss",
    ),
)


class TestSlugRules:
    """`slugify` mints the id GitHub mints, pinned against real headings."""

    @pytest.mark.parametrize("heading,slug", REAL_HEADINGS, ids=lambda v: v[:40])
    def test_a_real_heading_slugs_to_its_real_id(self, heading: str, slug: str) -> None:
        assert slugify(re.sub(r"^#+ +", "", heading)) == slug

    def test_a_dropped_character_leaves_both_of_its_spaces(self) -> None:
        """The trap, stated on its own so a failure names the cause.

        `— ` is not one separator; it is space, dash, space. Dropping the dash
        leaves two spaces, and one hyphen each is what GitHub emits.
        """
        assert (
            slugify("Phase 5d — Provision PostgreSQL") == "phase-5d--provision-postgresql"
        )

    def test_a_run_of_spaces_is_not_collapsed(self) -> None:
        assert slugify("a   b") == "a---b"

    def test_case_is_folded_and_punctuation_dropped(self) -> None:
        assert (
            slugify("The `count_tokens` fallback: why?") == "the-count_tokens-fallback-why"
        )

    def test_underscores_and_hyphens_survive(self) -> None:
        assert slugify("`--exact` and repo_commit") == "--exact-and-repo_commit"

    def test_non_ascii_is_dropped(self) -> None:
        assert slugify("Café ☕ break") == "caf--break"

    def test_a_link_in_a_heading_slugs_on_its_text(self) -> None:
        assert slugify("See [the rubric](keep-cut-rubric.md)") == "see-the-rubric"


class TestHeadingSlugs:
    """Which lines of a file are headings, and what a repeat is called."""

    @staticmethod
    def _doc(tmp_path: Path, body: str) -> Path:
        path = tmp_path / "d.md"
        path.write_text(body)
        return path

    def test_headings_are_returned_in_document_order(self, tmp_path: Path) -> None:
        doc = self._doc(tmp_path, "# One\n\ntext\n\n### Two words\n")
        assert heading_slugs(doc) == ["one", "two-words"]

    def test_a_repeat_gets_a_numeric_suffix(self, tmp_path: Path) -> None:
        """Per file, not per pre-split document — #120's finding."""
        doc = self._doc(tmp_path, "## PHP layers\n\n## PHP layers\n\n## PHP layers\n")
        assert heading_slugs(doc) == ["php-layers", "php-layers-1", "php-layers-2"]

    def test_a_closed_atx_heading_drops_its_trailing_hashes(self, tmp_path: Path) -> None:
        assert heading_slugs(self._doc(tmp_path, "## Heading ##\n")) == ["heading"]

    def test_a_heading_inside_a_fence_is_not_a_heading(self, tmp_path: Path) -> None:
        """A `# comment` in a bash fence otherwise manufactures an anchor.

        The manufactured id is worse than a missing one: it makes a genuinely
        dead anchor resolve, so the gate reports green on the defect it exists
        for. This cohort's docs are dense with bash fences.
        """
        doc = self._doc(tmp_path, "# Real\n\n```bash\n# install the hook\n```\n")
        assert heading_slugs(doc) == ["real"]

    def test_a_code_span_in_a_heading_is_not_masked(self, tmp_path: Path) -> None:
        """`_mask_code` would blank the span's *contents* and mis-slug the id.

        A link's target must be read with code masked; a heading's text must be
        read with code intact. `` ### Backfilling `repo_commit` `` is a live
        anchor target in this repo and slugs on the word inside the backticks.
        """
        doc = self._doc(tmp_path, "### Backfilling `repo_commit`\n")
        assert heading_slugs(doc) == ["backfilling-repo_commit"]

    def test_three_spaces_of_indent_is_still_a_heading(self, tmp_path: Path) -> None:
        assert heading_slugs(self._doc(tmp_path, "   ## Indented\n")) == ["indented"]

    def test_four_spaces_of_indent_is_a_code_block(self, tmp_path: Path) -> None:
        assert heading_slugs(self._doc(tmp_path, "    ## Indented\n")) == []

    def test_a_hash_without_a_space_is_not_a_heading(self, tmp_path: Path) -> None:
        assert heading_slugs(self._doc(tmp_path, "#nohash\n#!/bin/sh\n")) == []

    def test_a_setext_heading_is_not_modelled(self, tmp_path: Path) -> None:
        """Deliberate: an anchor into one reads as a miss to judge, not a pass.

        Same call `measure-context.sh` documents. `skills/` has no setext
        heading; if one arrives, a false miss is the safe direction.
        """
        assert heading_slugs(self._doc(tmp_path, "Title\n=====\n")) == []

    def test_a_nested_fence_does_not_reopen_the_block(self, tmp_path: Path) -> None:
        """Same rule the link masker already proves, applied to headings.

        `measure-context.sh`'s `slugs_of` toggles on the fence *character*, so a
        ```bash block inside a ````markdown block closes the outer one and it
        starts harvesting template headings. This restatement uses the fence
        tracker this module already ships instead of inheriting that.
        """
        doc = self._doc(
            tmp_path,
            "````markdown\n```bash\necho hi\n```\n## Template heading\n````\n## Real\n",
        )
        assert heading_slugs(doc) == ["real"]


class TestAnchorGateBehaviour:
    """The anchor half, proven against fixtures rather than a passing tree."""

    def test_a_missing_heading_is_caught(self, tmp_path: Path) -> None:
        (tmp_path / "b.md").write_text("# B\n\n## Adding a stage\n")
        (tmp_path / "a.md").write_text("See [b](b.md#adding-a-new-stage).\n")
        assert dead_anchors(tmp_path) == [("a.md", 1, "b.md#adding-a-new-stage")]

    def test_a_present_heading_passes(self, tmp_path: Path) -> None:
        (tmp_path / "b.md").write_text("# B\n\n## Adding a new stage\n")
        (tmp_path / "a.md").write_text("See [b](b.md#adding-a-new-stage).\n")
        assert dead_anchors(tmp_path) == []

    def test_an_em_dash_heading_resolves(self, tmp_path: Path) -> None:
        """The end-to-end form of the trap: real heading, real link, must pass."""
        (tmp_path / "b.md").write_text("### Phase 5d — Provision PostgreSQL\n")
        (tmp_path / "a.md").write_text("[b](b.md#phase-5d--provision-postgresql)\n")
        assert dead_anchors(tmp_path) == []

    def test_a_same_file_anchor_is_checked(self, tmp_path: Path) -> None:
        """A heading rename inside one long file breaks `[jump](#setup)` too.

        `measure-context.sh` checks these and `budget-and-metrics.md` documents
        that it does; `skills/` holds seven of them today.
        """
        (tmp_path / "a.md").write_text("# A\n\n## Setup\n\nJump to [it](#steup).\n")
        assert dead_anchors(tmp_path) == [("a.md", 5, "#steup")]

    def test_a_resolving_same_file_anchor_passes(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("# A\n\n## Setup\n\nJump to [it](#setup).\n")
        assert dead_anchors(tmp_path) == []

    def test_a_fragment_is_matched_case_insensitively(self, tmp_path: Path) -> None:
        """GitHub only mints lowercase ids; `#Some-Heading` meant the one that exists."""
        (tmp_path / "b.md").write_text("## Some Heading\n")
        (tmp_path / "a.md").write_text("[b](b.md#Some-Heading)\n")
        assert dead_anchors(tmp_path) == []

    def test_a_dead_file_is_one_defect_not_two(self, tmp_path: Path) -> None:
        """A missing file is already on the dead-link list; do not report it twice."""
        (tmp_path / "a.md").write_text("[b](gone.md#anything)\n")
        assert dead_anchors(tmp_path) == []
        assert [t for _, _, t in dead_links(tmp_path)] == ["gone.md#anything"]

    def test_a_non_markdown_target_is_not_anchor_checked(self, tmp_path: Path) -> None:
        """`script.sh#L10` is GitHub's line anchor, not a heading id."""
        (tmp_path / "script.sh").write_text("echo hi\n")
        (tmp_path / "a.md").write_text("[s](script.sh#L10)\n")
        assert dead_anchors(tmp_path) == []

    def test_a_link_with_no_fragment_is_not_anchor_checked(self, tmp_path: Path) -> None:
        (tmp_path / "b.md").write_text("# B\n")
        (tmp_path / "a.md").write_text("[b](b.md) [c](b.md#)\n")
        assert dead_anchors(tmp_path) == []

    def test_an_external_url_fragment_is_out_of_scope(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("[i](https://example.com/x.md#nope)\n")
        assert dead_anchors(tmp_path) == []

    def test_the_query_suffix_stays_with_the_path(self, tmp_path: Path) -> None:
        (tmp_path / "b.md").write_text("## H\n")
        (tmp_path / "a.md").write_text("[b](b.md?plain=1#h)\n")
        assert dead_anchors(tmp_path) == []

    def test_an_anchor_inside_a_code_span_is_skipped(self, tmp_path: Path) -> None:
        """The one non-resolver a naive sweep of this tree finds.

        `budget-and-metrics.md` quotes `` `[l](docs/FOO.md#some-heading)` `` while
        describing the #124 bug. A grep for `](*.md#` counts it; a renderer never
        makes it a link. Sharing this module's extractor is what makes that an
        exemption on principle rather than a named entry in `EXEMPT_LINKS` — the
        registry ships empty for the anchor half exactly as it does for links.
        """
        (tmp_path / "a.md").write_text(
            "The extractor stripped the fragment, so `[l](docs/FOO.md#some-heading)` "
            "only checked the file.\n"
        )
        assert dead_anchors(tmp_path) == []

    def test_an_anchor_inside_a_fence_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "b.md").write_text("# B\n")
        (tmp_path / "a.md").write_text("```markdown\n[b](b.md#not-a-heading)\n```\n")
        assert dead_anchors(tmp_path) == []

    def test_the_reported_line_is_the_source_line(self, tmp_path: Path) -> None:
        """Masking preserves offsets, so a fenced block above a link cannot shift it."""
        (tmp_path / "b.md").write_text("# B\n")
        (tmp_path / "a.md").write_text("```bash\necho hi\n```\n\n[b](b.md#gone)\n")
        assert dead_anchors(tmp_path) == [("a.md", 5, "b.md#gone")]

    def test_findings_are_relative_to_base(self, tmp_path: Path) -> None:
        nested = tmp_path / "skills" / "s" / "references"
        nested.mkdir(parents=True)
        (nested / "b.md").write_text("# B\n")
        (nested / "a.md").write_text("[b](b.md#gone)\n")
        assert dead_anchors(nested, base=tmp_path) == [
            ("skills/s/references/a.md", 1, "b.md#gone")
        ]


class TestSlugifierAgreesWithMeasureContext:
    """The restated slugifier is pinned to the shell one it deliberately re-states.

    `measure-context.sh` runs against a *consuming* repo's tree from bash, so its
    `slugs_of` cannot be imported — the same wall `test_context_link_grammar.py`
    hit for `extract_links` and settled the same way: re-state the rule here, and
    pin the two against a shared table so a drift fails a test instead of
    splitting the cohort's answer from this repo's.

    The pin is on the slug *transformation*, which is where the em-dash trap
    lives. Fence tracking is deliberately not pinned: `slugs_of` toggles on the
    fence character and this module's tracker does not, so a nested fence is a
    known, documented divergence rather than a shared rule.
    """

    @staticmethod
    def _dead_anchors(tmp_path: Path, doc: str, links: str) -> list[str]:
        repo = tmp_path / "repo"
        repo.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        for key in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR",
                    "ANTHROPIC_API_KEY"):
            env.pop(key, None)
        for args in (
            ("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t"),
        ):
            subprocess.run(["git", "-C", str(repo), *args], check=True,
                           capture_output=True, env=env)
        (repo / "docs").mkdir()
        (repo / "docs" / "GUIDE.md").write_text(doc)
        (repo / "AGENTS.md").write_text(links)
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True,
                       capture_output=True, env=env)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True,
                       capture_output=True, env=env)
        result = subprocess.run(
            ["bash", str(MEASURE_CONTEXT), "--no-write"],
            capture_output=True, text=True, cwd=str(repo), env=env, timeout=60,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)["links"]["dead_anchors"]

    def test_the_shell_resolves_every_slug_this_module_mints(self, tmp_path: Path) -> None:
        """One doc carrying the whole real-heading table, linked by our own ids."""
        doc = "# Guide\n\n" + "\n\n".join(h for h, _ in REAL_HEADINGS) + "\n"
        links = "# P\n\n" + "\n\n".join(
            f"[l{i}](docs/GUIDE.md#{slugify(re.sub(r'^#+ +', '', heading))})"
            for i, (heading, _) in enumerate(REAL_HEADINGS)
        ) + "\n"
        assert self._dead_anchors(tmp_path, doc, links) == []

    def test_the_shell_rejects_the_collapsed_whitespace_slug(self, tmp_path: Path) -> None:
        """The pin has teeth in the direction the trap runs.

        Were the shell tolerant of a single hyphen here, a restatement that
        collapsed `\\s+` would agree with it and both would be wrong together.
        """
        doc = "# Guide\n\n### Phase 5d — Provision PostgreSQL\n"
        links = "# P\n\n[l](docs/GUIDE.md#phase-5d-provision-postgresql)\n"
        assert self._dead_anchors(tmp_path, doc, links) == [
            "AGENTS.md -> docs/GUIDE.md#phase-5d-provision-postgresql"
        ]
