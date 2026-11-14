"""deploying-releases' core, end to end against a throwaway root (#372).

The core is skills/deploying-releases/assets/deploy.sh, installed into a
consumer as scripts/deploy.sh. The world (deploying_releases_rig) is broker's
harness widened to the core's targets, hooks and restarts. Each class pins one
part of the contract in docs/plans/2026-11-13-deploying-releases.md; the
behaviour broker's own 183 tests pin is ported where the core kept it.

Linux only (GNU stat, util-linux flock): skipped on macOS, run in a container
as the rig's docstring shows.
"""

from __future__ import annotations

import fcntl
import json
import os

import pytest

from tests.structural.deploying_releases_rig import (
    API,
    BACKUP,
    HOOKS,
    JOB,
    PROBE,
    TEMPLATE,
    WHEELHOUSE_LOCK,
    World,
    assert_ok,
    ci_run,
    index_of,
    installs,
    require_linux_tools,
    restarts,
    unit,
)


@pytest.fixture
def world(tmp_path):
    require_linux_tools()
    w = World(tmp_path)
    yield w
    w.cleanup()


def hooks_with(*lines: str) -> str:
    return HOOKS + "\n".join(lines) + "\n"


class TestADeploy:
    def test_puts_origin_main_on_live(self, world):
        world.go_live()
        result = world.run()
        assert_ok(result)
        assert world.target() == f"releases/{world.build(world.main[-1])}"

    def test_the_release_is_the_commit_read_only_and_roots(self, world):
        sha = world.go_live()
        assert_ok(world.run())
        release = world.release(sha)
        assert (release / "version.txt").read_text() == "main-2"
        assert not os.access(release / "version.txt", os.W_OK)
        assert world.root_owned(release)
        assert (release / "REVISION").read_text().strip() == world.build(sha)
        assert "chown-of-writable" not in "\n".join(world.calls())

    def test_the_sync_is_locked_no_dev_copied_on_the_system_python_through_the_wrapper(
        self, world
    ):
        sha = world.go_live()
        assert_ok(world.run())
        calls = world.calls()
        wrapper = next(c for c in calls if c.startswith("co-pypi "))
        assert wrapper.split()[1] == str(world.release(sha))
        assert (
            "uv sync --locked --no-dev --compile-bytecode --link-mode copy --python /usr/bin/python3.12"
            in wrapper
        )
        sync = next(c for c in calls if c.startswith("uv ") and " sync " in c)
        assert "pair=set" in sync and "PYDL=never" in sync

    def test_ci_comes_before_the_build_and_the_switch_before_the_units(self, world):
        world.go_live()
        world.push({API: unit(API, world.root / "live", version="v2")})
        assert_ok(world.run())
        calls = world.calls()
        assert index_of(calls, "curl https://api.github.com/") < index_of(calls, "uv ")
        assert index_of(calls, "sudo mv -Tf") < index_of(calls, "sudo install -m 644")

    def test_a_code_only_deploy_restarts_the_api_and_verifies_each_changed_unit(
        self, world
    ):
        world.go_live()
        assert_ok(world.run())
        world.push()
        world.reset_log()
        result = world.run()
        assert_ok(result)
        calls = world.calls()
        assert restarts(calls) == [API]
        assert f"sudo systemctl start {BACKUP}" in calls
        assert not any(c == f"sudo systemctl start {PROBE}" for c in calls), (
            "a tick is never forced"
        )
        assert installs(calls) == []
        assert f"live is on {world.build(world.main[-1])}" in result.stderr

    def test_help_touches_nothing_and_names_the_version(self, world):
        result = world.run("--help")
        assert_ok(result)
        assert "--target" in result.stdout and "version 1" in result.stdout
        assert world.calls() == []


