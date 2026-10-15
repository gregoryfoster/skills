#!/usr/bin/env python3
"""Report what changed around an epic since the last check-in, by three cursors.

The engine behind scan.sh; run that, not this. Stdlib only, Python 3.9+.
Read-only: it writes nothing to GitHub, and only `git fetch` touches the
local checkout (skip it with --no-fetch).

Each run that used one cursor alone missed something (gregoryfoster/skills#348):

- **number watermark:** issues and PRs numbered above the last one seen,
  including follow-ups that never mention the epic (archiver#300 finding 10);
- **updated since:** anything updated since the last check-in, with the new or
  edited comments on the epic's own items and on the epic itself. This catches
  a reply on a closed child, a gate flipped in another thread, or a sibling
  coordinator's note on the epic (seventh run 152, watcher F13, CR 289);
- **commit range:** every commit from the last verified SHA to the tip, with
  or without an issue number, attributed (broker#80 128, watcher F39).

Plus every cross-repo ref in the epic body, with its state and last activity
(processor#24 F86/F133).
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _epic_edit import (  # noqa: E402
    FIELD_RE,
    GH_ISSUE_URL_RE,
    REF_RE,
    Infra,
    Parser,
    fenced,
    gh,
    gh_json,
    key,
    line_ref,
    normalize,
    ref_text,
    refs_in,
)

EXIT_OK, EXIT_USAGE, EXIT_INFRA = 0, 1, 2
MAX_PAGES = 20
TS_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?(?:Z|[+-]\d\d:\d\d)")
SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")


def parse_ts(value: str) -> dt.datetime:
    """An ISO time with a zone, as an aware datetime. A naive time is refused."""
    d = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError(f"{value!r} has no time zone; add Z or an offset")
    return d


def utc_z(value: str) -> str:
    """`…Z` in UTC. A `+02:00` offset would reach GitHub's query as a space (CR 256)."""
    return parse_ts(value).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_epic(host: str, epic: int, warnings: list[str]) -> tuple[str, str]:
    """(body, now): now is GitHub's own clock, from the response's Date header.

    It becomes {checked} and the next window's since, which GitHub compares
    with its own updated_at. A local clock running ahead would open a gap
    between two windows that neither scan sees (CR 301).
    """
    out = gh(["api", "-i", f"repos/{host}/issues/{epic}"], "fetching the epic")
    parts = re.split(r"\r?\n\r?\n", out, maxsplit=1)
    head, body = (parts[0], parts[1]) if len(parts) == 2 else ("", out)
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise Infra(
            f"fetching the epic: gh returned non-JSON: {body[:200]!r}"
        ) from None
    for ln in head.splitlines():
        if ln.lower().startswith("date:"):
            try:
                when = email.utils.parsedate_to_datetime(ln[5:].strip())
                return data.get("body") or "", when.astimezone(
                    dt.timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            except (TypeError, ValueError):
                break
    warnings.append("GitHub sent no usable Date header: 'now' is this machine's clock")
    return data.get("body") or "", dt.datetime.now(dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def header_fields(lines: list[str]) -> dict[str, str]:
    fence = fenced(lines)
    out = {}
    for i, ln in enumerate(lines):
        m = FIELD_RE.match(ln)
        if m and not fence[i]:
            out.setdefault(m.group("field").strip().lower(), m.group("value").strip())
    return out


def cursors_from_body(lines: list[str], warnings: list[str]) -> dict:
    f = header_fields(lines)
    out: dict = {"since": None, "watermark": None, "from_sha": None}
    checked = f.get("last check-in", "")
    if m := TS_RE.search(checked):
        try:
            out["since"] = utc_z(m.group(0))
        except ValueError as e:  # the right shape, not a real time (CR 267)
            warnings.append(f"Last check-in {m.group(0)!r} is not a valid time: {e}")
    elif checked:
        warnings.append(f"Last check-in {checked!r} holds no ISO time with a zone")
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


CAPPED: list[str] = []  # what stopped at MAX_PAGES this run: report["capped"]


def pages(path: str, what: str, stop=None):
    sep = "&" if "?" in path else "?"
    for page in range(1, MAX_PAGES + 1):
        batch = gh_json(["api", f"{path}{sep}per_page=100&page={page}"], what)
        if not batch:
            return
        yield from batch
        if len(batch) < 100 or (stop and stop(batch[-1])):
            return
    # A cap reached in silence reads as a complete answer (CR 259).
    CAPPED.append(what)


def new_comments(host: str, num: int, since: str, what: str) -> list[dict]:
    return [
        {
            "id": c["id"],
            "author": (c.get("user") or {}).get("login"),
            "created_at": c.get("created_at"),
            "updated_at": c.get("updated_at"),
            "edited": c.get("updated_at") != c.get("created_at"),
            "url": c.get("html_url"),
        }
        for c in pages(f"repos/{host}/issues/{num}/comments?since={since}", what)
    ]


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


# Always dropped, whatever the installed git lists: the ones #189 and CR 261
# were about.
GIT_LOCAL_FLOOR = {
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
}


# Listed by --local-env-vars, but they carry `git -c` and GIT_CONFIG_KEY_n
# settings, which name no repository: an http.extraheader the fetch needs to
# authenticate can arrive this way (CR 303).
GIT_CONFIG_KEEP = {"GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT"}


def git_env() -> dict:
    """The environment minus git's repository-local variables.

    An inherited GIT_DIR beats `git -C` (docs/STYLE.md, #189), and so do
    GIT_COMMON_DIR, GIT_OBJECT_DIRECTORY and the rest of what
    `git rev-parse --local-env-vars` lists (CR 261), bar GIT_CONFIG_KEEP.
    Auth variables such as GIT_SSH_COMMAND and GIT_ASKPASS stay too, or the
    fetch can't authenticate. Prompts are off, so a fetch fails rather than
    hangs (CR 268).
    """
    bare = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--local-env-vars"],
            capture_output=True,
            text=True,
            env=bare,
        )
        local = set(r.stdout.split()) if r.returncode == 0 else set()
    except OSError:
        local = set()
    drop = (local - GIT_CONFIG_KEEP) | GIT_LOCAL_FLOOR
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def git(args: list[str], git_dir: str, what: str) -> str:
    env = git_env()
    try:
        r = subprocess.run(
            ["git", "-C", git_dir, *args], capture_output=True, text=True, env=env
        )
    except OSError as e:  # git not installed: the commit cursor's loss only (CR 279)
        raise Infra(f"{what}: git could not run: {e}") from None
    if r.returncode != 0:
        raise Infra(
            f"{what}: git {' '.join(args)} exited {r.returncode}:\n{r.stderr.strip()}"
        )
    return r.stdout


def pr_closes(num: str, host: str, cache: dict, warnings: list[str]) -> list[str]:
    """The issues a PR closes, as keys; [] when num is an issue, not a PR.

    Only gh's own "not a PR" answer means that. A rate limit or an auth
    failure is a warning, not a silent "unattributed" (CR 273).
    """
    if num not in cache:
        try:
            data = gh_json(
                ["pr", "view", num, "-R", host, "--json", "closingIssuesReferences"],
                f"reading what #{num} closes",
            )
        except Infra as e:
            if "Could not resolve to a PullRequest" not in str(e):
                warnings.append(
                    f"#{num}'s closing issues unread: {str(e).splitlines()[-1]}"
                )
            cache[num] = []
        else:
            keys = []
            for it in data.get("closingIssuesReferences") or []:
                repo_obj = it.get("repository") or {}
                owner = (repo_obj.get("owner") or {}).get("login")
                if owner and repo_obj.get("name"):
                    repo = f"{owner}/{repo_obj['name']}"
                else:
                    u = GH_ISSUE_URL_RE.match(str(it.get("url", "")))
                    repo = u.group("repo") if u else None
                    if repo is None:
                        warnings.append(
                            f"#{num} closes #{it.get('number')} in an unnamed repo; skipped"
                        )
                        continue
                keys.append(key(repo, it["number"], host))
            cache[num] = keys
    return cache[num]


def commits(
    git_dir: str,
    from_sha: str,
    ref: str,
    host: str,
    epic: int,
    items: set[str],
    warnings: list[str],
) -> list[dict]:
    out = git(
        ["log", "--format=%H%x1f%an%x1f%s%x1f%b%x1e", f"{from_sha}..{ref}"],
        git_dir,
        "reading the commit range",
    )
    rows = []
    prs: dict = {}
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
        via_pr = []
        if not children:
            # A squash merge's subject is "title (#PR)": the child is what the
            # PR closes, not the number the commit cites (CR 257).
            for r in refs:
                repo, num = r.rsplit("#", 1)
                if repo != host.lower() or r == epic_key:
                    continue
                closed = [c for c in pr_closes(num, host, prs, warnings) if c in items]
                if closed:
                    via_pr.append(r)
                    children.extend(c for c in closed if c not in children)
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
                "via_pr": via_pr,
                "attribution": attribution,
            }
        )
    return rows


