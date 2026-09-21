"""#301 — resolve each script; never reuse one script's directory for another.

[#63] replaced a hardcoded wrong path with a probe, and the probe was correct
for the one script it probed for. Every skill whose later steps run *other*
scripts then reused the directory it found: Step 1 probed `pre-ship.sh`,
printed `SKILL_SCRIPTS=<dir>`, and Steps 1.5, 2, 4, 5 and 6 ran
`<dir>/doc-check.sh`, `<dir>/check-status.sh` and so on.

That holds only while `scripts/` is all-or-nothing, and the supported override
is not. docs/STYLE.md's "wrap, don't fork" recipe ([#105]) puts ONE file in a
project's `scripts/` — a `pre-ship.sh` wrapper that loads env and delegates
back to the vendored gate. Three of the thirteen cohort repos keep a
`scripts/pre-ship.sh` and none of the skill's other five scripts
(CannObserv/watcher and usa-wa a wrapper, power-map a fork; listed through the
API 2026-09-21), so Step 1 printed `SKILL_SCRIPTS=scripts` and every later
step exited 127 on "No such file or directory". No step anticipated 127, and
the two that did not run were the two whose purpose is to refuse a silent pass:
Step 1.5's doc check and Step 2's working-tree verdict ([#257]).

The fix resolves per script. A publishing block lists every script the skill
runs, clears `SD` for each, probes `scripts/` → `.claude/skills/<n>/scripts/` →
`~/.claude/skills/<n>/scripts/` for THAT file, and prints `<name.sh>=<path>`.
Later steps substitute `<name.sh>`; there is no directory placeholder left to
reuse. A script found nowhere stops the block by name — at Step 1, where the
Iron Law can still act, rather than as a 127 five steps later.

What this file pins:

- **Behaviour, on watcher's own layout.** A project `scripts/` holding only
  `pre-ship.sh`: the wrapper wins for the gate and runs, and every other script
  resolves to the skill. This is also #105's override kept working.
- **A project copy wins for its own script only**, in every publishing skill.
- **A script found nowhere stops the block, naming it** — including when the
  script before it resolved from `scripts/`, which is the case a missing
  per-iteration `SD=` reset would silently answer with the wrong directory.
  Under zsh as well as bash, since the Bash tool runs in zsh wherever that is
  the login shell (macOS's default): zsh never expands the word of
  `${SD:?word}`, so the name that used to live there printed as a literal
  `$S` (CR 4). The single-script blocks (`reviewing-*`) are held to the same.
- **Every placeholder has a published path, and every published path ships.**
- **No directory placeholder survives** in a skill that carries a block.
- **The steps that enumerate exit codes say what 127 means**, so "not found"
  cannot read as "nothing to check".
- **The cadence workflow, the same way.** curating-context's CI job exports
  one path per script (`MEASURE_CONTEXT_SH`, …) rather than one directory for
  all of them, and fails its resolve step naming a script found nowhere.

[#63]: https://github.com/gregoryfoster/skills/issues/63
[#105]: https://github.com/gregoryfoster/skills/issues/105
[#257]: https://github.com/gregoryfoster/skills/issues/257
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

MARKER = "<!-- skill:required id=skill-scripts -->"

# The loop line that identifies a resolution block at all — the same literal
# test_content_invariants.py and test_override_required_fragments.py key on.
RESOLUTION_LOOP = (
    'for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do'
)

# A publishing block iterates a list. Deliberately NOT anchored on the `SD=`
# that must follow `do`: test_each_pass_clears_sd pins that as text, and the
# behavioural tests must still parse a block that lost it, to show its effect.
LIST_HEAD = re.compile(r"^for S in ([^;\n]+); do\b", re.M)

# A substitution site: `bash "<doc-check.sh>"` in a fence or in inline code.
PLACEHOLDER = re.compile(r'"<([A-Za-z0-9_.-]+\.sh)>"')

# One line of a publishing block's output.
RESOLVED = re.compile(r"^<([A-Za-z0-9_.-]+\.sh)>=(.+)$", re.M)

SHIPPING = [
    "shipping-work",
    "shipping-work-php",
    "shipping-work-python-click",
    "shipping-work-python-fastapi",
]

# Every skill whose later steps substitute a resolved script path. Declared, so
# a block that stops parsing as a list fails here instead of dropping out of
# the parametrization below.
PUBLISHERS = sorted(
    SHIPPING
    + ["auditing-ci-cost", "curating-context", "using-git-worktrees", "writing-plans"]
)


def _skill_md(name: str) -> Path:
    return SKILLS_DIR / name / "SKILL.md"


def _docs(name: str) -> list[Path]:
    """SKILL.md plus every reference it can load — both carry call sites."""
    skill_dir = SKILLS_DIR / name
    return [skill_dir / "SKILL.md", *sorted(skill_dir.glob("references/**/*.md"))]


def _block(name: str) -> str:
    """The armed resolution block, fence stripped."""
    lines = _skill_md(name).read_text().splitlines()
    start = lines.index(MARKER)
    assert lines[start + 1].startswith("```"), f"{name}: {MARKER} arms no fence"
    end = next(i for i in range(start + 2, len(lines)) if lines[i].startswith("```"))
    return "\n".join(lines[start + 2 : end]) + "\n"


def _listed(name: str) -> list[str]:
    m = LIST_HEAD.search(_block(name))
    assert m, (
        f"{name}/SKILL.md's resolution block does not iterate a script list "
        "(`for S in a.sh b.sh; do SD=`). A block that resolves one anchor and "
        "publishes its directory is the #301 shape: every later step then runs "
        "a DIFFERENT script from a directory nobody checked holds it."
    )
    return m.group(1).split()


def _ships(name: str) -> list[str]:
    return sorted(p.name for p in (SKILLS_DIR / name / "scripts").glob("*.sh"))


def _stub(path: Path, origin: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/usr/bin/env bash\necho "ran:{origin}:{path.name}"\n')
    path.chmod(0o755)


def _project(
    tmp_path: Path,
    name: str,
    project_scripts: tuple[str, ...] = (),
    missing: tuple[str, ...] = (),
    vendored: str = "",
) -> Path:
    """A consumer checkout: the skill vendored under .claude/skills/<name>/
    (or `vendored`), shipping stubs named exactly as the real skill's scripts,
    plus whatever the project keeps in its own scripts/."""
    proj = tmp_path / "proj"
    proj.mkdir()
    skill_scripts = proj / (vendored or f".claude/skills/{name}/scripts")
    for script in _ships(name):
        if script not in missing:
            _stub(skill_scripts / script, "skill")
    for script in project_scripts:
        _stub(proj / "scripts" / script, "project")
    (tmp_path / "home").mkdir()
    return proj


# The shells a block must behave the same in. The Bash tool runs commands in
# the user's login shell when that is bash or zsh, and zsh is macOS's default.
SHELLS = ["bash", "zsh"]
_ZSH_MISSING = (
    "zsh is not on PATH, so the resolution blocks were NOT run under zsh — the "
    "shell the Bash tool uses wherever it is the login shell, macOS's default. "
    "Install zsh to get that coverage; set ZSH_REQUIRED=1 to make its absence "
    "a failure instead of a skip."
)


def _argv(shell: str) -> list[str]:
    if shell == "zsh" and not shutil.which("zsh"):
        if os.environ.get("ZSH_REQUIRED", "") not in ("", "0"):
            pytest.fail(_ZSH_MISSING)
        pytest.skip(_ZSH_MISSING)
    # -f: no startup files, so a developer's own .zshrc cannot decide the run.
    return ["zsh", "-f", "-c"] if shell == "zsh" else ["bash", "-c"]


def _run(name: str, proj: Path, shell: str = "bash") -> subprocess.CompletedProcess:
    # HOME is the fixture's, so the third probe cannot find a real user-level
    # install of the skill on the machine running the suite.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["HOME"] = str(proj.parent / "home")
    return subprocess.run(
        [*_argv(shell), _block(name)],
        cwd=str(proj),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def _resolved(stdout: str) -> dict[str, str]:
    return dict(RESOLVED.findall(stdout))


def _skill_path(name: str, script: str) -> str:
    return f".claude/skills/{name}/scripts/{script}"


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("name", SHIPPING)
def test_the_watcher_layout_keeps_its_wrapper_and_resolves_the_rest(
    name: str, shell: str, tmp_path: Path
) -> None:
    """The reported repro, and #105's override, in one fixture.

    `scripts/` holds a `pre-ship.sh` wrapper and nothing else. The wrapper must
    win for the gate — it is the documented override point — and must be the
    one script this block runs. Every other script must resolve to the skill:
    under the old block they all resolved to `scripts/` and exited 127.
    """
    proj = _project(tmp_path, name, project_scripts=("pre-ship.sh",))
    r = _run(name, proj, shell)
    assert r.returncode == 0, f"stdout={r.stdout!r}\nstderr={r.stderr!r}"
    resolved = _resolved(r.stdout)
    assert sorted(resolved) == sorted(_listed(name)), (
        f"{name}: Step 1 must print one `<name.sh>=<path>` line per script "
        f"its later steps run; it printed {resolved}. A single directory "
        "(`SKILL_SCRIPTS=scripts`) is what sent every later step to 127."
    )
    assert resolved["pre-ship.sh"] == "scripts/pre-ship.sh", (
        f"{name}: the project's pre-ship.sh wrapper no longer wins — the "
        f"override docs/STYLE.md documents (#105) is dead. Printed: {resolved}"
    )
    for script in _listed(name):
        if script == "pre-ship.sh":
            continue
        assert resolved.get(script) == _skill_path(name, script), (
            f"{name}: {script} resolved to {resolved.get(script)!r}, not the "
            "skill's own copy. A project scripts/ holding only a pre-ship.sh "
            "wrapper must not send later steps looking beside it (#301)."
        )
    ran = re.findall(r"^ran:.*$", r.stdout, re.M)
    assert ran == ["ran:project:pre-ship.sh"], (
        f"{name}: Step 1 must run the project's pre-ship.sh wrapper and "
        f"nothing else; it ran {ran}. The block runs the script it resolved "
        "LAST, so pre-ship.sh must end the list."
    )


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("name", PUBLISHERS)
def test_a_project_copy_wins_for_its_own_script_only(
    name: str, shell: str, tmp_path: Path
) -> None:
    first = _listed(name)[0]
    r = _run(name, _project(tmp_path, name, project_scripts=(first,)), shell)
    assert r.returncode == 0, f"stdout={r.stdout!r}\nstderr={r.stderr!r}"
    resolved = _resolved(r.stdout)
    expected = {
        s: (f"scripts/{s}" if s == first else _skill_path(name, s))
        for s in _listed(name)
    }
    assert resolved == expected, (
        f"{name}: with only scripts/{first} in the project, resolution must "
        f"send {first} there and every other script to the skill.\n"
        f"expected {expected}\nprinted  {resolved}"
    )


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("name", PUBLISHERS)
def test_a_script_found_nowhere_stops_the_block_by_name(
    name: str, shell: str, tmp_path: Path
) -> None:
    """At Step 1, not as a 127 mid-procedure — and never with the previous
    script's directory.

    The script before the missing one resolves from `scripts/`, so a block
    that forgot to clear SD per script would print `scripts/<missing>` with
    exit 0 — #301 in miniature, reintroduced by the fix.

    Named in zsh too. The name used to ride in `${SD:?$S not found in …}`,
    whose word zsh prints verbatim: the block stopped, but on
    `SD: $S not found in scripts/, .claude/skills/$N/scripts/, …`.
    """
    listed = _listed(name)
    if len(listed) > 1:
        missing, project_scripts = listed[1], (listed[0],)
    else:
        # One script: nothing precedes it to leak a directory, so this is only
        # the found-nowhere half.
        missing, project_scripts = listed[0], ()
    proj = _project(tmp_path, name, project_scripts=project_scripts, missing=(missing,))
    r = _run(name, proj, shell)
    assert r.returncode != 0, (
        f"{name} ({shell}): {missing} exists nowhere, yet the block exited 0 "
        f"and printed {_resolved(r.stdout)}. It must stop here, naming it."
    )
    _assert_names_what_it_missed(name, shell, missing, r.stderr)
    assert missing not in _resolved(r.stdout), r.stdout
    assert "ran:" not in r.stdout, (
        f"{name}: a script ran although resolution had failed: {r.stdout!r}"
    )


def _assert_names_what_it_missed(name: str, shell: str, missing: str, stderr: str):
    assert missing in stderr, (
        f"{name} ({shell}): the failure must name the script that was not "
        f"found; stderr={stderr!r}"
    )
    assert f".claude/skills/{name}/scripts/" in stderr, (
        f"{name} ({shell}): the failure must name where it looked, with the "
        f"skill's name filled in; stderr={stderr!r}"
    )


# Every block that resolves one script and runs it, publishing nothing.
SINGLES = sorted(
    p.parent.name
    for p in SKILLS_DIR.glob("*/SKILL.md")
    if RESOLUTION_LOOP in p.read_text() and p.parent.name not in PUBLISHERS
)


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("name", SINGLES)
def test_a_single_script_found_nowhere_stops_the_block_by_name(
    name: str, shell: str, tmp_path: Path
) -> None:
    """The same promise in the one-script form: its guard carried the searched
    paths in `${SD:?…}`'s word, which zsh printed with `$N` unexpanded."""
    m = re.search(r"^N=\S+ S=(\S+\.sh) SD=$", _block(name), re.M)
    assert m, f"{name}: no `N=… S=<script>.sh SD=` header in its block"
    script = m.group(1)
    r = _run(name, _project(tmp_path, name, missing=(script,)), shell)
    assert r.returncode != 0, (
        f"{name} ({shell}): {script} exists nowhere, yet the block exited 0: "
        f"stdout={r.stdout!r}"
    )
    _assert_names_what_it_missed(name, shell, script, r.stderr)
    assert "ran:" not in r.stdout, r.stdout


