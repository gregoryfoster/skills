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
import subprocess
from pathlib import Path

from .test_socraticode_graph_yield import (
    DRIVER,
    REPLIES_OK,
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
        version = entry["version"]
        install = cache / version
        (install / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (install / ".claude-plugin" / "plugin.json").write_text(
            json.dumps(
                {
                    "name": "socraticode",
                    "version": version,
                    "mcpServers": {
                        "socraticode": {
                            "command": "npx",
                            "args": ["-y", f"socraticode@{version}"],
                        }
                    },
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
