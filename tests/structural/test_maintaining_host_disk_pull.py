"""#425 — pull-disk-gc.sh stages the canonical GC's layer, or refuses.

The pull contract's steps 1–8 ([#425's contract comment]), each a refusal:
the pinned manifest digest, an index refused, the config digest, exactly one
`COPY disk-gc/ / # buildkit` layer found by `.history`, the layer counts
agreeing, the blob and diff_id digests, every member checked before anything
is extracted, and MANIFEST's exact file set checked by `sha256sum --strict
-c` in staging. A refusal exits 3, says which step on stdout as JSON, and
leaves no staging directory behind for an install to pick up.

Offline: the release is a fixture and the registry is a loopback stub
(`maintaining_host_disk_rig.py`).

[#425's contract comment]: https://github.com/gregoryfoster/skills/issues/425#issuecomment-6371095613
"""

import hashlib
import json
import os
import shutil
import signal
import tarfile

import pytest

from tests.structural import maintaining_host_disk_rig as rig

pytestmark = pytest.mark.usefixtures("linux_tools")


@pytest.fixture
def linux_tools():
    rig.require_linux_tools()


@pytest.fixture
def registry():
    r = rig.Registry()
    yield r
    r.close()


def pull(
    tmp_path, registry, image, digest=None, version=2, manifest_sha=None, env=None
):
    """Publish image, pin it (or `digest`), and run the copied puller."""
    published = registry.publish(image)
    scripts = rig.copy_scripts(
        tmp_path / "scripts",
        registry.url,
        digest or published,
        version=version,
        manifest_sha=manifest_sha,
    )
    into = tmp_path / "staging"
    result = rig.run(scripts / "pull-disk-gc.sh", "--into", into, env=env)
    return result, into


def refused(result, step):
    assert result.returncode == 3, (result.returncode, result.stdout, result.stderr)
    out = rig.stdout_json(result)
    assert out["ok"] is False
    assert out["refused"]["step"] == step, out
    return out["refused"]["why"]


# --- the pass ----------------------------------------------------------------


def test_stages_the_layer(tmp_path, registry):
    result, into = pull(tmp_path, registry, rig.Image())
    assert result.returncode == 0, result.stderr
    out = rig.stdout_json(result)
    assert out["ok"] is True
    assert out["version"] == 2
    assert out["layer"]["index"] == 1
    want = rig.gc_files()
    staged = rig.tree(into)
    assert set(staged) == set(want) | {f"{rig.GC_DIR}/MANIFEST"}
    for path, (data, mode) in want.items():
        assert staged[path] == (data, mode), path
    assert sorted(out["files"]) == sorted(staged)


def test_layer_is_found_by_history_not_position(tmp_path, registry):
    """The n-th non-empty history entry made the n-th layer. Here the GC's
    layer is the middle one of three, behind two empty-layer entries."""
    result, _ = pull(tmp_path, registry, rig.Image())
    assert result.returncode == 0, result.stderr
    out = rig.stdout_json(result)
    _, _, _, m = rig.Image().serialize()
    assert out["layer"]["digest"] == m["layers"][1]["digest"]


def test_manifest_request_names_both_manifest_types(tmp_path, registry):
    result, _ = pull(tmp_path, registry, rig.Image())
    assert result.returncode == 0, result.stderr
    (path, headers), *_ = [r for r in registry.requests if "/manifests/" in r[0]]
    assert path.endswith(f"/manifests/{rig.TAG}")
    accept = headers.get("Accept", "")
    assert rig.OCI_MANIFEST in accept and rig.DOCKER_MANIFEST in accept


def test_an_oci_manifest_passes_too(tmp_path, registry):
    image = rig.Image()
    image.manifest_media_type = rig.OCI_MANIFEST
    image.layer_media_type = "application/vnd.oci.image.layer.v1.tar+gzip"
    result, _ = pull(tmp_path, registry, image)
    assert result.returncode == 0, result.stderr


