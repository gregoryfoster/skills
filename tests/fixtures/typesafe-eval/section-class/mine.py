#!/usr/bin/env python3
"""Mine and build #435's labelled set. Kept beside the set (#463's note).

usage: python3 -I -B mine.py mine CLONES CASES.jsonl
       python3 -I -B mine.py build CLONES CASES.jsonl SET.jsonl PAIRS.jsonl LABELS.tsv
       python3 -I -B mine.py pairs PAIRS.jsonl CACHE.jsonl [MARGIN]
       python3 -I -B mine.py repeats CACHE.jsonl
       python3 -I -B mine.py v2 CLONES CASES.jsonl OUT.jsonl

mine   every ledger row (`.skills/context-metrics.jsonl`, at the commit REPOS
       names) that carries a class tag: `demote:` is B, `prune:` and
       `tighten:` are C, `delete:` is D. The row's curation commit is its
       `repo_commit`, or else the first ledger commit holding the row. Its base
       is the newest version of the row's `file`, at or before that commit,
       whose size is the previous row's `bytes` for that file. Each `##`
       section of the base is one case, labelled by the tags that name it or
       one of its `###` subsections (normalised text, exact before prefix), or
       `untagged`. `after_state` says whether the section is the same, edited
       or gone at the curation commit. Counts go to stderr, as posted on #435.
build  the evaluator's set, the pairs and the labels, from mine's output.
       Only policy files (AGENTS.md, CLAUDE.md, SKILL.md) are used. The set
       is every base section with one label: `untagged` and unchanged is A,
       and B, C and D as tagged. A section edited with no class tag, or
       tagged with two classes, has no single label and stays out of the set.
       PAIRS is every tagged section edited by its curation, before and after.
       The state is the section alone (V1), with the prototype's questions.
       No pass shipped, so no shipped builder exists.
pairs  #435's headline, from the cache alone, as JSON: in how many pairs a
       tightened section's P(C) fell and its P(A) rose, and a part-demoted
       section's P(B) fell. Each is [right, wrong, tied]; a move of MARGIN or
       less (default 0) counts as tied.
repeats  the noise floor for MARGIN: the cache keeps every reply, and some
       requests were sent twice. How often the choice changed, and how far the
       class probabilities moved (the 90th percentile and the largest).
v2     the issue's own design, for re-measuring: one request per base and
       per paired after-version, whose state is the whole file split at its
       `##` headings, with one Choice and one Noul per section. Not committed
       and not pinned.

The clones are public repos only; the fixture README's step 1 re-checks that
at commit time. Stdlib only.
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# name -> (owner/repo, the clone's HEAD). Mined 2026-10-23. Only repos that
# keep a ledger: processor and status don't.
REPOS = {
    "address-validator": ("CannObserv/address-validator", "9fcb4075ed49"),
    "archiver": ("CannObserv/archiver", "4129d366a75f"),
    "broker": ("CannObserv/broker", "068211dd62f7"),
    "notifier": ("CannObserv/notifier", "ab443708926e"),
    "power-map": ("CannObserv/power-map", "7f4e88d73bc3"),
    "replicator": ("CannObserv/replicator", "cb0d7b934c93"),
    "skills": ("gregoryfoster/skills", "ce85dee772cd"),
    "usa-wa": ("CannObserv/usa-wa", "b75bd451c91d"),
    "watcher": ("CannObserv/watcher", "223eac75a35a"),
    "wslcb-licensing-tracker": ("CannObserv/wslcb-licensing-tracker", "ad3f6ce0dfbe"),
}
LEDGER = ".skills/context-metrics.jsonl"
POLICY = ("AGENTS.md", "CLAUDE.md", "SKILL.md")
CLASS_TAGS = {"demote": "B", "prune": "C", "tighten": "C", "delete": "D"}
MODEL = "jev-1.13.0"

# The rubric's class definitions (references/keep-cut-rubric.md), condensed.
CRITERIA = {
    "A": "Keep inline. Only this project's authors know it, and an agent needs it on "
    "nearly every task: build, test or lint commands with their non-obvious flags, "
    "environment preconditions, a hard constraint with its reason, a project-specific "
    "gotcha that costs a session to rediscover, or the index of reference docs.",
    "B": "Demote to a reference doc. Correct and valuable, but needed only on some "
    "tasks: layout trees and module inventories, API or schema listings, style "
    "guides, deployment topology or infrastructure detail, an architecture overview, "
    "per-endpoint or per-table contracts, domain vocabulary beyond a few core terms.",
    "C": "Tighten in place. Content an agent needs on nearly every task, wrapped in "
    "prose it doesn't need: a rationale stated more than once, narrative history of "
    "how a rule arose, migration-relative phrasing ('no longer', 'now works "
    "differently'), bullet walls, or pressure language like 'CRITICAL: You MUST'.",
    "D": "Delete. It restates what a capable coding agent does anyway (generic "
    "virtues, 'think step by step', language-level facts, progress-update "
    "scaffolding, 'don't be lazy'), or duplicates another part of the file verbatim.",
}
DEFAULT_RULE = (
    "restate a default a capable coding agent already follows without being told "
    "(a generic virtue, 'think step by step', a language-level fact, "
    "progress-update scaffolding, a 'don't be lazy' exhortation), rather than "
    "stating something about this project?"
)
QUESTIONS = {
    "class": {
        "type": "choice",
        "instructions": "`text` is one `##` section of an agent policy file (an "
        "AGENTS.md or a SKILL.md), which a coding agent loads into context on every "
        "task in this repo. `tokens` is its size and `share` its fraction of the "
        "file. Which class does the section belong to?",
        "criteria": CRITERIA,
    },
    "default": {"type": "noul", "instructions": f"Does `text` {DEFAULT_RULE}"},
}
V2_CLASS = (
    "`sections` is an agent policy file (an AGENTS.md or a SKILL.md), split at its "
    "`##` headings, which a coding agent loads into context on every task in this "
    "repo. Which class does `sections[{i}]` belong to?"
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    ).stdout


def rows_of(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def class_tags(row: dict) -> list[str]:
    return [a for a in row.get("actions") or [] if a.split(":", 1)[0] in CLASS_TAGS]


def row_keys(rows: list[dict]) -> list[tuple]:
    """(ts, file, curates, n): n tells apart two same-day rows for one file."""
    seen, out = collections.Counter(), []
    for r in rows:
        k = (r.get("ts"), r.get("file"), bool(class_tags(r)))
        out.append((*k, seen[k]))
        seen[k] += 1
    return out


def sections(text: str) -> list[tuple[str, str, list[str]]]:
    """`##` sections outside fences: (heading, body with its heading line, `###` titles).

    A fence closes only on its opener's character, at least as long (CommonMark).
    """
    out, fence = [], None
    for line in text.splitlines(keepends=True):
        m = re.match(r" {0,3}(`{3,}|~{3,})", line)
        if m:
            run = m.group(1)
            if fence is None:
                fence = (run[0], len(run))
            elif run[0] == fence[0] and len(run) >= fence[1]:
                fence = None
                if out:
                    out[-1][1] += line
                continue
        if fence is None and re.match(r"## (?!#)", line):
            out.append([line[3:].strip(), line, []])
            continue
        if out:
            out[-1][1] += line
            if fence is None and re.match(r"### (?!#)", line):
                out[-1][2].append(line[4:].strip())
    return [tuple(s) for s in out]


def norm(s: str) -> str:
    s = re.sub(r"[`*_]", "", s.lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def match(target: str, secs) -> tuple[int | None, str]:
    """The section a tag's target names: exact heading, exact `###`, then prefixes."""
    t = norm(target)
    if not t:
        return None, "none"

    def prefix(a: str, b: str) -> bool:
        return a.startswith(b + " ") or b.startswith(a + " ")

    tests = (
        ("exact", lambda h, subs: norm(h) == t),
        ("sub-exact", lambda h, subs: any(norm(s) == t for s in subs)),
        ("prefix", lambda h, subs: prefix(t, norm(h))),
        ("sub-prefix", lambda h, subs: any(prefix(t, norm(s)) for s in subs)),
    )
    for how, test in tests:
        for i, (h, _, subs) in enumerate(secs):
            if test(h, subs):
                return i, how
    return None, "none"