# ---------------------------------------------------------------------------
# The text the behaviour depends on
# ---------------------------------------------------------------------------


def test_every_publisher_is_declared() -> None:
    """PUBLISHERS is the parametrization; discovery is the backstop.

    A skill whose SKILL.md substitutes `<name.sh>` placeholders publishes
    paths, so it must be listed — and a listed skill must still carry one.
    """
    using = {
        p.parent.name
        for p in SKILLS_DIR.glob("*/SKILL.md")
        if RESOLUTION_LOOP in p.read_text() and PLACEHOLDER.search(p.read_text())
    }
    assert using == set(PUBLISHERS), (
        f"skills substituting <name.sh> placeholders: {sorted(using)}; "
        f"declared PUBLISHERS: {PUBLISHERS}"
    )


@pytest.mark.parametrize("name", PUBLISHERS)
def test_each_pass_clears_sd(name: str) -> None:
    """Without it, a script found nowhere inherits the previous script's
    directory and prints a path that does not exist, with exit 0 — the
    found-nowhere test above shows the effect; this names the line."""
    _listed(name)
    assert re.search(r"^for S in [^;\n]+; do SD=$", _block(name), re.M), (
        f"{name}/SKILL.md's script loop must clear SD at the top of every "
        "pass: `for S in …; do SD=`."
    )


