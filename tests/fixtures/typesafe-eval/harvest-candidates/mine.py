#!/usr/bin/env python3
"""Mine #436's labelled set: harvests that happened, replayed against the open children.

usage: python3 -I -B mine.py fetch RAW_DIR
       python3 -I -B mine.py align RAW_DIR [JMIN]
       python3 -I -B mine.py build RAW_DIR OUT.jsonl
       python3 -I -B mine.py threads RAW_DIR OUT.jsonl
       python3 -I -B mine.py rank SET.jsonl CACHE.jsonl
       python3 -I -B mine.py score THREADS.jsonl CACHE.jsonl SCORES.tsv
       python3 -I -B mine.py scores SCORES.tsv

Fixture code for gregoryfoster/skills#436, kept so #439 can lift the loader
(see the README). Stdlib only; `fetch` needs an authenticated gh. The pass's
own pieces are imported from skills/coordinating-epics/scripts/_harvest.py,
so the cases are built the way the shipped step builds them.

labels.tsv is the labelled set, one row per harvest or aligned paragraph:

  repo source target harvest_at comment k kind verdict

  repo, source, target  a "Changed since filed" comment on TARGET that
                        harvested SOURCE's thread (source `-` when the
                        harvest came from no child's thread)
  harvest_at            when that comment was posted: the event's time.
                        Children open then, with their bodies as of then
                        (rebuilt from GitHub's edit history), are the
                        candidates, and the source's comments before it
                        are the thread
  comment, k            a source paragraph the harvest drew on, as
                        `_harvest.comment_paras` numbers them; empty when
                        no paragraph aligned
  kind                  named (the paragraph names the target, as the step
                        reads it) | unnamed | unaligned | out-of-scope
  verdict               genuine | spurious (a hand-check of the alignment)
                        | the out-of-scope reason

fetch    downloads the "Changed since filed" comments of the public epics,
         each source thread, each epic, its children and their edit history
align    proposes, for each in-scope harvest, the source paragraphs sharing
         the most words with it (Jaccard >= JMIN, default 0.2), for a
         hand-check; the verdicts are labels.tsv's
build    writes the set: every genuine unnamed paragraph x the children open
         at its harvest, through `_harvest.build_case`
threads  writes the whole-thread set for the six events #436 measured
rank     the target's rank among the open children, by the plain-matching
         baseline (shared backticked spans, then shared words) and by the
         Noul; with the cache's repeats, the noise between two answers
score    writes scores.tsv from the whole-thread set and its replies
scores   the whole-thread table from scores.tsv (no text in it): where each
         unnamed positive ranks among its event's residue rows
"""

from __future__ import annotations

import collections
import functools
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "skills" / "coordinating-epics" / "scripts"))
sys.dont_write_bytecode = True
import _epic_edit as E  # noqa: E402
import _harvest as H  # noqa: E402

LABELS = HERE / "labels.tsv"
EPICS = {
    "CannObserv/wslcb-licensing-tracker": 205,
    "CannObserv/archiver": 300,
    "CannObserv/broker": 80,
    "gregoryfoster/skills": 451,
}
THREAD_EVENTS = [
    ("CannObserv/archiver", 307),
    ("CannObserv/archiver", 312),
    ("CannObserv/broker", 101),
    ("CannObserv/wslcb-licensing-tracker", 206),
    ("CannObserv/wslcb-licensing-tracker", 207),
    ("CannObserv/wslcb-licensing-tracker", 208),
]


# --- raw data -----------------------------------------------------------------


def _gh(args: list[str]):
    return json.loads(subprocess.check_output(["gh", *args]))


def _path(raw: Path, kind: str, repo: str, num: int) -> Path:
    return raw / kind / f"{repo.replace('/', '_')}_{num}.json"


def issue(raw: Path, repo: str, num: int) -> dict:
    p = _path(raw, "issues", repo, num)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        it = _gh(["api", f"repos/{repo}/issues/{num}"])
        pages = _gh(
            [
                "api",
                "--paginate",
                "--slurp",
                f"repos/{repo}/issues/{num}/comments?per_page=100",
            ]
        )
        p.write_text(
            json.dumps({"issue": it, "comments": [c for pg in pages for c in pg]})
        )
    return json.loads(p.read_text())