def resolve_base(repo: Path, after: str, path: str, size) -> str | None:
    if not after or not size:
        return None
    for c in git(repo, "log", "--format=%H", after, "--", path).split():
        if git(repo, "cat-file", "-s", f"{c}:{path}").strip() == str(size):
            return c
    return None


def mine(clones: Path, out: Path) -> None:
    stats, cases = collections.Counter(), []
    for name, (_, pin) in REPOS.items():
        repo = clones / name
        final = rows_of(git(repo, "show", f"{pin}:{LEDGER}"))
        first_seen, first_tags = {}, {}
        for c in git(
            repo, "log", "--reverse", "--format=%H", pin, "--", LEDGER
        ).split():
            rows = rows_of(git(repo, "show", f"{c}:{LEDGER}"))
            for k, r in zip(row_keys(rows), rows):
                if k not in first_seen:
                    first_seen[k], first_tags[k] = c, set(class_tags(r))
        prev_by_file = {}
        for k, r in zip(row_keys(final), final):
            path = r.get("file")
            prev, prev_by_file[path] = prev_by_file.get(path), r
            tags = class_tags(r)
            if not tags:
                continue
            stats["curations"] += 1
            after = r.get("repo_commit") or first_seen.get(k)
            if after and not git(repo, "cat-file", "-t", after).strip():
                after = first_seen.get(k)
            base = resolve_base(repo, after, path, prev and prev.get("bytes"))
            if not base:
                stats["base_unresolved"] += 1
                continue
            policy = os.path.basename(path) in POLICY
            stats["policy_rows" if policy else "doc_rows"] += 1
            bsec = sections(git(repo, "show", f"{base}:{path}"))
            asec = {
                norm(h): b for h, b, _ in sections(git(repo, "show", f"{after}:{path}"))
            }

            def by_section(tag_list):
                got = collections.defaultdict(set)
                for a in tag_list:
                    kind, _, target = a.partition(":")
                    i, how = match(target, bsec)
                    if i is not None:
                        got[i].add(CLASS_TAGS[kind])
                return got

            for a in tags:
                stats[f"match_{match(a.partition(':')[2], bsec)[1]}"] += 1
            now = by_section(tags)
            if first_tags.get(k, set(tags)) != set(tags):
                stats["rows_amended"] += 1
                then = by_section(first_tags[k])
                stats["section_flips"] += sum(
                    then.get(i, set()) != now.get(i, set())
                    for i in set(then) | set(now)
                )
            for i, (h, body, _) in enumerate(bsec):
                label = "+".join(sorted(now[i])) if i in now else "untagged"
                ab = asec.get(norm(h))
                state = (
                    "gone"
                    if ab is None
                    else "same"
                    if ab.strip() == body.strip()
                    else "edited"
                )
                if policy:
                    stats[f"label_{label}_{state}"] += 1
                cases.append(
                    {
                        "repo": name,
                        "file": path,
                        "ts": r.get("ts"),
                        "base": base,
                        "after": after,
                        "heading": h,
                        "label": label,
                        "after_state": state,
                        "policy": policy,
                    }
                )
    out.write_text("".join(json.dumps(c) + "\n" for c in cases))
    for key in sorted(stats):
        print(f"{key}\t{stats[key]}", file=sys.stderr)


