"""Download the dataset once and write the fixed split to data/splits.json.

    uv run python -m scripts.load_data

The split, deterministic (seed 42):
  eval     the 400 job ids from eval/eval_ids.txt. Used only by the frozen eval run.
  copies   rows outside eval whose five text fields equal an eval row's. Excluded everywhere, so no
           eval text leaks into development.
  dev      300 rows (75 fraud, 225 legit) for prompt work and dev runs.
  jev_fit  all remaining fraud plus 3,000 legit, for fitting Jev's cut-off. Never overlaps dev.
Dev and jev_fit come from the pool with exact repeats removed (one row per text), so a template
posted many times counts once.
"""

import json
import random
from pathlib import Path

from app.dataset import CSV_SHA256, CSV_URL, download, read_rows, text_key

ROOT = Path(__file__).resolve().parents[1]
EVAL_IDS = ROOT / "eval" / "eval_ids.txt"
SPLITS = ROOT / "data" / "splits.json"

SEED = 42
DEV_FRAUD, DEV_LEGIT = 75, 225
FIT_LEGIT = 3000


def read_eval_ids(path: Path = EVAL_IDS) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def make_splits(rows: list[dict[str, str]], eval_ids: list[str], seed: int = SEED) -> dict:
    by_id = {row["job_id"]: row for row in rows}
    missing = [job_id for job_id in eval_ids if job_id not in by_id]
    if missing:
        raise ValueError(f"eval ids not in the dataset (they must be job_id values): {missing[:5]}")

    def fraud(ids: list[str]) -> list[str]:
        return [job_id for job_id in ids if by_id[job_id]["fraudulent"] == "1"]

    eval_set = set(eval_ids)
    eval_texts = {text_key(by_id[job_id]) for job_id in eval_ids}
    copies = sorted(
        (row["job_id"] for row in rows if row["job_id"] not in eval_set and text_key(row) in eval_texts),
        key=int,
    )

    # The pool: everything else, one row per distinct text (the lowest job id wins).
    seen: set[str] = set()
    pool: list[str] = []
    for row in sorted(rows, key=lambda r: int(r["job_id"])):
        key = text_key(row)
        if row["job_id"] in eval_set or key in eval_texts or key in seen:
            continue
        seen.add(key)
        pool.append(row["job_id"])

    rng = random.Random(seed)
    pool_fraud = fraud(pool)
    pool_legit = [job_id for job_id in pool if by_id[job_id]["fraudulent"] == "0"]
    dev = rng.sample(pool_fraud, DEV_FRAUD) + rng.sample(pool_legit, DEV_LEGIT)
    dev_set = set(dev)
    fit_legit = rng.sample([job_id for job_id in pool_legit if job_id not in dev_set], FIT_LEGIT)
    jev_fit = [job_id for job_id in pool_fraud if job_id not in dev_set] + fit_legit

    def part(ids: list[str]) -> dict:
        ordered = sorted(ids, key=int)
        return {"ids": ordered, "fraud": fraud(ordered)}

    return {
        "source": {"url": CSV_URL, "sha256": CSV_SHA256, "rows": len(rows)},
        "seed": seed,
        "eval": part(eval_ids),
        "dev": part(dev),
        "jev_fit": part(jev_fit),
        "excluded_copies": copies,
        "pool_size": len(pool),
    }


def main() -> None:
    rows = read_rows(download())
    splits = make_splits(rows, read_eval_ids())
    SPLITS.parent.mkdir(parents=True, exist_ok=True)
    SPLITS.write_text(json.dumps(splits, indent=1) + "\n")
    for name in ("eval", "dev", "jev_fit"):
        print(f"{name:8} {len(splits[name]['ids']):5} rows, {len(splits[name]['fraud']):4} fraud")
    copies, pool = len(splits["excluded_copies"]), splits["pool_size"]
    print(f"excluded {copies:5} copies of eval rows; pool {pool} distinct rows")
    print(f"wrote {SPLITS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