def test_a_root_entry_and_dot_slash_names_pass(tmp_path, registry):
    """Some tar writers emit the archive's root as `./` and prefix every
    name with it; that is the same layer, not a refusal."""
    members = [rig.Member("./", kind=tarfile.DIRTYPE, mode=0o755)]
    for m in rig.gc_members():
        m.name = "./" + m.name
        members.append(m)
    image = rig.Image(gc_layer_tar=rig.tar_bytes(members))
    result, into = pull(tmp_path, registry, image)
    assert result.returncode == 0, result.stdout
    assert (into / rig.GC_DIR / "disk-gc").is_file()


def test_never_asks_for_latest(tmp_path, registry):
    pull(tmp_path, registry, rig.Image())
    assert not [p for p, _ in registry.requests if "latest" in p]


# --- step 1: the pin ---------------------------------------------------------


def test_pin_of_latest_is_refused(tmp_path, registry):
    digest = registry.publish(rig.Image())
    scripts = rig.copy_scripts(tmp_path / "s", registry.url, digest, tag="latest")
    result = rig.run(scripts / "pull-disk-gc.sh", "--into", tmp_path / "staging")
    refused(result, "pin")
    assert not registry.requests


# --- step 3: the manifest ----------------------------------------------------


def test_wrong_manifest_digest(tmp_path, registry):
    result, into = pull(tmp_path, registry, rig.Image(), digest="sha256:" + "0" * 64)
    why = refused(result, "manifest")
    assert "digest" in why
    assert not into.exists()


def test_index_is_refused(tmp_path, registry):
    """An index pinned by its own digest passes the digest check and still
    refuses: the contract wants a single-platform manifest."""
    index = (
        b'{"schemaVersion": 2, "mediaType": "%s", "manifests": []}'
        % rig.OCI_INDEX.encode()
    )
    registry.publish(rig.Image())
    registry.manifest = index
    registry.manifest_type = rig.OCI_INDEX
    scripts = rig.copy_scripts(tmp_path / "s", registry.url, rig.sha256(index))
    result = rig.run(scripts / "pull-disk-gc.sh", "--into", tmp_path / "staging")
    assert refused(result, "manifest") == (
        "the pinned digest names an index, not one image"
    )


# --- step 4: the config ------------------------------------------------------


def test_config_digest_mismatch(tmp_path, registry):
    image = rig.Image()
    _, blobs, _, manifest = image.serialize()
    digest = manifest["config"]["digest"]
    # The same length, one byte different: the size passes, the digest doesn't.
    real = blobs[digest]
    registry.served[digest] = real[:-1] + (b" " if real[-1:] != b" " else b"\n")
    result, _ = pull(tmp_path, registry, image)
    assert "digest" in refused(result, "config")


# --- step 5: the layer, by history ------------------------------------------


def test_no_copy_entry(tmp_path, registry):
    image = rig.Image()
    image.history[3]["created_by"] = "COPY other/ / # buildkit"
    result, _ = pull(tmp_path, registry, image)
    assert "0" in refused(result, "layer")


def test_two_copy_entries(tmp_path, registry):
    image = rig.Image()
    image.history[4]["created_by"] = rig.COPY_LINE
    result, _ = pull(tmp_path, registry, image)
    assert "2" in refused(result, "layer")


def test_copy_entry_marked_empty_does_not_count(tmp_path, registry):
    image = rig.Image()
    image.history.append({"created_by": rig.COPY_LINE, "empty_layer": True})
    result, _ = pull(tmp_path, registry, image)
    assert result.returncode == 0, result.stdout


def test_layer_count_mismatch_history(tmp_path, registry):
    image = rig.Image()
    image.history.append({"created_by": "RUN /bin/sh -c late # buildkit"})
    result, _ = pull(tmp_path, registry, image)
    assert "count" in refused(result, "layer")


