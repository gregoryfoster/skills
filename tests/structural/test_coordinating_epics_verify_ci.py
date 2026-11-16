"""coordinating-epics: verify-ci.sh reports CI by job, never by workflow (#394).

The first three tests are #394's own reproduction, from its "Why": the three
ways coordinators got CI verification wrong. A workflow-level green read as a
pass while a required job hadn't run; `conclusion` read before `status` was
`completed`; a scheduled job failing on `main`, unseen for about ten weeks. A
fake gh stands in for GitHub's REST API.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "skills" / "coordinating-epics" / "scripts" / "verify-ci.sh"
REPO = "acme/widgets"
SHA = "a" * 40
BASE = "b" * 40
TIP = "c" * 40


def _yaml_reachable() -> bool:
    """What the wrapper needs: a python3 that imports yaml, or uv."""
    py = shutil.which("python3")
    if (
        py
        and subprocess.run([py, "-c", "import yaml"], capture_output=True).returncode
        == 0
    ):
        return True
    return shutil.which("uv") is not None


pytestmark = pytest.mark.skipif(
    not _yaml_reachable(),
    reason="verify-ci.sh needs python3 with PyYAML, or uv to supply it; neither is here",
)

FAKE_GH = r"""#!__PYTHON__
import json, os, re, sys
from urllib.parse import parse_qs, urlsplit
path = os.environ["FAKE_GH_STATE"]
st = json.load(open(path))
args = sys.argv[1:]
st.setdefault("calls", []).append(args)
def out(obj):
    json.dump(st, open(path, "w"))
    print(json.dumps(obj))
    sys.exit(0)
def fail(msg="HTTP 404: Not Found"):
    json.dump(st, open(path, "w"))
    print(msg, file=sys.stderr)
    sys.exit(1)
if st.get("fail_all"):
    fail(st["fail_all"])
if args[0] != "api":
    fail("unsupported")
u = urlsplit(args[1])
q = {k: v[0] for k, v in parse_qs(u.query).items()}
p = u.path.split("/")[3:]  # after repos/OWNER/REPO
page, per = int(q.get("page", 1)), int(q.get("per_page", 30))
def paged(key, rows):
    out({key: rows[(page - 1) * per : page * per]})
def seq(name, k):
    # The n-th read of k gets the n-th entry; the last one repeats.
    reads = st.setdefault("reads", {})
    n = reads[name + k] = reads.get(name + k, 0) + (1 if page == 1 else 0)
    entries = st[name].get(k, [[]])
    return entries[min(n, len(entries)) - 1]
if p == []:
    out({"default_branch": "main"})
if p[:1] == ["commits"] and len(p) == 2:
    sha = p[1]
    c = st["commits"].get(sha)
    if c is None:
        fail("HTTP 404: Not Found\nNo commit found for SHA: " + sha)
    out({"sha": sha, "parents": [{"sha": x} for x in c.get("parents", [])],
         "commit": {"message": c.get("message", "a change")}})
if p[:1] == ["compare"]:
    # GitHub's compare lists 300 files at most, on page 1; later pages are
    # empty (CR 2262).
    files = [{"filename": f} for f in st["files"][:300]]
    out({"files": files if page == 1 else []})
if p[:3] == ["contents", ".github", "workflows"] and len(p) == 3:
    out([{"type": "file", "path": ".github/workflows/" + n} for n in st["workflows"]])
if p[:3] == ["contents", ".github", "workflows"]:
    text = st["workflows"][p[3]]
    out({"content": __import__("base64").b64encode(text.encode()).decode()})
if p == ["actions", "runs"]:
    paged("workflow_runs", st["runs"].get(q["head_sha"], []))
if p[:1] == ["commits"] and p[2:] == ["check-runs"]:
    paged("check_runs", seq("checks", p[1]))
if p[:1] == ["branches"]:
    out({"commit": {"sha": st["tip"]}})
if p == ["actions", "workflows"]:
    paged("workflows", st.get("active", []))
if p[:2] == ["actions", "workflows"] and p[3:] == ["runs"]:
    latest = st.get("latest", {}).get(p[2])
    if not isinstance(latest, list):  # one run, or a branch's runs newest first
        latest = [latest] if latest else []
    paged("workflow_runs", latest)
if p[:2] == ["actions", "runs"] and p[3:] == ["jobs"]:
    paged("jobs", seq("jobs", p[2]))
