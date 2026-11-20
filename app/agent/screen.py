"""The screen: decides whether a posting is clearly clean enough to skip the escalation model, and
looks for prompt injection.

Injection phrases are checked in code on every posting, whatever screen runs: a hit sets the
injection flag, which makes the label at least NEEDS_REVIEW (decide). The phrases are kept short and
precise, so they don't fire on ordinary postings (instructions to applicants are not injections).

Phase 3 has only screen "none": every posting goes to the model. Jev and the Haiku fallback come next.
"""

import re

from app.agent.clean import QUOTABLE_FIELDS, Cleaned
from app.agent.configs import AgentConfig

INJECTION_PATTERNS = [
    re.compile(p, re.I | re.M)
    for p in (
        r"\b(ignore|disregard|forget)\s+(all\s+|any\s+)?(the\s+|your\s+)?(previous|prior|above|earlier)\s+(instructions|rules|prompts?)",
        r"\bnote\s+to\s+the\s+(ai|assistant|model|reviewer|classifier)\b",
        r"\b(ai|llm|automated)\s+(reviewer|moderator|classifier)\b",
        r"\byou\s+are\s+(an?\s+)?(ai|language\s+model|assistant|chatbot)\b",
        r"\b(system\s+prompt|developer\s+message)\b",
        r"^\s*(system|assistant)\s*:",
        r"\b(label|mark|classify)\s+(this|the)\s+(posting|job|ad)\s+as\s+(allowed|safe|legitimate)\b",
    )
]


def injection_hits(cleaned: Cleaned) -> list[str]:
    """The injection phrases found in the posting's quotable fields."""
    hits = []
    for name in QUOTABLE_FIELDS:
        for pattern in INJECTION_PATTERNS:
            match = pattern.search(cleaned.fields[name])
            if match:
                hits.append(match.group(0).strip())
    return hits


async def run_screen(cleaned: Cleaned, policy: dict, config: AgentConfig) -> dict:
    hits = injection_hits(cleaned)
    if config.screen == "none":
        return {
            "used": "none",
            "cleared": False,
            "scores": {},
            "injection": None,
            "regex_hits": hits,
            "injection_flag": bool(hits),
        }
    raise NotImplementedError(f"screen {config.screen!r} is not built yet")