@pytest.mark.parametrize("name", PUBLISHERS)
def test_every_placeholder_has_a_published_path(name: str) -> None:
    listed = set(_listed(name))
    for doc in _docs(name):
        unpublished = sorted(set(PLACEHOLDER.findall(doc.read_text())) - listed)
        assert not unpublished, (
            f"{doc.relative_to(SKILLS_DIR)} substitutes {unpublished}, which "
            f"{name}'s resolution block never prints. Add each to its "
            "`for S in …` list — a placeholder nobody printed has nothing to "
            "substitute, and an agent will improvise a path."
        )


@pytest.mark.parametrize("name", PUBLISHERS)
def test_every_published_path_ships_and_is_used(name: str) -> None:
    listed = _listed(name)
    assert len(listed) == len(set(listed)), f"{name} lists a script twice: {listed}"
    absent = sorted(set(listed) - set(_ships(name)))
    assert not absent, (
        f"{name} resolves {absent}, which its scripts/ does not ship — the "
        "block would stop every run on a vendor typo."
    )
    used = set()
    for doc in _docs(name):
        used |= set(PLACEHOLDER.findall(doc.read_text()))
    runs_last = 'bash "${SD:?}/$S"' in _block(name)
    idle = sorted(set(listed) - used - ({listed[-1]} if runs_last else set()))
    assert not idle, (
        f"{name} resolves {idle} but no step substitutes it. A listed script "
        "that nothing runs can still stop the block when absent; drop it."
    )