fail()
"""

CI = """\
name: CI
on:
  push:
    branches: [main]
    paths-ignore: ["docs/**", "**.md"]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps: [{run: "true"}]
  test:
    name: Tests
    strategy: {matrix: {py: ["3.11", "3.12"]}}
    runs-on: ubuntu-latest
    steps: [{run: "true"}]
  deploy:
    if: github.ref == 'refs/heads/main'
    needs: [lint]
    runs-on: ubuntu-latest
    steps: [{run: "true"}]
  smoke:
    needs: [deploy]
    runs-on: ubuntu-latest
    steps: [{run: "true"}]
"""

NIGHTLY = """\
name: nightly
on:
  schedule: [{cron: "0 3 * * *"}]
jobs:
  e2e:
    runs-on: ubuntu-latest
    steps: [{run: "true"}]
"""


def check(name, status="completed", conclusion="success", suite=1, sha=SHA):
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "check_suite": {"id": suite},
        "head_sha": sha,
        "html_url": f"https://github.com/{REPO}/actions/runs/1/job/{abs(hash(name))}",
    }


def run_of(path, suite=1, event="push", sha=SHA, rid=100, branch="main", repo=REPO):
    return {
        "id": rid,
        "path": path,
        "check_suite_id": suite,
        "event": event,
        "head_sha": sha,
        "head_branch": branch,
        "head_repository": {"full_name": repo},
    }


GREEN = [
    check("lint"),
    check("Tests (3.11)"),
    check("Tests (3.12)"),
    check("deploy"),
    check("smoke"),
]


class Rig:
    def __init__(self, tmp: Path):
        self.bin = tmp / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(FAKE_GH.replace("__PYTHON__", sys.executable))
        gh.chmod(0o755)
        self.path = tmp / "gh-state.json"
        self.state = {
            "commits": {SHA: {"parents": [BASE]}},
            "files": ["src/app.py"],
            "workflows": {"ci.yml": CI},
            "runs": {SHA: [run_of(".github/workflows/ci.yml")]},
            "checks": {SHA: [GREEN]},
            "tip": SHA,
            "active": [
                {"id": 7, "path": ".github/workflows/ci.yml", "state": "active"}
            ],
            "latest": {"7": run_of(".github/workflows/ci.yml", rid=100)},
            "jobs": {"100": [GREEN]},
        }

    def run(self, *args: str) -> subprocess.CompletedProcess:
        self.path.write_text(json.dumps(self.state))
        env = {k: v for k, v in __import__("os").environ.items() if k != "GH_TOKEN"}
        env["PATH"] = f"{self.bin}:{env.get('PATH', '')}"
        env["FAKE_GH_STATE"] = str(self.path)
        return subprocess.run(
            ["bash", str(SCRIPT), "--repo", REPO, "--sha", SHA, *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def report(res) -> dict:
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def rows(rep, target="sha"):
    return {r["job"]: r for r in rep["rows"] if r["target"] == target}


# ---------------------------------------------------------------- #394, verbatim


def test_394_a_workflow_level_green_with_a_required_job_unrun_is_not_green(rig):
    """#394: "They read a workflow-level green as a pass while a required job
    hadn't run." Every check run that exists passed; `lint` never ran."""
    rig.state["checks"][SHA] = [[c for c in GREEN if c["name"] != "lint"]]
    rep = report(rig.run())
    assert rep["missing"] == [{"workflow": ".github/workflows/ci.yml", "job": "lint"}]
    assert rep["verdict"] == "incomplete"
    assert "sha: .github/workflows/ci.yml / lint never ran" in rep["because"]


def test_394_conclusion_is_read_only_once_status_is_completed(rig):
    """#394: "They read `conclusion` before `status` was `completed`." GitHub
    can hold a stale conclusion on a re-run in progress."""
    rig.state["checks"][SHA] = [
        [check("lint", status="in_progress", conclusion="success")] + GREEN[1:]
    ]
    rep = report(rig.run())
    assert rows(rep)["lint"]["status"] == "in_progress"
    assert rows(rep)["lint"]["conclusion"] is None
    assert rep["verdict"] == "pending"


