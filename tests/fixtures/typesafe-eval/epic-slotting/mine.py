#!/usr/bin/env python3
"""Mine and build #439's labelled set. Kept beside the set (#463's note).

usage: python3 -I -B mine.py fetch RAW LABELS.tsv
       python3 -I -B mine.py first-seen RAW > ROWS.jsonl
       python3 -I -B mine.py build RAW LABELS.tsv SET.jsonl PAIRS.jsonl
       python3 -I -B mine.py compare SET.jsonl CACHE.jsonl LABELS.tsv
       python3 -I -B mine.py pairs SET.jsonl PAIRS.jsonl CACHE.jsonl MARGIN
       python3 -I -B mine.py repeats CACHE.jsonl

fetch       every public epic in EPICS with its whole body history
            (`userContentEdits`, whose oldest node is the original body), each
            epic repo's issue list, and the history of every item LABELS.tsv
            names, into RAW. Needs an authenticated gh.
first-seen  the mechanical half of the labelling, one JSON row per same-repo
            issue (not PR) filed after its epic: the first body revision that
            names it, ranges like `#360–#373` included, where it lands there
            (`box`: a checklist line it leads; `nobox`; `never`), the sections
            naming it, the new log sentences naming it, and a draft label
            (`box` is child, a Parked section or "park" in the log is park, an
            out-of-scope section or "out of epic" in the log is out). The
            labels in LABELS.tsv are those drafts after a hand read of every
            row that isn't a checklist line, and of 30 that are.
build       the evaluator's set and the pairs. A case is one labelled item:
            the epic as it read in the revision *before* the one that slotted
            the item (`epic_view`), and the item's body as it stood at that
            edit (`item_view`), asked QUESTIONS. A pair case asks again with
            the epic as it read before the later edit that changed the slot.
compare     #439's headline, from the set and the cache alone, as JSON: the
            Choice's agreement against the kind-aware plain baseline
            (`plain`), per epic kind and without the same-edit labels, with
            the paired counts and a two-sided sign test.
pairs       [toward, away, within MARGIN]: for each item whose slot changed
            at a later check-in, whether P(the later slot) rose from its first
            reading to the later one. Read MARGIN off `repeats`.
repeats    how often the same request answered twice changed its choice,
            and how far its confidence moved.

No pass shipped, so the builder lives here. The epics are public repos only;
the fixture README's step 1 re-checks that at commit time. Stdlib only.
"""

from __future__ import annotations

import collections
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

MODEL = "jev-1.13.0"
# The 15 public epics carrying the cursor header, 2026-10-24. status#16 has
# no Log, and wslcb#219 had slotted nothing yet, so neither gives a label.
EPICS = [
    "gregoryfoster/skills#451",
    "gregoryfoster/skills#404",
    "CannObserv/address-validator#272",
    "CannObserv/archiver#357",
    "CannObserv/broker#80",
    "CannObserv/notifier#116",
    "CannObserv/power-map#598",
    "CannObserv/processor#24",
    "CannObserv/replicator#135",
    "CannObserv/status#16",
    "CannObserv/usa-wa#414",
    "CannObserv/watcher#368",
    "CannObserv/watcher#394",
    "CannObserv/wslcb-licensing-tracker#205",
    "CannObserv/wslcb-licensing-tracker#219",
]
USABLE = ("child", "out of epic", "park", "closed-in-fact", "duplicate", "split")
# (case id, the slot it moved to, the revision whose edit moved it).
PAIRS = [
    ("CannObserv/address-validator#326@272", "child", 59),
    ("CannObserv/archiver#390@357", "child", 8),
    ("CannObserv/archiver#394@357", "child", 8),
    ("CannObserv/archiver#397@357", "park", 12),
    ("CannObserv/usa-wa#512@414", "park", 43),
    ("CannObserv/watcher#397@394", "park", 6),
    ("CannObserv/address-validator#311@272", "child", 27),
]

# --- the case -----------------------------------------------------------------

MAX_ITEM_BODY = 12_000
MAX_GOAL = 4_000
MAX_LINE = 400
MAX_SECTION = 6_000
BOX_RE = re.compile(r"^\s*[-*]\s*\[([ xX])\]\s*(.*)$")
HEAD_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
CURSOR_RE = re.compile(
    r"^\s*[-*]\s*\*\*(Last check-in|Last issue seen|Last verified SHA|Next|Last probe)\b",
    re.I,
)
# The sections that say what the epic covers and what it doesn't.
SCOPE_RE = re.compile(
    r"boundar|scope|not tracked|outside|out of|rule|exit criterion|related", re.I
)
PARK_RE = re.compile(r"park", re.I)

