"""patching-hosts: a third-party package's class key is its repo's Origin (#695).

apt-get -s prints a candidate's release in an Inst line's parentheses as
apt's RelStr: `<Label>:` where the Release file has a Label, then
`<Version>/<Archive>`, `<Archive>`, or with no Archive the site. That's the
Label, and a knob's `origin` lines, unattended-upgrades' `o=`, `read_origins`'
`origin:` findings and `apply.sh`'s `followed_class` all name the Origin. The
probe keyed the class on the Label, and cut it at its first `)`:

- the ondrej/php PPA reads `PPA for PHP (deprecated)`, so its packages
  classed as `third-party:PPA_for_PHP_(deprecated`, a key no knob line can
  state;
- packages.sury.org has no Label, so its packages classed as its suite,
  `noble`;
- Docker's reads `Docker CE`, its Origin `Docker`.

What this file pins:

- `inst_class` keys each on the Origin, from apt-cache policy's release
  lines, and reads a Label holding spaces and a `)` whole;
- a release apt-cache policy doesn't list, or whose text two origins print
  (two Label-less repos on one suite), keeps apt's own text, as before;
- `class_of` keeps its contract: the same text gives the same key;
- the probe's pending set, its knob findings and its one-origin dry run read
  the Origin, so `origin LP-PPA-ondrej-php hold` and `origin
  packages.sury.org follow` name what they meant to; Tailscale's is unchanged;
- `apply.sh`'s one-origin bulk takes a Label-less repo's packages.

The Inst and policy lines are real: an ubuntu:24.04 container, apt 2.8.3,
arm64, with libgd3 installed from Ubuntu, then each repo added in turn
(2026-11-23).
"""

import subprocess

import pytest

from tests.structural.patching_hosts_rig import SKILL, clean_env, dispatcher
from tests.structural.test_patching_hosts_apply import KNOB, SIM_ARGS, TUE_1530
from tests.structural.test_patching_hosts_lane import _lane
from tests.structural.test_patching_hosts_probe import Host as ProbeHost
from tests.structural.test_patching_hosts_probe import _ids

LIB = SKILL / "scripts" / "_probe-lib.sh"

ONDREJ_INST = (
    "Inst libgd3 [2.3.3-9ubuntu5] (2.3.3-13+ubuntu24.04.1+deb.sury.org+1"
    " PPA for PHP (deprecated):24.04/noble [arm64])"
)
ONDREJ_POLICY = (
    " 500 https://ppa.launchpadcontent.net/ondrej/php/ubuntu noble/main arm64 Packages\n"
    "     release v=24.04,o=LP-PPA-ondrej-php,a=noble,n=noble,"
    "l=PPA for PHP (deprecated),c=main,b=arm64\n"
    "     origin ppa.launchpadcontent.net\n"
)
SURY_INST = (
    "Inst libgd3 [2.3.3-9ubuntu5] (2.3.3-17+debsuryorg24.04.1+php+2 noble [arm64])"
)
SURY_POLICY = (
    " 500 https://packages.sury.org/php noble/main arm64 Packages\n"
    "     release o=deb.sury.org,a=noble,n=noble,c=main,b=arm64\n"
    "     origin packages.sury.org\n"
)
DOCKER_INST = (
    "Inst containerd.io [2.4.2-2~ubuntu.24.04~noble]"
    " (2.4.2-4~ubuntu.24.04~noble Docker CE:noble [arm64])"
)
DOCKER_POLICY = (
    " 500 https://download.docker.com/linux/ubuntu noble/stable arm64 Packages\n"
    "     release o=Docker,a=noble,l=Docker CE,c=stable,b=arm64\n"
    "     origin download.docker.com\n"
)
TS_INST = "Inst tailscale [1.102.2] (1.102.4 Tailscale:pkgs.tailscale.com [arm64])"
TS_POLICY = (
    " 500 https://pkgs.tailscale.com/stable/ubuntu noble/main arm64 Packages\n"
    "     release o=Tailscale,n=noble,l=Tailscale,c=main,b=arm64\n"
    "     origin pkgs.tailscale.com\n"
)
UBUNTU_INST = (
    "Inst libc6 [2.39-0ubuntu8.3] (2.39-0ubuntu8.4"
    " Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [arm64])"
)
UBUNTU_POLICY = (
    " 500 http://ports.ubuntu.com/ubuntu-ports noble-security/main arm64 Packages\n"
    "     release v=24.04,o=Ubuntu,a=noble-security,n=noble,l=Ubuntu,c=main,b=arm64\n"
    "     origin ports.ubuntu.com\n"
    " 500 http://ports.ubuntu.com/ubuntu-ports noble-updates/main arm64 Packages\n"
    "     release v=24.04,o=Ubuntu,a=noble-updates,n=noble,l=Ubuntu,c=main,b=arm64\n"
    "     origin ports.ubuntu.com\n"
)
POLICY = ONDREJ_POLICY + SURY_POLICY + DOCKER_POLICY + TS_POLICY + UBUNTU_POLICY


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


