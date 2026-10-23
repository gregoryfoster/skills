#!/usr/bin/env python3
"""Mine and build #447's labelled set. Kept beside the set (#463's note).

usage: python3 -I -B mine.py lines CLONES OUT.jsonl
       python3 -I -B mine.py rewrites CLONES OUT.jsonl
       python3 -I -B mine.py build CLONES LABELS.tsv SET.jsonl
       python3 -I -B mine.py pairs SET.jsonl CACHE.jsonl

lines     every non-blank line in each policy file's index section at the
          commit REPOS names, outside fences, with its pointers: Markdown
          links read from the file's directory (from the root for a leading
          `/`, as measure-context.sh's `norm` does), and backticked `*.md`
          paths read from the root. A target that is a Markdown file gains its
          headings and opening. The section is "Detail Docs", or the title
          SECTION names for a repo.
rewrites  every commit, up to the named one, that re-worded an index line and
          kept its first link target. `doc_in_commit` says the same commit
          changed that doc. The 17 accuracy fixes in LABELS.tsv were read from
          this list.
build     the evaluator's set. H cases: for each fix commit in LABELS.tsv, the
          line before it (HP, a yes) and after it (HN, a no), both against the
          doc at the fix's parent. R cases: every HEAD line whose first
          distinct target is a Markdown doc, in repo then line order, all no.
          The prototype's question and state; no shipped builder exists, since
          #447 shipped no pass.
pairs     #447's headline, from the cache alone, as JSON: in how many pairs
          the line before a fix scored above its own fix.

LABELS.tsv is `id<TAB>inaccurate<TAB>borderline<TAB>source<TAB>note`, `y` or
`n`, `-` where it doesn't apply, with `#` comments. `borderline` marks a HEAD
line whose doc has grown a topic the line doesn't name: not inaccurate under
the rubric, reported apart. The clones are public repos only; the fixture
README's step 1 re-checks that at commit time. Stdlib only.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# name -> (owner/repo, the clone's HEAD). Mined 2026-10-23.
REPOS = {
    "address-validator": ("CannObserv/address-validator", "120058b4b0ee"),
    "archiver": ("CannObserv/archiver", "4129d366a75f"),
    "broker": ("CannObserv/broker", "26269460e6de"),
    "notifier": ("CannObserv/notifier", "36f950d6fd06"),
    "power-map": ("CannObserv/power-map", "cba807236842"),
    "processor": ("CannObserv/processor", "a23970b9b3cc"),
    "replicator": ("CannObserv/replicator", "cb0d7b934c93"),
    "skills": ("gregoryfoster/skills", "ae1c15d6f8fc"),
    "status": ("CannObserv/status", "5cf187834e70"),
    "usa-wa": ("CannObserv/usa-wa", "b75bd451c91d"),
    "watcher": ("CannObserv/watcher", "1a0b69778ba8"),
    "wslcb-licensing-tracker": ("CannObserv/wslcb-licensing-tracker", "d5ac823469da"),
}
POLICY = "AGENTS.md"
# The index section's title, where it isn't "Detail Docs". No repo's history
# used another (CR 487), so both walks match it exactly.
SECTION = {"wslcb-licensing-tracker": "Reference"}

INLINE = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
TICKED = re.compile(r"`((?:\.{1,2}/|[\w.-]+/)*[\w.-]+\.md)(#[\w-]+)?`")
URL = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")

QUESTION = (
    "`index_line` is one line in the index of a repo's agent-instructions file. An "
    "agent reads it to decide whether to open the reference doc whose headings and "
    "opening paragraph are in `doc`. Does the line misdescribe that doc: does it "
    "claim a topic the doc doesn't cover, or leave out a major topic the doc covers, "
    "so that an agent looking for that topic wouldn't open this doc? Answer no when "
    "the line names the doc's purpose rather than listing its contents, abbreviates "
    "its headings, or leaves out minor sections. Answer no for a routing condition "
    "in the line ('read it before ...') or a link to another doc: only the line can "
    "carry those. A heading whose section only says its content moved elsewhere is "
    "not a topic the doc covers."
)


def git(clones: Path, repo: str, *args: str) -> str | None:
    r = subprocess.run(
        ["git", "-C", str(clones / repo), *args], capture_output=True, text=True
    )
    return r.stdout if r.returncode == 0 else None


def norm(d: str, t: str) -> str:
    """measure-context.sh's `norm`: from D, or from the root for a leading `/`."""
    combined = t.lstrip("/") if t.startswith("/") else (f"{d}/{t}" if d else t)
    out: list[str] = []
    for p in combined.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            out = out[:-1]
        else:
            out.append(p)
    return "/".join(out)


