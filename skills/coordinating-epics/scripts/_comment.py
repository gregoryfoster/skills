#!/usr/bin/env python3
"""Lint a comment with the epic editor's rules, then post it and read it back.

The engine behind comment.sh; run that, not this. Stdlib only, Python 3.9+.

epic-edit.sh guards the epic's body, but briefs, write-backs and closing
notes go out as comments, and these went wrong in live runs
(gregoryfoster/skills#395, broker#80 97/120/125): a short ref that links
nowhere, a bare #N after a qualified ref, a leftover SUBn or {{…}}, an
unexpanded $VAR from an unquoted heredoc, a comment link to the wrong issue.
So the whole comment goes through the editor's own lint(), with fenced() and
tabled() read over the whole body (a comment has no earlier version to diff),
before anything is posted. The post is read back, because an exit code alone
proves nothing (address-validator#272 finding 48).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _epic_edit import (  # noqa: E402
    REPO_FORM,
    Infra,
    Parser,
    Refused,
    Usage,
    add_token_flag,
    fenced,
    gh_cause,
    gh_json,
    indented,
    lint,
    load_tokens,
    normalize,
    split_raw,
    tabled,
)

EXIT_OK, EXIT_USAGE, EXIT_INFRA, EXIT_REFUSED, EXIT_READBACK = 0, 1, 2, 3, 4
# GitHub refuses a longer comment body: "Body is too long" [stated: GitHub's
# own error text, not measured here].
COMMENT_LIMIT = 65536
# How far before the post a listing looks for a comment a failed POST may
# still have stored: the local clock and GitHub's can disagree.
CLOCK_SLACK = dt.timedelta(minutes=10)

USAGE_EXTRA = """\
modes:
  --issue N --body-file F    lint F, post it on issue N, read the comment back
  ... --dry-run              lint F and read issue N; post nothing
  --lint-file F              lint F only, with no issue and no write: a body
                             posted another way, such as a new epic's before
                             gh issue create
  ... --predicted N          a ref to #N, the number that new issue will
                             take, isn't refused as above the repo's highest

lint:
  epic-edit.sh's own (its --help, "lint"), over the whole body: short refs, a
  bare #N after another repo's ref, SUBn and {{...}} placeholders, uninjected
  {now}/{today}, unexpanded shell variables, escaped backticks, secrets, a
  bare #N above --repo's highest number, and comment links that don't resolve
  to the issue they name (--no-link-check skips those). A fenced block is
  checked for secrets only; a code span skips all but SUBn and secrets. A
  bare #N is --repo's, as GitHub renders it in a comment there.

  An empty or whitespace-only file is refused, and so is a body over GitHub's
  65,536-character cap for a comment.

exit codes:
  0  posted and read back matching; with --dry-run or --lint-file, clean
  1  usage: a bad flag, an unreadable file or a bad --token-for. Nothing was
     fetched or posted.
  2  infrastructure: gh failed (its own stderr is shown). Nothing was posted,
     including a POST gh reported failed when the issue's comments since then
     hold no such comment.
  3  refused: an empty file, a body over the cap, or a lint finding. Nothing
     was posted.
  4  not confirmed: posted (summary "posted": true) but the read-back failed
     or differs, or the POST failed and the issue's comments couldn't be read
     to see whether it landed ("posted": "unknown"). Read the issue's comments
     before posting again: a second post is a duplicate.
"""


def same(sent: str, back: str) -> bool:
    """Whether GitHub kept the body sent: raw lines, else as GitHub rewrites
    them (CRLF, trailing whitespace), as the editor's read-back compares."""
    return split_raw(back) == split_raw(sent) or normalize(back) == normalize(sent)


def check(
    text: str, host: str, check_links: bool, known: frozenset[int] = frozenset()
) -> list[str]:
    """The lint's findings for the whole body; Refused for one with nothing to lint."""
    if not text.strip():
        raise Refused("the file is empty or whitespace only; nothing to post")
    if len(text) > COMMENT_LIMIT:
        raise Refused(
            f"the body is {len(text):,} characters, and GitHub refuses a comment"
            f" over {COMMENT_LIMIT:,}. Split it, oldest part first"
        )
    lines = text.replace("\r\n", "\n").split("\n")
    return lint(lines, host, check_links, fenced(lines), tabled(lines), known)


def landed(host: str, issue: int, text: str, since: dt.datetime) -> dict | None:
    """The comment a failed POST stored after all, newest first, or None.

    A 502 or a timeout can come back after GitHub stored the comment (the
    editor's CR 309), and posting again would duplicate it.
    """
    ts = (since - CLOCK_SLACK).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = gh_json(
        ["api", f"repos/{host}/issues/{issue}/comments?since={ts}&per_page=100"],
        "listing the issue's comments since the post",
    )
    hits = [
        c
        for c in rows or []
        if isinstance(c, dict) and same(text, str(c.get("body") or ""))
    ]
    return hits[-1] if hits else None


