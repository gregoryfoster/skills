"""The schema check's classification (src/core/schema_state.py): no database needed."""

import pytest

from src.core.schema_state import SchemaState, classify

KNOWN = frozenset({"base", "head"})


@pytest.mark.parametrize(
    ("db_revision", "state"),
    [
        (None, SchemaState.UNMIGRATED),
        ("head", SchemaState.CURRENT),
        ("base", SchemaState.BEHIND),
        ("from-a-newer-release", SchemaState.AHEAD),
    ],
)
def test_classify(db_revision, state):
    assert classify(db_revision, head="head", known=KNOWN) is state


def test_only_current_and_ahead_serve():
    assert {s for s in SchemaState if s.can_serve} == {
        SchemaState.CURRENT,
        SchemaState.AHEAD,
    }
