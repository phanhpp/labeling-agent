"""Load test: does the running system label 95% of postings within 60 seconds at the brief's peak?

Sends real dataset postings (the real fraud mix, never the eval 400 or their copies, never one already
sent) through the real API, queue and workers, then reads each posting's arrival time and the time its
label was saved from the database. That is submit-to-label time, which is what the 60 s target means;
the eval measures only the working time of each run.

    # 200,000 posts a day is 2.3 a second; the brief's 5x peak is 11.6 a second
    uv run python -m scripts.load_test --rate 11.6 --seconds 30 --name peak-48
    uv run python -m scripts.load_test --burst 200 --name burst-48

Run it against a stack with real keys and the worker set-up to test, for example 3 workers of 16:
    WORKER_CONCURRENCY=16 docker compose up -d --scale worker=3
It writes eval/runs/load-<name>/summary.json; eval/report.py puts the results in RESULTS.md.
"""

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
from psycopg.rows import dict_row

from app import demo
from app.auth import DEMO_USERS, demo_token

RUNS = Path(__file__).resolve().parents[1] / "eval" / "runs"
CLIENT = DEMO_USERS["marketplace"].client_id
SENT_FIELDS_SKIPPED = ("fraudulent",)  # the gold label: a marketplace doesn't know it


def pick(conn, n: int, seed: int) -> list[dict]:
    """n real postings at the dataset's own fraud mix, none already in this app."""
    sent = conn.execute("SELECT job_id, raw FROM postings WHERE client_id = %s", (CLIENT,)).fetchall()
    rows = demo.sample(
        demo.pool(),
        n,
        None,
        seed,
        {r["job_id"] for r in sent},
        frozenset(demo.ad_text(r["raw"]) for r in sent),
    )
    return [{k: v for k, v in row.items() if k not in SENT_FIELDS_SKIPPED} for row in rows]


async def send_at_rate(url: str, postings: list[dict], rate: float) -> int:
    """POST each posting on its own, evenly spaced at `rate` a second, like live traffic."""
    headers = {"Authorization": f"Bearer {demo_token('marketplace')}"}
    accepted = 0
    async with httpx.AsyncClient(base_url=url, headers=headers, timeout=30) as client:
        start = time.monotonic()

        async def one(i: int, posting: dict) -> None:
            nonlocal accepted
            await asyncio.sleep(max(0.0, start + i / rate - time.monotonic()))
            response = await client.post("/v1/postings", json=posting)
            accepted += response.status_code == 202

        await asyncio.gather(*(one(i, p) for i, p in enumerate(postings)))
    return accepted


def send_burst(url: str, postings: list[dict]) -> int:
    """All at once, in one batch request, like a marketplace sending a backlog."""
    headers = {"Authorization": f"Bearer {demo_token('marketplace')}"}
    out = httpx.post(
        f"{url}/v1/postings/batch", json={"postings": postings}, headers=headers, timeout=60
    ).json()
    return out["accepted"]


def wait_for_labels(conn, job_ids: list[str], timeout_s: int) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        left = conn.execute(
            "SELECT count(*) AS n FROM postings p WHERE p.client_id = %s AND p.job_id = ANY(%s)"
            " AND NOT EXISTS (SELECT 1 FROM labels l WHERE l.posting_id = p.id)",
            (CLIENT, job_ids),
        ).fetchone()["n"]
        print(f"  {len(job_ids) - left} of {len(job_ids)} labeled", flush=True)
        if left == 0:
            return
        time.sleep(5)
    print("  timed out: the rest count as over the target")


def measure(conn, job_ids: list[str]) -> dict:
    rows = conn.execute(
        """
        SELECT p.job_id, p.created_at AS submitted, l.created_at AS labeled, l.cost_usd, l.reason_codes
        FROM postings p
        LEFT JOIN LATERAL (
            SELECT created_at, cost_usd, reason_codes FROM labels WHERE posting_id = p.id
            ORDER BY created_at LIMIT 1
        ) l ON true
        WHERE p.client_id = %s AND p.job_id = ANY(%s)
        """,
        (CLIENT, job_ids),
    ).fetchall()
    done = [r for r in rows if r["labeled"] is not None]
    seconds = sorted((r["labeled"] - r["submitted"]).total_seconds() for r in done)
    unlabeled = len(rows) - len(done)
    # an unlabeled posting is over any target, so it sorts last
    padded = seconds + [float("inf")] * unlabeled

    def pct(q: float) -> float | None:
        if not padded:
            return None
        value = padded[min(len(padded) - 1, int(q * len(padded)))]
        return None if value == float("inf") else round(value, 1)

    first = min(r["submitted"] for r in rows)
    last = max(r["labeled"] for r in done) if done else None
    return {
        "postings": len(rows),
        "labeled": len(done),
        "submit_to_label_s": {
            "p50": pct(0.5),
            "p95": pct(0.95),
            "max": round(seconds[-1], 1) if seconds else None,
        },
        "within_60s": round(sum(s <= 60 for s in seconds) / len(rows), 3) if rows else None,
        "throughput_per_s": round(len(done) / (last - first).total_seconds(), 2) if last else None,
        "failed": sum("dlq" in (r["reason_codes"] or []) for r in done),
        "cost_usd": round(float(sum(r["cost_usd"] or 0 for r in done)), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--database-url", default="postgresql://labeler:labeler@localhost:5432/labeler")
    shape = parser.add_mutually_exclusive_group(required=True)
    shape.add_argument("--rate", type=float, help="postings a second, sent one by one")
    shape.add_argument("--burst", type=int, help="this many postings in one batch")
    parser.add_argument("--seconds", type=int, default=30, help="how long to send at --rate")
    parser.add_argument("--name", required=True, help="the run's folder: eval/runs/load-<name>")
    parser.add_argument(
        "--workers", default="", help="the worker set-up under test, for the record, e.g. 3x16"
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--timeout", type=int, default=600, help="seconds to wait for every label")
    args = parser.parse_args()

    with psycopg.connect(args.database_url, row_factory=dict_row, autocommit=True) as conn:
        n = round(args.rate * args.seconds) if args.rate else args.burst
        postings = pick(conn, n, args.seed)
        print(f"sending {len(postings)} postings", flush=True)
        started = datetime.now(UTC)
        if args.rate:
            accepted = asyncio.run(send_at_rate(args.url, postings, args.rate))
        else:
            accepted = send_burst(args.url, postings)
        print(f"accepted {accepted}", flush=True)
        job_ids = [p["job_id"] for p in postings]
        wait_for_labels(conn, job_ids, args.timeout)
        result = measure(conn, job_ids)

    summary = {
        "run": f"load-{args.name}",
        "started_at": started.isoformat(),
        "shape": {"rate_per_s": args.rate, "seconds": args.seconds} if args.rate else {"burst": args.burst},
        "workers": args.workers,
        "accepted": accepted,
        **result,
    }
    folder = RUNS / f"load-{args.name}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
