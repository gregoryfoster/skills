"""_pull.py — the canonical disk GC's pull contract, steps 1–8 (#425).

Run by pull-disk-gc.sh, which documents it; not meant to be run directly.
Every check refuses: it prints {"ok": false, "refused": {"step", "why"}} on
stdout, removes the staging directory it made, and exits 3. curl fetches
(it drops the token on the registry's cross-host redirect, as urllib would
not), and `sha256sum --strict -c` checks MANIFEST, as the contract says.
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
REGISTRY = re.compile(r"https://[A-Za-z0-9.-]+(:[0-9]+)?\Z")
REPOSITORY = re.compile(r"[a-z0-9]+([._/-][a-z0-9]+)*\Z")
PIN_LINE = re.compile(r"^(DISK_GC_[A-Z0-9_]+)=(.*)$", re.M)
PIN_KEYS = (
    "DISK_GC_REGISTRY",
    "DISK_GC_REPOSITORY",
    "DISK_GC_TAG",
    "DISK_GC_MANIFEST_DIGEST",
    "DISK_GC_VERSION",
    "DISK_GC_MANIFEST_SHA256",
)

MANIFEST_TYPES = (
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
)
INDEX_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)
GZIP_LAYER_TYPES = (
    "application/vnd.oci.image.layer.v1.tar+gzip",
    "application/vnd.docker.image.rootfs.diff.tar.gzip",
)
COPY_LINE = "COPY disk-gc/ / # buildkit"
PREFIX = "usr/local/lib/"
PREFIX_PARENTS = ("usr", "usr/local", "usr/local/lib")
GC_DIR = "usr/local/lib/cannobserv/disk-gc/"
MANIFEST = GC_DIR + "MANIFEST"
VERSION = GC_DIR + "VERSION"
# The layer is ~22 KB gzipped (VERSION 2); anything near this is not it.
MAX_LAYER_BYTES = 16 * 1024 * 1024
MANIFEST_LINE = re.compile(r"([0-9a-f]{64})  (.+)\Z")


class Refused(Exception):
    def __init__(self, step, why):
        super().__init__(why)
        self.step, self.why = step, why


def sha256_of(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_pin(path):
    """The pin file's KEY=value lines, each checked for its shape."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        raise Refused("pin", f"can't read {path}: {e.strerror}") from e
    found = {}
    for key, value in PIN_LINE.findall(text):
        if key in found:
            raise Refused("pin", f"{key} is set twice")
        found[key] = value
    missing = [k for k in PIN_KEYS if k not in found]
    if missing:
        raise Refused("pin", f"missing {', '.join(missing)}")
    checks = (
        ("DISK_GC_REGISTRY", REGISTRY, "https:// and a host"),
        ("DISK_GC_REPOSITORY", REPOSITORY, "a repository name"),
        ("DISK_GC_TAG", HEX40, "a released tag, 40 hex (never :latest)"),
        ("DISK_GC_MANIFEST_DIGEST", DIGEST, "sha256:<64 hex>"),
        ("DISK_GC_VERSION", re.compile(r"[1-9][0-9]*\Z"), "a positive integer"),
        ("DISK_GC_MANIFEST_SHA256", re.compile(r"[0-9a-f]{64}\Z"), "64 hex"),
    )
    for key, pattern, shape in checks:
        if not pattern.match(found[key]):
            raise Refused("pin", f"{key}={found[key]!r} is not {shape}")
    return found


# What a response may weigh before its size is known from the manifest.
MAX_DOC_BYTES = 16 * 1024 * 1024


def fetch(url, out, step, headers=(), size=None):
    """GET url into out with curl, https only, redirects included, and its
    stderr ours, unswallowed. With `size`, the manifest's declared size: curl
    stops past it, and any other length refuses; without, MAX_DOC_BYTES."""
    # -q first: no ~/.curlrc, which could add a header, a proxy or --insecure.
    cmd = ["curl", "-q", "-fsSL", "--proto", "=https", "--proto-redir", "=https"]
    cmd += ["--max-redirs", "3", "--retry", "2", "--connect-timeout", "20"]
    cmd += ["-m", "120", "--max-filesize", str(size or MAX_DOC_BYTES), "-o", out]
    for h in headers:
        cmd += ["-H", h]
    cmd.append(url)
    rc = subprocess.run(cmd, stdout=sys.stderr).returncode
    where = url.split("?")[0]
    if rc == 63:
        raise Refused(
            step, f"GET {where} is bigger than its size, {size or MAX_DOC_BYTES} bytes"
        )
    if rc != 0:
        raise Refused(step, f"GET {where} failed (curl exit {rc})")
    with open(out, "rb") as f:
        data = f.read()
    if size is not None and len(data) != size:
        raise Refused(step, f"GET {where} is {len(data)} bytes, not its size {size}")
    return data


