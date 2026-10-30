"""A fake `gh` and helpers for the coordinating-epics script tests.

The fake serves a tiny in-memory GitHub from a JSON state file: issue bodies,
issue lists, comments, and comment lookups. It records every PATCH, and can be
told to accept a PATCH and change nothing, the failure address-validator#272
finding 48 saw from the real thing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# An issue's created_at when a test sets none.
CREATED = "2026-10-01T00:00:00Z"
SCRIPTS = REPO_ROOT / "skills" / "coordinating-epics" / "scripts"

FAKE_GH = r"""#!__PYTHON__
import json, os, re, sys
CREATED = "__CREATED__"
from urllib.parse import parse_qs, urlsplit

state_path = os.environ["FAKE_GH_STATE"]
st = json.load(open(state_path))
args = sys.argv[1:]
st.setdefault("calls", []).append(args)

def save():
    json.dump(st, open(state_path, "w"))

# The node GitHub adds on a body's first edit, measured on #516 (CR 1195):
# the body as created, editedAt the creation time, updatedAt the first edit's.
def original_node(it, original, first_edit_at):
    return {"editedAt": it.get("created_at", CREATED), "updatedAt": first_edit_at,
            "editor": {"login": "gregoryfoster"}, "diff": original}

INCLUDE = "-i" in args  # gh api -i: the status line and headers first

def out(obj):
    save()
    if INCLUDE:
        date = st.get("server_date", "Wed, 14 Oct 2026 18:03:27 GMT")
        print("HTTP/2.0 200 OK\nContent-Type: application/json\r")
        print(f"Date: {date}\r\n\r")
    print(json.dumps(obj))
    sys.exit(0)

def fail(msg="HTTP 404: Not Found"):  # an empty msg: gh exits 1 and says nothing
    save()
    if msg:
        print(f"gh: {msg}", file=sys.stderr)
    sys.exit(1)

if st.get("fail_all"):
    fail(st["fail_all"])
for frag, msg in st.get("fail_paths", {}).items():  # {"issues/99": "HTTP 502: …"}
    if frag in " ".join(args):
        fail(msg)

def find(repo):  # GitHub's names are case-insensitive
    return next((v for k, v in st["repos"].items() if k.lower() == repo.lower()), None)

if args[:2] == ["issue", "list"]:
    repo = args[args.index("-R") + 1]
    issues = (find(repo) or {}).get("issues", {})
    out([{"number": int(n)} for n, it in issues.items() if it.get("state") == "open" and not it.get("pull_request")])

if args[:2] == ["pr", "view"]:
    num, repo = args[2], args[args.index("-R") + 1]
    if "pr_error" in st:
        fail(st["pr_error"])
    closes = (find(repo) or {}).get("prs", {}).get(num)
    if closes is None:
        fail(f"GraphQL: Could not resolve to a PullRequest with the number of {num}.")
    refs = []
    for c in closes:  # an int is this repo's issue; "owner/repo#N" another's
        r, n = (c.rsplit("#", 1) if isinstance(c, str) else (repo, c))
        o, name = r.split("/")
        refs.append({"number": int(n), "repository": {"name": name, "owner": {"login": o}}})
    out({"closingIssuesReferences": refs})

if args[0] != "api":
    fail("unsupported")

method = "GET"
rest = [x for x in args[1:] if x != "-i"]

if rest[0] == "graphql":  # gh api graphql -f query=… -f owner=… -F number=…
    st.setdefault("graphql_calls", 0)
    st["graphql_calls"] += 1
    if "graphql_error" in st:  # a cloud session's proxy refuses GraphQL
        fail(st["graphql_error"])
    var = dict(a.split("=", 1) for a in rest[1:] if "=" in a)
    r = find(f"{var['owner']}/{var['name']}") or {}
    issues = r.get("issues", {})
    if "userContentEdits" in var["query"]:
        edits = r.get("edits", {}).get(var["number"], [])
        out({"data": {"repository": {"issue": {"userContentEdits": {"nodes": edits}}}}})
    data, errors = {}, []
    for alias, num in re.findall(r"(\w+): issueOrPullRequest\(number: (\d+)\)", var["query"]):
        it = issues.get(num)
        if it is None:
            data[alias] = None
            errors.append({"type": "NOT_FOUND", "path": ["repository", alias],
                           "message": f"Could not resolve to an issue or pull request with the number of {num}."})
        else:
            data[alias] = {"number": int(num), "updatedAt": it.get("updated_at")}
    body = {"data": {"repository": data}}
    if errors:  # gh prints the body, then fails with the errors (exit 1)
        body["errors"] = errors
        save()
        print(json.dumps(body))
        print("gh: " + errors[0]["message"], file=sys.stderr)
        sys.exit(1)
    out(body)