SLOT = (
    "`epic` is a GitHub issue that tracks a body of work through a checklist of "
    "child issues: `epic.goal` says what it covers, `epic.scope` holds its "
    "boundary decisions and rules, `epic.children` its checklist lines (done: "
    "ticked), and `epic.parked` what waits on a trigger. `item` is an issue filed "
    "since the coordinator last looked, with its state now. Which slot does the "
    "coordinator give `item` in this epic?"
)
# check-in.md §3's six outcomes, each in §3's own terms.
OPTIONS = {
    "child": "Work this epic covers and that should be done now or in order: it "
    "gets its own checklist line, slotted by dependency. A follow-up to a child, "
    "a bug in what a child shipped, or a piece split off a child is a child.",
    "closed-in-fact": "Work this epic covers that is already delivered: the item "
    "is closed, or a child's merged change already did it, so it is verified, "
    "linked and closed with evidence instead of slotted.",
    "split": "The item mixes work this epic covers with work it doesn't, so the "
    "epic's part is filed as its own issue and the rest is left out.",
    "out of epic": "Not this epic's work: another skill, service, area or epic, a "
    "record or notice with no action, or tooling around the epic rather than its "
    "work. It is said so plainly and cross-linked only where it changes a "
    "remaining step.",
    "duplicate": "The same work as an existing child or another open issue, so it "
    "is closed in favour of that one.",
    "park": "This epic's concern, but not to be done yet: it waits on a trigger "
    "(another repo, a decision, a date, an event) and goes in the parked table "
    "with that trigger.",
}
QUESTIONS = {"slot": {"type": "choice", "instructions": SLOT, "criteria": OPTIONS}}


def _clip(s: str, n: int) -> str:
    s = s.strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def epic_view(number: int, title: str, body: str) -> dict:
    """The epic as the Choice reads it: goal, scope sections, checklist, parked."""
    goal, sections, cur, children, parked, scope = [], {}, None, [], [], []
    for line in body.splitlines():
        h = HEAD_RE.match(line)
        if h:
            cur = h.group(2)
            sections[cur] = []
            continue
        if cur is None:
            if not CURSOR_RE.match(line):
                goal.append(line)
            continue
        sections[cur].append(line)
        m = BOX_RE.match(line)
        if m:
            children.append(
                {"done": m.group(1) != " ", "line": _clip(m.group(2), MAX_LINE)}
            )
    for name, lines in sections.items():
        text = "\n".join(x for x in lines if not BOX_RE.match(x)).strip()
        if not text or re.search(r"\blog\b", name, re.I):
            continue
        if PARK_RE.search(name):
            parked.append(_clip(text, MAX_SECTION))
        elif SCOPE_RE.search(name):
            scope.append({"section": name, "text": _clip(text, MAX_SECTION)})
    return {
        "number": number,
        "title": title,
        "goal": _clip("\n".join(goal), MAX_GOAL),
        "scope": scope,
        "children": children,
        "parked": parked,
    }


def item_view(number: int, title: str, body: str, state: str, labels: list) -> dict:
    return {
        "number": number,
        "title": title,
        "state": state,
        "labels": labels,
        "body": _clip(body or "", MAX_ITEM_BODY),
    }


def build_case(epic: dict, item: dict) -> tuple:
    return {"epic": epic, "item": item}, QUESTIONS


# --- the plain baseline -------------------------------------------------------

CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
REF = re.compile(r"(?<![\w#.-])(?:([\w.-]+/[\w.-]+))?#(\d+)(?!\d)")
PROCESS_LOG = re.compile(r"process[- ]log", re.I)
BURN_DOWN = re.compile(r"burn[- ]?down|backlog", re.I)


def kind(epic_title: str) -> str:
    """A whole-backlog burn-down, or a themed epic: read from the title."""
    return "burn-down" if BURN_DOWN.search(epic_title) else "themed"


def _refs(text: str, repo: str) -> set:
    return {
        ((m.group(1) or repo).lower(), int(m.group(2)))
        for m in REF.finditer(CODE.sub(" ", text))
    }


