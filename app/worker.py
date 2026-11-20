"""The worker: takes jobs from the queue and runs the labeling agent on each, a few at a time.

For each job:
  1. Look at the job's LangGraph thread. If an earlier attempt finished the graph but died before
     saving, save that result. If it stopped part-way, resume it: finished nodes don't run again.
     Otherwise start a new run.
  2. Save the label and mark the job done, in one transaction.
  3. If the run raised (an API error after retries, the 90 s limit), the attempt failed: the job is
     queued again after a wait, and after 3 attempts the posting is held for review (reason dlq).

Also, every 30 s, re-queue jobs whose worker died (the reaper), and every hour delete checkpoints
older than 7 days. Logs carry job ids, labels and reason codes, never posting text.

Without API keys the worker idles: postings are accepted and wait in the queue.

Run: uv run python -m app.worker
"""

import asyncio
import logging
import os
import signal
import time
import uuid

from app import config, db, store
from app import queue as jobs
from app.agent import checkpoints
from app.agent.configs import AgentConfig, missing_keys, worker_config
from app.agent.graph import build, model_version
from app.agent.state import Context

log = logging.getLogger("app.worker")

JOB_TIMEOUT_S = 90  # Sonnet's worst case is 2 tries of 25 s, plus Jev's 3 tries of 5 s
POLL_S = 1.0
REAP_EVERY_S = 30
PRUNE_EVERY_S = 3600
KEEP_CHECKPOINTS_DAYS = 7


class PolicyChanged(Exception):
    """The job's draft was edited after the job was queued: its result would label old content."""


