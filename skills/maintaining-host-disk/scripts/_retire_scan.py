"""_retire_scan.py — find a host's own disk tooling from the retire list (#425).

Run by retire-check.sh, which documents it; not meant to be run directly. It
reads unit files, drop-ins and crontabs under a root and changes nothing.
"""

import argparse
import json
import os
import re
import shlex
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
TOKENS = {(repo, entry): tokens for repo, entry, tokens in RETIRE_LIST}
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


def unit_dirs(root):
    """(scope, absolute dir, relative dir, local) for every unit directory."""
    out = []
    for rel in SYSTEM_DIRS:
        out.append(("system", os.path.join(root, rel), rel, rel in LOCAL_DIRS))
    out.append(
        ("user", os.path.join(root, "etc/systemd/user"), "etc/systemd/user", True)
    )
    homes = [("root", "root")]
    home_base = os.path.join(root, "home")
    if os.path.isdir(home_base):
        homes += [(name, f"home/{name}") for name in listdir(home_base)]
    for user, home in homes:
        rel = f"{home}/.config/systemd/user"
        out.append((f"user:{user}", os.path.join(root, rel), rel, True))
    return [d for d in out if os.path.isdir(d[1])]


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
)
URL = re.compile(
    r"(?i)\b([a-z][a-z0-9+.-]*://)(?:[^/@\s'\"]*@)?([^/\s'\"?#]+)([^\s'\"]*)"
)


def redact(command):
    """The command with secrets masked: NAME=value and --name value where the
    name says token, key, secret, pass or auth; an Authorization header; and
    a URL's userinfo, path and query (its host stays, to say what it was)."""
    for pattern, repl in REDACTIONS:
        command = pattern.sub(repl, command)
    return URL.sub(
        lambda m: m.group(1) + m.group(2) + ("/<redacted>" if m.group(3) else ""),
        command,
    )


def basenames(command):
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    return {os.path.basename(w.lstrip("@-:+!")) for w in words}


def match(names):
    return [(repo, entry) for repo, entry, tokens in RETIRE_LIST if set(tokens) & names]


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
    units, dirs = {}, {}
    for scope, absdir, reldir, local in unit_dirs(root):
        dirs.setdefault(scope, []).append((absdir, reldir))
        for name in listdir(absdir):
            if not name.endswith((".service", ".timer")):
                continue
            full = os.path.join(absdir, name)
            if (scope, name) in units or not os.path.isfile(full):
                continue
            units[(scope, name)] = {
                "scope": scope,
                "unit": name,
                "where": f"{reldir}/{name}",
                "local": local,
                "text": read(full),
            }
    for (scope, name), unit in units.items():
        chosen = {}
        for absdir, reldir in dirs[scope]:
            dropdir = os.path.join(absdir, f"{name}.d")
            if not os.path.isdir(dropdir):
                continue
            for conf in listdir(dropdir):
                if conf.endswith(".conf") and conf not in chosen:
                    chosen[conf] = (
                        f"{reldir}/{name}.d/{conf}",
                        read(os.path.join(dropdir, conf)),
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
    user = scope.split(":", 1)[1]
    home = "root" if user == "root" else f"home/{user}"
    return [os.path.join(root, home, ".config/systemd/user")]


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


def scan_cron(root):
    """(where, command) for each cron line and each run-parts script."""
    out = []
    files = ["etc/crontab"]
    for d in ("etc/cron.d", "var/spool/cron/crontabs"):
        full = os.path.join(root, d)
        if os.path.isdir(full):
            files += [f"{d}/{n}" for n in listdir(full)]
    for rel in files:
        text = read(os.path.join(root, rel))
        for lineno, line in enumerate((text or "").splitlines(), 1):
            if (
                line.strip()
                and not line.lstrip().startswith("#")
                and "=" not in line.split()[0]
            ):
                out.append((f"{rel}:{lineno}", line.strip()))
    for period in ("hourly", "daily", "weekly", "monthly"):
        d = f"etc/cron.{period}"
        full = os.path.join(root, d)
        if os.path.isdir(full):
            out += [(f"{d}/{n}", f"{d}/{n}") for n in listdir(full)]
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


def gc_report(args, root):
    if args.gc_report:
        text = read(args.gc_report)
        if text is None:
            print(f"retire-check: can't read {args.gc_report}", file=sys.stderr)
            sys.exit(2)
        return {
            "file": args.gc_report,
            "exit": None,
            "lines": text.splitlines()[:REPORT_LINES],
        }
    if args.run_gc_report:
        gc = os.path.join(root, GC_DIR, "disk-gc")
        run = subprocess.run(
            [args.python, "-I", gc, "gc"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return {
            "file": None,
            "exit": run.returncode,
            "lines": run.stdout.splitlines()[:REPORT_LINES],
        }
    return None


def main():
    ap = argparse.ArgumentParser(prog="_retire_scan.py")
    ap.add_argument("--root", default="/")
    ap.add_argument("--gc-report")
    ap.add_argument("--run-gc-report", action="store_true")
    ap.add_argument("--python", default="/usr/bin/python3")
    args = ap.parse_args()
    root = os.path.abspath(args.root)

    units = scan_units(root)
    found, candidates, matched = [], [], set()
    for (scope, name), unit in sorted(units.items()):
        if name.startswith(CANONICAL):
            continue
        commands = exec_lines(unit) if name.endswith(".service") else []
        names = {name.rsplit(".", 1)[0]}
        for _where, cmd in commands:
            names |= basenames(cmd)
        hits = match(names)
        for repo, entry in hits:
            tokens = set(TOKENS[(repo, entry)])
            where, cmd = next(
                ((w, c) for w, c in commands if tokens & basenames(c)),
                commands[0] if commands else (unit["where"], ""),
            )
            word = sorted(tokens & (basenames(cmd) | {name.rsplit(".", 1)[0]}))[0]
            timer = timer_for(units, scope, name) if name.endswith(".service") else None
            dirs = scope_dirs(root, scope)
            enabled = wanted(root, dirs, name) or bool(
                timer and wanted(root, dirs, timer)
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
    for where, line in scan_cron(root):
        hits = match(basenames(line))
        for repo, entry in hits:
            word = sorted(set(TOKENS[(repo, entry)]) & basenames(line))[0]
            found.append(
                {
                    "repo": repo,
                    "entry": entry,
                    "kind": "cron",
                    "scope": "cron",
                    "unit": None,
                    "timer": None,
                    "enabled": True,
                    "match": word,
                    "where": where,
                    "command": redact(line),
                }
            )
        if not hits and LOOKALIKE.search(line):
            candidates.append(
                {
                    "kind": "cron",
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
