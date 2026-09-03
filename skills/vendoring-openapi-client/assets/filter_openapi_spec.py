"""Filter an OpenAPI spec down to a prefix subset and prune orphan components.

Used by the vendored-client regen flow to drop producer surfaces the consumer
never calls (e.g. an ``/admin/*`` HTMX surface) before feeding the spec to
``openapi-python-client`` — generating unconsumed surface inflates the
generated tree, the PR review burden, and the dep surface for no gain.

The filter:
  1. Keeps only ``paths`` whose key starts with ``--keep-prefix`` (default
     ``/api/v1/``).
  2. Walks the surviving operations to collect every ``$ref`` (transitive
     closure across ``schemas``, ``parameters``, ``responses``,
     ``requestBodies``, ``headers``, ``links``, ``callbacks``, ``examples``,
     ``pathItems``).
  3. Scans operation-level ``security`` blocks to collect referenced
     ``securitySchemes`` (these are referenced by name, not by ``$ref``).
  4. Rebuilds ``components`` with only the reachable entries.
  5. Preserves ``openapi``, ``info``, ``servers``, ``tags``, ``security``
     (root-level) as-is.

Output is JSON with sorted keys + 2-space indent so diffs are minimal across
regens.

Usage:
    python scripts/filter_openapi_spec.py INPUT OUTPUT [--keep-prefix /api/v1/]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_REF_PATTERN = re.compile(r"^#/components/([^/]+)/([^/]+)$")

_COMPONENT_KEYS_TRAVERSED = (
    "schemas",
    "parameters",
    "responses",
    "requestBodies",
    "headers",
    "links",
    "callbacks",
    "examples",
    "pathItems",
)


def _collect_refs(node: Any, found: dict[str, set[str]]) -> None:
    """Recursively walk ``node`` collecting ``$ref`` targets into ``found``.

    ``found`` is mutated in place: ``{component_section: {name, ...}}``.
    Non-component refs (external files, JSON pointers into ``paths``) are
    ignored — FastAPI-style specs are single-file and all internal refs hit
    ``#/components/...``.
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            m = _REF_PATTERN.match(ref)
            if m:
                section, name = m.group(1), m.group(2)
                found.setdefault(section, set()).add(name)
        for value in node.values():
            _collect_refs(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, found)


def _collect_security_scheme_names(operation: dict[str, Any], found: set[str]) -> None:
    """Add operation-level ``security: [{scheme_name: []}, ...]`` names to ``found``."""
    security = operation.get("security")
    if not isinstance(security, list):
        return
    for requirement in security:
        if isinstance(requirement, dict):
            for scheme_name in requirement.keys():
                found.add(scheme_name)


def _transitive_closure(
    initial: dict[str, set[str]],
    components: dict[str, Any],
) -> dict[str, set[str]]:
    """Expand ``initial`` to include refs reachable through component bodies."""
    closure: dict[str, set[str]] = {k: set(v) for k, v in initial.items()}
    changed = True
    while changed:
        changed = False
        for section, names in list(closure.items()):
            section_body = components.get(section, {})
            if not isinstance(section_body, dict):
                continue
            for name in list(names):
                target = section_body.get(name)
                if target is None:
                    continue
                new_refs: dict[str, set[str]] = {}
                _collect_refs(target, new_refs)
                for new_section, new_names in new_refs.items():
                    bucket = closure.setdefault(new_section, set())
                    before = len(bucket)
                    bucket.update(new_names)
                    if len(bucket) > before:
                        changed = True
    return closure


def filter_spec(spec: dict[str, Any], keep_prefix: str) -> dict[str, Any]:
    """Return a new spec dict with paths filtered to ``keep_prefix`` and
    ``components`` pruned to only what the surviving paths reach.

    Pure function — does not mutate ``spec``.
    """
    paths = spec.get("paths", {})
    if not isinstance(paths, dict):
        raise ValueError("spec.paths must be an object")

    kept_paths = {p: body for p, body in paths.items() if p.startswith(keep_prefix)}
    if not kept_paths:
        raise ValueError(
            f"no paths matched keep_prefix={keep_prefix!r}; check the prefix and the input spec"
        )

    initial_refs: dict[str, set[str]] = {}
    security_scheme_names: set[str] = set()
    # Root-level ``security`` is a global default applied to every
    # operation that does not declare its own.  Collect referenced
    # scheme names from it so a spec whose operations rely entirely on
    # the global default (no per-op `security:` block) still preserves
    # its securityScheme components after filtering — producers that
    # declare security per-operation today may consolidate to a root
    # default later, and that must not silently break the filter.
    root_security = spec.get("security", [])
    if isinstance(root_security, list):
        for requirement in root_security:
            if isinstance(requirement, dict):
                for scheme_name in requirement.keys():
                    security_scheme_names.add(scheme_name)
    for path_body in kept_paths.values():
        if not isinstance(path_body, dict):
            continue
        _collect_refs(path_body, initial_refs)
        for method_key, method_body in path_body.items():
            if method_key in {
                "get",
                "post",
                "put",
                "delete",
                "patch",
                "options",
                "head",
                "trace",
            }:
                if isinstance(method_body, dict):
                    _collect_security_scheme_names(method_body, security_scheme_names)

    components = spec.get("components", {})
    if not isinstance(components, dict):
        components = {}

    closure = _transitive_closure(initial_refs, components)
    if security_scheme_names:
        closure.setdefault("securitySchemes", set()).update(security_scheme_names)

    new_components: dict[str, Any] = {}
    for section, names in closure.items():
        section_body = components.get(section)
        if not isinstance(section_body, dict):
            continue
        kept = {
            name: section_body[name] for name in sorted(names) if name in section_body
        }
        if kept:
            new_components[section] = kept

    new_spec: dict[str, Any] = {}
    for top_key in ("openapi", "info", "servers", "tags", "security"):
        if top_key in spec:
            new_spec[top_key] = spec[top_key]
    new_spec["paths"] = kept_paths
    if new_components:
        new_spec["components"] = new_components

    return new_spec


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else None
    )
    parser.add_argument("input", type=Path, help="path to raw OpenAPI spec JSON")
    parser.add_argument("output", type=Path, help="path to write filtered spec JSON")
    parser.add_argument(
        "--keep-prefix",
        default="/api/v1/",
        help="path prefix to keep (default: /api/v1/)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    raw = json.loads(args.input.read_text())
    filtered = filter_spec(raw, keep_prefix=args.keep_prefix)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(filtered, indent=2, sort_keys=True) + "\n")
    kept_path_count = len(filtered.get("paths", {}))
    comp_summary = ", ".join(
        f"{k}={len(v)}" for k, v in sorted(filtered.get("components", {}).items())
    )
    print(
        f"filtered {args.input} -> {args.output}: "
        f"paths={kept_path_count} components=({comp_summary})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