_shown: dict = {}


def show(clones: Path, repo: str, rev: str, path: str) -> str:
    k = (repo, rev, path)
    if k not in _shown:
        _shown[k] = git(clones / repo, "show", f"{rev}:{path}")
    return _shown[k]


def v1_state(text: str, heading: str, path: str) -> dict | None:
    secs = sections(text)
    total = sum(len(b.encode()) for _, b, _ in secs) or 1
    for h, body, _ in secs:
        if norm(h) == norm(heading):
            return {
                "file": os.path.basename(path),
                "heading": h,
                "text": body,
                "tokens": len(body.encode()) // 4,
                "share": round(len(body.encode()) / total, 3),
            }
    return None


def single_label(case: dict) -> str | None:
    if case["label"] == "untagged":
        return "A" if case["after_state"] == "same" else None
    return case["label"] if case["label"] in CRITERIA else None


def build(
    clones: Path, cases_path: Path, set_path: Path, pairs_path: Path, labels: Path
) -> None:
    cases = [json.loads(line) for line in cases_path.read_text().splitlines()]
    rows, pairs = [], []
    tsv = [
        "# id\tlabel\tafter_state\tsource\theading",
        "# label: the curation's tags (demote B; prune, tighten C; delete D); "
        "an untagged section its curation left unchanged is A.",
    ]
    for c in cases:
        if not c["policy"]:
            continue
        source = f"{c['repo']}:{c['file']}@{c['base'][:12]}"
        before = v1_state(
            show(clones, c["repo"], c["base"], c["file"]), c["heading"], c["file"]
        )
        label = single_label(c)
        if label:
            cid = f"S{len(rows) + 1:04d}"
            rows.append(
                {
                    "id": cid,
                    "state": before,
                    "questions": QUESTIONS,
                    "expected": {"class": label, "default": False},
                    "source": source,
                }
            )
            tsv.append(f"{cid}\t{label}\t{c['after_state']}\t{source}\t{c['heading']}")
        if c["label"] != "untagged" and c["after_state"] == "edited":
            after = v1_state(
                show(clones, c["repo"], c["after"], c["file"]), c["heading"], c["file"]
            )
            kinds = [
                k
                for k, s in (("tightened", "C"), ("part-demoted", "B"))
                if s in c["label"]
            ]
            pairs.append(
                {
                    "id": f"P{len(pairs) + 1:03d}",
                    "label": c["label"],
                    "kinds": kinds,
                    "source": f"{source}..{c['after'][:12]}",
                    "before": before,
                    "after": after,
                }
            )
    set_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    pairs_path.write_text("".join(json.dumps(p) + "\n" for p in pairs))
    labels.write_text("\n".join(tsv) + "\n")
    print(f"{len(rows)} cases, {len(pairs)} pairs", file=sys.stderr)


