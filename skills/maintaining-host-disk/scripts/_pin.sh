#!/usr/bin/env bash
# _pin.sh — the one home of the canonical disk GC release this skill installs.
# Read by _pull.py as data, and sourced by install-disk-gc.sh; running it
# does nothing.
# A new GC release is a commit here, never a host's own setting (#425), and
# it re-checks patching-hosts' _probe-lib.sh too, which mirrors the release's
# config reader and usage() and names the VERSIONs it matches.
# The DISK_GC_* variables are this file's output.
# shellcheck disable=SC2034
set -euo pipefail

pin_usage() {
  cat <<'USAGE'
Usage: . _pin.sh    (read as data by _pull.py, sourced by install-disk-gc.sh;
                    running it does nothing)

The release of ghcr.io/cannobserv/co-image-base whose disk-gc layer this
skill installs: a released tag (40 hex, never :latest) and the sha256 of its
manifest, which the puller checks before it trusts anything else. VERSION is
the integer the layer's own VERSION file must hold.

  DISK_GC_REGISTRY         the registry, scheme and host
  DISK_GC_REPOSITORY       the image's repository on it
  DISK_GC_TAG              the released tag
  DISK_GC_MANIFEST_DIGEST  sha256:<hex> of that tag's manifest
  DISK_GC_VERSION          the layer's VERSION at that tag
  DISK_GC_MANIFEST_SHA256  the sha256 of that layer's own MANIFEST, which
                           the puller and the installer both check, so a
                           staged tree is bound to the release

Each is one KEY=value line with nothing else on it: _pull.py reads this
file as data and refuses one it can't parse.
USAGE
}

case "${0##*/}" in
  _pin.sh) case "${1-}" in -h | --help) pin_usage; exit 0 ;; esac ;;
esac

# VERSION 3: VS Code server builds kept by version, newer than the newest
# live one, or the newest when none is live (2026-10-27, #510).
DISK_GC_REGISTRY=https://ghcr.io
DISK_GC_REPOSITORY=cannobserv/co-image-base
DISK_GC_TAG=a4857ac9332f0aa368ae427d39d2e8df0cee0bb5
DISK_GC_MANIFEST_DIGEST=sha256:7cbad644d2ece3e163bd3087727d710b05beceff1d935bf64813f2fd3fa23168
DISK_GC_VERSION=3
# From the release (#510); the puller's step 8 matched it, 2026-10-28.
DISK_GC_MANIFEST_SHA256=9347ffff2ff66e3925efa25d2cc5d4e5b70d83d512619de6a6ac96cb5abfe258