def fence(line: str, opener: str | None) -> tuple[str | None, bool]:
    """(the open fence after LINE, or None; whether LINE is a marker). Only a run of
    the opener's own character, at least as long, closes it (CR 480's rule)."""
    m = FENCE.match(line)
    if not m:
        return opener, False
    run = m.group(1)
    if opener is None:
        return run, True
    if run[0] == opener[0] and len(run) >= len(opener):
        return None, True
    return opener, False


def section(lines: list[str], repo: str) -> tuple[int, int] | None:
    """[start, end) of REPO's index section, to the next heading at its level or above."""
    title = SECTION.get(repo, "Detail Docs").lower()
    start = level = None
    for i, line in enumerate(lines):
        h = HEADING.match(line)
        if not h:
            continue
        if start is None and h.group(2).lower() == title:
            start, level = i + 1, len(h.group(1))
        elif start is not None and len(h.group(1)) <= level:
            return start, i
    return (start, len(lines)) if start is not None else None


def outline(text: str) -> dict:
    """The doc as the question sees it: `#`-`###` headings, and the opening paragraph."""
    heads, para, opening, opener = [], [], None, None
    for line in text.splitlines():
        opener, marker = fence(line, opener)
        if marker or opener:
            continue
        h = HEADING.match(line)
        if h:
            if opening is None and para:
                opening = " ".join(para)
            para = []
            if len(h.group(1)) <= 3:
                heads.append("#" * len(h.group(1)) + " " + h.group(2))
            continue
        if opening is None and line.strip() and not line.strip().startswith("<!--"):
            para.append(line.strip())
        elif opening is None and not line.strip() and para:
            opening = " ".join(para)
    opening = opening or " ".join(para)
    return {"headings": heads, "opening": opening[:700]}


# --- lines -------------------------------------------------------------------


def head_lines(clones: Path) -> list[dict]:
    rows = []
    for repo, (_slug, rev) in sorted(REPOS.items()):
        lines = git(clones, repo, "show", f"{rev}:{POLICY}").splitlines()
        start, end = section(lines, repo)
        opener = None
        for i in range(start, end):
            line = lines[i]
            opener, marker = fence(line, opener)
            if marker or opener or not line.strip():
                continue
            targets = []
            for t in INLINE.findall(line):
                if URL.match(t) or t.startswith("#"):
                    targets.append({"raw": t, "kind": "url"})
                    continue
                path = norm("", t.split("#")[0])
                targets.append({"raw": t, "kind": "link", "path": path})
            for p, a in TICKED.findall(line):
                targets.append({"raw": p + a, "kind": "ticked", "path": norm("", p)})
            for t in targets:
                if "path" in t and t["path"].endswith(".md"):
                    text = git(clones, repo, "show", f"{rev}:{t['path']}")
                    if text is not None:
                        t.update(outline(text))
            rows.append(
                {
                    "repo": repo,
                    "file": POLICY,
                    "line": i + 1,
                    "text": line.strip(),
                    "targets": targets,
                }
            )
    return rows


def first_doc(row: dict) -> dict | None:
    """The first distinct target that is a Markdown doc, or None."""
    seen = []
    for t in row["targets"]:
        if t.get("path") in seen:
            continue
        seen.append(t.get("path"))
        if "headings" in t:
            return t
    return None


# --- rewrites ----------------------------------------------------------------


def index_by_target(text: str, repo: str) -> dict[str, str]:
    """{first link target: line} for the index lines in TEXT, fences skipped as
    `head_lines` skips them."""
    lines = text.splitlines()
    span = section(lines, repo)
    if span is None:
        return {}
    out: dict[str, str] = {}
    opener = None
    for line in lines[span[0] : span[1]]:
        opener, marker = fence(line, opener)
        if marker or opener:
            continue
        m = INLINE.search(line)
        if m and not URL.match(m.group(1)):
            out.setdefault(m.group(1).split("#")[0].lstrip("./"), line.strip())
    return out


