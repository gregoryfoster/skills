"""#572 — the doctor names a `.skills/refresh-skip-hooks` id that
`.pre-commit-config.yaml` does not define.

The refresh hook adds the knob's ids to pre-commit's SKIP for its own commit
(tests/structural/test_refresh_skip_hooks.py). pre-commit ignores a SKIP id it
does not know, so a hook renamed in the config quietly runs on the refresh's
commit again, and a suite that outlasts the hook's 120 s timeout gets it killed,
with nothing said. The doctor is where that drift can be seen.

What this file pins:

- **An id the config does not define is named**, with the reason and the fix.
- **What counts as defined**: an `id:` or an `alias:` (SKIP matches either), in
  list-item or key form, quoted or not, with a trailing comment.
- **The knob's grammar**: whole-line comments, blank lines and CRLF, several ids
  on a line, as the refresh hook reads it. A word the hook refuses (a comma, a
  mid-line `#`) is named as malformed, not as an undefined id, and the comment
  after a `#` is not looked up (CR 1816).
- **A knob with no config to read it** is said.
- **Silent where it has nothing to say**: no knob, or every id defined.
- **Advisory in every mode**: the exit code never moves, `--check-only`
  included.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCTOR = REPO_ROOT / "skills" / "managing-skills" / "scripts" / "doctor.sh"

KNOB = ".skills/refresh-skip-hooks"
MARKER = "does not define"

CONFIG = """\
repos:
  - repo: local
    hooks:
      - id: pytest   # the slow one
        name: pytest
        entry: uv run pytest
        language: system
      - id: "ty"
        alias: 'typecheck'
        entry: uv run ty check
        language: system
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.6
    hooks:
      -   id: ruff
"""


def _clean_env() -> dict:
    """Env without inherited GIT_* vars (docs/STYLE.md, #189)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _doctor(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(DOCTOR), "--no-preflight", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=120,
    )


@pytest.fixture
def consumer(tmp_path: Path) -> Path:
    repo = tmp_path / "consumer"
    repo.mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "init", "-q", "-b", "main"],
        check=True,
        capture_output=True,
        env=_clean_env(),
        timeout=60,
    )
    (repo / ".skills").mkdir()
    (repo / ".pre-commit-config.yaml").write_text(CONFIG)
    return repo


def _knob(repo: Path, text: str) -> None:
    (repo / KNOB).write_bytes(text.encode())


def test_an_id_the_config_does_not_define_is_named(consumer):
    _knob(consumer, "pytest pytests\nmypy\n")
    result = _doctor(consumer)
    assert result.returncode == 0, result.stderr
    assert MARKER in result.stderr, result.stderr
    assert "doctor:   pytests mypy" in result.stderr.splitlines(), result.stderr
    assert "#572" in result.stderr


@pytest.mark.parametrize(
    "ids",
    ["pytest", "ty", "typecheck", "ruff", "pytest ty ruff"],
    ids=["list-item-with-comment", "double-quoted", "alias", "wide-indent", "all"],
)
def test_ids_and_aliases_count_as_defined(consumer, ids):
    _knob(consumer, ids + "\n")
    result = _doctor(consumer)
    assert MARKER not in result.stderr, result.stderr


def test_the_knobs_grammar_is_the_hooks(consumer):
    _knob(consumer, "# slow stages\r\n\r\n  pytest   ty\r\n# end\r\nruff")
    result = _doctor(consumer)
    assert MARKER not in result.stderr, result.stderr


def test_a_knob_with_no_config_is_said(consumer):
    (consumer / ".pre-commit-config.yaml").unlink()
    _knob(consumer, "pytest\n")
    result = _doctor(consumer)
    assert result.returncode == 0, result.stderr
    assert "there is no .pre-commit-config.yaml" in result.stderr, result.stderr


def test_no_knob_is_silent(consumer):
    result = _doctor(consumer)
    assert KNOB not in result.stderr, result.stderr


@pytest.mark.parametrize("mode", [[], ["--check-only"]], ids=["default", "check-only"])
def test_advisory_in_every_mode(consumer, mode):
    baseline = _doctor(consumer, *mode).returncode
    _knob(consumer, "nope\n")
    result = _doctor(consumer, *mode)
    assert MARKER in result.stderr, result.stderr
    assert result.returncode == baseline


@pytest.mark.parametrize(
    ("text", "named"),
    [("pytest,ty\n", "pytest,ty"), ("pytest # the slow one\n", "#")],
    ids=["comma", "trailing-comment"],
)
def test_a_word_the_hook_refuses_is_named_as_malformed(consumer, text, named):
    """CR 1816: reported as an undefined id, `# the slow one` sent the operator
    to rename `#`, `the`, `slow` and `one`."""
    _knob(consumer, text)
    result = _doctor(consumer)
    assert result.returncode == 0, result.stderr
    assert f"is unusable — not hook ids: {named}" in result.stderr, result.stderr
    assert MARKER not in result.stderr, (
        f"a malformed word was looked up as an id:\n{result.stderr}"
    )
