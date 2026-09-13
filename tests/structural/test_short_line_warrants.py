"""A line under 8 characters is warranted by naming all of it (#283).

`prove-no-loss.sh` refused any CONTENT under 8 characters, because CONTENT was
matched as a substring and a short substring identifies no line — `ly l`
matching one line today is luck. But a line under 8 characters has no longer
fragment to name. Deleted code is full of them:

- closers: `}`, `})`, `);`, `end`, `fi`, `done`, `esac`;
- fence openers with a language tag: ```js, ```sh, ```json, ```yaml;
- a bare closing fence, when the deleted block was the file's only one.

So a curation that deleted such a block could never reach `ok`, however
carefully it had judged every line — exit 3 without the entries, exit 1 with
them. `failed` then told `score-cohort.sh` content was dropped, the misreading
#111's warrants exist to prevent. #278 fixed the repeated lines of a deleted
sample; this is what it left.

The rule is the one the claim file already uses for ATOMs: below the floor,
CONTENT is matched WHOLE — by equality with a line, never as a substring — so
`disproven :: }` warrants every lost `}` and never reaches `return {}`.

One refinement on the issue's letter, pinned below. It asked that short CONTENT
"not a whole line at --base" be refused. A fragment of a base line is, which is
the `ly l` case. Content in no base line at all is not: that is the next run
after a curation deleted the line, or a run against another target, and under
equality such an entry can match nothing. Refusing it would turn the expiry
this file promises to report into an exit 1 on every later run.
"""

from pathlib import Path

from .test_loss_warrants import _ack, _prove, _repo

# The issue's reproduction: a file whose only other block is ```bash, so the
# bare closing fence survives and the two short lines are the whole residue.
SETUP = "## Setup\n\n```bash\nmake install\n```\n"
JS_BLOCK = "```js\nfunction connect(url) {\n  return open(url);\n}\n```\n"
LONG_LINES = ("function connect(url) {", "return open(url);")


def _deleted_js_block(tmp_path: Path) -> Path:
    before = f"# P\n\n{SETUP}\n## Client\n\nConnect first.\n\n{JS_BLOCK}"
    repo = _repo(tmp_path, before)
    (repo / "AGENTS.md").write_text(f"# P\n\n{SETUP}\n## Client\n\nConnect first.\n")
    return repo


def _long_entries() -> list[str]:
    return [f"disproven :: {line}" for line in LONG_LINES]


class TestADeletedBlockCanReachOk:
    def test_the_short_lines_are_the_residue(self, tmp_path: Path):
        """The issue's first bullet, pinned as the premise: with one entry per
        long line, exactly the opener and the closer are left, and nothing an
        entry of 8 characters could name."""
        repo = _deleted_js_block(tmp_path)
        _ack(repo, *_long_entries())
        r = _prove(repo)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "lost: 2" in r.stdout, r.stdout
        lost = [x.strip() for x in r.stdout.splitlines() if x.startswith("  LOST  ")]
        assert lost == ["LOST  ```js", "LOST  }"], r.stdout

    def test_one_entry_per_lost_line_exits_clean(self, tmp_path: Path):
        """The acceptance criterion, with the two entries the floor used to
        refuse: `}` is one character, ```js five."""
        repo = _deleted_js_block(tmp_path)
        _ack(repo, *_long_entries(), "disproven :: }", "disproven :: ```js")
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "loss_warranted: 4" in r.stdout, r.stdout
        assert "lost: 0" in r.stdout, r.stdout

    def test_copies_of_a_short_line_are_one_judgement(self, tmp_path: Path):
        """#278's rule holds at the short end: every lost `}` is the same text,
        so one entry covers them and the report counts them beside it."""
        block = (
            "```js\nfunction a() {\n  run();\n}\nfunction b() {\n  stop();\n}\n```\n"
        )
        repo = _repo(tmp_path, f"# P\n\n{SETUP}\n{block}")
        (repo / "AGENTS.md").write_text(f"# P\n\n{SETUP}")
        _ack(
            repo,
            "disproven :: ```js",
            "disproven :: function a() {",
            "disproven :: function b() {",
            "disproven :: run();",
            "disproven :: stop();",
            "disproven :: }",
        )
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "1 hit(s) x2: disproven :: }" in r.stdout, r.stdout
        assert "loss_warranted: 7" in r.stdout, r.stdout


