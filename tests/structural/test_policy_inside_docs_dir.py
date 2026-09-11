"""A policy file inside `--docs-dir` is measured once, as the policy (#277).

`measure-context.sh` inventories reference docs with a `find` over the docs dir,
and nothing kept the policy file out of it. In a layout that puts the policy
file inside that dir — `--docs-dir skills/<name>`, or a monorepo keeping its
guidance under `docs/` — a run measured it once as `policy` and again as one of
its own reference docs:

- `tokens_live`, the watched ceiling on what one session can pull in, counted
  it twice: a one-line doc tree reported at more than twice its size;
- `docs_total` on the ledger row was one too many;
- `docs[]` held a row for it, priced against the per-doc budget on top of the
  policy verdict it already had;
- an `--exact` run counted it twice, weighted it twice in the persisted
  bytes-per-token ratio, and anchored it in two identical calibration rows.

#274's CR 1 had patched one more symptom, `links.unindexed`, with a term in its
filter. The fix drops that term; `test_unindexed_docs.py` keeps the property.

No API calls: the `--exact` case answers from a local stub on
`ANTHROPIC_BASE_URL`.
"""

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "skills" / "curating-context" / "scripts"
MEASURE = SCRIPTS / "measure-context.sh"
RECORD = SCRIPTS / "record-telemetry.sh"

# Root-anchored, so one text links the same doc from either location and the
# two layouts differ in where the policy file sits and nothing else. Long enough
# to outweigh every doc below, which the doc-budget case depends on.
POLICY = (
    "# P\n\n"
    "Guidance an agent reads first, long enough to outweigh every doc below.\n\n"
    "## Detail Docs\n\n"
    "- [docs/A.md](/docs/A.md) — a\n"
)
DOCS = {
    "docs/A.md": "# A\n\nLinked.\n",
    "docs/ORPHAN.md": "# O\n\nLinked by nothing.\n",
}
INSIDE = ("--file", "docs/AGENTS.md", "--docs-dir", "docs")


def _clean_env() -> dict:
    """No inherited git state, context knob or credential: each case supplies
    whatever it needs, or a developer's shell answers instead."""
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("GIT_", "CONTEXT_", "ANTHROPIC_"))
    }


def _repo(tmp_path: Path, name: str, policy_at: str, extra: dict | None = None) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, env=_clean_env())
    for rel, text in {policy_at: POLICY, **DOCS, **(extra or {})}.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(MEASURE), "--no-write", "--no-env-file", *args],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=60,
    )