def edits(raw: Path, repo: str, num: int) -> list:
    """The body's edit history, newest first: each node's `diff` is the whole body after it."""
    p = _path(raw, "edits", repo, num)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        o, n = repo.split("/")
        q = (
            f'query{{repository(owner:"{o}",name:"{n}"){{issue(number:{num})'
            "{userContentEdits(first:100){nodes{editedAt diff}}}}}"
        )
        d = _gh(["api", "graphql", "-f", f"query={q}"])
        p.write_text(
            json.dumps(d["data"]["repository"]["issue"]["userContentEdits"]["nodes"])
        )
    return json.loads(p.read_text())


def body_at(raw: Path, repo: str, num: int, when: str) -> str:
    es = [e for e in edits(raw, repo, num) if e["editedAt"] <= when]
    return (
        (es[0]["diff"] or "") if es else (issue(raw, repo, num)["issue"]["body"] or "")
    )


def fetch(raw: Path) -> None:
    for row in read_labels():
        if row["source"] != "-":
            issue(raw, row["repo"], int(row["source"]))
        issue(raw, row["repo"], int(row["target"]))
    for repo in EPICS:
        for c in children(raw, repo):
            issue(raw, repo, c)
            edits(raw, repo, c)


# --- events -------------------------------------------------------------------


def read_labels() -> list[dict]:
    cols = "repo source target harvest_at comment k kind verdict".split()
    rows = []
    for line in LABELS.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        rows.append(dict(zip(cols, line.split("\t"))))
    return rows


def children(raw: Path, repo: str) -> list[int]:
    """The epic's checklist items in its own repo, in order."""
    host = repo.lower()
    out = []
    for line in (issue(raw, repo, EPICS[repo])["issue"]["body"] or "").splitlines():
        if E.box_state(line) is None:
            continue
        ref = E.line_ref(line, host)
        if ref and ref[1].startswith(host + "#"):
            out.append(int(ref[1].rsplit("#", 1)[1]))
    return list(dict.fromkeys(out))


def event(raw: Path, repo: str, source: int, when: str) -> tuple[list, list]:
    """(open children as of WHEN, the source's thread as the step reads it, up to WHEN)."""
    kids = []
    for n in children(raw, repo):
        if n == source:
            continue
        it = issue(raw, repo, n)["issue"]
        if it["created_at"] < when and (
            it["closed_at"] is None or it["closed_at"] > when
        ):
            kids.append(
                H.Child(
                    key=E.key(None, n, repo.lower()),
                    label=f"#{n}",
                    number=n,
                    title=it["title"],
                    body=body_at(raw, repo, n, when),
                )
            )
    return kids, H.select(issue(raw, repo, source)["comments"], None, when)


def events(raw: Path) -> dict:
    """(repo, source) -> (when, children, comments); an event's time is its first harvest's."""
    when = {}
    for r in read_labels():
        if r["kind"] != "out-of-scope":
            k = (r["repo"], int(r["source"]))
            when[k] = min(when.get(k, r["harvest_at"]), r["harvest_at"])
    return {k: (w, *event(raw, k[0], k[1], w)) for k, w in sorted(when.items())}


# --- alignment ----------------------------------------------------------------

STOP = set(
    "the a an and or of to in is it its for on as at by be this that with from "
    "not are was if but so no it's into than then".split()
)
SPAN = re.compile(r"`([^`\n]{3,})`")


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_./-]{3,}", text.lower()) if w not in STOP}


def spans(text: str) -> set[str]:
    return {
        s.strip().lower()
        for s in SPAN.findall(text)
        if not re.fullmatch(r"[0-9a-f]{7,40}|#?\d+", s.strip())
    }


def harvests_of(comments: list, source: int, when: str) -> list:
    """The "Changed since filed" comments from WHEN on whose heading names SOURCE.

    The source is the heading's first ref; when none is (broker#73's heading
    names its epic first), any ref to it in the heading line will do.
    """
    csf = [
        c
        for c in comments
        if "changed since filed" in (c["body"] or "").split("\n")[0].lower()
        and c["created_at"] >= when
    ]

    def heading_refs(c):
        return re.findall(r"#(\d+)", c["body"].split("\n")[0])

    first = [c for c in csf if heading_refs(c)[:1] == [str(source)]]
    return first or [c for c in csf if str(source) in heading_refs(c)]


