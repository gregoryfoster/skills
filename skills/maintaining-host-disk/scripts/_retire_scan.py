"""_retire_scan.py — find a host's own disk tooling from the retire list (#425).

Run by retire-check.sh, which documents it; not meant to be run directly. It
reads unit files, drop-ins and crontabs under a root and changes nothing.
"""

import argparse
import json
import os
import re
import stat
import subprocess
import sys

# The retire list (#425 step 1), as what a unit or cron line can be matched
# by: a script's basename, or a unit's own name. references/retiring.md
# carries the same list with what each one did; a test holds them together.
RETIRE_LIST = (
    ("wslcb", "disk_hygiene.py", ("disk_hygiene.py",)),
    ("address-validator", "disk-hygiene.sh", ("disk-hygiene.sh",)),
    ("address-validator", "docker-prune", ("docker-prune", "docker-prune.sh")),
    ("watcher", "cleanup.sh", ("cleanup.sh",)),
    ("usa-wa", "disk-gc.sh", ("disk-gc.sh",)),
    ("power-map", "prune_disk.py", ("prune_disk.py",)),
    ("power-map", "check_disk_headroom.py", ("check_disk_headroom.py",)),
    ("broker", "prune_editor_builds.sh", ("prune_editor_builds.sh",)),
)
BY_HAND = (
    (
        "observo",
        "cache timers",
        "no fixed unit or script name to match: list observo's timers and read "
        "each one's ExecStart by hand",
    ),
)

SYSTEM_DIRS = (
    "etc/systemd/system",
    "usr/local/lib/systemd/system",
    "lib/systemd/system",
    "usr/lib/systemd/system",
)
# Packaged units (lib/, usr/lib/) are matched against the list but never
# offered as lookalikes: systemd-tmpfiles-clean is not a host's own GC.
LOCAL_DIRS = ("etc/systemd/system", "usr/local/lib/systemd/system")
CANONICAL = ("cannobserv-disk-gc", "cannobserv-disk-headroom")
TIMERS = ("cannobserv-disk-gc.timer", "cannobserv-disk-headroom.timer")
GC_DIR = "usr/local/lib/cannobserv/disk-gc"
LOOKALIKE = re.compile(
    r"disk|prune|clean|hygiene|headroom|vacuum|(^|[^a-z])gc([^a-z]|$)", re.I
)
EXEC_KEYS = ("ExecStart", "ExecStartPre", "ExecStartPost", "ExecStop")
REPORT_LINES = 500
UNREADABLE = []


HOMES = {}  # user -> home, relative to the root


def homes(root):
    """(user, home relative to the root) for each account in the root's
    etc/passwd whose home is a directory there; /root and home/* when it has
    no passwd. A service account's home outside /home counts."""
    text = read(os.path.join(root, "etc/passwd"))
    if text is None:
        found = [("root", "root")]
        if os.path.isdir(os.path.join(root, "home")):
            found += [(n, f"home/{n}") for n in listdir(os.path.join(root, "home"))]
        return [(u, h) for u, h in found if os.path.isdir(os.path.join(root, h))]
    found = []
    for line in text.splitlines():
        fields = line.split(":")
        if len(fields) < 6 or not fields[5].startswith("/") or fields[5] == "/":
            continue
        home = os.path.normpath(fields[5]).lstrip("/")
        if os.path.isdir(os.path.join(root, home)) and fields[0] not in dict(found):
            found.append((fields[0], home))
    return found


USER_UNIT_DIRS = (".config/systemd/user", ".local/share/systemd/user")


def unit_dirs(root):
    """(scope, absolute dir, relative dir, local) for every unit directory,
    in systemd's order within each scope."""
    out = []
    for rel in SYSTEM_DIRS:
        out.append(("system", os.path.join(root, rel), rel, rel in LOCAL_DIRS))
    out.append(
        ("user", os.path.join(root, "etc/systemd/user"), "etc/systemd/user", True)
    )
    for user, home in homes(root):
        HOMES[user] = home
        for sub in USER_UNIT_DIRS:
            rel = f"{home}/{sub}"
            out.append((f"user:{user}", os.path.join(root, rel), rel, True))
    return [d for d in out if present(root, d[1])]