def plain(state: dict, repo: str) -> str:
    """The kind-aware plain slot: in a burn-down every new issue is a child; in a
    themed epic, a child only when it names the epic or an open child's line.
    A process-log entry is out of either."""
    item, epic, repo = state["item"], state["epic"], repo.lower()
    if PROCESS_LOG.search(item["title"]):
        return "out of epic"
    if kind(epic["title"]) == "burn-down":
        return "child"
    open_refs = set()
    for c in epic["children"]:
        m = None if c["done"] else REF.search(c["line"])
        if m:
            open_refs.add(((m.group(1) or repo).lower(), int(m.group(2))))
    named = _refs(item["title"] + "\n" + item["body"], repo)
    return (
        "child"
        if (repo, epic["number"]) in named or named & open_refs
        else "out of epic"
    )


# --- loading ------------------------------------------------------------------


def _gh(args: list[str]):
    return json.loads(subprocess.check_output(["gh", *args]))


def _name(ref: str) -> tuple[str, str, int]:
    repo, n = ref.split("#")
    owner, name = repo.split("/")
    return owner, name, int(n)


EDITS_Q = """query($o:String!,$r:String!,$n:Int!,$c:String){repository(owner:$o,name:$r){
 issueOrPullRequest(number:$n){ ... on Issue { number title body createdAt
 userContentEdits(first:100, after:$c){pageInfo{hasNextPage endCursor}
 nodes{editedAt diff}}}}}}"""


def _history(owner: str, name: str, n: int) -> dict:
    out, cursor = None, None
    while True:
        args = ["api", "graphql", "-f", f"query={EDITS_Q}"]
        args += ["-F", f"o={owner}", "-F", f"r={name}", "-F", f"n={n}"]
        if cursor:
            args += ["-F", f"c={cursor}"]
        d = _gh(args)["data"]["repository"]["issueOrPullRequest"]
        page = d["userContentEdits"]
        if out is None:
            out, d["userContentEdits"] = d, list(page["nodes"])
        else:
            out["userContentEdits"] += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return out
        cursor = page["pageInfo"]["endCursor"]


def _issues(repo: str) -> list:
    items, page = [], 1
    while True:
        d = _gh(["api", f"repos/{repo}/issues?state=all&per_page=100&page={page}"])
        if not d:
            return items
        items += [
            {
                "number": x["number"],
                "title": x["title"],
                "state": x["state"],
                "created_at": x["created_at"],
                "closed_at": x["closed_at"],
                "pr": "pull_request" in x,
                "author": x["user"]["login"],
                "labels": [lb["name"] for lb in x["labels"]],
            }
            for x in d
        ]
        page += 1


def fetch(raw: Path, labels: Path) -> None:
    for sub in ("epics", "repos", "items"):
        (raw / sub).mkdir(parents=True, exist_ok=True)
    for ref in EPICS:
        o, r, n = _name(ref)
        (raw / "epics" / f"{o}_{r}_{n}.json").write_text(json.dumps(_history(o, r, n)))
    for repo in sorted({e.split("#")[0] for e in EPICS}):
        (raw / "repos" / f"{repo.replace('/', '_')}.json").write_text(
            json.dumps(_issues(repo))
        )
    for lab in read_labels(labels).values():
        o, r, n = _name(lab["id"].split("@")[0])
        (raw / "items" / f"{o}_{r}_{n}.json").write_text(json.dumps(_history(o, r, n)))


def revisions(epic: dict) -> list[tuple[str, str]]:
    """(editedAt, body) oldest first. An epic never edited has only its body."""
    rv = sorted(
        ((e["editedAt"], e["diff"] or "") for e in epic["userContentEdits"]),
        key=lambda x: x[0],
    )
    if not rv or rv[-1][1] != (epic["body"] or ""):
        rv.append(("9999", epic["body"] or ""))
    return rv


def body_at(item: dict, when: str) -> str:
    """The body as it stood at WHEN: the newest edit at or before it."""
    es = [e for e in item["userContentEdits"] if e["editedAt"] <= when]
    return (max(es, key=lambda e: e["editedAt"])["diff"] if es else item["body"]) or ""


def _load(raw: Path, kind_: str, name: str):
    return json.loads((raw / kind_ / f"{name}.json").read_text())


# --- first-seen ---------------------------------------------------------------

RANGE = re.compile(r"(?<![\w/#.-])#(\d+)\s*(?:–|—|-|to)\s*#(\d+)(?!\d)")
SENT = re.compile(r"(?<=[.;:!?])\s+(?=[A-Z#*(`])")
OUT_RE = re.compile(
    r"out of (the )?epic|not a child|outside|out of scope|not this epic|not tracked",
    re.I,
)


