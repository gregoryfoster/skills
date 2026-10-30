"""patching-hosts' language block, and the knob's owner lines (epic #516).

What this file pins, each against its issue and the operator's decision on
it (2026-10-29):

- #508: a knob service whose `WorkingDirectory=` holds no lockfile is listed
  with `lockfile: null`, and the class reads incomplete with the reason. An
  `owner` line that matches nothing on the host is a `knob` finding, but only
  once every reading it could match was taken.
- #427: an `owner` glob matches each container image's `repository:tag`, and
  every tag of a repository, as a binary's matches its basename. The image
  entry carries `owner` and `owner_line`.
- #456: a root-owned `uv.lock` is audited as `nobody`, with a uv only root
  can change, from `/usr/local/bin` or `/usr/bin`. uv never runs as root.
- #422: a uv with no `audit` leaves the tree unaudited, naming its version
  and the first that has one. Nothing is fetched.
- #391: an origin of the shape `<user>@github*:Owner/repo(.git)` names its
  owner, by that shape alone: no ssh config is read and no ssh runs.

The probe's rig and the language helpers are test_patching_hosts_probe.py's.
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from tests.structural.patching_hosts_rig import dispatcher
from tests.structural.test_patching_hosts_probe import (
    APP,
    UV_CLEAN,
    Host,
    _audit,
    _finding,
    _ids,
    _lang,
    _tree,
    _uv,
)

KNOB = "class production\nposture automatic\n"
NO_LOCK = (
    "a knob service runs from it, and it holds no lockfile (uv.lock, "
    "package-lock.json, poetry.lock, Pipfile.lock, pnpm-lock.yaml, yarn.lock)"
)


class LangHost(Host):
    # ssh answers nothing, and its calls are logged: the probe never asks it.
    STUBBED = (*Host.STUBBED, "ssh")
    # The environment every run gets, as STUB_USER=root for a root probe.
    env: dict[str, str] = {}

    def execute(self, cmd, rc=0, env_extra=None):
        return super().execute(cmd, rc, {**self.env, **(env_extra or {})})


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


@pytest.fixture
def host(tmp_path) -> LangHost:
    return LangHost(tmp_path).knob(KNOB)


def _knob(h: Host, *lines: str) -> Host:
    # The knob's own lines come first, so the first of LINES is line 3.
    return h.knob(KNOB + "".join(f"{line}\n" for line in lines))


def _images(h: Host, listing: str) -> Host:
    # A running dockerd, and `docker images` as the probe formats it.
    h.show("docker.service", ActiveState="active")
    h.on("docker", "images --format*", listing)
    return h


def _system_uv(h: Host, body: str, where: str = "usr/local/bin/uv") -> Path:
    return h.write(where, "#!/bin/sh\n" + body, mode=0o755)


# --- #508: a knob service's tree with no lockfile ------------------------------


@pytest.mark.parametrize("unit", ["app.service", "app"])
def test_a_knob_service_whose_tree_holds_no_lockfile_is_listed(host, unit):
    _tree(host, locks=())
    _knob(host, f"service {unit}")
    _uv(host)
    out = _audit(host)
    assert _lang(out) == [
        {
            "dir": f"/{APP}",
            "lockfile": None,
            "units": ["app.service"],
            "owner": "unknown",
            "owner_line": None,
            "audited": False,
            "advisories": None,
            "packages": None,
            "why": NO_LOCK,
        }
    ]
    assert out["pending"]["language"]["complete"] is False
    assert not host.calls("uv")


def test_another_units_directory_with_no_lockfile_is_nobodys_tree(host):
    # Not a knob service: an admin's unit runs from anywhere.
    _tree(host, locks=())
    _uv(host)
    out = _audit(host)
    assert out["pending"]["language"] == {"trees": [], "complete": True}


def test_a_knob_service_beside_its_lock_is_audited_as_before(host):
    _tree(host)
    _knob(host, "service app.service")
    _uv(host)
    out = _audit(host)
    [t] = _lang(out)
    assert (t["lockfile"], t["audited"]) == ("uv.lock", True)
    assert out["pending"]["language"]["complete"] is True


# --- #508, #427: an owner line that matches nothing ----------------------------


def test_an_owner_line_that_matches_nothing_is_a_knob_finding(host):
    # No docker: a running host with none has no images to match.
    host.absent("docker")
    _knob(host, "owner /srv/app/live CannObserv/app")
    out = host.run()
    f = _finding(out, "owner:/srv/app/live")
    assert f["kind"] == "knob"
    assert f["message"].startswith(
        "knob line 3: owner /srv/app/live matches nothing on this host"
    )
    assert "correct the line, or remove it" in f["message"]


@pytest.mark.parametrize(
    "glob",
    [
        "tool",  # a binary's basename
        "/usr/local/bin/tool",  # its path
        f"/{APP}",  # a unit's WorkingDirectory=, without --refresh-into
        "/home/exedev/*",  # a glob over a tree
        "socraticode/ollama-slim",  # every tag of an image's repository
        "qdrant/qdrant:v1.17.0",  # one image's repository:tag
    ],
)
def test_an_owner_line_that_matches_something_is_no_finding(host, glob):
    host.write("usr/local/bin/tool", "#!/bin/sh\n", mode=0o755)
    _tree(host)
    _images(
        host,
        "socraticode/ollama-slim:0.34.0|3 hours ago\nqdrant/qdrant:v1.17.0|7 months ago\n",
    )
    _knob(host, f"owner {glob} self")
    out = host.run()
    assert not [i for i in _ids(out) if i.startswith("owner:")]
    assert not [n for n in out["not_read"] if "owner line" in n]


def test_an_owner_line_is_no_finding_while_the_images_went_unread(host):
    # docker is there, and dockerd isn't running: an unread image may be
    # the one the line names.
    _knob(host, "owner socraticode/ollama-slim self")
    out = host.run()
    assert "owner:socraticode/ollama-slim" not in _ids(out)
    assert any(
        n.startswith("the knob's owner line 3: it matches nothing read")
        and "container images weren't read" in n
        for n in out["not_read"]
    )


def test_an_owner_line_shadowed_by_a_later_one_still_matched(host):
    # Both lines name the binary; the later one owns it, and the earlier
    # isn't stale for it.
    host.absent("docker")
    host.write("usr/local/bin/tool", "#!/bin/sh\n", mode=0o755)
    _knob(host, "owner /usr/local/bin/* image", "owner tool self")
    out = host.run()
    [b] = out["updates"]["outside_apt"]["binaries"]
    assert (b["owner"], b["owner_line"]) == ("self", 4)
    assert not [i for i in _ids(out) if i.startswith("owner:")]


# --- #427: an owner line names a container image's owner -----------------------


def test_an_owner_glob_matches_each_images_repository_and_tag(host):
    _images(
        host,
        "socraticode/ollama-slim:0.34.0|3 hours ago\n"
        "socraticode/ollama-slim:latest|5 weeks ago\n"
        "qdrant/qdrant:v1.17.0|7 months ago\n"
        "redis:7|1 year ago\n",
    )
    _knob(
        host,
        "owner socraticode/ollama-slim self",
        "owner qdrant/qdrant:v1.* CannObserv/index",
    )
    out = host.run()
    assert out["updates"]["outside_apt"]["container_images"] == [
        {
            "image": "socraticode/ollama-slim:0.34.0",
            "created": "3 hours ago",
            "owner": "self",
            "owner_line": 3,
        },
        {
            "image": "socraticode/ollama-slim:latest",
            "created": "5 weeks ago",
            "owner": "self",
            "owner_line": 3,
        },
        {
            "image": "qdrant/qdrant:v1.17.0",
            "created": "7 months ago",
            "owner": "CannObserv/index",
            "owner_line": 4,
        },
        {
            "image": "redis:7",
            "created": "1 year ago",
            "owner": None,
            "owner_line": None,
        },
    ]
    assert not [i for i in _ids(out) if i.startswith("owner:")]


def test_a_repository_glob_doesnt_match_a_longer_repository(host):
    # socraticode/ollama names neither socraticode/ollama-slim nor its tags.
    _images(host, "socraticode/ollama-slim:0.34.0|3 hours ago\n")
    _knob(host, "owner socraticode/ollama self")
    out = host.run()
    [img] = out["updates"]["outside_apt"]["container_images"]
    assert img["owner"] is None
    assert _finding(out, "owner:socraticode/ollama")["kind"] == "knob"


# --- #391: an ssh host alias's origin -----------------------------------------


@pytest.mark.parametrize(
    "url, owner",
    [
        ("git@github-usa-wa:CannObserv/usa-wa.git", "CannObserv/usa-wa"),
        ("deploy@github:CannObserv/watcher", "CannObserv/watcher"),
        ("git@github.com:CannObserv/app.git", "CannObserv/app"),
        ("https://github.com/CannObserv/app.git", "CannObserv/app"),
        # Not the shape: an alias that doesn't start with github, whatever
        # its HostName in ~/.ssh/config says.
        ("git@deploy-app:CannObserv/app.git", "unknown"),
        ("git@gitlab-app:CannObserv/app.git", "unknown"),
        ("github-app:CannObserv/app.git", "unknown"),
    ],
)
def test_an_ssh_alias_origin_names_its_owner_by_shape(host, url, owner):
    _tree(host)
    _uv(host)
    host.write(
        "home/exedev/.ssh/config",
        "Host deploy-app\n  HostName github.com\n  IdentityFile ~/.ssh/app\n",
    )
    host.write(f"{APP}/.git/config", f'[remote "origin"]\n\turl = {url}\n')
    [t] = _lang(_audit(host))
    assert (t["owner"], t["owner_line"]) == (owner, None)
    assert not host.calls("ssh")


# --- #422: a uv with no audit -------------------------------------------------

NO_AUDIT = (
    "error: unrecognized subcommand 'audit'\n\n"
    "Usage: uv [OPTIONS] <COMMAND>\n\nFor more information, try '--help'.\n"
)


@pytest.mark.parametrize(
    "version, why",
    [
        (
            'echo "uv 0.10.4"',
            "uv 0.10.4 has no `audit`; needs >= 0.10.8: upgrade /usr/local/bin/uv",
        ),
        ("exit 1", "uv has no `audit`; needs >= 0.10.8: upgrade /usr/local/bin/uv"),
    ],
)
def test_a_uv_with_no_audit_names_its_version_and_the_first_with_one(
    host, version, why
):
    _tree(host)
    _knob(host, "owner /home/exedev/app CannObserv/app")
    ran = host.tmp / "uv.args"
    (host.tmp / "no-audit").write_text(NO_AUDIT)
    _system_uv(
        host,
        f'printf "%s\\n" "$*" >> "{ran}"\n'
        f'case $1 in --version) {version} ;; *) cat "{host.tmp}/no-audit" >&2; exit 2 ;; esac\n',
    )
    out = _audit(host)
    [t] = _lang(out)
    assert (t["audited"], t["advisories"], t["why"]) == (False, None, why)
    # Routed to the tree's owner, who upgrades it.
    assert (t["owner"], t["owner_line"]) == ("CannObserv/app", 3)
    assert out["pending"]["language"]["complete"] is False
    # No fetch: the audit and the version, and no other uv.
    assert ran.read_text().splitlines() == [
        "audit --frozen --no-cache --no-python-downloads --no-config",
        "--version",
    ]
    assert not host.calls("uv") and not host.calls("curl")


# --- #456: a root-owned lock --------------------------------------------------

ROOT_LOCK = (
    "its uv.lock is root's, so it's audited as nobody with a uv only root can "
    "change, and neither /usr/local/bin/uv nor /usr/bin/uv is one"
)
needs_root = pytest.mark.skipif(
    os.geteuid() != 0, reason="only root can make the root-owned files this reads"
)


def _root_tree(h: Host) -> Host:
    # The lock's uid is the test's, which /etc/passwd names root.
    _tree(h)
    h.write("etc/passwd", f"root:x:{os.getuid()}:0:root:/root:/bin/bash\n")
    return h


@needs_root
@pytest.mark.parametrize("where", ["usr/local/bin/uv", "usr/bin/uv"])
def test_a_root_owned_lock_is_audited_as_nobody_with_a_root_only_uv(host, where):
    _root_tree(host)
    on_path = _uv(host)
    seen = host.tmp / "system-uv.seen"
    (host.tmp / "clean").write_text(UV_CLEAN)
    _system_uv(
        host,
        f'printf "%s %s %s\\n" "$PWD" "${{STUB_USER:-exedev}}" "$(ls)" > "{seen}"\n'
        f'cat "{host.tmp}/clean" >&2\n',
        where,
    )
    [t] = _lang(_audit(host))
    assert (t["audited"], t["advisories"], t["why"]) == (True, 0, None)
    where_ran, who, files = seen.read_text().split(" ", 2)
    assert who == "nobody" and files.split() == ["pyproject.toml", "uv.lock"]
    assert not where_ran.startswith(str(host.root))
    # The probe's PATH, where a user-writable uv can come from, isn't asked.
    assert not on_path.exists() and not host.calls("uv")


@needs_root
@pytest.mark.parametrize(
    "case",
    [
        "home only",
        "path only",
        "group-writable",
        "not root's",
        "dir not root's",
        "a root-owned link into a home",
    ],
)
def test_a_root_owned_lock_never_takes_a_uv_another_user_can_change(host, case):
    _root_tree(host)
    on_path = _uv(host)
    ran = host.tmp / "system-uv.ran"
    body = f'touch "{ran}"\necho "Found no known vulnerabilities" >&2\n'
    if case == "home only":
        _system_uv(host, body, "root/.local/bin/uv")
    elif case != "path only":
        uv = _system_uv(host, body)
        if case == "group-writable":
            uv.chmod(0o775)
        elif case == "not root's":
            os.chown(uv, 1000, 1000)
        elif case == "dir not root's":
            os.chown(uv.parent, 1000, 1000)
        else:
            # CR 1138: the link is root's, and what it runs is the user's.
            target = _system_uv(host, body, "home/exedev/.local/bin/uv")
            os.chown(target, 1000, 1000)
            uv.unlink()
            uv.symlink_to(target)
    [t] = _lang(_audit(host))
    assert (t["audited"], t["why"]) == (False, ROOT_LOCK)
    assert not ran.exists() and not on_path.exists()


@needs_root
def test_a_root_owned_link_to_a_root_only_uv_is_taken(host):
    # CR 1138: an installer's /usr/local/bin/uv -> /opt/uv/uv, all root's.
    _root_tree(host)
    _uv(host)
    ran = host.tmp / "system-uv.ran"
    target = _system_uv(
        host, f'touch "{ran}"\necho "Found no known vulnerabilities" >&2\n', "opt/uv/uv"
    )
    (host.root / "usr/local/bin").mkdir(parents=True)
    (host.root / "usr/local/bin/uv").symlink_to(target)
    [t] = _lang(_audit(host))
    assert (t["audited"], t["why"]) == (True, None)
    assert ran.exists()


@needs_root
def test_nobody_really_runs_the_audit_on_a_root_owned_tree(tmp_path):
    # The rest of this file drops to nobody through the sudo stub. Here
    # runuser really does, as on a host whose probe runs as root, so the
    # copy, the scratch directory and uv itself are nobody's. pytest's own
    # tmp_path is root's 0700, which nobody can't enter.
    runuser = shutil.which("runuser")
    if not runuser:
        pytest.skip("no runuser to drop to nobody")
    base = Path(tempfile.mkdtemp(prefix="lang-456."))
    try:
        base.chmod(0o755)
        h = _root_tree(LangHost(base).knob(KNOB))
        h.env = {"STUB_USER": "root"}
        out_dir = base / "seen"
        out_dir.mkdir(mode=0o777)
        out_dir.chmod(0o777)
        h.tmpdir.chmod(0o1777)
        (base / "clean").write_text(UV_CLEAN)
        _system_uv(
            h,
            f'/usr/bin/id -un > "{out_dir}/who"; ls > "{out_dir}/files"\n'
            f'cat "{base}/clean" >&2\n',
        )
        # The stubs nobody's shell reaches are the system's own.
        h.on("runuser", "*", script=f'exec {runuser} "$@"')
        (h.bin / "timeout").symlink_to(shutil.which("timeout"))
        h.on("apt-get", "update*", "Reading package lists...\n")
        out = h.run("--refresh-into", str(base / "fresh"))
        [t] = _lang(out)
        assert (t["audited"], t["why"]) == (True, None), t
        assert (out_dir / "who").read_text().strip() == "nobody"
        assert (out_dir / "files").read_text().split() == ["pyproject.toml", "uv.lock"]
    finally:
        shutil.rmtree(base)