class TestAShortEntryIsNeverASubstring:
    """The direction that matters. Accepting a one-character entry is only
    safe because it cannot reach any line but its own."""

    def test_a_closer_does_not_warrant_a_line_that_contains_one(self, tmp_path: Path):
        """The issue's second criterion. As a substring, `}` would reach
        `return {}` as well as `}` — and then be refused as over-broad, or,
        with `}` gone, wave the other line through."""
        block = "```js\nfunction empty() {\n  return {}\n}\n```\n"
        repo = _repo(tmp_path, f"# P\n\n{SETUP}\n{block}")
        (repo / "AGENTS.md").write_text(f"# P\n\n{SETUP}")
        _ack(
            repo,
            "disproven :: ```js",
            "disproven :: function empty() {",
            "disproven :: }",
        )
        r = _prove(repo)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "lost: 1" in r.stdout, r.stdout
        assert "  LOST  return {}" in r.stdout, r.stdout
        assert "over-broad" not in r.stderr, r.stderr

    def test_a_short_entry_reaches_a_line_only_whole(self, tmp_path: Path):
        """Whitespace around a line is not part of it, as everywhere in this
        report — the closer indented two levels is still `}`."""
        block = "```js\nif (x) {\n    wait(x);\n    }\n```\n"
        repo = _repo(tmp_path, f"# P\n\n{SETUP}\n{block}")
        (repo / "AGENTS.md").write_text(f"# P\n\n{SETUP}")
        _ack(
            repo,
            "disproven :: ```js",
            "disproven :: if (x) {",
            "disproven :: wait(x);",
            "disproven :: }",
        )
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr


class TestAFragmentIsStillRefused:
    """The issue's third criterion. `ly l` in test_loss_warrants.py runs
    unchanged; these pin the cases it does not."""

    def test_a_fragment_of_a_base_line_is_refused(self, tmp_path: Path):
        """`{` is inside `function connect(url) {` and is no line of its own:
        under equality it could never match, and as a substring it would be
        the luck the floor exists to refuse."""
        repo = _deleted_js_block(tmp_path)
        _ack(repo, *_long_entries(), "disproven :: {")
        r = _prove(repo)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "characters" in r.stderr and "at least 8" in r.stderr, r.stderr
        assert "loss_warranted" not in r.stdout, (
            "a refused ack file must not also emit a verdict: " + r.stdout
        )

    def test_the_refusal_names_every_way_out(self, tmp_path: Path):
        """Three things look like a fragment and the run cannot tell them
        apart: an entry written as one, an entry whose own short line is gone
        while a longer line holding its text remains, and an entry judged for
        another target. So the message names all three remedies."""
        repo = _deleted_js_block(tmp_path)
        _ack(repo, "disproven :: {")
        r = _prove(repo)
        assert r.returncode == 1, r.stderr
        assert "whole line" in r.stderr, r.stderr
        assert "prune" in r.stderr, r.stderr
        assert "PATH :: WARRANT :: CONTENT" in r.stderr, r.stderr


class TestAShortEntryWhoseLineIsGoneExpiresQuietly:
    """The refinement. Content in no line at --base cannot match anything, and
    is exactly what the run after a code-block deletion sees."""

    def test_the_next_run_reports_it_rather_than_refusing(self, tmp_path: Path):
        """The previous curation deleted the `}` and warranted it. This run's
        --base no longer holds any `}`, and the entry must age into the
        report every other expired entry lands in — not exit 1."""
        repo = _repo(tmp_path, f"# P\n\n{SETUP}\nKeep this line.\n")
        (repo / "AGENTS.md").write_text(f"# P\n\n{SETUP}\nKeep this line.\n")
        _ack(repo, "AGENTS.md :: disproven :: }")
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "matched nothing" in r.stdout, r.stdout
        assert "lost: 0" in r.stdout, r.stdout

    def test_an_unscoped_one_on_another_target_is_ambiguous_not_refused(
        self, tmp_path: Path
    ):
        """#251's case at the short end: unscoped, and absent from this
        target, the run cannot tell a gone line from an entry judged elsewhere
        — so it says so, and does not guess by refusing."""
        repo = _repo(tmp_path, f"# P\n\n{SETUP}")
        _ack(repo, "disproven :: }")
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "cannot tell which" in r.stdout, r.stdout

    def test_one_scoped_to_another_target_is_not_judged_here(self, tmp_path: Path):
        """Even a fragment of THIS target's line: an entry pinned elsewhere is
        about lines this run never read."""
        repo = _deleted_js_block(tmp_path)
        _ack(
            repo,
            *_long_entries(),
            "disproven :: }",
            "disproven :: ```js",
            "docs/API.md :: disproven :: {",
        )
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "scoped to another target" in r.stdout, r.stdout
