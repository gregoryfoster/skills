"""coordinating-epics: a per-repo token map for scan.sh and the editor (#520).

The ambient gh token reads the epic's own repo. A private sibling's refs need
that sibling's token, and without one every check-in got the same 404s: the
scan's cross-repo reads (processor#24 F142, F154; #472 finding 8;
address-validator#272's fifth sighting) and the editor's comment-link check
(F169). `--token-for OWNER/REPO=VAR` names the variable holding a repo's
token, as the cohort's `.env` names them (`GH_TOKEN_PROVISIONER`). The value
reaches gh only as GH_TOKEN, for calls on that repo, and is never shown.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from tests.structural.coordinating_epics_gh_layer import install, output, token_calls
from tests.structural.coordinating_epics_rig import SCRIPTS, Rig, summary

HOST = "CannObserv/address-validator"
EPIC = 272
PROV = "CannObserv/provisioner"
WP = "CannObserv/cannabis.observer-wordpress"
AMBIENT = "ambient-token-0001"
PROV_TOKEN = "prov-token-SECRET-1111"
WP_TOKEN = "wp-token-SECRET-2222"

# The fifth sighting's epic, as far as the scan reads it: four refs the
# ambient token 404s on, all readable with the repo's own PAT.
BODY = """\
- **Last check-in:** 2026-11-05T09:00Z
- **Last issue seen:** #272

## Tier 1

- [ ] #273 next

## Waits