if rest[:2] == ["-X", "PATCH"]:
    method, rest = "PATCH", rest[2:]
path = rest[0]
u = urlsplit(path)
q = {k: v[0] for k, v in parse_qs(u.query).items()}
parts = u.path.split("/")

if method == "PATCH":
    repo = f"{parts[1]}/{parts[2]}"
    body = json.load(open(rest[rest.index("--input") + 1]))["body"]
    st.setdefault("patches", []).append(body)
    if not st.get("patch_noop"):
        it = find(repo)["issues"][parts[4]]
        original = it.get("body", "")
        it["body"] = body
        # GitHub's clock moves updated_at, and the edit lands in the body's
        # history, under the one account every thread writes as (#518).
        now = st.get("server_now", "2026-10-14T18:03:27Z")
        it["updated_at"] = now
        edits = find(repo).setdefault("edits", {}).setdefault(parts[4], [])
        if not edits:  # a body's first edit also records it as created (CR 1195)
            edits.append(original_node(it, it.get("created_body", original), now))
        edits.append({"editedAt": now, "updatedAt": now, "editor": {"login": "gregoryfoster"}, "diff": body})
    after = st.get("patch_fails_after_apply")  # GitHub applied it; gh saw a 502
    if after:  # or gh's whole stderr, when a string
        fail(after if isinstance(after, str) else "HTTP 502: Bad Gateway")
    out({"number": int(parts[4])})

repo = f"{parts[1]}/{parts[2]}"
r = find(repo)
if r is None:
    fail()
issues = r.get("issues", {})

if len(parts) == 3:  # repos/OWNER/REPO: the repo itself
    if "repo_error" in st:
        fail(st["repo_error"])
    out({"default_branch": r.get("default_branch", "main")})

if len(parts) == 6 and parts[3] == "issues" and parts[4] == "comments":
    cid = parts[5]
    if cid not in st.get("comment_index", {}):
        fail()
    out({"id": int(cid), "issue_url": st["comment_index"][cid]})

if len(parts) == 4 and parts[3] == "issues":
    rows = [dict(it, number=int(n)) for n, it in issues.items()]
    if "since" in q:
        rows = [x for x in rows if x.get("updated_at", "") >= q["since"]]
        # GitHub's listing can leave out a row updated minutes earlier (#407).
        rows = [x for x in rows if x["number"] not in st.get("list_omits", [])]
    if q.get("sort") == "created":
        rows.sort(key=lambda x: (x.get("created_at", ""), x["number"]), reverse=True)
    else:
        rows.sort(key=lambda x: x["number"], reverse=True)
    per, page = int(q.get("per_page", 30)), int(q.get("page", 1))
    out(rows[(page - 1) * per : page * per])

if len(parts) == 5 and parts[3] == "issues":
    it = issues.get(parts[4])
    if it is None:
        fail()
    gets = st.setdefault("gets", {})
    gets[parts[4]] = gets.get(parts[4], 0) + 1
    if st.get("fail_on_get", {}).get(parts[4]) == gets[parts[4]]:
        fail("HTTP 502: Bad Gateway")
    change = st.get("change_on_get", {}).get(parts[4])
    if change and gets[parts[4]] == change["at"]:
        it.update({k: v for k, v in change.items() if k != "at"})
    out(dict(it, number=int(parts[4])))

if len(parts) == 6 and parts[5] == "comments":
    cs = r.get("comments", {}).get(parts[4], [])
    if "since" in q:
        cs = [c for c in cs if c.get("updated_at", "") >= q["since"]]
    per, page = int(q.get("per_page", 30)), int(q.get("page", 1))
    out(cs[(page - 1) * per : page * per])

