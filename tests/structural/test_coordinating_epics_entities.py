"""coordinating-epics: the ref readers decode an entity where GitHub does (#671).

GitHub decodes an HTML entity in Markdown text before it links refs. The
readers read the text as written, so the two disagreed in both directions: the
"#183" of "&#183;" (a "·") counted as a mention, which let an open #183 pass
`--account` untracked, and a real ref written "&#x23;49" wasn't counted.

Every rendering here was measured with `gh api markdown` (gfm mode, context
gregoryfoster/skills, 2026-11-16 and 2026-11-20). GitHub's rules are
cmark-gfm's, not `html.unescape`'s. A commit message isn't Markdown, and there
GitHub reads an entity as written: commit 608c8094's "&#183;" put a
`referenced` event on gregoryfoster/skills#183. A fake gh stands in for GitHub.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess

import pytest

from tests.structural.coordinating_epics_rig import SCRIPTS, Rig, summary

REPO = "acme/widgets"
EPIC = 10

BODY = """\
# Burn-down

- **Last check-in:** 2026-10-01T09:00Z
- **Last issue seen:** #14
- **Last verified SHA:** {sha}

## Tier 1

- [ ] #11 first thing
- [ ] #12 second thing

## Log

- 2026-10-01: created.
"""


def _load():
    spec = importlib.util.spec_from_file_location(
        "_epic_edit", SCRIPTS / "_epic_edit.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ee = _load()
H = REPO.lower()


def k(n: int, repo: str = H) -> str:
    return f"{repo}#{n}"


# ---------------------------------------------------------------- the decode


@pytest.mark.parametrize(
    "text, decoded",
    [
        ("&#183;", "·"),
        ("&#x23;49", "#49"),
        ("&#X23;62", "#62"),
        ("&amp;", "&"),
        ("&num;53", "#53"),
        ("&#35 58", "&#35 58"),
        ("&amp #59", "&amp #59"),
        ("&num86", "&num86"),
        ("&#00000035;70", "#70"),
        ("&#000000035;71", "&#000000035;71"),
        ("&#x00000023;74", "#74"),
        ("&#x000000023;75", "&#x000000023;75"),
        ("&nosuch;#76", "&nosuch;#76"),
        ("&#0;#78", "�#78"),
        ("&#1114112;#79", "�#79"),
        ("&#xD800;", "�"),
        ("\\&#35;51", "\\&#35;51"),
        ("\\\\&#35;88", "\\\\#88"),
        ("&amp;#183;", "&#183;"),
        ("no entity here", "no entity here"),
    ],
    ids=[
        "decimal",
        "hex",
        "hex-upper-x",
        "named-amp",
        "named-num",
        "decimal-needs-its-semicolon",
        "name-needs-its-semicolon",
        "legacy-name-needs-it-too",
        "eight-decimal-digits",
        "nine-is-no-entity",
        "eight-hex-digits",
        "nine-hex-is-no-entity",
        "unknown-name",
        "zero",
        "past-unicode",
        "surrogate",
        "escaped-amp",
        "escaped-backslash-then-entity",
        "one-pass",
        "plain",
    ],
)
def test_671_an_entity_decodes_by_githubs_rules_not_pythons(text, decoded):
    """Each row measured: the semicolon is required, a numeric entity has 1 to
    8 digits, an escaped "&" starts none, and the decode is one pass."""
    assert ee.decode_entities(text) == decoded


# ---------------------------------------------------------------- refs_in


@pytest.mark.parametrize(
    "line, refs",
    [
        ("- [x] #45 &#183; verified", {k(45)}),
        ("- [x] #48 &#x23;49 hex", {k(48), k(49)}),
        ("- [x] #46 &amp; #47 pair", {k(46), k(47)}),
    ],
    ids=["middot-is-no-mention", "hex-hash-is-a-ref", "amp-joins-two"],
)
def test_671_the_issues_three_rows_read_as_github_links_them(line, refs):
    assert ee.refs_in([line], REPO) == refs


@pytest.mark.parametrize(
    "line, refs",
    [
        ("named &num;53 here", {k(53)}),
        ("split #5&#52; digits", {k(54)}),
        ("digit #8&#x34; hex", {k(84)}),
        ("letter #85&#97; after", set()),
        ("word a&#35;61 joins", set()),
        ("qualified cli/cli&#35;55 here", {"cli/cli#55"}),
        ("double &amp;#183; amp", {k(183)}),
        ("escaped \\&#35;51 amp", {k(35)}),
        ("escaped \\\\&#35;88 backslash", {k(88)}),
        ("no semicolon &#35 58 here", {k(35)}),
        ("nine digits &#000000035;71", {k(35)}),
        ("nbsp a&nbsp;#80 here", {k(80)}),
        ("in html <b>&#35;93</b> here", {k(93)}),
    ],
    ids=[
        "named",
        "digits-join-across-an-entity",
        "hex-digit-joins",
        "a-decoded-letter-ends-no-ref",
        "a-word-before-the-hash",
        "qualified",
        "one-pass",
        "escaped-amp",
        "escaped-backslash",
        "no-semicolon",
        "nine-digits",
        "nbsp-before",
        "inside-an-html-tag",
    ],
)
def test_671_a_ref_is_read_after_the_decode(line, refs):
    assert ee.refs_in([line], REPO) == refs


@pytest.mark.parametrize(
    "lines, refs",
    [
        (["code span `&#x23;50` stays"], set()),
        (["``` text", "&#x23;50", "```"], set()),
        (["entity backticks &#96;#56&#96; here"], {k(56)}),
        (["entity brackets &#91;#57&#93;(https://example.com) here"], {k(57)}),
        (["link text [&#35;91](https://example.com) here"], set()),
        (["| a | b |", "|---|---|", "| &#35;94 x | y &#124; #95 |"], {k(94), k(95)}),
    ],
    ids=[
        "a-code-span-keeps-its-entity",
        "a-fence-keeps-its-entity",
        "decoded-backticks-are-no-span",
        "decoded-brackets-are-no-link",
        "link-text-links-nothing",
        "a-table-rows-cells",
    ],
)
def test_671_a_decoded_character_is_text_never_markup(lines, refs):
    """#415's rule holds: GitHub leaves an entity in code literal. And code
    spans and links are found on the text as written, so a backtick or a
    bracket that an entity spells opens nothing."""
    assert ee.refs_in(lines, REPO) == refs


@pytest.mark.parametrize(
    "line, refs",
    [
        ("bare https://github.com/cli/cli/issues&#47;98 here", set()),
        ("bare https://example.com/a/&#35;99 here", set()),
        (
            "bare https://github.com/cli/cli/issues/89&#35;issuecomment-1 here",
            {"cli/cli#89"},
        ),
        ("lt gt &lt;https://github.com/cli/cli/issues/97&gt; here", {"cli/cli#97"}),
    ],
    ids=["slash-entity", "hash-entity-in-a-path", "fragment-entity", "lt-gt-around"],
)
def test_671_a_url_is_read_as_written(line, refs):
    """GitHub leaves an entity in a bare URL alone: the first two render as
    plain links, and the last two as the issue's ref."""
    assert ee.refs_in([line], REPO) == refs


