"""Postgres: one async connection pool, and the schema."""

from pathlib import Path

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app import config

SCHEMA = Path(__file__).with_name("schema.sql")

# Any fixed number works: it names the lock that apply_schema takes.
_SCHEMA_LOCK = 4242


async def open_pool(url: str | None = None, max_size: int = 10) -> AsyncConnectionPool:
    """Open a pool whose rows come back as dicts. Waits until the first connection works."""
    pool = AsyncConnectionPool(
        url or config.database_url(),
        max_size=max_size,
        kwargs={"row_factory": dict_row},
        open=False,
    )
    await pool.open(wait=True)
    return pool


async def apply_schema(conn: AsyncConnection) -> None:
    """Create every table, index and trigger that is missing. Safe to run again.

    Two processes creating the same tables at the same moment fail (the spike hit UniqueViolation),
    so this takes an advisory lock first: a second caller waits, then finds everything in place.
    """
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK,))
        await conn.execute(SCHEMA.read_text())
