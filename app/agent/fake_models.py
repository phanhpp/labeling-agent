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
_SECTION = re.compile(r"^(§\d+) ", re.M)  # each section's first line in the system prompt


class FakeLabeler:
    def __init__(self, model: str):
        self.model = f"fake-{model}"

    def invoke(self, messages) -> dict:
        posting = _POSTING.search(
            messages[-1].content if hasattr(messages[-1], "content") else messages[-1][1]
        )
        text = posting.group(1) if posting else ""
        system = messages[0].content[0]["text"] if hasattr(messages[0], "content") else ""
        codes = list(dict.fromkeys(_SECTION.findall(system))) or [*_RULES, "§5"]
        findings = []
        for code, phrases in _RULES.items():
            quote = _quote(text, phrases)
            status = "matched" if quote else "not_matched"
            findings.append(
                RawFinding(
                    section=code,
                    reasoning=f'Found "{quote}".' if quote else "None of this section's words appear.",
                    status=status,
                    quotes=[quote] if quote else [],
                    confidence=0.8,
                )
            )
        empty = "company_profile" in text.split("Empty fields:")[-1] if "Empty fields:" in text else False
        no_logo = "company_logo" in text.split("Empty fields:")[-1] if "Empty fields:" in text else False
        # §6: a copied company overview, with an empty profile and no logo
        overview = _quote(text, ["corporate overview"]) if empty and no_logo else None
        if "§6" in codes:
            findings.append(
                RawFinding(
                    section="§6",
                    reasoning="A copied company overview, with no profile and no logo."
                    if overview
                    else "No copied company overview without a profile and logo.",
                    status="matched" if overview else "not_matched",
                    quotes=[overview] if overview else [],
                    confidence=0.7,
                )
            )
        findings.append(
            RawFinding(
                section="§5",
                reasoning="The company profile is empty." if empty else "The company profile is filled in.",
                status="matched" if empty else "not_matched",
                missing_fields=["company_profile"] if empty else [],
                confidence=0.6,
            )
        )
        kept = [f for f in findings if f.section in codes]
        matched = [f.section for f in kept if f.status == "matched"]
        answer = RawAnswer(
            findings=kept,
            rationale=f"Word rules matched {', '.join(matched)}." if matched else "No word rule matched.",
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
