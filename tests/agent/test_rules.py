"""The label rules (check and decide), one row per rule. No model: answers are written by hand."""

import copy

import pytest

from app import policy as policies
from app.agent.check import check
from app.agent.clean import clean_posting
from app.agent.decide import decide, redecide
from app.agent.models import RawAnswer, RawFinding

V1 = policies.load_file(policies.POLICIES_DIR / "v1.yaml")

POSTING = clean_posting(
    {
        "title": "Remote Payment Processing Agent",
        "company_profile": "",
        "description": (
            "Earn $5,000 a week working 2 hours a day.We're hiring now! "
            "Before your first shift, buy the $149 starter kit."
        ),
        "requirements": (
            "No experience needed. Send your bank details to #EMAIL_ab12cd# to complete the application."
        ),
        "benefits": "Work from home.",
        "salary_range": "",
        "has_company_logo": "0",
        "telecommuting": "1",
    }
)
FEE = "buy the $149 starter kit"
PAY = "Earn $5,000 a week working 2 hours a day"
FAKE = "Pay a $99 registration fee before you start"  # not in the posting


def answer(overrides: dict | None = None, extra: list[RawFinding] = ()) -> RawAnswer:
    """Every section not matched (confidence 0.9) unless overridden. An override of None leaves
    that section out of the answer."""
    findings = []
    for section in V1["sections"]:
        code = section["code"]
        given = (overrides or {}).get(code, {})
        if given is None:
            continue
        values = {"status": "not_matched", "quotes": [], "missing_fields": [], "confidence": 0.9} | given
        findings.append(RawFinding(section=code, reasoning=f"Reasoning for {code}.", **values))
    return RawAnswer(findings=[*findings, *extra], rationale="The model's rationale.")


def matched(*quotes: str, missing=(), confidence=0.9) -> dict:
    return {
        "status": "matched",
        "quotes": list(quotes),
        "missing_fields": list(missing),
        "confidence": confidence,
    }


ROWS = [
    # (id, overrides, injection, label, sections, reason codes)
    (
        "a VIOLATING section with a verified quote",
        {"§1": matched(FEE, confidence=0.95)},
        False,
        "VIOLATING",
        ["§1"],
        [],
    ),
    (
        "a quote not in the posting makes the section unsure",
        {"§1": matched(FAKE)},
        False,
        "NEEDS_REVIEW",
        ["§1"],
        ["quote_unverified", "section_unsure"],
    ),
    (
        "one verified quote is enough; the other is dropped",
        {"§1": matched(FAKE, FEE)},
        False,
        "VIOLATING",
        ["§1"],
        [],
    ),
    (
        "§5 alone, resting on a field that really is empty",
        {"§5": matched(missing=["company_profile"])},
        False,
        "NEEDS_REVIEW",
        ["§5"],
        ["review_section_matched"],
    ),
    (
        "§5 citing a field that is not empty",
        {"§5": matched(missing=["title"])},
        False,
        "NEEDS_REVIEW",
        ["§5"],
        ["quote_unverified", "section_unsure"],
    ),
    (
        "§1 and §5 together: VIOLATING, both listed",
        {"§1": matched(FEE), "§5": matched(missing=["company_profile"])},
        False,
        "VIOLATING",
        ["§1", "§5"],
        [],
    ),
    (
        "missing fields alone never make VIOLATING",
        {"§4": matched(missing=["salary_range", "company_logo"])},
        False,
        "NEEDS_REVIEW",
        ["§4"],
        ["quote_unverified", "section_unsure"],
    ),
    ("nothing matched", {"§3": {"confidence": 0.7}}, False, "ALLOWED", [], []),
    (
        "an unsure section",
        {"§2": {"status": "unsure", "confidence": 0.5}},
        False,
        "NEEDS_REVIEW",
        ["§2"],
        ["section_unsure"],
    ),
    ("a suspected injection is held for review", {}, True, "NEEDS_REVIEW", [], ["injection"]),
    (
        "a suspected injection is held for review even with a matched section",
        {"§1": matched(FEE)},
        True,
        "NEEDS_REVIEW",
        [],
        ["injection"],
    ),
    (
        "a section the model left out is unsure",
        {"§3": None},
        False,
        "NEEDS_REVIEW",
        ["§3"],
        ["section_unsure"],
    ),
    (
        "spacing the model added still matches",
        {"§4": matched("a day. We're hiring now")},
        False,
        "VIOLATING",
        ["§4"],
        [],
    ),
]