@pytest.mark.parametrize(
    "name",
    sorted(
        p.parent.name
        for p in SKILLS_DIR.glob("*/SKILL.md")
        if RESOLUTION_LOOP in p.read_text()
    ),
)
def test_no_directory_placeholder_survives(name: str) -> None:
    """`<SKILL_SCRIPTS>` named a directory, which is what made reuse possible.

    Scoped to the agent-facing placeholder. `curating-context`'s cadence
    workflow is a CI surface with no placeholders; the cadence tests below
    hold it to the same rule.
    """
    assert 'echo "SKILL_SCRIPTS=' not in _skill_md(name).read_text(), (
        f"{name}/SKILL.md still publishes one directory for all its scripts. "
        "One directory resolved for one script and reused for others is #301."
    )
    for doc in _docs(name):
        assert '"<SKILL_SCRIPTS>/' not in doc.read_text(), (
            f"{doc.relative_to(SKILLS_DIR)} still substitutes the "
            "<SKILL_SCRIPTS> directory; substitute the per-script "
            '`"<name.sh>"` placeholder its block prints (#301).'
        )


def _section(body: str, heading: str) -> str:
    start = body.index(heading)
    nxt = body.find("\n### ", start + len(heading))
    return body[start : nxt if nxt != -1 else len(body)]


