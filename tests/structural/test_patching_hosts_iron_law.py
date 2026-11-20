"""patching-hosts' Iron Law, pinned word for word (#673).

The Iron Law is a required fragment (`<!-- skill:required id=iron-law -->`):
a project override that copies it must keep it, and must change with it.
#673 widened its first line from approval "given in the host's own
session" to three forms: that session, an approved plan that covers the
host, or the host's own standing approval. The operator decided (2026-11-19)
that its text is pinned, so any later change to it is a deliberate edit
this test names, and the overrides that copy it can be told.
"""

import re

from tests.structural.patching_hosts_rig import SKILL

IRON_LAW = (
    "NO APPLY, RESTART OR REBOOT WITHOUT THE OWNER'S APPROVAL: IN THE HOST'S OWN "
    "SESSION, BY AN APPROVED PLAN THAT COVERS THE HOST, OR BY THE HOST'S OWN "
    "STANDING APPROVAL\n"
    "NO APPLY ON A HOST WITH A DATA STORE UNTIL ITS RECOVERY POINT HAS LEFT THE NODE\n"
    "NO CLAIM ABOUT THE HOST THAT WASN'T READ ON THE HOST\n"
)


def _fragment() -> str:
    text = (SKILL / "SKILL.md").read_text()
    m = re.search(
        r"^<!-- skill:required id=iron-law -->\n```\n(.*?)^```$", text, re.M | re.S
    )
    assert m, "SKILL.md lost its required iron-law fragment"
    return m.group(1)


def test_the_iron_law_is_pinned_word_for_word():
    assert _fragment() == IRON_LAW


def test_each_line_of_the_iron_law_is_one_line():
    # A wrapped line would read as a fourth law to a reader, or an override.
    assert len(_fragment().splitlines()) == 3