def test_394_a_scheduled_job_failing_on_main_is_red(rig):
    """#394: "They missed a scheduled job that was failing on `main`." It ran
    on an older commit, so the SHA's own check runs never show it."""
    rig.state["workflows"]["nightly.yml"] = NIGHTLY
    rig.state["active"].append(
        {"id": 8, "path": ".github/workflows/nightly.yml", "state": "active"}
    )
    rig.state["latest"]["8"] = run_of(
        ".github/workflows/nightly.yml", event="schedule", sha=BASE, rid=200
    )
    rig.state["jobs"]["200"] = [[check("e2e", conclusion="failure", sha=BASE)]]
    rep = report(rig.run())
    e2e = rows(rep, "main-latest")["e2e"]
    assert (e2e["event"], e2e["conclusion"], e2e["sha"]) == (
        "schedule",
        "failure",
        BASE,
    )
    assert rep["verdict"] == "red"
    assert rep["missing"] == []  # a schedule-only workflow isn't expected on push


# ---------------------------------------------------------------- expectations


def test_all_jobs_passing_is_green_and_each_row_says_whether_it_was_expected(rig):
    rep = report(rig.run())
    assert rep["verdict"] == "green" and rep["because"] == []
    got = {k: v["expected"] for k, v in rows(rep).items()}
    assert got == {
        "lint": True,
        "Tests (3.11)": True,
        "Tests (3.12)": True,
        "deploy": "conditional",
        "smoke": "conditional",  # needs a conditional job
    }
    assert all(r["expected"] is None for r in rep["rows"] if r["target"] != "sha")


def test_a_conditional_job_that_didnt_run_is_never_missing(rig):
    rig.state["checks"][SHA] = [
        [c for c in GREEN if c["name"] not in ("deploy", "smoke")]
    ]
    rep = report(rig.run())
    assert rep["missing"] == [] and rep["verdict"] == "green"


@pytest.mark.parametrize(
    "files, ran",
    [
        (["docs/guide.md"], False),
        (["README.md"], False),
        (["docs/guide.md", "src/app.py"], True),
    ],
    ids=["docs-only-skips", "root-md-skips", "one-code-file-runs"],
)
def test_paths_ignore_decides_whether_jobs_are_expected(rig, files, ran):
    rig.state["files"] = files
    rig.state["checks"][SHA] = [[]]
    rig.state["runs"][SHA] = []
    rep = report(rig.run())
    assert bool(rep["missing"]) is ran
    assert rep["verdict"] == ("incomplete" if ran else "green")


def test_a_paths_filter_and_a_leading_double_star_matching_the_root(rig):
    """auditing-ci-cost trap 6: a leading **/ matches zero directories."""
    rig.state["workflows"]["ci.yml"] = CI.replace(
        'paths-ignore: ["docs/**", "**.md"]',
        'paths: ["**/pyproject.toml", "src/**", "!src/vendor/**"]',
    )
    for files, ran in (
        (["pyproject.toml"], True),
        (["src/vendor/x.py"], False),
        (["docs/a.md"], False),
    ):
        rig.state["files"] = files
        rig.state["checks"][SHA] = [[]]
        assert bool(report(rig.run())["missing"]) is ran, files


@pytest.mark.parametrize(
    "on",
    [
        "push",
        "[push, pull_request]",
        "{push: {branches: [release]}}",
        "{push: {tags: ['v*']}}",
    ],
)
def test_the_push_trigger_in_each_form(rig, on):
    wf = (
        "name: CI\non: "
        + on
        + "\njobs:\n  lint:\n    runs-on: x\n    steps: [{run: 'true'}]\n"
    )
    rig.state["workflows"]["ci.yml"] = wf
    rig.state["checks"][SHA] = [[]]
    expected = "release" not in on and "tags" not in on
    assert bool(report(rig.run())["missing"]) is expected


def test_skip_ci_in_the_head_commit_expects_nothing(rig):
    rig.state["commits"][SHA]["message"] = "docs: typo [skip ci]"
    rig.state["checks"][SHA] = [[]]
    rep = report(rig.run())
    assert rep["missing"] == [] and any("skip CI" in w for w in rep["warnings"])


def test_a_name_holding_an_expression_matches_by_its_literal_prefix(rig):
    rig.state["workflows"]["ci.yml"] = CI.replace(
        "name: Tests", "name: Tests on ${{ matrix.py }}"
    )
    rig.state["checks"][SHA] = [[check("lint"), check("Tests on 3.11")]]
    rep = report(rig.run())
    assert rows(rep)["Tests on 3.11"]["expected"] is True and rep["missing"] == []
    rig.state["workflows"]["ci.yml"] = CI.replace(
        "name: Tests", "name: ${{ matrix.py }}"
    )
    rep = report(rig.run())
    assert rep["unmatched"] == [
        {"workflow": ".github/workflows/ci.yml", "job": "${{ matrix.py }}"}
    ]
    assert rep["verdict"] == "incomplete"