def _lib(body: str, **env: str) -> str:
    r = subprocess.run(
        ["bash", "-c", f'. "{LIB}"; {body}'],
        capture_output=True,
        text=True,
        env={**clean_env(), **env},
        check=True,
    )
    return r.stdout


def _inst_class(line: str, policy: str) -> str:
    return _lib(
        'inst_class c "$LINE" "$POLICY"; printf %s "$c"', LINE=line, POLICY=policy
    )


@pytest.mark.parametrize(
    "line, key",
    [
        (ONDREJ_INST, "third-party:LP-PPA-ondrej-php"),
        (SURY_INST, "third-party:deb.sury.org"),
        (DOCKER_INST, "third-party:Docker"),
        (TS_INST, "third-party:Tailscale"),
        (UBUNTU_INST, "security"),
    ],
    ids=["ondrej", "sury", "docker", "tailscale", "ubuntu"],
)
def test_the_class_key_is_the_repos_origin(line, key):
    assert _inst_class(line, POLICY) == key
    # The line with its package name taken off reads the same.
    assert _inst_class(line.split(" ", 2)[2], POLICY) == key


def test_a_label_with_a_paren_reads_whole_where_no_release_line_maps_it():
    # No policy: apt's own text, but no longer cut at the label's ")".
    assert _inst_class(ONDREJ_INST, "") == "third-party:PPA_for_PHP_(deprecated)"
    assert _inst_class(SURY_INST, "") == "third-party:noble"


def test_two_origins_printing_the_same_text_keep_apts_own():
    other = SURY_POLICY.replace("deb.sury.org", "example.org").replace(
        "packages.sury.org", "apt.example.org"
    )
    assert _inst_class(SURY_INST, SURY_POLICY + other) == "third-party:noble"


def test_class_of_keeps_its_contract():
    out = _lib(
        'class_of a "PPA for PHP (deprecated):24.04/noble"; '
        'class_of b "PPA for PHP (deprecated"; class_of c noble; '
        'class_of d "Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security"; '
        'printf "%s|%s|%s|%s" "$a" "$b" "$c" "$d"'
    )
    assert out == (
        "third-party:PPA_for_PHP_(deprecated)|third-party:PPA_for_PHP_(deprecated"
        "|third-party:noble|security"
    )


def test_sim_class_reads_the_origin_given_the_policy():
    sim = f"NOTE: This is only a simulation!\n{ONDREJ_INST}\n{UBUNTU_INST}\n"
    out = _lib(
        'sim_class a libgd3 "$SIM" "$POLICY"; sim_class b libgd3 "$SIM"; '
        'sim_class c libc6 "$SIM" "$POLICY"; printf "%s|%s|%s" "$a" "$b" "$c"',
        SIM=sim,
        POLICY=POLICY,
    )
    assert out == (
        "third-party:LP-PPA-ondrej-php|third-party:PPA_for_PHP_(deprecated)|security"
    )


# apt-get -s adds a suffix after the paren where a package breaks another:
# " []" or " [<pkg>:<arch> ]" (noble, apt 2.8.3, 2026-11-23; CR 2764).
SUFFIXED = [
    (
        "Inst perl-base [5.38.2-3.2build2] (5.38.2-3.2ubuntu0.7 Ubuntu:24.04/noble-updates,"
        " Ubuntu:24.04/noble-security [arm64]) []",
        "security",
    ),
    (
        "Inst libperl5.38t64 [5.38.2-3.2build2] (5.38.2-3.2ubuntu0.7"
        " Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [arm64]) [perl:arm64 ]",
        "security",
    ),
    (SURY_INST + " []", "third-party:deb.sury.org"),
    (DOCKER_INST + " [docker-ce:arm64 ]", "third-party:Docker"),
    (
        "Inst php8.3-cli [8.3.1] (8.3.2 PPA for PHP (deprecated):24.04/noble [arm64]) []",
        "third-party:LP-PPA-ondrej-php",
    ),
]


