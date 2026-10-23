#!/usr/bin/env python3
"""Mine, select and build #442's labelled set. Kept beside the set (#463's note).

usage: python3 -I -B mine.py groups CLONES GROUPS.jsonl
       python3 -I -B mine.py collect CLONES GROUPS.jsonl RAW.jsonl
       python3 -I -B mine.py select CLONES RAW.jsonl INPUTS.jsonl [LABELS.tsv]
       python3 -I -B mine.py build INPUTS.jsonl LABELS.tsv SET.jsonl
       python3 -I -B mine.py delegated CLONES INPUTS.jsonl LABELS.tsv HELD.tsv CACHE.jsonl

groups   finds every commit that added a `tighten` entry to a repo's
         `.skills/context-loss-ok`, and for each entry the base line it names:
         the nearest first-parent ancestor (up to ANCESTORS back) where a
         tracked `*.md` holds a line containing the entry's CONTENT. One group
         per (repo, commit, file), with the oldest base any of its entries
         needed, so every entry's line is lost against it.
collect  runs the shipped `prove-no-loss.sh --claims --candidates` once per
         group, in a detached worktree of the group's commit, with `--file`
         and `--base` from the group. It keeps the records for the lines that
         group's own entries warranted, so each base line is judged against
         the rewrite that warranted it, once. Each record gains `source`.
select   picks the cases. Slice H is every sentence the pass would send that
         has history evidence: a word 4-gram it had that its successor lacked
         came back in a later descendant commit of the file, or a review fix
         (a subject naming a CR or a restore, among the next FIX_WINDOW
         descendant commits touching the file) edited a line of its
         successor. Slice R is a seeded RANDOM_N of the rest, the rate a run
         sees. INPUTS keeps every record of each section that holds a picked
         sentence, so `to_rows` rebuilds those sentences and their ordinals
         exactly; each record gains `slice` ({id: H|R} for the sentences on
         it). Given LABELS.tsv, it draws nothing and keeps the ids labelled
         there with their slices: a slice grows by appending ids, never by
         re-sampling (#441's note). The committed slices were drawn before
         the successor fallback scored words rather than atoms, which made 3
         more sentences askable, so a fresh draw would not reproduce them.
build    writes the evaluator's set through the shipped code: `to_rows`, then
         `build_case`, one case per labelled id. LABELS.tsv is
         `id<TAB>dropped<TAB>restored<TAB>slice<TAB>note`, `y` or `n`, with `#`
         comments; `restored` says a later review put the sentence's content
         back, and is evidence, not the label.
delegated  #470's measurement, printed as JSON. For each labelled case it
         follows every pointer in the successor to its doc at the curation
         commit: a Markdown link, or a backticked `*.md` path, read against
         the successor's directory and then the repo root. It applies the
         pass's `kept` test there twice, to the whole doc and to the anchored
         section when the link has an anchor (a `§"Heading"` is read as
         none). At the default threshold it reports the flags and catches
         with each, and the ceiling a perfect "held at the destination"
         judgment reaches, from HELD.tsv:
         `id<TAB>held<TAB>where<TAB>how<TAB>note`, one row per positive.

A case id is `<repo>:<commit>:<file>:<line>#<k>`, the k-th sentence the pass
builds that starts on that base line. The clones are public repos only; the
fixture README's step 1 re-checks that at commit time. Stdlib only.
"""

from __future__ import annotations

import importlib.util
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SCRIPTS = ROOT / "skills" / "curating-context" / "scripts"
PROVE = SCRIPTS / "prove-no-loss.sh"
EVAL = ROOT / "scripts" / "typesafe-eval.py"
sys.path.insert(0, str(SCRIPTS))
import _tightened_rules as tr  # noqa: E402