def test_layer_count_mismatch_manifest(tmp_path, registry):
    image = rig.Image()
    image.extra_layers = [
        {"mediaType": rig.DOCKER_LAYER, "size": 1, "digest": "sha256:" + "1" * 64}
    ]
    result, _ = pull(tmp_path, registry, image)
    assert "count" in refused(result, "layer")


def test_layer_count_mismatch_diff_ids(tmp_path, registry):
    image = rig.Image()
    image.diff_ids_override = lambda ids: ids + ["sha256:" + "2" * 64]
    result, _ = pull(tmp_path, registry, image)
    assert "count" in refused(result, "layer")


def test_layer_that_is_not_gzip_is_refused(tmp_path, registry):
    image = rig.Image()
    image.layer_media_type = "application/vnd.oci.image.layer.v1.tar+zstd"
    image.manifest_media_type = rig.OCI_MANIFEST
    result, _ = pull(tmp_path, registry, image)
    assert "mediaType" in refused(result, "layer")


# --- step 6: the blob --------------------------------------------------------


def test_blob_digest_mismatch(tmp_path, registry):
    image = rig.Image()
    _, blobs, _, manifest = image.serialize()
    digest = manifest["layers"][1]["digest"]
    real = blobs[digest]
    # The same length, one byte flipped: the size passes, the digest doesn't.
    registry.served[digest] = real[:20] + bytes([real[20] ^ 0xFF]) + real[21:]
    result, into = pull(tmp_path, registry, image)
    assert "digest" in refused(result, "blob")
    assert not into.exists()


def test_diff_id_mismatch(tmp_path, registry):
    image = rig.Image()

    def swap(ids):
        ids = list(ids)
        ids[1] = "sha256:" + "3" * 64
        return ids

    image.diff_ids_override = swap
    result, _ = pull(tmp_path, registry, image)
    assert "diff_id" in refused(result, "blob")


# --- step 7: the members, before anything is extracted -----------------------


def layer_with(extra):
    return rig.Image(gc_layer_tar=rig.tar_bytes(rig.gc_members() + [extra]))


@pytest.mark.parametrize(
    "member, says",
    [
        (rig.Member("usr/local/lib/cannobserv/../../../etc/passwd", b"x"), ".."),
        (rig.Member("usr/local/lib/cannobserv/disk-gc/.wh.disk-gc"), "whiteout"),
        (rig.Member("usr/local/lib/.wh..wh..opq"), "whiteout"),
        (
            rig.Member(
                "usr/local/lib/cannobserv/disk-gc/run",
                kind=tarfile.SYMTYPE,
                linkname="/etc/shadow",
            ),
            "link",
        ),
        (
            rig.Member(
                "usr/local/lib/cannobserv/disk-gc/hard",
                kind=tarfile.LNKTYPE,
                linkname="usr/local/lib/cannobserv/disk-gc/disk-gc",
            ),
            "link",
        ),
        (rig.Member("etc/cannobserv/disk-gc/disk-gc.conf", b"x"), "outside"),
        (rig.Member("usr/local/bin/disk-gc", b"x", mode=0o755), "outside"),
        (rig.Member("usr/local/lib", b"x"), "outside"),
        (rig.Member("/usr/local/lib/abs", b"x"), "absolute"),
        (rig.Member("usr/local/lib/fifo", kind=tarfile.FIFOTYPE), "type"),
        (rig.Member("usr/local/lib/cannobserv/s", b"x", mode=0o4755), "mode"),
        (rig.Member("usr/local/lib/cannobserv/w", b"x", mode=0o666), "mode"),
        (rig.Member("usr/local/lib/cannobserv/disk-gc/disk-gc", b"again"), "twice"),
        (rig.Member("usr/local/lib/cannobserv/a\nb", b"x"), "control"),
    ],
    ids=lambda v: v.name if isinstance(v, rig.Member) else v,
)
def test_member_refusals(tmp_path, registry, member, says):
    result, into = pull(tmp_path, registry, layer_with(member))
    assert says in refused(result, "members")
    assert not into.exists(), "a refused member must leave nothing extracted"


