"""LangGraph's Postgres checkpointer: the agent state after every node, so a run that dies resumes.

On resume (ainvoke(None, config) on the same thread), finished nodes don't run again; the node that
was running when the process died does. So a crash repeats at most one model call.

Only one process creates the checkpoint tables (the API, at startup), under an advisory lock:
two processes running setup() at once fail with UniqueViolation (seen in the spike).
"""

import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_SETUP_LOCK = 4243


async def setup_checkpoints(url: str) -> None:
    """Create the checkpoint tables if missing. Safe to run again, and from several processes.

    setup() builds an index with CREATE INDEX CONCURRENTLY, which waits for every open transaction.
    A process blocked in pg_advisory_lock holds one open, so waiting that way deadlocks (a test hit
    it). Instead each process polls pg_try_advisory_lock, which holds nothing while it waits.
    """
    async with await AsyncConnection.connect(
        url, autocommit=True, prepare_threshold=0, row_factory=dict_row
    ) as conn:
        while True:
            row = await (
                await conn.execute("SELECT pg_try_advisory_lock(%s) AS got", (_SETUP_LOCK,))
            ).fetchone()
            if row["got"]:
                break
            await asyncio.sleep(0.2)
        try:
            await AsyncPostgresSaver(conn).setup()
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s)", (_SETUP_LOCK,))


async def open_checkpointer(url: str, max_size: int = 10) -> tuple[AsyncPostgresSaver, AsyncConnectionPool]:
    """A checkpointer on its own pool. The saver needs autocommit connections, unlike the app's pool."""
    pool = AsyncConnectionPool(
        url,
        max_size=max_size,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
    await pool.open(wait=True)
    return AsyncPostgresSaver(pool), pool


def thread_id(posting_id: int, policy_version: str, model_version: str) -> str:
    """One thread per (posting, policy version, model version). A draft passes its content hash as
    the version, so an edited draft never resumes an old run."""
    return f"{posting_id}:{policy_version}:{model_version}"