# name -> (owner/repo, the clone's HEAD). Mined 2026-10-22.
REPOS = {
    "address-validator": ("CannObserv/address-validator", "16ff211fc3d8"),
    "archiver": ("CannObserv/archiver", "5252b265d098"),
    "broker": ("CannObserv/broker", "f4a2518af585"),
    "notifier": ("CannObserv/notifier", "28915857665f"),
    "power-map": ("CannObserv/power-map", "e20e9c37fdb8"),
    "processor": ("CannObserv/processor", "57fc8a341153"),
    "replicator": ("CannObserv/replicator", "d0107d0f6f7d"),
    "skills": ("gregoryfoster/skills", "64626e8ac835"),
    "status": ("CannObserv/status", "f9d8ef5977b0"),
    "usa-wa": ("CannObserv/usa-wa", "0b5863281af2"),
    "watcher": ("CannObserv/watcher", "1a0b69778ba8"),
    "wslcb-licensing-tracker": ("CannObserv/wslcb-licensing-tracker", "c9937c8ad57f"),
}

SEED = 442
RANDOM_N = 150
ANCESTORS = 40
FIX_WINDOW = 15
GREP_CHUNK = 400
ACK = ".skills/context-loss-ok"
WARRANTS = {
    "retarget",
    "rename",
    "duplicate",
    "disproven",
    "default",
    "tighten",
    "index",
}
FIX = re.compile(r"\bCR\b|restor|put back|re-add|again|keeps?\b", re.I)
WORD = re.compile(r"[a-z0-9][a-z0-9'_-]*")


def _env() -> dict:
    # A hook's GIT_DIR would make every clone answer as this repo (#189).
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=_env()
    )
    if check and r.returncode:
        sys.exit(f"git {' '.join(args)} in {repo}: {r.stderr.strip()}")
    return r.stdout if r.returncode == 0 else ""


def _check_heads(clones: Path) -> None:
    for name, (_slug, rev) in REPOS.items():
        head = _git(clones / name, "rev-parse", "HEAD").strip()
        if not head.startswith(rev):
            sys.exit(f"{clones / name} is at {head[:12]}, not {rev}")


def _tighten(line: str):
    """(scope, content) of a `tighten` entry, as prove-no-loss.sh parses one."""
    if line.lstrip().startswith("#"):
        return None
    head, sep, tail = line.partition("::")
    scope, warrant, content = None, head.strip(), tail.strip()
    if sep and warrant not in WARRANTS and "::" in tail:
        second, _, rest = tail.partition("::")
        scope, warrant, content = warrant, second.strip(), rest.strip()
    return (scope, content) if sep and warrant == "tighten" and content else None


def _grep_first(repo: Path, content: str, base: str, files: list[str]) -> str:
    """The first line at BASE in FILES holding CONTENT, or "".

    In chunks of GREP_CHUNK paths, so a long list neither overflows argv nor
    is cut short, and git grep's own order across chunks is kept. Exit 1 is no
    match; anything above it is an error, not an empty result.
    """
    for i in range(0, len(files), GREP_CHUNK):
        args = ["grep", "-F", "-n", "-e", content, base, "--"]
        r = subprocess.run(
            ["git", "-C", str(repo), *args, *files[i : i + GREP_CHUNK]],
            capture_output=True,
            text=True,
            env=_env(),
        )
        if r.returncode > 1:
            sys.exit(f"git grep at {base} in {repo}: {r.stderr.strip()}")
        if r.returncode == 0:
            return r.stdout.splitlines()[0]
    return ""


