#!/usr/bin/env python3
"""Report what changed around an epic since the last check-in, by three cursors.

The engine behind scan.sh; run that, not this. Stdlib only, Python 3.9+.
Read-only: it writes nothing to GitHub, and only `git fetch` touches the
local checkout (skip it with --no-fetch).

Each run that used one cursor alone missed something (gregoryfoster/skills#348):

- **number watermark:** issues and PRs numbered above the last one seen,
  including follow-ups that never mention the epic (archiver#300 finding 10);
- **updated since:** anything updated since the last check-in, with the new or
  edited comments on the epic's own items. This catches a reply on a closed
  child, or a gate flipped in another thread (seventh run 152, watcher F13);
- **commit range:** every commit from the last verified SHA to the tip, with
  or without an issue number, attributed (broker#80 128, watcher F39).

Plus every cross-repo ref in the epic body, with its state and last activity
(processor#24 F86/F133).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _epic_edit import (  # noqa: E402
    FIELD_RE,
    REF_RE,
    Infra,
    fenced,
    fetch_body,
    gh_json,
    key,
    line_ref,
    normalize,
    ref_text,
    refs_in,
)

EXIT_OK, EXIT_USAGE, EXIT_INFRA = 0, 1, 2
MAX_PAGES = 20
TS_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?Z")
SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")


def header_fields(lines: list[str]) -> dict[str, str]:
    fence = fenced(lines)
    out = {}
    for i, ln in enumerate(lines):
        m = FIELD_RE.match(ln)
        if m and not fence[i]:
            out.setdefault(m.group("field").strip().lower(), m.group("value").strip())
    return out


def cursors_from_body(lines: list[str]) -> dict:
    f = header_fields(lines)
    out: dict = {"since": None, "watermark": None, "from_sha": None}
    if m := TS_RE.search(f.get("last check-in", "")):
        ts = m.group(0)
        out["since"] = ts if ts.count(":") == 2 else ts[:-1] + ":00Z"
    if m := re.search(r"#(\d+)", f.get("last issue seen", "")):
        out["watermark"] = int(m.group(1))
    if m := SHA_RE.search(f.get("last verified sha", "")):
        out["from_sha"] = m.group(0)
    return out


def item_keys(lines: list[str], host: str) -> set[str]:
    fence = fenced(lines)
    out = set()
    for i, ln in enumerate(lines):
        lr = line_ref(ln, host)
        if lr and not fence[i]:
            out.add(lr[1])
    return out


def pages(path: str, what: str, stop=None):
    sep = "&" if "?" in path else "?"
    for page in range(1, MAX_PAGES + 1):
        batch = gh_json(["api", f"{path}{sep}per_page=100&page={page}"], what)
        if not batch:
            return
        yield from batch
        if len(batch) < 100 or (stop and stop(batch[-1])):
            return


def issue_row(it: dict, host: str, epic: int, items: set[str]) -> dict:
    body = it.get("body") or ""
    epic_key = key(None, epic, host)
    mentions = any(
        key(m.group("repo"), m.group("num"), host) == epic_key
        for m in REF_RE.finditer(ref_text(body))
    )
    return {
        "number": it["number"],
        "kind": "pr" if it.get("pull_request") else "issue",
        "title": it.get("title"),
        "state": it.get("state"),
        "author": (it.get("user") or {}).get("login"),
        "created_at": it.get("created_at"),
        "updated_at": it.get("updated_at"),
        "closed_at": it.get("closed_at"),
        "labels": [lb.get("name") for lb in it.get("labels") or []],
        "in_epic": key(None, it["number"], host) in items,
        "mentions_epic": mentions,
    }


def git(args: list[str], git_dir: str, what: str) -> str:
    # An inherited GIT_DIR beats `git -C` (docs/STYLE.md, #189): from a hook
    # or a linked worktree it would aim the range at another checkout.
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")
    }
    r = subprocess.run(
        ["git", "-C", git_dir, *args], capture_output=True, text=True, env=env
    )
    if r.returncode != 0:
        raise Infra(
            f"{what}: git {' '.join(args)} exited {r.returncode}:\n{r.stderr.strip()}"
        )
    return r.stdout


def commits(
    git_dir: str, from_sha: str, ref: str, host: str, epic: int, items: set[str]
) -> list[dict]:
    out = git(
        ["log", "--format=%H%x1f%an%x1f%s%x1f%b%x1e", f"{from_sha}..{ref}"],
        git_dir,
        "reading the commit range",
    )
    rows = []
    epic_key = key(None, epic, host)
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, author, subject, body = (rec.split("\x1f") + ["", "", ""])[:4]
        refs = sorted(
            {
                key(m.group("repo"), m.group("num"), host)
                for m in REF_RE.finditer(ref_text(subject + "\n" + body))
            }
        )
        children = [r for r in refs if r in items]
        if children:
            attribution = "child"
        elif epic_key in refs:
            attribution = "epic"
        elif author.endswith("[bot]"):
            attribution = "bot"
        else:
            attribution = "unattributed"
        rows.append(
            {
                "sha": sha,
                "author": author,
                "subject": subject,
                "refs": refs,
                "children": children,
                "attribution": attribution,
            }
        )
    return rows


def run(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="scan.sh",
        description="Report what changed around an epic since the last check-in (read-only).",
        epilog=(
            "cursors default to the epic's own header lines:\n"
            "  - **Last check-in:** 2026-10-14T18:03Z\n"
            "  - **Last issue seen:** #57\n"
            "  - **Last verified SHA:** 1a2b3c4\n"
            "A cursor that is neither given nor in the header is skipped, with a warning.\n\n"
            "exit codes: 0 report written; 1 usage; 2 gh or git failed (their stderr shown)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--repo", required=True, help="owner/repo holding the epic")
    p.add_argument("--epic", required=True, type=int, help="the epic's issue number")
    p.add_argument("--since", help="ISO time (overrides the epic's Last check-in)")
    p.add_argument(
        "--watermark",
        type=int,
        help="highest number already seen (overrides Last issue seen)",
    )
    p.add_argument(
        "--from-sha", help="last verified commit (overrides Last verified SHA)"
    )
    p.add_argument(
        "--git-dir",
        default=".",
        help="local checkout for the commit range (default: .)",
    )
    p.add_argument(
        "--ref",
        default="origin/HEAD",
        help="tip of the range (default: origin/HEAD, the remote's default branch)",
    )
    p.add_argument("--no-fetch", action="store_true", help="don't run git fetch first")
    a = p.parse_args(argv)
    host = a.repo
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", host):
        p.error("--repo must be owner/repo")
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    warnings: list[str] = []
    try:
        lines = normalize(fetch_body(host, a.epic))
        cur = cursors_from_body(lines)
        if a.since:
            cur["since"] = a.since
        if a.watermark is not None:
            cur["watermark"] = a.watermark
        if a.from_sha:
            cur["from_sha"] = a.from_sha
        cur["ref"] = a.ref
        items = item_keys(lines, host)
        report: dict = {"repo": host, "epic": a.epic, "now": now, "cursors": cur}

        newest = gh_json(
            [
                "api",
                f"repos/{host}/issues?state=all&sort=created&direction=desc&per_page=1",
            ],
            "reading the repo's highest number",
        )
        report["max_number"] = newest[0]["number"] if newest else 0

        if cur["watermark"] is None:
            warnings.append("no watermark: new numbers not scanned")
            report["new_numbers"] = None
        else:
            wm = cur["watermark"]
            rows = [
                issue_row(it, host, a.epic, items)
                for it in pages(
                    f"repos/{host}/issues?state=all&sort=created&direction=desc",
                    "listing new numbers",
                    stop=lambda last: last["number"] <= wm,
                )
                if it["number"] > wm
            ]
            report["new_numbers"] = sorted(rows, key=lambda r: r["number"])

        if cur["since"] is None:
            warnings.append("no since: updates and comments not scanned")
            report["updated_since"] = None
        else:
            since = cur["since"]
            rows = []
            for it in pages(
                f"repos/{host}/issues?state=all&since={since}", "listing updates"
            ):
                if it["number"] == a.epic:
                    continue
                row = issue_row(it, host, a.epic, items)
                if row["in_epic"]:
                    row["new_comments"] = [
                        {
                            "id": c["id"],
                            "author": (c.get("user") or {}).get("login"),
                            "created_at": c.get("created_at"),
                            "updated_at": c.get("updated_at"),
                            "edited": c.get("updated_at") != c.get("created_at"),
                            "url": c.get("html_url"),
                        }
                        for c in pages(
                            f"repos/{host}/issues/{it['number']}/comments?since={since}",
                            "reading new comments",
                        )
                    ]
                rows.append(row)
            report["updated_since"] = sorted(rows, key=lambda r: r["number"])

        if cur["from_sha"] is None:
            warnings.append("no from-sha: commit range not scanned")
            report["commits"] = None
        else:
            # A git failure costs this cursor only: the other two, and the
            # cross-repo states, are still worth having (CR 245).
            try:
                if not a.no_fetch:
                    git(["fetch", "--quiet", "origin"], a.git_dir, "fetching origin")
                report["commits"] = commits(
                    a.git_dir, cur["from_sha"], a.ref, host, a.epic, items
                )
            except Infra as e:
                report["commits"] = None
                warnings.append(f"commit range not scanned: {e}")

        cross = []
        for ref in sorted(
            r for r in refs_in(lines, host) if not r.startswith(host.lower() + "#")
        ):
            repo, num = ref.rsplit("#", 1)
            row: dict = {"ref": ref}
            try:
                it = gh_json(["api", f"repos/{repo}/issues/{num}"], f"reading {ref}")
            except Infra as e:
                row["error"] = str(e).splitlines()[-1]
                warnings.append(
                    f"{ref} unreadable; check which token reaches {repo}: {row['error']}"
                )
            else:
                row.update(
                    title=it.get("title"),
                    state=it.get("state"),
                    updated_at=it.get("updated_at"),
                    closed_at=it.get("closed_at"),
                    updated_since=bool(
                        cur["since"] and (it.get("updated_at") or "") >= cur["since"]
                    ),
                )
            cross.append(row)
        report["cross_repo"] = cross
        report["warnings"] = warnings
        print(json.dumps(report, indent=2))
        return EXIT_OK
    except Infra as e:
        print(f"ERROR {e}", file=sys.stderr)
        return EXIT_INFRA


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
