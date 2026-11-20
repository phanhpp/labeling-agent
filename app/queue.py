"""The job queue, in the jobs table (Part A uses SQS; locally Postgres does the same job).

    queued --claim--> running --done--> done
                         \\--error--> queued again after a wait, or failed after 3 attempts
    running for over 120 s (the worker died) --reaper--> the same as an error

A claim takes the oldest queued job of the most urgent queue (live, then backfill, then shadow)
with FOR UPDATE SKIP LOCKED, so two workers never take the same job. The claim counts the attempt,
so a job that keeps killing its worker also ends in the dead-letter path.

A worker finishes a job only if it still holds it: done and failed check the status and the attempt
number it claimed. If the reaper re-queued the job meanwhile, the late result is ignored.
"""

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

MAX_ATTEMPTS = 3
LOCK_TIMEOUT_S = 120  # longer than the 90 s job limit, so the reaper never takes a job still running
RETRY_WAIT_S = (5, 30)  # wait before attempt 2 and attempt 3

_PRIORITY = "CASE queue WHEN 'live' THEN 0 WHEN 'backfill' THEN 1 ELSE 2 END"


async def claim(conn: AsyncConnection, thread_for) -> dict | None:
    """Take the next job, or None. thread_for(job) gives the LangGraph thread id saved on it."""
    async with conn.transaction():
        job = await (
            await conn.execute(
                f"SELECT * FROM jobs WHERE status = 'queued' AND run_after <= now()"
                f" ORDER BY {_PRIORITY}, id LIMIT 1 FOR UPDATE SKIP LOCKED"
            )
        ).fetchone()
        if job is None:
            return None
        return await (
            await conn.execute(
                "UPDATE jobs SET status = 'running', locked_at = now(), attempts = attempts + 1,"
                " thread_id = %s WHERE id = %s RETURNING *",
                (thread_for(job), job["id"]),
            )
        ).fetchone()


async def mark_done(conn: AsyncConnection, job: dict) -> bool:
    """Finish a job this worker holds. False if it no longer holds it (nothing is changed)."""
    row = await (
        await conn.execute(
            "UPDATE jobs SET status = 'done', locked_at = NULL, finished_at = now(), last_error = NULL"
            " WHERE id = %s AND status = 'running' AND attempts = %s RETURNING id",
            (job["id"], job["attempts"]),
        )
    ).fetchone()
    return row is not None


async def mark_failed(conn: AsyncConnection, job: dict, error: str, model_version: str) -> str | None:
    """Record a failed attempt. Returns "retry", "dead" or None (this worker no longer holds the job).

    Before the last attempt the job is queued again after a wait. After it, the job fails and the
    posting gets a NEEDS_REVIEW label with reason "dlq", so a failure is never a silent ALLOWED.
    """
    if job["attempts"] < MAX_ATTEMPTS:
        wait = RETRY_WAIT_S[min(job["attempts"], len(RETRY_WAIT_S)) - 1]
        row = await (
            await conn.execute(
                "UPDATE jobs SET status = 'queued', locked_at = NULL, last_error = %s,"
                " run_after = now() + make_interval(secs => %s)"
                " WHERE id = %s AND status = 'running' AND attempts = %s RETURNING id",
                (error, wait, job["id"], job["attempts"]),
            )
        ).fetchone()
        return "retry" if row else None
    async with conn.transaction():
        row = await (
            await conn.execute(
                "UPDATE jobs SET status = 'failed', locked_at = NULL, last_error = %s, finished_at = now()"
                " WHERE id = %s AND status = 'running' AND attempts = %s RETURNING id",
                (error, job["id"], job["attempts"]),
            )
        ).fetchone()
        if row is None:
            return None
        await save_dead_letter_label(conn, job, model_version)
    return "dead"


async def save_dead_letter_label(conn: AsyncConnection, job: dict, model_version: str) -> None:
    """NEEDS_REVIEW with reason dlq. Never replaces a real label for the same version and models."""
    await conn.execute(
        "INSERT INTO labels (posting_id, policy_version, policy_hash, model_version, label, confidence,"
        " reason_codes, rationale, cleaned) VALUES (%s, %s, %s, %s, 'NEEDS_REVIEW', 0, %s, %s, %s)"
        " ON CONFLICT (posting_id, policy_version, model_version) DO NOTHING",
        (
            job["posting_id"],
            job["policy_version"],
            job["policy_hash"],
            model_version,
            ["dlq"],
            f"Labeling failed {MAX_ATTEMPTS} times; held for review.",
            Jsonb({}),
        ),
    )


async def reap(conn: AsyncConnection, model_version: str) -> int:
    """Treat jobs locked for over LOCK_TIMEOUT_S as failed attempts. Returns how many it found."""
    stale = await (
        await conn.execute(
            "SELECT * FROM jobs WHERE status = 'running' AND locked_at < now() - make_interval(secs => %s)",
            (LOCK_TIMEOUT_S,),
        )
    ).fetchall()
    for job in stale:
        await mark_failed(conn, job, "lock expired: the worker stopped during the job", model_version)
    return len(stale)


async def counts(conn: AsyncConnection) -> dict:
    rows = await (await conn.execute("SELECT status, count(*) AS n FROM jobs GROUP BY status")).fetchall()
    return {r["status"]: r["n"] for r in rows}
