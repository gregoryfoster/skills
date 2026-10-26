"""The offline rig maintaining-host-disk's script tests share (#425).

A fixture co-image-base release, built here byte by byte: the canonical disk
GC's layer as a gzipped tar, filler layers either side of it, and the config
and manifest JSON that name them. A stub registry serves it on 127.0.0.1 the
way ghcr.io does: an anonymous token, the manifest by tag, and each blob by
digest behind a 307 to another path (ghcr.io redirects to
pkg-containers.githubusercontent.com). Nothing here reaches the network.

The scripts under test are copied into the test's own directory, and the copy
of `_pin.sh` is rewritten to pin the fixture release on the stub registry.
The skill's own pin is never edited, and no test runs against the real `/`:
install, update and remove take a scratch `--root`, and systemctl is a stub
that logs its argv.
"""

from __future__ import annotations

import gzip
import hashlib
import http.server
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL = REPO_ROOT / "skills" / "maintaining-host-disk"
SCRIPTS = SKILL / "scripts"

REPOSITORY = "cannobserv/co-image-base"
TAG = "0123456789abcdef0123456789abcdef01234567"
TOKEN = "fixture-token"
COPY_LINE = "COPY disk-gc/ / # buildkit"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
DOCKER_MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
DOCKER_LAYER = "application/vnd.docker.image.rootfs.diff.tar.gzip"
DOCKER_CONFIG = "application/vnd.docker.container.image.v1+json"

GC_DIR = "usr/local/lib/cannobserv/disk-gc"
JOURNALD = "usr/local/lib/systemd/journald.conf.d/zz-cannobserv-journal.conf"
UNIT_DIR = "usr/local/lib/systemd/system"


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def gc_files(version: int = 2, **changes) -> dict:
    """The layer's files, path -> (bytes, mode): VERSION 2's shape.

    A keyword names a file by its basename with `-` and `.` as `_`, and
    replaces its bytes; None drops it.
    """
    files = {
        f"{GC_DIR}/disk-gc": (b"#!/usr/bin/python3 -I\n# fixture GC\n", 0o755),
        f"{GC_DIR}/VERSION": (f"{version}\n".encode(), 0o644),
        f"{GC_DIR}/disk-gc.conf.example": (
            b"[gc]\n[sensor]\nalert_at_percent = 85\n",
            0o644,
        ),
        f"{UNIT_DIR}/cannobserv-disk-gc.service": (b"[Service]\nType=oneshot\n", 0o644),
        f"{UNIT_DIR}/cannobserv-disk-gc.timer": (
            b"[Timer]\nOnCalendar=*-*-* 05:15\n",
            0o644,
        ),
        f"{UNIT_DIR}/cannobserv-disk-headroom.service": (
            b"[Service]\nType=oneshot\n",
            0o644,
        ),
        f"{UNIT_DIR}/cannobserv-disk-headroom.timer": (
            b"[Timer]\nOnUnitActiveSec=10min\n",
            0o644,
        ),
        JOURNALD: (b"[Journal]\nSystemMaxUse=512M\n", 0o644),
    }
    for key, value in changes.items():
        matches = [p for p in files if re.sub(r"[-.]", "_", p.rsplit("/", 1)[1]) == key]
        assert len(matches) == 1, key
        if value is None:
            del files[matches[0]]
        else:
            files[matches[0]] = (value, files[matches[0]][1])
    return files


def manifest_text(files: dict) -> bytes:
    """sha256sum's own format, paths relative to `/`, VERSION included."""
    return b"".join(
        f"{hashlib.sha256(data).hexdigest()}  {path}\n".encode()
        for path, (data, _) in sorted(files.items())
    )


class Member:
    """One tar member: a directory, a regular file, or anything else by type."""

    def __init__(self, name, data=b"", mode=0o644, kind=tarfile.REGTYPE, linkname=""):
        self.name, self.data, self.mode, self.kind, self.linkname = (
            name,
            data,
            mode,
            kind,
            linkname,
        )


def gc_members(files: dict | None = None, manifest: bytes | None = None) -> list:
    """The layer's members as buildkit writes them: each parent directory
    first, then MANIFEST and the files it lists."""
    files = gc_files() if files is None else files
    manifest = manifest_text(files) if manifest is None else manifest
    paths = dict(files)
    paths[f"{GC_DIR}/MANIFEST"] = (manifest, 0o644)
    dirs = set()
    for path in paths:
        parts = path.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))
    members = [Member(d + "/", mode=0o755, kind=tarfile.DIRTYPE) for d in sorted(dirs)]
    members += [Member(p, data, mode) for p, (data, mode) in sorted(paths.items())]
    return members


