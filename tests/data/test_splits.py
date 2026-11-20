"""The fixed split in data/splits.json. The first tests read the committed file (no download);
the last one recomputes it from the CSV and needs the dataset (marker `data`)."""

import json

import pytest

from scripts.load_data import SPLITS, make_splits, read_eval_ids


@pytest.fixture(scope="module")
def splits() -> dict:
    return json.loads(SPLITS.read_text())


def test_eval_set_is_the_briefs_400(splits):
    assert splits["eval"]["ids"] == sorted(read_eval_ids(), key=int)
    assert len(splits["eval"]["ids"]) == 400
    assert len(splits["eval"]["fraud"]) == 100


def test_dev_set_is_300_with_75_fraud(splits):
    assert len(splits["dev"]["ids"]) == 300
    assert len(splits["dev"]["fraud"]) == 75


def test_no_set_overlaps_another(splits):
    sets = {
        "eval": set(splits["eval"]["ids"]),
        "dev": set(splits["dev"]["ids"]),
        "jev_fit": set(splits["jev_fit"]["ids"]),
        "copies": set(splits["excluded_copies"]),
    }
    names = list(sets)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            assert not sets[a] & sets[b], f"{a} and {b} share rows"


def test_copies_of_eval_rows_are_excluded(splits):
    # 586 rows outside eval repeat an eval row's five text fields exactly (measured on the CSV).
    assert len(splits["excluded_copies"]) == 586


@pytest.mark.data
def test_the_split_recomputes_identically_from_the_csv(splits):
    from app.dataset import CSV_PATH, read_rows

    if not CSV_PATH.exists():
        pytest.skip("no dataset; run: uv run python -m scripts.load_data")
    assert make_splits(read_rows(CSV_PATH), read_eval_ids()) == splits
