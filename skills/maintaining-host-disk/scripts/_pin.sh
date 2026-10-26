#!/usr/bin/env bash
# _pin.sh — the one home of the canonical disk GC release this skill installs.
# Read by _pull.py as data, and sourced by install-disk-gc.sh; running it
# does nothing.
# A new GC release is a commit here, never a host's own setting (#425).
# The DISK_GC_* variables are its output.
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

# VERSION 2: the headroom sensor's clear line (CannObserv/provisioner#85,
# merged in provisioner#87, 2026-10-24).
DISK_GC_REGISTRY=https://ghcr.io
DISK_GC_REPOSITORY=cannobserv/co-image-base
DISK_GC_TAG=4ac2cc21bcf5b4ab863776a37d2f718713662580
DISK_GC_MANIFEST_DIGEST=sha256:0e230e4dfb255a0e27ae43367e823bd65b4c5156f51cd071a4c1c1c8f83e624f
DISK_GC_VERSION=2
# From the digest-verified layer, read by the #485 orchestrator (CR 520).
DISK_GC_MANIFEST_SHA256=066a9f3ad4e59bec523a0476ee81d4e87534cca82e50356a116043d8716d208c