@pytest.mark.parametrize(
    "line, key", SUFFIXED, ids=["empty", "pkg-arch", "sury", "docker", "ondrej"]
)
def test_a_suffix_after_the_paren_doesnt_change_the_class(line, key):
    assert _inst_class(line, POLICY) == key
    name = line.split(" ")[1]
    out = _lib(
        f'sim_class c {name} "$SIM" "$POLICY"; printf %s "$c"',
        SIM=f"NOTE: This is only a simulation!\n{line}\n",
        POLICY=POLICY,
    )
    assert out == key


def test_origin_split_takes_a_suffixed_line_from_its_origin():
    sim = f"{SURY_INST} []\n{SURY_INST.replace('libgd3', 'libgd-tools')}\n"
    sim += SUFFIXED[0][0] + "\n"
    out = _lib(
        'origin_names n packages.sury.org "$POLICY"; '
        'origin_split k s "$n" "$SIM" "$POLICY"; printf "%s|%s" "$k" "$s"',
        SIM=sim,
        POLICY=POLICY,
    )
    assert out == "libgd3 libgd-tools|perl-base"


# --- the probe ---------------------------------------------------------------


def _probe(tmp_path, knob: str, sim: str, policy: str = POLICY) -> ProbeHost:
    h = ProbeHost(tmp_path).knob(knob)
    h.on("apt-get", "-s *dist-upgrade", f"NOTE: This is only a simulation!\n{sim}")
    h.on("apt-cache", "*policy", policy)
    return h


def test_the_probe_counts_each_origin_under_its_o_name(tmp_path):
    sim = "\n".join((ONDREJ_INST, DOCKER_INST, TS_INST, UBUNTU_INST)) + "\n"
    sim += SURY_INST.replace("libgd3", "libgd-tools") + "\n"
    out = _probe(tmp_path, "posture automatic\n", sim).run()
    assert out["pending"]["by_class"]["third_party"] == {
        "LP-PPA-ondrej-php": 1,
        "deb.sury.org": 1,
        "Docker": 1,
        "Tailscale": 1,
    }
    assert out["pending"]["packages"]["third_party"] == [
        "libgd3",
        "containerd.io",
        "tailscale",
        "libgd-tools",
    ]


def test_the_probe_counts_suffixed_lines_by_their_class(tmp_path):
    sim = "".join(line + "\n" for line, _ in SUFFIXED)
    out = _probe(tmp_path, "posture automatic\n", sim).run()
    p = out["pending"]
    assert p["by_class"]["security_lower_bound"] == 2
    assert p["by_class"]["updates"] == 0
    assert p["by_class"]["third_party"] == {
        "deb.sury.org": 1,
        "Docker": 1,
        "LP-PPA-ondrej-php": 1,
    }


def test_a_knob_line_naming_the_origin_or_its_site_covers_its_packages(tmp_path):
    knob = (
        "posture scheduled\n"
        "origin LP-PPA-ondrej-php hold the PPA is frozen\n"
        "origin packages.sury.org follow\n"
        "origin Docker hold the image pins it\n"
        "origin Tailscale follow\n"
    )
    sim = (
        f"{ONDREJ_INST}\n{SURY_INST.replace('libgd3', 'libgd-tools')}\n{DOCKER_INST}\n"
    )
    out = _probe(tmp_path, knob, sim).run()
    assert not [i for i in _ids(out) if i.startswith("origin:")], _ids(out)


def test_the_probes_one_origin_dry_run_takes_a_label_less_repos_packages(tmp_path):
    h = _probe(
        tmp_path,
        "class production\nposture scheduled\norigin packages.sury.org follow\n",
        f"{SURY_INST}\n{UBUNTU_INST}\n",
    )
    h.on(
        "unattended-upgrade",
        "--dry-run -d",
        "Packages that will be upgraded: libgd3\n",
    )
    h.on(
        "apt-get",
        "update*",
        script="for a; do case $a in Dir::State::Lists=*) d=${a#*=} ;; esac; done; "
        'touch "${d}security.ubuntu.com_ubuntu_dists_noble-security_InRelease" '
        '"${d}packages.sury.org_php_dists_noble_InRelease"; exit 0',
    )
    lane = "origin:packages.sury.org"
    out = h.run(
        "--refresh-into",
        str(h.tmp / "fresh"),
        "--dry-run-into",
        str(h.tmp / "dry"),
        "--lane",
        lane,
    )
    d = out["pending"]["dry_run"]
    assert d["lane"] == lane and d["count"] == 1, d
    assert d["origin_pending"] == ["libgd3"]
    [(_, _, apt_config)] = h.calls("unattended-upgrade")
    conf = open(apt_config).read()
    assert '  "^libc6$";' in conf and '"^libgd3$"' not in conf