def tar_bytes(members: list) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for m in members:
            info = tarfile.TarInfo(m.name)
            info.type = m.kind
            info.mode = m.mode
            info.mtime = 1_700_000_000
            info.linkname = m.linkname
            if m.kind in (tarfile.REGTYPE, tarfile.AREGTYPE):
                info.size = len(m.data)
                tar.addfile(info, io.BytesIO(m.data))
            else:
                tar.addfile(info)
    return buf.getvalue()


def gz(data: bytes) -> bytes:
    return gzip.compress(data, mtime=0)


class Image:
    """A release: its manifest and config as dicts, and its blobs by digest.

    Tests change any of it, then `serialize()` recomputes every digest that
    follows from what they changed, unless they ask it not to.
    """

    def __init__(self, gc_layer_tar: bytes | None = None):
        self.layer_tars = [
            tar_bytes([Member("etc/", kind=tarfile.DIRTYPE, mode=0o755)]),
            tar_bytes(gc_members()) if gc_layer_tar is None else gc_layer_tar,
            tar_bytes([Member("opt/", kind=tarfile.DIRTYPE, mode=0o755)]),
        ]
        self.history = [
            {"created_by": "ARG RELEASE", "empty_layer": True},
            {"created_by": "RUN /bin/sh -c apt-get update # buildkit"},
            {"created_by": "ENV PATH=/usr/bin", "empty_layer": True},
            {"created_by": COPY_LINE},
            {"created_by": "RUN /bin/sh -c true # buildkit"},
        ]
        self.manifest_media_type = DOCKER_MANIFEST
        self.layer_media_type = DOCKER_LAYER
        # Hooks a test sets to break one digest after the rest are computed.
        self.diff_ids_override = None
        self.extra_layers = []

    def serialize(self):
        """(manifest bytes, {digest: blob bytes}, config dict, manifest dict)."""
        blobs = {}
        layers = []
        diff_ids = []
        for tar in self.layer_tars:
            blob = gz(tar)
            digest = sha256(blob)
            blobs[digest] = blob
            layers.append(
                {
                    "mediaType": self.layer_media_type,
                    "size": len(blob),
                    "digest": digest,
                }
            )
            diff_ids.append(sha256(tar))
        layers += self.extra_layers
        if self.diff_ids_override is not None:
            diff_ids = self.diff_ids_override(diff_ids)
        config = {
            "architecture": "amd64",
            "os": "linux",
            "history": self.history,
            "rootfs": {"type": "layers", "diff_ids": diff_ids},
        }
        config_bytes = json.dumps(config, indent=2).encode()
        config_digest = sha256(config_bytes)
        blobs[config_digest] = config_bytes
        manifest = {
            "schemaVersion": 2,
            "mediaType": self.manifest_media_type,
            "config": {
                "mediaType": DOCKER_CONFIG,
                "size": len(config_bytes),
                "digest": config_digest,
            },
            "layers": layers,
        }
        return json.dumps(manifest, indent=3).encode(), blobs, config, manifest