def present(root, path):
    """Whether path is a directory; one it can't reach for permission is
    recorded in UNREADABLE (its nearest ancestor the caller can't enter),
    never taken for absent: a 0700 home read as non-root otherwise reads as
    a home with no units."""
    try:
        return stat.S_ISDIR(os.stat(path).st_mode)
    except PermissionError:
        blocked = path
        parent = os.path.dirname(path)
        while parent.startswith(root) and parent != root:
            if os.path.isdir(parent) and not os.access(parent, os.R_OK | os.X_OK):
                blocked = parent
            parent = os.path.dirname(parent)
        UNREADABLE.append(blocked)
        return False
    except OSError:
        return False


def in_root(root, path, hops=8):
    """path with its links followed as they would be with `root` as /: an
    absolute target is taken under the root, and one that climbs out of it
    is not followed (None). Under --root / that is ordinary resolution."""
    root = os.path.abspath(root)
    for _ in range(hops):
        if not os.path.islink(path):
            break
        target = os.readlink(path)
        if target.startswith("/"):
            path = os.path.join(root, target.lstrip("/"))
        else:
            path = os.path.join(os.path.dirname(path), target)
        path = os.path.normpath(path)
        if root != "/" and not (path == root or path.startswith(root + os.sep)):
            return None
    else:
        return None
    return path


def listdir(path):
    """A directory's names, sorted, or none where it can't be read: a home
    unreadable to a non-root caller is skipped, and `unreadable` says so."""
    try:
        return sorted(os.listdir(path))
    except OSError:
        if os.path.isdir(path):
            UNREADABLE.append(path)
        return []


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def directives(text):
    """(key, value, line number) triples, a continued line joined onto the
    line it starts on."""
    out = []
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        start, line = i + 1, lines[i]
        while line.endswith("\\") and i + 1 < len(lines):
            i += 1
            line = line[:-1] + " " + lines[i]
        i += 1
        line = line.strip()
        if not line or line[0] in "#;[" or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out.append((key.strip(), value.strip(), start))
    return out


# What a printed command may not carry (#425: no secrets on an issue).
SECRET_WORD = r"[A-Za-z0-9_.-]*(?:token|key|secret|pass|auth)[A-Za-z0-9_.-]*"
QUOTED_OR_WORD = r"(?:\"[^\"]*\"|'[^']*'|[^\s'\"]+)"
REDACTIONS = (
    (
        re.compile(rf"(?i)(?<![A-Za-z0-9_])((?:--?)?{SECRET_WORD})={QUOTED_OR_WORD}"),
        r"\1=<redacted>",
    ),
    (
        re.compile(rf"(?i)(?<![A-Za-z0-9_])(--{SECRET_WORD})\s+(?!-){QUOTED_OR_WORD}"),
        r"\1 <redacted>",
    ),
    (re.compile(r"(?i)(authorization:\s*)[^'\"\n]*"), r"\1<redacted>"),
    # Any other header whose name says it: X-Api-Key, X-Auth-Token, ...
    (
        re.compile(
            r"(?i)(?<![A-Za-z0-9_-])([A-Za-z0-9_-]*(?:token|key|secret|auth|pass)"
            r"[A-Za-z0-9_-]*:\s*)[^'\"\n]+"
        ),
        r"\1<redacted>",
    ),
    # curl -u / --user user:pass
    (
        re.compile(
            r"(?<![\w-])(-u|--user)(=|\s+)(\"[^\"]*:[^\"]*\"|'[^']*:[^']*'"
            r"|[^\s'\";&|]*:[^\s'\";&|]*)"
        ),
        r"\1\2<redacted>",
    ),
    # A JSON body's "token": "..." and the like
    (
        re.compile(rf'(?i)("{SECRET_WORD}"\s*:\s*)"[^"]*"'),
        r'\1"<redacted>"',
    ),
)
# Flags that are a password only to their own command: mysql*'s -pPASS
# and redis-cli's -a PASS.
BY_COMMAND = (
    (
        re.compile(r"mysql\w*\Z"),
        re.compile(r"(?<=\s)-p(?=[^\s'\"])[^\s'\"]+"),
        "-p<redacted>",
    ),
    (re.compile(r"redis-cli\Z"), re.compile(r"(?<=\s)-a\s+[^\s'\"]+"), "-a <redacted>"),
)