@pytest.mark.parametrize("name", SHIPPING)
@pytest.mark.parametrize(
    "heading",
    [
        "### Step 1.5 — Documentation spot-check",
        "### Step 2 — Ensure a clean working tree",
    ],
)
def test_steps_that_enumerate_exit_codes_say_127_is_no_verdict(
    name: str, heading: str
) -> None:
    """Step 1.5 documents 1 and 2, Step 2 documents 2. A reader following that
    text had no branch for 127 and could read "No such file or directory" as
    "nothing to check" — the step whose purpose is to refuse a silent pass
    silently not running (#301)."""
    section = _section(_skill_md(name).read_text(), heading)
    assert "127" in section, (
        f"{name}/SKILL.md '{heading}' enumerates exit codes but not 127, so a "
        "script that never ran has no documented reading but 'not a failure'."
    )


# ---------------------------------------------------------------------------
# The cadence workflow: the same rule on a CI surface
# ---------------------------------------------------------------------------
#
# curating-context's scheduled job kept the #301 shape after the SKILL.md fix:
# its resolve step probed measure-context.sh, exported that directory as
# SKILL_SCRIPTS through $GITHUB_ENV, and later steps ran check-seams.sh,
# check-counts.sh, record-telemetry.sh and merge-token-counts.sh from it. A
# project scripts/ holding measure-context.sh alone sent all four there.
#
# One render covers all three copies: references/cadence/workflow.md and this
# repo's .github/workflows/context-cadence.yml are pinned byte-for-byte to
# `install-cadence.sh --print` elsewhere in the suite.

INSTALL_CADENCE = SKILLS_DIR / "curating-context" / "scripts" / "install-cadence.sh"
CADENCE = "curating-context"
RESOLVE_STEP = "Resolve the skill scripts"

# How a later step expands a path the resolve step exported: "$CHECK_SEAMS_SH".
EXPORTED_PATH = re.compile(r"\$\{?([A-Z][A-Z0-9_]*_SH)\b")


def _env_name(script: str) -> str:
    """The variable a script's path is exported as: measure-context.sh ->
    MEASURE_CONTEXT_SH."""
    return re.sub(r"[.-]", "_", script).upper()


