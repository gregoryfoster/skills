"""Every rendered relative link inside `skills/**/*.md` must resolve.

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

## Scope

- `skills/**/*.md` only. `AGENTS.md` and `docs/` have their own coverage.
- File resolution only, not `#anchor` resolution — anchors are
  `curating-context`'s job (`measure-context.sh`, `links.dead_anchors`).
- Inline links `[label](target)` and images `![alt](target)`. No reference-style
  definitions (`[ref]: target`) — none exist in `skills/` outside code fences.
- Indented (four-space) code blocks are not masked. Distinguishing one from a
  continuation paragraph inside a list is unreliable, no carve-out needs it, and
  `EXEMPT_LINKS` is the escape hatch if one ever does.

No API calls required.
"""

import re
from pathlib import Path
from urllib.parse import unquote

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "skills"

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


# Links that must stay dead. Key is `(path relative to repo root, exact target)`;
# value is the reason, which a reviewer reads in the diff.
#
# Empty by design — every illustrative link in this repo sits inside a code
# fence or code span and is skipped on principle rather than by name. Add an
# entry only for a link in *rendered prose* that must not resolve, and say why.
EXEMPT_LINKS: dict[tuple[str, str], str] = {}


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


def dead_links_in(markdown: Path, base: Path) -> list[tuple[str, int, str]]:
    """Return `(path-relative-to-base, line number, target)` for one file's dead links.

    A target is checked when it is relative and names a path: absolute URIs,
    protocol-relative URLs and bare `#fragment` anchors are out of scope, and a
    `#fragment`/`?query` suffix is stripped before resolving, so `foo.md#heading`
    is a check that `foo.md` exists and nothing more.
    """
    text = _mask_code(markdown.read_text())
    relative = markdown.relative_to(base).as_posix()
    findings: list[tuple[str, int, str]] = []
    for match in _LINK_RE.finditer(text):
        target = match["target"]
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        if not target or target.startswith("#") or _ABSOLUTE_RE.match(target):
            continue
        path = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if not path:
            continue
        if (markdown.parent / path).exists():
            continue
        findings.append((relative, text.count("\n", 0, match.start()) + 1, target))
    return findings


def dead_links(root: Path, base: Path | None = None) -> list[tuple[str, int, str]]:
    """`dead_links_in` over every `*.md` under `root`, in path order."""
    base = root if base is None else base
    return [
        finding
        for markdown in sorted(root.rglob("*.md"))
        for finding in dead_links_in(markdown, base)
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
        stale = stale_exemptions(dead_links(SKILLS_DIR, base=REPO_ROOT))
        assert stale == [], (
            "EXEMPT_LINKS entries no longer name a dead link — the link resolves, "
            f"moved, or was deleted. Remove them: {stale}"
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