def mentions(n: int, text: str, repo: str) -> bool:
    if re.search(rf"(?<![\w/#.-])#{n}(?!\d)", text):
        return True
    if re.search(rf"(?<![\w.-]){re.escape(repo)}#{n}(?!\d)", text, re.I):
        return True
    return any(
        int(a) < n < int(b) and int(b) - int(a) < 40 for a, b in RANGE.findall(text)
    )


def log_lines(body: str) -> list[str]:
    m = re.search(r"^#{1,3}\s*Log\b.*?$(.*?)(?=^#{1,3}\s|\Z)", body, re.M | re.S)
    return [x for x in (m.group(1).splitlines() if m else []) if x.strip()]


def leads(n: int, line: str, repo: str) -> bool:
    """A checklist line whose first ref is the item."""
    m = BOX_RE.match(line)
    fr = m and re.search(r"(?:[\w.-]+/[\w.-]+)?#(\d+)", m.group(2))
    return (
        bool(fr)
        and fr.group(1) == str(n)
        and fr.group(0).lower()
        in (
            f"#{n}",
            f"{repo}#{n}".lower(),
        )
    )


def first_seen(raw: Path):
    for ref in EPICS:
        o, r, num = _name(ref)
        repo, epic = f"{o}/{r}", _load(raw, "epics", f"{o}_{r}_{num}")
        rv = revisions(epic)
        if not any(log_lines(b) for _, b in rv):
            continue
        for it in sorted(_load(raw, "repos", f"{o}_{r}"), key=lambda i: i["number"]):
            n = it["number"]
            if n <= num or it["pr"]:
                continue
            row = {"id": f"{repo}#{n}@{num}", "title": it["title"]}
            hit = next(
                (
                    k
                    for k, (t, b) in enumerate(rv)
                    if t >= it["created_at"] and mentions(n, b, repo)
                ),
                None,
            )
            if hit is None:
                yield {**row, "where": "never", "draft": "never"}
                continue
            body, prev = rv[hit][1], rv[hit - 1][1] if hit else ""
            cur, secs = "(top)", set()
            for line in body.splitlines():
                h = HEAD_RE.match(line)
                if h:
                    cur = h.group(2)
                elif mentions(n, line, repo):
                    secs.add(cur)
            box = any(leads(n, x, repo) for x in body.splitlines())
            ctx = [
                s
                for x in log_lines(body)
                if x not in prev
                for s in SENT.split(x)
                if mentions(n, s, repo)
            ]
            text = " ".join(ctx)
            if box:
                draft = "child"
            elif any(PARK_RE.search(s) for s in secs) or re.search(
                r"\bpark", text, re.I
            ):
                draft = "park"
            elif OUT_RE.search(text) or any(OUT_RE.search(s) for s in secs):
                draft = "out of epic"
            else:
                draft = "?"
            yield {
                **row,
                "rev": hit,
                "t": rv[hit][0],
                "where": "box" if box else "nobox",
                "sections": sorted(secs),
                "log": ctx,
                "draft": draft,
            }


# --- build --------------------------------------------------------------------


def read_labels(path: Path) -> dict[str, dict]:
    lines = path.read_text().splitlines()
    head = lines[0].split("\t")
    return {
        row["id"]: row
        for row in (dict(zip(head, x.split("\t"))) for x in lines[1:] if x.strip())
    }


def case_at(raw: Path, case_id: str, rev: int, expected: str, source: str) -> dict:
    """One case: the epic as it read before revision REV, the item as of REV."""
    item_ref, epic_n = case_id.split("@")
    o, r, n = _name(item_ref)
    repo = f"{o}/{r}"
    epic = _load(raw, "epics", f"{o}_{r}_{epic_n}")
    rv = revisions(epic)
    when = rv[rev][0]
    issue = next(i for i in _load(raw, "repos", f"{o}_{r}") if i["number"] == n)
    state = "closed" if issue["closed_at"] and issue["closed_at"] < when else "open"
    body = body_at(_load(raw, "items", f"{o}_{r}_{n}"), when)
    st, q = build_case(
        epic_view(epic["number"], epic["title"], rv[rev - 1][1]),
        item_view(n, issue["title"], body, state, issue["labels"]),
    )
    return {
        "id": case_id,
        "state": st,
        "questions": q,
        "expected": {"slot": expected},
        "source": source or f"{repo}#{epic_n} r{rev}",
    }