# --- step 8: MANIFEST in staging ---------------------------------------------


def test_manifest_check_failure(tmp_path, registry):
    files = rig.gc_files()
    manifest = rig.manifest_text(files)
    files = rig.gc_files(disk_gc=b"not what MANIFEST hashed\n")
    image = rig.Image(gc_layer_tar=rig.tar_bytes(rig.gc_members(files, manifest)))
    result, into = pull(tmp_path, registry, image)
    assert "sha256sum" in refused(result, "staging")
    assert not into.exists()


def test_extra_file(tmp_path, registry):
    extra = rig.Member(f"{rig.GC_DIR}/stowaway", b"x")
    result, into = pull(tmp_path, registry, layer_with(extra))
    why = refused(result, "staging")
    assert "stowaway" in why
    assert not into.exists()


def test_missing_manifest(tmp_path, registry):
    members = [m for m in rig.gc_members() if not m.name.endswith("/MANIFEST")]
    result, _ = pull(tmp_path, registry, rig.Image(gc_layer_tar=rig.tar_bytes(members)))
    assert "MANIFEST" in refused(result, "staging")


def test_missing_version(tmp_path, registry):
    files = rig.gc_files(VERSION=None)
    image = rig.Image(gc_layer_tar=rig.tar_bytes(rig.gc_members(files)))
    result, _ = pull(tmp_path, registry, image)
    assert "VERSION" in refused(result, "staging")


def test_manifest_path_outside_the_prefix(tmp_path, registry):
    files = rig.gc_files()
    manifest = rig.manifest_text(files) + b"%s  etc/passwd\n" % (b"0" * 64)
    image = rig.Image(gc_layer_tar=rig.tar_bytes(rig.gc_members(files, manifest)))
    result, _ = pull(tmp_path, registry, image)
    assert "etc/passwd" in refused(result, "staging")


def test_version_other_than_the_pin(tmp_path, registry):
    files = rig.gc_files(version=3)
    image = rig.Image(gc_layer_tar=rig.tar_bytes(rig.gc_members(files)))
    sha = hashlib.sha256(rig.manifest_text(files)).hexdigest()
    result, _ = pull(tmp_path, registry, image, manifest_sha=sha)
    assert "VERSION" in refused(result, "staging")


# --- CR 520: modes, and MANIFEST bound to the pin --------------------------------


def test_manifest_other_than_the_pinned_one_is_refused(tmp_path, registry):
    """A layer whose files and MANIFEST agree, but whose MANIFEST isn't the
    one the pin names: sha256sum -c alone would pass it."""
    files = rig.gc_files(disk_gc=b"#!/bin/sh\n# not the release\n")
    image = rig.Image(gc_layer_tar=rig.tar_bytes(rig.gc_members(files)))
    result, into = pull(tmp_path, registry, image)
    assert "pin" in refused(result, "staging")
    assert not into.exists()


def test_root_entry_mode_other_than_0755_is_refused(tmp_path, registry):
    members = [rig.Member("./", kind=tarfile.DIRTYPE, mode=0o777)] + rig.gc_members()
    result, into = pull(
        tmp_path, registry, rig.Image(gc_layer_tar=rig.tar_bytes(members))
    )
    assert "mode" in refused(result, "members")
    assert not into.exists()


@pytest.mark.parametrize(
    "member",
    [
        rig.Member(
            "usr/local/lib/cannobserv/hidden/", kind=tarfile.DIRTYPE, mode=0o000
        ),
        rig.Member("usr/local/lib/cannobserv/open/", kind=tarfile.DIRTYPE, mode=0o775),
        rig.Member("usr/local/lib/cannobserv/disk-gc/x", b"x", mode=0o600),
        rig.Member("usr/local/lib/cannobserv/disk-gc/y", b"x", mode=0o750),
    ],
    ids=lambda m: f"{m.name.rstrip('/').rsplit('/', 1)[1]}-{m.mode:o}",
)
def test_member_modes_are_0644_0755_or_a_0755_dir(tmp_path, registry, member):
    result, into = pull(tmp_path, registry, layer_with(member))
    assert "mode" in refused(result, "members")
    assert not into.exists()


