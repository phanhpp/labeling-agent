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

from app.dataset import CSV_PATH, read_rows

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


def sample(rows, n: int, fraud_share: float | None, seed: int, skip: set[str]) -> list[dict]:
    """n rows not in skip (postings already sent). With a fraud share, that share is fraud; without,
    a plain random sample, so about the dataset's 5%. The same seed gives the same sample."""
    rng = random.Random(seed)
    free = [row for row in rows if row["job_id"] not in skip]
    if fraud_share is None:
        return rng.sample(free, min(n, len(free)))
    fraud = [row for row in free if row["fraudulent"] == "1"]
    legit = [row for row in free if row["fraudulent"] != "1"]
    k = min(round(n * fraud_share), len(fraud))
    picked = rng.sample(fraud, k) + rng.sample(legit, min(n - k, len(legit)))
    rng.shuffle(picked)
    return picked
