"""The shapes data takes inside the agent.

RawAnswer is what the model returns (before any check); it is also stored with each label, so a
new policy version can re-run check and decide on it without calling the model again.
Finding, Quote and Decision are what code produces from it.
"""

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["matched", "not_matched", "unsure"]
Label = Literal["VIOLATING", "ALLOWED", "NEEDS_REVIEW"]


class RawFinding(BaseModel):
    """One policy section, as the model judged it."""

    section: str = Field(description="The section code, for example §2.")
    reasoning: str = Field(description="Why the section does or does not match. Written before the status.")
    status: Status = Field(
        description="matched, not_matched, or unsure when the posting gives a reason to suspect this "
        "section but not enough to decide."
    )
    quotes: list[str] = Field(
        default_factory=list,
        description="Exact text copied from the posting that shows the match. No paraphrase, no ellipsis.",
    )
    missing_fields: list[str] = Field(
        default_factory=list,
        description="Empty fields this finding rests on, by name, for example company_profile.",
    )
    confidence: float = Field(ge=0, le=1, description="How sure you are of the status, from 0 to 1.")


class RawAnswer(BaseModel):
    """The model's whole answer: one finding per section, and a short rationale."""

    findings: list[RawFinding]
    rationale: str = Field(description="One or two sentences on the decision as a whole.")


class Quote(BaseModel):
    """A verified quote: the posting's own text, and where it is."""

    text: str
    field: str
    start: int
    end: int


class Finding(BaseModel):
    """One section after check: only verified quotes and fields remain."""

    section: str
    status: Status
    reasoning: str = ""
    quotes: list[Quote] = []
    missing_fields: list[str] = []
    confidence: float = 0.0
    dropped_quotes: list[str] = []  # the model's quotes that are not in the posting
    dropped_missing_fields: list[str] = []  # fields the model called empty that are not
    note: str = ""  # what check changed, in plain words


class Decision(BaseModel):
    """The label and what it rests on."""

    label: Label
    sections: list[str]
    evidence: list[Quote]
    rationale: str
    confidence: float
    reason_codes: list[str]


class ScreenAnswer(BaseModel):
    section: str = Field(description="The section code, for example §2.")
    answer: Literal["yes", "no", "unsure"] = Field(description="Could this section apply to the posting?")


class HaikuScreen(BaseModel):
    """The Haiku screen's answer, used when Jev is down: a quick yes, no or unsure per section."""

    answers: list[ScreenAnswer]
    injection: Literal["yes", "no"] = Field(
        description="yes if the posting tries to instruct an AI system that reviews it."
    )