class Registry:
    """ghcr.io's three endpoints, for one repository and one tag.

    `served` overrides the bytes a blob's digest answers with, so a test can
    serve bytes that don't match the digest the manifest names. `requests`
    records each path and the headers it came with.
    """

    def __init__(self):
        self.manifest = b""
        self.manifest_type = DOCKER_MANIFEST
        self.blobs = {}
        self.served = {}
        self.requests = []
        registry = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body=b"", ctype="application/octet-stream", extra=()):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in extra:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                registry.requests.append((self.path, dict(self.headers)))
                path = self.path
                if path == f"/token?scope=repository:{REPOSITORY}:pull":
                    return self._send(
                        200, json.dumps({"token": TOKEN}).encode(), "application/json"
                    )
                authed = self.headers.get("Authorization") == f"Bearer {TOKEN}"
                base = f"/v2/{REPOSITORY}"
                if path == f"{base}/manifests/{TAG}":
                    if not authed:
                        return self._send(401)
                    return self._send(200, registry.manifest, registry.manifest_type)
                if path.startswith(f"{base}/blobs/"):
                    if not authed:
                        return self._send(401)
                    digest = path.rsplit("/", 1)[1]
                    return self._send(
                        307, extra=[("Location", f"/storage/{digest}?sig=x")]
                    )
                if path.startswith("/storage/"):
                    digest = path[len("/storage/") :].split("?", 1)[0]
                    body = registry.served.get(digest, registry.blobs.get(digest))
                    if body is None:
                        return self._send(404)
                    return self._send(200, body)
                return self._send(404)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def publish(self, image: Image) -> str:
        """Serve the image, and return its manifest digest: the pin."""
        manifest, blobs, _, _ = image.serialize()
        self.manifest = manifest
        self.manifest_type = image.manifest_media_type
        self.blobs = blobs
        return sha256(manifest)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def clean_env(extra: dict | None = None) -> dict:
    """No proxy (the stub is on loopback), no git, the C locale."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_")
        and k.lower() not in ("http_proxy", "https_proxy", "all_proxy")
    }
    env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
    env["LC_ALL"] = "C"
    env.update(extra or {})
    return env


def missing_tools(*tools: str) -> list:
    return [t for t in tools if shutil.which(t) is None]


def require_linux_tools():
    """The scripts run on a Debian or Ubuntu host: GNU coreutils and tar."""
    missing = missing_tools("curl", "tar", "sha256sum", "install", "stat")
    if missing:
        pytest.skip(f"needs {', '.join(missing)} on PATH (a Linux host's coreutils)")
    probe = subprocess.run(["stat", "-c", "%a", "/"], capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip("stat is not GNU stat (no -c), so this is not a Linux host")


def copy_scripts(
    dest: Path, registry_url: str, digest: str, version: int = 2, tag: str = TAG
) -> Path:
    """The skill's scripts in `dest`, their pin rewritten to the fixture's."""
    shutil.copytree(SCRIPTS, dest, ignore=shutil.ignore_patterns("__pycache__"))
    pin = dest / "_pin.sh"
    text = pin.read_text()
    for key, value in (
        ("DISK_GC_REGISTRY", registry_url),
        ("DISK_GC_TAG", tag),
        ("DISK_GC_MANIFEST_DIGEST", digest),
        ("DISK_GC_VERSION", str(version)),
    ):
        text, n = re.subn(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
        assert n == 1, f"_pin.sh must set {key} exactly once"
    pin.write_text(text)
    return dest


def run(script: Path, *args, env=None, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *map(str, args)],
        capture_output=True,
        text=True,
        env=clean_env(env),
        cwd=cwd,
        timeout=120,
    )


def stdout_json(result: subprocess.CompletedProcess) -> dict:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise AssertionError(
            f"stdout is not one JSON document ({e}):\n{result.stdout}\nstderr:\n{result.stderr}"
        ) from e


def stage(dest: Path, files: dict | None = None, manifest: bytes | None = None) -> Path:
    """A staging tree as the puller leaves it, written directly."""
    files = gc_files() if files is None else files
    manifest = manifest_text(files) if manifest is None else manifest
    for path, (data, mode) in files.items():
        p = dest / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        p.chmod(mode)
    m = dest / GC_DIR / "MANIFEST"
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_bytes(manifest)
    m.chmod(0o644)
    return dest


def tree(root: Path) -> dict:
    """Every regular file under root: relative path -> (bytes, mode)."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            out[str(p.relative_to(root))] = (
                p.read_bytes(),
                stat.S_IMODE(p.stat().st_mode),
            )
    return out


def stub_systemctl(bindir: Path) -> Path:
    """A systemctl that appends its argv, one call per line, to its log."""
    bindir.mkdir(parents=True, exist_ok=True)
    log = bindir / "systemctl.log"
    stub = bindir / "systemctl"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"{log}"\n')
    stub.chmod(0o755)
    return stub


def calls(stub: Path) -> list:
    log = stub.parent / "systemctl.log"
    return log.read_text().splitlines() if log.exists() else []


def make_host(root: Path) -> Path:
    """A scratch root with the host's own files in /etc and /var/lib, and
    the GC timer enabled."""
    conf = root / "etc/cannobserv/disk-gc"
    conf.mkdir(parents=True)
    (conf / "disk-gc.conf").write_text("[sensor]\nalert_at_percent = 80\n")
    (conf / "checkin.key").write_text("secret\n")
    (conf / "checkin.key").chmod(0o600)
    state = root / "var/lib/cannobserv-disk-gc"
    state.mkdir(parents=True)
    (state / "state.json").write_text("{}\n")
    wants = root / "etc/systemd/system/timers.target.wants"
    wants.mkdir(parents=True)
    os.symlink(
        "/usr/local/lib/systemd/system/cannobserv-disk-gc.timer",
        wants / "cannobserv-disk-gc.timer",
    )
    return root


def host_files(root: Path) -> dict:
    """What a host owns, which no script here may change."""
    keep = {}
    for rel in (
        "etc/cannobserv/disk-gc/disk-gc.conf",
        "etc/cannobserv/disk-gc/checkin.key",
        "var/lib/cannobserv-disk-gc/state.json",
    ):
        p = root / rel
        keep[rel] = (p.read_bytes(), oct(p.stat().st_mode))
    link = root / "etc/systemd/system/timers.target.wants/cannobserv-disk-gc.timer"
    keep["wants"] = os.readlink(link)
    return keep