def redact_by_command(command):
    parts = re.split(r"([;&|]+)", command)
    for i, part in enumerate(parts):
        names = {os.path.basename(w.strip("'\"")) for w in part.split()}
        for name_re, flag_re, repl in BY_COMMAND:
            if any(name_re.match(n) for n in names):
                parts[i] = flag_re.sub(repl, parts[i])
    return "".join(parts)


URL = re.compile(
    r"(?i)\b([a-z][a-z0-9+.-]*://)(?:[^/@\s'\"]*@)?([^/\s'\"?#]+)([^\s'\"]*)"
)


def redact(command):
    """The command with secrets masked, best-effort: NAME=value and --name
    value where the name says token, key, secret, pass or auth; any header
    so named, Authorization included; curl's -u/--user user:pass; a JSON
    "token": "..."; mysql*'s -pPASS and redis-cli's -a PASS; and a URL's
    userinfo, path and query (its host stays, to say what it was)."""
    command = redact_by_command(command)
    for pattern, repl in REDACTIONS:
        command = pattern.sub(repl, command)
    return URL.sub(
        lambda m: m.group(1) + m.group(2) + ("/<redacted>" if m.group(3) else ""),
        command,
    )


# A token is a whole word of a command: after a path separator, and with
# a space, a quote, a backtick or one of ;&|()<> on each side. That finds
# it inside `sh -c "..."` and before a redirect, and not inside a longer
# name.
TOKEN_RES = {
    tok: re.compile(r"(^|[/\s'\"`;&|()<>])" + re.escape(tok) + r"($|[\s'\"`;&|()<>])")
    for _repo, _entry, tokens in RETIRE_LIST
    for tok in tokens
}


def match(command, stem=None):
    """(repo, entry, word) for each entry a command, or a unit's own name
    `stem`, matches."""
    hits = []
    for repo, entry, tokens in RETIRE_LIST:
        words = [t for t in tokens if TOKEN_RES[t].search(command) or t == stem]
        if words:
            hits.append((repo, entry, words[0]))
    return hits


def wanted(root, scope_dirs, unit):
    """Whether a .wants/ or .requires/ link names the unit, in its scope."""
    for base in scope_dirs:
        if not os.path.isdir(base):
            continue
        for sub in listdir(base):
            if sub.endswith((".wants", ".requires")) and os.path.lexists(
                os.path.join(base, sub, unit)
            ):
                return True
    return False