def test_a_reusable_workflows_jobs_match_as_caller_slash_callee(rig):
    rig.state["checks"][SHA] = [GREEN + [check("lint / ruff")]]
    assert rows(report(rig.run()))["lint / ruff"]["expected"] is True


def test_a_check_run_from_another_app_is_a_row_with_no_workflow(rig):
    rig.state["checks"][SHA] = [GREEN + [check("codecov", suite=99)]]
    row = rows(report(rig.run()))["codecov"]
    assert row["workflow"] is None and row["expected"] is False


def test_the_tip_is_read_when_it_isnt_the_sha(rig):
    rig.state["tip"] = TIP
    rig.state["checks"][TIP] = [[check("lint", conclusion="failure", sha=TIP)]]
    rep = report(rig.run())
    assert (
        rep["main_sha"] == TIP and rows(rep, "main")["lint"]["conclusion"] == "failure"
    )
    assert rep["verdict"] == "red"
    assert any(b.startswith("main: ") for b in rep["because"])


def test_over_300_changed_files_makes_a_filtered_workflow_conditional(rig):
    """GitHub's compare stops at 300 files, so 300 read means 300 or more
    (CR 2262): the fake lists 301 and returns 300, as GitHub does."""
    rig.state["files"] = [f"src/f{i}.py" for i in range(301)]
    rig.state["checks"][SHA] = [[]]
    rep = report(rig.run())
    assert rep["missing"] == [] and rep["changed_files"] == 300
    assert any("300 or more" in w and "first 300" in w for w in rep["warnings"])


def test_base_defaults_to_the_first_parent_and_can_be_given(rig):
    assert report(rig.run())["base"] == BASE
    other = "d" * 40
    assert report(rig.run("--base", other))["base"] == other


# ---------------------------------------------------------------- waiting


def test_wait_reads_again_until_nothing_is_pending(rig):
    rig.state["checks"][SHA] = [
        [check("lint", status="queued", conclusion=None)] + GREEN[1:],
        GREEN,
    ]
    rep = report(rig.run("--wait", "30", "--interval", "1"))
    assert rep["verdict"] == "green"
    state = json.loads(rig.path.read_text())
    assert state["reads"]["checks" + SHA] == 2


def test_wait_is_bounded_and_says_so(rig):
    rig.state["checks"][SHA] = [
        [check("lint", status="queued", conclusion=None)] + GREEN[1:]
    ]
    rep = report(rig.run("--wait", "1", "--interval", "1"))
    assert rep["verdict"] == "pending"
    assert "still pending after --wait 1" in rep["warnings"]


def test_the_default_reads_once(rig):
    rig.state["checks"][SHA] = [
        [check("lint", status="queued", conclusion=None)] + GREEN[1:]
    ]
    report(rig.run())
    assert json.loads(rig.path.read_text())["reads"]["checks" + SHA] == 1


# ---------------------------------------------------------------- failures


def test_a_gh_failure_is_exit_2_and_shows_ghs_own_stderr(rig):
    """A gate script keeps gh's whole stderr, not its last line (#398, #410)."""
    rig.state["fail_all"] = "HTTP 401: Bad credentials\nhint: run gh auth login"
    res = rig.run()
    assert res.returncode == 2 and res.stdout == ""
    assert "Bad credentials" in res.stderr and "hint: run gh auth login" in res.stderr


def test_a_404_names_the_token_to_try(rig):
    rig.state["fail_all"] = "HTTP 404: Not Found"
    res = rig.run()
    assert (
        res.returncode == 2 and "check which token reaches acme/widgets" in res.stderr
    )


@pytest.mark.parametrize(
    "args",
    [["--sha", "not-a-sha"], ["--wait", "-1"], ["--repo", "nope"], ["--interval", "0"]],
)
def test_usage_errors_are_exit_1_and_read_nothing(rig, args):
    res = rig.run(*args)
    assert res.returncode == 1, res.stderr
    assert not rig.path.exists() or "calls" not in json.loads(rig.path.read_text())


# ---------------------------------------------------------------- CR 2242–2246


