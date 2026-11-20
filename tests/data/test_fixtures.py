"""The UI fixtures (tests/fixtures/postings.jsonl) are valid postings and never eval rows."""

import json
from pathlib import Path

from app.api.intake import PostingIn

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "postings.jsonl"
SPLITS = Path(__file__).resolve().parents[2] / "data" / "splits.json"


def rows() -> list[dict]:
    return [json.loads(line) for line in FIXTURES.read_text().splitlines() if line]


def test_every_fixture_passes_the_intake_schema():
    for row in rows():
        PostingIn.model_validate(row)


def test_fixtures_hold_the_cases_the_ui_tests_need_and_no_eval_rows():
    ids = {r["job_id"] for r in rows()}
    assert {"fx-fee", "fx-pay", "fx-impersonation", "fx-injection", "fx-logo", "fx-script"} <= ids
    splits = json.loads(SPLITS.read_text())
    dataset_ids = ids - {i for i in ids if i.startswith("fx-")}
    assert dataset_ids <= set(splits["dev"]["ids"])
    assert not dataset_ids & set(splits["eval"]["ids"])
