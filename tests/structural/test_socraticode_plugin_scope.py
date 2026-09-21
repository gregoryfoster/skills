"""The plugin registry entry the driver reads is the one the session loads (#305 CR 28).

`installed_plugins.json` lists one entry per install, each with a `scope`
(`user`, `managed`, `project` or `local`) and, for the last two, the
`projectPath` it was installed for. `mcp-driver.mjs` took the first entry
found. Since #305 that entry decides severity: `sessionServer()` reads from it
the version of the server answering the session's queries, and judges the
graph's builder against that. A `project` entry installed for another checkout,
listed first, made this project's check judge its graph against a server its
session never loads.

The rule held here is Claude Code's own, read from the 2.1.278 binary rather
than assumed: a `user` or `managed` entry applies everywhere; a `project` or
`local` one only where its `projectPath` is the project, or names the same
repository (a worktree of it); and among the entries that apply, the loader
takes the first in registry order whose install is present — installs append,
and no scope outranks another beyond that order.
"""

import json
import shutil
import subprocess
from pathlib import Path

from .test_socraticode_graph_yield import (
    DRIVER,
    REPLIES_OK,
    STUB_SERVER,
    _clean_env,
    _git,
    _graph_built_by,
    _health_check,
    requires_node,
)


def _config(tmp_path: Path, entries: list[dict]) -> Path:
    """A CLAUDE_CONFIG_DIR holding one cached plugin per version `entries` name.

    Each entry's `version` becomes a cache directory whose inline definition
    launches exactly `socraticode@<version>`, so the version the driver
    reports says which entry it took; the rest of the entry is written to the
    registry as given, with `installPath` pointing at that directory.
    """
    config = tmp_path / "claude-config"
    cache = config / "plugins" / "cache" / "socraticode" / "socraticode"
    registry = []
    for entry in entries:
        entry = dict(entry)
        version = entry["version"]
        # A `server` key replaces the npx definition, and is not registry data.
        server = entry.pop("server", None) or {
            "command": "npx",
            "args": ["-y", f"socraticode@{version}"],
        }
        install = cache / version
        (install / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (install / ".claude-plugin" / "plugin.json").write_text(
            json.dumps(
                {
                    "name": "socraticode",
                    "version": version,
                    "mcpServers": {"socraticode": server},
                }
            )
        )
        registry.append({**entry, "installPath": str(install)})
    (config / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": {"socraticode@socraticode": registry}})
    )
    return config


def _loaded(config: Path, project: Path) -> dict | None:
    """`launchFromPluginConfig({ project })` under `config`."""
    script = (
        f"import {{ launchFromPluginConfig }} from {json.dumps(str(DRIVER))};"
        "process.stdout.write(JSON.stringify(launchFromPluginConfig("
        f"{{ project: {json.dumps(str(project))} }})));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
        env=_clean_env(CLAUDE_CONFIG_DIR=str(config)),
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


class TestTheRegistryEntryIsTheSessions:
    @requires_node
    def test_another_projects_entry_listed_first_is_skipped(
        self, tmp_path: Path
    ) -> None:
        here, elsewhere = _dir(tmp_path, "here"), _dir(tmp_path, "elsewhere")
        config = _config(
            tmp_path,
            [
                {
                    "scope": "project",
                    "projectPath": str(elsewhere),
                    "version": "1.13.1",
                },
                {"scope": "user", "version": "1.14.0"},
            ],
        )
        p = _loaded(config, here)
        assert p is not None and p["pluginVersion"] == "1.14.0", (
            "a project-scope entry installed for another checkout does not load "
            f"here, so the session here runs the user install\n{p}"
        )

    @requires_node
    def test_only_another_projects_entry_means_no_plugin_here(
        self, tmp_path: Path
    ) -> None:
        """The registry lists it, and nothing applies: an answer, not a cache scan."""
        here, elsewhere = _dir(tmp_path, "here"), _dir(tmp_path, "elsewhere")
        config = _config(
            tmp_path,
            [{"scope": "local", "projectPath": str(elsewhere), "version": "1.13.1"}],
        )
        assert _loaded(config, here) is None

    @requires_node
    def test_an_applying_entry_whose_install_is_gone_is_not_a_cache_scan(
        self, tmp_path: Path
    ) -> None:
        """#305 CR 49: the cache holds other projects' versions, too.

        Claude Code's loader takes an applying entry or nothing; it never scans
        the cache. The driver fell through to the newest cached version when no
        applying entry's install loaded — here, the other project's 1.14.0.
        """
        here, elsewhere = _dir(tmp_path, "here"), _dir(tmp_path, "elsewhere")
        config = _config(
            tmp_path,
            [
                {"scope": "local", "projectPath": str(here), "version": "1.13.1"},
                {"scope": "local", "projectPath": str(elsewhere), "version": "1.14.0"},
            ],
        )
        shutil.rmtree(
            config / "plugins" / "cache" / "socraticode" / "socraticode" / "1.13.1"
        )
        assert _loaded(config, here) is None
        p = _loaded(config, elsewhere)
        assert p is not None and p["pluginVersion"] == "1.14.0", p

    @requires_node
    def test_this_projects_entry_applies(self, tmp_path: Path) -> None:
        here = _dir(tmp_path, "here")
        config = _config(
            tmp_path,
            [
                {"scope": "local", "projectPath": str(here), "version": "1.13.1"},
                {"scope": "user", "version": "1.14.0"},
            ],
        )
        p = _loaded(config, here)
        assert p is not None and p["pluginVersion"] == "1.13.1", p

    @requires_node
    def test_registry_order_decides_between_entries_that_apply(
        self, tmp_path: Path
    ) -> None:
        """Claude Code's loader takes the first that applies; no scope outranks it."""
        here = _dir(tmp_path, "here")
        config = _config(
            tmp_path,
            [
                {"scope": "user", "version": "1.14.0"},
                {"scope": "project", "projectPath": str(here), "version": "1.13.1"},
            ],
        )
        p = _loaded(config, here)
        assert p is not None and p["pluginVersion"] == "1.14.0", p

    @requires_node
    def test_a_worktree_of_the_projects_repository_matches(
        self, tmp_path: Path
    ) -> None:
        main = _dir(tmp_path, "main")
        subprocess.run(
            ["git", "-C", str(main), "init", "-q"],
            check=True,
            capture_output=True,
            env=_clean_env(),
        )
        (main / "README.md").write_text("x\n")
        _git(main, "add", "-A")
        _git(main, "commit", "-qm", "init")
        worktree = tmp_path / "wt"
        _git(main, "worktree", "add", "-q", "-b", "wt", str(worktree))
        config = _config(
            tmp_path,
            [{"scope": "project", "projectPath": str(main), "version": "1.13.1"}],
        )
        p = _loaded(config, worktree)
        assert p is not None and p["pluginVersion"] == "1.13.1", p

    @staticmethod
    def _bare_with_worktrees(tmp_path: Path, name: str) -> tuple[Path, Path]:
        """A bare repository `name`.git and two worktrees of it."""
        origin = _dir(tmp_path, f"{name}-origin")
        subprocess.run(
            ["git", "-C", str(origin), "init", "-q"],
            check=True,
            capture_output=True,
            env=_clean_env(),
        )
        (origin / "README.md").write_text("x\n")
        _git(origin, "add", "-A")
        _git(origin, "commit", "-qm", "init")
        bare = tmp_path / f"{name}.git"
        _git(tmp_path, "clone", "-q", "--bare", str(origin), str(bare))
        a, b = tmp_path / f"{name}-a", tmp_path / f"{name}-b"
        _git(bare, "worktree", "add", "-q", "-b", "a", str(a))
        _git(bare, "worktree", "add", "-q", "-b", "b", str(b))
        return a, b

    @requires_node
    def test_worktrees_of_a_bare_repository_are_one_repository(
        self, tmp_path: Path
    ) -> None:
        """#305 CR 50: the binary's canonical root for them is the bare dir.

        The driver asked for a main checkout, and a bare repository has none,
        so an entry recorded at one worktree applied at the other for Claude
        Code and not for the driver. The entry is spelled through /var on
        macOS, where tmp_path is /private/var, so the realpath is exercised.
        """
        a, b = self._bare_with_worktrees(tmp_path, "repo")
        recorded = str(a).replace("/private/var/", "/var/", 1)
        config = _config(
            tmp_path,
            [{"scope": "local", "projectPath": recorded, "version": "1.13.1"}],
        )
        p = _loaded(config, b)
        assert p is not None and p["pluginVersion"] == "1.13.1", p

    @requires_node
    def test_another_bare_repositorys_worktree_does_not_match(
        self, tmp_path: Path
    ) -> None:
        a, _ = self._bare_with_worktrees(tmp_path, "one")
        _, b = self._bare_with_worktrees(tmp_path, "two")
        config = _config(
            tmp_path,
            [{"scope": "local", "projectPath": str(a), "version": "1.13.1"}],
        )
        assert _loaded(config, b) is None


class TestTheEntryDecidesSeverity:
    """Why the choice matters: the builder check is judged against it."""

    @requires_node
    def test_health_check_judges_against_the_entry_this_project_loads(
        self, tmp_path: Path
    ) -> None:
        """A graph cut by v1.13.1, a session that loads the v1.14.0 install.

        Read first-found, the other checkout's v1.13.1 entry called the graph
        current for the session — a note, exit 0 — when the server answering
        this project's session would cut it again at v1.14.0.
        """
        project, elsewhere = _dir(tmp_path, "repo"), _dir(tmp_path, "elsewhere")
        config = _config(
            tmp_path,
            [
                {
                    "scope": "project",
                    "projectPath": str(elsewhere),
                    "version": "1.13.1",
                },
                {"scope": "user", "version": "1.14.0"},
            ],
        )
        result, report = _health_check(
            tmp_path,
            project,
            {**REPLIES_OK, "codebase_graph_status": _graph_built_by("1.13.1")},
            STUB_SERVER_VERSION="1.14.0",
            CLAUDE_CONFIG_DIR=str(config),
        )
        assert report is not None, result.stdout + result.stderr
        assert report["sessionServer"]["version"] == "1.14.0", report["sessionServer"]
        assert result.returncode == 1, result.stdout + result.stderr


def _stub_engine(tmp_path: Path, version: str) -> dict:
    """A plugin definition launching a stub server that is socraticode `version`.

    Interpreter and path, so the definition FIXES its version — read from the
    package.json beside it, as `pluginLaunchVersion()` reads a real one — and
    the stub names the same version in its handshake.
    """
    pkg = tmp_path / f"engine-{version}" / "node_modules" / "socraticode"
    (pkg / "dist").mkdir(parents=True)
    (pkg / "dist" / "index.mjs").write_text(STUB_SERVER)
    (pkg / "package.json").write_text(
        json.dumps({"name": "socraticode", "version": version})
    )
    return {
        "command": shutil.which("node") or "node",
        "args": [str(pkg / "dist" / "index.mjs")],
        "env": {"STUB_SERVER_VERSION": version},
    }


class TestTheCheckLaunchesWhatTheProjectLoads:
    """#305 CR 42: the check's own server comes from the project's entry too.

    CR 28 read the SESSION's definition from the entry applying at the project,
    but the check still launched the one applying at the cwd, and
    `sessionServer()` took "which this check launched too" on the word of
    `launch.plugin` alone. SKILL.md documents `health-check "<PROJECT_PATH>"`,
    so a cwd in another project is a supported call, and from one the report
    named a v1.13.1 session server beside a plugin definition launching
    v1.14.0 — and exited 0 on a graph that server would cut again.
    """

    @staticmethod
    def _projects(tmp_path: Path) -> tuple[Path, Path, Path]:
        a, b = _dir(tmp_path, "a"), _dir(tmp_path, "b")
        config = _config(
            tmp_path,
            [
                {
                    "scope": "local",
                    "projectPath": str(a),
                    "version": "1.13.1",
                    "server": _stub_engine(tmp_path, "1.13.1"),
                },
                {
                    "scope": "local",
                    "projectPath": str(b),
                    "version": "1.14.0",
                    "server": _stub_engine(tmp_path, "1.14.0"),
                },
            ],
        )
        return a, b, config

    @staticmethod
    def _check(tmp_path: Path, project: Path, cwd: Path, config: Path) -> tuple:
        """health-check `project` from `cwd`, launching whatever the plugin defines."""
        replies = tmp_path / "replies.json"
        replies.write_text(
            json.dumps(
                {**REPLIES_OK, "codebase_graph_status": _graph_built_by("1.13.1")}
            )
        )
        result = subprocess.run(
            ["node", str(DRIVER), "health-check", str(project)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(cwd),
            env=_clean_env(
                CLAUDE_CONFIG_DIR=str(config),
                # No pin and no SOCRATICODE_ENTRY: the plugin's definition is
                # the launch, as it is on a plugin-only host.
                SOCRATICODE_PIN_DIR=str(tmp_path / "no-pin"),
                STUB_REPLIES=str(replies),
                HEALTH_TIMEOUT_MS="30000",
            ),
        )
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            report = None
        return result, report

    @requires_node
    def test_checking_b_from_a_launches_bs_server(self, tmp_path: Path) -> None:
        """The review's repro: exit 0, and a report that contradicted itself."""
        a, b, config = self._projects(tmp_path)
        result, report = self._check(tmp_path, b, a, config)
        assert report is not None, result.stdout + result.stderr
        assert report["server"]["version"] == "1.14.0", (
            "the check launched the definition applying at its cwd, not the "
            f"one the project's session loads\n{report['server']}"
        )
        session = report["sessionServer"]
        assert session["version"] == "1.14.0", session
        assert "engine-1.14.0" in session["plugin"]["launches"], session
        assert result.returncode == 1, (
            "a v1.13.1 graph under a session that runs v1.14.0 is stale, "
            f"whichever directory the check ran from\n{result.stderr}"
        )

    @requires_node
    def test_checking_a_from_b_launches_as_server(self, tmp_path: Path) -> None:
        """The other order: a current graph was called stale by B's server."""
        a, b, config = self._projects(tmp_path)
        result, report = self._check(tmp_path, a, b, config)
        assert report is not None, result.stdout + result.stderr
        assert report["server"]["version"] == "1.13.1", report["server"]
        assert report["sessionServer"]["version"] == "1.13.1", report["sessionServer"]
        assert result.returncode == 0, (
            "a v1.13.1 graph under a session that runs v1.13.1 is current, "
            f"whichever directory the check ran from\n{result.stderr}"
        )

    @requires_node
    def test_launched_too_needs_the_same_definition(self, tmp_path: Path) -> None:
        """`launch.plugin` says the launch was A plugin definition, not WHICH one."""
        engine = _stub_engine(tmp_path, "1.13.1")
        script = (
            f"import {{ sessionServer }} from {json.dumps(str(DRIVER))};"
            "process.stdout.write(JSON.stringify(sessionServer({"
            "launch: { source: 'plugin.json inline (/other/plugin.json)', plugin: true },"
            f"plugin: {{ ...{json.dumps(engine)}, plugin: true,"
            " source: 'plugin.json inline (/this/plugin.json)' },"
            "checkVersion: '1.14.0' })));"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert result.returncode == 0, result.stderr
        s = json.loads(result.stdout)
        assert s["version"] == "1.13.1", s
        assert "launched too" not in s["basis"], s
