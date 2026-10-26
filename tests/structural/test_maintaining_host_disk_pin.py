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

# VERSION 2 (CannObserv/provisioner#85, merged in provisioner#87), from
# https://github.com/gregoryfoster/skills/issues/425#issuecomment-6387455753
TAG = "4ac2cc21bcf5b4ab863776a37d2f718713662580"
DIGEST = "sha256:0e230e4dfb255a0e27ae43367e823bd65b4c5156f51cd071a4c1c1c8f83e624f"


def pin_values() -> dict:
    return dict(re.findall(r"^(DISK_GC_[A-Z_]+)=(\S+)$", PIN.read_text(), flags=re.M))


def test_pin_is_version_2():
    values = pin_values()
    assert values["DISK_GC_TAG"] == TAG
    assert values["DISK_GC_MANIFEST_DIGEST"] == DIGEST
    assert values["DISK_GC_VERSION"] == "2"
    assert values["DISK_GC_REGISTRY"] == "https://ghcr.io"
    assert values["DISK_GC_REPOSITORY"] == "cannobserv/co-image-base"


def test_pin_is_a_released_tag_and_its_digest():
    values = pin_values()
    assert re.fullmatch(r"[0-9a-f]{40}", values["DISK_GC_TAG"])
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", values["DISK_GC_MANIFEST_DIGEST"])


def test_each_key_is_set_once():
    keys = re.findall(r"^(DISK_GC_[A-Z_]+)=", PIN.read_text(), flags=re.M)
    assert sorted(keys) == sorted(set(keys))


def test_no_other_file_in_skills_carries_the_pin():
    """Short prefixes too: a doc that quotes `4ac2cc2…` is a second copy that
    a release bump would leave behind."""
    tag_head, digest_head = TAG[:7], DIGEST.split(":")[1][:7]
    hits = []
    for path in sorted(rig.REPO_ROOT.glob("skills/**/*")):
        if not path.is_file() or path == PIN or "__pycache__" in path.parts:
            continue
        text = path.read_text(errors="replace")
        if tag_head in text or digest_head in text:
            hits.append(str(path.relative_to(rig.REPO_ROOT)))
    assert not hits, f"the pin must live only in {PIN.name}; also found in {hits}"
