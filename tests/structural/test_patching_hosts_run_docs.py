"""patching-hosts' run docs: a host with no datastore, and the after reading.

- #492: SKILL.md step 5 and run.md section 2 sent a host whose knob declares
  no `datastore` to `recovery-point.sh`, which refuses it. They now say it
  skips the script, that its bulk takes no `--run`, and that the bulk
  records the before-versions in the run directory it makes and prints. The
  refusal run.md quotes is the script's own.
- #508, part 2: no step took the language reading after a run. The record
  names `probe.sh --refresh-into` as its last step, in every run, and a
  class or tree it couldn't read is recorded as no read, never 0.
"""

import re

from tests.structural.patching_hosts_rig import SKILL

SKILL_MD = (SKILL / "SKILL.md").read_text()
RUN = (SKILL / "references" / "run.md").read_text()
AFTER = (SKILL / "references" / "reboot-and-record.md").read_text()
RECOVERY = (SKILL / "scripts" / "recovery-point.sh").read_text()


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start : end if end >= 0 else len(text)]


def _step(n: int) -> str:
    [line] = [li for li in SKILL_MD.splitlines() if li.startswith(f"{n}. ")]
    return line


def test_skill_step_5_sends_only_a_datastore_host_to_the_recovery_point():
    step = _step(5)
    assert "where the knob declares a `datastore`" in step
    assert "A host with none skips it" in step
    assert "without `--run`" in step
    assert "records the before-versions in a run directory it makes and prints" in step


def test_run_md_section_2_says_a_host_with_no_datastore_skips_the_script():
    s2 = _section(RUN, "## 2. The recovery point")
    assert "skips `recovery-point.sh`" in s2
    assert "takes no `--run`" in s2
    assert "`/var/backups/patching-hosts-<UTC>`" in s2
    assert "prints it as its JSON's `run`" in s2


def test_the_refusal_run_md_quotes_is_the_scripts_own():
    m = re.search(r'refuse "(the knob declares no datastore[^"]*)"', RECOVERY)
    assert m, "recovery-point.sh no longer refuses a host with no datastore"
    s2 = _section(RUN, "## 2. The recovery point")
    assert f"`recovery-point: refused: {m.group(1)}`" in s2
    assert "exits 3" in s2


def test_approval_2_names_the_recovery_point_only_where_there_is_one():
    approvals = _section(RUN, "## Approvals")
    assert "after the recovery point, on a host that declares a `datastore`" in (
        approvals
    )


def test_the_record_takes_the_after_reading_with_refresh_into_last():
    s7 = _section(AFTER, "## 7. The record")
    assert "`probe.sh --refresh-into <dir>`" in s7
    assert "in every run, whether it rebooted or not" in s7
    # The only probe that reads the language class.
    assert "`--post-boot`" in s7 and "language" in s7


def test_an_unread_class_or_tree_is_recorded_as_no_read_never_0():
    s7 = _section(AFTER, "## 7. The record")
    assert "*no read*, never as 0" in s7
    assert "`not_read`" in s7 and "`lockfile: null`" in s7


# #423, #490, #501: the probe reads, with named exceptions, and says where
# the contract is stated.
READINGS = (SKILL / "references" / "readings.md").read_text()
KNOB_MD = (SKILL / "references" / "knob.md").read_text()


def test_the_probes_promise_names_its_exceptions():
    step = _step(1)
    assert "Ubuntu Pro's own log and lock" in step
    assert "--no-sudo" in step and "probe.privilege" in step
    for path in ("/var/log/ubuntu-advantage.log", "/var/lib/ubuntu-advantage/lock"):
        assert path in READINGS, path
    assert "It changes nothing" not in step


def test_a_health_line_is_safe_at_any_time_and_recovery_isnt_run_by_every_probe():
    [health] = [li for li in KNOB_MD.splitlines() if li.startswith("| `health ")]
    assert "safe and cheap at any time" in health
    [recovery] = [li for li in KNOB_MD.splitlines() if li.startswith("| `recovery ")]
    assert "--post-boot" in recovery


def test_readings_name_the_dry_runs_own_download_readings():
    # CR 1290: #499's two readings, where the dry run's cost is read.
    [row] = [
        li for li in READINGS.splitlines() if li.startswith("| The dry run's cost")
    ]
    assert "download_bound_kib" in row and "free_kib_dry_run_dir" in row