class Worker:
    def __init__(self, pool, saver, agent: AgentConfig, concurrency: int = 4):
        self.pool = pool
        self.saver = saver
        self.agent = agent
        self.graph = build(checkpointer=saver)
        self.model_version = model_version(agent)
        self.concurrency = concurrency
        self._policies: dict[tuple[str, str], dict] = {}

    def thread_for(self, job: dict) -> str:
        """The version name plus its content hash: an edited draft never resumes an older run."""
        version = f"{job['policy_version']}@{job['policy_hash'][:12]}"
        return checkpoints.thread_id(job["posting_id"], version, self.model_version)

    async def policy_for(self, conn, job: dict) -> dict:
        key = (job["policy_version"], job["policy_hash"])
        if key not in self._policies:
            row = await store.policy_version(conn, job["policy_version"])
            if row is None or row["content_hash"] != job["policy_hash"]:
                raise PolicyChanged(
                    f"policy {job['policy_version']} changed after job {job['id']} was queued"
                )
            self._policies[key] = row["body"]
        return self._policies[key]

    async def cache_lookup(self, key: str) -> dict | None:
        async with self.pool.connection() as conn:
            return await store.cache_lookup(conn, key)

    async def run_job(self, job: dict) -> dict:
        """Run (or resume) the graph for one job and save the label. Returns the decision."""
        async with self.pool.connection() as conn:
            posting = await store.posting(conn, job["posting_id"])
            policy = await self.policy_for(conn, job)
        context = Context(
            policy=policy,
            policy_version=job["policy_version"],
            config=self.agent,
            cache_lookup=self.cache_lookup,
        )
        run_id = uuid.uuid4()  # LangSmith uses it as the trace id
        graph_config = {
            "configurable": {"thread_id": job["thread_id"]},
            "run_id": run_id,
            "run_name": "label_posting",
            "metadata": {
                "job": job["id"],
                "posting": job["posting_id"],
                "policy_version": job["policy_version"],
            },
        }
        started = time.monotonic()
        snapshot = await self.graph.aget_state(graph_config)
        if snapshot.values and not snapshot.next:
            state = snapshot.values  # finished by an earlier attempt that died before saving
        else:
            graph_input = None if snapshot.next else {"raw": posting["raw"]}  # None resumes
            state = await asyncio.wait_for(
                self.graph.ainvoke(graph_input, graph_config, context=context, durability="sync"),
                JOB_TIMEOUT_S,
            )
        latency_ms = round((time.monotonic() - started) * 1000)
        trace_id = str(run_id) if os.environ.get("LANGSMITH_TRACING") == "true" else None
        async with self.pool.connection() as conn, conn.transaction():
            await store.save_label(conn, job, state, self.model_version, latency_ms, trace_id)
            if not await jobs.mark_done(conn, job):
                log.warning("job %s was re-queued while running; its result is saved anyway", job["id"])
        return state["decision"]

    async def handle(self, job: dict) -> None:
        try:
            decision = await self.run_job(job)
        except PolicyChanged:
            async with self.pool.connection() as conn:
                await jobs.cancel(conn, job, "draft changed before this job ran")
            log.info("job %s skipped: its draft changed", job["id"])
            return
        except Exception as error:  # noqa: BLE001 - any failure is a failed attempt
            reason = "timeout" if isinstance(error, TimeoutError) else type(error).__name__
            async with self.pool.connection() as conn:
                outcome = await jobs.mark_failed(
                    conn, job, f"{reason}: {str(error)[:300]}", self.model_version
                )
            log.warning("job %s attempt %s failed (%s): %s", job["id"], job["attempts"], reason, outcome)
            return
        log.info(
            "job %s posting %s labeled %s %s",
            job["id"],
            job["posting_id"],
            decision["label"],
            ",".join(decision["reason_codes"]) or "-",
        )

    async def reap(self) -> None:
        async with self.pool.connection() as conn:
            found = await jobs.reap(conn, self.model_version)
        if found:
            log.warning("reaper found %s jobs whose worker stopped", found)

    async def prune(self) -> None:
        """Delete the LangGraph threads of jobs finished over 7 days ago."""
        async with self.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT id, thread_id FROM jobs WHERE status IN ('done', 'failed')"
                    " AND NOT checkpoints_pruned AND thread_id IS NOT NULL"
                    " AND finished_at < now() - make_interval(days => %s) LIMIT 500",
                    (KEEP_CHECKPOINTS_DAYS,),
                )
            ).fetchall()
            for row in rows:
                await self.saver.adelete_thread(row["thread_id"])
                await conn.execute("UPDATE jobs SET checkpoints_pruned = true WHERE id = %s", (row["id"],))

    async def run(self, stop: asyncio.Event) -> None:
        """Claim and run jobs until stop is set, at most `concurrency` at a time."""
        slots = asyncio.Semaphore(self.concurrency)
        running: set[asyncio.Task] = set()
        last_reap = last_prune = 0.0
        while not stop.is_set():
            now = time.monotonic()
            if now - last_reap >= REAP_EVERY_S:
                await self.reap()
                last_reap = now
            if now - last_prune >= PRUNE_EVERY_S:
                await self.prune()
                last_prune = now
            await slots.acquire()
            async with self.pool.connection() as conn:
                job = await jobs.claim(conn, self.thread_for)
            if job is None:
                slots.release()
                await _sleep(stop, POLL_S)
                continue
            task = asyncio.create_task(self.handle(job))
            running.add(task)
            task.add_done_callback(lambda t: (running.discard(t), slots.release()))
        await asyncio.gather(*running)


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), seconds)
    except TimeoutError:
        pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for noisy in ("httpx", "anthropic", "langsmith"):
        logging.getLogger(noisy).setLevel(logging.WARNING)  # their logs could carry request bodies
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    agent = worker_config()
    if agent.model not in config.MODEL_ALLOWLIST:
        raise SystemExit(f"model {agent.model} is not in the allowlist")
    missing = missing_keys(agent)
    if missing:
        log.warning(
            "not labeling: %s not set. Postings are queued until the keys are added.", ", ".join(missing)
        )
        await stop.wait()
        return

    url = config.database_url()
    pool = await db.open_pool(url)
    saver, saver_pool = await checkpoints.open_checkpointer(url)
    concurrency = int(os.environ.get("WORKER_CONCURRENCY", "4"))
    worker = Worker(pool, saver, agent, concurrency)
    log.info(
        "worker started: config %s, %s at a time, backend %s", agent.name, concurrency, config.llm_backend()
    )
    try:
        await worker.run(stop)
    finally:
        await saver_pool.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
