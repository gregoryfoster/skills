"""adopting-dependabot's check-dependabot.sh against a stub gh (#376).

Each scenario is one of the ways a configured Dependabot goes quiet, taken from
the cohort: a full PR limit (notifier#103), a failing update run (watcher#358's
private wheelhouse), the dependency graph off while alerts and security updates
are on (notifier#140), and alerts off. The stub answers ``gh api`` from a
fixture table and fails anything it wasn't given, so no test reaches GitHub.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.utils.skill_loader import SKILLS_DIR

CHECK = SKILLS_DIR / "adopting-dependabot" / "scripts" / "check-dependabot.sh"
REPO = "acme/svc"

STUB = """#!/usr/bin/env python3
import json, os, sys
table = json.load(open(os.environ["GH_STUB_TABLE"]))
args = sys.argv[1:]
assert args[0] == "api", args
key = args[1]
with open(os.environ["GH_STUB_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if key not in table:
    sys.stderr.write("gh: Not Found (HTTP 404)\\n")
    print(json.dumps({"message": "Not Found"}))
    sys.exit(1)
entry = table[key]
if entry.get("body") is not None:
    print(json.dumps(entry["body"]))
if entry.get("status", 200) >= 300:
    sys.stderr.write("gh: %s (HTTP %d)\\n" % (entry.get("message", "error"), entry["status"]))
    sys.exit(1)
"""

CONFIG = """\
version: 2
updates:
  - package-ecosystem: "uv"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 3
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
"""


def _pr(
    n: int,
    ref: str,
    login: str = "dependabot[bot]",
    created: str = "2026-10-20T00:00:00Z",
) -> dict:
    return {
        "number": n,
        "head": {"ref": ref},
        "user": {"login": login},
        "created_at": created,
    }


def _run(title: str, conclusion: str, created: str) -> dict:
    return {
        "path": "dynamic/dependabot/dependabot-updates",
        "display_title": title,
        "conclusion": conclusion,
        "created_at": created,
        "html_url": f"https://github.com/{REPO}/actions/runs/1",
    }


def healthy() -> dict:
    """notifier after notifier#140: every check passes."""
    content = base64.b64encode(CONFIG.encode()).decode()
    return {
        f"repos/{REPO}": {"body": {"default_branch": "main"}},
        f"repos/{REPO}/contents/.github/dependabot.yml?ref=main": {
            "body": {"content": content}
        },
        f"repos/{REPO}/pulls?state=open&per_page=100": {
            "body": [
                _pr(1, "dependabot/uv/fastapi-0.147.0"),
                _pr(2, "feature/x", login="someone"),
            ]
        },
        f"repos/{REPO}/actions/runs?event=dynamic&per_page=100": {
            "body": {
                "workflow_runs": [
                    {
                        "path": "dynamic/dependabot/update-graph",
                        "display_title": "Configured Graph Update",
                    },
                    _run(
                        "uv in / for fastapi - Update #3",
                        "success",
                        "2026-10-26T00:00:00Z",
                    ),
                    _run(
                        "github_actions in /. - Update #2",
                        "success",
                        "2026-10-25T00:00:00Z",
                    ),
                    _run("uv in / - Update #1", "failure", "2026-10-19T00:00:00Z"),
                ]
            }
        },
        f"repos/{REPO}/pulls?state=all&per_page=100&sort=created&direction=desc": {
            "body": [_pr(1, "dependabot/uv/fastapi-0.147.0")]
        },
        f"repos/{REPO}/git/trees/main?recursive=1": {
            "body": {
                "truncated": False,
                "tree": [
                    {"path": "uv.lock", "type": "blob"},
                    {"path": "clients/python/uv.lock", "type": "blob"},
                    {"path": "skills-vendor/x", "type": "commit"},
                ],
            }
        },
        "graphql": {
            "body": {
                "data": {
                    "repository": {
                        "dependencyGraphManifests": {
                            "totalCount": 3,
                            "nodes": [
                                {"filename": "uv.lock"},
                                {"filename": "clients/python/uv.lock"},
                                {"filename": ".github/workflows/ci.yml"},
                            ],
                        }
                    }
                }
            }
        },
        f"repos/{REPO}/dependabot/alerts?state=open&per_page=100": {"body": []},
        f"repos/{REPO}/automated-security-fixes": {
            "body": {"enabled": True, "paused": False}
        },
    }


def _check(tmp_path: Path, table: dict, *args: str) -> tuple[int, dict | None, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "gh"
    stub.write_text(STUB)
    stub.chmod(0o755)
    (tmp_path / "table.json").write_text(json.dumps(table))
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GH_STUB_TABLE": str(tmp_path / "table.json"),
        "GH_STUB_LOG": str(tmp_path / "gh.log"),
    }
    proc = subprocess.run(
        ["bash", str(CHECK), *(args or ("--repo", REPO))],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    out = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, out, proc.stderr


def _by_name(out: dict) -> dict[str, dict]:
    return {c["name"]: c for c in out["checks"]}


def test_a_healthy_repo_passes(tmp_path):
    rc, out, err = _check(tmp_path, healthy())
    assert rc == 0, err
    checks = _by_name(out)
    assert {n: c["status"] for n, c in checks.items()} == {
        "config": "pass",
        "limit:github-actions": "pass",
        "limit:uv": "pass",
        "update-runs": "pass",
        "last-pr": "info",
        "graph": "pass",
        "alerts": "pass",
        "security-updates": "pass",
    }
    assert checks["limit:uv"]["open"] == 1, "only dependabot[bot]'s own branches count"
    assert checks["limit:github-actions"]["limit"] == 5, (
        "an unset limit is the default 5"
    )
    assert "uv in /" in checks["update-runs"]["detail"], (
        "the older failure is superseded"
    )


def test_a_full_pr_limit_fails(tmp_path):
    """notifier#103: three open of three, and nothing more opens, security updates included."""
    table = healthy()
    table[f"repos/{REPO}/pulls?state=open&per_page=100"]["body"] = [
        _pr(n, f"dependabot/uv/p{n}") for n in range(3)
    ]
    rc, out, _ = _check(tmp_path, table)
    assert rc == 1
    limit = _by_name(out)["limit:uv"]
    assert limit["status"] == "fail" and "says so nowhere" in limit["detail"]


def test_a_failing_latest_update_run_fails(tmp_path):
    """watcher#358: the updater can't resolve a private index, and no PR ever opens."""
    table = healthy()
    runs = table[f"repos/{REPO}/actions/runs?event=dynamic&per_page=100"]["body"][
        "workflow_runs"
    ]
    runs.insert(0, _run("uv in / - Update #4", "failure", "2026-10-27T00:00:00Z"))
    rc, out, _ = _check(tmp_path, table)
    assert rc == 1
    assert "uv in /" in _by_name(out)["update-runs"]["detail"]
    assert _by_name(out)["update-runs"]["status"] == "fail"


def test_no_update_run_at_all_fails(tmp_path):
    table = healthy()
    table[f"repos/{REPO}/actions/runs?event=dynamic&per_page=100"]["body"] = {
        "workflow_runs": []
    }
    rc, out, _ = _check(tmp_path, table)
    assert rc == 1 and _by_name(out)["update-runs"]["status"] == "fail"


def test_graph_off_fails_even_with_alerts_and_security_updates_on(tmp_path):
    """notifier#140: 0 alerts, ever, across three rounds of transitive advisories."""
    table = healthy()
    manifests = table["graphql"]["body"]["data"]["repository"][
        "dependencyGraphManifests"
    ]
    manifests.update(totalCount=0, nodes=[])
    rc, out, _ = _check(tmp_path, table)
    assert rc == 1
    graph = _by_name(out)["graph"]
    assert graph["status"] == "fail" and "graph is off" in graph["detail"]
    assert _by_name(out)["alerts"]["status"] == "pass"
    assert _by_name(out)["security-updates"]["status"] == "pass"


def test_one_lockfile_missing_from_the_graph_fails(tmp_path):
    """Two repos needed the graph switched on individually after the org-wide action."""
    table = healthy()
    manifests = table["graphql"]["body"]["data"]["repository"][
        "dependencyGraphManifests"
    ]
    manifests["nodes"] = [{"filename": "uv.lock"}]
    rc, out, _ = _check(tmp_path, table)
    assert rc == 1
    assert _by_name(out)["graph"]["missing"] == ["clients/python/uv.lock"]


def test_alerts_disabled_fails(tmp_path):
    table = healthy()
    table[f"repos/{REPO}/dependabot/alerts?state=open&per_page=100"] = {
        "status": 403,
        "body": {"message": "Dependabot alerts are disabled for this repository."},
    }
    rc, out, _ = _check(tmp_path, table)
    assert rc == 1 and _by_name(out)["alerts"]["status"] == "fail"


def test_a_least_privilege_token_reads_unread_never_pass(tmp_path):
    """Without Administration: read, the toggles are unread, and unread doesn't fail the run."""
    table = healthy()
    table[f"repos/{REPO}/dependabot/alerts?state=open&per_page=100"] = {
        "status": 403,
        "body": {"message": "Resource not accessible by personal access token"},
    }
    table[f"repos/{REPO}/vulnerability-alerts"] = {
        "status": 403,
        "body": {"message": "Must have admin rights"},
    }
    table[f"repos/{REPO}/automated-security-fixes"] = {
        "status": 403,
        "body": {"message": "Must have admin rights"},
    }
    rc, out, _ = _check(tmp_path, table)
    assert rc == 0
    assert _by_name(out)["alerts"]["status"] == "unread"
    assert _by_name(out)["security-updates"]["status"] == "unread"
    assert _by_name(out)["graph"]["status"] == "pass", (
        "the manifest count is what such a token can read"
    )


def test_security_updates_off_or_paused_fails(tmp_path):
    for state in (
        {"enabled": False, "paused": False},
        {"enabled": True, "paused": True},
    ):
        table = healthy()
        table[f"repos/{REPO}/automated-security-fixes"]["body"] = state
        rc, out, _ = _check(tmp_path, table)
        assert rc == 1 and _by_name(out)["security-updates"]["status"] == "fail", state


@pytest.mark.parametrize(
    ("config", "why"),
    [
        (None, "no .github/dependabot.yml"),
        ("version: 1\nupdates: []\n", "version is not 2"),
        (
            'version: 2\nupdates:\n  - package-ecosystem: uv\n    directory: "/"\n',
            "no schedule.interval",
        ),
        (
            "version: 2\nupdates:\n  - package-ecosystem: uv\n    schedule: {interval: weekly}\n",
            "no directory",
        ),
    ],
    ids=["absent", "version-1", "no-interval", "no-directory"],
)
def test_a_broken_config_fails_and_skips_the_limit_reading(tmp_path, config, why):
    table = healthy()
    key = f"repos/{REPO}/contents/.github/dependabot.yml?ref=main"
    if config is None:
        del table[key]
    else:
        table[key]["body"]["content"] = base64.b64encode(config.encode()).decode()
    rc, out, _ = _check(tmp_path, table)
    assert rc == 1
    checks = _by_name(out)
    assert checks["config"]["status"] == "fail" and why in checks["config"]["detail"]
    assert not any(n.startswith("limit:") for n in checks)
    assert "graph" in checks, "the security path is read whether or not a config exists"


def test_the_yaml_spelling_is_read(tmp_path):
    table = healthy()
    table[f"repos/{REPO}/contents/.github/dependabot.yaml?ref=main"] = table.pop(
        f"repos/{REPO}/contents/.github/dependabot.yml?ref=main"
    )
    rc, out, _ = _check(tmp_path, table)
    assert rc == 0 and _by_name(out)["config"]["status"] == "pass"


def test_every_call_is_a_read(tmp_path):
    _check(tmp_path, healthy())
    for line in (tmp_path / "gh.log").read_text().splitlines():
        args = json.loads(line)
        assert not {"-X", "--method", "--input"} & set(args), args
        if args[1] != "graphql":
            assert not {"-f", "-F", "--field", "--raw-field"} & set(args), (
                f"a field makes gh POST: {args}"
            )


def test_usage_errors_exit_2(tmp_path):
    rc, _, err = _check(tmp_path, healthy(), "--repo", "not a repo")
    assert rc == 2 and "OWNER/REPO" in err
    rc, _, err = _check(tmp_path, {}, "--repo", "acme/gone")
    assert rc == 2 and "acme/gone" in err
    proc = subprocess.run(["bash", str(CHECK)], capture_output=True, text=True)
    assert proc.returncode == 2 and "--repo" in proc.stderr
