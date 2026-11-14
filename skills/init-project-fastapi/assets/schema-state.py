"""The database's Alembic revision against this code's head (status R8, archiver#330).

Exit codes: 0 current or ahead, 3 behind or unmigrated, 2 anything else. Never 1,
which Python uses for an uncaught exception. Read by the deploy's migrate hook:
it upgrades on 3 and skips on ahead, since an expand-only schema serves older code.
"""

import argparse
import asyncio
import enum
import sys
from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from src.core.config import get_database_url
from src.core.db_safety import assert_database_safety

#: The release (or checkout) root: this module sits at <root>/src/core/.
ROOT = Path(__file__).resolve().parents[2]
#: A Postgres that hangs rather than refuses would stall the deploy for 60 s.
CONNECT_TIMEOUT_SECONDS = 10
EXIT_OK, EXIT_ERROR, EXIT_BEHIND = 0, 2, 3


class SchemaState(enum.Enum):
    CURRENT = "current"
    BEHIND = "behind"
    AHEAD = "ahead"
    UNMIGRATED = "unmigrated"

    @property
    def can_serve(self) -> bool:
        """`ahead` serves too: by the expand-only rule, older code runs on a newer schema."""
        return self in (SchemaState.CURRENT, SchemaState.AHEAD)


def code_head(script: ScriptDirectory) -> str:
    """The code's single Alembic head; more than one has no 'behind'."""
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected one Alembic head, found {sorted(heads)}")
    return heads[0]


def classify(
    db_revision: str | None,
    *,
    head: str,
    known: frozenset[str],
) -> SchemaState:
    """Pure: the state of a database at `db_revision` for code at `head`."""
    if db_revision is None:
        return SchemaState.UNMIGRATED
    if db_revision == head:
        return SchemaState.CURRENT
    return SchemaState.BEHIND if db_revision in known else SchemaState.AHEAD


async def database_revision(conn: AsyncConnection) -> str | None:
    """The database's revision, or None with no version table (to_regclass never raises)."""
    table = await conn.execute(text("SELECT to_regclass('alembic_version')"))
    if table.scalar() is None:
        return None
    version = await conn.execute(text("SELECT version_num FROM alembic_version"))
    return version.scalar()


async def probe(url: str) -> tuple[SchemaState, str | None, str]:
    script = ScriptDirectory(str(ROOT / "alembic"))
    head = code_head(script)
    known = frozenset(rev.revision for rev in script.walk_revisions())
    engine = create_async_engine(url, connect_args={"timeout": CONNECT_TIMEOUT_SECONDS})
    try:
        async with engine.connect() as conn:
            rev = await database_revision(conn)
    finally:
        await engine.dispose()
    return classify(rev, head=head, known=known), rev, head


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m src.core.schema_state").parse_args(argv)
    try:
        assert_database_safety()
        state, rev, head = asyncio.run(probe(get_database_url()))
    except Exception as e:  # every failure is exit 2, named on stderr
        print(f"schema_state: {e}", file=sys.stderr)
        return EXIT_ERROR
    print(f"{state.value} database={rev or '-'} code={head}")
    return EXIT_OK if state.can_serve else EXIT_BEHIND


if __name__ == "__main__":
    sys.exit(main())
