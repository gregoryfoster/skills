"""patching-hosts' run docs: a host with no datastore, and the after reading.

- #492: SKILL.md step 5 and run.md section 2 sent a host whose knob declares
  no `datastore` to `recovery-point.sh`, which refuses it. They now say it
  skips the script, that its bulk takes no `--run`, and that the bulk
  records the before-versions in the run directory it makes and prints. The
  refusal run.md quotes is the script's own.
- #508, part 2: no step took the language reading after a run. The record
  names `probe.sh --refresh-into` as its last step, in every run, and a
  class or tree it couldn't read is recorded as no read, never 0.
- #529: `scheduled` runs at the host's cadence, `cadence weekly|monthly`,
  weekly by default, and the docs say so rather than "monthly"; run.md
  states what a run with nothing pending does, a reboot still due included.
- #464, ask 2: policy.md's procedure for a pre-announced security release,
  linked from run.md's one-origin lane. Each step is checked against what
  the scripts do: the early refresh takes no `--lane`, the recovery point
  holds for 24 hours, the poll reads the lists the probe fetched, and the
  count waits for the fix.
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


def test_the_recovery_rule_reads_the_same_everywhere():
    # CR 1294: only after a held step that restarted a declared data store.
    import subprocess

    rule = "restarted a declared data store"
    [row] = [li for li in KNOB_MD.splitlines() if li.startswith("| `recovery ")]
    help_text = subprocess.run(
        ["bash", str(SKILL / "scripts" / "apply.sh"), "--help"],
        capture_output=True,
        text=True,
    ).stdout
    for name, text in (("knob.md", row), ("run.md", RUN), ("--help", help_text)):
        assert rule in " ".join(text.split()), name


def test_the_list_age_row_names_the_unpack_margin():
    # CR 1300: a ctime within an hour of os-release's is an unpack's.
    [row] = [li for li in READINGS.splitlines() if li.startswith("| List age ")]
    assert "an hour" in row


# --- #529: the host's cadence, and the empty week ----------------------------------

POLICY = (SKILL / "references" / "policy.md").read_text()


def _description() -> str:
    front = SKILL_MD.split("---", 2)[1]
    [line] = [li for li in front.splitlines() if li.startswith("description: ")]
    return line


def _triggers() -> list[str]:
    front = SKILL_MD.split("---", 2)[1]
    [line] = [li for li in front.splitlines() if li.strip().startswith("triggers: ")]
    return [t.strip() for t in line.split(":", 1)[1].split(",")]


def test_the_description_says_the_hosts_cadence_and_keeps_every_trigger():
    d = _description()
    assert "monthly" not in d
    assert "the host's cadence" in d
    for t in _triggers():
        assert f'"{t}"' in d, t


def test_policy_and_knob_speak_of_the_hosts_cadence_not_a_month():
    for name, text in (("policy.md", POLICY), ("knob.md", KNOB_MD)):
        flat = " ".join(text.split())
        assert "the host's cadence" in flat, name
        for said in ("once a month", "monthly run", "monthly window", "| monthly |"):
            assert said not in flat, f"{name}: {said}"
    [row] = [li for li in KNOB_MD.splitlines() if li.startswith("| `cadence ")]
    assert "weekly" in row and "Absent" in row


def test_run_md_says_what_a_run_with_nothing_pending_does():
    s = " ".join(_section(RUN, "## A run with nothing pending").split())
    assert "ends at the readings and the record" in s
    for skipped in ("no recovery point", "no callers' notice", "no window"):
        assert skipped in s, skipped
    # #496: an image push between runs left a reboot due with nothing pending.
    assert "#496" in s and "`impact.reboot`" in s
    assert "approval 3(b)" in s


def test_an_empty_week_needs_a_refresh_that_fetched():
    # CR 1444: since #542 a failed source leaves refreshed false and counts
    # against the host's own lists, where nothing pending may be months old.
    s = " ".join(_section(RUN, "## A run with nothing pending").split())
    assert "`pending.lists.refreshed`" in s
    assert "`lists:refresh`" in s and "#542" in s


# --- #542: what a failed source reads as ---------------------------------------


def _refresh_row() -> str:
    [row] = [li for li in READINGS.splitlines() if li.startswith("| A refresh ")]
    return row


def test_the_refresh_row_names_apts_floor_for_error_on_any():
    # CR 1438: an older apt refuses the option, and every refresh fails.
    row = _refresh_row()
    assert "apt 2.1.16" in row
    assert "older apt" in row


def test_the_refresh_row_says_what_to_do_with_a_source_down_for_good():
    # CR 1439: a dead source now stops every lane, the one-origin lane's
    # window included, and the owner's fix is to the host's sources.
    row = _refresh_row()
    assert "one-origin lane" in row
    assert "removed" in row and "owner" in row


# --- #464, ask 2: a pre-announced security release ---------------------------------

PRE = "### A pre-announced security release"
APPLY_SH = (SKILL / "scripts" / "apply.sh").read_text()
PROBE_SH = (SKILL / "scripts" / "probe.sh").read_text()


def _pre() -> str:
    assert PRE in POLICY, "policy.md has no pre-announced release procedure"
    start = POLICY.index(PRE)
    end = POLICY.find("\n## ", start)
    return POLICY[start:end]


def test_run_md_links_the_procedure_from_the_one_origin_lane():
    [para] = [
        p
        for p in RUN.split("\n\n")
        if p.startswith("**An expedited run of one origin**")
    ]
    assert "policy.md#a-pre-announced-security-release" in para


def test_the_procedure_rides_a_dated_window_and_the_origin_lane():
    s = _pre()
    assert "dated `window` line" in s and "#421" in s
    assert "`apply.sh --step bulk --lane origin:<origin>" in s
    assert "owner's approval" in s
    # The decision on #464: the dated window and the origin lane are the
    # expedite path, and no knob line names one.
    assert "expedite" not in KNOB_MD


def test_before_t_records_versions_refreshes_and_bounds_the_recovery_point():
    before = _pre().split("**After T**")[0]
    assert "before-versions" in before
    # The probe refuses --lane without --dry-run-into, so the early refresh
    # names no lane.
    assert "it goes with --dry-run-into" in PROBE_SH
    assert "`probe.sh --refresh-into DIR`" in before
    assert "--lane" not in before.split("**Before T:**")[1]
    assert "`lists:refresh`" in before
    # The bulk refuses a recovery point that began more than a day before it.
    assert "\nRP_MAX_AGE=86400\n" in APPLY_SH
    assert "recovery point" in before and "24 hours" in before


def test_after_t_polls_the_lists_the_probe_fetched_and_states_the_lag():
    after = _pre().split("**After T**")[1].split("**Then**")[0]
    # Plain apt-cache policy reads the host's own lists, which the probe
    # never refreshes.
    assert "`apt-cache -o Dir::State::Lists=DIR/lists/ policy <pkg>`" in after
    assert "never assume" in after


def test_then_counts_after_the_fix_verifies_the_runtime_and_records_the_cves():
    then = _pre().split("**Then**")[1]
    assert (
        "`probe.sh --lane origin:<origin> --refresh-into DIR --dry-run-into DIR`"
        in then
    )
    # A one-origin dry run that counted nothing is refused.
    assert "counted nothing from the" in APPLY_SH
    assert "counted nothing" in then
    assert "`impact.reboot.needrestart_services`" in then
    assert "reload" in then and "config test" in then
    assert "a real request" in then
    assert "CVE IDs" in then