def run(argv: list[str]) -> int:
    p = Parser(
        prog="comment.sh",
        description="Lint a comment with epic-edit.sh's rules, then post it and read it back.",
        epilog=USAGE_EXTRA,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--repo",
        required=True,
        help="owner/repo the comment goes to; its bare #N refs are this repo's",
    )
    p.add_argument("--issue", type=int, help="the issue or PR to comment on")
    p.add_argument("--body-file", metavar="F", help="the comment's text")
    p.add_argument(
        "--lint-file",
        metavar="F",
        help="lint F only: no --issue, nothing posted",
    )
    p.add_argument(
        "--predicted",
        type=int,
        metavar="N",
        help="with --lint-file: the number the body's own issue will take, so a"
        " ref to it isn't refused as above the repo's highest",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="lint and read the issue, post nothing",
    )
    p.add_argument(
        "--no-link-check", action="store_true", help="skip resolving comment links"
    )
    add_token_flag(p)
    a = p.parse_args(argv)
    host = a.repo
    if not re.fullmatch(REPO_FORM, host):
        p.error("--repo must be owner/repo")
    if a.lint_file is not None:
        if a.issue is not None or a.body_file is not None or a.dry_run:
            p.error("--lint-file takes no --issue, --body-file or --dry-run")
    elif a.predicted is not None:
        p.error("--predicted goes with --lint-file only")
    elif a.issue is None or a.body_file is None:
        p.error("give --issue N and --body-file F, or --lint-file F")
    summary: dict = {"repo": host}
    if a.lint_file is None:
        summary.update(issue=a.issue, dry_run=a.dry_run, posted=False)
    try:
        load_tokens(a.token_for)
        path = a.lint_file if a.lint_file is not None else a.body_file
        try:
            text = Path(path).read_text()
        except (OSError, UnicodeDecodeError) as e:
            raise Usage(f"reading {path}: {e}") from None
        summary["chars"] = len(text)
        known = frozenset([a.predicted] if a.predicted is not None else [])
        problems = check(text, host, not a.no_link_check, known)
        if problems:
            raise Refused("lint:\n" + "\n".join(f"  {x}" for x in problems))
        if a.lint_file is not None:
            summary["lint"] = "clean"
            print(json.dumps(summary, indent=2))
            return EXIT_OK
        if a.dry_run:
            it = gh_json(["api", f"repos/{host}/issues/{a.issue}"], "reading the issue")
            summary["state"] = it.get("state") if isinstance(it, dict) else None
            print(json.dumps(summary, indent=2))
            return EXIT_OK

        started = dt.datetime.now(dt.timezone.utc)
        fd, payload = tempfile.mkstemp(prefix="comment-", suffix=".json")
        post_error: Infra | None = None
        posted = None
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"body": text}, f)
            posted = gh_json(
                [
                    "api",
                    "-X",
                    "POST",
                    f"repos/{host}/issues/{a.issue}/comments",
                    "--input",
                    payload,
                ],
                "posting the comment",
            )
            if not isinstance(posted, dict) or not posted.get("id"):
                raise Infra(
                    f"posting the comment: gh returned no comment id: {str(posted)[:200]!r}"
                )
        except Infra as e:
            post_error = e
        finally:
            os.unlink(payload)

        if post_error is not None:
            # GitHub answered with a refusal: nothing was stored.
            if re.search(r"\bHTTP 4\d\d\b", str(post_error)):
                raise Infra(
                    f"posting the comment: {indented(gh_cause(post_error))}",
                    stderr=post_error.stderr,
                    code=post_error.code,
                ) from None
            try:
                posted = landed(host, a.issue, text, started)
            except Infra as e:
                summary["posted"] = "unknown"
                print(json.dumps(summary, indent=2))
                print(
                    "ERROR the POST failed, and listing the issue's comments to see"
                    " whether it landed failed too. Read the issue's comments before"
                    " posting again: a second post is a duplicate",
                    file=sys.stderr,
                )
                print(
                    f"  the POST's error: {indented(gh_cause(post_error))}",
                    file=sys.stderr,
                )
                print(
                    f"  the listing's error: {indented(gh_cause(e))}", file=sys.stderr
                )
                return EXIT_READBACK
            if posted is None:
                raise Infra(
                    "posting the comment failed, and the issue's comments since"
                    " hold no such comment, so nothing was posted:"
                    f" {indented(gh_cause(post_error))}",
                    stderr=post_error.stderr,
                    code=post_error.code,
                ) from None
            print(
                "WARNING gh reported the POST failed, but it landed: "
                + indented(gh_cause(post_error)),
                file=sys.stderr,
            )

        summary.update(
            posted=True, comment_id=posted.get("id"), url=posted.get("html_url")
        )

        def unconfirmed(why: str, cause: Infra | None = None) -> int:
            print(json.dumps(summary, indent=2))
            print(
                f"ERROR the comment was posted ({summary['url']}), but {why}. Read it"
                " on the issue, and edit it there if it's wrong; don't post it again",
                file=sys.stderr,
            )
            if cause is not None:
                print(
                    f"  the read-back's error: {indented(gh_cause(cause))}",
                    file=sys.stderr,
                )
            return EXIT_READBACK

        try:
            back = gh_json(
                ["api", f"repos/{host}/issues/comments/{posted['id']}"],
                "reading the comment back",
            )
        except Infra as e:
            summary["readback"] = "failed"
            return unconfirmed("reading it back failed", e)
        back = back if isinstance(back, dict) else {}
        if not str(back.get("issue_url", "")).endswith(f"/issues/{a.issue}"):
            summary["readback"] = "differs"
            return unconfirmed(f"the comment read back isn't on #{a.issue}")
        if not same(text, str(back.get("body") or "")):
            summary["readback"] = "differs"
            return unconfirmed("the body read back differs from the body sent")
        summary["readback"] = "matches"
        print(json.dumps(summary, indent=2))
        return EXIT_OK
    except Usage as e:
        print(f"USAGE {e}", file=sys.stderr)
        return EXIT_USAGE
    except Refused as e:
        summary["refused"] = str(e)
        print(json.dumps(summary, indent=2))
        print(f"REFUSED {e}", file=sys.stderr)
        return EXIT_REFUSED
    except Infra as e:
        print(json.dumps(summary, indent=2))
        print(f"ERROR {e}", file=sys.stderr)
        return EXIT_INFRA
    except OSError as e:
        print(f"ERROR {e}", file=sys.stderr)
        return EXIT_INFRA


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
