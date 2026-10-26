#!/usr/bin/env bash
# pull-disk-gc.sh — stage the canonical disk GC's files from the pinned
# co-image-base release, checked by the pull contract's steps 1-8 (#425).
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash pull-disk-gc.sh --into DIR

Pulls the one disk-gc layer of the co-image-base release pinned in _pin.sh,
anonymously and without docker, and extracts it into DIR, a directory that
must not exist yet. It installs nothing: install-disk-gc.sh does that from
DIR. Every check refuses, and a refusal leaves no DIR behind:

  1. pin       the pin is a released tag (40 hex, never :latest) and the
               sha256 of its manifest
  2. token     an anonymous pull token from the registry
  3. manifest  the manifest's sha256 is the pinned digest; an index, or any
               other media type, is refused
  4. config    the config blob's sha256 is the digest the manifest names
  5. layer     exactly one non-empty .history entry is
               "COPY disk-gc/ / # buildkit"; the non-empty entries, the
               config's .rootfs.diff_ids and the manifest's .layers agree in
               number; the entry's index picks the layer; it is gzipped
  6. blob      the layer's sha256 is its digest, and its gunzipped sha256 is
               its diff_id
  7. members   before anything is extracted: every member is a directory or
               a regular file under usr/local/lib/ (or one of that path's own
               parent directories), with no '..', no .wh. whiteout, no link,
               no control character, no name twice, and exact modes: a file
               0644 or 0755, a directory (the ./ root entry too) 0755
  8. staging   after extracting: MANIFEST and VERSION exist, MANIFEST lists
               only paths under usr/local/lib/, its sha256 is the pin's,
               `sha256sum --strict -c MANIFEST` passes from DIR, the files
               there are exactly MANIFEST's plus MANIFEST (a directory it
               can't read refuses), and VERSION is the pin's

Output (stdout, JSON): {"ok": true, "staging", "pin", "config_digest",
"layer": {index, digest, diff_id, bytes}, "version", "files"}, or
{"ok": false, "refused": {"step", "why"}}. Any other failure, and a signal
(TERM, HUP, INT), is a refusal at step "internal"; a staging directory it
made but couldn't remove is named in "staging_left". curl's and sha256sum's own
output, and every diagnostic, go to stderr.

Needs curl, tar, sha256sum and python3 (stdlib only). No root: run it as
any user, then install as root.

Options:
  --into DIR   where to stage the files; must not exist, and its parent must
  -h, --help   show this help

Exit codes:
  0  staged and checked
  2  usage: --into missing or already there, or a needed tool missing
  3  refused: a check failed, and the JSON says which
USAGE
}

INTO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --into)
      [ $# -ge 2 ] || { echo "pull-disk-gc: --into needs a directory" >&2; exit 2; }
      INTO=$2
      shift 2
      ;;
    -h | --help) usage; exit 0 ;;
    *) echo "pull-disk-gc: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$INTO" ] || { echo "pull-disk-gc: --into DIR is required" >&2; exit 2; }
if [ -e "$INTO" ] || [ -L "$INTO" ]; then
  echo "pull-disk-gc: $INTO already exists; stage into a new directory" >&2
  exit 2
fi
for tool in curl tar sha256sum python3; do
  command -v "$tool" >/dev/null || { echo "pull-disk-gc: needs $tool on PATH" >&2; exit 2; }
done

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec python3 -I -B "$HERE/_pull.py" --pin "$HERE/_pin.sh" --into "$INTO"
