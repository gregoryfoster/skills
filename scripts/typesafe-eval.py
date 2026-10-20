#!/usr/bin/env python3
"""Measure a TypeSafe judgment against a labelled set before anything gates on it.

usage: python3 scripts/typesafe-eval.py SET.jsonl [--cache FILE] [--offline]
           [--model ID] [--report FILE] [--format json|markdown]
           [--thresholds T,...] [--bins N] [--public]

Repo tooling for epic #451 (gregoryfoster/skills#449); no skill ships it. It
imports `scripts/_typesafe.py` beside it, and owns no HTTP code. Stdlib only,
Python 3.9+.

THE SET is JSONL, one case per line (blank lines are skipped):

  {"id": "c1", "state": ..., "questions": {...}, "expected": {...}, "source": "..."}

  id         a non-empty string, unique in the set
  state      any JSON: what the questions are asked about
  questions  {name: question}, sent as is. A question's type is `choice`
             (criteria an object of options), `score` (criteria a list of
             levels, 0 first) or `noul`. `box` is refused.
  expected   {name: label}, one label for every question:
               choice  a string that is a key of that question's criteria
               score   an integer level, 0 to len(criteria) - 1
               noul    true or false
  source     optional string saying where the case came from

  Metrics are per question name, and a name keeps its type across rows. A Score
  answer is a probability-weighted mean, so it's scored at the nearest level,
  half up, and its mean absolute error is reported beside the agreement.

THE REPORT is printed as JSON (or markdown, for posting on an issue). It holds
aggregates only, never a case's state or id:

  choice, score  agreement, a confusion matrix (rows expected, columns
                 predicted), and accuracy by confidence band
  noul           precision and recall at each threshold (yes when
                 noul >= threshold), a calibration table binning the noul
                 value itself (a Noul has no confidence), and the Brier score
  every run      the model asked for, every model that answered, calls made
                 and replayed, and token usage, live and in total, each
                 request counted once; tokens.missing counts usage fields a
                 reply didn't carry

  A run is valid only when one model answered every case, and, when the
  pinned model was asked for, that model is the pin. Otherwise the report is
  still printed, with "valid": false and the reason, and the exit is 5.

THE CACHE (--cache FILE) is JSONL, appended after every call: {id, key,
reply}. The key is a sha256 of the model asked for, the state and the
questions, so an edited case or another --model misses instead of replaying a
stale answer. A run that fails part-way resumes from it. It holds no state.
--offline never calls the API, and a miss is exit 1.

PRIVATE SETS. A set drawn from a private repo is never committed here. The set,
the cache and the report must each resolve outside every git work tree, or the
run refuses before reading anything. --public lifts that, for a set built from
public material. Stdout isn't guarded: don't redirect it into a checkout.

SENDING. Nothing is sent until the first cache miss. Then the client's opt-in
applies: TYPESAFE_OPT_IN=on, or else `.skills/typesafe` in the git checkout
holding the current directory, not this script's. Run from inside the source
repo, that is the source repo's own opt-in. Run from anywhere else (this repo
has no knob), TYPESAFE_OPT_IN=on is the operator's consent for the set's text.
The key comes from TYPESAFE_API_KEY. About 273 input tokens of overhead per
call [#448].

exit codes:
  0  a valid report
  1  usage error, a malformed set or cache, a cache miss under --offline, or a
     path refused as inside a work tree. Nothing was sent.
  2  a TypeSafe failure (its message shown), an answer missing a field its
     type promises, or a cache or report write that failed after answers came
     back (a report that can't be written goes to stdout). Answers already
     received are in the cache, when one was given.
  4  skipped: not opted in, or no key (the client's one line shown)
  5  invalid run: the report is printed, marked "valid": false
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python3 -I` drops it
import _typesafe  # noqa: E402

TYPES = ("choice", "score", "noul")
ROW_KEYS = {"id", "state", "questions", "expected", "source"}
DEFAULT_THRESHOLDS = tuple(round(0.1 * i, 1) for i in range(1, 10))
DEFAULT_BINS = 10
MAX_ERRORS = 20

EXIT_USAGE = 1
EXIT_FAILED = 2
EXIT_SKIPPED = 4
EXIT_INVALID = 5


class UsageError(Exception):
    """Exit 1: nothing was sent."""


class AnswerError(Exception):
    """An answer without the fields its type promises."""


# --- the set -----------------------------------------------------------------


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _refuse_constant(name: str):
    # NaN and Infinity parse, but the client can't send them (allow_nan=False).
    raise ValueError(f"{name} isn't valid JSON")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):  # 1e400 parses to inf (CR 412)
        raise ValueError(f"{text} overflows to infinity, which isn't valid JSON")
    return value


def _check_question(name: str, q, label) -> str | None:
    """Why this question or its label is unusable, or None."""
    if not isinstance(q, dict):
        return f"question {name!r} is not an object"
    kind = q.get("type")
    if kind not in TYPES:
        return (
            f"question {name!r} has type {kind!r}; only {', '.join(TYPES)} are scored"
        )
    criteria = q.get("criteria")
    if kind == "choice":
        if not isinstance(criteria, dict) or not criteria:
            return f"choice {name!r} needs criteria as a non-empty object"
        if not isinstance(label, str) or label not in criteria:
            return f"expected {name!r} is {label!r}, not one of {sorted(criteria)}"
    elif kind == "score":
        if not isinstance(criteria, list) or not criteria:
            return f"score {name!r} needs criteria as a non-empty list"
        if (
            not isinstance(label, int)
            or isinstance(label, bool)
            or not 0 <= label < len(criteria)
        ):
            return f"expected {name!r} is {label!r}, not a level 0-{len(criteria) - 1}"
    elif not isinstance(label, bool):
        return f"expected {name!r} is {label!r}; a noul label is true or false"
    return None


def load_set(lines) -> list[dict]:
    """Parse and validate the set. Raises UsageError listing every problem found."""
    rows, errors, seen, types = [], [], set(), {}
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(
                line, parse_constant=_refuse_constant, parse_float=_finite_float
            )
        except ValueError as e:
            errors.append(f"line {n}: not JSON: {e}")
            continue
        if not isinstance(row, dict):
            errors.append(f"line {n}: not an object")
            continue
        rid = row.get("id")
        where = f"line {n}" + (f" ({rid})" if isinstance(rid, str) else "")
        problems = []
        if not isinstance(rid, str) or not rid:
            problems.append("id must be a non-empty string")
        elif rid in seen:
            problems.append("id repeats an earlier case")
        unknown = sorted(set(row) - ROW_KEYS)
        if unknown:
            problems.append(f"unknown key(s) {unknown}")
        if "state" not in row:
            problems.append("state is missing")
        if "source" in row and not isinstance(row["source"], str):
            problems.append("source must be a string")
        questions, expected = row.get("questions"), row.get("expected")
        if (
            not isinstance(questions, dict)
            or not questions
            or not all(isinstance(k, str) for k in questions)
        ):
            problems.append("questions must be a non-empty object")
        elif not isinstance(expected, dict):
            problems.append("expected must be an object keyed by question name")
        elif set(expected) != set(questions):
            problems.append(
                "expected must label every question and nothing else "
                f"(questions {sorted(questions)}, expected {sorted(expected)})"
            )
        else:
            for name, q in questions.items():
                why = _check_question(name, q, expected[name])
                if why is None and types.setdefault(name, q["type"]) != q["type"]:
                    why = f"question {name!r} was {types[name]} on an earlier case"
                if why:
                    problems.append(why)
        if problems:
            errors.extend(f"{where}: {p}" for p in problems)
        else:
            seen.add(rid)
            rows.append(row)
    if errors:
        more = len(errors) - MAX_ERRORS
        shown = errors[:MAX_ERRORS] + ([f"... and {more} more"] if more > 0 else [])
        raise UsageError("the set is malformed:\n  " + "\n  ".join(shown))
    if not rows:
        raise UsageError("the set has no cases")
    return rows


# --- the cache ---------------------------------------------------------------


def request_key(model: str, state, questions: dict) -> str:
    body = json.dumps(
        {"model": model, "state": state, "questions": questions},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def load_cache(lines) -> dict[str, dict]:
    cache = {}
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError as e:
            raise UsageError(f"cache line {n}: not JSON: {e}") from None
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("key"), str)
            or not isinstance(entry.get("reply"), dict)
            or not isinstance(entry["reply"].get("answers"), dict)
        ):
            # The client checks a live reply's answers; a cached one is checked
            # here, or a hand-edited line crashes the scoring (CR 406).
            raise UsageError(
                f"cache line {n}: needs a string key and a reply with an answers object"
            )
        cache[entry["key"]] = entry["reply"]
    return cache


# --- the private-set guard ---------------------------------------------------


def in_work_tree(path: Path) -> bool | None:
    """True inside a git work tree, False outside, None when git can't say.

    The nearest existing ancestor is asked, after symlinks resolve, so a
    scratch link pointing into a checkout is caught. Every GIT_ variable is
    dropped: GIT_DIR answers for the repo it names, not the path, and
    GIT_CEILING_DIRECTORIES hides the checkout above it (CR 411).
    """
    probe = Path(os.path.realpath(path))
    while not probe.is_dir():
        probe = probe.parent
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["LC_ALL"] = "C"  # the "not a git repository" match below reads git's English
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=probe,
            env=env,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if out.returncode == 0:
        return out.stdout.strip() == "true"
    # git's own "not a git repository" is a clear no; anything else is unknown.
    return False if "not a git repository" in out.stderr else None


def guard(paths: dict[str, Path], public: bool) -> None:
    if public:
        return
    for what, path in paths.items():
        inside = in_work_tree(path)
        if inside is None:
            raise UsageError(
                f"can't tell whether the {what} {path} is inside a git work tree, "
                "so it's refused. Pass --public if the set is public material"
            )
        if inside:
            raise UsageError(
                f"the {what} {path} is inside a git work tree, where a private set "
                "could be committed. Keep it in scratch, or pass --public if the set "
                "is built from public material"
            )


# --- answers -----------------------------------------------------------------


def nearest_level(score: float, levels: int) -> int:
    return min(levels - 1, max(0, math.floor(score + 0.5)))


def read_answer(question: dict, answer) -> dict:
    """The fields a metric uses, checked. Raises AnswerError."""
    kind = question["type"]
    if not isinstance(answer, dict) or answer.get("type") != kind:
        raise AnswerError(f"expected a {kind} answer, got {answer!r}")
    if kind == "noul":
        if not _is_number(answer.get("noul")):
            raise AnswerError(f"noul answer has no number: {answer!r}")
        return {"p": float(answer["noul"])}
    if not _is_number(answer.get("confidence")):
        raise AnswerError(f"{kind} answer has no confidence: {answer!r}")
    if kind == "choice":
        if not isinstance(answer.get("choice"), str):
            raise AnswerError(f"choice answer has no choice: {answer!r}")
        return {"predicted": answer["choice"], "confidence": answer["confidence"]}
    if not _is_number(answer.get("score")):
        raise AnswerError(f"score answer has no score: {answer!r}")
    level = nearest_level(answer["score"], len(question["criteria"]))
    return {
        "predicted": level,
        "score": float(answer["score"]),
        "confidence": answer["confidence"],
    }


# --- metrics (pure) ----------------------------------------------------------


def band_of(value: float, bins: int) -> int:
    # 0.57 * 100 is 56.99999999999999; round off the float error first (CR 414).
    return min(bins - 1, max(0, int(round(value * bins, 9))))


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _bands(bins: int) -> list[dict]:
    return [
        {"lo": round(i / bins, 6), "hi": round((i + 1) / bins, 6)} for i in range(bins)
    ]


def label_metrics(records: list[dict], labels: list, bins: int) -> dict:
    """Choice or Score: agreement, confusion matrix, accuracy by confidence band."""
    index = {label: i for i, label in enumerate(labels)}
    matrix = [[0] * len(labels) for _ in labels]
    correct = 0
    bands = _bands(bins)
    for b in bands:
        b.update(n=0, correct=0)
    for r in records:
        hit = r["expected"] == r["predicted"]
        correct += hit
        matrix[index[r["expected"]]][index[r["predicted"]]] += 1
        b = bands[band_of(r["confidence"], bins)]
        b["n"] += 1
        b["correct"] += hit
    for b in bands:
        b["accuracy"] = _ratio(b["correct"], b["n"])
    return {
        "n": len(records),
        "correct": correct,
        "agreement": _ratio(correct, len(records)),
        "confusion": {"labels": labels, "matrix": matrix},
        "by_confidence": bands,
    }


def noul_metrics(records: list[dict], thresholds, bins: int) -> dict:
    """Noul: precision and recall per threshold, calibration by noul value, Brier."""
    sweep = []
    for t in thresholds:
        tp = sum(1 for r in records if r["p"] >= t and r["expected"])
        fp = sum(1 for r in records if r["p"] >= t and not r["expected"])
        fn = sum(1 for r in records if r["p"] < t and r["expected"])
        tn = len(records) - tp - fp - fn
        sweep.append(
            {
                "threshold": t,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "tn": tn,
                "precision": _ratio(tp, tp + fp),
                "recall": _ratio(tp, tp + fn),
            }
        )
    bands = _bands(bins)
    for b in bands:
        b.update(n=0, yes=0, _sum=0.0)
    for r in records:
        b = bands[band_of(r["p"], bins)]
        b["n"] += 1
        b["yes"] += r["expected"]
        b["_sum"] += r["p"]
    for b in bands:
        total = b.pop("_sum")
        b["mean_noul"] = _ratio(total, b["n"])
        b["observed_yes"] = _ratio(b["yes"], b["n"])
    brier = _ratio(sum((r["p"] - r["expected"]) ** 2 for r in records), len(records))
    positives = sum(1 for r in records if r["expected"])
    return {
        "n": len(records),
        "positives": positives,
        "negatives": len(records) - positives,
        "sweep": sweep,
        "calibration": bands,
        "brier": brier,
    }


def question_metrics(rows: list[dict], replies: list[dict], thresholds, bins) -> dict:
    """Per question name. `replies[i]` answers `rows[i]`."""
    grouped: dict[str, dict] = {}
    for row, reply in zip(rows, replies):
        for name, q in row["questions"].items():
            g = grouped.setdefault(
                name, {"type": q["type"], "records": [], "labels": []}
            )
            got = read_answer(q, reply["answers"].get(name))
            got["expected"] = row["expected"][name]
            g["records"].append(got)
            if q["type"] == "choice":
                g["labels"].extend(q["criteria"])
            elif q["type"] == "score":
                g["labels"].extend(range(len(q["criteria"])))
    out = {}
    for name, g in grouped.items():
        recs = g["records"]
        if g["type"] == "noul":
            m = noul_metrics(recs, thresholds, bins)
        else:
            seen = (
                g["labels"]
                + [r["expected"] for r in recs]
                + [r["predicted"] for r in recs]
            )
            labels = list(dict.fromkeys(seen))
            if g["type"] == "score":
                labels.sort()
            m = label_metrics(recs, labels, bins)
            if g["type"] == "score":
                m["mean_abs_error"] = _ratio(
                    sum(abs(r["score"] - r["expected"]) for r in recs), len(recs)
                )
        out[name] = {"type": g["type"], **m}
    return out


def validity(model_asked: str, replies: list[dict]) -> tuple[bool, str | None, list]:
    models = sorted({str(r.get("model", "<no model field>")) for r in replies})
    if len(models) > 1:
        return False, f"more than one model answered: {', '.join(models)}", models
    if model_asked == _typesafe.MODEL and models != [_typesafe.MODEL]:
        return (
            False,
            f"the pinned {_typesafe.MODEL} was asked for and {models[0]} answered",
            models,
        )
    return True, None, models


def usage_totals(replies: list[dict], live: list[bool], keys: list[str]) -> dict:
    """Token usage, each request once: a case repeated in the set is billed once (CR 417)."""
    totals = {"input": 0, "output": 0, "live_input": 0, "live_output": 0, "missing": 0}
    seen = set()
    for reply, was_live, key in zip(replies, live, keys):
        if key in seen:
            continue
        seen.add(key)
        usage = reply.get("usage") if isinstance(reply.get("usage"), dict) else {}
        for field, key in (("input_tokens", "input"), ("output_tokens", "output")):
            v = usage.get(field)
            if not _is_number(v):
                totals["missing"] += 1
                continue
            totals[key] += v
            if was_live:
                totals[f"live_{key}"] += v
    return totals


# --- rendering ---------------------------------------------------------------


def _cell(v) -> str:
    """A table cell: a `|` in a label would split it (CR 408)."""
    return str(v).replace("|", "\\|")


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def render_markdown(report: dict) -> str:
    out = ["## TypeSafe evaluation", ""]
    if not report["valid"]:
        out += [f"**INVALID RUN:** {report['invalid_reason']}", ""]
    t = report["tokens"]
    out += [
        f"- Model asked: `{report['model_asked']}`; answered: "
        + ", ".join(f"`{m}`" for m in report["models_answered"]),
        f"- Cases: {report['cases']} (set sha256 `{report['set_sha256'][:12]}`)",
        f"- Calls: {report['calls']['live']} live, {report['calls']['replayed']} replayed",
        f"- Input tokens: {t['input']:,} total, {t['live_input']:,} this run",
        "",
    ]
    for name, m in report["questions"].items():
        out += [f"### `{name}` ({m['type']}, n={m['n']})", ""]
        if m["type"] == "noul":
            out += [
                f"Positives {m['positives']}, negatives {m['negatives']}, "
                f"Brier {_fmt(m['brier'])}.",
                "",
                "| threshold | tp | fp | fn | tn | precision | recall |",
                "|---|---|---|---|---|---|---|",
            ]
            out += [
                f"| {s['threshold']} | {s['tp']} | {s['fp']} | {s['fn']} | {s['tn']} "
                f"| {_fmt(s['precision'])} | {_fmt(s['recall'])} |"
                for s in m["sweep"]
            ]
            out += [
                "",
                "| noul band | n | mean noul | observed yes |",
                "|---|---|---|---|",
            ]
            out += [
                f"| {b['lo']:.2f}-{b['hi']:.2f} | {b['n']} | {_fmt(b['mean_noul'])} "
                f"| {_fmt(b['observed_yes'])} |"
                for b in m["calibration"]
            ]
        else:
            line = f"Agreement {_fmt(m['agreement'])} ({m['correct']}/{m['n']})"
            if "mean_abs_error" in m:
                line += f", mean absolute error {_fmt(m['mean_abs_error'])}"
            labels = [_cell(x) for x in m["confusion"]["labels"]]
            out += [
                line + ".",
                "",
                "| expected \\ predicted | " + " | ".join(labels) + " |",
                "|---" * (len(labels) + 1) + "|",
            ]
            out += [
                f"| {label} | " + " | ".join(str(c) for c in row) + " |"
                for label, row in zip(labels, m["confusion"]["matrix"])
            ]
            out += ["", "| confidence band | n | accuracy |", "|---|---|---|"]
            out += [
                f"| {b['lo']:.2f}-{b['hi']:.2f} | {b['n']} | {_fmt(b['accuracy'])} |"
                for b in m["by_confidence"]
            ]
        out.append("")
    return "\n".join(out)


# --- the run -----------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse exits 2, which here means a TypeSafe failure
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        sys.exit(EXIT_USAGE)


def _thresholds(text: str) -> tuple:
    try:
        values = tuple(float(x) for x in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"not a comma-separated list: {text!r}"
        ) from None
    if not values or not all(0.0 <= v <= 1.0 for v in values):
        raise argparse.ArgumentTypeError("thresholds lie in 0-1")
    return values


def _bins(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        n = 0
    if not 1 <= n <= 100:
        raise argparse.ArgumentTypeError(f"bins is an integer 1-100, not {text!r}")
    return n


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = _Parser(
        prog="typesafe-eval.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        usage=argparse.SUPPRESS,
    )
    p.add_argument("set", type=Path, help="the labelled JSONL set")
    p.add_argument(
        "--cache", type=Path, help="cached-responses JSONL: replayed, then appended"
    )
    p.add_argument(
        "--offline",
        action="store_true",
        help="never call the API; a cache miss is exit 1",
    )
    p.add_argument(
        "--model",
        default=_typesafe.MODEL,
        help=f"model to ask (default: the pin, {_typesafe.MODEL})",
    )
    p.add_argument(
        "--report", type=Path, help="write the report here instead of stdout"
    )
    p.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="report format (default json)",
    )
    p.add_argument(
        "--thresholds",
        type=_thresholds,
        default=DEFAULT_THRESHOLDS,
        help="noul thresholds (default 0.1,...,0.9)",
    )
    p.add_argument(
        "--bins",
        type=_bins,
        default=DEFAULT_BINS,
        help="confidence and calibration bands (default 10)",
    )
    p.add_argument(
        "--public",
        action="store_true",
        help="the set is public material: allow paths inside a work tree",
    )
    args = p.parse_args(argv)
    if args.offline and args.cache is None:
        p.error("--offline needs --cache")
    return args


def main(
    argv, *, environ=None, transport=None, cwd=None, stdout=None, stderr=None
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args = parse_args(argv)

    def say(line: str) -> None:
        print(f"typesafe-eval: {line}", file=stderr)

    try:
        paths = {"set": args.set}
        if args.cache:
            paths["cache"] = args.cache
        if args.report:
            paths["report"] = args.report
        guard(paths, args.public)
        resolved = {}
        for what, path in paths.items():
            # A report over the set destroys hand labels nothing can restore (CR 410).
            other = resolved.setdefault(path.resolve(), what)
            if other != what:
                raise UsageError(f"the {what} and the {other} are both {path}")
        for what in ("cache", "report"):
            path = paths.get(what)
            if path is not None and not path.resolve().parent.is_dir():
                raise UsageError(f"the {what}'s directory {path.parent} doesn't exist")
        if args.report and args.report.is_dir():
            raise UsageError(f"the report {args.report} is a directory")
        try:
            raw = args.set.read_bytes()
            # utf-8-sig: an editor's byte-order mark is not line 1 (CR 407, as CR 391)
            rows = load_set(raw.decode("utf-8-sig").splitlines())
        except (OSError, UnicodeDecodeError) as e:
            raise UsageError(f"can't read the set {args.set}: {e}") from None
        cache = {}
        if args.cache and args.cache.exists():
            try:
                cache = load_cache(
                    args.cache.read_text(encoding="utf-8-sig").splitlines()
                )
            except (OSError, UnicodeDecodeError) as e:
                raise UsageError(f"can't read the cache {args.cache}: {e}") from None
        keys = [request_key(args.model, r["state"], r["questions"]) for r in rows]
        if args.offline:
            missing = [r["id"] for r, k in zip(rows, keys) if k not in cache]
            if missing:
                raise UsageError(
                    f"--offline, and {len(missing)} case(s) aren't in the cache "
                    f"for {args.model}: {', '.join(missing[:10])}"
                )
    except UsageError as e:
        say(str(e))
        return EXIT_USAGE

    replies, live, client = [], [], None
    for row, key in zip(rows, keys):
        if key in cache:
            replies.append(cache[key])
            live.append(False)
            continue
        try:
            if client is None:
                client = _typesafe.connect(
                    model=args.model,
                    environ=environ,
                    cwd=cwd,
                    transport=transport,
                    stderr=stderr,
                )
            reply = client.ask(row["state"], row["questions"])
        except _typesafe.Skipped as s:
            print(s.line, file=stderr)
            return EXIT_SKIPPED
        except _typesafe.TypeSafeError as e:
            print(e, file=stderr)
            say(f"case {row['id']} failed, so no later case was asked (CR 409)")
            if args.cache and any(live):
                say(f"{sum(live)} answer(s) are in {args.cache}; a re-run resumes")
            return EXIT_FAILED
        cache[key] = reply
        replies.append(reply)
        live.append(True)
        if args.cache:
            try:
                with args.cache.open("a", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {"id": row["id"], "key": key, "reply": reply},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            except OSError as e:
                # Answers were sent, so this isn't exit 1's "nothing was sent" (CR 413).
                say(
                    f"case {row['id']} was answered, but the cache {args.cache} can't take it: {e}"
                )
                return EXIT_FAILED

    try:
        questions = question_metrics(rows, replies, args.thresholds, args.bins)
    except AnswerError as e:
        say(f"an answer is malformed, so nothing was scored: {e}")
        return EXIT_FAILED
    valid, reason, models = validity(args.model, replies)
    report = {
        "valid": valid,
        "invalid_reason": reason,
        "model_asked": args.model,
        "models_answered": models,
        "cases": len(rows),
        "set_sha256": hashlib.sha256(raw).hexdigest(),
        "calls": {"live": sum(live), "replayed": len(live) - sum(live)},
        "tokens": usage_totals(replies, live, keys),
        "thresholds": list(args.thresholds),
        "bins": args.bins,
        "questions": questions,
    }
    text = (
        render_markdown(report)
        if args.format == "markdown"
        else json.dumps(report, indent=2)
    )
    if not valid:
        # Said before the write, so a failed write's exit 2 can't hide it (CR 418).
        say(f"invalid run: {reason}")
    if args.report:
        try:
            args.report.write_text(text + "\n", encoding="utf-8")
        except OSError as e:
            print(text, file=stdout)  # the answers were paid for; don't drop the report
            say(f"can't write the report {args.report}, so it's on stdout: {e}")
            return EXIT_FAILED
    else:
        print(text, file=stdout)
    return 0 if valid else EXIT_INVALID


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