def _measure(repo: Path, *args: str) -> dict:
    result = _run(repo, *args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class TestMeasuredOnceAsThePolicy:
    def test_where_the_policy_sits_does_not_change_what_the_surface_weighs(
        self, tmp_path: Path
    ):
        """The same policy text over the same docs, at the root and inside the
        docs dir. Only the policy file's path may differ."""
        root = _measure(_repo(tmp_path, "root", "AGENTS.md"))
        inside = _measure(_repo(tmp_path, "inside", "docs/AGENTS.md"), *INSIDE)
        assert inside["totals"] == root["totals"]
        assert inside["docs"] == root["docs"]
        assert inside["links"] == root["links"]
        assert {**inside["policy"], "path": None} == {**root["policy"], "path": None}

    def test_the_inventory_and_the_totals_leave_it_out(self, tmp_path: Path):
        data = _measure(_repo(tmp_path, "inside", "docs/AGENTS.md"), *INSIDE)
        tokens = {doc["path"]: doc["tokens"] for doc in data["docs"]}
        assert sorted(tokens) == ["docs/A.md", "docs/ORPHAN.md"]
        assert data["totals"]["files_docs"] == 2
        assert data["totals"]["tokens_docs"] == sum(tokens.values())
        # The policy once, plus the one doc it reaches; the orphan is inventoried
        # but not live.
        assert data["totals"]["tokens_live"] == (
            data["policy"]["tokens"] + tokens["docs/A.md"]
        )

    def test_the_ledger_row_counts_it_once(self, tmp_path: Path):
        repo = _repo(tmp_path, "inside", "docs/AGENTS.md")
        measured = _run(repo, *INSIDE)
        assert measured.returncode == 0, measured.stderr
        data = json.loads(measured.stdout)
        recorded = subprocess.run(
            ["bash", str(RECORD), "--dry-run"],
            input=measured.stdout,
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=_clean_env(),
            timeout=30,
        )
        assert recorded.returncode == 0, recorded.stdout + recorded.stderr
        line = [x for x in recorded.stdout.splitlines() if x.strip().startswith("{")][
            -1
        ]
        row = json.loads(line)
        assert row["docs_total"] == 2, row
        assert row["tokens_live"] == data["totals"]["tokens_live"], row

    def test_it_is_not_priced_against_the_doc_budget(self, tmp_path: Path):
        """A doc budget the policy file exceeds and every real doc is under:
        no doc row may carry a verdict, and the policy keeps its own."""
        doc_budget = 20
        data = _measure(
            _repo(tmp_path, "inside", "docs/AGENTS.md"),
            *INSIDE,
            "--doc-budget",
            str(doc_budget),
        )
        # The premise, so the case cannot pass on a policy file too small to
        # have been flagged.
        assert data["policy"]["tokens"] > doc_budget
        assert data["policy"]["over_budget"] is False
        assert not any(d["over_budget"] or d["near_budget"] for d in data["docs"])

    def test_a_dot_slash_spelling_is_the_same_file(self, tmp_path: Path):
        """`--file ./docs/AGENTS.md` matched no path the run compares with, and
        the inventory called the policy file an orphan of itself. The skip
        compares identity now (CR 1); what this pins is the trim, without which
        the ledger's `file` and the walk keep a second spelling."""
        repo = _repo(tmp_path, "inside", "docs/AGENTS.md")
        dotted = _measure(repo, "--file", "./docs/AGENTS.md", "--docs-dir", "docs")
        assert dotted["links"]["orphans"] == ["docs/ORPHAN.md"]
        assert dotted == _measure(repo, *INSIDE)

    def test_a_root_symlink_into_the_docs_dir_is_the_same_file(self, tmp_path: Path):
        """CR 1. Guidance kept under `docs/` and found at the root through a
        symlink: a flagless run — the cadence's — measures `AGENTS.md`, and the
        inventory's `find` lists its target. A path comparison missed it, and
        the policy file was reported an orphan of itself."""
        repo = _repo(tmp_path, "symlink", "docs/AGENTS.md")
        (repo / "AGENTS.md").symlink_to("docs/AGENTS.md")
        data = _measure(repo)
        root = _measure(_repo(tmp_path, "root", "AGENTS.md"))
        assert data["links"]["orphans"] == ["docs/ORPHAN.md"]
        assert data["totals"] == root["totals"]

    def test_under_an_archival_subtree_it_is_not_archive(self, tmp_path: Path):
        """The skip comes first: a policy file under `docs/plans/` is the policy,
        not a skipped dated snapshot. The real one beside it still is."""
        repo = _repo(
            tmp_path,
            "archival",
            "docs/plans/AGENTS.md",
            {"docs/plans/2026-01-01-old.md": "# Old\n"},
        )
        data = _measure(repo, "--file", "docs/plans/AGENTS.md", "--docs-dir", "docs")
        assert data["totals"]["archival_skipped"] == 1


# Two rates, so weighting the policy file twice moves the persisted ratio: at
# one rate for every file, a duplicate would be invisible in it.
def _tokens(text: str) -> int:
    return len(text.encode()) // (2 if text == POLICY else 4)


class _CountStub:
    """count_tokens on a local port, answering each file at its rate above and
    recording every text it was sent."""

    def __init__(self):
        self.sent: list[str] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 — BaseHTTPRequestHandler's spelling
                length = int(self.headers.get("content-length", 0))
                text = json.loads(self.rfile.read(length))["messages"][0]["content"]
                stub.sent.append(text)
                out = json.dumps({"input_tokens": _tokens(text)}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *args):  # keep pytest output clean
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "_CountStub":
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class TestAnExactRunCountsItOnce:
    def test_counted_weighted_and_anchored_once(self, tmp_path: Path):
        """`--calibrate`, because a scoped run persists nothing without it —
        and the persisted artifacts are where a duplicate outlives the run."""
        repo = _repo(tmp_path, "inside", "docs/AGENTS.md")
        env = _clean_env()
        env["ANTHROPIC_API_KEY"] = "sk-ant-not-a-real-key"
        cmd = ["bash", str(MEASURE), "--exact", "--calibrate", "--no-env-file"]
        with _CountStub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            result = subprocess.run(
                [*cmd, *INSIDE],
                capture_output=True,
                text=True,
                cwd=str(repo),
                env=env,
                timeout=60,
            )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["policy"]["tokens_exact"] is True
        assert stub.sent.count(POLICY) == 1

        counts = (repo / ".skills" / "context-token-counts").read_text()
        anchored = [
            line.split(" ", 2)[2]
            for line in counts.splitlines()
            if line and not line.startswith("#")
        ]
        assert sorted(anchored) == ["docs/A.md", "docs/AGENTS.md", "docs/ORPHAN.md"]

        # The surface ratio over each file once, orphan included: the guard
        # prices every file under the docs dir, linked or not.
        texts = [POLICY, *DOCS.values()]
        x100 = sum(len(t.encode()) for t in texts) * 100 // sum(map(_tokens, texts))
        ratio = (repo / ".skills" / "context-token-ratio").read_text().strip()
        assert ratio == f"{x100 // 100}.{x100 % 100:02d}"
