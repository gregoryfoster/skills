#!/usr/bin/env python3
"""Mine, select and build #441's labelled set. Kept beside the set (#463's note).

usage: python3 -I -B mine.py collect CLONES RAW.jsonl
       python3 -I -B mine.py select RAW.jsonl INPUTS.jsonl
       python3 -I -B mine.py build INPUTS.jsonl LABELS.tsv SET.jsonl

collect  runs the shipped `check-counts.sh --candidates` over each repo in
         REPOS, checked out under CLONES/<name> at the commit REPOS names:
         its policy file (AGENTS.md, else CLAUDE.md) and every non-archival
         `docs/**/*.md`, as `is_archival()` reads the default list. Each record
         gains `repo` and `rev`. It refuses a clone at another commit.
select   keeps every policy-file candidate (slice P, prefiltered ones too, so
         the prefilters' recall is measured; the pass sends none of them,
         and P is why), then, of the docs candidates
         that survive the prefilters, every TALLY_SHAPED one (slice S, for
         positives) and a seeded RANDOM_N of the rest (slice R, for precision
         at the docs' own rate). S is a seeded SHAPED_N first, then the others
         in file order: S was first labelled at 300, and widening it this way
         kept those ids. Each record gains `id`. The committed slices were
         drawn before CR 459 added the `time` mask, so re-running select
         now draws 7 fewer docs survivors; `build` reads inputs.jsonl and
         is unaffected.
build    writes the evaluator's set through the shipped code: one tally case
         per record the pass would send, so none from a policy file and none
         prefiltered. LABELS.tsv is `id<TAB>tally`, `y` or `n`, with `#`
         comments.

The clones are public repos only; the fixture README's step 1 re-checks that
at commit time. Stdlib only.
"""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SCRIPTS = ROOT / "skills" / "curating-context" / "scripts"
CHECK_COUNTS = SCRIPTS / "check-counts.sh"
sys.path.insert(0, str(SCRIPTS))
import _bare_digit_counts as bdc  # noqa: E402
import _stale_issue_prose as sip  # noqa: E402

# name -> (owner/repo, commit). Mined 2026-10-21.
REPOS = {
    "skills": ("gregoryfoster/skills", "b8c54db8"),
    "address-validator": ("CannObserv/address-validator", "5192c2b5da2d"),
    "archiver": ("CannObserv/archiver", "aa89e842b472"),
    "broker": ("CannObserv/broker", "213dbc9e6930"),
    "notifier": ("CannObserv/notifier", "28915857665f"),
    "power-map": ("CannObserv/power-map", "412bf1ca3489"),
    "processor": ("CannObserv/processor", "359e102cdbd9"),
    "replicator": ("CannObserv/replicator", "d0107d0f6f7d"),
    "status": ("CannObserv/status", "16c1782b7304"),
    "usa-wa": ("CannObserv/usa-wa", "cb9886d4cd5b"),
    "watcher": ("CannObserv/watcher", "1a0b69778ba8"),
    "wslcb-licensing-tracker": ("CannObserv/wslcb-licensing-tracker", "4772f8fd5be2"),
}

SEED = 441
SHAPED_N = 300
RANDOM_N = 100

# A number, then up to two words, then a plural that isn't a unit.
TALLY_SHAPED = re.compile(r"\b\d[\d,]*\+?\s+(?:[a-z][\w-]*\s+){0,2}?([a-z][\w-]*s)\b")
UNITS = re.compile(
    r"s|ms|secs?|seconds?|mins?|minutes?|h|hours?|days?|weeks?|months?|years?"
    r"|chars?|characters?|bytes?|tokens?|px|rem|em|times"
)


def _env() -> dict:
    # A hook's GIT_DIR would make every clone answer as this repo (#189).
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=_env(),
    ).stdout.strip()


def _files(repo: Path) -> list[str]:
    policy = next((f for f in ("AGENTS.md", "CLAUDE.md") if (repo / f).is_file()), None)
    docs = sorted(
        p.relative_to(repo).as_posix()
        for p in (repo / "docs").rglob("*.md")
        if p.is_file()
    )
    names = sip.archival_names({})
    live = [d for d in docs if not sip.is_archival(d, repo, names)]
    return ([policy] if policy else []) + live