def align(raw: Path, jmin: float) -> None:
    labels = read_labels()
    for (repo, source), (when, kids, comments) in events(raw).items():
        paras = [p for c in comments for p in H.comment_paras(c, repo.lower())]
        targets = {
            int(r["target"])
            for r in labels
            if r["repo"] == repo and r["source"] == str(source)
        }
        for t in sorted(targets):
            harvest = harvests_of(issue(raw, repo, t)["comments"], source, when)
            best: dict = {}
            for c in harvest:
                for h, _ in E.paragraphs(c["body"].splitlines()):
                    hw = words(h)
                    if len(hw) < 4:
                        continue
                    for p in paras:
                        pw = words(p.text)
                        j = len(hw & pw) / (len(hw | pw) or 1)
                        k = (p.comment_id, p.k)
                        if j >= jmin and j > best.get(k, (0,))[0]:
                            best[k] = (j, p, h)
            for (cid, k), (j, p, h) in sorted(best.items()):
                kind = "named" if E.key(None, t, repo.lower()) in p.named else "unnamed"
                print(f"{repo}\t{source}\t{t}\t{cid}\t{k}\t{kind}\t{j:.2f}")
                print(f"    SRC {p.text[:160]!r}\n    HRV {h[:160]!r}")


# --- the sets -----------------------------------------------------------------


def _cases(raw: Path, only: set | None, full: bool) -> list[dict]:
    labels = read_labels()
    pos = collections.defaultdict(set)
    for r in labels:
        if r["verdict"] == "genuine":
            pos[(r["repo"], int(r["source"]), int(r["comment"]), int(r["k"]))].add(
                int(r["target"])
            )
    unnamed = {
        (r["repo"], int(r["source"]), int(r["comment"]), int(r["k"]))
        for r in labels
        if r["verdict"] == "genuine" and r["kind"] == "unnamed"
    }
    out = []
    for (repo, source), (when, kids, comments) in events(raw).items():
        if only is not None and (repo, source) not in only:
            continue
        for c in comments:
            for p in H.comment_paras(c, repo.lower()):
                k = (repo, source, p.comment_id, p.k)
                if not full and k not in unnamed:
                    continue
                for ch in kids:
                    if full and ch.key in p.named:
                        continue
                    state, questions = H.build_case(
                        p.text,
                        repo,
                        source,
                        {"number": ch.number, "title": ch.title, "body": ch.body},
                    )
                    out.append(
                        {
                            "id": f"{repo}|{source}|{p.comment_id}:{p.k}|{ch.number}",
                            "state": state,
                            "questions": questions,
                            "expected": {"bears_on": ch.number in pos[k]},
                            "source": p.url,
                        }
                    )
    return out


def write(cases: list[dict], out: Path) -> None:
    with open(out, "w") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(
        f"{len(cases)} cases, {sum(c['expected']['bears_on'] for c in cases)} positive",
        file=sys.stderr,
    )


# --- metrics ------------------------------------------------------------------


def request_key(state, questions) -> str:
    return _load_eval().request_key("jev-1.13.0", state, questions)


@functools.lru_cache(maxsize=None)
def _load_eval():
    """The evaluator, loaded once: its request_key is the cache's key."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "typesafe_eval", ROOT / "scripts" / "typesafe-eval.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["typesafe_eval"] = mod
    spec.loader.exec_module(mod)
    return mod


def replies(cache: Path) -> dict:
    """Key -> every reply, in the cache's order (the evaluator keeps the last)."""
    out = collections.defaultdict(list)
    for line in cache.read_text().splitlines():
        if line.strip():
            e = json.loads(line)
            out[e["key"]].append(e["reply"]["answers"]["bears_on"]["noul"])
    return out


def baseline(state: dict) -> tuple:
    p, ch = state["paragraph"], state["child"]
    other = ch["title"] + "\n" + ch["body"]
    return (len(spans(p) & spans(other)), len(words(p) & words(other)))


