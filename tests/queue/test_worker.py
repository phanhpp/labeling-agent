"""The worker: labels, retries, resume after a crash, the job limit, the cache, pruning, no keys."""

import asyncio

import pytest

from app import policy as policies
from app import queue as jobs
from app import worker as worker_module
from app.agent import configs
from app.agent import graph as graph_module
from app.agent.models import RawAnswer, RawFinding
from app.agent.state import Context
from tests.fakes import FakeChat
from tests.helpers import CLEAN, POSTING, as_, drain, sql, submit

V1 = policies.load_file(policies.POLICIES_DIR / "v1.yaml")


def _answer() -> RawAnswer:
    return RawAnswer(
        findings=[
            RawFinding(
                section=s["code"],
                reasoning="r",
                status="matched" if s["code"] == "§1" else "not_matched",
                quotes=["pay the registration fee"] if s["code"] == "§1" else [],
                confidence=0.9,
            )
            for s in V1["sections"]
        ],
        rationale="A fee to start.",
    )


def _use(monkeypatch, chat):
    monkeypatch.setattr("app.agent.llm.chat", lambda profile: chat)
    return chat


async def _claim(worker):
    async with worker.pool.connection() as conn:
        return await jobs.claim(conn, worker.thread_for)


async def test_a_job_is_labeled_and_done(api, worker):
    await submit(api, POSTING)
    assert await drain(worker) == 1
    [job] = await sql(api, "SELECT status, finished_at IS NOT NULL AS finished FROM jobs")
    assert job == {"status": "done", "finished": True}
    [label] = await sql(api, "SELECT label, sections, model_version, latency_ms, trace_id FROM labels")
    assert label["label"] == "VIOLATING" and label["sections"] == ["§1"]
    assert label["model_version"] == worker.model_version and label["trace_id"] is None


async def test_a_failed_attempt_resumes_without_rerunning_finished_nodes(api, worker, monkeypatch):
    screens = []
    real = graph_module.run_screen

    async def counted(*args, **kwargs):
        screens.append(1)
        return await real(*args, **kwargs)

    monkeypatch.setattr("app.agent.graph.run_screen", counted)
    _use(monkeypatch, FakeChat(error=ConnectionError("Anthropic is down")))
    await submit(api, POSTING)
    await drain(worker)
    [job] = await sql(api, "SELECT status, attempts, last_error FROM jobs")
    assert job["status"] == "queued" and job["last_error"].startswith("ConnectionError")

    chat = _use(monkeypatch, FakeChat(_answer()))
    await sql(api, "UPDATE jobs SET run_after = now()")
    await drain(worker)
    [label] = await sql(api, "SELECT label FROM labels")
    assert label["label"] == "VIOLATING"
    assert len(screens) == 1 and len(chat.calls) == 1  # the screen ran once; Sonnet once per attempt


async def test_a_run_finished_but_not_saved_is_saved_without_calling_the_model(api, worker, monkeypatch):
    """The worker died between the graph's last node and saving the label."""
    await submit(api, POSTING)
    job = await _claim(worker)
    async with worker.pool.connection() as conn:
        policy = await worker.policy_for(conn, job)
    context = Context(policy=policy, policy_version="v1", config=worker.agent)
    config = {"configurable": {"thread_id": job["thread_id"]}}
    await worker.graph.ainvoke({"raw": POSTING}, config, context=context, durability="sync")

    chat = _use(monkeypatch, FakeChat(_answer()))
    await worker.handle(job)
    assert chat.calls == []
    assert [r["status"] for r in await sql(api, "SELECT status FROM jobs")] == ["done"]
    assert len(await sql(api, "SELECT id FROM labels")) == 1


async def test_a_job_over_the_time_limit_is_a_failed_attempt(api, worker, monkeypatch):
    class Stuck:
        async def ainvoke(self, messages):
            await asyncio.sleep(10)

    _use(monkeypatch, Stuck())
    monkeypatch.setattr(worker_module, "JOB_TIMEOUT_S", 0.2)
    await submit(api, POSTING)
    await drain(worker)
    [job] = await sql(api, "SELECT status, last_error FROM jobs")
    assert job["status"] == "queued" and job["last_error"].startswith("timeout")


