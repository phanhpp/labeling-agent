"""clean and find_quote on the real dataset (marker `data`: needs data/raw/, skipped without it).

Only dev rows are used for quotes, never eval rows.
"""

import json
import random

import pytest

from app.agent.clean import QUOTABLE_FIELDS, clean_posting
from app.agent.quotes import find_quote
from app.dataset import CSV_PATH, read_rows
from scripts.load_data import SPLITS

pytestmark = pytest.mark.data


@pytest.fixture(scope="module")
def rows():
    if not CSV_PATH.exists():
        pytest.skip("no dataset; run: uv run python -m scripts.load_data")
    return read_rows(CSV_PATH)


def test_every_row_cleans(rows):
    hidden = 0
    for row in rows:
        cleaned = clean_posting(row)
        hidden += cleaned.facts["hidden_chars_removed"]
        for name in QUOTABLE_FIELDS:
            text = cleaned.fields[name]
            assert "\xa0" not in text and "​" not in text
            assert "&amp;" not in text  # entities decoded
    assert hidden > 0  # about 1% of rows carry zero-width characters


def _as_the_model_might_type_it(text: str, rng: random.Random) -> str:
    """Change what a model often changes when quoting: spacing, capitals, quote marks."""
    text = text.replace("'", "’")
    text = text.replace(".", ". ") if rng.random() < 0.5 else text
    text = " ".join(text.split())  # line breaks and runs of spaces become single spaces
    return text.upper() if rng.random() < 0.3 else text


def test_quotes_cut_from_dev_postings_are_found_again(rows):
    dev_ids = set(json.loads(SPLITS.read_text())["dev"]["ids"])
    rng = random.Random(7)
    checked = 0
    for row in (r for r in rows if r["job_id"] in dev_ids):
        cleaned = clean_posting(row)
        for name in QUOTABLE_FIELDS:
            text = cleaned.fields[name]
            if len(text) < 60:
                continue
            start = rng.randrange(0, len(text) - 40)
            original = text[start : start + rng.randrange(20, 40)].strip()
            if len("".join(original.split())) < 8:
                continue
            found = find_quote(_as_the_model_might_type_it(original, rng), cleaned.fields)
            assert found is not None, (row["job_id"], name, original)
            assert cleaned.fields[found.field][found.start : found.end] == found.text
            checked += 1
    assert checked > 500
