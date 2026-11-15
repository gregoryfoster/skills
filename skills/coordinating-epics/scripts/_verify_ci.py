#!/usr/bin/env python3
"""Report CI by job on a child's final SHA and on the tip of the default branch.

The engine behind verify-ci.sh; run that, not this. Python 3.9+ with PyYAML,
which the wrapper supplies. Read-only on GitHub.

Coordinators got CI verification wrong three ways (gregoryfoster/skills#394):
a workflow-level green read as a pass while a required job hadn't run;
`conclusion` read before `status` was `completed`; and a scheduled job failing
on the default branch unseen for about ten weeks. So this reads every job,
works out which jobs the push should have run from the workflows' own YAML,
reads `conclusion` only on a completed job, and reports each active
workflow's latest run on the branch, whatever its event.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _epic_edit import (  # noqa: E402
    REPO_FORM,
    Infra,
    Parser,
    Usage,
    add_token_flag,
    gh_cause,
    gh_json,
    indented,
    load_tokens,
    token_hint,
)

EXIT_OK, EXIT_USAGE, EXIT_INFRA = 0, 1, 2
MAX_PAGES = 20
# GitHub evaluates a path filter over the first 300 changed files only.
FILTER_FILES = 300
# A completed job whose conclusion means it didn't pass.
BAD = {
    "failure",
    "cancelled",
    "timed_out",
    "action_required",
    "startup_failure",
    "stale",
}
# Any of these in the head commit's message skips push workflows.
SKIP_CI_RE = re.compile(
    r"\[(?:skip ci|ci skip|no ci|skip actions|actions skip)\]", re.IGNORECASE
)

USAGE_EXTRA = """\
what it reads:
  - the workflows in .github/workflows at --sha, and the files changed from
    --base (default: --sha's first parent) to --sha. Each workflow whose push
    trigger matches --branch, and whose paths / paths-ignore filter the changed
    files pass, is expected to run every job. A job with its own `if:`, or one
    that needs such a job, is "conditional": reported when it ran, never
    missing. A head commit carrying [skip ci] (or its kin) expects nothing.
  - the check runs on --sha, each tied to its workflow by check suite.
  - the check runs on the branch's tip, when that isn't --sha.
  - each active workflow's latest run on the branch, any event but a pull
    request's, from this repo, not a fork, with its jobs: a scheduled job
    failing there shows, whichever commit it ran on.

  A push of several commits: pass --base as the commit before the push, or a
  file changed earlier in it is missed, and so is a workflow it triggered.

output (JSON on stdout):
  rows: one per job, {target, workflow, job, sha, status, conclusion, url,
  event, branch, superseded, expected}. branch is the run's: only a push run
  on --branch counts for an expected job. superseded is true for a job of a
  run that a later run of the same workflow, event and branch replaced, such
  as an earlier nightly on an idle tip: shown, never judged. target is "sha", "main" (the branch's tip) or
  "main-latest". conclusion stays null until status is "completed".
  expected is true, "conditional" or false for a "sha" row, and null for the
  others, which are read, not predicted.
  missing: each expected job with no check run on --sha, {workflow, job}.
  unmatched: expected jobs whose name is an expression this can't evaluate.
  verdict, the first that holds (because names the jobs behind it):
    red         a completed job concluded failure, cancelled, timed_out,
                action_required, startup_failure or stale
    pending     a job isn't completed yet; re-run, or pass --wait
    incomplete  an expected job never ran, or a name couldn't be matched
    green       every job completed, and none of those
  warnings: what limited the reading, such as a filter over 300 files.

waiting:
  --wait SECONDS re-reads every --interval seconds (default 15) until no job is
  pending and none is missing, or the time is up. The default, 0, reads once.

exit codes (scan.sh's): 0 report written, whatever the verdict; 1 usage;
2 gh failed (its whole stderr shown, and on a 403 or 404 the token to try).
"""


# ---------------------------------------------------------------- filters


def glob_re(pattern: str) -> re.Pattern:
    """GitHub's filter glob as a regex over a whole path.

    `*` stays within a directory, `**` crosses them, and a `**/` matches zero
    directories too, so `**/x` matches a root `x` (auditing-ci-cost trap 6).
    `?` and `+` act on the character before them, as GitHub's cheat sheet
    says; `[...]` is a class. A pattern naming a directory matches nothing
    under it unless it ends in `/**`, as in GitHub.
    """
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c in "?+" and out:
            out.append(c)
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j == -1:
                out.append(re.escape(c))
            else:
                out.append(pattern[i : j + 1])
                i = j + 1
                continue
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out) + r"\Z")


def matches(patterns: list[str], path: str) -> bool:
    """Whether path matches the list, read in order: a `!` pattern unmatches."""
    hit = False
    for p in patterns:
        neg = p.startswith("!")
        if glob_re(p[1:] if neg else p).match(path):
            hit = not neg
    return hit


def as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def push_trigger(doc: dict):
    """The workflow's push trigger: None when it has none, {} when it is bare."""
    on = doc.get("on", doc.get(True))  # YAML 1.1 reads a bare `on` as True
    if isinstance(on, str):
        return {} if on == "push" else None
    if isinstance(on, list):
        return {} if "push" in on else None
    if isinstance(on, dict) and "push" in on:
        return on["push"] or {}
    return None


def push_runs(
    trigger: dict, branch: str, files: list[str] | None, warnings: list[str], wf: str
):
    """True, False, or "conditional" when the files can't settle it."""
    branches = as_list(trigger.get("branches"))
    ignored = as_list(trigger.get("branches-ignore"))
    if branches and not matches(branches, branch):
        return False
    if ignored and matches(ignored, branch):
        return False
    tagged = any(trigger.get(k) is not None for k in ("tags", "tags-ignore"))
    if not branches and not ignored and tagged:
        return False  # tag filters only: a branch push doesn't trigger it
    paths = as_list(trigger.get("paths"))
    ignore = as_list(trigger.get("paths-ignore"))
    if not paths and not ignore:
        return True
    if files is None:
        warnings.append(
            f"{wf}: the commit has no parent, so the files a path filter reads"
            " are unknown"
        )
        return "conditional"
    if len(files) > FILTER_FILES:
        warnings.append(
            f"{wf}: {len(files)} files changed, and GitHub filters on the first"
            f" {FILTER_FILES} only, so whether it ran can't be predicted"
        )
        return "conditional"
    if paths:
        return any(matches(paths, f) for f in files)
    return not all(matches(ignore, f) for f in files)


# ---------------------------------------------------------------- jobs


def display_names(doc: dict) -> dict[str, str]:
    """Each job's key to the name its check run carries."""
    out = {}
    for key, job in (doc.get("jobs") or {}).items():
        name = job.get("name") if isinstance(job, dict) else None
        out[str(key)] = str(name) if name is not None else str(key)
    return out


def conditional_jobs(doc: dict) -> set[str]:
    """Jobs with their own `if:`, and those needing one, transitively."""
    jobs = {
        str(k): v for k, v in (doc.get("jobs") or {}).items() if isinstance(v, dict)
    }
    cond = {k for k, v in jobs.items() if "if" in v}
    grew = True
    while grew:
        grew = False
        for k, v in jobs.items():
            if k not in cond and set(as_list(v.get("needs"))) & cond:
                cond.add(k)
                grew = True
    return cond


def name_prefix(name: str) -> str | None:
    """The literal part of a name to match by: all of it, or what precedes
    its first `${{`; None when that is empty."""
    head = name.split("${{", 1)[0].rstrip()
    return head or None


def runs_as(check_name: str, prefix: str, whole: bool) -> bool:
    """A check run's name for a job: the name, a matrix `name (…)`, or a
    reusable workflow's `name / job`. A name cut at an expression matches
    anything that starts with its literal part."""
    if not whole:
        return check_name.startswith(prefix)
    return check_name == prefix or check_name.startswith(
        (prefix + " (", prefix + " / ")
    )


# ---------------------------------------------------------------- reading


def pages(path: str, what: str, key: str | None = None):
    sep = "&" if "?" in path else "?"
    for page in range(1, MAX_PAGES + 1):
        data = gh_json(["api", f"{path}{sep}per_page=100&page={page}"], what)
        batch = ((data or {}).get(key) or []) if key else (data or [])
        yield from batch
        if len(batch) < 100:
            return
    # No option narrows these reads (CR 2261): an idle tip collects a suite
    # per scheduled run, and the reading stops rather than judge a part.
    raise Infra(
        f"{what}: more than {MAX_PAGES * 100} rows, more than this reads, so no"
        " verdict is given. Read that commit's jobs on GitHub by hand (#394)"
    )


def workflows_at(repo: str, sha: str, warnings: list[str]) -> dict[str, dict]:
    """Each workflow file at sha, path to its parsed YAML."""
    try:
        listing = gh_json(
            ["api", f"repos/{repo}/contents/.github/workflows?ref={sha}"],
            "listing the workflows",
        )
    except Infra as e:
        if "HTTP 404" in str(e):
            warnings.append(f"no .github/workflows at {sha[:12]}: nothing is expected")
            return {}
        raise
    out = {}
    for f in listing if isinstance(listing, list) else []:
        path = f.get("path", "")
        if f.get("type") != "file" or not path.endswith((".yml", ".yaml")):
            continue
        blob = gh_json(
            ["api", f"repos/{repo}/contents/{path}?ref={sha}"], f"reading {path}"
        )
        try:
            text = base64.b64decode(blob.get("content") or "").decode()
            doc = yaml.safe_load(text)
        except (ValueError, UnicodeDecodeError, yaml.YAMLError) as e:
            warnings.append(
                f"{path} unreadable as YAML, so its jobs aren't expected: {e}"
            )
            continue
        if isinstance(doc, dict):
            out[path] = doc
    return out


def changed_files(repo: str, base: str, sha: str) -> list[str]:
    files = []
    for f in pages(
        f"repos/{repo}/compare/{base}...{sha}", "reading the changed files", "files"
    ):
        files.append(f.get("filename", ""))
        if f.get("previous_filename"):  # a rename touches both paths
            files.append(f["previous_filename"])
    return files


def check_rows(repo: str, sha: str, target: str) -> list[dict]:
    """One row per check run on sha, tied to its workflow by check suite."""
    runs = {
        r.get("check_suite_id"): r
        for r in pages(
            f"repos/{repo}/actions/runs?head_sha={sha}",
            f"listing the workflow runs on {sha[:12]}",
            "workflow_runs",
        )
    }
    # Scheduled and issue_comment runs are created on the tip, so an idle
    # tip collects a suite per run: only the newest run of each workflow,
    # event and branch is read for the verdict (CR 2260).
    newest: dict[tuple, int] = {}
    for r in runs.values():
        k = (r.get("path"), r.get("event"), r.get("head_branch"))
        newest[k] = max(newest.get(k, 0), int(r.get("id") or 0))
    rows = []
    for c in pages(
        f"repos/{repo}/commits/{sha}/check-runs",
        f"listing the check runs on {sha[:12]}",
        "check_runs",
    ):
        run = runs.get((c.get("check_suite") or {}).get("id")) or {}
        rows.append(
            job_row(
                c,
                target,
                run.get("path"),
                run.get("event"),
                sha,
                run.get("head_branch"),
            )
        )
        k = (run.get("path"), run.get("event"), run.get("head_branch"))
        rows[-1]["superseded"] = bool(run) and int(run.get("id") or 0) < newest[k]
    return rows


def job_row(
    c: dict,
    target: str,
    workflow: str | None,
    event: str | None,
    sha: str,
    branch: str | None = None,
) -> dict:
    status = c.get("status")
    return {
        "target": target,
        "workflow": workflow.split("@", 1)[0] if workflow else None,
        "job": c.get("name"),
        "sha": c.get("head_sha") or sha,
        "status": status,
        # Read only once it is completed: an in-progress run's conclusion
        # is null, or stale from an earlier attempt (#394).
        "conclusion": c.get("conclusion") if status == "completed" else None,
        "url": c.get("html_url"),
        "event": event,
        # The branch the run was for: a push run on another branch, at the
        # same SHA, doesn't stand for the branch's own (CR 2258).
        "branch": branch,
        # A later run of the same workflow, event and branch replaced it:
        # shown, never judged (CR 2260).
        "superseded": False,
        "expected": None,
    }


# Runs GitHub's branch= filter returns that aren't this repo's own: it
# matches head_branch, which a fork's pull request from its own `main` carries
# too, and a pull_request_target run is a stranger's PR run in this repo's
# context (CR 2259).
FOREIGN_EVENTS = {"pull_request", "pull_request_target"}
# Pages of a workflow's runs on the branch read for its latest own run.
LATEST_PAGES = 3


def own_latest(repo: str, wf: dict, branch: str) -> tuple[dict | None, bool]:
    """The workflow's newest run on branch that is this repo's own: not a
    fork's, and not a pull request's (CR 2259); and whether any run was
    passed over to look for it."""
    passed = False
    for page in range(1, LATEST_PAGES + 1):
        data = gh_json(
            [
                "api",
                f"repos/{repo}/actions/workflows/{wf['id']}/runs"
                f"?branch={branch}&per_page=100&page={page}",
            ],
            f"reading {wf.get('path')}'s latest run on {branch}",
        )
        batch = (data or {}).get("workflow_runs") or []
        for r in batch:
            head = str((r.get("head_repository") or {}).get("full_name") or "")
            if head.lower() == repo.lower() and r.get("event") not in FOREIGN_EVENTS:
                return r, passed
            passed = True
        if len(batch) < 100:
            return None, passed
    return None, passed


def latest_on_branch(repo: str, branch: str, warnings: list[str]) -> list[dict]:
    """Each active workflow's latest own run on branch, any event but a pull
    request's, with its jobs."""
    rows = []
    for wf in pages(
        f"repos/{repo}/actions/workflows", "listing the workflows", "workflows"
    ):
        if wf.get("state") != "active":
            continue
        latest, passed = own_latest(repo, wf, branch)
        if not latest:
            if passed:  # one never run on the branch has nothing to say
                warnings.append(
                    f"{wf.get('path')}: no run of its own on {branch} in its"
                    f" latest {LATEST_PAGES * 100}, only pull requests' or forks',"
                    " so none is read"
                )
            continue
        jobs = list(
            pages(
                f"repos/{repo}/actions/runs/{latest['id']}/jobs",
                f"listing the jobs of run {latest['id']}",
                "jobs",
            )
        )
        # A queued run has no jobs yet: the run stands for them, or its
        # pending state would read as nothing to report.
        for j in jobs or [dict(latest, name="(no jobs yet)")]:
            rows.append(
                job_row(
                    j,
                    "main-latest",
                    wf.get("path"),
                    latest.get("event"),
                    latest.get("head_sha"),
                    latest.get("head_branch"),
                )
            )
    return rows


# ---------------------------------------------------------------- judging


def expect(
    docs: dict[str, dict],
    branch: str,
    files: list[str] | None,
    skip_ci: bool,
    warnings: list[str],
) -> list[dict]:
    """Each job the push should run: {workflow, job, prefix, whole, conditional}."""
    out = []
    if skip_ci:
        warnings.append(
            "the head commit asks to skip CI, so no push workflow is expected"
        )
        return out
    for path, doc in sorted(docs.items()):
        trigger = push_trigger(doc)
        if trigger is None:
            continue
        runs = push_runs(
            trigger if isinstance(trigger, dict) else {}, branch, files, warnings, path
        )
        if runs is False:
            continue
        cond = conditional_jobs(doc)
        for key, name in display_names(doc).items():
            prefix = name_prefix(name)
            out.append(
                {
                    "workflow": path,
                    "job": name,
                    "prefix": prefix,
                    "whole": prefix == name,
                    "conditional": runs == "conditional" or key in cond,
                }
            )
    return out


def judge(
    expected: list[dict], rows: list[dict], branch: str
) -> tuple[list[dict], list[dict]]:
    """Mark each "sha" row's expected; return (missing, unmatched)."""
    missing, unmatched = [], []
    for row in rows:
        if row["target"] == "sha":
            row["expected"] = False
    rows = [r for r in rows if not r["superseded"]]
    for e in expected:
        if e["prefix"] is None:
            unmatched.append({"workflow": e["workflow"], "job": e["job"]})
            continue
        hits = [
            r
            for r in rows
            if r["target"] == "sha"
            and r["event"] == "push"
            and r["branch"] == branch
            and r["workflow"] == e["workflow"]
            and runs_as(r["job"] or "", e["prefix"], e["whole"])
        ]
        for r in hits:
            if r["expected"] is not True:
                r["expected"] = "conditional" if e["conditional"] else True
        if not hits and not e["conditional"]:
            missing.append({"workflow": e["workflow"], "job": e["job"]})
    return missing, unmatched


def verdict(
    rows: list[dict], missing: list[dict], unmatched: list[dict]
) -> tuple[str, list[str]]:
    """The verdict, and the jobs behind it, so a red from a managed run such
    as Dependabot's (event "dynamic") reads as that, not as the child's."""

    def name(r: dict) -> str:
        return f"{r['target']}: {r['workflow'] or '(no workflow)'} / {r['job']} ({r['event']})"

    rows = [r for r in rows if not r["superseded"]]

    red = [f"{name(r)} {r['conclusion']}" for r in rows if r["conclusion"] in BAD]
    if red:
        return "red", red
    pending = [f"{name(r)} {r['status']}" for r in rows if r["status"] != "completed"]
    if pending:
        return "pending", pending
    if missing or unmatched:
        return "incomplete", [
            f"sha: {m['workflow']} / {m['job']} {why}"
            for ms, why in ((missing, "never ran"), (unmatched, "name not matched"))
            for m in ms
        ]
    return "green", []


# ---------------------------------------------------------------- main


def read_once(
    a, report: dict, docs: dict, files: list[str] | None, skip_ci: bool
) -> None:
    warnings: list[str] = list(report["warnings_fixed"])
    expected = expect(docs, report["branch"], files, skip_ci, warnings)
    rows = check_rows(a.repo, report["sha"], "sha")
    tip = gh_json(
        ["api", f"repos/{a.repo}/branches/{report['branch']}"],
        f"reading {report['branch']}'s tip",
    )
    report["main_sha"] = ((tip or {}).get("commit") or {}).get("sha")
    if report["main_sha"] and report["main_sha"] != report["sha"]:
        rows += check_rows(a.repo, report["main_sha"], "main")
    rows += latest_on_branch(a.repo, report["branch"], warnings)
    missing, unmatched = judge(expected, rows, report["branch"])
    report.update(
        rows=rows,
        missing=missing,
        unmatched=unmatched,
        warnings=warnings,
    )
    report["verdict"], report["because"] = verdict(rows, missing, unmatched)


def run(argv: list[str]) -> int:
    p = Parser(
        prog="verify-ci.sh",
        description="Report CI by job on a final SHA and on the default branch's tip (read-only).",
        epilog=USAGE_EXTRA,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--repo", required=True, help="owner/repo the commit is in")
    p.add_argument("--sha", required=True, help="the child's final commit")
    p.add_argument(
        "--base", help="the commit before the push (default: --sha's first parent)"
    )
    p.add_argument("--branch", help="the branch pushed to (default: GitHub's default)")
    p.add_argument(
        "--wait",
        type=int,
        default=0,
        metavar="SECONDS",
        help="re-read until nothing is pending or missing, up to this long (default 0: one read)",
    )
    p.add_argument(
        "--interval",
        type=int,
        default=15,
        metavar="SECONDS",
        help="seconds between reads with --wait (default 15)",
    )
    add_token_flag(p)
    a = p.parse_args(argv)
    if not re.fullmatch(REPO_FORM, a.repo):
        p.error("--repo must be owner/repo")
    for name in ("sha", "base"):
        v = getattr(a, name)
        if v is not None and not re.fullmatch(r"[0-9a-fA-F]{7,40}", v):
            p.error(f"--{name} must be a commit SHA")
    if a.wait < 0 or a.interval < 1:
        p.error("--wait must be 0 or more, and --interval 1 or more")
    try:
        load_tokens(a.token_for)
    except Usage as e:
        p.error(str(e))
    try:
        commit = gh_json(
            ["api", f"repos/{a.repo}/commits/{a.sha}"], "reading the commit"
        )
        sha = commit.get("sha") or a.sha
        parents = commit.get("parents") or []
        base = a.base or (parents[0].get("sha") if parents else None)
        message = (commit.get("commit") or {}).get("message") or ""
        branch = a.branch or gh_json(
            ["api", f"repos/{a.repo}"], "reading the default branch"
        ).get("default_branch")
        fixed: list[str] = []
        files = changed_files(a.repo, base, sha) if base else None
        docs = workflows_at(a.repo, sha, fixed)
        report = {
            "repo": a.repo,
            "sha": sha,
            "base": base,
            "branch": branch,
            "changed_files": None if files is None else len(files),
            "warnings_fixed": fixed,
        }
        deadline = time.monotonic() + a.wait
        while True:
            read_once(a, report, docs, files, bool(SKIP_CI_RE.search(message)))
            left = deadline - time.monotonic()
            # An unmatched name stays unmatched: only a pending job or a
            # missing one, whose run may not exist yet, can change.
            waiting = report["verdict"] == "pending" or (
                report["verdict"] == "incomplete" and report["missing"]
            )
            if not waiting or left <= 0:
                break
            time.sleep(min(a.interval, left))
        if waiting and a.wait:
            report["warnings"].append(
                f"still {report['verdict']} after --wait {a.wait}"
            )
        report.pop("warnings_fixed")
        print(json.dumps(report, indent=2))
        return EXIT_OK
    except Infra as e:
        if e.code is None:  # not gh's own exit: the message is the cause
            print(f"ERROR {indented(str(e))}", file=sys.stderr)
        else:
            what = str(e).split("\n", 1)[0].split(": gh ", 1)[0]
            print(f"ERROR {what}:", file=sys.stderr)
            print(f"  gh's error: {indented(gh_cause(e))}", file=sys.stderr)
        if re.search(r"\bHTTP 40[34]\b", gh_cause(e)):
            hint = token_hint(a.repo)
            print(f"  {hint or f'check which token reaches {a.repo}'}", file=sys.stderr)
        return EXIT_INFRA


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
