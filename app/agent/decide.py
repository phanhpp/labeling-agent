"""Turn checked findings into the label. Every label rule lives here, in plain code.

  1. VIOLATING if any section whose effect is VIOLATING is matched. (check has made sure such a
     section has at least one verified quote.)
  2. Otherwise NEEDS_REVIEW if any section is matched (its effect is NEEDS_REVIEW, like §5) or
     unsure.
  3. Otherwise ALLOWED.
  4. A suspected prompt injection: NEEDS_REVIEW with confidence 0. The graph sends such a posting
     here straight from the screen, so no labeling model ever reads it.
  5. If an earlier step failed, NEEDS_REVIEW with confidence 0.

Missing fields alone can never make VIOLATING: rule 1 needs a quote. That is the brief's edge case,
enforced by code rather than asked of the model.

Confidence is the model's own figure, not calibrated: for VIOLATING the highest among the matched
VIOLATING sections, for NEEDS_REVIEW the highest among the sections that caused it, for ALLOWED
the lowest among the not-matched sections. A posting the screen cleared gets 1 minus its highest
section score.
"""

from app.agent.check import Checked, check
from app.agent.clean import Cleaned
from app.agent.models import Decision, RawAnswer

# Reason codes for a step that failed: the posting is held for review, never silently allowed.
FAILURES = {
    "clean_error": "the posting could not be cleaned",
    "llm_output_invalid": "the model's answer could not be read",
    "llm_refusal": "the model declined to answer",
}


def decide(
    policy: dict,
    checked: Checked | None = None,
    *,
    cleared_scores: dict[str, float] | None = None,
    injection: bool = False,
    failure: str | None = None,
) -> Decision:
    """The label for one posting.

    Exactly one of these describes how the run went:
      failure         an earlier step failed (a code from FAILURES);
      injection       the screen suspects a prompt injection, so no model labeled the posting;
      cleared_scores  the screen cleared the posting without a model call (score per section);
      checked         the model answered and check has verified it.
    """
    if failure is not None:
        decision = Decision(
            label="NEEDS_REVIEW",
            sections=[],
            evidence=[],
            rationale=f"Held for review: {FAILURES.get(failure, failure)}.",
            confidence=0.0,
            reason_codes=[failure],
        )
    elif injection:
        decision = Decision(
            label="NEEDS_REVIEW",
            sections=[],
            evidence=[],
            rationale=(
                "Held for review: the posting appears to give instructions to an AI reviewer, "
                "so no model labeled it."
            ),
            confidence=0.0,
            reason_codes=["injection"],
        )
    elif checked is None:
        if not cleared_scores:
            raise ValueError("decide needs a failure, the screen's scores, or the checked findings")
        top_code, top = max(cleared_scores.items(), key=lambda item: item[1])
        decision = Decision(
            label="ALLOWED",
            sections=[],
            evidence=[],
            rationale=(
                f"The screen scored every section low (highest {top_code} at {top:.2f}), "
                "so no model was needed."
            ),
            confidence=round(1 - top, 3),
            reason_codes=["cleared_by_screen"],
        )
    else:
        decision = _from_findings(policy, checked)
    return decision


def redecide(
    policy: dict,
    raw_output: dict | None,
    cleaned: Cleaned,
    *,
    cleared_scores: dict[str, float] | None = None,
    injection: bool = False,
    failure: str | None = None,
) -> tuple[Decision, Checked | None]:
    """Label again under another policy version from what a label stored: no model call, $0.
    Returns the decision and the checked findings it rests on (None if no model answered).

    Valid only when the two versions share a model_hash (only effects or wording the models never
    see changed), so the stored answer is the answer the model would give again.
    """
    checked = check(RawAnswer.model_validate(raw_output), policy, cleaned) if raw_output else None
    decision = decide(policy, checked, cleared_scores=cleared_scores, injection=injection, failure=failure)
    return decision, checked


def _from_findings(policy: dict, checked: Checked) -> Decision:
    effects = {section["code"]: section["effect"] for section in policy["sections"]}
    matched = [f for f in checked.findings if f.status == "matched"]
    unsure = [f for f in checked.findings if f.status == "unsure"]
    violating = [f for f in matched if effects[f.section] == "VIOLATING"]

    reasons = list(checked.reason_codes)
    if violating:
        label, basis = "VIOLATING", matched  # a matched §5 is part of the case too
        confidence = max(f.confidence for f in violating)
    elif matched or unsure:
        label, basis = "NEEDS_REVIEW", matched + unsure
        confidence = max(f.confidence for f in basis)
        if matched:
            reasons.append("review_section_matched")
        if unsure:
            reasons.append("section_unsure")
    else:
        label, basis = "ALLOWED", []
        confidence = min((f.confidence for f in checked.findings), default=0.0)

    order = list(effects)
    basis = sorted(basis, key=lambda f: order.index(f.section))
    rationale = checked.rationale
    if checked.downgraded and label != "VIOLATING":
        rationale = (
            f"Held for review: the model matched {', '.join(checked.downgraded)}, "
            "but its evidence could not be found in the posting."
        )
    return Decision(
        label=label,
        sections=[f.section for f in basis],
        evidence=[quote for f in basis for quote in f.quotes],
        rationale=rationale,
        confidence=round(confidence, 3),
        reason_codes=reasons,
    )
