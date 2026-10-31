"""host-memory.md's -1000 class is an `exe-init` build bug (#339).

host-memory.md said a session's class "belongs to the session's path in, not
to the host", and that what sets the path "was not determined". exe.dev then
confirmed (2026-09-29) that some `exe-init` builds start sessions at
`oom_score_adj` -1000, as a bug fixed in new VMs. co-replicator's `exe-init`
was replaced, and its sessions now read 0 directly under `exe-init`. So the
doc listed replicator in the wrong row, cited a pin test that now asserts the
opposite, and recorded its earlyoom decline at -1000 when it was re-decided at
0 (CannObserv/replicator#112, PR #126).

The epic's disposition: point at patching-hosts' exe.dev profile for the
`exe-init` facts rather than restate them, so the builds, the version probe
and the fix have one home. What host-memory.md says about the cap and swap
(#340) stays.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "init-socraticode"
HOST_MEMORY = SKILL / "references" / "host-memory.md"
TROUBLESHOOTING = SKILL / "references" / "troubleshooting.md"
PROFILE = (
    ROOT
    / "skills"
    / "patching-hosts"
    / "references"
    / "environments"
    / "exe-dev-exeuntu.md"
)
PROFILE_LINK = "../../patching-hosts/references/environments/exe-dev-exeuntu.md"


def _text() -> str:
    return " ".join(HOST_MEMORY.read_text().split())


def _class_row(marker: str) -> str:
    text = HOST_MEMORY.read_text()
    section = text[text.index("### 1.") : text.index("### 2.")]
    return next(ln for ln in section.splitlines() if ln.startswith(marker))


def _section(start: str, end: str | None = None) -> str:
    text = _text()
    i = text.index(start)
    return text[i : text.index(end, i)] if end else text[i:]


class TestTheClassIsTheBuild:
    def test_the_path_framing_is_gone(self) -> None:
        text = _text()
        for stale in (
            "The class belongs to the session's path in",
            "What sets the path, and so the class, was not determined",
        ):
            assert stale not in text, (
                f"host-memory.md still says {stale!r}. exe.dev confirmed the "
                "-1000 class is an exe-init build bug (#339)."
            )
        assert "`exe-init` build" in text, "name the build as the class's cause"

    def test_it_points_at_the_profile_for_the_exe_init_facts(self) -> None:
        assert PROFILE.is_file(), PROFILE
        assert "## Sessions and OOM" in PROFILE.read_text()
        assert f"{PROFILE_LINK}#sessions-and-oom" in HOST_MEMORY.read_text(), (
            "host-memory.md should point at patching-hosts' exe.dev profile "
            "for which builds, how to read one, and the fix — one home, not "
            "a second copy (#339)"
        )

    def test_it_does_not_restate_the_builds(self) -> None:
        text = HOST_MEMORY.read_text()
        builds = [b for b in ("8579326", "14fd603", "6403375d") if b in text]
        assert not builds, (
            f"host-memory.md restates exe-init builds {builds}; they live in "
            "patching-hosts' exe.dev profile (#339)"
        )


class TestReplicatorIsAtZero:
    def test_replicator_left_the_minus_1000_row(self) -> None:
        row = _class_row("| **-1000**")
        measured_on = row.split("|")[2]
        assert "replicator" not in measured_on, (
            f"replicator reads 0 since its exe-init was replaced (#339): {row}"
        )

    def test_replicator_is_in_the_zero_row(self) -> None:
        row = _class_row("| **0**")
        assert "replicator" in row.split("|")[2], row

    def test_the_pin_cited_is_the_one_that_asserts_zero(self) -> None:
        pin = _section("**Pin the reading", "### 2.")
        assert "TestTheSessionPremise" in pin, (
            "replicator's pin is now tests/test_deploy.py::TestTheSessionPremise, "
            f"which asserts 0 (#339): {pin}"
        )
        assert not re.search(r"`bcf3e5a`, `TestTheEarlyoomDecline`\)\. A host", pin), (
            "the -1000 pin is cited as if it still held"
        )

    def test_the_earlyoom_decline_is_recorded_at_zero(self) -> None:
        four = _section("### 4.")
        zero = next(ln for ln in four.split(" | **") if ln.startswith("0**"))
        assert "replicator" in zero and "declin" in zero, (
            "replicator declined earlyoom again at 0 (CannObserv/replicator#112, "
            f"PR #126); the 0 row should say so (#339): {zero}"
        )
        assert "replicator did" not in _section("### 4.", "On replicator's dry run"), (
            "the -1000 row still records replicator's decline there"
        )


class TestTheCapAndSwapStay:
    """#340's content is not this issue's to change."""

    def test_the_swap_bound_stays(self) -> None:
        text = _text()
        assert "MemorySwapMax=0 because MemoryMax= bounds RAM only" in text
        assert "The health hook caps itself" in text

    def test_row_u_drops_the_path_framing_too(self) -> None:
        row = next(
            ln
            for ln in TROUBLESHOOTING.read_text().splitlines()
            if ln.startswith("| **U**")
        )
        assert "by the path the session came in on" not in row, (
            "row U repeats host-memory.md's path framing (#339)"
        )