@pytest.mark.parametrize(
    "line",
    [
        "target [t](https://github.com/cli/cli/issues&#47;60) here",
        "angled <https://github.com/cli/cli/issues&#47;90> here",
    ],
    ids=["link-target", "angled-url"],
)
def test_671_an_entity_inside_an_issue_urls_path_is_an_accepted_under_read(line):
    """GitHub decodes these two and links the issue. Reading a URL as written
    is one rule that keeps the bare form right, at the price of this form,
    which nobody writes."""
    assert ee.refs_in([line], REPO) == set()


@pytest.mark.parametrize(
    "line", ["see foo&#47;#15", "see foo&sol;#15", "see foo&#x2f;#15"]
)
def test_cr2418_a_slash_an_entity_spells_reads_as_a_slash_does(line):
    """CR 2418, an accepted limit. GitHub links #15 here, as it links the
    plain "foo/#15" [measured]. The readers skip a ref after a "/", which is
    right inside a URL and an under-read outside one. That gap is older than
    #671 and is its own issue to file. At the base the entity form was read,
    by accident: the ";" stood before the "#". Decoded, it reads as the plain
    form does, so --account can now call #15 unlisted."""
    assert ee.refs_in([line], REPO) == ee.refs_in(["see foo/#15"], REPO) == set()


# ---------------------------------------------------------------- leads


@pytest.mark.parametrize(
    "line, subjects",
    [
        ("- [x] &#35;45 title", [k(45)]),
        ("- [x] #46 &#43; #47 pair", [k(46), k(47)]),
        ("- [x] #46&#44; #47 pair", [k(46), k(47)]),
        ("- [x] #46 `&#43;` #47 in code", [k(46)]),
        ("- [x] #46 &nosuch; #47 unknown", [k(46)]),
        ("- [x] #46 \\&amp; #47 escaped", [k(46)]),
    ],
    ids=[
        "an-entity-led-line",
        "plus-entity-joins",
        "comma-entity-joins",
        "a-joiner-in-code-joins-nothing",
        "an-unknown-name-joins-nothing",
        "an-escaped-amp-is-no-entity",
    ],
)
def test_671_a_lines_subject_is_read_after_the_decode(line, subjects):
    """line_subjects reads the raw line, not through outside_code. It is still
    safe from code: no pattern of a lead or a joiner admits a backtick."""
    assert ee.line_subjects(line, REPO) == ("item", subjects)


