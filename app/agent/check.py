"""Check the model's answer against the posting and the policy. Pure code, no model.

For each policy section, in policy order:
  - each quote is looked up in the posting (quotes.find_quote); one that isn't there is dropped;
  - a missing field counts only if that field really is empty (the facts from clean);
  - a matched section whose effect is VIOLATING needs at least one verified quote. With none left
    it becomes unsure (reason quote_unverified). Missing fields never count as its evidence;
  - a matched section whose effect is NEEDS_REVIEW (§5) may stand on verified missing fields;
  - a section the model left out becomes unsure; a section the policy doesn't have is ignored.
"""

from dataclasses import dataclass, field

from app.agent.clean import Cleaned
from app.agent.models import Finding, Quote, RawAnswer, RawFinding
from app.agent.quotes import find_quote


@dataclass
class Checked:
    findings: list[Finding]  # one per policy section, in policy order
    rationale: str  # the model's own
    reason_codes: list[str] = field(default_factory=list)
    downgraded: list[str] = field(default_factory=list)  # sections turned from matched into unsure
    unknown_sections: list[str] = field(default_factory=list)  # ids the policy doesn't have


def check(answer: RawAnswer, policy: dict, cleaned: Cleaned) -> Checked:
    effects = {section["code"]: section["effect"] for section in policy["sections"]}
    by_code: dict[str, RawFinding] = {}
    unknown = []
    for raw in answer.findings:
        if raw.section not in effects:
            unknown.append(raw.section)
        else:
            by_code.setdefault(raw.section, raw)  # if a section is answered twice, the first counts

    empty = set(cleaned.facts["empty_fields"])
    result = Checked(findings=[], rationale=answer.rationale, unknown_sections=unknown)
    for code, effect in effects.items():
        raw = by_code.get(code)
        if raw is None:
            result.findings.append(
                Finding(section=code, status="unsure", note="The model's answer left this section out.")
            )
            continue

        quotes: list[Quote] = []
        dropped = []
        for text in raw.quotes:
            quote = find_quote(text, cleaned.fields)
            if quote is None:
                dropped.append(text)
            elif quote not in quotes:
                quotes.append(quote)
        missing = [name for name in raw.missing_fields if name in empty]
        wrong_missing = [name for name in raw.missing_fields if name not in empty]

        status, note = raw.status, ""
        if status == "matched":
            evidence = quotes if effect == "VIOLATING" else quotes + missing
            if not evidence:
                status = "unsure"
                note = "The model matched this section, but none of its evidence is in the posting."
                result.downgraded.append(code)
                if "quote_unverified" not in result.reason_codes:
                    result.reason_codes.append("quote_unverified")

        result.findings.append(
            Finding(
                section=code,
                status=status,
                reasoning=raw.reasoning,
                quotes=quotes,
                missing_fields=missing,
                confidence=raw.confidence,
                dropped_quotes=dropped,
                dropped_missing_fields=wrong_missing,
                note=note,
            )
        )
    return result