def groups(clones: Path, out: Path) -> None:
    _check_heads(clones)
    found = {}
    for name in REPOS:
        repo = clones / name
        for commit in reversed(_git(repo, "log", "--format=%H", "--", ACK).split()):
            diff = _git(repo, "show", "--format=", commit, "--", ACK)
            added = [
                _tighten(x[1:])
                for x in diff.splitlines()
                if x.startswith("+") and not x.startswith("+++")
            ]
            added = [a for a in added if a]
            if not added:
                continue
            mds = [
                f
                for f in _git(repo, "ls-tree", "-r", "--name-only", commit + "^").split(
                    "\n"
                )
                if f.endswith(".md")
            ]
            ancestors = _git(
                repo, "rev-list", "--first-parent", "-n", str(ANCESTORS), commit + "^"
            ).split()
            for scope, content in added:
                files = [f for f in mds if scope is None or scope in f]
                for depth, base in enumerate(ancestors):
                    hit = _grep_first(repo, content, base, files)
                    if hit:
                        _rev, path, _line, text = hit.split(":", 3)
                        g = found.setdefault(
                            (name, commit, path),
                            {
                                "repo": name,
                                "commit": commit,
                                "file": path,
                                "base": base,
                                "depth": depth,
                                "lines": [],
                            },
                        )
                        if depth > g["depth"]:
                            g["base"], g["depth"] = base, depth
                        g["lines"].append(text.strip())
                        break
    out.write_text("".join(json.dumps(g) + "\n" for g in found.values()))
    print(
        f"{len(found)} groups, {sum(len(g['lines']) for g in found.values())} lines",
        file=sys.stderr,
    )


def collect(clones: Path, groups_path: Path, raw: Path) -> None:
    _check_heads(clones)
    recs = []
    for g in (json.loads(x) for x in groups_path.read_text().splitlines()):
        repo = clones / g["repo"]
        own = set(g["lines"])
        with tempfile.TemporaryDirectory(dir=clones) as tmp:
            wt = Path(tmp) / "wt"
            _git(repo, "worktree", "add", "-q", "--detach", str(wt), g["commit"])
            try:
                cand = Path(tmp) / "candidates.jsonl"
                r = subprocess.run(
                    [
                        "bash",
                        str(PROVE),
                        "--base",
                        g["base"],
                        "--file",
                        g["file"],
                        "--claims",
                        "--candidates",
                        str(cand),
                    ],
                    cwd=wt,
                    capture_output=True,
                    text=True,
                    env=_env(),
                )
                if r.returncode not in (0, 3):
                    sys.exit(
                        f"prove-no-loss.sh exited {r.returncode} on "
                        f"{g['repo']}@{g['commit'][:10]}: {r.stderr}"
                    )
                for x in cand.read_text(encoding="utf-8").splitlines():
                    rec = json.loads(x)
                    if rec["text"] in own:
                        rec["source"] = {
                            "repo": g["repo"],
                            "commit": g["commit"],
                            "base": g["base"],
                        }
                        recs.append(rec)
            finally:
                _git(repo, "worktree", "remove", "--force", str(wt))
    raw.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
    print(f"{len(recs)} records", file=sys.stderr)


def _by_commit(recs: list[dict]) -> dict:
    out = defaultdict(list)
    for r in recs:
        out[(r["source"]["repo"], r["source"]["commit"])].append(r)
    return out


def rows(recs: list[dict]) -> list[tuple[str, tr.Row, tuple]]:
    """(case id, row, its section's key) for every sentence `to_rows` builds."""
    out = []
    for (repo, commit), group in _by_commit(recs).items():
        # One section at a time, in the order to_rows meets them, so each
        # row knows its section: a nested heading's lines fall in its
        # parent's span too, and a span test picks the wrong one.
        sections: dict = {}
        for r in group:
            sections.setdefault((r["file"], r["section_line"]), []).append(r)
        seen: dict = {}
        for (file, start), part in sections.items():
            for row in tr.to_rows(part, []):
                k = seen[(row.file, row.line)] = seen.get((row.file, row.line), 0) + 1
                cid = f"{repo}:{commit[:7]}:{row.file}:{row.line}#{k}"
                out.append((cid, row, (repo, commit, file, start)))
    return out


def _grams(text: str, n: int = 4) -> set:
    w = WORD.findall(text.lower())
    return {" ".join(w[i : i + n]) for i in range(len(w) - n + 1)}


