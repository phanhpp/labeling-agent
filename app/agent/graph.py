"""The labeling agent: a fixed LangGraph graph.

    START -> clean -> cache --hit--> END
                        \\ miss -> screen --cleared--> decide -> END
                                        \\ escalate -> check -> decide -> END

An expected failure in clean or escalate goes straight to decide, which holds the posting for review.
An unexpected exception goes up to the caller (the worker retries the job; the eval lists it as errored).
The graph writes nothing to the database: whoever runs it saves the result.
"""

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app import policy as policies
from app.agent import AGENT_VERSION
from app.agent.cache import cache_key
from app.agent.check import Checked, check
from app.agent.clean import Cleaned, clean_posting
from app.agent.decide import decide
from app.agent.escalate import PROMPT_VERSION, escalate, render_posting
from app.agent.models import Finding, RawAnswer
from app.agent.screen import run_screen
from app.agent.state import Context, State
from app.config import llm_backend


def _cleaned(state: State) -> Cleaned:
    return Cleaned(fields=state["cleaned"], facts=state["facts"])


async def clean_node(state: State) -> dict:
    try:
        cleaned = clean_posting(state["raw"])
    except Exception:  # noqa: BLE001 - any failure to clean holds the posting for review
        return {"failure": "clean_error"}
    return {"cleaned": cleaned.fields, "facts": cleaned.facts, "model_input": render_posting(cleaned)}


async def cache_node(state: State, runtime: Runtime[Context]) -> dict:
    ctx = runtime.context
    key = cache_key(
        state["model_input"],
        policies.content_hash(ctx.policy),
        f"{AGENT_VERSION}/{PROMPT_VERSION}",
        {"escalate": ctx.config.model, "screen": ctx.config.screen, "backend": llm_backend()},
        {"hints": ctx.config.hints, **ctx.config.screen_settings},
    )
    if ctx.config.cache and ctx.cache_lookup is not None:
        hit = await ctx.cache_lookup(key)
        if hit is not None:
            return {"cache_key": key, "decision": hit["decision"], "cached_from": hit["label_id"]}
    return {"cache_key": key}


async def screen_node(state: State, runtime: Runtime[Context]) -> dict:
    ctx = runtime.context
    screen, usage = await run_screen(_cleaned(state), ctx.policy, ctx.config)
    return {"screen": screen, "usage": usage}


async def escalate_node(state: State, runtime: Runtime[Context]) -> dict:
    ctx = runtime.context
    hints = state["screen"].get("scores") if ctx.config.hints else None
    result = await escalate(_cleaned(state), ctx.policy, ctx.config.escalation, hints)
    update: dict = {"usage": [result.usage]}
    if result.failure:
        update["failure"] = result.failure
    else:
        update["raw_output"] = result.answer.model_dump()
    return update


async def check_node(state: State, runtime: Runtime[Context]) -> dict:
    answer = RawAnswer.model_validate(state["raw_output"])
    checked = check(answer, runtime.context.policy, _cleaned(state))
    return {
        "checked": {
            "findings": [f.model_dump() for f in checked.findings],
            "rationale": checked.rationale,
            "reason_codes": checked.reason_codes,
            "downgraded": checked.downgraded,
            "unknown_sections": checked.unknown_sections,
        }
    }


async def decide_node(state: State, runtime: Runtime[Context]) -> dict:
    screen = state.get("screen") or {}
    checked = None
    if state.get("checked"):
        data = state["checked"]
        checked = Checked(
            findings=[Finding(**f) for f in data["findings"]],
            rationale=data["rationale"],
            reason_codes=data["reason_codes"],
            downgraded=data["downgraded"],
            unknown_sections=data["unknown_sections"],
        )
    decision = decide(
        runtime.context.policy,
        checked,
        cleared_scores=screen.get("scores") if screen.get("cleared") else None,
        injection=bool(screen.get("injection_flag")),
        failure=state.get("failure"),
    )
    decision.reason_codes += screen.get("reason_codes", [])  # screen_fallback, screen_unavailable
    return {"decision": decision.model_dump()}


def _after_clean(state: State) -> str:
    return "decide" if state.get("failure") else "cache"


def _after_cache(state: State) -> str:
    return END if state.get("cached_from") is not None else "screen"


def _after_screen(state: State) -> str:
    return "decide" if state["screen"].get("cleared") else "escalate"


def _after_escalate(state: State) -> str:
    return "decide" if state.get("failure") else "check"


def build(checkpointer=None):
    graph = StateGraph(State, context_schema=Context)
    graph.add_node("clean", clean_node)
    graph.add_node("cache", cache_node)
    graph.add_node("screen", screen_node)
    graph.add_node("escalate", escalate_node)
    graph.add_node("check", check_node)
    graph.add_node("decide", decide_node)
    graph.add_edge(START, "clean")
    graph.add_conditional_edges("clean", _after_clean, ["cache", "decide"])
    graph.add_conditional_edges("cache", _after_cache, ["screen", END])
    graph.add_conditional_edges("screen", _after_screen, ["escalate", "decide"])
    graph.add_conditional_edges("escalate", _after_escalate, ["check", "decide"])
    graph.add_edge("check", "decide")
    graph.add_edge("decide", END)
    return graph.compile(checkpointer=checkpointer)


def model_version(config) -> str:
    """Which code and models made a label: part of the labels table's key. Labels from the fake
    backend say so, and the backend is in the cache key too, so a fake label is never reused."""
    fake = "fake;" if llm_backend() == "fake" else ""
    return (
        f"{fake}{config.name};escalate={config.model};screen={config.screen};"
        f"agent={AGENT_VERSION};prompt={PROMPT_VERSION}"
    )