def test_cr_2242_tags_ignore_alone_doesnt_trigger_on_a_branch_push(rig):
    wf = "name: CI\non: {push: {tags-ignore: ['v*']}}\njobs:\n  lint:\n    runs-on: x\n"
    rig.state["workflows"]["ci.yml"] = wf
    rig.state["checks"][SHA] = [[]]
    assert report(rig.run())["missing"] == []


def test_cr_2243_a_pull_request_run_doesnt_stand_for_the_push(rig):
    rig.state["runs"][SHA] = [run_of(".github/workflows/ci.yml", event="pull_request")]
    rep = report(rig.run())
    assert {m["job"] for m in rep["missing"]} == {"lint", "Tests"}
    assert rows(rep)["lint"]["expected"] is False


def test_cr_2244_a_root_commits_filtered_workflow_is_conditional(rig):
    rig.state["commits"][SHA]["parents"] = []
    rig.state["checks"][SHA] = [[]]
    rep = report(rig.run())
    assert rep["base"] is None and rep["changed_files"] is None
    assert rep["missing"] == [] and any("no parent" in w for w in rep["warnings"])


def test_cr_2245_a_queued_run_with_no_jobs_yet_is_pending(rig):
    rig.state["latest"]["7"] = dict(run_of(".github/workflows/ci.yml"), status="queued")
    rig.state["jobs"]["100"] = [[]]
    rep = report(rig.run())
    row = rows(rep, "main-latest")["(no jobs yet)"]
    assert row["status"] == "queued" and rep["verdict"] == "pending"


def test_cr_2246_wait_doesnt_re_read_for_a_name_it_cant_match(rig):
    rig.state["workflows"]["ci.yml"] = CI.replace(
        "name: Tests", "name: ${{ matrix.py }}"
    )
    rep = report(rig.run("--wait", "30", "--interval", "1"))
    assert rep["verdict"] == "incomplete"
    assert json.loads(rig.path.read_text())["reads"]["checks" + SHA] == 1


def test_cr_2258_a_push_run_on_another_branch_doesnt_stand_for_the_branchs(rig):
    """The child's feature branch ran green on the SHA, then was
    fast-forwarded to main before main's push run existed: main's jobs never
    ran, so nothing on the SHA counts for them."""
    rig.state["runs"][SHA] = [run_of(".github/workflows/ci.yml", branch="feat")]
    rep = report(rig.run())
    assert {m["job"] for m in rep["missing"]} == {"lint", "Tests"}
    assert rep["verdict"] == "incomplete"
    assert rows(rep)["lint"]["branch"] == "feat"
    assert rows(rep)["lint"]["expected"] is False


def test_cr_2259_a_fork_prs_run_from_its_own_main_isnt_mains_latest(rig):
    """GitHub's branch= filter matches head_branch, which a fork's pull
    request from its own `main` carries: its passing run must not hide the
    nightly failing on this repo's main."""
    rig.state["workflows"]["nightly.yml"] = NIGHTLY
    rig.state["active"].append(
        {"id": 8, "path": ".github/workflows/nightly.yml", "state": "active"}
    )
    fork = dict(
        run_of(".github/workflows/nightly.yml", event="pull_request", rid=300),
        head_repository={"full_name": "stranger/widgets"},
    )
    own_pr = run_of(".github/workflows/nightly.yml", event="pull_request", rid=250)
    nightly = run_of(
        ".github/workflows/nightly.yml", event="schedule", sha=BASE, rid=200
    )
    rig.state["latest"]["8"] = [fork, own_pr, nightly]
    rig.state["jobs"]["300"] = [[check("e2e")]]
    rig.state["jobs"]["250"] = [[check("e2e")]]
    rig.state["jobs"]["200"] = [[check("e2e", conclusion="failure", sha=BASE)]]
    rep = report(rig.run())
    assert rows(rep, "main-latest")["e2e"]["conclusion"] == "failure"
    assert rep["verdict"] == "red"


def test_cr_2259_no_run_of_its_own_on_the_branch_is_a_warning(rig):
    fork = dict(
        run_of(".github/workflows/ci.yml", event="pull_request", rid=300),
        head_repository={"full_name": "stranger/widgets"},
    )
    rig.state["latest"]["7"] = [fork]
    rig.state["jobs"]["300"] = [[check("lint", conclusion="failure")]]
    rep = report(rig.run())
    assert rows(rep, "main-latest") == {}
    assert rep["verdict"] == "green"
    assert any("ci.yml" in w and "no run of its own" in w for w in rep["warnings"])


