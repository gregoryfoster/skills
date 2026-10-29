"""Read whether a repo's Dependabot is working, not just configured (#376).

Run through check-dependabot.sh, which picks an interpreter with PyYAML.
Every reading goes through ``gh api`` and is read-only. JSON on stdout,
diagnostics on stderr.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import quote

import yaml

# The ecosystem's segment in a Dependabot branch: dependabot/<segment>/...
BRANCH_SEGMENT = {
    "github-actions": "github_actions",
    "npm": "npm_and_yarn",
    "gomod": "go_modules",
    "docker-compose": "docker_compose",
}
# Lockfiles the dependency graph reads. One committed and unlisted means no
# alert can match it, so no security update is ever opened for it (#376 15).
LOCKFILES = {
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "composer.lock",
    "Cargo.lock",
    "Gemfile.lock",
}
GRAPH_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    dependencyGraphManifests(first: 100) { totalCount nodes { filename } }
  }
}
"""
# "uv in / for fastapi - Update #1", "uv in /, /clients/python for anyio, ... - Update #2"
RUN_KEY = re.compile(r"^(\S+) in (.+?)\.?(?: for .+)? - Update #\d+$")


class GhError(Exception):
    """gh itself failed: not installed, not authenticated, no such repo."""


def gh(*args: str) -> tuple[int | None, object]:
    """(HTTP status, parsed body) for one ``gh api`` call. 2xx reads as 200."""
    try:
        proc = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
    except OSError as exc:
        raise GhError(f"gh: {exc}") from exc
    body: object = None
    if proc.stdout.strip():
        try:
            body = json.loads(proc.stdout)
        except json.JSONDecodeError:
            body = proc.stdout
    if proc.returncode == 0:
        return 200, body
    m = re.search(r"HTTP (\d{3})", proc.stderr)
    if not m:
        raise GhError(
            f"gh api {args[0]}: {proc.stderr.strip() or f'exited {proc.returncode}'}"
        )
    return int(m.group(1)), body


def message(body: object) -> str:
    return body.get("message", "") if isinstance(body, dict) else str(body or "")


def check(name: str, status: str, detail: str, **extra: object) -> dict:
    return {"name": name, "status": status, "detail": detail, **extra}


def read_config(repo: str, branch: str) -> tuple[dict | None, list[dict]]:
    for path in (".github/dependabot.yml", ".github/dependabot.yaml"):
        status, body = gh(f"repos/{repo}/contents/{path}?ref={quote(branch, safe='')}")
        if status == 200 and isinstance(body, dict):
            break
        if status != 404:
            return None, [
                check("config", "unread", f"{path}: HTTP {status} {message(body)}")
            ]
    else:
        return None, [
            check(
                "config",
                "fail",
                f"no .github/dependabot.yml on {branch}: nothing is proposed",
            )
        ]
    try:
        doc = yaml.safe_load(base64.b64decode(body["content"]).decode())
    except (KeyError, ValueError, yaml.YAMLError) as exc:
        return None, [check("config", "fail", f"{path} doesn't parse: {exc}")]
    if not isinstance(doc, dict) or doc.get("version") != 2:
        return None, [
            check(
                "config", "fail", f"{path}: version is not 2, so Dependabot ignores it"
            )
        ]
    problems = []
    for i, block in enumerate(doc.get("updates") or []):
        eco = block.get("package-ecosystem")
        if not eco:
            problems.append(f"updates[{i}] names no package-ecosystem")
        if "directory" not in block and "directories" not in block:
            problems.append(f"updates[{i}] ({eco}) names no directory")
        if not (block.get("schedule") or {}).get("interval"):
            problems.append(f"updates[{i}] ({eco}) has no schedule.interval")
    if not doc.get("updates"):
        problems.append("no updates blocks")
    if problems:
        return doc, [
            check(
                "config",
                "fail",
                "; ".join(problems)
                + " — Dependabot rejects it, visibly only in its own tab",
            )
        ]
    return doc, [
        check("config", "pass", f"{path}: {len(doc['updates'])} update block(s)")
    ]


