"""Read a repo's Dependabot surface: phases 1 and 2 of adopting-dependabot (#376).

Run through inventory.sh, which picks an interpreter with PyYAML. Reads only
committed files (``git ls-files``) and, with ``--upstream``, each action's
tags through ``git ls-remote``. Writes nothing. JSON on stdout, diagnostics
on stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

import tomllib
import yaml

# Directories that are never the repo's own manifests, when git can't list.
GIT_LOCATION = {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"}
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "skills-vendor",
    "__pycache__",
    ".worktrees",
}

GENERATED = re.compile(
    r"(?i)\b(generated|rendered)\s+(by|from|with)\b|\bdo\s+not\s+(hand[- ])?edit\b|@generated"
)
USES_LINE = re.compile(r"""^\s*(?:-\s+)?uses:\s*["']?([^\s"'#]+)["']?(.*)$""")
VERSION_COMMENT = re.compile(r"#\s*(v?\d+(?:\.\d+){0,2})\b")
SHA = re.compile(r"^[0-9a-f]{40}$")
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
MAJOR = re.compile(r"^v?(\d+)$")
MINOR = re.compile(r"^v?(\d+)\.(\d+)$")
SECRET_REF = re.compile(r"\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)")
VAR_REF = re.compile(r"\bvars\.([A-Za-z_][A-Za-z0-9_]*)")
INDEX_RUN = re.compile(
    r"--find-links|--index-url|--extra-index-url|\bUV_(?:EXTRA_)?INDEX(?:_URL)?\b|"
    r"\bUV_FIND_LINKS\b|\bPIP_(?:EXTRA_)?INDEX_URL\b|wheelhouse",
    re.I,
)
REQ_INDEX = re.compile(
    r"^\s*(-f|--find-links|-i|--index-url|--extra-index-url)[\s=]+(\S+)"
)
REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def tracked_files(root: Path) -> list[str]:
    """Committed paths, POSIX-relative. Falls back to a walk outside git."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
            # An inherited GIT_DIR outranks -C: under a hook it names another repo.
            env={k: v for k, v in os.environ.items() if k not in GIT_LOCATION},
        ).stdout
        return sorted(p for p in out.decode().split("\0") if p)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(
            f"inventory: git ls-files failed ({exc}); walking the tree", file=sys.stderr
        )
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            found.append(Path(dirpath, name).relative_to(root).as_posix())
    return sorted(found)


def dependabot_dir(path: str) -> str:
    """The directory Dependabot names for a file: ``/`` or ``/sub/dir``."""
    parent = PurePosixPath(path).parent.as_posix()
    return "/" if parent == "." else f"/{parent}"


def is_workflow(path: str) -> bool:
    p = PurePosixPath(path)
    return p.parent.as_posix() == ".github/workflows" and p.suffix in {".yml", ".yaml"}


# --- ecosystems ---------------------------------------------------------------


def ecosystems(files: list[str]) -> list[dict]:
    present = set(files)
    found: dict[tuple[str, str], list[str]] = {}

    def add(eco: str, directory: str, evidence: str) -> None:
        found.setdefault((eco, directory), []).append(evidence)

    for f in files:
        p = PurePosixPath(f)
        name, d = p.name, dependabot_dir(f)
        if is_workflow(f):
            add("github-actions", "/", f)
        elif name in {"action.yml", "action.yaml"}:
            add("github-actions", d, f)
        elif name == "uv.lock":
            add("uv", d, f)
        elif (
            name == "pyproject.toml"
            and (p.parent / "uv.lock").as_posix() not in present
        ):
            add("pip", d, f)
        elif re.fullmatch(r"requirements[\w.-]*\.(txt|in)", name) or name in {
            "Pipfile",
            "poetry.lock",
        }:
            add("pip", d, f)
        elif name == "package.json":
            add("npm", d, f)
        elif name == "composer.json":
            add("composer", d, f)
        elif re.fullmatch(r"(.+\.)?Dockerfile(\..+)?|Containerfile", name):
            add("docker", d, f)
        elif re.fullmatch(r"(docker-)?compose(\.[\w-]+)?\.ya?ml", name):
            add("docker-compose", d, f)
        elif name == "go.mod":
            add("gomod", d, f)
        elif name == "Cargo.toml":
            add("cargo", d, f)
        elif name == "Gemfile":
            add("bundler", d, f)
        elif p.suffix == ".tf":
            add("terraform", d, f)
        elif name == ".pre-commit-config.yaml":
            add("pre-commit", d, f)
    return [
        {"ecosystem": eco, "directory": d, "evidence": ev}
        for (eco, d), ev in sorted(found.items())
    ]


