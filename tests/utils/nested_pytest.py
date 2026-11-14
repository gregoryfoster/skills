"""The environment for a pytest that a test starts (#554). Red: a passthrough."""

import os
from collections.abc import Mapping
from pathlib import Path


def nested_pytest_env(
    temp_parent: Path, base: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Today's behaviour, which the red tests measure: the caller's env as is."""
    del temp_parent
    return dict(os.environ if base is None else base)