def declared_size(desc, what):
    size = desc.get("size")
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or not 0 < size <= MAX_LAYER_BYTES
    ):
        raise Refused(
            "manifest", f"{what} has no size, or one past {MAX_LAYER_BYTES} bytes"
        )
    return size


def load_json(data, step, what):
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeDecodeError) as e:
        raise Refused(step, f"{what} is not JSON: {e}") from e
    if not isinstance(doc, dict):
        raise Refused(step, f"{what} is not a JSON object")
    return doc


def check_manifest(data, pinned):
    """Step 3: the pinned digest first, then the shape the digest named."""
    got = sha256_of(data)
    if got != pinned:
        raise Refused("manifest", f"its digest is {got}, not the pinned {pinned}")
    doc = load_json(data, "manifest", "the manifest")
    media = doc.get("mediaType")
    if media in INDEX_TYPES or "manifests" in doc:
        raise Refused("manifest", "the pinned digest names an index, not one image")
    if media not in MANIFEST_TYPES or doc.get("schemaVersion") != 2:
        raise Refused("manifest", f"mediaType {media!r} is not an image manifest")
    config = doc.get("config")
    layers = doc.get("layers")
    if not isinstance(config, dict) or not DIGEST.match(str(config.get("digest", ""))):
        raise Refused("manifest", "its config has no sha256 digest")
    if not isinstance(layers, list) or not layers:
        raise Refused("manifest", "it lists no layers")
    for layer in layers:
        if not isinstance(layer, dict) or not DIGEST.match(
            str(layer.get("digest", ""))
        ):
            raise Refused("manifest", "a layer has no sha256 digest")
    return doc


def find_layer(manifest, config):
    """Step 5: the n-th non-empty history entry made the n-th layer."""
    history = config.get("history")
    rootfs = config.get("rootfs")
    diff_ids = rootfs.get("diff_ids") if isinstance(rootfs, dict) else None
    if not isinstance(history, list) or not isinstance(diff_ids, list):
        raise Refused("layer", "the config has no .history or .rootfs.diff_ids")
    made = [
        h for h in history if not (isinstance(h, dict) and h.get("empty_layer") is True)
    ]
    layers = manifest["layers"]
    if not len(made) == len(diff_ids) == len(layers):
        raise Refused(
            "layer",
            f"layer count disagrees: {len(made)} non-empty history entries, "
            f"{len(diff_ids)} diff_ids, {len(layers)} manifest layers",
        )
    hits = [
        i
        for i, h in enumerate(made)
        if isinstance(h, dict) and h.get("created_by") == COPY_LINE
    ]
    if len(hits) != 1:
        raise Refused(
            "layer", f"{len(hits)} history entries are {COPY_LINE!r}; exactly 1 must be"
        )
    n = hits[0]
    if not DIGEST.match(str(diff_ids[n])):
        raise Refused("layer", f"diff_ids[{n}] is not a sha256 digest")
    media = layers[n].get("mediaType")
    if media not in GZIP_LAYER_TYPES:
        raise Refused("layer", f"layer {n}'s mediaType {media!r} is not a gzipped tar")
    return n, layers[n]["digest"], diff_ids[n]


def gunzip(blob):
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(blob)) as f:
            data = f.read(MAX_LAYER_BYTES + 1)
    except (OSError, EOFError) as e:
        raise Refused("blob", f"the layer doesn't gunzip: {e}") from e
    if len(data) > MAX_LAYER_BYTES:
        raise Refused("blob", f"the layer unpacks past {MAX_LAYER_BYTES} bytes")
    return data


def safe_path(name, step):
    """A relative path with no `..`, no whiteout and no control character."""
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise Refused(step, f"{name!r} has a control character")
    if name.startswith("/"):
        raise Refused(step, f"{name!r} is absolute")
    parts = name.split("/")
    if ".." in parts:
        raise Refused(step, f"{name!r} has a '..' component")
    if any(p.startswith(".wh.") for p in parts):
        raise Refused(step, f"{name!r} is a whiteout (.wh.)")
    if any(p in ("", ".") for p in parts):
        raise Refused(step, f"{name!r} has an empty or '.' component")
    return name