def read_labels(path: Path) -> dict[str, dict]:
    """id -> {label, after_state, source, heading}, from LABELS.tsv."""
    out = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            cid, label, state, source, heading = line.split("\t")
            out[cid] = {
                "label": label,
                "after_state": state,
                "source": source,
                "heading": heading,
            }
    return out


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
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_cache(path: Path) -> dict:
    """Key -> reply. A repeated key keeps its last reply, as typesafe-eval.py does."""
    return {e["key"]: e["reply"] for e in cache_entries(path)}


# A pair's expected direction: the class whose probability should move, and
# +1 when it should fall from before to after, -1 when it should rise.
PAIR_TESTS = {
    "tightened": {"C_falls": ("C", 1), "A_rises": ("A", -1)},
    "part-demoted": {"B_falls": ("B", 1)},
}


def pairs(pairs_path: Path, cache_path: Path, margin: float = 0.0) -> dict:
    """[right, wrong, tied] per test. A move of `margin` or less counts as tied."""
    cache = read_cache(cache_path)
    tally = {kind: {t: [0, 0, 0] for t in tests} for kind, tests in PAIR_TESTS.items()}
    for line in pairs_path.read_text().splitlines():
        p = json.loads(line)
        probs = [
            cache[request_key(p[s], QUESTIONS)]["answers"]["class"]["probabilities"]
            for s in ("before", "after")
        ]
        for kind in p["kinds"]:
            for test, (cls, sign) in PAIR_TESTS[kind].items():
                d = round(sign * (probs[0][cls] - probs[1][cls]), 6)
                tally[kind][test][0 if d > margin else 1 if d < -margin else 2] += 1
    return tally


def repeats(cache_path: Path) -> dict:
    """How far Jev's answer moved when the same request was sent twice."""
    by_key = collections.defaultdict(list)
    for e in cache_entries(cache_path):
        by_key[e["key"]].append(e["reply"]["answers"]["class"])
    again = [v for v in by_key.values() if len(v) > 1]
    # A request's move: the widest spread of any one class's probability.
    moves = sorted(
        round(
            max(
                max(a["probabilities"][c] for a in v)
                - min(a["probabilities"][c] for a in v)
                for c in CRITERIA
            ),
            6,
        )
        for v in again
    )
    return {
        "repeated": len(again),
        "choice_changed": sum(len({a["choice"] for a in v}) > 1 for v in again),
        "max_move": moves[-1] if moves else None,
        "p90_move": moves[int(0.9 * len(moves))] if moves else None,
    }


def v2(clones: Path, cases_path: Path, out: Path) -> None:
    cases = [json.loads(line) for line in cases_path.read_text().splitlines()]
    want = set()
    for c in cases:
        if c["policy"]:
            want.add((c["repo"], c["file"], c["base"]))
            if c["label"] != "untagged" and c["after_state"] == "edited":
                want.add((c["repo"], c["file"], c["after"]))
    with out.open("w") as fh:
        for repo, path, rev in sorted(want):
            secs = sections(show(clones, repo, rev, path))
            state = {
                "file": os.path.basename(path),
                "sections": [
                    {"heading": h, "text": b, "tokens": len(b.encode()) // 4}
                    for h, b, _ in secs
                ],
            }
            questions = {}
            for i in range(len(secs)):
                questions[f"class_{i}"] = {
                    "type": "choice",
                    "instructions": V2_CLASS.format(i=i),
                    "criteria": CRITERIA,
                }
                questions[f"default_{i}"] = {
                    "type": "noul",
                    "instructions": f"Does `sections[{i}].text` {DEFAULT_RULE}",
                }
            fh.write(
                json.dumps(
                    {
                        "id": f"{repo}:{path}@{rev[:12]}",
                        "state": state,
                        "questions": questions,
                    }
                )
                + "\n"
            )


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0 if len(argv) >= 2 else 1
    cmd, args = argv[1], [Path(a) for a in argv[2:]]
    if cmd == "mine" and len(args) == 2:
        mine(*args)
    elif cmd == "build" and len(args) == 5:
        build(*args)
    elif cmd == "pairs" and len(args) in (2, 3):
        margin = float(str(args[2])) if len(args) == 3 else 0.0
        print(json.dumps(pairs(args[0], args[1], margin)))
    elif cmd == "repeats" and len(args) == 1:
        print(json.dumps(repeats(*args)))
    elif cmd == "v2" and len(args) == 3:
        v2(*args)
    else:
        print(__doc__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
