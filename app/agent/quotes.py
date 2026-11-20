"""Find the model's quote in the posting, ignoring differences that don't change the words.

The model is asked to copy text exactly, but it often fixes spacing (it writes "Show. We're" for
the glued "Show.We're"), changes capitals, curls quotes, or echoes the prompt's escaping (&lt;).
So matching ignores whitespace, case and quote or dash styles, and decodes entities.

What comes back is always the posting's own text, sliced from the field, so the evidence shown is
verbatim by construction, whatever the model typed.
"""

import html

from app.agent.clean import QUOTABLE_FIELDS
from app.agent.models import Quote

# Shorter than this (letters, digits and punctuation; spaces don't count) is too little to be
# evidence: "fee" would be found almost anywhere.
MIN_QUOTE_CHARS = 8

_FOLD = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "–": "-",
    "—": "-",
    "‒": "-",
    "−": "-",
    "…": "...",
}
_QUOTE_MARKS = "\"'“”‘’"


def find_quote(
    quote: str, fields: dict[str, str], quotable: tuple[str, ...] = QUOTABLE_FIELDS
) -> Quote | None:
    """The quote as it appears in the first quotable field that contains it, or None."""
    trimmed = _trim(html.unescape(quote))
    # A full stop the model added at the end gets a second try without it.
    candidates = [trimmed, trimmed[:-1]] if trimmed.endswith(".") else [trimmed]
    for candidate in candidates:
        needle, _ = _normalise(candidate)
        if len(needle) < MIN_QUOTE_CHARS:
            continue
        for name in quotable:
            text = fields.get(name, "")
            haystack, positions = _normalise(text)
            i = haystack.find(needle)
            if i >= 0:
                start, end = positions[i], positions[i + len(needle) - 1] + 1
                return Quote(text=text[start:end], field=name, start=start, end=end)
    return None


def _trim(quote: str) -> str:
    """Remove what the model wraps around a quote: quote marks around all of it, and a leading or
    trailing ellipsis. A quote mark at only one end belongs to the posting and stays."""
    quote = quote.strip()
    if len(quote) >= 2 and quote[0] in _QUOTE_MARKS and quote[-1] in _QUOTE_MARKS:
        quote = quote[1:-1].strip()
    for ellipsis in ("...", "…"):
        quote = quote.removeprefix(ellipsis).removesuffix(ellipsis).strip()
    return quote


def _normalise(text: str) -> tuple[str, list[int]]:
    """Text without whitespace, folded, plus each kept character's position in the original."""
    chars: list[str] = []
    positions: list[int] = []
    for i, ch in enumerate(text):
        if ch.isspace():
            continue
        for out in _FOLD.get(ch, ch).casefold():
            chars.append(out)
            positions.append(i)
    return "".join(chars), positions
