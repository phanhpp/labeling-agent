"""The jobs-table queue: priority, no double claims, retries, the dead-letter path and the reaper."""

import asyncio

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app import queue as jobs
from app import store
from tests.helpers import CLEAN, POSTING, sql, submit

MODEL = "test-model"


def _thread(job):
    return f"t{job['id']}"


async def _claim(api):
    async with api.app.state.pool.connection() as conn:
        return await jobs.claim(conn, _thread)


async def _queue_three(api):
    """One posting with a job on each queue, created shadow first, so creation order can't explain
    the result."""
    await submit(api, POSTING)
    [posting] = await sql(api, "SELECT id FROM postings")
    await sql(api, "DELETE FROM jobs")
    async with api.app.state.pool.connection() as conn:
        live = await store.live_policy(conn)
        for name, queue in (("vs", "shadow"), ("vb", "backfill"), ("vl", "live")):
            await conn.execute(
                "INSERT INTO policy_versions (name, status, body, content_hash, model_hash, author)"
                " VALUES (%s, 'draft', %s, 'h', 'm', 't')",
                (name, Jsonb(live["body"])),
            )
            await store.enqueue(conn, posting["id"], name, "h", queue)


async def test_live_is_claimed_before_backfill_before_shadow(api):
    await _queue_three(api)
    order = [(await _claim(api))["queue"] for _ in range(3)]
    assert order == ["live", "backfill", "shadow"]
    assert await _claim(api) is None


async def test_a_claim_counts_the_attempt_and_records_the_thread(api):
    await submit(api, POSTING)
    job = await _claim(api)
    assert (job["status"], job["attempts"], job["thread_id"]) == ("running", 1, f"t{job['id']}")
    assert job["locked_at"] is not None


async def test_two_workers_never_claim_the_same_job(api, fresh_db_url):
    await submit(api, *({**CLEAN, "job_id": f"j{i}"} for i in range(30)))

    async def claimer():
        got = []
        async with await psycopg.AsyncConnection.connect(fresh_db_url, row_factory=dict_row) as conn:
            while (job := await jobs.claim(conn, _thread)) is not None:
                got.append(job["id"])
                await conn.commit()
        return got

    claimed = await asyncio.gather(*(claimer() for _ in range(6)))
    every = [job for got in claimed for job in got]
    assert len(every) == 30 and len(set(every)) == 30


async def test_a_job_waits_before_its_next_attempt(api):
    await submit(api, POSTING)
    job = await _claim(api)
    async with api.app.state.pool.connection() as conn:
        assert await jobs.mark_failed(conn, job, "ConnectionError", MODEL) == "retry"
    [row] = await sql(api, "SELECT status, attempts, last_error, run_after > now() AS waiting FROM jobs")
    assert row == {"status": "queued", "attempts": 1, "last_error": "ConnectionError", "waiting": True}
    assert await _claim(api) is None  # not before its wait is over


async def _fail(api, times: int):
    for _ in range(times):
        await sql(api, "UPDATE jobs SET run_after = now()")
        job = await _claim(api)
        async with api.app.state.pool.connection() as conn:
            outcome = await jobs.mark_failed(conn, job, "ConnectionError", MODEL)
    return outcome


async def test_after_three_failed_attempts_the_posting_is_held_for_review(api):
    await submit(api, POSTING)
    assert await _fail(api, 3) == "dead"
    [job] = await sql(api, "SELECT status, attempts FROM jobs")
    assert job == {"status": "failed", "attempts": 3}
    [label] = await sql(api, "SELECT label, reason_codes, confidence FROM labels")
    assert label == {"label": "NEEDS_REVIEW", "reason_codes": ["dlq"], "confidence": 0.0}


async def test_a_dead_letter_never_replaces_a_real_label(api):
    await submit(api, POSTING)
    job = await _claim(api)
    async with api.app.state.pool.connection() as conn:
        await conn.execute(
            "INSERT INTO labels (posting_id, policy_version, policy_hash, model_version, label,"
            " confidence, cleaned) VALUES (%s, 'v1', %s, %s, 'ALLOWED', 0.9, '{}')",
            (job["posting_id"], job["policy_hash"], MODEL),
        )
        await jobs.save_dead_letter_label(conn, job, MODEL)
    assert [r["label"] for r in await sql(api, "SELECT label FROM labels")] == ["ALLOWED"]


async def test_the_reaper_requeues_a_job_whose_worker_stopped(api):
    await submit(api, POSTING)
    await _claim(api)
    await sql(api, "UPDATE jobs SET locked_at = now() - interval '121 seconds'")
    async with api.app.state.pool.connection() as conn:
        assert await jobs.reap(conn, MODEL) == 1
    [row] = await sql(api, "SELECT status, last_error FROM jobs")
    assert row["status"] == "queued" and "lock expired" in row["last_error"]


async def test_the_reaper_leaves_a_job_that_is_still_running(api):
    await submit(api, POSTING)
    await _claim(api)
    async with api.app.state.pool.connection() as conn:
        assert await jobs.reap(conn, MODEL) == 0


async def test_a_reaped_jobs_late_result_is_ignored(api):
    await submit(api, POSTING)
    first = await _claim(api)
    await sql(api, "UPDATE jobs SET locked_at = now() - interval '121 seconds'")
    async with api.app.state.pool.connection() as conn:
        await jobs.reap(conn, MODEL)
    await sql(api, "UPDATE jobs SET run_after = now()")
    second = await _claim(api)
    async with api.app.state.pool.connection() as conn:
        assert await jobs.mark_done(conn, first) is False  # the first worker no longer holds it
        assert await jobs.mark_failed(conn, first, "late", MODEL) is None
        assert await jobs.mark_done(conn, second) is True
    [row] = await sql(api, "SELECT status, attempts FROM jobs")
    assert row == {"status": "done", "attempts": 2}


async def test_one_open_job_per_posting_and_version(api):
    await submit(api, POSTING)
    [posting] = await sql(api, "SELECT id, raw FROM postings")
    async with api.app.state.pool.connection() as conn:
        await store.enqueue(conn, posting["id"], "v1", "h", "backfill")  # already queued: ignored
    assert len(await sql(api, "SELECT id FROM jobs")) == 1
