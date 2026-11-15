#!/usr/bin/env python3
"""Create a drafted epic's children, then the epic, from a JSON plan (#396).

The engine behind create-from-plan.sh; run that, not this. Stdlib only,
Python 3.9+.

Creation was the step coordinators most often redid by hand
(gregoryfoster/skills#396): a lookbehind missed `SUB7/#8` (archiver#300
finding 1), the epic's number went unchecked against the body's prediction
(watcher F11), and a cross-repo parent needed children in several repos
under one parent (watcher#368 F3). So:

- every body is linted, and every repo read with the token in use, before
  anything is created;
- children are created in dependency order, then the epic, and each local
  id is substituted as a whole token, never a prefix;
- each create is recorded before it is sent, so a re-run resumes, and a
  create gh called failed but GitHub stored is found, not repeated;
- the epic's number is checked against its prediction;
- the run ends in `epic-edit.sh --adopt-live --lint-all`, whose log-comment
  is the epic's first log entry.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _epic_edit import (  # noqa: E402
    FIELD_RE,
    OWNER_REPO,
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
    per_repo_cursor,
    tabled,
    token_hint,
    write_atomic,
)

EXIT_OK, EXIT_USAGE, EXIT_INFRA, EXIT_REFUSED, EXIT_READBACK = 0, 1, 2, 3, 4

USAGE_EXTRA = """\
the plan (a JSON file):
  {"epic": {"title": "...", "body_file": "epic.md"},
   "children": [{"id": "SUB1", "title": "...", "body_file": "c1.md"},
                {"id": "SUB2", "repo": "owner/other", "title": "...",
                 "body_file": "c2.md", "after": ["SUB1"]}],
   "log": "optional first log entry; default lists what was created"}
  A body_file is read relative to the plan. "repo" defaults to --repo.
  "after" lists ids created first; a cycle is a usage error.

placeholders:
  A child's id is SUBn (n from 1), and SUB0 is the epic. In any body, SUBn
  or #SUBn stands for that issue's ref: #N in its own repo, owner/repo#N in
  another. It is matched as a whole token, so SUB1 is no prefix of SUB10,
  and SUB7/#8 substitutes. Never prefix one with a repo (owner/repo#SUB1);
  the repo is written for you. An id no plan entry names is a usage error.

order:
  1. Check the plan; read every body.
  2. Read each repo with the token in use (--token-for), and refuse one
     without issues, before anything is created.
  3. Lint every body as comment.sh --lint-file does, on a preview with each
     id replaced by its predicted ref; refuse on any finding.
  4. Create the children in dependency order, each body with the ids known
     so far; then the epic, with SUB0 as its predicted number.
  5. If the epic took another number, correct its own refs from the plan.
  6. Replace the ids left in every created body (forward refs, SUB0).
  7. epic-edit.sh --adopt-live --lint-all on the epic: a "Last issue seen
     (owner/repo)" cursor line for each other repo the body lacks, and a
     log-comment, the epic's first log entry.

state:
  --state FILE (default <plan>.state.json) holds each local id's repo,
  number and URL. A create is recorded as pending before it is sent, and a
  re-run reads the state: a created id is not created again, and a pending
  one is first looked for above the number read before it was sent, by its
  title and body (a 502 or a timeout can come back after GitHub stored it).
  An adoption that exited 0 is not run again.