def limits(repo: str, doc: dict) -> list[dict]:
    status, prs = gh(f"repos/{repo}/pulls?state=open&per_page=100")
    if status != 200 or not isinstance(prs, list):
        return [check("limit", "unread", f"open PRs: HTTP {status} {message(prs)}")]
    open_by_segment: dict[str, int] = {}
    for pr in prs:
        ref = pr.get("head", {}).get("ref", "")
        if pr.get("user", {}).get("login") == "dependabot[bot]" and ref.startswith(
            "dependabot/"
        ):
            segment = ref.split("/")[1]
            open_by_segment[segment] = open_by_segment.get(segment, 0) + 1
    out = []
    by_eco: dict[str, list[dict]] = {}
    for block in doc.get("updates") or []:
        by_eco.setdefault(block.get("package-ecosystem", "?"), []).append(block)
    for eco, blocks in sorted(by_eco.items()):
        segment = BRANCH_SEGMENT.get(eco, eco.replace("-", "_"))
        # The limit holds per block; open PRs are told apart by ecosystem only,
        # and a security-update PR's branch looks like a version update's.
        limit = sum(b.get("open-pull-requests-limit", 5) for b in blocks)
        count = open_by_segment.get(segment, 0)
        note = "" if len(blocks) == 1 else f" (summed over {len(blocks)} blocks)"
        if count >= limit:
            out.append(
                check(
                    f"limit:{eco}",
                    "fail",
                    f"{count} open of a limit of {limit}{note}: Dependabot opens no more version "
                    "updates, and says so nowhere. Land or close PRs, or raise the limit. The count "
                    "may include security-update PRs, which have their own fixed limit of 10",
                    open=count,
                    limit=limit,
                )
            )
        else:
            out.append(
                check(
                    f"limit:{eco}",
                    "pass",
                    f"{count} open of {limit}{note}",
                    open=count,
                    limit=limit,
                )
            )
    return out


def runs(repo: str, per_page: int, doc: dict) -> list[dict]:
    status, body = gh(f"repos/{repo}/actions/runs?event=dynamic&per_page={per_page}")
    if status != 200 or not isinstance(body, dict):
        return [check("update-runs", "unread", f"runs: HTTP {status} {message(body)}")]
    updates = [
        r
        for r in body.get("workflow_runs", [])
        if r.get("path", "").endswith("/dependabot-updates")
    ]
    if not updates:
        return [
            check(
                "update-runs",
                "fail",
                f"no Dependabot Updates run among the last {per_page} dynamic runs",
            )
        ]
    # A run for an ecosystem since dropped from the config isn't this config's.
    configured = {
        BRANCH_SEGMENT.get(e, e.replace("-", "_"))
        for e in (b.get("package-ecosystem", "") for b in doc.get("updates") or [])
    }
    latest: dict[str, dict] = {}
    for run in updates:  # newest first
        m = RUN_KEY.match(run.get("display_title", ""))
        if m and m.group(1) not in configured:
            continue
        key = f"{m.group(1)} in {m.group(2)}" if m else run.get("display_title", "?")
        latest.setdefault(key, run)
    # Only a success passes (#511). A run still queued or in progress has no
    # conclusion yet, which is how it looks right after the config's push; any
    # other conclusion (cancelled, timed_out, startup_failure, ...) opened no PR.
    unfinished = {k: r for k, r in latest.items() if r.get("conclusion") is None}
    failed = {
        k: r
        for k, r in latest.items()
        if k not in unfinished and r.get("conclusion") != "success"
    }
    newest = updates[0].get("created_at")
    waiting = "; ".join(
        f"{k}: {r.get('status') or 'unfinished'} since {r.get('created_at')}"
        for k, r in sorted(unfinished.items())
    )
    if failed:
        listed = "; ".join(
            f"{k} ({r.get('conclusion')}, {r.get('created_at')}, {r.get('html_url')})"
            for k, r in sorted(failed.items())
        )
        return [
            check(
                "update-runs",
                "fail",
                f"the latest run didn't succeed for: {listed}. A failed update run opens no PR "
                "and reads as 'no updates available' everywhere else"
                + (f". Not finished yet: {waiting}" if waiting else ""),
                newest=newest,
            )
        ]
    if unfinished:
        return [
            check(
                "update-runs",
                "info",
                f"not finished; re-run after it completes: {waiting}",
                newest=newest,
            )
        ]
    return [
        check(
            "update-runs",
            "pass",
            f"latest run per ecosystem and directory succeeded: {sorted(latest)}",
            newest=newest,
        )
    ]


def last_pr(repo: str) -> list[dict]:
    status, prs = gh(
        f"repos/{repo}/pulls?state=all&per_page=100&sort=created&direction=desc"
    )
    if status != 200 or not isinstance(prs, list):
        return [check("last-pr", "unread", f"PRs: HTTP {status} {message(prs)}")]
    bot = [p for p in prs if p.get("user", {}).get("login") == "dependabot[bot]"]
    if not bot:
        return [check("last-pr", "info", "no Dependabot PR among the 100 newest PRs")]
    created = bot[0]["created_at"]
    age = (
        datetime.now(UTC) - datetime.fromisoformat(created.replace("Z", "+00:00"))
    ).days
    return [
        check(
            "last-pr",
            "info",
            f"#{bot[0]['number']} opened {created}, {age} days ago",
            age_days=age,
        )
    ]


