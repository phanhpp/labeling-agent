"""The live demo (DEMO_MODE=true): send real dataset postings in, as a marketplace would, and keep the
dataset's own label beside them for the UI's "Compare with dataset" switch.

The pool is every dataset row except the 400 evaluation postings and their 586 exact copies, so the
demo never touches the eval. dataset_labels is read only by the analyst API: the agent and the worker
never read it (tests/api/test_demo.py checks their code), so the label can't leak into a decision.
"""

import json
import os
import random
from functools import lru_cache

from app.dataset import CSV_PATH, TEXT_FIELDS, read_rows, text_key

SPLITS = CSV_PATH.parents[1] / "splits.json"  # data/splits.json (scripts/ isn't in the image)

MIN_POSTINGS, MAX_POSTINGS = 10, 100
MIXES = {"real": None, "more_fraud": 0.25}  # None: a plain random sample (about 5% fraud)
USD_PER_POSTING = 0.0035  # measured on dev 300 with jev_sonnet: $3.26 per 1,000 at 25% fraud


def enabled() -> bool:
    return os.environ.get("DEMO_MODE", "false") == "true"


def dataset_ready() -> bool:
    return CSV_PATH.exists() and SPLITS.exists()


def outside_eval(rows: list[dict], splits: dict) -> list[dict]:
    """The rows the demo may send: never an eval row or a copy of one."""
    banned = set(splits["eval"]["ids"]) | set(splits["excluded_copies"])
    return [row for row in rows if row["job_id"] not in banned]


@lru_cache(maxsize=1)
def pool() -> tuple[dict, ...]:
    """Read once per process (the CSV is 50 MB)."""
    return tuple(outside_eval(read_rows(CSV_PATH), json.loads(SPLITS.read_text())))


def ad_text(row: dict) -> str:
    """The ad's text (the five text fields), for spotting reposts; a missing field counts as empty."""
    return text_key({field: row.get(field, "") for field in TEXT_FIELDS})


def sample(
    rows,
    n: int,
    fraud_share: float | None,
    seed: int,
    skip: set[str],
    skip_texts: frozenset[str] = frozenset(),
) -> list[dict]:
    """n rows not already sent: not in skip (job ids) and not a repost of an ad already sent (skip_texts,
    the five text fields). The dataset has reposts, the same ad under different job ids, so the sample
    also takes each ad once. With a fraud share, that share is fraud; without, a plain random sample
    (about the dataset's 5%). The same seed gives the same sample."""
    rng = random.Random(seed)
    seen, free = set(skip_texts), []
    for row in rows:
        key = ad_text(row)
        if row["job_id"] in skip or key in seen:
            continue
        seen.add(key)
        free.append(row)
    if fraud_share is None:
        return rng.sample(free, min(n, len(free)))
    fraud = [row for row in free if row["fraudulent"] == "1"]
    legit = [row for row in free if row["fraudulent"] != "1"]
    k = min(round(n * fraud_share), len(fraud))
    picked = rng.sample(fraud, k) + rng.sample(legit, min(n - k, len(legit)))
    rng.shuffle(picked)
    return picked


def dataset_label_for(posting_raw: dict) -> bool | None:
    """The dataset's answer (fraud or not) for a posting the app holds, if it is a dataset row: same job
    id and the same text. None for anything else (a marketplace's own posting, a fixture)."""
    row = _by_job_id().get(posting_raw.get("job_id", ""))
    if row is None or ad_text(row) != ad_text(posting_raw):
        return None
    return row["fraudulent"] == "1"


@lru_cache(maxsize=1)
def _by_job_id() -> dict[str, dict]:
    return {row["job_id"]: row for row in pool()}