def scan_units(root):
    """Each service and timer, per scope: the file from the first directory
    that has it, then its drop-ins from every directory of that scope, in
    filename order, the first directory winning a name clash. That is
    systemd's own merge, so an /etc override (`systemctl edit`) applies to a
    unit that ships lower down, and a lower drop-in to a unit in /etc."""
    units, dirs, masked = {}, {}, set()
    for scope, absdir, reldir, local in unit_dirs(root):
        dirs.setdefault(scope, []).append((absdir, reldir))
        for name in listdir(absdir):
            if not name.endswith((".service", ".timer")):
                continue
            full = os.path.join(absdir, name)
            if (scope, name) in units:
                continue
            # A link to /dev/null masks the unit for every directory below.
            if os.path.islink(full) and os.readlink(full) == "/dev/null":
                masked.add((scope, name))
                continue
            full = in_root(root, full)
            if full is None or not os.path.isfile(full):
                continue
            units[(scope, name)] = {
                "scope": scope,
                "unit": name,
                "where": f"{reldir}/{name}",
                "local": local,
                "text": read(full),
                "masked": (scope, name) in masked,
            }
    # A user's manager reads /etc/systemd/user between ~/.config and
    # ~/.local/share: a user's drop-in on a unit there is that user's unit.
    etc_user = dirs.get("user", [])
    for scope in [s for s in dirs if s.startswith("user:")]:
        own = dirs[scope]
        config = [d for d in own if d[1].endswith(USER_UNIT_DIRS[0])]
        rest = [d for d in own if d not in config]
        dirs[scope] = config + etc_user + rest
        for (s_, name), unit in list(units.items()):
            if s_ != "user" or (scope, name) in units:
                continue
            if any(os.path.isdir(os.path.join(a, f"{name}.d")) for a, _r in own):
                units[(scope, name)] = dict(unit, scope=scope)
    for (scope, name), unit in units.items():
        chosen = {}
        for absdir, reldir in dirs[scope]:
            dropdir = os.path.join(absdir, f"{name}.d")
            if not os.path.isdir(dropdir):
                continue
            for conf in listdir(dropdir):
                if conf.endswith(".conf") and conf not in chosen:
                    real = in_root(root, os.path.join(dropdir, conf))
                    chosen[conf] = (
                        f"{reldir}/{name}.d/{conf}",
                        read(real) if real else None,
                    )
        unit["dropins"] = [chosen[c] for c in sorted(chosen)]
    return units


def exec_lines(unit):
    """The effective Exec* commands: a drop-in's empty `ExecStart=` resets
    that key, as systemd does."""
    by_key = {}
    for where, text in [(unit["where"], unit["text"])] + unit.get("dropins", []):
        for key, value, lineno in directives(text):
            if key not in EXEC_KEYS:
                continue
            if value == "":
                by_key[key] = []
            else:
                by_key.setdefault(key, []).append((f"{where}:{lineno}", value))
    return [line for key in EXEC_KEYS for line in by_key.get(key, [])]


def scope_dirs(root, scope):
    if scope == "system":
        return [os.path.join(root, "etc/systemd/system")]
    if scope == "user":
        return [os.path.join(root, "etc/systemd/user")]
    home = HOMES[scope.split(":", 1)[1]]
    return [os.path.join(root, home, sub) for sub in USER_UNIT_DIRS]


def setting(unit, key):
    """A single-valued key's effective value: the unit file, then each
    drop-in in order, the last one setting it winning."""
    value = None
    for text in [unit["text"]] + [t for _w, t in unit.get("dropins", [])]:
        for k, v, _lineno in directives(text):
            if k == key:
                value = v or None
    return value


def timer_for(units, scope, service):
    stem = service[: -len(".service")]
    for (s, name), t in units.items():
        if s != scope or not name.endswith(".timer"):
            continue
        target = setting(t, "Unit")
        if target == service or (target is None and name[: -len(".timer")] == stem):
            return name
    return None


WRAPPER_BYTES = 64 * 1024  # a cron.<period> script read for what it runs
RUN_PARTS_NAME = re.compile(r"[A-Za-z0-9_-]+\Z")


def inside(root, path):
    """Where a symlink at path points, resolved inside the root."""
    return in_root(root, path) or os.path.join(root, ".no-such-path")


