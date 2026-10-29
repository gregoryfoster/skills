"""#522 — the "GC timer only" path names how a failed GC run gets reported.

`turning-on.md` § 5 lets a host whose own probe reports its free space enable
only the GC timer, with `gc_stale_hours = 0` and no monitor. The canonical
`cannobserv-disk-gc.service` has no `OnFailure=`, and `gc-failed` comes only
from the sensor, so on that path a GC that exits 1 or 2, or times out, run
after run, reports nothing. § 5 said so and offered no close, and the host
usually on that path is one whose own tooling *had* a failure net
(CannObserv/observo#705).

§ 5 now names the three closes (a drop-in `OnFailure=`, the host's probe
reading `state.json`, or both timers after all) and makes retiring tooling
that had a failure net conditional on one of them. `retiring.md`'s checklist
asks the question, and the unit-side hook is left to the GC's owner.
"""

import re

from tests.structural import maintaining_host_disk_rig as rig

TURNING_ON = rig.SKILL / "references" / "turning-on.md"
RETIRING = rig.SKILL / "references" / "retiring.md"


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = text.find("\n## ", start + len(heading))
    return text[start : nxt if nxt != -1 else len(text)]


def _gc_timer_only() -> str:
    timers = _section(TURNING_ON.read_text(), "## 5. The timers")
    start = timers.index("**A host whose own probe already reports its free space**")
    return timers[start:]


class TestTheGcTimerOnlyPathNamesItsCloses:
    def test_a_drop_in_on_failure(self):
        text = _gc_timer_only()
        assert "/etc/systemd/system/cannobserv-disk-gc.service.d/" in text, text
        assert "OnFailure=" in text, text
        assert "MANIFEST" in text, "say why a drop-in leaves the install intact"

    def test_the_probe_reads_state_json(self):
        text = _gc_timer_only()
        assert "/var/lib/cannobserv-disk-gc/state.json" in text, text
        assert "`exit`" in text and "`finished_at`" in text, text

    def test_both_timers_after_all(self):
        assert "both timers" in _gc_timer_only()

    def test_retiring_a_failure_net_waits_on_one_of_them(self):
        text = _gc_timer_only()
        assert re.search(r"retir\w*[^.]*failure net", text, re.S), text

    def test_the_unit_side_hook_is_left_to_its_owner(self):
        text = _gc_timer_only()
        assert "provisioner#61" in text, text


class TestTheRetireChecklistAsks:
    def test_question_four_names_the_failure_net(self):
        text = RETIRING.read_text()
        q4 = next(ln for ln in text.splitlines() if ln.startswith("4. "))
        assert "OnFailure=" in q4, q4
        assert "dead-man" in q4, q4
        assert "turning-on.md#5-the-timers" in q4, q4