def test_an_unreadable_staging_directory_refuses_rather_than_hides(tmp_path):
    """os.walk skips a directory it can't list unless told otherwise, which
    would hide its files from the exact-file-set check."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_pull", rig.SCRIPTS / "_pull.py")
    pull_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pull_mod)
    staging = rig.stage(tmp_path / "staging")
    sha = hashlib.sha256((staging / rig.GC_DIR / "MANIFEST").read_bytes()).hexdigest()
    calls = []

    def walk(top, onerror=None, **kw):
        calls.append(onerror)
        if onerror is not None:
            onerror(PermissionError(13, "Permission denied", str(top)))
        return iter(())

    real = pull_mod.os.walk
    pull_mod.os.walk = walk
    try:
        with pytest.raises(pull_mod.Refused) as e:
            pull_mod.check_staging(str(staging), 2, sha)
    finally:
        pull_mod.os.walk = real
    assert calls and calls[0] is not None
    assert e.value.step == "staging"


# --- usage -------------------------------------------------------------------


def test_into_must_not_exist(tmp_path, registry):
    into = tmp_path / "staging"
    into.mkdir()
    (into / "keep").write_text("mine")
    digest = registry.publish(rig.Image())
    scripts = rig.copy_scripts(tmp_path / "s", registry.url, digest)
    result = rig.run(scripts / "pull-disk-gc.sh", "--into", into)
    assert result.returncode == 2
    assert (into / "keep").read_text() == "mine"
    assert not registry.requests


def test_into_is_required(tmp_path):
    result = rig.run(rig.SCRIPTS / "pull-disk-gc.sh")
    assert result.returncode == 2
    assert "--into" in result.stderr


# --- CR 527: any failure is a refusal, and staging is never left behind ----


def load_pull():
    import importlib.util

    spec = importlib.util.spec_from_file_location("_pull_527", rig.SCRIPTS / "_pull.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_main(module, tmp_path, capsys, fake_pull):
    """main() with a stand-in for pull() that makes the staging directory
    and then fails its own way."""
    into = tmp_path / "staging"
    pin = (
        rig.copy_scripts(tmp_path / "s", "https://ghcr.io", "sha256:" + "0" * 64)
        / "_pin.sh"
    )

    def pull(pin_values, staging, work, made):
        os.mkdir(staging)
        made.append(staging)
        locked = os.path.join(staging, "usr")
        os.mkdir(locked)
        open(os.path.join(locked, "f"), "w").close()
        os.chmod(locked, 0o500)
        fake_pull()

    module.pull = pull
    rc = module.main(["--pin", str(pin), "--into", str(into)])
    out = json.loads(capsys.readouterr().out)
    return rc, out, into


def test_an_unexpected_error_is_a_refusal_with_json(tmp_path, capsys):
    module = load_pull()

    def boom():
        raise PermissionError(13, "Permission denied", "MANIFEST")

    rc, out, into = run_main(module, tmp_path, capsys, boom)
    assert rc == 3
    assert out["refused"]["step"] == "internal"
    assert "Permission denied" in out["refused"]["why"]
    assert not into.exists(), "a read-only directory inside staging still goes"


def test_a_signal_after_staging_is_made_still_removes_it(tmp_path, capsys):
    module = load_pull()

    def unhandled(signum, frame):  # so a puller without a handler can't kill pytest
        raise RuntimeError("the puller didn't handle SIGTERM")

    previous = signal.signal(signal.SIGTERM, unhandled)
    try:
        rc, out, into = run_main(
            module, tmp_path, capsys, lambda: os.kill(os.getpid(), signal.SIGTERM)
        )
        restored = signal.getsignal(signal.SIGTERM)
    finally:
        signal.signal(signal.SIGTERM, previous)
    assert restored is unhandled
    assert rc == 3
    assert out["refused"]["step"] == "internal"
    assert "signal" in out["refused"]["why"]
    assert not into.exists()


def test_staging_it_cannot_remove_is_reported(tmp_path, capsys, monkeypatch):
    module = load_pull()
    # module.shutil is the process's own shutil: patch it so it's put back.
    monkeypatch.setattr(module.shutil, "rmtree", lambda *a, **k: None)

    def boom():
        raise OSError("no")

    rc, out, into = run_main(module, tmp_path, capsys, boom)
    assert rc == 3
    assert out["staging_left"] == str(into)


# --- CR 528: https only, and nothing bigger than the manifest says ---------


def test_a_pin_on_an_http_registry_is_refused(tmp_path, registry):
    digest = registry.publish(rig.Image())
    scripts = rig.copy_scripts(tmp_path / "s", "http://127.0.0.1:1", digest)
    result = rig.run(scripts / "pull-disk-gc.sh", "--into", tmp_path / "staging")
    assert "https" in refused(result, "pin")


def test_a_redirect_to_http_is_refused(tmp_path, registry):
    registry.redirect_scheme = "http"
    result, into = pull(tmp_path, registry, rig.Image())
    refused(result, "config")
    assert not into.exists()
    assert not [p for p, _ in registry.requests if p.startswith("/storage/")]


def test_a_layer_bigger_than_its_declared_size_is_refused(tmp_path, registry):
    image = rig.Image()
    image.layer_size_override = {1: 100}
    result, into = pull(tmp_path, registry, image)
    assert "size" in refused(result, "blob")
    assert not into.exists()


def test_a_config_smaller_than_its_declared_size_is_refused(tmp_path, registry):
    image = rig.Image()
    _, _, _, manifest = image.serialize()
    image.config_size_override = manifest["config"]["size"] + 10
    result, _ = pull(tmp_path, registry, image)
    assert "size" in refused(result, "config")


# --- CR 537a: tests that hold the logic they cover --------------------------


def test_the_token_never_follows_the_redirect_to_another_host(tmp_path, registry):
    result, _ = pull(tmp_path, registry, rig.Image())
    assert result.returncode == 0, result.stderr
    storage = [h for p, h in registry.requests if p.startswith("/storage/")]
    assert storage, "the blobs must be fetched through the redirect"
    assert all("Authorization" not in h for h in storage)
    assert all(h.get("Host", "").startswith("localhost") for h in storage)


def tar_shim(tmp_path):
    """A tar on PATH that logs each call, then runs the real one."""
    bindir = tmp_path / "shim"
    bindir.mkdir()
    log = bindir / "tar.log"
    real = shutil.which("tar")
    (bindir / "tar").write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"{log}"\nexec "{real}" "$@"\n'
    )
    (bindir / "tar").chmod(0o755)
    return {"PATH": f"{bindir}:{os.environ['PATH']}"}, log


def test_nothing_is_extracted_before_the_member_checks(tmp_path, registry):
    """CR 549: GNU tar wouldn't write through an escaping link anyway, so a
    sentinel proved nothing. The shim proves tar never runs at all."""
    env, log = tar_shim(tmp_path)
    members = rig.gc_members() + [
        rig.Member(
            "usr/local/lib/cannobserv/escape", kind=tarfile.SYMTYPE, linkname="/etc"
        ),
    ]
    result, into = pull(
        tmp_path, registry, rig.Image(gc_layer_tar=rig.tar_bytes(members)), env=env
    )
    assert "link" in refused(result, "members")
    assert not log.exists(), log.read_text()
    assert not into.exists()


def test_the_tar_shim_sees_a_passing_pull(tmp_path, registry):
    """The control: the same shim does see the extraction of a good layer."""
    env, log = tar_shim(tmp_path)
    result, _ = pull(tmp_path, registry, rig.Image(), env=env)
    assert result.returncode == 0, result.stderr
    assert "-xpf" in log.read_text()


def test_into_whose_parent_is_missing_is_a_usage_error(tmp_path, registry):
    """CR 538: exit 2, before any request, as for an --into that exists."""
    digest = registry.publish(rig.Image())
    scripts = rig.copy_scripts(tmp_path / "s", registry.url, digest)
    result = rig.run(scripts / "pull-disk-gc.sh", "--into", tmp_path / "no" / "staging")
    assert result.returncode == 2, result.stdout
    assert not registry.requests


# --- CR 547: no signal escapes the cleanup, or the mkdir-to-append gap ------


def guarded(signum):
    """A handler for the test process, so a puller that lets a signal
    through fails the test instead of killing pytest."""

    def unhandled(_signum, _frame):
        raise RuntimeError(f"the puller let signal {signum} through")

    return signal.signal(signum, unhandled)


def test_a_second_signal_during_cleanup_is_ignored(tmp_path, capsys, monkeypatch):
    module = load_pull()
    real = module.remove_tree

    def remove_tree(path):
        os.kill(os.getpid(), signal.SIGTERM)  # a second TERM, mid-cleanup
        return real(path)

    monkeypatch.setattr(module, "remove_tree", remove_tree)
    previous = guarded(signal.SIGTERM)
    try:
        rc, out, into = run_main(
            module, tmp_path, capsys, lambda: os.kill(os.getpid(), signal.SIGTERM)
        )
    finally:
        signal.signal(signal.SIGTERM, previous)
    assert rc == 3
    assert out["refused"]["step"] == "internal"
    assert not into.exists()


def test_a_signal_between_mkdir_and_its_record_still_removes_staging(
    tmp_path, monkeypatch
):
    """The signal lands right after os.mkdir returns: staging must already
    be in `made`, or nothing removes it."""
    module = load_pull()
    real_mkdir = os.mkdir

    def mkdir(path, *a, **k):
        real_mkdir(path, *a, **k)
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(module.os, "mkdir", mkdir)
    staging, made = str(tmp_path / "staging"), []
    previous = signal.signal(signal.SIGTERM, module.on_signal)
    try:
        with pytest.raises(module.Refused):
            module.make_staging(staging, made)
    finally:
        signal.signal(signal.SIGTERM, previous)
    assert made == [staging]


# --- CR 552: curl reads no curlrc, and a file too big is never read in ------


def test_a_curlrc_is_never_read(tmp_path, registry):
    """-q first: ~/.curlrc could add a header, a proxy, or --insecure."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".curlrc").write_text('header = "X-From-Curlrc: read"\n')
    result, _ = pull(tmp_path, registry, rig.Image(), env={"HOME": str(home)})
    assert result.returncode == 0, result.stderr
    assert registry.requests
    assert not [h for _, h in registry.requests if "X-From-Curlrc" in h]


def test_a_file_bigger_than_declared_is_refused_before_it_is_read(
    tmp_path, monkeypatch
):
    """CR 552b: an older curl may not apply --max-filesize to a chunked
    response, so the size on disk is checked before the bytes are read."""
    module = load_pull()
    bindir = tmp_path / "shim"
    bindir.mkdir()
    # A curl that "downloads" 200 bytes wherever -o points, and succeeds.
    (bindir / "curl").write_text(
        "#!/usr/bin/env bash\n"
        'while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done\n'
        'head -c 200 /dev/zero >"$out"\n'
    )
    (bindir / "curl").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    out = tmp_path / "blob"
    opened = []
    real_open = open

    def watching_open(path, *a, **k):
        opened.append(str(path))
        return real_open(path, *a, **k)

    monkeypatch.setattr(module, "open", watching_open, raising=False)
    with pytest.raises(module.Refused) as e:
        module.fetch("https://x.example/blob", str(out), "blob", size=100)
    assert "200" in e.value.why
    assert str(out) not in opened
