"""A fake labeling model for CI, tests and demos without keys (LLM_BACKEND=fake).

It answers from simple phrase rules on the posting, the same way every time, and always quotes the
posting's own text, so everything after it (check, decide, the queue, the UI) runs for real. Labels
it makes carry model_version "fake...". It is never used by the eval.
"""

import re

from langchain_core.messages import AIMessage

from app.agent.models import HaikuScreen, RawAnswer, RawFinding, ScreenAnswer

# Section -> phrases that make the fake model call it matched.
_RULES = {
    "§1": ["starter kit", "registration fee", "application fee", "pay for training"],
    "§2": ["bank details", "whatsapp", "telegram", "social security", "copy of your id"],
    "§3": ["package inspector", "payment processing agent", "reshipping", "gift cards"],
    "§4": ["no experience needed", "no experience necessary"],
}
_POSTING = re.compile(r"<posting>\n(.*)\n</posting>", re.S)


class FakeLabeler:
    def __init__(self, model: str):
        self.model = f"fake-{model}"

    def invoke(self, messages) -> dict:
        posting = _POSTING.search(
            messages[-1].content if hasattr(messages[-1], "content") else messages[-1][1]
        )
        text = posting.group(1) if posting else ""
        findings = []
        for code, phrases in _RULES.items():
            quote = _quote(text, phrases)
            status = "matched" if quote else "not_matched"
            findings.append(
                RawFinding(
                    section=code,
                    reasoning="Fake rule.",
                    status=status,
                    quotes=[quote] if quote else [],
                    confidence=0.8,
                )
            )
        empty = "company_profile" in text.split("Empty fields:")[-1] if "Empty fields:" in text else False
        findings.append(
            RawFinding(
                section="§5",
                reasoning="Fake rule.",
                status="matched" if empty else "not_matched",
                missing_fields=["company_profile"] if empty else [],
                confidence=0.6,
            )
        )
        answer = RawAnswer(
            findings=findings, rationale="Labeled by the fake model (no real model was called)."
        )
        raw = AIMessage(
            content="",
            response_metadata={"stop_reason": "end_turn", "model": self.model},
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        return {"raw": raw, "parsed": answer, "parsing_error": None}

    async def ainvoke(self, messages) -> dict:
        return self.invoke(messages)


def _quote(text: str, phrases: list[str]) -> str | None:
    """The phrase and the words after it, cut from the same line, so it is verbatim."""
    lowered = text.lower()
    for phrase in phrases:
        i = lowered.find(phrase)
        if i >= 0:
            line_end = text.find("\n", i)
            line_end = len(text) if line_end < 0 else line_end
            return text[i : min(line_end, i + 60)].strip()
    return None


class FakeScreen:
    """A fake Haiku screen that never clears anything, so every posting reaches the fake labeler."""

    async def ainvoke(self, messages) -> dict:
        answer = HaikuScreen(
            answers=[ScreenAnswer(section=f"§{i}", answer="unsure") for i in range(1, 6)], injection="no"
        )
        raw = AIMessage(
            content="",
            response_metadata={"stop_reason": "end_turn", "model": "fake-haiku"},
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        return {"raw": raw, "parsed": answer, "parsing_error": None}