class TestConfiguration:
    def test_an_invalid_project_is_refused(self, world):
        world.hooks(HOOKS.replace("PROJECT=acme", "PROJECT=Acme_1"))
        result = world.run()
        assert result.returncode == 1
        assert "is not a unit prefix" in result.stderr

    def test_ci_github_needs_the_repo(self, world):
        world.hooks(HOOKS.replace("GITHUB_REPO=CannObserv/acme", ""))
        result = world.run()
        assert result.returncode == 1 and "GITHUB_REPO" in result.stderr

    def test_a_knob_that_is_not_a_whole_number_is_refused_before_anything(self, world):
        result = world.run(ACME_DEPLOY_KEEP="5x")
        assert result.returncode == 1 and "ACME_DEPLOY_KEEP=5x" in result.stderr
        assert not any(c.startswith("sudo ") for c in world.calls())

    def test_a_missing_hooks_file_is_refused(self, world):
        (world.checkout / "scripts" / "deploy_hooks.sh").unlink()
        result = world.run()
        assert result.returncode == 1 and "deploy_hooks.sh is missing" in result.stderr

    def test_a_root_writable_by_others_is_refused(self, world):
        world.root.chmod(0o777)
        result = world.run()
        assert result.returncode == 1 and "writable by more than root" in result.stderr

    def test_a_second_deploy_waits_on_nobody(self, world):
        fd = os.open(world.root, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            result = world.run()
        finally:
            os.close(fd)
        assert result.returncode == 1 and "another deploy is running" in result.stderr


class TestWhatMayBeDeployed:
    def test_an_unpushed_commit_is_refused(self, world):
        result = world.run(world.unpushed)
        assert result.returncode == 1 and "on no pushed branch" in result.stderr

    def test_a_branch_commit_needs_target_dev(self, world):
        result = world.run(world.feature)
        assert result.returncode == 1 and "--target dev" in result.stderr

    def test_an_older_main_commit_may_be_deployed(self, world):
        world.go_live()
        result = world.run(world.main[-1])
        assert_ok(result)


class TestTheCIGate:
    def test_a_failed_job_is_refused_by_name_and_nothing_is_built(self, world):
        world.go_live()
        world.ci_jobs(1, **{JOB: "failure"})
        result = world.run()
        assert result.returncode == 1
        assert "lint + test (failure)" in result.stderr
        assert not (world.root / "releases").exists()

    def test_a_job_named_in_ci_jobs_missing_from_the_run_is_refused(self, world):
        world.go_live()
        world.ci_jobs(1, **{JOB: "absent", "other": "success"})
        result = world.run()
        assert (
            result.returncode == 1 and "lint + test (not in the run)" in result.stderr
        )

    def test_a_commit_behind_the_tip_with_no_run_is_refused_at_once(self, world):
        world.go_live()
        world.push()
        world.ci_answers([])
        result = world.run(world.main[-2])
        assert result.returncode == 1 and "newest commit of each push" in result.stderr

    def test_a_run_still_going_when_the_wait_ends_is_refused(self, world):
        sha = world.go_live()
        world.ci_answers([ci_run(1, sha, status="in_progress")])
        result = world.run(ACME_DEPLOY_CI_WAIT_SECONDS="0")
        assert result.returncode == 1 and "still in_progress" in result.stderr
        assert not (world.root / "releases").exists()

    def test_skip_ci_asks_nobody_and_journals_it(self, world):
        world.go_live()
        result = world.run("--skip-ci")
        assert_ok(result)
        assert not any(
            c.startswith("curl https://api.github.com/") for c in world.calls()
        )
        assert any(
            "CI not checked" in c for c in world.calls() if c.startswith("logger")
        )

    def test_ci_none_is_a_standing_switch(self, world):
        world.hooks(hooks_with("CI=none"))
        world.go_live()
        result = world.run()
        assert_ok(result)
        assert not any(
            c.startswith("curl https://api.github.com/") for c in world.calls()
        )
        assert "CI=none" in result.stderr

    def test_ci_auth_gh_asks_through_gh_without_a_token(self, world):
        world.hooks(hooks_with("CI_AUTH=gh"))
        world.go_live()
        result = world.run(GH_TOKEN="pat", GITHUB_TOKEN="pat")
        assert_ok(result)
        gh = [c for c in world.calls() if c.startswith("gh ")]
        assert gh and all("token= " in c for c in gh), gh

    def test_github_refusing_refuses_with_its_message(self, world):
        world.go_live()
        result = world.run(FAKE_CI_ERROR="API rate limit exceeded")
        assert result.returncode == 1 and "API rate limit exceeded" in result.stderr


class TestReleases:
    def test_a_built_release_is_reused(self, world):
        world.go_live()
        assert_ok(world.run())
        world.reset_log()
        result = world.run()
        assert_ok(result)
        assert "reusing release" in result.stderr
        assert not any(c.startswith("uv ") for c in world.calls())

    def test_a_lock_from_the_wheelhouse_is_refused_journaled(self, world):
        world.go_live()
        world.push(top={"uv.lock": WHEELHOUSE_LOCK})
        result = world.run()
        assert result.returncode == 1 and "./.wheelhouse" in result.stderr
        assert world.target() is None
        assert any("wheelhouse" in c for c in world.calls() if c.startswith("logger"))

    def test_an_interpreter_under_home_is_refused(self, world):
        world.go_live()
        result = world.run(FAKE_PYTHON_HOME="/home/exedev/.local/share/uv/python")
        assert result.returncode == 1 and "not one outside /home" in result.stderr

    def test_a_failed_sync_switches_nothing(self, world):
        world.go_live()
        result = world.run(FAKE_SYNC_FAIL="1")
        assert result.returncode == 1 and world.target() is None

    def test_a_linked_release_whose_venv_no_longer_runs_is_never_rebuilt(self, world):
        world.go_live()
        assert_ok(world.run())
        result = world.run(FAKE_BROKEN_VENV="1")
        assert result.returncode == 1 and "a target runs it" in result.stderr

    def test_an_interrupted_build_is_rebuilt(self, world):
        sha = world.go_live()
        assert_ok(world.run("--build-only"))
        os.chmod(world.root / "releases", 0o755)
        (world.release(sha) / "REVISION").chmod(0o644)
        os.chmod(world.release(sha), 0o755)
        (world.release(sha) / "REVISION").unlink()
        result = world.run()
        assert_ok(result)
        assert "an interrupted build; rebuilding" in result.stderr

    def test_build_only_switches_nothing(self, world):
        sha = world.go_live()
        result = world.run("--build-only")
        assert_ok(result)
        assert world.release(sha).is_dir() and world.target() is None


class TestHooks:
    def test_errexit_holds_inside_a_hook(self, world):
        world.hooks(hooks_with("build_extra() { false; echo past >&2; }"))
        world.go_live()
        result = world.run()
        assert result.returncode == 1
        assert "build_extra failed" in result.stderr and "past" not in result.stderr

    def test_a_required_artifact_missing_is_refused(self, world):
        world.hooks(hooks_with("REQUIRED_ARTIFACTS=(static/bundle.js)"))
        world.go_live()
        result = world.run()
        assert result.returncode == 1 and "static/bundle.js" in result.stderr

    def test_build_extra_makes_the_artifact_in_the_release(self, world):
        world.hooks(
            hooks_with(
                "REQUIRED_ARTIFACTS=(static/bundle.js)",
                "build_extra() { mkdir -p static && echo js > static/bundle.js; }",
            )
        )
        sha = world.go_live()
        assert_ok(world.run())
        assert (world.release(sha) / "static" / "bundle.js").exists()

    def test_migrate_runs_before_the_switch_and_its_failure_switches_nothing(
        self, world
    ):
        world.hooks(
            hooks_with('migrate() { echo "migrate $1 $PWD" >> "$FAKE_LOG"; false; }')
        )
        world.go_live()
        result = world.run()
        assert result.returncode == 1 and "migrate failed for live" in result.stderr
        assert world.target() is None
        assert any(c.startswith("migrate live ") for c in world.calls())

    def test_pre_switch_check_refuses_with_require_active_timer(self, world):
        world.hooks(
            hooks_with("pre_switch_check() { require_active_timer acme-probe.timer; }")
        )
        world.go_live()
        result = world.run(FAKE_INACTIVE="acme-probe.timer")
        assert (
            result.returncode == 1 and "acme-probe.timer is not active" in result.stderr
        )
        assert world.target() is None

    def test_post_build_check_failing_takes_revision_back_off(self, world):
        world.hooks(hooks_with("post_build_check() { return 3; }"))
        sha = world.go_live()
        result = world.run()
        assert result.returncode == 1 and "post_build_check failed" in result.stderr
        assert not (world.release(sha) / "REVISION").exists()

    def test_hooks_run_from_the_checkout_on_a_reuse_too(self, world):
        world.hooks(
            hooks_with('pre_switch_check() { echo "pwd $PWD" >> "$FAKE_LOG"; }')
        )
        world.go_live()
        assert_ok(world.run())
        assert_ok(world.run())
        seen = [c.split(" ", 1)[1] for c in world.calls() if c.startswith("pwd ")]
        assert seen == [str(world.checkout)] * 2, seen

    def test_post_verify_failing_is_a_note_never_a_rollback(self, world):
        world.hooks(hooks_with("post_verify() { return 1; }"))
        sha = world.go_live()
        result = world.run()
        assert_ok(result)
        assert "a note, never a rollback" in result.stderr
        assert world.target() == f"releases/{world.build(sha)}"

    def test_a_restarted_unit_with_no_check_is_verified_by_its_new_process(self, world):
        world.hooks(hooks_with("verify() { return 2; }"))
        world.go_live()
        result = world.run()
        assert_ok(result)
        assert f"{API} runs {world.build(world.main[-1])}" in result.stderr


class TestVerifyAndSwitchBack:
    def test_a_health_check_on_the_wrong_build_switches_back_and_proves_the_old(
        self, world
    ):
        world.go_live()
        assert_ok(world.run())
        old = world.target()
        bad = world.push()
        result = world.run(FAKE_HEALTH_STALE_ON=world.build(bad))
        assert result.returncode == 1, result.stderr
        assert world.target() == old
        assert "which is answering" in result.stderr

    def test_a_unit_that_dies_on_the_new_build_switches_back(self, world):
        world.hooks(hooks_with("verify() { return 2; }"))
        world.go_live()
        assert_ok(world.run())
        bad = world.push()
        result = world.run(FAKE_DIES_ON=world.build(bad))
        assert (
            result.returncode == 1 and world.target() != f"releases/{world.build(bad)}"
        )

    def test_nothing_answering_after_the_switch_back_exits_4(self, world):
        world.go_live()
        assert_ok(world.run())
        world.push()
        result = world.run(FAKE_HEALTH_DOWN="1")
        assert result.returncode == 4 and "NOT answering" in result.stderr

    def test_a_first_deploy_that_fails_removes_the_link(self, world):
        # The units ran live before any release existed: with the link gone,
        # the API cannot start, so nothing answers and that is found, not assumed.
        world.go_live()
        result = world.run(FAKE_BACKUP_FAIL_BUILD=world.build(world.main[-1]))
        assert result.returncode == 4, result.stderr
        assert world.target() is None
        assert restarts(world.calls()).count(API) == 2

    def test_a_failed_cutover_proves_the_checkout_units_it_put_back(self, world):
        # A retrofit's first deploy: the installed units run the checkout. The
        # release's units are installed, the deploy fails, and the checkout's
        # units go back, restarted and verified: exit 1, answering.
        sha = world.push(world.live_units)
        result = world.run(FAKE_BACKUP_FAIL_BUILD=world.build(sha))
        assert result.returncode == 1, result.stderr
        assert "which is answering" in result.stderr
        assert world.target() is None
        assert world.installed(API) == world.dev_units[API]
        assert restarts(world.calls()).count(API) == 2

    def test_a_changed_unit_goes_back_on_failure(self, world):
        world.go_live()
        assert_ok(world.run())
        before = world.installed(BACKUP)
        bad = world.push(
            {BACKUP: unit(BACKUP, world.root / "live", version="v2", kind="oneshot")}
        )
        result = world.run(FAKE_BACKUP_FAIL_BUILD=world.build(bad))
        assert result.returncode == 1, result.stderr
        assert world.installed(BACKUP) == before


class TestUnits:
    def test_a_changed_unit_is_installed_with_one_daemon_reload(self, world):
        world.go_live()
        world.push({API: unit(API, world.root / "live", version="v2")})
        assert_ok(world.run())
        calls = world.calls()
        assert installs(calls) == [API]
        assert calls.count("sudo systemctl daemon-reload") == 1
        assert "v2" in world.installed(API)

    def test_a_new_unit_is_installed_and_named_not_enabled(self, world):
        world.go_live()
        name = "acme-sweep.service"
        world.push(
            {
                name: unit(name, world.root / "live", kind="oneshot"),
                "acme-sweep.timer": unit("acme-sweep.timer", None),
            }
        )
        result = world.run()
        assert_ok(result)
        assert world.installed(name) is not None
        assert "acme-sweep.timer" not in world.enabled()
        assert "not enabled" in result.stderr

    def test_an_enable_new_timer_is_enabled_once_verified(self, world):
        world.hooks(hooks_with("ENABLE_NEW=(acme-sweep.timer)"))
        world.go_live()
        world.push(
            {
                "acme-sweep.service": unit(
                    "acme-sweep.service", world.root / "live", kind="oneshot"
                ),
                "acme-sweep.timer": unit("acme-sweep.timer", None),
            }
        )
        assert_ok(world.run())
        assert "acme-sweep.timer" in world.enabled()

    def test_an_enable_new_timer_is_not_enabled_when_the_deploy_fails(self, world):
        world.hooks(hooks_with("ENABLE_NEW=(acme-sweep.timer)"))
        world.go_live()
        assert_ok(world.run())
        bad = world.push({"acme-sweep.timer": unit("acme-sweep.timer", None)})
        result = world.run(FAKE_HEALTH_STALE_ON=world.build(bad))
        assert result.returncode == 1
        assert "acme-sweep.timer" not in world.enabled()
        assert world.installed("acme-sweep.timer") is None

    def test_a_unit_loaded_stale_switches_back_to_the_build_that_answers(self, world):
        world.go_live()
        assert_ok(world.run())
        old = world.target()
        before = world.installed(API)
        world.push({API: unit(API, world.root / "live", version="v2")})
        result = world.run(FAKE_NEEDS_RELOAD=API)
        assert result.returncode == 1, result.stderr
        assert "still needs a daemon-reload" in result.stderr
        assert world.target() == old and world.installed(API) == before

    def test_a_long_running_unit_that_is_not_enabled_is_neither_restarted_nor_verified(
        self, world
    ):
        world.go_live()
        world.disable(API)
        result = world.run()
        assert_ok(result)
        assert restarts(world.calls()) == []
        assert f"{API} is installed but not enabled" in result.stderr

    def test_a_host_config_that_differs_is_a_note_never_an_install(self, world):
        world.go_live()
        world.push({"sysctl.d/60-acme.conf": "vm.x = 1\n"})
        result = world.run()
        assert_ok(result)
        assert (
            "host config deploy/sysctl.d/60-acme.conf is not installed" in result.stderr
        )
        assert not (world.host / "etc" / "sysctl.d").exists()

    def test_no_restart_switches_and_installs_but_restarts_nothing(self, world):
        world.go_live()
        world.push({API: unit(API, world.root / "live", version="v2")})
        result = world.run("--no-restart")
        assert_ok(result)
        assert restarts(world.calls()) == [] and "v2" in world.installed(API)
        assert "--no-restart" in result.stderr


class TestVerify:
    def test_a_plain_rerun_after_no_restart_verifies_nothing(self, world):
        world.go_live()
        assert_ok(world.run("--no-restart"))
        world.reset_log()
        result = world.run()
        assert_ok(result)
        assert restarts(world.calls()) == []
        assert "nothing to verify" in result.stderr

    def test_verify_restarts_and_proves_a_build_already_live(self, world):
        sha = world.go_live()
        assert_ok(world.run("--no-restart"))
        world.reset_log()
        result = world.run("--verify", world.build(sha))
        assert_ok(result)
        calls = world.calls()
        assert restarts(calls) == [API]
        assert f"sudo systemctl start {BACKUP}" in calls
        assert f"live is on {world.build(sha)}" in result.stderr
        assert not any(c.startswith("uv ") for c in calls), "the release is reused"

    def test_verify_switches_back_when_the_build_does_not_answer(self, world):
        sha = world.go_live()
        assert_ok(world.run("--no-restart"))
        result = world.run(
            "--verify", world.build(sha), FAKE_HEALTH_STALE_ON=world.build(sha)
        )
        assert result.returncode == 4, result.stderr
        assert "nothing to switch back to" in result.stderr

    @pytest.mark.parametrize("other", ["--no-restart", "--build-only"])
    def test_verify_refuses_a_flag_that_restarts_nothing(self, world, other):
        result = world.run("--verify", other)
        assert result.returncode == 1 and "--verify" in result.stderr
        assert world.calls() == []


class TestTargets:
    def dev_and_live(self, world, api_only_dev: bool = False) -> dict[str, str]:
        units = dict(world.live_units)
        units["acme-api-dev.service"] = unit("acme-api-dev.service", world.root / "dev")
        if not api_only_dev:
            units["acme-probe-dev.service"] = unit(
                "acme-probe-dev.service", world.root / "dev", kind="oneshot"
            )
        return units

    def test_dev_goes_first_then_live(self, world):
        world.go_live(self.dev_and_live(world))
        world.start("acme-api-dev.service")
        (world.state / "enabled").write_text(
            world.state.joinpath("enabled").read_text() + "acme-api-dev.service\n"
        )
        result = world.run()
        assert_ok(result)
        assert result.stderr.index("dev is on") < result.stderr.index("live is on")
        assert world.target("dev") == world.target("live")

    def test_a_target_is_its_units_working_directory_alone(self, world):
        world.go_live(self.dev_and_live(world, api_only_dev=True))
        result = world.run("--target", "dev")
        assert_ok(result)
        assert world.target("dev") and world.target("live") is None

    def test_a_branch_commit_deploys_to_dev_only(self, world):
        world.go_live(self.dev_and_live(world))
        sha = world.push(self.dev_and_live(world), branch="feature")
        result = world.run("--target", "dev", "--skip-ci", sha)
        assert_ok(result)
        assert world.target("dev") == f"releases/{world.build(sha)}"
        assert world.target("live") is None

    def test_a_repo_with_no_dev_unit_has_no_dev_target(self, world):
        world.go_live()
        result = world.run("--target", "dev")
        assert (
            result.returncode == 1
            and "runs" in result.stderr
            and "/dev" in result.stderr
        )


class TestServiceDir:
    def test_a_subtree_service_is_the_releases_root(self, world):
        world.hooks(hooks_with("SERVICE_DIR=service"))
        files = {f"deploy/{k}": v for k, v in world.live_units.items()}
        files.update(
            {
                "uv.lock": (world.checkout / "uv.lock").read_text(),
                "pyproject.toml": "[project]\n",
            }
        )
        world.install(world.live_units)
        sha = world.push(top={f"service/{k}": v for k, v in files.items()})
        assert_ok(world.run())
        release = world.release(sha)
        assert (release / "pyproject.toml").exists() and (
            release / "deploy" / API
        ).exists()
        assert not (release / "service").exists()


class TestPrune:
    def test_keep_counts_past_every_link_and_spares_what_live_replaced(self, world):
        world.go_live()
        builds = []
        for _ in range(4):
            sha = world.push()
            assert_ok(world.run(ACME_DEPLOY_KEEP="1"))
            builds.append(world.build(sha))
        left = sorted(p.name for p in (world.root / "releases").iterdir())
        assert builds[-1] in left and builds[-2] in left
        assert builds[0] not in left


def test_the_shipped_hooks_template_is_refused_until_filled_in(world):
    world.hooks(TEMPLATE.read_text())
    result = world.run()
    assert result.returncode == 1 and "is not a unit prefix" in result.stderr


def test_backup_state_is_read_through_the_hooks_own_jq(world):
    world.go_live()
    # The fake backup reports another build on every run, the old build's
    # too: the switch back proves nothing either, so exit 4.
    result = world.run(FAKE_BACKUP_SAYS="someone-else")
    assert result.returncode == 4, result.stderr
    assert "without .revision == $want" in result.stderr
    assert json.loads(world.backup_state.read_text())["revision"] == "someone-else"


@pytest.mark.parametrize(("required", "outcome"), [("", "skip"), ("1", "fail")])
def test_gnubin_required_turns_the_skip_into_a_failure(monkeypatch, required, outcome):
    from tests.structural import deploying_releases_rig as rig

    monkeypatch.setattr(rig.shutil, "which", lambda name: None)
    monkeypatch.setenv("GNUBIN_REQUIRED", required)
    expected = pytest.fail.Exception if outcome == "fail" else pytest.skip.Exception
    with pytest.raises(expected, match="DID NOT RUN"):
        rig.require_linux_tools()