def rewrites(clones: Path) -> list[dict]:
    """Each commit against its first parent, as `build` reads it. Walking the log
    pairwise instead paired commits from parallel branches (power-map merges)."""
    rows = []
    for repo, (_slug, rev) in sorted(REPOS.items()):
        log = git(
            clones, repo, "log", "--no-merges", "--format=%H %cs", rev, "--", POLICY
        )
        for sha, date in [line.split() for line in (log or "").splitlines()][::-1]:
            text = git(clones, repo, "show", f"{sha}:{POLICY}")
            if text is None:
                continue
            cur = index_by_target(text, repo)
            prev = index_by_target(
                git(clones, repo, "show", f"{sha}^:{POLICY}") or "", repo
            )
            touched = set(
                (
                    git(clones, repo, "show", "--name-only", "--format=", sha) or ""
                ).split()
            )
            subject = (git(clones, repo, "log", "-1", "--format=%s", sha) or "").strip()
            for target, line in cur.items():
                if target in prev and prev[target] != line:
                    rows.append(
                        {
                            "repo": repo,
                            "sha": sha[:10],
                            "date": date,
                            "subject": subject,
                            "target": target,
                            "doc_in_commit": target in touched,
                            "before": prev[target],
                            "after": line,
                        }
                    )
    return rows


# --- build -------------------------------------------------------------------


def read_labels(path: Path) -> dict[str, dict]:
    out = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cid, inaccurate, borderline, source, note = line.split("\t")
        out[cid] = {
            "inaccurate": inaccurate == "y",
            "borderline": borderline == "y",
            "source": source,
            "note": note,
        }
    return out


def case(cid: str, line: str, text: str, label: bool, source: str) -> dict:
    return {
        "id": cid,
        "state": {"index_line": line, "doc": outline(text)},
        "questions": {"inaccurate": {"type": "noul", "instructions": QUESTION}},
        "expected": {"inaccurate": label},
        "source": source,
    }


def build(clones: Path, labels: dict[str, dict]) -> list[dict]:
    out = []
    for cid, lab in labels.items():
        if not cid.startswith("HP"):
            continue
        # source: "<repo>:<doc>@<fix sha>^", the doc as it stood before the fix.
        repo, rest = lab["source"].split(":", 1)
        doc, sha = rest.rstrip("^").split("@")
        before = index_by_target(git(clones, repo, "show", f"{sha}^:{POLICY}"), repo)
        after = index_by_target(git(clones, repo, "show", f"{sha}:{POLICY}"), repo)
        text = git(clones, repo, "show", f"{sha}^:{doc}")
        out.append(case(cid, before[doc], text, True, lab["source"]))
        hn = "HN" + cid[2:]
        out.append(case(hn, after[doc], text, labels[hn]["inaccurate"], lab["source"]))
    n = 0
    for row in head_lines(clones):
        target = first_doc(row)
        if target is None:
            continue
        n += 1
        cid = f"R{n:03d}"
        rev = REPOS[row["repo"]][1]
        text = git(clones, row["repo"], "show", f"{rev}:{target['path']}")
        source = f"{row['repo']}:{row['file']}:{row['line']}@{rev}"
        assert labels[cid]["source"] == source, (cid, source)
        out.append(case(cid, row["text"], text, labels[cid]["inaccurate"], source))
    return out


# --- pairs -------------------------------------------------------------------


def pairs(set_path: Path, cache_path: Path) -> dict:
    # By id: every H case was asked live. Only R cases share a request (7 HEAD
    # lines are an HN correction unchanged since), and they are cached as the HN.
    p = {}
    for line in cache_path.read_text().splitlines():
        row = json.loads(line)
        p[row["id"]] = row["reply"]["answers"]["inaccurate"]["noul"]
    out = []
    for line in set_path.read_text().splitlines():
        cid = json.loads(line)["id"]
        if cid.startswith("HP"):
            out.append((cid, p[cid], p["HN" + cid[2:]]))
    return {
        "pairs": len(out),
        "before_above": sum(a > b for _, a, b in out),
        "tied": sum(a == b for _, a, b in out),
    }


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[0] not in ("lines", "rewrites", "build", "pairs"):
        print(__doc__.strip(), file=sys.stderr)
        return 1
    cmd = argv[0]
    if cmd == "pairs":
        print(json.dumps(pairs(Path(argv[1]), Path(argv[2]))))
        return 0
    clones = Path(argv[1])
    if cmd == "lines":
        rows = head_lines(clones)
    elif cmd == "rewrites":
        rows = rewrites(clones)
    else:
        rows = build(clones, read_labels(Path(argv[2])))
    with open(argv[-1], "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