def executable(path):
    """Whether run-parts, as root, would run it: a regular file with any
    execute bit. The mode, not os.access, which asks about the caller."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and bool(st.st_mode & 0o111)


def assignment(line):
    return "=" in line.split()[0] and not line.split()[0].startswith(("/", "@"))


def scan_cron(root):
    """(kind, where, command, enabled) for each crontab and anacrontab line,
    and each run-parts entry, judged by run-parts' own rules."""
    out = []
    files = ["etc/crontab"]
    for d in ("etc/cron.d", "var/spool/cron/crontabs"):
        full = os.path.join(root, d)
        if os.path.isdir(full):
            files += [f"{d}/{n}" for n in listdir(full)]
    for kind, rels in (("cron", files), ("anacron", ["etc/anacrontab"])):
        for rel in rels:
            real = in_root(root, os.path.join(root, rel))
            text = read(real) if real else None
            # Debian's cron reads /etc/cron.d by run-parts' naming rule too.
            runs = not rel.startswith("etc/cron.d/") or bool(
                RUN_PARTS_NAME.match(os.path.basename(rel))
            )
            for lineno, line in enumerate((text or "").splitlines(), 1):
                line = line.strip()
                if line and not line.startswith("#") and not assignment(line):
                    out.append((kind, f"{rel}:{lineno}", line, runs))
    for period in ("hourly", "daily", "weekly", "monthly"):
        d = f"etc/cron.{period}"
        full = os.path.join(root, d)
        if not os.path.isdir(full):
            continue
        for n in listdir(full):
            path = os.path.join(full, n)
            command, real = f"{d}/{n}", path
            if os.path.islink(path):
                command = f"{d}/{n} -> {os.readlink(path)}"
                real = inside(root, path)
            # run-parts runs only executables named [A-Za-z0-9_-]+.
            runs = bool(RUN_PARTS_NAME.match(n)) and executable(real)
            out.append(("cron", f"{d}/{n}", command, runs))
            # A wrapper script: what it runs is in its lines, not its name.
            if os.path.isfile(real) and os.path.getsize(real) <= WRAPPER_BYTES:
                for lineno, line in enumerate((read(real) or "").splitlines(), 1):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        out.append(("cron", f"{d}/{n}:{lineno}", line, runs))
    return out


def canonical(root):
    version = read(os.path.join(root, GC_DIR, "VERSION"))
    version = version.strip() if version else None
    timers = {}
    system = os.path.join(root, "etc/systemd/system")
    for t in TIMERS:
        if not os.path.isfile(os.path.join(root, "usr/local/lib/systemd/system", t)):
            timers[t] = "absent"
        else:
            timers[t] = "enabled" if wanted(root, [system], t) else "disabled"
    return {
        "installed": os.path.isfile(os.path.join(root, GC_DIR, "disk-gc")),
        "version": int(version) if version and version.isdigit() else version,
        "timers": timers,
    }


def cut(lines):
    """At most REPORT_LINES lines, saying when it cut."""
    return {
        "lines": lines[:REPORT_LINES],
        "truncated": len(lines) > REPORT_LINES,
        "total_lines": len(lines),
    }


