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

# VERSION 4: of the VS Code server builds newer than the newest live one,
# only the newest is kept (2026-11-01, #551).
DISK_GC_REGISTRY=https://ghcr.io
DISK_GC_REPOSITORY=cannobserv/co-image-base
DISK_GC_TAG=d675fcbcd20db77a7af5576bd133fc0c577d3808
DISK_GC_MANIFEST_DIGEST=sha256:25d9289e246b42a9e00589482cb39afd0ceb013be1a9a950083186f0c241fded
DISK_GC_VERSION=4
# From the release (#551); the puller's step 8 matched it, 2026-11-02.
DISK_GC_MANIFEST_SHA256=89059897fdde255419676ba486742bd0ee63ce7063a61c0c5ee3a316bd3fc00a
