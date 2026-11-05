"""The map builder and selector behind pre-commit's test selection (#537).

`scripts/gate_select.py build` turns a full run's traces into the map;
`select` turns a commit's changed paths into the test files to run. A rule
that selects too little is a skipped test that would have failed, so every
rule in the plan's table has a case, and so does each way the full suite has
to win: a change shared by every test, a map from another version, a map that
cannot be read.

No API calls. Builds run against synthetic trace files.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "gate_select.py"
_spec = importlib.util.spec_from_file_location("gate_select", SCRIPT)
gs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gs)


def _proc(*argv: str) -> str:
    return json.dumps([".", *argv])


def _build(tmp_path: Path, workers: dict[str, list[dict]]) -> dict:
    prefix = tmp_path / "trace"
    for worker, recs in workers.items():
        (tmp_path / f"trace.{worker}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in recs)
        )
    out = tmp_path / "map.json"
    assert gs.build(str(prefix), str(out), "tree") == 0
    return json.loads(out.read_text())["tests"]


class TestBuild:
    def test_units(self, tmp_path):
        tests = _build(
            tmp_path,
            {
                "gw0": [
                    {
                        "file": "tests/structural/test_a.py",
                        "open": ["skills/shipping-work/SKILL.md", "AGENTS.md"],
                        "list": ["docs"],
                        "exec": ["skills/managing-skills/scripts/doctor.sh"],
                    },
                    {"file": "tests/structural/test_b.py", "list": ["skills"]},
                    {"file": "tests/structural/test_c.py", "list": ["."]},
                ]
            },
        )
        assert tests["tests/structural/test_a.py"] == [
            "AGENTS.md",
            "docs/",
            "skills/managing-skills",
            "skills/shipping-work",
        ]
        assert tests["tests/structural/test_b.py"] == ["*"]
        assert tests["tests/structural/test_c.py"] == ["*"]

    def test_an_existence_check_is_a_file_unit(self, tmp_path):
        tests = _build(
            tmp_path,
            {
                "gw0": [
                    {
                        "file": "tests/structural/test_a.py",
                        "stat": ["AGENTS.md", "skills/shipping-work/SKILL.md"],
                    }
                ]
            },
        )
        assert tests["tests/structural/test_a.py"] == [
            "AGENTS.md",
            "skills/shipping-work",
        ]

    def test_workers_merge(self, tmp_path):
        tests = _build(
            tmp_path,
            {
                "gw0": [{"file": "tests/structural/test_a.py", "open": ["README.md"]}],
                "gw1": [{"file": "tests/structural/test_a.py", "open": ["AGENTS.md"]}],
            },
        )
        assert tests["tests/structural/test_a.py"] == ["AGENTS.md", "README.md"]

    @pytest.mark.parametrize(
        "argv,whole",
        [
            (("git", "-C", "<outside>", "init", "-q"), False),
            (("git", "init", "-q", "<outside>"), False),
            (("git", "ls-files"), True),
            (("git", "-C", ".", "status"), True),
            (("bash", "skills/x/scripts/y.sh", "--help"), False),
            (("bash", "skills/x/scripts/y.sh"), True),
            (("bash", "-c", "cat AGENTS.md"), True),
            (("<outside>", "-c", "print(1)"), True),
            # A script run directly is as free to read the repo as under bash.
            (("skills/x/scripts/y.sh",), True),
            (("/home/u/repo/scripts/pre-ship.sh", "--fast"), True),
            (("./y.sh", "--help"), False),
            (("stat", "-c", "%U", "<outside>"), False),
            (("true",), False),
        ],
    )
    def test_a_subprocess_from_inside_the_repo(self, tmp_path, argv, whole):
        tests = _build(
            tmp_path,
            {"main": [{"file": "tests/structural/test_a.py", "proc": [_proc(*argv)]}]},
        )
        assert ("*" in tests["tests/structural/test_a.py"]) is whole, argv

    def test_no_trace_is_an_error(self, tmp_path):
        assert gs.build(str(tmp_path / "none"), str(tmp_path / "map.json"), "") == 2


MAP_TESTS = {
    "tests/structural/test_whole.py": ["*"],
    "tests/structural/test_ship.py": ["skills/shipping-work"],
    "tests/structural/test_doctor.py": ["skills/managing-skills", "retired-skills"],
    "tests/structural/test_agents.py": ["AGENTS.md"],
    "tests/structural/test_docs.py": ["docs/"],
    "tests/structural/test_gone.py": ["skills/shipping-work"],
}
ON_DISK = sorted(set(MAP_TESTS) - {"tests/structural/test_gone.py"}) + [
    "tests/structural/test_new.py"
]
ALWAYS = ["tests/structural/test_new.py", "tests/structural/test_whole.py"]


@pytest.fixture
def map_path(tmp_path):
    path = tmp_path / "map.json"
    path.write_text(
        json.dumps({"version": gs.VERSION, "tree": "t", "tests": MAP_TESTS})
    )
    return str(path)


class TestSelect:
    @pytest.mark.parametrize(
        "changed,expected",
        [
            (["tests/structural/test_agents.py"], ["tests/structural/test_agents.py"]),
            (["skills/shipping-work/SKILL.md"], ["tests/structural/test_ship.py"]),
            (
                ["skills/managing-skills/scripts/doctor.sh"],
                ["tests/structural/test_doctor.py"],
            ),
            (["retired-skills"], ["tests/structural/test_doctor.py"]),
            (["AGENTS.md"], ["tests/structural/test_agents.py"]),
            (["docs/KNOBS.md"], ["tests/structural/test_docs.py"]),
            (["docs/plans/2026-11-05-x.md"], []),
            (["LICENSE"], []),
        ],
    )
    def test_rules(self, map_path, changed, expected):
        rc, out = gs.select(map_path, changed, ON_DISK)
        assert rc == 0
        assert out == sorted(set(expected) | set(ALWAYS))

    def test_a_deleted_test_is_not_selected(self, map_path):
        rc, out = gs.select(map_path, ["skills/shipping-work/SKILL.md"], ON_DISK)
        assert "tests/structural/test_gone.py" not in out

    @pytest.mark.parametrize(
        "path",
        [
            "tests/utils/skill_loader.py",
            "tests/structural/doc_check_fixtures.py",
            "tests/conftest.py",
            "scripts/structural-tests.sh",
            "pyproject.toml",
            "requirements-test.txt",
            ".pre-commit-config.yaml",
            ".claude/hooks/x.sh",
            ".github/workflows/x.yml",
        ],
    )
    def test_a_shared_change_runs_the_full_suite(self, map_path, path):
        rc, out = gs.select(map_path, ["skills/shipping-work/SKILL.md", path], ON_DISK)
        assert rc == 3 and path in out[0]

    def test_a_map_of_another_version_runs_the_full_suite(self, tmp_path):
        path = tmp_path / "map.json"
        path.write_text(json.dumps({"version": gs.VERSION + 1, "tests": {}}))
        rc, _ = gs.select(str(path), ["AGENTS.md"], ON_DISK)
        assert rc == 3


def _cli(*args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestCli:
    def test_help(self):
        r = _cli("--help")
        assert r.returncode == 0 and "Exit codes" in r.stdout

    def test_select_prints_files(self, map_path, tmp_path):
        root = tmp_path / "root"
        for f in ON_DISK:
            (root / f).parent.mkdir(parents=True, exist_ok=True)
            (root / f).write_text("")
        r = _cli("select", "--map", map_path, "--root", str(root), stdin="AGENTS.md\n")
        assert r.returncode == 0, r.stderr
        assert r.stdout.split() == sorted({"tests/structural/test_agents.py", *ALWAYS})

    def test_full_is_exit_3_with_a_reason(self, map_path):
        r = _cli("select", "--map", map_path, stdin="pyproject.toml\n")
        assert r.returncode == 3
        assert r.stdout.startswith("FULL\t") and "pyproject.toml" in r.stdout

    @pytest.mark.parametrize("line", ["{not json", '{"open": []}', '"a string"'])
    def test_a_malformed_trace_is_exit_2(self, tmp_path, line):
        (tmp_path / "trace.main.jsonl").write_text(line + "\n")
        out = tmp_path / "map.json"
        r = _cli("build", "--trace", str(tmp_path / "trace"), "--out", str(out))
        assert r.returncode == 2, r.stderr
        assert r.stderr.startswith("ERROR:") and "Traceback" not in r.stderr
        assert not out.exists()

    def test_an_unreadable_map_is_exit_2(self, tmp_path):
        r = _cli("select", "--map", str(tmp_path / "missing.json"), stdin="AGENTS.md\n")
        assert r.returncode == 2 and "cannot read the map" in r.stderr

    def test_a_bad_argument_is_exit_2(self):
        assert _cli("select").returncode == 2
