"""#425 — the canonical GC's release pin has one home: the skill's `_pin.sh`.

Decided at the #485 gate: the pin lives in the skill only, with no `.skills/`
knob, so a new GC release is a skill commit and every host gets it through its
repo's skills-vendor bump. One home means a second copy can't drift from it:
no other file under `skills/` may carry the tag or the manifest digest, and the
scripts read it rather than restate it.
"""

import re

from tests.structural import maintaining_host_disk_rig as rig

PIN = rig.SCRIPTS / "_pin.sh"

# VERSION 3 (2026-10-27), from
# https://github.com/gregoryfoster/skills/issues/510
TAG = "a4857ac9332f0aa368ae427d39d2e8df0cee0bb5"
DIGEST = "sha256:7cbad644d2ece3e163bd3087727d710b05beceff1d935bf64813f2fd3fa23168"
# The layer's own MANIFEST, from the same issue. pull-disk-gc.sh at this pin
# staged layer sha256:9a5bbd46…9d030 (23,039 bytes) and its step 8 matched
# this, 2026-10-28.
MANIFEST_SHA256 = "9347ffff2ff66e3925efa25d2cc5d4e5b70d83d512619de6a6ac96cb5abfe258"


def pin_values() -> dict:
    return dict(
        re.findall(r"^(DISK_GC_[A-Z0-9_]+)=(\S+)$", PIN.read_text(), flags=re.M)
    )


def test_pin_is_version_3():
    values = pin_values()
    assert values["DISK_GC_TAG"] == TAG
    assert values["DISK_GC_MANIFEST_DIGEST"] == DIGEST
    assert values["DISK_GC_VERSION"] == "3"
    assert values["DISK_GC_MANIFEST_SHA256"] == MANIFEST_SHA256
    assert values["DISK_GC_REGISTRY"] == "https://ghcr.io"
    assert values["DISK_GC_REPOSITORY"] == "cannobserv/co-image-base"


def test_pin_is_a_released_tag_and_its_digest():
    values = pin_values()
    assert re.fullmatch(r"[0-9a-f]{40}", values["DISK_GC_TAG"])
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", values["DISK_GC_MANIFEST_DIGEST"])
    assert re.fullmatch(r"[0-9a-f]{64}", values["DISK_GC_MANIFEST_SHA256"])


def test_each_key_is_set_once():
    keys = re.findall(r"^(DISK_GC_[A-Z0-9_]+)=", PIN.read_text(), flags=re.M)
    assert sorted(keys) == sorted(set(keys))


def test_no_other_file_in_skills_carries_the_pin():
    """Short prefixes too: a doc that quotes `4ac2cc2…` is a second copy that
    a release bump would leave behind."""
    heads = (TAG[:7], DIGEST.split(":")[1][:7], MANIFEST_SHA256[:7])
    hits = []
    for path in sorted(rig.REPO_ROOT.glob("skills/**/*")):
        if not path.is_file() or path == PIN or "__pycache__" in path.parts:
            continue
        text = path.read_text(errors="replace")
        if any(h in text for h in heads):
            hits.append(str(path.relative_to(rig.REPO_ROOT)))
    assert not hits, f"the pin must live only in {PIN.name}; also found in {hits}"
