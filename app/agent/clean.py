"""Clean a posting before any model sees it, and note facts that code can check later.

Cleaning is light on purpose. The dataset has no HTML, but postings from the API might:
  - HTML becomes text only when a field contains tags. Scripts, styles, comments and hidden
    elements are dropped: hidden text is a classic way to slip instructions to a model.
  - HTML entities are decoded and non-breaking spaces become spaces.
  - Invisible characters (zero-width, text-direction controls, other control characters) go.
  - Runs of spaces are collapsed. Glued sentences ("Show.We're") stay as they are, because the
    quote matcher ignores whitespace anyway.
The cleaned text is what the models see, what quotes are checked against and what the UI shows.
"""

import html
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from bs4 import BeautifulSoup, Comment

# The models may quote these fields.
QUOTABLE_FIELDS = ("title", "company_profile", "description", "requirements", "benefits", "salary_range")
# Shown to the models as context, never quoted.
CONTEXT_FIELDS = (
    "department",
    "employment_type",
    "required_experience",
    "required_education",
    "industry",
    "function",
    "telecommuting",
    "has_company_logo",
    "has_questions",
)
# Shown to analysts only: no policy section uses location, and leaving it out of the model input
# lets repeats of one posting in different cities share a cached label.
ANALYST_ONLY_FIELDS = ("location",)
ALL_FIELDS = QUOTABLE_FIELDS + CONTEXT_FIELDS + ANALYST_ONLY_FIELDS

MAX_FIELD_CHARS = 20_000  # the longest posting in the dataset is about 15,000 characters in all

_TAG = re.compile(r"<\s*/?\s*[a-zA-Z!][^>]*>")  # "<5 years" is not a tag: a letter must follow "<"
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?![.\d])", re.I)
_HIDDEN_TAGS = {"script", "style", "template", "noscript"}
_INVISIBLE = (
    {"​", "‌", "‍", "⁠", "﻿"}  # zero-width characters
    | {chr(c) for c in range(0x202A, 0x202F)}  # text-direction embeddings and overrides
    | {chr(c) for c in range(0x2066, 0x206A)}  # text-direction isolates
)
_SPACES = {"\xa0", " ", " "}  # non-breaking spaces
_TOKEN = re.compile(r"#(EMAIL|PHONE|URL)_[0-9a-f]+#")  # how the dataset anonymised contact details


@dataclass
class Cleaned:
    fields: dict[str, str]  # every field in ALL_FIELDS, cleaned, "" when absent
    facts: dict  # empty_fields, contact_tokens, hidden_chars_removed, truncated_fields


def clean_posting(raw: dict) -> Cleaned:
    fields: dict[str, str] = {}
    hidden = 0
    truncated = []
    for name in ALL_FIELDS:
        text, removed = clean_text(_as_text(raw.get(name)))
        if len(text) > MAX_FIELD_CHARS:
            text = text[:MAX_FIELD_CHARS]
            truncated.append(name)
        fields[name] = text
        hidden += removed
    facts = {
        "empty_fields": empty_fields(fields),
        "contact_tokens": dict(
            Counter(m.group(1) for f in QUOTABLE_FIELDS for m in _TOKEN.finditer(fields[f]))
        ),
        "hidden_chars_removed": hidden,
        "truncated_fields": truncated,
    }
    return Cleaned(fields=fields, facts=facts)


def clean_text(text: str) -> tuple[str, int]:
    """The cleaned text, and how many characters were hidden or invisible and so removed."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    removed = 0
    if _TAG.search(text):
        text, removed = _html_to_text(text)
    text = _decode_entities(text)
    kept = []
    for ch in text:
        if ch in _SPACES:
            kept.append(" ")
        elif ch in _INVISIBLE or (unicodedata.category(ch) == "Cc" and ch not in "\n\t"):
            removed += 1
        else:
            kept.append(ch)
    text = "".join(kept)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(), removed


def empty_fields(fields: dict[str, str]) -> list[str]:
    """Fields a finding may rest on as missing. "company_logo" stands for has_company_logo = 0."""
    missing = [name for name in QUOTABLE_FIELDS if not fields[name]]
    if fields.get("has_company_logo") == "0":
        missing.append("company_logo")
    return missing


def _decode_entities(text: str) -> str:
    """Decode HTML entities until nothing changes. Five dataset rows are encoded twice
    ("&amp;amp;"), so one round would leave "&amp;" in the text."""
    for _ in range(3):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return text


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _html_to_text(markup: str) -> tuple[str, int]:
    soup = BeautifulSoup(markup, "html.parser")
    removed = 0
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        removed += len(comment)
        comment.extract()
    for element in soup.find_all(_is_hidden):
        if element.decomposed:  # already gone with a hidden parent
            continue
        removed += len(element.get_text())
        element.decompose()
    return soup.get_text(" "), removed


def _is_hidden(tag) -> bool:
    return (
        tag.name in _HIDDEN_TAGS or tag.has_attr("hidden") or bool(_HIDDEN_STYLE.search(tag.get("style", "")))
    )
