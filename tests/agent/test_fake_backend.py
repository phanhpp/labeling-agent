"""LLM_BACKEND=fake: the whole agent runs with no key and no API call (used by CI and the no-keys demo)."""

from app import policy as policies
from app.agent import llm
from app.agent.configs import CONFIGS
from app.agent.graph import build
from app.agent.state import Context

V1 = policies.load_file(policies.POLICIES_DIR / "v1.yaml")


async def label(monkeypatch, posting: dict) -> dict:
    monkeypatch.setenv("LLM_BACKEND", "fake")
    llm.chat.cache_clear()
    try:
        state = await build().ainvoke(
            {"raw": posting}, context=Context(policy=V1, policy_version="v1", config=CONFIGS["sonnet_only"])
        )
    finally:
        llm.chat.cache_clear()
    return state["decision"]


async def test_the_fake_model_finds_a_starter_kit_fee(monkeypatch):
    decision = await label(
        monkeypatch,
        {
            "title": "Assembler",
            "company_profile": "Craftline Kits, since 2015.",
            "description": "Before you start, buy the starter kit for $149.",
        },
    )
    assert decision["label"] == "VIOLATING"
    assert decision["sections"] == ["§1"]
    assert decision["evidence"][0]["text"].startswith("starter kit")  # verified against the posting


async def test_the_fake_model_sends_an_empty_profile_to_review(monkeypatch):
    decision = await label(
        monkeypatch, {"title": "Clerk", "company_profile": "", "description": "Filing work."}
    )
    assert decision["label"] == "NEEDS_REVIEW"
    assert decision["sections"] == ["§5"]


async def test_the_fake_model_allows_a_plain_posting(monkeypatch):
    decision = await label(
        monkeypatch,
        {
            "title": "Clerk",
            "company_profile": "Lumen Books, Melbourne, since 2016.",
            "description": "Filing and phones.",
        },
    )
    assert decision["label"] == "ALLOWED"