exit codes:
  0  every issue created, every id replaced, and the epic adopted
  1  usage: a malformed plan, a missing body file, an unknown or
     repo-prefixed id, a cycle, a bad --token-for. Nothing was created.
  2  infrastructure: gh failed (its own stderr shown, and the token to try
     for a repo it couldn't read). The state says what was created; re-run.
  3  refused: a lint finding, an empty body, or a repo without issues.
     Nothing was created.
  4  not confirmed: a body patched with the real numbers reads back
     different. Read the issue named before re-running.
  Any other code is epic-edit.sh's own, from step 7 (its --help).
"""

ID_RE = re.compile(r"SUB(?:0|[1-9][0-9]*)")
# A local id as a whole token, with an optional leading "#": "SUB7/#8"
# substitutes, and "SUB1" is no prefix of "SUB10" (archiver#300 finding 1).
TOKEN_RE = re.compile(r"#?\bSUB(?P<n>[0-9]+)\b")
PREFIXED_RE = re.compile(OWNER_REPO + r"#SUB[0-9]+")
EPIC_ID = "SUB0"


def render(text: str, repo: str, numbers: dict[str, tuple[str, int]]) -> str:
    """text with each id numbers knows replaced by its ref as seen from repo:
    #N there, owner/repo#N elsewhere. Unknown ids stay."""

    def sub(m: re.Match) -> str:
        hit = numbers.get("SUB" + m.group("n"))
        if hit is None:
            return m.group(0)
        r, n = hit
        return f"#{n}" if r.lower() == repo.lower() else f"{r}#{n}"

    return TOKEN_RE.sub(sub, text)


def tokens(text: str) -> set[str]:
    return {"SUB" + m.group("n") for m in TOKEN_RE.finditer(text)}


def load_plan(path: Path, host: str) -> tuple[dict, list[dict]]:
    """(the epic, the children in creation order), each with its body read."""
    try:
        plan = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise Usage(f"reading --plan: {e}") from None
    if not isinstance(plan, dict) or not isinstance(plan.get("epic"), dict):
        raise Usage("the plan needs an 'epic' object")
    kids = plan.get("children")
    if not isinstance(kids, list) or not kids:
        raise Usage("the plan needs a non-empty 'children' list")
    if plan.get("log") is not None and not isinstance(plan.get("log"), str):
        raise Usage("the plan's 'log' must be text")

    def entry(raw, where: str, is_epic: bool) -> dict:
        if not isinstance(raw, dict):
            raise Usage(f"{where}: must be an object")
        e = {"id": EPIC_ID if is_epic else raw.get("id"), "repo": host}
        if not is_epic:
            if (
                not isinstance(e["id"], str)
                or not ID_RE.fullmatch(e["id"])
                or (e["id"] == EPIC_ID)
            ):
                raise Usage(f"{where}: id {e['id']!r} must be SUBn, n from 1")
            repo = raw.get("repo", host)
            if not isinstance(repo, str) or not re.fullmatch(REPO_FORM, repo):
                raise Usage(f"{where}: repo {repo!r} must be owner/repo")
            e["repo"] = repo
            after = raw.get("after", [])
            if not isinstance(after, list) or not all(
                isinstance(x, str) for x in after
            ):
                raise Usage(f"{where}: after must be a list of ids")
            e["after"] = after
        for f in ("title", "body_file"):
            if not isinstance(raw.get(f), str) or not raw[f].strip():
                raise Usage(f"{where}: {f} must be non-empty text")
        e["title"] = raw["title"].strip()
        e["file"] = raw["body_file"]
        try:
            e["template"] = (path.parent / raw["body_file"]).read_text()
        except (OSError, UnicodeDecodeError) as err:
            raise Usage(f"{where}: reading {raw['body_file']}: {err}") from None
        return e

    epic = entry(plan["epic"], "epic", True)
    children = [entry(c, f"children[{i}]", False) for i, c in enumerate(kids)]
    ids = [c["id"] for c in children]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise Usage(f"ids used twice: {', '.join(dup)}")
    known = set(ids) | {EPIC_ID}
    for c in children:
        bad = [x for x in c["after"] if x not in ids]
        if bad:
            raise Usage(f"{c['id']}: after names no child: {', '.join(bad)}")
    order = ordered(children)
    problems = []
    for e in [*children, epic]:
        for m in PREFIXED_RE.finditer(e["template"]):
            problems.append(
                f"{e['file']}: {m.group(0)}: write the id alone; its repo is added"
            )
        for t in sorted(tokens(e["template"]) - known):
            problems.append(f"{e['file']}: {t} names no plan entry")
    if problems:
        raise Usage("placeholders:\n" + "\n".join(f"  {p}" for p in problems))
    epic["log"] = plan.get("log")
    return epic, order


def ordered(children: list[dict]) -> list[dict]:
    """Dependency order, plan order between equals; a cycle is a usage error."""
    done: list[dict] = []
    left = list(children)
    while left:
        ready = [
            c for c in left if all(a in {d["id"] for d in done} for a in c["after"])
        ]
        if not ready:
            raise Usage("a cycle in 'after': " + ", ".join(c["id"] for c in left))
        done.append(ready[0])
        left.remove(ready[0])
    return done


def top_number(repo: str) -> int:
    newest = gh_json(
        [
            "api",
            f"repos/{repo}/issues?state=all&sort=created&direction=desc&per_page=1",
        ],
        f"reading {repo}'s highest number",
    )
    return newest[0]["number"] if newest else 0


def reachable(repo: str) -> None:
    """Read repo with the token its calls use; Refused when it has no issues."""
    try:
        info = gh_json(["api", f"repos/{repo}"], f"reading {repo}")
    except Infra as e:
        hint = token_hint(repo) or f"check which token reaches {repo}"
        raise Infra(
            f"{repo} can't be read, so nothing was created; {hint}:"
            f" {indented(gh_cause(e))}",
            stderr=e.stderr,
            code=e.code,
        ) from None
    if isinstance(info, dict) and info.get("has_issues") is False:
        raise Refused(f"{repo} has issues turned off, so nothing was created")


def same(a: str, b: str) -> bool:
    return normalize(a) == normalize(b)


def find_created(repo: str, above: int, title: str, body: str, taken: set[int]):
    """The issue a create stored though gh reported a failure: numbered above
    what was read before it, with its title and body. None when there's none."""
    rows = gh_json(
        [
            "api",
            f"repos/{repo}/issues?state=all&sort=created&direction=desc&per_page=100",
        ],
        f"looking in {repo} for the issue a failed create may have stored",
    )
    for it in rows or []:
        n = it.get("number")
        if (
            isinstance(n, int)
            and n > above
            and n not in taken
            and not it.get("pull_request")
            and it.get("title") == title
            and same(str(it.get("body") or ""), body)
        ):
            return {"number": n, "html_url": it.get("html_url")}
    return None


def post_issue(repo: str, title: str, body: str, payload: Path) -> dict:
    write_atomic(payload, json.dumps({"title": title, "body": body}))
    try:
        data = gh_json(
            ["api", "-X", "POST", f"repos/{repo}/issues", "--input", str(payload)],
            f"creating an issue in {repo}",
        )
    finally:
        payload.unlink(missing_ok=True)
    if not isinstance(data, dict) or type(data.get("number")) is not int:
        raise Infra(
            f"creating an issue in {repo}: gh returned no number: {str(data)[:200]!r}"
        )
    return data


def run(argv: list[str]) -> int:
    p = Parser(
        prog="create-from-plan.sh",
        description="Create a drafted epic's children, then the epic, from a JSON plan.",
        epilog=USAGE_EXTRA,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--repo", required=True, help="owner/repo the epic goes in")
    p.add_argument("--plan", required=True, help="the plan, a JSON file")
    p.add_argument("--state", help="the run's state file (default <plan>.state.json)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="check, read every repo, lint, and print the order; create nothing",
    )
    p.add_argument(
        "--state-dir", help="epic-edit.sh's baseline directory, passed to it"
    )
    p.add_argument(
        "--no-link-check", action="store_true", help="skip resolving comment links"
    )
    add_token_flag(p)
    a = p.parse_args(argv)
    host = a.repo
    if not re.fullmatch(REPO_FORM, host):
        p.error("--repo must be owner/repo")
    plan_path = Path(a.plan)
    state_path = Path(a.state) if a.state else Path(str(plan_path) + ".state.json")
    summary: dict = {
        "repo": host,
        "plan": str(plan_path),
        "state": str(state_path),
        "dry_run": a.dry_run,
    }
    try:
        load_tokens(a.token_for)
        epic, children = load_plan(plan_path, host)
        try:
            state = json.loads(state_path.read_text()) if state_path.exists() else {}
        except (OSError, json.JSONDecodeError) as e:
            raise Usage(f"reading the state file {state_path}: {e}") from None
        items: dict = state.setdefault("items", {})
        state["repo"] = host

        def save() -> None:
            write_atomic(state_path, json.dumps(state, indent=2) + "\n")

        repos = list(dict.fromkeys([host] + [c["repo"] for c in children]))
        for r in repos:
            reachable(r)

        # Every id's number: created ones as recorded, the rest predicted
        # from each repo's highest number, in creation order.
        numbers: dict[str, tuple[str, int]] = {}
        for i, it in items.items():
            if it.get("number"):
                numbers[i] = (it["repo"], it["number"])
        tops = {r.lower(): top_number(r) for r in repos}
        nxt = dict(tops)
        predicted: dict[str, tuple[str, int]] = dict(numbers)
        for e in [*children, epic]:
            if e["id"] not in predicted:
                nxt[e["repo"].lower()] += 1
                predicted[e["id"]] = (e["repo"], nxt[e["repo"].lower()])

        problems = []
        for e in [*children, epic]:
            text = render(e["template"], e["repo"], predicted)
            if not text.strip():
                problems.append(f"{e['file']}: the body is empty")
                continue
            lines = text.replace("\r\n", "\n").split("\n")
            known = frozenset(
                n for (r, n) in predicted.values() if r.lower() == e["repo"].lower()
            )
            problems += [
                f"{e['file']}: {x}"
                for x in lint(
                    lines,
                    e["repo"],
                    not a.no_link_check,
                    fenced(lines),
                    tabled(lines),
                    known,
                )
            ]
        if problems:
            raise Refused("lint:\n" + "\n".join(f"  {x}" for x in problems))

        def ref(e: dict) -> str:
            r, n = predicted[e["id"]]
            return f"#{n}" if r.lower() == host.lower() else f"{r}#{n}"

        if a.dry_run:
            summary["children"] = [
                {
                    "id": c["id"],
                    "repo": c["repo"],
                    "title": c["title"],
                    "predicted": ref(c),
                }
                for c in children
            ]
            summary["epic"] = {
                "title": epic["title"],
                "predicted": predicted[EPIC_ID][1],
            }
            print(json.dumps(summary, indent=2))
            return EXIT_OK

        payload = state_path.with_name(state_path.name + ".payload")
        rows: list[dict] = []

        def create(e: dict, body: str) -> dict:
            """Create e, or find the one an earlier attempt stored."""
            it = items.get(e["id"]) or {}
            if it.get("number"):
                return {"created": "already", **it}
            taken = {
                x["number"]
                for x in items.values()
                if x.get("number") and x["repo"].lower() == e["repo"].lower()
            }
            if it.get("state") == "pending":
                hit = find_created(
                    e["repo"], it["above"], e["title"], it.get("body", body), taken
                )
                if hit is not None:
                    it.update(
                        state="created", number=hit["number"], url=hit["html_url"]
                    )
                    save()
                    return {"created": "found", **it}
            above = top_number(e["repo"])
            it = {
                "repo": e["repo"],
                "title": e["title"],
                "state": "pending",
                "above": above,
                "body": body,
            }
            items[e["id"]] = it
            save()
            try:
                data = post_issue(e["repo"], e["title"], body, payload)
            except Infra as err:
                if re.search(r"\bHTTP 4\d\d\b", str(err)):  # refused: nothing stored
                    raise
                hit = find_created(e["repo"], above, e["title"], body, taken)
                if hit is None:
                    raise Infra(
                        f"creating {e['id']} in {e['repo']} failed, and its issues"
                        " above the number read before hold no such issue:"
                        f" {indented(gh_cause(err))}",
                        stderr=err.stderr,
                        code=err.code,
                    ) from None
                print(
                    f"WARNING gh reported creating {e['id']} failed, but it landed:"
                    f" {indented(gh_cause(err))}",
                    file=sys.stderr,
                )
                it.update(state="created", number=hit["number"], url=hit["html_url"])
                save()
                return {"created": "found", **it}
            it.update(state="created", number=data["number"], url=data.get("html_url"))
            save()
            return {"created": True, **it}

        for c in children:
            got = create(c, render(c["template"], c["repo"], numbers))
            numbers[c["id"]] = (c["repo"], got["number"])
            rows.append(
                {
                    "id": c["id"],
                    "repo": c["repo"],
                    "title": c["title"],
                    "number": got["number"],
                    "url": got.get("url"),
                    "created": got["created"],
                }
            )
        summary["children"] = rows

        # The epic last, naming itself by the number it predicts now.
        guess = items.get(EPIC_ID, {}).get("number") or top_number(host) + 1
        numbers[EPIC_ID] = (host, guess)
        got = create(epic, render(epic["template"], host, numbers))
        n = got["number"]
        summary["epic"] = {
            "title": epic["title"],
            "number": n,
            "url": got.get("url"),
            "predicted": guess,
            "created": got["created"],
            "corrected": False,
        }
        numbers[EPIC_ID] = (host, n)
        if n != guess and EPIC_ID in tokens(epic["template"]):
            # Another issue took the predicted number (watcher F11): its own
            # refs are rebuilt from the plan, before anything adopts it.
            print(
                f"WARNING the epic was created as #{n}, but its body predicted #{guess}:"
                " its own refs are corrected from the plan",
                file=sys.stderr,
            )
            patch(host, n, render(epic["template"], host, numbers), payload)
            summary["epic"]["corrected"] = True
            items[EPIC_ID]["body"] = render(epic["template"], host, numbers)
            save()

        # Forward refs and SUB0, in every body created before they existed.
        for c in [*children, epic]:
            r, num = numbers[c["id"]]
            current = gh_json(["api", f"repos/{r}/issues/{num}"], f"reading {r}#{num}")
            body = str((current or {}).get("body") or "")
            if not tokens(body) & set(numbers):
                continue
            patch(r, num, render(body, r, numbers), payload)
            for row in rows:
                if row["id"] == c["id"]:
                    row["patched"] = True

        adopt = state.get("adopt") or {}
        if adopt.get("exit") == 0:
            summary["adopt"] = adopt
            print(json.dumps(summary, indent=2))
            return EXIT_OK
        epic_now = gh_json(["api", f"repos/{host}/issues/{n}"], f"reading #{n}")
        lines = normalize(str((epic_now or {}).get("body") or ""))
        have = {
            per_repo_cursor(m.group("field"))
            for ln in lines
            if (m := FIELD_RE.match(ln)) and not ln[:1].isspace()
        }
        ops = []
        for r in repos[1:]:
            if r.lower() not in have:
                top = max(
                    [top_number(r)]
                    + [x[1] for x in numbers.values() if x[0].lower() == r.lower()]
                )
                ops.append(
                    {
                        "op": "header",
                        "field": f"Last issue seen ({r})",
                        "value": f"{r}#{top}",
                    }
                )
        log = (
            adopt.get("log")
            or epic["log"]
            or (
                dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
                + f": created from a plan, with {len(children)} children: "
                + ", ".join(
                    f"#{numbers[c['id']][1]}"
                    if c["repo"].lower() == host.lower()
                    else f"{c['repo']}#{numbers[c['id']][1]}"
                    for c in children
                )
                + "."
            )
        )
        ops.append({"op": "log-comment", "text": log})
        state["adopt"] = {"log": log}
        save()
        cmd = [
            "bash",
            str(Path(__file__).resolve().parent / "epic-edit.sh"),
            "--repo",
            host,
            "--epic",
            str(n),
            "--adopt-live",
            "--lint-all",
            "--ops",
            "-",
        ]
        if a.state_dir:
            cmd += ["--state-dir", a.state_dir]
        if a.no_link_check:
            cmd.append("--no-link-check")
        for spec in a.token_for:
            cmd += ["--token-for", spec]
        res = subprocess.run(cmd, input=json.dumps(ops), capture_output=True, text=True)
        sys.stderr.write(res.stderr)
        try:
            edited = json.loads(res.stdout)
        except json.JSONDecodeError:
            edited = res.stdout.strip()[:500]
        summary["adopt"] = state["adopt"] = {
            "exit": res.returncode,
            "log": log,
            "summary": edited,
        }
        save()
        print(json.dumps(summary, indent=2))
        return res.returncode
    except Usage as e:
        print(f"USAGE {e}", file=sys.stderr)
        return EXIT_USAGE
    except Refused as e:
        summary["refused"] = str(e)
        print(json.dumps(summary, indent=2))
        print(f"REFUSED {e}", file=sys.stderr)
        return EXIT_REFUSED
    except NotConfirmed as e:
        summary["unconfirmed"] = str(e)
        print(json.dumps(summary, indent=2))
        print(f"ERROR {e}", file=sys.stderr)
        return EXIT_READBACK
    except Infra as e:
        print(json.dumps(summary, indent=2))
        print(f"ERROR {e}", file=sys.stderr)
        return EXIT_INFRA
    except OSError as e:
        print(f"ERROR {e}", file=sys.stderr)
        return EXIT_INFRA


class NotConfirmed(Exception):
    """A patch whose read-back differs from what was sent."""


def patch(repo: str, num: int, body: str, payload: Path) -> None:
    """PATCH the issue's body, then read it back: an exit code alone proves
    nothing (address-validator#272 finding 48)."""
    write_atomic(payload, json.dumps({"body": body}))
    try:
        gh_json(
            [
                "api",
                "-X",
                "PATCH",
                f"repos/{repo}/issues/{num}",
                "--input",
                str(payload),
            ],
            f"writing {repo}#{num}'s real numbers",
        )
    finally:
        payload.unlink(missing_ok=True)
    back = gh_json(["api", f"repos/{repo}/issues/{num}"], f"reading {repo}#{num} back")
    if not same(str((back or {}).get("body") or ""), body):
        raise NotConfirmed(
            f"{repo}#{num}'s body read back differs from the one sent with the real"
            " numbers. Read it on the issue before re-running"
        )


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