@pytest.mark.parametrize(
    ("overrides", "injection", "label", "sections", "reasons"),
    [row[1:] for row in ROWS],
    ids=[row[0] for row in ROWS],
)
def test_label_rules(overrides, injection, label, sections, reasons):
    decision = decide(V1, check(answer(overrides), V1, POSTING), injection=injection)
    assert decision.label == label
    assert decision.sections == sections
    assert decision.reason_codes == reasons


def test_evidence_is_the_postings_own_text_not_the_models():
    decision = decide(V1, check(answer({"§4": matched("A DAY. WE’RE HIRING NOW")}), V1, POSTING))
    [quote] = decision.evidence
    assert quote.text == "a day.We're hiring now"  # sliced from the posting, glued as it is there
    assert POSTING.fields[quote.field][quote.start : quote.end] == quote.text


def test_a_dropped_quote_is_kept_for_the_record():
    checked = check(answer({"§1": matched(FAKE, FEE)}), V1, POSTING)
    finding = checked.findings[0]
    assert [q.text for q in finding.quotes] == [FEE]
    assert finding.dropped_quotes == [FAKE]


def test_confidence_follows_the_findings_that_decided():
    violating = decide(
        V1,
        check(answer({"§1": matched(FEE, confidence=0.6), "§4": matched(PAY, confidence=0.8)}), V1, POSTING),
    )
    assert violating.confidence == 0.8  # the highest matched VIOLATING section
    allowed = decide(V1, check(answer({"§3": {"confidence": 0.7}}), V1, POSTING))
    assert allowed.confidence == 0.7  # the lowest among the not-matched sections


def test_when_check_downgrades_a_section_the_rationale_says_so():
    decision = decide(V1, check(answer({"§1": matched(FAKE)}), V1, POSTING))
    assert decision.rationale.startswith("Held for review: the model matched §1")


def test_unknown_sections_are_ignored_and_recorded():
    rogue = RawFinding(section="§9", reasoning="?", status="matched", quotes=[FEE], confidence=1.0)
    checked = check(answer(extra=[rogue]), V1, POSTING)
    assert checked.unknown_sections == ["§9"]
    assert decide(V1, checked).label == "ALLOWED"


def test_a_section_answered_twice_counts_once_first_answer_wins():
    second = RawFinding(section="§1", reasoning="?", status="not_matched", confidence=0.9)
    decision = decide(V1, check(answer({"§1": matched(FEE)}, extra=[second]), V1, POSTING))
    assert decision.label == "VIOLATING"


def test_a_posting_cleared_by_the_screen():
    decision = decide(V1, cleared_scores={"§1": 0.1, "§5": 0.25})
    assert decision.label == "ALLOWED"
    assert decision.confidence == 0.75
    assert decision.reason_codes == ["cleared_by_screen"]
    assert "§5" in decision.rationale


@pytest.mark.parametrize("failure", ["clean_error", "llm_output_invalid", "llm_refusal"])
def test_a_failed_step_holds_the_posting_with_confidence_0(failure):
    decision = decide(V1, failure=failure)
    assert (decision.label, decision.confidence, decision.reason_codes) == ("NEEDS_REVIEW", 0.0, [failure])


def test_decide_needs_to_know_how_the_run_went():
    with pytest.raises(ValueError):
        decide(V1)


def test_redecide_under_v4_changes_the_label_without_a_model_call():
    """v4 makes §4 NEEDS_REVIEW. The stored answer is re-checked and re-decided; no model runs."""
    v4 = copy.deepcopy(V1)
    v4["sections"][3]["effect"] = "NEEDS_REVIEW"
    assert policies.model_hash(v4) == policies.model_hash(V1)  # what makes the stored answer reusable

    stored = answer({"§4": matched(PAY, confidence=0.8)}).model_dump()
    assert redecide(V1, stored, POSTING).label == "VIOLATING"
    under_v4 = redecide(v4, stored, POSTING)
    assert under_v4.label == "NEEDS_REVIEW"
    assert under_v4.sections == ["§4"]
    assert under_v4.reason_codes == ["review_section_matched"]


def test_redecide_of_a_cleared_posting_stays_allowed():
    assert redecide(V1, None, POSTING, cleared_scores={"§1": 0.1}).label == "ALLOWED"
