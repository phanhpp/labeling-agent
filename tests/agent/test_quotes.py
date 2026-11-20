import pytest

from app.agent.quotes import find_quote

FIELDS = {
    "title": "Data Entry Clerk",
    "company_profile": "",
    "description": "Featured on the Today Show.We're located in Chelsea.\nWork from home 2-3 days a week.",
    "requirements": 'salary < 5k a month\nWe\'re looking for "self-starters".',
    "benefits": "Free lunch",
    "salary_range": "",
    "industry": "Staffing and recruiting",
}

FOUND = [
    # (id, the model's quote, the posting's text that comes back, field)
    ("exact", "Work from home 2-3 days a week", "Work from home 2-3 days a week", "description"),
    (
        "a space the model added to glued text",
        "Today Show. We're located",
        "Today Show.We're located",
        "description",
    ),
    ("a line break quoted as a space", "Chelsea. Work from home", "Chelsea.\nWork from home", "description"),
    ("different capitals", "WORK FROM HOME 2-3 days", "Work from home 2-3 days", "description"),
    (
        "curly quote marks",
        "We’re looking for “self-starters”",
        'We\'re looking for "self-starters"',
        "requirements",
    ),
    ("a dash style", "home 2–3 days", "home 2-3 days", "description"),
    ("the prompt's escaping echoed back", "salary &lt; 5k a month", "salary < 5k a month", "requirements"),
    ("a full stop the model added", "Free lunch.", "Free lunch", "benefits"),
    (
        "wrapping quotes and an ellipsis",
        '"...Work from home 2-3 days..."',
        "Work from home 2-3 days",
        "description",
    ),
]


@pytest.mark.parametrize(("quote", "text", "field"), [r[1:] for r in FOUND], ids=[r[0] for r in FOUND])
def test_found(quote, text, field):
    found = find_quote(quote, FIELDS)
    assert found is not None
    assert (found.text, found.field) == (text, field)
    assert FIELDS[field][found.start : found.end] == found.text  # always the posting's own text


NOT_FOUND = [
    ("not in the posting", "Pay a $99 registration fee"),
    ("too short to be evidence", "lunch"),
    ("in a field that may not be quoted", "Staffing and recruiting"),
    ("across two fields", "Free lunch Data Entry"),
    ("an elided quote", "Featured on ... in Chelsea"),
]


@pytest.mark.parametrize("quote", [r[1] for r in NOT_FOUND], ids=[r[0] for r in NOT_FOUND])
def test_not_found(quote):
    assert find_quote(quote, FIELDS) is None


def test_the_first_quotable_field_wins():
    fields = {"title": "Data Entry Clerk", "description": "Hiring a Data Entry Clerk today"}
    assert find_quote("Data Entry Clerk", fields).field == "title"