def gc_report(args, root):
    if args.gc_report:
        text = read(args.gc_report)
        if text is None:
            usage(f"can't read {args.gc_report}")
        return {"file": args.gc_report, "exit": None, **cut(text.splitlines())}
    if not args.run_gc_report:
        return None
    gc = os.path.join(root, GC_DIR, "disk-gc")
    try:
        run = subprocess.run(
            [args.python, "-I", gc, "gc", "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=args.gc_timeout,
        )
    except subprocess.TimeoutExpired:
        return {"file": None, "exit": "timeout", "json": None, **cut([])}
    except OSError as e:
        usage(f"can't run {args.python}: {e.strerror}")
    try:
        doc = json.loads(run.stdout)
    except ValueError:
        doc = None
    lines = (run.stdout if doc is None else "").splitlines() + run.stderr.splitlines()
    return {"file": None, "exit": run.returncode, "json": doc, **cut(lines)}


def usage(why):
    print(f"retire-check: {why}", file=sys.stderr)
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser(prog="_retire_scan.py")
    ap.add_argument("--root", default="/")
    report = ap.add_mutually_exclusive_group()
    report.add_argument("--gc-report")
    report.add_argument("--run-gc-report", action="store_true")
    ap.add_argument("--python", default="/usr/bin/python3")
    ap.add_argument("--gc-timeout", type=int, default=900)
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    if args.run_gc_report and os.path.realpath(root) != "/":
        usage(
            "--run-gc-report runs the live GC, which reads the live config and "
            "/proc whatever --root says; run it with --root / (the default)"
        )

    units = scan_units(root)
    found, candidates, matched = [], [], set()
    for (scope, name), unit in sorted(units.items()):
        if name.startswith(CANONICAL):
            continue
        commands = exec_lines(unit) if name.endswith(".service") else []
        stem = name.rsplit(".", 1)[0]
        hits = {}
        for where, cmd in commands:
            for repo, entry, word in match(cmd):
                hits.setdefault((repo, entry), (word, where, cmd))
        for repo, entry, word in match("", stem):
            first = commands[0] if commands else (unit["where"], "")
            hits.setdefault((repo, entry), (word, *first))
        for (repo, entry), (word, where, cmd) in sorted(hits.items()):
            timer = timer_for(units, scope, name) if name.endswith(".service") else None
            dirs = scope_dirs(root, scope)
            # A masked timer starts nothing, whatever wants links remain.
            timer_live = bool(timer) and not units[(scope, timer)]["masked"]
            enabled = not unit["masked"] and (
                wanted(root, dirs, name) or (timer_live and wanted(root, dirs, timer))
            )
            found.append(
                {
                    "repo": repo,
                    "entry": entry,
                    "kind": "systemd",
                    "scope": scope,
                    "unit": name,
                    "timer": timer,
                    "enabled": enabled,
                    "masked": unit["masked"],
                    "match": word,
                    "where": where,
                    "command": redact(cmd),
                }
            )
            matched.add((scope, name))
            if timer:
                matched.add((scope, timer))
    for (scope, name), unit in sorted(units.items()):
        if name.startswith(CANONICAL) or (scope, name) in matched or not unit["local"]:
            continue
        lines = exec_lines(unit)
        text = " ".join(c for _w, c in lines)
        if LOOKALIKE.search(name) or LOOKALIKE.search(text):
            candidates.append(
                {
                    "kind": "systemd",
                    "scope": scope,
                    "unit": name,
                    "where": lines[0][0] if lines else unit["where"],
                    "command": redact(text),
                    "why": "its name or command looks like disk tooling; read what it removes",
                }
            )
    for kind, where, line, runs in scan_cron(root):
        hits = match(line)
        for repo, entry, word in hits:
            found.append(
                {
                    "repo": repo,
                    "entry": entry,
                    "kind": kind,
                    "scope": "cron",
                    "unit": None,
                    "timer": None,
                    "enabled": runs,
                    "masked": False,
                    "match": word,
                    "where": where,
                    "command": redact(line),
                }
            )
        if not hits and LOOKALIKE.search(line):
            candidates.append(
                {
                    "kind": kind,
                    "scope": "cron",
                    "unit": None,
                    "where": where,
                    "command": redact(line),
                    "why": "a cron line that looks like disk tooling; read what it removes",
                }
            )

    report = gc_report(args, root)
    nxt = []
    if report is None:
        nxt.append(
            "get the GC's report-only run: sudo /usr/bin/python3 -I "
            "/usr/local/lib/cannobserv/disk-gc/disk-gc gc >report.txt 2>&1, "
            "then pass --gc-report report.txt"
        )
    if UNREADABLE:
        nxt.append(
            "run it as root: some unit or cron directories couldn't be read (unreadable)"
        )
    if found or candidates:
        nxt.append(
            "for each found entry and candidate, read what it removes against the "
            "checklist in references/retiring.md before retiring it"
        )
    out = {
        "root": root,
        "canonical": canonical(root),
        "found": found,
        "candidates": candidates,
        "by_hand": [{"repo": r, "entry": e, "why": w} for r, e, w in BY_HAND],
        "gc_report": report,
        "unreadable": sorted({os.path.relpath(p, root) for p in UNREADABLE}),
        "next": nxt,
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