def _cadence_steps(tmp_path: Path) -> dict[str, str]:
    """Each named `run:` block of the workflow, as rendered."""
    render = tmp_path / "render"
    render.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "init", "-q"], cwd=render, check=True, env=env)
    r = subprocess.run(
        ["bash", str(INSTALL_CADENCE), "--print", "--cron", "0 15 * * 1"],
        cwd=str(render),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert r.returncode == 0, r.stderr
    steps = yaml.safe_load(r.stdout)["jobs"]["measure"]["steps"]
    return {s["name"]: s["run"] for s in steps if s.get("name") and s.get("run")}


def _cadence_listed(steps: dict[str, str]) -> list[str]:
    m = LIST_HEAD.search(steps[RESOLVE_STEP])
    assert m, (
        f"the cadence workflow's '{RESOLVE_STEP}' step does not iterate a "
        "script list (`for S in a.sh b.sh; do SD=`). Resolving one script and "
        "exporting its directory is the #301 shape: every later step then runs "
        "a DIFFERENT script from a directory nobody checked holds it."
    )
    return m.group(1).split()


def _resolve(
    steps: dict[str, str], proj: Path
) -> tuple[subprocess.CompletedProcess, dict[str, str]]:
    """Run the rendered resolve step as Actions does (`bash -e`), and read
    back what it exported for the later steps."""
    gh_env = proj.parent / "github_env"
    gh_env.write_text("")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GITHUB_ENV"] = str(gh_env)
    r = subprocess.run(
        ["bash", "-e", "-c", steps[RESOLVE_STEP]],
        cwd=str(proj),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    exported = dict(
        line.split("=", 1) for line in gh_env.read_text().splitlines() if "=" in line
    )
    return r, exported


@pytest.mark.parametrize(
    "vendored", [f".claude/skills/{CADENCE}/scripts", f"skills/{CADENCE}/scripts"]
)
def test_the_cadence_resolves_each_script_on_its_own(
    vendored: str, tmp_path: Path
) -> None:
    """scripts/ holds measure-context.sh and nothing else. It wins for that
    script alone; every other script resolves to the vendored skill, through
    either of the workflow's two skill locations."""
    steps = _cadence_steps(tmp_path)
    listed = _cadence_listed(steps)
    assert "measure-context.sh" in listed, listed
    proj = _project(
        tmp_path, CADENCE, project_scripts=("measure-context.sh",), vendored=vendored
    )
    r, exported = _resolve(steps, proj)
    assert r.returncode == 0, f"stdout={r.stdout!r}\nstderr={r.stderr!r}"
    expected = {
        _env_name(s): (
            f"scripts/{s}" if s == "measure-context.sh" else f"{vendored}/{s}"
        )
        for s in listed
    }
    assert exported == expected, (
        "with only scripts/measure-context.sh in the project, the cadence must "
        "export that one path from scripts/ and every other script's from the "
        f"skill (#301).\nexpected {expected}\nexported {exported}"
    )


def test_a_cadence_script_found_nowhere_fails_the_resolve_step_by_name(
    tmp_path: Path,
) -> None:
    """The script before the missing one resolves from scripts/, so a loop
    that kept the previous pass's directory would export a path that does not
    exist, exit 0, and fail steps later as a 127."""
    steps = _cadence_steps(tmp_path)
    listed = _cadence_listed(steps)
    missing = listed[1]
    proj = _project(tmp_path, CADENCE, project_scripts=(listed[0],), missing=(missing,))
    r, exported = _resolve(steps, proj)
    assert r.returncode != 0, (
        f"{missing} exists nowhere, yet the resolve step exited 0 and "
        f"exported {exported}. It must fail here, naming it."
    )
    assert missing in r.stderr, (
        f"the failure must name the script that was not found; stderr={r.stderr!r}"
    )
    assert _env_name(missing) not in exported, exported


def test_every_cadence_step_runs_a_path_the_resolve_step_exported(
    tmp_path: Path,
) -> None:
    """The list is the contract between the resolve step and the rest. A step
    expanding a name nobody exported runs `bash ""`; a listed script nothing
    runs can still fail the job when absent. And no directory variable is
    left for a step to join a different script onto."""
    steps = _cadence_steps(tmp_path)
    listed = _cadence_listed(steps)
    assert len(listed) == len(set(listed)), f"a script is listed twice: {listed}"
    absent = sorted(set(listed) - set(_ships(CADENCE)))
    assert not absent, f"the cadence resolves {absent}, which {CADENCE} does not ship"
    later = "\n".join(run for name, run in steps.items() if name != RESOLVE_STEP)
    exported = {_env_name(s) for s in listed}
    used = set(EXPORTED_PATH.findall(later))
    assert used == exported, (
        f"steps expand {sorted(used)}; the resolve step exports {sorted(exported)}"
    )
    joined = re.findall(r'"\$\{?[A-Za-z_]+\}?/[^"]*\.sh', "\n".join(steps.values()))
    assert not joined, (
        f"a step joins a script name onto a directory variable: {joined}. "
        "One directory resolved for one script and reused for others is #301."
    )
