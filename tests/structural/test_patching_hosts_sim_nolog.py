"""Every apt simulation patching-hosts runs leaves apt's planner log alone (#704).

Run as root, an `apt-get -s` rewrites /var/log/apt/eipp.log.xz, apt's
planner log of the host's last real install (apt 2.8.3, #696, CR 2779): a
read-only plan or probe would overwrite the record someone debugging that
install would read. probe.sh passes `Dir::Log::Planner=/dev/null` in
APT_OPTS, apply.sh in SIM_NOLOG, and the prune scripts in PRUNE_SIM_OPTS.
This holds the next simulation to it.

The scan reads the scripts as shell, not as text: a comment or a message
that names `apt-get -s` (`fail "apt-get -s dist-upgrade failed …"`) isn't a
command, and an option an array carries (`"${SIM_NOLOG[@]}"`) counts. A
command built inside a quoted string, as reboot-chain.sh builds its script,
isn't read: none runs `apt-get -s` today.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "patching-hosts" / "scripts"
PLANNER = "Dir::Log::Planner=/dev/null"
SIMULATE = {"-s", "--simulate", "--just-print", "--dry-run", "--recon", "--no-act"}
ARRAY_DEF = re.compile(
    r"(?:^|[\s;(])(?:local\s+-a\s+)?([A-Za-z_][A-Za-z0-9_]*)=\((.*)\)"
)
ARRAY_USE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\[@\]")


HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")


def code_of(body: str) -> str:
    """The script as the shell reads its words: quoted text, comments and
    heredoc bodies blanked to spaces, the quotes themselves and every
    newline kept, so each position still matches the source's. An array
    expansion inside double quotes stays readable."""
    out, q, i, n = [], "", 0, len(body)
    heredocs: list[tuple[str, bool]] = []
    while i < n:
        c = body[i]
        if q == "'":
            q = "" if c == "'" else q
            out.append(c if c in "'\n" else " ")
        elif q == '"':
            if c == "\\" and i + 1 < n:
                out.append("  " if body[i + 1] != "\n" else " \n")
                i += 2
                continue
            if c == '"':
                q = ""
                out.append(c)
            elif body.startswith("${", i):
                # "${NAME[@]}" is an array's words, not message text.
                j = body.find("}", i)
                j = n - 1 if j < 0 else j
                out.append(body[i : j + 1])
                i = j + 1
                continue
            else:
                out.append(c if c == "\n" else " ")
        elif c == "\\" and i + 1 < n:
            out.append(body[i : i + 2])
            i += 2
            continue
        elif c in "'\"":
            q = c
            out.append(c)
        elif c == "#" and (i == 0 or body[i - 1] in " \t\n;(|&"):
            j = body.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
            continue
        elif c == "<" and body.startswith("<<", i) and not body.startswith("<<<", i):
            m = HEREDOC.match(body, i)
            if m:
                heredocs.append((m.group(3), m.group(1) == "-"))
            out.append(c)
        elif c == "\n" and heredocs:
            # The bodies start on the next line, each to its delimiter.
            out.append(c)
            i += 1
            for word, tabs in heredocs:
                while i < n:
                    j = body.find("\n", i)
                    j = n if j < 0 else j
                    line = body[i:j]
                    out.append(" " * len(line))
                    if j < n:
                        out.append("\n")
                    i = j + 1
                    if (line.lstrip("\t") if tabs else line) == word:
                        break
            heredocs = []
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def logical_lines_of(body: str) -> list[tuple[int, str, str]]:
    """Each command line as (its first line's number, its code, its source),
    a backslash continuation joined."""
    rows, code, raw, start = [], "", "", 0
    for n, (c, r) in enumerate(zip(code_of(body).split("\n"), body.split("\n")), 1):
        if not code:
            start = n
        if c.endswith("\\"):
            code += c[:-1] + " "
            raw += r[:-1] + " "
            continue
        rows.append((start, code + c, raw + r))
        code, raw = "", ""
    if code:
        rows.append((start, code, raw))
    return rows


def commands(code: str, raw: str) -> list[tuple[str, str]]:
    """The line's simple commands, split at an unquoted ; | & ( or ), as
    (code, source): the words are read from the code, an option from the
    source, so a quoted one counts."""
    return [
        (m.group(), raw[m.start() : m.end()])
        for m in re.finditer(r"[^;|&()]+", code)
        if m.group().strip()
    ]


def scan(scripts: dict[str, str]) -> list[str]:
    """`<file>:<line>: <command>` for each apt-get simulation that carries
    the planner option neither itself nor through every definition of an
    array it expands."""
    rows = {name: logical_lines_of(body) for name, body in scripts.items()}
    defs: dict[str, list[str]] = {}
    for lines in rows.values():
        for _, code, raw in lines:
            for m in ARRAY_DEF.finditer(code):
                defs.setdefault(m.group(1), []).append(raw[m.start(2) : m.end(2)])
    # An array carries the option when each of its definitions does, itself
    # or through an array it expands: to a fixed point.
    carries: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, bodies in defs.items():
            if name not in carries and all(
                PLANNER in b or any(u in carries for u in ARRAY_USE.findall(b))
                for b in bodies
            ):
                carries.add(name)
                changed = True
    missing = []
    for name, lines in rows.items():
        for n, code, raw in lines:
            for cmd, src in commands(code, raw):
                words = cmd.split()
                if "apt-get" not in words:
                    continue
                if not SIMULATE & set(words[words.index("apt-get") + 1 :]):
                    continue
                if PLANNER in src or any(u in carries for u in ARRAY_USE.findall(src)):
                    continue
                missing.append(f"{name}:{n}: {src.strip()}")
    return missing


def the_scripts() -> dict[str, str]:
    return {p.name: p.read_text() for p in sorted(SCRIPTS.glob("*.sh"))}


def test_every_apt_get_simulation_leaves_the_planner_log_alone():
    missing = scan(the_scripts())
    assert not missing, (
        "apt-get -s run as root rewrites /var/log/apt/eipp.log.xz (#704): pass "
        f"-o {PLANNER}, as APT_OPTS, SIM_NOLOG and PRUNE_SIM_OPTS do:\n"
        + "\n".join(missing)
    )


def test_the_scan_reads_the_known_simulations():
    """Not vacuous: the scan finds the sites it holds, in each script that
    simulates, the ones through an array included."""
    scripts = the_scripts()
    found = scan({k: v.replace(PLANNER, "X") for k, v in scripts.items()})
    files = {f.split(":", 1)[0] for f in found}
    assert {
        "probe.sh",
        "apply.sh",
        "prune-plan.sh",
        "_prune-lib.sh",
        "_probe-lib.sh",
    } <= files, found
    assert len(found) >= 9, found


def test_the_scan_skips_comments_and_messages_and_follows_arrays():
    body = "\n".join(
        [
            "# apt-get -s autoremove, in a comment",
            'fail "apt-get -s dist-upgrade failed: nothing was held"',
            "x=1  # apt-get -s here too",
            f"OK=(-o {PLANNER})",
            'WRAP=(as_root apt-get -s "${OK[@]}")',
            'capture out apt-get -s "${OK[@]}" dist-upgrade',
            'capture out "${WRAP[@]}" install',
            "capture out apt-get -s \\",
            f"  -o {PLANNER} autoremove",
            "BARE=(apt-get -s)",
            "capture y apt-get -s autoremove",
            'capture z apt-get -s ${BARE[@]+"${BARE[@]}"} purge x',
            "apt-get purge -y x",
            "BAD=(-o Debug::NoLocking=1)",
            'capture w apt-get -s "${BAD[@]}" remove x',
            "cat <<'USAGE'",
            "  apt-get -s autoremove, in a heredoc's help",
            "USAGE",
            f'capture v apt-get -s -o "{PLANNER}" autoremove',
            'msg="a message over',
            'two lines: apt-get -s remove"',
        ]
    )
    missing = [m.split(":")[1] for m in scan({"t.sh": body})]
    assert missing == ["10", "11", "12", "15"], scan({"t.sh": body})
