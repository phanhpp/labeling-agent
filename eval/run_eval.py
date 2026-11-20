"""Run the agent over a split or a suite and write results.jsonl and summary.json.

    uv run python -m eval.run_eval --split dev --config sonnet_only --limit 30
    uv run python -m eval.run_eval --suite edge_cases --config sonnet_only
    uv run python -m eval.run_eval --split eval --config jev_sonnet --frozen   # the frozen eval only

The graph runs in-process (no queue, no database, no checkpointer) with the cache off, so every
posting gets a fresh model call and the cost and latency are real. A posting whose run raises is
recorded as errored, never as a wrong answer.
"""

import argparse
import asyncio
import json
import random
import time
from datetime import UTC, datetime
from pathlib import Path

from app import config as settings
from app import policy as policies
from app.agent.configs import CONFIGS
from app.agent.graph import build, model_version
from app.agent.state import Context
from app.dataset import CSV_PATH, read_rows
from eval.metrics import summarize
from scripts.load_data import SPLITS

EVAL_DIR = Path(__file__).resolve().parent
RUNS = EVAL_DIR / "runs"
SUITES = EVAL_DIR / "suites"


def record_for(item: dict, state: dict, latency_ms: int) -> dict:
    decision = state["decision"]
    findings = (state.get("checked") or {}).get("findings", [])
    return {
        "job_id": item["job_id"],
        "gold": item.get("gold"),
        "label": decision["label"],
        "sections": decision["sections"],
        "evidence": [q["text"] for q in decision["evidence"]],
        "confidence": decision["confidence"],
        "reason_codes": decision["reason_codes"],
        "rationale": decision["rationale"],
        "findings": {f["section"]: f["status"] for f in findings},
        "screen": {k: v for k, v in (state.get("screen") or {}).items() if k != "regex_hits"},
        "quotes_verified": sum(len(f["quotes"]) for f in findings),
        "quotes_dropped": sum(len(f["dropped_quotes"]) for f in findings),
        "dropped_quotes": [q for f in findings for q in f["dropped_quotes"]],
        "cost_usd": round(sum(u.get("cost_usd", 0) for u in state.get("usage", [])), 6),
        "latency_ms": latency_ms,
    }


async def run(items: list[dict], config_name: str, concurrency: int, out: Path) -> list[dict]:
    policy = policies.load_file(policies.POLICIES_DIR / "v1.yaml")
    config = CONFIGS[config_name]
    context = Context(policy=policy, policy_version="v1", config=config)
    graph = build()
    gate = asyncio.Semaphore(concurrency)
    records: list[dict] = []
    out.parent.mkdir(parents=True, exist_ok=True)
    results_file = out.open("w")

    async def one(item: dict) -> None:
        async with gate:
            start = time.monotonic()
            try:
                state = await graph.ainvoke({"raw": item["raw"]}, context=context)
                record = record_for(item, state, round((time.monotonic() - start) * 1000))
            except Exception as error:  # noqa: BLE001 - errored, not wrong
                record = {
                    "job_id": item["job_id"],
                    "gold": item.get("gold"),
                    "error": f"{type(error).__name__}: {str(error)[:200]}",
                }
            if "expect" in item:
                record["expect"] = item["expect"]
                record["passed"] = "error" not in record and passes(record, item["expect"])
            records.append(record)
            results_file.write(json.dumps(record) + "\n")
            results_file.flush()
            print(
                f"{len(records):4}/{len(items)} {record['job_id']:>8} "
                f"{record.get('label', 'ERRORED'):12} {record.get('error', '')[:80]}",
                flush=True,
            )

    await asyncio.gather(*(one(item) for item in items))
    results_file.close()
    return records


def passes(record: dict, expect: dict) -> bool:
    """A suite row passes when the label is one of the allowed ones and the sections and reason codes
    include (or exclude) what the row lists."""
    return (
        record["label"] in expect.get("labels", [record["label"]])
        and all(s in record["sections"] for s in expect.get("sections_include", []))
        and not any(s in record["sections"] for s in expect.get("sections_exclude", []))
        and all(c in record["reason_codes"] for c in expect.get("reason_codes_include", []))
    )


def split_items(split: str, limit: int | None, seed: int = 42) -> list[dict]:
    ids = json.loads(SPLITS.read_text())[split]["ids"]
    if limit:
        ids = random.Random(seed).sample(ids, limit)
    wanted = set(ids)
    return [
        {"job_id": row["job_id"], "gold": int(row["fraudulent"]), "raw": row}
        for row in read_rows(CSV_PATH)
        if row["job_id"] in wanted
    ]


def suite_items(name: str) -> list[dict]:
    lines = (SUITES / f"{name}.jsonl").read_text().splitlines()
    return [
        {"job_id": row["id"], "raw": row["posting"], "expect": row["expect"], "gold": row.get("gold")}
        for row in map(json.loads, filter(None, lines))
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--split", choices=["dev", "jev_fit", "eval"])
    source.add_argument("--suite")
    parser.add_argument("--config", required=True, choices=sorted(CONFIGS))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--name", help="the run folder's name (default: date-config-source)")
    parser.add_argument("--frozen", action="store_true", help="required for --split eval")
    args = parser.parse_args()

    if settings.llm_backend() == "fake":
        raise SystemExit("run_eval refuses LLM_BACKEND=fake: an eval must call the real models")
    if args.split == "eval" and not args.frozen:
        raise SystemExit(
            "--split eval is the frozen eval: pass --frozen, and change nothing after reading it"
        )

    items = split_items(args.split, args.limit) if args.split else suite_items(args.suite)
    source_name = args.split or f"suite-{args.suite}"
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    name = args.name or f"{stamp}-{args.config}-{source_name}" + (f"-{args.limit}" if args.limit else "")
    folder = RUNS / name
    records = asyncio.run(run(items, args.config, args.concurrency, folder / "results.jsonl"))

    summary = {
        "run": name,
        "config": args.config,
        "model_version": model_version(CONFIGS[args.config]),
        "source": source_name,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    if args.suite:
        summary |= {
            "passed": sum(1 for r in records if r.get("passed")),
            "total": len(records),
            "failed": [r["job_id"] for r in records if not r.get("passed")],
        }
    else:
        summary |= summarize(records)
    (folder / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps({k: summary[k] for k in summary if k not in ("calibration",)}, indent=1))


if __name__ == "__main__":
    main()
