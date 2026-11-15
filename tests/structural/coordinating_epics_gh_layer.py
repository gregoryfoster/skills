"""A layer over coordinating_epics_rig's fake gh: per-repo tokens and comment posts.

Kept out of the rig so the rig stays one file other chains edit. `install`
moves the rig's fake to `gh-base` and puts this layer at `gh`; every call the
layer doesn't answer is handed to the base unchanged.

What the layer adds, all read from the rig's own state file:

- `tokens`: {"owner/repo": "value"}. A call on that repo whose GH_TOKEN isn't
  the value fails as GitHub does for a private repo the token can't see: 404
  (#520). Every call's repo and GH_TOKEN go in `token_calls`.
- `echo_env`: "owner/repo". A call on that repo fails, printing its GH_TOKEN
  and argv to stderr, so a test can assert no token value is ever shown.
- comment posts (#395): `gh api -X POST repos/O/R/issues/N/comments --input F`
  stores the comment, and `gh api repos/O/R/issues/comments/ID` reads it back
  with its body. `post_error` fails the post before it lands,
  `post_fails_after_apply` after; `post_stores` is the body GitHub keeps
  instead of the one sent; `comment_get_error` fails the read-back.
"""

from __future__ import annotations

import sys

LAYER = r"""#!__PYTHON__
import datetime as dt, json, os, re, sys

state_path = os.environ["FAKE_GH_STATE"]
st = json.load(open(state_path))
args = sys.argv[1:]
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gh-base")


def save():
    json.dump(st, open(state_path, "w"))


def fail(msg="HTTP 404: Not Found"):
    save()
    if msg:
        print(f"gh: {msg}", file=sys.stderr)
    sys.exit(1)


def repo_of(args):
    if args[:2] == ["api", "graphql"]:
        v = dict(a.split("=", 1) for a in args[2:] if "=" in a)
        return f"{v.get('owner')}/{v.get('name')}"
    for i, a in enumerate(args):
        if a in ("-R", "--repo") and i + 1 < len(args):
            return args[i + 1]
        m = re.match(r"repos/([^/]+/[^/?]+)", a)
        if m:
            return m.group(1)
    return None


repo = repo_of(args) or ""
tok = os.environ.get("GH_TOKEN", "")
st.setdefault("token_calls", []).append([repo, tok])
if st.get("echo_env", "").lower() == repo.lower() and repo:
    fail(f"HTTP 404: Not Found\nGH_TOKEN={tok}\nargv: {' '.join(args)}")
need = {k.lower(): v for k, v in st.get("tokens", {}).items()}.get(repo.lower())
if need is not None and tok != need:
    fail()


def find(repo):
    return next((v for k, v in st["repos"].items() if k.lower() == repo.lower()), None)


now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
m = re.fullmatch(r"repos/([^/]+/[^/]+)/issues/(\d+)/comments", args[3] if len(args) > 3 else "")
if args[:3] == ["api", "-X", "POST"] and m:
    body = json.load(open(args[args.index("--input") + 1]))["body"]
    st.setdefault("posts", []).append(body)
    if "post_error" in st:
        fail(st["post_error"])
    r = find(m.group(1))
    if r is None or m.group(2) not in r.get("issues", {}):
        fail()
    cid = st.get("next_comment_id", 9001)
    st["next_comment_id"] = cid + 1
    kept = st.get("post_stores", body)
    url = f"https://github.com/{m.group(1)}/issues/{m.group(2)}#issuecomment-{cid}"
    api = f"https://api.github.com/repos/{m.group(1)}/issues/{m.group(2)}"
    c = {"id": cid, "html_url": url, "issue_url": api, "body": kept,
         "created_at": now, "updated_at": now}
    r.setdefault("comments", {}).setdefault(m.group(2), []).append(c)
    st.setdefault("comment_index", {})[str(cid)] = api
    st.setdefault("comment_bodies", {})[str(cid)] = c
    if st.get("post_fails_after_apply"):
        fail(st["post_fails_after_apply"])
    save()
    print(json.dumps(c))
    sys.exit(0)

m = re.fullmatch(r"repos/[^/]+/[^/]+/issues/comments/(\d+)", args[1] if len(args) > 1 else "")
if args[:1] == ["api"] and len(args) == 2 and m and m.group(1) in st.get("comment_bodies", {}):
    if "comment_get_error" in st:
        fail(st["comment_get_error"])
    save()
    print(json.dumps(st["comment_bodies"][m.group(1)]))
    sys.exit(0)

save()
os.execv(BASE, [BASE, *args])
"""


def install(rig) -> None:
    """Put the layer in front of the rig's fake gh."""
    base = rig.bin / "gh-base"
    (rig.bin / "gh").rename(base)
    layer = rig.bin / "gh"
    layer.write_text(LAYER.replace("__PYTHON__", sys.executable))
    layer.chmod(0o755)


def token_calls(rig) -> list[tuple[str, str]]:
    """Every gh call's (repo, GH_TOKEN) since the rig began."""
    return [tuple(x) for x in rig.load().get("token_calls", [])]


def output(res) -> str:
    return res.stdout + res.stderr