@pytest.mark.parametrize(
    "line",
    [
        "&nbsp;&nbsp;- [ ] #12 sub",
        "&#45; [ ] #12 old",
        "- [ ]&#32;#12 a space an entity spells",
        "- [ ] &nbsp;#12 after a second space",
        "&#45; #12 a bullet an entity spells",
        "| &nbsp;#12 | a cell |",
        "&#124; #12 | a pipe an entity spells |",
    ],
    ids=[
        "nbsp-indent",
        "entity-marker",
        "entity-space-after-the-box",
        "nbsp-before-the-ref",
        "entity-bullet",
        "nbsp-in-a-cell",
        "entity-pipe",
    ],
)
def test_cr2414_a_lines_marker_box_and_pipe_are_read_as_written(line):
    """CR 2414: the lead was matched on the decoded line, so an entity acted
    as markup. GitHub renders the first two as paragraphs, and at the base
    none of these led anything. Only what follows the marker is decoded."""
    assert ee.line_subjects(line, REPO) is None


# ---------------------------------------------------------------- the lint


def test_671_the_lint_reads_a_bare_ref_an_entity_spells():
    problems = ee.lint(
        ["see acme/gadgets#3, &#35;6 too", "and name&#35;5 here"],
        REPO,
        False,
        known=frozenset({6}),
    )
    assert any("bare #6 after acme/gadgets#" in p for p in problems), problems
    assert any("short ref name#5 links nowhere" in p for p in problems), problems


def test_cr2417_the_lints_own_refusals_apply_to_what_an_entity_spells(tmp_path):
    """CR 2417, kept on purpose. The lint reads the line as GitHub renders it,
    so its standing refusals reach a ref an entity spells: here "&amp;" is an
    "&", and GitHub links the bare #11 after cli/cli#5 as this repo's. The
    base accepted the line and wrote that wrong link. It is this set's second
    refusal that is new, with --account's, and for the same reason."""
    r = Rig(tmp_path)
    r.issue(REPO, EPIC, body=BODY.format(sha="0000000"))
    r.issue(REPO, 11)
    assert r.edit(REPO, EPIC, [], "--adopt-live").returncode == 0
    ops = [{"op": "log", "text": "{today}: cli/cli#5 &amp; #11 closed."}]
    res = r.edit(REPO, EPIC, ops, "--no-link-check")
    assert res.returncode == 3, res.stderr
    assert "bare #11 after cli/cli# reads as this repo's" in res.stderr


# ---------------------------------------------------------------- epic-edit.sh


@pytest.fixture
def adopted(tmp_path):
    r = Rig(tmp_path)
    r.issue(REPO, EPIC, body=BODY.format(sha="0000000"))
    for n in (11, 12):
        r.issue(REPO, n)
    res = r.edit(REPO, EPIC, [], "--adopt-live")
    assert res.returncode == 0, res.stderr
    return r


def test_671_account_refuses_an_open_issue_mentioned_only_as_an_entity(adopted):
    """The failure --account exists to prevent: #183 is open, and the body's
    only "mention" of it is a "·" spelled &#183;."""
    adopted.issue(REPO, 183)
    ops = [{"op": "log", "text": "{today}: #12 &#183; verified."}]
    res = adopted.edit(REPO, EPIC, ops, "--account")
    assert res.returncode == 3, res.stderr
    assert summary(res)["unlisted"] == [183]


def test_671_account_counts_a_ref_an_entity_spells(adopted):
    """The other direction: a real ref written &#x23;N refused a valid write."""
    adopted.issue(REPO, 13)
    ops = [{"op": "log", "text": "{today}: &#x23;13 out of epic."}]
    res = adopted.edit(REPO, EPIC, ops, "--account")
    assert res.returncode == 0, res.stderr


def test_671_a_middot_entity_isnt_linted_as_a_number_past_the_repos_highest(adopted):
    """The lint read &#9999; as a bare #9999, above the repo's highest."""
    ops = [{"op": "log", "text": "{today}: #12 &#9999; verified."}]
    res = adopted.edit(REPO, EPIC, ops)
    assert res.returncode == 0, res.stderr