def check_members(tar_data):
    """Step 7: directories and regular files under usr/local/lib/, nothing else."""
    try:
        tar = tarfile.open(fileobj=io.BytesIO(tar_data), mode="r:")
        members = tar.getmembers()
    except tarfile.TarError as e:
        raise Refused("members", f"the layer is not a readable tar: {e}") from e
    seen = set()
    for m in members:
        raw = m.name[2:] if m.name.startswith("./") else m.name
        if m.isdir() and raw.rstrip("/") in ("", "."):
            # The archive's own root, which some writers emit as ./; tar -p
            # applies its mode to the staging directory itself.
            if m.mode != 0o755:
                raise Refused("members", f"the root entry has mode {m.mode:o}, not 755")
            continue
        name = safe_path(raw.rstrip("/") if m.isdir() else raw, "members")
        if m.issym() or m.islnk():
            raise Refused("members", f"{name!r} is a link")
        if not (m.isdir() or m.isreg()):
            raise Refused(
                "members", f"{name!r} has type {m.type!r}, not a directory or a file"
            )
        inside = name.startswith(PREFIX) or (m.isdir() and name in PREFIX_PARENTS)
        if not inside:
            raise Refused("members", f"{name!r} is outside {PREFIX}")
        if m.mode not in ((0o755,) if m.isdir() else (0o644, 0o755)):
            want = "755" if m.isdir() else "644 or 755"
            raise Refused("members", f"{name!r} has mode {m.mode:o}, not {want}")
        if name in seen:
            raise Refused("members", f"{name!r} is in the layer twice")
        seen.add(name)


def manifest_paths(text):
    """MANIFEST's paths, each under usr/local/lib/ and listed once."""
    paths = []
    for i, line in enumerate(text.splitlines(), 1):
        m = MANIFEST_LINE.match(line)
        if not m:
            raise Refused("staging", f"MANIFEST line {i} is not sha256sum's format")
        path = safe_path(m.group(2), "staging")
        if not path.startswith(PREFIX):
            raise Refused("staging", f"MANIFEST lists {path!r}, outside {PREFIX}")
        if path == MANIFEST or path in paths:
            raise Refused("staging", f"MANIFEST lists {path!r} twice or lists itself")
        paths.append(path)
    if not paths:
        raise Refused("staging", "MANIFEST lists nothing")
    return paths


def walk_error(e):
    raise Refused("staging", f"can't read {e.filename}: {e.strerror}")


def check_staging(staging, version, manifest_sha):
    """Step 8, after extracting: MANIFEST is the pinned one, checks, and is
    the whole file set."""
    for need in (MANIFEST, VERSION):
        if not os.path.isfile(os.path.join(staging, need)):
            raise Refused("staging", f"{need} is not in the layer")
    with open(os.path.join(staging, MANIFEST), "rb") as f:
        manifest = f.read()
    listed = manifest_paths(manifest.decode("utf-8", errors="replace"))
    got = hashlib.sha256(manifest).hexdigest()
    if got != manifest_sha:
        raise Refused(
            "staging", f"MANIFEST's sha256 is {got}, not the pin's {manifest_sha}"
        )
    rc = subprocess.run(
        ["sha256sum", "--strict", "-c", MANIFEST], cwd=staging, stdout=sys.stderr
    ).returncode
    if rc != 0:
        raise Refused("staging", f"sha256sum --strict -c MANIFEST failed (exit {rc})")
    found = set()
    for root, _dirs, files in os.walk(staging, onerror=walk_error):
        for name in files:
            found.add(os.path.relpath(os.path.join(root, name), staging))
    want = set(listed) | {MANIFEST}
    if found != want:
        extra = sorted(found - want)
        absent = sorted(want - found)
        raise Refused(
            "staging", f"files not in MANIFEST: {extra}; listed but absent: {absent}"
        )
    with open(os.path.join(staging, VERSION), encoding="utf-8", errors="replace") as f:
        got = f.read().strip()
    if got != str(version):
        raise Refused("staging", f"VERSION is {got!r}, and the pin says {version}")
    return sorted(found)


