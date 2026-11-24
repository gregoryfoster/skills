"""Every apt simulation patching-hosts runs leaves apt's planner log alone,
and every apt read the prune scripts run, its caches as root (#704).

Run as root, an `apt-get -s` rewrites /var/log/apt/eipp.log.xz, apt's
planner log of the host's last real install (apt 2.8.3, #696, CR 2779): a
read-only plan or probe would overwrite the record someone debugging that
install would read. probe.sh passes `-o Dir::Log::Planner=/dev/null` in
APT_OPTS, apply.sh in SIM_NOLOG, and the prune scripts in PRUNE_SIM_OPTS.
An apt-get or apt-cache as root also rebuilds a stale pkgcache.bin, so the
prune scripts' apt-cache reads pass PRUNE_CACHE_OPTS (CR 2824).

The scan reads the scripts as shell, not as text. A comment, a heredoc's
help or a message that names `apt-get -s` (`fail "apt-get -s dist-upgrade
failed …"`) isn't a command; a command substitution, in double quotes or
not, and a backtick are. A simulation is `apt-get` or `apt`, by any path,
with `-s`, a short cluster holding `s` (`-qs`), a long form, or
`-o APT::Get::Simulate=true`. The option counts when it is `-o` and its
last `Dir::Log::Planner` is `/dev/null`, quoted or not, or when it comes
through an array each of whose `NAME=(…)` definitions carries it.

Not read, as accepted limits (CR 2823): an array changed by `read -a` or by
an element's assignment (`A[1]=…`); a command word that is itself an
array's expansion (`"${A[@]}" -s` with `A=(apt-get)`); and a command inside
a quoted string, `sh -c '…'` or the script reboot-chain.sh builds in `c
"…"` lines. None runs a simulation today.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "patching-hosts" / "scripts"
PRUNE_SCRIPTS = ("prune-plan.sh", "prune.sh", "_prune-lib.sh")
PLANNER = "Dir::Log::Planner=/dev/null"
CACHE_BLANKS = ("Dir::Cache::pkgcache=", "Dir::Cache::srcpkgcache=")
SIMULATE_LONG = {"--simulate", "--just-print", "--dry-run", "--recon", "--no-act"}
SIMULATE_OPT = re.compile(r"(?i)APT::Get::Simulate=[\"']?(?:true|yes|1|on)\b")
PLANNER_OPT = re.compile(r"-o\s*[\"']?Dir::Log::Planner=([^\s\"')]*)")
ARRAY_DEF = re.compile(
    r"(?:^|[\s;(])(?:(?:local|declare)\s+-a\s+)?([A-Za-z_][A-Za-z0-9_]*)=\((.*)\)"
)
ARRAY_USE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\[[@*]\]")
HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
# What code_of puts where a comment or a heredoc's body was.
GONE = "\x01"


def code_of(body: str) -> str:
    """The script as the shell reads its words, position for position:
    quoted text blanked to spaces, a comment and a heredoc's body to GONE,
    the quotes and every newline kept. A command substitution, `$(…)` or a
    backtick, is code even inside double quotes; a backtick reads as ( and
    ), so the commands split there. An array's expansion inside double
    quotes stays readable."""
    out: list[str] = []
    stack = ["top"]
    heredocs: list[tuple[str, bool]] = []
    i, n = 0, len(body)
    while i < n:
        c, top = body[i], stack[-1]
        if top == "sq":
            if c == "'":
                stack.pop()
            out.append(c if c in "'\n" else " ")
        elif top == "dq":
            if c == "\\" and i + 1 < n:
                out.append(" \n" if body[i + 1] == "\n" else "  ")
                i += 2
                continue
            if c == '"':
                stack.pop()
                out.append(c)
            elif body.startswith("$(", i):
                stack.append("sub")
                out.append("$(")
                i += 2
                continue
            elif c == "`":
                stack.append("bt")
                out.append("(")
            elif body.startswith("${", i):
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
        elif c == "'":
            stack.append("sq")
            out.append(c)
        elif c == '"':
            stack.append("dq")
            out.append(c)
        elif c == "`":
            if top == "bt":
                stack.pop()
                out.append(")")
            else:
                stack.append("bt")
                out.append("(")
        elif body.startswith("$(", i):
            stack.append("sub")
            out.append("$(")
            i += 2
            continue
        elif c == "(":
            if top in ("sub", "par"):
                stack.append("par")
            out.append(c)
        elif c == ")":
            if top in ("sub", "par"):
                stack.pop()
            out.append(c)
        elif c == "#" and (i == 0 or body[i - 1] in " \t\n;(|&`"):
            j = body.find("\n", i)
            j = n if j < 0 else j
            out.append(GONE * (j - i))
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
                    out.append(GONE * len(line))
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
    """Each command line as (its first line's number, its code, its source
    without comments), a backslash continuation joined."""
    rows, code, raw, start = [], "", "", 0
    for n, (c, r) in enumerate(zip(code_of(body).split("\n"), body.split("\n")), 1):
        r = "".join(" " if k == GONE else ch for k, ch in zip(c, r))
        c = c.replace(GONE, " ")
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


def arrays(rows: dict) -> dict[str, list[str]]:
    """Each array's `NAME=(…)` definitions' source, across the scripts."""
    defs: dict[str, list[str]] = {}
    for lines in rows.values():
        for _, code, raw in lines:
            for m in ARRAY_DEF.finditer(code):
                defs.setdefault(m.group(1), []).append(raw[m.start(2) : m.end(2)])
    return defs


def carries_planner(src: str) -> bool:
    values = PLANNER_OPT.findall(src)
    return bool(values) and values[-1] == "/dev/null"


def apt_word(words: list[str], names: tuple[str, ...]) -> int:
    """The index of the first word that is one of NAMES, by any path, or -1."""
    for k, w in enumerate(words):
        if w.rsplit("/", 1)[-1] in names:
            return k
    return -1


def simulates(words: list[str], src: str) -> bool:
    for w in words:
        if w.split("=", 1)[0] in SIMULATE_LONG:
            return True
        if re.fullmatch(r"-[A-Za-z]+", w) and "s" in w[1:]:
            return True
    return bool(SIMULATE_OPT.search(src))


def scan(scripts: dict[str, str]) -> list[str]:
    """`<file>:<line>: <command>` for each apt-get or apt simulation that
    carries the planner option neither itself nor through every definition
    of an array it expands."""
    rows = {name: logical_lines_of(body) for name, body in scripts.items()}
    defs = arrays(rows)
    # An array carries the option when each of its definitions does, itself
    # or through an array it expands: to a fixed point.
    carries: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, bodies in defs.items():
            if name not in carries and all(
                carries_planner(b) or any(u in carries for u in ARRAY_USE.findall(b))
                for b in bodies
            ):
                carries.add(name)
                changed = True
    missing = []
    for name, lines in rows.items():
        for n, code, raw in lines:
            for cmd, src in commands(code, raw):
                words = cmd.split()
                k = apt_word(words, ("apt-get", "apt"))
                if k < 0 or not simulates(words[k + 1 :], src):
                    continue
                if carries_planner(src) or any(
                    u in carries for u in ARRAY_USE.findall(src)
                ):
                    continue
                missing.append(f"{name}:{n}: {src.strip()}")
    return missing


def scan_cache(scripts: dict[str, str]) -> list[str]:
    """`<file>:<line>: <command>` for each apt-cache call that passes the
    cache blanks neither itself nor through PRUNE_CACHE_OPTS."""
    missing = []
    for name, body in scripts.items():
        for n, code, raw in logical_lines_of(body):
            for cmd, src in commands(code, raw):
                if apt_word(cmd.split(), ("apt-cache",)) < 0:
                    continue
                if all(b in src for b in CACHE_BLANKS):
                    continue
                if "PRUNE_CACHE_OPTS" in ARRAY_USE.findall(src):
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


def test_every_prune_apt_cache_read_passes_the_cache_blanks():
    """apt-cache as root rebuilds a stale pkgcache.bin (CR 2824), so each
    one the prune scripts run passes PRUNE_CACHE_OPTS, which carries both
    blanks as root."""
    scripts = the_scripts()
    prune = {k: scripts[k] for k in PRUNE_SCRIPTS}
    assert not scan_cache(prune), scan_cache(prune)
    found = scan_cache(
        {k: v.replace("PRUNE_CACHE_OPTS", "X") for k, v in prune.items()}
    )
    assert any(f.startswith("prune-plan.sh:") for f in found), found
    rows = {k: logical_lines_of(v) for k, v in prune.items()}
    defs = arrays(rows)["PRUNE_CACHE_OPTS"]
    assert any(all(b in d for b in CACHE_BLANKS) for d in defs), defs


# Each is a simulation that leaves the planner log to apt: the scan must name
# it (CR 2823).
PLANTED = {
    "plain": "apt-get -s autoremove",
    "capture": "capture x apt-get -s autoremove",
    "as_root": "capture x as_root apt-get -s autoremove",
    "command substitution": "x=$(apt-get -s autoremove)",
    "quoted substitution": 'x="$(apt-get -s autoremove)"',
    "local quoted substitution": 'local x="$(as_root apt-get -s autoremove)"',
    "backticks": "x=`apt-get -s autoremove`",
    "backticks in quotes": 'x="`apt-get -s autoremove`"',
    "here-string": 'grep x <<<"$(apt-get -s autoremove)"',
    "process substitution": "while read l; do :; done < <(apt-get -s autoremove)",
    "pipeline": "apt-get -s autoremove | grep Remv",
    "after ;": "true; apt-get -s autoremove",
    "after &&": "true && apt-get -s autoremove",
    "if": "if apt-get -s autoremove; then :; fi",
    "braces": "{ apt-get -s autoremove; }",
    "continuation": "capture x apt-get \\\n  -s autoremove",
    "-qs": "apt-get -qs autoremove",
    "-sq": "apt-get -sq autoremove",
    "-yqs": "apt-get -yqs autoremove",
    "--simulate": "apt-get --simulate autoremove",
    "--dry-run": "apt-get --dry-run autoremove",
    "--simulate=": "apt-get --simulate=true autoremove",
    "apt -s": "apt -s autoremove",
    "a path": "/usr/bin/apt-get -s autoremove",
    "command": "command apt-get -s autoremove",
    "Simulate=true": "apt-get -o APT::Get::Simulate=true autoremove",
    "a comment names it": f"capture x apt-get -s autoremove  # not -o {PLANNER}",
    "a word that isn't -o": f'X="{PLANNER}" apt-get -s autoremove',
    "a longer value": f'capture x apt-get -s autoremove "-o {PLANNER}x"',
    "overridden later": f"apt-get -s -o {PLANNER} -o Dir::Log::Planner=/var/log/x remove",
    "an empty definition": f'Q=(-o {PLANNER})\nQ=()\napt-get -s "${{Q[@]}}" autoremove',
    "a self-reference": f'U=(-o {PLANNER})\nU=("${{U[@]:1}}")\napt-get -s "${{U[@]}}" x',
    "an array without it": 'B=(-o Debug::NoLocking=1)\napt-get -s "${B[@]}" x',
    "a bare array": 'B=(apt-get -s)\ncapture z "${B[@]}" purge x',
    "after a heredoc": "cat <<EOF\nhi\nEOF\napt-get -s autoremove",
    "after an escaped quote": 'echo "a \\" b"; apt-get -s autoremove',
    "after a # in a word": "x=a#b apt-get -s autoremove",
    "after $#": "echo $# ; apt-get -s autoremove",
}

# Each isn't one, or carries the option: the scan must pass it.
CLEAN = {
    "a comment": "# apt-get -s autoremove",
    "a trailing comment": "x=1  # apt-get -s here too",
    "a message": 'fail "apt-get -s dist-upgrade failed: nothing was held"',
    "a single-quoted message": "echo 'apt-get -s autoremove'",
    "a message over two lines": 'msg="a message over\ntwo lines: apt-get -s remove"',
    "a heredoc's help": "cat <<'USAGE'\n  apt-get -s autoremove\nUSAGE",
    "no simulation": "apt-get purge -y x",
    "the option": f"capture x apt-get -s -o {PLANNER} autoremove",
    "the option quoted": f'capture x apt-get -s -o "{PLANNER}" autoremove',
    "the option on the next line": f"capture x apt-get -s \\\n  -o {PLANNER} x",
    "-qs with it": f"apt-get -qs -o {PLANNER} autoremove",
    "in a substitution with it": f'x="$(apt-get -s -o {PLANNER} autoremove)"',
    "through an array": f'OK=(-o {PLANNER})\napt-get -s "${{OK[@]}}" autoremove',
    "through [*]": f"OK=(-o {PLANNER})\napt-get -s ${{OK[*]}} autoremove",
    "through two arrays": f'OK=(-o {PLANNER})\nW=(as_root apt-get -s "${{OK[@]}}")\ncapture x "${{W[@]}}" install',
    "an optional array": f'OK=(-o {PLANNER})\napt-get -s ${{OK[@]+"${{OK[@]}}"}} x',
}


def test_the_scan_names_every_planted_simulation():
    escaped = [k for k, body in PLANTED.items() if not scan({"t.sh": body})]
    assert not escaped, escaped


def test_the_scan_passes_what_isnt_one_or_carries_the_option():
    named = {k: scan({"t.sh": body}) for k, body in CLEAN.items()}
    assert not {k: v for k, v in named.items() if v}, named


def test_the_cache_scan_names_a_bare_apt_cache():
    assert scan_cache({"t.sh": "capture x apt-cache rdepends --installed bash"})
    assert scan_cache({"t.sh": 'x="$(/usr/bin/apt-cache policy bash)"'})
    assert not scan_cache(
        {"t.sh": 'apt-cache ${PRUNE_CACHE_OPTS[@]+"${PRUNE_CACHE_OPTS[@]}"} show x'}
    )
    assert not scan_cache({"t.sh": 'echo "apt-cache rdepends failed"'})