async def test_three_failures_end_in_needs_review_for_the_client(api, worker, monkeypatch):
    _use(monkeypatch, FakeChat(error=ConnectionError("down")))
    await submit(api, POSTING)
    for _ in range(3):
        await sql(api, "UPDATE jobs SET run_after = now()")
        await drain(worker)
    out = (await api.get("/v1/postings/p1/label", headers=as_("marketplace"))).json()
    assert out["label"] == "NEEDS_REVIEW" and out["reason_codes"] == ["dlq"]


async def test_the_same_text_elsewhere_reuses_the_label(api, worker, monkeypatch):
    """Location isn't sent to the models, so the same ad in another city is a cache hit."""
    await submit(api, {**POSTING, "location": "US, NY, New York"})
    await drain(worker)
    chat = _use(monkeypatch, FakeChat(_answer()))
    await submit(api, {**POSTING, "job_id": "p1-sf", "location": "US, CA, San Francisco"})
    await drain(worker)
    assert chat.calls == []
    first, second = await sql(api, "SELECT id, label, derived_from, reason_codes FROM labels ORDER BY id")
    assert second["derived_from"] == first["id"] and second["label"] == first["label"]
    assert "cached" in second["reason_codes"]


async def test_the_loop_runs_jobs_concurrently_and_stops_cleanly(api, worker):
    await submit(api, *({**CLEAN, "job_id": f"j{i}"} for i in range(10)))
    stop = asyncio.Event()
    loop = asyncio.create_task(worker.run(stop))
    for _ in range(100):
        if len(await sql(api, "SELECT id FROM jobs WHERE status = 'done'")) == 10:
            break
        await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(loop, 5)
    assert len(await sql(api, "SELECT id FROM labels")) == 10


async def test_old_checkpoints_are_pruned(api, worker):
    await submit(api, POSTING)
    await drain(worker)
    [job] = await sql(api, "SELECT id, posting_id, thread_id FROM jobs")
    await sql(api, "UPDATE jobs SET finished_at = now() - interval '8 days'")
    await worker.prune()
    config = {"configurable": {"thread_id": job["thread_id"]}}
    assert (await worker.graph.aget_state(config)).values == {}
    steps = (await api.get(f"/ui/postings/{job['posting_id']}/steps", headers=as_("viewer"))).json()
    assert steps["job"]["checkpoints_pruned"] is True and steps["steps"] == []


async def test_recent_checkpoints_are_kept(api, worker):
    await submit(api, POSTING)
    await drain(worker)
    await worker.prune()
    assert (await sql(api, "SELECT checkpoints_pruned FROM jobs"))[0]["checkpoints_pruned"] is False


@pytest.mark.parametrize(
    ("env", "config", "missing"),
    [
        ({}, "haiku_sonnet", ["ANTHROPIC_API_KEY"]),
        ({"TYPESAFE_API_KEY": "x"}, "jev_sonnet", ["ANTHROPIC_API_KEY"]),
        ({"TYPESAFE_API_KEY": "x", "ANTHROPIC_API_KEY": "x"}, "jev_sonnet", []),
        ({"ANTHROPIC_API_KEY": "x", "AGENT_CONFIG": "jev_sonnet"}, "jev_sonnet", ["TYPESAFE_API_KEY"]),
        ({"LLM_BACKEND": "fake"}, "sonnet_only", []),
    ],
)
def test_which_config_runs_and_which_keys_it_lacks(monkeypatch, env, config, missing):
    for key in ("ANTHROPIC_API_KEY", "TYPESAFE_API_KEY", "AGENT_CONFIG", "LLM_BACKEND"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    chosen = configs.worker_config()
    assert chosen.name == config
    assert configs.missing_keys(chosen) == missing


async def test_without_keys_the_api_accepts_postings_and_health_says_not_labeling(api, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "real")
    for key in ("ANTHROPIC_API_KEY", "TYPESAFE_API_KEY", "AGENT_CONFIG"):
        monkeypatch.delenv(key, raising=False)
    health = (await api.get("/health")).json()
    assert health["live_labeling"] is False and health["missing_keys"] == ["ANTHROPIC_API_KEY"]
    await submit(api, POSTING)
    assert (await api.get("/v1/postings/p1/label", headers=as_("marketplace"))).status_code == 202
