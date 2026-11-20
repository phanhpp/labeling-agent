"""Model clients, built lazily and reused, plus what each call cost.

chat(profile) returns a runnable that answers with a RawAnswer. It is built on first use (so importing
this module needs no API key) and cached, like kg's _classifier(). Tests replace it with a fake by
monkeypatching app.agent.llm.chat. With LLM_BACKEND=fake the fake backend is used instead of Claude.
"""

from functools import cache

from langchain_anthropic import ChatAnthropic
from langchain_core.runnables import Runnable

from app import config
from app.agent.configs import ESCALATION_PROFILES
from app.agent.models import RawAnswer


@cache
def chat(profile: str) -> Runnable:
    """Structured output for one escalation profile: invoke() returns {"raw", "parsed", "parsing_error"}."""
    settings = dict(ESCALATION_PROFILES[profile])
    model = settings.pop("model")
    if model not in config.MODEL_ALLOWLIST:
        raise ValueError(f"model {model!r} is not in MODEL_ALLOWLIST")
    if config.llm_backend() == "fake":
        from app.agent.fake_models import FakeLabeler

        return FakeLabeler(model)
    llm = ChatAnthropic(
        model=model,
        max_tokens=4000,
        timeout=config.MODEL_TIMEOUT_S,
        max_retries=config.MODEL_MAX_RETRIES,
        **settings,
    )
    # json_schema puts the schema in output_config.format: Sonnet 5.5 refuses forced tool use.
    return llm.with_structured_output(RawAnswer, method="json_schema", include_raw=True)


def cost_usd(model: str, usage: dict | None) -> float:
    """Dollars for one call, from LangChain's usage_metadata."""
    if not usage or model not in config.PRICES:
        return 0.0
    price = config.PRICES[model]
    details = usage.get("input_token_details") or {}
    cache_read = details.get("cache_read") or 0
    cache_write = details.get("cache_creation") or 0
    plain_input = usage.get("input_tokens", 0) - cache_read - cache_write
    total = (
        plain_input * price["input"]
        + cache_write * price["cache_write"]
        + cache_read * price["cache_read"]
        + usage.get("output_tokens", 0) * price["output"]
    )
    return round(total / 1_000_000, 6)