def test_671_a_scans_new_issue_mentioned_only_as_an_entity_isnt_mentioned(adopted):
    adopted.issue(REPO, 183)
    report = adopted.tmp / "scan.json"
    report.write_text(
        json.dumps(
            {
                "repo": REPO,
                "epic": EPIC,
                "now": "2026-10-14T18:03:27Z",
                "max_number": 183,
                "updated_since": [],
                "new_numbers": [{"number": 183, "kind": "issue"}],
            }
        )
    )
    ops = [{"op": "log", "text": "{today}: #12 &#183; verified."}]
    res = adopted.edit(REPO, EPIC, ops, "--scan", str(report))
    assert res.returncode == 3 and "doesn't mention: #183" in res.stderr


@pytest.mark.parametrize(
    "line", ["&#45; [ ] #12 old", "&nbsp;&nbsp;- [ ] #12 sub"], ids=["marker", "indent"]
)
def test_cr2414_a_line_an_entity_makes_look_like_an_item_isnt_a_second_lead(
    adopted, line
):
    """With #12's real item beside it, tick was refused as ambiguous."""
    add = [{"op": "add-line", "section": "Log", "line": line}]
    assert adopted.edit(REPO, EPIC, add).returncode == 0
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#12"}])
    assert res.returncode == 0, res.stderr
    assert "- [x] #12 second thing" in adopted.body(REPO, EPIC)
    assert line in adopted.body(REPO, EPIC)


@pytest.mark.parametrize(
    "line",
    ["&#45; [ ] #13 old", "- [ ]&#32;#13 entity space"],
    ids=["entity-marker", "entity-space-after-the-box"],
)
def test_cr2414_such_a_line_alone_is_a_refusal_not_a_traceback(adopted, line):
    """The item was found on the decoded line and its box set on the raw one,
    where there was none: an AssertionError, exit 1."""
    adopted.issue(REPO, 13)
    add = [{"op": "add-line", "section": "Log", "line": line}]
    assert adopted.edit(REPO, EPIC, add).returncode == 0
    res = adopted.edit(REPO, EPIC, [{"op": "tick", "ref": "#13"}])
    assert res.returncode == 3, res.stderr
    assert "no checklist item leads with it" in res.stderr
    assert "Traceback" not in res.stderr


# ---------------------------------------------------------------- scan.sh


def git(repo, *args):
    r = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    )
    if r.returncode != 0:
        raise AssertionError(
            f"fixture git {' '.join(args)} exited {r.returncode} in {repo}:\n{r.stderr}"
        )
    return r.stdout.strip()


@pytest.fixture
def scanned(tmp_path):
    repo = tmp_path / "checkout"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "a@b")
    git(repo, "config", "user.name", "Coder")
    (repo / "f").write_text("0")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    r = Rig(tmp_path)
    r.checkout = repo
    base = git(repo, "rev-list", "--max-parents=0", "HEAD")
    r.issue(
        REPO, EPIC, body=BODY.format(sha=base[:9]), updated_at="2026-10-02T00:00:00Z"
    )
    for n in (11, 12, 14):
        r.issue(REPO, n, updated_at="2026-09-30T00:00:00Z", body="")
    return r


def scan(rig) -> dict:
    res = rig.run(
        "scan.sh",
        "--repo",
        REPO,
        "--epic",
        str(EPIC),
        "--git-dir",
        str(rig.checkout),
        "--ref",
        "main",
        "--no-fetch",
    )
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


@pytest.mark.parametrize(
    "body, mentions",
    [("Part of &#x23;10", True), ("Sizes 9 &#10; 11", False)],
    ids=["a-ref-an-entity-spells", "an-entity-that-holds-the-number"],
)
def test_671_the_scan_reads_an_epic_mention_after_the_decode(scanned, body, mentions):
    scanned.issue(REPO, 17, updated_at="2026-10-02T14:00:00Z", body=body)
    rows = {x["number"]: x for x in scan(scanned)["new_numbers"]}
    assert rows[17]["mentions_epic"] is mentions


@pytest.mark.parametrize(
    "message, children",
    [
        ("fix: the &#12; guard", ["acme/widgets#12"]),
        ("fix: the &#x23;12 guard", []),
    ],
    ids=["an-entity-holding-the-number", "a-hash-an-entity-spells"],
)
def test_671_a_commit_message_is_read_as_written(scanned, message, children):
    """A commit message isn't Markdown. Measured: 608c8094's "&#183;" put a
    `referenced` event on gregoryfoster/skills#183, so GitHub read it raw."""
    (scanned.checkout / "g").write_text("1")
    git(scanned.checkout, "add", ".")
    git(scanned.checkout, "commit", "-q", "-m", message)
    assert scan(scanned)["commits"][0]["children"] == children