def build(raw: Path, labels: Path, set_out: Path, pairs_out: Path) -> None:
    labs = read_labels(labels)
    rows = [
        case_at(raw, i, int(lab["rev"]), lab["label"], f"{lab['epic']} r{lab['rev']}")
        for i, lab in labs.items()
        if lab["label"] in USABLE
    ]
    pairs = []
    for cid, slot, rev in PAIRS:
        c = case_at(raw, cid, rev, slot, "")
        c["id"] = f"{cid}:later"
        pairs.append(c)
    for out, cases in ((set_out, rows), (pairs_out, pairs)):
        out.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases))


# --- measuring ----------------------------------------------------------------


def request_key(state, questions) -> str:
    """typesafe-eval.py's cache key, so the committed cache replays a pair too."""
    body = json.dumps(
        {"model": MODEL, "state": state, "questions": questions},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def cache_entries(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def read_cache(path: Path) -> dict:
    """Key -> reply. A repeated key keeps its last reply, as typesafe-eval.py does."""
    return {e["key"]: e["reply"] for e in cache_entries(path)}


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def sign_p(better: int, worse: int) -> float:
    n, k = better + worse, min(better, worse)
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2**n)


def compare(set_path: Path, cache_path: Path, labels: Path) -> dict:
    cache, labs = read_cache(cache_path), read_labels(labels)
    rows = []
    for c in _jsonl(set_path):
        want = c["expected"]["slot"]
        got = cache[request_key(c["state"], c["questions"])]["answers"]["slot"][
            "choice"
        ]
        base = plain(c["state"], c["id"].split("#")[0])
        lab = labs[c["id"]]
        rows.append((lab["kind"], lab["flag"], want, got == want, base == want))

    def tally(sub):
        b = sum(ok and not pb for *_, ok, pb in sub)
        w = sum(pb and not ok for *_, ok, pb in sub)
        return {
            "n": len(sub),
            "choice": sum(ok for *_, ok, _ in sub),
            "plain": sum(pb for *_, pb in sub),
            "choice_only": b,
            "plain_only": w,
            "sign_p": round(sign_p(b, w), 6),
        }

    out = {"all": tally(rows)}
    out["all, no same-edit"] = tally([x for x in rows if x[1] != "same-edit"])
    for k in ("burn-down", "themed"):
        out[k] = tally([x for x in rows if x[0] == k])
    return out


def pairs(set_path: Path, pairs_path: Path, cache_path: Path, margin: float) -> list:
    """[toward, away, within MARGIN]: did P(the later slot) rise from the first
    reading of the epic to the one before the edit that moved the item?"""
    cache = read_cache(cache_path)
    first = {c["id"]: c for c in _jsonl(set_path)}
    out = [0, 0, 0]
    for later in _jsonl(pairs_path):
        slot = later["expected"]["slot"]
        p = [
            cache[request_key(c["state"], c["questions"])]["answers"]["slot"][
                "probabilities"
            ][slot]
            for c in (first[later["id"].rsplit(":", 1)[0]], later)
        ]
        d = round(p[1] - p[0], 6)
        out[0 if d > margin else 1 if d < -margin else 2] += 1
    return out


def repeats(cache_path: Path) -> dict:
    by_key = collections.defaultdict(list)
    for e in cache_entries(cache_path):
        by_key[e["key"]].append(e["reply"]["answers"]["slot"])
    again = [v for v in by_key.values() if len(v) > 1]
    moves = sorted(
        round(max(a["confidence"] for a in v) - min(a["confidence"] for a in v), 6)
        for v in again
        if len({a["choice"] for a in v}) == 1
    )
    return {
        "repeated": len(again),
        "choice_changed": sum(len({a["choice"] for a in v}) > 1 for v in again),
        "max_move": moves[-1] if moves else None,
        "p90_move": moves[int(0.9 * len(moves))] if moves else None,
    }


def main(argv: list[str]) -> int:
    cmd, *args = argv or ["--help"]
    if cmd == "fetch" and len(args) == 2:
        fetch(Path(args[0]), Path(args[1]))
    elif cmd == "first-seen" and len(args) == 1:
        for row in first_seen(Path(args[0])):
            print(json.dumps(row, ensure_ascii=False))
    elif cmd == "build" and len(args) == 4:
        build(*map(Path, args))
    elif cmd == "compare" and len(args) == 3:
        print(json.dumps(compare(*map(Path, args)), indent=1))
    elif cmd == "pairs" and len(args) == 4:
        print(json.dumps(pairs(*map(Path, args[:3]), float(args[3]))))
    elif cmd == "repeats" and len(args) == 1:
        print(json.dumps(repeats(Path(args[0]))))
    else:
        print(__doc__.strip(), file=sys.stderr if cmd != "--help" else sys.stdout)
        return 0 if cmd == "--help" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