# --- Python manifests -----------------------------------------------------------


def _req_name(spec: str) -> str:
    m = REQ_NAME.match(spec)
    return m.group(1) if m else spec


def python_manifests(root: Path, files: list[str]) -> dict:
    indexes, sources, exact, tables = [], [], [], []
    for f in files:
        name = PurePosixPath(f).name
        path = root / f
        if name in {"pyproject.toml", "uv.toml"}:
            try:
                doc = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError) as exc:
                print(f"inventory: {f}: unreadable TOML ({exc})", file=sys.stderr)
                continue
            uv = doc if name == "uv.toml" else doc.get("tool", {}).get("uv", {})
            for key in ("index-url", "extra-index-url", "find-links"):
                values = uv.get(key, [])
                for value in [values] if isinstance(values, str) else values:
                    indexes.append(
                        {"file": f, "kind": key, "value": value, "local": _local(value)}
                    )
            for entry in uv.get("index", []):
                url = entry.get("url", "")
                indexes.append(
                    {
                        "file": f,
                        "kind": "index",
                        "value": url,
                        "name": entry.get("name"),
                        "local": _local(url),
                    }
                )
            if uv.get("no-index"):
                indexes.append(
                    {"file": f, "kind": "no-index", "value": True, "local": True}
                )
            for pkg, src in (uv.get("sources") or {}).items():
                for one in src if isinstance(src, list) else [src]:
                    if one.get("workspace"):
                        continue
                    kind = next(
                        (k for k in ("git", "path", "url", "index") if k in one),
                        "other",
                    )
                    ref = {k: one[k] for k in ("tag", "rev", "branch") if k in one}
                    sources.append(
                        {
                            "file": f,
                            "package": pkg,
                            "kind": kind,
                            "value": one.get(kind),
                            **ref,
                        }
                    )
            if name == "pyproject.toml":
                project = doc.get("project", {})
                runtime = [
                    s for s in project.get("dependencies", []) if isinstance(s, str)
                ]
                groups = doc.get("dependency-groups", {})
                tables.append(
                    {
                        "file": f,
                        "directory": dependabot_dir(f),
                        "runtime": len(runtime),
                        "optional": sorted(project.get("optional-dependencies", {})),
                        "groups": sorted(groups),
                    }
                )
                declared = [("dependencies", s) for s in runtime]
                for extra, specs in project.get("optional-dependencies", {}).items():
                    declared += [
                        (f"optional:{extra}", s) for s in specs if isinstance(s, str)
                    ]
                for group, specs in groups.items():
                    declared += [
                        (f"group:{group}", s) for s in specs if isinstance(s, str)
                    ]
                for table, spec in declared:
                    if "==" in spec or "===" in spec:
                        exact.append(
                            {
                                "file": f,
                                "table": table,
                                "package": _req_name(spec),
                                "spec": spec,
                            }
                        )
        elif re.fullmatch(r"requirements[\w.-]*\.(txt|in)", name):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                print(f"inventory: {f}: unreadable ({exc})", file=sys.stderr)
                continue
            for line in lines:
                if m := REQ_INDEX.match(line):
                    indexes.append(
                        {
                            "file": f,
                            "kind": m.group(1),
                            "value": m.group(2),
                            "local": _local(m.group(2)),
                        }
                    )
                elif "git+" in line:
                    sources.append(
                        {
                            "file": f,
                            "package": _req_name(line),
                            "kind": "git",
                            "value": line.strip(),
                        }
                    )
                elif "==" in line and not line.lstrip().startswith("#"):
                    exact.append(
                        {
                            "file": f,
                            "table": "requirements",
                            "package": _req_name(line),
                            "spec": line.strip(),
                        }
                    )
        elif name in {"pip.conf", ".npmrc"}:
            indexes.append({"file": f, "kind": name, "value": None, "local": False})
    return {
        "private_indexes": indexes,
        "pinned_sources": sources,
        "exact_pins": exact,
        "tables": tables,
    }


