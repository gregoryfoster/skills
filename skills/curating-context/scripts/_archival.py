#!/usr/bin/env python3
"""Which files are dated history: `_context-lib.sh`'s ctx_is_archival, in Python.

Import it; don't run it. Stdlib only, Python 3.9+. #463 wrote it inside
`_stale_issue_prose.py`; #441 moved it here when a second pass needed it,
so the skill keeps one Python matcher rather than one per pass.

A path is archival when any component of it, relative to the repo root, is
one of the names in CTX_ARCHIVAL, read the library's way: unset or empty means
ARCHIVAL_DEFAULT. Phase 1 takes `measure-context.sh --archival` instead, so a
custom list goes to both.
"""

from __future__ import annotations

import os
from pathlib import Path

# `_context-lib.sh`'s CTX_ARCHIVAL_DEFAULT, held to it (and to
# measure-context.sh's copy) by a parity test, so the defaults can't drift
# (#463). An overridden list still can: CTX_ARCHIVAL moves the passes, while
# Phase 1 takes measure-context.sh --archival.
ARCHIVAL_DEFAULT = "plans specs research audits archive"


def archival_names(environ=None) -> list[str]:
    """CTX_ARCHIVAL as the library reads it: `${CTX_ARCHIVAL:-default}`, split on whitespace."""
    env = os.environ if environ is None else environ
    return (env.get("CTX_ARCHIVAL") or ARCHIVAL_DEFAULT).split()


def is_archival(fname: str, root: Path, names) -> bool:
    """ctx_is_archival: any component of the root-relative path is one of `names`.

    An absolute path under the root is made relative first, so a checkout that
    happens to sit under ~/archive/ isn't all history.
    """
    path = Path(fname)
    if path.is_absolute():
        for p, r in ((path, root), (path.resolve(), root.resolve())):
            try:
                path = p.relative_to(r)
                break
            except ValueError:
                pass
    return any(part in names for part in path.parts)