def _evidence(clones: Path, repo: str, commit: str, row: tr.Row, cache: dict) -> bool:
    path = clones / repo
    key = (repo, commit, row.file)
    if key not in cache:
        cache[key] = _git(
            path,
            "rev-list",
            "--reverse",
            "--ancestry-path",
            f"{commit}..HEAD",
            "--",
            row.file,
        ).split()
    later = cache[key]
    after = row.successor["text"]
    dropped = _grams(row.sentence) - _grams(after)
    for c in later:
        if dropped & (
            _grams(_git(path, "show", f"{c}:{row.file}", check=False)) - _grams(after)
        ):
            return True
    head = row.successor.get("heading")
    for c in later[:FIX_WINDOW]:
        if not FIX.search(_git(path, "log", "-1", "--format=%s", c)):
            continue
        diff = _git(path, "show", "--format=", "-U0", c, "--", row.file)
        removed = [
            x[1:].strip()
            for x in diff.splitlines()
            if x.startswith("-") and not x.startswith("---")
        ]
        if any(x and x in after for x in removed) or (head and head in diff):
            return True
    return False


def select(clones: Path, raw: Path, inputs: Path, labels: Path | None = None) -> None:
    _check_heads(clones)
    recs = [json.loads(x) for x in raw.read_text().splitlines()]
    built = [(cid, row, sec) for cid, row, sec in rows(recs) if not row.status]
    if labels is not None:
        picked = {cid: lab["slice"] for cid, lab in read_labels(labels).items()}
        missing = set(picked) - {cid for cid, _, _ in built}
        if missing:
            sys.exit(f"{len(missing)} labelled ids aren't sent: {sorted(missing)[:3]}")
    else:
        cache: dict = {}
        hist = [x for x in built if _evidence(clones, *x[2][:2], x[1], cache)]
        held = {x[0] for x in hist}
        rest = sorted((x for x in built if x[0] not in held), key=lambda x: x[0])
        picked = {cid: "H" for cid, _, _ in hist}
        sample = random.Random(SEED).sample(rest, RANDOM_N)
        picked.update({cid: "R" for cid, _, _ in sample})
    # The records on a picked sentence's own lines, and no others: a sentence
    # is built when a record touches it, and every sentence starting on a
    # kept line is touched by that line's record, so each id's ordinal comes
    # back exactly. The rest of a section's records would only repeat its
    # text (they took this file from 2.9 MB to 6 MB).
    keep, by_line = set(), defaultdict(dict)
    for cid, row, (repo, commit, file, start) in built:
        if cid in picked:
            keep |= {(repo, commit, file, n) for n in range(row.line, row.end_line + 1)}
            by_line[(repo, commit, file, row.line)][cid] = picked[cid]
    out = []
    for r in recs:
        key = (r["source"]["repo"], r["source"]["commit"], r["file"], r["line"])
        if key in keep:
            r["slice"] = by_line.get(key, {})
            out.append(r)
    inputs.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
    parts = list(picked.values())
    print(
        f"H {parts.count('H')}, R {parts.count('R')}; {len(out)} records",
        file=sys.stderr,
    )


def read_labels(path: Path) -> dict[str, dict]:
    labels = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cid, dropped, restored, part, note = line.split("\t", 4)
        labels[cid] = {
            "dropped": dropped == "y",
            "restored": restored == "y",
            "slice": part,
            "note": note,
        }
    return labels


def cases(inputs: list[dict], labels: dict[str, dict]) -> list[dict]:
    out = []
    for cid, row, _sec in rows(inputs):
        if cid not in labels:
            continue
        state, questions = tr.build_case(
            row.sentence, row.heading, row.successor["text"]
        )
        repo, commit = cid.split(":", 2)[:2]
        out.append(
            {
                "id": cid,
                "state": state,
                "questions": questions,
                "expected": {"dropped": labels[cid]["dropped"]},
                "source": f"{REPOS[repo][0]}@{commit} ({labels[cid]['slice']})",
            }
        )
    missing = set(labels) - {c["id"] for c in out}
    if missing:
        sys.exit(f"{len(missing)} labelled ids build no case: {sorted(missing)[:3]}")
    return out