fail()
"""


class Rig:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(
            FAKE_GH.replace("__PYTHON__", sys.executable).replace(
                "__CREATED__", CREATED
            )
        )
        gh.chmod(0o755)
        self.state_path = tmp / "gh-state.json"
        self.state_dir = tmp / "state"
        self.state: dict = {"repos": {}, "comment_index": {}}
        self.save()

    # state ---------------------------------------------------------------
    def save(self) -> None:
        self.state_path.write_text(json.dumps(self.state))

    def load(self) -> dict:
        self.state = json.loads(self.state_path.read_text())
        return self.state

    def issue(self, repo: str, num: int, **fields) -> None:
        self.load()
        r = self.state["repos"].setdefault(repo, {"issues": {}, "comments": {}})
        it = r["issues"].setdefault(
            str(num), {"state": "open", "title": f"issue {num}", "body": ""}
        )
        it.update(fields)
        self.save()

    def comment(self, repo: str, num: int, cid: int, **fields) -> None:
        self.load()
        r = self.state["repos"][repo]
        r.setdefault("comments", {}).setdefault(str(num), []).append(
            dict(
                {
                    "id": cid,
                    "html_url": f"https://github.com/{repo}/issues/{num}#issuecomment-{cid}",
                },
                **fields,
            )
        )
        self.state["comment_index"][str(cid)] = (
            f"https://api.github.com/repos/{repo}/issues/{num}"
        )
        self.save()

    def pr(self, repo: str, num: int, closes: list) -> None:
        self.load()
        self.state["repos"][repo].setdefault("prs", {})[str(num)] = closes
        self.save()

    def change_on_get(self, num: int, at: int, body: str) -> None:
        """Another writer edits issue num just before the at-th GET of it.

        The edit persists, so every GET from the at-th on sees it: at=2 means
        "after the first fetch", whichever later fetch comes next.
        """
        self.load()
        self.state.setdefault("change_on_get", {})[str(num)] = {"at": at, "body": body}
        self.state["gets"] = {}
        self.save()

    def fail_on_get(self, num: int, at: int) -> None:
        """The at-th GET of issue num, counted from now, fails as a 502."""
        self.load()
        self.state.setdefault("fail_on_get", {})[str(num)] = at
        self.state["gets"] = {}
        self.save()

    def auto_edit(self, num: int, body: str, repo: str = "acme/widgets") -> None:
        """GitHub's own edit, such as a closing child's auto-tick: no history
        entry, and the body as created stays what the first edit records."""
        self.load()
        it = self.state["repos"][repo]["issues"][str(num)]
        it.setdefault("created_body", it.get("body", ""))
        it["body"] = body
        self.save()

    def edit_elsewhere(
        self, num: int, body: str, at: str, repo: str = "acme/widgets"
    ) -> None:
        """Another thread edits issue num's body at GitHub time at, by hand."""
        self.load()
        r = self.state["repos"][repo]
        it = r["issues"][str(num)]
        edits = r.setdefault("edits", {}).setdefault(str(num), [])
        if not edits:  # as the fake's PATCH does (CR 1195)
            edits.append(
                {
                    "editedAt": it.get("created_at", CREATED),
                    "updatedAt": at,
                    "editor": {"login": "gregoryfoster"},
                    "diff": it.get("created_body", it.get("body", "")),
                }
            )
        it.update(body=body, updated_at=at)
        edits.append(
            {
                "editedAt": at,
                "updatedAt": at,
                "editor": {"login": "gregoryfoster"},
                "diff": body,
            }
        )
        self.save()

    def body(self, repo: str, num: int) -> str:
        return self.load()["repos"][repo]["issues"][str(num)]["body"]

    def set_flag(self, name: str, value) -> None:
        self.load()
        self.state[name] = value
        self.save()

    # running -------------------------------------------------------------
    def env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["PATH"] = f"{self.bin}{os.pathsep}{env.get('PATH', '')}"
        env["FAKE_GH_STATE"] = str(self.state_path)
        return env

    def run(
        self,
        script: str,
        *args: str,
        stdin: str | None = None,
        extra_env: dict | None = None,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SCRIPTS / script), *args],
            input=stdin,
            capture_output=True,
            text=True,
            env={**self.env(), **(extra_env or {})},
            timeout=60,
        )

    def edit(
        self, repo: str, epic: int, ops: list | None = None, *flags: str
    ) -> subprocess.CompletedProcess:
        args = [
            "--repo",
            repo,
            "--epic",
            str(epic),
            "--state-dir",
            str(self.state_dir),
            *flags,
        ]
        if ops is not None:
            args += ["--ops", "-"]
            return self.run("epic-edit.sh", *args, stdin=json.dumps(ops))
        return self.run("epic-edit.sh", *args)


def summary(r: subprocess.CompletedProcess) -> dict:
    return json.loads(r.stdout)
