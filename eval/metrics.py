"""Metrics for an eval run. Pure functions over the per-posting records that run_eval writes.

Two ways to count a NEEDS_REVIEW against the binary gold label:
  main    NEEDS_REVIEW counts as caught (an analyst will see it), like VIOLATING
  strict  only VIOLATING counts as caught
Errored records (the system didn't answer) are listed and left out of every score: an outage must
not look like a quality drop.
"""

import math
import random
from collections import Counter

LABELS = ("VIOLATING", "NEEDS_REVIEW", "ALLOWED")
REAL_FRAUD_RATE = 0.048  # 866 of 17,880 in the full dataset


def flagged(label: str, mode: str) -> bool:
    return label == "VIOLATING" or (mode == "main" and label == "NEEDS_REVIEW")


def prf(records: list[dict], mode: str) -> dict:
    tp = sum(1 for r in records if r["gold"] == 1 and flagged(r["label"], mode))
    fp = sum(1 for r in records if r["gold"] == 0 and flagged(r["label"], mode))
    fn = sum(1 for r in records if r["gold"] == 1 and not flagged(r["label"], mode))
    legit = sum(1 for r in records if r["gold"] == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    false_positive_rate = fp / legit if legit else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "precision_at_real_rate": round(precision_at_rate(recall, false_positive_rate, REAL_FRAUD_RATE), 4),
    }


def precision_at_rate(recall: float, false_positive_rate: float, fraud_rate: float) -> float:
    """Precision if fraud were `fraud_rate` of postings, not the eval set's 25%: the same recall and
    false positive rate, reweighted."""
    caught = recall * fraud_rate
    false_alarms = false_positive_rate * (1 - fraud_rate)
    return caught / (caught + false_alarms) if caught + false_alarms else 0.0


def bootstrap(records: list[dict], mode: str, n: int = 1000, seed: int = 0) -> dict:
    """95% intervals for precision, recall and F1, by resampling postings with replacement."""
    rng = random.Random(seed)
    draws = {"precision": [], "recall": [], "f1": []}
    for _ in range(n):
        sample = [records[rng.randrange(len(records))] for _ in records]
        result = prf(sample, mode)
        for key in draws:
            draws[key].append(result[key])
    return {
        key: [round(_percentile(v, 0.025), 4), round(_percentile(v, 0.975), 4)] for key, v in draws.items()
    }


def confusion(records: list[dict]) -> dict:
    table = {"fraud": dict.fromkeys(LABELS, 0), "legit": dict.fromkeys(LABELS, 0)}
    for r in records:
        table["fraud" if r["gold"] == 1 else "legit"][r["label"]] += 1
    return table


def review_causes(records: list[dict]) -> dict:
    """Why postings went to review, by reason code (a posting can have several)."""
    causes = Counter(code for r in records if r["label"] == "NEEDS_REVIEW" for code in r["reason_codes"])
    return dict(causes.most_common())


def calibration(records: list[dict]) -> list[dict]:
    """Is a stated confidence of 0.9 right about 90% of the time? Correct = the main decision matches gold."""
    bins = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)]
    rows = []
    for low, high in bins:
        inside = [r for r in records if low <= r["confidence"] < high]
        correct = sum(1 for r in inside if flagged(r["label"], "main") == (r["gold"] == 1))
        rows.append(
            {
                "confidence": f"{low:.1f}-{min(high, 1.0):.1f}",
                "n": len(inside),
                "correct": round(correct / len(inside), 3) if inside else None,
            }
        )
    return rows


def summarize(records: list[dict]) -> dict:
    scored = [r for r in records if "error" not in r]
    errored = [{"job_id": r["job_id"], "error": r["error"]} for r in records if "error" in r]
    latencies = sorted(r["latency_ms"] for r in scored)
    verified = sum(r["quotes_verified"] for r in scored)
    dropped = sum(r["quotes_dropped"] for r in scored)
    reviewed = sum(1 for r in scored if r["label"] == "NEEDS_REVIEW")
    return {
        "postings": len(records),
        "scored": len(scored),
        "errored": errored,
        "fraud_in_scored": sum(r["gold"] for r in scored),
        "main": prf(scored, "main") | {"ci95": bootstrap(scored, "main")} if scored else {},
        "strict": prf(scored, "strict") | {"ci95": bootstrap(scored, "strict")} if scored else {},
        "confusion": confusion(scored),
        "review_load": round(reviewed / len(scored), 4) if scored else 0.0,
        "review_causes": review_causes(scored),
        "cost_per_1000_usd": round(1000 * sum(r["cost_usd"] for r in scored) / len(scored), 4)
        if scored
        else 0.0,
        "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)}
        if latencies
        else {},
        "quotes": {
            "verified": verified,
            "dropped": dropped,
            "verified_share": round(verified / (verified + dropped), 4) if verified + dropped else None,
        },
        "calibration": calibration(scored),
    }


def _percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile of a list."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p * len(ordered)) - 1)]