def build(inputs: Path, labels: Path, out: Path) -> None:
    recs = [json.loads(x) for x in inputs.read_text().splitlines()]
    built = cases(recs, read_labels(labels))
    out.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in built))
    print(f"{len(built)} cases", file=sys.stderr)


# --- delegated (#470) --------------------------------------------------------

INLINE = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
REFDEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)", re.M)
TICKED = re.compile(r"`((?:\.{1,2}/|[\w.-]+/)*[\w.-]+\.md)(#[\w-]+)?`")
URL = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
DELEGATED = re.compile(r"(delegated|moved)\b")


def read_held(path: Path) -> dict[str, dict]:
    held = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cid, flag, where, how, note = line.split("\t", 4)
        held[cid] = {"held": flag == "y", "where": where, "how": how, "note": note}
    return held


def probabilities(inputs: list[dict], labels: dict, cache: Path) -> dict[str, float]:
    """Each case's committed `dropped` p, keyed as typesafe-eval.py keys its cache."""
    spec = importlib.util.spec_from_file_location("typesafe_eval", EVAL)
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    replies = {}
    for line in cache.read_text().splitlines():
        row = json.loads(line)
        replies[row["key"]] = row["reply"]["answers"]["dropped"]["noul"]
    model = tr._typesafe.MODEL
    return {
        c["id"]: replies[ev.request_key(model, c["state"], c["questions"])]
        for c in cases(inputs, labels)
    }


def pointers(text: str) -> list[str]:
    """Every target the text points to: Markdown links, then backticked `.md` paths."""
    found = INLINE.findall(text) + REFDEF.findall(text)
    return found + [path + (anchor or "") for path, anchor in TICKED.findall(text)]


def _slug(heading: str) -> str:
    h = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading.strip().lower())
    h = re.sub(r"`|\*|(?<!\w)_|_(?!\w)", "", h)
    return re.sub(r"[^\w\- ]", "", h).replace(" ", "-")


def anchored(text: str, anchor: str) -> str | None:
    """The section GitHub's slug ANCHOR names in TEXT, to the next heading at its level or above."""
    lines, heads, fence = text.splitlines(), [], None
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            fence = None if fence else line.lstrip()[:3]
        elif fence is None and (m := HEADING.match(line.strip())):
            heads.append((i, len(m.group(1)), _slug(m.group(2))))
    seen: dict = {}
    for i, level, slug in heads:
        n = seen[slug] = seen.get(slug, -1) + 1
        if (slug if n == 0 else f"{slug}-{n}") == anchor:
            end = next((j for j, lv, _ in heads if j > i and lv <= level), len(lines))
            return "\n".join(lines[i:end])
    return None


def step1(clones: Path, inputs: list[dict], labels: dict) -> dict[str, dict]:
    """{id: {doc, section}}: whether the sentence is `kept` at a doc its successor points to."""
    docs: dict = {}

    def show(repo: str, commit: str, path: str):
        if (repo, commit, path) not in docs:
            r = subprocess.run(
                ["git", "-C", str(clones / repo), "show", f"{commit}:{path}"],
                capture_output=True,
                text=True,
                env=_env(),
            )
            docs[(repo, commit, path)] = r.stdout if r.returncode == 0 else None
        return docs[(repo, commit, path)]

    out = {}
    for cid, row, (repo, commit, _file, _start) in rows(inputs):
        if cid not in labels:
            continue
        sentence, here = tr._flat(row.sentence), row.successor["file"]
        doc = section = False
        for target in pointers(row.successor["text"]):
            if URL.match(target):
                continue
            path, _, anchor = target.partition("#")
            # A link is relative to its file; a backticked path is often the repo's.
            tried = (
                [here]
                if not path
                else [
                    os.path.normpath(os.path.join(os.path.dirname(here), path)),
                    os.path.normpath(path.lstrip("/")),
                ]
            )
            text = next((t for t in (show(repo, commit, p) for p in tried) if t), None)
            if text is None:
                continue
            doc = doc or sentence in tr._flat(text)
            if anchor:
                part = anchored(text, anchor)
                section = section or (part is not None and sentence in tr._flat(part))
        out[cid] = {"doc": doc, "section": section}
    return out


