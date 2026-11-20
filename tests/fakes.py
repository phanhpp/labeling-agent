"""Stand-ins for the models, injected by monkeypatching the factories in app.agent.llm (as in kg)."""

from langchain_core.messages import AIMessage

from app.agent.models import RawAnswer

USAGE = {
    "input_tokens": 2000,
    "output_tokens": 500,
    "total_tokens": 2500,
    "input_token_details": {"cache_read": 1500, "cache_creation": 0},
}


class FakeChat:
    """Answers like ChatAnthropic.with_structured_output(..., include_raw=True) and records prompts."""

    def __init__(
        self, answer: RawAnswer | None = None, stop_reason: str = "end_turn", error: Exception | None = None
    ):
        self.answer = answer
        self.stop_reason = stop_reason
        self.error = error
        self.calls: list = []

    async def ainvoke(self, messages) -> dict:
        self.calls.append(messages)
        if self.error:
            raise self.error
        raw = AIMessage(
            content="",
            response_metadata={"stop_reason": self.stop_reason, "model": "claude-sonnet-5-5"},
            usage_metadata=USAGE,
        )
        parsed = self.answer if self.stop_reason == "end_turn" else None
        return {"raw": raw, "parsed": parsed, "parsing_error": None if parsed else ValueError("no answer")}


def use_chat(monkeypatch, fake: FakeChat) -> FakeChat:
    monkeypatch.setattr("app.agent.llm.chat", lambda profile: fake)
    return fake