def run(argv: list[str]) -> int:
    p = Parser(
        prog="scan.sh",
        description="Report what changed around an epic since the last check-in (read-only).",
        epilog=(
            "cursors default to the epic's own header lines:\n"
            "  - **Last check-in:** 2026-10-14T18:03Z\n"
            "  - **Last issue seen:** #57\n"
            "  - **Last verified SHA:** 1a2b3c4\n"
            "A cursor that is neither given nor in the header is skipped, with a warning.\n\n"
            "max_number is the highest number seen by any cursor. An issue transferred in\n"
            "keeps its old creation date, so the newest-created row isn't always the\n"
            "highest number, and the watermark walk can stop before reaching it. Its\n"
            "transfer updates it, so updated-since still lists it.\n\n"
            "exit codes: 0 report written; 1 usage; 2 gh failed (its stderr shown).\n"
            "A git failure costs the commit cursor only: commits is null, the reason\n"
            "(git's stderr included) is in warnings, and the exit is 0."
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
    if a.since:
        try:
            a.since = utc_z(a.since)
        except ValueError as e:
            p.error(f"--since: {e}")
    warnings: list[str] = []
    CAPPED.clear()
    try:
        raw_body, now = fetch_epic(host, a.epic, warnings)
        lines = normalize(raw_body)
        cur = cursors_from_body(lines, warnings)
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
            report["max_number"] = max(
                [report["max_number"]] + [r["number"] for r in rows]
            )

        if cur["since"] is None:
            warnings.append("no since: updates and comments not scanned")
            report["updated_since"] = None
            report["epic_comments"] = None
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
                    row["new_comments"] = new_comments(
                        host, it["number"], since, "reading new comments"
                    )
                rows.append(row)
            report["updated_since"] = sorted(rows, key=lambda r: r["number"])
            # The epic is no row of its own, but a sibling coordinator or the
            # operator writes to it by comment (siblings.md) (CR 289).
            report["epic_comments"] = new_comments(
                host, a.epic, since, "reading the epic's new comments"
            )
            report["max_number"] = max(
                [report["max_number"]] + [r["number"] for r in rows]
            )

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
                    a.git_dir, cur["from_sha"], a.ref, host, a.epic, items, warnings
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
                        cur["since"]
                        and it.get("updated_at")
                        and parse_ts(it["updated_at"]) >= parse_ts(cur["since"])
                    ),
                )
            cross.append(row)
        report["cross_repo"] = cross
        # epic-edit.sh reads "capped": a {last_seen} past a cut-off walk
        # would skip what the walk never reached (CR 302).
        report["capped"] = list(dict.fromkeys(CAPPED))
        report["warnings"] = warnings + [
            f"{w}: stopped at {MAX_PAGES * 100} rows; the list is incomplete"
            for w in report["capped"]
        ]
        print(json.dumps(report, indent=2))
        return EXIT_OK
    except Infra as e:
        print(f"ERROR {e}", file=sys.stderr)
        return EXIT_INFRA


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