def tally(labels: dict, p: dict, cleared, part: str | None = None) -> dict:
    """Flags, catches and false alarms at the default threshold, CLEARED ids never flagged."""
    ids = [c for c in labels if part is None or labels[c]["slice"] == part]
    flagged = [c for c in ids if p[c] >= tr.DEFAULT_THRESHOLD and c not in cleared]
    caught = sum(labels[c]["dropped"] for c in flagged)
    return {
        "flags": len(flagged),
        "catches": caught,
        "positives": sum(labels[c]["dropped"] for c in ids),
        "false_alarms": len(flagged) - caught,
    }


def cost(labels: dict, p: dict, cleared) -> dict:
    """What clearing CLEARED takes from the flags: its catches, the drops and
    review-restored rules among them, and every restored rule it clears at
    any p (the threshold can't bring those back)."""
    hidden = [
        c for c in cleared if labels[c]["dropped"] and p[c] >= tr.DEFAULT_THRESHOLD
    ]
    return {
        "cleared_catches": len(hidden),
        "hidden_drops": sorted(
            c for c in hidden if not DELEGATED.match(labels[c]["note"])
        ),
        "hidden_restored": sorted(c for c in hidden if labels[c]["restored"]),
        "restored_at_any_threshold": sorted(
            c for c in cleared if labels[c]["dropped"] and labels[c]["restored"]
        ),
    }


def ceiling(labels: dict, held: dict, p: dict) -> dict:
    """A perfect "held at the destination" judgment: every held positive cleared.

    Negatives have no held label, so the flags are an upper bound: a negative
    held at a destination would be cleared too, and that only helps.
    """
    cleared = {c for c, h in held.items() if h["held"]}
    return {
        "all": tally(labels, p, cleared),
        "R": tally(labels, p, cleared, "R"),
        **cost(labels, p, cleared),
    }


def delegated(clones: Path, inputs: Path, labels: Path, held: Path, cache: Path):
    _check_heads(clones)
    recs = [json.loads(x) for x in inputs.read_text().splitlines()]
    lab, kept = read_labels(labels), read_held(held)
    positives = {c for c in lab if lab[c]["dropped"]}
    if set(kept) != positives:
        sys.exit(f"{held} must hold exactly the {len(positives)} positives")
    p = probabilities(recs, lab, cache)
    found = step1(clones, recs, lab)
    report = {"threshold": tr.DEFAULT_THRESHOLD}
    for name, cleared in (
        ("shipped", set()),
        ("whole_doc", {c for c, f in found.items() if f["doc"]}),
        ("anchored_section", {c for c, f in found.items() if f["section"]}),
    ):
        report[name] = {
            "all": tally(lab, p, cleared),
            "R": tally(lab, p, cleared, "R"),
            "cleared": {
                "positives": sum(lab[c]["dropped"] for c in cleared),
                "negatives": sum(not lab[c]["dropped"] for c in cleared),
            },
            **cost(lab, p, cleared),
        }
    report["ceiling"] = ceiling(lab, kept, p)
    print(json.dumps(report, indent=1))


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "groups":
        groups(Path(argv[1]), Path(argv[2]))
    elif len(argv) == 4 and argv[0] == "collect":
        collect(Path(argv[1]), Path(argv[2]), Path(argv[3]))
    elif argv[:1] == ["select"] and len(argv) in (4, 5):
        select(*(Path(a) for a in argv[1:]))
    elif len(argv) == 4 and argv[0] == "build":
        build(Path(argv[1]), Path(argv[2]), Path(argv[3]))
    elif len(argv) == 6 and argv[0] == "delegated":
        delegated(*(Path(a) for a in argv[1:]))
    else:
        print(__doc__.strip(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