def _local(value: object) -> bool:
    """A path rather than a URL: resolvable only where that path exists."""
    return isinstance(value, str) and "://" not in value


# --- workflows ------------------------------------------------------------------


def _triggers(doc: dict) -> list[str]:
    on = doc.get("on", doc.get(True))  # YAML 1.1 reads a bare `on` key as true
    if isinstance(on, str):
        return [on]
    if isinstance(on, list):
        return [str(t) for t in on]
    if isinstance(on, dict):
        return [str(t) for t in on]
    return []


def _permissions(perms: object) -> tuple[bool, list[str]]:
    """(grants an OIDC token, the scopes it grants write on)."""
    if perms == "write-all":
        return True, ["write-all"]
    if isinstance(perms, dict):
        writes = sorted(k for k, v in perms.items() if v == "write" and k != "id-token")
        return perms.get("id-token") == "write", writes
    return False, []


def _runs_on(job: dict) -> list[str]:
    value = job.get("runs-on")
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, dict):
        labels = value.get("labels", [])
        return [labels] if isinstance(labels, str) else [str(v) for v in labels]
    return []


def workflow(root: Path, f: str) -> tuple[dict, list[dict]]:
    text = (root / f).read_text(encoding="utf-8")
    lines = text.splitlines()
    generated = next((ln.strip() for ln in lines[:15] if GENERATED.search(ln)), None)
    uses = []
    for n, line in enumerate(lines, 1):
        if m := USES_LINE.match(line):
            comment = VERSION_COMMENT.search(m.group(2))
            uses.append(
                {
                    "file": f,
                    "line": n,
                    "ref": m.group(1),
                    "comment": comment.group(1) if comment else None,
                }
            )
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        print(f"inventory: {f}: unparseable YAML ({exc})", file=sys.stderr)
        return {"file": f, "error": "unparseable YAML", "generated": generated}, uses
    triggers = _triggers(doc)
    wf_oidc, wf_writes = _permissions(doc.get("permissions"))
    wf_text = json.dumps(doc.get("env", {}))
    jobs = []
    for job_id, job in (doc.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        body = json.dumps(job) + wf_text
        secrets = sorted(set(SECRET_REF.findall(body)) - {"GITHUB_TOKEN"})
        if job.get("secrets") == "inherit":
            secrets.append("inherit")
        oidc, writes = (
            _permissions(job["permissions"])
            if "permissions" in job
            else (wf_oidc, wf_writes)
        )
        steps = job.get("steps", []) or []
        index_steps = [
            s.get("name") or s.get("uses") or "run"
            for s in steps
            if isinstance(s, dict) and INDEX_RUN.search(json.dumps(s))
        ]
        jobs.append(
            {
                "id": job_id,
                "needs": "oidc" if oidc else "secret" if secrets else "nothing",
                # A reusable workflow's credentials are in the workflow it calls.
                "calls": job.get("uses") if isinstance(job.get("uses"), str) else None,
                "secrets": secrets,
                "vars": sorted(set(VAR_REF.findall(body))),
                "write_permissions": writes,
                "private_index_steps": index_steps,
                "runs_on": _runs_on(job),
            }
        )
    gates_pr = any(t in {"pull_request", "pull_request_target"} for t in triggers)
    scheduled_only = bool(triggers) and set(triggers) <= {
        "schedule",
        "workflow_dispatch",
    }
    return {
        "file": f,
        "triggers": triggers,
        "gates_pull_request": gates_pr,
        "scheduled_only": scheduled_only,
        "generated": generated,
        "jobs": jobs,
    }, uses


NEEDS_RANK = ["nothing", "secret", "oidc"]


def resolve_calls(workflows: list[dict]) -> None:
    """A job calling a reusable workflow needs what the called one's jobs need.

    A local call (``./.github/workflows/x.yml``) takes the strongest ``needs``
    among that workflow's jobs, and its own; a call to another repo reads
    ``unknown``, since its credentials can't be read from here.
    """
    by_file = {w["file"]: w for w in workflows}

    def needs_of(job: dict, seen: frozenset[str]) -> str:
        call = job.get("calls")
        if not call:
            return job["needs"]
        if not call.startswith("./"):
            return "unknown"
        target = by_file.get(call.removeprefix("./").partition("@")[0])
        if target is None or target["file"] in seen:
            return "unknown"
        found = [needs_of(j, seen | {target["file"]}) for j in target.get("jobs", [])]
        if "unknown" in found:
            return "unknown"
        return max([job["needs"], *found], key=NEEDS_RANK.index)

    resolved = {
        (w["file"], j["id"]): needs_of(j, frozenset({w["file"]}))
        for w in workflows
        for j in w.get("jobs", [])
    }
    for w in workflows:
        for j in w.get("jobs", []):
            j["needs"] = resolved[(w["file"], j["id"])]


def pin_form(ref: str) -> tuple[str, str | None, str | None]:
    """(form, action, version) for a ``uses:`` ref."""
    if ref.startswith("./"):
        return "local", None, None
    if ref.startswith("docker://"):
        return "docker", None, None
    action_path, _, version = ref.partition("@")
    action = "/".join(action_path.split("/")[:2])
    if not version:
        return "unpinned", action, None
    if SHA.match(version):
        return "sha", action, None
    if MAJOR.match(version):
        return "major", action, version
    if MINOR.match(version):
        return "minor", action, version
    if SEMVER.match(version):
        return "exact", action, version
    return "branch", action, version


# --- upstream tags --------------------------------------------------------------


def _version(text: str | None) -> tuple[int, ...] | None:
    if not text:
        return None
    m = re.match(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$", text)
    return tuple(int(g) for g in m.groups() if g is not None) if m else None


def upstream(action: str, timeout: int) -> dict:
    url = f"https://github.com/{action}.git"
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--tags", url],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": f"git ls-remote: {exc}"}
    if proc.returncode != 0:
        return {
            "error": f"git ls-remote exited {proc.returncode}: {proc.stderr.strip()[:200]}"
        }
    commit: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        tag = ref.removeprefix("refs/tags/")
        if tag.endswith("^{}"):
            commit[tag[:-3]] = sha  # the peeled commit wins over the tag object
        else:
            commit.setdefault(tag, sha)
    releases = sorted(
        (tuple(map(int, m.groups())), t) for t in commit if (m := SEMVER.match(t))
    )
    majors = sorted(int(m.group(1)) for t in commit if (m := MAJOR.match(t)))
    return {
        "newest": releases[-1][1] if releases else None,
        "newest_version": list(releases[-1][0]) if releases else None,
        "floating_majors": majors,
        "tags": commit,
    }


def assess(ref: dict, up: dict) -> dict:
    """Where one pin stands against upstream's current tag scheme."""
    if "error" in up:
        return {"status": "unread", "why": up["error"]}
    newest = tuple(up["newest_version"] or ())
    if not newest:
        return {"status": "unread", "why": "upstream publishes no vX.Y.Z tag"}
    form, version = ref["form"], ref.get("version")
    if form in {"branch", "unpinned"}:
        # No version to compare, and nothing for Dependabot to propose.
        return {
            "status": form,
            "why": "a branch moves on its own; pin a tag or a SHA"
            if form == "branch"
            else "no @ref at all; pin a tag or a SHA",
        }
    if form == "sha":
        sha = ref["ref"].partition("@")[2]
        tagged = sorted(
            (tuple(map(int, m.groups())), t)
            for t, c in up["tags"].items()
            if c == sha and (m := SEMVER.match(t))
        )
        # The newest release at this SHA reads truer than a `# v4` comment.
        version = tagged[-1][1] if tagged else ref.get("comment")
        if version is None:
            return {
                "status": "unknown",
                "why": "no version comment, and no tag points at this SHA",
            }
        if ref.get("comment") and ref["comment"] not in up["tags"]:
            return {
                "status": "missing",
                "why": f"the comment's {ref['comment']} is no tag upstream",
            }
        if ref.get("comment") and up["tags"].get(ref["comment"]) != sha:
            return {
                "status": "mismatch",
                "why": f"{ref['comment']} upstream is not this SHA",
            }
    elif version not in up["tags"]:
        return {"status": "missing", "why": f"{version} is no tag upstream"}
    pinned = _version(version) or ()
    if form == "major":
        if pinned[0] >= newest[0]:
            return {"status": "current"}
        top = max(up["floating_majors"], default=None)
        if newest[0] not in up["floating_majors"]:
            return {
                "status": "frozen",
                "why": f"upstream's newest is {up['newest']} but its newest floating major tag is "
                f"v{top}: a major-form pin is proposed no further (#376 failure 13)",
            }
        return {
            "status": "behind",
            "why": f"v{newest[0]} exists; Dependabot should propose it",
        }
    padded = pinned + (0,) * (3 - len(pinned))
    if form == "minor":
        padded = pinned + (newest[2] if pinned[:2] == newest[:2] else 0,)
    found = (
        {"status": "current"}
        if padded >= newest
        else {"status": "behind", "why": f"newest is {up['newest']}"}
    )
    return {**found, "version": version} if form == "sha" else found


# --- main -----------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(prog="inventory.sh", add_help=False)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--upstream", action="store_true")
    ap.add_argument("--timeout", type=int, default=20)
    args = ap.parse_args()
    root = Path(args.repo_root).resolve()
    if not root.is_dir():
        print(f"inventory: {root} is not a directory", file=sys.stderr)
        return 2
    files = tracked_files(root)

    workflows, refs = [], []
    for f in files:
        if is_workflow(f) or PurePosixPath(f).name in {"action.yml", "action.yaml"}:
            wf, uses = workflow(root, f)
            if is_workflow(f):
                workflows.append(wf)
            refs.extend(uses)
    for r in refs:
        r["form"], r["action"], r["version"] = pin_form(r["ref"])
    resolve_calls(workflows)

    actions = sorted({r["action"] for r in refs if r["action"]})
    if args.upstream:
        cache = {a: upstream(a, args.timeout) for a in actions}
        for r in refs:
            if r["action"]:
                r.update(assess(r, cache[r["action"]]))
        upstream_out = {
            a: {k: v for k, v in up.items() if k != "tags"} for a, up in cache.items()
        }
    else:
        upstream_out = None

    labels: dict[str, list[str]] = {}
    for wf in workflows:
        for job in wf.get("jobs", []):
            for label in job["runs_on"]:
                labels.setdefault(label, []).append(f"{wf['file']}:{job['id']}")

    config = next(
        (
            f
            for f in (".github/dependabot.yml", ".github/dependabot.yaml")
            if f in files
        ),
        None,
    )
    out = {
        "repo_root": str(root),
        "dependabot_config": config,
        "ecosystems": ecosystems(files),
        "workflows": workflows,
        "actions": {
            "distinct": actions,
            "count": len(actions),
            "refs": refs,
        },
        "runner_labels": [
            {"label": label, "floating": label.endswith("-latest"), "jobs": jobs}
            for label, jobs in sorted(labels.items())
        ],
        **python_manifests(root, files),
        "upstream": upstream_out,
    }
    json.dump(out, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