def pull(pin, staging, work, made):
    registry, repo = pin["DISK_GC_REGISTRY"], pin["DISK_GC_REPOSITORY"]
    tag, pinned = pin["DISK_GC_TAG"], pin["DISK_GC_MANIFEST_DIGEST"]
    base = f"{registry}/v2/{repo}"

    token_doc = load_json(
        fetch(
            f"{registry}/token?scope=repository:{repo}:pull", f"{work}/token", "token"
        ),
        "token",
        "the token response",
    )
    token = token_doc.get("token")
    if not isinstance(token, str) or not token:
        raise Refused("token", "the token response has no .token")
    auth = (f"Authorization: Bearer {token}",)

    accept = "Accept: " + ", ".join(MANIFEST_TYPES)
    manifest = check_manifest(
        fetch(
            f"{base}/manifests/{tag}", f"{work}/manifest", "manifest", auth + (accept,)
        ),
        pinned,
    )

    config_digest = manifest["config"]["digest"]
    config_data = fetch(
        f"{base}/blobs/{config_digest}",
        f"{work}/config",
        "config",
        auth,
        declared_size(manifest["config"], "the config"),
    )
    got = sha256_of(config_data)
    if got != config_digest:
        raise Refused("config", f"its digest is {got}, not {config_digest}")
    config = load_json(config_data, "config", "the config")

    n, layer_digest, diff_id = find_layer(manifest, config)

    blob = fetch(
        f"{base}/blobs/{layer_digest}",
        f"{work}/layer.tar.gz",
        "blob",
        auth,
        declared_size(manifest["layers"][n], f"layer {n}"),
    )
    got = sha256_of(blob)
    if got != layer_digest:
        raise Refused("blob", f"its digest is {got}, not {layer_digest}")
    tar_data = gunzip(blob)
    got = sha256_of(tar_data)
    if got != diff_id:
        raise Refused(
            "blob", f"its gunzipped digest is {got}, not diff_ids[{n}] {diff_id}"
        )

    check_members(tar_data)

    tar_path = f"{work}/layer.tar"
    with open(tar_path, "wb") as f:
        f.write(tar_data)
    make_staging(staging, made)
    os.chmod(staging, 0o755)  # mkdir's mode is masked by the umask
    rc = subprocess.run(
        ["tar", "-xpf", tar_path, "-C", staging, "--no-same-owner"], stdout=sys.stderr
    ).returncode
    if rc != 0:
        raise Refused("staging", f"tar couldn't extract the layer (exit {rc})")
    files = check_staging(
        staging, int(pin["DISK_GC_VERSION"]), pin["DISK_GC_MANIFEST_SHA256"]
    )
    return {
        "ok": True,
        "staging": staging,
        "pin": {
            "tag": tag,
            "manifest_digest": pinned,
            "version": int(pin["DISK_GC_VERSION"]),
        },
        "config_digest": config_digest,
        "layer": {
            "index": n,
            "digest": layer_digest,
            "diff_id": diff_id,
            "bytes": len(blob),
        },
        "version": int(pin["DISK_GC_VERSION"]),
        "files": files,
    }


SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)


def make_staging(staging, made):
    """mkdir and its record in `made` as one step: the signals are blocked
    between them, so one that lands there is delivered (and refuses) only
    once `made` names the directory it must remove."""
    signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
    try:
        try:
            os.mkdir(staging, 0o755)
        except OSError as e:
            raise Refused("staging", f"can't make {staging}: {e.strerror}") from e
        made.append(staging)
    finally:
        signal.pthread_sigmask(signal.SIG_UNBLOCK, SIGNALS)


def on_signal(signum, _frame):
    raise Refused("internal", f"interrupted by signal {signum}")


def remove_tree(path):
    """Remove a staging tree this run made, read-only directories and all;
    whether it is gone."""
    try:
        os.chmod(path, 0o700)
        for top, dirs, _files in os.walk(path):
            for d in dirs:
                p = os.path.join(top, d)
                if not os.path.islink(p):
                    os.chmod(p, 0o700)
    except OSError:
        pass
    shutil.rmtree(path, ignore_errors=True)
    return not os.path.lexists(path)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="_pull.py")
    ap.add_argument("--pin", required=True)
    ap.add_argument("--into", required=True)
    args = ap.parse_args(argv)
    staging = os.path.abspath(args.into)
    made = []
    previous = {s: signal.signal(s, on_signal) for s in SIGNALS}
    try:
        work = tempfile.mkdtemp(prefix="disk-gc-pull.")
        try:
            try:
                result = pull(read_pin(args.pin), staging, work, made)
            except Refused as e:
                refusal = e
            except Exception as e:  # any failure is a refusal, never a traceback
                refusal = Refused("internal", f"{type(e).__name__}: {e}")
            else:
                refusal = None
            # From here on, cleanup and the report run to the end: a second
            # signal is ignored rather than raised out of them.
            for s in SIGNALS:
                signal.signal(s, signal.SIG_IGN)
        finally:
            remove_tree(work)
        if refusal is None:
            print(json.dumps(result, indent=2))
            return 0
        # Only a directory this run made: nothing half-checked is left to install.
        left = [path for path in made if not remove_tree(path)]
        out = {"ok": False, "refused": {"step": refusal.step, "why": refusal.why}}
        if left:
            out["staging_left"] = left[0]
            print(
                f"pull-disk-gc: couldn't remove {left[0]}; delete it", file=sys.stderr
            )
        print(json.dumps(out, indent=2))
        print(
            f"pull-disk-gc: refused at {refusal.step}: {refusal.why}", file=sys.stderr
        )
        return 3
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


if __name__ == "__main__":
    sys.exit(main())
