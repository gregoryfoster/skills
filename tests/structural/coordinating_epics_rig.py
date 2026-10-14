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
SCRIPTS = REPO_ROOT / "skills" / "coordinating-epics" / "scripts"

FAKE_GH = r"""#!__PYTHON__
import json, os, sys
from urllib.parse import parse_qs, urlsplit

state_path = os.environ["FAKE_GH_STATE"]
st = json.load(open(state_path))
args = sys.argv[1:]
st.setdefault("calls", []).append(args)

def save():
    json.dump(st, open(state_path, "w"))

def out(obj):
    save()
    print(json.dumps(obj))
    sys.exit(0)

def fail(msg="HTTP 404: Not Found"):
    save()
    print(f"gh: {msg}", file=sys.stderr)
    sys.exit(1)

if st.get("fail_all"):
    fail(st["fail_all"])

if args[:2] == ["issue", "list"]:
    repo = args[args.index("-R") + 1]
    issues = st["repos"].get(repo, {}).get("issues", {})
    out([{"number": int(n)} for n, it in issues.items() if it.get("state") == "open" and not it.get("pull_request")])

if args[:2] == ["pr", "view"]:
    num, repo = args[2], args[args.index("-R") + 1]
    if st.get("pr_error"):
        fail(st["pr_error"])
    closes = st["repos"].get(repo, {}).get("prs", {}).get(num)
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
rest = args[1:]
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
        st["repos"][repo]["issues"][parts[4]]["body"] = body
    out({"number": int(parts[4])})

repo = f"{parts[1]}/{parts[2]}"
r = st["repos"].get(repo)
if r is None:
    fail()
issues = r.get("issues", {})

if len(parts) == 6 and parts[3] == "issues" and parts[4] == "comments":
    cid = parts[5]
    if cid not in st.get("comment_index", {}):
        fail()
    out({"id": int(cid), "issue_url": st["comment_index"][cid]})

if len(parts) == 4 and parts[3] == "issues":
    rows = [dict(it, number=int(n)) for n, it in issues.items()]
    if "since" in q:
        rows = [x for x in rows if x.get("updated_at", "") >= q["since"]]
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
    change = st.get("change_on_get", {}).get(parts[4])
    if change and gets[parts[4]] == change["at"]:
        it["body"] = change["body"]
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
        gh.write_text(FAKE_GH.replace("__PYTHON__", sys.executable))
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
        """Another writer edits issue num just before the at-th GET of it."""
        self.load()
        self.state.setdefault("change_on_get", {})[str(num)] = {"at": at, "body": body}
        self.state["gets"] = {}
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
