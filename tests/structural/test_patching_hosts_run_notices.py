"""patching-hosts: two notices power-map's run of 2026-11-18 lacked (#680).

- The bulk took a package published between its dry run (01:04Z) and the
  bulk (05:36Z): noble-security's libcpanel-json-xs-perl, counted nowhere.
  verdict.version_moved covers only held packages, so it showed only by a
  diff by hand. The bulk's upgrade now lists what it took that the dry run
  didn't count (uncounted, null where the dry run's selection wasn't read)
  and the dry run's age at the bulk's start, with a next line when any was
  taken. Not a refusal: the space gate re-reads after apt-get update.
- reboot-chain.sh listed what the boot would empty in tmp_staged, and the
  agent didn't read the list out before approval 3(b). Its next now says
  how many paths under /tmp the boot empties, or may empty where that's
  unknown, before the approval; nothing where the rule keeps /tmp.
"""

import pytest

from tests.structural.patching_hosts_rig import dispatcher
from tests.structural.test_patching_hosts_apply import TUE_1530
from tests.structural.test_patching_hosts_apply import Host as ApplyHost
from tests.structural.test_patching_hosts_apply import _ready as _ready_apply
from tests.structural.test_patching_hosts_reboot import Host as ChainHost
from tests.structural.test_patching_hosts_reboot import _ready as _ready_chain
from tests.structural.test_patching_hosts_reboot import _tmp_rule


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


# The fixture's dry run selects five; the postgres group holds two of them.
COUNTED = (
    f"began={TUE_1530 - 3600}\nexit=0\ncount=4\nwall_seconds=540\nsecurity_only=1\n"
    "lists_refreshed=1\nbulk_takes=libc6 libxml2 libssl3t64\n"
)


@pytest.fixture
def host(tmp_path):
    return _ready_apply(ApplyHost(tmp_path))


def test_the_bulk_lists_what_it_took_that_the_dry_run_didnt_count(host):
    (host.dry / "summary").write_text(COUNTED)
    host.uu(
        "Packages that will be upgraded: libc6 libcpanel-json-xs-perl\n"
        "All upgrades installed\n"
    )
    out = host.run()
    assert out["verdict"]["ok"] is True, out["verdict"]
    assert out["upgrade"]["uncounted"] == ["libcpanel-json-xs-perl"]
    assert out["upgrade"]["dry_run_age_seconds"] == 3600
    [n] = [n for n in out["next"] if "upgrade.uncounted" in n]
    assert "libcpanel-json-xs-perl" in n and "3600 s" in n


def test_a_bulk_that_took_only_what_was_counted_lists_nothing(host):
    (host.dry / "summary").write_text(COUNTED)
    out = host.run()
    assert out["upgrade"]["uncounted"] == []
    assert not [n for n in out["next"] if "upgrade.uncounted" in n]


def test_where_the_dry_runs_selection_wasnt_read_uncounted_is_null(host):
    # The fixture's summary has neither select nor bulk_takes lines.
    out = host.run()
    assert out["upgrade"]["uncounted"] is None
    assert out["upgrade"]["dry_run_age_seconds"] == 3600


def test_the_select_lines_count_too(host):
    (host.dry / "summary").write_text(
        COUNTED.replace("bulk_takes=libc6 libxml2 libssl3t64\n", "")
        + "select_read=1\nselect=libc6 2.39-0ubuntu8.6 security\n"
    )
    host.uu("Packages that will be upgraded: libc6 tzdata\nAll upgrades installed\n")
    out = host.run()
    assert out["upgrade"]["uncounted"] == ["tzdata"]


def test_a_held_steps_upgrade_has_no_uncounted(host):
    (host.dry / "summary").write_text(COUNTED)
    host.run()
    out = host.run(step="postgres")
    assert "uncounted" not in out["upgrade"]
    assert "dry_run_age_seconds" not in out["upgrade"]


# --- the chain's /tmp line --------------------------------------------------------


@pytest.fixture
def chain(tmp_path):
    return _ready_chain(ChainHost(tmp_path))


def _staged(chain, cleared: str, paths: list[str]) -> None:
    _tmp_rule(chain, cleared)
    chain.STUBBED = (*ChainHost.STUBBED, "find")
    chain.cases["find"] = [("*", "".join(p + "\n" for p in paths), 0, "", None)]


@pytest.mark.parametrize(
    "cleared, paths, line",
    [
        (
            "1",
            ["/tmp/a", "/tmp/b"],
            "The boot empties /tmp: 2 paths under it will be gone",
        ),
        (
            "",
            ["/tmp/a"],
            "Whether the boot empties /tmp is unknown: 1 path under it may be gone",
        ),
    ],
)
def test_before_an_approval_the_chain_says_how_much_of_tmp_the_boot_empties(
    chain, cleared, paths, line
):
    _staged(chain, cleared, paths)
    out = chain.reboot(approve=False, rc=3)
    assert out["tmp_staged"] == paths
    [n] = [n for n in out["next"] if "/tmp" in n and "tmp_staged" in n]
    assert n.startswith(line), n


def test_where_the_rule_keeps_tmp_the_chain_says_nothing_of_it(chain):
    _staged(chain, "0", ["/tmp/a"])
    out = chain.reboot(approve=False, rc=3)
    assert out["tmp_staged"] == []
    assert not [n for n in out["next"] if "tmp_staged" in n]
