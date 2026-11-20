"""The Postgres checkpointer: a run that dies resumes without redoing finished nodes."""

import asyncio
import json

from app import policy as policies
from app.agent import checkpoints
from app.agent.configs import CONFIGS
from app.agent.graph import build
from app.agent.models import RawAnswer, RawFinding
from app.agent.state import Context
from tests.fakes import FakeChat, use_chat

V1 = policies.load_file(policies.POLICIES_DIR / "v1.yaml")
POSTING = {
    "title": "Assembler",
    "company_profile": "Craftline Kits, since 2015.",
    "description": "Before your first shift, buy the $149 starter kit.",
}
ANSWER = RawAnswer(
    findings=[
        RawFinding(
            section=s["code"],
            reasoning="r",
            status="matched" if s["code"] == "§1" else "not_matched",
            quotes=["buy the $149 starter kit"] if s["code"] == "§1" else [],
            confidence=0.9,
        )
        for s in V1["sections"]
    ],
    rationale="Fee to start.",
)


async def test_setup_runs_twice_and_in_parallel(fresh_db_url):
    await asyncio.gather(*(checkpoints.setup_checkpoints(fresh_db_url) for _ in range(3)))
    await checkpoints.setup_checkpoints(fresh_db_url)


async def test_a_crashed_run_resumes_after_the_screen(fresh_db_url, monkeypatch):
    await checkpoints.setup_checkpoints(fresh_db_url)
    saver, pool = await checkpoints.open_checkpointer(fresh_db_url)
    screens = []
    real_screen = __import__("app.agent.graph", fromlist=["run_screen"]).run_screen

    async def counted(*args, **kwargs):
        screens.append(1)
        return await real_screen(*args, **kwargs)

    monkeypatch.setattr("app.agent.graph.run_screen", counted)
    graph = build(checkpointer=saver)
    config = {"configurable": {"thread_id": checkpoints.thread_id(1, "v1", "test")}}
    context = Context(policy=V1, policy_version="v1", config=CONFIGS["sonnet_only"])
    try:
        use_chat(monkeypatch, FakeChat(error=ConnectionError("worker died mid-call")))
        try:
            await graph.ainvoke({"raw": POSTING}, config, context=context, durability="sync")
        except ConnectionError:
            pass
        assert (await graph.aget_state(config)).next == ("escalate",)

        use_chat(monkeypatch, FakeChat(ANSWER))
        state = await graph.ainvoke(None, config, context=context, durability="sync")
        assert state["decision"]["label"] == "VIOLATING"
        assert len(screens) == 1  # the finished screen did not run again
        assert (await graph.aget_state(config)).next == ()
        json.dumps(state)  # the state is plain JSON, as checkpoints need
    finally:
        await pool.close()


STRICT_RUN = """
import asyncio, os, sys
from app import policy as policies
from app.agent import checkpoints
from app.agent.configs import CONFIGS
from app.agent.graph import build
from app.agent.state import Context

async def main():
    url = os.environ["DATABASE_URL"]
    await checkpoints.setup_checkpoints(url)
    saver, pool = await checkpoints.open_checkpointer(url)
    graph = build(checkpointer=saver)
    config = {"configurable": {"thread_id": "strict"}}
    v1 = policies.load_file(policies.POLICIES_DIR / "v1.yaml")
    context = Context(policy=v1, policy_version="v1", config=CONFIGS["sonnet_only"])
    posting = {"title": "Assembler", "description": "Pay the registration fee for your starter kit."}
    await graph.ainvoke({"raw": posting}, config, context=context, durability="sync")
    history = [s async for s in graph.aget_state_history(config)]  # loads every checkpoint
    print(len(history), history[0].values["decision"]["label"])
    await pool.close()

asyncio.run(main())
"""


def test_checkpoints_load_with_strict_msgpack(fresh_db_url):
    """With LANGGRAPH_STRICT_MSGPACK=true, loading a checkpoint may only build safe types (the
    compose services run this way). Our state is plain JSON, so every checkpoint still loads."""
    import os
    import subprocess
    import sys

    env = {
        **os.environ,
        "LANGGRAPH_STRICT_MSGPACK": "true",
        "LLM_BACKEND": "fake",
        "DATABASE_URL": fresh_db_url,
    }
    out = subprocess.run(
        [sys.executable, "-c", STRICT_RUN], env=env, capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stderr[-2000:]
    steps, label = out.stdout.split()
    assert int(steps) == 8 and label == "VIOLATING"
