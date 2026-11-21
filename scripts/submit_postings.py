"""Send dataset postings to the running API through the batch endpoint, like a marketplace would.

This is the only way dataset rows enter the database. The eval split is refused: the eval reads the
CSV directly (eval/run_eval.py) and its postings never go into Postgres.

    uv run python -m scripts.submit_postings --split dev --limit 50
"""

import argparse
import json
import random

import httpx

from app.auth import demo_token
from app.dataset import download, read_rows
from scripts.load_data import SPLITS

FIELDS_NOT_SENT = ("fraudulent",)  # the gold label: a marketplace doesn't know it
BATCH = 500


def postings(split: str, limit: int | None, seed: int = 42) -> list[dict]:
    if split == "eval":
        raise SystemExit("the eval split never enters the database; run eval/run_eval.py instead")
    ids = json.loads(SPLITS.read_text())[split]["ids"]
    if limit:
        ids = random.Random(seed).sample(ids, limit)
    wanted = set(ids)
    rows = [row for row in read_rows(download()) if row["job_id"] in wanted]
    return [{k: v for k, v in row.items() if k not in FIELDS_NOT_SENT} for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="dev", choices=["dev", "jev_fit"])
    parser.add_argument("--limit", type=int, help="a seeded random sample of this many")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--token", default="demo-marketplace")
    parser.add_argument(
        "--dataset-labels",
        action="store_true",
        help="then save the dataset's answer for them, for the UI's Compare with dataset (demo mode)",
    )
    args = parser.parse_args()

    items = postings(args.split, args.limit)
    headers = {"Authorization": f"Bearer {args.token}"}
    with httpx.Client(base_url=args.url, headers=headers, timeout=60) as client:
        for start in range(0, len(items), BATCH):
            response = client.post("/v1/postings/batch", json={"postings": items[start : start + BATCH]})
            response.raise_for_status()
            out = response.json()
            statuses = [item["status"] for item in out["items"]]
            print(
                f"batch {out['batch_id']}: {statuses.count('queued')} queued, "
                f"{statuses.count('duplicate')} already there, {out['rejected']} rejected"
            )
            for item in out["items"]:
                if item["status"] == "rejected":
                    print(f"  rejected item {item['index']}: {item['reason']} {item.get('details', '')}")
    if args.dataset_labels:
        editor = {"Authorization": f"Bearer {demo_token('editor')}"}
        out = httpx.post(f"{args.url}/demo/dataset-labels", headers=editor, timeout=60)
        out.raise_for_status()
        print(f"dataset labels saved for {out.json()['recorded']} postings")


if __name__ == "__main__":
    main()