# --- apply.sh ----------------------------------------------------------------


def test_the_one_origin_bulk_takes_a_label_less_repos_packages(tmp_path):
    lane = "origin:packages.sury.org"
    host = _lane(tmp_path, KNOB + "origin packages.sury.org follow\n")
    s = host.state
    (s / "sim").write_text(f"{SURY_INST}\n{UBUNTU_INST}\n")
    (s / "sim-after").write_text(f"{UBUNTU_INST}\n")
    host.cases["apt-get"].insert(
        0,
        (
            SIM_ARGS,
            "",
            0,
            "",
            f'if [ -e "{s}/took" ]; then cat "{s}/sim-after"; else cat "{s}/sim"; fi; exit 0',
        ),
    )
    host.on("apt-cache", "policy", POLICY)
    host.uu(
        "Packages that will be upgraded: libgd3\nAll upgrades installed\n",
        before=f'touch "{s}/took"; ',
    )
    (host.dry / "summary").write_text(
        f"began={TUE_1530 - 3600}\nexit=0\ncount=1\nwall_seconds=60\n"
        f"security_only=0\nlane={lane}\norigin_left=\nlists_refreshed=1\n"
    )
    out = host.run("--lane", lane)
    assert out["verdict"]["ok"] is True, out
    assert out["upgrade"]["origin_pending"] == ["libgd3"]
    skipped = host.record("lane.conf").split("Package-Blacklist {")[1]
    assert '  "^libc6$";' in skipped and "libgd3" not in skipped


# A file: repo, flat (noble, apt 2.8.3, 2026-11-23; CR 2772): apt-cache policy
# prints no origin line under its release line, since its site is empty. With
# no Suite in its Release file, apt-get -s prints "localhost" for it.
FILE_POLICY = (
    " 500 file:/repo3 ./ Packages\n"
    "     release o=Local3,c=\n"
    " 500 file:/repo2 ./ Packages\n"
    "     release o=Local,a=stable,l=Local Repo,c=\n"
)


@pytest.mark.parametrize(
    "line, policy, key",
    [
        (
            "Inst hostname [3.23+nmu2ubuntu2] (99.0 localhost [arm64])",
            FILE_POLICY + UBUNTU_POLICY,
            "third-party:Local3",
        ),
        (
            "Inst hostname [3.23+nmu2ubuntu2] (99.0 Local Repo:stable [arm64])",
            FILE_POLICY + UBUNTU_POLICY,
            "third-party:Local",
        ),
        # Last in the policy, with nothing after it.
        (
            "Inst hostname [3.23+nmu2ubuntu2] (99.0 Local Repo:stable [arm64])",
            UBUNTU_POLICY + FILE_POLICY,
            "third-party:Local",
        ),
        # A Release file with no Origin: nothing to map, so apt's text.
        (
            "Inst hostname [3.23+nmu2ubuntu2] (99.0 localhost [arm64])",
            " 500 file:/repo1 ./ Packages\n     release c=\n" + UBUNTU_POLICY,
            "third-party:localhost",
        ),
    ],
    ids=["no-suite", "suite", "last", "no-origin"],
)
def test_a_file_repo_with_no_origin_line_maps_too(line, policy, key):
    assert _inst_class(line, policy) == key
    # A site-less release doesn't take the next release's origin line.
    assert _inst_class(UBUNTU_INST, policy) == "security"


def test_a_bulk_that_cant_read_the_policy_says_its_classes_read_the_label(tmp_path):
    # CR 2771: the security and maintenance lanes go on without it, keyed on
    # apt's Label as before #695, and the bulk's record says so.
    host = _lane(tmp_path)
    host.cases["apt-cache"].insert(0, ("policy", "", 100, "E: broken\n", None))
    out = host.run("--lane", "maintenance")
    assert out["verdict"]["ok"] is True, out
    why = out["holds"]["classes_by_label"]
    assert "apt-cache policy" in why and "E: broken" in why and "#695" in why


def test_a_bulk_that_reads_the_policy_says_nothing_of_it(tmp_path):
    host = _lane(tmp_path)
    host.on("apt-cache", "policy", POLICY)
    out = host.run("--lane", "maintenance")
    assert out["verdict"]["ok"] is True, out
    assert "classes_by_label" not in out["holds"]