def test_cr_2260_a_scheduled_run_a_newer_one_superseded_doesnt_hold_red(rig):
    """Scheduled runs are created on the tip, so every nightly suite stays on
    an idle tip: an old failure, passed since, must not keep it red."""
    nightly = ".github/workflows/nightly.yml"
    rig.state["runs"][SHA] = [
        run_of(".github/workflows/ci.yml"),
        run_of(nightly, suite=3, event="schedule", rid=102),
        run_of(nightly, suite=2, event="schedule", rid=101),
    ]
    rig.state["checks"][SHA] = [
        GREEN + [check("e2e", suite=3), check("e2e", conclusion="failure", suite=2)]
    ]
    rep = report(rig.run())
    assert rep["verdict"] == "green", rep["because"]
    e2e = [r for r in rep["rows"] if r["job"] == "e2e"]
    assert sorted((r["conclusion"], r["superseded"]) for r in e2e) == [
        ("failure", True),
        ("success", False),
    ]


def test_cr_2261_more_check_runs_than_it_reads_says_what_to_do(rig):
    """An idle tip passes 2000 check runs in days; there is no range to
    narrow, so the error names the way out."""
    rig.state["checks"][SHA] = [GREEN * 401]
    res = rig.run()
    assert res.returncode == 2
    assert "narrow the range" not in res.stderr
    assert "by hand" in res.stderr and "#394" in res.stderr


def test_cr_2263_a_disabled_workflows_jobs_arent_expected(rig):
    """A workflow disabled on GitHub never runs, so its push jobs would read
    as never ran at every check-in, and every --wait would run out."""
    rig.state["workflows"]["old.yml"] = "on: push\njobs:\n  t:\n    runs-on: x\n"
    rig.state["active"].append(
        {"id": 9, "path": ".github/workflows/old.yml", "state": "disabled_manually"}
    )
    rep = report(rig.run())
    assert rep["missing"] == [] and rep["verdict"] == "green", rep["because"]
    assert any("old.yml" in w and "disabled_manually" in w for w in rep["warnings"])


DEPENDABOT = "dynamic/dependabot/dependabot-updates"


def test_dependabots_update_job_is_a_row_never_the_verdict(rig):
    """The operator's decision (#394, 2026-11-15): Dependabot's own update
    job failing turned both read-only live checks red, though the child's CI
    was green. It stays in rows, marked advisory, and a warning names it."""
    rig.state["active"].append({"id": 11, "path": DEPENDABOT, "state": "active"})
    rig.state["latest"]["11"] = run_of(DEPENDABOT, event="dynamic", rid=400)
    rig.state["jobs"]["400"] = [[check("Dependabot", conclusion="failure")]]
    rep = report(rig.run())
    row = rows(rep, "main-latest")["Dependabot"]
    assert row["advisory"] is True and row["conclusion"] == "failure"
    assert rep["verdict"] == "green", rep["because"]
    assert any(DEPENDABOT in w and "not judged" in w for w in rep["warnings"])
    assert rows(rep, "main-latest")["lint"]["advisory"] is False


def test_dependabots_update_job_pending_doesnt_hold_the_verdict(rig):
    rig.state["active"].append({"id": 11, "path": DEPENDABOT, "state": "active"})
    rig.state["latest"]["11"] = run_of(DEPENDABOT, event="dynamic", rid=400)
    rig.state["jobs"]["400"] = [
        [check("Dependabot", status="in_progress", conclusion=None)]
    ]
    rep = report(rig.run("--wait", "30", "--interval", "1"))
    assert rep["verdict"] == "green"
    assert json.loads(rig.path.read_text())["reads"]["checks" + SHA] == 1


def test_another_dynamic_workflow_still_counts(rig):
    """Only Dependabot's update job was decided; Dependabot's dependency graph
    and any other managed run still turn the verdict."""
    path = "dynamic/dependabot/update-graph"
    rig.state["active"].append({"id": 12, "path": path, "state": "active"})
    rig.state["latest"]["12"] = run_of(path, event="dynamic", rid=401)
    rig.state["jobs"]["401"] = [[check("submit", conclusion="failure")]]
    rep = report(rig.run())
    assert rep["verdict"] == "red"
    assert rows(rep, "main-latest")["submit"]["advisory"] is False