def rank(set_path: Path, cache: Path) -> dict:
    """The target's rank among its paragraph's open children (ties count against it)."""
    by_para = collections.defaultdict(list)
    for line in set_path.read_text().splitlines():
        c = json.loads(line)
        by_para[c["id"].rsplit("|", 1)[0]].append(c)
    ans = replies(cache)

    def keyed(c):
        return ans[request_key(c["state"], c["questions"])]

    result = {
        "pairs": 0,
        "baseline": [0, 0],
        "noul_last": [0, 0],
        "noul_mean": [0, 0],
        "random": [0.0, 0.0],
        "paired": [0, 0, 0],
    }
    for cases in by_para.values():
        for t in [c for c in cases if c["expected"]["bears_on"]]:
            negs = [c for c in cases if not c["expected"]["bears_on"]]
            result["pairs"] += 1
            ranks = {}
            for name, score in (
                ("baseline", lambda c: baseline(c["state"])),
                ("noul_last", lambda c: keyed(c)[-1]),
                ("noul_mean", lambda c: sum(keyed(c)) / len(keyed(c))),
            ):
                r = 1 + sum(score(n) >= score(t) for n in negs)
                ranks[name] = r
                result[name][0] += r <= 1
                result[name][1] += r <= 3
            result["random"][0] += 1 / (len(negs) + 1)
            result["random"][1] += min(1.0, 3 / (len(negs) + 1))
            b, n = ranks["baseline"], ranks["noul_mean"]
            result["paired"][0 if n < b else 1 if n > b else 2] += 1
    better, worse, _ = result["paired"]
    m = better + worse
    result["sign_p"] = round(
        sum(math.comb(m, k) for k in range(better, m + 1)) / 2**m, 4
    )
    result["random"] = [round(x, 1) for x in result["random"]]
    moves = sorted(round(max(v) - min(v), 6) for v in ans.values() if len(v) > 1)
    result["repeats"] = {
        "repeated": len(moves),
        "max_move": moves[-1] if moves else None,
        "p90_move": moves[int(0.9 * len(moves))] if moves else None,
    }
    return result


def write_scores(set_path: Path, cache: Path, out: Path) -> None:
    """The whole-thread run as text-free rows: event, paragraph, child, Noul (last reply), label."""
    ans = replies(cache)
    lines = ["# event\tparagraph\tchild\tnoul\tlabel\n"]
    for line in set_path.read_text().splitlines():
        c = json.loads(line)
        repo, source, para, child = c["id"].split("|")
        noul = ans[request_key(c["state"], c["questions"])][-1]
        label = int(c["expected"]["bears_on"])
        lines.append(f"{repo}#{source}\t{para}\t{child}\t{noul}\t{label}\n")
    out.write_text("".join(lines))


def scores(path: Path) -> dict:
    """event -> (residue rows, Noul rank of each unnamed positive, how many in the top 20)."""
    rows = collections.defaultdict(list)
    for line in path.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        event_, _pid, _child, noul, label = line.split("\t")
        rows[event_].append((float(noul), label == "1"))
    out = {}
    for ev_, rs in rows.items():
        negs = [p for p, lab in rs if not lab]
        ranks = sorted(1 + sum(n >= p for n in negs) for p, lab in rs if lab)
        top = sorted(rs, key=lambda r: -r[0])[:20]
        out[ev_] = (len(rs), ranks, sum(lab for _, lab in top))
    return out


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    cmd, args = argv[0], argv[1:]
    if cmd == "fetch" and len(args) == 1:
        fetch(Path(args[0]))
    elif cmd == "align" and len(args) in (1, 2):
        align(Path(args[0]), float(args[1]) if len(args) == 2 else 0.2)
    elif cmd == "build" and len(args) == 2:
        write(_cases(Path(args[0]), None, full=False), Path(args[1]))
    elif cmd == "threads" and len(args) == 2:
        write(_cases(Path(args[0]), set(THREAD_EVENTS), full=True), Path(args[1]))
    elif cmd == "rank" and len(args) == 2:
        print(json.dumps(rank(Path(args[0]), Path(args[1])), indent=1))
    elif cmd == "score" and len(args) == 3:
        write_scores(Path(args[0]), Path(args[1]), Path(args[2]))
    elif cmd == "scores" and len(args) == 1:
        for ev_, (n, ranks, top) in scores(Path(args[0])).items():
            print(
                f"{ev_}\tresidue {n}\tunnamed positives ranked {ranks}\ttop-20 holds {top}"
            )
    else:
        print(__doc__.strip(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    sys.exit(main(sys.argv[1:]))
