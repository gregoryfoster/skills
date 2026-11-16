"""The refresh hook says when its bump leaves a rendered artifact behind (#647).

Measured on a cohort host (2026-11-14): `.github/workflows/context-cadence.yml`
was rendered by `install-cadence.sh` on 2026-09-25. The daily refresh hook
then bumped the vendored skills many times, past #560's `pr` render and the
template's move from `actions/checkout@v5` to `@v7`. Nothing re-ran the
renderer's `--check`, so the workflow stayed on the old template, and after
the host set `.skills/merge_mode` to `pr` it still pushed to the default
branch. It surfaced only when a human asked why.

After a bump that moves the vendored tree, the hook now runs each installed
renderer's `--check` against the bumped tree: today, `install-cadence.sh`
when the cadence workflow exists. Its `re-render: behind` line is the drift;
exit 3 is not, because a clone without the per-clone merge drivers is exit 3
on every check. A drift is logged, said once on stderr, and in `pr` mode
written into the body of a pull request the hook opens. Nothing is
re-rendered: a re-render is a reviewed change.

The consumer rig is tests/utils/refresh_hook_consumer.py's, with
curating-context vendored beside managing-skills: an older `install-cadence.sh`
at the recorded pointer (its template's checkout pin is `@v5`) and the
current one upstream.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.structural.test_refresh_hook_pr_mode import (
    PR_BRANCH,
    _calls,
    _commit_knob,
    _creates,
    _gh,
    _new_day,
    _rule,
)
from tests.utils.refresh_hook_consumer import (
    VENDOR,
    _vendor_commit,
    break_remote,
    build,
    clean_env,
    git,
    gitlink,
    log_text,
    origin_gitlink,
    run_hook,
)
from tests.utils.skill_loader import SKILLS_DIR

INSTALL_CADENCE = SKILLS_DIR / "curating-context" / "scripts" / "install-cadence.sh"
CC_SCRIPTS = "skills/curating-context/scripts"
WF = ".github/workflows/context-cadence.yml"
OLD_PIN = "TEMPLATE_CHECKOUT_MAJOR=5"


def _old_renderer() -> str:
    text = INSTALL_CADENCE.read_text()
    assert "TEMPLATE_CHECKOUT_MAJOR=7" in text, "the template's pin moved"
    return text.replace("TEMPLATE_CHECKOUT_MAJOR=7", OLD_PIN)


def _put_renderer(up: Path, text: str, message: str) -> str:
    path = up / CC_SCRIPTS / "install-cadence.sh"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)
    git(up, "add", "-A")
    git(up, "commit", "-qm", message)
    return git(up, "rev-parse", "HEAD").stdout.strip()


def _print(c) -> str:
    """The workflow the renderer at the recorded pointer writes, as `--print`
    gives it in the consumer's checkout."""
    out = subprocess.run(
        ["bash", str(c.path / VENDOR / CC_SCRIPTS / "install-cadence.sh"), "--print"],
        cwd=c.path,
        capture_output=True,
        text=True,
        env=clean_env(),
        timeout=60,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def _consumer(tmp_path: Path, *, link: bool = True, render: bool = True):
    """The consumer at an older renderer, the workflow it rendered committed,
    and upstream one commit ahead: the current renderer."""
    c = build(tmp_path)
    old = _put_renderer(c.up, _old_renderer(), "vendor: curating-context, @v5")
    sub = c.path / VENDOR
    git(sub, "fetch", "-q", "origin")
    git(sub, "checkout", "-q", old)
    git(c.path, "add", VENDOR)
    if link:
        (c.path / "skills").mkdir(exist_ok=True)
        (c.path / "skills" / "curating-context").symlink_to(
            Path("..") / VENDOR / "skills" / "curating-context"
        )
    if render:
        text = _print(c)
        assert "actions/checkout@v5" in text
        (c.path / WF).parent.mkdir(parents=True, exist_ok=True)
        (c.path / WF).write_text(text)
    git(c.path, "add", "-A")
    git(c.path, "commit", "-qm", "render the cadence at the vendored renderer")
    git(c.path, "push", "-q", "origin", "main")
    c.old = old
    return c


def _upstream_renderer_moves(c) -> str:
    return _put_renderer(
        c.up, INSTALL_CADENCE.read_text(), "vendor: curating-context, @v7"
    )


def test_a_bump_that_leaves_the_workflow_behind_says_so(tmp_path):
    """The issue's reproduction: the bump lands and the workflow is stale.
    Before #647 this run said nothing at all about it."""
    c = _consumer(tmp_path)
    new = _upstream_renderer_moves(c)
    r = run_hook(c)
    assert r.returncode == 0, r.stderr
    assert gitlink(c) == new and origin_gitlink(c) == new, "the bump didn't land"
    assert WF in r.stderr, r.stderr
    assert "skills/curating-context/scripts/install-cadence.sh" in r.stderr, r.stderr
    assert "review the diff" in r.stderr, r.stderr
    log = log_text(c)
    assert re.search(r"renders: .*context-cadence\.yml.*behind", log), log
    # Reported, never re-rendered.
    assert "actions/checkout@v5" in (c.path / WF).read_text()
    assert git(c.path, "status", "--porcelain").stdout == ""


def test_said_once_per_run(tmp_path):
    c = _consumer(tmp_path)
    _upstream_renderer_moves(c)
    r = run_hook(c)
    assert r.stderr.count(WF) == 1, r.stderr


def test_a_bump_that_keeps_the_workflow_current_says_nothing(tmp_path):
    """The renderer at the new pointer writes the installed file back. Exit 3
    from --check (this clone has no merge drivers) is not drift."""
    c = _consumer(tmp_path)
    new = _vendor_commit(c.up, c.v2 + "# fixture: doctor only\n", "vendor: doctor only")
    r = run_hook(c)
    assert r.returncode == 0, r.stderr
    assert gitlink(c) == new
    assert WF not in r.stderr, r.stderr
    assert "renders:" in log_text(c), "the check ran and was logged"


def test_no_installed_workflow_runs_no_check(tmp_path):
    c = _consumer(tmp_path, render=False)
    _upstream_renderer_moves(c)
    r = run_hook(c)
    assert r.returncode == 0, r.stderr
    assert "renders:" not in log_text(c)
    assert WF not in r.stderr


def test_a_renderer_it_cannot_find_is_a_log_line_not_a_failure(tmp_path):
    c = _consumer(tmp_path, link=False)
    new = _upstream_renderer_moves(c)
    r = run_hook(c)
    assert r.returncode == 0, r.stderr
    assert gitlink(c) == new
    assert "no install-cadence.sh" in log_text(c), log_text(c)
    assert WF not in r.stderr, r.stderr


def test_a_renderer_that_fails_is_a_log_line_not_a_failure(tmp_path):
    c = _consumer(tmp_path)
    _put_renderer(c.up, "#!/usr/bin/env bash\necho broken >&2\nexit 9\n", "broken")
    r = run_hook(c)
    assert r.returncode == 0, r.stderr
    log = log_text(c)
    assert re.search(r"renders: could not check .* \(exit 9\)", log), log
    assert "broken" in log_text(c), "the renderer's own words reach the log"
    assert WF not in r.stderr, r.stderr


def test_pr_mode_writes_it_into_the_pull_request_and_says_after_the_merge(tmp_path):
    """The host's case: the knob says pr, the workflow was rendered direct at
    an older template, and the hook proposes a bump. The report must say the
    re-render comes after the merge: the content is restored to main's
    pointer, so a re-render now writes the old template."""
    c = _consumer(tmp_path)
    _commit_knob(c, "pr\n")
    _rule(c)
    state = _gh(c)
    _upstream_renderer_moves(c)
    r = run_hook(c)
    assert r.returncode == 0, r.stderr
    assert len(_creates(state)) == 1, _calls(state)
    calls = "\n".join(_calls(state))
    assert WF in calls, f"the PR body doesn't name the workflow: {calls}"
    assert "after this merges" in calls.split(WF, 1)[1].lower(), calls
    assert WF in r.stderr and PR_BRANCH in r.stderr, r.stderr
    assert "once that pull request merges" in r.stderr.split(WF, 1)[1].lower(), r.stderr
    # The checkout is back on main's pointer; nothing was re-rendered.
    assert "actions/checkout@v5" in (c.path / WF).read_text()


def test_pr_mode_with_a_current_workflow_leaves_the_body_as_it_was(tmp_path):
    c = _consumer(tmp_path)
    _commit_knob(c, "pr\n")
    # Re-rendered pr at the recorded renderer, which the bump doesn't move:
    # the installed file is what a re-render writes, so no drift.
    (c.path / WF).write_text(_print(c))
    git(c.path, "commit", "-qam", "re-render for pr")
    git(c.path, "push", "-q", "origin", "main")
    _rule(c)
    state = _gh(c)
    _vendor_commit(c.up, c.v2 + "# fixture: doctor only\n", "vendor: doctor only")
    r = run_hook(c)
    assert r.returncode == 0, r.stderr
    assert len(_creates(state)) == 1, _calls(state)
    assert WF not in "\n".join(_calls(state))
    assert WF not in r.stderr, r.stderr


def test_pr_mode_opening_the_pr_without_a_push_says_so_too(tmp_path):
    """CR 2298: the branch already carries the bump (yesterday's `gh pr
    create` failed), so today's run pushes nothing and only opens the PR. Its
    body names the drift, and stderr must too, or the session never hears
    of the body's note."""
    c = _consumer(tmp_path)
    _commit_knob(c, "pr\n")
    _rule(c)
    state = _gh(c)
    (state / "create_err").write_text("HTTP 502: the server had a bad day\n")
    _upstream_renderer_moves(c)
    first = run_hook(c)
    assert first.returncode == 0, first.stderr
    assert _creates(state) and not (state / "prs").exists(), _calls(state)
    (state / "create_err").unlink()
    _new_day(c)
    r = run_hook(c)
    assert r.returncode == 0, r.stderr
    assert len(_creates(state)) == 2, _calls(state)
    assert WF in _creates(state)[-1] or WF in "\n".join(_calls(state)), _calls(state)
    assert WF in r.stderr, r.stderr


def test_pr_mode_an_open_pr_updated_in_place_keeps_its_body(tmp_path):
    """CR 2301: a later bump pushed onto the open PR's branch is said on
    stderr, and the PR's body, which the reviewer owns, is never edited."""
    c = _consumer(tmp_path)
    _commit_knob(c, "pr\n")
    (c.path / WF).write_text(_print(c))
    git(c.path, "commit", "-qam", "re-render for pr")
    git(c.path, "push", "-q", "origin", "main")
    _rule(c)
    state = _gh(c)
    _vendor_commit(c.up, c.v2 + "# fixture: doctor only\n", "vendor: doctor only")
    first = run_hook(c)
    assert first.returncode == 0, first.stderr
    assert len(_creates(state)) == 1 and WF not in first.stderr, first.stderr
    _new_day(c)
    _upstream_renderer_moves(c)
    r = run_hook(c)
    assert r.returncode == 0, r.stderr
    assert len(_creates(state)) == 1, _calls(state)
    assert not [x for x in _calls(state) if x.startswith("pr edit")], _calls(state)
    assert WF in r.stderr and PR_BRANCH in r.stderr, r.stderr


def test_direct_mode_a_refused_push_rolls_back_and_says_nothing(tmp_path):
    """CR 2300: a push that fails rolls the bump back, so there is no new
    template to be behind, and the check isn't run."""
    c = _consumer(tmp_path)
    _upstream_renderer_moves(c)
    break_remote(c)
    r = run_hook(c)
    assert r.returncode == 0, r.stderr
    assert gitlink(c) == c.old, "the refused bump wasn't rolled back"
    assert WF not in r.stderr, r.stderr
    assert "renders:" not in log_text(c), log_text(c)