- CannObserv/provisioner#16 each host's two facts
- CannObserv/provisioner#61 the image bump
- CannObserv/provisioner#77 the disk GC
- CannObserv/cannabis.observer-wordpress#1152 the plugin pin
"""

ENV = {
    "GH_TOKEN": AMBIENT,
    "GH_TOKEN_PROVISIONER": PROV_TOKEN,
    "GH_TOKEN_CANNABIS_OBSERVER_WORDPRESS": WP_TOKEN,
}
MAP = [
    "--token-for",
    f"{PROV}=GH_TOKEN_PROVISIONER",
    "--token-for",
    f"{WP}=GH_TOKEN_CANNABIS_OBSERVER_WORDPRESS",
]


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path)
    install(r)
    r.issue(HOST, EPIC, body=BODY, updated_at="2026-11-05T09:00:00Z")
    r.issue(HOST, 273, updated_at="2026-11-01T00:00:00Z")
    # provisioner#16 had a new comment on 2026-11-06, the one the coordinator
    # missed behind the warning.
    r.issue(PROV, 16, updated_at="2026-11-06T15:00:00Z")
    r.issue(PROV, 61, updated_at="2026-10-20T00:00:00Z")
    r.issue(PROV, 77, updated_at="2026-10-21T00:00:00Z", state="closed")
    r.issue(WP, 1152, updated_at="2026-10-22T00:00:00Z")
    r.set_flag("tokens", {PROV: PROV_TOKEN, WP: WP_TOKEN})
    return r


def scan(rig, *extra, env=None):
    return rig.run(
        "scan.sh",
        "--repo",
        HOST,
        "--epic",
        str(EPIC),
        "--no-fetch",
        *extra,
        extra_env={**ENV, **(env or {})},
    )


def edit(rig, ops, *extra, env=None):
    return rig.run(
        "epic-edit.sh",
        "--repo",
        HOST,
        "--epic",
        str(EPIC),
        "--state-dir",
        str(rig.state_dir),
        "--ops",
        "-",
        *extra,
        stdin=json.dumps(ops),
        extra_env={**ENV, **(env or {})},
    )


def cross(report: dict) -> dict:
    return {x["ref"]: x for x in report["cross_repo"]}


# ---------------------------------------------------------------- the sightings


def test_the_fifth_sighting_names_the_variable_that_would_have_read_it(rig):
    """address-validator#272, 2026-11-07: four `unreadable; check which token
    reaches …` warnings at every check-in, read as noise. Each now names the
    set variable and the flag that uses it, and says updated_at is unknown."""
    res = scan(rig)
    assert res.returncode == 0, res.stderr
    r = json.loads(res.stdout)
    for ref, var, repo in (
        ("cannobserv/provisioner#16", "GH_TOKEN_PROVISIONER", "cannobserv/provisioner"),
        ("cannobserv/provisioner#61", "GH_TOKEN_PROVISIONER", "cannobserv/provisioner"),
        ("cannobserv/provisioner#77", "GH_TOKEN_PROVISIONER", "cannobserv/provisioner"),
        (
            "cannobserv/cannabis.observer-wordpress#1152",
            "GH_TOKEN_CANNABIS_OBSERVER_WORDPRESS",
            "cannobserv/cannabis.observer-wordpress",
        ),
    ):
        assert "error" in cross(r)[ref]
        (w,) = [w for w in r["warnings"] if w.startswith(ref + " ")]
        assert "updated_at is unknown" in w, w
        assert f"{var} is set: pass --token-for {repo}={var}" in w, w


def test_the_fifth_sighting_reads_every_ref_with_the_mapped_tokens(rig):
    """The same epic, with the repo's own PATs mapped: every row has its
    state, and provisioner#16's new comment shows as updated since."""
    res = scan(rig, *MAP)
    assert res.returncode == 0, res.stderr
    r = json.loads(res.stdout)
    rows = cross(r)
    assert all("error" not in x for x in rows.values()), rows
    assert rows["cannobserv/provisioner#16"]["updated_since"] is True
    assert rows["cannobserv/provisioner#61"]["updated_since"] is False
    assert rows["cannobserv/provisioner#77"]["state"] == "closed"
    assert rows["cannobserv/cannabis.observer-wordpress#1152"]["state"] == "open"
    assert not [w for w in r["warnings"] if "unreadable" in w], r["warnings"]


def test_f169_a_comment_link_on_a_private_sibling_resolves_with_its_token(rig):
    """processor#24 F169: the lint refused a cross-repo comment link the
    ambient token couldn't read. With the sibling's token mapped, it resolves."""
    rig.comment(PROV, 16, 555, body="two facts per host")
    url = f"https://github.com/{PROV}/issues/16#issuecomment-555"
    ops = [{"op": "note", "ref": "#273", "text": f"waits on [the ask]({url})"}]
    assert edit(rig, [], "--adopt-live").returncode == 0
    res = edit(rig, ops)
    assert res.returncode == 3, res.stderr
    assert "comment link doesn't resolve" in res.stderr
    assert (
        "GH_TOKEN_PROVISIONER is set: pass --token-for"
        " cannobserv/provisioner=GH_TOKEN_PROVISIONER" in res.stderr
    ), res.stderr
    res = edit(rig, ops, *MAP)
    assert res.returncode == 0, res.stderr
    assert url in rig.body(HOST, EPIC)


# ---------------------------------------------------------------- the mechanism


def test_the_token_reaches_gh_only_as_gh_token_for_its_own_repo(rig):
    res = scan(rig, *MAP)
    assert res.returncode == 0, res.stderr
    calls = token_calls(rig)
    for repo, tok in calls:
        want = {PROV.lower(): PROV_TOKEN, WP.lower(): WP_TOKEN}.get(
            repo.lower(), AMBIENT
        )
        assert tok == want, (repo, tok)
    assert {r.lower() for r, _ in calls} >= {HOST.lower(), PROV.lower(), WP.lower()}
    argv = json.dumps(rig.load()["calls"])
    assert PROV_TOKEN not in argv and WP_TOKEN not in argv


def test_a_mapped_epic_repo_is_read_with_its_token_graphql_included(rig):
    """The map covers the epic's own repo too: its REST reads and the GraphQL
    cross-check of its items."""
    rig.set_flag("tokens", {HOST: "host-token-SECRET-3333"})
    res = scan(
        rig,
        "--token-for",
        f"{HOST}=GH_TOKEN_ADDRESS_VALIDATOR",
        env={"GH_TOKEN_ADDRESS_VALIDATOR": "host-token-SECRET-3333"},
    )
    assert res.returncode == 0, res.stderr
    assert rig.load().get("graphql_calls", 0) >= 1
    host_calls = [t for r, t in token_calls(rig) if r.lower() == HOST.lower()]
    assert host_calls and set(host_calls) == {"host-token-SECRET-3333"}


def test_the_repo_in_the_map_is_matched_whatever_its_case(rig):
    res = scan(rig, "--token-for", "cannobserv/PROVISIONER=GH_TOKEN_PROVISIONER")
    r = json.loads(res.stdout)
    assert "error" not in cross(r)["cannobserv/provisioner#16"]


def run_bare(rig, script: str, *args: str, unset: str, stdin: str = "[]"):
    """Run with ENV, but with the variable unset rather than empty."""
    env = {**rig.env(), **ENV}
    env.pop(unset, None)
    return subprocess.run(
        ["bash", str(SCRIPTS / script), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
@pytest.mark.parametrize("script", ["scan.sh", "epic-edit.sh"])
def test_a_mapped_variable_that_is_missing_is_a_usage_error_not_a_fallback(
    rig, script, value
):
    """#520: never a silent fall back to the ambient token. Exit 1, the
    variable named, nothing fetched."""
    args = ["--repo", HOST, "--epic", str(EPIC)]
    args += ["--token-for", f"{PROV}=GH_TOKEN_PROVISIONER"]
    if script == "epic-edit.sh":
        args += ["--state-dir", str(rig.state_dir), "--adopt-live", "--ops", "-"]
    if value is None:
        res = run_bare(rig, script, *args, unset="GH_TOKEN_PROVISIONER")
    else:
        res = rig.run(
            script, *args, stdin="[]", extra_env={**ENV, "GH_TOKEN_PROVISIONER": ""}
        )
    assert res.returncode == 1, res.stderr
    assert "GH_TOKEN_PROVISIONER" in res.stderr
    assert ("not set" if value is None else "is empty") in res.stderr, res.stderr
    assert token_calls(rig) == []


@pytest.mark.parametrize(
    "spec",
    [
        f"{PROV}=ghp_" + "A" * 36,
        f"{PROV}=github_pat_" + "B" * 30,
        "ghp_" + "C" * 36,
        f"{PROV}",
        f"{PROV}=",
        "not-a-repo=GH_TOKEN_X",
        f"{PROV}=GH-TOKEN",
    ],
    ids=[
        "classic-token-as-name",
        "fine-grained-token-as-name",
        "token-alone",
        "no-equals",
        "no-name",
        "no-owner",
        "bad-name",
    ],
)
def test_a_malformed_map_is_a_usage_error_that_never_echoes_a_value(rig, spec):
    """A token pasted where its variable's name goes is refused without
    printing it: the usage error names the repo, never the value."""
    res = scan(rig, "--token-for", spec)
    assert res.returncode == 1, res.stderr
    secret = spec.split("=", 1)[-1]
    if secret.startswith(("ghp_", "github_pat_")):
        assert secret not in output(res)
    assert token_calls(rig) == []


def test_one_repo_mapped_to_two_variables_is_a_usage_error(rig):
    res = scan(
        rig,
        "--token-for",
        f"{PROV}=GH_TOKEN_PROVISIONER",
        "--token-for",
        f"{PROV.lower()}=GH_TOKEN_CANNABIS_OBSERVER_WORDPRESS",
    )
    assert res.returncode == 1 and "cannobserv/provisioner" in res.stderr.lower()


@pytest.mark.parametrize("script", ["scan", "edit"])
def test_no_token_value_is_ever_shown_even_when_gh_echoes_it(rig, script):
    """gh's whole stderr is surfaced (#410, #426). A gh that printed its own
    environment would put the token in a warning or an error, so every token
    in the map is masked in what gh says."""
    rig.set_flag("echo_env", PROV)
    rig.comment(PROV, 16, 555, body="x")
    if script == "scan":
        res = scan(rig, *MAP)
        assert res.returncode == 0, res.stderr
        r = json.loads(res.stdout)
        assert "GH_TOKEN_PROVISIONER" in cross(r)["cannobserv/provisioner#16"]["error"]
    else:
        assert edit(rig, [], "--adopt-live").returncode == 0
        url = f"https://github.com/{PROV}/issues/16#issuecomment-555"
        res = edit(rig, [{"op": "note", "ref": "#273", "text": url}], *MAP)
        assert res.returncode == 3, res.stderr
    out = output(res)
    assert "argv:" in out  # gh's stderr was shown
    assert PROV_TOKEN not in out and WP_TOKEN not in out
    assert AMBIENT not in out


def test_a_mapped_repo_that_still_fails_names_its_variable_and_never_retries(rig):
    """The mapped token is the only one tried for that repo: a 404 with it is
    reported as such, with no second read under the ambient token."""
    rig.set_flag("tokens", {PROV: "some-other-token", WP: WP_TOKEN})
    res = scan(rig, *MAP)
    r = json.loads(res.stdout)
    (w,) = [w for w in r["warnings"] if w.startswith("cannobserv/provisioner#16 ")]
    assert "with GH_TOKEN_PROVISIONER (--token-for)" in w, w
    prov = [t for repo, t in token_calls(rig) if repo.lower() == PROV.lower()]
    assert prov and set(prov) == {PROV_TOKEN}


def test_a_candidate_holding_the_ambient_token_is_not_suggested(rig):
    """Naming a variable that holds the token that just failed would send the
    next agent round the same loop."""
    res = scan(rig, env={"GH_TOKEN_PROVISIONER": AMBIENT})
    r = json.loads(res.stdout)
    (w,) = [w for w in r["warnings"] if w.startswith("cannobserv/provisioner#16 ")]
    assert "--token-for" not in w and "check which token reaches" in w, w


def test_the_owner_qualified_candidate_is_named_too(rig):
    res = scan(
        rig,
        env={"GH_TOKEN_PROVISIONER": "", "GH_TOKEN_CANNOBSERV_PROVISIONER": PROV_TOKEN},
    )
    r = json.loads(res.stdout)
    (w,) = [w for w in r["warnings"] if w.startswith("cannobserv/provisioner#16 ")]
    assert (
        "GH_TOKEN_CANNOBSERV_PROVISIONER is set: pass --token-for"
        " cannobserv/provisioner=GH_TOKEN_CANNOBSERV_PROVISIONER" in w
    ), w


def test_help_documents_the_flag(rig):
    for script in ("scan.sh", "epic-edit.sh"):
        res = rig.run(script, "--help")
        assert res.returncode == 0 and "--token-for" in res.stdout, script


def test_summary_carries_no_token_value(rig):
    rig.comment(PROV, 16, 555, body="x")
    assert edit(rig, [], "--adopt-live", *MAP).returncode == 0
    url = f"https://github.com/{PROV}/issues/16#issuecomment-555"
    res = edit(rig, [{"op": "note", "ref": "#273", "text": url}], *MAP)
    assert res.returncode == 0, res.stderr
    s = summary(res)
    assert PROV_TOKEN not in json.dumps(s)