def graph(repo: str, branch: str) -> list[dict]:
    status, tree = gh(f"repos/{repo}/git/trees/{quote(branch, safe='')}?recursive=1")
    if status != 200 or not isinstance(tree, dict):
        return [check("graph", "unread", f"tree: HTTP {status} {message(tree)}")]
    if tree.get("truncated"):
        return [
            check(
                "graph",
                "unread",
                "the tree listing is truncated; compare the lockfiles by hand",
            )
        ]
    locks = sorted(
        e["path"]
        for e in tree.get("tree", [])
        if e.get("type") == "blob" and PurePosixPath(e["path"]).name in LOCKFILES
    )
    if not locks:
        return [check("graph", "n/a", "no committed lockfile the graph reads")]
    owner, name = repo.split("/", 1)
    status, body = gh(
        "graphql",
        "-H",
        "Accept: application/vnd.github.hawkgirl-preview+json",
        "-f",
        f"query={GRAPH_QUERY}",
        "-F",
        f"owner={owner}",
        "-F",
        f"name={name}",
    )
    try:
        manifests = body["data"]["repository"]["dependencyGraphManifests"]  # type: ignore[index]
    except (TypeError, KeyError):
        return [
            check(
                "graph",
                "unread",
                f"dependencyGraphManifests: HTTP {status} {message(body)}",
            )
        ]
    listed = {n["filename"] for n in manifests["nodes"]}
    missing = [p for p in locks if p not in listed]
    if not missing:
        return [
            check(
                "graph",
                "pass",
                f"{manifests['totalCount']} manifests, every lockfile listed: {locks}",
            )
        ]
    why = (
        "0 manifests: the dependency graph is off, or this token can't see it"
        if manifests["totalCount"] == 0
        else f"{manifests['totalCount']} manifests, but not {missing}"
    )
    return [
        check(
            "graph",
            "fail",
            f"{why}. With no graph entry, no alert matches the lockfile and no security update opens; "
            "transitive advisories arrive only as a red audit",
            missing=missing,
        )
    ]


def alerts(repo: str) -> list[dict]:
    status, body = gh(f"repos/{repo}/dependabot/alerts?state=open&per_page=100")
    if status == 200 and isinstance(body, list):
        return [
            check(
                "alerts", "pass", f"on; {len(body)} open alert(s) read", open=len(body)
            )
        ]
    if "disabled" in message(body).lower():
        return [
            check("alerts", "fail", f"{message(body)}: no advisory reaches this repo")
        ]
    status, body = gh(f"repos/{repo}/vulnerability-alerts")
    if status == 200:
        return [
            check(
                "alerts",
                "pass",
                "on (vulnerability-alerts 204); the alert list is unreadable to this token",
            )
        ]
    if status == 404:
        return [
            check(
                "alerts",
                "fail",
                "Dependabot alerts are off: no advisory reaches this repo",
            )
        ]
    return [
        check(
            "alerts",
            "unread",
            f"needs Dependabot alerts: read, or Administration: read (HTTP {status})",
        )
    ]


def security_updates(repo: str) -> list[dict]:
    status, body = gh(f"repos/{repo}/automated-security-fixes")
    if status != 200 or not isinstance(body, dict):
        return [
            check(
                "security-updates",
                "unread",
                f"needs Administration: read (HTTP {status} {message(body)})",
            )
        ]
    if not body.get("enabled"):
        return [
            check(
                "security-updates",
                "fail",
                "Dependabot security updates are off: an alert opens no PR",
            )
        ]
    if body.get("paused"):
        return [
            check("security-updates", "fail", "Dependabot security updates are paused")
        ]
    return [check("security-updates", "pass", "on, not paused")]


def main() -> int:
    ap = argparse.ArgumentParser(prog="check-dependabot.sh", add_help=False)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--runs", type=int, default=100)
    args = ap.parse_args()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        print(
            f"check-dependabot: --repo takes OWNER/REPO, not {args.repo!r}",
            file=sys.stderr,
        )
        return 2
    if not 1 <= args.runs <= 100:
        # GitHub serves at most 100 per page; more would read 100 and claim more.
        print(f"check-dependabot: --runs takes 1-100, not {args.runs}", file=sys.stderr)
        return 2
    try:
        status, meta = gh(f"repos/{args.repo}")
        if status != 200 or not isinstance(meta, dict):
            print(
                f"check-dependabot: {args.repo}: HTTP {status} {message(meta)}",
                file=sys.stderr,
            )
            return 2
        branch = meta["default_branch"]
        doc, checks = read_config(args.repo, branch)
        if doc is not None and checks[0]["status"] == "pass":
            checks += limits(args.repo, doc)
            checks += runs(args.repo, args.runs, doc)
        checks += last_pr(args.repo)
        checks += graph(args.repo, branch)
        checks += alerts(args.repo)
        checks += security_updates(args.repo)
    except GhError as exc:
        print(f"check-dependabot: {exc}", file=sys.stderr)
        return 2
    summary: dict[str, int] = {}
    for c in checks:
        summary[c["status"]] = summary.get(c["status"], 0) + 1
    json.dump(
        {
            "repo": args.repo,
            "default_branch": branch,
            "checks": checks,
            "summary": summary,
        },
        sys.stdout,
        indent=2,
    )
    print()
    return 1 if summary.get("fail") else 0


if __name__ == "__main__":
    sys.exit(main())