def collect(clones: Path, raw: Path) -> None:
    out = []
    for name, (_slug, rev) in REPOS.items():
        repo = clones / name
        head = _git(repo, "rev-parse", "HEAD")
        if not head.startswith(rev):
            sys.exit(f"{repo} is at {head[:12]}, not {rev}")
        for f in _files(repo):
            tmp = clones / ".candidates.jsonl"
            r = subprocess.run(
                ["bash", str(CHECK_COUNTS), "--file", f, "--candidates", str(tmp)],
                cwd=repo,
                capture_output=True,
                text=True,
                env=_env(),
            )
            if r.returncode not in (0, 3):
                sys.exit(
                    f"check-counts.sh exited {r.returncode} on {name}/{f}: {r.stderr}"
                )
            for line in tmp.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                out.append({"repo": name, "rev": rev, **rec})
    raw.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
    print(f"{len(out)} candidates", file=sys.stderr)


def _shaped(clause: str) -> bool:
    text = bdc._mask(clause, bdc._sentences._code_spans(clause))
    m = TALLY_SHAPED.search(text)
    return bool(m) and not UNITS.fullmatch(m.group(1))


def select(raw: Path, inputs: Path) -> None:
    recs = [json.loads(line) for line in raw.read_text().splitlines()]
    policy = [r for r in recs if "/" not in r["file"]]
    docs = [r for r in recs if "/" in r["file"] and bdc.prefilter(r["clause"])[0]]
    shaped = [r for r in docs if _shaped(r["clause"])]
    rest = [r for r in docs if not _shaped(r["clause"])]
    rng = random.Random(SEED)
    sample = rng.sample(shaped, min(SHAPED_N, len(shaped)))
    picked = [("P", policy), ("S", sample)]
    picked.append(("R", rng.sample(rest, min(RANDOM_N, len(rest)))))
    # Then every other shaped one, in file order, so the first labels keep
    # their ids: positives are the expensive part (#438's note).
    seen = {id(r) for r in sample}
    extra = [r for r in shaped if id(r) not in seen]
    out = []
    for letter, part in picked:
        for i, r in enumerate(part):
            out.append({"id": f"{letter}{i:03d}", **r})
    for i, r in enumerate(extra, len(sample)):
        out.append({"id": f"S{i:03d}", **r})
    inputs.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
    print(
        f"P {len(policy)}, S {len(sample) + len(extra)} of {len(shaped)}, "
        f"R {len(picked[2][1])} of {len(rest)}",
        file=sys.stderr,
    )


def read_labels(path: Path) -> dict[str, bool]:
    labels = {}
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        cid, mark = line.split("\t")
        labels[cid] = mark.strip() == "y"
    return labels


def source(r: dict) -> str:
    return f"{r['repo']}:{r['file']}:{r['line']}@{r['rev']}"


def cases(inputs: list[dict], labels: dict[str, bool]) -> list[dict]:
    out = []
    for r in inputs:
        row = bdc.to_row(r)
        if row.status:
            continue
        state, questions = bdc.build_tally_case(row.clause, row.numbers, row.heading)
        out.append(
            {
                "id": r["id"],
                "state": state,
                "questions": questions,
                "expected": {"tally": labels[r["id"]]},
                "source": source(r),
            }
        )
    return out


def build(inputs: Path, labels: Path, out: Path) -> None:
    recs = [json.loads(line) for line in inputs.read_text().splitlines()]
    built = cases(recs, read_labels(labels))
    out.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in built))
    print(f"{len(built)} cases", file=sys.stderr)


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "collect":
        collect(Path(argv[1]), Path(argv[2]))
    elif len(argv) == 3 and argv[0] == "select":
        select(Path(argv[1]), Path(argv[2]))
    elif len(argv) == 4 and argv[0] == "build":
        build(Path(argv[1]), Path(argv[2]), Path(argv[3]))
    else:
        print(__doc__.strip(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
